"""'Anything else': the Quantum_efficiency scan (hits per shot vs the folder parameter, T range,
negative T, peak rates), RingBEC hits, shot-number gaps and pauses per post-swap folder (from the
X listings and the LabVIEW logs), and log vs file agreement. Writes out/other_checks.json and
figures/qe_*.png, figures/gaps_*.png."""
from __future__ import annotations

import datetime as dt
import json
import re
import numpy as np
import pandas as pd
from common import OUT, SCRATCH, SAMPLES, figure, save, read_txy, txy_files, parse_labview_log

res = {}
LIST = SCRATCH / "listings"


def listing(name):
    rows = []
    for line in (LIST / f"{name}.txt").read_text().splitlines():
        size, mtime, path = line.split(" ", 2)
        m = re.search(r"/(d|d_txy_forc)(\d+)\.txt$", path)
        if m:
            rows.append(dict(kind="raw" if m.group(1) == "d" else "txy", shot=int(m.group(2)), size=int(size),
                             mtime=int(mtime), sub=path.split("/")[1] if path.count("/") >= 2 else ""))
    return pd.DataFrame(rows)


# --- QE
qe = SAMPLES / "calib-2026/20260812_Quantum_efficiency"
copied = []
for f in txy_files(qe):
    a = read_txy(f)
    T = a[:, 0]
    h, e = np.histogram(T[(T >= 0) & (T < 7)], bins=np.arange(0, 7, 0.001))
    copied.append(dict(sub=f.parent.name if f.parent != qe else "", shot=int(re.search(r"(\d+)", f.name).group(1)),
                       hits=len(a), bytes=f.stat().st_size, neg=int((T < 0).sum()), t_min=float(T.min()), t_max=float(T.max()),
                       beyond_4s=int((T > 4.1).sum()), peak_per_ms=int(h.max()), t_peak=float(e[np.argmax(h)])))
cq = pd.DataFrame(copied)
bph = (cq.bytes / cq.hits).median()
L = listing("20260812_Quantum_efficiency")
L["hits_est"] = L["size"] / bph
L["param"] = L["sub"].map(lambda s: float(s.replace("pt", ".")) if s else np.nan)
by = L.dropna(subset=["param"]).groupby("param").hits_est.agg(["count", "mean", "std"])
res["qe"] = {"bytes_per_hit": float(bph), "copied_files": cq.to_dict("records"),
             "hits_by_param_est": {f"{k:.3f}": {"shots": int(v["count"]), "mean_hits": round(v["mean"]), "sd": round(v["std"])} for k, v in by.iterrows()},
             "top_level_files": int((L["sub"] == "").sum()),
             "top_level_hits_est_median": float(L[L["sub"] == ""].hits_est.median())}
print(cq[["sub", "shot", "hits", "neg", "t_min", "t_max", "beyond_4s", "peak_per_ms", "t_peak"]].to_string())
print(by)
fig = figure(7, 4)
ax = fig.subplots()
ax.errorbar(by.index, by["mean"] / 1e3, by["std"] / 1e3, fmt="o", color="#4269d0")
ax.set_xlabel("folder parameter (16pt999 → 16.999; unit unknown, likely RF MHz)"); ax.set_ylabel("hits per shot [thousands] (from file size)")
ax.set_title("20260812_Quantum_efficiency: detected hits vs scanned parameter")
save(fig, "qe_hits_vs_param.png")

# --- shot gaps and pauses per folder (X listings: raw if present, else TXY)
res["gaps"] = {}
for name in ("20260620_Rabi_trial_weak_intrap", "20260625_Ramsey_weak_trap", "20260626_Ramsey_weaktrap", "20260627_Ramsey_weaktrap",
             "20260722-tight-trap-freq-meas", "20260723-tight-trap-freq-meas", "20260727-RingBEC", "20260812_Quantum_efficiency",
             "20261010-411trapcollisions44"):
    L = listing(name)
    k = "raw" if (L.kind == "raw").any() else "txy"
    s = L[L.kind == k].sort_values("shot")
    shots = s.shot.to_numpy()
    full = np.arange(shots.min(), shots.max() + 1)
    missing = np.setdiff1d(full, shots)
    t = s.sort_values("mtime").mtime.to_numpy()
    dts = np.diff(t)
    med = float(np.median(dts)) if len(dts) else None
    pauses = [(dt.datetime.fromtimestamp(int(t[i])).isoformat(), int(dts[i])) for i in np.flatnonzero(dts > 300)]
    r = {"kind": k, "files": int(len(s)), "shot_range": [int(shots.min()), int(shots.max())], "missing_in_range": int(len(missing)),
         "missing_runs": [], "median_interval_s": med, "pauses_over_5min": pauses[:12], "n_pauses": len(pauses),
         "first": dt.datetime.fromtimestamp(int(t.min())).isoformat(), "last": dt.datetime.fromtimestamp(int(t.max())).isoformat(),
         "raw_without_txy": int(len(set(L[L.kind == "raw"].shot) - set(L[L.kind == "txy"].shot))) if k == "raw" else None,
         "txy_zero_bytes": int(((L.kind == "txy") & (L["size"] == 0)).sum())}
    if len(missing):
        runs, start = [], missing[0]
        for a, b in zip(missing, list(missing[1:]) + [None]):
            if b != a + 1:
                runs.append([int(start), int(a)])
                start = b
        r["missing_runs"] = runs[:15]
    res["gaps"][name] = r
    print(name, {kk: v for kk, v in r.items() if kk not in ("pauses_over_5min",)})

# --- logs vs files (four raw folders)
res["logs"] = {}
for name in ("20260620_Rabi_trial_weak_intrap", "20260625_Ramsey_weak_trap", "20260626_Ramsey_weaktrap", "20260627_Ramsey_weaktrap"):
    log = parse_labview_log(SAMPLES / "calib-2026" / name / "log_LabviewMatlab.txt")
    L = listing(name)
    raws = set(L[L.kind == "raw"].shot)
    ls = set(log.shot)
    scan_cols = [c for c in log.columns if c.endswith("scan") or c.endswith("_scan")]
    dup = int(log.shot.duplicated().sum())
    r = {"log_rows": int(len(log)), "log_shot_range": [int(log.shot.min()), int(log.shot.max())], "duplicate_shot_numbers": dup,
         "raw_files": len(raws), "logged_without_raw": len(ls - raws), "raw_without_log": len(raws - ls),
         "scan_columns": scan_cols, "log_interval_median_s": float(np.median(np.diff(np.sort(log.posix))))}
    # which log shot numbers map to raw shot numbers? check offset
    if raws - ls:
        r["raw_without_log_examples"] = sorted(raws - ls)[:10]
    if ls - raws:
        r["logged_without_raw_examples"] = sorted(ls - raws)[:10]
    res["logs"][name] = r
    print(name, r)
(OUT / "other_checks.json").write_text(json.dumps(res, indent=1, default=str))
