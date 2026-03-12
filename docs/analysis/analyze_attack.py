#!/usr/bin/env python3
"""
Attack Envelope Analyzer
========================
Measures ADSR attack time and curve shape from a recording of
multiple notes at different attack slider positions.

Usage:
    python analyze_attack.py hw_attack_sweep.wav

Expects: one WAV file with multiple notes (one per attack setting),
each held long enough to reach sustain (~1s+), with gaps between them.

Outputs:
    attack_analysis.png     — per-note envelope plots with fits
    attack_mapping.png      — slider position → attack time curve
    attack_mapping.csv      — slider → time data
    attack_report.txt       — summary

Tip: name notes in order of ascending attack slider (0,1,2,...,10).
     The script numbers them in the order they appear.
"""
import sys
import numpy as np
import soundfile as sf
import scipy.signal as signal
from scipy.optimize import curve_fit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def extract_envelope(x, sr, hop=64):
    """RMS envelope with smoothing."""
    n_frames = len(x) // hop
    env = np.zeros(n_frames)
    for i in range(n_frames):
        frame = x[i*hop:(i+1)*hop]
        env[i] = np.sqrt(np.mean(frame**2))
    # Light smoothing
    win = np.hanning(7)
    win /= win.sum()
    env = np.convolve(env, win, mode='same')
    return env, hop


def find_notes(env, sr, hop, min_gap_s=0.15, min_dur_s=0.2):
    """Find note boundaries from envelope."""
    env_db = 20 * np.log10(env + 1e-10)
    pk = np.max(env_db)
    thresh = pk - 30

    above = env_db > thresh
    trans = np.diff(above.astype(int))
    raw_starts = list(np.where(trans == 1)[0])
    raw_ends = list(np.where(trans == -1)[0])

    if not raw_starts:
        return []

    # Merge close onsets
    starts, ends = [raw_starts[0]], []
    for i in range(1, len(raw_starts)):
        pe = raw_ends[i-1] if i-1 < len(raw_ends) else raw_starts[i]-1
        gap_s = (raw_starts[i] - pe) * hop / sr
        if gap_s < min_gap_s:
            continue
        ends.append(raw_ends[i-1])
        starts.append(raw_starts[i])
    ends.append(raw_ends[-1] if raw_ends else len(env)-1)

    # Filter by duration
    notes = []
    for s, e in zip(starts, ends):
        dur = (e - s) * hop / sr
        if dur >= min_dur_s:
            notes.append((s, e))
    return notes


def measure_attack(env, sr, hop, note_start, note_end):
    """
    Measure attack characteristics from an envelope segment.

    Returns dict with:
        attack_time_ms: time from 10% to 90% of sustain level
        attack_time_ms_5_95: time from 5% to 95%
        tau_ms: fitted exponential time constant
        curve_type: 'linear', 'exponential', 'rc' based on best fit
        sustain_level: steady-state amplitude
        env_time: time array (ms)
        env_norm: normalized envelope (0=silence, 1=sustain)
        fit_time: time array for fitted curve
        fit_values: fitted curve values
    """
    seg = env[note_start:note_end]
    t = np.arange(len(seg)) * hop / sr  # seconds

    # Find sustain level (mean of last 30% of note)
    n = len(seg)
    sustain_region = seg[int(n * 0.7):]
    sustain = np.mean(sustain_region)

    if sustain < 1e-8:
        return None

    # Normalize: 0 = silence, 1 = sustain
    env_norm = seg / sustain

    # Find onset: first sample above 5% of sustain
    onset_idx = 0
    for i in range(len(env_norm)):
        if env_norm[i] > 0.05:
            onset_idx = max(0, i - 1)
            break

    # Find when we reach sustain: first sample above 95%
    settled_idx = len(env_norm) - 1
    for i in range(onset_idx, len(env_norm)):
        if env_norm[i] > 0.95:
            settled_idx = i
            break

    # Attack region
    atk_env = env_norm[onset_idx:settled_idx+1]
    atk_t = t[onset_idx:settled_idx+1] - t[onset_idx]

    if len(atk_t) < 3:
        return None

    # 10%–90% attack time
    t10, t90 = None, None
    for i, v in enumerate(env_norm[onset_idx:]):
        if v >= 0.1 and t10 is None:
            t10 = i * hop / sr
        if v >= 0.9 and t90 is None:
            t90 = i * hop / sr
            break

    # 5%–95% attack time
    t5, t95 = None, None
    for i, v in enumerate(env_norm[onset_idx:]):
        if v >= 0.05 and t5 is None:
            t5 = i * hop / sr
        if v >= 0.95 and t95 is None:
            t95 = i * hop / sr
            break

    attack_10_90 = (t90 - t10) * 1000 if (t10 is not None and t90 is not None) else None
    attack_5_95 = (t95 - t5) * 1000 if (t5 is not None and t95 is not None) else None

    # Fit models to the attack curve
    fits = {}

    # Model 1: Linear ramp
    def linear(t, a, b):
        return np.clip(a * t + b, 0, 1.2)

    # Model 2: Exponential (RC charge): 1 - exp(-t/tau)
    def rc_charge(t, tau, amp, offset):
        return np.clip(amp * (1.0 - np.exp(-t / max(tau, 1e-6))) + offset, 0, 1.5)

    # Model 3: Exponential with power (adjustable curve shape)
    def rc_power(t, tau, power, amp, offset):
        x = 1.0 - np.exp(-t / max(tau, 1e-6))
        return np.clip(amp * np.power(x, max(power, 0.1)) + offset, 0, 1.5)

    best_fit = None
    best_rms = 1e6

    # Fit linear
    try:
        popt, _ = curve_fit(linear, atk_t, atk_env, p0=[1.0/max(atk_t[-1], 0.001), 0],
                            maxfev=5000)
        fitted = linear(atk_t, *popt)
        rms = np.sqrt(np.mean((atk_env - fitted)**2))
        fits['linear'] = {'params': popt, 'rms': rms, 'fitted': fitted,
                          'label': f'Linear (slope={popt[0]:.1f}/s)'}
        if rms < best_rms:
            best_rms = rms
            best_fit = 'linear'
    except:
        pass

    # Fit RC charge
    try:
        tau_guess = atk_t[-1] / 3 if len(atk_t) > 0 else 0.01
        popt, _ = curve_fit(rc_charge, atk_t, atk_env,
                            p0=[tau_guess, 1.0, 0.0],
                            bounds=([1e-5, 0.1, -0.5], [10, 2.0, 0.5]),
                            maxfev=5000)
        fitted = rc_charge(atk_t, *popt)
        rms = np.sqrt(np.mean((atk_env - fitted)**2))
        fits['rc'] = {'params': popt, 'rms': rms, 'fitted': fitted,
                      'label': f'RC (τ={popt[0]*1000:.1f}ms)'}
        if rms < best_rms:
            best_rms = rms
            best_fit = 'rc'
    except:
        pass

    # Fit RC with power curve
    try:
        tau_guess = atk_t[-1] / 3 if len(atk_t) > 0 else 0.01
        popt, _ = curve_fit(rc_power, atk_t, atk_env,
                            p0=[tau_guess, 1.0, 1.0, 0.0],
                            bounds=([1e-5, 0.1, 0.1, -0.5], [10, 5.0, 2.0, 0.5]),
                            maxfev=5000)
        fitted = rc_power(atk_t, *popt)
        rms = np.sqrt(np.mean((atk_env - fitted)**2))
        fits['rc_power'] = {'params': popt, 'rms': rms, 'fitted': fitted,
                            'label': f'RC^p (τ={popt[0]*1000:.1f}ms, p={popt[1]:.2f})'}
        if rms < best_rms:
            best_rms = rms
            best_fit = 'rc_power'
    except:
        pass

    # Extract tau from best fit
    tau_ms = None
    if best_fit == 'rc' and 'rc' in fits:
        tau_ms = fits['rc']['params'][0] * 1000
    elif best_fit == 'rc_power' and 'rc_power' in fits:
        tau_ms = fits['rc_power']['params'][0] * 1000

    return {
        'attack_10_90_ms': attack_10_90,
        'attack_5_95_ms': attack_5_95,
        'tau_ms': tau_ms,
        'best_fit': best_fit,
        'fits': fits,
        'sustain_level': sustain,
        'env_time_ms': t * 1000,
        'env_norm': env_norm,
        'atk_time_ms': atk_t * 1000,
        'atk_env': atk_env,
        'onset_idx': onset_idx,
        'settled_idx': settled_idx,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_attack.py <recording.wav> [slider_start] [slider_step]")
        print("  slider_start: attack slider value for first note (default: 0)")
        print("  slider_step:  increment per note (default: 1)")
        sys.exit(1)

    path = sys.argv[1]
    slider_start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    slider_step = int(sys.argv[3]) if len(sys.argv) > 3 else 1

    x, sr = sf.read(path)
    if x.ndim > 1:
        x = x.mean(axis=1)
    print(f"Loaded: {len(x)/sr:.2f}s @ {sr}Hz")

    # Extract envelope
    env, hop = extract_envelope(x, sr)
    notes = find_notes(env, sr, hop)
    print(f"Found {len(notes)} notes")

    results = []
    for i, (ns, ne) in enumerate(notes):
        slider = slider_start + i * slider_step
        r = measure_attack(env, sr, hop, ns, ne)
        if r is None:
            print(f"  Note {i+1} (slider {slider}): too short or quiet, skipping")
            continue
        r['slider'] = slider
        r['note_idx'] = i + 1
        results.append(r)

        atk = r['attack_10_90_ms']
        tau = r['tau_ms']
        fit = r['best_fit']
        atk_str = f"{atk:.1f}ms" if atk else "n/a"
        tau_str = f"{tau:.1f}ms" if tau else "n/a"
        print(f"  Note {i+1} (slider {slider}): 10-90% = {atk_str}, τ = {tau_str}, best fit: {fit}")

    if not results:
        print("No usable notes found!")
        sys.exit(1)

    # ===== PLOT 1: Per-note attack envelopes with fits =====
    n = len(results)
    cols = min(4, n)
    rows = max(1, (n + cols - 1) // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(5*cols, 4*rows), squeeze=False)
    af = axes.flatten()

    fit_colors = {'linear': '#FF5722', 'rc': '#4CAF50', 'rc_power': '#9C27B0'}

    for i, r in enumerate(results):
        ax = af[i]

        # Full envelope (zoomed to attack region)
        onset = r['onset_idx']
        settled = r['settled_idx']
        # Show from slightly before onset to 2x the attack duration past settled
        show_start = max(0, onset - 5)
        show_end = min(len(r['env_norm']), settled + (settled - onset))
        t_show = r['env_time_ms'][show_start:show_end]
        e_show = r['env_norm'][show_start:show_end]
        ax.plot(t_show, e_show, '#2196F3', linewidth=1.5, label='Measured')

        # Overlay fits
        for fname, fdata in r['fits'].items():
            t_fit = r['atk_time_ms']
            t_fit_abs = t_fit + r['env_time_ms'][onset]
            ax.plot(t_fit_abs, fdata['fitted'], '--', color=fit_colors.get(fname, 'gray'),
                    linewidth=1.2, alpha=0.7, label=fdata['label'])

        ax.axhline(1.0, color='gray', linewidth=0.5, linestyle=':')
        ax.axhline(0.1, color='gray', linewidth=0.3, linestyle=':')
        ax.axhline(0.9, color='gray', linewidth=0.3, linestyle=':')

        atk_str = f"{r['attack_10_90_ms']:.0f}ms" if r['attack_10_90_ms'] else "n/a"
        ax.set_title(f"Slider {r['slider']} ({atk_str})")
        ax.set_xlabel('ms')
        ax.set_ylabel('Amplitude (norm)')
        ax.set_ylim(-0.05, 1.3)
        ax.grid(True, alpha=0.3)
        if i == 0:
            ax.legend(fontsize=6)

    for i in range(n, len(af)):
        af[i].set_visible(False)

    fig.suptitle('Attack Envelopes — Per Slider Position', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig('attack_analysis.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nSaved: attack_analysis.png")

    # ===== PLOT 2: Slider → attack time mapping =====
    sliders = [r['slider'] for r in results]
    atk_times = [r['attack_10_90_ms'] if r['attack_10_90_ms'] else 0 for r in results]
    taus = [r['tau_ms'] if r['tau_ms'] else 0 for r in results]

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Linear scale
    axes[0].plot(sliders, atk_times, 'o-', color='#2196F3', markersize=6, linewidth=1.5,
                 label='10%–90% time')
    axes[0].plot(sliders, taus, 's--', color='#FF5722', markersize=5, linewidth=1,
                 label='τ (exp fit)')
    axes[0].set_xlabel('Attack Slider Position')
    axes[0].set_ylabel('Time (ms)')
    axes[0].set_title('Attack Time vs Slider (linear)')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # Log scale
    axes[1].semilogy(sliders, [max(t, 0.1) for t in atk_times], 'o-', color='#2196F3',
                     markersize=6, linewidth=1.5, label='10%–90% time')
    axes[1].semilogy(sliders, [max(t, 0.1) for t in taus], 's--', color='#FF5722',
                     markersize=5, linewidth=1, label='τ (exp fit)')
    axes[1].set_xlabel('Attack Slider Position')
    axes[1].set_ylabel('Time (ms)')
    axes[1].set_title('Attack Time vs Slider (log)')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3, which='both')

    fig.suptitle('Slider → Attack Time Mapping', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig('attack_mapping.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: attack_mapping.png")

    # ===== CSV =====
    with open('attack_mapping.csv', 'w') as f:
        f.write('slider,attack_10_90_ms,attack_5_95_ms,tau_ms,best_fit,sustain_level\n')
        for r in results:
            a1090 = f"{r['attack_10_90_ms']:.2f}" if r['attack_10_90_ms'] else ""
            a595 = f"{r['attack_5_95_ms']:.2f}" if r['attack_5_95_ms'] else ""
            tau = f"{r['tau_ms']:.2f}" if r['tau_ms'] else ""
            f.write(f"{r['slider']},{a1090},{a595},{tau},{r['best_fit']},{r['sustain_level']:.6f}\n")
    print(f"Saved: attack_mapping.csv")

    # ===== Report =====
    with open('attack_report.txt', 'w') as f:
        f.write("Attack Envelope Analysis Report\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Source: {path}\n")
        f.write(f"Sample rate: {sr}Hz\n")
        f.write(f"Notes analyzed: {len(results)}\n\n")
        f.write(f"{'Slider':>8} {'10-90%':>10} {'5-95%':>10} {'τ':>10} {'Fit':>12} {'Sustain':>10}\n")
        f.write(f"{'------':>8} {'------':>10} {'-----':>10} {'---':>10} {'---':>12} {'-------':>10}\n")
        for r in results:
            a1090 = f"{r['attack_10_90_ms']:.1f}ms" if r['attack_10_90_ms'] else "n/a"
            a595 = f"{r['attack_5_95_ms']:.1f}ms" if r['attack_5_95_ms'] else "n/a"
            tau = f"{r['tau_ms']:.1f}ms" if r['tau_ms'] else "n/a"
            f.write(f"{r['slider']:>8} {a1090:>10} {a595:>10} {tau:>10} {r['best_fit']:>12} {r['sustain_level']:>10.4f}\n")

        # Curve shape summary
        f.write(f"\n\nCurve Shape Summary\n")
        f.write(f"-" * 30 + "\n")
        fit_counts = {}
        for r in results:
            fit_counts[r['best_fit']] = fit_counts.get(r['best_fit'], 0) + 1
        for fit, count in sorted(fit_counts.items(), key=lambda x: -x[1]):
            f.write(f"  {fit}: {count}/{len(results)} notes\n")

        if any(r.get('fits', {}).get('rc_power') for r in results):
            powers = [r['fits']['rc_power']['params'][1]
                      for r in results if 'rc_power' in r.get('fits', {})]
            if powers:
                f.write(f"\n  RC power exponents: {', '.join(f'{p:.2f}' for p in powers)}\n")
                f.write(f"  Mean power: {np.mean(powers):.2f}\n")
                f.write(f"  (1.0 = standard RC, <1 = concave, >1 = convex/S-curve)\n")

    print(f"Saved: attack_report.txt")

    # Print summary
    print(f"\n{'Slider':>8} {'10-90%':>10} {'τ':>10} {'Curve':>12}")
    print(f"{'------':>8} {'------':>10} {'---':>10} {'-----':>12}")
    for r in results:
        a = f"{r['attack_10_90_ms']:.1f}ms" if r['attack_10_90_ms'] else "n/a"
        t = f"{r['tau_ms']:.1f}ms" if r['tau_ms'] else "n/a"
        print(f"{r['slider']:>8} {a:>10} {t:>10} {r['best_fit']:>12}")


if __name__ == '__main__':
    main()
