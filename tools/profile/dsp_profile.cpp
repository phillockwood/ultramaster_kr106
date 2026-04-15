// dsp_profile -- Standalone CPU profiler for KR106 DSP engine.
//
// Renders a fixed test scenario (6-voice chord, configurable preset)
// and reports timing breakdown: oscillator, VCF (with resampling),
// VCA/envelope, post-mix (HPF, chorus, etc).
//
// USAGE:
//   dsp_profile [samplerate] [preset] [seconds] [oversample]
//   Defaults: 96000, B81 Init (index 0), 10 seconds, 4x oversample

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <chrono>
#include <vector>
#include <algorithm>

#include "../../Source/DSP/KR106_DSP.h"
#include "../../Source/DSP/KR106_DSP_SetParam.h"
#include "../../Source/KR106_Presets_JUCE.h"

enum EParams
{
  kBenderDco = 0, kBenderVcf, kArpRate, kLfoRate, kLfoDelay,
  kDcoLfo, kDcoPwm, kDcoSub, kDcoNoise, kHpfFreq,
  kVcfFreq, kVcfRes, kVcfEnv, kVcfLfo, kVcfKbd,
  kVcaLevel, kEnvA, kEnvD, kEnvS, kEnvR,
  kTranspose, kHold, kArpeggio, kDcoPulse, kDcoSaw, kDcoSubSw,
  kChorusOff, kChorusI, kChorusII,
  kOctTranspose, kArpMode, kArpRange, kLfoMode, kPwmMode,
  kVcfEnvInv, kVcaMode,
  kBender, kTuning, kPower,
  kPortaMode, kPortaRate,
  kTransposeOffset, kBenderLfo,
  kAdsrMode,
  kMasterVol,
  kSettingVoices, kSettingOversample, kSettingIgnoreVel,
  kSettingArpLimitKbd, kSettingArpSync, kSettingLfoSync,
  kSettingMonoRetrig, kSettingMidiSysEx,
  kNumParams
};

static bool isSliderParam(int i)
{
    return (i >= 0 && i <= 19) || i == 40;
}

static void setParam(KR106DSP<float>& dsp, int param, float value)
{
    dsp.SetParam(param, static_cast<double>(value));
}

static void loadPreset(KR106DSP<float>& dsp, int presetArrayIndex)
{
    const int* v = kFactoryPresets[presetArrayIndex].values;
    setParam(dsp, kPower, 1.f);
    setParam(dsp, kMasterVol, 0.5f);
    setParam(dsp, kAdsrMode, static_cast<float>(v[43]));
    for (int i = 0; i < 44; i++)
    {
        float val = isSliderParam(i) ? (v[i] / 127.f) : static_cast<float>(v[i]);
        setParam(dsp, i, val);
    }
    setParam(dsp, kPortaMode, 2.f);
    dsp.mMasterVol = 0.5f * 0.5f;
    dsp.mMasterVolSmooth = dsp.mMasterVol;
    dsp.mVcaLevelSmooth = dsp.mVcaLevel;
}

using Clock = std::chrono::high_resolution_clock;

int main(int argc, char* argv[])
{
    float sr = (argc > 1) ? static_cast<float>(atof(argv[1])) : 96000.f;
    int presetIdx = (argc > 2) ? atoi(argv[2]) : 0; // 0 = first J106 preset
    float seconds = (argc > 3) ? static_cast<float>(atof(argv[3])) : 10.f;
    int oversample = (argc > 4) ? atoi(argv[4]) : 4;

    // J106 presets start at index 128
    int absIdx = 128 + presetIdx;
    if (absIdx >= kNumFactoryPresets) { fprintf(stderr, "Invalid preset index\n"); return 1; }

    static constexpr int kBlockSize = 512;
    int totalSamples = static_cast<int>(sr * seconds);
    int totalBlocks = totalSamples / kBlockSize;

    fprintf(stderr, "=== KR106 DSP Profiler ===\n");
    fprintf(stderr, "Preset: %s (index %d)\n", kFactoryPresets[absIdx].name, presetIdx);
    fprintf(stderr, "Sample rate: %.0f Hz\n", sr);
    fprintf(stderr, "Oversample: %dx\n", oversample);
    fprintf(stderr, "Duration: %.1f sec (%d blocks of %d)\n", seconds, totalBlocks, kBlockSize);
    fprintf(stderr, "\n");

    // Initialize DSP
    KR106DSP<float> dsp(6);
    dsp.Reset(sr, kBlockSize);
    loadPreset(dsp, absIdx);
    // SetParam doesn't handle oversample; set directly on each voice's VCF
    dsp.ForEachVoice([oversample](kr106::Voice<float>& v) {
        v.mVCF.SetOversample(oversample);
    });

    // Allocate output buffers
    std::vector<float> bufL(kBlockSize, 0.f);
    std::vector<float> bufR(kBlockSize, 0.f);
    float* outputs[2] = { bufL.data(), bufR.data() };

    // Play a 6-voice chord: C3 E3 G3 C4 E4 G4
    static constexpr int kChord[] = { 48, 52, 55, 60, 64, 67 };
    for (int n : kChord)
        dsp.NoteOn(n, 127);

    // Warm up (1 second)
    int warmupBlocks = static_cast<int>(sr / kBlockSize);
    for (int b = 0; b < warmupBlocks; b++)
    {
        memset(bufL.data(), 0, kBlockSize * sizeof(float));
        memset(bufR.data(), 0, kBlockSize * sizeof(float));
        dsp.ProcessBlock(nullptr, outputs, 2, kBlockSize);
    }

    // === Profile: Full ProcessBlock ===
    auto t0 = Clock::now();
    for (int b = 0; b < totalBlocks; b++)
    {
        memset(bufL.data(), 0, kBlockSize * sizeof(float));
        memset(bufR.data(), 0, kBlockSize * sizeof(float));
        dsp.ProcessBlock(nullptr, outputs, 2, kBlockSize);
    }
    auto t1 = Clock::now();
    double fullMs = std::chrono::duration<double, std::milli>(t1 - t0).count();
    double rtRatio = (seconds * 1000.0) / fullMs;

    fprintf(stderr, "--- Full ProcessBlock ---\n");
    fprintf(stderr, "  Wall time: %.1f ms for %.1f sec audio\n", fullMs, seconds);
    fprintf(stderr, "  Real-time ratio: %.1fx\n", rtRatio);
    fprintf(stderr, "  CPU usage: %.1f%%\n", 100.0 / rtRatio);
    fprintf(stderr, "\n");

    // === Profile: Voices only (no post-mix) ===
    // Re-init to same state
    dsp.Reset(sr, kBlockSize);
    loadPreset(dsp, absIdx);
    setParam(dsp, kSettingOversample, static_cast<float>(oversample));
    for (int n : kChord)
        dsp.NoteOn(n, 127);
    for (int b = 0; b < warmupBlocks; b++)
    {
        memset(bufL.data(), 0, kBlockSize * sizeof(float));
        memset(bufR.data(), 0, kBlockSize * sizeof(float));
        dsp.ProcessBlock(nullptr, outputs, 2, kBlockSize);
    }

    // Time just the voice processing by running ProcessBlock but
    // measuring a proxy: run with 0 voices vs 6 voices and subtract.
    // First: 6 voices
    auto tv0 = Clock::now();
    for (int b = 0; b < totalBlocks; b++)
    {
        memset(bufL.data(), 0, kBlockSize * sizeof(float));
        memset(bufR.data(), 0, kBlockSize * sizeof(float));
        dsp.ProcessBlock(nullptr, outputs, 2, kBlockSize);
    }
    auto tv1 = Clock::now();
    double voices6Ms = std::chrono::duration<double, std::milli>(tv1 - tv0).count();

    // Now release all notes and measure with 0 active voices
    for (int n : kChord)
        dsp.NoteOff(n);
    // Let voices die out
    for (int b = 0; b < warmupBlocks * 2; b++)
    {
        memset(bufL.data(), 0, kBlockSize * sizeof(float));
        memset(bufR.data(), 0, kBlockSize * sizeof(float));
        dsp.ProcessBlock(nullptr, outputs, 2, kBlockSize);
    }

    auto tn0 = Clock::now();
    for (int b = 0; b < totalBlocks; b++)
    {
        memset(bufL.data(), 0, kBlockSize * sizeof(float));
        memset(bufR.data(), 0, kBlockSize * sizeof(float));
        dsp.ProcessBlock(nullptr, outputs, 2, kBlockSize);
    }
    auto tn1 = Clock::now();
    double voices0Ms = std::chrono::duration<double, std::milli>(tn1 - tn0).count();

    double voiceCostMs = voices6Ms - voices0Ms;
    double postMixMs = voices0Ms;
    double perVoiceMs = voiceCostMs / 6.0;

    fprintf(stderr, "--- Breakdown (6 voices vs 0 voices) ---\n");
    fprintf(stderr, "  6 voices active:  %.1f ms\n", voices6Ms);
    fprintf(stderr, "  0 voices active:  %.1f ms (post-mix only)\n", voices0Ms);
    fprintf(stderr, "  Voice cost (6v):  %.1f ms (%.1f%%)\n", voiceCostMs, 100.0 * voiceCostMs / voices6Ms);
    fprintf(stderr, "  Post-mix cost:    %.1f ms (%.1f%%)\n", postMixMs, 100.0 * postMixMs / voices6Ms);
    fprintf(stderr, "  Per voice:        %.1f ms (%.1f%%)\n", perVoiceMs, 100.0 * perVoiceMs / voices6Ms);
    fprintf(stderr, "\n");

    // === Profile: Oversample comparison ===
    // Run at 1x, 2x, 4x to isolate resampling cost
    fprintf(stderr, "--- Oversample comparison ---\n");
    for (int os : {1, 2, 4})
    {
        dsp.Reset(sr, kBlockSize);
        loadPreset(dsp, absIdx);
        dsp.ForEachVoice([os](kr106::Voice<float>& v) {
            v.mVCF.SetOversample(os);
        });
        for (int n : kChord)
            dsp.NoteOn(n, 127);
        for (int b = 0; b < warmupBlocks; b++)
        {
            memset(bufL.data(), 0, kBlockSize * sizeof(float));
            memset(bufR.data(), 0, kBlockSize * sizeof(float));
            dsp.ProcessBlock(nullptr, outputs, 2, kBlockSize);
        }

        auto to0 = Clock::now();
        for (int b = 0; b < totalBlocks; b++)
        {
            memset(bufL.data(), 0, kBlockSize * sizeof(float));
            memset(bufR.data(), 0, kBlockSize * sizeof(float));
            dsp.ProcessBlock(nullptr, outputs, 2, kBlockSize);
        }
        auto to1 = Clock::now();
        double osMs = std::chrono::duration<double, std::milli>(to1 - to0).count();
        double osRt = (seconds * 1000.0) / osMs;

        fprintf(stderr, "  %dx oversample: %.1f ms (%.1fx RT, %.1f%% CPU)\n",
                os, osMs, osRt, 100.0 / osRt);
    }
    fprintf(stderr, "\n");

    // === Derived estimates ===
    // VCF+resampling cost ≈ (4x time - 1x time) since at 1x there's no resampling
    // and ProcessSample runs once vs 4 times
    fprintf(stderr, "--- Summary ---\n");
    fprintf(stderr, "  The difference between 4x and 1x includes:\n");
    fprintf(stderr, "    - 3 extra ProcessSample calls per voice per sample\n");
    fprintf(stderr, "    - All resampling filter operations (HIIR polyphase)\n");
    fprintf(stderr, "  If we move to shared downsampling, we save the per-voice\n");
    fprintf(stderr, "  resampling but keep all ProcessSample calls.\n");

    return 0;
}
