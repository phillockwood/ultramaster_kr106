#!/usr/bin/env python3
"""
Fit slider position (0-218px, normalized 0-1) → ms curves for Juno-106 ADSR.
Generates 128-entry C++ LUTs for KR106_DSP.h.
"""

import csv
import numpy as np
from scipy.interpolate import PchipInterpolator
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))

SLIDER_MAX_PX = 218.0

# Known endpoints
# Decay/Release minimum is 1.5ms at slider=0 (same as Attack)
# Attack/Decay/Release all max at 218px

# ── Load data ────────────────────────────────────────────────────────────────

def load_data(csv_path):
    data = {'A': [], 'D': [], 'R': []}
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row['Preset'].strip()
            a_sl = row.get('A Slider', '').strip()
            d_sl = row.get('D Slider', '').strip()
            r_sl = row.get('R Slider', '').strip()
            a_ms = row.get('Ams', '').strip()
            d_ms = row.get('Dms', '').strip().replace('..', '.')
            r_ms = row.get('Rms', '').strip()

            if a_sl and a_ms:
                try:
                    data['A'].append((int(a_sl), float(a_ms), name))
                except ValueError:
                    pass
            if d_sl and d_ms:
                try:
                    data['D'].append((int(d_sl), float(d_ms), name))
                except ValueError:
                    pass
            if r_sl and r_ms:
                try:
                    data['R'].append((int(r_sl), float(r_ms), name))
                except ValueError:
                    pass
    return data


csv_path = f"{script_dir}/preset_adsr_sliders.csv"
all_data = load_data(csv_path)

# ── Outlier exclusions ───────────────────────────────────────────────────────

exclude = {
    'A': set(),
    'D': {'A11 Brass'},       # 76px→1606ms, neighbors at 80px→877/890
    'R': {
        'A11 Brass',          # 80px→337ms, neighbors at 78px→815, 82px→930
        'B81 Low Dark Strings',  # 82px→9.5ms, clearly wrong
    },
}


# ── Build LUT ────────────────────────────────────────────────────────────────

def build_lut(name, data_pts, exclude_labels):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

    # Filter and sort by slider px
    pts = [(px, ms, label) for px, ms, label in data_pts if label not in exclude_labels]
    pts.sort(key=lambda x: x[0])

    # Add decay/release 0px→1.5ms anchor if no 0px data
    px_vals = [p[0] for p in pts]
    if 0 not in px_vals:
        pts.insert(0, (0, 1.5, '(anchor)'))
        print("  Added 0px→1.5ms anchor")

    # Group by slider px, take median ms for each
    from collections import defaultdict
    groups = defaultdict(list)
    for px, ms, label in pts:
        groups[px].append((ms, label))

    anchors = []
    for px in sorted(groups.keys()):
        ms_vals = [v[0] for v in groups[px]]
        median_ms = np.median(ms_vals)
        anchors.append((px, median_ms))
        if len(ms_vals) > 1:
            labels = [v[1] for v in groups[px]]
            print(f"  px={px:3d}: median of {len(ms_vals)} pts = {median_ms:.1f}ms  ({', '.join(labels)})")

    # Normalize to 0-1
    x = np.array([a[0] / SLIDER_MAX_PX for a in anchors])
    y = np.array([a[1] for a in anchors])

    # PCHIP fit
    pchip = PchipInterpolator(x, y)

    # Generate 128-entry LUT (0-1 in 128 steps)
    lut_x = np.linspace(0, 1, 128)
    lut_y = np.clip(pchip(lut_x), y[0], y[-1])

    # Enforce monotonicity
    for i in range(1, 128):
        if lut_y[i] < lut_y[i-1]:
            lut_y[i] = lut_y[i-1]

    # Validate against all data (including excluded, marked)
    print(f"\n  {len(pts)} data points, {len(anchors)} unique slider positions")
    residuals = []
    for px, ms, label in data_pts:
        norm = px / SLIDER_MAX_PX
        pred = float(np.clip(pchip(norm), y[0], y[-1]))
        is_excluded = label in exclude_labels
        residuals.append((px, ms, pred, ms - pred, label, is_excluded))

    errs = [abs(r[3]) for r in residuals if not r[5]]
    if errs:
        rmse = np.sqrt(np.mean([r[3]**2 for r in residuals if not r[5]]))
        print(f"  RMSE = {rmse:.1f}ms  Max error = {max(errs):.1f}ms")

        worst = sorted([r for r in residuals if not r[5]], key=lambda r: abs(r[3]), reverse=True)[:10]
        print(f"\n  Worst residuals:")
        for px, actual, pred, err, label, _ in worst:
            pct = abs(err) / max(actual, 1) * 100
            print(f"    {label:25s} {px:3d}px: actual {actual:8.1f}ms, pred {pred:8.1f}ms, err {err:+.1f}ms ({pct:.0f}%)")

    # Print excluded
    excluded_r = [r for r in residuals if r[5]]
    if excluded_r:
        print(f"\n  Excluded:")
        for px, actual, pred, err, label, _ in excluded_r:
            print(f"    {label:25s} {px:3d}px: actual {actual:8.1f}ms, pred {pred:8.1f}ms")

    # Print C++ LUT
    tag = name.split()[0]
    print(f"\n  static constexpr float k{tag}LUT[128] = {{")
    for i in range(0, 128, 8):
        vals = [f"{lut_y[j]:.1f}f" for j in range(i, min(i+8, 128))]
        print(f"    {', '.join(vals)},")
    print(f"  }};")

    # Print key points
    print(f"\n  Key LUT values:")
    for idx in [0, 16, 32, 48, 64, 80, 96, 112, 127]:
        norm = idx / 127.0
        print(f"    [{idx:3d}] slider={norm:.3f} → {lut_y[idx]:.1f}ms")

    return pchip


print("Slider position (0-218px, normalized 0-1) → ms")
print("================================================")

build_lut("Attack slider→ms", all_data['A'], exclude['A'])
build_lut("Decay slider→ms", all_data['D'], exclude['D'])
build_lut("Release slider→ms", all_data['R'], exclude['R'])
