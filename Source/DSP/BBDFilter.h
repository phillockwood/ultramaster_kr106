#pragma once

#include <cmath>

// ============================================================
// BBDFilter — 2nd-order Butterworth biquad (TPT SVF) + TPT
// 1-pole lowpass, matched to the Juno-6/60 chorus prefilter.
//
// Replaces the original 4x cascaded TPT 1-pole design whose
// pole frequencies (4020/7234/8830/10620 Hz) were derived from
// isolated 1/(2piRC) calculations. The actual transistor circuit
// (2SA1015 PNP emitter followers, ±15V) has very different
// behavior because the emitter followers' low output impedance
// (~43 ohms) makes the shunt caps transparent. The real response
// has a sharp Butterworth-like knee, not a gradual 4-pole rolloff.
//
// ngspice simulation confirms Juno-6 and Juno-60 prefilters
// produce identical frequency response despite different biasing:
//   -3 dB at 9,661 Hz
//   Flat passband through 5 kHz (< 0.3 dB ripple)
//   -22 dB/octave stopband slope (12–20 kHz)
//
// Best fit: 2nd-order Butterworth (Q=0.707) at 9,661 Hz + 1-pole
// at 20,000 Hz. Error vs ngspice: ±0.5 dB from DC to 15 kHz.
//
//   Freq    ngspice   Model    Error
//   5 kHz   -0.3 dB   -0.2 dB   +0.1
//   10 kHz  -3.5 dB   -3.5 dB    0.0
//   12 kHz  -7.5 dB   -7.0 dB   +0.5
//   15 kHz  -14.0 dB  -14.3 dB  -0.3
// ============================================================
struct BBDFilter
{
  // Cutoff — from ngspice simulation of Juno-6 and Juno-60
  // prefilter circuits (both produce identical AC response).
  static constexpr float kBiquadFc = 9661.f;
  static constexpr float kBiquadQ  = 0.7071f;   // Butterworth
  static constexpr float kPoleFc   = 20000.f;    // HF tilt pole

  // --- TPT SVF biquad (2nd-order lowpass) ---
  struct SVFBiquad
  {
    float mIC1eq = 0.f;  // integrator 1 state
    float mIC2eq = 0.f;  // integrator 2 state

    void Reset() { mIC1eq = mIC2eq = 0.f; }

    void SetState(float value)
    {
      mIC1eq = 0.f;
      mIC2eq = value;
    }

    float Process(float input, float g, float a1)
    {
      float v3 = input - mIC2eq;
      float v1 = a1 * mIC1eq + a1 * g * v3;
      float v2 = mIC2eq + g * v1;
      mIC1eq = 2.f * v1 - mIC1eq;
      mIC2eq = 2.f * v2 - mIC2eq;
      return v2;  // lowpass output
    }
  };

  // --- TPT 1-pole lowpass ---
  struct TPT1
  {
    float mS = 0.f;

    void Reset() { mS = 0.f; }

    void SetState(float value) { mS = value; }

    float Process(float input, float g)
    {
      float v = (input - mS) * g / (1.f + g);
      float lp = mS + v;
      mS = lp + v;
      return lp;
    }
  };

  SVFBiquad mBiquad;
  TPT1 mPole;
  float mG_bq  = 0.f;   // biquad integrator gain
  float mA1_bq = 0.f;   // biquad feedback coefficient
  float mG_p   = 0.f;   // 1-pole integrator gain

  void Init(float sampleRate)
  {
    // Biquad coefficients
    float fc = std::min(kBiquadFc, sampleRate * 0.45f);
    mG_bq = tanf(static_cast<float>(M_PI) * fc / sampleRate);
    mA1_bq = 1.f / (1.f + mG_bq / kBiquadQ + mG_bq * mG_bq);

    // 1-pole coefficient
    float fc_p = std::min(kPoleFc, sampleRate * 0.45f);
    mG_p = tanf(static_cast<float>(M_PI) * fc_p / sampleRate);

    Reset();
  }

  void Reset()
  {
    mBiquad.Reset();
    mPole.Reset();
  }

  void SetState(float value)
  {
    mBiquad.SetState(value);
    mPole.SetState(value);
  }

  float Process(float input)
  {
    float x = mBiquad.Process(input, mG_bq, mA1_bq);
    x = mPole.Process(x, mG_p);
    return x;
  }
};
