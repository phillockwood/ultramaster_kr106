#pragma once

#include <cmath>
#include <cstdint>

// LEVELS (calibrated April 2026):
// Calibrated against the DSP saw oscillator at -12.2 dBFS rms (single
// voice at middle C, VCA and master at 0 dB, filters open) to match
// hardware S/N ratios:
//   Dry path: 67.8 dB below signal (hw: saw -8.5, dry noise -76.3 dBFS)
//   Wet path: 48.5 dB below signal (hw: chorus on, noise -57.0 dBFS)
//
// Hardware per-band breakdown over dry baseline:
//
//   band             dry        chorus    chorus-dry
//   60 Hz           -86 dB     -77 dB     +9 dB
//   120 Hz          -89 dB     -71 dB     +18 dB
//   240 Hz          -91 dB     -81 dB     +10 dB
//   1-5 kHz         -90 dB     -69 dB     +21 dB
//   5-15 kHz        -94 dB     -66 dB     +28 dB
//   15-30 kHz       -97 dB     -64 dB     +33 dB
//
// Hardware wet noise is significantly HF-tilted; modeled here with a
// +15 dB high shelf at 5 kHz on the wet broadband generator.
//
// CAVEAT: the DSP wavetable saw has less HF content than hardware (the
// hardware analog saw extends much further into the HF band, masking
// noise that the DSP saw doesn't). For dark patches, the wet HF noise
// in the DSP may sound brighter than hardware. Default user noise
// calibration should sit around 0.7x to compensate; users wanting full
// hardware realism can scale to 1.0x.

namespace kr106 {

// ============================================================
// White noise — uniform PRNG, ±1 peak, optional 1-pole HF tilt
// ============================================================
// LCG matching the previous inline implementation. Seed each instance
// differently so parallel channels decorrelate. Two filter stages: a
// post-PRNG smoothing LPF (existing), and an optional one-pole high
// shelf for the wet-path HF noise tilt.
struct AnalogFloorNoise
{
  uint32_t mSeed = 0x12345678u;
  float mLpState = 0.f;
  float mLpCoeff = 0.f;       // PRNG smoothing LPF
  float mShelfState = 0.f;    // high-shelf state
  float mShelfCoeff = 0.f;    // shelf corner coefficient (0 = disabled)
  float mShelfGain = 0.f;     // shelf high-frequency gain - 1 (0 = flat)
  float mPink0=0, mPink1=0, mPink2=0, mPink3=0, mPink4=0, mPink5=0, mPink6=0;
  bool mPinkEnabled = false;

  void Init(float sampleRate, float cutoffHz = 20000.f)
  {
    const float fc = std::min(cutoffHz, sampleRate * 0.45f);
    mLpCoeff = 1.f - expf(-2.f * static_cast<float>(M_PI) * fc / sampleRate);
    mShelfCoeff = 0.f;
    mShelfGain = 0.f;
  }

  // Optional: enable a high-shelf to tilt the spectrum upward.
  // shelfFcHz: corner frequency of the shelf
  // hfBoostDb: boost above the shelf (e.g. 12.0 for +12 dB at HF)
  void SetHighShelf(float shelfFcHz, float hfBoostDb, float sampleRate)
  {
    const float fc = std::min(shelfFcHz, sampleRate * 0.45f);
    mShelfCoeff = 1.f - expf(-2.f * static_cast<float>(M_PI) * fc / sampleRate);
    mShelfGain  = powf(10.f, hfBoostDb / 20.f) - 1.f;
  }

  float Process()
  {
    mSeed = mSeed * 196314165u + 907633515u;
    float white = (2.f * static_cast<float>(mSeed) / static_cast<float>(0xFFFFFFFFu)) - 1.f;

    if (mPinkEnabled)
    {
      // Paul Kellet's economical pink filter (~ ±0.5 dB across audio band)
      mPink0 = 0.99886f * mPink0 + white * 0.0555179f;
      mPink1 = 0.99332f * mPink1 + white * 0.0750759f;
      mPink2 = 0.96900f * mPink2 + white * 0.1538520f;
      mPink3 = 0.86650f * mPink3 + white * 0.3104856f;
      mPink4 = 0.55000f * mPink4 + white * 0.5329522f;
      mPink5 = -0.7616f * mPink5 - white * 0.0168980f;
      float pink = mPink0 + mPink1 + mPink2 + mPink3 + mPink4 + mPink5 + mPink6 + white * 0.5362f;
      mPink6 = white * 0.115926f;

      float pinkOut = pink * 0.11f;

      if (mShelfGain != 0.f)
      {
        mShelfState += mShelfCoeff * (pinkOut - mShelfState);
        return pinkOut + mShelfGain * (pinkOut - mShelfState);
      }
      return pinkOut;
    } else
    {
      mLpState += mLpCoeff * (white - mLpState);
      if (mShelfGain != 0.f)
      {
        // High shelf = input + shelf_gain * (input - lowpass(input))
        mShelfState += mShelfCoeff * (mLpState - mShelfState);
        return mLpState + mShelfGain * (mLpState - mShelfState);
      }
      return mLpState;
    }
  }
};

// ============================================================
// Rail ripple — 120 Hz + harmonics (full-wave rectifier output)
// ============================================================
struct RailRipple
{
  float mPhase = 0.f;
  float mInc = 0.f;
  float mA1 = 0.f, mA2 = 0.f, mA3 = 0.f;

  void SetMainsHz(float mainsHz, float sampleRate)
  {
    mInc = (2.f * mainsHz) / sampleRate; // full-wave = 2× mains
  }

  void SetAmplitudes(float a1, float a2, float a3)
  {
    mA1 = a1;
    mA2 = a2;
    mA3 = a3;
  }

  void Reset() { mPhase = 0.f; }

  float Process()
  {
    mPhase += mInc;
    if (mPhase >= 1.f) mPhase -= 1.f;
    const float tp = 2.f * static_cast<float>(M_PI) * mPhase;
    return mA1 * sinf(tp) + mA2 * sinf(2.f * tp) + mA3 * sinf(3.f * tp);
  }
};

// ============================================================
// Calibrated levels (from background_noise.wav, April 2026)
// ============================================================
namespace analog_noise {

// Dry path — always on, injected pre-HPF in DSP.h.
// Calibrated to give -67.8 dB S/N below the DSP saw at typical playing
// level (-12.2 dBFS rms reference).
constexpr float kDryBroadbandGain = 1.5e-3f;

// was 1.7e-4 — compensate for HF cut
// Dry rail ripple — calibrated from hardware band measurements scaled
// to DSP saw level. Amplitudes (not rms) — RailRipple uses sin amplitude.
constexpr float kDryRipple120 = 1.8e-5f; // was 3.3e-5 (−5 dB)
constexpr float kDryRipple240 = 8.9e-6f; // was 2.6e-5 (−9 dB)
constexpr float kDryRipple360 = 6.3e-6f; // was 1.2e-5 (−6 dB)

// Wet path — chorus-on only, injected inside Chorus::Process.
// Wet broadband baseline plus a high shelf at 5 kHz reproduces the
// hardware HF tilt (+21 dB midband, +33 dB HF over dry).
constexpr float kWetBroadbandGain = 1.8e-3f;
constexpr float kWetShelfCornerHz = 3000.f;
constexpr float kWetShelfBoostDb = 6.f;

// Wet rail ripple — measured +18 dB above dry at 120 Hz, decreasing
// at higher harmonics. Injected common-mode (shared rail) into both
// wet channels.
constexpr float kWetRipple120 = 7.9e-5f; // was 1.3e-4 (−4 dB)
constexpr float kWetRipple240 = 2.2e-5f; // was 4.15e-5 (−5 dB)
constexpr float kWetRipple360 = 9.8e-6f; // was 7.3e-6 (+3 dB)

  } // namespace analog_noise
  
} // namespace kr106