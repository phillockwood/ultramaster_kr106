import csv, math

# ResK_J6: k = 0.9 * (exp(2.128 * res) - 1)
# Then k > 3.0 gets soft-clipped: k = 3.0 + excess / (1 + excess * 0.2)
# Then k *= powf(ratio, -0.09) but that's frq-dependent, ignore for now
def res_to_k(res):
    k = 0.9 * (math.exp(2.128 * res) - 1.0)
    if k > 3.0:
        excess = k - 3.0
        k = 3.0 + excess / (1.0 + excess * 0.2)
    return k

print("frq,res,k,target_hz,measured_hz,metric,needed_g_mult")

with open("sweep_nocomp.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        frq = float(row["frq"])
        res = float(row["res"])
        target = float(row["target_hz"])
        k = res_to_k(res)

        if res in (0.0, 0.3, 0.5):
            # use -3dB cutoff
            fc = row["fc3db_hz"]
            if not fc: continue
            measured = float(fc)
            metric = "fc3db"
        elif res in (0.7, 0.8):
            # use peak
            peak = row["peak_hz"]
            if not peak: continue
            measured = float(peak)
            metric = "peak"
        else:
            continue

        # needed_g_mult = target / measured
        # (if measured is too low, we need g_mult > 1 to boost; if too high, < 1)
        g_mult = target / measured
        print(f"{frq},{res},{k:.4f},{target},{measured},{metric},{g_mult:.6f}")

