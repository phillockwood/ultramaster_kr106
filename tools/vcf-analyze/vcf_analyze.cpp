// Standalone VCF filter analysis tool
// Links KR106VCF.h directly — no iPlug2 dependencies needed.
//
// Usage: vcf_analyze <frq 0..1> <res 0..1> [samplerate]
//
// 1. Self-oscillation test: feeds silence, measures if output sustains
//    and reports oscillation frequency via zero-crossing analysis.
// 2. Frequency response: resets filter, feeds a unit impulse,
//    captures the IR and FFTs it for the magnitude response.

#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <cstring>
#include <vector>
#include <complex>
#include <algorithm>
#include <numeric>

// Include the VCF directly — it's header-only with no external deps
#include "../../Source/DSP/KR106VCF.h"

// ── Radix-2 FFT ──────────────────────────────────────────────────────

using Complex = std::complex<double>;

static void fft(std::vector<Complex>& x)
{
    size_t N = x.size();
    if (N <= 1) return;

    // Bit-reversal permutation
    for (size_t i = 1, j = 0; i < N; i++) {
        size_t bit = N >> 1;
        for (; j & bit; bit >>= 1)
            j ^= bit;
        j ^= bit;
        if (i < j) std::swap(x[i], x[j]);
    }

    // Cooley-Tukey butterflies
    for (size_t len = 2; len <= N; len <<= 1) {
        double ang = -2.0 * M_PI / len;
        Complex wlen(cos(ang), sin(ang));
        for (size_t i = 0; i < N; i += len) {
            Complex w(1.0);
            for (size_t j = 0; j < len / 2; j++) {
                Complex u = x[i + j];
                Complex v = x[i + j + len / 2] * w;
                x[i + j] = u + v;
                x[i + j + len / 2] = u - v;
                w *= wlen;
            }
        }
    }
}

// ── Self-oscillation test ────────────────────────────────────────────

struct OscResult {
    bool oscillating;
    double frequency;   // Hz, from zero-crossing
    double amplitude;   // peak amplitude
    double diffEnv;     // steady-state mDiffEnv from VCF
};

static OscResult test_self_oscillation(float frq, float res, float sampleRate)
{
    kr106::VCF vcf;
    vcf.SetSampleRate(sampleRate);
    vcf.Reset();

    int totalSamples = static_cast<int>(sampleRate * 2.0f); // 2 seconds
    int settleTime = static_cast<int>(sampleRate * 1.0f);   // 1 second settle

    // Run for settle time with silence
    for (int i = 0; i < settleTime; i++)
        vcf.Process(0.f, frq, res);

    // Collect 1 second of output
    int measureSamples = totalSamples - settleTime;
    std::vector<float> output(measureSamples);
    for (int i = 0; i < measureSamples; i++)
        output[i] = vcf.Process(0.f, frq, res);

    // Measure peak amplitude
    float peak = 0.f;
    for (float s : output)
        peak = std::max(peak, fabsf(s));

    OscResult result;
    result.amplitude = peak;
    result.diffEnv = vcf.mDiffEnv;  // steady-state after 2s

    // The VCF injects adaptive thermal noise to seed self-oscillation,
    // so even with zero resonance there's a small output (~1e-3 peak).
    // Use 0.01 threshold to distinguish real oscillation from noise.
    if (peak < 0.01f) {
        result.oscillating = false;
        result.frequency = 0.0;
        return result;
    }

    result.oscillating = true;

    // Zero-crossing frequency measurement (positive-going crossings)
    int crossings = 0;
    for (int i = 1; i < measureSamples; i++) {
        if (output[i - 1] <= 0.f && output[i] > 0.f)
            crossings++;
    }

    result.frequency = static_cast<double>(crossings) * sampleRate / measureSamples;
    return result;
}

// ── Frequency response via impulse response FFT ─────────────────────

struct FreqResponse {
    std::vector<double> freqHz;
    std::vector<double> magnitudeDb;
};

static FreqResponse measure_frequency_response(float frq, float res, float sampleRate)
{
    constexpr int kIRLen = 65536;       // actual IR samples
    constexpr int kFFTSize = 262144;    // 4x zero-pad for finer interpolation

    kr106::VCF vcf;
    vcf.SetSampleRate(sampleRate);
    vcf.Reset();

    // Suppress the VCF's adaptive thermal noise by pre-setting the
    // input envelope follower high.
    vcf.mInputEnv = 1.f;

    // Capture impulse response — no window needed since the IR
    // naturally decays to zero within the capture length. The 4x
    // zero-padding provides fine spectral interpolation for accurate
    // peak and -3dB detection.
    std::vector<Complex> ir(kFFTSize, 0.0); // zero-padded
    for (int i = 0; i < kIRLen; i++) {
        float input = (i == 0) ? 1.f : 0.f;
        ir[i] = vcf.Process(input, frq, res);
    }

    fft(ir);

    FreqResponse resp;
    int bins = kFFTSize / 2 + 1;
    resp.freqHz.resize(bins);
    resp.magnitudeDb.resize(bins);

    for (int i = 0; i < bins; i++) {
        resp.freqHz[i] = static_cast<double>(i) * sampleRate / kFFTSize;
        double mag2 = std::norm(ir[i]);
        resp.magnitudeDb[i] = 10.0 * log10(std::max(mag2, 1e-30));
    }

    return resp;
}

// ── Main ─────────────────────────────────────────────────────────────

static void print_usage(const char* prog)
{
    fprintf(stderr, "Usage: %s <frq 0..1> <res 0..1> [samplerate]\n", prog);
    fprintf(stderr, "  frq: normalized cutoff frequency (0..1)\n");
    fprintf(stderr, "  res: resonance (0..1)\n");
    fprintf(stderr, "  samplerate: default 44100\n");
}

int main(int argc, char* argv[])
{
    if (argc < 3) {
        print_usage(argv[0]);
        return 1;
    }

    float frq = static_cast<float>(atof(argv[1]));
    float res = static_cast<float>(atof(argv[2]));
    float sampleRate = (argc > 3) ? static_cast<float>(atof(argv[3])) : 44100.f;

    if (frq < 0.f || frq > 1.f || res < 0.f || res > 1.f) {
        fprintf(stderr, "Error: frq and res must be in 0..1\n");
        return 1;
    }

    printf("═══════════════════════════════════════════════════════\n");
    printf("  KR106 VCF Analysis — frq=%.4f  res=%.4f  sr=%.0f\n", frq, res, sampleRate);
    printf("═══════════════════════════════════════════════════════\n\n");

    OscResult osc = test_self_oscillation(frq, res, sampleRate);
    FreqResponse resp = measure_frequency_response(frq, res, sampleRate);

    constexpr int kFFTSize = 262144;
    double binWidth = sampleRate / static_cast<double>(kFFTSize);
    int bins = static_cast<int>(resp.magnitudeDb.size());

    // Target frequency: frq is normalized to Nyquist
    double targetHz = frq * sampleRate * 0.5;

    // Find the resonance peak (global maximum in magnitude spectrum,
    // skipping DC bin)
    int peakBin = 1;
    double peakDb = resp.magnitudeDb[1];
    for (int i = 2; i < bins; i++) {
        if (resp.magnitudeDb[i] > peakDb) {
            peakDb = resp.magnitudeDb[i];
            peakBin = i;
        }
    }

    // Parabolic interpolation for sub-bin peak accuracy.
    // Fits a parabola through bins [peakBin-1, peakBin, peakBin+1] in dB
    // and finds the vertex. Gives ~0.1 bin precision.
    double peakFreq = peakBin * binWidth;
    if (peakBin > 0 && peakBin < bins - 1) {
        double a = resp.magnitudeDb[peakBin - 1];
        double b = resp.magnitudeDb[peakBin];
        double c = resp.magnitudeDb[peakBin + 1];
        double delta = 0.5 * (a - c) / (a - 2.0 * b + c);
        peakFreq = (peakBin + delta) * binWidth;
        peakDb = b - 0.25 * (a - c) * delta;
    }

    // Passband (DC) gain reference: average bins 1–5 (~0.17–0.84 Hz).
    // Bin 0 can have DC offset artifacts from the resampler chain;
    // bins 1–5 are deep in the passband for any cutoff setting.
    double passbandDb = 0;
    {
        int lo = 1, hi = std::min(5, bins - 1);
        double sum = 0;
        for (int i = lo; i <= hi; i++)
            sum += resp.magnitudeDb[i];
        passbandDb = sum / (hi - lo + 1);
    }

    // Find -3dB cutoff: the frequency where the response first drops
    // and stays 3 dB below the passband level.
    // Always search from DC upward — this finds the actual filter cutoff,
    // not the post-peak rolloff (which would be misleading at high res).
    double target3dB = passbandDb - 3.0;
    double fc3dB = -1;
    double peakProminence = peakDb - passbandDb;
    int searchStart = std::max(1, static_cast<int>(20.0 / binWidth));
    for (int i = searchStart; i < bins; i++) {
        if (resp.magnitudeDb[i] < target3dB && i > 0 && resp.magnitudeDb[i - 1] >= target3dB) {
            // Require 20+ consecutive bins below threshold to skip
            // past resonance bumps and window ripple
            int confirmBins = std::min(20, bins - i - 1);
            bool confirmed = true;
            for (int j = 1; j <= confirmBins; j++) {
                if (resp.magnitudeDb[i + j] > target3dB) { confirmed = false; break; }
            }
            if (!confirmed) continue;
            double frac = (target3dB - resp.magnitudeDb[i - 1]) /
                          (resp.magnitudeDb[i] - resp.magnitudeDb[i - 1]);
            fc3dB = (i - 1 + frac) * binWidth;
            break;
        }
    }

    // Detect self-oscillation from FFT prominence as well — the
    // time-domain test can miss cases where the filter sustains but
    // the 1s settle wasn't quite enough, or amplitude is borderline.
    // Prominence > 50 dB with a sharp peak is a dead giveaway.
    bool effectivelyOscillating = osc.oscillating || (peakProminence > 50.0);

    // Best resonant frequency measurement: ZC when oscillating (more
    // accurate), FFT peak otherwise.
    double bestFreq = osc.oscillating ? osc.frequency : peakFreq;
    const char* bestSource = osc.oscillating ? "ZC" : "FFT";

    // Error: best measurement vs target, in cents
    double bestErrorCents = 0;
    if (targetHz > 0 && bestFreq > 0)
        bestErrorCents = 1200.0 * log2(bestFreq / targetHz);

    // Error: -3dB point vs target, in cents
    double fc3dBerrorCents = 0;
    if (targetHz > 0 && fc3dB > 0)
        fc3dBerrorCents = 1200.0 * log2(fc3dB / targetHz);

    printf("\n  Self-oscillation:  %s", effectivelyOscillating ? "YES" : "no");
    if (osc.oscillating)
        printf("  (peak amplitude: %.4f)", osc.amplitude);
    else if (effectivelyOscillating)
        printf("  (detected from FFT prominence: %.0f dB)", peakProminence);
    printf("\n  Target freq:       %.1f Hz  (frq=%.4f)\n", targetHz, frq);
    if (peakProminence > 15.0) {
        printf("  Res peak (%s):    %.1f Hz  (%+.1f dB, error: %+.1f cents)\n",
               bestSource, bestFreq, peakProminence, bestErrorCents);
    } else {
        printf("  Res peak:          none (prominence %.1f dB — no resonance)\n",
               peakProminence);
    }
    if (fc3dB > 0) {
        printf("  -3dB cutoff:       %.1f Hz  (error: %+.1f cents)\n",
               fc3dB, fc3dBerrorCents);
    } else {
        printf("  -3dB cutoff:       not found\n");
    }
    printf("  Passband gain:     %+.1f dB\n", passbandDb);
    printf("  DiffEnv:           %.4f  (A²=%.4f, DF boost=%.4f)\n",
           osc.diffEnv, osc.diffEnv * osc.diffEnv,
           1.0 + 0.06 * osc.diffEnv * osc.diffEnv);

    return 0;
}
