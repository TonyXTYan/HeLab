"""Channel 7 (and channel 5) survey over every raw file available locally.

Output: out/ch7_survey.csv (one row per raw file), out/ch7_pulses.csv (one row per ch7 pulse).
"""
from __future__ import annotations

import os
import numpy as np
import pandas as pd
from common import OUT, SAMPLES, BIN, raw_files, read_raw, shot_number

SETS = {
    "2026-06-20 Rabi (s)": SAMPLES / "txy-2026/2026-06-20-rabi-weak-intrap",
    "2026-06-25 Ramsey (s)": SAMPLES / "txy-2026/2026-06-25-ramsey-weak-trap",
    "2026-06-26 Ramsey (s)": SAMPLES / "txy-2026/2026-06-26-ramsey-weak-trap",
    "2026-06-27 Ramsey (s)": SAMPLES / "txy-2026/2026-06-27-ramsey-weak-trap",
    "2026-06-25 Ramsey all": SAMPLES / "calib-2026/20260625_Ramsey_weak_trap",
    "2026-07 tight trap": SAMPLES / "calib-2026/20260722-tight-trap-freq-meas",
    "2025-01 pre-swap": SAMPLES / "calib-2026/20250104_off_axis_check_mirror",
}
for name in sorted(os.listdir(SAMPLES / "txy-v1")):
    if (SAMPLES / "txy-v1" / name).is_dir():
        SETS[f"v1 {name}"] = SAMPLES / "txy-v1" / name

rows, pulses = [], []
for set_name, folder in SETS.items():
    for path in raw_files(folder):
        c, t = read_raw(path)
        t0 = t[0]
        rel = (t - t0) * BIN
        corner = c <= 3
        counts = {f"n{k}": int((c == k).sum()) for k in range(8)}
        other = sorted(set(np.unique(c).tolist()) - set(range(8)))
        last_corner = rel[corner].max() if corner.any() else np.nan
        first_corner = rel[corner].min() if corner.any() else np.nan
        i7 = np.flatnonzero(c == 7)
        i5 = np.flatnonzero(c == 5)
        r = dict(set=set_name, sub=path.parent.name, shot=shot_number(path), rows=len(c), **counts,
                 other_channels=str(other), t0_bins=int(t0), t0_s=t0 * BIN, first_channel=int(c[0]),
                 first_corner_s=first_corner, last_corner_s=last_corner, last_row_s=rel[-1], max_s=rel.max(),
                 ch5_rel_max_us=(rel[i5].max() * 1e6) if len(i5) else np.nan,
                 ch5_rel_min_us=(rel[i5[1:]].min() * 1e6) if len(i5) > 1 else np.nan,
                 mtime=os.path.getmtime(path))
        for j, i in enumerate(i7):
            tt = rel[i]
            win = 0.05
            before = int(((rel >= tt - win) & (rel < tt) & corner).sum())
            after = int(((rel >= tt) & (rel < tt + win) & corner).sum())
            # nearest corner pulses
            dc = np.abs(rel[corner] - tt)
            pulses.append(dict(set=set_name, sub=path.parent.name, shot=shot_number(path), k=j, t_s=tt,
                               row_frac=i / len(c), row=int(i), rows=len(c), corner_before_50ms=before,
                               corner_after_50ms=after, nearest_corner_us=dc.min() * 1e6 if len(dc) else np.nan,
                               last_corner_s=last_corner, t_abs_bins=int(t[i])))
        r["ch7_t_s"] = ";".join(f"{rel[i]:.6f}" for i in i7)
        rows.append(r)
    print(set_name, len([r for r in rows if r["set"] == set_name]), flush=True)

OUT.mkdir(exist_ok=True)
pd.DataFrame(rows).to_csv(OUT / "ch7_survey.csv", index=False)
pd.DataFrame(pulses).to_csv(OUT / "ch7_pulses.csv", index=False)
