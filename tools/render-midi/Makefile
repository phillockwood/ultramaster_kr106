CXX ?= clang++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra
DSP = ../../Source/DSP

DEPS = $(wildcard $(DSP)/*.h)

all: render_midi peak_presets

render_midi: render_midi.cpp $(DEPS)
	$(CXX) $(CXXFLAGS) -o $@ render_midi.cpp

peak_presets: peak_presets.cpp $(DEPS) ../../Source/KR106_Presets_JUCE.h
	$(CXX) $(CXXFLAGS) -o $@ peak_presets.cpp

clean:
	rm -f render_midi peak_presets

.PHONY: all clean
