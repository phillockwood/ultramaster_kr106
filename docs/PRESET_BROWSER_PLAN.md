# Preset Browser — 18 Buttons

## Context

The plugin's 128 factory presets (A11–A88, B11–B88) are only accessible via
MIDI program change or host preset mechanisms. Ableton VST3 and the standalone
app have no way to browse them. Adding 18 buttons (2 group + 8 bank + 8 patch)
gives direct, always-visible preset selection matching the Juno-106 naming.

## Preset Organization

128 presets indexed 0–127:
- Group A = indices 0–63, Group B = indices 64–127
- Bank 1–8 within each group (8 patches per bank)
- Patch 1–8 within each bank
- Index = group×64 + (bank-1)×8 + (patch-1)

## Files to Modify

1. **`Source/Controls/KR106Button.h`** — new `KR106PresetButton` control class
2. **`Source/PluginEditor.h`** — preset selection state, 18 button pointers
3. **`Source/PluginEditor.cpp`** — create 18 buttons, wire click → `setCurrentProgram`
4. **`Source/PluginProcessor.h`** — expose `mCurrentPreset` for UI to read

## Design

### New Control: `KR106PresetButton`

A simple button (no parameter binding) that draws using existing `DrawKR106Button()`.
Tracks its own "selected" state for visual highlight.

```cpp
class KR106PresetButton : public juce::Component
{
public:
    KR106PresetButton(const juce::String& label, int buttonType,
                      std::function<void()> onClick)
        : mLabel(label), mButtonType(buttonType), mOnClick(std::move(onClick)) {}

    void setSelected(bool sel) { mSelected = sel; repaint(); }
    bool isSelected() const { return mSelected; }

    void paint(juce::Graphics& g) override
    {
        DrawKR106Button(g, 0.f, 0.f, w, h, mButtonType, mPressed || mSelected);
        // Draw label text centered on button face
    }

    void mouseDown(const juce::MouseEvent&) override
    {
        mPressed = true;
        if (mOnClick) mOnClick();
        repaint();
    }

    void mouseUp(const juce::MouseEvent&) override
    {
        mPressed = false;
        repaint();
    }

private:
    juce::String mLabel;
    int mButtonType;
    bool mPressed = false;
    bool mSelected = false;
    std::function<void()> mOnClick;
};
```

### Editor State

```cpp
// Preset browser state
int mPresetGroup = 0;  // 0=A, 1=B
int mPresetBank  = 0;  // 0–7
int mPresetPatch = 0;  // 0–7

KR106PresetButton* mGroupBtns[2]  = {};
KR106PresetButton* mBankBtns[8]   = {};
KR106PresetButton* mPatchBtns[8]  = {};
```

### Button Click Logic

- **Group button** click: set `mPresetGroup`, call `loadPreset()`
- **Bank button** click: set `mPresetBank`, call `loadPreset()`
- **Patch button** click: set `mPresetPatch`, call `loadPreset()`

```cpp
void loadPreset()
{
    int idx = mPresetGroup * 64 + mPresetBank * 8 + mPresetPatch;
    mProcessor.setCurrentProgram(idx);
    updatePresetButtons();  // refresh selected states
}

void updatePresetButtons()
{
    for (int i = 0; i < 2; i++) mGroupBtns[i]->setSelected(i == mPresetGroup);
    for (int i = 0; i < 8; i++) mBankBtns[i]->setSelected(i == mPresetBank);
    for (int i = 0; i < 8; i++) mPatchBtns[i]->setSelected(i == mPresetPatch);
}
```

### Sync from Host/MIDI

When the host changes the program (via `setCurrentProgram` from MIDI program
change or host preset browser), the editor needs to update. In `timerCallback`,
check `mProcessor.getCurrentProgram()` and decompose back to group/bank/patch:

```cpp
int cur = mProcessor.getCurrentProgram();
int newGroup = cur / 64;
int newBank  = (cur % 64) / 8;
int newPatch = cur % 8;
if (newGroup != mPresetGroup || newBank != mPresetBank || newPatch != mPresetPatch)
{
    mPresetGroup = newGroup;
    mPresetBank  = newBank;
    mPresetPatch = newPatch;
    updatePresetButtons();
}
```

### Button Placement

User will update the background image and provide coordinates. Buttons will use
existing `DrawKR106Button()` with button types:
- Group A/B: type 1 (Yellow) or type 2 (Orange)
- Bank 1–8: type 0 (Cream)
- Patch 1–8: type 0 (Cream)

Labels drawn as small text centered on each button face ("A", "B", "1"–"8").

### Preset Name Display

Show the current preset name (e.g. "A35 Funky") somewhere — could be in the
tooltip area, or drawn on the background near the buttons. TBD based on
background image layout.

## Waiting On

- Updated background image with preset button area
- Button coordinates (x, y, w, h for each of the 18 buttons)
- Whether preset name should be displayed, and where

## Verification

- Click each group/bank/patch button → correct preset loads
- Selected buttons stay highlighted
- MIDI program change updates button selection
- Host preset change (e.g. Logic program list) syncs buttons
- All 128 presets accessible (A11 through B88)
- Live performance params preserved on preset change (existing behavior)
