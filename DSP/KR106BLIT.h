#pragma once

#include <cmath>
#include <mutex>

// Band-Limited Impulse Train oscillator core
// Ported from original KR106 synth blit.h/blit.c

namespace kr106 {

static constexpr int kSinLookupSize = 4096;
static constexpr int kSinLookupMask = kSinLookupSize - 1;

inline float* GetSinLookup()
{
  static float sTable[kSinLookupSize + 1];
  static std::once_flag sFlag;
  std::call_once(sFlag, []() {
    for (int i = 0; i <= kSinLookupSize; i++)
    {
      if (i == kSinLookupSize / 2 || i == kSinLookupSize)
        sTable[i] = 0.f;
      else
        sTable[i] = sinf(static_cast<float>(i) * 2.f * static_cast<float>(M_PI) / kSinLookupSize);
    }
  });
  return sTable;
}

// Interpolated sine lookup for pos in [0.0, 1.0)
inline float FastSin(float pos)
{
  float* table = GetSinLookup();
  float bucket = pos * kSinLookupSize;
  int i1 = static_cast<int>(bucket);
  float frac = bucket - i1;
  i1 &= kSinLookupMask;
  int i2 = i1 + 1;
  return table[i1] + frac * (table[i2] - table[i1]);
}

// Band-limited impulse train: sin(PI*pos*M) / sin(PI*pos)
// pos in [0.0, 2.0), M = number of harmonics (odd for unipolar)
inline float BLIT(float pos, float M)
{
  if (pos != 0.f && pos != 1.f && pos != 2.f)
  {
    float posOver2 = pos * 0.5f;
    float n = FastSin(posOver2 * M); // sin(PI * pos * M / 2) via lookup
    float d = FastSin(posOver2);     // sin(PI * pos / 2) via lookup
    if (d == 0.f) return M;
    return n / d;
  }
  // L'Hopital limit at discontinuities
  if (pos == 0.f || pos == 2.f) return M;
  return (static_cast<int>(M) & 1) ? M : -M;
}

} // namespace kr106
