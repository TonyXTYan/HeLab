"""Is the June -> July..October change exactly a 180-degree rotation?

Model: p_later = s R(theta) M p_june + offset, with M the identity or the mirror x -> -x.
(a) Hot spots: background-subtracted centroids (+-bootstrap) of the spots seen in both periods,
    least-squares fit of theta = 180 + delta, offset (and scale).
(b) Background-image correlation: June background hits transformed for each theta (and mirror),
    smoothed 0.25 mm images within r < 34 mm; the offset (<= 1.5 mm) that maximises the
    cross-correlation; Pearson r there. Full turn in 1-degree steps for both M, then 0.05-degree steps
    around the top local maxima; fine scan of delta over +-5 degrees (parabola peak; spread over
    half-samples); a scale scan at the best delta. Two variants so the brightest spot can't decide
    alone: counts clipped at 3x the median, and H1/H2 masked.
Later frames: 2026-10-09/10 collisions (main) and 2026-07-27 RingBEC (check).
Writes out/orientation.json, figures/orientation_*.png."""
from __future__ import annotations

import json
import numpy as np
from scipy import signal
from common import OUT, SAMPLES, SCRATCH, M_PER_BIN, figure, save, read_txy, txy_files


def bg_only(a):
    T = a[:, 0]
    edges = np.arange(0, 4.21, 0.01)
    h, _ = np.histogram(T, edges)
    busy = h > 2 * np.median(h[h > 0])
    busy = np.convolve(busy.astype(int), np.ones(5, int), mode="same") > 0
    i = np.clip(np.searchsorted(edges, T, side="right") - 1, 0, len(busy) - 1)
    return a[~busy[i] & (T > 0.01) & (T < 4.0)]


def june():
    out = []
    for n in ("p25-0620-rabi", "p25-0625-ramsey", "p25-0626-ramsey", "p25-0627-ramsey"):
        z = np.load(SCRATCH / "hits" / f"{n}.npz")
        out.append(np.c_[z["T"], (z["x1"] - z["x2"]) * M_PER_BIN, (z["y1"] - z["y2"]) * M_PER_BIN])
    return bg_only(np.concatenate(out))[:, 1:] * 1e3


def later(folder):
    return bg_only(np.concatenate([read_txy(f) for f in txy_files(SAMPLES / folder)]))[:, 1:] * 1e3


J = june()
L = {"collisions 2026-10": later("calib-2026/20261010-411trapcollisions44"), "RingBEC 2026-07-27": later("calib-2026/20260727-RingBEC")}
print("bg hits: June", len(J), {k: len(v) for k, v in L.items()})
res = {"bg_hits": {"June": len(J), **{k: len(v) for k, v in L.items()}}}

# ---------- (a) hot-spot centroids
rng = np.random.default_rng(3)


def centroid(P, guess, r_in=3.0, r_out=(4.0, 7.0), boot=300):
    def once(Q):
        c = np.array(guess, float)
        for _ in range(10):
            d = np.hypot(Q[:, 0] - c[0], Q[:, 1] - c[1])
            inner = Q[d < r_in]
            ring = (d >= r_out[0]) & (d < r_out[1])
            dens = ring.sum() / (np.pi * (r_out[1] ** 2 - r_out[0] ** 2))
            nb = dens * np.pi * r_in ** 2
            # background-subtracted centroid: uniform background has mean c within the disc
            ex = len(inner) - nb
            c_new = (inner.sum(axis=0) - nb * c) / max(ex, 1)
            if np.hypot(*(c_new - c)) < 1e-4:
                break
            c = c_new
        return c, ex
    near = P[np.hypot(P[:, 0] - guess[0], P[:, 1] - guess[1]) < 10]
    c, ex = once(near)
    bs = np.array([once(near[rng.integers(0, len(near), len(near))])[0] for _ in range(boot)])
    return c, bs.std(axis=0), ex


SPOTS = {"H1": (15.9, 1.3), "H2": (32.3, 1.2), "H3": (8.8, -1.0)}
cent = {}
for name, g in SPOTS.items():
    cj, sj, ej = centroid(J, g)
    cent[name] = {"June": [cj.round(3).tolist(), sj.round(3).tolist(), round(float(ej))]}
    for k, P in L.items():
        cl, sl, el = centroid(P, (-g[0], -g[1]))
        cent[name][k] = [cl.round(3).tolist(), sl.round(3).tolist(), round(float(el))]
res["hot_spot_centroids_mm"] = cent
print(json.dumps(cent, indent=1))


def fit_spots(key, scale=False):
    a = np.array([cent[n]["June"][0] for n in SPOTS]); sa = np.array([cent[n]["June"][1] for n in SPOTS])
    b = np.array([cent[n][key][0] for n in SPOTS]); sb = np.array([cent[n][key][1] for n in SPOTS])
    w = 1 / np.sqrt(sa ** 2 + sb ** 2 + 1e-6)

    def resid(p):
        th = np.radians(180 + p[0]); s = p[3] if scale else 1.0
        R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
        return ((s * a @ R.T + p[1:3] - b) * w).ravel()
    from scipy.optimize import least_squares
    r = least_squares(resid, [0, 0, 0] + ([1.0] if scale else []))
    J_ = r.jac
    cov = np.linalg.inv(J_.T @ J_) * max(1.0, (r.fun ** 2).sum() / max(len(r.fun) - len(r.x), 1))
    err = np.sqrt(np.diag(cov))
    out = {"delta_deg": [round(r.x[0], 3), round(err[0], 3)], "offset_mm": [[round(r.x[1], 3), round(err[1], 3)], [round(r.x[2], 3), round(err[2], 3)]],
           "chi2": round(float((r.fun ** 2).sum()), 2), "dof": len(r.fun) - len(r.x)}
    if scale:
        out["scale"] = [round(r.x[3], 4), round(err[3], 4)]
    return out


res["hot_spot_fit"] = {k: {"rotation+offset": fit_spots(k), "rotation+offset+scale": fit_spots(k, True)} for k in L}
print(json.dumps(res["hot_spot_fit"], indent=1))

# ---------- (b) image correlation
# 0.25 mm bins, Gaussian smoothing (sigma 0.75 mm), offset limited to +-1.5 mm (the hot-spot fit gives
# ~0.4 mm; a free +-4 mm offset lets the strongest spot alone match many angles, even a mirror).
# Two variants that keep one bright spot from deciding: counts clipped at 3x the disc median
# ("clipped"), and the two strongest spots (H1, H2) masked in both images ("H1/H2 masked").
from scipy import ndimage
BIN = 0.25
E = np.arange(-40, 40.001, BIN)
mid = (E[1:] + E[:-1]) / 2
MX, MY = np.meshgrid(mid, mid, indexing="ij")
DISC = np.hypot(MX, MY) < 34
SH = int(1.5 / BIN)
MASK_SPOTS = [(-15.88, -1.57), (-32.44, -1.42)]  # in the later frame


def image(P, variant):
    h = ndimage.gaussian_filter(np.histogram2d(P[:, 0], P[:, 1], bins=(E, E))[0], 0.75 / BIN)
    m = DISC.copy()
    if variant == "clipped":
        h = np.minimum(h, 3 * np.median(h[DISC]))
    else:
        for (x, y) in MASK_SPOTS:
            m &= np.hypot(MX - x, MY - y) > 4
    return h, m


def transform(P, theta_deg, mirror, s=1.0):
    Q = P.copy()
    if mirror:
        Q[:, 0] = -Q[:, 0]
    th = np.radians(theta_deg)
    return s * np.c_[np.cos(th) * Q[:, 0] - np.sin(th) * Q[:, 1], np.sin(th) * Q[:, 0] + np.cos(th) * Q[:, 1]]


def best_r(Am, Bm):
    (A, ma), (B, mb) = Am, Bm
    m = ma & mb
    a = np.where(m, A - A[m].mean(), 0); b = np.where(m, B - B[m].mean(), 0)
    cc = signal.fftconvolve(b, a[::-1, ::-1], mode="same")
    c0 = np.array(cc.shape) // 2
    sub = cc[c0[0] - SH:c0[0] + SH + 1, c0[1] - SH:c0[1] + SH + 1]
    i, j = np.unravel_index(np.argmax(sub), sub.shape)
    dx, dy = i - SH, j - SH
    As = np.roll(np.roll(A, dx, 0), dy, 1); mm = m & np.roll(np.roll(m, dx, 0), dy, 1)
    return float(np.corrcoef(As[mm], B[mm])[0, 1]), (dx * BIN, dy * BIN)


res["image"] = {}
curves = {}
VARIANTS = ("clipped", "H1/H2 masked")
for key, P in L.items():
    for variant in VARIANTS:
        tag = f"{key} ({variant})"
        Bm = image(P, variant)
        rimg = lambda t, mirror, s=1.0, Jx=J: best_r(image(transform(Jx, t, mirror, s), variant), Bm)  # noqa: E731
        full = {}
        for mirror in (False, True):
            th = np.arange(0, 360, 1.0)
            rr = np.array([rimg(t, mirror)[0] for t in th])
            order = np.argsort(rr)[::-1]
            peaks = [i for i in range(len(th)) if rr[i] >= rr[i - 1] and rr[i] >= rr[(i + 1) % len(th)]]
            peaks = sorted(peaks, key=lambda i: -rr[i])[:4]
            ref = []
            for i in peaks:
                tt = np.arange(th[i] - 1.0, th[i] + 1.001, 0.05)
                r2 = [rimg(t, mirror)[0] for t in tt]
                k = int(np.argmax(r2))
                ref.append({"theta_deg": round(float(tt[k]) % 360, 2), "r": round(float(r2[k]), 4)})
            full["mirror x->-x then rotate" if mirror else "rotation only"] = {
                "max_r_1deg_grid": round(float(rr.max()), 4), "theta_at_max": float(th[np.argmax(rr)]),
                "median_r": round(float(np.median(rr)), 4), "top_local_maxima_refined": ref}
            curves[(tag, mirror)] = (th, rr)
        dd = np.arange(-5, 5.0001, 0.05)
        rd = np.array([rimg(180 + d, False)[0] for d in dd])
        k = int(np.argmax(rd))
        sl = slice(max(k - 12, 0), k + 13)
        pc = np.polyfit(dd[sl], rd[sl], 2)
        dpk = float(-pc[1] / (2 * pc[0]))
        halves = []
        for hj in (0, 1):
            for hl in (0, 1):
                Bh = image(P[hl::2], variant)
                r_h = np.array([best_r(image(transform(J[hj::2], 180 + d, False), variant), Bh)[0] for d in dd[sl]])
                p2 = np.polyfit(dd[sl], r_h, 2)
                halves.append(float(-p2[1] / (2 * p2[0])))
        ss = np.arange(0.98, 1.0201, 0.0025)
        rs = np.array([rimg(180 + dpk, False, s)[0] for s in ss])
        ps = np.polyfit(ss, rs, 2)
        res["image"][tag] = {"full_turn": full, "delta_deg_peak": round(dpk, 3),
                             "delta_deg_sd_over_half_samples": round(float(np.std(halves, ddof=1)), 3), "delta_halves": np.round(halves, 3).tolist(),
                             "r_at_peak": round(float(rd[k]), 4), "offset_mm_at_peak": rimg(180 + dpk, False)[1],
                             "scale_peak": round(float(-ps[1] / (2 * ps[0])), 4)}
        curves[(tag, "fine")] = (dd, rd)
        print(tag, {kk: v for kk, v in res["image"][tag].items() if kk != "full_turn"})
        print("   ", json.dumps(full))
(OUT / "orientation.json").write_text(json.dumps(res, indent=1, default=float))

fig = figure(14, 8)
axs = fig.subplots(2, 2).ravel()
i = 0
for key in L:
    for variant in VARIANTS:
        tag = f"{key} ({variant})"
        ax = axs[i]; i += 1
        for mirror, col, lab in ((False, "#4269d0", "rotation"), (True, "#ef4444", "mirror x→−x, then rotation")):
            th, rr = curves[(tag, mirror)]
            ax.plot(th, rr, color=col, label=lab, lw=1)
        ax.set_xlabel("θ [deg]"); ax.set_ylabel("image correlation r"); ax.set_title(tag, fontsize=9)
        ax.set_xticks(range(0, 361, 45)); ax.legend(fontsize=8, loc="upper left")
        ins = ax.inset_axes([0.64, 0.5, 0.33, 0.33])
        dd, rd = curves[(tag, "fine")]
        ins.plot(180 + dd, rd, color="#4269d0", lw=1); ins.axvline(180, color="0.5", lw=0.6, ls=":")
        ins.set_title("180° ± 5°", fontsize=7); ins.tick_params(labelsize=6)
fig.suptitle("June 2026 background image, transformed by θ (or mirror then θ), vs later runs (offset ≤ 1.5 mm)")
save(fig, "orientation_scan.png")
