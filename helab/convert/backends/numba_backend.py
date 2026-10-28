"""The numba backend: the reference's loops compiled with numba (``numba_kernels``).

Registered as ``numba`` on import; numba itself is imported only when the backend is asked
whether it can run or is run, so HeLab and the tests work without it (``unavailable`` then says
why). Byte for byte the reference's output; ``numba_kernels``'s docstring says why its two changes
of form (no MATLAB output matrix, pieces) can't change it.

A conversion is NumPy's stable argsort and one compiled call, neither holding the GIL
(``releases_gil``): threads converting different shots
run in parallel. ``reconstruct_numba_pieces`` cuts one shot into pieces at gaps longer than the
match window and matches them serially, in a thread pool or with numba's ``prange``, for the
within-shot measurements; the registered backend runs the whole shot as one piece.

The compiled code is cached on disk: in the folder given to ``set_cache_folder`` before the
backend's first use (HeLab's helper passes one under ``cache_dir()``; this package stays free of
``helab.utils``), else where numba chooses. Without a usable cache the first call in a process
compiles (about 1.5 s); with it, it loads (about 0.1 s).

Qt-free; NumPy, and numba when installed.
"""
from __future__ import annotations

from concurrent.futures import Executor
import functools
import importlib
from pathlib import Path
import threading
from types import ModuleType
from typing import Literal

import numpy as np
import numpy.typing as npt

from helab.convert.backends.reference import offsets
from helab.convert.profile import DetectorProfile
from helab.convert.raw import RawPulses
from helab.convert.reconstruct import Backend, BackendError, Hits, NoRowsError, register_backend

NAME = "numba"
KERNELS = "helab.convert.backends.numba_kernels"
Within = Literal["serial", "threads", "prange"]

_cache_lock = threading.Lock()
_cache_folder: Path | None = None
_cache_folder_taken = False


def set_cache_folder(folder: Path | str | None) -> None:
    """Cache the compiled kernels in ``folder`` (created when missing), or, with None, where numba
    chooses. Call it before the backend's first use in the process: the kernels take it when they
    are first imported, and asking for another folder after that raises ``BackendError``."""
    global _cache_folder
    chosen = None if folder is None else Path(folder)
    with _cache_lock:
        if _cache_folder_taken and chosen != _cache_folder:
            where = "numba's own folder" if _cache_folder is None else str(_cache_folder)
            raise BackendError(f"The numba kernels already cache in {where}; set the cache folder before the "
                               "backend's first use")
        _cache_folder = chosen


def take_cache_folder() -> Path | None:
    """The folder ``set_cache_folder`` gave, fixed from now on (``numba_kernels`` calls this as it loads)."""
    global _cache_folder_taken
    with _cache_lock:
        _cache_folder_taken = True
        return _cache_folder


@functools.cache
def import_problem() -> str | None:
    """Why numba can't be imported here, or None. Any error while numba loads (not only an
    ImportError: numba raises others, e.g. for a NumPy it doesn't support or a broken llvmlite)
    leaves the backend unavailable with the reason; it never reaches ``available_backends``."""
    try:
        importlib.import_module("numba")
    except Exception as error:
        return f"numba can't be imported ({type(error).__name__}: {error})"
    return None


def _kernels() -> ModuleType:
    # importlib, not sys.modules: another thread may still be executing the module (the import
    # lock makes this one wait for it).
    return importlib.import_module(KERNELS)


def unavailable(profile: DetectorProfile | None) -> str | None:
    problem = import_problem()
    if problem is not None or profile is None:
        return problem
    if profile.x2_handling != "matlab" or profile.y_handling != "matlab":
        return f"only the 'matlab' candidate handling is compiled, not {profile.x2_handling}/{profile.y_handling}"
    if profile.position_formula not in ("centred", "raw"):
        return f"position formula {profile.position_formula!r} isn't compiled"
    return None


class _Arguments:
    """The profile as the kernels take it: float64 and int64 arrays, Python scalars."""

    def __init__(self, profile: DetectorProfile) -> None:
        self.subtract_time_zero = bool(profile.subtract_time_zero)
        self.corners = np.array([profile.channel_x1, profile.channel_x2, profile.channel_y1, profile.channel_y2],
                                dtype=np.float64)
        dead = (profile.dead_time_x1, profile.dead_time_x2, profile.dead_time_y1, profile.dead_time_y2)
        self.dead_active = np.array([dead_time > 0 for dead_time in dead], dtype=np.bool_)
        self.dead_tolerance = np.array([dead_time / profile.bin_time for dead_time in dead], dtype=np.float64)
        self.first = 1 if profile.skip_first_sorted_row else 0
        self.offsets = np.array(offsets(profile.search_depth), dtype=np.int64)
        self.window = float(profile.search_window)                                  # T_sum (L465)
        self.x_limit = float(profile.match_time_sum_x + profile.match_tolerance_x)  # L440
        self.y_limit = float(profile.match_time_sum_y + profile.match_tolerance_y)  # L441
        self.xy_limit = float(profile.xy_sum_tolerance)                             # L442
        self.time_sum_t_x = float(profile.time_sum_t_x)
        self.time_sum_t_y = float(profile.time_sum_t_y)
        self.centred = profile.position_formula == "centred"
        self.bin_time = float(profile.bin_time)
        self.v_perp_x = float(profile.v_perp_x)
        self.v_perp_y = float(profile.v_perp_y)
        self.overflow_row = bool(profile.matlab_overflow_row)


def _arrays(pulses: RawPulses, profile: DetectorProfile) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64],
                                                                  npt.NDArray[np.int64]]:
    """Channels, times and the times' stable argsort, NaN last (L58–60), as the kernels take them.
    NumPy sorts without the GIL."""
    if pulses.times.shape[0] == 0 and profile.subtract_time_zero:
        raise NoRowsError("The raw file has no rows (MATLAB fails at t_zero, L62)")
    times = np.ascontiguousarray(pulses.times, dtype=np.float64)
    return (np.ascontiguousarray(pulses.channels, dtype=np.float64), times,
            np.argsort(times, kind="stable").astype(np.int64, copy=False))


def reconstruct_numba(pulses: RawPulses, profile: DetectorProfile) -> Hits:
    channels, times, order = _arrays(pulses, profile)
    a = _Arguments(profile)
    hits: Hits = _kernels().convert(
        channels, times, order, a.subtract_time_zero, a.corners, a.dead_active, a.dead_tolerance, a.first, a.offsets,
        a.window, a.x_limit, a.y_limit, a.xy_limit, a.time_sum_t_x, a.time_sum_t_y, a.centred, a.bin_time,
        a.v_perp_x, a.v_perp_y, a.overflow_row)
    return hits


def reconstruct_numba_pieces(pulses: RawPulses, profile: DetectorProfile, pieces: int, within: Within = "serial",
                             executor: Executor | None = None) -> Hits:
    """One shot cut into up to ``pieces`` pieces at gaps longer than the match window, matched
    ``serial``ly, on ``executor``'s threads (``threads``), or with numba's ``prange``."""
    channels, times, order = _arrays(pulses, profile)
    a = _Arguments(profile)
    k = _kernels()
    channels, times = k.prepare(channels, times, order, a.subtract_time_zero, a.corners, a.dead_active, a.dead_tolerance)
    bounds: npt.NDArray[np.int64] = k.choose_bounds(times, a.window, max(1, pieces))
    n = times.shape[0]
    count = bounds.shape[0] - 1
    out = np.empty((n, 3), dtype=np.float64)
    counts = np.zeros(count, dtype=np.int64)
    failed = np.zeros(count, dtype=np.bool_)
    fail_x1 = np.zeros(count, dtype=np.float64)
    fail_x2 = np.zeros(count, dtype=np.float64)
    tail = (a.window, a.x_limit, a.y_limit, a.xy_limit, a.time_sum_t_x, a.time_sum_t_y, a.centred, a.corners,
            a.bin_time, a.v_perp_x, a.v_perp_y, out)
    if within == "prange":
        k.match_parallel(channels, times, bounds, a.first, a.offsets, *tail, counts, failed, fail_x1, fail_x2)
    else:
        def one(piece: int) -> tuple[int, bool, float, float]:
            result: tuple[int, bool, float, float] = k.match(
                channels, times, int(bounds[piece]), int(bounds[piece + 1]), a.first, a.offsets, *tail)
            return result

        results = (list(executor.map(one, range(count))) if within == "threads" and executor is not None
                   else [one(piece) for piece in range(count)])
        for piece, (piece_count, fail, x1_column, x2_column) in enumerate(results):
            counts[piece], failed[piece], fail_x1[piece], fail_x2[piece] = piece_count, fail, x1_column, x2_column
    hits: Hits = k.finish(out, bounds, counts, failed, fail_x1, fail_x2, n, a.overflow_row, a.bin_time, a.v_perp_x,
                          a.v_perp_y)
    return hits


def piece_bounds(pulses: RawPulses, profile: DetectorProfile, pieces: int) -> npt.NDArray[np.int64]:
    """Where ``reconstruct_numba_pieces`` cuts (row indices of the sorted pulses, 0 and N included)."""
    channels, times, order = _arrays(pulses, profile)
    a = _Arguments(profile)
    k = _kernels()
    _, times = k.prepare(channels, times, order, a.subtract_time_zero, a.corners, a.dead_active, a.dead_tolerance)
    bounds: npt.NDArray[np.int64] = k.choose_bounds(times, a.window, max(1, pieces))
    return bounds


register_backend(Backend(
    name=NAME,
    run=reconstruct_numba,
    unavailable=unavailable,
    releases_gil=True,
    description="The reference's loops compiled with numba (nogil, cached).",
))
