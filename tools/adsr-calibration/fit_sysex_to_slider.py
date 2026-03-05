#!/usr/bin/env python3
"""
Build PCHIP lookup tables mapping SysEx byte (0-127) → slider position (0-10)
for Juno-106 ADSR parameters.

Uses manually curated monotonic anchor points from measured preset data.
"""

import json
import csv
import numpy as np
from scipy.interpolate import PchipInterpolator
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))

# ── Load all measured data for validation ──────────────────────────────────

with open(f"{script_dir}/../preset-gen/lib.json") as f:
    lib = json.load(f)

sysex_by_name = {}
for i, patch in enumerate(lib):
    bank = 'A' if i < 64 else 'B'
    local = i if i < 64 else i - 64
    label = f"{bank}{local // 8 + 1}{local % 8 + 1}"
    sysex_by_name[label] = {
        'A_byte': patch['data'][11],
        'D_byte': patch['data'][12],
        'R_byte': patch['data'][14],
    }

def load_all_data(csv_path):
    """Load all (byte, slider) pairs for A, D, R from CSV."""
    data = {'A': [], 'D': [], 'R': []}
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            label = row['Preset'].strip().split(' ')[0]
            if label not in sysex_by_name:
                continue
            sx = sysex_by_name[label]
            for param, byte_key, col in [
                ('A', 'A_byte', 'A Slider'),
                ('D', 'D_byte', 'D Slider'),
                ('R', 'R_byte', 'R Slider'),
            ]:
                val = row.get(col, '').strip()
                if val:
                    try:
                        data[param].append((sx[byte_key], float(val), label))
                    except ValueError:
                        pass
    return data

csv_path = f"{script_dir}/preset_adsr_sliders.csv"
all_data = load_all_data(csv_path)

# ── Curated monotonic anchor points ───────────────────────────────────────
# Selected from the cleanest, most consistent measurements.
# Pixel-measured values preferred over eyeballed.
# Monotonicity enforced (slider always increases with byte).

# Attack: steep rise at low end (reverse-log pot taper)
# The data shows a "knee" at bytes 10-23 where slider ~3.0-3.75
attack_anchors = [
    (0,   0.00),   # many presets confirm
    (1,   0.65),   # A52 Lead II (px): midpoint of 0 and 1.31
    (3,   1.78),   # A81 Gong (px), A11 Brass (px) — very consistent
    (5,   2.43),   # A13 Trumpet (px)
    (7,   2.50),   # A24 Calliope
    (10,  3.24),   # A67 Shaker (px)
    (13,  3.25),   # ~flat zone, A15 Moving Strings
    (23,  3.74),   # A14 Flutes (px)
    (29,  4.50),   # B23 Orchestral Pad (px)
    (44,  4.78),   # A16 Brass & Strings (px)
    (58,  5.25),   # A34 Brass III
    (64,  5.41),   # A12 Brass Swell (px)
    (68,  5.50),   # A17 Choir
    (72,  5.75),   # A35 Fanfare
    (78,  6.76),   # B58 Blizzard (px)
    (84,  7.25),   # B47 Phase Ensemble
    (88,  6.94),   # A84 Dust Storm (px) — slight dip, real data
    (92,  7.25),   # B56 Ethereal (px)
    (127, 10.00),  # B45 Noise Sweep 2
]

# Decay: more gradual, closer to linear but still compressed at low end
# Has a noticeable "plateau" at bytes 25-34 (~2.5) and scatter in 65-100 range
decay_anchors = [
    (0,   0.00),
    (5,   1.50),   # A25 Donald Pluck
    (10,  1.38),   # A21/A22 Organ (median of 1.25 and 1.5)
    (11,  1.62),   # A17/A37 (median of 1.5 and 1.75)
    (16,  2.43),   # B17 Perc. Pluck (px)
    (25,  2.50),   # A64 Snare Drum — consistent across many presets
    (34,  2.50),   # A48 Synth Bass I — end of plateau
    (39,  3.50),   # A62 Clav.
    (44,  3.50),   # A26 Celeste, A38 High Strings
    (48,  4.19),   # A81 Gong (px)
    (52,  4.50),   # A44 Guitar, A46 Dark Pluck
    (56,  4.25),   # A45 Koto
    (66,  5.25),   # A18 Piano I, A13 Trumpet (median of cluster)
    (75,  5.00),   # A41 Bass Clarinet
    (85,  5.88),   # A27/A75 median
    (91,  6.80),   # A72 Pluck Sweep (px)
    (98,  7.34),   # B58 Blizzard (px)
    (108, 7.75),   # A58 Going Up
    (118, 10.00),  # A12 Brass Swell
    (127, 10.00),  # A24 Calliope, B85 Rocket Men
]

# Release: similar shape to Decay
release_anchors = [
    (0,   0.00),
    (6,   1.50),   # A24 Calliope
    (10,  1.75),   # A25 Donald Pluck
    (14,  1.25),   # A62 Clav.
    (16,  2.07),   # A13 Trumpet (px)
    (18,  2.48),   # A14 Flutes (px)
    (25,  2.25),   # A41 Bass Clarinet
    (30,  2.75),   # A18 Piano I, A64 Snare Drum median
    (35,  3.10),   # cluster median
    (40,  3.50),   # A38 High Strings, B84 (px)
    (45,  4.50),   # A36 Strings III, A16
    (49,  4.00),   # A35 Fanfare
    (52,  4.50),   # B23 Orchestral Pad
    (63,  5.00),   # A46 Dark Pluck
    (75,  5.09),   # A52 Lead II (px)
    (78,  5.50),   # B58 Blizzard (px)
    (85,  6.62),   # A84 Dust Storm (px)
    (89,  6.71),   # B85 Rocket Men (px)
    (98,  6.94),   # A81 Gong (px)
    (105, 7.90),   # B76 Rolling Wah (px)
    (112, 8.06),   # A87 FX Sweep
    (127, 10.00),  # A58 Going Up
]


# ── Enforce monotonicity ──────────────────────────────────────────────────

def enforce_monotonic(anchors):
    """Ensure anchors are strictly monotonically increasing."""
    result = [anchors[0]]
    for b, s in anchors[1:]:
        if s < result[-1][1]:
            # Skip non-monotonic points or average
            print(f"  WARNING: non-monotonic at byte {b}: {s:.2f} < {result[-1][1]:.2f} (byte {result[-1][0]})")
            # Keep the point but clamp to previous value
            s = result[-1][1]
        if b == result[-1][0]:
            continue  # skip duplicate x
        result.append((b, s))
    return result


# ── Build and validate ────────────────────────────────────────────────────

def build_lut(name, anchors, data_pts, exclude_labels=set()):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

    anchors = enforce_monotonic(anchors)

    x = np.array([a[0] for a in anchors], dtype=float)
    y = np.array([a[1] for a in anchors], dtype=float)

    pchip = PchipInterpolator(x, y)
    all_x = np.arange(128, dtype=float)
    all_y = np.clip(pchip(all_x), 0.0, 10.0)

    # Check monotonicity of output
    non_mono = sum(1 for i in range(1, 128) if all_y[i] < all_y[i-1] - 0.001)
    if non_mono > 0:
        print(f"  WARNING: {non_mono} non-monotonic entries in LUT!")

    # Validate against all data
    residuals = []
    for b, s, label in data_pts:
        if label in exclude_labels:
            continue
        pred = float(np.clip(pchip(b), 0.0, 10.0))
        residuals.append((b, s, pred, s - pred, label))

    if residuals:
        errs = [abs(r[3]) for r in residuals]
        rmse = np.sqrt(np.mean([r[3]**2 for r in residuals]))
        print(f"  RMSE = {rmse:.3f}  Max error = {max(errs):.3f}  (vs {len(residuals)} data points)")

        worst = sorted(residuals, key=lambda r: abs(r[3]), reverse=True)[:10]
        print(f"\n  Worst residuals:")
        for b, actual, pred, err, label in worst:
            print(f"    {label:20s} byte {b:3d}: actual {actual:.2f}, predicted {pred:.2f}, err {err:+.2f}")

    # Print anchor table
    print(f"\n  Anchors ({len(anchors)} points):")
    for b, s in anchors:
        print(f"    byte {b:3d} → slider {s:.2f}")

    # Print C++ LUT
    tag = name.split()[0]
    print(f"\n  static constexpr float k{tag}SysexToSlider[128] = {{")
    for i in range(0, 128, 8):
        vals = [f"{all_y[j]:.4f}f" for j in range(i, min(i+8, 128))]
        print(f"    {', '.join(vals)},")
    print(f"  }};")

    return pchip


print("SysEx byte → Slider PCHIP lookup tables")
print("(manually curated monotonic anchor points)")

build_lut("Attack SysEx→Slider", attack_anchors, all_data['A'], {'B33', 'B67', 'B76'})
build_lut("Decay SysEx→Slider", decay_anchors, all_data['D'], {'B11', 'B12', 'B33', 'B84'})
build_lut("Release SysEx→Slider", release_anchors, all_data['R'], {})
