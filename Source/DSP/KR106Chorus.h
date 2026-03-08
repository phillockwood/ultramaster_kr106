#pragma once

#include <cmath>
#include <algorithm>
#include <vector>

// KR-106 BBD Chorus Emulation
//
// Models the MN3009 bucket-brigade device (256 stages) with:
// - Hermite-interpolated variable delay line
// - Clock-rate-dependent bandwidth filter (the core BBD characteristic)
// - Fixed 15kHz pre/post anti-aliasing and reconstruction filters
// - Mild analog saturation
// - Two independent triangle LFOs for stereo spread
//
// Modes (from hardware):
//   I:   0.513 Hz triangle, ±0.5ms depth, 180° stereo offset
//   II:  0.863 Hz triangle, ±1.1ms depth, 180° stereo offset
//   I+II: tap0 at Chorus I rate, tap1 at Chorus II rate (independent)

namespace kr106 {

// ============================================================
// Triangle LFO for chorus modulation
// ============================================================
struct ChorusLFO
{
  float mPhase = 0.f; // [0, 1)
  float mInc = 0.f;   // phase increment per sample

  void SetRate(float hz, float sampleRate)
  {
    mInc = hz / sampleRate;
  }

  void Reset() { mPhase = 0.f; }

  void SetPhase(float p)
  {
    mPhase = p;
    if (mPhase >= 1.f) mPhase -= 1.f;
    if (mPhase < 0.f) mPhase += 1.f;
  }

  // Returns [-1, +1] triangle wave
  float Process()
  {
    mPhase += mInc;
    if (mPhase >= 1.f) mPhase -= 1.f;
    // Triangle: peak at phase=0 and 1, trough at 0.5
    return 1.f - 4.f * fabsf(mPhase - 0.5f);
  }
};

// ============================================================
// 1-pole TPT lowpass filter
// ============================================================
struct TPT1
{
  float mS = 0.f; // integrator state

  void Reset() { mS = 0.f; }

  // g = tan(pi * fc / sr), precomputed by caller
  float Process(float input, float g)
  {
    float v = (input - mS) * g / (1.f + g);
    float lp = mS + v;
    mS = lp + v;
    return lp;
  }
};

// ============================================================
// BBD delay line — one complete signal path
// ============================================================
struct BBDLine
{
  static constexpr int kNumStages = 256; // MN3009
  static constexpr float kFixedFilterHz = 15000.f;

  // Delay buffer (power-of-2 for bitmask wrapping)
  std::vector<float> mBuf;
  int mMask = 0;
  int mWPos = 0;

  // Fixed pre/post filters (15 kHz)
  TPT1 mPreLPF;
  TPT1 mPostLPF;
  float mFixedG = 0.f; // precomputed g for 15 kHz

  // Modulated BBD-bandwidth filter (1-pole TPT, ~-6dB/oct)
  float mBBD_S1 = 0.f;

  float mSampleRate = 44100.f;

  void Init(float sampleRate)
  {
    mSampleRate = sampleRate;

    // Buffer size: enough for max delay (~10ms) + margin for interpolation
    int minLen = static_cast<int>(sampleRate * 0.012f) + 4;
    int len = 1;
    while (len < minLen) len <<= 1;
    mBuf.assign(len, 0.f);
    mMask = len - 1;
    mWPos = 0;

    // Precompute fixed filter coefficient
    float fc = std::min(kFixedFilterHz, sampleRate * 0.45f);
    mFixedG = tanf(static_cast<float>(M_PI) * fc / sampleRate);

    mPreLPF.Reset();
    mPostLPF.Reset();
    mBBD_S1 = 0.f;
  }

  void Clear()
  {
    std::fill(mBuf.begin(), mBuf.end(), 0.f);
    mWPos = 0;
    mPreLPF.Reset();
    mPostLPF.Reset();
    mBBD_S1 = 0.f;
  }

  // 4-point Hermite (Catmull-Rom) interpolation
  static float Hermite(float frac, float y0, float y1, float y2, float y3)
  {
    float c0 = y1;
    float c1 = 0.5f * (y2 - y0);
    float c2 = y0 - 2.5f * y1 + 2.f * y2 - 0.5f * y3;
    float c3 = 0.5f * (y3 - y0) + 1.5f * (y1 - y2);
    return ((c3 * frac + c2) * frac + c1) * frac + c0;
  }

  float ReadHermite(float delaySamples) const
  {
    float rPos = static_cast<float>(mWPos) - delaySamples;
    if (rPos < 0.f) rPos += static_cast<float>(mMask + 1);

    int i1 = static_cast<int>(rPos);
    float frac = rPos - static_cast<float>(i1);

    float y0 = mBuf[(i1 - 1) & mMask];
    float y1 = mBuf[i1 & mMask];
    float y2 = mBuf[(i1 + 1) & mMask];
    float y3 = mBuf[(i1 + 2) & mMask];

    return Hermite(frac, y0, y1, y2, y3);
  }

  float Process(float input, float delaySamples)
  {
    // 1. Fixed pre-filter (anti-aliasing, 15kHz)
    float filtered = mPreLPF.Process(input, mFixedG);

    // 2. Write to delay buffer
    mBuf[mWPos & mMask] = filtered;

    // 3. Read with Hermite interpolation
    float wet = ReadHermite(delaySamples);

    // 4. Advance write position
    mWPos = (mWPos + 1) & mMask;

    // 5. BBD-bandwidth modulated lowpass (1-pole TPT)
    //    cutoff = BBD Nyquist = kNumStages / (4 * delay_seconds)
    //    Single pole (~-6dB/oct) matches the gentle BBD rolloff;
    //    combined with pre/post 15kHz filters gives ~-18dB/oct total.
    float delaySec = delaySamples / mSampleRate;
    if (delaySec < 1e-6f) delaySec = 1e-6f;
    float bbdNyquist = static_cast<float>(kNumStages) / (4.f * delaySec);
    float nyq = mSampleRate * 0.45f;
    float cutoff = std::min(bbdNyquist, nyq);
    float gBBD = tanf(static_cast<float>(M_PI) * cutoff / mSampleRate);

    float v1 = (wet - mBBD_S1) * gBBD / (1.f + gBBD);
    float lp1 = mBBD_S1 + v1;
    mBBD_S1 = lp1 + v1;
    wet = lp1;

    // 7. Fixed post-filter (reconstruction, 15kHz)
    wet = mPostLPF.Process(wet, mFixedG);

    // NaN guard
    if (!(mBBD_S1 > -100.f && mBBD_S1 < 100.f)) mBBD_S1 = 0.f;

    return wet;
  }
};

// ============================================================
// KR-106 Stereo Chorus — drop-in replacement
// ============================================================
struct Chorus
{
  BBDLine mLine0, mLine1;   // two BBD taps
  ChorusLFO mLFO0, mLFO1;  // two independent LFOs
  int mMode = 0;            // 0=off, 1=I, 2=II, 3=I+II
  float mSampleRate = 44100.f;

  // Hardware-measured constants
  static constexpr float kCenterDelayMs = 3.5f;
  static constexpr float kChorusIRate   = 0.513f; // Hz
  static constexpr float kChorusIDepth  = 0.5f;   // ms (half-swing)
  static constexpr float kChorusIIRate  = 0.863f;  // Hz
  static constexpr float kChorusIIDepth = 1.1f;   // ms (half-swing)
  static constexpr float kDryMix = 0.4f;
  static constexpr float kWetMix = 0.6f;
  static constexpr float kMakeupGain = 1.2f; // compensate comb filter energy loss
  static constexpr float kFadeMs = 5.f;      // crossfade duration for mode switching

  // Smoothed depths (avoids clicks on mode-to-mode transitions)
  float mDepth0 = 0.f, mDepth1 = 0.f;
  float mTargetDepth0 = 0.f, mTargetDepth1 = 0.f;

  // Crossfade (0 = dry, 1 = chorus)
  float mFade = 0.f;
  float mFadeTarget = 0.f;
  float mFadeInc = 0.f; // per-sample increment

  void Init(float sampleRate)
  {
    mSampleRate = sampleRate;
    mLine0.Init(sampleRate);
    mLine1.Init(sampleRate);
    mLFO0.Reset();
    mLFO1.Reset();

    mFadeInc = 1.f / (kFadeMs * 0.001f * sampleRate);

    // Configure for current mode
    if (mMode > 0)
    {
      ConfigureLFOs();
      UpdateDepthTargets();
      mDepth0 = mTargetDepth0;
      mDepth1 = mTargetDepth1;
      mFade = mFadeTarget = 1.f;
    }
  }

  void Clear()
  {
    mLine0.Clear();
    mLine1.Clear();
    mLFO0.Reset();
    mLFO1.Reset();
  }

  void SetMode(int newMode)
  {
    if (newMode == mMode) return;

    int oldMode = mMode;
    mMode = newMode;

    if (mMode == 0)
    {
      // Fade out — keep processing until fade completes
      mFadeTarget = 0.f;
      return;
    }

    // Coming from off: clear delay lines for clean start
    if (oldMode == 0)
    {
      mLine0.Clear();
      mLine1.Clear();
      mLFO0.Reset();
      mLFO1.Reset();
    }

    ConfigureLFOs();
    UpdateDepthTargets();
    mFadeTarget = 1.f;
  }

  void Process(float input, float& outL, float& outR)
  {
    // Advance crossfade
    if (mFade < mFadeTarget)
      mFade = std::min(mFade + mFadeInc, mFadeTarget);
    else if (mFade > mFadeTarget)
      mFade = std::max(mFade - mFadeInc, mFadeTarget);

    // Fully dry — skip chorus processing
    if (mFade <= 0.f)
    {
      outL = outR = input;
      return;
    }

    // Smooth depth toward target (~5ms)
    mDepth0 += (mTargetDepth0 - mDepth0) * mFadeInc;
    mDepth1 += (mTargetDepth1 - mDepth1) * mFadeInc;

    float lfo0 = mLFO0.Process();
    float lfo1 = mLFO1.Process();

    float delay0ms = kCenterDelayMs + mDepth0 * lfo0;
    float delay1ms = kCenterDelayMs + mDepth1 * lfo1;

    float delay0samp = delay0ms * 0.001f * mSampleRate;
    float delay1samp = delay1ms * 0.001f * mSampleRate;

    float wet0 = mLine0.Process(input, delay0samp);
    float wet1 = mLine1.Process(input, delay1samp);

    float chorusL = kMakeupGain * (kDryMix * input + kWetMix * wet0);
    float chorusR = kMakeupGain * (kDryMix * input + kWetMix * wet1);

    // Op-amp output stage saturation
    chorusL = tanhf(chorusL);
    chorusR = tanhf(chorusR);

    // Crossfade between dry and chorus
    outL = input + mFade * (chorusL - input);
    outR = input + mFade * (chorusR - input);
  }

private:
  void UpdateDepthTargets()
  {
    switch (mMode)
    {
      case 1: mTargetDepth0 = mTargetDepth1 = kChorusIDepth; break;
      case 2: mTargetDepth0 = mTargetDepth1 = kChorusIIDepth; break;
      case 3: mTargetDepth0 = kChorusIDepth; mTargetDepth1 = kChorusIIDepth; break;
    }
  }

  void ConfigureLFOs()
  {
    switch (mMode)
    {
      case 1: // Chorus I: both at I rate, 180° apart
        mLFO0.SetRate(kChorusIRate, mSampleRate);
        mLFO1.SetRate(kChorusIRate, mSampleRate);
        mLFO1.SetPhase(mLFO0.mPhase + 0.5f);
        break;
      case 2: // Chorus II: both at II rate, 180° apart
        mLFO0.SetRate(kChorusIIRate, mSampleRate);
        mLFO1.SetRate(kChorusIIRate, mSampleRate);
        mLFO1.SetPhase(mLFO0.mPhase + 0.5f);
        break;
      case 3: // I+II: independent rates
        mLFO0.SetRate(kChorusIRate, mSampleRate);
        mLFO1.SetRate(kChorusIIRate, mSampleRate);
        break;
    }
  }
};

} // namespace kr106
