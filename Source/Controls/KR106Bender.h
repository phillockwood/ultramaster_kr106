#pragma once

#include <juce_gui_basics/juce_gui_basics.h>
#include <juce_audio_processors/juce_audio_processors.h>
#include "PluginProcessor.h"
#include <cmath>

// ============================================================================
// KR106Bender -- 2D pitch bend lever (Juno-106 style)
// Horizontal: pitch bend (spring-back to center)
// Vertical push-up: LFO trigger on/off (handle shifts up, spring-back)
// ============================================================================
class KR106Bender : public juce::Component
{
public:
    KR106Bender(juce::RangedAudioParameter* param, const juce::Image& gradientImage,
                KR106AudioProcessor* processor)
        : mParam(param), mGradient(gradientImage), mProcessor(processor)
    {}

    void paint(juce::Graphics& g) override
    {
        const auto black = juce::Colour(0, 0, 0);
        const auto gray  = juce::Colour(128, 128, 128);
        const auto white = juce::Colour(255, 255, 255);

        float h = static_cast<float>(getHeight());
        float trackY = h - 8.f; // gradient track always at bottom
        float handleOff = mTriggered ? -4.f : 0.f; // handle shifts up 4px

        // Black background (fixed position)
        g.setColour(black);
        g.fillRect(4.f, trackY, 52.f, 8.f);

        // Gradient image (fixed position)
        g.drawImage(mGradient, 5.f, trackY + 1.f, 50.f, 6.f,
                    0, 0, mGradient.getWidth(), mGradient.getHeight());

        // Pointer -- param value normalized 0-1, map to -1..+1
        float value = mParam ? mParam->getValue() * 2.f - 1.f : 0.f;
        float midpoint = 30.f;
        float angle = juce::MathConstants<float>::pi * (2.f - value) / 4.f;

        float basex1  = cosf(angle + juce::MathConstants<float>::pi / 20.f) * 24.f + midpoint;
        float basex2  = cosf(angle - juce::MathConstants<float>::pi / 20.f) * 24.f + midpoint;
        float pointx1 = cosf(angle + juce::MathConstants<float>::pi / 50.f) * 36.f + midpoint;
        float pointx2 = cosf(angle - juce::MathConstants<float>::pi / 50.f) * 36.f + midpoint;

        float baseEndY = trackY + 1.f;               // base stays on track
        float pointEndY = trackY + 1.f + handleOff;  // point end tilts up

        // Gray outer shape (tilted quad)
        g.setColour(gray);
        {
            juce::Path p;
            if (basex1 < pointx1) {
                // base left, point right
                p.startNewSubPath(basex1,        baseEndY);
                p.lineTo(pointx2 + 2.f,         pointEndY);
                p.lineTo(pointx2 + 2.f,         pointEndY + 6.f);
                p.lineTo(basex1,                 baseEndY + 6.f);
            } else {
                // point left, base right
                p.startNewSubPath(pointx1,       pointEndY);
                p.lineTo(basex2 + 1.f,           baseEndY);
                p.lineTo(basex2 + 1.f,           baseEndY + 6.f);
                p.lineTo(pointx1,                pointEndY + 6.f);
            }
            p.closeSubPath();
            g.fillPath(p);
        }

        // White inner pointer (tilted quad)
        g.setColour(white);
        {
            juce::Path p;
            p.startNewSubPath(pointx1,       pointEndY);
            p.lineTo(pointx2 + 1.f,         pointEndY);
            p.lineTo(pointx2 + 1.f,         pointEndY + 6.f);
            p.lineTo(pointx1,               pointEndY + 6.f);
            p.closeSubPath();
            g.fillPath(p);
        }

        // Gray corner pixels
        g.setColour(gray);
        g.fillRect(pointx1, pointEndY, 1.f, 1.f);
        g.fillRect(pointx1, pointEndY + 5.f, 1.f, 1.f);
        g.fillRect(pointx2, pointEndY, 1.f, 1.f);
        g.fillRect(pointx2, pointEndY + 5.f, 1.f, 1.f);
    }

    void mouseDown(const juce::MouseEvent& e) override
    {
        if (!mParam) return;

        // Map click x to bender value
        float lx = static_cast<float>(e.getPosition().x);
        float midpoint = 30.f;
        float value = (lx - midpoint) / midpoint;
        value = juce::jlimit(-1.f, 1.f, value);

        mParam->beginChangeGesture();
        mParam->setValueNotifyingHost((value + 1.f) / 2.f);
        mDragStartVal = (value + 1.f) / 2.f;
        mDragStartY = e.getPosition().y;

        repaint();
    }

    void mouseDrag(const juce::MouseEvent& e) override
    {
        if (!mParam) return;

        // Horizontal: pitch bend
        float scale = e.mods.isShiftDown() ? 512.f : 128.f;
        float dX = static_cast<float>(e.getDistanceFromDragStartX());
        float value = mDragStartVal * 2.f - 1.f;
        value += dX / scale;
        value = juce::jlimit(-1.f, 1.f, value);
        mParam->setValueNotifyingHost((value + 1.f) / 2.f);

        // Vertical: trigger LFO when dragged up past threshold
        bool wasTriggered = mTriggered;
        int dY = e.getPosition().y - mDragStartY;
        mTriggered = (dY < -3); // 3px upward threshold

        if (mTriggered != wasTriggered && mProcessor)
            mProcessor->sendMidiFromUI(0xB0, 1, mTriggered ? 127 : 0);

        repaint();
    }

    void mouseUp(const juce::MouseEvent&) override
    {
        if (!mParam) return;

        // Spring back: pitch to center, trigger off
        mParam->setValueNotifyingHost(0.5f);
        mParam->endChangeGesture();

        if (mTriggered && mProcessor)
            mProcessor->sendMidiFromUI(0xB0, 1, 0);
        mTriggered = false;

        repaint();
    }

private:
    juce::RangedAudioParameter* mParam = nullptr;
    juce::Image mGradient;
    KR106AudioProcessor* mProcessor = nullptr;
    float mDragStartVal = 0.5f;
    int mDragStartY = 0;
    bool mTriggered = false;
};
