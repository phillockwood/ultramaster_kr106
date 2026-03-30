# VCF Modulation Budget

## Common to All Three Synths

- All use the IR3109 exponential converter (J106 has it inside the A1QH80017A combo IC)
- All have CPU-generated DCO pitch from ROM lookup tables
- VCF calibration target: 248 Hz self-oscillation, max resonance, max KBD tracking
- C4 is the KBD tracking zero point on J60 and J106 (no pitch modulation at C4)
- C1 is the KBD tracking zero point on J6

## What We Actually Know Per Model

### J106 (confirmed from ROM disassembly + service manual)

- 1 octave = 1143 DAC counts (confirmed: C4 = 248 Hz, C6 = 992 Hz, ratio = 4x = 2 octaves over 2286 DAC counts)
- kBaseFreq = 5.53 Hz at DAC 0 (derived from ROM calibration patch byte 49)
- DAC range: 0-16383 (14-bit) = 14.3 octaves
- Calibration: VCF byte 49, DAC 6272, 248 Hz self-oscillation, max res, max KBD
- KBD zero point: C4 (261.6 Hz)
- VCF slider: byte 0-127, dac = byte * 128

### J60 (from service manual, partial)

- Calibration: 248 Hz self-oscillation at VCF slider 3/10, max res, max KBD
- KBD zero point: C4 (no pitch change at C4)
- VCF Freq pot: 50KB linear, no loading network
- Counts/octave: NOT confirmed -- assumed same as J106 (same IR3109 chip)
- Base freq at slider 0: unknown (estimated ~28 Hz, but this depends on the second anchor point which we don't have)
- Oct/unit: unknown (need circuit trace or second frequency measurement)

### J6 (from hardware measurements)

- Calibration: 248 Hz self-oscillation at slider 5.5/10 (measured on hardware)
- KBD zero point: C1 (32.7 Hz)
- VCF Freq pot: 50KB linear + 100K series R (creates loading-induced taper)
- Counts/octave: NOT confirmed from service manual
- Circuit model: I(x) = (15*x + 11) / (x*(1-x)*50K + 100K), f = 2^(-12.0674 + 116879.07*I)

## J106 Modulation Ranges (from firmware)

All modulation sources sum into a single 14-bit DAC value before the expo converter.

| Source               | DAC range      | Octaves     | Spec       | Notes |
|----------------------|----------------|-------------|------------|-------|
| VCF Freq slider      | 0-16256        | 14.2        |            | byte 0-127, dac = byte * 128 |
| Env mod (max)        | 0-16255        | 14.2        | 14 oct     | slider*254 * env>>8; 2x finer resolution than VCF slider but same max range |
| LFO mod (+-max)      | +-4047         | +-3.5       | +-3.5 oct  | (lfoDepth*delayEnv>>8) * lfoVal>>9 |
| Bender (+-max)       | +-4064         | +-3.6       | +-3.5 oct  | bendSens * bendVal >> 4 |
| KBD track (C2-C7)    | +3429 / -2286  | +3.0 / -2.0 | +3/-2 oct  | pitch*0.375 relative to C4, 1:1 at max |

Note: The slider at max (byte 127) passes 50 kHz at slider 9.2/10 (byte 117).
At 44.1 kHz sample rate, the digital filter hits Nyquist before the IR3109
saturation model matters, so the tanh compression has no practical effect.

## J106 DAC Frequency Table

| DAC   | Octaves | Hz       | Note |
|-------|---------|----------|------|
| 0     | 0.0     | 5.5      | min  |
| 1143  | 1.0     | 11.1     |      |
| 2286  | 2.0     | 22.1     |      |
| 3429  | 3.0     | 44.2     |      |
| 4572  | 4.0     | 88.5     |      |
| 5715  | 5.0     | 177.0    |      |
| 6272  | 5.5     | 248.1    | cal point (byte 49) |
| 6858  | 6.0     | 353.9    |      |
| 8001  | 7.0     | 707.8    |      |
| 9144  | 8.0     | 1415.7   |      |
| 10287 | 9.0     | 2831.4   |      |
| 11430 | 10.0    | 5662.7   |      |
| 12573 | 11.0    | 11325    |      |
| 13716 | 12.0    | 22651    |      |
| 14859 | 13.0    | 45302    |      |
| 16383 | 14.3    | 105692   | above Nyquist at 44.1 kHz |

## Filter IC Comparison

|                  | Juno-6          | Juno-60         | Juno-106                      |
|------------------|-----------------|-----------------|-------------------------------|
| Filter IC        | IR3109          | IR3109 (same)   | A1QH80017A (IR3109+BA662)     |
| Range (spec)     | 4 Hz - 40 kHz   | not stated      | 5 Hz - 50 kHz                 |
| Cal point        | 248 Hz @ slider 5.5 | 248 Hz @ slider 3 | 248 Hz @ VCF byte 49     |
| VCF Freq pot     | 50KB + 100K series R | 50KB linear | N/A (firmware)               |
| KBD reference    | C1 (32.7 Hz)    | C4 (261.6 Hz)   | C4 (261.6 Hz)                |
| Oct/octave confirmed | No          | No              | Yes (C4/C6 = 1143 DAC/oct)   |

## J60 VCF Freq -- What's Missing

We only know one point on the J60 VCF curve (slider 0.3 = 248 Hz).
To fully characterize it we need either:

1. **Circuit trace:** Resistor values from VR22 pot wiper to IR3109 summing node,
   plus bias voltages. This gives us the CV gain and offset directly.
2. **KBD tracking verification:** If the J60 service manual has a second frequency
   at a different note (like J106's C6 = 992 Hz), that anchors the oct/unit.
3. **Second slider measurement:** Any other known slider position = known frequency.

Previous estimate (slider 0.3 = 248 Hz, slider 1.0 = 40 kHz) gave ~28 Hz base
and 10.5 oct/unit, but the 40 kHz assumption is unverified.
