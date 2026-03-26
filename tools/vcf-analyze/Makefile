CXX ?= clang++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra
DSP = ../../Source/DSP

all: vcf_analyze gen_filter_test gen_filter_test2

vcf_analyze: vcf_analyze.cpp
	$(CXX) $(CXXFLAGS) -o $@ vcf_analyze.cpp

gen_filter_test: gen_filter_test.cpp
	$(CXX) $(CXXFLAGS) -o $@ gen_filter_test.cpp

gen_filter_test2: gen_filter_test2.cpp
	$(CXX) $(CXXFLAGS) -o $@ gen_filter_test2.cpp

clean:
	rm -f vcf_analyze gen_filter_test gen_filter_test2

.PHONY: all clean
