"""Channel 7 in detail on every raw file of 2026-06-25 Ramsey (519 shots, 681 ch7 pulses), each
statistic beside a control: the same statistic at random times (uniform over each shot, 20 per ch7
pulse) and, where useful, at the times of ordinary x1 pulses.

1. corner pulses near ch7: first pulse per channel in [-50, +150] ns, offsets and order;
2. time sums with ch7 as if it were an MCP pulse: x1 + x2 - 2 t7 and y1 + y2 - 2 t7 (pulses within
   [-20, +150] ns of t7);
3. bursts: pulses per channel within +-1 us and +-10 us of ch7;
4. the matched hit near ch7 (corner within 10 ns): its corner offsets from t7 and its position;
   the spot (-6.6, -10.3) mm in the image (rate, size, time clustering);
5. channel 5's extra rows for comparison.
Writes out/ch7_deep.json and figures/ch7_deep_*.png."""
from __future__ import annotations

import json
import numpy as np
from common import OUT, SAMPLES, BIN, M_PER_BIN, SCRATCH, figure, save, raw_files, read_raw
from probe_match import match

rng = np.random.default_rng(7)
files = raw_files(SAMPLES / "calib-2026/20260625_Ramsey_weak_trap")
NS = 1e-9 / BIN  # bins per ns
first = {k: [] for k in range(4)}
first_rand = {k: [] for k in range(4)}
sums = {"x": [], "y": [], "x_rand": [], "y_rand": []}
mult = {"ch7": {w: [] for w in (1, 10)}, "rand": {w: [] for w in (1, 10)}, "x1": {w: [] for w in (1, 10)}}
assoc = []
n7 = 0
ch5 = []


def firsts(c, t, t_ref, store):
    for k in range(4):
        tk = t[c == k]
        j = np.searchsorted(tk, t_ref - 50 * NS)
        if j < len(tk) and tk[j] <= t_ref + 150 * NS:
            store[k].append((tk[j] - t_ref) / NS)
        else:
            store[k].append(np.nan)


def time_sums(c, t, t_ref, xs, ys):
    for (a, b, out) in ((0, 1, xs), (2, 3, ys)):
        ta = t[(c == a) & (t > t_ref - 20 * NS) & (t < t_ref + 150 * NS)]
        tb = t[(c == b) & (t > t_ref - 20 * NS) & (t < t_ref + 150 * NS)]
        for p in ta:
            for q in tb:
                out.append((p + q - 2 * t_ref) / NS)


def multiplicity(c, t, t_ref, w_us, store):
    m = (np.abs(t - t_ref) < w_us * 1e3 * NS) & (c <= 3)
    store.append(int(m.sum()))


for f in files:
    c, t = read_raw(f)
    o = np.argsort(t, kind="stable")
    c, t = c[o], t[o].astype(np.int64)
    t0f = read_raw(f)[1][0]
    i5 = np.flatnonzero(c == 5)
    ch5.append(((t[i5] - t0f) * BIN * 1e6).tolist())
    i7 = np.flatnonzero(c == 7)
    if not len(i7):
        continue
    span = (t.min(), t.max())
    h = match(c[np.argsort(o)] if False else read_raw(f)[0], read_raw(f)[1])
    cor = np.c_[h["x1"], h["x2"], h["y1"], h["y2"]] + t0f  # back to absolute bins
    x1s = t[c == 0]
    for i in i7:
        n7 += 1
        t7 = t[i]
        firsts(c, t, t7, first)
        time_sums(c, t, t7, sums["x"], sums["y"])
        for w in (1, 10):
            multiplicity(c, t, t7, w, mult["ch7"][w])
        for tr in rng.uniform(*span, 20):
            firsts(c, t, tr, first_rand)
            time_sums(c, t, tr, sums["x_rand"], sums["y_rand"])
            for w in (1, 10):
                multiplicity(c, t, tr, w, mult["rand"][w])
        for tr in rng.choice(x1s, 5):
            for w in (1, 10):
                multiplicity(c, t, tr, w, mult["x1"][w])
        if len(cor):
            dd = np.abs(cor - t7).min(axis=1)
            j = int(np.argmin(dd))
            if dd[j] < 10 * NS:
                assoc.append(dict(file=f.name, X=float(h["X"][j]), Y=float(h["Y"][j]), T=float(h["T"][j]),
                                  off=((cor[j] - t7) / NS).round(2).tolist()))

res = {"ch7_pulses": n7}
names = ["x1", "x2", "y1", "y2"]
res["first_pulse_within_-50_150ns"] = {}
for k in range(4):
    a = np.array(first[k]); b = np.array(first_rand[k])
    res["first_pulse_within_-50_150ns"][names[k]] = {
        "share_ch7": round(float(np.isfinite(a).mean()), 3), "share_random": round(float(np.isfinite(b).mean()), 3),
        "median_offset_ns_ch7": round(float(np.nanmedian(a)), 2) if np.isfinite(a).any() else None,
        "share_within_+-10ns_ch7": round(float((np.abs(a) < 10).mean()), 3), "share_within_+-10ns_random": round(float((np.abs(b) < 10).mean()), 4)}
# order of the prompt pulses (within -10..+15 ns)
orders = {}
F = np.array([first[k] for k in range(4)]).T
for row in F:
    present = [(v, names[k]) for k, v in enumerate(row) if np.isfinite(v) and -10 <= v <= 15]
    key = " < ".join(n for _, n in sorted(present)) or "none"
    orders[key] = orders.get(key, 0) + 1
res["prompt_order_counts"] = dict(sorted(orders.items(), key=lambda kv: -kv[1])[:10])
for ax in ("x", "y"):
    a, b = np.array(sums[ax]), np.array(sums[ax + "_rand"])
    ha, e = np.histogram(a, bins=np.arange(-40, 300.1, 5))
    hb, _ = np.histogram(b, bins=e)
    hb = hb / 20
    k = np.argmax(ha - hb)
    res[f"timesum_{ax}_vs_ch7"] = {"pairs": int(len(a)), "random_pairs_per_ch7_equiv": float(len(b) / 20),
                                   "largest_excess_bin_ns": float(e[k]), "excess_counts": float(ha[k] - hb[k]),
                                   "expected_if_mcp_ns": 84.0 if ax == "x" else 82.3}
    if ax == "x":
        ts_hist = {"x": (e, ha, hb)}
    else:
        ts_hist["y"] = (e, ha, hb)
res["burst_multiplicity_corner_pulses"] = {
    f"+-{w}us": {src: {"mean": round(float(np.mean(mult[src][w])), 2), "median": float(np.median(mult[src][w])),
                       "p90": float(np.percentile(mult[src][w], 90))} for src in mult} for w in (1, 10)}
A = np.array([[a["X"], a["Y"], a["T"], *a["off"]] for a in assoc])
res["associated_hits"] = {"n": int(len(A)), "X_mm_median": float(np.median(A[:, 0]) * 1e3), "Y_mm_median": float(np.median(A[:, 1]) * 1e3),
                          "corner_offsets_ns_median": dict(zip(names, np.median(A[:, 3:], axis=0).round(2).tolist())),
                          "corner_offsets_ns_iqr": dict(zip(names, np.subtract(*np.percentile(A[:, 3:], [75, 25], axis=0)).round(2).tolist())),
                          "mcp_time_minus_t7_ns_median": float(np.median((A[:, 3] + A[:, 4] - 3200 * 25e-3 / 25e-3 * 0 - 80.0) / 2))}
# the spot in the image: all June hits (build_hits npz), background windows
z = [np.load(SCRATCH / "hits" / f"{n}.npz") for n in ("p25-0620-rabi", "p25-0625-ramsey", "p25-0626-ramsey", "p25-0627-ramsey")]
T = np.concatenate([q["T"] for q in z]); Xm = np.concatenate([(q["x1"] - q["x2"]) for q in z]) * M_PER_BIN
Ym = np.concatenate([(q["y1"] - q["y2"]) for q in z]) * M_PER_BIN
shot = np.concatenate([q["shot"] + 100000 * i for i, q in enumerate(z)])
edges = np.arange(0, 4.21, 0.01); hh, _ = np.histogram(T, edges)
busy = hh > 2 * np.median(hh); busy = np.convolve(busy.astype(int), np.ones(5, int), mode="same") > 0
bg = ~busy[np.clip(np.searchsorted(edges, T, side="right") - 1, 0, len(busy) - 1)] & (T > 0.01) & (T < 4.0)
cx, cy = np.median(A[:, 0]), np.median(A[:, 1])
r = np.hypot(Xm - cx, Ym - cy)
inner = bg & (r < 3e-3); ring = bg & (r >= 4e-3) & (r < 8e-3)
dens_in = inner.sum() / (np.pi * 9); dens_ring = ring.sum() / (np.pi * (64 - 16))
res["spot_in_image"] = {"centre_mm": [round(cx * 1e3, 2), round(cy * 1e3, 2)], "bg_hits_r<3mm": int(inner.sum()),
                        "expected_from_4-8mm_ring": round(float(dens_ring * np.pi * 9), 1), "ratio": round(float(dens_in / dens_ring), 3)}
# time clustering of hits at the spot: pairs within 1 ms in the same shot vs expectation
ts = np.sort(T[inner] + shot[inner] * 10.0)
close = int((np.diff(ts) < 1e-3).sum())
rate = inner.sum() / (len(np.unique(shot)) * 4.03 * (1 - busy.mean()))
res["spot_in_image"]["pairs_within_1ms"] = close
res["spot_in_image"]["expected_pairs_within_1ms_poisson"] = round(float(inner.sum() * rate * 1e-3), 2)
# ch5 rows
c5 = [np.array(v) for v in ch5]
res["ch5"] = {"rows_per_shot": {str(k): int(v) for k, v in zip(*np.unique([len(v) for v in c5], return_counts=True))},
              "extra_rows_after_trigger_us_p5_p50_p95": np.percentile(np.concatenate([v[1:] for v in c5 if len(v) > 1]), [5, 50, 95]).round(3).tolist()}
(OUT / "ch7_deep.json").write_text(json.dumps(res, indent=1, default=float))
print(json.dumps(res, indent=1, default=float))

fig = figure(14, 8)
ax = fig.subplots(2, 3).ravel()
for k, col in zip(range(4), ["#4269d0", "#ef4444", "#16a34a", "#a855f7"]):
    a = np.array(first[k]); b = np.array(first_rand[k])
    ax[0].hist(a[np.isfinite(a)], bins=np.arange(-50, 150.1, 2), histtype="step", color=col, label=names[k])
ax[0].set_xlabel("first corner pulse − ch7 [ns]"); ax[0].set_ylabel("ch7 pulses"); ax[0].legend(); ax[0].set_title("first pulse per channel after ch7")
for i, axn in enumerate(("x", "y")):
    e, ha, hb = ts_hist[axn]
    ax[1 + i].step(e[:-1], ha, where="post", color="#ef4444", label="around ch7")
    ax[1 + i].step(e[:-1], hb, where="post", color="0.5", label="around random times (scaled)")
    ax[1 + i].axvline(84 if axn == "x" else 82.3, color="k", ls=":", lw=0.8)
    ax[1 + i].set_xlabel(f"{axn}1 + {axn}2 − 2·t7 [ns]"); ax[1 + i].legend(fontsize=8)
    ax[1 + i].set_title(f"ch7 as an MCP pulse? ({axn}); dotted: the 2022 time sum")
for src, col in (("ch7", "#ef4444"), ("rand", "0.5"), ("x1", "#4269d0")):
    v = np.array(mult[src][1])
    ax[3].hist(v, bins=np.arange(0, 40), histtype="step", density=True, color=col, label=src)
ax[3].set_xlabel("corner pulses within ±1 µs"); ax[3].set_yscale("log"); ax[3].legend(); ax[3].set_title("burst multiplicity")
ax[4].plot(A[:, 0] * 1e3, A[:, 1] * 1e3, ".", color="#ef4444", ms=4)
ax[4].set_aspect("equal"); ax[4].set_xlim(-40, 40); ax[4].set_ylim(-40, 40); ax[4].set_title("hits with a corner ≤10 ns from ch7")
ax[4].set_xlabel("X [mm]"); ax[4].set_ylabel("Y [mm]")
for k, col in zip(range(4), ["#4269d0", "#ef4444", "#16a34a", "#a855f7"]):
    ax[5].hist(A[:, 3 + k], bins=np.arange(-60, 80, 2), histtype="step", color=col, label=names[k])
ax[5].set_xlabel("corner of the associated hit − ch7 [ns]"); ax[5].legend(); ax[5].set_title("associated hits: corner timing")
save(fig, "ch7_deep.png")
