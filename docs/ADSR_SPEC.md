# Roland Juno-6 ADSR Envelope Generator — Hardware Reference & DSP Implementation Spec

## March 2026 — KR106 Project

---

## Architecture

The Juno-6 envelope generator uses the Roland IR3R01 custom analog IC. No datasheet exists for this chip. It was used across several Roland instruments and has been cloned by AMSynths (https://amsynths.co.uk/2019/05/09/roland-ir3r01-clone/). The Juno-6 circuit uses a 47nF timing capacitor and +7.5V reference voltage.

The IR3R01 is a purely analog envelope generator. This is a key distinction from the Juno-106, which replaced it with a software envelope computed by the NEC D7811G CPU and output through an 8-bit DAC at ~200µs update rate. The Juno-6's analog envelope has continuous output with no stepping artifacts.

The envelope controls a BA662 OTA-based VCA. In ENV mode, the IR3R01 output drives the VCA control input. In GATE mode, the ADSR is bypassed and the key gate signal goes directly to the VCA.


## Envelope Shape — All Stages Are RC

Every stage of the IR3R01 envelope is an RC curve: a capacitor charging or discharging through a variable resistance toward a target voltage. This was confirmed by measurement: the attack stage fits a pure RC charge with power exponent 0.99 (measured across six slider positions). Decay and release fit exponential-with-offset models (RC discharge toward a nonzero target).

The RC model for all stages:

    output += (target - output) * coefficient

Where coefficient = 1 - exp(-1 / (tau * sampleRate)), and tau is the RC time constant set by the slider position.

This is the same one-pole lowpass topology for every stage — only the target value and time constant change between attack, decay, and release.


## Attack

The attack stage charges the capacitor toward a voltage above the comparator threshold. When the envelope crosses 1.0 (normalized), the IR3R01 switches to the decay stage. The charge target is above 1.0 so that the exponential asymptote doesn't prevent the envelope from reaching the threshold in finite time.

Measured curve shape: RC charge, power exponent 0.99 (effectively pure RC). Consistent across all slider positions tested.

Published spec range: 2 ms to 3 seconds.

DSP model:

    target = 1.2  (overshoot ensures arrival at 1.0)
    mEnv += (1.2 - mEnv) * mAttackCoeff
    when mEnv >= 1.0: transition to decay

Slider-to-tau mapping (exponential):

    tau = 0.002 * pow(3.0 / 0.002, slider)

Where slider is 0.0 to 1.0. This gives tau = 2ms at slider 0, tau = 3s at slider 10.


## Decay

The decay stage discharges the capacitor toward the sustain voltage. Since a pure RC exponential asymptotically approaches its target but never reaches it, the circuit effectively arrives when the output is close enough that the remaining difference is below audible significance.

For the DSP model, an undershoot target slightly below the sustain level ensures the exponential crosses the sustain threshold in finite time, allowing a clean state transition.

Published spec range: 2 ms to 12 seconds (same circuit as release).

DSP model:

    undershoot = -0.1
    mEnv += (mSustain + undershoot - mEnv) * mDecayCoeff
    when mEnv <= mSustain: clamp to mSustain, transition to sustain

Slider-to-tau mapping:

    tau = 0.002 * pow(4.0 / 0.002, slider)

Where slider is 0.0 to 1.0. This gives tau = 2ms at slider 0, tau = 4s at slider 10. At 3 tau the envelope reaches ~95% of its target, so 3 × 4s = 12s matches the published spec.


## Sustain

Sustain is not a separate circuit state in the IR3R01 — it is the decay stage at equilibrium. The capacitor has discharged to the sustain voltage and the circuit holds it there.

If the sustain voltage changes while a note is held (the player moves the slider), the envelope tracks toward the new sustain level using the same RC time constant as the decay stage. This was confirmed by recording: setting sustain from 0 to 10 mid-note produces an exponential rise at the decay rate, and setting sustain from 10 to 0 produces an exponential fall at the same rate. The rise and fall are symmetric — same time constant in both directions — because the capacitor charges and discharges through the same resistor toward the new target.

DSP model:

    mEnv += (mSustain - mEnv) * mDecayCoeff

No directional logic, no asymmetric rates, no clamping. The RC equation inherently tracks in both directions and cannot overshoot.


## Release

The release stage begins when the key is released (gate goes low). The capacitor discharges toward zero through the release time constant. Like decay, an undershoot target below zero ensures finite completion.

Published spec range: 2 ms to 12 seconds (same circuit as decay).

DSP model:

    target = -0.1
    mEnv += (target - mEnv) * mReleaseCoeff
    when mEnv < 0.00001: set to 0, mark finished

Slider-to-tau mapping: same formula as decay.


## Gate Mode

When the Juno-6 VCA switch is set to GATE instead of ENV, the ADSR is bypassed. The gate signal drives the BA662 VCA control input directly. The VCA is not a perfect switch — the BA662 OTA has inherent control port capacitance that rounds the edges slightly, approximately 0.5–2 ms.

DSP model: linear ramp over 32 samples (~0.73 ms at 44100 Hz).

## Comparison: Juno-6 vs Juno-106

The Juno-106 replaced the IR3R01 analog envelope with a software implementation in the NEC D7811G CPU. Key differences:

The Juno-106 attack is a linear ramp (digital increment per update cycle), not an RC charge. The Juno-6 attack is concave (RC), reaching the midpoint at ~67% of the total time. The Juno-106 attack reaches the midpoint at exactly 50%.

The Juno-106 decay/release use a multiplicative model: env *= multiplier each update cycle. This produces a different curve shape than the RC model — specifically, the time to reach the sustain level is independent of the sustain level. In the Juno-6's RC model, decay to sustain=0.5 is faster than decay to sustain=0.01 at the same slider setting, because the exponential covers less distance.

The Juno-106 DAC updates at ~200 µs intervals (4.2 ms cycle across all CV channels), producing visible stepping in the envelope at fast settings. The Juno-6 analog output is continuous.


## Sources

Measurements from a 1982 Juno-6, recorded through Behringer UMC202HD (later MOTU M2) at 44.1 kHz. Attack curve shape measured across six slider positions using Python/librosa/scipy envelope extraction. Decay/release time constants measured from recordings with sustain set to ~25% for visible target level. Sustain tracking confirmed by recording with ADSR 0/0/0/0, then changing D and S mid-note. AMSynths IR3R01 clone article for chip-level details. Juno-106 comparison from NEC D7811G firmware analysis and existing C reference implementation (juno_synth.c).

Analysis scripts: analyze_attack.py, analyze_decay.py, analyze_decay_release.py, fit_tau.py, fit_tau_harmonics.py. All using juno_lib.py shared library.
