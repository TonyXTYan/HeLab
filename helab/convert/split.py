"""One shot cut into pieces at gaps the match can't cross, the pieces reconstructed with any
backend (in parallel when given an executor), and merged: the whole shot's output byte for byte.

**Where it cuts.** The pulses are sorted by time (stably, NaN last) and the file's first row's
time subtracted, as every backend does. A cut goes between sorted rows g and g + 1 only where
``t[g + 1] − t[g]`` is more than the search window and more than every dead time (in bins).
Then no x1 on one side can use a pulse on the other: rounding is monotonic, so for any x1 at or
before g and any row at or after g + 1, ``|t[j] − x1|`` is at least that gap and the window
test (L465) skips the row before its channel is looked at; every candidate x2 and y pulse is
windowed around x1, so the 36-row search never reaches across. (A row with a NaN time sorts
last and is never skipped by the window, but every test on it is false, so it can't make a hit
on either side.) Likewise the dead-time groups (uniquetol, within tol of a group's first value)
can't span the cut, so each piece's cut is the whole file's.

**What stays global.** Each piece is given its rows already sorted and shifted, with
``subtract_time_zero`` off (the file's own t_zero is kept), the first-row skip only in the
first piece, and the phantom row turned off. The phantom row depends on the whole file: MATLAB
preallocates floor(N/4) rows, and an x pair without a y after the **last** hit survives as a
T = 0 row when the hit count + 1 is past that. Every hit uses four rows, so that needs hits =
N // 4 exactly, with at most three rows (N mod 4) outside hits, two of them the lone x pair.
When the count allows it, the tail from the piece with the last hit to the end is run again as
one piece with the phantom row on: its rows are its own hits, the lone pair and at most one
more, so its floor(n/4) is its hit count, N // 4 less the hits before it, and its which_row
runs as the whole file's less those hits: it makes the phantom row exactly when the whole file
does.

**Merging.** The pieces' hits are concatenated in piece order and sorted once, stably, by T:
ties keep the x1 order, as in the whole file's sort.

Qt-free; standard library and NumPy only.
"""
from __future__ import annotations

from concurrent.futures import Executor
import math

import numpy as np
import numpy.typing as npt

from helab.convert.profile import DetectorProfile
from helab.convert.raw import RawPulses
from helab.convert.reconstruct import DEFAULT_BACKEND, Hits, NoRowsError, reconstruct

Floats = npt.NDArray[np.float64]
MIN_ROWS = 50_000  # below this a piece isn't worth handing to another worker


def cut_threshold(profile: DetectorProfile) -> float:
    """The smallest gap (bins) a cut may go in: more than this is safe."""
    dead_times = (profile.dead_time_x1, profile.dead_time_x2, profile.dead_time_y1, profile.dead_time_y2)
    return max([profile.search_window] + [dead_time / profile.bin_time for dead_time in dead_times if dead_time > 0])


def sorted_rows(pulses: RawPulses, profile: DetectorProfile) -> tuple[Floats, Floats]:
    """Channels and times sorted by time (stable, NaN last), less the first raw row's time."""
    order = np.argsort(pulses.times, kind="stable")
    t = pulses.times[order]
    if profile.subtract_time_zero and len(pulses):
        t = t - pulses.times[0]
    return pulses.channels[order], t


def plan_cuts(t: Floats, profile: DetectorProfile, pieces: int | None, min_rows: int = MIN_ROWS) -> list[int]:
    """The rows where pieces start (after the first): at safe gaps, each piece at least
    ``min_rows`` long and, when ``pieces`` is given, about len/pieces long."""
    n = t.shape[0]
    target = max(min_rows, math.ceil(n / pieces) if pieces else 1)
    gaps = (np.flatnonzero(np.diff(t) > cut_threshold(profile)) + 1).tolist()
    cuts: list[int] = []
    last = 0
    for gap in gaps:
        if gap - last >= target and n - gap >= min_rows:
            cuts.append(gap)
            last = gap
    return cuts


def _run(channels: Floats, times: Floats, profile: DetectorProfile, backend: str) -> Hits:
    return reconstruct(RawPulses(channels=channels, times=times), profile, backend)


def reconstruct_split(pulses: RawPulses, profile: DetectorProfile, backend: str = DEFAULT_BACKEND, *,
                      executor: Executor | None = None, max_pieces: int | None = None,
                      min_rows: int = MIN_ROWS) -> Hits:
    """``reconstruct(pulses, profile, backend)``, by pieces: about ``len / max_pieces`` rows each
    and at least ``min_rows`` (``max_pieces=None``: as many as the gaps allow; the tests force
    small pieces with ``min_rows=1``). One piece is the whole file, reconstructed as it is."""
    n = len(pulses)
    if n == 0 and profile.subtract_time_zero:
        raise NoRowsError("The raw file has no rows (MATLAB fails at t_zero, L62)")
    ch, t = sorted_rows(pulses, profile)
    cuts = plan_cuts(t, profile, max_pieces, min_rows)
    if not cuts:
        return reconstruct(pulses, profile, backend)
    starts = [0] + cuts
    ends = cuts + [n]
    base = profile.replace(subtract_time_zero=False, matlab_overflow_row=False)
    later = base.replace(skip_first_sorted_row=False)
    jobs = [(ch[a:b], t[a:b], base if a == 0 else later) for a, b in zip(starts, ends)]
    if executor is None:
        parts = [_run(c, x, p, backend) for c, x, p in jobs]
    else:
        parts = list(executor.map(_run, *zip(*jobs), [backend] * len(jobs)))

    hits = sum(part.shape[0] for part in parts)
    if profile.matlab_overflow_row and hits + 1 > n // 4:
        last = max((k for k, part in enumerate(parts) if part.shape[0]), default=0)
        start = starts[last]
        tail = profile.replace(subtract_time_zero=False,
                               skip_first_sorted_row=profile.skip_first_sorted_row and start == 0)
        parts = parts[:last] + [_run(ch[start:], t[start:], tail, backend)]
    merged = np.concatenate(parts) if parts else np.empty((0, 3))
    return merged[np.argsort(merged[:, 0], kind="stable")]
