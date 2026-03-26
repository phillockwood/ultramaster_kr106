#pragma once

#include <juce_gui_basics/juce_gui_basics.h>
#include "BinaryData.h"

// QWERTY keyboard shortcut diagram overlay.
class KR106QwertyDiagram : public juce::Component
{
public:
    KR106QwertyDiagram()
    {
        mTypeface = juce::Typeface::createSystemTypefaceFor(
            BinaryData::Segment14_otf, BinaryData::Segment14_otfSize);
    }

    struct KeyDef {
        int row, col;
        float indent, widthMul;
        const char* label;
        const char* hint;
        const char* action;
    };

    static constexpr float kKeyW = 26.f;
    static constexpr float kKeyH = 26.f;
    static constexpr float kGap = 2.f;
    static constexpr float kPadX = 5.f;
    static constexpr float kPadY = 5.f;

    const KeyDef* getKeys() const { return mKeys; }
    int numKeys() const { return kNumKeys; }

    std::function<void()> onClose;

    void mouseDown(const juce::MouseEvent&) override
    {
        if (onClose) onClose();
    }

    void mouseMove(const juce::MouseEvent& e) override
    {
        int idx = keyAt(e.x, e.y);
        if (idx != mHoverIdx) { mHoverIdx = idx; repaint(); }
    }

    void mouseExit(const juce::MouseEvent&) override
    {
        if (mHoverIdx >= 0) { mHoverIdx = -1; repaint(); }
    }

    void paint(juce::Graphics& g) override
    {
        int w = getWidth(), h = getHeight();

        auto black    = juce::Colour(0, 0, 0);
        auto dim      = juce::Colour(0, 128, 0);
        auto bright   = juce::Colour(0, 255, 0);
        auto inactive = juce::Colour(0, 80, 0);

        g.setColour(black);
        g.fillRect(0, 0, w, h);
        g.setColour(dim);
        g.drawRect(0, 0, w, h, 1);

        auto font = juce::Font(juce::FontOptions(mTypeface)
            .withMetricsKind(juce::TypefaceMetricsKind::legacy)).withHeight(9.f);
        auto fontSmall = juce::Font(juce::FontOptions(mTypeface)
            .withMetricsKind(juce::TypefaceMetricsKind::legacy)).withHeight(7.f);

        for (int i = 0; i < kNumKeys; i++)
        {
            auto& k = mKeys[i];
            float x = kPadX + k.col * (kKeyW + kGap) + k.indent;
            float y = kPadY + k.row * (kKeyH + kGap);
            float kw = kKeyW * k.widthMul;

            bool active = k.action != nullptr && k.action[0] != '\0';
            bool hover = (i == mHoverIdx);

            g.setColour((hover && active) ? juce::Colour(0, 60, 0) : black);
            g.fillRect(x, y, kw, kKeyH);

            g.setColour(active ? bright : inactive);
            g.drawRect(x, y, kw, kKeyH, 1.f);

            g.setFont(font);
            g.setColour(active ? bright : inactive);
            g.drawText(k.label, (int)x, (int)(y + 2), (int)kw, 12,
                       juce::Justification::centred);

            if (active && k.hint != nullptr && k.hint[0] != '\0')
            {
                g.setFont(fontSmall);
                g.setColour(dim);
                g.drawText(k.hint, (int)x, (int)(y + kKeyH - 11), (int)kw, 10,
                           juce::Justification::centred);
            }
        }

    }

private:
    static constexpr int kNumKeys = 49;

    const KeyDef mKeys[kNumKeys] = {
        // Row 0: number row
        {0, 0, 0, 1, "`", "OCT-", "` Octave Down"},
        {0, 1, 0, 1, "1", "OCT+", "1 Octave Up"},
        {0, 2, 0, 1, "2", "C#",   "2 C#+1"},
        {0, 3, 0, 1, "3", "D#",   "3 D#+1"},
        {0, 4, 0, 1, "4", "",     ""},
        {0, 5, 0, 1, "5", "F#",   "5 F#+1"},
        {0, 6, 0, 1, "6", "G#",   "6 G#+1"},
        {0, 7, 0, 1, "7", "A#",   "7 A#+1"},
        {0, 8, 0, 1, "8", "",     ""},
        {0, 9, 0, 1, "9", "C#",   "9 C#+2"},
        {0, 10, 0, 1, "0", "D#",  "0 D#+2"},
        {0, 11, 0, 1, "-", "F#",  "- F#+2"},
        {0, 12, 0, 1, "=", "G#",  "= G#+2"},
        // Row 1: QWERTY (Q between 1 and 2 = 1.5 keys indent)
        {1, 0, 42, 1, "Q", "C",    "Q C+1"},
        {1, 1, 42, 1, "W", "D",    "W D+1"},
        {1, 2, 42, 1, "E", "E",    "E E+1"},
        {1, 3, 42, 1, "R", "F",    "R F+1"},
        {1, 4, 42, 1, "T", "G",    "T G+1"},
        {1, 5, 42, 1, "Y", "A",    "Y A+1"},
        {1, 6, 42, 1, "U", "B",    "U B+1"},
        {1, 7, 42, 1, "I", "C",    "I C+2"},
        {1, 8, 42, 1, "O", "D",    "O D+2"},
        {1, 9, 42, 1, "P", "E",    "P E+2"},
        {1, 10, 42, 1, "[", "F",   "[ F+2"},
        {1, 11, 42, 1, "]", "G",   "] G+2"},
        // Row 2: ASDF (A between Q and W = 1.75 keys indent)
        {2, 0, 49, 1, "A", "",    ""},
        {2, 1, 49, 1, "S", "C#",  "S C#"},
        {2, 2, 49, 1, "D", "D#",  "D D#"},
        {2, 3, 49, 1, "F", "",    ""},
        {2, 4, 49, 1, "G", "F#",  "G F#"},
        {2, 5, 49, 1, "H", "G#",  "H G#"},
        {2, 6, 49, 1, "J", "A#",  "J A#"},
        {2, 7, 49, 1, "K", "",    ""},
        {2, 8, 49, 1, "L", "C#",  "L C#+1"},
        {2, 9, 49, 1, ";", "D#",  "; D#+1"},
        {2, 10, 49, 1, "'", "F",  "' F+1"},
        // Row 3: ZXCV (Z between A and S = 2.25 keys indent)
        {3, 0, 63, 1, "Z", "C",   "Z C (root)"},
        {3, 1, 63, 1, "X", "D",   "X D"},
        {3, 2, 63, 1, "C", "E",   "C E"},
        {3, 3, 63, 1, "V", "F",   "V F"},
        {3, 4, 63, 1, "B", "G",   "B G"},
        {3, 5, 63, 1, "N", "A",   "N A"},
        {3, 6, 63, 1, "M", "B",   "M B"},
        {3, 7, 63, 1, ",", "C",   ", C+1"},
        {3, 8, 63, 1, ".", "D",   ". D+1"},
        {3, 9, 63, 1, "/", "E",   "/ E+1"},
    };

    int keyAt(int mx, int my) const
    {
        for (int i = 0; i < kNumKeys; i++)
        {
            auto& k = mKeys[i];
            float x = kPadX + k.col * (kKeyW + kGap) + k.indent;
            float y = kPadY + k.row * (kKeyH + kGap);
            float kw = kKeyW * k.widthMul;
            if (mx >= x && mx < x + kw && my >= y && my < y + kKeyH)
                return i;
        }
        return -1;
    }

    juce::Typeface::Ptr mTypeface;
    int mHoverIdx = -1;
};
