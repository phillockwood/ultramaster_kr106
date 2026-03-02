PROJECT  = projects/KR106-macOS.xcodeproj
CONFIG  ?= Debug

# ── Targets ──────────────────────────────────────────────────────────────────

.PHONY: app vst3 au clap all clean presets help check-iplug2

app: check-iplug2
	xcodebuild -project "$(PROJECT)" -target APP -configuration $(CONFIG)

vst3: check-iplug2
	xcodebuild -project "$(PROJECT)" -target VST3 -configuration $(CONFIG)

au: check-iplug2
	xcodebuild -project "$(PROJECT)" -target AU -configuration $(CONFIG)

clap: check-iplug2
	xcodebuild -project "$(PROJECT)" -target CLAP -configuration $(CONFIG)

all: check-iplug2
	xcodebuild -project "$(PROJECT)" -target All -configuration $(CONFIG)

clean:
	xcodebuild -project "$(PROJECT)" -target All -configuration $(CONFIG) clean

presets:
	python3 scripts/gen_presets.py

# ── Helpers ───────────────────────────────────────────────────────────────────

check-iplug2:
	@test -f ../iPlug2/common-mac.xcconfig || \
	  (echo ""; \
	   echo "ERROR: iPlug2 not found at ../iPlug2"; \
	   echo "Clone iPlug2 as a sibling directory:"; \
	   echo "  cd .. && git clone https://github.com/iPlug2/iPlug2"; \
	   echo ""; exit 1)

help:
	@echo ""
	@echo "Ultramaster KR-106 — build targets"
	@echo ""
	@echo "  make app          Standalone .app (default: Debug)"
	@echo "  make vst3         VST3 plugin"
	@echo "  make au           Audio Unit (AUv2)"
	@echo "  make clap         CLAP plugin"
	@echo "  make all          All formats"
	@echo "  make clean        Remove build artifacts"
	@echo "  make presets      Regenerate KR106_Presets.h from patch files"
	@echo ""
	@echo "  CONFIG=Release make vst3   — release build"
	@echo ""
	@echo "Requires: Xcode, iPlug2 cloned as sibling at ../iPlug2 (see README)"
	@echo ""
