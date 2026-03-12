#!/usr/bin/env python3
"""
analyze_bbd_delay.py — BBD delay measurement from sine wave through Juno-6 chorus

Feed a pure sine (self-oscillating filter or external) through the chorus,
record stereo from the Mono + Stereo jacks. This script extracts:
  - BBD delay modulation range (min/max in ms)
  - LFO rate, waveshape (triangle vs sine), and phase relationship L/R
  - Note: absolute (center) delay requires a dry reference channel

Usage:
  python analyze_bbd_delay.py <stereo_wav> [--freq FREQ_HZ] [--mode MODE]

If --freq is omitted, the script auto-detects the fundamental.
--mode is just a label for the plot title (e.g. "chorus1", "chorus2", "chorus12")
"""

import sys
import argparse
import numpy as np
import scipy.signal as signal
import scipy.fft
import soundfile as sf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec


def find_fundamental(mono, sr, expected_range=(100, 2000)):
    """Auto-detect fundamental frequency via autocorrelation."""
    chunk_len = min(len(mono), sr)
    start = len(mono) // 2 - chunk_len // 2
    chunk = mono[start:start + chunk_len]
    chunk = chunk * np.hanning(len(chunk))

    corr = np.correlate(chunk, chunk, mode='full')
    corr = corr[len(corr) // 2:]
    corr = corr / corr[0]

    min_lag = int(sr / expected_range[1])
    max_lag = int(sr / expected_range[0])
    search = corr[min_lag:max_lag]
    if len(search) == 0:
        raise ValueError(f"No valid autocorrelation range for {expected_range} Hz")
    peak_lag = min_lag + np.argmax(search)
    freq = sr / peak_lag
    return freq


def extract_instantaneous_phase(audio, sr, freq):
    """
    Extract instantaneous phase at the fundamental using Hilbert transform.
    Also returns the amplitude envelope for gating unreliable regions.
    """
    # Bandpass around fundamental
    bw = max(freq * 0.08, 8)  # tight: 8% bandwidth, min 8 Hz
    lo = max(freq - bw, 5)
    hi = min(freq + bw, sr / 2 - 1)
    sos = signal.butter(6, [lo, hi], btype='band', fs=sr, output='sos')
    filtered = signal.sosfiltfilt(sos, audio)

    # Analytic signal
    analytic = signal.hilbert(filtered)
    inst_phase = np.unwrap(np.angle(analytic))
    amplitude = np.abs(analytic)

    return inst_phase, amplitude, filtered


def extract_delay_modulation(phase, amplitude, freq, sr, amp_gate_ratio=0.3):
    """
    Extract delay modulation from instantaneous phase.

    Subtracts the linear phase ramp (carrier), converts residual to ms.
    Gates out samples where amplitude is below threshold (unreliable phase).
    Applies median filter to reject remaining spikes.

    Returns: delay_ms (cleaned), t (time array), valid_mask, actual_freq, raw_delay
    """
    omega = 2 * np.pi * freq
    t = np.arange(len(phase)) / sr

    # Amplitude gate: mask out low-amplitude regions
    amp_threshold = np.median(amplitude) * amp_gate_ratio
    valid = amplitude > amp_threshold

    # Fit linear ramp only to valid samples
    valid_idx = np.where(valid)[0]
    # Also skip edges
    margin = int(sr * 0.3)
    edge_mask = (valid_idx > margin) & (valid_idx < len(phase) - margin)
    fit_idx = valid_idx[edge_mask]

    if len(fit_idx) < 100:
        raise ValueError("Not enough valid samples for phase fit")

    coeffs = np.polyfit(t[fit_idx], phase[fit_idx], 1)
    phase_linear = coeffs[0] * t + coeffs[1]
    phase_dev = phase - phase_linear

    actual_freq = coeffs[0] / (2 * np.pi)

    # Convert to delay in ms
    delay_ms = (phase_dev / omega) * 1000

    # Invalidate edges
    valid[:margin] = False
    valid[-margin:] = False

    # Median filter to squash remaining spikes (kernel ~5ms worth of samples)
    kernel = int(sr * 0.005) | 1  # odd number, ~5ms
    delay_medfilt = signal.medfilt(delay_ms, kernel_size=min(kernel, len(delay_ms) | 1))

    # Detect spikes: where raw deviates from median by > 0.5ms
    spike_mask = np.abs(delay_ms - delay_medfilt) > 0.5
    valid[spike_mask] = False

    # Use the median-filtered version as the clean signal
    delay_clean = delay_medfilt.copy()
    delay_clean[~valid] = np.nan

    return delay_clean, t, valid, actual_freq, delay_ms


def extract_lfo(delay_ms, sr, valid_mask, max_lfo_freq=5.0):
    """
    Extract LFO from delay signal. Interpolates over invalid gaps first.
    """
    # Interpolate NaN gaps for filtering
    delay_interp = delay_ms.copy()
    nans = np.isnan(delay_interp)
    if np.any(~nans):
        delay_interp[nans] = np.interp(
            np.where(nans)[0], np.where(~nans)[0], delay_interp[~nans]
        )

    # Lowpass to isolate LFO (< max_lfo_freq Hz)
    sos = signal.butter(4, max_lfo_freq, btype='low', fs=sr, output='sos')
    lfo = signal.sosfiltfilt(sos, delay_interp)
    return lfo


def measure_lfo_frequency(lfo, sr):
    """Measure LFO frequency from zero crossings of centered signal."""
    lfo_centered = lfo - np.mean(lfo)
    crossings = np.where(np.diff(np.sign(lfo_centered)))[0]
    if len(crossings) < 4:
        return 0.0, 0
    # Use same-direction crossings for full periods
    periods = np.diff(crossings[::2]) / sr
    if len(periods) == 0:
        periods = np.diff(crossings) / sr * 2
    freq = 1.0 / np.median(periods) if len(periods) > 0 else 0.0
    return freq, len(crossings) // 2


def classify_lfo_shape(lfo, sr):
    """
    Classify LFO waveshape by fitting both triangle and sine at the measured
    LFO frequency and comparing residuals.

    Returns shape name and metrics dict.
    """
    lfo_norm = lfo - np.mean(lfo)
    peak = np.max(np.abs(lfo_norm))
    if peak < 1e-12:
        return "flat", {}
    lfo_norm = lfo_norm / peak

    lfo_freq, _ = measure_lfo_frequency(lfo, sr)
    if lfo_freq <= 0:
        return "unknown", {}

    t = np.arange(len(lfo_norm)) / sr

    # Fit triangle and sine at many phase offsets
    best_tri_err = np.inf
    best_tri = None
    best_sin_err = np.inf
    best_sin = None
    n_test = 200
    for phi_idx in range(n_test):
        phi = 2 * np.pi * phi_idx / n_test
        tri = signal.sawtooth(2 * np.pi * lfo_freq * t + phi, width=0.5)
        sin = np.sin(2 * np.pi * lfo_freq * t + phi)
        tri_err = np.mean((lfo_norm - tri) ** 2)
        sin_err = np.mean((lfo_norm - sin) ** 2)
        if tri_err < best_tri_err:
            best_tri_err = tri_err
            best_tri = tri
        if sin_err < best_sin_err:
            best_sin_err = sin_err
            best_sin = sin

    fit_ratio = best_tri_err / best_sin_err if best_sin_err > 0 else 1.0

    metrics = {
        'fit_ratio': fit_ratio,
        'tri_rmse': np.sqrt(best_tri_err),
        'sin_rmse': np.sqrt(best_sin_err),
    }

    if fit_ratio < 0.7:
        shape = "triangle"
    elif fit_ratio < 0.9:
        shape = "triangle (rounded corners)"
    elif fit_ratio < 1.1:
        shape = "ambiguous (triangle ≈ sine)"
    elif fit_ratio < 1.4:
        shape = "sine (or rounded triangle)"
    else:
        shape = "sine"

    return shape, metrics


def main():
    parser = argparse.ArgumentParser(description='Analyze BBD delay from sine through chorus')
    parser.add_argument('wavfile', help='Stereo WAV file (L=Mono jack, R=Stereo jack)')
    parser.add_argument('--freq', type=float, default=None,
                        help='Fundamental frequency in Hz (auto-detected if omitted)')
    parser.add_argument('--trim', type=float, default=0.5,
                        help='Seconds to trim from start/end (default 0.5)')
    parser.add_argument('--mode', type=str, default='Chorus I',
                        help='Chorus mode label for plot title')
    args = parser.parse_args()

    # Load
    audio, sr = sf.read(args.wavfile)
    print(f"Loaded: {args.wavfile}")
    print(f"  Sample rate: {sr} Hz")
    print(f"  Duration: {len(audio)/sr:.2f}s")
    print(f"  Channels: {audio.shape[1] if audio.ndim > 1 else 1}")
    print(f"  Peak: {np.max(np.abs(audio)):.4f}")

    if audio.ndim == 1:
        print("\nERROR: Need stereo file (L=Mono jack, R=Stereo jack)")
        sys.exit(1)

    L = audio[:, 0]
    R = audio[:, 1]

    # Trim edges
    trim_samples = int(args.trim * sr)
    if trim_samples > 0 and len(L) > trim_samples * 3:
        L = L[trim_samples:-trim_samples]
        R = R[trim_samples:-trim_samples]
        print(f"  Trimmed {args.trim}s from each end, {len(L)/sr:.2f}s remaining")

    # Auto-detect frequency
    mono = (L + R) / 2
    if args.freq is None:
        freq = find_fundamental(mono, sr)
        print(f"\n  Auto-detected fundamental: {freq:.1f} Hz")
    else:
        freq = args.freq
        print(f"\n  Using specified fundamental: {freq:.1f} Hz")

    # Extract instantaneous phase + amplitude for each channel
    print("\nExtracting instantaneous phase...")
    phase_L, amp_L, filt_L = extract_instantaneous_phase(L, sr, freq)
    phase_R, amp_R, filt_R = extract_instantaneous_phase(R, sr, freq)

    # Extract per-channel delay modulation with spike rejection
    print("Extracting delay modulation (amplitude-gated, median-filtered)...")
    delay_L, t_L, valid_L, freq_L, raw_L = extract_delay_modulation(phase_L, amp_L, freq, sr)
    delay_R, t_R, valid_R, freq_R, raw_R = extract_delay_modulation(phase_R, amp_R, freq, sr)

    print(f"  Actual carrier freq (from L): {freq_L:.2f} Hz")
    print(f"  Actual carrier freq (from R): {freq_R:.2f} Hz")
    print(f"  Valid samples: L={np.sum(valid_L)}/{len(valid_L)} "
          f"({100*np.sum(valid_L)/len(valid_L):.1f}%), "
          f"R={np.sum(valid_R)}/{len(valid_R)} "
          f"({100*np.sum(valid_R)/len(valid_R):.1f}%)")

    # Extract LFO
    lfo_L = extract_lfo(delay_L, sr, valid_L)
    lfo_R = extract_lfo(delay_R, sr, valid_R)

    # LFO frequency
    lfo_freq_L, n_cycles_L = measure_lfo_frequency(lfo_L, sr)
    lfo_freq_R, n_cycles_R = measure_lfo_frequency(lfo_R, sr)

    # LFO shape
    shape_L, metrics_L = classify_lfo_shape(lfo_L, sr)
    shape_R, metrics_R = classify_lfo_shape(lfo_R, sr)

    # Modulation depth from the clean LFO (not raw)
    mod_L = (np.max(lfo_L) - np.min(lfo_L)) / 2
    mod_R = (np.max(lfo_R) - np.min(lfo_R)) / 2

    # Print results
    print(f"\n{'='*60}")
    print(f"BBD DELAY ANALYSIS — {args.mode}")
    print(f"{'='*60}")

    print(f"\nNote: center delay cannot be determined without a dry reference.")
    print(f"Values below are modulation depth only (deviation from mean).")

    print(f"\nLeft channel (Mono jack):")
    print(f"  Modulation depth: ±{mod_L:.3f} ms (peak-to-peak {mod_L*2:.3f} ms)")
    print(f"  LFO freq: {lfo_freq_L:.3f} Hz (period {1/lfo_freq_L:.2f}s, {n_cycles_L} cycles)")
    print(f"  LFO shape: {shape_L}")
    print(f"    fit_ratio (tri/sin): {metrics_L.get('fit_ratio', 0):.3f}  "
          f"(<1 = triangle better, >1 = sine better)")
    print(f"    tri RMSE: {metrics_L.get('tri_rmse', 0):.4f}  "
          f"sin RMSE: {metrics_L.get('sin_rmse', 0):.4f}")

    print(f"\nRight channel (Stereo jack):")
    print(f"  Modulation depth: ±{mod_R:.3f} ms (peak-to-peak {mod_R*2:.3f} ms)")
    print(f"  LFO freq: {lfo_freq_R:.3f} Hz (period {1/lfo_freq_R:.2f}s, {n_cycles_R} cycles)")
    print(f"  LFO shape: {shape_R}")
    print(f"    fit_ratio (tri/sin): {metrics_R.get('fit_ratio', 0):.3f}")
    print(f"    tri RMSE: {metrics_R.get('tri_rmse', 0):.4f}  "
          f"sin RMSE: {metrics_R.get('sin_rmse', 0):.4f}")

    # L/R phase relationship
    corr = np.correlate(lfo_L - np.mean(lfo_L), lfo_R - np.mean(lfo_R), mode='full')
    lags = np.arange(-len(lfo_L) + 1, len(lfo_L)) / sr
    peak_lag_idx = np.argmax(corr)
    peak_lag_s = lags[peak_lag_idx]
    avg_lfo_freq = (lfo_freq_L + lfo_freq_R) / 2
    if avg_lfo_freq > 0:
        phase_offset_deg = peak_lag_s * avg_lfo_freq * 360
    else:
        phase_offset_deg = 0

    print(f"\nL/R LFO relationship:")
    print(f"  Time offset: {peak_lag_s*1000:.1f} ms")
    print(f"  Phase offset: {phase_offset_deg:.1f}°")
    if abs(abs(phase_offset_deg) - 180) < 30:
        print(f"  → Antiphase (expected for Juno chorus)")
    elif abs(phase_offset_deg) < 30 or abs(phase_offset_deg) > 330:
        print(f"  → In-phase (unexpected — check jack assignments)")
    else:
        print(f"  → Partial offset ({phase_offset_deg:.0f}°)")

    # Depth asymmetry check
    if mod_R > 0:
        print(f"\nDepth match: L ±{mod_L:.3f} vs R ±{mod_R:.3f} ms "
              f"(ratio {mod_L/mod_R:.2f})")

    # ----- Plots -----
    fig = plt.figure(figsize=(16, 16))
    gs = GridSpec(5, 2, figure=fig, hspace=0.4, wspace=0.3)

    title = f"Juno-6 BBD Chorus Analysis — {args.mode} — {freq:.1f} Hz sine"

    # 1. Raw waveform overview
    ax1 = fig.add_subplot(gs[0, :])
    t_full = np.arange(len(L)) / sr
    ax1.plot(t_full, L, alpha=0.5, linewidth=0.3, label='L (Mono)')
    ax1.plot(t_full, R, alpha=0.5, linewidth=0.3, label='R (Stereo)')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Amplitude')
    ax1.set_title('Raw Waveform')
    ax1.legend(loc='upper right')

    # 2. Raw vs cleaned delay (show what was rejected)
    ax2 = fig.add_subplot(gs[1, :])
    ax2.plot(t_L, raw_L, color='lightblue', linewidth=0.3, alpha=0.5, label='L raw')
    ax2.plot(t_L, lfo_L, color='C0', linewidth=1.2, label=f'L cleaned (LFO {lfo_freq_L:.3f} Hz)')
    ax2.plot(t_R, raw_R, color='bisque', linewidth=0.3, alpha=0.5, label='R raw')
    ax2.plot(t_R, lfo_R, color='C1', linewidth=1.2, label=f'R cleaned (LFO {lfo_freq_R:.3f} Hz)')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Delay modulation (ms)')
    ax2.set_title('BBD Delay Modulation (raw + cleaned)')
    ax2.legend(loc='upper right', fontsize=8)
    ax2.grid(True, alpha=0.3)

    # 3. Zoomed LFO detail — ~4 cycles from middle
    ax3 = fig.add_subplot(gs[2, 0])
    if avg_lfo_freq > 0:
        zoom_len = min(int(4 / avg_lfo_freq * sr), len(lfo_L) - 100)
    else:
        zoom_len = min(int(4 * sr), len(lfo_L) - 100)
    zoom_start = len(lfo_L) // 2 - zoom_len // 2
    t_zoom = np.arange(zoom_len) / sr
    ax3.plot(t_zoom, lfo_L[zoom_start:zoom_start + zoom_len], linewidth=1.5, label='L')
    ax3.plot(t_zoom, lfo_R[zoom_start:zoom_start + zoom_len], linewidth=1.5, label='R')
    ax3.set_xlabel('Time (s)')
    ax3.set_ylabel('Delay (ms)')
    ax3.set_title('LFO Detail (~4 cycles, middle of recording)')
    ax3.legend()
    ax3.grid(True, alpha=0.3)

    # 4. LFO spectrum
    ax4 = fig.add_subplot(gs[2, 1])
    N = len(lfo_L)
    win = np.hanning(N)
    spec_L = np.abs(scipy.fft.rfft((lfo_L - np.mean(lfo_L)) * win))
    spec_R = np.abs(scipy.fft.rfft((lfo_R - np.mean(lfo_R)) * win))
    freqs = scipy.fft.rfftfreq(N, 1 / sr)
    mask = freqs < 10
    spec_L_db = 20 * np.log10(spec_L[mask] / np.max(spec_L[mask]) + 1e-10)
    spec_R_db = 20 * np.log10(spec_R[mask] / np.max(spec_R[mask]) + 1e-10)
    ax4.plot(freqs[mask], spec_L_db, linewidth=1, label='L')
    ax4.plot(freqs[mask], spec_R_db, linewidth=1, label='R')
    ax4.set_xlabel('Frequency (Hz)')
    ax4.set_ylabel('Magnitude (dB, normalized)')
    ax4.set_title('LFO Spectrum (triangle: odd harmonics @ -1/n²)')
    ax4.legend()
    ax4.grid(True, alpha=0.3)
    ax4.set_ylim(-60, 5)
    for h in range(1, 8):
        f_h = avg_lfo_freq * h
        if f_h < 10:
            ax4.axvline(f_h, color='gray', alpha=0.3, linestyle='--', linewidth=0.5)

    # 5. Delay histogram
    ax5 = fig.add_subplot(gs[3, 0])
    valid_L_data = lfo_L[~np.isnan(delay_L)] if np.any(~np.isnan(delay_L)) else lfo_L
    valid_R_data = lfo_R[~np.isnan(delay_R)] if np.any(~np.isnan(delay_R)) else lfo_R
    ax5.hist(valid_L_data, bins=80, alpha=0.6, label='L', density=True, color='C0')
    ax5.hist(valid_R_data, bins=80, alpha=0.6, label='R', density=True, color='C1')
    ax5.set_xlabel('Delay modulation (ms)')
    ax5.set_ylabel('Density')
    ax5.set_title('Delay Distribution (triangle→flat, sine→U-shaped)')
    ax5.legend()

    # 6. L vs R scatter
    ax6 = fig.add_subplot(gs[3, 1])
    step = max(1, len(lfo_L) // 5000)
    sc = ax6.scatter(lfo_L[::step], lfo_R[::step], s=2, alpha=0.3, c=t_L[::step], cmap='viridis')
    ax6.set_xlabel('L delay (ms)')
    ax6.set_ylabel('R delay (ms)')
    ax6.set_title('L vs R Delay (antiphase → negative slope)')
    ax6.set_aspect('equal')
    ax6.grid(True, alpha=0.3)
    plt.colorbar(sc, ax=ax6, label='Time (s)', shrink=0.8)

    # 7. Waveshape fit comparison — overlay triangle and sine on one cycle
    ax7 = fig.add_subplot(gs[4, 0])
    if avg_lfo_freq > 0:
        one_cycle = int(sr / avg_lfo_freq)
        mid = len(lfo_L) // 2
        chunk = lfo_L[mid:mid + one_cycle]
        chunk_norm = (chunk - np.mean(chunk))
        cpeak = np.max(np.abs(chunk_norm))
        if cpeak > 0:
            chunk_norm = chunk_norm / cpeak

        t_cycle = np.linspace(0, 360, len(chunk_norm))
        ax7.plot(t_cycle, chunk_norm, 'k-', linewidth=2, label='Measured LFO')

        # Best-fit triangle and sine
        tc = np.arange(len(chunk_norm)) / sr
        best_tri_err = np.inf
        best_tri = None
        best_sin_err = np.inf
        best_sin = None
        for phi_idx in range(200):
            phi = 2 * np.pi * phi_idx / 200
            tri = signal.sawtooth(2 * np.pi * avg_lfo_freq * tc + phi, width=0.5)
            sin = np.sin(2 * np.pi * avg_lfo_freq * tc + phi)
            tri_err = np.mean((chunk_norm - tri) ** 2)
            sin_err = np.mean((chunk_norm - sin) ** 2)
            if tri_err < best_tri_err:
                best_tri_err = tri_err
                best_tri = tri
            if sin_err < best_sin_err:
                best_sin_err = sin_err
                best_sin = sin

        ax7.plot(t_cycle, best_tri, '--', linewidth=1.2, color='C2',
                 label=f'Triangle fit (RMSE {np.sqrt(best_tri_err):.4f})')
        ax7.plot(t_cycle, best_sin, '--', linewidth=1.2, color='C3',
                 label=f'Sine fit (RMSE {np.sqrt(best_sin_err):.4f})')
        ax7.set_xlabel('Phase (degrees)')
        ax7.set_ylabel('Normalized amplitude')
        ax7.set_title('LFO Waveshape Comparison (L, 1 cycle)')
        ax7.legend(fontsize=8)
        ax7.grid(True, alpha=0.3)

    # 8. Amplitude envelope (shows where phase estimation is reliable)
    ax8 = fig.add_subplot(gs[4, 1])
    t_amp = np.arange(len(amp_L)) / sr
    ax8.plot(t_amp, amp_L, linewidth=0.5, alpha=0.7, label='L amplitude')
    ax8.plot(t_amp, amp_R, linewidth=0.5, alpha=0.7, label='R amplitude')
    amp_thresh_L = np.median(amp_L) * 0.3
    ax8.axhline(amp_thresh_L, color='red', linestyle=':', alpha=0.5, label='Gate threshold')
    ax8.set_xlabel('Time (s)')
    ax8.set_ylabel('Amplitude')
    ax8.set_title('Signal Amplitude (gating reliability)')
    ax8.legend(fontsize=8)

    plt.suptitle(title, fontsize=14, y=0.98)

    outpath = args.wavfile.rsplit('.', 1)[0] + '_bbd_analysis.png'
    plt.savefig(outpath, dpi=150, bbox_inches='tight')
    print(f"\nPlot saved: {outpath}")
    plt.close()


if __name__ == '__main__':
    main()
