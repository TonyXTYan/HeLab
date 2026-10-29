"""Matching-parameter effects with HeLab's converter (numpy backend) on the 2025-plate raw samples:
each variant perturbs matlab-2019 (= plates-2025) fields. Per variant: hits, the change, and where the
change falls: in the atoms' arrival windows (from the baseline's T histogram; 5 ms bins over 5x the
median) or outside them (background: dark counts + random combinations). A change that is mostly
outside the windows adds or removes non-atoms. x2 retry (not a profile option) uses probe_match.
Writes out/matching_params.json."""
from __future__ import annotations

import io
import json
import numpy as np
from common import OUT, SAMPLES, helab_env, raw_files, read_raw

helab_env()
from helab.convert.pipeline import convert_raw  # noqa: E402
from helab.convert.profile import builtin_profile  # noqa: E402
from probe_match import match  # noqa: E402

BASE = builtin_profile("plates-2025")
VARIANTS = {
    "baseline (matlab-2019 = plates-2025 today)": {},
    "match_tolerance 100 (x and y)": dict(match_tolerance_x=100.0, match_tolerance_y=100.0),
    "match_tolerance 300": dict(match_tolerance_x=300.0, match_tolerance_y=300.0),
    "xy_sum_tolerance 200": dict(xy_sum_tolerance=200.0),
    "xy_sum_tolerance 300": dict(xy_sum_tolerance=300.0),
    "xy_sum_tolerance 600": dict(xy_sum_tolerance=600.0),
    "window 3600 (search 3600, |x1-x2| < 3800)": dict(search_window=3600.0, match_time_sum_x=3600.0, match_time_sum_y=3600.0),
    "window 4000 (search 4000, |x1-x2| < 4200)": dict(search_window=4000.0, match_time_sum_x=4000.0, match_time_sum_y=4000.0),
    "search_depth 18": dict(search_depth=18),
    "search_depth 72": dict(search_depth=72),
    "dead time 0.25 us all corners": dict(dead_time_x1=0.25e-6, dead_time_x2=0.25e-6, dead_time_y1=0.25e-6, dead_time_y2=0.25e-6),
    "dead time x1 0.5 us (2023 edit)": dict(dead_time_x1=0.5e-6),
    "time sums in T 3367/3294 (T shift only)": dict(time_sum_t_x=3367.0, time_sum_t_y=3294.0),
}
SETS = {"Jun 2026 (4 runs, 172 shots)": [p for p in sorted((SAMPLES / "txy-2026").iterdir()) if p.is_dir()],
        "Jul 2026 tight trap (24 shots)": [SAMPLES / "calib-2026/20260722-tight-trap-freq-meas"]}


def parse(b):
    if not b:
        return np.zeros((0, 3))
    return np.loadtxt(io.BytesIO(b), delimiter=",", ndmin=2)


res = {}
for sname, folders in SETS.items():
    files = [f for d in folders for f in raw_files(d)]
    datas = [f.read_bytes() for f in files]
    out = {}
    base_T = None
    for vname, ch in VARIANTS.items():
        prof = BASE.replace(name="probe", tag="", **ch)
        Ts = [parse(convert_raw(d, prof, "numpy"))[:, 0] for d in datas]
        T = np.concatenate(Ts)
        if base_T is None:
            base_T = T
            edges = np.arange(0, 4.21, 0.005)
            h, _ = np.histogram(T, edges)
            on = h > 5 * max(np.median(h), 1)
        i = np.clip(np.searchsorted(edges, T, side="right") - 1, 0, len(on) - 1)
        inw = on[i] & (T >= 0) & (T < 4.2)
        out[vname] = {"hits": int(len(T)), "in_atom_windows": int(inw.sum()), "outside": int((~inw).sum())}
        print(sname, vname, out[vname], flush=True)
    # x2 retry via the probe
    tot = inw_n = 0
    Tall = []
    for f in files:
        c, t = read_raw(f)
        Tall.append(match(c, t, x2_retry=True)["T"])
    T = np.concatenate(Tall)
    i = np.clip(np.searchsorted(edges, T, side="right") - 1, 0, len(on) - 1)
    inw = on[i] & (T >= 0) & (T < 4.2)
    out["x2 retry (probe_match; MATLAB keeps the first x2)"] = {"hits": int(len(T)), "in_atom_windows": int(inw.sum()), "outside": int((~inw).sum())}
    b = out[next(iter(VARIANTS))]
    for v in out.values():
        v["change_pct"] = round(100 * (v["hits"] - b["hits"]) / b["hits"], 3)
        v["change_in_windows"] = v["in_atom_windows"] - b["in_atom_windows"]
        v["change_outside"] = v["outside"] - b["outside"]
    out["_atom_window_time_fraction"] = float(on.mean())
    res[sname] = out
(OUT / "matching_params.json").write_text(json.dumps(res, indent=1))
for s, o in res.items():
    print("\n", s, "window fraction", o["_atom_window_time_fraction"])
    for k, v in o.items():
        if not k.startswith("_"):
            print(f"  {k:55s} {v['hits']:8d} {v['change_pct']:+7.3f}%  in-win {v['change_in_windows']:+7d}  outside {v['change_outside']:+6d}")
