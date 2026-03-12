#!/usr/bin/env python3
"""
Combined Decay + Release Analyzer
===================================
For recordings where each note has:
  1. Attack (fast) → Peak
  2. Decay → Sustain (held)
  3. Release → Silence

Splits each note into decay and release portions, fits both.

Usage:
    python analyze_decay_release.py recording.wav [slider_start] [slider_step]

Recording setup:
    Attack=0, Sustain=~0.5, vary Decay+Release together (same slider).
    Hold each note ~2-3s at sustain, then release and let ring to silence.

Outputs:
    dr_analysis.png     — per-note envelope plots with fits
    dr_mapping.png      — slider → time curves
    dr_mapping.csv      — data
    dr_report.txt       — summary
"""
import sys
import numpy as np
import soundfile as sf
import scipy.fft as fft
from scipy.optimize import curve_fit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def extract_envelope(x, sr, hop=64):
    """RMS envelope."""
    n_frames = len(x) // hop
    env = np.zeros(n_frames)
    for i in range(n_frames):
        frame = x[i*hop:(i+1)*hop]
        env[i] = np.sqrt(np.mean(frame**2))
    win = np.hanning(9)
    win /= win.sum()
    env = np.convolve(env, win, mode='same')
    return env, hop


def find_notes(env, sr, hop, min_gap_s=0.3, min_dur_s=0.5):
    """Find note boundaries including full release tail."""
    env_db = 20 * np.log10(env + 1e-10)
    pk = np.max(env_db)
    thresh = pk - 50  # very low to catch release tails
    above = env_db > thresh
    trans = np.diff(above.astype(int))
    raw_starts = list(np.where(trans == 1)[0])
    raw_ends = list(np.where(trans == -1)[0])
    if not raw_starts:
        return []
    starts, ends = [raw_starts[0]], []
    for i in range(1, len(raw_starts)):
        pe = raw_ends[i-1] if i-1 < len(raw_ends) else raw_starts[i]-1
        gap_s = (raw_starts[i] - pe) * hop / sr
        if gap_s < min_gap_s:
            continue
        ends.append(raw_ends[i-1])
        starts.append(raw_starts[i])
    ends.append(raw_ends[-1] if raw_ends else len(env)-1)
    notes = []
    for s, e in zip(starts, ends):
        dur = (e - s) * hop / sr
        if dur >= min_dur_s:
            notes.append((s, e))
    return notes


def find_sustain_and_release(env_norm, hop, sr):
    """
    Find the sustain region and release point in a normalized envelope.
    Returns (sustain_level, sustain_start, release_point) as frame indices.
    """
    n = len(env_norm)

    # Find peak
    peak_idx = np.argmax(env_norm)

    # Scan forward from peak to find where envelope settles (derivative near zero)
    # Use a sliding window to detect the sustain plateau
    win_size = max(10, int(0.05 * sr / hop))  # 50ms window

    # Compute local derivative magnitude
    deriv = np.abs(np.diff(env_norm))
    smooth_deriv = np.convolve(deriv, np.ones(win_size)/win_size, mode='same')

    # Find sustain: region after peak where derivative is low
    # Start searching after the initial decay
    search_start = peak_idx + max(5, int(0.02 * sr / hop))

    # Find the sustain level by looking for the most common amplitude
    # in the second half of the note
    mid = (search_start + n) // 2
    if mid >= n:
        mid = search_start + (n - search_start) // 2

    # Histogram approach: find the mode of the envelope in the middle section
    middle_section = env_norm[mid:int(n * 0.9)]
    if len(middle_section) < 10:
        middle_section = env_norm[search_start:]

    if len(middle_section) < 5:
        return None, None, None

    # Estimate sustain as median of the middle section
    sustain_est = np.median(middle_section)

    # Find where envelope first settles within 10% of sustain estimate
    sustain_start = search_start
    for i in range(search_start, n):
        if abs(env_norm[i] - sustain_est) < sustain_est * 0.15:
            sustain_start = i
            break

    # Find release point: where envelope drops below sustain - 15%
    # Search from the end backwards to find where it was still at sustain
    release_point = n - 1
    threshold = sustain_est * 0.80

    # Walk backward from end to find where it was still near sustain
    for i in range(n - 1, sustain_start, -1):
        if env_norm[i] >= threshold:
            release_point = i
            break

    # Refine: walk forward from release_point to find the actual drop
    for i in range(release_point, min(release_point + int(0.5 * sr / hop), n)):
        if env_norm[i] < threshold:
            release_point = i
            break

    # Recalculate sustain level from the plateau region
    plateau = env_norm[sustain_start:release_point]
    if len(plateau) > 5:
        sustain_level = np.median(plateau)
    else:
        sustain_level = sustain_est

    return sustain_level, sustain_start, release_point


def fit_decay(t, env, target=0):
    """Fit exponential decay toward target. Returns (tau, fitted, fit_name, rms)."""
    fits = {}

    # exp(-t/tau) scaled to start at env[0] and approach target
    amp = env[0] - target

    def exp_d(t, tau):
        return amp * np.exp(-t / max(tau, 1e-6)) + target

    def exp_power_d(t, tau, power):
        return amp * np.exp(-np.power(t / max(tau, 1e-6), max(power, 0.1))) + target

    try:
        tau_g = t[len(t)//3] if len(t) > 3 else 0.1
        popt, _ = curve_fit(exp_d, t, env, p0=[tau_g], bounds=([1e-5], [30]), maxfev=5000)
        fitted = exp_d(t, *popt)
        rms = np.sqrt(np.mean((env - fitted)**2)) / (amp + 1e-10)
        fits['exp'] = (popt[0], fitted, rms, f'exp (τ={popt[0]*1000:.0f}ms)')
    except:
        pass

    try:
        tau_g = t[len(t)//3] if len(t) > 3 else 0.1
        popt, _ = curve_fit(exp_power_d, t, env, p0=[tau_g, 1.0],
                            bounds=([1e-5, 0.1], [30, 5.0]), maxfev=5000)
        fitted = exp_power_d(t, *popt)
        rms = np.sqrt(np.mean((env - fitted)**2)) / (amp + 1e-10)
        fits['exp_power'] = (popt[0], fitted, rms,
                             f'exp^p (τ={popt[0]*1000:.0f}ms, p={popt[1]:.2f})')
    except:
        pass

    if not fits:
        return None, None, None, None, None

    best_name = min(fits, key=lambda k: fits[k][2])
    tau, fitted, rms, label = fits[best_name]

    power = None
    if best_name == 'exp_power' and 'exp_power' in fits:
        # Get power from the fit
        try:
            tau_g = t[len(t)//3] if len(t) > 3 else 0.1
            popt, _ = curve_fit(exp_power_d, t, env, p0=[tau_g, 1.0],
                                bounds=([1e-5, 0.1], [30, 5.0]), maxfev=5000)
            power = popt[1]
        except:
            pass

    return tau, fitted, best_name, label, power


def analyze_note(env, sr, hop, ns, ne):
    """Analyze one note: extract decay and release portions."""
    seg = env[ns:ne]
    t = np.arange(len(seg)) * hop / sr
    peak_idx = np.argmax(seg)
    peak_val = seg[peak_idx]

    if peak_val < 1e-8:
        return None

    env_norm = seg / peak_val

    sustain_level, sustain_start, release_point = find_sustain_and_release(env_norm, hop, sr)

    if sustain_level is None or sustain_start is None or release_point is None:
        return None

    # --- DECAY portion: from peak to sustain ---
    decay_seg = env_norm[peak_idx:sustain_start]
    decay_t = t[peak_idx:sustain_start] - t[peak_idx]

    decay_tau, decay_fitted, decay_fit_name, decay_label, decay_power = None, None, None, None, None
    decay_90_10 = None
    if len(decay_t) > 5:
        decay_tau, decay_fitted, decay_fit_name, decay_label, decay_power = \
            fit_decay(decay_t, decay_seg, target=sustain_level)

        # 90%→10% of the decay range
        decay_range = 1.0 - sustain_level
        thresh_90 = 1.0 - 0.1 * decay_range
        thresh_10 = sustain_level + 0.1 * decay_range
        t90, t10 = None, None
        for i, v in enumerate(decay_seg):
            if v <= thresh_90 and t90 is None:
                t90 = decay_t[i]
            if v <= thresh_10 and t10 is None:
                t10 = decay_t[i]
                break
        if t90 is not None and t10 is not None:
            decay_90_10 = (t10 - t90) * 1000

    # --- RELEASE portion: from release point to silence ---
    release_seg = env_norm[release_point:]
    release_t = t[release_point:release_point+len(release_seg)] - t[release_point]

    release_tau, release_fitted, release_fit_name, release_label, release_power = None, None, None, None, None
    release_90_10 = None
    if len(release_t) > 5:
        release_start_val = release_seg[0]
        # Normalize release to start at 1.0
        if release_start_val > 0.01:
            release_norm = release_seg / release_start_val
            release_tau, release_fitted, release_fit_name, release_label, release_power = \
                fit_decay(release_t, release_norm, target=0)
            # Scale fitted back
            if release_fitted is not None:
                release_fitted = release_fitted * release_start_val

            # 90%→10%
            t90, t10 = None, None
            for i, v in enumerate(release_norm):
                if v <= 0.9 and t90 is None:
                    t90 = release_t[i]
                if v <= 0.1 and t10 is None:
                    t10 = release_t[i]
                    break
            if t90 is not None and t10 is not None:
                release_90_10 = (t10 - t90) * 1000

    return {
        'env_norm': env_norm,
        'time_ms': t * 1000,
        'peak_idx': peak_idx,
        'sustain_level': sustain_level,
        'sustain_start': sustain_start,
        'release_point': release_point,
        # Decay
        'decay_tau_ms': decay_tau * 1000 if decay_tau else None,
        'decay_90_10_ms': decay_90_10,
        'decay_fitted': decay_fitted,
        'decay_t_ms': decay_t * 1000 if len(decay_t) > 0 else None,
        'decay_seg': decay_seg if len(decay_seg) > 0 else None,
        'decay_fit': decay_fit_name,
        'decay_label': decay_label,
        'decay_power': decay_power,
        # Release
        'release_tau_ms': release_tau * 1000 if release_tau else None,
        'release_90_10_ms': release_90_10,
        'release_fitted': release_fitted,
        'release_t_ms': release_t * 1000 if len(release_t) > 0 else None,
        'release_seg': release_seg if len(release_seg) > 0 else None,
        'release_fit': release_fit_name,
        'release_label': release_label,
        'release_power': release_power,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_decay_release.py <recording.wav> [slider_start] [slider_step]")
        sys.exit(1)

    path = sys.argv[1]
    slider_start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    slider_step = int(sys.argv[3]) if len(sys.argv) > 3 else 1

    x, sr = sf.read(path)
    if x.ndim > 1:
        x = x.mean(axis=1)
    print(f"Loaded: {len(x)/sr:.2f}s @ {sr}Hz")

    env, hop = extract_envelope(x, sr)
    notes = find_notes(env, sr, hop)
    print(f"Found {len(notes)} notes")

    results = []
    for i, (ns, ne) in enumerate(notes):
        slider = slider_start + i * slider_step
        r = analyze_note(env, sr, hop, ns, ne)
        if r is None:
            print(f"  Note {i+1} (slider {slider}): analysis failed, skipping")
            continue
        r['slider'] = slider
        r['note_idx'] = i + 1
        results.append(r)

        dt = f"{r['decay_tau_ms']:.0f}ms" if r['decay_tau_ms'] else "n/a"
        rt = f"{r['release_tau_ms']:.0f}ms" if r['release_tau_ms'] else "n/a"
        d90 = f"{r['decay_90_10_ms']:.0f}ms" if r['decay_90_10_ms'] else "n/a"
        r90 = f"{r['release_90_10_ms']:.0f}ms" if r['release_90_10_ms'] else "n/a"
        sus = f"{r['sustain_level']:.2f}"
        print(f"  Note {i+1} (slider {slider}): sus={sus} | decay τ={dt} 90-10={d90} | release τ={rt} 90-10={r90}")

    if not results:
        print("No usable notes found!")
        sys.exit(1)

    # ===== PLOT 1: Per-note envelopes =====
    n = len(results)
    cols = min(3, n)
    rows = max(1, (n + cols - 1) // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(6*cols, 4*rows), squeeze=False)
    af = axes.flatten()

    for i, r in enumerate(results):
        ax = af[i]
        # Full envelope
        ax.plot(r['time_ms'], r['env_norm'], '#2196F3', linewidth=1, alpha=0.8, label='Envelope')

        # Mark regions
        t_sus_start = r['time_ms'][r['sustain_start']]
        t_rel = r['time_ms'][r['release_point']]
        ax.axvline(t_sus_start, color='green', linewidth=0.8, linestyle=':', alpha=0.6, label='Sustain start')
        ax.axvline(t_rel, color='red', linewidth=0.8, linestyle=':', alpha=0.6, label='Release')
        ax.axhline(r['sustain_level'], color='gray', linewidth=0.5, linestyle='--', alpha=0.5)

        # Overlay decay fit
        if r['decay_fitted'] is not None and r['decay_t_ms'] is not None:
            offset = r['time_ms'][r['peak_idx']]
            ax.plot(r['decay_t_ms'] + offset, r['decay_fitted'],
                    '--', color='#FF5722', linewidth=1.5, alpha=0.7,
                    label=r['decay_label'])

        # Overlay release fit
        if r['release_fitted'] is not None and r['release_t_ms'] is not None:
            ax.plot(r['release_t_ms'] + t_rel, r['release_fitted'],
                    '--', color='#9C27B0', linewidth=1.5, alpha=0.7,
                    label=r['release_label'])

        d_str = f"D:{r['decay_tau_ms']:.0f}" if r['decay_tau_ms'] else "D:n/a"
        r_str = f"R:{r['release_tau_ms']:.0f}" if r['release_tau_ms'] else "R:n/a"
        ax.set_title(f"Slider {r['slider']} ({d_str} / {r_str}ms)")
        ax.set_xlabel('ms')
        ax.set_ylabel('Amplitude')
        ax.set_ylim(-0.05, 1.15)
        ax.grid(True, alpha=0.3)
        if i == 0:
            ax.legend(fontsize=5, loc='upper right')

    for i in range(n, len(af)):
        af[i].set_visible(False)

    fig.suptitle('Decay + Release Envelopes', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig('dr_analysis.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nSaved: dr_analysis.png")

    # ===== PLOT 2: Mapping =====
    sliders = [r['slider'] for r in results]
    d_taus = [r['decay_tau_ms'] if r['decay_tau_ms'] else 0 for r in results]
    r_taus = [r['release_tau_ms'] if r['release_tau_ms'] else 0 for r in results]

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    axes[0].plot(sliders, d_taus, 'o-', color='#2196F3', markersize=6, linewidth=1.5, label='Decay τ')
    axes[0].plot(sliders, r_taus, 's--', color='#FF5722', markersize=5, linewidth=1, label='Release τ')
    axes[0].set_xlabel('Slider')
    axes[0].set_ylabel('τ (ms)')
    axes[0].set_title('Linear')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].semilogy(sliders, [max(t, 0.1) for t in d_taus], 'o-', color='#2196F3',
                     markersize=6, linewidth=1.5, label='Decay τ')
    axes[1].semilogy(sliders, [max(t, 0.1) for t in r_taus], 's--', color='#FF5722',
                     markersize=5, linewidth=1, label='Release τ')
    axes[1].set_xlabel('Slider')
    axes[1].set_ylabel('τ (ms)')
    axes[1].set_title('Log')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3, which='both')

    fig.suptitle('Decay vs Release τ — Same Slider Setting', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig('dr_mapping.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: dr_mapping.png")

    # ===== CSV =====
    with open('dr_mapping.csv', 'w') as f:
        f.write('slider,sustain,decay_tau_ms,decay_90_10_ms,decay_fit,decay_power,release_tau_ms,release_90_10_ms,release_fit,release_power\n')
        for r in results:
            dt = f"{r['decay_tau_ms']:.2f}" if r['decay_tau_ms'] else ""
            d90 = f"{r['decay_90_10_ms']:.2f}" if r['decay_90_10_ms'] else ""
            dp = f"{r['decay_power']:.3f}" if r['decay_power'] else ""
            rt = f"{r['release_tau_ms']:.2f}" if r['release_tau_ms'] else ""
            r90 = f"{r['release_90_10_ms']:.2f}" if r['release_90_10_ms'] else ""
            rp = f"{r['release_power']:.3f}" if r['release_power'] else ""
            f.write(f"{r['slider']},{r['sustain_level']:.4f},{dt},{d90},{r['decay_fit']},{dp},{rt},{r90},{r['release_fit']},{rp}\n")
    print(f"Saved: dr_mapping.csv")

    # ===== Report =====
    with open('dr_report.txt', 'w') as f:
        f.write("Decay + Release Analysis Report\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Source: {path}\n")
        f.write(f"Sample rate: {sr}Hz\n")
        f.write(f"Notes analyzed: {len(results)}\n\n")

        f.write(f"{'Slider':>8} {'Sustain':>8} {'D τ':>10} {'D 90-10':>10} {'D fit':>10} {'R τ':>10} {'R 90-10':>10} {'R fit':>10} {'D≈R?':>6}\n")
        f.write(f"{'------':>8} {'-------':>8} {'----':>10} {'-------':>10} {'-----':>10} {'----':>10} {'-------':>10} {'-----':>10} {'----':>6}\n")
        for r in results:
            dt = f"{r['decay_tau_ms']:.0f}" if r['decay_tau_ms'] else "—"
            d90 = f"{r['decay_90_10_ms']:.0f}" if r['decay_90_10_ms'] else "—"
            rt = f"{r['release_tau_ms']:.0f}" if r['release_tau_ms'] else "—"
            r90 = f"{r['release_90_10_ms']:.0f}" if r['release_90_10_ms'] else "—"
            # Check if decay ≈ release
            match = ""
            if r['decay_tau_ms'] and r['release_tau_ms']:
                ratio = r['decay_tau_ms'] / r['release_tau_ms']
                match = "YES" if 0.7 < ratio < 1.3 else f"{ratio:.1f}x"
            f.write(f"{r['slider']:>8} {r['sustain_level']:>8.2f} {dt:>10} {d90:>10} {str(r['decay_fit']):>10} {rt:>10} {r90:>10} {str(r['release_fit']):>10} {match:>6}\n")

        # Power exponents
        d_powers = [r['decay_power'] for r in results if r['decay_power'] is not None]
        r_powers = [r['release_power'] for r in results if r['release_power'] is not None]
        if d_powers:
            f.write(f"\nDecay power exponents: {', '.join(f'{p:.2f}' for p in d_powers)}")
            f.write(f" (mean: {np.mean(d_powers):.2f})\n")
        if r_powers:
            f.write(f"Release power exponents: {', '.join(f'{p:.2f}' for p in r_powers)}")
            f.write(f" (mean: {np.mean(r_powers):.2f})\n")

    print(f"Saved: dr_report.txt")

    # Summary
    print(f"\n{'Slider':>8} {'Sustain':>8} {'Decay τ':>10} {'Release τ':>10} {'Match':>8}")
    print(f"{'------':>8} {'-------':>8} {'-------':>10} {'---------':>10} {'-----':>8}")
    for r in results:
        dt = f"{r['decay_tau_ms']:.0f}ms" if r['decay_tau_ms'] else "n/a"
        rt = f"{r['release_tau_ms']:.0f}ms" if r['release_tau_ms'] else "n/a"
        match = ""
        if r['decay_tau_ms'] and r['release_tau_ms']:
            ratio = r['decay_tau_ms'] / r['release_tau_ms']
            match = "≈" if 0.7 < ratio < 1.3 else f"{ratio:.1f}x"
        print(f"{r['slider']:>8} {r['sustain_level']:>8.2f} {dt:>10} {rt:>10} {match:>8}")


if __name__ == '__main__':
    main()
