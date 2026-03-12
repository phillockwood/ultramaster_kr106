#!/usr/bin/env python3
"""
Saw ramp curvature fitter.
Extracts averaged cycles from the HW recording and fits RC tau.

Usage: python fit_tau.py hw_saw_8_octaves.wav

Outputs:
    tau_fit_result.png  — sweep plot + waveform comparisons
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


def extract_cycle(x, sr, s, e):
    """Extract averaged cycle from a note segment."""
    dur = (e - s) / sr
    ss = s + int(min(0.05, dur * 0.15) * sr)
    avail = e - ss
    nf = min(4096, 2**int(np.floor(np.log2(max(256, avail)))))
    if nf < 256:
        return None, None

    mag = np.abs(fft.rfft(x[ss:ss+nf] * np.hanning(nf)))
    freqs = np.arange(len(mag)) * sr / nf
    mask = (freqs > 20) & (freqs < 15000)
    fund = freqs[mask][np.argmax(mag[mask])]
    spc = max(1, int(sr / fund))

    cycles = []
    p = ss
    for _ in range(50):
        if p + spc + 10 > e:
            break
        ok = False
        for j in range(p, min(p + spc, e - 1)):
            if j + 1 < len(x) and x[j] <= 0 and x[j + 1] > 0:
                p = j
                ok = True
                break
        if not ok:
            p += spc
            continue
        c = x[p:p+spc]
        if len(c) == spc:
            cycles.append(c)
        p += spc
        if len(cycles) >= 15:
            break

    if not cycles:
        return None, None

    avg = np.mean(cycles, axis=0)
    # DC block (mean removal — same effect as coupling cap at steady state)
    avg -= np.mean(avg)
    # Normalize to -1..1
    avg /= np.max(np.abs(avg)) + 1e-10
    return avg, fund


def rc_saw_model(fund_hz, sr, tau_seconds):
    """Generate one cycle of RC-curved saw, DC blocked and normalized."""
    spc = int(sr / fund_hz)
    cps = fund_hz / sr
    tau_samples = tau_seconds * sr
    alpha = 1.0 / (cps * tau_samples)
    exp_neg_alpha = np.exp(-alpha)
    rc_norm = 1.0 / (1.0 - exp_neg_alpha)

    pos = np.arange(spc) / spc  # 0 to ~1
    curved = (1.0 - np.exp(-pos * alpha)) * rc_norm
    saw = 2.0 * curved - 1.0

    # DC block
    saw -= np.mean(saw)
    # Normalize
    saw /= np.max(np.abs(saw)) + 1e-10
    return saw


def fit_error(tau, hw_data, sr):
    """Total weighted RMS error across all notes."""
    total = 0
    weight_sum = 0
    for avg, fund in hw_data:
        if avg is None:
            continue
        model = rc_saw_model(fund, sr, tau)
        # Resample if lengths differ
        if len(model) != len(avg):
            model = np.interp(
                np.linspace(0, 1, len(avg)),
                np.linspace(0, 1, len(model)),
                model
            )
        # Skip the first 15% (blip/reset transient) and last 5% (pre-reset)
        n = len(avg)
        start = int(n * 0.15)
        end = int(n * 0.95)
        err = np.mean((avg[start:end] - model[start:end])**2)
        # Weight lower notes more (they show more curvature)
        weight = 1.0 / (fund + 1)
        total += err * weight
        weight_sum += weight
    return total / max(weight_sum, 1e-10)


def main():
    if len(sys.argv) < 2:
        print("Usage: python fit_tau.py <hw_saw_recording.wav>")
        sys.exit(1)

    x, sr = sf.read(sys.argv[1])
    if x.ndim > 1:
        x = x.mean(axis=1)
    print(f"Loaded: {len(x)/sr:.2f}s @ {sr}Hz")

    notes = find_notes(x, sr)
    print(f"Found {len(notes)} notes")

    hw_data = []
    for s, e in notes:
        avg, fund = extract_cycle(x, sr, s, e)
        if avg is not None:
            hw_data.append((avg, fund))
            print(f"  {fund:.0f}Hz ({len(avg)} samples/cycle)")

    if not hw_data:
        print("No usable notes found!")
        sys.exit(1)

    # Coarse sweep
    print("\nSweeping tau...")
    taus = np.logspace(-10.3, -2.3, 300)  # ~0.05ms to ~50ms
    errors = [fit_error(t, hw_data, sr) for t in taus]

    best_idx = np.argmin(errors)
    coarse_tau = taus[best_idx]
    print(f"Coarse best: {coarse_tau*1000:.3f}ms (error: {errors[best_idx]:.8f})")

    # Fine refinement
    result = minimize_scalar(
        lambda t: fit_error(t, hw_data, sr),
        bounds=(coarse_tau * 0.3, coarse_tau * 3),
        method='bounded'
    )
    best_tau = result.x
    best_err = result.fun
    print(f"Refined best: {best_tau*1000:.3f}ms (error: {best_err:.8f})")

    # Also test a few specific values for reference
    print(f"\n{'tau (ms)':>10} {'error':>12}")
    for t in [0.0005, 0.001, 0.002, 0.004, 0.008, 0.015, 0.025, best_tau]:
        e = fit_error(t, hw_data, sr)
        marker = " <-- BEST" if abs(t - best_tau) < 1e-6 else ""
        print(f"{t*1000:>10.2f} {e:>12.8f}{marker}")

    # ===== PLOTS =====
    n_notes = len(hw_data)
    fig_rows = 2 + (n_notes + 2) // 3
    fig = plt.figure(figsize=(18, 4 * fig_rows))

    # 1. Tau sweep curve
    ax = fig.add_subplot(fig_rows, 3, (1, 3))
    ax.semilogx(taus * 1000, errors, 'b-', linewidth=1)
    ax.axvline(best_tau * 1000, color='red', linestyle='--',
               label=f'Best: {best_tau*1000:.2f}ms')
    ax.set_xlabel('Tau (ms)')
    ax.set_ylabel('Weighted RMS Error')
    ax.set_title('Tau Sweep (lower = better fit)')
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 2-N. Per-note waveform comparisons
    for i, (avg, fund) in enumerate(hw_data):
        ax = fig.add_subplot(fig_rows, 3, 4 + i)
        t_ms = np.arange(len(avg)) / sr * 1000
        ax.plot(t_ms, avg, '#2196F3', linewidth=1.2, label='Hardware')

        model = rc_saw_model(fund, sr, best_tau)
        if len(model) != len(avg):
            model = np.interp(
                np.linspace(0, 1, len(avg)),
                np.linspace(0, 1, len(model)),
                model
            )
        ax.plot(t_ms, model, '#FF5722', linewidth=1.2, alpha=0.7, label='RC model')

        # Also show linear saw for reference
        linear = np.linspace(-1, 1, len(avg))
        linear -= np.mean(linear)
        linear /= np.max(np.abs(linear)) + 1e-10
        ax.plot(t_ms, linear, 'k--', linewidth=0.5, alpha=0.3, label='Linear')

        rms = np.sqrt(np.mean((avg - model)**2))
        ax.set_title(f'{fund:.0f}Hz (err: {rms:.3f})')
        ax.grid(True, alpha=0.3)
        if i == 0:
            ax.legend(fontsize=7)
        ax.set_xlabel('ms')

    fig.suptitle(f'RC Tau Fit: best = {best_tau*1000:.2f}ms\n'
                 f'For KR106Oscillators.h: static constexpr float kRcTauSeconds = {best_tau:.6f}f;',
                 fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig('tau_fit_result.png', dpi=150, bbox_inches='tight')
    plt.close()

    print(f"\n{'='*50}")
    print(f"RESULT: kRcTauSeconds = {best_tau:.6f}f  ({best_tau*1000:.3f}ms)")
    print(f"{'='*50}")
    print(f"\nPlot saved: tau_fit_result.png")


if __name__ == '__main__':
    main()
