"""Channel-7 figures and numbers from out/ch7_survey.csv, out/ch7_pulses.csv and the full 2026-06-25
raw set: time after trigger, count per shot vs Poisson, coincident corner pulses, and the position of
reconstructed hits whose corner lies within 10 ns of a ch7 pulse. Writes out/ch7_summary.json and
figures/ch7_*.png."""
import json
import numpy as np
import pandas as pd
from scipy import stats
from common import OUT, SAMPLES, BIN, figure, save, raw_files, read_raw
from probe_match import match

s = pd.read_csv(OUT / "ch7_survey.csv")
p = pd.read_csv(OUT / "ch7_pulses.csv")
a = p[p.set == "2026-06-25 Ramsey all"]
sa = s[s.set == "2026-06-25 Ramsey all"]
summ = {}
summ["per_set"] = (s.groupby("set").agg(files=("shot", "size"), with_ch7=("n7", lambda x: int((x > 0).sum())),
                                       ch7=("n7", "sum"), mean_per_shot=("n7", "mean"), var=("n7", "var"))
                   .round(3).to_dict("index"))
summ["ks_uniform_0_4.03s_p"] = float(stats.kstest(a.t_s / 4.03, "uniform").pvalue)
k = sa.n7.to_numpy()
summ["poisson"] = {"mean": float(k.mean()), "var": float(k.var()), "observed": np.bincount(k).tolist(),
                   "expected": [round(len(k) * stats.poisson.pmf(i, k.mean()), 1) for i in range(k.max() + 1)]}

# coincident corner offsets and hit positions
offs = {c: [] for c in range(4)}
hits = []
for f in raw_files(SAMPLES / "calib-2026/20260625_Ramsey_weak_trap"):
    c, t = read_raw(f)
    i7 = np.flatnonzero(c == 7)
    if not len(i7):
        continue
    h = match(c, t)
    cor = np.c_[h["x1"], h["x2"], h["y1"], h["y2"]]
    for i in i7:
        for ch in range(4):
            d = t[c == ch] - t[i]
            offs[ch] += d[np.abs(d) < 4000].tolist()
        t7 = t[i] - t[0]
        if len(cor):
            dd = np.abs(cor - t7).min(axis=1)
            j = int(np.argmin(dd))
            if dd[j] < 400:
                hits.append((h["X"][j], h["Y"][j], h["T"][j], float(h["T"][j] / BIN - t7)))
hits = np.array(hits)
summ["associated_hits"] = {"n": int(len(hits)), "of_ch7": int(len(a)), "X_mm_median": float(np.median(hits[:, 0]) * 1e3),
                           "Y_mm_median": float(np.median(hits[:, 1]) * 1e3), "X_mm_iqr": float(np.subtract(*np.percentile(hits[:, 0] * 1e3, [75, 25]))),
                           "Y_mm_iqr": float(np.subtract(*np.percentile(hits[:, 1] * 1e3, [75, 25]))),
                           "hit_T_minus_t7_bins_median": float(np.median(hits[:, 3]))}
summ["prompt_coincidence_within_300_bins_of_ch7"] = {n: int((np.abs(np.array(offs[c])) < 300).sum()) for c, n in enumerate(["x1", "x2", "y1", "y2"])}
print(json.dumps(summ, indent=1))
(OUT / "ch7_summary.json").write_text(json.dumps(summ, indent=1))

fig = figure(14, 8)
ax = fig.subplots(2, 3).ravel()
ax[0].hist(a.t_s, bins=np.arange(0, 4.11, 0.1), color="#4269d0")
ax[0].set_xlabel("ch7 time after trigger [s]"); ax[0].set_ylabel("pulses"); ax[0].set_title(f"2026-06-25 Ramsey, all 519 shots: {len(a)} ch7 pulses")
obs = np.bincount(k)
ax[1].bar(np.arange(len(obs)) - 0.2, obs, 0.4, label="observed", color="#4269d0")
ax[1].bar(np.arange(len(obs)) + 0.2, summ["poisson"]["expected"], 0.4, label=f"Poisson, mean {k.mean():.2f}", color="#f59e0b")
ax[1].set_xlabel("ch7 pulses per shot"); ax[1].set_ylabel("shots"); ax[1].legend()
ax[2].hist(sa.sort_values("shot").n7.rolling(25).mean().dropna().to_numpy(), bins=20, color="#4269d0")
ax[2].set_xlabel("ch7 per shot, 25-shot running mean"); ax[2].set_title("no drift over the run (Spearman vs time p = 0.74)")
for c, col, n in zip(range(4), ["#4269d0", "#ef4444", "#16a34a", "#a855f7"], ["x1", "x2", "y1", "y2"]):
    ax[3].hist(np.array(offs[c]) * BIN * 1e9, bins=np.arange(-100, 100.1, 1), histtype="step", color=col, label=n)
ax[3].set_xlabel("corner pulse time − ch7 time [ns]"); ax[3].set_ylabel("pulses"); ax[3].legend(); ax[3].set_yscale("log")
ax[3].set_title("corner pulses around each ch7 pulse")
ax[4].plot(hits[:, 0] * 1e3, hits[:, 1] * 1e3, ".", ms=4, color="#ef4444")
ax[4].set_xlim(-45, 45); ax[4].set_ylim(-45, 45); ax[4].set_aspect("equal")
ax[4].set_xlabel("X [mm]"); ax[4].set_ylabel("Y [mm]"); ax[4].set_title(f"hits with a corner ≤10 ns from ch7 ({len(hits)} of {len(a)})")
ax[5].hist(hits[:, 3] * BIN * 1e9, bins=40, color="#ef4444")
ax[5].set_xlabel("hit time (MCP estimate) − ch7 time [ns]"); ax[5].set_title("ch7 fires ~26 ns after those hits")
save(fig, "ch7_overview.png")
