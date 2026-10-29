"""Back-to-back g2 with one method on (a) the 2022-plate "3 halos" run (calib-v1, a free-space
Bragg halo: positive control) and (b) the 2025-plate collisions44 run. Velocity about the halo centre
(midpoint of the two BECs bounding it), shell selection |rho - 1| < w (rho: velocity over the
expected radius, ellipsoidal for collisions44 from its measured equator), poles near the BECs cut.
g2(|v1+v2|) = in-shot / consecutive-shot pairs, normalised on 15-30 % of R. Prints and saves
out/halo_bb_control.json; figures/halo_bb_control.png."""
import json
import numpy as np
from common import OUT, SAMPLES, figure, save, read_txy, txy_files

TF, G = 0.4161, 9.796


def becs(shots, t_guess, xy_r=8e-3):
    a = np.concatenate(shots)
    T, X, Y = a.T
    out = []
    for tg in t_guess:
        m = np.abs(T - tg) < 2e-3
        h, e = np.histogram(T[m], bins=400)
        tp = e[np.argmax(h)]
        mm = m & (np.abs(T - tp) < 3e-4)
        out.append((tp, np.median(X[mm]), np.median(Y[mm])))
    return out


def run(name, shots, b1, b2, axes, tilt_deg, width=0.12, pole=0.75):
    tc = (b1[0] + b2[0]) / 2
    cx, cy = (b1[1] + b2[1]) / 2, (b1[2] + b2[2]) / 2
    th = np.radians(tilt_deg)
    vs = []
    for a in shots:
        T, X, Y = a.T
        vx, vy, vz = (X - cx) / TF * 1e3, (Y - cy) / TF * 1e3, G * (T - tc) * 1e3
        u, w = np.cos(th) * vx + np.sin(th) * vy, -np.sin(th) * vx + np.cos(th) * vy
        rho = np.sqrt((u / axes[0]) ** 2 + (w / axes[1]) ** 2 + (vz / axes[2]) ** 2)
        m = (np.abs(rho - 1) < width) & (np.abs(vz) < pole * axes[2])
        vs.append(np.c_[vx, vy, vz][m])
    R = np.mean(axes)
    E = np.linspace(0, 0.3 * R, 31)

    def norms(between):
        out = []
        for i in range(len(vs)):
            a = vs[i]; b = vs[(i + 1) % len(vs)] if between else a
            s = a[:, None, :] + b[None, :, :]
            s = s[np.triu_indices(len(a), 1)] if not between else s.reshape(-1, 3)
            n = np.linalg.norm(s, axis=1)
            out.append(n[n < E[-1]])
        return np.concatenate(out)
    hi, _ = np.histogram(norms(False), E)
    hb, _ = np.histogram(norms(True), E)
    sl = slice(15, 30)
    sc = hi[sl].sum() / hb[sl].sum()
    g2 = hi / np.maximum(hb * sc, 1e-9)
    err = np.sqrt(np.maximum(hi, 1)) / np.maximum(hb * sc, 1e-9)
    k = 3  # first 3 bins = 3 % of R
    peak = hi[:k].sum() / (hb[:k].sum() * sc)
    perr = np.sqrt(hi[:k].sum()) / (hb[:k].sum() * sc)
    return {"name": name, "centre": [tc, cx * 1e3, cy * 1e3], "axes_mm_s": axes, "shell_hits_per_shot": float(np.median([len(v) for v in vs])),
            "bin_mm_s": float(E[1]), "g2_first3": float(peak), "g2_first3_err": float(perr), "pairs_first3": int(hi[:k].sum()),
            "g2": g2.tolist(), "g2_err": err.tolist(), "edges": E.tolist()}


res = []
s22 = [read_txy(f) for f in txy_files(SAMPLES / "calib-v1/plates-2022_20230130_halo_3_halos")]
b = becs(s22, (3.8640, 3.8770, 3.8900))
print("2022 BECs", b)
for i in range(2):
    vr = G * (b[i + 1][0] - b[i][0]) / 2 * 1e3
    res.append(run(f"2022 plates, 2023-01-30 halo {i + 1}", s22, b[i], b[i + 1], [vr, vr, vr], 0.0))
s25 = [read_txy(f) for f in txy_files(SAMPLES / "calib-2026/20261010-411trapcollisions44")]
b = becs(s25, (2.13825, 2.14230))
print("2025 BECs", b)
vr = G * (b[1][0] - b[0][0]) / 2 * 1e3
res.append(run("2025 plates, 2026-10-10 collisions44 (ellipsoid)", s25, b[0], b[1], [34.0, 15.0, vr], -35.0, width=0.2))
for r in res:
    print(r["name"], "shell hits/shot", r["shell_hits_per_shot"], "bin %.2f mm/s" % r["bin_mm_s"],
          "g2(first 3 bins) %.3f ± %.3f (pairs %d)" % (r["g2_first3"], r["g2_first3_err"], r["pairs_first3"]))
    print("   ", " ".join(f"{x:.2f}" for x in r["g2"][:12]))
(OUT / "halo_bb_control.json").write_text(json.dumps(res, indent=1))
fig = figure(12, 4)
axs = fig.subplots(1, len(res))
for ax, r in zip(axs, res):
    e = np.array(r["edges"]); mid = (e[1:] + e[:-1]) / 2
    ax.errorbar(mid, r["g2"], r["g2_err"], fmt="o", ms=3, color="#4269d0")
    ax.axhline(1, color="0.6", lw=0.8)
    ax.set_title(r["name"], fontsize=8); ax.set_xlabel("|v1 + v2| [mm/s]"); ax.set_ylabel("g2 back-to-back")
save(fig, "halo_bb_control.png")
