# KR-106 iPlug2 Port — Status & Next Steps

## What's Done

### Environment
- iPlug2 cloned to `~/src/iPlug2` with submodules
- Dependencies downloaded (`download-prebuilt-libs.sh`, `download-iplug-sdks.sh`)
- Project duplicated from IPlugInstrument via `duplicate.py`

### DSP Modules Ported (all in `DSP/`)
All ported as header-only C++ classes from the original `~/src/KR106/` sources:

| File | Ported From | Status |
|------|-------------|--------|
| `KR106SawOsc.h` | `libmoog/Saw.C` | Done |
| `KR106PulseOsc.h` | `libmoog/Pulse.C` | Done |
| `KR106ADSR.h` | `libmoog/ADSR.C` | Done |
| `KR106Noise.h` | `libmoog/Rand.C` | Done |
| `KR106Filter.h` | `libmoog/ResonantLowPass.C` | Done |
| `Bilinear.h` | `libmoog/bilinear.h` | Done |
| `KR106HPF.h` | `libmoog/HPF.C` + `IIR2.C` | Done |
| `KR106LFO.h` | `kr106/kr106_lfo.C` | Done |
| `KR106Delay.h` | `libmoog/Delay.C` | Done |
| `KR106Chorus.h` | `kr106/kr106_chorus.C` | Done |
| `KR106Voice.h` | `kr106/kr106_voice.C` | Done |

### Plugin Files Modified
| File | Status |
|------|--------|
| `KR106.h` | Done — 30-param enum, class declaration |
| `KR106.cpp` | Done — param defs, basic vector GUI, ProcessBlock |
| `KR106_DSP.h` | Done — 6 voices + HPF + stereo chorus orchestration |
| `config.h` | Needs PLUG_UNIQUE_ID and PLUG_MFR_ID updated |

### Not Yet Ported
- `KR106Balance` (RMS normalization via EnvelopeFollower) — deferred, non-essential for first sound
- Arpeggiator — out of scope for phase 1
- Skeuomorphic GUI — waiting for DSP to be verified working

---

## What's Next

### 1. Build the project
- Need Xcode (not just Command Line Tools) to build via `xcodebuild`
- Open `KR106.xcworkspace` in Xcode
- The DSP/ header files need to be added to the Xcode project's compile sources
- Since all DSP is header-only (included transitively via KR106_DSP.h -> KR106Voice.h -> all others), they should compile without adding them explicitly, but the `DSP/` folder needs to be in the header search paths

### 2. Fix likely compile issues
- The `DSP/` directory may need to be added to the Xcode project's header search path
- Check that `MidiSynth.h`, `SynthVoice.h` etc. are found (they're in `iPlug2/IPlug/Extras/Synth/`)
- May need to verify template instantiation of `KR106Voice<sample>`

### 3. Test first sound
- Load in a DAW or standalone app
- Play MIDI notes — should hear raw oscillators through the filter with ADSR envelope
- Verify VCF cutoff sweep, resonance, chorus modes

### 4. Tune and fix
- Compare against original KR106 source behavior
- Verify sample-rate independence at 48kHz and 96kHz
- Add Balance module if needed for filter resonance compensation

### 5. Skeuomorphic GUI (future)
- Create bitmap assets for KR-106 panel
- Replace vector controls with IBitmapControl instances

---

## Key Architecture Notes

### Signal Chain
```
Per Voice:  Pulse(-0.5) + Saw(0.5) + Sub(-0.67) + Noise
              -> VCF (4-pole resonant LPF, gain=0.1)
              -> VCA (ADSR or Gate envelope)

Global:     Sum of 6 voices -> HPF -> Stereo Chorus -> Volume -> Output
```

### Sub Oscillator Sync Direction
The sub oscillator is the MASTER — its sync output resets pulse and saw phase.
This matches the KR-106 hardware where a flip-flop divider provides the fundamental.

### VCF Cutoff Formula (from kr106_voice.C:387-428)
```
logNyq = log(sampleRate / 2)
tmp = logNyq * vcffrq
tmp += (log(kbd) + log(nyquist/32.703)) * vcfkbd
tmp += logNyq * env * vcfenv * 0.73 * envInvert
tmp += logNyq * lfo * vcflfo * 0.2
cutoff = clamp(exp(tmp) / nyquist, 20/nyquist, 0.999)
```

### PWM Routing
- Mode -1 (LFO): width = (lfo * 0.5 + 0.5) * pwmSlider
- Mode 0 (Manual): width = pwmSlider
- Mode 1 (ENV): width = envOutput * pwmSlider

### Original Source Reference
All original sources are at `~/src/KR106/` (untouched, read-only reference).
