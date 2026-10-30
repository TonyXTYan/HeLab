"""Background (dark-count) images, hot spots and the active-area edge per era.

Hits outside the atoms' arrival windows (10 ms T bins whose rate is below 2x the median bin's, with
20 ms margins) are close to a flat field of the MCP's dark counts plus random combinations. Per
era: the background image (0.5 mm bins), HeLab's hot-spot finder (helab.analysis.hotspots, alpha
0.01, 1 mm background scale), and the edge: per 15-degree sector, the radius where the background
density falls to half its 10-28 mm plateau, fitted with an ellipse (centre, semi-axes, tilt).
Writes out/images_hotspots.json and figures/img_*.png.
"""
from __future__ import annotations

import json
import numpy as np
from matplotlib.colors import LogNorm
from common import OUT, SCRATCH, SAMPLES, M_PER_BIN, figure, save, read_txy, txy_files, helab_env

helab_env()
from helab.analysis.hotspots import find_hot_spots  # noqa: E402


def from_npz(names):
    out = []
    for n in names:
        z = np.load(SCRATCH / "hits" / f"{n}.npz", allow_pickle=True)
        X = (z["x1"] - z["x2"]) * M_PER_BIN
        Y = (z["y1"] - z["y2"]) * M_PER_BIN
        out.append(np.c_[z["T"], X, Y, z["shot"]])
    return np.concatenate(out)


def from_txy(folders, step=1):
    out = []
    for folder in folders:
        for i, f in enumerate(txy_files(folder)[::step]):
            a = read_txy(f)
            if len(a):
                out.append(np.c_[a, np.full(len(a), i)])
    return np.concatenate(out)


ERAS = {
    "2017 plates (2019-11 halos)": lambda: from_txy([SAMPLES / "calib-v1/plates-2017_20191105_halos"]),
    "2022 plates (2022-12, 2023-01 halos)": lambda: from_txy([SAMPLES / "calib-v1/plates-2022_20221212_halo_test_4",
                                                              SAMPLES / "calib-v1/plates-2022_20230130_halo_3_halos"]),
    "2025 plates, Jun 2026 (Rabi/Ramsey)": lambda: from_npz(["p25-0620-rabi", "p25-0625-ramsey", "p25-0626-ramsey", "p25-0627-ramsey"]),
    "2025 plates, Jul 2026 (tight trap)": lambda: from_txy([SAMPLES / "calib-2026/20260722-tight-trap-freq-meas"]),
    "2025 plates, 2026-07-27 RingBEC": lambda: from_txy([SAMPLES / "calib-2026/20260727-RingBEC"]),
    "2025 plates, 2026-08-12 QE": lambda: from_txy([SAMPLES / "calib-2026/20260812_Quantum_efficiency"]),
    "2025 plates, 2026-10-10 collisions": lambda: from_txy([SAMPLES / "calib-2026/20261010-411trapcollisions44"]),
}


def background_mask(T):
    edges = np.arange(0, 4.21, 0.01)
    h, _ = np.histogram(T, edges)
    med = np.median(h[h > 0])
    busy = h > 2 * med
    # 20 ms margins
    busy = np.convolve(busy.astype(int), np.ones(5, int), mode="same") > 0
    i = np.clip(np.searchsorted(edges, T, side="right") - 1, 0, len(busy) - 1)
    return ~busy[i] & (T > 0.01) & (T < 4.0), float(1 - busy.mean())


def edge_ellipse(X, Y, cx0=0.0, cy0=0.0):
    """Per 15-degree sector: radius where density drops to half its plateau (10-28 mm)."""
    r = np.hypot(X - cx0, Y - cy0)
    th = np.arctan2(Y - cy0, X - cx0)
    pts = []
    for k in range(24):
        a0 = -np.pi + k * np.pi / 12
        s = (th >= a0) & (th < a0 + np.pi / 12)
        if s.sum() < 2000:
            continue
        rr = r[s]
        e = np.arange(0, 60.5, 0.5) * 1e-3
        h, _ = np.histogram(rr, e)
        dens = h / (np.pi * (e[1:] ** 2 - e[:-1] ** 2))
        dens = np.convolve(dens, np.ones(3) / 3, mode="same")
        mid = (e[1:] + e[:-1]) / 2
        plateau = np.median(dens[(mid > 10e-3) & (mid < 28e-3)])
        beyond = np.flatnonzero((mid > 28e-3) & (dens < 0.5 * plateau))
        if len(beyond) == 0:
            continue
        j = beyond[0]
        # linear interpolation between j-1 and j
        f = (dens[j - 1] - 0.5 * plateau) / max(dens[j - 1] - dens[j], 1e-12)
        redge = mid[j - 1] + f * (mid[j] - mid[j - 1])
        ang = a0 + np.pi / 24
        pts.append((cx0 + redge * np.cos(ang), cy0 + redge * np.sin(ang), redge, ang))
    pts = np.array(pts)
    if len(pts) < 8:
        return None, pts
    x, y = pts[:, 0], pts[:, 1]
    # general conic fit A x^2 + B xy + C y^2 + D x + E y = 1
    M = np.c_[x ** 2, x * y, y ** 2, x, y]
    A, B, C, D, E = np.linalg.lstsq(M, np.ones(len(x)), rcond=None)[0]
    den = B ** 2 - 4 * A * C
    xc = (2 * C * D - B * E) / den
    yc = (2 * A * E - B * D) / den
    F = -1 - (A * xc ** 2 + B * xc * yc + C * yc ** 2 + D * xc + E * yc)
    # axes from eigen of [[A, B/2],[B/2, C]] scaled by -F
    w, v = np.linalg.eigh(np.array([[A, B / 2], [B / 2, C]]))
    axes = np.sqrt(-F / w)
    tilt = float(np.degrees(np.arctan2(v[1, 0], v[0, 0])))
    resid = np.hypot(x - xc, y - yc)
    return {"centre_mm": [round(float(xc) * 1e3, 2), round(float(yc) * 1e3, 2)],
            "semi_axes_mm": [round(float(axes[0]) * 1e3, 2), round(float(axes[1]) * 1e3, 2)],
            "axis_ratio": round(float(max(axes) / min(axes)), 4), "tilt_deg_of_first_axis": round(tilt, 1),
            "mean_radius_mm": round(float(resid.mean()) * 1e3, 2), "radius_sd_mm": round(float(resid.std()) * 1e3, 2),
            "sectors": int(len(x))}, pts


res = {}
images = {}
for era, loader in ERAS.items():
    a = loader()
    T, X, Y = a[:, 0], a[:, 1], a[:, 2]
    bg, frac = background_mask(T)
    r = {"hits": int(len(T)), "bg_hits": int(bg.sum()), "bg_time_fraction": round(frac, 3)}
    # background rate per shot (Hz): bg hits / (shots * 4.0 s * frac)
    s = find_hot_spots(X[bg], Y[bg], (-0.05, 0.05), (-0.05, 0.05))
    r["hot_spots"] = [{"x_mm": round(h.circle.x * 1e3, 2), "y_mm": round(h.circle.y * 1e3, 2),
                       "r_mm": round(h.circle.r * 1e3, 2), "excess": round(h.excess, 1), "counts": h.counts,
                       "p": float(f"{h.p:.2g}") if hasattr(h, "p") else None} for h in s.spots]
    ell, pts = edge_ellipse(X[bg], Y[bg])
    r["edge"] = ell
    res[era] = r
    images[era] = (X[bg], Y[bg], s, pts, ell)
    print(era, {k: v for k, v in r.items() if k != "hot_spots"}, "spots", len(r["hot_spots"]), flush=True)

(OUT / "images_hotspots.json").write_text(json.dumps(res, indent=1, default=float))

fig = figure(18, 10)
axs = fig.subplots(2, 4).ravel()
for ax, (era, (x, y, s, pts, ell)) in zip(axs, images.items()):
    h = np.histogram2d(x * 1e3, y * 1e3, bins=200, range=((-50, 50), (-50, 50)))[0]
    ax.imshow(h.T, origin="lower", extent=[-50, 50, -50, 50], norm=LogNorm(vmin=max(1, np.percentile(h[h > 0], 5))), cmap="magma")
    for sp in s.spots[:15]:
        ax.add_patch(__import__("matplotlib.patches").patches.Circle((sp.circle.x * 1e3, sp.circle.y * 1e3), max(sp.circle.r * 1e3, 1.5), fill=False, ec="#22d3ee", lw=1))
    if len(pts):
        ax.plot(pts[:, 0] * 1e3, pts[:, 1] * 1e3, ".", color="#4ade80", ms=4)
    ax.add_patch(__import__("matplotlib.patches").patches.Circle((0, 0), 38, fill=False, ec="w", ls=":", lw=0.8))
    ax.set_title(f"{era}\nbackground hits {len(x):,}", fontsize=8)
    ax.set_xlabel("X [mm]"); ax.set_ylabel("Y [mm]")
axs[-1].axis("off")
fig.suptitle("Background-window hits (dark counts + random combinations); cyan: hot spots found; green: half-density edge per sector; dotted: r = 38 mm")
save(fig, "img_background_by_era.png")
