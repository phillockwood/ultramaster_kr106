#!/usr/bin/env python3
"""
Decay/Release Envelope Analyzer
================================
Measures ADSR decay (or release) time and curve shape.

For DECAY:  Set attack=0, sustain=0, release=max. Vary decay slider.
            Each note spikes to peak then decays to silence while held.
            Hold each note long enough for full decay.

For RELEASE: Set attack=0, decay=0, sustain=max. Vary release slider.
             Play short staccato notes — the release tail is what we measure.
             Leave enough silence after each for full release.

Usage:
    python analyze_decay.py hw_decay_sweep.wav [slider_start] [slider_step]
    python analyze_decay.py hw_release_sweep.wav 0 1

Outputs:
    decay_analysis.png   — per-note envelope plots with fits
    decay_mapping.png    — slider → time curve
    decay_mapping.csv    — data
    decay_report.txt     — summary
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
    win = np.hanning(7)
    win /= win.sum()
    env = np.convolve(env, win, mode='same')
    return env, hop


def find_notes(env, sr, hop, min_gap_s=0.15, min_dur_s=0.1):
    """Find note boundaries including the decay/release tail."""
    env_db = 20 * np.log10(env + 1e-10)
    pk = np.max(env_db)
    # Use a low threshold to catch the full decay tail
    thresh = pk - 45
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


def measure_decay(env, sr, hop, note_start, note_end):
    """
    Measure decay/release from peak to silence.

    Returns dict with timing, fitted tau, curve shape.
    """
    seg = env[note_start:note_end]
    t = np.arange(len(seg)) * hop / sr

    # Find peak
    peak_idx = np.argmax(seg)
    peak_val = seg[peak_idx]

    if peak_val < 1e-8:
        return None

    # Decay portion: from peak onward
    decay_seg = seg[peak_idx:]
    decay_t = t[peak_idx:] - t[peak_idx]

    if len(decay_t) < 5:
        return None

    # Normalize: 1.0 = peak, 0.0 = silence
    decay_norm = decay_seg / peak_val

    # Find the sustain floor (minimum in last 20% of note, or noise floor)
    tail = decay_norm[int(len(decay_norm) * 0.8):]
    sustain_floor = np.mean(tail) if len(tail) > 0 else 0

    # Measure 90%→10% decay time (inverse of attack's 10%→90%)
    t90, t10 = None, None
    for i, v in enumerate(decay_norm):
        if v <= 0.9 and t90 is None:
            t90 = decay_t[i]
        if v <= 0.1 and t10 is None:
            t10 = decay_t[i]
            break

    # 95%→5%
    t95, t5 = None, None
    for i, v in enumerate(decay_norm):
        if v <= 0.95 and t95 is None:
            t95 = decay_t[i]
        if v <= 0.05 and t5 is None:
            t5 = decay_t[i]
            break

    decay_90_10 = (t10 - t90) * 1000 if (t90 is not None and t10 is not None) else None
    decay_95_5 = (t5 - t95) * 1000 if (t95 is not None and t5 is not None) else None

    # Time to reach -20dB (10% of peak)
    t_20dB = t10 * 1000 if t10 is not None else None

    # Time to reach -40dB (1% of peak)
    t_40dB = None
    for i, v in enumerate(decay_norm):
        if v <= 0.01:
            t_40dB = decay_t[i] * 1000
            break

    # ===== Fit models =====
    fits = {}
    best_fit = None
    best_rms = 1e6

    # Trim to the active decay region (above noise floor)
    active = decay_norm > max(sustain_floor + 0.01, 0.02)
    if np.sum(active) < 5:
        active = np.ones(len(decay_norm), dtype=bool)
        active[0] = True  # at least include peak

    fit_t = decay_t[active]
    fit_env = decay_norm[active]

    if len(fit_t) < 4:
        return None

    # Model 1: Simple exponential decay: exp(-t/tau)
    def exp_decay(t, tau):
        return np.exp(-t / max(tau, 1e-6))

    try:
        tau_guess = fit_t[len(fit_t)//2] if len(fit_t) > 0 else 0.1
        popt, _ = curve_fit(exp_decay, fit_t, fit_env, p0=[tau_guess],
                            bounds=([1e-5], [30]), maxfev=5000)
        fitted = exp_decay(fit_t, *popt)
        rms = np.sqrt(np.mean((fit_env - fitted)**2))
        fits['exp'] = {'params': popt, 'rms': rms,
                       'fitted_t': fit_t, 'fitted_v': fitted,
                       'label': f'exp (τ={popt[0]*1000:.1f}ms)'}
        if rms < best_rms:
            best_rms = rms
            best_fit = 'exp'
    except:
        pass

    # Model 2: Exponential with offset: a*exp(-t/tau) + offset
    def exp_decay_off(t, tau, amp, offset):
        return amp * np.exp(-t / max(tau, 1e-6)) + offset

    try:
        tau_guess = fit_t[len(fit_t)//2] if len(fit_t) > 0 else 0.1
        popt, _ = curve_fit(exp_decay_off, fit_t, fit_env,
                            p0=[tau_guess, 1.0, 0.0],
                            bounds=([1e-5, 0.1, -0.2], [30, 2.0, 0.5]),
                            maxfev=5000)
        fitted = exp_decay_off(fit_t, *popt)
        rms = np.sqrt(np.mean((fit_env - fitted)**2))
        fits['exp_off'] = {'params': popt, 'rms': rms,
                           'fitted_t': fit_t, 'fitted_v': fitted,
                           'label': f'exp+off (τ={popt[0]*1000:.1f}ms, off={popt[2]:.2f})'}
        if rms < best_rms:
            best_rms = rms
            best_fit = 'exp_off'
    except:
        pass

    # Model 3: Exponential with power: exp(-(t/tau)^p)
    def exp_power(t, tau, power):
        return np.exp(-np.power(t / max(tau, 1e-6), max(power, 0.1)))

    try:
        tau_guess = fit_t[len(fit_t)//2] if len(fit_t) > 0 else 0.1
        popt, _ = curve_fit(exp_power, fit_t, fit_env,
                            p0=[tau_guess, 1.0],
                            bounds=([1e-5, 0.1], [30, 5.0]),
                            maxfev=5000)
        fitted = exp_power(fit_t, *popt)
        rms = np.sqrt(np.mean((fit_env - fitted)**2))
        fits['exp_power'] = {'params': popt, 'rms': rms,
                             'fitted_t': fit_t, 'fitted_v': fitted,
                             'label': f'exp^p (τ={popt[0]*1000:.1f}ms, p={popt[1]:.2f})'}
        if rms < best_rms:
            best_rms = rms
            best_fit = 'exp_power'
    except:
        pass

    tau_ms = None
    if best_fit == 'exp' and 'exp' in fits:
        tau_ms = fits['exp']['params'][0] * 1000
    elif best_fit == 'exp_off' and 'exp_off' in fits:
        tau_ms = fits['exp_off']['params'][0] * 1000
    elif best_fit == 'exp_power' and 'exp_power' in fits:
        tau_ms = fits['exp_power']['params'][0] * 1000

    return {
        'decay_90_10_ms': decay_90_10,
        'decay_95_5_ms': decay_95_5,
        't_20dB_ms': t_20dB,
        't_40dB_ms': t_40dB,
        'tau_ms': tau_ms,
        'best_fit': best_fit,
        'fits': fits,
        'peak_val': peak_val,
        'sustain_floor': sustain_floor,
        'decay_time_ms': decay_t * 1000,
        'decay_norm': decay_norm,
        'full_time_ms': t * 1000,
        'full_norm': seg / peak_val,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_decay.py <recording.wav> [slider_start] [slider_step]")
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
        r = measure_decay(env, sr, hop, ns, ne)
        if r is None:
            print(f"  Note {i+1} (slider {slider}): failed, skipping")
            continue
        r['slider'] = slider
        r['note_idx'] = i + 1
        results.append(r)

        d = r['decay_90_10_ms']
        tau = r['tau_ms']
        fit = r['best_fit']
        d_str = f"{d:.1f}ms" if d else "n/a"
        tau_str = f"{tau:.1f}ms" if tau else "n/a"
        print(f"  Note {i+1} (slider {slider}): 90-10% = {d_str}, τ = {tau_str}, fit: {fit}")

    if not results:
        print("No usable notes found!")
        sys.exit(1)

    # ===== PLOT 1: Per-note decay envelopes =====
    n = len(results)
    cols = min(4, n)
    rows = max(1, (n + cols - 1) // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(5*cols, 4*rows), squeeze=False)
    af = axes.flatten()

    fit_colors = {'exp': '#4CAF50', 'exp_off': '#FF5722', 'exp_power': '#9C27B0'}

    for i, r in enumerate(results):
        ax = af[i]
        ax.plot(r['decay_time_ms'], r['decay_norm'], '#2196F3', linewidth=1.5, label='Measured')

        for fname, fdata in r['fits'].items():
            ax.plot(fdata['fitted_t'] * 1000, fdata['fitted_v'], '--',
                    color=fit_colors.get(fname, 'gray'), linewidth=1.2, alpha=0.7,
                    label=fdata['label'])

        ax.axhline(0.1, color='gray', linewidth=0.3, linestyle=':')
        ax.axhline(0.9, color='gray', linewidth=0.3, linestyle=':')

        d_str = f"{r['decay_90_10_ms']:.0f}ms" if r['decay_90_10_ms'] else "n/a"
        ax.set_title(f"Slider {r['slider']} ({d_str})")
        ax.set_xlabel('ms')
        ax.set_ylabel('Amplitude (norm)')
        ax.set_ylim(-0.05, 1.2)
        ax.grid(True, alpha=0.3)
        if i == 0:
            ax.legend(fontsize=6)

    for i in range(n, len(af)):
        af[i].set_visible(False)

    fig.suptitle('Decay Envelopes — Per Slider Position', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig('decay_analysis.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nSaved: decay_analysis.png")

    # ===== PLOT 2: Mapping =====
    sliders = [r['slider'] for r in results]
    decay_times = [r['decay_90_10_ms'] if r['decay_90_10_ms'] else 0 for r in results]
    taus = [r['tau_ms'] if r['tau_ms'] else 0 for r in results]

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    axes[0].plot(sliders, decay_times, 'o-', color='#2196F3', markersize=6, linewidth=1.5,
                 label='90%–10% time')
    axes[0].plot(sliders, taus, 's--', color='#FF5722', markersize=5, linewidth=1, label='τ')
    axes[0].set_xlabel('Slider Position')
    axes[0].set_ylabel('Time (ms)')
    axes[0].set_title('Decay Time vs Slider (linear)')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].semilogy(sliders, [max(t, 0.1) for t in decay_times], 'o-', color='#2196F3',
                     markersize=6, linewidth=1.5, label='90%–10% time')
    axes[1].semilogy(sliders, [max(t, 0.1) for t in taus], 's--', color='#FF5722',
                     markersize=5, linewidth=1, label='τ')
    axes[1].set_xlabel('Slider Position')
    axes[1].set_ylabel('Time (ms)')
    axes[1].set_title('Decay Time vs Slider (log)')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3, which='both')

    fig.suptitle('Slider → Decay Time Mapping', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig('decay_mapping.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: decay_mapping.png")

    # ===== CSV =====
    with open('decay_mapping.csv', 'w') as f:
        f.write('slider,decay_90_10_ms,decay_95_5_ms,tau_ms,t_20dB_ms,t_40dB_ms,best_fit,peak,sustain_floor\n')
        for r in results:
            d9010 = f"{r['decay_90_10_ms']:.2f}" if r['decay_90_10_ms'] else ""
            d955 = f"{r['decay_95_5_ms']:.2f}" if r['decay_95_5_ms'] else ""
            tau = f"{r['tau_ms']:.2f}" if r['tau_ms'] else ""
            t20 = f"{r['t_20dB_ms']:.2f}" if r['t_20dB_ms'] else ""
            t40 = f"{r['t_40dB_ms']:.2f}" if r['t_40dB_ms'] else ""
            f.write(f"{r['slider']},{d9010},{d955},{tau},{t20},{t40},{r['best_fit']},{r['peak_val']:.6f},{r['sustain_floor']:.4f}\n")
    print(f"Saved: decay_mapping.csv")

    # ===== Report =====
    with open('decay_report.txt', 'w') as f:
        f.write("Decay/Release Envelope Analysis Report\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Source: {path}\n")
        f.write(f"Sample rate: {sr}Hz\n")
        f.write(f"Notes analyzed: {len(results)}\n\n")
        f.write(f"{'Slider':>8} {'90-10%':>10} {'95-5%':>10} {'τ':>10} {'-20dB':>10} {'-40dB':>10} {'Fit':>12}\n")
        f.write(f"{'------':>8} {'------':>10} {'-----':>10} {'---':>10} {'-----':>10} {'-----':>10} {'---':>12}\n")
        for r in results:
            d9010 = f"{r['decay_90_10_ms']:.1f}ms" if r['decay_90_10_ms'] else "n/a"
            d955 = f"{r['decay_95_5_ms']:.1f}ms" if r['decay_95_5_ms'] else "n/a"
            tau = f"{r['tau_ms']:.1f}ms" if r['tau_ms'] else "n/a"
            t20 = f"{r['t_20dB_ms']:.0f}ms" if r['t_20dB_ms'] else "n/a"
            t40 = f"{r['t_40dB_ms']:.0f}ms" if r['t_40dB_ms'] else "n/a"
            f.write(f"{r['slider']:>8} {d9010:>10} {d955:>10} {tau:>10} {t20:>10} {t40:>10} {r['best_fit']:>12}\n")

        f.write(f"\n\nCurve Shape Summary\n")
        f.write(f"-" * 30 + "\n")
        fit_counts = {}
        for r in results:
            fit_counts[r['best_fit']] = fit_counts.get(r['best_fit'], 0) + 1
        for fit, count in sorted(fit_counts.items(), key=lambda x: -x[1]):
            f.write(f"  {fit}: {count}/{len(results)} notes\n")

        if any('exp_power' in r.get('fits', {}) for r in results):
            powers = [r['fits']['exp_power']['params'][1]
                      for r in results if 'exp_power' in r.get('fits', {})]
            if powers:
                f.write(f"\n  Decay power exponents: {', '.join(f'{p:.2f}' for p in powers)}\n")
                f.write(f"  Mean power: {np.mean(powers):.2f}\n")
                f.write(f"  (1.0 = pure exponential, <1 = fast initial/slow tail, >1 = slow initial/fast tail)\n")

    print(f"Saved: decay_report.txt")

    # Print summary
    print(f"\n{'Slider':>8} {'90-10%':>10} {'τ':>10} {'Curve':>12}")
    print(f"{'------':>8} {'------':>10} {'---':>10} {'-----':>12}")
    for r in results:
        d = f"{r['decay_90_10_ms']:.1f}ms" if r['decay_90_10_ms'] else "n/a"
        t = f"{r['tau_ms']:.1f}ms" if r['tau_ms'] else "n/a"
        print(f"{r['slider']:>8} {d:>10} {t:>10} {r['best_fit']:>12}")


if __name__ == '__main__':
    main()
