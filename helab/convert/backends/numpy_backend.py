"""The NumPy backend: the reference's output byte for byte, vectorised where the order can't
matter (``.ai/sessions/2026-10-29-claude-txy-numpy/notes.md`` has the argument in full).

MATLAB's match is greedy: each x1, in time order, takes the first free x2 in search order
(−1, +1, −2, …), then the first free y pair, and marks the four pulses used (channel NaN), so a
later x1 can't take them. Marks only ever remove candidates, which gives the split used here:

1. **Optimistic, vectorised.** For every x1 at once, ignoring marks: the candidate rows (in the
   window, of the right channel), the first x2 and the first y pair in search order. Times are
   sorted, so each x1's window is one run of rows, found exactly; only the offsets some x1 of a
   block reaches are looked at. Rows with a NaN time (sorted last) fail every test and are left
   out.
2. **What marks can change.** With fewer candidates an x1 can't find a match it didn't find
   before; and if the x2 and the y pair it chose are still free when its turn comes, they are
   still the first free ones in search order. So an optimistic failure is final, and a choice
   is final unless an earlier x1 marked one of its pulses. An earlier x1 can only mark its own
   candidates, so an x1 none of whose chosen pulses is a candidate of an earlier x1
   ("touched", below) is final as it stands: it is "clean".
3. **Exact and sequential, only for the rest.** The clean x1s' pulses are marked first (no
   earlier x1 has them as candidates, so marking them early changes nothing it sees); then the
   other x1s run in time order: their optimistic choice is kept when its pulses are still free,
   or the reference's search is run again for that x1 with the marks as they are.

The output is then formed as MATLAB's matrix holds it: the hits in x1 order, the phantom row
(an x pair with no y after the last hit, in a row MATLAB grew with zeros past floor(N/4)), T, X
and Y, and one stable sort by T. The dead-time cut (uniquetol) is vectorised the same way: the
next group's start for every pulse at once, then a walk from group to group.

Qt-free; standard library and NumPy only.
"""
from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

from helab.convert.backends.reference import offsets
from helab.convert.profile import DetectorProfile
from helab.convert.raw import RawPulses
from helab.convert.reconstruct import Backend, Hits, NoRowsError, register_backend

Floats = npt.NDArray[np.float64]
Index = npt.NDArray[np.intp]
Mask = npt.NDArray[np.bool_]
Candidates = list[tuple[int, float]]  # (row, time), in search order

NAN = math.nan
CHUNK = 8192  # x1 rows per vectorised block (bounds the (rows, 36) temporaries)

# Outcome of an x1: no x2, an x2 but no y pair (MATLAB's which_row goes back), a hit.
NONE, NO_Y, HIT = 0, 1, 2


def uniquetol_keep(values: Floats, tol: float) -> Mask:
    """``reference.uniquetol_keep`` for values sorted ascending, NaN last: the first of each
    group, a group being the values within ``tol`` (≤) of its first one."""
    size = values.shape[0]
    keep = np.ones(size, dtype=np.bool_)
    if size < 2:
        return keep
    if not math.isfinite(tol):
        from helab.convert.backends.reference import uniquetol_keep as by_value
        return np.array(by_value(values.tolist(), tol), dtype=np.bool_)
    # Non-finite values are each their own group (|v − first| is NaN or Inf) and sorted to the
    # ends: −Inf first, then the finite run, then Inf and NaN.
    finite = np.flatnonzero(np.isfinite(values))
    if finite.shape[0] < 2:
        return keep
    lo, hi = int(finite[0]), int(finite[-1]) + 1
    run = values[lo:hi]
    count = run.shape[0]
    here = np.arange(count)
    # The next group's first value after a group starting at k: the first m > k with
    # run[m] − run[k] > tol (rounding is monotonic, so these m are a suffix). Found by a search
    # on run + tol, then corrected step by step to the exact test.
    nxt = np.maximum(np.searchsorted(run, run + tol, side="right"), here + 1)
    while True:
        down = (nxt - 1 > here) & (run[np.minimum(nxt - 1, count - 1)] - run > tol)
        if not bool(down.any()):
            break
        nxt[down] -= 1
    while True:
        up = nxt < count
        up[up] = run[nxt[up]] - run[up] <= tol
        if not bool(up.any()):
            break
        nxt[up] += 1
    chain = np.zeros(count, dtype=np.bool_)
    steps = nxt.tolist()
    k = 0
    while k < count:
        chain[k] = True
        k = steps[k]
    keep[lo:hi] = chain
    return keep


def _dead_time_cut(ch: Floats, t: Floats, profile: DetectorProfile) -> Floats:
    corners = ((profile.channel_x1, profile.dead_time_x1), (profile.channel_x2, profile.dead_time_x2),
               (profile.channel_y1, profile.dead_time_y1), (profile.channel_y2, profile.dead_time_y2))
    if all(dead_time <= 0 for _, dead_time in corners):
        return ch
    out = ch.copy()
    for channel, dead_time in corners:  # each from the rows before any cut (L2023:429–458)
        if dead_time > 0:
            rows = np.flatnonzero(ch == channel)
            keep = uniquetol_keep(t[rows], dead_time / profile.bin_time)
            out[rows[~keep]] = NAN
    return out


def reconstruct_numpy(pulses: RawPulses, profile: DetectorProfile) -> Hits:
    # Inf − Inf and the like are NaN, as in MATLAB, and fail their tests: not worth a warning.
    with np.errstate(invalid="ignore", over="ignore"):
        return _reconstruct(pulses, profile)


def _reconstruct(pulses: RawPulses, profile: DetectorProfile) -> Hits:
    n = len(pulses)
    if n == 0 and profile.subtract_time_zero:
        raise NoRowsError("The raw file has no rows (MATLAB fails at t_zero, L62)")
    order = np.argsort(pulses.times, kind="stable")  # L58–60; NaN last
    t = pulses.times[order]
    if profile.subtract_time_zero:
        t = t - pulses.times[0]  # L62–66: the first raw row, not the earliest
    ch = _dead_time_cut(pulses.channels[order], t, profile)

    first = 1 if profile.skip_first_sorted_row else 0
    # Rows with a NaN time sort last. Every test on them is false (L477, L544), so they can't be
    # a match or change one: they are left out, and an x1 with a NaN time finds nothing.
    end = n - int(np.count_nonzero(np.isnan(t)))
    x1 = np.flatnonzero(ch[:end] == profile.channel_x1)
    x1 = x1[x1 >= first]
    m = x1.shape[0]
    search = np.array(offsets(profile.search_depth), dtype=np.intp)

    match = _Match(m, n)
    for begin in range(0, m, CHUNK):
        _optimistic(begin, x1[begin:begin + CHUNK], t, ch, end, search, profile, match)
    _settle(x1, n, profile, match)
    return _hits(x1, t, n, profile, match.outcome, match.x2_row, match.y1_row, match.y2_row)


class _Match:
    """Each x1's outcome and rows (−1: none), which x1s an earlier one could interfere with, and
    for those their candidates. ``touched[j]``: the first x1 (by position) with row j as a
    candidate."""

    def __init__(self, m: int, n: int) -> None:
        self.outcome = np.zeros(m, dtype=np.int8)
        self.x2_row = np.full(m, -1, dtype=np.intp)
        self.y1_row = np.full(m, -1, dtype=np.intp)
        self.y2_row = np.full(m, -1, dtype=np.intp)
        self.risky = np.zeros(m, dtype=np.bool_)
        self.touched = np.full(n, m, dtype=np.intp)
        # (position, x1 time, x2, y1 and y2 candidates) for each risky x1, in x1 order.
        self.pending: list[tuple[int, float, Candidates, Candidates, Candidates]] = []


def _windows(rows: Index, x1_t: Floats, t: Floats, end: int, window: float, left: int,
             right: int) -> tuple[Index, Index]:
    """The rows in each x1's window (L465), as [lo, hi), cut to the rows the search reaches.
    Times are sorted and rounding is monotonic, so ``not |t[j] − x1| > window`` holds on one run
    of rows around the x1: a search on the times finds it, then each end is moved to the exact
    test."""
    floor = np.maximum(rows - left, 0)
    ceiling = np.minimum(rows + right + 1, end)
    lo = np.clip(np.searchsorted(t[:end], x1_t - window, side="left"), floor, rows)
    hi = np.clip(np.searchsorted(t[:end], x1_t + window, side="right"), rows + 1, ceiling)
    _move(lo, floor, -1, -1, x1_t, t, window, while_inside=True)    # down over rows inside
    _move(lo, rows, 1, 0, x1_t, t, window, while_inside=False)      # up off rows outside
    _move(hi, ceiling, 1, 0, x1_t, t, window, while_inside=True)
    _move(hi, rows + 1, -1, -1, x1_t, t, window, while_inside=False)
    return lo, hi


def _move(ends: Index, limit: Index, step: int, look: int, x1_t: Floats, t: Floats, window: float, *,
          while_inside: bool) -> None:
    """Move each end by ``step`` (in place) until it reaches ``limit`` or the row at
    ``end + look`` stops being inside the window (``while_inside``) or outside it."""
    while True:
        more = ends > limit if step < 0 else ends < limit
        if not bool(more.any()):
            return
        outside = np.abs(t[ends[more] + look] - x1_t[more]) > window   # L465
        more[more] = ~outside if while_inside else outside
        if not bool(more.any()):
            return
        ends[more] += step


def _optimistic(begin: int, rows: Index, t: Floats, ch: Floats, end: int, search: Index, profile: DetectorProfile,
                match: _Match) -> None:
    """Step 1 for one block of x1 rows: each one's choice ignoring marks, and its candidates."""
    n = t.shape[0]
    count = rows.shape[0]
    block = slice(begin, begin + count)
    x1_t = t[rows]
    window = profile.search_window
    lo, hi = _windows(rows, x1_t, t, end, window, max(0, -int(search.min())), max(0, int(search.max())))
    # Only the offsets some x1 of the block reaches inside its window (L456–465): the search
    # order −1, +1, −2, +2, … makes them a prefix.
    reach = int(max((rows - lo).max(), (hi - 1 - rows).max()))
    width = int(np.searchsorted(np.abs(search), reach, side="right"))
    if not width:
        return
    j = rows[:, None] + search[None, :width]
    in_window = (j >= lo[:, None]) & (j < hi[:, None])
    j = np.clip(j, 0, n - 1)
    cj = ch[j]
    x_limit = profile.match_time_sum_x + profile.match_tolerance_x       # L440
    x2_ok = in_window & (cj == profile.channel_x2) & (np.abs(x1_t[:, None] - t[j]) < x_limit)   # L474–477
    y1_ok = in_window & (cj == profile.channel_y1)                       # L524
    y2_ok = in_window & (cj == profile.channel_y2)                       # L542

    flat = np.flatnonzero((x2_ok | y1_ok | y2_ok).ravel())
    np.minimum.at(match.touched, j.ravel()[flat], flat // width + begin)

    has_x2 = x2_ok.any(axis=1)
    x2_j = np.where(has_x2, j[np.arange(count), x2_ok.argmax(axis=1)], -1)   # the first in search order
    match.outcome[block] = np.where(has_x2, NO_Y, NONE)
    match.x2_row[block] = x2_j
    # Every (y1, y2) pair of each x1 with an x2, in the nested search order (L505–546).
    y1_flat = np.flatnonzero((y1_ok & has_x2[:, None]).ravel())          # by x1, then search order
    y2_flat = np.flatnonzero((y2_ok & has_x2[:, None]).ravel())
    y1_who, y2_who = y1_flat // width, y2_flat // width
    y2_count = np.bincount(y2_who, minlength=count)
    per_y1 = y2_count[y1_who]
    total = int(per_y1.sum())
    if total:
        pair_y1 = np.repeat(np.arange(y1_who.shape[0]), per_y1)
        pair_who = y1_who[pair_y1]
        pair_y2 = (np.cumsum(y2_count) - y2_count)[pair_who] + np.arange(total) - np.repeat(np.cumsum(per_y1) - per_y1,
                                                                                              per_y1)
        y1_j = j.ravel()[y1_flat[pair_y1]]
        y2_j = j.ravel()[y2_flat[pair_y2]]
        y1_t, y2_t = t[y1_j], t[y2_j]
        x1_p, x2_p = x1_t[pair_who], t[x2_j[pair_who]]
        y_limit = profile.match_time_sum_y + profile.match_tolerance_y   # L441
        ok = (np.abs(y1_t - y2_t) < y_limit) & (np.abs(x1_p + x2_p - y1_t - y2_t) < profile.xy_sum_tolerance)  # L544
        good = np.flatnonzero(ok)
        if good.shape[0]:
            good_who = pair_who[good]
            firsts = good[np.concatenate(([True], good_who[1:] != good_who[:-1]))]
            at = begin + pair_who[firsts]
            match.outcome[at] = HIT
            match.y1_row[at] = y1_j[firsts]
            match.y2_row[at] = y2_j[firsts]

    # Step 2: every x1 before these is done, so touched is final for their rows.
    position = np.arange(begin, begin + count)
    outcome, touched = match.outcome[block], match.touched
    hit = outcome == HIT
    risky = (outcome != NONE) & (touched[np.maximum(x2_j, 0)] < position)
    risky |= hit & ((touched[np.maximum(match.y1_row[block], 0)] < position)
                    | (touched[np.maximum(match.y2_row[block], 0)] < position))
    match.risky[block] = risky
    local = np.flatnonzero(risky)
    if not local.shape[0]:
        return
    # Their candidates, kept for step 3: rows and times per x1, flat, with each x1's start.
    flats = []
    for ok_mask in (x2_ok, y1_ok, y2_ok):
        where = np.flatnonzero(ok_mask[local].ravel())
        rows_j = j[local].ravel()[where]
        starts = np.searchsorted(where // width, np.arange(local.shape[0] + 1))
        flats.append((rows_j.tolist(), t[rows_j].tolist(), starts.tolist()))
    for k, (p, x1_v) in enumerate(zip((local + begin).tolist(), x1_t[local].tolist())):
        x2c, y1c, y2c = (list(zip(r[s[k]:s[k + 1]], v[s[k]:s[k + 1]])) for r, v, s in flats)
        match.pending.append((p, x1_v, x2c, y1c, y2c))


def _settle(x1: Index, n: int, profile: DetectorProfile, match: _Match) -> None:
    """Step 3: mark the clean hits' pulses, then run the risky x1s in order with the marks."""
    hit = match.outcome == HIT
    clean = np.flatnonzero(hit & ~match.risky)
    used = np.zeros(n, dtype=np.bool_)
    for rows in (x1[clean], match.x2_row[clean], match.y1_row[clean], match.y2_row[clean]):
        used[rows] = True
    if not match.pending:
        return
    marks = bytearray(used.tobytes())
    y_limit = profile.match_time_sum_y + profile.match_tolerance_y
    xy_limit = profile.xy_sum_tolerance
    outcome, x2_row, y1_row, y2_row = match.outcome, match.x2_row, match.y1_row, match.y2_row
    for p, x1_v, x2c, y1c, y2c in match.pending:
        x2, y1, y2, state = int(x2_row[p]), int(y1_row[p]), int(y2_row[p]), int(outcome[p])
        if not marks[x2] and (state == NO_Y or (not marks[y1] and not marks[y2])):
            if state == HIT:
                marks[int(x1[p])] = marks[x2] = marks[y1] = marks[y2] = 1
            continue
        x2, y1, y2 = _search_one(x1_v, x2c, y1c, y2c, marks, y_limit, xy_limit)
        x2_row[p], y1_row[p], y2_row[p] = x2, y1, y2
        outcome[p] = NONE if x2 < 0 else NO_Y if y1 < 0 else HIT
        if y1 >= 0:
            marks[int(x1[p])] = marks[x2] = marks[y1] = marks[y2] = 1


def _search_one(x1: float, x2c: Candidates, y1c: Candidates, y2c: Candidates, marks: bytearray, y_limit: float,
                xy_limit: float) -> tuple[int, int, int]:
    """The reference's search for one x1 (L451–560) over its candidates (window, channel and,
    for x2, the x limit already applied), a marked row's channel being NaN: its x2 and y rows,
    −1 where none."""
    x2_index, x2 = next(((j, value) for j, value in x2c if not marks[j]), (-1, 0.0))
    if x2_index < 0:  # a second free x2 only ends the search (how_many_x == ~1)
        return -1, -1, -1
    for j2, y1 in y1c:
        if marks[j2]:
            continue
        for j3, y2 in y2c:
            if not marks[j3] and abs(y1 - y2) < y_limit and abs(x1 + x2 - y1 - y2) < xy_limit:
                return x2_index, j2, j3
    return x2_index, -1, -1


def _hits(x1: Index, t: Floats, n: int, profile: DetectorProfile, outcome: npt.NDArray[np.int8], x2_row: Index,
          y1_row: Index, y2_row: Index) -> Hits:
    """MATLAB's output matrix (L444–592): the hits in x1 order, the phantom row, the final sort."""
    centred = profile.position_formula == "centred"
    hit = np.flatnonzero(outcome == HIT)
    x1_t, x2_t = t[x1[hit]], t[x2_row[hit]]
    y1_t, y2_t = t[y1_row[hit]], t[y2_row[hit]]
    tx = 0.5 * (x1_t + x2_t - profile.time_sum_t_x)                      # L485
    ty = 0.5 * (y1_t + y2_t - profile.time_sum_t_y)                      # L551
    columns = [(tx + ty) / 2,                                            # L552
               x1_t - tx if centred else x1_t, x2_t - tx if centred else x2_t,
               y1_t - ty if centred else y1_t, y2_t - ty if centred else y2_t]
    # L580–581: rows with a NaN T are dropped (a hit's T is finite whenever its tests pass, but
    # the rule is MATLAB's).
    columns = [column[~np.isnan(columns[0])] for column in columns]
    # The phantom row: after the last hit, an x1 with an x2 but no y writes its x pair into row
    # (hits + 1); past MATLAB's floor(n/4) preallocated rows that row was grown with zeros, so
    # its T is 0 and it survives the NaN filter (L444, L580–581). The last such x1 wins.
    after = outcome[(hit[-1] + 1 if hit.shape[0] else 0):]
    lone = np.flatnonzero(after == NO_Y)
    if profile.matlab_overflow_row and lone.shape[0] and hit.shape[0] + 1 > n // 4:
        p = (hit[-1] + 1 if hit.shape[0] else 0) + int(lone[-1])
        x1_v, x2_v = t[x1[p]], t[x2_row[p]]
        tx_v = 0.5 * (x1_v + x2_v - profile.time_sum_t_x)
        phantom = [0.0, x1_v - tx_v if centred else x1_v, x2_v - tx_v if centred else x2_v, 0.0, 0.0]
        columns = [np.append(column, value) for column, value in zip(columns, phantom)]
    bin_time = profile.bin_time
    out = np.empty((columns[0].shape[0], 3), dtype=np.float64)
    out[:, 0] = columns[0] * bin_time                                    # L590–592
    out[:, 1] = (columns[1] - columns[2]) * profile.v_perp_x * bin_time
    out[:, 2] = (columns[3] - columns[4]) * profile.v_perp_y * bin_time
    return out[np.argsort(out[:, 0], kind="stable")]                     # L1525–1530


def _unavailable(profile: DetectorProfile | None) -> str | None:
    if profile is not None and (profile.x2_handling, profile.y_handling) != ("matlab", "matlab"):
        return "only MATLAB's candidate handling"
    return None


register_backend(Backend(
    name="numpy",
    run=reconstruct_numpy,
    unavailable=_unavailable,
    description="NumPy: vectorised candidate search, an exact pass where earlier matches could interfere.",
))
