"""A copy of HeLab's reference 4-corner match (helab/convert/backends/reference.py, matlab-2019
semantics: stable sort, t_zero from the first raw row, first sorted row skipped, nearest-first
search, x2 kept on ambiguity, used pulses marked) that ALSO returns the matched corner times, so
time sums and positions can be studied per hit. The phantom overflow row is not reproduced (it is
at most one hit per file at T = 0 and is dropped here). Validated against HeLab's converter by
validate_probe.py.

match(c, t, window=3200, x_limit=3400, y_limit=3400, xy_limit=400, depth=36, tsum_x=3200, tsum_y=3200,
      x2_retry=False)
 -> dict of arrays: x1, x2, y1, y2 (bins after t_zero), T (s), X, Y (m, matlab-2019 v_perp),
    i7near (unused here)
"""
from __future__ import annotations

import numpy as np

BIN = 25e-12
V = 5.2632e5


def offsets(depth: int) -> list[int]:
    out = []
    for k in range(1, depth // 2 + 1):
        out += [-k, k]
    return out


def match(c: np.ndarray, t: np.ndarray, window: float = 3200, x_limit: float = 3400, y_limit: float = 3400,
          xy_limit: float = 400, depth: int = 36, tsum_x: float = 3200, tsum_y: float = 3200,
          x2_retry: bool = False, channels=(0, 1, 2, 3)) -> dict[str, np.ndarray]:
    order = np.argsort(t, kind="stable")
    ch = c[order].astype(float).tolist()
    tt = (t[order] - t[0]).astype(float).tolist()
    n = len(tt)
    cx1, cx2, cy1, cy2 = channels
    search = offsets(depth)
    rows = []
    for i in range(1, n):
        if ch[i] != cx1:
            continue
        x1 = tt[i]
        cands = []
        for d in search:
            j = i + d
            if j < 0 or j >= n or abs(tt[j] - x1) > window:
                continue
            if ch[j] == cx2 and abs(x1 - tt[j]) < x_limit:
                cands.append(j)
                if len(cands) > 1:
                    break
        if not cands:
            continue
        tried = cands if x2_retry else cands[:1]
        for jx in tried:
            x2 = tt[jx]
            found = None
            for d2 in search:
                j2 = i + d2
                if j2 < 0 or j2 >= n or abs(tt[j2] - x1) > window or ch[j2] != cy1:
                    continue
                y1 = tt[j2]
                for d3 in search:
                    j3 = i + d3
                    if j3 < 0 or j3 >= n or abs(tt[j3] - x1) > window or ch[j3] != cy2:
                        continue
                    y2 = tt[j3]
                    if abs(y1 - y2) < y_limit and abs(x1 + x2 - y1 - y2) < xy_limit:
                        if found is None:
                            found = (j2, j3)
                        else:
                            break
                # MATLAB: a second y pair breaks only the inner loop; the first found is kept and
                # the outer loop goes on, but later matches only count (how_many_y) and the
                # values written are the LAST matching pair's, then pulses marked. Reproduce:
            if found is None:
                continue
            # Re-run MATLAB's exact assignment order: every matching (y1, y2) pair before the inner
            # break overwrites y1/y2 and marks; the reference writes the first pair of each y1 loop
            # only while how_many_y <= 1, i.e. the first pair overall. So the first pair is kept.
            j2, j3 = found
            rows.append((x1, x2, tt[j2], tt[j3]))
            ch[i] = ch[jx] = ch[j2] = ch[j3] = np.nan
            break
    a = np.array(rows, dtype=float).reshape(-1, 4)
    x1, x2, y1, y2 = a.T
    tx = 0.5 * (x1 + x2 - tsum_x)
    ty = 0.5 * (y1 + y2 - tsum_y)
    T = (tx + ty) / 2 * BIN
    X = ((x1 - tx) - (x2 - tx)) * V * BIN
    Y = ((y1 - ty) - (y2 - ty)) * V * BIN
    o = np.argsort(T, kind="stable")
    return {"x1": x1[o], "x2": x2[o], "y1": y1[o], "y2": y2[o], "T": T[o], "X": X[o], "Y": Y[o]}
