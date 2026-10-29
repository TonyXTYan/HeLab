"""Channel-7 rate history: stream a sample of raw files from every post-swap raw folder on X
(read-only, nothing copied) plus every local raw file, and record per file: channel counts, ch7
times, ch5 rows, duration, mtime, and the wiring fingerprint (each corner's delay-line reflection
delay: the same-channel interval peak near 170-175 ns or 187-197 ns). Writes out/ch7_x_files.csv
and out/ch7_x_pulses.csv.

python ch7_x_scan.py
"""
import os

# The 2026-09-22 BEC run's folder on X.
SEPT_2026_FOLDER = os.environ.get("CH7_SEPT_2026_FOLDER", "2026-09-22 BEC run")

from __future__ import annotations

import os
import re
import numpy as np
import pandas as pd
from common import OUT, SAMPLES, SCRATCH, BIN, read_raw, raw_files, shot_number

X = "/Volumes/192.168.137.1-4/dld_output_cheerypicked"
STEPS = {"20260620_Rabi_trial_weak_intrap": 10, "20260626_Ramsey_weaktrap": 12, "20260627_Ramsey_weaktrap": 15,
         "20260722-tight-trap-freq-meas": 4, SEPT_2026_FOLDER: 3}


def x_files(folder: str, step: int) -> list[tuple[str, str]]:
    listing = SCRATCH / "listings" / (("20260922" if folder.startswith("20260922") else folder) + ".txt")
    paths = []
    for line in listing.read_text().splitlines():
        size, mtime, path = line.split(" ", 2)
        if re.search(r"/d\d+\.txt$", path):
            paths.append(path if path.startswith("/") else f"{X}/{path}")
    out = []
    for sub in sorted({os.path.dirname(p) for p in paths}):
        ps = sorted((p for p in paths if os.path.dirname(p) == sub), key=shot_number)
        out += [(folder, p) for p in ps[::step]]
    return out


def fingerprint(c, t):
    fp = {}
    for k, n in enumerate(("x1", "x2", "y1", "y2")):
        iv = np.diff(np.sort(t[c == k])) * BIN * 1e9
        lo = int(((iv >= 165) & (iv < 181)).sum())
        hi = int(((iv >= 184) & (iv < 200)).sum())
        fp[f"refl_lo_{n}"], fp[f"refl_hi_{n}"] = lo, hi
    return fp


todo = []
for folder, step in STEPS.items():
    todo += x_files(folder, step)
todo += [("20260625_Ramsey_weak_trap (local, all)", str(p)) for p in raw_files(SAMPLES / "calib-2026/20260625_Ramsey_weak_trap")]
rows, pulses = [], []
for i, (folder, path) in enumerate(todo):
    try:
        c, t = read_raw(path)
    except Exception as e:  # noqa: BLE001
        print("skip", path, e)
        continue
    t0 = t[0]
    rel = (t - t0) * BIN
    i5 = np.flatnonzero(c == 5)
    r = dict(folder=folder, sub=os.path.basename(os.path.dirname(path)), shot=shot_number(path), mtime=os.path.getmtime(path),
             size=os.path.getsize(path), duration=float(rel.max()), first_channel=int(c[0]),
             **{f"n{k}": int((c == k).sum()) for k in range(8)},
             n_other=int((c > 7).sum() + (c < 0).sum()),
             ch5_extra=int(len(i5) - 1), ch5_first_extra_us=float(rel[i5[1]] * 1e6) if len(i5) > 1 else np.nan,
             ch5_span_ns=float((rel[i5[1:]].max() - rel[i5[1:]].min()) * 1e9) if len(i5) > 2 else np.nan,
             **fingerprint(c, t))
    rows.append(r)
    for j in np.flatnonzero(c == 7):
        pulses.append(dict(folder=folder, sub=r["sub"], shot=r["shot"], mtime=r["mtime"], t_s=float(rel[j]), row_frac=j / len(c)))
    if i % 50 == 0:
        print(i, len(todo), folder, flush=True)
pd.DataFrame(rows).to_csv(OUT / "ch7_x_files.csv", index=False)
pd.DataFrame(pulses).to_csv(OUT / "ch7_x_pulses.csv", index=False)
print("done", len(rows))
