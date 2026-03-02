#include "KR106.h"
#include "IPlug_include_in_plug_src.h"
#include "IControls.h"
#include "KR106Controls.h"

KR106::KR106(const InstanceInfo& info)
: iplug::Plugin(info, MakeConfig(kNumParams, kNumPresets))
{
  // --- Sliders: percent type (0-1 linear) ---
  GetParam(kBenderDco)->InitDouble("Bender DCO", 0., 0., 1., 0.01, "%");
  GetParam(kBenderVcf)->InitDouble("Bender VCF", 0., 0., 1., 0.01, "%");
  GetParam(kLfoDelay)->InitDouble("LFO Delay", 0., 0., 1., 0.01, "");
  GetParam(kDcoLfo)->InitDouble("DCO LFO", 0., 0., 1., 0.01, "%");
  GetParam(kDcoPwm)->InitDouble("DCO PWM", 0., 0., 1., 0.01, "%");
  GetParam(kDcoSub)->InitDouble("DCO Sub", 1., 0., 1., 0.01, "%");
  GetParam(kDcoNoise)->InitDouble("DCO Noise", 0., 0., 1., 0.01, "%");
  GetParam(kVcfFreq)->InitDouble("VCF Freq", 700., 20., 18000., 1., "Hz",
    IParam::kFlagsNone, "", IParam::ShapeExp());
  GetParam(kVcfRes)->InitDouble("VCF Res", 0., 0., 1., 0.01, "%");
  GetParam(kVcfEnv)->InitDouble("VCF Env", 0., 0., 1., 0.01, "%");
  GetParam(kVcfLfo)->InitDouble("VCF LFO", 0., 0., 1., 0.01, "%");
  GetParam(kVcfKbd)->InitDouble("VCF Kbd", 0., 0., 1., 0.01, "%");
  GetParam(kEnvS)->InitDouble("Sustain", 0.9, 0.001, 1., 0.001, "%");

  GetParam(kVcaLevel)->InitDouble("Volume", 1., 0., 1., 0.01, "");

  // --- Sliders: BPM type (linear with real range) ---
  GetParam(kArpRate)->InitDouble("Arp Rate", 120., 90., 3000., 0.1, "BPM"); // 1.5–50 Hz
  GetParam(kLfoRate)->InitDouble("LFO Rate", 300., 18., 1200., 0.1, "BPM"); // 0.3–20 Hz

  // --- 4-position HPF switch: 0=bass boost, 1=flat, 2=HPF 240Hz, 3=HPF 720Hz ---
  GetParam(kHpfFreq)->InitInt("HPF", 1, 0, 3);

  // --- Sliders: time type (quartic curve) ---
  GetParam(kEnvA)->InitDouble("Attack", 50., 1., 3000., 0.1, "ms",
    IParam::kFlagsNone, "", IParam::ShapePowCurve(4.));
  GetParam(kEnvD)->InitDouble("Decay", 200., 2., 12000., 0.1, "ms",
    IParam::kFlagsNone, "", IParam::ShapePowCurve(4.));
  GetParam(kEnvR)->InitDouble("Release", 200., 2., 12000., 0.1, "ms",
    IParam::kFlagsNone, "", IParam::ShapePowCurve(4.));

  // --- Buttons (toggle 0/1) ---
  GetParam(kTranspose)->InitBool("Transpose", false);
  GetParam(kHold)->InitBool("Hold", false);
  GetParam(kArpeggio)->InitBool("Arpeggio", false);
  GetParam(kDcoPulse)->InitBool("Pulse", true);
  GetParam(kDcoSaw)->InitBool("Saw", true);
  GetParam(kDcoSubSw)->InitBool("Sub Sw", false);
  GetParam(kChorusOff)->InitBool("Chorus Off", true);
  GetParam(kChorusI)->InitBool("Chorus I", false);
  GetParam(kChorusII)->InitBool("Chorus II", false);

  // --- Switches ---
  GetParam(kOctTranspose)->InitInt("Octave", 1, 0, 2); // up=0, normal=1, down=2
  GetParam(kArpMode)->InitInt("Arp Mode", 0, 0, 2);
  GetParam(kArpRange)->InitInt("Arp Range", 0, 0, 2);
  GetParam(kLfoMode)->InitInt("LFO Mode", 0, 0, 1);
  GetParam(kPwmMode)->InitInt("PWM Mode", 1, 0, 2); // LFO=0, MAN=1, ENV=2
  GetParam(kVcfEnvInv)->InitInt("VCF Env Inv", 0, 0, 1);
  GetParam(kVcaMode)->InitInt("VCA Mode", 0, 0, 1);

  // --- Special ---
  GetParam(kBender)->InitDouble("Bender", 0., -1., 1., 0.01, "");
  GetParam(kTuning)->InitDouble("Tuning", 0., -1., 1., 0.01, "");
  GetParam(kPower)->InitBool("Power", true);

#include "KR106_Presets.h"

#if IPLUG_EDITOR
  mMakeGraphicsFunc = [&]() {
    return MakeGraphics(*this, PLUG_WIDTH, PLUG_HEIGHT, PLUG_FPS, 1.f);
  };

  mLayoutFunc = [&](IGraphics* pGraphics) {
    pGraphics->EnableMouseOver(true);
    pGraphics->LoadFont("Roboto-Regular", ROBOTO_FN);

    // Load bitmaps — @2x versions loaded automatically on Retina
    const IBitmap bgBitmap = pGraphics->LoadBitmap(BG_FN);
    const IBitmap knobBitmap = pGraphics->LoadBitmap(KNOB_FN, 32, true);
    const IBitmap smallKnobBitmap = pGraphics->LoadBitmap(SMALLKNOB_FN, 32, true);
    const IBitmap switch2wayBitmap = pGraphics->LoadBitmap(SWITCH_2WAY_FN, 2);
    const IBitmap switch3wayBitmap = pGraphics->LoadBitmap(SWITCH_3WAY_FN, 3);
    const IBitmap ledBitmap = pGraphics->LoadBitmap(LED_RED_FN, 2);

    // Background panel
    pGraphics->AttachControl(new IBitmapControl(0, 0, bgBitmap));

    const IBitmap benderGradient = pGraphics->LoadBitmap(BENDER_GRADIENT_FN);

    // === LEFT SECTION: Master controls ===
    // Power switch (46, 40) — 15x19 toggle
    pGraphics->AttachControl(new KR106PowerSwitchControl(IRECT(46, 40, 61, 59)));

    // Tuning knob — center 28x27 frame in original 39x39 widget at (34,64)
    pGraphics->AttachControl(new KR106KnobControl(40, 70, smallKnobBitmap, kTuning));

    // Bender sensitivity sliders (left side, below panel)
    pGraphics->AttachControl(new KR106SliderControl(IRECT(23, 127, 36, 176), kBenderDco));
    pGraphics->AttachControl(new KR106SliderControl(IRECT(41, 127, 54, 176), kBenderVcf));

    // LFO Trigger button (75, 182) — 41x19 momentary
    pGraphics->AttachControl(new KR106LFOTrigControl(IRECT(75, 182, 116, 201)));

    // Pitch bend lever (66, 206) — 60x8 spring-back horizontal
    pGraphics->AttachControl(new KR106BenderControl(IRECT(66, 206, 126, 214), kBender, benderGradient));

    // Octave transpose 3-way switch (70, 142)
    pGraphics->AttachControl(new KR106SwitchControl(70, 142, switch3wayBitmap, kOctTranspose));

    // === ARPEGGIATOR SECTION ===
    // Transpose button+LED (95, 52), Hold (122, 52), Arp (154, 52)
    // button_control_layout places: button at (x, y), LED at (x+4, y-9)
    // So combined bounds = (x, y-9, x+17, y+19)
    pGraphics->AttachControl(new KR106ButtonLEDControl(IRECT(95, 43, 112, 71), kTranspose, kYellow, ledBitmap));
    pGraphics->AttachControl(new KR106ButtonLEDControl(IRECT(122, 43, 139, 71), kHold, kYellow, ledBitmap));
    pGraphics->AttachControl(new KR106ButtonLEDControl(IRECT(154, 43, 171, 71), kArpeggio, kYellow, ledBitmap));

    // Arp mode 3-way switch (175, 48), range (212, 48)
    pGraphics->AttachControl(new KR106SwitchControl(175, 48, switch3wayBitmap, kArpMode));
    pGraphics->AttachControl(new KR106SwitchControl(212, 48, switch3wayBitmap, kArpRange));

    // Arp rate slider (229, 33)
    pGraphics->AttachControl(new KR106SliderControl(IRECT(229, 33, 242, 82), kArpRate));

    // === LFO SECTION ===
    pGraphics->AttachControl(new KR106SliderControl(IRECT(251, 33, 264, 82), kLfoRate));
    pGraphics->AttachControl(new KR106SliderControl(IRECT(269, 33, 282, 82), kLfoDelay));
    pGraphics->AttachControl(new KR106SwitchControl(284, 48, switch2wayBitmap, kLfoMode));

    // === DCO SECTION ===
    pGraphics->AttachControl(new KR106SliderControl(IRECT(316, 33, 329, 82), kDcoLfo));
    pGraphics->AttachControl(new KR106SliderControl(IRECT(334, 33, 347, 82), kDcoPwm));
    pGraphics->AttachControl(new KR106SwitchControl(349, 48, switch3wayBitmap, kPwmMode));

    // DCO waveform buttons+LEDs: Pulse (377), Saw (393), Sub (409)
    pGraphics->AttachControl(new KR106ButtonLEDControl(IRECT(377, 43, 394, 71), kDcoPulse, kYellow, ledBitmap));
    pGraphics->AttachControl(new KR106ButtonLEDControl(IRECT(393, 43, 410, 71), kDcoSaw, kYellow, ledBitmap));
    pGraphics->AttachControl(new KR106ButtonLEDControl(IRECT(409, 43, 426, 71), kDcoSubSw, kOrange, ledBitmap));

    // DCO Sub level and Noise sliders
    pGraphics->AttachControl(new KR106SliderControl(IRECT(430, 33, 443, 82), kDcoSub));
    pGraphics->AttachControl(new KR106SliderControl(IRECT(448, 33, 461, 82), kDcoNoise));

    // === HPF SECTION ===
    pGraphics->AttachControl(new KR106SliderControl(IRECT(472, 33, 485, 82), kHpfFreq));

    // === VCF SECTION ===
    pGraphics->AttachControl(new KR106SliderControl(IRECT(496, 33, 509, 82), kVcfFreq));
    pGraphics->AttachControl(new KR106SliderControl(IRECT(513, 33, 526, 82), kVcfRes));
    pGraphics->AttachControl(new KR106SwitchControl(535, 48, switch2wayBitmap, kVcfEnvInv));
    pGraphics->AttachControl(new KR106SliderControl(IRECT(552, 33, 565, 82), kVcfEnv));
    pGraphics->AttachControl(new KR106SliderControl(IRECT(570, 33, 583, 82), kVcfLfo));
    pGraphics->AttachControl(new KR106SliderControl(IRECT(588, 33, 601, 82), kVcfKbd));

    // === VCA SECTION ===
    pGraphics->AttachControl(new KR106SwitchControl(610, 48, switch2wayBitmap, kVcaMode));
    pGraphics->AttachControl(new KR106SliderControl(IRECT(638, 33, 651, 82), kVcaLevel));

    // === ENVELOPE SECTION ===
    pGraphics->AttachControl(new KR106SliderControl(IRECT(659, 33, 672, 82), kEnvA));
    pGraphics->AttachControl(new KR106SliderControl(IRECT(676, 33, 689, 82), kEnvD));
    pGraphics->AttachControl(new KR106SliderControl(IRECT(695, 33, 708, 82), kEnvS));
    pGraphics->AttachControl(new KR106SliderControl(IRECT(713, 33, 726, 82), kEnvR));

    // === CHORUS SECTION ===
    // Chorus Off is a plain button (no LED), Chorus I and II have LEDs
    pGraphics->AttachControl(new KR106ChorusOffControl(IRECT(735, 52, 752, 71), kChorusI, kChorusII));
    pGraphics->AttachControl(new KR106ButtonLEDControl(IRECT(751, 43, 768, 71), kChorusI, kYellow, ledBitmap));
    pGraphics->AttachControl(new KR106ButtonLEDControl(IRECT(767, 43, 784, 71), kChorusII, kOrange, ledBitmap));

    // === VALUE READOUT (below slider panel) ===
    pGraphics->AttachControl(new KR106ValueReadout(IRECT(229, 88, 726, 102)));

    // === SCOPE (upper right) ===
    pGraphics->AttachControl(new KR106ScopeControl(IRECT(791, 24, 919, 90)), kCtrlTagScope);

    // === KEYBOARD ===
    // Original: (129, 111) size 792x109 — 61 keys C2 to C7
    pGraphics->AttachControl(new KR106KeyboardControl(IRECT(129, 111, 921, 220)), kCtrlTagKeyboard);

    // QWERTY keyboard handler
    pGraphics->SetQwertyMidiKeyHandlerFunc([pGraphics](const IMidiMsg& msg) {
      dynamic_cast<KR106KeyboardControl*>(pGraphics->GetControlWithTag(kCtrlTagKeyboard))
        ->SetNoteFromMidi(msg.NoteNumber(), msg.StatusMsg() == IMidiMsg::kNoteOn);
    });
  };
#endif
}

#if IPLUG_DSP
void KR106::ProcessBlock(sample** inputs, sample** outputs, int nFrames)
{
  mDSP.ProcessBlock(inputs, outputs, 2, nFrames);
  if (!mPowerOn)
  {
    for (int i = 0; i < nFrames; i++)
      outputs[0][i] = outputs[1][i] = sample(0);
  }
  sample* scopeBufs[2] = { outputs[0], mDSP.GetSyncBuffer() };
  mScopeSender.ProcessBlock(scopeBufs, nFrames, kCtrlTagScope, 2, 0);
}

void KR106::OnReset()
{
  mDSP.Reset(GetSampleRate(), GetBlockSize());

  // Push all current parameter values to DSP on reset
  for (int i = 0; i < kNumParams; i++)
    mDSP.SetParam(i, GetParam(i)->Value());
}

void KR106::ProcessMidiMsg(const IMidiMsg& msg)
{
  TRACE;
  mDSP.ProcessMidiMsg(msg);
  SendMidiMsg(msg); // forward for keyboard display and MIDI output
}

void KR106::OnParamChange(int paramIdx)
{
  if (paramIdx == kPower)
    mPowerOn = GetParam(kPower)->Bool();
  else
    mDSP.SetParam(paramIdx, GetParam(paramIdx)->Value());
}

void KR106::OnIdle()
{
  mScopeSender.TransmitData(*this);
}
#endif
