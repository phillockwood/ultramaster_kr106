#!/usr/bin/env python3
"""
Juno-106 Test Recording Analyzer
=================================
Batch-processes test recordings from the Juno-106 Test Recording Guide.
Generates per-file analysis plots and a summary report.

Usage:
    python juno_analyzer.py <recordings_folder> [--output <output_folder>] [--reference <ref_folder>]

The --reference folder (optional) should contain matching filenames from your
synth engine for side-by-side comparison.

File naming: expects files like 01-saw-open.wav, 05-filter-cutoff-res0.wav, etc.
The leading number determines which analysis to run.
"""

import os
import sys
import glob
import argparse
import numpy as np
import soundfile as sf
import scipy.signal as signal
import scipy.fft as fft
from scipy.optimize import curve_fit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path
import json


# ============================================================
# Utilities
# ============================================================

def load_mono(path):
    """Load a WAV file, return mono float64 array and sample rate."""
    data, sr = sf.read(path)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data, sr


def find_onset(x, sr, threshold=0.005):
    """Find the first sample where smoothed amplitude exceeds threshold."""
    win = max(1, int(sr * 0.001))
    env = np.convolve(np.abs(x), np.ones(win) / win, mode='same')
    idx = np.where(env > threshold)[0]
    return idx[0] if len(idx) > 0 else 0


def find_offset(x, sr, threshold=0.005):
    """Find the last sample where smoothed amplitude exceeds threshold."""
    win = max(1, int(sr * 0.001))
    env = np.convolve(np.abs(x), np.ones(win) / win, mode='same')
    idx = np.where(env > threshold)[0]
    return idx[-1] if len(idx) > 0 else len(x) - 1


def rms(x):
    return np.sqrt(np.mean(x ** 2))


def db(x):
    return 20 * np.log10(np.abs(x) + 1e-10)


def avg_spectrum(x, start, n_fft, n_avg, sr):
    """Average magnitude spectrum over n_avg overlapping frames."""
    win = np.hanning(n_fft)
    hop = n_fft // 2
    specs = []
    for i in range(n_avg):
        offset = start + i * hop
        if offset + n_fft > len(x):
            break
        specs.append(np.abs(fft.rfft(x[offset:offset + n_fft] * win)))
    if not specs:
        return None, None
    mag = np.mean(specs, axis=0)
    freqs = np.arange(len(mag)) * sr / n_fft
    return freqs, mag


def find_fundamental(mag, freqs, min_f=50, max_f=2000):
    """Find the strongest peak between min_f and max_f."""
    mask = (freqs >= min_f) & (freqs <= max_f)
    if not np.any(mask):
        return 0, 0
    idx = np.argmax(mag[mask]) + np.searchsorted(freqs, min_f)
    return freqs[idx], mag[idx]


def spectral_centroid(mag, freqs):
    s = np.sum(mag)
    if s < 1e-10:
        return 0
    return np.sum(freqs * mag) / s


def amplitude_envelope(x, sr, hop=512):
    """Compute RMS amplitude envelope."""
    env, times = [], []
    for i in range(0, len(x) - hop, hop):
        env.append(rms(x[i:i + hop]))
        times.append(i / sr)
    return np.array(times), np.array(env)


# ============================================================
# Harmonic analysis
# ============================================================

def harmonic_analysis(mag, freqs, fund_freq, n_harmonics=30, wave='saw'):
    """
    Measure harmonics relative to fundamental.
    Returns list of dicts with harmonic info.
    """
    fund_amp = None
    results = []

    for n in range(1, n_harmonics + 1):
        target = fund_freq * n
        if target > freqs[-1] - 50:
            break

        search = max(8, fund_freq * 0.02)
        mask = (freqs >= target - search) & (freqs <= target + search)
        if not np.any(mask):
            continue

        local = mag[mask]
        local_f = freqs[mask]
        peak_idx = np.argmax(local)
        peak_freq = local_f[peak_idx]
        peak_amp = local[peak_idx]

        if n == 1:
            fund_amp = peak_amp

        rel_db = db(peak_amp / fund_amp) if fund_amp else 0

        if wave == 'saw':
            ideal_db = -20 * np.log10(n)
        elif wave == 'square':
            ideal_db = -20 * np.log10(n) if n % 2 == 1 else -999
        else:
            ideal_db = 0

        results.append({
            'n': n,
            'freq': peak_freq,
            'amp_db': rel_db,
            'ideal_db': ideal_db,
            'error_db': rel_db - ideal_db if ideal_db > -900 else rel_db,
            'is_odd': n % 2 == 1,
        })

    return results


# ============================================================
# Envelope extraction (ADSR)
# ============================================================

def extract_envelope(x, sr, hop=256):
    """Extract amplitude envelope using Hilbert transform, smoothed."""
    analytic = np.abs(signal.hilbert(x))
    # Smooth with ~5ms window
    win_size = max(1, int(sr * 0.005))
    if win_size % 2 == 0:
        win_size += 1
    smoothed = signal.medfilt(analytic, win_size)
    # Downsample
    times = np.arange(0, len(smoothed), hop) / sr
    env = smoothed[::hop]
    return times, env


def segment_notes(x, sr, threshold=0.01, min_gap_ms=100):
    """Find individual note segments in a recording with multiple notes."""
    hop = 256
    t, env = amplitude_envelope(x, sr, hop)
    env_db = db(env)

    above = env_db > db(threshold)
    segments = []
    in_note = False
    start = 0
    min_gap = int(min_gap_ms / 1000 * sr / hop)

    for i in range(len(above)):
        if above[i] and not in_note:
            in_note = True
            start = i
        elif not above[i] and in_note:
            # Check if this is just a brief dip
            gap_end = min(i + min_gap, len(above))
            if not np.any(above[i:gap_end]):
                segments.append((start * hop, i * hop))
                in_note = False

    if in_note:
        segments.append((start * hop, len(x)))

    return segments


def fit_decay(times, env, start_idx=None):
    """Fit exponential decay to envelope segment. Returns time constant in ms."""
    if start_idx is None:
        start_idx = np.argmax(env)

    t = times[start_idx:] - times[start_idx]
    y = env[start_idx:]

    # Trim to where signal is above noise
    above = y > np.max(y) * 0.01
    if np.sum(above) < 5:
        return None, None
    last = np.where(above)[0][-1]
    t = t[:last + 1]
    y = y[:last + 1]

    if len(t) < 5:
        return None, None

    try:
        def exp_decay(t, a, tau, c):
            return a * np.exp(-t / tau) + c
        p0 = [np.max(y), t[-1] / 3, 0]
        popt, _ = curve_fit(exp_decay, t, y, p0=p0, maxfev=5000)
        return popt[1] * 1000, popt  # tau in ms, full params
    except:
        return None, None


def fit_attack(times, env):
    """Measure attack time (10% to 90% of peak)."""
    peak_idx = np.argmax(env)
    peak = env[peak_idx]
    if peak < 1e-6:
        return None

    thresh_lo = peak * 0.1
    thresh_hi = peak * 0.9

    lo_idx = np.where(env[:peak_idx + 1] >= thresh_lo)[0]
    hi_idx = np.where(env[:peak_idx + 1] >= thresh_hi)[0]

    if len(lo_idx) == 0 or len(hi_idx) == 0:
        return None

    attack_ms = (times[hi_idx[0]] - times[lo_idx[0]]) * 1000
    return attack_ms


# ============================================================
# Filter analysis
# ============================================================

def track_filter_sweep(x, sr, n_fft=2048, hop=256):
    """Track filter cutoff and resonance through a sweep recording."""
    f, t, Zxx = signal.stft(x, sr, nperseg=n_fft, noverlap=n_fft - hop, window='hann')
    mag = np.abs(Zxx)

    cutoffs = []
    prominences = []
    slopes = []

    for i in range(mag.shape[1]):
        frame = mag[:, i]
        frame_db = db(frame)

        if np.max(frame_db) < -60:
            cutoffs.append(np.nan)
            prominences.append(np.nan)
            slopes.append(np.nan)
            continue

        valid = f > 40
        vf = f[valid]
        vd = frame_db[valid]
        vm = frame[valid]

        peak_idx = np.argmax(vm)
        peak_freq = vf[peak_idx]
        peak_db = vd[peak_idx]
        cutoffs.append(peak_freq)

        # Resonance prominence
        oct_below = np.searchsorted(vf, peak_freq / 2)
        if 0 < oct_below < len(vd):
            prominences.append(peak_db - vd[oct_below])
        else:
            prominences.append(0)

        # Rolloff slope
        f1, f2 = peak_freq * 2, peak_freq * 4
        i1, i2 = np.searchsorted(vf, f1), np.searchsorted(vf, f2)
        if i1 < len(vd) and i2 < len(vd) and i2 > i1:
            slopes.append(vd[i2] - vd[i1])
        else:
            slopes.append(np.nan)

    return t, np.array(cutoffs), np.array(prominences), np.array(slopes)


# ============================================================
# Chorus analysis
# ============================================================

def analyze_chorus(dry, wet, sr):
    """Compare dry and wet signals to extract chorus parameters."""
    min_len = min(len(dry), len(wet))
    dry = dry[:min_len]
    wet = wet[:min_len]

    # Cross-correlation to find delay
    n_fft_cc = 2 ** int(np.ceil(np.log2(min_len)))
    cc = np.abs(fft.ifft(fft.fft(wet, n_fft_cc) * np.conj(fft.fft(dry, n_fft_cc))))
    # Ignore zero-lag, look for delay peak in 1-30ms range
    min_delay = int(sr * 0.001)
    max_delay = int(sr * 0.030)
    search = cc[min_delay:max_delay]
    delay_samples = np.argmax(search) + min_delay
    delay_ms = delay_samples / sr * 1000

    # Modulation rate: look at envelope of the difference
    diff = wet - dry
    t_env, env = amplitude_envelope(diff, sr, hop=512)
    # FFT of envelope to find LFO rate
    if len(env) > 256:
        env_spec = np.abs(fft.rfft(env - np.mean(env)))
        env_freqs = np.arange(len(env_spec)) * sr / (512 * len(env_spec) * 2)
        # LFO rate should be between 0.1 and 15 Hz
        lfo_mask = (env_freqs > 0.1) & (env_freqs < 15)
        if np.any(lfo_mask):
            lfo_peak = env_freqs[lfo_mask][np.argmax(env_spec[lfo_mask])]
        else:
            lfo_peak = None
    else:
        lfo_peak = None

    return {
        'delay_ms': delay_ms,
        'lfo_rate_hz': lfo_peak,
    }


# ============================================================
# Waveform shape analysis
# ============================================================

def analyze_waveform_shape(x, sr, fund_freq):
    """Detailed single-cycle waveform analysis."""
    spc = int(sr / fund_freq)

    # Find a stable region
    onset = find_onset(x, sr)
    start = onset + int(0.3 * sr)
    if start + spc * 4 > len(x):
        start = onset + spc * 2

    # Align to a zero crossing
    for i in range(start, start + spc):
        if i + 1 < len(x) and x[i] <= 0 and x[i + 1] > 0:
            start = i
            break

    cycle = x[start:start + spc]
    if len(cycle) < 10:
        return {}

    cycle_norm = cycle / (np.max(np.abs(cycle)) + 1e-10)

    # Edge analysis
    deriv = np.diff(cycle_norm) * sr
    max_pos_deriv = np.max(deriv)
    max_neg_deriv = np.min(deriv)

    # Asymmetry
    pos_peak = np.max(cycle_norm)
    neg_peak = np.abs(np.min(cycle_norm))
    asymmetry = pos_peak / (neg_peak + 1e-10)

    # Gibbs overshoot
    p90 = np.percentile(cycle_norm[cycle_norm > 0], 90) if np.any(cycle_norm > 0) else 0
    overshoot = ((pos_peak / (p90 + 1e-10)) - 1) * 100 if p90 > 0 else 0

    return {
        'cycle': cycle_norm,
        'samples_per_cycle': spc,
        'max_pos_slope': max_pos_deriv,
        'max_neg_slope': max_neg_deriv,
        'asymmetry': asymmetry,
        'overshoot_pct': overshoot,
        'pos_peak': pos_peak,
        'neg_peak': -neg_peak,
    }


# ============================================================
# Analysis runners for each test type
# ============================================================

def analyze_oscillator(path, ref_path, output_dir, label):
    """Tests 1-4: Oscillator waveform analysis."""
    x, sr = load_mono(path)
    info = {'file': os.path.basename(path), 'sr': sr, 'type': 'oscillator'}

    onset = find_onset(x, sr)
    ss_start = onset + int(0.3 * sr)
    n_fft = 16384

    freqs, mag = avg_spectrum(x, ss_start, n_fft, 4, sr)
    if freqs is None:
        print(f"  WARNING: Could not compute spectrum for {path}")
        return info

    fund, fund_amp = find_fundamental(mag, freqs)
    info['fundamental_hz'] = fund
    info['peak_dbfs'] = float(db(np.max(np.abs(x))))
    info['rms_dbfs'] = float(db(rms(x)))
    info['spectral_centroid_hz'] = float(spectral_centroid(mag, freqs))

    # Detect wave type from filename
    fname = os.path.basename(path).lower()
    if 'square' in fname or 'sq' in fname:
        wave = 'square'
    else:
        wave = 'saw'

    harmonics = harmonic_analysis(mag, freqs, fund, wave=wave)
    info['harmonics'] = harmonics

    h20 = [h for h in harmonics if h['n'] <= 20 and h['ideal_db'] > -900]
    if h20:
        info['mean_harmonic_error_db'] = float(np.mean([abs(h['error_db']) for h in h20]))

    shape = analyze_waveform_shape(x, sr, fund)
    info.update(shape)

    # Load reference if available
    ref_x, ref_data = None, None
    if ref_path and os.path.exists(ref_path):
        ref_x, ref_sr = load_mono(ref_path)
        ref_freqs, ref_mag = avg_spectrum(ref_x, find_onset(ref_x, ref_sr) + int(0.3 * ref_sr), n_fft, 4, ref_sr)
        ref_harmonics = harmonic_analysis(ref_mag, ref_freqs, fund, wave=wave) if ref_freqs is not None else None
    else:
        ref_freqs, ref_mag, ref_harmonics = None, None, None

    # Plot
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    # Waveform
    if 'cycle' in shape:
        t_cyc = np.arange(len(shape['cycle'])) / sr * 1000
        axes[0, 0].plot(t_cyc, shape['cycle'], color='#2196F3', linewidth=1.2, label='Recording')
        axes[0, 0].set_title('Single Cycle (normalized)')
        axes[0, 0].set_xlabel('ms')
        axes[0, 0].grid(True, alpha=0.3)
        axes[0, 0].legend()

    # Spectrum
    axes[0, 1].plot(freqs, db(mag), color='#2196F3', linewidth=0.8, alpha=0.8, label='Recording')
    if ref_freqs is not None:
        axes[0, 1].plot(ref_freqs, db(ref_mag), color='#FF5722', linewidth=0.8, alpha=0.6, label='Reference')
    axes[0, 1].set_xlim(20, sr / 2)
    axes[0, 1].set_xscale('log')
    axes[0, 1].set_title('Spectrum')
    axes[0, 1].set_xlabel('Hz')
    axes[0, 1].set_ylabel('dB')
    axes[0, 1].legend()
    axes[0, 1].grid(True, alpha=0.3)

    # Harmonics vs ideal
    if harmonics:
        ns = [h['n'] for h in harmonics]
        axes[1, 0].plot(ns, [h['amp_db'] for h in harmonics], 'o-', color='#2196F3', markersize=4, label='Recording')
        axes[1, 0].plot(ns, [h['ideal_db'] if h['ideal_db'] > -900 else None for h in harmonics],
                        'k--', linewidth=1, alpha=0.5, label=f'Ideal {wave}')
        if ref_harmonics:
            ref_ns = [h['n'] for h in ref_harmonics]
            axes[1, 0].plot(ref_ns, [h['amp_db'] for h in ref_harmonics], 's-',
                            color='#FF5722', markersize=3, alpha=0.6, label='Reference')
        axes[1, 0].set_title('Harmonic Amplitudes')
        axes[1, 0].set_xlabel('Harmonic #')
        axes[1, 0].set_ylabel('dB re: fundamental')
        axes[1, 0].legend(fontsize=8)
        axes[1, 0].grid(True, alpha=0.3)

    # Harmonic error
    if harmonics:
        valid_h = [h for h in harmonics if h['ideal_db'] > -900]
        if valid_h:
            axes[1, 1].bar([h['n'] for h in valid_h], [h['error_db'] for h in valid_h],
                           color='#2196F3', alpha=0.7, label='Recording')
            if ref_harmonics:
                ref_valid = [h for h in ref_harmonics if h['ideal_db'] > -900]
                if ref_valid:
                    axes[1, 1].bar([h['n'] + 0.3 for h in ref_valid], [h['error_db'] for h in ref_valid],
                                   width=0.3, color='#FF5722', alpha=0.6, label='Reference')
            axes[1, 1].axhline(0, color='black', linewidth=0.5)
            axes[1, 1].set_title(f'Harmonic Error vs Ideal {wave.title()}')
            axes[1, 1].set_xlabel('Harmonic #')
            axes[1, 1].set_ylabel('Error (dB)')
            axes[1, 1].legend(fontsize=8)
            axes[1, 1].grid(True, alpha=0.3)

    fig.suptitle(f'{label}\nFund: {fund:.1f}Hz | Centroid: {info["spectral_centroid_hz"]:.0f}Hz | '
                 f'Peak: {info["peak_dbfs"]:.1f}dBFS | RMS: {info["rms_dbfs"]:.1f}dBFS',
                 fontsize=12, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f'{Path(path).stem}_analysis.png'), dpi=150, bbox_inches='tight')
    plt.close()

    return info


def analyze_envelope(path, ref_path, output_dir, label):
    """Tests 5-7: ADSR envelope analysis."""
    x, sr = load_mono(path)
    info = {'file': os.path.basename(path), 'sr': sr, 'type': 'envelope'}

    segments = segment_notes(x, sr, threshold=0.005, min_gap_ms=150)
    info['n_notes'] = len(segments)

    fig, axes = plt.subplots(2, 1, figsize=(16, 10))

    # Full envelope
    t_env, env = amplitude_envelope(x, sr, hop=256)
    axes[0].plot(t_env, db(env), color='#2196F3', linewidth=0.8)
    axes[0].set_title('Full Recording Envelope')
    axes[0].set_xlabel('Time (s)')
    axes[0].set_ylabel('dBFS')
    axes[0].grid(True, alpha=0.3)

    # Per-note analysis
    note_data = []
    colors = plt.cm.viridis(np.linspace(0.1, 0.9, len(segments)))

    for i, (start, end) in enumerate(segments):
        seg = x[start:end]
        t_seg, env_seg = extract_envelope(seg, sr, hop=128)

        # Normalize envelope
        peak_val = np.max(env_seg)
        if peak_val < 1e-6:
            continue
        env_norm = env_seg / peak_val

        attack_ms = fit_attack(t_seg, env_norm)
        decay_tau, decay_params = fit_decay(t_seg, env_norm)

        note_info = {
            'note_index': i,
            'attack_ms': float(attack_ms) if attack_ms else None,
            'decay_tau_ms': float(decay_tau) if decay_tau else None,
            'peak_amp': float(peak_val),
            'duration_ms': float((end - start) / sr * 1000),
        }
        note_data.append(note_info)

        axes[1].plot(t_seg * 1000, env_norm, color=colors[i], linewidth=1,
                     alpha=0.7, label=f'Note {i}: A={attack_ms:.0f}ms' if attack_ms else f'Note {i}')

    axes[1].set_title('Individual Note Envelopes (normalized)')
    axes[1].set_xlabel('Time (ms)')
    axes[1].set_ylabel('Amplitude (normalized)')
    if len(segments) <= 15:
        axes[1].legend(fontsize=7, ncol=2)
    axes[1].grid(True, alpha=0.3)

    info['notes'] = note_data

    # Summary
    attacks = [n['attack_ms'] for n in note_data if n['attack_ms'] is not None]
    decays = [n['decay_tau_ms'] for n in note_data if n['decay_tau_ms'] is not None]
    summary = f'{len(segments)} notes detected'
    if attacks:
        summary += f' | Attacks: {min(attacks):.0f}–{max(attacks):.0f}ms'
    if decays:
        summary += f' | Decay τ: {min(decays):.0f}–{max(decays):.0f}ms'

    fig.suptitle(f'{label}\n{summary}', fontsize=12, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f'{Path(path).stem}_analysis.png'), dpi=150, bbox_inches='tight')
    plt.close()

    return info


def analyze_filter(path, ref_path, output_dir, label):
    """Tests 8-9, 10-11: Filter analysis."""
    x, sr = load_mono(path)
    info = {'file': os.path.basename(path), 'sr': sr, 'type': 'filter'}

    t, cutoffs, prominences, slopes = track_filter_sweep(x, sr)
    valid = ~np.isnan(cutoffs)

    if np.any(valid):
        info['cutoff_min_hz'] = float(np.nanmin(cutoffs[valid]))
        info['cutoff_max_hz'] = float(np.nanmax(cutoffs[valid]))
        info['mean_resonance_db'] = float(np.nanmean(prominences[valid]))
        info['mean_slope_db_oct'] = float(np.nanmean(slopes[valid]))

    # Spectrogram
    fig, axes = plt.subplots(3, 1, figsize=(16, 14))

    f_sg, t_sg, S_sg = signal.spectrogram(x, sr, nperseg=2048, noverlap=1792, window='hann')
    axes[0].pcolormesh(t_sg, f_sg, 10 * np.log10(S_sg + 1e-10), shading='gouraud', cmap='magma', vmin=-80, vmax=-10)
    axes[0].set_ylim(0, 16000)
    axes[0].set_title('Spectrogram')
    axes[0].set_ylabel('Hz')

    axes[1].plot(t, cutoffs, color='#2196F3', linewidth=1.5)
    axes[1].set_yscale('log')
    axes[1].set_ylim(50, 20000)
    axes[1].set_title('Filter Cutoff Tracking')
    axes[1].set_ylabel('Hz')
    axes[1].grid(True, alpha=0.3, which='both')

    axes[2].plot(t, slopes, color='#2196F3', linewidth=1, alpha=0.8)
    axes[2].axhline(-24, color='gray', linestyle=':', alpha=0.5, label='-24 dB/oct (4-pole)')
    axes[2].axhline(-12, color='gray', linestyle='--', alpha=0.5, label='-12 dB/oct (2-pole)')
    axes[2].set_title('Rolloff Slope')
    axes[2].set_xlabel('Time (s)')
    axes[2].set_ylabel('dB/octave')
    axes[2].legend(fontsize=8)
    axes[2].grid(True, alpha=0.3)

    summary_parts = []
    if 'cutoff_min_hz' in info:
        summary_parts.append(f'Cutoff: {info["cutoff_min_hz"]:.0f}–{info["cutoff_max_hz"]:.0f}Hz')
    if 'mean_resonance_db' in info:
        summary_parts.append(f'Res prominence: {info["mean_resonance_db"]:.1f}dB')
    if 'mean_slope_db_oct' in info:
        summary_parts.append(f'Slope: {info["mean_slope_db_oct"]:.1f}dB/oct')

    fig.suptitle(f'{label}\n{" | ".join(summary_parts)}', fontsize=12, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f'{Path(path).stem}_analysis.png'), dpi=150, bbox_inches='tight')
    plt.close()

    return info


def analyze_noise_floor(path, ref_path, output_dir, label):
    """Test 12: Noise floor."""
    x, sr = load_mono(path)
    info = {'file': os.path.basename(path), 'sr': sr, 'type': 'noise_floor'}

    info['rms_dbfs'] = float(db(rms(x)))
    info['peak_dbfs'] = float(db(np.max(np.abs(x))))

    n_fft = 16384
    freqs, mag = avg_spectrum(x, len(x) // 4, n_fft, 8, sr)

    fig, ax = plt.subplots(1, 1, figsize=(14, 6))
    if freqs is not None:
        ax.plot(freqs, db(mag), color='#2196F3', linewidth=0.7)
        ax.set_xlim(20, sr / 2)
        ax.set_xscale('log')
        ax.set_title(f'{label}\nRMS: {info["rms_dbfs"]:.1f}dBFS | Peak: {info["peak_dbfs"]:.1f}dBFS')
        ax.set_xlabel('Hz')
        ax.set_ylabel('dB')
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f'{Path(path).stem}_analysis.png'), dpi=150, bbox_inches='tight')
    plt.close()

    return info


def analyze_chorus(path, ref_path, output_dir, label):
    """Tests 13-15, 20-21: Chorus analysis."""
    x, sr = load_mono(path)
    info = {'file': os.path.basename(path), 'sr': sr, 'type': 'chorus'}

    info['rms_dbfs'] = float(db(rms(x)))

    # Stereo analysis - chorus creates stereo width
    data, _ = sf.read(path)
    if data.ndim > 1 and data.shape[1] >= 2:
        diff = data[:, 0] - data[:, 1]
        info['stereo_diff_rms'] = float(rms(diff))
        info['lr_correlation'] = float(np.corrcoef(data[:, 0], data[:, 1])[0, 1])

    # Spectral analysis
    onset = find_onset(x, sr)
    ss_start = onset + int(0.3 * sr)
    n_fft = 16384
    freqs, mag = avg_spectrum(x, ss_start, n_fft, 4, sr)

    fig, axes = plt.subplots(2, 1, figsize=(14, 10))

    if freqs is not None:
        axes[0].plot(freqs, db(mag), color='#2196F3', linewidth=0.8)
        axes[0].set_xlim(20, sr / 2)
        axes[0].set_xscale('log')
        axes[0].set_title('Spectrum')
        axes[0].set_xlabel('Hz')
        axes[0].set_ylabel('dB')
        axes[0].grid(True, alpha=0.3)

    # Spectrogram to see modulation
    f_sg, t_sg, S_sg = signal.spectrogram(x, sr, nperseg=4096, noverlap=3584, window='hann')
    axes[1].pcolormesh(t_sg, f_sg, 10 * np.log10(S_sg + 1e-10), shading='gouraud', cmap='magma', vmin=-80, vmax=0)
    axes[1].set_ylim(0, 8000)
    axes[1].set_title('Spectrogram (chorus modulation visible as frequency smearing)')
    axes[1].set_xlabel('Time (s)')
    axes[1].set_ylabel('Hz')

    summary = f'RMS: {info["rms_dbfs"]:.1f}dBFS'
    if 'lr_correlation' in info:
        summary += f' | L/R corr: {info["lr_correlation"]:.3f}'
        summary += f' | Stereo diff RMS: {info["stereo_diff_rms"]:.6f}'

    fig.suptitle(f'{label}\n{summary}', fontsize=12, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f'{Path(path).stem}_analysis.png'), dpi=150, bbox_inches='tight')
    plt.close()

    return info


def analyze_generic(path, ref_path, output_dir, label):
    """Fallback analysis for unrecognized test types."""
    x, sr = load_mono(path)
    info = {'file': os.path.basename(path), 'sr': sr, 'type': 'generic'}

    info['duration_s'] = float(len(x) / sr)
    info['peak_dbfs'] = float(db(np.max(np.abs(x))))
    info['rms_dbfs'] = float(db(rms(x)))

    onset = find_onset(x, sr)
    ss_start = onset + int(0.2 * sr)
    n_fft = 8192
    freqs, mag = avg_spectrum(x, ss_start, n_fft, 4, sr)

    fig, axes = plt.subplots(2, 1, figsize=(14, 8))

    t_axis = np.arange(len(x)) / sr
    axes[0].plot(t_axis, x, color='#2196F3', linewidth=0.3)
    axes[0].set_title('Waveform')
    axes[0].set_xlabel('Time (s)')

    if freqs is not None:
        axes[1].plot(freqs, db(mag), color='#2196F3', linewidth=0.8)
        axes[1].set_xlim(20, sr / 2)
        axes[1].set_xscale('log')
        axes[1].set_title('Spectrum')
        axes[1].set_xlabel('Hz')
        axes[1].set_ylabel('dB')
        axes[1].grid(True, alpha=0.3)

    fig.suptitle(f'{label}\nDur: {info["duration_s"]:.1f}s | Peak: {info["peak_dbfs"]:.1f}dBFS | '
                 f'RMS: {info["rms_dbfs"]:.1f}dBFS', fontsize=12, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f'{Path(path).stem}_analysis.png'), dpi=150, bbox_inches='tight')
    plt.close()

    return info


# ============================================================
# Test routing
# ============================================================

def classify_test(filename):
    """Determine test type from filename."""
    fname = filename.lower()

    # Try to extract leading number
    num = None
    base = os.path.splitext(os.path.basename(fname))[0]
    parts = base.split('-', 1)
    if parts[0].isdigit():
        num = int(parts[0])

    # Route by number
    if num is not None:
        if num in (1, 2, 3, 4):
            return 'oscillator'
        if num in (5, 6, 7):
            return 'envelope'
        if num in (8, 9):
            return 'filter'
        if num in (10, 11):
            return 'filter'
        if num == 12:
            return 'noise_floor'
        if num in (13, 14, 15, 20, 21):
            return 'chorus'
        if num in (16, 17):
            return 'oscillator'
        if num in (18, 19):
            return 'filter'

    # Route by keywords
    for kw in ['saw', 'square', 'sub', 'osc', 'pwm', 'mixer']:
        if kw in fname:
            return 'oscillator'
    for kw in ['env', 'adsr', 'attack', 'decay', 'release']:
        if kw in fname:
            return 'envelope'
    for kw in ['filter', 'cutoff', 'sweep', 'res', 'self-osc', 'keyboard']:
        if kw in fname:
            return 'filter'
    for kw in ['noise-floor', 'silence']:
        if kw in fname:
            return 'noise_floor'
    for kw in ['chorus']:
        if kw in fname:
            return 'chorus'
    for kw in ['preset', 'factory', 'patch']:
        if kw in fname:
            return 'generic'

    return 'generic'


ANALYZERS = {
    'oscillator': analyze_oscillator,
    'envelope': analyze_envelope,
    'filter': analyze_filter,
    'noise_floor': analyze_noise_floor,
    'chorus': analyze_chorus,
    'generic': analyze_generic,
}


# ============================================================
# Report generation
# ============================================================

def generate_report(results, output_dir):
    """Write a plain text summary report."""
    report_path = os.path.join(output_dir, 'analysis_report.txt')
    with open(report_path, 'w') as f:
        f.write("Juno-106 Recording Analysis Report\n")
        f.write("=" * 50 + "\n\n")

        for r in results:
            f.write(f"--- {r['file']} ({r['type']}) ---\n")
            f.write(f"  Sample rate: {r['sr']} Hz\n")

            if r['type'] == 'oscillator':
                if 'fundamental_hz' in r:
                    f.write(f"  Fundamental: {r['fundamental_hz']:.2f} Hz\n")
                if 'spectral_centroid_hz' in r:
                    f.write(f"  Spectral centroid: {r['spectral_centroid_hz']:.0f} Hz\n")
                if 'peak_dbfs' in r:
                    f.write(f"  Peak: {r['peak_dbfs']:.1f} dBFS, RMS: {r['rms_dbfs']:.1f} dBFS\n")
                if 'mean_harmonic_error_db' in r:
                    f.write(f"  Mean harmonic error (H1-H20): {r['mean_harmonic_error_db']:.1f} dB\n")
                if 'asymmetry' in r:
                    f.write(f"  Waveform asymmetry: {r['asymmetry']:.3f} (1.0 = symmetric)\n")
                if 'overshoot_pct' in r:
                    f.write(f"  Gibbs/blip overshoot: {r['overshoot_pct']:.1f}%\n")

            elif r['type'] == 'envelope':
                f.write(f"  Notes detected: {r.get('n_notes', '?')}\n")
                if 'notes' in r:
                    for n in r['notes']:
                        parts = [f"  Note {n['note_index']}:"]
                        if n['attack_ms'] is not None:
                            parts.append(f"A={n['attack_ms']:.1f}ms")
                        if n['decay_tau_ms'] is not None:
                            parts.append(f"D(τ)={n['decay_tau_ms']:.1f}ms")
                        parts.append(f"dur={n['duration_ms']:.0f}ms")
                        f.write(' '.join(parts) + '\n')

            elif r['type'] == 'filter':
                if 'cutoff_min_hz' in r:
                    f.write(f"  Cutoff range: {r['cutoff_min_hz']:.0f}–{r['cutoff_max_hz']:.0f} Hz\n")
                if 'mean_resonance_db' in r:
                    f.write(f"  Mean resonance: {r['mean_resonance_db']:.1f} dB\n")
                if 'mean_slope_db_oct' in r:
                    f.write(f"  Mean rolloff: {r['mean_slope_db_oct']:.1f} dB/oct\n")

            elif r['type'] == 'noise_floor':
                f.write(f"  RMS: {r.get('rms_dbfs', '?')} dBFS\n")
                f.write(f"  Peak: {r.get('peak_dbfs', '?')} dBFS\n")

            elif r['type'] == 'chorus':
                if 'lr_correlation' in r:
                    f.write(f"  L/R correlation: {r['lr_correlation']:.4f}\n")
                if 'stereo_diff_rms' in r:
                    f.write(f"  Stereo diff RMS: {r['stereo_diff_rms']:.6f}\n")

            f.write('\n')

    print(f"\nReport written to {report_path}")
    return report_path


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='Juno-106 Test Recording Analyzer')
    parser.add_argument('input', help='Folder containing WAV recordings')
    parser.add_argument('--output', '-o', default=None, help='Output folder (default: <input>/analysis)')
    parser.add_argument('--reference', '-r', default=None, help='Folder with reference WAVs from your engine')
    args = parser.parse_args()

    input_dir = args.input
    output_dir = args.output or os.path.join(input_dir, 'analysis')
    ref_dir = args.reference

    os.makedirs(output_dir, exist_ok=True)

    wav_files = sorted(glob.glob(os.path.join(input_dir, '*.wav')))
    if not wav_files:
        print(f"No WAV files found in {input_dir}")
        sys.exit(1)

    print(f"Found {len(wav_files)} WAV files in {input_dir}")
    if ref_dir:
        print(f"Reference folder: {ref_dir}")
    print(f"Output: {output_dir}\n")

    results = []
    for path in wav_files:
        fname = os.path.basename(path)
        test_type = classify_test(fname)
        label = f'{fname} [{test_type}]'
        print(f"Analyzing: {fname} -> {test_type}")

        ref_path = None
        if ref_dir:
            ref_candidate = os.path.join(ref_dir, fname)
            if os.path.exists(ref_candidate):
                ref_path = ref_candidate

        analyzer = ANALYZERS.get(test_type, analyze_generic)
        try:
            info = analyzer(path, ref_path, output_dir, label)
            results.append(info)
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({'file': fname, 'type': test_type, 'error': str(e)})

    # Save JSON data
    json_path = os.path.join(output_dir, 'analysis_data.json')
    with open(json_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nRaw data saved to {json_path}")

    # Generate report
    generate_report(results, output_dir)

    print(f"\nDone. {len(results)} files analyzed.")
    print(f"Plots saved to {output_dir}/")


if __name__ == '__main__':
    main()
