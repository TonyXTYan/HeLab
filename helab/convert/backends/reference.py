"""The reference backend: a plain-Python port of the running path of MATLAB's
``dld_read_5channels_reconst_multi_imp(file, 1, 0, 1, 0)``, loop for loop. Readable, not fast:
every other backend is checked against it.

Line numbers ``L…`` are those of the 2019 file,
``legacy/tdc_autoconverter/lib/dld_read_5channels_reconst_multi_imp.m``; ``L2023:…`` those of the
front panel's 2023 copy. MATLAB's rows are 1-based; here ``i`` is the 0-based row ``count − 1``.
The quirks are reproduced on purpose (the profile names them; notes.md lists them):

- t_zero is the first row of the file as read, before sorting (L62), whatever its channel;
- the first row after sorting is skipped as "the trigger" (L449);
- the search visits rows −1, +1, −2, +2, … (L457) and skips rows more than T_sum from x1 (L465);
- ``how_many_x == ~1`` is ``how_many_x == 0`` (L498): a second x2 candidate only ends the search
  and the first is kept; the other x2 is never retried when y then fails;
- a second y pair only breaks the inner y2 loop (L546); the first pair is kept;
- used pulses get channel NaN (L557–560), so later x1 rows skip them;
- the output matrix is preallocated with floor(rows/4) NaN rows (L444) and grows with zeros past
  that, so an x1 with an x2 but no y left in a grown row survives as a hit with T = 0, Y = 0;
- the hits are sorted by T at the end (L1528–1530), stably.

Qt-free; standard library and NumPy only.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from helab.convert.profile import DetectorProfile
from helab.convert.raw import RawPulses
from helab.convert.reconstruct import Backend, Hits, NoRowsError, register_backend

NAN = math.nan


@dataclass
class MatchStats:
    """Counts kept by ``reconstruct_reference`` when asked, for the x2-handling report.

    ``x2_ambiguous``: x1 rows where the search met a second x2 candidate (and stopped there).
    ``y_missing``: x1 rows with an x2 but no y pair. ``x2_retry_would_match``: of those, the ones
    where the second x2 candidate would have found a y pair (checked without using it, so later
    matches are as MATLAB's: an estimate of what a retry would recover). ``y_ambiguous``: hits
    whose y search met a second pair."""
    x1_rows: int = 0
    x2_missing: int = 0
    x2_ambiguous: int = 0
    y_missing: int = 0
    y_missing_x2_ambiguous: int = 0
    x2_retry_would_match: int = 0
    y_ambiguous: int = 0
    hits: int = 0
    overflow_rows: int = 0
    dead_time_dropped: int = 0


def offsets(depth: int) -> list[int]:
    """The rows searched around x1: dummy = dummy + count2·(−1)^count2 (L456–457): −1, +1, −2, …"""
    out, dummy = [], 0
    for count2 in range(1, depth + 1):
        dummy += count2 * (-1) ** count2
        out.append(dummy)
    return out


def sort_order(values: list[float]) -> list[int]:
    """MATLAB's ``[~, I] = sort(v)``: ascending, stable, NaN last."""
    return sorted(range(len(values)), key=lambda k: (True, 0.0) if math.isnan(values[k]) else (False, values[k]))


def uniquetol_keep(values: list[float], tol: float) -> list[bool]:
    """Which entries ``uniquetol(values, tol, 'DataScale', 1)`` returns (its IA), for values
    already sorted ascending with NaN last: the first of each group, a group being the values
    within ``tol`` (≤) of its first one (not chained); every NaN is its own group. Measured with
    MATLAB R2025b (notes.md)."""
    keep = [False] * len(values)
    first = NAN
    for k, value in enumerate(values):
        if math.isnan(value) or math.isnan(first) or not abs(value - first) <= tol:
            keep[k] = True
            first = value
    return keep


def reconstruct_reference(pulses: RawPulses, profile: DetectorProfile, stats: MatchStats | None = None) -> Hits:
    raw_channels = pulses.channels.tolist()
    raw_times = pulses.times.tolist()
    n = len(raw_times)  # num_trigs, number_detections (L55, L429)
    if n == 0 and profile.subtract_time_zero:
        raise NoRowsError("The raw file has no rows (MATLAB fails at t_zero, L62)")

    # L58–60: sort the rows by time.
    order = sort_order(raw_times)
    ch = [raw_channels[k] for k in order]
    t = [raw_times[k] for k in order]

    # L62–66: subtract the first raw row's time (not the earliest).
    if profile.subtract_time_zero:
        t_zero = raw_times[0]
        t = [value - t_zero for value in t]

    # L2023:429–458: the dead-time cut, each corner from the rows before any cut.
    snapshot = list(ch)
    for channel, dead_time in ((profile.channel_x1, profile.dead_time_x1), (profile.channel_x2, profile.dead_time_x2),
                               (profile.channel_y1, profile.dead_time_y1), (profile.channel_y2, profile.dead_time_y2)):
        if dead_time > 0:
            rows = [k for k in range(n) if snapshot[k] == channel]
            keep = uniquetol_keep([t[k] for k in rows], dead_time / profile.bin_time)
            for k, first_of_group in zip(rows, keep):
                if not first_of_group:
                    ch[k] = NAN
                    if stats is not None:
                        stats.dead_time_dropped += 1

    search = offsets(profile.search_depth)
    window = profile.search_window                                       # T_sum (L465)
    x_limit = profile.match_time_sum_x + profile.match_tolerance_x       # T_sum_tol_throw (L440)
    y_limit = profile.match_time_sum_y + profile.match_tolerance_y       # T_sum_tol_keep (L441)
    xy_limit = profile.xy_sum_tolerance                                  # two_tolerance_keep (L442)
    centred = profile.position_formula == "centred"
    c_x1, c_x2, c_y1, c_y2 = profile.channel_x1, profile.channel_x2, profile.channel_y1, profile.channel_y2

    # L444: five_channel_output_4corners = NaN(floor(number_detections/4), 5): t, x1, x2, y1, y2.
    out = [[NAN] * 5 for _ in range(n // 4)]
    which_row = 0
    x1 = x2 = tx = 0.0
    x2_index = 0

    grown = 0.0 if profile.matlab_overflow_row else NAN

    def put(row: int, column: int, value: float) -> None:
        # MATLAB grows a matrix assigned past its end, filling the new rows with zeros.
        while len(out) < row:
            out.append([grown] * 5)
            if stats is not None:
                stats.overflow_rows += 1
        out[row - 1][column - 1] = value

    first = 1 if profile.skip_first_sorted_row else 0
    for i in range(first, n):                                            # L449: for count = 2:number_detections
        if ch[i] != c_x1:                                                # L450
            continue
        x1_val = t[i]                                                    # L451
        how_many_x = 0
        second_x2: float | None = None
        if stats is not None:
            stats.x1_rows += 1

        for dummy in search:                                             # L456–457
            j = i + dummy
            if j < 0 or j >= n:                                          # L459–464
                continue
            if abs(t[j] - x1_val) > window:                              # L465
                continue
            if ch[j] == c_x2:                                            # L474
                x2_val = t[j]
                if abs(x1_val - x2_val) < x_limit:                       # L477
                    how_many_x += 1
                    if how_many_x > 1:                                   # L479: breaks on a second x2
                        second_x2 = x2_val
                        break
                    x1 = x1_val
                    x2 = x2_val
                    which_row += 1
                    tx = 0.5 * (x1 + x2 - profile.time_sum_t_x)          # L485 (L2023:519 T_sum_x)
                    put(which_row, 2, x1 - tx if centred else x1)        # L486 (L2023:520)
                    put(which_row, 3, x2 - tx if centred else x2)        # L487 (L2023:521)
                    x2_index = j                                         # L490

        if how_many_x == 0:                                              # L498: how_many_x == ~1
            if stats is not None:
                stats.x2_missing += 1
            continue
        if stats is not None and how_many_x > 1:
            stats.x2_ambiguous += 1

        how_many_y = 0
        for dummy2 in search:                                            # L505–506
            j2 = i + dummy2
            if j2 < 0 or j2 >= n:                                        # L509–514
                continue
            if abs(t[j2] - x1_val) > window:                             # L515
                continue
            if ch[j2] != c_y1:                                           # L524
                continue
            y1_val = t[j2]
            for dummy3 in search:                                        # L529–530
                j3 = i + dummy3                                          # around x1, not y1
                if j3 < 0 or j3 >= n:                                    # L532–537
                    continue
                if abs(t[j3] - x1_val) > window:                         # L538
                    continue
                if ch[j3] != c_y2:                                       # L542
                    continue
                y2_val = t[j3]
                if abs(y1_val - y2_val) < y_limit and abs(x1 + x2 - y1_val - y2_val) < xy_limit:  # L544
                    how_many_y += 1
                    if how_many_y > 1:                                   # L546: only this y1's loop
                        break
                    y1 = y1_val
                    y2 = y2_val
                    ty = 0.5 * (y1 + y2 - profile.time_sum_t_y)          # L551 (L2023:585 T_sum_y)
                    hit_t = (tx + ty) / 2                                # L552
                    put(which_row, 4, y1 - ty if centred else y1)        # L553 (L2023:598)
                    put(which_row, 5, y2 - ty if centred else y2)        # L554 (L2023:599)
                    put(which_row, 1, hit_t)                             # L555
                    ch[i] = NAN                                          # L557–560: mark used
                    ch[x2_index] = NAN
                    ch[j2] = NAN
                    ch[j3] = NAN

        if how_many_y == 0:                                              # L574–576
            which_row -= 1
            if stats is not None:
                stats.y_missing += 1
                if second_x2 is not None:
                    stats.y_missing_x2_ambiguous += 1
                    if _has_y_pair(ch, t, i, x1_val, second_x2, search, window, y_limit, xy_limit, c_y1, c_y2):
                        stats.x2_retry_would_match += 1
        elif stats is not None and how_many_y > 1:
            stats.y_ambiguous += 1

    # L580–581: keep the rows with a T (a grown row's T is 0, not NaN, so it stays).
    kept = [row for row in out if not math.isnan(row[0])]
    # L590–592: T = t·bin_time, X = (x1′ − x2′)·v⊥x·bin_time, Y likewise, in MATLAB's order.
    bin_time, v_x, v_y = profile.bin_time, profile.v_perp_x, profile.v_perp_y
    hits = [[row[0] * bin_time, (row[1] - row[2]) * v_x * bin_time, (row[3] - row[4]) * v_y * bin_time] for row in kept]
    # L1525–1530: combine (only the 4-corner hits run) and sort by T.
    order = sort_order([hit[0] for hit in hits])
    if stats is not None:
        stats.hits += len(hits)
    return np.array([hits[k] for k in order], dtype=np.float64).reshape(-1, 3)


def _has_y_pair(ch: list[float], t: list[float], i: int, x1: float, x2: float, search: list[int], window: float,
                y_limit: float, xy_limit: float, c_y1: float, c_y2: float) -> bool:
    """Whether the y search (L505–546) would find a pair for x1 with this x2, changing nothing."""
    n = len(t)
    for dummy2 in search:
        j2 = i + dummy2
        if j2 < 0 or j2 >= n or abs(t[j2] - x1) > window or ch[j2] != c_y1:
            continue
        for dummy3 in search:
            j3 = i + dummy3
            if j3 < 0 or j3 >= n or abs(t[j3] - x1) > window or ch[j3] != c_y2:
                continue
            if abs(t[j2] - t[j3]) < y_limit and abs(x1 + x2 - t[j2] - t[j3]) < xy_limit:
                return True
    return False


def _run(pulses: RawPulses, profile: DetectorProfile) -> Hits:
    return reconstruct_reference(pulses, profile)


register_backend(Backend(
    name="reference",
    run=_run,
    unavailable=lambda profile: None,
    description="Plain-Python port of MATLAB's loops; the byte-for-byte reference.",
))
