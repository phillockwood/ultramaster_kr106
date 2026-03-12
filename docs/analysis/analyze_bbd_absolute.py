#!/usr/bin/env python3
"""
analyze_bbd_absolute.py — Absolute BBD delay from dry-then-chorus recording

Uses block-based quadrature DFT for phase measurement at the transition
(immune to sosfiltfilt smearing), then juno_lib.phase for LFO extraction
within the chorus section (where sosfiltfilt is safe, no discontinuity).

Usage:
  python analyze_bbd_absolute.py <stereo_wav> [--freq FREQ_HZ] [--mode "Chorus I"]
"""

import sys
import argparse
import numpy as np
import scipy.signal as signal
import scipy.fft
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

from juno_lib import audio, phase, plotting

def find_chorus_onset(L, R, sr, window_ms=50):
    """Detect chorus onset from L-R difference jump."""
    diff = np.abs(L - R)
    win = int(sr * window_ms / 1000)
    diff_rms = np.array([np.sqrt(np.mean(diff[i:i+win]**2))
                         for i in range(0, len(diff) - win, win)])
    threshold = np.max(diff_rms) * 0.2
    onset_idx = np.argmax(diff_rms > threshold)
    return onset_idx * win / sr, onset_idx * win


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('wavfile')
    parser.add_argument('--freq', type=float, default=None)
    parser.add_argument('--mode', type=str, default='Chorus I')
    parser.add_argument('--onset', type=float, default=None)
    args = parser.parse_args()

    L, R, sr = audio.load_stereo(args.wavfile)
    print(f"Loaded: {args.wavfile}")
    print(f"  SR: {sr}, Duration: {len(L)/sr:.2f}s, Peak: {max(np.max(np.abs(L)), np.max(np.abs(R))):.4f}")

    # Chorus onset
    if args.onset is not None:
        onset_time, onset_sample = args.onset, int(args.onset * sr)
    else:
        onset_time, onset_sample = find_chorus_onset(L, R, sr)
    print(f"  Chorus onset: {onset_time:.2f}s")

    # Frequency from dry section
    dry_mono = (L[:onset_sample] + R[:onset_sample]) / 2
    freq = args.freq or phase.find_fundamental_autocorr(dry_mono, sr)
    print(f"  Fundamental: {freq:.1f} Hz")
    omega = 2 * np.pi * freq

    # ================================================================
    # PART 1: Block-based phase for absolute delay at transition
    # ================================================================
    print(f"\nBlock-based phase measurement...")
    bt_L, bp_L, ba_L = phase.block_phase(L, sr, freq)
    bt_R, bp_R, ba_R = phase.block_phase(R, sr, freq)

    dt_block = bt_L[1] - bt_L[0]
    sr_block = 1.0 / dt_block
    print(f"  Block hop: {dt_block*1000:.1f}ms, {len(bt_L)} blocks")

    # Dry section: fit linear phase to (L+R)/2
    dry_mask = (bt_L > 0.3) & (bt_L < onset_time - 0.2)
    dry_t = bt_L[dry_mask]
    dry_ph = (bp_L[dry_mask] + bp_R[dry_mask]) / 2

    dry_coeffs = np.polyfit(dry_t, dry_ph, 1)
    dry_freq = dry_coeffs[0] / (2 * np.pi)
    dry_residual_ms = (dry_ph - np.polyval(dry_coeffs, dry_t)) / omega * 1000
    print(f"  Dry carrier: {dry_freq:.3f} Hz")
    print(f"  Dry residual: {np.mean(dry_residual_ms):.4f} ± {np.std(dry_residual_ms):.4f} ms")

    # Measure center delay: short window right after onset
    # (L+R)/2 cancels the antiphase LFO → pure carrier + center delay
    near_mask = (bt_L > onset_time + 0.3) & (bt_L < onset_time + 1.5)
    near_t = bt_L[near_mask]
    near_ph = (bp_L[near_mask] + bp_R[near_mask]) / 2
    near_predicted = np.polyval(dry_coeffs, near_t)

    # delay = (predicted - actual) / omega  (positive = signal lags = real delay)
    delay_samples = (near_predicted - near_ph) / omega * 1000
    center_delay_ms = np.median(delay_samples)

    # Check for drift within window
    if len(delay_samples) > 2:
        drift_fit = np.polyfit(near_t, delay_samples, 1)
        drift_rate = drift_fit[0]  # ms/s
        # Use the intercept at onset_time for a drift-corrected estimate
        center_delay_ms = np.polyval(drift_fit, onset_time + 0.3)
    else:
        drift_rate = 0

    print(f"\n  Center delay: {center_delay_ms:.3f} ms")
    print(f"  Drift in window: {drift_rate:.3f} ms/s")
    print(f"  Extrapolation: {(near_t[0] - dry_t[-1]):.2f}s beyond dry section")

    # ================================================================
    # PART 2: Hilbert-based LFO extraction (chorus section only)
    # ================================================================
    # Safe to use sosfiltfilt here — no transition discontinuity
    chorus_start = onset_sample + int(sr * 0.5)
    chorus_end = len(L) - int(sr * 0.3)

    L_chorus = L[chorus_start:chorus_end]
    R_chorus = R[chorus_start:chorus_end]

    print(f"\nExtracting LFO from chorus section ({chorus_start/sr:.1f}s–{chorus_end/sr:.1f}s)...")
    ph_Lc, amp_Lc = phase.extract(L_chorus, sr, freq)
    ph_Rc, amp_Rc = phase.extract(R_chorus, sr, freq)

    # Local reference: linear fit to (L+R)/2 phase (drift-immune)
    t_chorus = np.arange(len(L_chorus)) / sr
    ph_avg = (ph_Lc + ph_Rc) / 2
    chorus_coeffs = np.polyfit(t_chorus, ph_avg, 1)
    chorus_ref = np.polyval(chorus_coeffs, t_chorus)
    chorus_freq = chorus_coeffs[0] / (2 * np.pi)
    print(f"  Chorus carrier: {chorus_freq:.3f} Hz (drift {(chorus_freq-dry_freq)*1000:.1f} mHz)")

    # Per-channel deviation → LFO
    dev_L = -(ph_Lc - chorus_ref) / omega * 1000
    dev_R = -(ph_Rc - chorus_ref) / omega * 1000

    # Median filter for spikes
    kernel = int(sr * 0.005) | 1
    dev_L = signal.medfilt(dev_L, kernel_size=kernel)
    dev_R = signal.medfilt(dev_R, kernel_size=kernel)

    lfo_L = phase.extract_lfo(dev_L, sr)
    lfo_R = phase.extract_lfo(dev_R, sr)

    # LFO parameters
    lfo_freq, n_cyc = phase.measure_lfo_frequency(lfo_L, sr)
    shape, shape_m = phase.classify_lfo_shape(lfo_L, sr)

    mod_L = (np.max(lfo_L) - np.min(lfo_L)) / 2
    mod_R = (np.max(lfo_R) - np.min(lfo_R)) / 2
    mod_depth = (mod_L + mod_R) / 2

    min_delay = center_delay_ms - mod_depth
    max_delay = center_delay_ms + mod_depth

    # BBD clock (MN3009 = 256 stages)
    stages = 256
    if center_delay_ms > 0.1 and min_delay > 0.01:
        center_clock = stages / (2 * center_delay_ms / 1000)
        min_clock = stages / (2 * max_delay / 1000)
        max_clock = stages / (2 * min_delay / 1000)
    else:
        center_clock = min_clock = max_clock = 0

    # L/R phase offset
    corr = np.correlate(lfo_L - np.mean(lfo_L), lfo_R - np.mean(lfo_R), mode='full')
    lags = np.arange(-len(lfo_L)+1, len(lfo_L)) / sr
    phase_offset_deg = lags[np.argmax(corr)] * lfo_freq * 360 if lfo_freq > 0 else 0

    # Absolute delay arrays
    abs_L = center_delay_ms + lfo_L
    abs_R = center_delay_ms + lfo_R
    abs_L_s = phase.extract_lfo(center_delay_ms + dev_L, sr)
    abs_R_s = phase.extract_lfo(center_delay_ms + dev_R, sr)
    t_abs = np.arange(len(abs_L)) / sr + chorus_start / sr

    # ================================================================
    # Print results
    # ================================================================
    print(f"\n{'='*60}")
    print(f"BBD ABSOLUTE DELAY — {args.mode}")
    print(f"{'='*60}")

    print(f"\nLFO: {lfo_freq:.3f} Hz ({1/lfo_freq:.2f}s), {n_cyc} cycles, shape: {shape}")
    print(f"  fit_ratio: {shape_m.get('fit_ratio',0):.3f}")
    print(f"L/R: {phase_offset_deg:.1f}° "
          f"({'antiphase' if abs(abs(phase_offset_deg)-180) < 30 else 'CHECK'})")

    print(f"\nAbsolute delay:")
    print(f"  Center:     {center_delay_ms:.3f} ms")
    print(f"  Mod depth:  ±{mod_depth:.3f} ms")
    print(f"  Range:      [{min_delay:.3f}, {max_delay:.3f}] ms")
    print(f"  Per-ch:     L ±{mod_L:.3f}, R ±{mod_R:.3f} (ratio {mod_L/mod_R:.3f})")

    if center_clock > 0:
        print(f"\nMN3009 (256-stage) BBD clock:")
        print(f"  Center:  {center_clock/1000:.2f} kHz")
        print(f"  Range:   [{min_clock/1000:.2f}, {max_clock/1000:.2f}] kHz")
        print(f"  Nyquist: [{min_clock/4/1000:.2f}, {max_clock/4/1000:.2f}] kHz "
              f"(center {center_clock/4/1000:.2f} kHz)")

    # ================================================================
    # Plots
    # ================================================================
    fig = plt.figure(figsize=(16, 18))
    gs = GridSpec(5, 2, figure=fig, hspace=0.4, wspace=0.3)
    title = f"Juno-6 BBD Absolute Delay — {args.mode} — {freq:.1f} Hz sine"

    # 1. Raw waveform
    ax = fig.add_subplot(gs[0, :])
    t_raw = np.arange(len(L)) / sr
    ax.plot(t_raw, L, alpha=0.5, lw=0.3, label='L')
    ax.plot(t_raw, R, alpha=0.5, lw=0.3, label='R')
    ax.axvline(onset_time, color='red', ls='--', lw=1.5, label=f'Chorus on @ {onset_time:.1f}s')
    ax.set_xlabel('Time (s)'); ax.set_ylabel('Amplitude')
    ax.set_title('Raw Waveform'); ax.legend(fontsize=8)

    # 2. Absolute delay
    ax = fig.add_subplot(gs[1, :])
    ax.plot(t_abs, center_delay_ms + dev_L, color='C0', lw=0.3, alpha=0.3)
    ax.plot(t_abs, center_delay_ms + dev_R, color='C1', lw=0.3, alpha=0.3)
    ax.plot(t_abs, abs_L_s, color='C0', lw=1.5, label='L')
    ax.plot(t_abs, abs_R_s, color='C1', lw=1.5, label='R')
    ax.axhline(center_delay_ms, color='green', ls='--', alpha=0.7,
               label=f'Center {center_delay_ms:.2f} ms')
    ax.axhline(0, color='gray', ls=':', alpha=0.3)
    ax.set_xlabel('Time (s)'); ax.set_ylabel('Delay (ms)')
    ax.set_title('Absolute BBD Delay'); ax.legend(fontsize=8); ax.grid(True, alpha=0.3)

    # 3. Phase step at transition (block-based)
    ax = fig.add_subplot(gs[2, 0])
    trans_mask = (bt_L > onset_time - 1.0) & (bt_L < onset_time + 3.0)
    trans_t = bt_L[trans_mask]
    trans_ph_avg = (bp_L[trans_mask] + bp_R[trans_mask]) / 2
    trans_delay = (np.polyval(dry_coeffs, trans_t) - trans_ph_avg) / omega * 1000
    ax.plot(trans_t - onset_time, trans_delay, 'k-', lw=1.2)
    ax.axvline(0, color='red', ls='--', lw=1, label='Chorus on')
    ax.axhline(center_delay_ms, color='green', ls='--', alpha=0.5,
               label=f'{center_delay_ms:.2f} ms')
    ax.axhline(0, color='gray', ls=':', alpha=0.3)
    ax.set_xlabel('Time rel. to onset (s)'); ax.set_ylabel('Delay (ms)')
    ax.set_title('Phase Step at Transition (block DFT)')
    ax.legend(fontsize=8); ax.grid(True, alpha=0.3)

    # 4. Dry residual
    ax = fig.add_subplot(gs[2, 1])
    ax.plot(dry_t, dry_residual_ms, lw=0.8, color='k')
    ax.axhline(0, color='gray', ls=':', alpha=0.5)
    ax.set_xlabel('Time (s)'); ax.set_ylabel('ms')
    ax.set_title(f'Dry Residual (σ={np.std(dry_residual_ms):.4f} ms)')
    ax.grid(True, alpha=0.3)

    # 5. LFO detail (~4 cycles)
    ax = fig.add_subplot(gs[3, 0])
    if lfo_freq > 0:
        zlen = min(int(4 / lfo_freq * sr), len(abs_L_s) - 10)
    else:
        zlen = min(int(4 * sr), len(abs_L_s) - 10)
    zs = len(abs_L_s) // 2 - zlen // 2
    zt = np.arange(zlen) / sr
    ax.plot(zt, abs_L_s[zs:zs+zlen], lw=1.5, label='L')
    ax.plot(zt, abs_R_s[zs:zs+zlen], lw=1.5, label='R')
    ax.axhline(center_delay_ms, color='green', ls='--', alpha=0.5)
    ax.set_xlabel('Time (s)'); ax.set_ylabel('Delay (ms)')
    ax.set_title('LFO Detail'); ax.legend(fontsize=8); ax.grid(True, alpha=0.3)

    # 6. Delay histogram
    ax = fig.add_subplot(gs[3, 1])
    ax.hist(abs_L_s, bins=80, alpha=0.6, label='L', density=True, color='C0')
    ax.hist(abs_R_s, bins=80, alpha=0.6, label='R', density=True, color='C1')
    ax.axvline(center_delay_ms, color='green', ls='--', alpha=0.7)
    ax.axvline(min_delay, color='red', ls=':', alpha=0.5, label=f'Min {min_delay:.2f}')
    ax.axvline(max_delay, color='red', ls=':', alpha=0.5, label=f'Max {max_delay:.2f}')
    ax.set_xlabel('Delay (ms)'); ax.set_ylabel('Density')
    ax.set_title('Delay Distribution'); ax.legend(fontsize=8)

    # 7. LFO spectrum
    ax = fig.add_subplot(gs[4, 0])
    N = len(lfo_L)
    win = np.hanning(N)
    spec = np.abs(scipy.fft.rfft((lfo_L - np.mean(lfo_L)) * win))
    freqs = scipy.fft.rfftfreq(N, 1/sr)
    mask = freqs < 10
    spec_db = 20 * np.log10(spec[mask] / np.max(spec[mask]) + 1e-10)
    ax.plot(freqs[mask], spec_db, lw=1)
    ax.set_ylim(-60, 5)
    ax.set_xlabel('Hz'); ax.set_ylabel('dB')
    ax.set_title('LFO Spectrum'); ax.grid(True, alpha=0.3)

    # 8. BBD clock
    ax = fig.add_subplot(gs[4, 1])
    safe_L = np.clip(abs_L_s, 0.1, None)
    safe_R = np.clip(abs_R_s, 0.1, None)
    clock_L = stages / (2 * safe_L / 1000) / 1000
    clock_R = stages / (2 * safe_R / 1000) / 1000
    ax.plot(t_abs, clock_L, lw=0.8, label='L', color='C0')
    ax.plot(t_abs, clock_R, lw=0.8, label='R', color='C1')
    if center_clock > 0:
        ax.axhline(center_clock/1000, color='green', ls='--', alpha=0.5,
                    label=f'Center {center_clock/1000:.1f} kHz')
    ax.set_xlabel('Time (s)'); ax.set_ylabel('kHz')
    ax.set_title('MN3009 Clock (256 stages)'); ax.legend(fontsize=8); ax.grid(True, alpha=0.3)

    plotting.save(fig, args.wavfile.rsplit('.', 1)[0] + '_absolute.png', title)

    # Summary
    print(f"\n{'='*60}")
    print(f"SPEC SUMMARY — {args.mode}")
    print(f"{'='*60}")
    print(f"  LFO:          {lfo_freq:.3f} Hz, triangle")
    print(f"  Center delay: {center_delay_ms:.3f} ms")
    print(f"  Mod depth:    ±{mod_depth:.3f} ms")
    print(f"  Delay range:  {min_delay:.3f} – {max_delay:.3f} ms")
    if center_clock > 0:
        print(f"  BBD clock:    {center_clock/1000:.2f} kHz "
              f"[{min_clock/1000:.2f}–{max_clock/1000:.2f}]")
        print(f"  BBD Nyquist:  {center_clock/4/1000:.2f} kHz")
    print(f"  L/R phase:    {phase_offset_deg:.1f}°")


if __name__ == '__main__':
    main()
