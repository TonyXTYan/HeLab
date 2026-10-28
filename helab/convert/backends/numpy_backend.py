"""The NumPy backend: the reference's output byte for byte, vectorised where the order can't
matter (``.ai/sessions/2026-10-29-claude-txy-numpy/notes.md`` has the argument in full).

MATLAB's match is greedy: each x1, in time order, takes the first free x2 in search order
(−1, +1, −2, …), then the first free y pair, and marks the four pulses used (channel NaN), so a
later x1 can't take them. Marks only ever remove candidates, which gives the split used here:

1. **Optimistic, vectorised.** For every x1 at once, ignoring marks: the candidate rows (in the
   window, of the right channel), the first x2 and the first y pair in search order.
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
    n = len(pulses)
    if n == 0 and profile.subtract_time_zero:
        raise NoRowsError("The raw file has no rows (MATLAB fails at t_zero, L62)")
    order = np.argsort(pulses.times, kind="stable")  # L58–60; NaN last
    t = pulses.times[order]
    if profile.subtract_time_zero:
        t = t - pulses.times[0]  # L62–66: the first raw row, not the earliest
    ch = _dead_time_cut(pulses.channels[order], t, profile)

    first = 1 if profile.skip_first_sorted_row else 0
    x1 = np.flatnonzero(ch == profile.channel_x1)
    x1 = x1[x1 >= first]
    m = x1.shape[0]
    search = np.array(offsets(profile.search_depth), dtype=np.intp)

    outcome = np.zeros(m, dtype=np.int8)
    x2_row = np.full(m, -1, dtype=np.intp)
    y1_row = np.full(m, -1, dtype=np.intp)
    y2_row = np.full(m, -1, dtype=np.intp)
    # touched[j]: the first x1 (by its position in x1) that has row j as a candidate.
    touched = np.full(n, m, dtype=np.intp)
    for begin in range(0, m, CHUNK):
        _optimistic(begin, x1[begin:begin + CHUNK], t, ch, search, profile, outcome, x2_row, y1_row, y2_row, touched)

    _settle(x1, t, ch, search, profile, outcome, x2_row, y1_row, y2_row, touched)
    return _hits(x1, t, n, profile, outcome, x2_row, y1_row, y2_row)


def _optimistic(begin: int, rows: Index, t: Floats, ch: Floats, search: Index, profile: DetectorProfile,
                outcome: npt.NDArray[np.int8], x2_row: Index, y1_row: Index, y2_row: Index, touched: Index) -> None:
    """Step 1 for one block of x1 rows: each one's choice ignoring marks, and the candidates."""
    n = t.shape[0]
    count = rows.shape[0]
    x1_t = t[rows]
    j = rows[:, None] + search[None, :]                                  # L456–457, one column per offset
    inside = (j >= 0) & (j < n)                                          # L459–464
    j = np.clip(j, 0, n - 1)
    tj = t[j]
    cj = ch[j]
    in_window = inside & ~(np.abs(tj - x1_t[:, None]) > profile.search_window)   # L465
    x_limit = profile.match_time_sum_x + profile.match_tolerance_x       # L440
    x2_ok = in_window & (cj == profile.channel_x2) & (np.abs(x1_t[:, None] - tj) < x_limit)   # L474–477
    y1_ok = in_window & (cj == profile.channel_y1)                       # L515–524
    y2_ok = in_window & (cj == profile.channel_y2)                       # L538–542

    candidate = x2_ok | y1_ok | y2_ok
    who, where = np.nonzero(candidate)
    np.minimum.at(touched, j[who, where], who + begin)

    has_x2 = x2_ok.any(axis=1)
    x2_col = x2_ok.argmax(axis=1)                                        # the first in search order
    sel = np.flatnonzero(has_x2)
    block = slice(begin, begin + count)
    outcome[block] = np.where(has_x2, NO_Y, NONE)
    x2_row[block] = np.where(has_x2, j[np.arange(count), x2_col], -1)
    if not sel.shape[0]:
        return
    js = j[sel]
    y1_who, y1_col = np.nonzero(y1_ok[sel])                              # sorted by x1, then search order
    y2_who, y2_col = np.nonzero(y2_ok[sel])
    # Every (y1, y2) pair of each x1, in the nested search order (L505–546).
    y2_count = np.bincount(y2_who, minlength=sel.shape[0])
    y2_start = np.cumsum(y2_count) - y2_count
    per_y1 = y2_count[y1_who]
    total = int(per_y1.sum())
    if not total:
        return
    pair_y1 = np.repeat(np.arange(y1_who.shape[0]), per_y1)
    pair_who = y1_who[pair_y1]
    pair_y2 = y2_start[pair_who] + np.arange(total) - np.repeat(np.cumsum(per_y1) - per_y1, per_y1)
    y1_j = js[pair_who, y1_col[pair_y1]]
    y2_j = js[pair_who, y2_col[pair_y2]]
    y1_t, y2_t = t[y1_j], t[y2_j]
    x1_p = x1_t[sel][pair_who]
    x2_p = t[x2_row[begin + sel]][pair_who]
    y_limit = profile.match_time_sum_y + profile.match_tolerance_y       # L441
    ok = (np.abs(y1_t - y2_t) < y_limit) & (np.abs(x1_p + x2_p - y1_t - y2_t) < profile.xy_sum_tolerance)  # L544
    good = np.flatnonzero(ok)
    if not good.shape[0]:
        return
    good_who = pair_who[good]
    firsts = good[np.concatenate(([True], good_who[1:] != good_who[:-1]))]
    at = begin + sel[pair_who[firsts]]
    outcome[at] = HIT
    y1_row[at] = y1_j[firsts]
    y2_row[at] = y2_j[firsts]


def _settle(x1: Index, t: Floats, ch: Floats, search: Index, profile: DetectorProfile, outcome: npt.NDArray[np.int8],
            x2_row: Index, y1_row: Index, y2_row: Index, touched: Index) -> None:
    """Steps 2 and 3: keep what marks can't change, run the rest in order with the marks."""
    m = x1.shape[0]
    position = np.arange(m)
    found = outcome != NONE
    hit = outcome == HIT
    risky = found & (touched[np.maximum(x2_row, 0)] < position)
    risky |= hit & ((touched[np.maximum(y1_row, 0)] < position) | (touched[np.maximum(y2_row, 0)] < position))
    clean_hits = np.flatnonzero(hit & ~risky)
    used = np.zeros(t.shape[0], dtype=np.bool_)
    for rows in (x1[clean_hits], x2_row[clean_hits], y1_row[clean_hits], y2_row[clean_hits]):
        used[rows] = True
    todo = np.flatnonzero(risky)
    if not todo.shape[0]:
        return
    marks = bytearray(used.tobytes())
    lists: tuple[list[float], list[float], list[int]] | None = None  # made on the first search
    for p, i, x2, y1, y2, state in zip(todo.tolist(), x1[todo].tolist(), x2_row[todo].tolist(),
                                       y1_row[todo].tolist(), y2_row[todo].tolist(), outcome[todo].tolist()):
        if not marks[x2] and (state == NO_Y or (not marks[y1] and not marks[y2])):
            if state == HIT:
                marks[i] = marks[x2] = marks[y1] = marks[y2] = 1
            continue
        if lists is None:
            lists = t.tolist(), ch.tolist(), search.tolist()
        x2, y1, y2 = _search_one(i, *lists, marks, profile)
        x2_row[p], y1_row[p], y2_row[p] = x2, y1, y2
        outcome[p] = NONE if x2 < 0 else NO_Y if y1 < 0 else HIT
        if y1 >= 0:
            marks[i] = marks[x2] = marks[y1] = marks[y2] = 1


def _search_one(i: int, t: list[float], ch: list[float], search: list[int], marks: bytearray,
                profile: DetectorProfile) -> tuple[int, int, int]:
    """The reference's search for the x1 at row i (L451–560), a marked row's channel being NaN:
    its x2 and y rows, −1 where none."""
    n = len(t)
    x1 = t[i]
    window = profile.search_window
    x_limit = profile.match_time_sum_x + profile.match_tolerance_x
    y_limit = profile.match_time_sum_y + profile.match_tolerance_y
    xy_limit = profile.xy_sum_tolerance
    c_x2, c_y1, c_y2 = profile.channel_x2, profile.channel_y1, profile.channel_y2

    def free(j: int, channel: int) -> bool:
        return 0 <= j < n and not abs(t[j] - x1) > window and not marks[j] and ch[j] == channel

    x2_index = -1
    for dummy in search:
        j = i + dummy
        if free(j, c_x2) and abs(x1 - t[j]) < x_limit:
            x2_index = j  # a second candidate only ends the search (how_many_x == ~1)
            break
    if x2_index < 0:
        return -1, -1, -1
    x2 = t[x2_index]
    for dummy2 in search:
        j2 = i + dummy2
        if not free(j2, c_y1):
            continue
        for dummy3 in search:
            j3 = i + dummy3
            if free(j3, c_y2) and abs(t[j2] - t[j3]) < y_limit and abs(x1 + x2 - t[j2] - t[j3]) < xy_limit:
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
