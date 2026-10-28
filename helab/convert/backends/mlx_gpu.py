"""The ``mlx`` backend: the reference's match with the candidate search on the Apple GPU (MLX).

Byte for byte the reference's output (``backends/reference.py`` holds MATLAB's loops and quirks;
this module only changes how the answer is found). Metal has no float64 and the times reach
~1e10 bins, more than float32 holds exactly, so:

1. **CPU, NumPy, float64, as the reference:** sort the rows stably (NaN last), subtract the first
   raw row's time, and turn each row into a corner code (1 x1, 2 x2, 3 y1, 4 y2, 0 anything else).
   A row whose time isn't finite gets code 0: the reference never matches it (a NaN passes the
   window test but fails every sum test; an infinite time fails the window test). Then the
   corner times must be integers below 2^50, which makes every difference and sum the reference
   forms exact in int64 and lets each ``< L``/``> L`` test with a float limit become an integer
   test (``|d| > W`` is ``|d| > floor(W)``, ``|d| < L`` is ``|d| <= ceil(L) − 1``); otherwise the
   shot goes to the reference (a time with a fraction, which only a hand-made file has). The
   2023 dead-time cut (``uniquetol``) runs here, in integers: non-finite times never join a
   group, so the groups of the finite ones are the reference's.
2. **GPU, MLX, integers:** for every x1 at once, its **first choice**: the first x2 in search
   order (−1, +1, −2, …) and, with it, the first y pair in the nested y1/y2 order, **as if no
   pulse were used yet**. Differences from x1 are taken in int64 and clamped into int32 (only
   ``|d| <= window`` ever matters, so the clamp changes no test).
3. **CPU, the greedy order:** MATLAB marks the pulses of each hit as used, in x1 order, and a
   used pulse can't be chosen again. Marks only remove candidates, so a first choice whose
   pulses no earlier hit took is exactly MATLAB's choice (every candidate before it fails
   whatever is marked). Only an x1 whose first choice claims a pulse an earlier x1's first-choice
   hit also marks is **contested**; those are recomputed exactly, in x1 order, against the
   final hits of the x1 rows before them that can reach the same pulses (within twice the
   search reach), and a recomputed x1 whose answer changed makes the x1 rows after it within
   that reach contested too. Uncontested x1 rows keep their first choice.
4. **CPU, NumPy, float64:** T, X and Y from the matched rows' float64 times with the reference's
   operations in its order; MATLAB's phantom row (the last x pair with no y, in a grown row);
   one stable sort by T.

Without MLX, or off Apple Silicon, ``unavailable`` says why and nothing imports ``mlx``.
``first_choices_numpy`` is the same search on the CPU, for the tests and the timing comparison.

Qt-free; standard library and NumPy (MLX imported lazily, only to run).
"""
from __future__ import annotations

from dataclasses import dataclass
import functools
import heapq
import importlib.util
import math
import platform
import sys
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt

from helab.convert.backends.reference import offsets, reconstruct_reference
from helab.convert.profile import DetectorProfile
from helab.convert.raw import RawPulses
from helab.convert.reconstruct import Backend, Hits, NoRowsError, register_backend

if TYPE_CHECKING:
    import mlx.core

Ints = npt.NDArray[np.int64]
Codes = npt.NDArray[np.int8]

X1, X2, Y1, Y2 = 1, 2, 3, 4
# Corner times must stay below this so that x1 + x2 − y1 − y2 is exact in int64 and float64.
EXACT_LIMIT = 2.0 ** 50
# Differences from x1 are clamped to ±CLAMP in int32; the window must stay well inside it (a
# profile with a window of WINDOW_LIMIT bins or more goes to the reference).
CLAMP = 2 ** 28
WINDOW_LIMIT = CLAMP // 4
# x1 rows per GPU batch: the pair search holds rows × depth² int32 values (~5 kB per row at 36).
GPU_BATCH = 8192
NONE = -1


@dataclass(frozen=True)
class Limits:
    """The profile's tests on integer differences: a candidate is in the window when
    ``|d| <= window``; an x2 when also ``|d| <= x2``; a y pair when ``|y1 − y2| <= y`` and
    ``|x1 + x2 − y1 − y2| <= xy`` (each limit ``-1`` when nothing passes)."""
    window: int
    x2: int
    y: int
    xy: int


@dataclass(frozen=True)
class Prepared:
    """One shot ready to match: ``times`` (int64, sorted, from time zero; 0 for code-0 rows),
    ``codes`` per sorted row, ``x1_rows`` (the x1 rows the loop visits, ascending),
    ``float_times`` (the reference's float64 times, for the output), ``rows`` (all rows, for
    MATLAB's ``floor(rows/4)``), ``search`` (the row offsets in search order)."""
    times: Ints
    codes: Codes
    x1_rows: Ints
    float_times: npt.NDArray[np.float64]
    rows: int
    search: Ints
    limits: Limits


@dataclass
class Choices:
    """Per x1 row (aligned with ``Prepared.x1_rows``): the chosen x2 row, and the y1 and y2 rows
    of its pair, or ``NONE``. A hit has all three."""
    x2: Ints
    y1: Ints
    y2: Ints

    def copy(self) -> Choices:
        return Choices(self.x2.copy(), self.y1.copy(), self.y2.copy())


def _below(limit: float) -> int:
    """The largest integer ``|d|`` with ``|d| < limit`` (``-1``: none), at most ``4·CLAMP``: the
    candidates' differences, sums of three of them included, stay below ``3·CLAMP``."""
    return min(math.ceil(limit) - 1, 4 * CLAMP)


def _not_above(limit: float) -> int:
    """The largest integer ``|d|`` with ``not |d| > limit``, at most ``4·CLAMP``."""
    return min(math.floor(limit), 4 * CLAMP)


def limits_of(profile: DetectorProfile) -> Limits:
    return Limits(window=_not_above(profile.search_window),
                  x2=_below(profile.match_time_sum_x + profile.match_tolerance_x),
                  y=_below(profile.match_time_sum_y + profile.match_tolerance_y),
                  xy=_below(profile.xy_sum_tolerance))


def _dead_time_keep(values: Ints, tolerance: int) -> npt.NDArray[np.bool_]:
    """``uniquetol_keep`` for sorted integers: the first of each group, a group being the values
    within ``tolerance`` (≤) of its first one. A value more than ``tolerance`` after the one
    before it always starts a group, so only runs of close values need the walk."""
    keep = np.ones(values.shape[0], dtype=bool)
    if values.shape[0] < 2:
        return keep
    close = np.diff(values) <= tolerance             # value k + 1 within tolerance of value k
    if not close.any():
        return keep
    # Runs of close values: [start, end] index ranges where every step is close.
    edges = np.flatnonzero(np.diff(np.concatenate(([0], close.view(np.int8), [0]))))
    for start, end in zip(edges[0::2].tolist(), edges[1::2].tolist()):
        run = values[start:end + 1].tolist()
        first = run[0]
        for k in range(1, len(run)):
            if run[k] - first > tolerance:
                first = run[k]
            else:
                keep[start + k] = False
    return keep


def prepare(pulses: RawPulses, profile: DetectorProfile) -> Prepared | None:
    """Step 1 of the module's notes; None when a corner time isn't an integer below 2^50 or the
    window is ``WINDOW_LIMIT`` or more (the caller runs the reference)."""
    raw_times = pulses.times
    n = int(raw_times.shape[0])
    if n == 0 and profile.subtract_time_zero:
        raise NoRowsError("The raw file has no rows (MATLAB fails at t_zero, L62)")
    if profile.search_window >= WINDOW_LIMIT:
        return None
    order = np.argsort(raw_times, kind="stable")             # NaN last, as MATLAB's sort
    channels = pulses.channels[order]
    float_times = raw_times[order]
    if profile.subtract_time_zero:
        with np.errstate(invalid="ignore"):                    # inf − inf is NaN, as in the reference
            float_times = float_times - raw_times[0]
    codes = np.zeros(n, dtype=np.int8)
    for code, channel in ((X1, profile.channel_x1), (X2, profile.channel_x2), (Y1, profile.channel_y1),
                          (Y2, profile.channel_y2)):
        codes[channels == channel] = code
    finite = np.isfinite(float_times)
    codes[~finite] = 0
    corner = codes != 0
    corner_times = float_times[corner]
    if corner_times.size and (np.any(np.abs(corner_times) >= EXACT_LIMIT)
                              or np.any(corner_times != np.floor(corner_times))):
        return None
    times = np.zeros(n, dtype=np.int64)
    times[corner] = corner_times.astype(np.int64)
    # L2023:429–458: the dead-time cut, each corner from the rows before any cut.
    snapshot = codes.copy()
    for code, dead_time in ((X1, profile.dead_time_x1), (X2, profile.dead_time_x2), (Y1, profile.dead_time_y1),
                            (Y2, profile.dead_time_y2)):
        if dead_time > 0:
            rows = np.flatnonzero(snapshot == code)
            keep = _dead_time_keep(times[rows], _not_above(dead_time / profile.bin_time))
            codes[rows[~keep]] = 0
    first = 1 if profile.skip_first_sorted_row else 0
    x1_rows = np.flatnonzero(codes[first:] == X1).astype(np.int64) + first
    return Prepared(times=times, codes=codes, x1_rows=x1_rows, float_times=float_times, rows=n,
                    search=np.array(offsets(profile.search_depth), dtype=np.int64), limits=limits_of(profile))


def _first_true(mask: npt.NDArray[np.bool_]) -> Ints:
    """Per row, the index of the first True along the last axis, or NONE."""
    index = np.argmax(mask, axis=-1).astype(np.int64)
    return np.where(mask.any(axis=-1), index, NONE)


def first_choices_numpy(prep: Prepared) -> Choices:
    """Step 2 on the CPU: each x1's first choice, ignoring used pulses."""
    lim, search, n = prep.limits, prep.search, prep.rows
    width = search.shape[0]
    x2_out, y1_out, y2_out = (np.full(prep.x1_rows.shape[0], NONE, dtype=np.int64) for _ in range(3))
    for start in range(0, prep.x1_rows.shape[0], GPU_BATCH):
        rows = prep.x1_rows[start:start + GPU_BATCH]
        near = rows[:, None] + search[None, :]
        inside = (near >= 0) & (near < n)
        near = np.clip(near, 0, max(n - 1, 0))
        diff = np.clip(prep.times[near] - prep.times[rows][:, None], -CLAMP, CLAMP)
        code = np.where(inside & (np.abs(diff) <= lim.window), prep.codes[near], 0)
        x2k = _first_true((code == X2) & (np.abs(diff) <= lim.x2))
        has_x2 = x2k != NONE
        dx2 = np.take_along_axis(diff, np.maximum(x2k, 0)[:, None], axis=1)[:, 0]
        # x1 + x2 − y1 − y2 = dx2 − dy1 − dy2 and y1 − y2 = dy1 − dy2, all differences from x1.
        dy1, dy2 = diff[:, :, None], diff[:, None, :]
        pair = (((code == Y1)[:, :, None] & (code == Y2)[:, None, :]) & (np.abs(dy1 - dy2) <= lim.y)
                & (np.abs(dx2[:, None, None] - dy1 - dy2) <= lim.xy))
        pk = _first_true(pair.reshape(rows.shape[0], width * width))
        hit = has_x2 & (pk != NONE)
        x2_out[start:start + rows.shape[0]] = np.where(has_x2, near[np.arange(rows.shape[0]), np.maximum(x2k, 0)], NONE)
        k2, k3 = np.maximum(pk, 0) // width, np.maximum(pk, 0) % width
        y1_out[start:start + rows.shape[0]] = np.where(hit, rows + search[k2], NONE)
        y2_out[start:start + rows.shape[0]] = np.where(hit, rows + search[k3], NONE)
    return Choices(x2_out, y1_out, y2_out)


def first_choices_mlx(prep: Prepared) -> Choices:
    """Step 2 on the GPU: the same search as ``first_choices_numpy``, in MLX (int64 gathers and
    differences, int32 tests). Only the chosen offsets come back."""
    import mlx.core as mx

    lim, search_np, n = prep.limits, prep.search, prep.rows
    width = search_np.shape[0]
    count = prep.x1_rows.shape[0]
    if count == 0:
        return first_choices_numpy(prep)
    times = mx.array(prep.times)
    codes = mx.array(prep.codes)
    search = mx.array(search_np)
    flat = mx.arange(width * width, dtype=mx.int32)
    x2k_parts: list[mlx.core.array] = []
    pk_parts: list[mlx.core.array] = []
    for start in range(0, count, GPU_BATCH):
        rows = mx.array(prep.x1_rows[start:start + GPU_BATCH])
        x2k, pk = _gpu_batch(times, codes, rows, search, flat, n, width, lim)
        x2k_parts.append(x2k)
        pk_parts.append(pk)
    x2k_all = mx.concatenate(x2k_parts)
    pk_all = mx.concatenate(pk_parts)
    mx.eval(x2k_all, pk_all)
    x2k_np = np.array(x2k_all, dtype=np.int64)
    pk_np = np.array(pk_all, dtype=np.int64)
    rows_np = prep.x1_rows
    has_x2 = x2k_np < width
    hit = has_x2 & (pk_np < width * width)
    x2 = np.where(has_x2, rows_np + search_np[np.minimum(x2k_np, width - 1)], NONE)
    pk_safe = np.minimum(pk_np, width * width - 1)
    y1 = np.where(hit, rows_np + search_np[pk_safe // width], NONE)
    y2 = np.where(hit, rows_np + search_np[pk_safe % width], NONE)
    return Choices(x2, y1, y2)


def _gpu_batch(times: mlx.core.array, codes: mlx.core.array, rows: mlx.core.array,
               search: mlx.core.array, flat: mlx.core.array, n: int, width: int,
               lim: Limits) -> tuple[mlx.core.array, mlx.core.array]:
    """One batch of x1 rows: the first x2 offset (``width`` for none) and the first y pair as
    ``k2·width + k3`` (``width²`` for none)."""
    import mlx.core as m

    near = rows[:, None] + search[None, :]
    inside = (near >= 0) & (near < n)
    near = m.clip(near, 0, n - 1)
    diff = m.clip(m.take(times, near) - m.take(times, rows)[:, None], -CLAMP, CLAMP).astype(m.int32)
    adiff = m.abs(diff)
    code = m.where(inside & (adiff <= lim.window), m.take(codes, near), m.array(0, dtype=m.int8))
    index = m.arange(width, dtype=m.int32)[None, :]
    x2k = m.min(m.where((code == X2) & (adiff <= lim.x2), index, width), axis=1)
    dx2 = m.take_along_axis(diff, m.minimum(x2k, width - 1)[:, None], axis=1)
    dy1, dy2 = diff[:, :, None], diff[:, None, :]
    pair = (((code == Y1)[:, :, None] & (code == Y2)[:, None, :]) & (m.abs(dy1 - dy2) <= lim.y)
            & (m.abs(dx2[:, :, None] - dy1 - dy2) <= lim.xy))
    pk = m.min(m.where(pair.reshape(-1, width * width), flat[None, :], width * width), axis=1)
    return x2k, pk


def _exact_choice(prep: Prepared, i: int, used: set[int]) -> tuple[int, int, int]:
    """MATLAB's search for the x1 at row ``i`` with ``used`` rows marked (L456–560): the x2 row
    and the y pair's rows, NONE where there is none."""
    lim, n = prep.limits, prep.rows
    times, codes = prep.times, prep.codes
    x1 = int(times[i])
    candidates: list[tuple[int, int, int]] = []    # (row, code, difference) in search order
    for offset in prep.search.tolist():
        j = i + offset
        if j < 0 or j >= n or j in used or codes[j] == 0:
            continue
        d = int(times[j]) - x1
        if abs(d) <= lim.window:
            candidates.append((j, int(codes[j]), d))
    x2_row = x2_diff = NONE
    for j, code, d in candidates:
        if code == X2 and abs(d) <= lim.x2:
            x2_row, x2_diff = j, d
            break
    if x2_row == NONE:
        return NONE, NONE, NONE
    for j2, code2, d2 in candidates:
        if code2 != Y1:
            continue
        for j3, code3, d3 in candidates:
            if code3 == Y2 and abs(d2 - d3) <= lim.y and abs(x2_diff - d2 - d3) <= lim.xy:
                return x2_row, j2, j3
    return x2_row, NONE, NONE


def resolve(prep: Prepared, first: Choices) -> Choices:
    """Step 3: MATLAB's greedy order, from the first choices (see the module's notes)."""
    count = prep.x1_rows.shape[0]
    final = first.copy()
    if count == 0:
        return final
    hit = final.y1 != NONE
    a = np.arange(count, dtype=np.int64)
    # owner[row]: the earliest x1 (index into x1_rows) whose first-choice hit marks the row.
    owner = np.full(prep.rows, count, dtype=np.int64)
    for column in (final.x2, final.y1, final.y2):
        np.minimum.at(owner, column[hit], a[hit])
    contested = np.zeros(count, dtype=bool)
    for column in (final.x2, final.y1, final.y2):
        claimed = column != NONE
        contested[claimed] |= owner[column[claimed]] < a[claimed]
    if not contested.any():
        return final
    reach = 2 * int(np.max(np.abs(prep.search))) if prep.search.size else 0
    rows = prep.x1_rows
    queue = np.flatnonzero(contested).tolist()
    heapq.heapify(queue)
    queued = contested.copy()
    while queue:
        k = heapq.heappop(queue)
        i = int(rows[k])
        low = int(np.searchsorted(rows, i - reach, side="left"))
        used: set[int] = set()
        for b in range(low, k):
            if final.y1[b] != NONE:
                used.update((int(final.x2[b]), int(final.y1[b]), int(final.y2[b])))
        choice = _exact_choice(prep, i, used)
        if choice != (int(final.x2[k]), int(final.y1[k]), int(final.y2[k])):
            final.x2[k], final.y1[k], final.y2[k] = choice
            high = int(np.searchsorted(rows, i + reach, side="right"))
            for b in range(k + 1, high):
                if not queued[b]:
                    queued[b] = True
                    heapq.heappush(queue, b)
    return final


def assemble(prep: Prepared, final: Choices, profile: DetectorProfile) -> Hits:
    """Step 4: the hits from the matched rows, in MATLAB's float64 operations and order."""
    t = prep.float_times
    hit = final.y1 != NONE
    rows = prep.x1_rows[hit]
    x1, x2 = t[rows], t[final.x2[hit]]
    y1, y2 = t[final.y1[hit]], t[final.y2[hit]]
    tx = 0.5 * (x1 + x2 - profile.time_sum_t_x)                      # L485
    ty = 0.5 * (y1 + y2 - profile.time_sum_t_y)                      # L551
    centred = profile.position_formula == "centred"
    columns = [(tx + ty) / 2,                                        # L552
               x1 - tx if centred else x1, x2 - tx if centred else x2,
               y1 - ty if centred else y1, y2 - ty if centred else y2]
    out = np.stack(columns, axis=1) if rows.size else np.empty((0, 5))
    # The phantom row: after the last hit, an x1 whose x2 matched but no y wrote its x pair into
    # row hits + 1; past MATLAB's floor(rows/4) preallocation that row was grown with zeros, so
    # its T is 0, not NaN, and it is kept (L444, L580).
    attempts = np.flatnonzero(final.x2 != NONE)
    last_hit = int(np.flatnonzero(hit)[-1]) if hit.any() else -1
    if (profile.matlab_overflow_row and attempts.size and int(attempts[-1]) > last_hit
            and rows.size + 1 > prep.rows // 4):
        k = int(attempts[-1])
        px1, px2 = t[prep.x1_rows[k]], t[final.x2[k]]
        ptx = 0.5 * (px1 + px2 - profile.time_sum_t_x)
        phantom = np.array([[0.0, px1 - ptx if centred else px1, px2 - ptx if centred else px2, 0.0, 0.0]])
        out = np.concatenate([out, phantom])
    bin_time, v_x, v_y = profile.bin_time, profile.v_perp_x, profile.v_perp_y
    hits = np.empty((out.shape[0], 3), dtype=np.float64)
    hits[:, 0] = out[:, 0] * bin_time                                # L590–592
    hits[:, 1] = (out[:, 1] - out[:, 2]) * v_x * bin_time
    hits[:, 2] = (out[:, 3] - out[:, 4]) * v_y * bin_time
    return hits[np.argsort(hits[:, 0], kind="stable")]               # L1528–1530


def reconstruct_mlx(pulses: RawPulses, profile: DetectorProfile, gpu: bool = True) -> Hits:
    """The backend; ``gpu=False`` runs step 2 with NumPy instead (the CPU baseline)."""
    prep = prepare(pulses, profile)
    if prep is None:
        return reconstruct_reference(pulses, profile)
    first = first_choices_mlx(prep) if gpu else first_choices_numpy(prep)
    return assemble(prep, resolve(prep, first), profile)


@functools.cache
def _platform_unavailable() -> str | None:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return f"MLX needs Apple Silicon (this is {sys.platform} {platform.machine()})"
    if importlib.util.find_spec("mlx") is None:
        return "MLX isn't installed (pip install mlx)"
    try:
        import mlx.core as mx
        if not mx.metal.is_available():
            return "MLX finds no Metal GPU"
    except Exception as error:  # noqa: BLE001 - any import or device failure means "can't run"
        return f"MLX can't start: {error}"
    return None


def _unavailable(profile: DetectorProfile | None) -> str | None:
    reason = _platform_unavailable()
    if reason is not None or profile is None:
        return reason
    if profile.x2_handling != "matlab" or profile.y_handling != "matlab":
        return "only the matlab x2 and y handling"
    return None


def _run(pulses: RawPulses, profile: DetectorProfile) -> Hits:
    return reconstruct_mlx(pulses, profile)


register_backend(Backend(
    name="mlx",
    run=_run,
    unavailable=_unavailable,
    releases_gil=False,
    description="Candidate search on the Apple GPU (MLX), greedy order and output on the CPU.",
))
