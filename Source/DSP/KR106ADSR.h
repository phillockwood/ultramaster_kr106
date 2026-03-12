#pragma once

#include <algorithm>
#include <cmath>

namespace kr106 {

// ============================================================
// ADSR Envelope — models the IR3R01 OTA envelope generator
// ============================================================
// Juno-6 mode (mJ6Mode = true):
//   All stages are pure RC curves from the IR3R01 analog EG.
//   Attack charges toward 1.2 (comparator overshoot), decay/release
//   discharge toward undershoot targets to ensure finite completion.
//   Slider→tau mapped by exponential formula from measured hardware.
//
// Juno-106 mode (mJ6Mode = false):
//   Attack is a linear ramp (D7811G digital EG approximation).
//   Decay/release are fixed exponential multipliers toward 0.
//   Slider→ms mapped by 128-entry LUTs.
struct ADSR
{
  enum State { kAttack, kDecay, kSustain, kRelease, kFinished };
  static constexpr float kGateSlope       = 1.f / 32.f;
  static constexpr float kMinLevel        = 0.001f;  // -60dB: calibrates 106-mode decay/release
  static constexpr float kSilence         = 1e-5f;   // -100dB: release termination threshold
  static constexpr float kAttackTarget    = 1.2f;    // RC charge overshoot (hardware comparator)
  static constexpr float kDecayUndershoot = -0.1f;   // below sustain (ensures finite decay)
  static constexpr float kReleaseTarget   = -0.1f;   // below zero (ensures finite release)

  State mState = kFinished;
  float mEnv = 0.f;
  float mGateEnv = 0.f;
  bool  mJ6Mode = false;       // true = Juno-6 RC curves, false = Juno-106 digital

  // Juno-106 mode coefficients
  float mAttackRate = 0.f;     // linear per-sample increment
  float mDecayRate = 0.f;      // linear rate (for sustain tracking)
  float mDecayMul = 1.f;       // fixed exponential multiplier (toward 0)
  float mReleaseMul = 1.f;     // fixed exponential multiplier (toward 0)

  // Juno-6 mode coefficients (one-pole RC)
  float mAttackCoeff = 0.f;
  float mDecayCoeff = 0.f;
  float mReleaseCoeff = 0.f;

  float mSustain = 1.f;
  float mSampleRate = 44100.f;
  float mTimeScale = 1.f;      // per-voice component tolerance

  void SetSampleRate(float sr) { mSampleRate = sr; }

  // --- Juno-106 setters (ms-based, from LUT) ---

  void SetAttack(float ms)
  {
    mAttackRate = 1000.f / (ms * mTimeScale * mSampleRate);
  }

  void SetDecay(float ms)
  {
    mDecayRate = 1000.f / (ms * mTimeScale * mSampleRate);
    mDecayMul = expf(logf(kMinLevel) * mDecayRate);
  }

  void SetRelease(float ms)
  {
    float releaseRate = 1000.f / (ms * mTimeScale * mSampleRate);
    mReleaseMul = expf(logf(kMinLevel) * releaseRate);
  }

  // --- Juno-6 setters (tau in seconds, from exponential formula) ---

  void SetAttackTau(float tauSeconds)
  {
    mAttackCoeff = 1.f - expf(-1.f / (tauSeconds * mTimeScale * mSampleRate));
  }

  void SetDecayTau(float tauSeconds)
  {
    mDecayCoeff = 1.f - expf(-1.f / (tauSeconds * mTimeScale * mSampleRate));
  }

  void SetReleaseTau(float tauSeconds)
  {
    mReleaseCoeff = 1.f - expf(-1.f / (tauSeconds * mTimeScale * mSampleRate));
  }

  void SetSustain(float s) { mSustain = s; }

  void NoteOn() { mState = kAttack; }
  void NoteOff() { mState = kRelease; }

  bool GetBusy() const { return mState != kFinished || mGateEnv > 0.f; }

  float Process()
  {
    switch (mState)
    {
      case kAttack:
        if (mJ6Mode)
          mEnv += (kAttackTarget - mEnv) * mAttackCoeff;
        else
          mEnv += mAttackRate;
        mGateEnv += kGateSlope;
        if (mEnv >= 1.f)
          mState = kDecay;
        break;

      case kDecay:
        if (mJ6Mode)
          mEnv += (mSustain + kDecayUndershoot - mEnv) * mDecayCoeff;
        else
          mEnv *= mDecayMul;
        mGateEnv += kGateSlope;
        if (mEnv <= mSustain)
        {
          mEnv = mSustain;
          mState = kSustain;
        }
        break;

      case kSustain:
        if (mJ6Mode)
        {
            mEnv += (mSustain - mEnv) * mDecayCoeff;
        }
        else
        {
          if (mEnv < mSustain)
          {
            mEnv += 3.f * mDecayRate;
            if (mEnv > mSustain) mEnv = mSustain;
          }
          else if (mEnv > mSustain)
          {
            mEnv *= mDecayMul;
            if (mEnv < mSustain) mEnv = mSustain;
          }
        }
        break;

      case kRelease:
        mGateEnv -= kGateSlope;
        if (mJ6Mode)
          mEnv += (kReleaseTarget - mEnv) * mReleaseCoeff;
        else
          mEnv *= mReleaseMul;
        if (mEnv < kSilence)
        {
          mEnv = 0.f;
          mState = kFinished;
        }
        break;

      case kFinished:
        mGateEnv -= kGateSlope;
        break;
    }

    mGateEnv = std::clamp(mGateEnv, 0.f, 1.f);
    return mEnv;
  }
};

} // namespace kr106
