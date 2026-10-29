"""Match every local raw file of the chosen sets with probe_match twice, the matlab-2019 window
(3200) and a wide one (window 4000, |x1-x2| and |y1-y2| < 4200), and save per-hit corner times to
SCRATCH/hits/<set>.npz. Also per-channel raw pulse times for the spacing study (first N files).

python build_hits.py [set ...]
"""
from __future__ import annotations

import sys
import numpy as np
from common import SAMPLES, SCRATCH, raw_files, read_raw, shot_number
from probe_match import match

SETS = {
    "p25-0620-rabi": [SAMPLES / "txy-2026/2026-06-20-rabi-weak-intrap"],
    "p25-0625-ramsey": [SAMPLES / "calib-2026/20260625_Ramsey_weak_trap"],
    "p25-0626-ramsey": [SAMPLES / "txy-2026/2026-06-26-ramsey-weak-trap"],
    "p25-0627-ramsey": [SAMPLES / "txy-2026/2026-06-27-ramsey-weak-trap"],
    "p25-07-tight": [SAMPLES / "calib-2026/20260722-tight-trap-freq-meas"],
    "p22-2025-01-offaxis": [SAMPLES / "calib-2026/20250104_off_axis_check_mirror"],
    "p22-2022-11-ghost-mcp": [SAMPLES / "txy-v1/2022-11-ghost-counts-mcp"],
    "p22-2023-02-he3he4": [SAMPLES / "txy-v1/2023-02-new-plates-he3he4"],
    "p22-2023-03-bells": [SAMPLES / "txy-v1/2023-03-momentum-bells"],
    "p22-2024-11-lowocc": [SAMPLES / "txy-v1/2024-11-rt-low-occupancy"],
    "p17-2022-07-large-he3": [SAMPLES / "txy-v1/2022-07-old-plates-large-he3"],
    "p17-2020-halos": [SAMPLES / "txy-v1/2020-halos-weak-trap"],
}
WIDE = dict(window=4000, x_limit=4200, y_limit=4200)

out = SCRATCH / "hits"
out.mkdir(parents=True, exist_ok=True)
for name in (sys.argv[1:] or list(SETS)):
    acc = {k: [] for k in ("x1", "x2", "y1", "y2", "T", "shot")}
    wacc = {k: [] for k in ("x1", "x2", "y1", "y2", "T", "shot")}
    pulses = {k: [] for k in range(4)}
    npulse = []
    files = [f for folder in SETS[name] for f in raw_files(folder)]
    for f in files:
        c, t = read_raw(f)
        s = shot_number(f)
        for a, kw in ((acc, {}), (wacc, WIDE)):
            h = match(c, t, **kw)
            for k in ("x1", "x2", "y1", "y2", "T"):
                a[k].append(h[k])
            a["shot"].append(np.full(len(h["T"]), s))
        npulse.append([s, *[(c == k).sum() for k in range(8)], (t.max() - t[0])])
        if len(pulses[0]) < 60:
            for k in range(4):
                pulses[k].append(np.sort(t[c == k]))
    np.savez_compressed(out / f"{name}.npz", **{k: np.concatenate(v) for k, v in acc.items()},
                        **{"w_" + k: np.concatenate(v) for k, v in wacc.items()}, npulse=np.array(npulse, dtype=float),
                        **{f"pulses{k}": np.array(v, dtype=object) for k, v in pulses.items()}, files=len(files))
    print(name, len(files), "hits", sum(map(len, acc["T"])), "wide", sum(map(len, wacc["T"])), flush=True)
