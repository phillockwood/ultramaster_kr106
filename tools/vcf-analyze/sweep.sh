#!/bin/bash
# VCF frequency compensation sweep test
# Runs vcf_analyze across a grid of (frq, res) values and writes CSV.
#
# Usage: ./sweep.sh [output.csv] [samplerate]
#   output.csv: default sweep_raw.csv
#   samplerate: default 44100

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOL="$SCRIPT_DIR/vcf_analyze"
OUTPUT="${1:-sweep_raw.csv}"
SR="${2:-44100}"

if [ ! -x "$TOOL" ]; then
    echo "Building vcf_analyze..." >&2
    make -C "$SCRIPT_DIR" -s || exit 1
fi

# Fine grid at low frq (0.04–0.30 step 0.02), coarser above (step 0.05)
FRQS="0.04 0.06 0.08 0.10 0.12 0.14 0.16 0.18 0.20 0.22 0.24 0.26 0.28 0.30 0.35 0.40 0.45 0.50 0.55 0.60 0.65 0.70 0.75 0.80"
RESS="0.0 0.3 0.5 0.7 0.8 0.9 1.0"

echo "frq,res,target_hz,peak_hz,peak_err_cents,peak_prom_db,fc3db_hz,fc3db_err_cents,self_osc,osc_freq" | tee "$OUTPUT"

for f in $FRQS; do
    for r in $RESS; do
        out=$("$TOOL" "$f" "$r" "$SR" 2>/dev/null)

        target=$(echo "$out" | sed -n 's/.*Target freq: *\([0-9.]*\).*/\1/p')

        peak_line=$(echo "$out" | grep "Res peak (")
        if [ -n "$peak_line" ]; then
            peak=$(echo "$peak_line" | sed 's/.*): *//;s/ Hz.*//')
            prom=$(echo "$peak_line" | sed 's/.*(//;s/ dB.*//')
            pcents=$(echo "$peak_line" | sed 's/.*error: *//;s/ cents.*//')
        else
            peak=""
            prom=$(echo "$out" | grep "Res peak:" | sed 's/.*prominence //;s/ dB.*//')
            pcents=""
        fi

        fc3=$(echo "$out" | grep "3dB cutoff:" | sed -n 's/.*: *\([0-9.]*\) Hz.*/\1/p')
        fc3c=$(echo "$out" | grep "3dB cutoff:" | sed -n 's/.*error: *\([^ ]*\) cents.*/\1/p')
        osc=$(echo "$out" | grep "Self-oscillation:" | awk '{print $2}')
        oscf=$(echo "$out" | grep "Zero-cross freq:" | sed 's/.*: *//;s/ Hz.*//')

        echo "$f,$r,$target,$peak,$pcents,$prom,$fc3,$fc3c,$osc,$oscf" | tee -a "$OUTPUT"
    done
done

echo "" >&2
echo "Sweep complete: $OUTPUT ($(wc -l < "$OUTPUT") rows)" >&2
