"""Geometry and flat field of the 2025 plates from background-window hits:

* the 180-degree rotation test: correlation of the June 2026 background image with the later runs'
  images as they are and rotated by 180 degrees (4 mm bins, r < 34 mm, hot spots included);
* hot spots matched across runs in the June frame (later runs rotated by 180 degrees);
* edge ellipse with uncertainty: fitted on even and odd shots separately;
* relative dark-count density map (flat-field proxy) and its spread beyond Poisson.
Writes out/geometry_flatfield.json, figures/ff_*.png."""
from __future__ import annotations

import json
import numpy as np
from common import OUT, SCRATCH, SAMPLES, M_PER_BIN, figure, save, read_txy, txy_files



def from_npz(names):
    out = []
    for n in names:
        z = np.load(SCRATCH / "hits" / f"{n}.npz", allow_pickle=True)
        out.append(np.c_[z["T"], (z["x1"] - z["x2"]) * M_PER_BIN, (z["y1"] - z["y2"]) * M_PER_BIN, z["shot"]])
    return np.concatenate(out)


def from_txy(folder):
    out = []
    for i, f in enumerate(txy_files(folder)):
        a = read_txy(f)
        if len(a):
            out.append(np.c_[a, np.full(len(a), i)])
    return np.concatenate(out)


def background(a):
    T = a[:, 0]
    edges = np.arange(0, 4.21, 0.01)
    h, _ = np.histogram(T, edges)
    busy = h > 2 * np.median(h[h > 0])
    busy = np.convolve(busy.astype(int), np.ones(5, int), mode="same") > 0
    i = np.clip(np.searchsorted(edges, T, side="right") - 1, 0, len(busy) - 1)
    return a[~busy[i] & (T > 0.01) & (T < 4.0)]


RUNS = {
    "Jun 2026": lambda: from_npz(["p25-0620-rabi", "p25-0625-ramsey", "p25-0626-ramsey", "p25-0627-ramsey"]),
    "2026-07-27 RingBEC": lambda: from_txy(SAMPLES / "calib-2026/20260727-RingBEC"),
    "2026-10-10 collisions": lambda: from_txy(SAMPLES / "calib-2026/20261010-411trapcollisions44"),
}
bg = {k: background(f()) for k, f in RUNS.items()}
E = np.arange(-36, 36.01, 4) * 1e-3
mid = (E[1:] + E[:-1]) / 2
MX, MY = np.meshgrid(mid, mid, indexing="ij")
inside = np.hypot(MX, MY) < 34e-3


def img(b, rot=False):
    x, y = b[:, 1], b[:, 2]
    if rot:
        x, y = -x, -y
    return np.histogram2d(x, y, bins=(E, E))[0]


res = {"rotation_test": {}}
ref = img(bg["Jun 2026"])
for k in ("2026-07-27 RingBEC", "2026-10-10 collisions"):
    for rot in (False, True):
        im = img(bg[k], rot)
        c = np.corrcoef(ref[inside], im[inside])[0, 1]
        # also with x-only or y-only flips
        res["rotation_test"][f"{k} {'rotated 180' if rot else 'as is'}"] = round(float(c), 3)
    for nm, fx, fy in (("mirror X only", -1, 1), ("mirror Y only", 1, -1)):
        x, y = bg[k][:, 1] * fx, bg[k][:, 2] * fy
        im = np.histogram2d(x, y, bins=(E, E))[0]
        res["rotation_test"][f"{k} {nm}"] = round(float(np.corrcoef(ref[inside], im[inside])[0, 1]), 3)
print(res["rotation_test"])

# relative density (flat-field proxy), June and collisions (rotated to the June frame)
def rel(im):
    r = im / im[inside].mean()
    r[~inside] = np.nan
    return r


rj, rc = rel(ref), rel(img(bg["2026-10-10 collisions"], True))
for name, im, r in (("Jun 2026", ref, rj), ("collisions (rotated)", img(bg["2026-10-10 collisions"], True), rc)):
    vals = r[inside]
    poisson = np.sqrt(1 / im[inside].mean())
    res[f"flat_{name}"] = {"bg_hits": int(im.sum()), "rel_sd": round(float(np.std(vals)), 3), "poisson_sd": round(float(poisson), 3),
                           "excess_sd": round(float(np.sqrt(max(np.var(vals) - poisson ** 2, 0))), 3),
                           "p5_p95": [round(float(np.percentile(vals, 5)), 3), round(float(np.percentile(vals, 95)), 3)],
                           "min_max": [round(float(vals.min()), 3), round(float(vals.max()), 3)]}
avg = (rj + rc) / 2
# without hot-spot bins (relative density > 2 in either run): the spread and the June-vs-collisions agreement
ok = inside & (rj < 2) & (rc < 2)
pj, pc = np.sqrt(1 / ref[inside].mean()), 0.05
res["flat_without_hot_bins"] = {
    "bins": int(ok.sum()), "corr_jun_vs_collisions_rotated": round(float(np.corrcoef(rj[ok], rc[ok])[0, 1]), 3),
    "sd_jun": round(float(np.std(rj[ok])), 3), "sd_collisions": round(float(np.std(rc[ok])), 3),
    "sd_of_difference": round(float(np.std(rj[ok] - rc[ok])), 3),
    "p5_p95_mean_map": [round(float(np.percentile(avg[ok], 5)), 3), round(float(np.percentile(avg[ok], 95)), 3)],
    "radial_profile_mean_map": {f"{lo}-{lo + 6} mm": round(float(np.nanmean(avg[ok & (np.hypot(MX, MY) * 1e3 >= lo) & (np.hypot(MX, MY) * 1e3 < lo + 6)])), 3)
                                for lo in (0, 6, 12, 18, 24, 30)}}
print(res["flat_without_hot_bins"])
res["flat_mean_map_4mm_bins"] = {"edges_mm": (E * 1e3).round(1).tolist(), "relative_density": np.where(np.isnan(avg), None, np.round(avg, 3)).tolist()}

# edge with uncertainty: even/odd shots
from images_hotspots_edge import edge_ellipse  # noqa: E402
res["edge"] = {}
for k, b in bg.items():
    fits = []
    for part in (0, 1):
        s = (b[:, 3].astype(int) % 2) == part
        e, _ = edge_ellipse(b[s, 1], b[s, 2])
        fits.append(e)
    full, _ = edge_ellipse(b[:, 1], b[:, 2])
    res["edge"][k] = {"all": full, "even": fits[0], "odd": fits[1]}
    print(k, full, [f and f["semi_axes_mm"] for f in fits])
(OUT / "geometry_flatfield.json").write_text(json.dumps(res, indent=1, default=float))

fig = figure(13, 4.2)
ax = fig.subplots(1, 3)
for a_, (t, m) in zip(ax, (("Jun 2026 background (relative)", rj), ("2026-10-10 collisions, rotated 180° (relative)", rc), ("mean of both", avg))):
    im = a_.imshow(m.T, origin="lower", extent=[-36, 36, -36, 36], cmap="RdBu_r", vmin=0.6, vmax=1.4)
    a_.set_title(t, fontsize=9); a_.set_xlabel("X [mm] (June frame)"); a_.set_ylabel("Y [mm]")
fig.colorbar(im, ax=ax, label="dark-count density / mean (4 mm bins, r < 34 mm)")
save(fig, "ff_relative_density.png")
