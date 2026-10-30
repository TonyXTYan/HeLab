"""Per-channel pulse spacing (same-channel consecutive intervals) and pulse budget per set:
pulses per channel relative to hits, the shortest interval (dead time), and excess at short
intervals (ringing: a second pulse a fixed delay after the first). Also the D-pedestal estimate of
the fraction of hits that are random combinations. Writes out/pulse_spacing.json, figures/ps_*.png."""
from __future__ import annotations

import json
import numpy as np
from common import OUT, SCRATCH, BIN, figure, save

H = SCRATCH / "hits"
SETS = ["p25-0625-ramsey", "p25-07-tight", "p22-2023-03-bells", "p22-2024-11-lowocc", "p22-2022-11-ghost-mcp",
        "p17-2022-07-large-he3", "p17-2020-halos"]
NAMES = ["x1", "x2", "y1", "y2"]
res = {}
fig = figure(14, 8)
axs = fig.subplots(2, 4).ravel()
for si, name in enumerate(SETS):
    z = np.load(H / f"{name}.npz", allow_pickle=True)
    npulse = z["npulse"]
    hits = len(z["T"])
    tot = npulse[:, 1:5].sum(axis=0)
    r = {"files": int(z["files"]), "hits": hits, "pulses": dict(zip(NAMES, tot.astype(int).tolist())),
         "pulses_per_hit": dict(zip(NAMES, np.round(tot / hits, 3).tolist())),
         "x1_over_mean_others": float(tot[0] / tot[1:].mean()), "x2_over_mean_y": float(tot[1] / tot[2:].mean())}
    D = z["x1"] + z["x2"] - z["y1"] - z["y2"]
    med = np.median(D)
    ped = ((np.abs(D - med) > 250) & (np.abs(D) < 400)).sum()
    width = (np.minimum(400, med + 1e9) - (med + 250)) + ((med - 250) - (-400))
    dens = ped / max(width, 1)
    r["random_combination_fraction_est"] = float(dens * 800 / hits)
    spacing = {}
    for k in range(4):
        iv = np.concatenate([np.diff(p) for p in z[f"pulses{k}"]]) * BIN * 1e9  # ns
        h, e = np.histogram(iv, bins=np.arange(0, 2001, 5))
        flat = h[(e[:-1] > 1000)].mean()
        mn = float(np.percentile(iv, 0.01))
        excess = (h[e[:-1] < 300] - flat).clip(0).sum() / len(iv)
        peak = float(e[np.argmax(h[:60])]) if h[:60].max() > 3 * flat else None
        spacing[NAMES[k]] = {"min_ns_p0.01": round(mn, 2), "excess_below_300ns_frac": round(float(excess), 4),
                             "peak_ns": peak, "frac_below_50ns": round(float((iv < 50).mean()), 4),
                             "frac_below_300ns": round(float((iv < 300).mean()), 4)}
        axs[si].plot(e[:-1] + 2.5, np.maximum(h, 0.5), label=NAMES[k], lw=1)
    r["spacing"] = spacing
    axs[si].set_yscale("log"); axs[si].set_xlim(0, 600); axs[si].set_title(name, fontsize=9)
    axs[si].set_xlabel("same-channel interval [ns]")
    if si == 0:
        axs[si].legend()
    res[name] = r
axs[-1].axis("off")
fig.suptitle("Same-channel pulse intervals (first 60 files per set; 5 ns bins)")
save(fig, "ps_intervals.png")
(OUT / "pulse_spacing.json").write_text(json.dumps(res, indent=1))
for n, r in res.items():
    print(n, r["pulses_per_hit"], "x1/others %.3f" % r["x1_over_mean_others"], "random comb %.3f" % r["random_combination_fraction_est"])
    for c, s in r["spacing"].items():
        print("    ", c, s)
