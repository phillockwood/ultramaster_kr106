#pragma once

#include <cstdint>
#include <cmath>
#include <algorithm>

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
 * Convert DAC value to VCF cutoff frequency in Hz.
 *
 * ═══════════════════════════════════════════════════════════════════════
 * Anchors derived from the uPD7810 ROM calibration patch cross-referenced
 * with the service manual's 248 Hz tuning target. Defaults (frqTrim=0,
 * widthTrim=1) reproduce a perfectly calibrated unit.
 * ═══════════════════════════════════════════════════════════════════════
 *
 * DERIVATION
 *
 * The Juno-106 ROM contains a built-in test/calibration patch at a known
 * address. Its VCF-relevant parameters are:
 *
 *     VCF Freq  = $B1    (bit 7 is a flag; value = $31 = 49 decimal)
 *     VCF Res   = $7F    (max)
 *     VCF KBD   = $7F    (max)
 *     VCF Env   = $00    (no envelope modulation)
 *     VCF LFO   = $00    (no LFO modulation)
 *
 * The bit-7-as-flag interpretation was confirmed by systematic comparison
 * of all ROM test patches against the service manual: 127 out of 128
 * parameter values match perfectly when bit 7 is stripped. For example,
 * patch 8 has Decay=$8A and Release=$0A — different raw bytes, same lower
 * 7 bits ($0A), and the service manual shows the same value (1.3) for both.
 *
 * The service manual calibration procedure (Section 4) states:
 *   - RES max, KBD max, play C4 → self-oscillation at 248 Hz
 *   - Play C6 → self-oscillation at 992 Hz (verifies 2-octave KBD tracking)
 *
 * C4 is the firmware's KBD reference point (zero offset). At C4 with
 * ENV=0 and LFO=0, the DAC sees only the VCF Freq slider contribution:
 *
 *     dac = 49 × 128 = 6272
 *     248 Hz = kBaseFreq × 2^(6272 / 1143)
 *     kBaseFreq = 5.528
 *
 * The 992/248 ratio of exactly 4.0× (2 octaves over 2286 DAC counts)
 * confirms 1143 DAC per octave → kScale = ln(2)/1143.
 *
 * For a 4-pole cascaded integrator (IR3109), self-oscillation occurs at
 * the cutoff frequency: each pole contributes arctan(ω/ωc) = 45° at
 * ω = ωc, totaling 180° for the feedback path. So 248 Hz IS the cutoff,
 * not a resonance-shifted artifact.
 *
 * SERVICE MANUAL ERRATUM
 *
 * The service manual states the VCF slider is at "6.3/10" for this test.
 * This is incorrect. The ROM patch loads $B1, whose actual parameter value
 * is $31 = 49 (bit 7 is a flag, not data). On the 0–127 scale this is
 * 49/127 = 3.9/10. The manual writer likely interpreted the raw byte $B1
 * without stripping the flag bit: $B1 >> 1 = $58 = 88, giving 88/127 ≈
 * 6.9/10, possibly rounded or misread as 6.3. The ROM is the ground truth.
 *
 * CALIBRATION
 *
 * The hardware procedure is iterative: adjust FREQ trimpot so C4 self-osc
 * = 248 Hz, then WIDTH trimpot so C6 self-osc = 992 Hz; the two interact,
 * so repeat until both within ±10 cents. This defines both anchors
 * simultaneously. Unit-to-unit variation observed at DAC=16383 across
 * voices (51202, 51238, 52251, 51848 Hz — 35 cents spread) is ultrasonic
 * and does not affect musical tracking; any residual audible-range
 * variation is absorbed by frqTrim / widthTrim settings.
 *
 * COMPRESSION
 *
 * The IR3109 expo converter saturates at high bias currents (physical
 * limit of the translinear cell). Modeled as:
 *
 *     f_out = f_raw / (1 + (f_raw/kCeil)^n)^(1/n)
 *
 * With kCompN=6, the exp line stays within 0.01 cents of ideal through
 * 10 kHz and within 1 cent through 20 kHz, then compresses sharply. Max
 * at DAC=16383 lands at 51923 Hz, inside the observed voice-spread
 * envelope. The hard knee is deliberate: self-oscillation tracking is
 * only relevant in the audio range, and the real IR3109's earlier
 * rolloff is not worth replicating at cost of audible-range accuracy.
 *
 * SIGNAL PATH
 *
 *   VCF Freq slider (0–127) ──┐
 *   KBD tracking               ├── summed in firmware ── DAC ── × widthTrim
 *   ENV amount × env level     │                                    │
 *   LFO amount × LFO level  ──┘                               summing node
 *                                                                   │
 *                                                      + frqTrim ───┤
 *                                                    (DC bias from  │
 *                                                     ±15V divider) │
 *                                                                   ▼
 *                                                   IR3109 expo converter
 *                                                                   │
 *                                                            VCF cutoff freq
 *
 * frqTrim and widthTrim mirror the hardware FREQ and WIDTH trimpots.
 */
inline float dacToHz(uint16_t dac, float frqTrim = 0.0f, float widthTrim = 1.0f)
{
  static constexpr float kBaseFreq = 5.528477f;       // = 248 / 2^(6272/1143)
  static constexpr float kScale    = 0.0006064280f;   // = ln(2) / 1143
  static constexpr float kCeil     = 52000.0f;
  static constexpr float kCompN    = 6.0f;
  static constexpr float kInvCompN = 1.f / kCompN;

  float cv_lin = static_cast<float>(dac) * widthTrim + frqTrim;
  float f = kBaseFreq * expf(cv_lin * kScale);
  float r = f / kCeil;
  return f / powf(1.f + powf(r, kCompN), kInvCompN);
}


} // namespace kr106
