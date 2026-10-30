"""Burst detail and history.
(1) 2026-06-25 (local, all 519): bursts (>= 15 corner pulses in 1 us, all four corners, quiet windows):
    size in pulses (1 us and 3 us), first channel, with/without ch7; ghost hits: reconstructed hits whose
    corners fall inside a burst (count, position).
(2) History: the same burst finder on a sample of raw files streamed from X (read-only): 06-20, 06-26,
    06-27, 07-21/22 and 09-21/22, giving burst rate and the share with ch7 per folder.
Writes out/ch7_burst_detail.json, figures/ch7_burst_sizes.png."""
import os

# The 2026-09-22 BEC run's folder on X.
SEPT_2026_FOLDER = os.environ.get("CH7_SEPT_2026_FOLDER", "2026-09-22 BEC run")

from __future__ import annotations

import json
import os
import re
import numpy as np
from common import OUT, SAMPLES, SCRATCH, BIN, M_PER_BIN, figure, save, raw_files, read_raw, shot_number
from probe_match import match

NS = 1e-9 / BIN
X = "/Volumes/192.168.137.1-4/dld_output_cheerypicked"


def quiet_mask(sec, edges, busy):
    return ~busy[np.clip(np.searchsorted(edges, sec, side="right") - 1, 0, len(busy) - 1)]


def busy_windows(Ts):
    edges = np.arange(0, 4.21, 0.01)
    h, _ = np.histogram(np.concatenate(Ts), edges)
    busy = h > 2 * np.median(h[h > 0])
    return edges, np.convolve(busy.astype(int), np.ones(5, int), mode="same") > 0


def bursts_in(c, t, edges, busy):
    """t: bins from t_zero, sorted. Returns list of (start, end, size1us, size3us, first_channel, has7)."""
    sec = t * BIN
    q = quiet_mask(sec, edges, busy)
    corner = (c <= 3) & q
    tc, cc = t[corner], c[corner]
    t7 = t[c == 7]
    out, used = [], -1
    for i in range(len(tc)):
        if tc[i] <= used:
            continue
        k = np.searchsorted(tc, tc[i] + 1000 * NS)
        if k - i >= 15 and len(set(cc[i:k].tolist())) == 4:
            k3 = np.searchsorted(tc, tc[i] + 3000 * NS)
            used = tc[k3 - 1]
            out.append((tc[i], tc[k3 - 1], k - i, k3 - i, int(cc[i]), bool(np.any(np.abs(t7 - tc[i]) < 1000 * NS))))
    return out


def load(path):
    c, t = read_raw(path)
    t0 = t[0]
    o = np.argsort(t, kind="stable")
    return c[o], t[o] - t0, (c, t)


res = {}
# (1) detail on 06-25
files = raw_files(SAMPLES / "calib-2026/20260625_Ramsey_weak_trap")
loaded = [load(f) for f in files]
edges, busy = busy_windows([(t[c <= 3]) * BIN for c, t, _ in loaded])
B, ghost = [], []
for (c, t, raw) in loaded:
    bs = bursts_in(c, t, edges, busy)
    B += bs
    if bs:
        h = match(*raw)
        cor = np.c_[h["x1"], h["x2"], h["y1"], h["y2"]]
        for (s, e, *_ , has7) in bs:
            inb = np.all((cor >= s - 50 * NS) & (cor <= e + 50 * NS), axis=1)
            for j in np.flatnonzero(inb):
                ghost.append((h["X"][j], h["Y"][j], has7))
B = np.array(B, dtype=float)
G = np.array(ghost, dtype=float)
w7 = B[:, 5] == 1
res["0625"] = {"bursts": int(len(B)), "with_ch7": int(w7.sum()),
               "size_1us_median_with7": float(np.median(B[w7, 2])), "size_1us_median_without7": float(np.median(B[~w7, 2])),
               "size_3us_median_with7": float(np.median(B[w7, 3])), "size_3us_median_without7": float(np.median(B[~w7, 3])),
               "first_channel_share": {str(k): round(float((B[:, 4] == k).mean()), 3) for k in range(4)},
               "share_with_ch7_by_size_3us": {}, "ghost_hits": int(len(G)), "ghost_hits_per_burst": round(len(G) / len(B), 2),
               "ghost_X_mm_median": float(np.median(G[:, 0]) * 1e3) if len(G) else None,
               "ghost_Y_mm_median": float(np.median(G[:, 1]) * 1e3) if len(G) else None,
               "ghost_hits_share_of_quiet_hits": None}
for lo, hi in ((15, 20), (20, 25), (25, 30), (30, 40), (40, 1000)):
    s = (B[:, 3] >= lo) & (B[:, 3] < hi)
    res["0625"]["share_with_ch7_by_size_3us"][f"{lo}-{hi}"] = [int(s.sum()), round(float(B[s, 5].mean()), 3) if s.any() else None]
quiet_hits = 0
for (c, t, raw) in loaded:
    h = match(*raw)
    quiet_hits += int(quiet_mask(h["T"], edges, busy).sum())
res["0625"]["ghost_hits_share_of_quiet_hits"] = round(len(G) / quiet_hits, 4)
print(json.dumps(res["0625"], indent=1))

fig = figure(13, 4.2)
ax = fig.subplots(1, 3)
ax[0].hist(B[~w7, 3], bins=np.arange(15, 80), histtype="step", density=True, label="bursts without ch7", color="0.4")
ax[0].hist(B[w7, 3], bins=np.arange(15, 80), histtype="step", density=True, label="bursts with ch7", color="#ef4444")
ax[0].set_xlabel("corner pulses within 3 µs of the burst start"); ax[0].legend(); ax[0].set_title("2026-06-25: burst size")
if len(G):
    ax[1].hist2d(G[:, 0] * 1e3, G[:, 1] * 1e3, bins=80, range=((-40, 40), (-40, 40)), cmap="magma")
    ax[1].set_aspect("equal"); ax[1].set_title(f"hits reconstructed inside bursts ({len(G)})"); ax[1].set_xlabel("X [mm]"); ax[1].set_ylabel("Y [mm]")

# (2) history on X
hist = {}
plan = {"20260620_Rabi_trial_weak_intrap": 40, "20260626_Ramsey_weaktrap": 60, "20260627_Ramsey_weaktrap": 80,
        "20260722-tight-trap-freq-meas": 12, SEPT_2026_FOLDER: 6}
for folder, step in plan.items():
    lst = SCRATCH / "listings" / (("20260922" if folder.startswith("20260922") else folder) + ".txt")
    paths = []
    for line in lst.read_text().splitlines():
        _, _, p = line.split(" ", 2)
        if re.search(r"/d\d+\.txt$", p):
            paths.append(p if p.startswith("/") else f"{X}/{p}")
    paths = sorted(paths, key=lambda p: (os.path.dirname(p), shot_number(p)))[::step]
    data = [load(p) for p in paths]
    e2, b2 = busy_windows([(t[c <= 3]) * BIN for c, t, _ in data])
    nb = n7b = n7 = 0
    qt = 0.0
    for c, t, _ in data:
        bs = bursts_in(c, t, e2, b2)
        nb += len(bs); n7b += sum(b[5] for b in bs); n7 += int((c == 7).sum())
        qt += float(t.max() * BIN) * (1 - b2.mean())
    hist[folder] = {"files": len(data), "quiet_s": round(qt, 1), "bursts": nb, "burst_rate_hz": round(nb / qt, 2),
                    "bursts_with_ch7": int(n7b), "share_with_ch7": round(n7b / max(nb, 1), 4), "ch7": n7}
    print(folder, hist[folder], flush=True)
res["history"] = hist
names = list(hist)
ax[2].plot(range(len(names)), [hist[n]["burst_rate_hz"] for n in names], "o-", label="bursts / s (quiet windows)", color="0.3")
ax2 = ax[2].twinx()
ax2.plot(range(len(names)), [100 * hist[n]["share_with_ch7"] for n in names], "s-", color="#ef4444", label="% of bursts with ch7")
ax[2].set_xticks(range(len(names)), [n[:8] for n in names], rotation=30, fontsize=7)
ax[2].set_ylabel("bursts per second"); ax2.set_ylabel("% with ch7", color="#ef4444"); ax[2].set_title("history (samples from X)")
save(fig, "ch7_burst_sizes.png")
(OUT / "ch7_burst_detail.json").write_text(json.dumps(res, indent=1, default=float))
