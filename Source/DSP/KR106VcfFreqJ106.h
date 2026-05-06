#pragma once

#include <cstdint>
#include <cmath>
#include <algorithm>

#include "J106DACHzTable.h"   // kV4Hz[4096] — measured V4 cutoff per DAC code

// Clean-room reimplementation of the D7811G firmware's VCF cutoff frequency
// calculation ($04D5–$064E). All arithmetic is uint16_t with explicit
// carry/borrow tracking, matching the uPD7811's 16-bit EA register pair
// and DADD/DSUBNB instructions.

namespace kr106
{

// Replicates the uPD7811 8×16 multiply pattern:
//   A = coeff (8-bit), BC = value (16-bit)
//   result = (coeff * value) >> 8  →  16-bit
inline uint16_t mul8x16_hi(uint8_t coeff, uint16_t value)
{
  return static_cast<uint16_t>(static_cast<uint32_t>(coeff) * value >> 8);
}

// 16-bit add matching DADDNC EA,BC.
// If carry occurs (result > 0xFFFF), clears the underflow flag —
// the value wrapped back up past the top, so any prior underflow
// is no longer meaningful.
inline uint16_t vcf_add(uint16_t ea, uint16_t bc, bool& overflow)
{
  uint32_t result = static_cast<uint32_t>(ea) + bc;
  if (result > 0xFFFF) overflow = false; // carry clears underflow flag
  return static_cast<uint16_t>(result);
}

// 16-bit subtract matching DSUBNB EA,BC.
// If borrow occurs (bc > ea), sets the underflow flag.
// Result wraps naturally as uint16_t.
inline uint16_t vcf_sub(uint16_t ea, uint16_t bc, bool& overflow)
{
  if (bc > ea) overflow = true; // borrow sets underflow flag
  return ea - bc;               // wraps naturally as uint16_t
}

// Clamp to 14-bit DAC range 0x0000–0x3FFF.
// EAH bits 6-7 set (ea > 0x3FFF) catches both genuine upward overflow
// and wrapped-below-zero values. The underflow flag distinguishes them:
//   underflow=true  → value wrapped below zero → clamp to 0x0000 (min)
//   underflow=false → genuine upward overflow  → clamp to 0x3FFF (max)
inline uint16_t vcf_clamp(uint16_t ea, bool underflow)
{
  if (ea > 0x3FFF)
    return underflow ? 0x0000 : 0x3FFF;
  return ea;
}

// Compute a single voice's VCF cutoff CV, mirroring the main loop
// calculation at $04D5–$064E.
//
// All 16-bit inputs are in the firmware's 14-bit DAC range 0x0000–0x3FFF
// (stored left-justified as 0x0000–0x3F80 when received from the slider).
//
// pitch is 8.8 fixed-point semitones from FF71_notePitchFrac.
// envelope is the 16-bit per-voice ADSR accumulator from FF27+.
inline uint16_t calc_vcf_freq(
    uint16_t vcfCutoff,    // FF3D: slider value 0x0000–0x3F80
    uint16_t vcfLfoSignal, // FF53: pre-computed LFO→VCF amount
    uint16_t vcfBendAmt,   // FF65: pre-computed bend→VCF amount
    uint8_t  vcfEnvMod,    // FF41: env mod depth 0–254 (slider × 2)
    uint8_t  vcfKeyTrack,  // FF42: key track depth 0–254 (slider × 2)
    bool     lfoPolarity,  // FF4A bit1: false = add LFO, true = subtract
    bool     bendPolarity, // FF1E bit5: false = add bend, true = subtract
    bool     envPolarity,  // FF37 bit1: true = positive env, false = negative
    uint16_t envelope,     // per-voice ADSR level 0x0000–0x3FFF
    uint16_t pitch         // per-voice 8.8 fixed-point pitch
)
{
  // Step 1: Compute shared base = cutoff ± LFO ± bend
  uint16_t ea = vcfCutoff;
  bool overflow = false;

  if (!lfoPolarity)
    ea = vcf_add(ea, vcfLfoSignal, overflow);
  else
    ea = vcf_sub(ea, vcfLfoSignal, overflow);

  if (!bendPolarity)
    ea = vcf_add(ea, vcfBendAmt, overflow);
  else
    ea = vcf_sub(ea, vcfBendAmt, overflow);

  // Step 2: Envelope mod
  uint16_t scaledEnv = mul8x16_hi(vcfEnvMod, envelope);

  if (envPolarity)
    ea = vcf_add(ea, scaledEnv, overflow);
  else
    ea = vcf_sub(ea, scaledEnv, overflow);

  // Step 3: Key tracking
  // pitch is 8.8 fixed-point; scale by 3/8 = (pitch/4 + pitch/8)
  uint16_t pScaled = (pitch >> 2) + (pitch >> 3); // pitch × 0.375

  // Middle C (MIDI 60 = 0x3C00 in 8.8) × 0.375 = 0x1680
  static constexpr uint16_t MIDDLE_C_SCALED = 0x1680;

  if (pScaled > MIDDLE_C_SCALED)
  {
    uint16_t keyDelta = mul8x16_hi(vcfKeyTrack, pScaled - MIDDLE_C_SCALED);
    ea = vcf_add(ea, keyDelta, overflow);
  }
  else
  {
    uint16_t keyDelta = mul8x16_hi(vcfKeyTrack, MIDDLE_C_SCALED - pScaled);
    ea = vcf_sub(ea, keyDelta, overflow);
  }

  // Step 4: Clamp to 14-bit DAC range
  return vcf_clamp(ea, overflow);
}

// Pre-compute LFO→VCF modulation amount.
// Called once per main loop tick before calc_vcf_freq().
inline uint16_t calc_vcf_lfo_signal(
    uint8_t  lfoToVcf,     // FF48: VCF LFO depth 0–254
    uint8_t  depthScalar,  // 0–0xFF from LFO onset envelope
    uint16_t lfoVal        // FF4D: LFO waveform magnitude 0x0000–0x1FFF
)
{
  uint8_t combined = static_cast<uint8_t>(
      static_cast<uint16_t>(lfoToVcf) * depthScalar >> 8);
  return static_cast<uint16_t>(
      static_cast<uint32_t>(combined) * lfoVal >> 9);
}

// Pre-compute bend→VCF modulation amount.
// Called once per main loop tick before calc_vcf_freq().
inline uint16_t calc_vcf_bend_amt(
    uint8_t vcfBendSens, // FF8C: ADC value 0–255
    uint8_t bendVal      // FF06: processed bend CV 0–255
)
{
  return static_cast<uint16_t>(
      static_cast<uint16_t>(vcfBendSens) * bendVal >> 4);
}

/**
 * Convert the firmware's 14-bit VCF DAC accumulator to cutoff frequency.
 *
 * Implementation: direct lookup against `kV4Hz[4096]` in J106DACHzTable.h —
 * a measured per-DAC-code frequency profile from voice card V4 of the
 * lfrancis J106, gain-calibrated so DAC code 1568 (= byte 49 anchor)
 * reads exactly 248.000 Hz. The table is the authoritative model: it
 * encodes the BA662/IR3109 exp converter's full shape (kFloor, exp body,
 * soft-knee), the slider sweep's bow, and DAC bit-boundary INL — none of
 * which a closed-form analytical model captured cleanly.
 *
 * SIGNAL PATH
 *
 *   VCF Freq slider (0–127) ──┐
 *   KBD tracking               ├── summed in firmware ── 14-bit accumulator
 *   ENV amount × env level     │                                    │
 *   LFO amount × LFO level  ──┘                               × widthTrim
 *                                                                   │
 *                                                      + frqTrim ───┤
 *                                                                   ▼
 *                                                          clamp [0, 16383]
 *                                                                   │
 *                                                            >> 2 (top 12)
 *                                                                   │
 *                                                          kV4Hz[code] → Hz
 *
 * frqTrim/widthTrim mirror the hardware FREQ and WIDTH trimpots; they
 * shift the accumulator BEFORE the chip's 12-bit truncation, so they have
 * sub-DAC-code resolution in the model even though the chip itself does
 * not. With (frqTrim=0, widthTrim=1) the table directly reproduces the
 * service-manual anchors:
 *   - DAC code 1568 (byte 49 at C4 with KBD center)        → 248 Hz
 *   - DAC code 2139 (byte 49 + 2-octave KBD shift at C6)   → 992 Hz
 *
 * Per-voice variance is captured by (frqTrim, widthTrim) deviations from
 * (0, 1). Two trim parameters can hit any two anchor measurements
 * exactly; any further per-voice non-linearity is unmodeled (the lfrancis
 * V4 table is the reference voice).
 */
inline float dacToHz(uint16_t dac, float frqTrim = 0.0f, float widthTrim = 1.0f)
{
  // Per-voice trim is applied to the 14-bit firmware accumulator. Hardware
  // writes the top 12 bits to the DAC chip, so we mask the bottom 2 bits.
  float cv_lin = static_cast<float>(dac) * widthTrim + frqTrim;
  int   internal = static_cast<int>(cv_lin + 0.5f);
  if (internal < 0)     internal = 0;
  if (internal > 16383) internal = 16383;
  int code = internal >> 2;  // 12-bit DAC chip code (0..4095)
  return static_cast<float>(kV4Hz[code]);
}


} // namespace kr106
