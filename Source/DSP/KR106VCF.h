#pragma once

#include <cmath>
#include <algorithm>
#include <cstring>
#include <cstdint>

namespace kr106 {

// ============================================================
// Inline half-band polyphase IIR resampler (replaces HIIR)
// ============================================================
// 12-coefficient allpass polyphase network for 2x up/downsampling.
// Same algorithm and coefficients as Laurent de Soras' HIIR library (WTFPL).
static constexpr int kNumResamplerCoefs = 12;

struct Upsampler2x
{
  float coef[kNumResamplerCoefs] = {};
  float x[kNumResamplerCoefs] = {};
  float y[kNumResamplerCoefs] = {};

  void set_coefs(const double c[kNumResamplerCoefs])
  {
    for (int i = 0; i < kNumResamplerCoefs; i++)
      coef[i] = static_cast<float>(c[i]);
  }

  void clear_buffers()
  {
    memset(x, 0, sizeof(x));
    memset(y, 0, sizeof(y));
  }

  void process_sample(float& out_0, float& out_1, float input)
  {
    float even = input;
    float odd = input;
    // Process pairs of allpass stages
    for (int i = 0; i < kNumResamplerCoefs; i += 2)
    {
      float t0 = (even - y[i]) * coef[i] + x[i];
      float t1 = (odd - y[i + 1]) * coef[i + 1] + x[i + 1];
      x[i] = even;   x[i + 1] = odd;
      y[i] = t0;     y[i + 1] = t1;
      even = t0;     odd = t1;
    }
    out_0 = even;
    out_1 = odd;
  }
};

struct Downsampler2x
{
  float coef[kNumResamplerCoefs] = {};
  float x[kNumResamplerCoefs] = {};
  float y[kNumResamplerCoefs] = {};

  void set_coefs(const double c[kNumResamplerCoefs])
  {
    for (int i = 0; i < kNumResamplerCoefs; i++)
      coef[i] = static_cast<float>(c[i]);
  }

  void clear_buffers()
  {
    memset(x, 0, sizeof(x));
    memset(y, 0, sizeof(y));
  }

  float process_sample(const float in[2])
  {
    float spl_0 = in[1];
    float spl_1 = in[0];
    for (int i = 0; i < kNumResamplerCoefs; i += 2)
    {
      float t0 = (spl_0 - y[i]) * coef[i] + x[i];
      float t1 = (spl_1 - y[i + 1]) * coef[i + 1] + x[i + 1];
      x[i] = spl_0;   x[i + 1] = spl_1;
      y[i] = t0;       y[i + 1] = t1;
      spl_0 = t0;     spl_1 = t1;
    }
    return 0.5f * (spl_0 + spl_1);
  }
};

// ============================================================
// 4-pole TPT Cascade LPF (models IR3109 OTA filter)
// ============================================================
// Four 1-pole trapezoidal integrators with global resonance feedback.
// State variables are integrator outputs — coefficient-independent,
// so per-sample cutoff modulation is artifact-free. No sin/cos needed.
struct VCF
{
  float mS[4] = {}; // integrator states
  bool mBypassLoopClamp = false; // set true to disable high-freq resonance limiter
  bool mNonlinearStages = true; // set true for per-stage OTA tanh (IR3109 model)
  uint32_t mNoiseSeed = 123456789u; // thermal noise PRNG state

  // 2x oversampling: polyphase filters for anti-imaging/aliasing
  Upsampler2x mUpsampler;
  Downsampler2x mDownsampler;

  VCF()
  {
    static constexpr double kCoeffs2x[12] = {
      0.036681502163648017, 0.13654762463195794, 0.27463175937945444,
      0.42313861743656711, 0.56109869787919531, 0.67754004997416184,
      0.76974183386322703, 0.83988962484963892, 0.89226081800387902,
      0.9315419599631839,  0.96209454837808417, 0.98781637073289585
    };
    mUpsampler.set_coefs(kCoeffs2x);
    mDownsampler.set_coefs(kCoeffs2x);
  }

  void Reset()
  {
    mS[0] = mS[1] = mS[2] = mS[3] = 0.f;
    mUpsampler.clear_buffers();
    mDownsampler.clear_buffers();
  }

  // OTA saturation on the feedback path (Padé tanh approximant).
  // Models the IR3109's resonance feedback re-entering through an OTA
  // differential pair: tanh(V_diff / 2V_T). This is what limits
  // resonance amplitude and gives the filter its character.
  static float OTASat(float x)
  {
    if (x > 3.f) return 1.f;
    if (x < -3.f) return -1.f;
    float x2 = x * x;
    return x * (27.f + x2) / (27.f + 9.f * x2);
  }

  // Derivative of OTASat (sech² approximant), for Newton-Raphson.
  static float OTASatDeriv(float x)
  {
    if (x > 3.f || x < -3.f) return 0.f;
    float x2 = x * x;
    float d = 27.f + 9.f * x2;
    return 27.f * (27.f - 3.f * x2) / (d * d);
  }

  // Nonlinear one-pole OTA-C stage: solves y = s + g*tanh(x - y)
  // via one Newton-Raphson iteration from the linear TPT estimate.
  static float NLStage(float& s, float x, float g, float g1)
  {
    // Linear estimate (exact if tanh were linear)
    float y = s + g1 * (x - s);
    // One NR iteration: f(y) = y - s - g*tanh(x-y), f'(y) = 1 + g*sech²(x-y)
    float diff = x - y;
    float t = OTASat(diff);
    float f = y - s - g * t;
    float df = 1.f + g * OTASatDeriv(diff);
    y -= f / df;
    // Trapezoidal state update
    s = 2.f * y - s;
    return y;
  }

  // frq: normalized cutoff [0, ~0.9] where 1.0 = Nyquist (base rate)
  // res: resonance amount [0, 1]
  // 2x oversampled: upsample input, run filter at 2x rate, downsample
  float Process(float input, float frq, float res)
  {
    float up[2], down[2];
    mUpsampler.process_sample(up[0], up[1], input);

    // Halve frq for the oversampled domain (Nyquist is 2x higher)
    float frq2x = frq * 0.5f;
    down[0] = ProcessSample(up[0], frq2x, res);
    down[1] = ProcessSample(up[1], frq2x, res);

    return mDownsampler.process_sample(down);
  }

private:
  // Internal per-sample filter at the oversampled rate
  float ProcessSample(float input, float frq, float res)
  {
    // Warp cutoff to continuous-time frequency, then to integrator coeff
    float g = tanf(std::min(frq, 0.85f) * static_cast<float>(M_PI) * 0.5f);

    // Adaptive thermal noise: models BA662/IR3109 OTA bias current noise.
    // High level when filter is quiet (to seed self-oscillation startup),
    // fades to inaudible once oscillation is established. This keeps
    // pure self-oscillation patches (e.g. Glockenspiel) clean while
    // still providing reliable oscillation seeding.
    mNoiseSeed = mNoiseSeed * 196314165u + 907633515u;
    float white = static_cast<float>(mNoiseSeed) / static_cast<float>(0xFFFFFFFFu) * 2.f - 1.f;
    float stateEnergy = fabsf(mS[0]) + fabsf(mS[1]) + fabsf(mS[2]) + fabsf(mS[3]);
    float noiseLevel = 1e-3f / (1.f + stateEnergy * 1000.f);
    input += white * noiseLevel;

    // Feedback amount (k=0 no resonance, k=4 self-oscillation threshold)
    float k = res * 4.f;

    // Precompute gains for the 4-pole cascade solution
    float g1 = g / (1.f + g);  // one-pole gain

    // Linear cascade: the predictor is exact, so the filter is
    // unconditionally stable regardless of modulation speed.
    float G = g1 * g1 * g1 * g1;

    // OTA bandwidth rolloff: the IR3109's transconductance drops at
    // high frequencies due to transistor fT limits. Below frq=0.3
    // (where aliased harmonics fall above audible range), allow full
    // self-oscillation character. Above 0.3, progressively reduce the
    // loop gain to prevent the resonance limit cycle from producing
    // audible aliased harmonics near Nyquist.
    if (!mBypassLoopClamp)
    {
      float maxLoop = 1.2f - std::max(frq - 0.3f, 0.f);
      maxLoop = std::max(maxLoop, 0.4f);
      float maxK = maxLoop / std::max(G, 1e-6f);
      k = std::min(k, maxK);
    }

    float S = mS[0] * g1 * g1 * g1
            + mS[1] * g1 * g1
            + mS[2] * g1
            + mS[3];

    // Q compensation: the Juno-6 BA662 feeds a portion of the input
    // signal alongside the feedback, boosting drive at high resonance.
    // This counteracts the passband volume drop and pushes the OTA
    // nonlinearities harder — a key part of the Juno's warmth.
    float comp = 1.f + res * res * 0.5f;  // gentle quadratic ramp
    float u = (input * comp - k * OTASat(S)) / (1.f + k * G);

    float lp4;
    if (mNonlinearStages)
    {
      // Per-stage OTA tanh nonlinearity: models the IR3109 differential
      // pair in each stage. tanh(Vin - Vout) acts as a slew-rate limiter,
      // causing signal-dependent cutoff shift and subtle harmonic generation.
      // Each stage solves y = s + g*tanh(x - y) via one Newton-Raphson
      // iteration from the linear estimate, avoiding the artifacts that
      // the explicit form produces at high cutoff + resonance.
      float lp1 = NLStage(mS[0], u,   g, g1);
      float lp2 = NLStage(mS[1], lp1, g, g1);
      float lp3 = NLStage(mS[2], lp2, g, g1);
      lp4       = NLStage(mS[3], lp3, g, g1);
    }
    else
    {
      // Linear stages: predictor above is exact, unconditionally stable.
      float v, s;
      s = mS[0]; v = g1 * (u - s);   mS[0] = s + 2.f * v; float lp1 = s + v;
      s = mS[1]; v = g1 * (lp1 - s); mS[1] = s + 2.f * v; float lp2 = s + v;
      s = mS[2]; v = g1 * (lp2 - s); mS[2] = s + 2.f * v; float lp3 = s + v;
      s = mS[3]; v = g1 * (lp3 - s); mS[3] = s + 2.f * v; lp4       = s + v;
    }

    // Flush denormals from integrator states
    for (auto& st : mS)
      if (fabsf(st) < 1e-15f) st = 0.f;

    return lp4;
  }
};

} // namespace kr106
