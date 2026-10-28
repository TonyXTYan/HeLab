"""Lens's independent reading of the MATLAB converter, used only to cross-check.

NOT the port (that is helab/convert/, by the builder). Written from the MATLAB sources and the
probes in crosscheck/matlab-walkthrough.md, without reading the builder's code, so the two can
disagree. Standard library only; run with `python3 -I oracle.py <raw> <variant> [out]`.

variant: "2019" (legacy/tdc_autoconverter) or "2023" (legacy/DLD_front_panel ... lab edit).
"""

from __future__ import annotations

import math
import re
import sys

BIN_TIME = 25e-12
V_PERP_X = 5.2632e005
V_PERP_Y = 5.2632e005
TSUM = 3200
TOL = 200
SEARCH_NO = 36
NAN = float("nan")


class MatlabError(Exception):
    """MATLAB itself errors here (e.g. index out of bounds on an empty file)."""


# ---- textscan('%f64%f64', Delimiter ',', ReturnOnError) -- see walkthrough §1 -------------
_NUM = re.compile(rb"[ \t]*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|[-+]?(?:NaN|Inf|nan|inf))")


def read_raw(data: bytes) -> list[list[float]]:
    """Mimic textscan for the inputs probed (walkthrough §1); unprobed inputs may differ."""
    fields: list[float] = []
    pos = 0
    n = len(data)
    # textscan reads a flat stream of fields; a delimiter or EOL ends a field, empty → NaN.
    # Blank lines are skipped; a line with fewer fields leaves NaN for the missing one.
    col = 0
    while True:
        # skip blank lines / EOLs only at the start of a row
        if col == 0:
            while pos < n and data[pos : pos + 1] in (b"\r", b"\n"):
                pos += 1
            if pos >= n:
                break
        m = _NUM.match(data, pos)
        if m:
            fields.append(float(m.group(1)))
            pos = m.end()
            while pos < n and data[pos : pos + 1] in (b" ", b"\t"):
                pos += 1
        else:
            # empty field? only if next char is a delimiter or EOL / EOF
            if pos >= n or data[pos : pos + 1] in (b",", b"\r", b"\n"):
                if col == 0 and pos >= n:
                    break
                fields.append(NAN)
            else:
                # conversion error: ReturnOnError stops; a partial row is dropped? (probe: the
                # stream "0,12x4" kept (0,12)), so a number prefix is taken above already
                break
        col ^= 1
        if pos >= n:
            break
        c = data[pos : pos + 1]
        if c == b",":
            pos += 1
            if col == 0 and pos >= n:
                break
            continue
        if c in (b"\r", b"\n"):
            # EOL: if we are mid-row, the second field is empty → NaN
            if col == 1:
                fields.append(NAN)
                col = 0
            continue
        # garbage right after a number (e.g. "12x4"): stop
        break
    if col == 1:
        fields.append(NAN)
    return [[fields[i], fields[i + 1]] for i in range(0, len(fields) - 1, 2)]


def _matlab_sort_key_indices(vals: list[float]) -> list[int]:
    """MATLAB sort ascending, stable, NaN last."""
    return sorted(range(len(vals)), key=lambda i: (math.isnan(vals[i]), 0.0 if math.isnan(vals[i]) else vals[i]))


def uniquetol_first(vals: list[float], tol: float) -> list[int]:
    """Indices kept by uniquetol(v, tol, 'DataScale', 1): sorted, group = within tol of the
    group's first (not chained), keep the first (lowest index among ties). Probed."""
    order = _matlab_sort_key_indices(vals)
    kept: list[int] = []
    ref = None
    for i in order:
        v = vals[i]
        if ref is None or not (abs(v - ref) <= tol):
            kept.append(i)
            ref = v
    return kept


def reconstruct(raw: list[list[float]], variant: str) -> list[list[float]]:
    num = len(raw)
    if num == 0:
        raise MatlabError("Index in position 1 exceeds array bounds (t_zero on an empty file)")
    order = _matlab_sort_key_indices([r[1] for r in raw])
    srt = [[raw[i][0], raw[i][1]] for i in order]
    t_zero = raw[0][1]  # the UNSORTED first row
    for r in srt:
        r[1] = r[1] - t_zero

    if variant == "2023":
        x1_rows = [k for k, r in enumerate(srt) if r[0] == 0]
        x1_vec = [srt[k][1] for k in x1_rows]
        keep = set(uniquetol_first(x1_vec, 0.5e-6 / BIN_TIME))
        for j, k in enumerate(x1_rows):
            if j not in keep:
                srt[k][0] = NAN
        t_sum_x, t_sum_y = 3390, 3275
    else:
        t_sum_x = t_sum_y = TSUM

    T_sum = TSUM
    tol_throw = T_sum + TOL
    tol_keep = T_sum + TOL
    two_keep = 2 * TOL
    prealloc = num // 4
    out: list[list[float]] = [[NAN] * 5 for _ in range(prealloc)]
    which_row = 0  # MATLAB 1-based row; 0 = none

    def put(row: int, colv: dict[int, float]) -> None:
        while len(out) < row:
            out.append([0.0] * 5)  # MATLAB grows with zeros
        for c, v in colv.items():
            out[row - 1][c] = v

    N = num
    for count in range(2, N + 1):  # 1-based
        if srt[count - 1][0] != 0:
            continue
        x1_val = srt[count - 1][1]
        dummy = 0
        how_many_x = 0
        x1 = x2 = tx = 0.0
        x2_index = 0
        for count2 in range(1, SEARCH_NO + 1):
            dummy = dummy + count2 * (-1) ** count2
            r = count + dummy
            if r <= 0 or r > N:
                continue
            if abs(srt[r - 1][1] - x1_val) > T_sum:
                continue
            if srt[r - 1][0] == 1:
                x2_val = srt[r - 1][1]
                if abs(x1_val - x2_val) < tol_throw:
                    how_many_x += 1
                    if how_many_x > 1:
                        break
                    x1 = x1_val
                    x2 = x2_val
                    which_row += 1
                    tx = 0.5 * (x1 + x2 - t_sum_x)
                    if variant == "2023":
                        put(which_row, {1: x1, 2: x2})
                    else:
                        put(which_row, {1: x1 - tx, 2: x2 - tx})
                    x2_index = r
        if how_many_x == 0:  # `how_many_x == ~1`
            continue
        how_many_y = 0
        dummy2 = 0
        for count3 in range(1, SEARCH_NO + 1):
            dummy2 = dummy2 + count3 * (-1) ** count3
            r2 = count + dummy2
            if r2 <= 0 or r2 > N:
                continue
            if abs(srt[r2 - 1][1] - x1_val) > T_sum:
                continue
            if srt[r2 - 1][0] == 2:
                y1_val = srt[r2 - 1][1]
                dummy3 = 0
                for count4 in range(1, SEARCH_NO + 1):
                    dummy3 = dummy3 + count4 * (-1) ** count4
                    r3 = count + dummy3
                    if r3 <= 0 or r3 > N:
                        continue
                    if abs(srt[r3 - 1][1] - x1_val) > T_sum:
                        continue
                    if srt[r3 - 1][0] == 3:
                        y2_val = srt[r3 - 1][1]
                        if abs(y1_val - y2_val) < tol_keep and abs(x1 + x2 - y1_val - y2_val) < two_keep:
                            how_many_y += 1
                            if how_many_y > 1:
                                break
                            y1 = y1_val
                            y2 = y2_val
                            ty = 0.5 * (y1 + y2 - t_sum_y)
                            t = (tx + ty) / 2
                            if variant == "2023":
                                put(which_row, {3: y1, 4: y2, 0: t})
                            else:
                                put(which_row, {3: y1 - ty, 4: y2 - ty, 0: t})
                            srt[count - 1][0] = NAN
                            srt[x2_index - 1][0] = NAN
                            srt[r2 - 1][0] = NAN
                            srt[r3 - 1][0] = NAN
        if how_many_y == 0:
            which_row -= 1

    good = [r for r in out if not math.isnan(r[0])]
    tri = [[r[0] * BIN_TIME, (r[1] - r[2]) * V_PERP_X * BIN_TIME, (r[3] - r[4]) * V_PERP_Y * BIN_TIME] for r in good]
    idx = _matlab_sort_key_indices([r[0] for r in tri])
    return [tri[i] for i in idx]


def fmt(v: float) -> str:
    if math.isnan(v):
        return "NaN"
    if math.isinf(v):
        return "Inf" if v > 0 else "-Inf"
    return "%.8g" % v


def dlmwrite_bytes(rows: list[list[float]]) -> bytes:
    return "".join(",".join(fmt(v) for v in r) + "\n" for r in rows).encode()


def main() -> None:
    raw_path, variant = sys.argv[1], sys.argv[2]
    with open(raw_path, "rb") as fh:
        data = fh.read()
    try:
        rows = reconstruct(read_raw(data), variant)
    except MatlabError as e:
        print("ERROR", e)
        return
    out = dlmwrite_bytes(rows)
    if len(sys.argv) > 3:
        if variant == "2019" and not rows:
            print("NOFILE")
            return
        with open(sys.argv[3], "wb") as fh:
            fh.write(out)
    print(len(rows))


if __name__ == "__main__":
    main()
