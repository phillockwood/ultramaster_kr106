#!/usr/bin/env python3
"""
RC Tau Fitter — Harmonic Ratio Method
======================================
Fits kRcTauSeconds by matching the even/odd harmonic ratio pattern
across pitches. This method is immune to AC coupling effects since
both HW and model see the same highpass — the ratio cancels it.

Usage:
    python fit_tau_harmonics.py hw_saw_8_octaves.wav [vst_saw_8_octaves.wav]

If a VST file is provided, it overlays the current VST's ratios for comparison.

Outputs:
    tau_harmonic_fit.png  — fit results
    Prints recommended kRcTauSeconds value
"""
import sys
import numpy as np
import soundfile as sf
import scipy.fft as fft
from scipy.optimize import minimize_scalar
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def find_notes(x, sr):
    hop = 256
    env = np.array([np.sqrt(np.mean(x[i:i+hop]**2)) for i in range(0, len(x)-hop, hop)])
    env_db = 20*np.log10(env + 1e-10)
    pk = np.max(env_db)
    above = env_db > (pk - 25)
    trans = np.diff(above.astype(int))
    raw_s = list(np.where(trans == 1)[0])
    raw_e = list(np.where(trans == -1)[0])
    if not raw_s:
        return []
    starts, ends = [raw_s[0]], []
    for i in range(1, len(raw_s)):
        pe = raw_e[i-1] if i-1 < len(raw_e) else raw_s[i]-1
        if (raw_s[i] - pe) * hop / sr < 0.15:
            continue
        ends.append(raw_e[i-1])
        starts.append(raw_s[i])
    ends.append(raw_e[-1] if raw_e else len(env)-1)
    return [(s*hop, e*hop) for s, e in zip(starts, ends)]


def measure_harmonics(x, sr, s, e):
    """Measure harmonic amplitudes relative to fundamental."""
    dur = (e - s) / sr
    ss = s + int(min(0.05, dur * 0.15) * sr)
    avail = e - ss
    nf = min(8192, 2**int(np.floor(np.log2(max(256, avail)))))
    if nf < 256 or avail < nf:
        return None, None, None

    # Average several FFT frames
    specs = []
    for i in range(4):
        off = ss + i * (nf // 2)
        if off + nf > e:
            break
        specs.append(np.abs(fft.rfft(x[off:off+nf] * np.hanning(nf))))
    if not specs:
        return None, None, None

    mag = np.mean(specs, axis=0)
    freqs = np.arange(len(mag)) * sr / nf

    # Find fundamental
    mask = (freqs > 20) & (freqs < 15000)
    fi = np.argmax(mag[mask]) + np.searchsorted(freqs, 20)
    fund = freqs[fi]
    fund_amp = mag[fi]

    # Measure each harmonic
    harmonics = {}  # n -> dB relative to fundamental
    for n in range(1, 80):
        target = fund * n
        if target > sr / 2 - 200:
            break
        sc = max(freqs[1] * 1.5, fund * 0.04)
        hm = (freqs >= target - sc) & (freqs <= target + sc)
        if not np.any(hm):
            continue
        peak_amp = np.max(mag[hm])
        harmonics[n] = 20 * np.log10(peak_amp / fund_amp + 1e-10)

    return fund, harmonics, mag


def even_odd_ratios(harmonics, max_n=30):
    """
    Compute the mean difference between even and odd harmonic levels.
    Returns a list of (n_even, ratio_dB) where ratio is even_dB - avg_adjacent_odds_dB.
    A perfect saw has ratio ≈ 0. More curvature → more negative ratio.
    """
    ratios = []
    for n in range(2, max_n, 2):  # even harmonics
        if n not in harmonics:
            continue
        # Compare to average of adjacent odd harmonics
        odds = []
        if (n - 1) in harmonics:
            odds.append(harmonics[n - 1])
        if (n + 1) in harmonics:
            odds.append(harmonics[n + 1])
        if not odds:
            continue
        avg_odd = np.mean(odds)
        ratio = harmonics[n] - avg_odd
        ratios.append((n, ratio))
    return ratios


def rc_saw_harmonic_ratios(fund_hz, sr, tau_seconds, max_n=30):
    """
    Compute the harmonic ratios for an RC-curved saw at given pitch and tau.
    Uses analytical FFT of the RC waveform — no AC coupling involved.
    """
    spc = int(sr / fund_hz)
    if spc < 4:
        return []

    cps = fund_hz / sr
    tau_samples = tau_seconds * sr
    alpha = 1.0 / (cps * tau_samples)
    exp_neg_alpha = np.exp(-alpha)
    rc_norm = 1.0 / (1.0 - exp_neg_alpha)

    # Generate one cycle at high resolution
    n_pts = max(spc, 4096)  # at least 4096 points for clean FFT
    pos = np.arange(n_pts) / n_pts
    curved = (1.0 - np.exp(-pos * alpha)) * rc_norm
    saw = 2.0 * curved - 1.0
    saw -= np.mean(saw)  # remove DC

    # FFT
    mag = np.abs(fft.rfft(saw * np.hanning(n_pts)))
    freqs = np.arange(len(mag)) * sr / n_pts

    # Measure harmonics
    fund_amp = None
    harmonics = {}
    for n in range(1, max_n + 1):
        target = fund_hz * n
        if target > sr / 2 - 200:
            break
        sc = max(freqs[1] * 1.5, fund_hz * 0.04)
        hm = (freqs >= target - sc) & (freqs <= target + sc)
        if not np.any(hm):
            continue
        peak = np.max(mag[hm])
        if n == 1:
            fund_amp = peak
        if fund_amp and fund_amp > 0:
            harmonics[n] = 20 * np.log10(peak / fund_amp + 1e-10)

    return even_odd_ratios(harmonics, max_n)


def fit_error(tau, hw_notes_data, sr):
    """
    Total error: how well does the RC model's even/odd ratio pattern
    match the hardware across all pitches?
    """
    total = 0
    count = 0

    for fund, hw_harmonics in hw_notes_data:
        hw_ratios = even_odd_ratios(hw_harmonics)
        model_ratios = rc_saw_harmonic_ratios(fund, sr, tau)

        if not hw_ratios or not model_ratios:
            continue

        # Match by harmonic number
        hw_dict = dict(hw_ratios)
        model_dict = dict(model_ratios)
        common = sorted(set(hw_dict.keys()) & set(model_dict.keys()))

        if len(common) < 2:
            continue

        for n in common:
            diff = hw_dict[n] - model_dict[n]
            total += diff * diff
            count += 1

    return total / max(count, 1)


def main():
    if len(sys.argv) < 2:
        print("Usage: python fit_tau_harmonics.py <hw_recording.wav> [vst_recording.wav]")
        sys.exit(1)

    hw_path = sys.argv[1]
    vst_path = sys.argv[2] if len(sys.argv) > 2 else None

    # Load hardware
    x, sr = sf.read(hw_path)
    if x.ndim > 1:
        x = x.mean(axis=1)
    print(f"HW: {len(x)/sr:.2f}s @ {sr}Hz")

    notes = find_notes(x, sr)
    print(f"Found {len(notes)} notes")

    hw_data = []  # list of (fund, harmonics_dict)
    for s, e in notes:
        fund, harmonics, _ = measure_harmonics(x, sr, s, e)
        if fund and harmonics:
            hw_data.append((fund, harmonics))
            ratios = even_odd_ratios(harmonics)
            mean_ratio = np.mean([r for _, r in ratios]) if ratios else 0
            print(f"  {fund:.0f}Hz: {len(harmonics)} harmonics, mean even/odd ratio: {mean_ratio:.1f}dB")

    # Load VST if provided
    vst_data = []
    if vst_path:
        vx, vsr = sf.read(vst_path)
        if vx.ndim > 1:
            vx = vx.mean(axis=1)
        print(f"\nVST: {len(vx)/vsr:.2f}s @ {vsr}Hz")

        # Try tempo-based slicing first (120bpm = 1s per note)
        vst_notes_tempo = [(int(i*1.0*vsr), int((i*1.0+0.5)*vsr))
                           for i in range(8) if int((i*1.0+0.5)*vsr) <= len(vx)]
        vst_notes_detect = find_notes(vx, vsr)

        # Use whichever found more notes
        vst_notes = vst_notes_tempo if len(vst_notes_tempo) >= len(vst_notes_detect) else vst_notes_detect
        print(f"VST: {len(vst_notes)} notes")

        for s, e in vst_notes:
            fund, harmonics, _ = measure_harmonics(vx, vsr, s, e)
            if fund and harmonics:
                vst_data.append((fund, harmonics))

    # ===== FIT TAU =====
    print("\nSweeping tau...")
    taus = np.logspace(-5, -1, 400)  # 0.01ms to 100ms
    errors = [fit_error(t, hw_data, sr) for t in taus]

    best_idx = np.argmin(errors)
    coarse_tau = taus[best_idx]
    print(f"Coarse best: {coarse_tau*1000:.4f}ms")

    # Refine
    result = minimize_scalar(
        lambda t: fit_error(t, hw_data, sr),
        bounds=(coarse_tau * 0.2, coarse_tau * 5),
        method='bounded'
    )
    best_tau = result.x
    print(f"Refined best: {best_tau*1000:.4f}ms")

    # Reference points
    print(f"\n{'tau (ms)':>10} {'error':>12}")
    for t in sorted(set([0.0001, 0.0005, 0.001, 0.002, 0.004, 0.008, 0.015, 0.025, best_tau])):
        e = fit_error(t, hw_data, sr)
        marker = " <-- BEST" if abs(t - best_tau) / best_tau < 0.01 else ""
        print(f"{t*1000:>10.3f} {e:>12.4f}{marker}")

    # ===== PLOTS =====
    n_notes = len(hw_data)
    fig = plt.figure(figsize=(18, 4 + 4 * ((n_notes + 2) // 3)))
    gs = fig.add_gridspec(1 + (n_notes + 2) // 3, 3, hspace=0.4)

    # Tau sweep
    ax = fig.add_subplot(gs[0, :])
    ax.semilogx(taus * 1000, errors, 'b-', linewidth=1)
    ax.axvline(best_tau * 1000, color='red', linestyle='--',
               label=f'Best: {best_tau*1000:.3f}ms')
    ax.set_xlabel('Tau (ms)')
    ax.set_ylabel('Even/Odd Ratio Error')
    ax.set_title('Tau Sweep — Harmonic Ratio Method (immune to AC coupling)')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    # Per-note: even/odd ratio comparison
    colors_hw = '#2196F3'
    colors_model = '#FF5722'
    colors_vst = '#4CAF50'

    for i, (fund, hw_harmonics) in enumerate(hw_data):
        row = 1 + i // 3
        col = i % 3
        ax = fig.add_subplot(gs[row, col])

        hw_ratios = even_odd_ratios(hw_harmonics)
        model_ratios = rc_saw_harmonic_ratios(fund, sr, best_tau)

        if hw_ratios:
            ns_hw = [n for n, _ in hw_ratios]
            vals_hw = [v for _, v in hw_ratios]
            ax.plot(ns_hw, vals_hw, 'o-', color=colors_hw, markersize=4,
                    linewidth=1.2, label='Hardware')

        if model_ratios:
            ns_m = [n for n, _ in model_ratios]
            vals_m = [v for _, v in model_ratios]
            ax.plot(ns_m, vals_m, 'x--', color=colors_model, markersize=5,
                    linewidth=1.2, label=f'RC model')

        # VST overlay if available
        vst_match = None
        for vf, vh in vst_data:
            if abs(np.log2(vf / (fund + 1e-10))) < 0.2:
                vst_match = vh
                break
        if vst_match:
            vst_ratios = even_odd_ratios(vst_match)
            if vst_ratios:
                ns_v = [n for n, _ in vst_ratios]
                vals_v = [v for _, v in vst_ratios]
                ax.plot(ns_v, vals_v, 's:', color=colors_vst, markersize=3,
                        linewidth=1, label='VST (current)')

        ax.axhline(0, color='gray', linewidth=0.5)
        ax.set_title(f'{fund:.0f}Hz')
        ax.set_xlabel('Even harmonic #')
        ax.set_ylabel('Even − Odd (dB)')
        ax.set_ylim(-30, 5)
        ax.grid(True, alpha=0.3)
        if i == 0:
            ax.legend(fontsize=7)

    fig.suptitle(
        f'RC Tau Fit (Harmonic Ratio Method)\n'
        f'Best tau = {best_tau*1000:.3f}ms → '
        f'static constexpr float kRcTauSeconds = {best_tau:.6f}f;',
        fontsize=14, fontweight='bold'
    )
    plt.tight_layout()
    plt.savefig('tau_harmonic_fit.png', dpi=150, bbox_inches='tight')
    plt.close()

    # ===== SUMMARY =====
    print(f"\n{'='*60}")
    print(f"RESULT: kRcTauSeconds = {best_tau:.6f}f  ({best_tau*1000:.3f}ms)")
    print(f"{'='*60}")
    print(f"\nPaste into KR106Oscillators.h:")
    print(f"  static constexpr float kRcTauSeconds = {best_tau:.6f}f;")
    print(f"\nPlot saved: tau_harmonic_fit.png")

    if vst_data:
        print(f"\n--- Per-pitch comparison ---")
        print(f"{'Pitch':>8} {'HW ratio':>10} {'Model':>10} {'VST':>10}")
        for fund, hw_h in hw_data:
            hw_r = even_odd_ratios(hw_h)
            model_r = rc_saw_harmonic_ratios(fund, sr, best_tau)
            hw_mean = np.mean([v for _, v in hw_r]) if hw_r else 0
            model_mean = np.mean([v for _, v in model_r]) if model_r else 0

            vst_mean = 0
            for vf, vh in vst_data:
                if abs(np.log2(vf / (fund + 1e-10))) < 0.2:
                    vst_r = even_odd_ratios(vh)
                    vst_mean = np.mean([v for _, v in vst_r]) if vst_r else 0
                    break

            print(f"{fund:>8.0f} {hw_mean:>10.1f} {model_mean:>10.1f} {vst_mean:>10.1f}")


if __name__ == '__main__':
    main()
