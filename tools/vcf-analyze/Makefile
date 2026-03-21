CXX ?= clang++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra
TARGET = vcf_analyze

all: $(TARGET)

$(TARGET): vcf_analyze.cpp ../../Source/DSP/KR106VCF.h
	$(CXX) $(CXXFLAGS) -o $@ vcf_analyze.cpp

clean:
	rm -f $(TARGET)

.PHONY: all clean
