# Roland Juno-6 Chorus — Hardware Reference & DSP Implementation Spec

## March 2026 — KR106 Project

---

## Architecture

The Juno-6 chorus is a stereo analog effect using two MN3009 256-stage Bucket-Brigade Device (BBD) delay lines driven by a single triangle-wave LFO. Both outputs are BBD-processed — there is no dry signal path through the chorus circuit. The "Mono" and "Stereo" output jacks on the Juno-6 are the two separate BBD taps, not a mono sum and stereo pair.

The LFO drives one BBD clock directly and the other through an inverting stage, producing antiphase modulation: when tap 0's delay increases, tap 1's delay decreases by the same amount. This creates the wide stereo image from a single oscillator.

Signal flow:

    Voice output → BBD tap 0 (LFO +) → Mono jack (Left)
    Voice output → BBD tap 1 (LFO −) → Stereo jack (Right)


## LFO Circuit

The LFO is built around IC13 (½ TA75558S), a standard integrator + comparator triangle oscillator. Mode switching (SW4/SW5) selects resistor values (R128 330K, R127 33K, R130 100K) to change the oscillation rate and amplitude simultaneously.

From handwritten annotations on the service schematic:

    Mode I:    triangle, 20 Vpp, 2.5 sec period (0.4 Hz)
    Mode II:   triangle, 20 Vpp, 1.5 sec period (0.67 Hz)
    Mode I+II: sine,     2.6 Vpp, 124 ms period (8 Hz)

Mode I+II is not a combination of the two chorus modes — it is a third distinct mode with its own rate and depth. At 8 Hz with low amplitude, it produces pitch vibrato rather than the sweeping chorus character of modes I and II.


## Measured Parameters (Chorus I)

Source: 496 Hz sine wave from self-oscillating VCF, recorded stereo from Mono + Stereo jacks through UMC202HD interface at 44.1 kHz.

LFO rate: 0.45 Hz (2.2 second period), confirmed triangle waveshape by template fitting (triangle RMSE 0.09 vs sine RMSE 0.20). LFO spectrum shows odd harmonics at 3× and 5× fundamental, consistent with triangle wave.

Modulation depth: ±3.2 ms (averaged across L and R channels). The L and R channels showed ±2.9 ms and ±3.4 ms respectively, but since the hardware uses a single LFO with inversion, the true depth is identical for both — the asymmetry is a measurement artifact from amplitude-dependent phase estimation reliability.

L/R phase offset: -179.2°, confirming antiphase from single inverted LFO.

BBD gain: approximately 3–5 dB above dry signal level, ratio ~1.5×.


## BBD Bandwidth

Source: noise recording (bright saw patch, filter wide open) with and without Chorus I. BBD frequency response extracted from wet/dry power spectral density ratio (Welch method, 8192-point segments).

The measured response is flat through 4 kHz with a gentle rolloff above. Key points relative to the 200–2000 Hz passband average:

    4 kHz:  -0.7 dB
    6 kHz:  -1.4 dB
    8 kHz:  -2.3 dB
    10 kHz: -3.1 dB
    12 kHz: -3.3 dB
    15 kHz: -3.5 dB

Best fit: 1-pole lowpass at 14 kHz (RMSE 0.92 dB over 2–18 kHz range). This is the combined response of the MN3009's sample-and-hold sinc rolloff, the anti-aliasing input filter, and the reconstruction output filter.

The rolloff is gentle enough that for DSP purposes, a single 1-pole TPT filter at 14 kHz per delay line accurately reproduces the measured response. The previous implementation used three filters per line (pre, modulated, post) — this was over-engineered relative to what the hardware actually does.


## Derived Parameters

Mode II has the same 20 Vpp LFO amplitude as Mode I per the schematic, so the modulation depth is the same ±3.2 ms. The rate is 0.67 Hz (1.5 second period).

Mode I+II has 2.6 Vpp, which is 0.13× of the 20 Vpp used in modes I and II. Scaling the measured ±3.2 ms depth gives ±0.42 ms. At 8 Hz, this is pitch vibrato — the delay modulation is too fast and too shallow to produce the sweeping chorus effect.

The narrower stereo width measured for Mode I+II (L/R correlation 0.73 vs 0.51–0.52 for modes I and II) is explained by the smaller delay modulation creating less L/R difference, not by a different routing topology.

Center delay is estimated at ~3 ms (nominal MN3009 chorus operating point). With 256 stages, this gives a BBD clock frequency of approximately 43 kHz and a BBD Nyquist of approximately 10.7 kHz, consistent with the measured -3 dB point at 10 kHz.


## DSP Implementation Summary

Each chorus mode requires: one triangle (or sine) LFO, two delay lines with Hermite interpolation, one 1-pole lowpass per line, and gain staging.

    LFO output → +depth for tap 0, −depth for tap 1
    delay_0 = center_delay + depth × lfo(t)
    delay_1 = center_delay − depth × lfo(t)

Parameters for all three modes:

    Mode     Rate (Hz)   Shape      Depth (ms)   Center (ms)
    I        0.45        triangle   ±3.2         3.0
    II       0.67        triangle   ±3.2         3.0
    I+II     8.0         sine       ±0.42        3.0

BBD filter: 1-pole TPT lowpass at 14 kHz on each delay line output.

BBD gain: 1.5× (applied after filtering).

No dry/wet mix — both outputs are 100% BBD. When chorus is off, the signal bypasses the BBD entirely.


## Sources

Juno-6 service schematic (chorus LFO circuit with handwritten annotations for mode parameters). Measurements from a 1982 Juno-6 recorded through Behringer UMC202HD at 44.1 kHz, March 2026. Analysis scripts: analyze_bbd_delay.py (modulation extraction), analyze_bbd_absolute.py (center delay), inline bandwidth analysis from noise recordings. All analysis used juno_lib.py shared library.


## Open Questions

Absolute center delay was not conclusively measured — the phase-based approach suffered from frequency drift between dry and chorus sections (the VCF's self-oscillation frequency shifts ~57 mHz when the chorus circuit loads the signal path). The nominal 3 ms value is inferred from the BBD Nyquist matching the measured bandwidth rolloff. A direct measurement would require DC-coupled recording or a clock frequency measurement at the MN3009 pins.

The BBD gain of ~1.5× may vary with clock frequency (gain decreases at slower clock rates due to charge leakage through more bucket transfers). This was not characterized across the modulation range.
