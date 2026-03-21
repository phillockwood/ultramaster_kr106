BUILD_DIR = build-juce
CONFIG   ?= Debug

.PHONY: build run reaper clean deps help

build:
	# Touch .cpp so CMake picks up header-only DSP changes
	@touch Source/PluginProcessor.cpp Source/PluginEditor.cpp
	cmake -B $(BUILD_DIR) -DCMAKE_BUILD_TYPE=$(CONFIG)
	cmake --build $(BUILD_DIR) --config $(CONFIG)

run: build
	-killall "Ultramaster KR-106" 2>/dev/null; sleep 0.5
	open "$(BUILD_DIR)/KR106_artefacts/$(CONFIG)/Standalone/Ultramaster KR-106.app"

reaper: build
	@echo "Restarting Reaper with fresh VST cache..."
	-killall REAPER 2>/dev/null; sleep 1
	rm -f "$(HOME)/Library/Application Support/REAPER/reaper-vstplugins64.ini"
	open -a REAPER

clean:
	rm -rf $(BUILD_DIR)

# Linux: install JUCE build dependencies
deps:
	sudo apt-get update
	sudo apt-get install -y \
	  libasound2-dev \
	  libx11-dev libxrandr-dev libxinerama-dev libxcursor-dev \
	  libfreetype-dev \
	  libwebkit2gtk-4.1-dev \
	  mesa-common-dev libgl-dev

help:
	@echo ""
	@echo "Ultramaster KR-106"
	@echo ""
	@echo "  make build        Build all formats (AU, VST3, LV2, Standalone)"
	@echo "  make run          Build and launch Standalone (macOS)"
	@echo "  make reaper       Build and restart Reaper (macOS)"
	@echo "  make deps         Install Linux build dependencies (apt)"
	@echo "  make clean        Remove build directory"
	@echo ""
	@echo "  CONFIG=Release make build  — release build"
	@echo ""
