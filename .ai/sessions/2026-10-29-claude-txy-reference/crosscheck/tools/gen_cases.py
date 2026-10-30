"""Generate the synthetic raw cases in crosscheck/cases/<case>/d1.txt (+ case.json).

Run: python3 -I gen_cases.py <cases-dir>. Deterministic. Times are in 25 ps bins; every file
starts (unsorted) with a trigger row "5,B" unless the case says otherwise, B = 13656646605557
(a real trigger time's magnitude). Rows end in CRLF, as the lab's raw files do.

A hit at normalised time t with position dx, dy and sums sx, sy is four pulses:
x1 = t + (sx + dx)/2, x2 = t + (sx - dx)/2, y1 = t + (sy + dy)/2, y2 = t + (sy - dy)/2,
so x1 - x2 = dx and x1 + x2 - y1 - y2 = sx - sy.
"""

from __future__ import annotations

import json
import os
import random
import sys

B = 13656646605557
T0 = 4_000_000_000  # 0.1 s after the trigger: T prints without an exponent
GAP = 100_000  # 2.5 µs between hits: well outside every window


Row = tuple[int, int]


def hit(t: int, dx: int = 0, dy: int = 0, sx: int = 3200, sy: int = 3200) -> list[Row]:
    assert (sx + dx) % 2 == 0 and (sy + dy) % 2 == 0, "keep pulses on integer bins"
    return [
        (0, t + (sx + dx) // 2),
        (1, t + (sx - dx) // 2),
        (2, t + (sy + dy) // 2),
        (3, t + (sy - dy) // 2),
    ]


def trig() -> list[Row]:
    return [(5, 0)]


def sort_rows(rows: list[Row]) -> list[Row]:
    return sorted(rows, key=lambda r: r[1])


def lines(rows: list[Row], *, base: int = B) -> list[bytes]:
    return [f"{c},{t + base}".encode() for c, t in rows]


def crlf(ls: list[bytes], *, trailing: bool = True) -> bytes:
    body = b"\r\n".join(ls)
    return body + (b"\r\n" if trailing and ls else b"")


CASES: dict[str, tuple[str, bytes]] = {}


def case(name: str, desc: str, data: bytes) -> None:
    assert name not in CASES
    CASES[name] = (desc, data)


def std(rows: list[Row]) -> bytes:
    """Trigger first, then the rest sorted by time, CRLF."""
    return crlf(lines(trig() + sort_rows(rows)))


def build() -> None:
    # --- sanity ---------------------------------------------------------------------------
    rows: list[Row] = []
    for i, (dx, dy) in enumerate([(0, 0), (1000, -800), (-2400, 1800), (3000, 3000), (-3000, -3000)]):
        rows += hit(T0 + i * GAP, dx, dy)
    case("basic", "Trigger plus five clean, well-separated hits (centre, off-centre, near edges).", std(rows))

    # --- x2 ambiguity ---------------------------------------------------------------------
    # A: two x2 within the window; the nearer row on the -1 side comes first in the search
    # order (-1,+1,-2,+2...). Both satisfy the y sum check? The kept one is the first found.
    t = T0
    rows = [(0, t + 1600), (1, t + 1600 - 50), (1, t + 1600 + 900)]  # x1, x2a (earlier), x2b
    rows += [(2, t + 1600 - 25), (3, t + 1600 + 25)]  # y sum = 2t+3200 matches x1+x2a only
    t2 = t + GAP  # B: the first-found x2 is the WRONG one (sum check fails), no retry
    x1 = t2 + 1600
    rows += [(0, x1), (1, x1 - 10), (1, x1 + 600), (2, x1 + 280), (3, x1 + 310)]
    # x1+x2(-10) = 2x1-10; y sum = 2x1+590; diff 600 > 400 fails; x2(+600) gives 2x1+600 vs
    # 2x1+590, diff 10 < 400 would pass -> a retry would recover it, MATLAB drops it.
    t3 = t + 2 * GAP  # C: three x2 candidates (how_many_x reaches 2 and breaks)
    x1 = t3 + 1600
    rows += [(0, x1), (1, x1 + 100), (1, x1 - 200), (1, x1 + 300), (2, x1 + 40), (3, x1 + 70)]
    t4 = t + 3 * GAP  # D: x2 earlier and later at the SAME row distance: -1 wins over +1
    x1 = t4 + 1600
    rows += [(2, x1 - 1100), (1, x1 - 500), (0, x1), (1, x1 + 500), (3, x1 + 600)]
    # sorted: y1, x2a (row -1), x1, x2b (row +1), y2; the y sum fits x2a only
    case(
        "ambiguous_x2",
        "x1 with 2-3 x2 candidates: first in search order kept (how_many_x==~1 quirk); "
        "first-found x2 wrong -> hit dropped, the other x2 never retried; -1 before +1.",
        std(rows),
    )

    # --- y ambiguity ----------------------------------------------------------------------
    rows = []
    t = T0  # A: two valid y pairs; first in nested search order (y1 outer, y2 inner) kept
    x1 = t + 1600
    rows += [(0, x1), (1, x1)]  # x sum 2x1
    rows += [(2, x1 - 30), (3, x1 + 30), (2, x1 + 500), (3, x1 - 500)]
    t = T0 + GAP  # B: first y1 in search order has no valid y2; second y1 has
    x1 = t + 1600
    rows += [(0, x1), (1, x1 + 2), (2, x1 - 3000), (2, x1 + 100), (3, x1 - 98)]
    t = T0 + 2 * GAP  # C: one y1 with two valid y2 (second breaks inner loop only)
    x1 = t + 1600
    rows += [(0, x1), (1, x1), (2, x1 + 10), (3, x1 - 10), (3, x1 - 150), (2, x1 + 900)]
    case(
        "ambiguous_y",
        "Two valid y pairs (first in nested y1/y2 search order kept), a y1 with no partner "
        "before one with, one y1 with two y2; `break` leaves only the y2 loop.",
        std(rows),
    )

    # --- tolerances: x window (T_sum 3200 skip vs 3400 check) ----------------------------
    rows = []
    for i, dx in enumerate([3198, 3200, 3202, 3300, 3398, -3200, -3202]):
        rows += hit(T0 + i * GAP, dx, 0)
    case(
        "tol_x_window",
        "|x1-x2| = 3198, 3200 (kept: skip is > T_sum), 3202, 3300, 3398 (dropped by the "
        "T_sum skip although < 3400), and -3200/-3202.",
        std(rows),
    )

    # --- y difference < 3400 strict, y pulses within 3200 of x1 --------------------------
    rows = []
    # with sx=sy and dx=0, y1-x1 = dy/2: the T_sum skip never binds for |dy| < 6400.
    for i, dy in enumerate([3398, 3400, 3402, -3398, -3400]):
        rows += hit(T0 + i * GAP, 0, dy)
    # y pulse more than T_sum from x1 though the y pair itself is fine: dx = 3000 puts x1 at
    # t+3100; dy = -3000 puts y1 at t+100 -> |y1 - x1| = 3000 OK; push sums to break it:
    t = T0 + 5 * GAP  # y1 exactly T_sum from x1: kept
    rows += [(0, t + 3200), (1, t), (2, t), (3, t + 3200)]
    t = T0 + 6 * GAP  # y1 3201 from x1: skipped although the pair and sums would pass
    rows += [(0, t + 3200), (1, t), (2, t - 1), (3, t + 3201)]
    case(
        "tol_y_diff",
        "|y1-y2| = 3398 kept, 3400/3402 dropped (strict <3400); a y1 exactly 3200 bins from "
        "x1 kept, 3201 skipped though the pair is consistent (the window is relative to x1).",
        std(rows),
    )

    # --- x-y sum difference < 400 strict --------------------------------------------------
    rows = []
    for i, (sx, sy) in enumerate([(3200, 2802), (3200, 2800), (3200, 2798), (3200, 3598), (3200, 3600), (3400, 3000), (3398, 3000)]):
        rows += hit(T0 + i * GAP, 0, 0, sx, sy)
    case(
        "tol_sum",
        "x sum - y sum = 398 kept, 400 and 402 dropped, -398 kept, -400 dropped, 400 and 398 "
        "with sx != 3200 (T then uses T_sum, not the real sums).",
        std(rows),
    )

    # --- 2023 dead time on x1 (uniquetol 20000 bins, first of a group, not chained) ------
    rows = []
    base = T0
    offsets = [0, 15000, 30000, 45000]  # not chained: keeps 0 and 30000
    offsets += [200000, 220000, 240000, 240001, 260001, 260002]  # inclusive at 20000
    offsets += [400000, 419999]  # 19999 apart: second dropped
    for k, off in enumerate(offsets):
        rows += hit(base + off, (k % 5 - 2) * 400, (k % 3 - 1) * 400)
    # duplicates: two x1 at the same time, each with its own x2/y (so both could match)
    t = base + 600000
    rows += [(0, t + 1600), (0, t + 1600), (1, t + 1500), (1, t + 1700), (2, t + 1600), (3, t + 1600), (2, t + 1590), (3, t + 1610)]
    case(
        "dead_time_x1",
        "x1 pulses 15000/20000/20001/19999 bins apart and two at the same time, each with its "
        "own partners: 2019 matches all; 2023's uniquetol keeps the first of each 20000-bin "
        "group (not chained, inclusive), ties keep the first row.",
        std(rows),
    )

    # --- empty and trigger-only ------------------------------------------------------------
    case("empty", "A 0-byte file: MATLAB errors at t_zero = dld_output_raw(1,2).", b"")
    case("blank_only", "A file holding one CRLF: textscan gives 0 rows; MATLAB errors as for empty.", b"\r\n")
    case("trigger_only", "One trigger row: no hits (2019 writes no file; 2023 an empty one).", crlf(lines(trig())))
    case(
        "no_hits",
        "Trigger plus corner pulses that never form a hit: x1 with no x2, x2/y alone.",
        std([(0, T0), (2, T0 + 10), (3, T0 + 20), (1, T0 + GAP), (2, T0 + 2 * GAP)]),
    )

    # --- phantom row (MATLAB grows the NaN prealloc with zeros) ---------------------------
    case(
        "phantom_lone_pair",
        "Trigger + x1 + x2 and no y: NaN(floor(3/4)=0,5) grows with ZEROS when the x pair is "
        "stored, so the failed row keeps T=0 and survives the NaN filter: a hit at T=0, Y=0.",
        std([(0, T0 + 1600), (1, T0 + 1400)]),
    )
    case(
        "phantom_after_hit",
        "Trigger + one hit + a lone x pair after it (N=7, prealloc 1 row): the lone pair grows "
        "row 2 with zeros -> a phantom T=0 row.",
        std(hit(T0, 400, 200) + [(0, T0 + GAP + 1600), (1, T0 + GAP + 1000)]),
    )
    case(
        "phantom_none",
        "Same as phantom_after_hit but the lone pair comes BEFORE the hit: the row is reused "
        "by the hit, no phantom.",
        std([(0, T0 + 1600), (1, T0 + 1000)] + hit(T0 + GAP, 400, 200)),
    )
    rows = []
    for i in range(3):
        rows += hit(T0 + i * GAP, 100 * i, -100 * i)
    rows += [(0, T0 + 3 * GAP + 1600), (1, T0 + 3 * GAP + 1500), (2, T0 + 3 * GAP + 1600)]
    case(
        "phantom_multi",
        "Trigger + 3 hits + x1,x2,y1 (N=16, prealloc 4 rows, 3 successes): row 4 is "
        "preallocated NaN, so no phantom (contrast with phantom_after_hit).",
        std(rows),
    )
    rows = []
    for i in range(3):
        rows += hit(T0 + i * GAP, 100 * i, -100 * i)
    rows += [(0, T0 + 3 * GAP + 1600), (1, T0 + 3 * GAP + 1500)]
    case(
        "phantom_multi_cut",
        "phantom_multi without the lone y1 (N=15, prealloc 3, 3 successes): the lone pair "
        "grows row 4 with zeros -> a phantom T=0 row.",
        std(rows),
    )

    # --- truncated / malformed lines -------------------------------------------------------
    rows = trig() + sort_rows(hit(T0, 200, -200) + hit(T0 + GAP, -600, 400))
    ls = lines(rows)
    case("no_trailing_newline", "Two hits, last line without CRLF.", crlf(ls, trailing=False))
    case("lf_endings", "Two hits with LF line endings.", b"\n".join(ls) + b"\n")
    case(
        "blank_lines",
        "Two hits with blank lines in the middle and at the end (textscan skips them).",
        b"\r\n".join(ls[:3] + [b""] + ls[3:6] + [b"", b""] + ls[6:]) + b"\r\n\r\n",
    )
    last_c, last_t = rows[-1]
    full = f"{last_c},{last_t + B}".encode()
    case(
        "trunc_digits",
        "Last line cut mid-number (still being written): its time loses digits, sorts to "
        "near the trigger, and the last hit loses a pulse.",
        crlf(ls[:-1], trailing=True) + full[: len(full) - 6],
    )
    case(
        "trunc_comma",
        "Last line is '<ch>,' (time missing): textscan gives NaN, which sorts last.",
        crlf(ls[:-1]) + f"{last_c},".encode(),
    )
    case(
        "trunc_channel",
        "Last line is '<ch>' only: textscan gives (ch, NaN).",
        crlf(ls[:-1]) + f"{last_c}".encode(),
    )
    case("trunc_cr", "Last line ends in a lone CR.", crlf(ls[:-1]) + full + b"\r")
    mid = len(ls) // 2
    case(
        "nan_time_mid",
        "A line '0' (no time) in the middle: (0, NaN) sorts last and counts in N.",
        crlf(ls[:mid] + [b"0"] + ls[mid:]),
    )
    case(
        "garbage_mid",
        "A non-numeric line in the middle: textscan (ReturnOnError) stops there, so only the "
        "rows before it are read.",
        crlf(ls[:mid] + [b"x,123"] + ls[mid:]),
    )

    case(
        "tzero_nan",
        "The first line is '5,' (no time): t_zero is NaN, every time becomes NaN, no hits.",
        b"5,\r\n" + crlf(lines(sort_rows(hit(T0, 0, 0) + hit(T0 + GAP, 400, 400)))),
    )

    # --- hits at the start and end of the file --------------------------------------------
    rows = trig() + [(1, -2000), (0, -1500), (2, -1800), (3, -1700)]  # x2 sorts first
    rows += hit(T0, 0, 0)
    rows += [(2, 2 * T0 - 3), (1, 2 * T0 - 2), (3, 2 * T0 - 1), (0, 2 * T0)]  # x1 is the last row
    case(
        "hits_at_edges",
        "A hit before the trigger (negative T) whose x2 is the first sorted row (reachable at "
        "count+dummy = 1), and a hit whose x1 is the last row (search runs past N).",
        crlf(lines([rows[0]] + sort_rows(rows[1:]))),
    )
    rows = [(0, -5000), (1, -5000 + 300), (2, -5000 + 150), (3, -5000 + 150)]
    rows += hit(T0, 0, 0)
    case(
        "first_sorted_x1",
        "The earliest pulse is an x1 (before the trigger): sorted row 1 is skipped as 'the "
        "trigger' though it is a corner, so its hit is lost.",
        crlf(lines(trig() + sort_rows(rows))),
    )

    # --- unsorted input, t_zero from the unsorted first row -------------------------------
    rng = random.Random(7)
    rows = []
    for i in range(6):
        rows += hit(T0 + i * GAP, rng.randrange(-30, 30) * 100, rng.randrange(-30, 30) * 100)
    pre = [(5, -6_000_000 + 37 * k) for k in range(5)]  # earlier ch5 rows, as in 2022 d1
    body = pre + rows
    rng.shuffle(body)
    case(
        "unsorted",
        "Trigger first, then pulses in shuffled order including five earlier channel-5 rows: "
        "t_zero is row 1 (the trigger), not the minimum.",
        crlf(lines(trig() + body)),
    )
    rows = []
    for i in range(3):
        rows += hit(T0 + i * GAP, 200 * i, -300 * i)
    first = rows[5]  # a corner pulse first (t_zero = its time)
    rest = trig() + rows[:5] + rows[6:]
    case(
        "tzero_not_trigger",
        "The first line is a corner pulse (x2 of hit 2), the trigger second: t_zero is that "
        "pulse's time, so every T shifts by it (some T negative).",
        crlf(lines([first] + sort_rows(rest))),
    )

    # --- equal times ------------------------------------------------------------------------
    t = T0
    rows = [(0, t + 1600), (1, t + 1600), (1, t + 1600), (2, t + 1600), (3, t + 1600), (2, t + 1600), (3, t + 1600)]
    # T ties in the output: two hits at the same t (equal T), A's x1 first (searched config)
    t2 = T0 + GAP
    rows += hit(t2, -600, 2000) + hit(t2, 2400, 2200)
    t3 = T0 + 2 * GAP  # generation order != T order: B's x1 is earlier, its T later
    rows += hit(t3, 2400, 1200) + hit(t3 + 500, 400, -1200)
    case(
        "equal_times",
        "Pulses at identical times (stable sort keeps file order), two hits with equal T "
        "(final sort is stable), and hits generated out of T order (final sort reorders).",
        std(rows),
    )

    # --- search window --------------------------------------------------------------------
    rows = []
    t = T0  # A: an x2 more than T_sum away sits inside the window, the real x2 beyond it
    x1 = t + 1600
    rows += [(0, x1), (1, x1 - 3300), (1, x1 + 3250), (1, x1 + 900), (2, x1 + 450), (3, x1 + 450)]
    t = T0 + GAP  # B: 18 MCP pulses between x1 and x2: x2 at row +19 is outside the window
    x1 = t + 1600
    rows += [(0, x1)] + [(4, x1 + 1 + k) for k in range(18)] + [(1, x1 + 100), (2, x1 + 50), (3, x1 + 50)]
    t = T0 + 2 * GAP  # C: 17 MCP pulses: x2 at row +18 is the last row searched
    x1 = t + 1600
    rows += [(0, x1)] + [(4, x1 + 1 + k) for k in range(17)] + [(1, x1 + 100), (2, x1 - 50), (3, x1 - 50)]
    t = T0 + 3 * GAP  # D: 18 pulses BEFORE x1: x2 at row -19, outside; -18 inside (E)
    x1 = t + 1600
    rows += [(1, x1 - 200)] + [(4, x1 - 190 + k) for k in range(18)] + [(0, x1), (2, x1 - 100), (3, x1 - 100)]
    t = T0 + 4 * GAP
    x1 = t + 1600
    rows += [(1, x1 - 200)] + [(4, x1 - 190 + k) for k in range(17)] + [(0, x1), (2, x1 - 100), (3, x1 - 100)]
    case(
        "search_window",
        "An x2 > T_sum away inside the 36-row window is skipped and the search goes on; "
        "partners at row +-19 are out of reach, at +-18 found (offsets -1,+1,...,-18,+18).",
        std(rows),
    )

    # --- used pulses are NaN'd; x2 of a failed match stays free --------------------------
    rows = []
    t = T0  # two x1 sharing one x2: the first takes it, the second finds nothing
    rows += [(0, t + 1600), (0, t + 1700), (1, t + 1650), (2, t + 1625), (3, t + 1625)]
    t = T0 + GAP  # x1a finds x2 but no y; x1b then uses the same x2 with y
    # x1a sum 2t+3250, x1b sum 2t+3310, y sum 2t+3680: a fails (430), b passes (370)
    rows += [(0, t + 1600), (1, t + 1650), (0, t + 1660), (2, t + 1840), (3, t + 1840)]
    case(
        "used_pulses",
        "Two x1 sharing one x2 (the first takes it; the pulse is then NaN for the second); an "
        "x2 whose x1 found no y stays free for the next x1.",
        std(rows),
    )

    # --- channel 4 present / absent, other channels ----------------------------------------
    rows = []
    for i in range(4):
        rows += hit(T0 + i * GAP, 500 * i - 700, 300 - 200 * i)
        rows += [(4, T0 + i * GAP + 1600 - 3)]
    case("mcp_present", "Four hits each with an MCP (channel 4) pulse: MCP rows sit in the window but are ignored.", std(rows))
    rows = []
    for i in range(4):
        rows += hit(T0 + i * GAP, 500 * i - 700, 300 - 200 * i)
    case("mcp_absent", "The same four hits without MCP pulses (output must equal mcp_present's).", std(rows))
    rows = []
    for i in range(3):
        rows += hit(T0 + i * GAP, 100, 100) + [(6, T0 + i * GAP + 1600), (7, T0 + i * GAP + 1601)]
    case("other_channels", "Channels 6 and 7 among the hits (ignored, but occupy window rows).", std(rows))

    # --- number formatting ------------------------------------------------------------------
    rows = []
    for i, (dx, dy) in enumerate([(2, -2), (0, 0), (-4, 6), (1, 1), (3, -1)]):
        rows += hit(1000 + i * 5000, dx, dy, 3200 + (dx % 2), 3200 + (dy % 2))
    case(
        "small_values",
        "Hits ~25 ns to 0.5 us after the trigger and |X|,|Y| of a few bins: T and X/Y print "
        "with e-05/e-06/e-07 exponents; X or Y exactly 0; odd sums give quarter-bin T.",
        std(rows),
    )
    rows = []
    for i, tt in enumerate([4_000_000_001, 39_999_999_999, 80_000_000_003, 400_000_000_007]):
        rows += hit(tt, 2 * i + 1 - 2 * (i % 2) * 3, -(2 * i + 1), 3201, 3199)
    case(
        "large_times",
        "Hits at 0.1, 1.0, 2.0 and 10 s after the trigger: T >= 1 prints 8 significant "
        "digits (rounding at the 8th digit), quarter bins.",
        std(rows),
    )

    # --- many triggers at the start (as in real files) -------------------------------------
    rows = [(5, 37 * k + 400) for k in range(11)]
    for i in range(3):
        rows += hit(2000 + i * 4000, -1000 * i, 500 * i)
    case(
        "trigger_burst",
        "Twelve channel-5 rows within 1 us of the trigger (as in 2024-11 d1111) and hits "
        "starting 50 ns later, inside the trigger rows' window.",
        std(rows),
    )


def main() -> None:
    out = sys.argv[1]
    build()
    index = {}
    for name, (desc, data) in CASES.items():
        d = os.path.join(out, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "d1.txt"), "wb") as fh:
            fh.write(data)
        index[name] = desc
    with open(os.path.join(out, "index.json"), "w") as fh:
        json.dump(index, fh, indent=1)
        fh.write("\n")
    print(len(CASES), "cases")


if __name__ == "__main__":
    main()
