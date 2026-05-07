#pragma once

#include <cmath>

// ============================================================
// J60 HPF — 4-position switched (CD4051B selects capacitor)
//
// Circuit: signal -> 1M to GND (DC bias) -> C (switched) ->
//   470K to GND + 38K series -> 10µF NP -> uPC1252 VCA (30K input Z)
//
// R_eff = 470K || (38K + 30K_VCA) = 59.4K
// First-order HPF, -6 dB/oct slope.
//
// Frequencies derived from ngspice AC simulation with 30K VCA
// load (uPC1252H2 input impedance).
//
// Position 0: FLAT (bypass, no capacitor in path)
// Position 1: C=.022µF  -> fc = 122 Hz
// Position 2: C=.01µF   -> fc = 269 Hz
// Position 3: C=.0047µF -> fc = 571 Hz
// ============================================================
inline float getJuno60HPFFreq(int position)
{
  switch (position)
  {
    case 0:  return 0.f;     // FLAT (bypass)
    case 1:  return 122.f;   // .022µF, ngspice: 122 Hz
    case 2:  return 269.f;   // .01µF,  ngspice: 269 Hz
    case 3:  return 571.f;   // .0047µF, ngspice: 571 Hz
    default: return 0.f;
  }
}

// ============================================================
// J106 HPF — 4-position switched (CD4051B selects capacitor)
//
// Circuit: C (switched) -> 1M to GND -> 47K series ->
//   inverting op amp with 47K feedback (gain = -1)
//
// R_eff = 1M || 47K = 44.9K (op amp virtual ground loads 47K)
// First-order HPF, -6 dB/oct slope.
//
// Position 0: C=.0047µF -> fc = 754 Hz
// Position 1: C=.015µF  -> fc = 236 Hz
// Position 2: FLAT (bypass)
// Slider positions (UI order, bottom to top):
//   0: Bass boost (+9.4 dB low shelf)
//   1: Flat (bypass)
//   2: HPF ~236 Hz  (CD4051 pin 1: C=.015µF)
//   3: HPF ~754 Hz  (CD4051 pin 0: C=.0047µF)
// ============================================================
inline float getJuno106HPFFreq(int position)
{
  switch (position)
  {
    case 0:  return -1.f;    // Bass boost (negative signals HPF::Process to use biquad)
    case 1:  return 0.f;     // FLAT (bypass)
    case 2:  return 236.f;   // .015µF
    case 3:  return 754.f;   // .0047µF
    default: return 0.f;
  }
}

// ============================================================
// J6 HPF — continuous pot (measured PCHIP interpolation)
//
// 11-point curve measured from hardware Juno-6.
// Input: slider position 0–1
// Output: HPF cutoff frequency in Hz (38.6 – 1394.2 Hz)
//
// The J6 uses a continuous potentiometer to vary the HPF
// cutoff, unlike the J60/J106 which use switched capacitors.
// ============================================================
inline float getJuno6HPFFreqPCHIP(float x)
{
  static const float y[] = {
    38.6f, 83.5f, 181.3f, 394.7f, 418.4f,
    437.1f, 455.8f, 605.5f, 988.6f, 1183.2f, 1394.2f
  };
  static constexpr int N = 11;
  static constexpr float h = 0.1f;

  if (x <= 0.0f) return y[0];
  if (x >= 1.0f) return y[N - 1];

  float x_scaled = x * 10.0f;
  int i = (int)x_scaled;
  if (i >= N - 1) i = N - 2;
  float t = x_scaled - (float)i;

  auto get_slope = [&](int idx) -> float {
    if (idx <= 0 || idx >= N - 1) return 0.0f;
    float d_prev = (y[idx] - y[idx - 1]) / h;
    float d_next = (y[idx + 1] - y[idx]) / h;
    if (d_prev * d_next <= 0.0f) return 0.0f;
    return 2.0f / (1.0f / d_prev + 1.0f / d_next);
  };

  float m_i = get_slope(i);
  float m_next = get_slope(i + 1);

  float t2 = t * t;
  float t3 = t2 * t;
  float h00 = 2.0f * t3 - 3.0f * t2 + 1.0f;
  float h10 = t3 - 2.0f * t2 + t;
  float h01 = -2.0f * t3 + 3.0f * t2;
  float h11 = t3 - t2;

  return h00 * y[i] + h10 * h * m_i + h01 * y[i + 1] + h11 * h * m_next;
}

// Juno-106 HPF position 0: Bass Boost
//
// Two-stage circuit + inverting summer:
//   Stage 1: passive RC. R1(47K)||C1(.047µF) in series from input to
//            NodeA. CA(.01µF) from NodeA to GND. NodeA → 47K → +IN of U2.
//   Stage 2: U2 non-inverting op amp. Rg(10K) from -IN to GND.
//            Feedback Z_f = Rf(100K) || Cf(.022µF) from output to -IN.
//   Summer:  inverting op amp U1. Direct path through R43(47K),
//            boost path through R44(220K), feedback R45(47K).
//            Both BASS and the HPF cut positions share this summer
//            (the cuts pass through it for the unity-gain inversion;
//            BASS adds the boost path on top).
//
// Transfer function (small-signal, magnitude):
//   H(s) = direct + alpha * G2(s) * H1(s)
//   where direct = R45/R43 = 1.0, alpha = R45/R44 = 0.2136
//         H1(s) = (1 + s·R1·C1) / (1 + s·R1·(C1+CA))
//         G2(s) = (1 + Rf/Rg) · (1 + s·(Rg||Rf)·Cf) / (1 + s·Rf·Cf)
//
// Result: 2-pole, 2-zero biquad with
//   poles at 59.4 Hz and 72.3 Hz (real)
//   zeros at 72.0 Hz and 170 Hz (real)
//   DC gain  +10.50 dB  = 20·log10(1 + 11·R45/R44)
//   HF gain  +1.41  dB  = 20·log10(1 + (R45/R44)·(C1/(C1+CA)))
//
// The 72 Hz pole and 72 Hz zero nearly cancel — H1's zero coincides
// with G2's pole at the audio coupling point, leaving an effective
// shape close to a first-order shelf with f_pole ≈ 59 Hz, f_zero ≈ 170 Hz.
//
// Verified against hardware noise sweep (J106 unit, 96 kHz):
// RMS error 0.55 dB across 20 Hz–20 kHz. The 2 dB residual at ~2 kHz
// is consistent with Welch noise variance and not a real feature.
//
// NOTE: small-signal model. If the M5218L stages exhibit level-
// dependent behavior, an additional saturator stage would be needed.
// Pending verification with multi-level noise sweep.

struct BassBoostFilter
{
  // Component values (from schematic)
  static constexpr float kR1  = 47e3f;     // Stage 1 series R
  static constexpr float kC1  = 0.047e-6f; // Stage 1 series cap (||R1)
  static constexpr float kCA  = 0.01e-6f;  // NodeA shunt cap to GND
  static constexpr float kRg  = 10e3f;     // Stage 2 -IN to GND
  static constexpr float kRf  = 100e3f;    // Stage 2 feedback R
  static constexpr float kCf  = 0.022e-6f; // Stage 2 feedback C (||Rf)
  static constexpr float kR43 = 47e3f;     // Summer direct path
  static constexpr float kR44 = 220e3f;    // Summer boost path
  static constexpr float kR45 = 47e3f;     // Summer feedback

  float b0 = 1.f, b1 = 0.f, b2 = 0.f;
  float a1 = 0.f, a2 = 0.f;
  double z1 = 0.f, z2 = 0.f;

  void Init(float sampleRate)
  {
    // Time constants
    const float tau_1z = kR1 * kC1;
    const float tau_1p = kR1 * (kC1 + kCA);
    const float tau_2z = (kRg * kRf / (kRg + kRf)) * kCf;
    const float tau_2p = kRf * kCf;

    const float G2_dc  = 1.f + kRf / kRg;          // 11.0
    const float alpha  = kR45 / kR44;              // 0.2136
    const float direct = kR45 / kR43;              // 1.0

    // Build H(s) = N(s) / D(s) as polynomials in s, low-power-first.
    // D(s) = (1 + s·tau_1p)(1 + s·tau_2p) = 1 + (tau_1p+tau_2p)s + (tau_1p·tau_2p)s²
    const float D0 = 1.f;
    const float D1 = tau_1p + tau_2p;
    const float D2 = tau_1p * tau_2p;
    // Numerator boost = (1 + s·tau_1z)(1 + s·tau_2z)
    const float Nb0 = 1.f;
    const float Nb1 = tau_1z + tau_2z;
    const float Nb2 = tau_1z * tau_2z;
    // N(s) = direct·D(s) + alpha·G2_dc·N_boost(s)
    const float ag = alpha * G2_dc;
    const float N0 = direct * D0 + ag * Nb0;
    const float N1 = direct * D1 + ag * Nb1;
    const float N2 = direct * D2 + ag * Nb2;

    // Bilinear transform: s → (2/T)·(z-1)/(z+1).
    // Pre-warping isn't needed here because all the interesting poles
    // and zeros (~60–200 Hz) are far below Nyquist at 44.1k+.
    // Standard bilinear of (N0 + N1·s + N2·s²) / (D0 + D1·s + D2·s²):
    const float K  = 2.f * sampleRate;
    const float K2 = K * K;
    const float a0 = D0 + D1 * K + D2 * K2;
    b0 = (N0 + N1 * K + N2 * K2) / a0;
    b1 = 2.f * (N0 - N2 * K2) / a0;
    b2 = (N0 - N1 * K + N2 * K2) / a0;
    a1 = 2.f * (D0 - D2 * K2) / a0;
    a2 = (D0 - D1 * K + D2 * K2) / a0;
    
    Reset();
  }

  void Reset() { z1 = z2 = 0.f; }

  float Process(float x)
  {
    float y = b0 * x + z1;
    z1 = b1 * x - a1 * y + z2;
    z2 = b2 * x - a2 * y;
    return y;
  }
};