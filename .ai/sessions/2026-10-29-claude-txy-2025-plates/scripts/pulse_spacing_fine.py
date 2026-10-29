"""Same-channel intervals at 1 ns resolution, 0-400 ns, per pulse; reflection-peak positions and the
shortest intervals. Writes out/pulse_spacing_fine.json and figures/ps_fine.png."""
import json
import numpy as np
from common import OUT, SCRATCH, BIN, figure, save

H = SCRATCH / "hits"
SETS = {"2025 plates Jun 2026 (0625 Ramsey)": "p25-0625-ramsey", "2025 plates Jul 2026 (tight trap)": "p25-07-tight",
        "2022 plates 2023-03": "p22-2023-03-bells", "2022 plates 2024-11": "p22-2024-11-lowocc",
        "2017 plates 2022-07": "p17-2022-07-large-he3"}
NAMES = ["x1", "x2", "y1", "y2"]
fig = figure(14, 7)
axs = fig.subplots(2, 2).ravel()
res = {}
for label, name in SETS.items():
    z = np.load(H / f"{name}.npz", allow_pickle=True)
    r = {}
    for k in range(4):
        iv = np.concatenate([np.diff(p) for p in z[f"pulses{k}"]]) * BIN * 1e9
        h, e = np.histogram(iv, bins=np.arange(0, 401, 1))
        sel = (e[:-1] >= 140) & (e[:-1] < 240)
        pk = float(e[:-1][sel][np.argmax(h[sel])] + 0.5)
        # centroid of the peak +-10 ns above the 240-300 ns level
        base = h[(e[:-1] >= 260) & (e[:-1] < 320)].mean()
        w = (e[:-1] >= pk - 10) & (e[:-1] <= pk + 10)
        cen = float(((e[:-1][w] + 0.5) * (h[w] - base).clip(0)).sum() / max((h[w] - base).clip(0).sum(), 1))
        r[NAMES[k]] = {"reflection_peak_ns": round(cen, 1),
                       "reflection_excess_per_pulse": round(float((h[(e[:-1] >= pk - 15) & (e[:-1] <= pk + 15)] - base).clip(0).sum() / len(iv)), 4),
                       "shortest_ns_p0.1": round(float(np.percentile(iv, 0.1)), 1),
                       "frac_below_100ns": round(float((iv < 100).mean()), 4)}
        axs[k].plot(e[:-1] + 0.5, h / len(iv), lw=0.8, label=label)
    res[label] = r
for k in range(4):
    axs[k].set_yscale("log"); axs[k].set_title(f"{NAMES[k]}: same-channel intervals (1 ns bins, per pulse)")
    axs[k].set_xlabel("interval [ns]")
axs[0].legend(fontsize=7)
save(fig, "ps_fine.png")
(OUT / "pulse_spacing_fine.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
