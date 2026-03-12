#!/usr/bin/env python3
"""
juno_lib — Shared library for Juno synthesizer audio analysis.

Provides reusable building blocks for:
  - Audio I/O and envelope extraction
  - Note and section detection
  - Exponential / RC curve fitting
  - Harmonic and spectral analysis
  - Phase tracking and LFO extraction
  - Plotting helpers
  - CSV / report output

Usage:
    from juno_lib import audio, notes, fitting, spectral, phase, plotting, report
"""

import sys
import numpy as np
import soundfile as sf
import scipy.fft as fft
import scipy.signal as signal
from scipy.optimize import curve_fit, minimize_scalar
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


# ============================================================
# audio — loading, envelope, RMS
# ============================================================

class audio:
    @staticmethod
    def load(path, mono=True):
        """Load WAV, return (data, sr). If mono=True, mix to mono."""
        x, sr = sf.read(path)
        if mono and x.ndim > 1:
            x = x.mean(axis=1)
        return x, sr

    @staticmethod
    def load_stereo(path):
        """Load WAV, return (L, R, sr). Raises if mono."""
        x, sr = sf.read(path)
        if x.ndim == 1 or x.shape[1] < 2:
            raise ValueError("File is mono, need stereo")
        return x[:, 0], x[:, 1], sr

    @staticmethod
    def envelope(x, sr, hop=64, smooth_win=7):
        """
        RMS envelope with Hanning smoothing.

        Returns (env, hop) where env is in amplitude units,
        and time in seconds = index * hop / sr.
        """
        n_frames = len(x) // hop
        env = np.zeros(n_frames)
        for i in range(n_frames):
            frame = x[i * hop:(i + 1) * hop]
            env[i] = np.sqrt(np.mean(frame ** 2))
        if smooth_win > 1:
            win = np.hanning(smooth_win)
            win /= win.sum()
            env = np.convolve(env, win, mode='same')
        return env, hop

    @staticmethod
    def rms(x):
        return np.sqrt(np.mean(x ** 2))

    @staticmethod
    def db(x):
        return 20 * np.log10(np.abs(x) + 1e-10)

    @staticmethod
    def env_time(env, hop, sr):
        """Time array in seconds for an envelope."""
        return np.arange(len(env)) * hop / sr

    @staticmethod
    def env_time_ms(env, hop, sr):
        """Time array in milliseconds for an envelope."""
        return np.arange(len(env)) * hop / sr * 1000


# ============================================================
# notes — detecting note boundaries and sections
# ============================================================

class notes:
    @staticmethod
    def find(env, sr, hop, threshold_db=30, min_gap_s=0.15, min_dur_s=0.1):
        """
        Find note boundaries from an RMS envelope.

        Args:
            env: RMS envelope array
            sr: sample rate
            hop: envelope hop size in samples
            threshold_db: dB below peak to set the on/off threshold
            min_gap_s: minimum silence between notes (seconds)
            min_dur_s: minimum note duration (seconds)

        Returns:
            List of (start_frame, end_frame) tuples in envelope-frame indices.
        """
        env_db = 20 * np.log10(env + 1e-10)
        pk = np.max(env_db)
        above = env_db > (pk - threshold_db)
        trans = np.diff(above.astype(int))
        raw_starts = list(np.where(trans == 1)[0])
        raw_ends = list(np.where(trans == -1)[0])

        if not raw_starts:
            return []

        starts, ends = [raw_starts[0]], []
        for i in range(1, len(raw_starts)):
            pe = raw_ends[i - 1] if i - 1 < len(raw_ends) else raw_starts[i] - 1
            gap_s = (raw_starts[i] - pe) * hop / sr
            if gap_s < min_gap_s:
                continue
            ends.append(raw_ends[i - 1])
            starts.append(raw_starts[i])
        ends.append(raw_ends[-1] if raw_ends else len(env) - 1)

        return [(s, e) for s, e in zip(starts, ends)
                if (e - s) * hop / sr >= min_dur_s]

    @staticmethod
    def find_sample_boundaries(x, sr, threshold_db=25, min_gap_s=0.15):
        """
        Find note boundaries, return as sample indices (not envelope frames).
        Useful for waveform-level analysis (fit_tau, fit_tau_harmonics).
        """
        hop = 256
        env = np.array([np.sqrt(np.mean(x[i:i + hop] ** 2))
                        for i in range(0, len(x) - hop, hop)])
        env_db = 20 * np.log10(env + 1e-10)
        pk = np.max(env_db)
        above = env_db > (pk - threshold_db)
        trans = np.diff(above.astype(int))
        raw_s = list(np.where(trans == 1)[0])
        raw_e = list(np.where(trans == -1)[0])

        if not raw_s:
            return []

        starts, ends = [raw_s[0]], []
        for i in range(1, len(raw_s)):
            pe = raw_e[i - 1] if i - 1 < len(raw_e) else raw_s[i] - 1
            if (raw_s[i] - pe) * hop / sr < min_gap_s:
                continue
            ends.append(raw_e[i - 1])
            starts.append(raw_s[i])
        ends.append(raw_e[-1] if raw_e else len(env) - 1)

        return [(s * hop, e * hop) for s, e in zip(starts, ends)]

    @staticmethod
    def find_sections(x_mono, sr, min_gap=0.2, min_dur=0.5):
        """
        Find sections separated by silence (for chorus, multi-part recordings).
        Returns list of (start_sample, end_sample) tuples.
        """
        hop = 512
        env = np.array([np.sqrt(np.mean(x_mono[i:i + hop] ** 2))
                        for i in range(0, len(x_mono) - hop, hop)])
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
            pe = raw_e[i - 1] if i - 1 < len(raw_e) else raw_s[i] - 1
            if (raw_s[i] - pe) * hop / sr < min_gap:
                continue
            ends.append(raw_e[i - 1])
            starts.append(raw_s[i])
        ends.append(raw_e[-1] if raw_e else len(env) - 1)

        return [(s * hop, e * hop) for s, e in zip(starts, ends)
                if (e - s) * hop / sr >= min_dur]

    @staticmethod
    def slider_args(argv, default_start=0, default_step=1):
        """
        Parse common slider CLI args: script.py file [slider_start] [slider_step]
        Returns (slider_start, slider_step).
        """
        start = int(argv[2]) if len(argv) > 2 else default_start
        step = int(argv[3]) if len(argv) > 3 else default_step
        return start, step

    @staticmethod
    def slider_value(index, start, step):
        """Slider position for note at given index."""
        return start + index * step


# ============================================================
# fitting — exponential and RC curve models
# ============================================================

class fitting:
    """Curve fitting models for envelope and waveform analysis."""

    # --- Decay/release models (amplitude decreasing) ---

    @staticmethod
    def fit_decay_models(t, env, sustain_floor=0):
        """
        Fit multiple decay models to a normalized decay envelope.

        Args:
            t: time array (seconds), starting at 0
            env: normalized amplitude (1.0 = peak, decaying toward sustain_floor)
            sustain_floor: target floor (0 for release, >0 for decay to sustain)

        Returns:
            dict of {name: {params, rms, fitted_t, fitted_v, label, tau_ms}}
            plus 'best' key with name of lowest-RMS fit.
        """
        if len(t) < 4:
            return {'best': None}

        fits = {}
        best_name, best_rms = None, 1e6
        tau_guess = t[len(t) // 2] if len(t) > 0 else 0.1

        # Model 1: Simple exponential
        def exp_decay(t, tau):
            return np.exp(-t / max(tau, 1e-6))

        try:
            popt, _ = curve_fit(exp_decay, t, env, p0=[tau_guess],
                                bounds=([1e-5], [30]), maxfev=5000)
            fitted = exp_decay(t, *popt)
            rms = np.sqrt(np.mean((env - fitted) ** 2))
            fits['exp'] = {
                'params': popt, 'rms': rms,
                'fitted_t': t, 'fitted_v': fitted,
                'tau_ms': popt[0] * 1000,
                'label': f'exp (τ={popt[0] * 1000:.1f}ms)',
            }
            if rms < best_rms:
                best_rms, best_name = rms, 'exp'
        except Exception:
            pass

        # Model 2: Exponential with offset
        def exp_decay_off(t, tau, amp, offset):
            return amp * np.exp(-t / max(tau, 1e-6)) + offset

        try:
            popt, _ = curve_fit(exp_decay_off, t, env,
                                p0=[tau_guess, 1.0, sustain_floor],
                                bounds=([1e-5, 0.1, -0.2], [30, 2.0, 0.5]),
                                maxfev=5000)
            fitted = exp_decay_off(t, *popt)
            rms = np.sqrt(np.mean((env - fitted) ** 2))
            fits['exp_off'] = {
                'params': popt, 'rms': rms,
                'fitted_t': t, 'fitted_v': fitted,
                'tau_ms': popt[0] * 1000,
                'label': f'exp+off (τ={popt[0] * 1000:.1f}ms, off={popt[2]:.2f})',
            }
            if rms < best_rms:
                best_rms, best_name = rms, 'exp_off'
        except Exception:
            pass

        # Model 3: Exponential with power
        def exp_power(t, tau, power):
            return np.exp(-np.power(t / max(tau, 1e-6), max(power, 0.1)))

        try:
            popt, _ = curve_fit(exp_power, t, env,
                                p0=[tau_guess, 1.0],
                                bounds=([1e-5, 0.1], [30, 5.0]),
                                maxfev=5000)
            fitted = exp_power(t, *popt)
            rms = np.sqrt(np.mean((env - fitted) ** 2))
            fits['exp_power'] = {
                'params': popt, 'rms': rms,
                'fitted_t': t, 'fitted_v': fitted,
                'tau_ms': popt[0] * 1000,
                'label': f'exp^p (τ={popt[0] * 1000:.1f}ms, p={popt[1]:.2f})',
            }
            if rms < best_rms:
                best_rms, best_name = rms, 'exp_power'
        except Exception:
            pass

        fits['best'] = best_name
        return fits

    # --- Attack models (amplitude increasing) ---

    @staticmethod
    def fit_attack_models(t, env):
        """
        Fit attack curve models to a normalized attack envelope.

        Args:
            t: time array (seconds), starting at 0
            env: normalized amplitude (0→1)

        Returns:
            dict of {name: {params, rms, fitted, label, tau_ms}}
            plus 'best' key.
        """
        if len(t) < 3:
            return {'best': None}

        fits = {}
        best_name, best_rms = None, 1e6

        # Linear
        def linear(t, a, b):
            return np.clip(a * t + b, 0, 1.2)

        try:
            popt, _ = curve_fit(linear, t, env,
                                p0=[1.0 / max(t[-1], 0.001), 0], maxfev=5000)
            fitted = linear(t, *popt)
            rms = np.sqrt(np.mean((env - fitted) ** 2))
            fits['linear'] = {
                'params': popt, 'rms': rms, 'fitted': fitted,
                'tau_ms': None,
                'label': f'Linear (slope={popt[0]:.1f}/s)',
            }
            if rms < best_rms:
                best_rms, best_name = rms, 'linear'
        except Exception:
            pass

        # RC charge: 1 - exp(-t/tau)
        def rc_charge(t, tau, amp, offset):
            return np.clip(amp * (1.0 - np.exp(-t / max(tau, 1e-6))) + offset, 0, 1.5)

        try:
            tau_guess = t[-1] / 3 if len(t) > 0 else 0.01
            popt, _ = curve_fit(rc_charge, t, env,
                                p0=[tau_guess, 1.0, 0.0],
                                bounds=([1e-5, 0.1, -0.5], [10, 2.0, 0.5]),
                                maxfev=5000)
            fitted = rc_charge(t, *popt)
            rms = np.sqrt(np.mean((env - fitted) ** 2))
            fits['rc'] = {
                'params': popt, 'rms': rms, 'fitted': fitted,
                'tau_ms': popt[0] * 1000,
                'label': f'RC (τ={popt[0] * 1000:.1f}ms)',
            }
            if rms < best_rms:
                best_rms, best_name = rms, 'rc'
        except Exception:
            pass

        # RC charge with power
        def rc_power(t, tau, power, amp, offset):
            x = 1.0 - np.exp(-t / max(tau, 1e-6))
            return np.clip(amp * np.power(x, max(power, 0.1)) + offset, 0, 1.5)

        try:
            tau_guess = t[-1] / 3 if len(t) > 0 else 0.01
            popt, _ = curve_fit(rc_power, t, env,
                                p0=[tau_guess, 1.0, 1.0, 0.0],
                                bounds=([1e-5, 0.1, 0.1, -0.5], [10, 5.0, 2.0, 0.5]),
                                maxfev=5000)
            fitted = rc_power(t, *popt)
            rms = np.sqrt(np.mean((env - fitted) ** 2))
            fits['rc_power'] = {
                'params': popt, 'rms': rms, 'fitted': fitted,
                'tau_ms': popt[0] * 1000,
                'label': f'RC^p (τ={popt[0] * 1000:.1f}ms, p={popt[1]:.2f})',
            }
            if rms < best_rms:
                best_rms, best_name = rms, 'rc_power'
        except Exception:
            pass

        fits['best'] = best_name
        return fits

    @staticmethod
    def best_tau_ms(fits):
        """Extract tau in ms from the best fit in a fits dict."""
        name = fits.get('best')
        if name and name in fits:
            return fits[name].get('tau_ms')
        return None

    # --- Threshold crossing measurements ---

    @staticmethod
    def crossing_time(env, t, threshold, direction='down'):
        """
        Find first time where env crosses threshold.

        direction='down': first sample <= threshold (decay)
        direction='up':   first sample >= threshold (attack)
        """
        if direction == 'down':
            for i, v in enumerate(env):
                if v <= threshold:
                    return t[i]
        else:
            for i, v in enumerate(env):
                if v >= threshold:
                    return t[i]
        return None

    @staticmethod
    def time_between(env, t, high, low, direction='down'):
        """
        Time in ms between two threshold crossings.
        For decay: high→low (e.g. 0.9→0.1).
        For attack: low→high (e.g. 0.1→0.9).
        """
        if direction == 'down':
            t_high = fitting.crossing_time(env, t, high, 'down')
            t_low = fitting.crossing_time(env, t, low, 'down')
        else:
            t_high = fitting.crossing_time(env, t, low, 'up')
            t_low = fitting.crossing_time(env, t, high, 'up')

        if t_high is not None and t_low is not None:
            return abs(t_low - t_high) * 1000  # ms
        return None

    # --- RC waveform model (for oscillator curvature fitting) ---

    @staticmethod
    def rc_saw_cycle(fund_hz, sr, tau_seconds):
        """
        Generate one cycle of RC-curved saw, DC blocked and normalized.
        Returns normalized waveform array.
        """
        spc = int(sr / fund_hz)
        cps = fund_hz / sr
        tau_samples = tau_seconds * sr
        alpha = 1.0 / (cps * tau_samples)
        exp_neg_alpha = np.exp(-alpha)
        rc_norm = 1.0 / (1.0 - exp_neg_alpha)

        pos = np.arange(spc) / spc
        curved = (1.0 - np.exp(-pos * alpha)) * rc_norm
        saw = 2.0 * curved - 1.0
        saw -= np.mean(saw)
        saw /= np.max(np.abs(saw)) + 1e-10
        return saw

    @staticmethod
    def sweep_tau(error_fn, log_range=(-5, -1), n_coarse=400):
        """
        Sweep tau values, find best, then refine with bounded minimization.

        Args:
            error_fn: callable(tau_seconds) -> error
            log_range: (log10_min, log10_max) for coarse sweep
            n_coarse: number of coarse sweep points

        Returns:
            (best_tau_seconds, coarse_taus, coarse_errors)
        """
        taus = np.logspace(log_range[0], log_range[1], n_coarse)
        errors = [error_fn(t) for t in taus]
        best_idx = np.argmin(errors)
        coarse_tau = taus[best_idx]

        result = minimize_scalar(
            error_fn,
            bounds=(coarse_tau * 0.2, coarse_tau * 5),
            method='bounded',
        )
        return result.x, taus, errors


# ============================================================
# spectral — FFT, harmonics, filter tracking
# ============================================================

class spectral:
    @staticmethod
    def avg_spectrum(x, sr, n_fft=8192):
        """
        Compute averaged magnitude spectrum over overlapping windows.
        Returns (freqs, mag).
        """
        win = np.hanning(n_fft)
        hop = n_fft // 2
        specs = []
        for i in range(0, len(x) - n_fft, hop):
            specs.append(np.abs(fft.rfft(x[i:i + n_fft] * win)))
        if not specs:
            return None, None
        mag = np.mean(specs, axis=0)
        freqs = np.arange(len(mag)) * sr / n_fft
        return freqs, mag

    @staticmethod
    def find_fundamental(x, sr, start_sample=None, n_fft=8192, min_f=20, max_f=15000):
        """
        Find fundamental frequency from FFT peak.
        If start_sample given, uses that offset; otherwise uses middle of signal.
        """
        if start_sample is None:
            start_sample = len(x) // 4
        avail = len(x) - start_sample
        n = min(n_fft, 2 ** int(np.floor(np.log2(max(256, avail)))))
        if n < 256 or avail < n:
            return None

        mag = np.abs(fft.rfft(x[start_sample:start_sample + n] * np.hanning(n)))
        freqs = np.arange(len(mag)) * sr / n
        mask = (freqs > min_f) & (freqs < max_f)
        if not np.any(mask):
            return None
        idx = np.argmax(mag[mask]) + np.searchsorted(freqs, min_f)
        return freqs[idx]

    @staticmethod
    def measure_harmonics(x, sr, start, end, n_avg=4, max_harmonics=80):
        """
        Measure harmonic amplitudes relative to fundamental.

        Returns (fund_hz, harmonics_dict, mag_spectrum) or (None, None, None).
        harmonics_dict: {harmonic_number: dB_relative_to_fundamental}
        """
        dur = (end - start) / sr
        ss = start + int(min(0.05, dur * 0.15) * sr)
        avail = end - ss
        nf = min(8192, 2 ** int(np.floor(np.log2(max(256, avail)))))
        if nf < 256 or avail < nf:
            return None, None, None

        specs = []
        for i in range(n_avg):
            off = ss + i * (nf // 2)
            if off + nf > end:
                break
            specs.append(np.abs(fft.rfft(x[off:off + nf] * np.hanning(nf))))
        if not specs:
            return None, None, None

        mag = np.mean(specs, axis=0)
        freqs = np.arange(len(mag)) * sr / nf

        # Find fundamental
        mask = (freqs > 20) & (freqs < 15000)
        fi = np.argmax(mag[mask]) + np.searchsorted(freqs, 20)
        fund = freqs[fi]
        fund_amp = mag[fi]

        harmonics = {}
        for n in range(1, max_harmonics + 1):
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

    @staticmethod
    def even_odd_ratios(harmonics, max_n=30):
        """
        Compute even/odd harmonic level differences.
        Returns list of (even_harmonic_number, ratio_dB).
        """
        ratios = []
        for n in range(2, max_n, 2):
            if n not in harmonics:
                continue
            odds = []
            if (n - 1) in harmonics:
                odds.append(harmonics[n - 1])
            if (n + 1) in harmonics:
                odds.append(harmonics[n + 1])
            if not odds:
                continue
            ratios.append((n, harmonics[n] - np.mean(odds)))
        return ratios

    @staticmethod
    def spectral_centroid(mag, freqs):
        s = np.sum(mag)
        return np.sum(freqs * mag) / s if s > 1e-10 else 0


# ============================================================
# phase — phase tracking, LFO extraction (for chorus/BBD)
# ============================================================

class phase:
    @staticmethod
    def extract(audio_1d, sr, freq, bandwidth_ratio=0.08):
        """
        Extract unwrapped phase and amplitude envelope via Hilbert transform
        after narrow bandpass around freq.

        Returns (unwrapped_phase, amplitude_envelope).
        """
        bw = max(freq * bandwidth_ratio, 8)
        lo = max(freq - bw, 5)
        hi = min(freq + bw, sr / 2 - 1)
        sos = signal.butter(6, [lo, hi], btype='band', fs=sr, output='sos')
        filtered = signal.sosfiltfilt(sos, audio_1d)
        analytic = signal.hilbert(filtered)
        return np.unwrap(np.angle(analytic)), np.abs(analytic)

 # ---- Block-based phase (causal, no sosfiltfilt) ----
    @staticmethod
    def block_phase(sig, sr, freq, block_ms=10.0):
        """
        Causal block-based phase measurement via quadrature DFT.
        Uses absolute-time references to remove carrier phase — output
        is residual phase only (constant for a pure tone, modulated by
        delay changes). Safe across discontinuities (no sosfiltfilt).
        Returns (block_center_times, unwrapped_residual_phase, amplitude).
        """
        omega = 2 * np.pi * freq
        period = sr / freq
        n_periods = max(2, round(block_ms / 1000 * freq))
        block_len = int(round(n_periods * period))
        hop = block_len // 2

        n_blocks = (len(sig) - block_len) // hop + 1
        times = np.zeros(n_blocks)
        phases = np.zeros(n_blocks)
        amps = np.zeros(n_blocks)
        win = np.hanning(block_len)
        win_sum = np.sum(win)

        for i in range(n_blocks):
            s = i * hop
            t_abs = (s + np.arange(block_len)) / sr
            cos_ref = np.cos(omega * t_abs)
            sin_ref = np.sin(omega * t_abs)
            block = sig[s:s + block_len] * win
            I = 2 * np.sum(block * cos_ref) / win_sum
            Q = 2 * np.sum(block * sin_ref) / win_sum
            phases[i] = np.arctan2(Q, I)
            amps[i] = np.sqrt(I**2 + Q**2)
            times[i] = (s + block_len / 2) / sr

        return times, np.unwrap(phases), amps
        
    @staticmethod
    def extract_lfo(data, sr, max_lfo_freq=5.0):
        """Lowpass filter to isolate LFO modulation."""
        sos = signal.butter(4, max_lfo_freq, btype='low', fs=sr, output='sos')
        return signal.sosfiltfilt(sos, data)

    @staticmethod
    def measure_lfo_frequency(lfo, sr):
        """Estimate LFO frequency from zero crossings. Returns (freq_hz, n_cycles)."""
        centered = lfo - np.mean(lfo)
        crossings = np.where(np.diff(np.sign(centered)))[0]
        if len(crossings) < 4:
            return 0.0, 0
        periods = np.diff(crossings[::2]) / sr
        freq = 1.0 / np.median(periods) if len(periods) > 0 else 0.0
        return freq, len(crossings) // 2

    @staticmethod
    def classify_lfo_shape(lfo, sr):
        """
        Classify LFO as triangle or sine by fitting both.
        Returns (shape_str, metrics_dict).
        """
        norm = lfo - np.mean(lfo)
        peak = np.max(np.abs(norm))
        if peak < 1e-12:
            return "flat", {}
        norm = norm / peak

        freq, _ = phase.measure_lfo_frequency(lfo, sr)
        if freq <= 0:
            return "unknown", {}

        t = np.arange(len(norm)) / sr
        best_tri, best_sin = np.inf, np.inf
        for phi_idx in range(200):
            phi = 2 * np.pi * phi_idx / 200
            tri_err = np.mean((norm - signal.sawtooth(2 * np.pi * freq * t + phi, width=0.5)) ** 2)
            sin_err = np.mean((norm - np.sin(2 * np.pi * freq * t + phi)) ** 2)
            best_tri = min(best_tri, tri_err)
            best_sin = min(best_sin, sin_err)

        ratio = best_tri / best_sin if best_sin > 0 else 1.0
        metrics = {'fit_ratio': ratio, 'tri_rmse': np.sqrt(best_tri), 'sin_rmse': np.sqrt(best_sin)}

        if ratio < 0.7:
            shape = "triangle"
        elif ratio < 0.9:
            shape = "triangle (rounded)"
        elif ratio < 1.1:
            shape = "ambiguous"
        else:
            shape = "sine"
        return shape, metrics

    @staticmethod
    def find_fundamental_autocorr(mono, sr, expected_range=(100, 2000)):
        """Find fundamental via autocorrelation (good for clean tones)."""
        chunk_len = min(len(mono), sr)
        start = min(int(sr * 0.5), len(mono) // 4)
        chunk = mono[start:start + chunk_len]
        chunk = chunk * np.hanning(len(chunk))
        corr = np.correlate(chunk, chunk, mode='full')
        corr = corr[len(corr) // 2:]
        corr = corr / corr[0]
        min_lag = int(sr / expected_range[1])
        max_lag = int(sr / expected_range[0])
        search = corr[min_lag:max_lag]
        peak_lag = min_lag + np.argmax(search)
        return sr / peak_lag


# ============================================================
# plotting — shared matplotlib helpers
# ============================================================

class plotting:
    # Standard color palette
    BLUE = '#2196F3'
    ORANGE = '#FF5722'
    GREEN = '#4CAF50'
    PURPLE = '#9C27B0'
    GRAY = '#888888'

    FIT_COLORS = {
        'linear': '#FF5722',
        'exp': '#4CAF50',
        'exp_off': '#FF5722',
        'exp_power': '#9C27B0',
        'rc': '#4CAF50',
        'rc_power': '#9C27B0',
    }

    @staticmethod
    def grid(n_items, max_cols=4):
        """
        Create a subplot grid for n_items.
        Returns (fig, axes_flat) with unused axes hidden.
        """
        cols = min(max_cols, n_items)
        rows = max(1, (n_items + cols - 1) // cols)
        fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 4 * rows), squeeze=False)
        af = axes.flatten()
        for i in range(n_items, len(af)):
            af[i].set_visible(False)
        return fig, af

    @staticmethod
    def save(fig, path, title=None, dpi=150):
        """Set suptitle, tight_layout, save, close."""
        if title:
            fig.suptitle(title, fontsize=14, fontweight='bold')
        plt.tight_layout()
        fig.savefig(path, dpi=dpi, bbox_inches='tight')
        plt.close(fig)
        print(f"Saved: {path}")

    @staticmethod
    def mapping_plot(sliders, series, path, title='Slider Mapping',
                     ylabel='Time (ms)'):
        """
        Standard 2-panel (linear + log) mapping plot.

        series: list of (values, style_dict, label) where style_dict
                has keys like color, marker, linestyle.
        """
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))

        for vals, style, label in series:
            axes[0].plot(sliders, vals, label=label, **style)
            axes[1].semilogy(sliders, [max(v, 0.1) for v in vals], label=label, **style)

        for ax, scale in zip(axes, ['linear', 'log']):
            ax.set_xlabel('Slider Position')
            ax.set_ylabel(ylabel)
            ax.set_title(f'{title} ({scale})')
            ax.legend()
            ax.grid(True, alpha=0.3, which='both' if scale == 'log' else 'major')

        plotting.save(fig, path, title)

    @staticmethod
    def hlines(ax, *levels):
        """Draw light horizontal reference lines."""
        for lvl in levels:
            ax.axhline(lvl, color='gray', linewidth=0.3, linestyle=':')


# ============================================================
# report — CSV and text report generation
# ============================================================

class report:
    @staticmethod
    def csv(path, header, rows):
        """
        Write a CSV file.

        header: list of column name strings
        rows: list of lists/tuples (values)
        """
        with open(path, 'w') as f:
            f.write(','.join(header) + '\n')
            for row in rows:
                f.write(','.join(str(v) for v in row) + '\n')
        print(f"Saved: {path}")

    @staticmethod
    def txt(path, lines):
        """Write a text report from a list of strings."""
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')
        print(f"Saved: {path}")

    @staticmethod
    def fmt(val, suffix='ms', precision=1, width=10):
        """Format a nullable numeric value for display."""
        if val is None:
            return f"{'n/a':>{width}}"
        return f"{val:.{precision}f}{suffix}".rjust(width)

    @staticmethod
    def fmt_csv(val, precision=2):
        """Format a nullable numeric value for CSV."""
        if val is None:
            return ""
        return f"{val:.{precision}f}"

    @staticmethod
    def table_header(cols, widths=None):
        """
        Format a table header + separator.

        cols: list of (name, width) or just names with default width 10
        Returns two strings: header line and separator line.
        """
        if widths is None:
            widths = [10] * len(cols)
        header = ''.join(f"{c:>{w}}" for c, w in zip(cols, widths))
        sep = ''.join(f"{'─' * (w - 2):>{w}}" for w in widths)
        return header, sep
