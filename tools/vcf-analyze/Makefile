CXX ?= clang++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra
DSP = ../../Source/DSP

all: vcf_analyze vcf_analyze_hw gen_filter_test gen_filter_test2 106_calibration res_calibrate

vcf_analyze: vcf_analyze.cpp
	$(CXX) $(CXXFLAGS) -o $@ vcf_analyze.cpp

vcf_analyze_hw: vcf_analyze_hw.cpp
	$(CXX) $(CXXFLAGS) -o $@ vcf_analyze_hw.cpp

gen_filter_test: gen_filter_test.cpp
	$(CXX) $(CXXFLAGS) -o $@ gen_filter_test.cpp

gen_filter_test2: gen_filter_test2.cpp
	$(CXX) $(CXXFLAGS) -o $@ gen_filter_test2.cpp

106_calibration: 106_calibration.cpp $(wildcard $(DSP)/*.h)
	$(CXX) $(CXXFLAGS) -o $@ 106_calibration.cpp

res_calibrate: res_calibrate.cpp $(wildcard $(DSP)/*.h)
	$(CXX) $(CXXFLAGS) -o $@ res_calibrate.cpp

clean:
	rm -f vcf_analyze vcf_analyze_hw gen_filter_test gen_filter_test2 106_calibration res_calibrate

.PHONY: all clean
