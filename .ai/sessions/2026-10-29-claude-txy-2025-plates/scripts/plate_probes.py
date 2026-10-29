"""Raw-pulse plate probes per set, from build_hits.py's npz files:

* x-y time-sum difference D = (x1 + x2) - (y1 + y2) (bins): median, IQR, and its map across the plate;
* absolute time sums for the one set with MCP pulses (2022-11 ghost counts), as a check of the method;
* edge clipping: hits a wide window (4000) adds; their T distribution vs normal hits and vs flat;
* per-channel pulse spacing (same-channel intervals: ringing, dead time) and the fraction of each
  channel's pulses used in hits;
* footprint: 99.9 % ranges and the edge radius by angle (from all hits; and background-window hits).

Writes out/plate_probes.json and figures/pp_*.png.
"""
from __future__ import annotations

import json
import numpy as np
from matplotlib.colors import LogNorm
from common import OUT, SCRATCH, BIN, M_PER_BIN, figure, save, read_raw, raw_files, SAMPLES

H = SCRATCH / "hits"
GROUPS = {
    "2025 plates, Jun 2026 (weak trap)": ["p25-0620-rabi", "p25-0625-ramsey", "p25-0626-ramsey", "p25-0627-ramsey"],
    "2025 plates, Jul 2026 (tight trap)": ["p25-07-tight"],
    "2022 plates (2023-02..2025-01)": ["p22-2023-02-he3he4", "p22-2023-03-bells", "p22-2024-11-lowocc", "p22-2025-01-offaxis"],
    "2022 plates, 2022-11 ghost counts (MCP)": ["p22-2022-11-ghost-mcp"],
    "2017 plates (2020, 2022-07)": ["p17-2020-halos", "p17-2022-07-large-he3"],
}


def load(names):
    d = {}
    for n in names:
        z = np.load(H / f"{n}.npz", allow_pickle=True)
        for k in z.files:
            if k.startswith("pulses") or k == "files":
                continue
            d.setdefault(k, []).append(z[k])
        d.setdefault("files", []).append(int(z["files"]))
    return {k: (np.concatenate(v) if k != "files" else sum(v)) for k, v in d.items()}


def atom_windows(T, width=0.005, factor=5.0):
    """T bins whose rate is above `factor` x the median rate: the atoms' arrival windows."""
    edges = np.arange(0, 4.2 + width, width)
    h, _ = np.histogram(T, edges)
    base = np.median(h)
    on = h > factor * max(base, 1)
    return edges, on, base


def in_windows(T, edges, on):
    i = np.clip(np.searchsorted(edges, T, side="right") - 1, 0, len(on) - 1)
    return on[i] & (T >= 0) & (T < edges[-1])


res = {}
for gname, names in GROUPS.items():
    d = load(names)
    x1, x2, y1, y2, T = d["x1"], d["x2"], d["y1"], d["y2"], d["T"]
    D = (x1 + x2) - (y1 + y2)
    Xb, Yb = x1 - x2, y1 - y2
    r = {"files": d["files"], "hits": int(len(T))}
    q = np.percentile(D, [25, 50, 75])
    r["D_median"], r["D_iqr"] = float(q[1]), float(q[2] - q[0])
    # bootstrap over shots for the median's uncertainty
    shots = d["shot"]
    us = np.unique(shots)
    rng = np.random.default_rng(1)
    groups = [D[shots == s] for s in us]
    meds = [np.median(np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])) for _ in range(200)]
    r["D_median_boot_sd"] = float(np.std(meds))
    # D vs position: linear fit D = a + b X + c Y (bins), robust (on hits with |D| < 400)
    m = np.abs(D - q[1]) < 300
    A = np.c_[np.ones(m.sum()), Xb[m] / 1000, Yb[m] / 1000, (Xb[m] / 1000) ** 2, (Yb[m] / 1000) ** 2, Xb[m] * Yb[m] / 1e6]
    coef, *_ = np.linalg.lstsq(A, D[m], rcond=None)
    r["D_fit_bins"] = dict(zip(["c0", "per_kbin_X", "per_kbin_Y", "X2", "Y2", "XY"], np.round(coef, 2).tolist()))
    # 2-D median map
    edges = np.linspace(-3000, 3000, 25)
    ix = np.digitize(Xb, edges) - 1
    iy = np.digitize(Yb, edges) - 1
    mp = np.full((24, 24), np.nan)
    for a in range(24):
        for b in range(24):
            s = (ix == a) & (iy == b)
            if s.sum() > 30:
                mp[b, a] = np.median(D[s])
    r["D_map_range_p5_p95"] = [float(np.nanpercentile(mp, 5)), float(np.nanpercentile(mp, 95))]
    # 99.9 % ranges, bins
    r["X_range_999_bins"] = np.percentile(Xb, [0.05, 99.95]).round(0).tolist()
    r["Y_range_999_bins"] = np.percentile(Yb, [0.05, 99.95]).round(0).tolist()
    # edge clipping: wide extras
    w = {k: d["w_" + k] for k in ("x1", "x2", "y1", "y2", "T")}
    wX, wY = w["x1"] - w["x2"], w["y1"] - w["y2"]
    span = np.max(np.abs(np.c_[w["x2"], w["y1"], w["y2"]] - w["x1"][:, None]), axis=1)
    extra = (np.abs(wX) >= 3200) | (np.abs(wY) >= 3200) | (span > 3200)
    r["wide_hits"] = int(len(w["T"]))
    r["wide_added"] = int(len(w["T"]) - len(T))
    r["wide_added_pct"] = 100 * (len(w["T"]) - len(T)) / max(len(T), 1)
    r["wide_extra_flagged"] = int(extra.sum())
    r["extra_by"] = {"|X|>=3200": int((np.abs(wX) >= 3200).sum()), "|Y|>=3200": int((np.abs(wY) >= 3200).sum()),
                     "span>3200 only": int((extra & (np.abs(wX) < 3200) & (np.abs(wY) < 3200)).sum())}
    ed, on, base = atom_windows(T)
    frac_window = on.mean()
    r["atom_window_fraction_of_time"] = float(frac_window)
    r["frac_in_atoms_normal"] = float(in_windows(T, ed, on).mean())
    r["frac_in_atoms_extra"] = float(in_windows(w["T"][extra], ed, on).mean()) if extra.any() else None
    # background-subtracted estimate of the extras that are atoms: f_e = a f_n + (1-a) f_flat
    if extra.any():
        fe, fn, ff = r["frac_in_atoms_extra"], r["frac_in_atoms_normal"], frac_window
        r["extra_atom_share_est"] = float((fe - ff) / (fn - ff)) if fn != ff else None
        r["extra_D_median"] = float(np.median((w["x1"] + w["x2"] - w["y1"] - w["y2"])[extra]))
        r["extra_D_iqr"] = float(np.subtract(*np.percentile((w["x1"] + w["x2"] - w["y1"] - w["y2"])[extra], [75, 25])))
    # footprint radius by angle, from hits (all), centre = median of hits within 99%
    Xmm, Ymm = Xb * M_PER_BIN * 1e3, Yb * M_PER_BIN * 1e3
    bg = ~in_windows(T, ed, on)
    r["bg_hits"] = int(bg.sum())
    res[gname] = r
    # figures per group
    tag = names[0].split("-")[0] + "_" + gname.split("(")[0].strip().replace(" ", "_").replace(",", "")
    fig = figure(13, 4)
    ax = fig.subplots(1, 3)
    ax[0].hist(D, bins=np.arange(-450, 451, 5), color="#4269d0")
    ax[0].set_xlabel("(x1+x2) − (y1+y2) [bins of 25 ps]"); ax[0].set_ylabel("hits"); ax[0].set_title(f"{gname}\nx−y time-sum difference")
    im = ax[1].imshow(mp, origin="lower", extent=[-3000 * M_PER_BIN * 1e3, 3000 * M_PER_BIN * 1e3] * 2, cmap="RdBu_r",
                      vmin=q[1] - 60, vmax=q[1] + 60)
    fig.colorbar(im, ax=ax[1], label="median difference [bins]")
    ax[1].set_xlabel("X [mm]"); ax[1].set_ylabel("Y [mm]"); ax[1].set_title("difference across the plate")
    ax[2].hist(T, bins=np.arange(0, 4.2, 0.01), histtype="step", density=True, label="normal hits", color="#4269d0")
    if extra.any():
        ax[2].hist(w["T"][extra], bins=np.arange(0, 4.2, 0.05), histtype="step", density=True, label=f"wide-window extras (n={extra.sum()})", color="#ef4444")
    ax[2].set_yscale("log"); ax[2].set_xlabel("T [s]"); ax[2].set_ylabel("density"); ax[2].legend(fontsize=8)
    ax[2].set_title("arrival times: normal vs extra hits")
    save(fig, f"pp_{tag}.png")

# Absolute time sums from MCP pulses (2022-11 ghost counts), for comparison with D
mcp = {"sum_x": [], "sum_y": [], "X": [], "Y": []}
for f in raw_files(SAMPLES / "txy-v1/2022-11-ghost-counts-mcp"):
    from probe_match import match
    c, t = read_raw(f)
    h = match(c, t)
    tm = np.sort((t[c == 4] - t[0]).astype(float))
    est = (h["x1"] + h["x2"] - 3200) / 2  # MATLAB's tx ~ MCP time
    j = np.clip(np.searchsorted(tm, est), 1, len(tm) - 1)
    near = np.where(np.abs(tm[j] - est) < np.abs(tm[j - 1] - est), tm[j], tm[j - 1])
    ok = np.abs(near - est) < 400
    mcp["sum_x"].append((h["x1"] + h["x2"] - 2 * near)[ok]); mcp["sum_y"].append((h["y1"] + h["y2"] - 2 * near)[ok])
    mcp["X"].append((h["x1"] - h["x2"])[ok]); mcp["Y"].append((h["y1"] - h["y2"])[ok])
mcp = {k: np.concatenate(v) for k, v in mcp.items()}
sx, sy = mcp["sum_x"], mcp["sum_y"]
res["mcp_2022_11"] = {"hits_with_mcp": int(len(sx)), "sum_x_median": float(np.median(sx)), "sum_y_median": float(np.median(sy)),
                      "sum_x_iqr": float(np.subtract(*np.percentile(sx, [75, 25]))),
                      "sum_y_iqr": float(np.subtract(*np.percentile(sy, [75, 25]))),
                      "D_from_mcp": float(np.median(sx - sy))}
for ax_name, s, pos in (("x", sx, mcp["X"]), ("y", sy, mcp["Y"])):
    m = np.abs(s - np.median(s)) < 300
    A = np.c_[np.ones(m.sum()), mcp["X"][m] / 1000, mcp["Y"][m] / 1000, (mcp["X"][m] / 1000) ** 2, (mcp["Y"][m] / 1000) ** 2]
    coef, *_ = np.linalg.lstsq(A, s[m], rcond=None)
    res["mcp_2022_11"][f"sum_{ax_name}_fit"] = dict(zip(["c0", "per_kbin_X", "per_kbin_Y", "X2", "Y2"], np.round(coef, 1).tolist()))
(OUT / "plate_probes.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
