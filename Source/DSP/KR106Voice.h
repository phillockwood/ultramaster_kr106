#pragma once

#include <cmath>
#include <algorithm>
#include <cstring>
#include <cstdint>

#include "KR106ADSR.h"
#include "KR106Oscillators.h"
#include "KR106VCF.h"

// Complete KR-106 voice: oscillators -> VCF -> ADSR -> VCA

namespace kr106 {

// ============================================================
// KR106Voice — complete per-voice signal chain
// ============================================================
template <typename T>
class Voice
{
public:
  // DSP modules
  Oscillators mOsc;
  VCF mVCF;
  ADSR mADSR;

  // Voice control (replaces iPlug2 mInputs ControlRamps)
  double mPitch = 0.0;      // 1V/oct relative to A440
  double mPitchBend = 0.0;  // pitch bend in octaves

  // Voice parameters (set by KR106DSP::SetParam via ForEachVoice)
  float mDcoLfo = 0.f;
  float mDcoPwm = 0.f;
  float mDcoSub = 1.f;
  float mDcoNoise = 0.f;
  float mVcfFreq = 700.f;    // Hz
  float mVcfRes = 0.f;
  float mVcfEnv = 0.f;
  float mVcfLfo = 0.f;
  float mVcfKbd = 0.f;
  float mBendDco = 0.f;
  float mBendVcf = 0.f;
  float mBendLfo = 0.f;
  float mRawBend = 0.f;      // UI bender lever horizontal [-1, +1]
  float mBenderModAmt = 0.f; // UI bender lever vertical push [0, 1]
  float mOctTranspose = 0.f; // octave shift in semitones (±12)
  bool mSawOn = true;
  bool mPulseOn = true;
  bool mSubOn = false;
  int mPwmMode = 0;      // -1=LFO, 0=MAN, 1=ENV
  int mVcfEnvInvert = 1; // 1 or -1
  int mVcaMode = 0;      // 0=ADSR, 1=Gate
  float mVelocity = 0.f; // stored from Trigger()
  T* mSyncOut = nullptr;  // scope sync output (pulse on oscillator phase reset)

  // Portamento / glide
  float mGlidePitch = -100.f;  // current glide pitch (1V/oct); -100 = uninitialized
  bool  mPortaEnabled = false;
  float mPortaRateParam = 0.f; // knob value [0,1], stored for SR-change recompute
  float mPortaCoeff = 0.f;     // per-sample smoothing coeff toward target pitch

  float mSampleRate = 44100.f;

  // Per-voice component tolerance offsets (fixed at construction).
  // Models resistor/capacitor/OTA matching tolerances in the hardware.
  float mVcfFreqOffset = 0.f;  // log-freq offset (±5% cutoff)
  float mPitchOffset = 0.f;    // octave offset (±3 cents)
  float mVcaGainScale = 1.f;   // linear gain (±0.5 dB)
  float mPwMinOffset = 0.f;    // ±0.02 around 0.50 (PW range low end)
  float mPwMaxOffset = 0.f;    // ±0.02 around 0.95 (PW range high end)

  void InitVariance(int voiceIndex)
  {
    // Deterministic LCG PRNG seeded by voice index — same offsets every
    // session, modeling one specific unit's fixed component tolerances.
    uint32_t seed = static_cast<uint32_t>(voiceIndex) * 2654435761u + 0x46756E6Bu;
    auto rng = [&seed]() -> float {
      seed = seed * 196314165u + 907633515u;
      return static_cast<float>(seed) / static_cast<float>(0xFFFFFFFF) * 2.f - 1.f;
    };

    mVcfFreqOffset = rng() * 0.05f;            // ±5% filter cutoff
    mPitchOffset = rng() * 3.f / 1200.f;       // ±3 cents (in octaves)
    mADSR.mTimeScale = 1.f + rng() * 0.08f;    // ±8% envelope timing
    mVcaGainScale = 1.f + rng() * 0.06f;       // ±0.5 dB VCA gain
    mPwMinOffset = rng() * 0.02f;              // PW min: 48–52%
    mPwMaxOffset = rng() * 0.02f;              // PW max: 93–97%
  }

  void UpdatePortaCoeff()
  {
    // Cubic mapping: knob 0→0s, 1→3s glide time constant
    float t = mPortaRateParam * mPortaRateParam * mPortaRateParam * 3.f;
    mPortaCoeff = (t > 0.001f) ? expf(-1.f / (t * mSampleRate)) : 0.f;
  }

  // Precomputed sample-rate constants (defaults for 44100 Hz)
  float mInvNyq = 1.f / 22050.f;
  float mMinCPS = 20.f / 22050.f;

  bool GetBusy() const { return mADSR.GetBusy(); }

  void SetUnisonPitch(double pitch)
  {
    mPitch = pitch;
  }

  void Trigger(double level, bool isRetrigger)
  {
    mVelocity = static_cast<float>(level);

    // Snap glide pitch if portamento is off, or voice has never been triggered
    float newPitch = static_cast<float>(mPitch);
    if (!mPortaEnabled || mGlidePitch < -10.f)
      mGlidePitch = newPitch;

    mADSR.NoteOn();
    if (!isRetrigger)
    {
      mOsc.Reset();
      mVCF.Reset();
      // Seed filter state for instant self-oscillation startup.
      // On real hardware the filter is always processing (even when VCA
      // is closed), so self-oscillation is already at full amplitude when
      // a key is pressed. Digitally, idle voices have zero state, so we
      // inject energy proportional to resonance. At res=1.0 the seed of
      // 0.3 matches the steady-state self-oscillation amplitude, giving
      // near-instant startup for patches like Glockenspiel.
      float resSeed = std::max(mVcfRes - 0.7f, 0.f) / 0.3f; // 0 at res<=0.7, 1 at res=1.0
      mVCF.mS[0] = 0.3f * resSeed;
    }
  }

  void Release()
  {
    mADSR.NoteOff();
  }

  void SetSampleRateAndBlockSize(double sampleRate, int blockSize)
  {
    (void)blockSize;
    mSampleRate = static_cast<float>(sampleRate);
    mADSR.SetSampleRate(mSampleRate);

    // Precomputed constants for VCF frequency calculation.
    // VCF modulation works in log-frequency space; these convert
    // between log-Hz and normalized cutoff (cycles per sample).
    float nyq = mSampleRate * 0.5f;
    mInvNyq = 1.f / nyq;       // Hz → normalized cutoff
    mMinCPS = 20.f * mInvNyq;  // 20 Hz floor in normalized units
 
    UpdatePortaCoeff();
  }

  void ProcessSamplesAccumulating(T** inputs, T** outputs,
    int nInputs, int nOutputs, int startIdx, int nFrames)
  {
    double pitch = mPitch;
    double pitchBend = mPitchBend;
    float velocity = mVelocity;

    // Portamento: glide mGlidePitch toward target per sample; otherwise snap once
    float targetPitch = static_cast<float>(pitch);
    float baseFreq = 0.f;
    if (!mPortaEnabled)
    {
      mGlidePitch = targetPitch;
      baseFreq = 440.f * powf(2.f, targetPitch + static_cast<float>(pitchBend));
    }

    // LFO buffer from global modulation (index 0)
    T* lfoBuffer = (nInputs > 0 && inputs[0]) ? inputs[0] : nullptr;

    for (int i = startIdx; i < startIdx + nFrames; i++)
    {
      if (mPortaEnabled)
      {
        mGlidePitch = mPortaCoeff * mGlidePitch + (1.f - mPortaCoeff) * targetPitch;
        baseFreq = 440.f * powf(2.f, mGlidePitch + static_cast<float>(pitchBend));
      }

      float lfo = lfoBuffer ? static_cast<float>(lfoBuffer[i]) : 0.f;
      float env = mADSR.Process();

      // --- Pulse width modulation ---
      float pw;
      switch (mPwmMode)
      {
        case -1: pw = mDcoPwm * (lfo + 1.f) * 0.5f; break; // LFO
        case  0: pw = mDcoPwm; break;                        // Manual
        case  1: pw = mDcoPwm * env; break;                   // ENV
        default: pw = mDcoPwm;
      }
      // Per-voice PW calibration variance (hardware component tolerance)
      float pwMin = 0.50f + mPwMinOffset;  // [0.48, 0.52]
      float pwMax = 0.95f + mPwMaxOffset;  // [0.93, 0.97]
      pw = pwMin + pw * (pwMax - pwMin);

      // --- Pitch modulation ---
      // Combined into single exp2: octave transpose + LFO + bender
      float pitchMod = mOctTranspose / 12.f
        + mPitchOffset
        + 2.f * lfo * (mDcoLfo + mBenderModAmt * mBendLfo) / 12.f
        + mRawBend * mBendDco;
      float freq = baseFreq * powf(2.f, pitchMod);
      float cps = freq / mSampleRate;

      // Safety clamp
      if (cps <= 0.f || cps >= 0.5f)
      {
        outputs[0][i] += 0.;
        if (nOutputs > 1) outputs[1][i] += 0.;
        continue;
      }

      // --- Oscillators ---
      bool sync = false;
      float oscOut = mOsc.Process(cps, pw, mSawOn, mPulseOn, mSubOn, mDcoSub, mDcoNoise, sync);

      if (sync)
      {
        if (mSyncOut) mSyncOut[i] = T(1);
      }

      // --- VCF frequency calculation ---
      // All modulation sources sum in log-frequency space, modeling voltage
      // summing into the IR3109's exponential converter.
      //
      // Scaling from Juno-6 published specs and circuit analysis:
      //   ENV:  10 octaves at max slider (invert path 1.121× normal,
      //         from IC8 gain asymmetry: R104/R99 vs R103/R98)
      //   LFO:  ±3 octaves at max slider (6 octaves total swing)
      //   KBD:  0–100% keyboard tracking (1.0 = 1V/oct)
      //   Bend: 6 octaves range (tuned independently from LFO)
      static constexpr float kEnvScale    = 6.931f;  // 10 * ln(2): 10 octaves
      static constexpr float kEnvInvScale = 7.766f;  // 10 * 1.121 * ln(2): inverted path gain asymmetry
      static constexpr float kLfoScale    = 2.079f;  // 3 * ln(2): ±3 octaves

      float envScale = (mVcfEnvInvert > 0) ? kEnvScale : kEnvInvScale;

      float vcfFrq = logf(mVcfFreq) + mVcfFreqOffset;
      vcfFrq += logf(baseFreq / 32.703f) * mVcfKbd;  // keyboard tracking: 1.0 = 100% = 1V/oct
      vcfFrq += env * mVcfEnv * envScale * float(mVcfEnvInvert);
      vcfFrq += lfo * mVcfLfo * kLfoScale;
      vcfFrq += 4.15888f * mRawBend * mBendVcf;  // bender (6 oct range, tuned separately)

      // Clamped to [20 Hz, 0.975 × Nyquist]: hardware range is 4 Hz–40 kHz,
      // but at 44.1 kHz the upper bound is Nyquist-limited to ~21.5 kHz.
      // At higher sample rates (96k+) the full 40 kHz range is available.
      float vcfCPS = expf(vcfFrq) * mInvNyq;
      vcfCPS = std::clamp(vcfCPS, mMinCPS, 0.975f);

      float filtered = mVCF.Process(oscOut, vcfCPS, mVcfRes);

      float signal = filtered;

      // --- VCA ---
      float vcaOut;
      if (mVcaMode)
        vcaOut = signal * mADSR.mGateEnv * velocity * mVcaGainScale; // Gate mode
      else
        vcaOut = signal * env * velocity * mVcaGainScale;              // ADSR mode

      // Accumulate mono (chorus does stereo later)
      outputs[0][i] += static_cast<T>(vcaOut);
      if (nOutputs > 1) outputs[1][i] += static_cast<T>(vcaOut);
    }
  }
};

} // namespace kr106
