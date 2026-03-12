#!/usr/bin/env python3
"""
Filter Cutoff Mapping Extractor
================================
Extracts the cutoff-vs-slider-position curve from a filter sweep recording.
Best with noise source and high resonance (res 10) so the resonance peak is trackable.

Usage:
    python filter_mapping.py 09_filter_sweep_res10.wav

Outputs:
    filter_mapping.png   — cutoff curve plot with spectrogram
    filter_mapping.csv   — slider position vs cutoff frequency
"""

import sys
import numpy as np
import soundfile as sf
import scipy.signal as signal
from scipy.signal import medfilt
from scipy.optimize import curve_fit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    if len(sys.argv) < 2:
        print("Usage: python filter_mapping.py <sweep_recording.wav>")
        sys.exit(1)

    path = sys.argv[1]
    x, sr = sf.read(path)
    if x.ndim > 1:
        x = x.mean(axis=1)
    print(f"Loaded: {path}")
    print(f"  Duration: {len(x)/sr:.2f}s, Sample rate: {sr} Hz")

    # STFT
    n_fft = 4096
    hop = 512
    f, t, Zxx = signal.stft(x, sr, nperseg=n_fft, noverlap=n_fft - hop, window='hann')
    mag = np.abs(Zxx)
    print(f"  STFT: {mag.shape[1]} frames, {mag.shape[0]} freq bins")

    # Track resonance peak per frame
    cutoffs = np.full(mag.shape[1], np.nan)
    for i in range(mag.shape[1]):
        frame = mag[:, i]
        valid_mask = f > 25
        vm = frame[valid_mask]
        vf = f[valid_mask]
        if np.max(vm) < 1e-8:
            continue
        cutoffs[i] = vf[np.argmax(vm)]

    # Smooth with median filter
    cutoffs_clean = medfilt(np.nan_to_num(cutoffs, nan=0), 21)
    cutoffs_clean[cutoffs_clean < 25] = np.nan
    valid = ~np.isnan(cutoffs_clean)

    if np.sum(valid) < 50:
        print("ERROR: Not enough valid frames. Is there signal in the file?")
        sys.exit(1)

    print(f"  Tracked cutoff range: {np.nanmin(cutoffs_clean[valid]):.0f} – {np.nanmax(cutoffs_clean[valid]):.0f} Hz")

    # Find sweep region: where cutoff is rising consistently
    dc = np.diff(np.nan_to_num(cutoffs_clean, nan=0))
    dc_smooth = np.convolve(dc, np.ones(30) / 30, mode='same')

    sweep_start = 0
    for i in range(len(dc_smooth) - 50):
        if np.mean(dc_smooth[i:i + 50]) > 0.3:
            sweep_start = i
            break

    sweep_end = len(cutoffs_clean) - 1
    peak_cutoff = np.nanmax(cutoffs_clean)
    for i in range(len(cutoffs_clean) - 1, sweep_start, -1):
        if valid[i] and cutoffs_clean[i] > 0.85 * peak_cutoff:
            sweep_end = i
            break

    # Extract sweep
    sw_t = t[sweep_start:sweep_end + 1]
    sw_c = cutoffs_clean[sweep_start:sweep_end + 1]
    sw_t_norm = (sw_t - sw_t[0]) / (sw_t[-1] - sw_t[0])
    good = ~np.isnan(sw_c)
    sw_t_g = sw_t_norm[good]
    sw_c_g = sw_c[good]

    print(f"\nSweep detected:")
    print(f"  Time: {t[sweep_start]:.2f}s – {t[sweep_end]:.2f}s")
    print(f"  Cutoff: {sw_c_g[0]:.0f} – {sw_c_g[-1]:.0f} Hz")

    # Fit exponential
    def exp_fit(t, a, b, c):
        return a * np.exp(b * t) + c

    has_fit = False
    try:
        p, _ = curve_fit(exp_fit, sw_t_g, sw_c_g, p0=[50, 5, 50], maxfev=10000)
        fitted = exp_fit(sw_t_g, *p)
        rms_err = np.sqrt(np.mean((sw_c_g - fitted) ** 2))
        print(f"\nExponential fit:")
        print(f"  f(slider) = {p[0]:.1f} * exp({p[1]:.3f} * slider/10) + {p[2]:.1f}")
        print(f"  RMS error: {rms_err:.0f} Hz")
        has_fit = True
    except Exception as e:
        print(f"Exponential fit failed: {e}")

    # Slider position table
    print(f"\n{'Slider':>8} {'Cutoff Hz':>10}")
    print(f"{'------':>8} {'----------':>10}")
    for s in np.arange(0, 10.5, 0.5):
        idx = min(int((s / 10) * (len(sw_c_g) - 1)), len(sw_c_g) - 1)
        print(f"{s:>8.1f} {sw_c_g[idx]:>10.0f}")

    # ===== PLOT =====
    fig, axes = plt.subplots(2, 1, figsize=(16, 12))

    # Cutoff vs slider
    sl = sw_t_g * 10
    axes[0].plot(sl, sw_c_g, color='#2196F3', linewidth=1.5, label='Measured (Juno hardware)')
    if has_fit:
        axes[0].plot(sl, fitted, '#FF5722', linewidth=1.5, linestyle='--',
                     label=f'Fit: {p[0]:.0f}·exp({p[1]:.2f}·x)+{p[2]:.0f} (err {rms_err:.0f}Hz)')
    axes[0].set_yscale('log')
    axes[0].set_xlim(0, 10)
    axes[0].set_ylim(20, 30000)
    axes[0].set_title('Filter Cutoff vs Slider Position (Res=10)')
    axes[0].set_xlabel('Slider Position (0–10)')
    axes[0].set_ylabel('Cutoff (Hz)')

    for freq, lbl in [(100, '100'), (500, '500'), (1000, '1k'), (5000, '5k'),
                       (10000, '10k'), (18000, '18k'), (20000, '20k')]:
        c = 'red' if freq == 18000 else 'gray'
        axes[0].axhline(freq, color=c, linewidth=0.8 if freq == 18000 else 0.4,
                         linestyle=':', alpha=0.6)
        axes[0].text(0.15, freq * 1.08, lbl, fontsize=8, color=c)

    axes[0].legend(fontsize=10)
    axes[0].grid(True, alpha=0.3, which='both')

    # Spectrogram with overlay
    f_sg, t_sg, S_sg = signal.spectrogram(x, sr, nperseg=2048, noverlap=1792, window='hann')
    axes[1].pcolormesh(t_sg, f_sg, 10 * np.log10(S_sg + 1e-10),
                        shading='gouraud', cmap='magma', vmin=-80, vmax=-10)
    axes[1].plot(t[valid], cutoffs_clean[valid], color='cyan', linewidth=1, alpha=0.8)
    axes[1].axhline(18000, color='red', linewidth=1, linestyle=':', alpha=0.7)
    axes[1].set_ylim(0, min(sr / 2, 30000))
    axes[1].set_title('Spectrogram with Tracked Cutoff')
    axes[1].set_xlabel('Time (s)')
    axes[1].set_ylabel('Hz')

    fig.suptitle('Juno VCF Cutoff Frequency Mapping', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig('filter_mapping.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nPlot saved: filter_mapping.png")

    # Save CSV
    import csv
    with open('filter_mapping.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['slider_0_to_10', 'cutoff_hz'])
        for i in range(len(sw_c_g)):
            w.writerow([f'{(i / (len(sw_c_g) - 1)) * 10:.3f}', f'{sw_c_g[i]:.1f}'])
    print(f"CSV saved: filter_mapping.csv")


if __name__ == '__main__':
    main()
