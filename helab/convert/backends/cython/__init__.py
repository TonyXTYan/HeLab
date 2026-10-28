"""The ``cython`` backend: the reference's match loop compiled with Cython, the GIL released.

``backends/reference.py`` loop for loop in C (``native/cython/_kernel.pyx``, built by
``python native/cython/build.py`` into ``_kernel`` here; the binary is never committed). The
kernel sorts, cuts dead time, matches and assembles; this module turns the profile into the
kernel's numbers and splits one shot for ``threads`` > 1. Every kernel call releases the GIL, so
threads converting different shots run in parallel (``releases_gil``).

Byte for byte the reference's output: the kernel does the same double operations in the same
order (the build turns FMA contraction and fast-math off), the same stable NaN-last sorts, the
same quirks (the phantom row, ``NoRowsError``, the first-row skip, the dead-time cut).

**Within one shot** (``reconstruct_cython(…, threads=k)``): the sorted, dead-time-cut rows are cut
at gaps where ``t[k] − t[k−1] > search_window``, and the pieces are matched in parallel. Why that
can't change the output:

- every candidate a search visits is skipped when ``|t[j] − x1| > search_window``. Across such a
  gap, for x1 at i < k ≤ j (or j < k ≤ i), ``|t[j] − t[i]| ≥ t[k] − t[k−1] > search_window``
  (the times are sorted and rounded subtraction is monotone), so no search crosses a cut: in the
  whole shot the row is skipped for its time, in a piece for being outside it. Rows with a NaN
  time sort last and never pass a comparison; no cut is made beside them (a NaN gap isn't
  ``>``). The 36-row search is therefore the same in a piece as in the shot, and a match only
  marks rows in its own piece, so pieces don't interact;
- time zero (the first raw row) and the dead-time cut are applied to the whole shot before
  cutting; only the first piece skips its first row (the first sorted row);
- hits keep their order: pieces are joined in row order before the one final stable sort by T;
- the phantom row is MATLAB's row W + 1 (W hits in the whole shot), present when it lies past the
  preallocated ``floor(rows/4)`` (whole-shot rows) and an x pair without a y came after the last
  hit; its x columns are that pair's. Each piece reports its last such pair after its own last
  hit, and the pieces' reports are folded in order, which gives the whole shot's.

``tests/test_convert_backend_cython.py`` checks that every split equals the whole on the cases,
the phantom and dead-time ones among them.

Qt-free; standard library and NumPy (the compiled kernel needs nothing else).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
from pathlib import Path
from types import ModuleType

import numpy as np
import numpy.typing as npt

from helab.convert.profile import DetectorProfile
from helab.convert.raw import RawPulses
from helab.convert.reconstruct import Backend, Hits, NoRowsError, register_backend

_SOURCE = Path(__file__).resolve().parents[4] / "native" / "cython" / "_kernel.pyx"
_BUILD_HINT = "python native/cython/build.py (needs Cython, setuptools and a C compiler)"

_module: ModuleType | None = None  # not "_kernel": that name is the submodule's
_why_not: str | None = None
_loaded = False


def kernel() -> ModuleType | None:
    """The compiled kernel, imported on first use; None when it isn't built, or is older than its
    source in this checkout (``unavailable`` then says why)."""
    global _module, _why_not, _loaded
    if not _loaded:
        _loaded = True
        try:
            module = _import_kernel()
        except ImportError as error:
            _why_not = f"the compiled kernel isn't built ({error}); build it with {_BUILD_HINT}"
        else:
            built = getattr(module, "SOURCE_SHA256", None)
            if _SOURCE.is_file() and built != hashlib.sha256(_SOURCE.read_bytes()).hexdigest():
                _why_not = f"the compiled kernel is older than {_SOURCE.name}; rebuild it with {_BUILD_HINT}"
            else:
                _module = module
    return _module


def _import_kernel() -> ModuleType:
    return importlib.import_module("helab.convert.backends.cython._kernel")


def _reset() -> None:
    """Forget the import, so the next ``kernel()`` tries again (tests)."""
    global _module, _why_not, _loaded
    _module, _why_not, _loaded = None, None, False


def unavailable(profile: DetectorProfile | None) -> str | None:
    if kernel() is None:
        return _why_not
    if profile is not None:
        for name in ("channel_x1", "channel_x2", "channel_y1", "channel_y2"):
            channel = getattr(profile, name)
            # The kernel compares channels as doubles; the reference compares them exactly.
            try:
                exact = float(channel) == channel
            except OverflowError:
                exact = False
            if not exact:
                return f"{name} = {channel} isn't exactly a double"
    return None


def search_offsets(depth: int, rows: int) -> npt.NDArray[np.intp]:
    """The reference's ``offsets(depth)`` (−1, +1, −2, +2, …), cut where every further offset
    passes both ends of ``rows`` rows (|offset| = ceil(k/2) for the k-th), which changes nothing."""
    count = max(0, min(depth, 2 * rows + 2))
    k = np.arange(1, count + 1, dtype=np.intp)
    return np.where(k % 2 == 0, k // 2, -((k + 1) // 2)).astype(np.intp)


def cut_points(times: npt.NDArray[np.float64], window: float, pieces: int) -> list[int]:
    """Up to ``pieces`` − 1 row indices k, ascending, where the sorted ``times`` jump by more than
    ``window`` (``times[k] − times[k−1] > window``), each the first such gap at or after an equal
    share of the rows. Fewer when the shot has fewer gaps."""
    rows = int(times.shape[0])
    if pieces <= 1 or rows < 2:
        return []
    gaps = np.flatnonzero(np.diff(times) > window) + 1
    if gaps.size == 0:
        return []
    targets = (np.arange(1, pieces) * rows) // pieces
    chosen = gaps[np.minimum(np.searchsorted(gaps, targets), gaps.size - 1)]
    return sorted({int(k) for k in chosen})


def reconstruct_cython(pulses: RawPulses, profile: DetectorProfile, threads: int = 1) -> Hits:
    """The reference's output; ``threads`` > 1 cuts the shot (module docstring) and matches the
    pieces in that many threads."""
    module = kernel()
    if module is None:
        raise RuntimeError(f"The cython backend can't run: {_why_not}")
    n = len(pulses)
    if n == 0 and profile.subtract_time_zero:
        raise NoRowsError("The raw file has no rows (MATLAB fails at t_zero, L62)")
    corners = ((profile.channel_x1, profile.dead_time_x1), (profile.channel_x2, profile.dead_time_x2),
               (profile.channel_y1, profile.dead_time_y1), (profile.channel_y2, profile.dead_time_y2))
    dead = [(float(channel), dead_time / profile.bin_time) for channel, dead_time in corners if dead_time > 0]
    channels, times = module.prepare(
        np.ascontiguousarray(pulses.channels, dtype=np.float64), np.ascontiguousarray(pulses.times, dtype=np.float64),
        profile.subtract_time_zero, np.array([c for c, _ in dead], dtype=np.float64),
        np.array([tol for _, tol in dead], dtype=np.float64))

    search = search_offsets(profile.search_depth, n)
    settings = (search, profile.search_window, profile.match_time_sum_x + profile.match_tolerance_x,
                profile.match_time_sum_y + profile.match_tolerance_y, profile.xy_sum_tolerance,
                float(profile.channel_x1), float(profile.channel_x2), float(profile.channel_y1),
                float(profile.channel_y2), profile.time_sum_t_x, profile.time_sum_t_y,
                profile.position_formula == "centred")
    first = 1 if profile.skip_first_sorted_row else 0
    bounds = [0, *cut_points(times, profile.search_window, threads), n]
    outs = [np.empty(((hi - lo) // 4 + 1, 5), dtype=np.float64) for lo, hi in zip(bounds, bounds[1:])]

    def run(piece: int) -> tuple[int, bool, float, float]:
        lo, hi = bounds[piece], bounds[piece + 1]
        result: tuple[int, bool, float, float] = module.match(channels, times, lo, hi, max(lo, first), *settings,
                                                              outs[piece])
        return result

    if len(outs) == 1:
        results = [run(0)]
    else:
        with ThreadPoolExecutor(min(threads, len(outs))) as pool:
            results = list(pool.map(run, range(len(outs))))

    # The phantom row: the last x pair without a y after the last hit, over the pieces in order.
    pending: tuple[float, float] | None = None
    for hits, piece_pending, x1_column, x2_column in results:
        if hits or piece_pending:
            pending = (x1_column, x2_column) if piece_pending else None
    total = sum(result[0] for result in results)
    phantom = pending is not None and profile.matlab_overflow_row and total + 1 > n // 4
    x1_column, x2_column = pending if pending is not None else (0.0, 0.0)
    out: Hits = module.assemble([(rows, result[0]) for rows, result in zip(outs, results)], phantom, x1_column,
                                x2_column, profile.bin_time, profile.v_perp_x, profile.v_perp_y)
    return out


def _run(pulses: RawPulses, profile: DetectorProfile) -> Hits:
    return reconstruct_cython(pulses, profile)


register_backend(Backend(
    name="cython",
    run=_run,
    unavailable=unavailable,
    releases_gil=True,
    description="The reference's loops compiled with Cython (native/cython/), the GIL released.",
))
