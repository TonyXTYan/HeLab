"""Does channel 7 change conversion? (1) HeLab's converter (matlab-2019 and plates-2025, numpy
backend) on every local post-swap raw file with channel 7, as is and with the ch7 rows removed:
byte-compare the TXY. (2) Are ch7 events part of reconstructed hits? For each ch7 pulse, the
nearest matched hit's corner within ±400 bins, and that hit's T, X, Y."""
from __future__ import annotations

import json
import numpy as np
from common import OUT, SAMPLES, BIN, helab_env, raw_files, read_raw
from probe_match import match

helab_env()
from helab.convert.pipeline import convert_raw  # noqa: E402
from helab.convert.profile import builtin_profile  # noqa: E402

folders = [SAMPLES / "calib-2026/20260625_Ramsey_weak_trap", SAMPLES / "calib-2026/20260722-tight-trap-freq-meas",
           *[p for p in sorted((SAMPLES / "txy-2026").iterdir()) if p.is_dir()]]
same = diff = 0; diffs = []
hit_near = []; n7 = 0
for folder in folders:
    for f in raw_files(folder):
        data = f.read_bytes()
        if b"\n7," not in data:
            continue
        lines = data.split(b"\n")
        stripped = b"\n".join(l for l in lines if not l.startswith(b"7,"))
        for prof in ("matlab-2019", "plates-2025"):
            p = builtin_profile(prof)
            a = convert_raw(data, p, "numpy"); b = convert_raw(stripped, p, "numpy")
            if a == b:
                same += 1
            else:
                diff += 1; diffs.append((str(f), prof))
        c, t = read_raw(f)
        h = match(c, t)
        corners = np.c_[h["x1"], h["x2"], h["y1"], h["y2"]]
        for i in np.flatnonzero(c == 7):
            t7 = t[i] - t[0]
            n7 += 1
            if len(corners) == 0:
                continue
            d = np.abs(corners - t7).min(axis=1)
            k = int(np.argmin(d))
            hit_near.append(dict(file=f.name, t7_s=t7 * BIN, nearest_corner_bins=float(d[k]),
                                 T=float(h["T"][k]), X=float(h["X"][k]), Y=float(h["Y"][k]),
                                 dt_hit_bins=float(h["T"][k] / BIN - t7)))
near = [r for r in hit_near if r["nearest_corner_bins"] < 400]
res = {"files_x_profiles_identical": same, "differing": diff, "diffs": diffs[:20], "ch7_pulses": n7,
       "ch7_with_a_hit_corner_within_400_bins": len(near),
       "examples": near[:15]}
(OUT / "ch7_conversion.json").write_text(json.dumps(res, indent=1))
print(json.dumps({k: v for k, v in res.items() if k != "examples"}, indent=1))
for r in near[:15]:
    print(r)
