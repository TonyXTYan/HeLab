"""Which converter wrote each MATLAB TXY? The 2023 lab edit drops x1 pulses within 0.5 us of an
earlier kept x1, so its hits almost never come closer than ~0.4 us in T; the 2019 converter has
many such pairs in dense clouds. Also flags malformed lines (not 3 fields) and non-monotonic T.
Scans every d_txy_forc*.txt under txy-2026 and calib-2026. Writes out/txy_origin_scan.csv."""
import re
import numpy as np
import pandas as pd
from common import OUT, SAMPLES, shot_number

rows = []
for root in (SAMPLES / "txy-2026", SAMPLES / "calib-2026"):
    for f in sorted(root.rglob("d_txy_forc*.txt")):
        text = f.read_bytes()
        lines = text.split(b"\n")
        if lines and lines[-1] == b"":
            lines = lines[:-1]
        bad = [i + 1 for i, l in enumerate(lines) if l.count(b",") != 2]
        good = [l for l in lines if l.count(b",") == 2]
        T = np.array([float(l.split(b",")[0]) for l in good]) if good else np.zeros(0)
        dT = np.diff(T)
        close = int((dT < 0.4e-6).sum())
        dense = int((dT < 5e-6).sum())  # pairs in dense parts
        rows.append(dict(folder=str(f.parent.relative_to(SAMPLES)), shot=shot_number(f), lines=len(lines), bad_lines=len(bad),
                         first_bad=bad[0] if bad else None, nonmonotonic=int((dT < 0).sum()), close_pairs=close,
                         dense_pairs=dense, close_share=close / dense if dense else np.nan))
df = pd.DataFrame(rows)
df["origin_guess"] = np.where(df.dense_pairs < 200, "too sparse", np.where(df.close_share < 0.02, "2023-edit-like", "2019-like"))
df.to_csv(OUT / "txy_origin_scan.csv", index=False)
pd.set_option("display.width", 200)
print(df.groupby("folder").agg(files=("shot", "size"), bad=("bad_lines", lambda x: (x > 0).sum()), nonmono=("nonmonotonic", lambda x: (x > 0).sum()),
                               e23=("origin_guess", lambda x: (x == "2023-edit-like").sum()), e19=("origin_guess", lambda x: (x == "2019-like").sum()),
                               sparse=("origin_guess", lambda x: (x == "too sparse").sum()), close_share_med=("close_share", "median")))
print(df[(df.bad_lines > 0) | (df.nonmonotonic > 0) | (df.origin_guess == "2023-edit-like")].to_string())
