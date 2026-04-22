#pragma once

#include <cstdint>
#include <algorithm>

// Shared Juno-106 SysEx decoder -- no JUCE dependency.
//
// Decodes Roland SysEx IPR (Individual Parameter) and APR (All Parameter
// Report) messages into (paramIdx, normalizedValue) pairs that can be
// fed to KR106DSP::SetParam or JUCE's setValueNotifyingHost.
//
// The caller provides a callback that receives each decoded param.
// This keeps the decoder independent of JUCE vs raw DSP usage.

namespace kr106 {

// SysEx CC index -> EParams mapping (matches PluginProcessor.h enum order)
// EParams enum values must match between plugin and tools.
struct SysExDecoder
{
  // EParams indices used by the decoder. Caller must ensure these match
  // the actual enum. Using named constants avoids #including the enum.
  int kLfoRate, kLfoDelay, kDcoLfo, kDcoPwm;
  int kDcoNoise, kVcfFreq, kVcfRes, kVcfEnv;
  int kVcfLfo, kVcfKbd, kVcaLevel, kEnvA;
  int kEnvD, kEnvS, kEnvR, kDcoSub;
  int kOctTranspose, kDcoPulse, kDcoSaw;
  int kChorusOff, kChorusI, kChorusII;
  int kPwmMode, kVcfEnvInv, kVcaMode, kHpfFreq;
  int kDcoSubSw;
  bool j106Mode;  // true = J106 (PWM byte 105 limit)

  // CC index -> param index (first 16 slider params in SysEx order)
  int ccToParam(int cc) const
  {
    switch (cc) {
      case 0x00: return kLfoRate;
      case 0x01: return kLfoDelay;
      case 0x02: return kDcoLfo;
      case 0x03: return kDcoPwm;
      case 0x04: return kDcoNoise;
      case 0x05: return kVcfFreq;
      case 0x06: return kVcfRes;
      case 0x07: return kVcfEnv;
      case 0x08: return kVcfLfo;
      case 0x09: return kVcfKbd;
      case 0x0A: return kVcaLevel;
      case 0x0B: return kEnvA;
      case 0x0C: return kEnvD;
      case 0x0D: return kEnvS;
      case 0x0E: return kEnvR;
      case 0x0F: return kDcoSub;
      default: return -1;
    }
  }

  // Scale a SysEx byte to normalized 0-1 float.
  // CC 0x03 (PWM) uses byte/105 in J106 mode, byte/127 otherwise.
  float scaleCC(int cc, int val) const
  {
    if (cc == 0x03 && j106Mode)
    {
      val = std::min(val, 105);
      return val / 105.f;
    }
    return val / 127.f;
  }

  // Decode switch byte 1 (SW1): octave, pulse, saw, chorus
  // Calls setParam(paramIdx, value) for each decoded param.
  template <typename SetParam>
  void decodeSW1(uint8_t val, SetParam setParam) const
  {
    int oct = (val & 0x04) ? 2 : (val & 0x02) ? 1 : 0;
    setParam(kOctTranspose, static_cast<float>(oct));
    setParam(kDcoPulse, (val & 0x08) ? 1.f : 0.f);
    setParam(kDcoSaw,   (val & 0x10) ? 1.f : 0.f);
    bool chorusOn = !(val & 0x20);
    bool chorusL1 = (val & 0x40) != 0;
    setParam(kChorusOff, chorusOn ? 0.f : 1.f);
    setParam(kChorusI,   (chorusOn && chorusL1)  ? 1.f : 0.f);
    setParam(kChorusII,  (chorusOn && !chorusL1) ? 1.f : 0.f);
  }

  // Decode switch byte 2 (SW2): PWM mode, VCF env inv, VCA mode, HPF
  template <typename SetParam>
  void decodeSW2(uint8_t val, SetParam setParam) const
  {
    setParam(kPwmMode,    (val & 0x01) ? 1.f : 0.f);
    setParam(kVcfEnvInv,  (val & 0x02) ? 1.f : 0.f);
    setParam(kVcaMode,    (val & 0x04) ? 1.f : 0.f);
    int hpf = 3 - ((val >> 3) & 0x03);
    setParam(kHpfFreq, static_cast<float>(hpf));
  }

  // Decode an IPR (Individual Parameter Report): 41 32 0n cc vv
  // data points to the bytes AFTER F0 (i.e. data[0] = 0x41).
  // Returns true if decoded successfully.
  template <typename SetParam>
  bool decodeIPR(const uint8_t* data, int len, SetParam setParam) const
  {
    if (len < 5 || data[0] != 0x41 || data[1] != 0x32) return false;
    int ctrl = data[3];
    int val  = data[4];

    if (ctrl <= 0x0F)
    {
      int param = ccToParam(ctrl);
      if (param >= 0)
        setParam(param, scaleCC(ctrl, val));
      // J106: infer sub switch from sub level
      if (ctrl == 0x0F && kDcoSubSw >= 0)
        setParam(kDcoSubSw, val > 0 ? 1.f : 0.f);
      return true;
    }
    else if (ctrl == 0x10)
    {
      decodeSW1(static_cast<uint8_t>(val), setParam);
      return true;
    }
    else if (ctrl == 0x11)
    {
      decodeSW2(static_cast<uint8_t>(val), setParam);
      return true;
    }
    return false;
  }

  // Decode an APR (All Parameter Report): 41 3x 0n pp [16 sliders] [sw1] [sw2]
  // data points to the bytes AFTER F0.
  // patchNum is written to *outPatch if non-null.
  // Returns true if decoded successfully.
  template <typename SetParam>
  bool decodeAPR(const uint8_t* data, int len, SetParam setParam, int* outPatch = nullptr) const
  {
    if (len < 21 || data[0] != 0x41) return false;
    int cmd = data[1];
    if (cmd != 0x30 && cmd != 0x31) return false;

    if (outPatch) *outPatch = data[3];
    const uint8_t* p = data + 4;

    // 16 slider params
    for (int cc = 0; cc < 16; cc++)
    {
      int param = ccToParam(cc);
      if (param >= 0)
        setParam(param, scaleCC(cc, p[cc]));
    }

    // Switch bytes
    decodeSW1(p[16], setParam);
    decodeSW2(p[17], setParam);

    // J106: infer sub switch from sub level
    if (kDcoSubSw >= 0)
      setParam(kDcoSubSw, p[0x0F] > 0 ? 1.f : 0.f);

    return true;
  }

  // Decode any SysEx message (dispatches to IPR or APR).
  // data points to the bytes AFTER F0.
  template <typename SetParam>
  bool decode(const uint8_t* data, int len, SetParam setParam, int* outPatch = nullptr) const
  {
    if (len < 4 || data[0] != 0x41) return false;
    int cmd = data[1];
    if (cmd == 0x32)
      return decodeIPR(data, len, setParam);
    if (cmd == 0x30 || cmd == 0x31)
      return decodeAPR(data, len, setParam, outPatch);
    return false;
  }
};

} // namespace kr106
