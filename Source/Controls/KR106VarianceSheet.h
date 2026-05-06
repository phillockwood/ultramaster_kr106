#pragma once

#include <juce_gui_basics/juce_gui_basics.h>
#include "PluginProcessor.h"
#include "KR106MenuSheet.h"

// ============================================================================
// KR106VarianceSheet — per-voice component variance editor.
// Grid showing 10 voices × 6 variance parameters with drag-to-edit.
// Black background, green LED font, same aesthetic as preset/menu sheets.
// ============================================================================
class KR106VarianceSheet : public juce::Component
{
public:
    static constexpr int kMaxVoices = 10;
    static constexpr int kNumParams = 5;
    // Layout: title, noise row (analog + chorus on one line), header, 10 voices
    static constexpr int kFirstVoiceRow = 3; // title + noise + header
    static constexpr int kTotalRows = kFirstVoiceRow + kMaxVoices;
    static constexpr int kLabelCol = 1;   // voice label column
    static constexpr int kTotalCols = kLabelCol + kNumParams;

    KR106VarianceSheet(KR106AudioProcessor* proc, juce::Typeface::Ptr typeface,
                       std::function<void()> onClose)
        : mProcessor(proc), mTypeface(typeface), mOnClose(std::move(onClose))
    {
        setWantsKeyboardFocus(true);
        readFromVoices();
        if (mProcessor)
        {
            mAnalogNoiseKnob = mulToKnob(mProcessor->mDSP.mNoiseFloorMul);
            mMainsNoiseKnob = mulToKnob(mProcessor->mDSP.mMainsMul);
            mClockNoiseKnob = mulToKnob(mProcessor->mDSP.mChorus.mClockMul);
            mBbdDriveKnob = mProcessor->mDSP.mChorus.mBbdDriveUser / 100.f;
            mDriftKnob = mProcessor->mDSP.mDriftAmount;
            // Note: chorus mAnalogMul is always kept in sync with mNoiseFloorMul
        }
    }

    // Cell sizes match the 8×16 preset sheet grid (940/8 = 117w, 224/16 = 14h)
    static constexpr int kColW = 117;
    static constexpr int kRowH = 14;

    int calcWidth() const { return kTotalCols * kColW; }
    int calcHeight() const { return kTotalRows * kRowH + 2; }

    void showAt(juce::Rectangle<int> bounds)
    {
        setBounds(bounds);
        grabKeyboardFocus();
    }

    void paint(juce::Graphics& g) override
    {
        using namespace KR106Theme;
        g.fillAll(bg());
        g.setFont(ledFont(mTypeface));

        int w = getWidth();
        int h = getHeight();
        int activeVoices = mProcessor ? mProcessor->mVoiceCount : 6;

        // Title row: 3 cols for title, 4 cols for buttons (right-aligned)
        int colW7 = w / kTotalCols;
        g.setColour(bright());
        g.drawSingleLineText("COMPONENT VARIANCE", 4, kRowH - 2);

        mTunePoorlyRect  = { colW7 * 2, 0, colW7, kRowH };
        mTuneLazyRect    = { colW7 * 3, 0, colW7, kRowH };
        mTunePerfectRect = { colW7 * 4, 0, colW7, kRowH };
        mCloseRect       = { colW7 * 5, 0, w - colW7 * 5, kRowH };

        auto drawBtn = [&](juce::Rectangle<int>& r, const char* label, int hoverId) {
            if (mHoverRow == hoverId)
            {
                g.setColour(hoverBg());
                g.fillRect(r);
            }
            g.setColour(bright());
            g.drawSingleLineText(label, r.getX() + 4, r.getBottom() - 2);
        };
        drawBtn(mTunePoorlyRect,  "OUT OF TUNE",  -2);
        drawBtn(mTuneLazyRect,    "HUMAN TUNE",   -3);
        drawBtn(mTunePerfectRect, "ROBOT TUNE",   -4);
        drawBtn(mCloseRect,       "CLOSE",         -9);

        // Noise/drive row: 4 controls using voice-grid column width
        {
            int y = kRowH;
            int cellH = kRowH;
            int cellW = w / kTotalCols; // not used directly, see colW7 below

            auto paintNoiseCell = [&](int hitId, int x0, int cw, const char* label, float knobVal, bool showDb) {
                bool isHover = (mHoverRow == hitId);
                bool isSel = (mSelectedRow == hitId);
                if (isSel)
                {
                    g.setColour(bright());
                    g.fillRect(x0 + 1, y + 1, cw - 1, cellH - 1);
                }
                else if (isHover)
                {
                    g.setColour(hoverBg());
                    g.fillRect(x0 + 1, y + 1, cw - 1, cellH - 1);
                }
                g.setColour(isSel ? bg() : bright());
                g.drawSingleLineText(label, x0 + 4, y + cellH - 2);
                juce::String text;
                if (showDb)
                {
                    // Tapered noise mapping: knob 0 = silent, 0.5 = 0 dB, 1.0 = +12 dB.
                    if (knobVal <= 0.f)
                        text = "-INF dB";
                    else
                    {
                        float db = 20.f * log10f(knobToMul(knobVal));
                        text = juce::String(db, 1) + " dB";
                    }
                }
                else
                {
                    int pct = juce::roundToInt(knobVal * 100.f);
                    text = juce::String(pct) + " %";
                }
                g.drawSingleLineText(text,
                                     x0 + cw - 8, y + cellH - 2,
                                     juce::Justification::right);
            };
            int colW7 = w / kTotalCols;
            paintNoiseCell(-10, 0,         colW7, "DCO DRIFT",    mDriftKnob,        false);
            paintNoiseCell(-5,  colW7,     colW7, "FLOOR NS",     mAnalogNoiseKnob,  true);
            paintNoiseCell(-6,  colW7 * 2, colW7, "MAINS NS",     mMainsNoiseKnob,   true);
            paintNoiseCell(-7,  colW7 * 3, colW7, "CHORUS NS",    mClockNoiseKnob,   true);
            paintNoiseCell(-8,  colW7 * 4, colW7, "BBD DRIVE",    mBbdDriveKnob,     false);
        }

        // Header row (bright text on dark bg)
        int headerY = 2 * kRowH;
        int headerH = kRowH;
        g.setColour(bright());
        g.drawSingleLineText("VOICE", 4, headerY + headerH - 2);
        for (int p = 0; p < kNumParams; p++)
        {
            auto info = kr106::Voice<float>::GetVarianceInfo(p);
            int x = (p + 1) * kColW;
            g.drawSingleLineText(info.name, x + kColW - 8, headerY + headerH - 2,
                                 juce::Justification::right);
        }

        // Grid lines
        g.setColour(grid());
        for (int row = 1; row <= kTotalRows; row++)
        {
            int y = row * kRowH;
            g.drawHorizontalLine(y, 0.f, static_cast<float>(w));
        }
        int voiceGridTop = static_cast<int>(kFirstVoiceRow * kRowH);
        g.drawVerticalLine(kColW, static_cast<float>(kRowH), static_cast<float>(h));
        for (int p = 1; p < kNumParams; p++)
        {
            int x = (p + 1) * kColW;
            g.drawVerticalLine(x, static_cast<float>(voiceGridTop), static_cast<float>(h));
        }

        // Voice rows
        for (int v = 0; v < kMaxVoices; v++)
        {
            int row = v + kFirstVoiceRow;
            int y = row * kRowH;
            int cellH = (row + 1) * kRowH - y;
            bool inactive = v >= activeVoices;

            // Voice label
            static const char* voiceNames[] = {
                "ONE", "TWO", "THREE", "FOUR", "FIVE",
                "SIX", "SEVEN", "EIGHT", "NINE", "TEN"
            };
            g.setColour(inactive ? disabled() : bright());
            g.drawSingleLineText(voiceNames[v], 4, y + cellH - 2);

            // Parameter values
            for (int p = 0; p < kNumParams; p++)
            {
                int x = (p + 1) * kColW;
                bool isHover = (mHoverRow == v && mHoverCol == p);
                bool isSelected = (mSelectedRow == v && mSelectedCol == p);

                if (isSelected)
                {
                    g.setColour(bright());
                    g.fillRect(x + 1, y + 1, kColW - 1, cellH - 1);
                }
                else if (isHover)
                {
                    g.setColour(hoverBg());
                    g.fillRect(x + 1, y + 1, kColW - 1, cellH - 1);
                }

                auto info = kr106::Voice<float>::GetVarianceInfo(p);
                float displayF = mValues[v][p] * info.displayScale + info.displayOffset;
                float displayStep = info.step * info.displayScale;
                juce::String text;
                if (displayStep < 0.99f)
                {
                    // Sub-integer step (e.g. 0.25): show enough decimals
                    int decimals = (displayStep < 0.1f) ? 2 : (displayStep < 0.5f ? 2 : 1);
                    if (info.displayOffset != 0.f)
                        text = juce::String(displayF, decimals);
                    else
                        text = (displayF >= 0.f ? "+" : "") + juce::String(displayF, decimals);
                }
                else
                {
                    int display = juce::roundToInt(displayF);
                    if (info.displayOffset != 0.f)
                        text = juce::String(display);
                    else
                        text = (display >= 0 ? "+" : "") + juce::String(display);
                }
                text += " " + juce::String(info.unit);

                g.setColour(inactive ? disabled() : isSelected ? bg() : bright());
                g.drawSingleLineText(text, x + kColW - 8, y + cellH - 2,
                                     juce::Justification::right);
            }
        }

        g.setColour(border());
        g.drawRect(getLocalBounds());
    }

    void mouseMove(const juce::MouseEvent& e) override
    {
        auto [row, col] = hitTest(e.getPosition());
        if (row != mHoverRow || col != mHoverCol)
        {
            mHoverRow = row;
            mHoverCol = col;
            repaint();
        }
    }

    void mouseDown(const juce::MouseEvent& e) override
    {
        // Close button
        if (mCloseRect.contains(e.getPosition())) { dismiss(); return; }

        // Check tune buttons
        if (mTunePoorlyRect.contains(e.getPosition()))  { tuneRandomize(1.f);  return; }
        if (mTuneLazyRect.contains(e.getPosition()))    { tuneRandomize(0.2f); return; }
        if (mTunePerfectRect.contains(e.getPosition())) { tunePerfect();       return; }

        auto [row, col] = hitTest(e.getPosition());
        if (isNoiseKnob(row))
        {
            mSelectedRow = row;
            mSelectedCol = 0;
            mDragStartY = e.y;
            mDragStartValue = noiseKnob(row);
            repaint();
        }
        else if (row >= 0 && row < kMaxVoices && col >= 0 && col < kNumParams)
        {
            mSelectedRow = row;
            mSelectedCol = col;
            mDragStartY = e.y;
            mDragStartValue = mValues[row][col];
            repaint();
        }
        else
        {
            dismiss();
        }
    }

    void mouseDrag(const juce::MouseEvent& e) override
    {
        if (isNoiseKnob(mSelectedRow))
        {
            float delta = (mDragStartY - e.y) * (1.f / 80.f);
            noiseKnob(mSelectedRow) = std::clamp(mDragStartValue + delta, 0.f, 1.f);
            applyNoise();
            repaint();
            return;
        }
        if (mSelectedRow < 0) return;
        auto info = kr106::Voice<float>::GetVarianceInfo(mSelectedCol);
        float delta = (mDragStartY - e.y) * info.step;
        float newVal = std::clamp(mDragStartValue + delta, -info.range, info.range);
        mValues[mSelectedRow][mSelectedCol] = newVal;
        applyToVoice(mSelectedRow, mSelectedCol);
        repaint();
    }

    void mouseUp(const juce::MouseEvent&) override
    {
        // Keep selection active for arrow key editing
    }

    void mouseExit(const juce::MouseEvent&) override
    {
        if (mHoverRow >= -1 || mHoverCol >= 0)
        {
            mHoverRow = -1;
            mHoverCol = -1;
            repaint();
        }
    }

    bool keyPressed(const juce::KeyPress& key) override
    {
        if (key == juce::KeyPress::escapeKey)
        {
            dismiss();
            return true;
        }

        // Tab / Shift+Tab: navigate between rows
        // Order: noise(-5..-8) -> voice 0 -> voice 1 -> ... -> voice 9
        if (key == juce::KeyPress::tabKey)
        {
            if (key.getModifiers().isShiftDown())
            {
                if (mSelectedRow == 0)
                    { mSelectedRow = -8; }           // voice 0 -> last noise cell
                else if (mSelectedRow > 0)
                    mSelectedRow--;                   // voice N -> voice N-1
                else if (mSelectedRow == -5)
                    { mSelectedRow = kMaxVoices - 1; mSelectedCol = 0; } // wrap to last voice
            }
            else
            {
                if (mSelectedRow <= -5 && mSelectedRow >= -8)
                    { mSelectedRow = 0; mSelectedCol = 0; } // noise -> voice 0
                else if (mSelectedRow < kMaxVoices - 1)
                    mSelectedRow++;                   // voice N -> voice N+1
                else
                    mSelectedRow = -5;                // wrap to noise row
            }
            repaint();
            return true;
        }

        // Noise/drive row
        if (mSelectedRow <= -5 && mSelectedRow >= -8)
        {
            float& knob = noiseKnob(mSelectedRow);
            if (key == juce::KeyPress::upKey)
            {
                knob = std::clamp(knob + 0.01f, 0.f, 1.f);
                applyNoise();
                repaint();
                return true;
            }
            if (key == juce::KeyPress::downKey)
            {
                knob = std::clamp(knob - 0.01f, 0.f, 1.f);
                applyNoise();
                repaint();
                return true;
            }
            if (key == juce::KeyPress::leftKey)
            {
                if (mSelectedRow < -5) mSelectedRow++;
                repaint();
                return true;
            }
            if (key == juce::KeyPress::rightKey)
            {
                if (mSelectedRow > -8) mSelectedRow--;
                repaint();
                return true;
            }
            return false;
        }

        if (mSelectedRow < 0) return false;

        auto info = kr106::Voice<float>::GetVarianceInfo(mSelectedCol);

        if (key == juce::KeyPress::upKey)
        {
            mValues[mSelectedRow][mSelectedCol] = std::clamp(
                mValues[mSelectedRow][mSelectedCol] + info.step,
                -info.range, info.range);
            applyToVoice(mSelectedRow, mSelectedCol);
            repaint();
            return true;
        }
        if (key == juce::KeyPress::downKey)
        {
            mValues[mSelectedRow][mSelectedCol] = std::clamp(
                mValues[mSelectedRow][mSelectedCol] - info.step,
                -info.range, info.range);
            applyToVoice(mSelectedRow, mSelectedCol);
            repaint();
            return true;
        }
        if (key == juce::KeyPress::leftKey)
        {
            mSelectedCol = std::max(0, mSelectedCol - 1);
            repaint();
            return true;
        }
        if (key == juce::KeyPress::rightKey)
        {
            mSelectedCol = std::min(kNumParams - 1, mSelectedCol + 1);
            repaint();
            return true;
        }

        return false;
    }

    void focusLost(FocusChangeType) override
    {
        dismiss();
    }

private:
    void readFromVoices()
    {
        if (!mProcessor) return;
        for (int v = 0; v < kMaxVoices; v++)
        {
            auto* voice = mProcessor->mDSP.GetVoice(v);
            for (int p = 0; p < kNumParams; p++)
                mValues[v][p] = voice->GetVariance(p);
        }
    }

    void applyToVoice(int v, int p)
    {
        if (!mProcessor) return;
        auto* voice = mProcessor->mDSP.GetVoice(v);
        voice->SetVariance(p, mValues[v][p]);
    }

    void tunePerfect()
    {
        for (int v = 0; v < kMaxVoices; v++)
        {
            for (int p = 0; p < kNumParams; p++)
            {
                mValues[v][p] = 0.f;
                applyToVoice(v, p);
            }
        }
        mAnalogNoiseKnob = 0.f;
        mMainsNoiseKnob = 0.f;
        mClockNoiseKnob = 0.f;
        mBbdDriveKnob = 0.f;
        mDriftKnob = 0.f;
        applyNoise();
        repaint();
    }

    void tuneRandomize(float scale)
    {
        // Use current time as seed for a new "hardware unit"
        uint32_t baseSeed = static_cast<uint32_t>(juce::Time::currentTimeMillis());
        for (int v = 0; v < kMaxVoices; v++)
        {
            uint32_t seed = baseSeed + static_cast<uint32_t>(v) * 2654435761u;
            auto rng = [&seed]() -> float {
                seed = seed * 196314165u + 907633515u;
                return static_cast<float>(seed) / static_cast<float>(0xFFFFFFFF) * 2.f - 1.f;
            };
            for (int p = 0; p < kNumParams; p++)
            {
                auto info = kr106::Voice<float>::GetVarianceInfo(p);
                // Human Tune uses humanRange; Out Of Tune uses 2x humanRange.
                // info.range is the user-editable manual cap, not used here.
                float r = (scale > 0.5f) ? (info.humanRange * 2.f) : info.humanRange;
                mValues[v][p] = rng() * r;
            }
            for (int p = 0; p < kNumParams; p++)
                applyToVoice(v, p);
        }
        // Noise/drive: Human Tune = unity (0.5), Out of Tune = elevated (0.65)
        float noiseLevel = (scale > 0.5f) ? 0.65f : 0.5f;
        mAnalogNoiseKnob = noiseLevel;
        mMainsNoiseKnob = noiseLevel;
        mClockNoiseKnob = noiseLevel;
        mBbdDriveKnob = noiseLevel;
        // Drift: Human Tune = 0.25 (recently calibrated), Out of Tune = 0.75 (drifted classic).
        mDriftKnob = (scale > 0.5f) ? 0.75f : 0.25f;
        applyNoise();
        // Reroll per-voice static-offset units so each tune-randomize click
        // creates a fresh "hardware unit" feel rather than reshuffling the
        // same scaled values.
        if (mProcessor)
            mProcessor->mDSP.RerollDriftUnits(baseSeed);
        repaint();
    }

    std::pair<int, int> hitTest(juce::Point<int> pos) const
    {
        if (mCloseRect.contains(pos)) return { -9, -1 };

        if (pos.y < kRowH)
        {
            if (mTunePoorlyRect.contains(pos))  return { -2, -1 };
            if (mTuneLazyRect.contains(pos))    return { -3, -1 };
            if (mTunePerfectRect.contains(pos)) return { -4, -1 };
        }

        // Noise/drive row: y = 1*kRowH to 2*kRowH, 6 columns (5 used)
        if (pos.y >= kRowH && pos.y < 2 * kRowH)
        {
            int colW7 = getWidth() / kTotalCols;
            int col = pos.x / colW7;
            if (col == 0) return { -10, 0 };
            if (col == 1) return { -5,  0 };
            if (col == 2) return { -6,  0 };
            if (col == 3) return { -7,  0 };
            if (col == 4) return { -8,  0 };
            return { -1, -1 }; // empty columns
        }

        int row = pos.y / kRowH - kFirstVoiceRow;
        int col = pos.x / kColW - 1;

        if (row < 0 || row >= kMaxVoices || col < 0 || col >= kNumParams)
            return { -1, -1 };

        return { row, col };
    }

    // Noise floor taper: 0..1 knob -> multiplier.
    // 0 = silent, 0.5 = unity, 1 = 4x.
    static float knobToMul(float knob)
    {
        if (knob <= 0.f) return 0.f;
        return powf(4.f, 2.f * knob - 1.f); // 0.25..1..4
    }

    static float mulToKnob(float mul)
    {
        if (mul <= 0.f) return 0.f;
        return (log2f(mul) / 2.f + 1.f) * 0.5f; // inverse of knobToMul
    }

    static bool isNoiseKnob(int hitId)
    {
        return hitId == -5 || hitId == -6 || hitId == -7 || hitId == -8 || hitId == -10;
    }

    float& noiseKnob(int hitId)
    {
        if (hitId == -6)  return mMainsNoiseKnob;
        if (hitId == -7)  return mClockNoiseKnob;
        if (hitId == -8)  return mBbdDriveKnob;
        if (hitId == -10) return mDriftKnob;
        return mAnalogNoiseKnob; // -5
    }

    void applyNoise()
    {
        if (!mProcessor) return;
        float analogMul = knobToMul(mAnalogNoiseKnob);
        mProcessor->mDSP.mNoiseFloorMul = analogMul;
        mProcessor->mDSP.mChorus.mAnalogMul = analogMul;
        mProcessor->mDSP.mMainsMul = knobToMul(mMainsNoiseKnob);
        mProcessor->mDSP.mChorus.mMainsMul = knobToMul(mMainsNoiseKnob);
        mProcessor->mDSP.mChorus.mClockMul = knobToMul(mClockNoiseKnob); // 0=silent, 0.5=unity, 1.0=4x
        // BBD drive: userVal 0..100, k = 0.48 * (userVal/100)^2
        float userVal = mBbdDriveKnob * 100.f;
        mProcessor->mDSP.mChorus.mBbdDriveUser = userVal;
        mProcessor->mDSP.mChorus.updateBbdDrive();
        mProcessor->mDSP.SetDriftAmount(mDriftKnob);
    }

    void dismiss()
    {
        if (mOnClose) mOnClose();
    }

    KR106AudioProcessor* mProcessor = nullptr;
    juce::Typeface::Ptr mTypeface;
    std::function<void()> mOnClose;

    float mAnalogNoiseKnob = 0.5f;  // 0..1, 0.5 = unity
    float mMainsNoiseKnob = 0.5f;
    float mClockNoiseKnob = 0.5f;
    float mBbdDriveKnob = 0.5f;   // 0..1, 0.5 = default (50%)
    float mDriftKnob = 0.25f;     // 0..1, 0 = robot, 1 = uncalibrated
    float mValues[kMaxVoices][kNumParams] = {};
    int mHoverRow = -1, mHoverCol = -1;
    int mSelectedRow = -1, mSelectedCol = -1;
    float mDragStartY = 0.f;
    float mDragStartValue = 0.f;
    juce::Rectangle<int> mTunePoorlyRect, mTuneLazyRect, mTunePerfectRect, mCloseRect;
};
