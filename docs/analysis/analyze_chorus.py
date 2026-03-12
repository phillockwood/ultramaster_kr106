#!/usr/bin/env python3
"""
Juno Chorus Analyzer
=====================
Analyzes the Juno BBD chorus from a stereo recording of white noise.

The Juno chorus uses two modulated BBD delay lines (not wet/dry).
Left and Right outputs are the two separate BBD taps, modulated by
triangle LFOs in antiphase. This creates the stereo width.

Recording setup:
    Noise at full, all oscillators off, filter open, VCA gate mode.
    Record STEREO. Three sections with gaps:
      1. Chorus OFF (dry)
      2. Chorus I (slow modulation)
      3. Chorus II (fast modulation)
      (optional 4th: Chorus I+II)

Usage:
    python analyze_chorus.py recording.wav [n_sections]

    n_sections: 3 or 4 (default: 3)

Outputs:
    chorus_analysis.png   — spectra, comb patterns, modulation, stereo
    chorus_report.txt     — summary with measured parameters
"""
import sys
import numpy as np
import soundfile as sf
import scipy.signal as signal
import scipy.fft as fft
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def find_sections(x_mono, sr, min_gap=0.2, min_dur=0.5):
    """Find sections separated by silence."""
    hop = 512
    env = np.array([np.sqrt(np.mean(x_mono[i:i+hop]**2))
                    for i in range(0, len(x_mono)-hop, hop)])
    env_db = 20 * np.log10(env + 1e-10)
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
        if (raw_s[i] - pe) * hop / sr < min_gap:
            continue
        ends.append(raw_e[i-1])
        starts.append(raw_s[i])
    ends.append(raw_e[-1] if raw_e else len(env)-1)
    sections = []
    for s, e in zip(starts, ends):
        if (e - s) * hop / sr >= min_dur:
            sections.append((s * hop, e * hop))
    return sections


def avg_spectrum(x, sr, n_fft=8192):
    """Compute averaged magnitude spectrum."""
    win = np.hanning(n_fft)
    hop = n_fft // 2
    specs = []
    for i in range(0, len(x) - n_fft, hop):
        specs.append(np.abs(fft.rfft(x[i:i+n_fft] * win)))
    if not specs:
        return None, None
    mag = np.mean(specs, axis=0)
    freqs = np.arange(len(mag)) * sr / n_fft
    return freqs, mag


def measure_comb(freqs, mag_dry, mag_chorus):
    """
    Measure comb filter pattern by dividing chorus spectrum by dry.
    Returns the transfer function and detected notch spacing (= 1/delay).
    """
    # Transfer function
    tf = mag_chorus / (mag_dry + 1e-10)
    tf_db = 20 * np.log10(tf + 1e-10)

    # Find notches (local minima in transfer function)
    # Smooth first to avoid noise
    win = np.hanning(15)
    win /= win.sum()
    tf_smooth = np.convolve(tf_db, win, mode='same')

    # Find local minima
    notch_indices = []
    for i in range(2, len(tf_smooth) - 2):
        if (tf_smooth[i] < tf_smooth[i-1] and tf_smooth[i] < tf_smooth[i+1]
                and tf_smooth[i] < -3):  # at least 3dB dip
            notch_indices.append(i)

    notch_freqs = freqs[notch_indices] if notch_indices else []

    # Estimate delay from notch spacing
    # For a comb filter: notches at f = (n+0.5)/delay for additive,
    # or f = n/delay for subtractive
    delay_ms = None
    if len(notch_freqs) >= 3:
        spacings = np.diff(notch_freqs)
        median_spacing = np.median(spacings)
        if median_spacing > 0:
            delay_ms = 1000.0 / median_spacing

    return tf_db, notch_freqs, delay_ms


def measure_modulation(x_L, x_R, sr):
    """
    Measure LFO modulation by tracking the instantaneous delay
    using short-time cross-correlation between L and R channels.

    Also measures modulation by tracking spectral centroid over time.
    """
    # Method 1: Track spectral centroid over time (works with noise)
    hop = 2048
    n_fft = 4096
    win = np.hanning(n_fft)

    centroids_L = []
    centroids_R = []
    times = []

    for i in range(0, min(len(x_L), len(x_R)) - n_fft, hop):
        spec_L = np.abs(fft.rfft(x_L[i:i+n_fft] * win))
        spec_R = np.abs(fft.rfft(x_R[i:i+n_fft] * win))
        freqs = np.arange(len(spec_L)) * sr / n_fft

        # Spectral centroid
        sc_L = np.sum(freqs * spec_L) / (np.sum(spec_L) + 1e-10)
        sc_R = np.sum(freqs * spec_R) / (np.sum(spec_R) + 1e-10)
        centroids_L.append(sc_L)
        centroids_R.append(sc_R)
        times.append((i + n_fft // 2) / sr)

    centroids_L = np.array(centroids_L)
    centroids_R = np.array(centroids_R)
    times = np.array(times)

    # Method 2: Track RMS power in a narrow band over time
    # The BBD comb filter sweeps, so power in any narrow band oscillates
    band_low, band_high = 2000, 3000  # Hz
    band_rms_L = []
    band_rms_R = []

    for i in range(0, min(len(x_L), len(x_R)) - n_fft, hop):
        spec_L = np.abs(fft.rfft(x_L[i:i+n_fft] * win))
        spec_R = np.abs(fft.rfft(x_R[i:i+n_fft] * win))
        freqs = np.arange(len(spec_L)) * sr / n_fft
        mask = (freqs >= band_low) & (freqs <= band_high)
        band_rms_L.append(np.sqrt(np.mean(spec_L[mask]**2)))
        band_rms_R.append(np.sqrt(np.mean(spec_R[mask]**2)))

    band_rms_L = np.array(band_rms_L)
    band_rms_R = np.array(band_rms_R)

    # Detect LFO rate from periodicity of the centroid modulation
    lfo_rate = None
    if len(centroids_L) > 10:
        # Remove DC and find dominant frequency
        c_detrend = centroids_L - np.mean(centroids_L)
        if len(c_detrend) > 0:
            # Zero-pad for resolution
            pad = max(len(c_detrend) * 4, 2048)
            c_fft = np.abs(fft.rfft(c_detrend * np.hanning(len(c_detrend)), n=pad))
            c_freqs = np.arange(len(c_fft)) * (1.0 / (times[1] - times[0])) / pad
            # Look for peak between 0.1 Hz and 15 Hz (reasonable LFO range)
            mask = (c_freqs > 0.1) & (c_freqs < 15)
            if np.any(mask):
                peak_idx = np.argmax(c_fft[mask]) + np.searchsorted(c_freqs, 0.1)
                lfo_rate = c_freqs[peak_idx]

    return {
        'times': times,
        'centroids_L': centroids_L,
        'centroids_R': centroids_R,
        'band_rms_L': band_rms_L,
        'band_rms_R': band_rms_R,
        'lfo_rate_hz': lfo_rate,
    }


def measure_stereo(x_L, x_R, sr):
    """Measure stereo relationship between L and R BBD taps."""
    # Cross-correlation to find phase relationship
    n = min(len(x_L), len(x_R))
    # Use a chunk from the middle
    chunk = min(n, sr * 2)  # 2 seconds
    start = (n - chunk) // 2
    L = x_L[start:start+chunk]
    R = x_R[start:start+chunk]

    # Correlation coefficient
    corr = np.corrcoef(L, R)[0, 1]

    # Short-time correlation to see it varying
    hop = 2048
    win_size = 4096
    st_corr = []
    st_times = []
    for i in range(0, min(len(L), len(R)) - win_size, hop):
        lw = L[i:i+win_size]
        rw = R[i:i+win_size]
        c = np.corrcoef(lw, rw)[0, 1]
        st_corr.append(c)
        st_times.append((start + i + win_size // 2) / sr)

    # L-R difference level (stereo width)
    diff = L - R
    sum_sig = L + R
    diff_rms = np.sqrt(np.mean(diff**2))
    sum_rms = np.sqrt(np.mean(sum_sig**2))
    width_db = 20 * np.log10(diff_rms / (sum_rms + 1e-10) + 1e-10)

    return {
        'correlation': corr,
        'st_corr': np.array(st_corr),
        'st_times': np.array(st_times),
        'width_db': width_db,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_chorus.py <stereo_recording.wav> [n_sections]")
        sys.exit(1)

    path = sys.argv[1]
    n_sections = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    x, sr = sf.read(path)
    print(f"Loaded: {len(x)/sr:.2f}s @ {sr}Hz, {x.ndim}D {'stereo' if x.ndim > 1 and x.shape[1] >= 2 else 'MONO'}")

    if x.ndim == 1 or x.shape[1] < 2:
        print("WARNING: File is mono. Stereo analysis will be limited.")
        print("The Juno chorus outputs two BBD taps as L/R — record in stereo!")
        x_L = x if x.ndim == 1 else x[:, 0]
        x_R = x_L.copy()
        is_stereo = False
    else:
        x_L = x[:, 0]
        x_R = x[:, 1]
        is_stereo = True

    # Find sections using mono sum
    x_mono = (x_L + x_R) / 2
    sections = find_sections(x_mono, sr)
    print(f"Found {len(sections)} sections")

    labels = ['Dry', 'Chorus I', 'Chorus II', 'Chorus I+II'][:n_sections]
    if len(sections) < n_sections:
        print(f"Warning: expected {n_sections} sections, found {len(sections)}")
        labels = labels[:len(sections)]

    section_data = []
    for i, (s, e) in enumerate(sections[:n_sections]):
        dur = (e - s) / sr
        # Use middle 80% to avoid transients
        margin = int((e - s) * 0.1)
        s_m, e_m = s + margin, e - margin
        L = x_L[s_m:e_m]
        R = x_R[s_m:e_m]
        mono = (L + R) / 2

        freqs_L, mag_L = avg_spectrum(L, sr)
        freqs_R, mag_R = avg_spectrum(R, sr)
        freqs_M, mag_M = avg_spectrum(mono, sr)

        rms = 20 * np.log10(np.sqrt(np.mean(mono**2)) + 1e-10)
        label = labels[i] if i < len(labels) else f"Section {i+1}"
        print(f"  {label}: {dur:.2f}s, RMS={rms:.1f}dBFS")

        data = {
            'label': label,
            'L': L, 'R': R, 'mono': mono,
            'freqs_L': freqs_L, 'mag_L': mag_L,
            'freqs_R': freqs_R, 'mag_R': mag_R,
            'freqs_M': freqs_M, 'mag_M': mag_M,
            'rms': rms,
        }

        # Modulation analysis for chorus sections
        if i > 0:
            mod = measure_modulation(L, R, sr)
            data['modulation'] = mod
            if mod['lfo_rate_hz']:
                print(f"    LFO rate: {mod['lfo_rate_hz']:.2f} Hz")

            if is_stereo:
                stereo = measure_stereo(L, R, sr)
                data['stereo'] = stereo
                print(f"    L/R correlation: {stereo['correlation']:.3f}, width: {stereo['width_db']:.1f}dB")

        # Comb filter analysis (compare to dry)
        if i > 0 and len(section_data) > 0:
            dry = section_data[0]
            tf_L, notches_L, delay_L = measure_comb(freqs_L, dry['mag_L'], mag_L)
            tf_R, notches_R, delay_R = measure_comb(freqs_R, dry['mag_R'], mag_R)
            data['tf_L'] = tf_L
            data['tf_R'] = tf_R
            data['notches_L'] = notches_L
            data['notches_R'] = notches_R
            data['delay_L_ms'] = delay_L
            data['delay_R_ms'] = delay_R
            if delay_L:
                print(f"    BBD delay L: ~{delay_L:.2f}ms")
            if delay_R:
                print(f"    BBD delay R: ~{delay_R:.2f}ms")

        section_data.append(data)

    # ===== PLOTS =====
    n_chorus = len(section_data) - 1  # number of chorus modes
    fig = plt.figure(figsize=(18, 5 * (3 + n_chorus)))
    gs = fig.add_gridspec(3 + n_chorus, 2, hspace=0.4, wspace=0.25)

    colors = {'Dry': '#888888', 'Chorus I': '#2196F3', 'Chorus II': '#FF5722', 'Chorus I+II': '#4CAF50'}

    # 1. Spectra comparison (L channel)
    ax = fig.add_subplot(gs[0, 0])
    for d in section_data:
        c = colors.get(d['label'], 'gray')
        ax.plot(d['freqs_L'], 20 * np.log10(d['mag_L'] + 1e-10),
                color=c, linewidth=0.7, alpha=0.8, label=d['label'] + ' L')
    ax.set_xscale('log')
    ax.set_xlim(20, sr / 2)
    ax.set_title('Spectra — Left Channel')
    ax.set_xlabel('Hz')
    ax.set_ylabel('dB')
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3, which='both')

    # 2. Spectra comparison (R channel)
    ax = fig.add_subplot(gs[0, 1])
    for d in section_data:
        c = colors.get(d['label'], 'gray')
        ax.plot(d['freqs_R'], 20 * np.log10(d['mag_R'] + 1e-10),
                color=c, linewidth=0.7, alpha=0.8, label=d['label'] + ' R')
    ax.set_xscale('log')
    ax.set_xlim(20, sr / 2)
    ax.set_title('Spectra — Right Channel')
    ax.set_xlabel('Hz')
    ax.set_ylabel('dB')
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3, which='both')

    # 3. Transfer functions (chorus vs dry)
    ax_L = fig.add_subplot(gs[1, 0])
    ax_R = fig.add_subplot(gs[1, 1])
    for d in section_data[1:]:
        c = colors.get(d['label'], 'gray')
        if 'tf_L' in d:
            freqs = section_data[0]['freqs_L']
            ax_L.plot(freqs, d['tf_L'], color=c, linewidth=0.7, alpha=0.8, label=d['label'])
            ax_R.plot(freqs, d['tf_R'], color=c, linewidth=0.7, alpha=0.8, label=d['label'])

    for ax, ch in [(ax_L, 'Left'), (ax_R, 'Right')]:
        ax.set_xscale('log')
        ax.set_xlim(20, sr / 2)
        ax.set_ylim(-20, 10)
        ax.axhline(0, color='black', linewidth=0.5)
        ax.set_title(f'Transfer Function vs Dry — {ch}')
        ax.set_xlabel('Hz')
        ax.set_ylabel('dB')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3, which='both')

    # 4. L vs R comparison for each chorus mode
    for ci, d in enumerate(section_data[1:]):
        ax = fig.add_subplot(gs[2, ci % 2] if ci < 2 else gs[2 + ci // 2, ci % 2])
        if 'tf_L' in d and 'tf_R' in d:
            freqs = section_data[0]['freqs_L']
            ax.plot(freqs, d['tf_L'], color='#2196F3', linewidth=0.7, alpha=0.8, label='Left BBD')
            ax.plot(freqs, d['tf_R'], color='#FF5722', linewidth=0.7, alpha=0.8, label='Right BBD')
            ax.set_xscale('log')
            ax.set_xlim(100, 10000)
            ax.set_ylim(-15, 10)
            ax.axhline(0, color='black', linewidth=0.5)
            ax.set_title(f'{d["label"]}: Left vs Right BBD')
            ax.set_xlabel('Hz')
            ax.set_ylabel('dB')
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3, which='both')

    # 5. Modulation over time
    for ci, d in enumerate(section_data[1:]):
        row = 3 + ci
        if row >= 3 + n_chorus:
            break
        if 'modulation' not in d:
            continue

        ax = fig.add_subplot(gs[row, 0])
        mod = d['modulation']
        ax.plot(mod['times'], mod['centroids_L'], color='#2196F3', linewidth=0.8, alpha=0.7, label='L centroid')
        ax.plot(mod['times'], mod['centroids_R'], color='#FF5722', linewidth=0.8, alpha=0.7, label='R centroid')
        ax.set_title(f'{d["label"]}: Spectral Centroid Over Time (LFO visible)')
        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Centroid (Hz)')
        lfo_str = f" — LFO: {mod['lfo_rate_hz']:.2f}Hz" if mod['lfo_rate_hz'] else ""
        ax.set_title(f'{d["label"]}: Spectral Centroid{lfo_str}')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

        # Stereo correlation over time
        if 'stereo' in d:
            ax2 = fig.add_subplot(gs[row, 1])
            st = d['stereo']
            ax2.plot(st['st_times'], st['st_corr'], color='#9C27B0', linewidth=0.8)
            ax2.axhline(st['correlation'], color='gray', linewidth=0.5, linestyle='--',
                        label=f'Mean: {st["correlation"]:.3f}')
            ax2.set_title(f'{d["label"]}: L/R Correlation Over Time')
            ax2.set_xlabel('Time (s)')
            ax2.set_ylabel('Correlation')
            ax2.set_ylim(-1, 1)
            ax2.legend(fontsize=8)
            ax2.grid(True, alpha=0.3)

    fig.suptitle('Juno Chorus Analysis — Stereo BBD Two-Tap System', fontsize=15, fontweight='bold')
    plt.tight_layout()
    plt.savefig('chorus_analysis.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nSaved: chorus_analysis.png")

    # ===== REPORT =====
    with open('chorus_report.txt', 'w') as f:
        f.write("Juno Chorus Analysis Report\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Source: {path}\n")
        f.write(f"Sample rate: {sr}Hz\n")
        f.write(f"Stereo: {is_stereo}\n")
        f.write(f"Sections: {len(section_data)}\n\n")

        for d in section_data:
            f.write(f"--- {d['label']} ---\n")
            f.write(f"  RMS: {d['rms']:.1f} dBFS\n")

            if 'delay_L_ms' in d and d['delay_L_ms']:
                f.write(f"  BBD delay L: {d['delay_L_ms']:.2f}ms\n")
            if 'delay_R_ms' in d and d['delay_R_ms']:
                f.write(f"  BBD delay R: {d['delay_R_ms']:.2f}ms\n")

            if 'modulation' in d:
                mod = d['modulation']
                if mod['lfo_rate_hz']:
                    f.write(f"  LFO rate: {mod['lfo_rate_hz']:.2f} Hz\n")
                centroid_range_L = np.ptp(mod['centroids_L'])
                centroid_range_R = np.ptp(mod['centroids_R'])
                f.write(f"  Centroid modulation range L: {centroid_range_L:.0f} Hz\n")
                f.write(f"  Centroid modulation range R: {centroid_range_R:.0f} Hz\n")

            if 'stereo' in d:
                st = d['stereo']
                f.write(f"  L/R correlation: {st['correlation']:.3f}\n")
                f.write(f"  Stereo width (S/M): {st['width_db']:.1f} dB\n")
                f.write(f"  Correlation range: {np.min(st['st_corr']):.2f} to {np.max(st['st_corr']):.2f}\n")

            if 'notches_L' in d and len(d['notches_L']) > 0:
                f.write(f"  Comb notches L (first 5): {', '.join(f'{n:.0f}Hz' for n in d['notches_L'][:5])}\n")
            if 'notches_R' in d and len(d['notches_R']) > 0:
                f.write(f"  Comb notches R (first 5): {', '.join(f'{n:.0f}Hz' for n in d['notches_R'][:5])}\n")

            f.write("\n")

        # Summary table
        f.write("\nSummary\n")
        f.write("-" * 60 + "\n")
        f.write(f"{'Mode':<15} {'LFO Hz':>8} {'Delay L':>10} {'Delay R':>10} {'L/R Corr':>10} {'Width':>8}\n")
        for d in section_data[1:]:
            lfo = f"{d['modulation']['lfo_rate_hz']:.2f}" if 'modulation' in d and d['modulation']['lfo_rate_hz'] else "—"
            dL = f"{d['delay_L_ms']:.2f}ms" if d.get('delay_L_ms') else "—"
            dR = f"{d['delay_R_ms']:.2f}ms" if d.get('delay_R_ms') else "—"
            corr = f"{d['stereo']['correlation']:.3f}" if 'stereo' in d else "—"
            width = f"{d['stereo']['width_db']:.1f}dB" if 'stereo' in d else "—"
            f.write(f"{d['label']:<15} {lfo:>8} {dL:>10} {dR:>10} {corr:>10} {width:>8}\n")

    print(f"Saved: chorus_report.txt")


if __name__ == '__main__':
    main()
