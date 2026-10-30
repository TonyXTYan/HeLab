"""Back-to-back (BB) correlation of the s-wave halo in 20261010-411trapcollisions44 (2025 plates,
866 TXY shots, matlab-2019 conversion) and what it can and cannot calibrate.

Velocities about the halo centre (the midpoint of the two BECs): vx = (X - Xc)/t_f, vy likewise
(t_f = 0.4161 s, HeLab's default for h = 0.848 m), vz = g (T - Tc). Halo hits: |vz| < 30 mm/s,
in-plane |v| < 45 mm/s, outside both BEC cores and the streak lines. Pairs within a shot: s = v1 + v2
(0 for a back-to-back pair); the same between consecutive shots normalises: g2_BB(s) = in-shot /
between-shot pair counts, scaled so the 8-20 mm/s shell is 1. Peak: amplitude at |s| < 1.5 mm/s,
per-axis RMS width of s for |s| < 4 mm/s (background-subtracted).

Any affine map of X, Y (scale per axis, rotation, shear, centre) keeps v1 + v2 = 2c for every BB
pair, so the BB peak cannot pick X/Y scale or rotation: shown numerically. Non-linear maps
(radial r -> r (1 + k r^2), and quadratic per-axis terms) do smear it: scanned here.
Writes out/halos.json, figures/halo_*.png."""
from __future__ import annotations

import json
import numpy as np
from common import OUT, SAMPLES, figure, save, read_txy, txy_files

TF = 0.4161
G = 9.796
BEC_T = (2.13825, 2.14230)
BEC_XY = (-6.98e-3, -1.33e-3)
TC = sum(BEC_T) / 2

shots = []
for f in txy_files(SAMPLES / "calib-2026/20261010-411trapcollisions44"):
    a = read_txy(f)
    if len(a):
        shots.append(a)


def select(a):
    T, X, Y = a.T
    m = (np.abs(T - TC) < 30e-3 / G) & (np.hypot(X - BEC_XY[0], Y - BEC_XY[1]) < 45e-3 * TF)
    for tb in BEC_T:
        m &= ~((np.abs(T - tb) < 0.7e-3) & (np.hypot(X - BEC_XY[0], Y - BEC_XY[1]) < 6e-3))
    # higher diffraction orders and the bright features: drop the dense Y≈+2 mm, X<-15 mm band etc. by T
    return a[m]


halo = [select(a) for a in shots]
print("halo hits per shot: median", np.median([len(h) for h in halo]), "total", sum(len(h) for h in halo))


def velocities(a, warp=None):
    T, X, Y = a.T
    if warp is not None:
        X, Y = warp(X, Y)
    vx = (X - BEC_XY[0]) / TF * 1e3
    vy = (Y - BEC_XY[1]) / TF * 1e3
    vz = G * (T - TC) * 1e3
    return np.c_[vx, vy, vz]


EDGES = np.arange(0, 20.01, 0.5)


def pair_sums(vs, between=False):
    out = []
    for i in range(len(vs)):
        a = vs[i]
        b = vs[(i + 1) % len(vs)] if between else a
        if len(a) < 2 or len(b) < 2:
            continue
        s = a[:, None, :] + b[None, :, :]
        if not between:
            iu = np.triu_indices(len(a), 1)
            s = s[iu]
        else:
            s = s.reshape(-1, 3)
        n = np.linalg.norm(s, axis=1)
        out.append(s[n < 20])
    return np.concatenate(out)


def bb_metrics(warp=None):
    vs = [velocities(h, warp) for h in halo]
    s_in = pair_sums(vs)
    s_bt = pair_sums(vs, between=True)
    hi, _ = np.histogram(np.linalg.norm(s_in, axis=1), EDGES)
    hb, _ = np.histogram(np.linalg.norm(s_bt, axis=1), EDGES)
    mid = (EDGES[1:] + EDGES[:-1]) / 2
    shell = (mid > 8) & (mid < 20)
    scale = hi[shell].sum() / hb[shell].sum()
    g2 = hi / np.maximum(hb * scale, 1e-9)
    near_in = (np.linalg.norm(s_in, axis=1) < 1.5).sum()
    near_bt = (np.linalg.norm(s_bt, axis=1) < 1.5).sum() * scale
    # per-axis RMS of s inside 4 mm/s, background-subtracted (between-shot distribution scaled)
    widths = []
    for k in range(3):
        sel_in = s_in[np.linalg.norm(s_in, axis=1) < 4][:, k]
        sel_bt = s_bt[np.linalg.norm(s_bt, axis=1) < 4][:, k]
        m2 = ((sel_in ** 2).sum() - scale * (sel_bt ** 2).sum()) / max(len(sel_in) - scale * len(sel_bt), 1)
        widths.append(float(np.sqrt(max(m2, 0))))
    return {"g2_peak_lt1.5": float(near_in / near_bt), "pairs_lt1.5": int(near_in), "rms_width_xyz_mm_s": widths,
            "g2_curve": g2.tolist()}


base = bb_metrics()
res = {"halo_centre": {"T": TC, "X_mm": BEC_XY[0] * 1e3, "Y_mm": BEC_XY[1] * 1e3, "bec_dT_ms": (BEC_T[1] - BEC_T[0]) * 1e3,
                       "expected_radius_mm_s": G * (BEC_T[1] - BEC_T[0]) / 2 * 1e3},
       "baseline": {k: v for k, v in base.items() if k != "g2_curve"}}
print("baseline", res["baseline"])

# affine checks: x scale 1.05, rotation 0.1 rad about detector centre (should not change the peak)
cx, cy = BEC_XY
affine = {
    "x_scale_1.05": lambda X, Y: (cx + (X - cx) * 1.05, Y),
    "rotate_0.1rad": lambda X, Y: (cx + np.cos(.1) * (X - cx) - np.sin(.1) * (Y - cy), cy + np.sin(.1) * (X - cx) + np.cos(.1) * (Y - cy)),
}
res["affine"] = {}
for k, w in affine.items():
    m = bb_metrics(w)
    res["affine"][k] = {kk: v for kk, v in m.items() if kk != "g2_curve"}
    print(k, res["affine"][k])

# non-linear: radial about the detector centre (0, 0): r -> r (1 + k r^2), r in m
res["radial"] = {}
for k in (-60.0, -30.0, -15.0, 0.0, 15.0, 30.0, 60.0):  # 1/m^2: 30 /m^2 = 0.3 % at 10 mm, 1.9 % at 25 mm
    w = (lambda kk: (lambda X, Y: (X * (1 + kk * (X ** 2 + Y ** 2)), Y * (1 + kk * (X ** 2 + Y ** 2)))))(k)
    m = bb_metrics(w)
    res["radial"][str(k)] = {kk: v for kk, v in m.items() if kk != "g2_curve"}
    print("radial", k, res["radial"][str(k)])
# non-linear per axis: X -> X + a X^2 (a in 1/m): a = 1 /m is 1 % at 10 mm
res["x_quadratic"] = {}
for a in (-2.0, -1.0, 0.0, 1.0, 2.0):
    w = (lambda aa: (lambda X, Y: (X + aa * X ** 2, Y)))(a)
    m = bb_metrics(w)
    res["x_quadratic"][str(a)] = {kk: v for kk, v in m.items() if kk != "g2_curve"}
    print("xq", a, res["x_quadratic"][str(a)]["g2_peak_lt1.5"], res["x_quadratic"][str(a)]["rms_width_xyz_mm_s"])
res["y_quadratic"] = {}
for a in (-2.0, -1.0, 0.0, 1.0, 2.0):
    w = (lambda aa: (lambda X, Y: (X, Y + aa * Y ** 2)))(a)
    m = bb_metrics(w)
    res["y_quadratic"][str(a)] = {kk: v for kk, v in m.items() if kk != "g2_curve"}
    print("yq", a, res["y_quadratic"][str(a)]["g2_peak_lt1.5"], res["y_quadratic"][str(a)]["rms_width_xyz_mm_s"])
(OUT / "halos.json").write_text(json.dumps(res, indent=1))

fig = figure(12, 4)
ax = fig.subplots(1, 3)
mid = (EDGES[1:] + EDGES[:-1]) / 2
ax[0].plot(mid, base["g2_curve"], "o-", ms=3, color="#4269d0")
ax[0].axhline(1, color="0.6", lw=0.8)
ax[0].set_xlabel("|v1 + v2| [mm/s]"); ax[0].set_ylabel("g2 back-to-back"); ax[0].set_title("BB correlation, 2025 plates (collisions44)")
ks = sorted(res["radial"], key=float)
ax[1].plot([float(k) for k in ks], [res["radial"][k]["g2_peak_lt1.5"] for k in ks], "o-", color="#ef4444")
ax[1].set_xlabel("radial distortion k [1/m²] (r → r(1+k r²))"); ax[1].set_ylabel("g2 at |s| < 1.5 mm/s")
ax[1].set_title("non-linear: radial")
for nm, col in (("x_quadratic", "#4269d0"), ("y_quadratic", "#16a34a")):
    ks = sorted(res[nm], key=float)
    ax[2].plot([float(k) for k in ks], [res[nm][k]["g2_peak_lt1.5"] for k in ks], "o-", color=col, label=nm)
ax[2].set_xlabel("quadratic term a [1/m] (X → X + a X²)"); ax[2].legend(); ax[2].set_title("non-linear: per axis")
save(fig, "halo_bb.png")
