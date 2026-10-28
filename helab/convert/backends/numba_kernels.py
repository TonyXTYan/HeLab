"""The numba backend's compiled loops (``numba_backend`` imports this only when numba loads).

The reference's loops (``backends/reference.py``, with MATLAB's line numbers there) as
``@njit(cache=True, nogil=True)`` functions on float64 arrays. Two changes of form, neither of
output:

- the MATLAB output matrix (``NaN(floor(N/4), 5)``, grown with zeros) isn't built. Hits are
  written in the order they're found, and the **phantom row** is rebuilt at the end: ``which_row``
  never goes below a row that holds a hit, so the only row past the last hit that can be written
  is the one after it, by an x1 whose x pair found no y. It survives (T = 0) exactly when the last
  such x pair came after the last hit, the row lies past the ``floor(N/4)`` preallocated ones, and
  the profile grows rows with zeros (``matlab_overflow_row``); it holds that pair's columns and
  zeros, so the arithmetic below repeats the reference's on those values.
- the match runs over pieces ``[lo, hi)`` of the sorted rows, cut where two consecutive finite
  times are more than the window apart (``choose_bounds``). For an x1 at row ``i`` in a piece and a
  finite row ``j`` in another, ``|t[j] − t[i]|`` is at least that gap (rounded subtraction is
  monotonic), so the reference skips ``j`` (L465, L515, L538) as it skips rows past the array's
  ends; a row with a NaN time is never skipped by the window but never matches (every comparison
  with NaN is false) and so is never marked. So a piece reads and marks only its own rows, and
  the pieces' hits in piece order are the reference's rows in order. The global parts stay
  global: ``t_zero`` (first raw row), the sort, the dead-time cut (before any cut, so its 20,000
  bin groups can't be split), the skip of the first sorted row (only the first piece starts at
  it), ``floor(N/4)`` over all rows, and the final stable sort by T.

``prange`` over pieces (``match_parallel``) uses numba's threading layer, which (the default
``workqueue`` on macOS) must not be entered from two Python threads at once; the registered
backend runs one piece, serially, and leaves threads to the caller.

Qt-free; NumPy and numba only.
"""
from __future__ import annotations

import importlib
import math
from typing import Any, Callable, TypeVar, cast

import numpy as np
import numpy.typing as npt

_numba: Any = importlib.import_module("numba")
prange: Any = _numba.prange

Floats = npt.NDArray[np.float64]
Ints = npt.NDArray[np.int64]
F = TypeVar("F", bound=Callable[..., Any])
# False when numba had nowhere to write its cache and the kernels compile in every process.
cached = True


def _compile(function: F, parallel: bool) -> F:
    global cached
    try:
        return cast(F, _numba.njit(cache=True, nogil=True, parallel=parallel)(function))
    except RuntimeError:
        # numba found no folder it can write its cache to (a read-only checkout and user cache
        # folder): compile in every process instead (about 1.5 s on the first call) rather than fail.
        cached = False
        return cast(F, _numba.njit(nogil=True, parallel=parallel)(function))


def _jit(function: F) -> F:
    return _compile(function, parallel=False)


def _jit_parallel(function: F) -> F:
    return _compile(function, parallel=True)


@_jit
def prepare(raw_channels: Floats, raw_times: Floats, order: Ints, subtract_time_zero: bool, corners: Floats,
            dead_active: npt.NDArray[np.bool_], dead_tolerance: Floats) -> tuple[Floats, Floats]:
    """Put the rows in ``order`` (the times' stable argsort, NaN last: NumPy's ``kind="stable"``,
    a timsort, 4× faster than numba's mergesort on the nearly sorted TDC stream), subtract the
    first raw row's time, cut dead time (L58–66, L2023:429–458). ``corners``: x1, x2, y1, y2
    channels; the tolerance is in bins."""
    n = raw_times.shape[0]
    channels = raw_channels[order]
    times = raw_times[order]
    if subtract_time_zero:
        t_zero = raw_times[0]
        for k in range(n):
            times[k] = times[k] - t_zero
    snapshot = channels.copy()
    for corner in range(4):
        if not dead_active[corner]:
            continue
        channel = corners[corner]
        tolerance = dead_tolerance[corner]
        first = math.nan
        for k in range(n):
            if snapshot[k] != channel:
                continue
            value = times[k]
            if math.isnan(value) or math.isnan(first) or not abs(value - first) <= tolerance:
                first = value
            else:
                channels[k] = math.nan
    return channels, times


@_jit
def choose_bounds(times: Floats, window: float, pieces: int) -> Ints:
    """Up to ``pieces`` pieces of about equal length, each cut at the first gap at or after its
    target row where two consecutive finite times are more than ``window`` apart."""
    n = times.shape[0]
    bounds = np.empty(pieces + 1, dtype=np.int64)
    bounds[0] = 0
    count = 1
    b = 1
    for piece in range(1, pieces):
        target = (n * piece) // pieces
        if b < target:
            b = target
        while b < n and not (math.isfinite(times[b - 1]) and math.isfinite(times[b])
                             and times[b] - times[b - 1] > window):
            b += 1
        if b >= n:
            break
        bounds[count] = b
        count += 1
        b += 1
    bounds[count] = n
    return bounds[:count + 1]


@_jit
def match(channels: Floats, times: Floats, lo: int, hi: int, first: int, offsets: Ints, window: float,
          x_limit: float, y_limit: float, xy_limit: float, time_sum_t_x: float, time_sum_t_y: float, centred: bool,
          corners: Floats, bin_time: float, v_perp_x: float, v_perp_y: float,
          out: Floats) -> tuple[int, bool, float, float]:
    """The x1 loop (L449–576) over rows ``[lo, hi)``: hits to ``out[lo:lo + count]`` (T, X, Y as
    L590–592 make them); returns the count and, when the last x pair with no y came after the
    last hit, True and its two columns (the phantom row's candidates)."""
    c_x1, c_x2, c_y1, c_y2 = corners[0], corners[1], corners[2], corners[3]
    count = 0
    failed = False
    fail_x1 = fail_x2 = 0.0
    x1 = x2 = tx = 0.0
    column_x1 = column_x2 = column_y1 = column_y2 = hit_t = 0.0
    x2_index = 0
    start = lo if lo > first else first
    for i in range(start, hi):                                           # L449
        if channels[i] != c_x1:                                          # L450
            continue
        x1_val = times[i]                                                # L451
        how_many_x = 0
        for dummy in offsets:                                            # L456–457
            j: int = i + dummy
            if j < lo or j >= hi:                                        # L459–464
                continue
            if abs(times[j] - x1_val) > window:                          # L465
                continue
            if channels[j] == c_x2:                                      # L474
                x2_val = times[j]
                if abs(x1_val - x2_val) < x_limit:                       # L477
                    how_many_x += 1
                    if how_many_x > 1:                                   # L479
                        break
                    x1 = x1_val
                    x2 = x2_val
                    tx = 0.5 * (x1 + x2 - time_sum_t_x)                  # L485
                    column_x1 = x1 - tx if centred else x1               # L486
                    column_x2 = x2 - tx if centred else x2               # L487
                    x2_index = j                                         # L490
        if how_many_x == 0:                                              # L498
            continue
        how_many_y = 0
        for dummy2 in offsets:                                           # L505–506
            j2: int = i + dummy2
            if j2 < lo or j2 >= hi:                                      # L509–514
                continue
            if abs(times[j2] - x1_val) > window:                         # L515
                continue
            if channels[j2] != c_y1:                                     # L524
                continue
            y1_val = times[j2]
            for dummy3 in offsets:                                       # L529–530
                j3: int = i + dummy3
                if j3 < lo or j3 >= hi:                                  # L532–537
                    continue
                if abs(times[j3] - x1_val) > window:                     # L538
                    continue
                if channels[j3] != c_y2:                                 # L542
                    continue
                y2_val = times[j3]
                if abs(y1_val - y2_val) < y_limit and abs(x1 + x2 - y1_val - y2_val) < xy_limit:  # L544
                    how_many_y += 1
                    if how_many_y > 1:                                   # L546
                        break
                    ty = 0.5 * (y1_val + y2_val - time_sum_t_y)          # L551
                    hit_t = (tx + ty) / 2                                # L552
                    column_y1 = y1_val - ty if centred else y1_val       # L553
                    column_y2 = y2_val - ty if centred else y2_val       # L554
                    channels[i] = math.nan                               # L557–560
                    channels[x2_index] = math.nan
                    channels[j2] = math.nan
                    channels[j3] = math.nan
        if how_many_y == 0:                                              # L574–576
            failed = True
            fail_x1 = column_x1
            fail_x2 = column_x2
            continue
        row = lo + count                                                 # L590–592
        out[row, 0] = hit_t * bin_time
        out[row, 1] = (column_x1 - column_x2) * v_perp_x * bin_time
        out[row, 2] = (column_y1 - column_y2) * v_perp_y * bin_time
        count += 1
        failed = False
    return count, failed, fail_x1, fail_x2


@_jit
def finish(out: Floats, bounds: Ints, counts: Ints, failed: npt.NDArray[np.bool_], fail_x1: Floats,
           fail_x2: Floats, rows: int, overflow_row: bool, bin_time: float, v_perp_x: float,
           v_perp_y: float) -> Floats:
    """The pieces' hits in order, the phantom row if it survives (L444, L580–581), sorted by T
    stably (L1528–1530)."""
    total = 0
    phantom = False
    phantom_x1 = phantom_x2 = 0.0
    for piece in range(counts.shape[0]):
        total += counts[piece]
        if counts[piece] > 0:
            phantom = False
        if failed[piece]:
            phantom = True
            phantom_x1 = fail_x1[piece]
            phantom_x2 = fail_x2[piece]
    # The phantom is row total + 1: grown with zeros (it survives) past the floor(N/4) NaN rows.
    phantom = phantom and overflow_row and total + 1 > rows // 4
    hits = np.empty((total + (1 if phantom else 0), 3), dtype=np.float64)
    k = 0
    for piece in range(counts.shape[0]):
        lo = bounds[piece]
        for row in range(lo, lo + counts[piece]):
            hits[k, 0] = out[row, 0]
            hits[k, 1] = out[row, 1]
            hits[k, 2] = out[row, 2]
            k += 1
    if phantom:
        grown = 0.0
        hits[k, 0] = grown * bin_time
        hits[k, 1] = (phantom_x1 - phantom_x2) * v_perp_x * bin_time
        hits[k, 2] = (grown - grown) * v_perp_y * bin_time
    order = np.argsort(hits[:, 0], kind="mergesort")
    sorted_hits = np.empty_like(hits)
    for k in range(order.shape[0]):
        sorted_hits[k, 0] = hits[order[k], 0]
        sorted_hits[k, 1] = hits[order[k], 1]
        sorted_hits[k, 2] = hits[order[k], 2]
    return sorted_hits


@_jit
def convert(raw_channels: Floats, raw_times: Floats, order: Ints, subtract_time_zero: bool, corners: Floats,
            dead_active: npt.NDArray[np.bool_], dead_tolerance: Floats, first: int, offsets: Ints, window: float,
            x_limit: float, y_limit: float, xy_limit: float, time_sum_t_x: float, time_sum_t_y: float, centred: bool,
            bin_time: float, v_perp_x: float, v_perp_y: float, overflow_row: bool) -> Floats:
    """One shot, one piece, in one call without the GIL (``order`` as ``prepare``'s)."""
    channels, times = prepare(raw_channels, raw_times, order, subtract_time_zero, corners, dead_active, dead_tolerance)
    n = times.shape[0]
    out = np.empty((n, 3), dtype=np.float64)
    bounds = np.zeros(2, dtype=np.int64)
    bounds[1] = n
    count, fail, fail_x1, fail_x2 = match(channels, times, 0, n, first, offsets, window, x_limit, y_limit, xy_limit,
                                          time_sum_t_x, time_sum_t_y, centred, corners, bin_time, v_perp_x,
                                          v_perp_y, out)
    counts = np.full(1, count, dtype=np.int64)
    failed = np.full(1, fail, dtype=np.bool_)
    return finish(out, bounds, counts, failed, np.full(1, fail_x1), np.full(1, fail_x2), n, overflow_row, bin_time,
                  v_perp_x, v_perp_y)


@_jit_parallel
def match_parallel(channels: Floats, times: Floats, bounds: Ints, first: int, offsets: Ints, window: float,
                   x_limit: float, y_limit: float, xy_limit: float, time_sum_t_x: float, time_sum_t_y: float,
                   centred: bool, corners: Floats, bin_time: float, v_perp_x: float, v_perp_y: float, out: Floats,
                   counts: Ints, failed: npt.NDArray[np.bool_], fail_x1: Floats, fail_x2: Floats) -> None:
    """``match`` on every piece at once (numba's threads); each piece writes only its own rows."""
    for piece in prange(bounds.shape[0] - 1):
        lo = int(bounds[piece])
        hi = int(bounds[piece + 1])
        count, fail, x1_column, x2_column = match(
            channels, times, lo, hi, first, offsets, window, x_limit, y_limit, xy_limit,
            time_sum_t_x, time_sum_t_y, centred, corners, bin_time, v_perp_x, v_perp_y, out)
        counts[piece] = count
        failed[piece] = fail
        fail_x1[piece] = x1_column
        fail_x2[piece] = x2_column
