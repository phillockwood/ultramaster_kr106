CXX ?= clang++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra
DEPS = $(wildcard ../../Source/DSP/*.h) ../../Source/KR106_Presets_JUCE.h

dsp_profile: dsp_profile.cpp $(DEPS)
	$(CXX) $(CXXFLAGS) -o $@ dsp_profile.cpp

clean:
	rm -f dsp_profile

.PHONY: clean
