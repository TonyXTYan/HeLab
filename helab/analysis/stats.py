"""Numerical building blocks for the first analyses: auto-crop, display sampling, counts
and histograms. Pure NumPy, no Qt, so they run in the analysis worker and in tests."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable

import numpy as np
import numpy.typing as npt

from helab.analysis.dataset_view import DatasetView, Events
from helab.analysis.results import Cancelled

AXES = ("T", "X", "Y")
# TXY columns as the helper reads them (``io_helper.read_txy``): seconds and metres.
UNITS = ("s", "m", "m")
DISPLAY_CAP = 100_000
DEFAULT_KEEP = 0.99
MAX_BINS = 2000


@dataclass(frozen=True)
class CropBox:
    """An axis-aligned box over the T/X/Y columns and how many events it holds."""
    lower: tuple[float, ...]
    upper: tuple[float, ...]
    kept: int
    total: int
    keep: float  # the requested fraction (nan for a manual box)
    left_out: int  # events outside the box
    manual: bool = False  # the user's bounds, not auto-crop

    @property
    def fraction(self) -> float:
        return self.kept / self.total if self.total else 1.0

    def contains(self, events: Events) -> npt.NDArray[np.bool_]:
        lower, upper = np.asarray(self.lower), np.asarray(self.upper)
        return np.all((events >= lower) & (events <= upper), axis=1)


class _Face:
    """One end of one axis while peeling: events in sorted order from that end."""

    def __init__(self, axis: int, values: npt.NDArray[np.float64], order: npt.NDArray[np.intp], step: int) -> None:
        self.axis, self.values, self.order, self.step = axis, values, order, step
        self.position = 0 if step > 0 else len(order) - 1
        self.group: list[int] = []  # the remaining events at this end's value
        self.value = self.next = math.nan
        self.next_event = -1
        self.peeled = 0  # events left out from this end so far

    def look(self, removed: npt.NDArray[np.bool_]) -> None:
        """Find this end's value, the remaining events at it, and the next value inward."""
        values, order, step, n = self.values, self.order, self.step, len(self.order)
        position = self.position
        while 0 <= position < n and removed[order[position]]:
            position += step
        self.position, self.group, self.next_event = position, [], -1
        if not 0 <= position < n:
            self.value = self.next = math.nan
            return
        self.value = float(values[position])
        while 0 <= position < n and values[position] == self.value:
            if not removed[order[position]]:
                self.group.append(int(order[position]))
            position += step
        while 0 <= position < n and removed[order[position]]:
            position += step
        if 0 <= position < n:
            self.next, self.next_event = float(values[position]), int(order[position])
        else:
            self.next = math.nan


def shortest_window(ordered: npt.NDArray[np.float64], m: int) -> tuple[float, float]:
    """The exact shortest interval holding m of these sorted values (a sliding window over
    them). Among equally short windows, the middle one."""
    widths = ordered[m - 1:] - ordered[:len(ordered) - m + 1]
    ties = np.flatnonzero(widths == widths.min())
    start = int(ties[len(ties) // 2])
    return float(ordered[start]), float(ordered[start + m - 1])


def crop_box(events: Events, keep: float = DEFAULT_KEEP,
             cancelled: Callable[[], bool] | None = None) -> CropBox:
    """The auto-crop box holding at least ``keep`` of the events: the one place the crop
    rule lives (the scatter's Auto-crop keep % calls only this).

    A heuristic, not the narrowest possible box:
    1. Peel: start from the box around every event and repeatedly leave out the events at
       one end of one axis, choosing the end whose removal narrows its axis the most,
       relative to that axis's current width, per event left out; stop before the box
       would hold fewer than ceil(keep · n) events.
    2. Narrow: give each axis in turn the exact shortest window holding ceil(keep · n) of
       the events inside the box's other axes, and repeat while any axis gets narrower
       (at most ``NARROW_ROUNDS`` rounds). This recovers what step 1's one-step choices
       miss, such as a gap behind a clustered tail.
    Sparse tails go first, one-sided ones included (late T events). ``keep`` ≥ 1 gives the
    full extent. Nothing is sampled here. ``cancelled`` is polled; it raises ``Cancelled``.
    """
    events = np.asarray(events, dtype=np.float64)
    total = len(events)
    columns = events.shape[1] if events.ndim == 2 else 3
    if total == 0:
        nan = (math.nan,) * columns
        return CropBox(nan, nan, 0, 0, keep, 0)
    needed = max(1, math.ceil(min(max(keep, 0.0), 1.0) * total))
    lower, upper = _peel(events, needed, cancelled)
    _narrow(events, lower, upper, needed, cancelled)
    box = CropBox(tuple(float(v) for v in lower), tuple(float(v) for v in upper), 0, total, keep, 0)
    kept = int(np.count_nonzero(box.contains(events)))
    return CropBox(box.lower, box.upper, kept, total, keep, total - kept)


NARROW_ROUNDS = 4


def _check(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise Cancelled()


def _peel(events: Events, needed: int, cancelled: Callable[[], bool] | None
          ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    total, columns = events.shape
    removed = np.zeros(total, dtype=bool)
    faces: list[_Face] = []
    for axis in range(columns):
        order = np.argsort(events[:, axis], kind="stable")
        values = events[order, axis]
        faces += [_Face(axis, values, order, 1), _Face(axis, values, order, -1)]
    for face in faces:
        face.look(removed)
    remaining = total
    steps = 0
    while True:
        steps += 1
        if steps % 4096 == 0:
            _check(cancelled)
        best: _Face | None = None
        gain = 0.0
        for face in faces:
            if not face.group or math.isnan(face.next):
                continue
            low, high = faces[2 * face.axis], faces[2 * face.axis + 1]
            width = high.value - low.value
            if width <= 0 or remaining - len(face.group) < needed:
                continue
            score = abs(face.next - face.value) / width / len(face.group)
            # On a tie, the end that has left out fewer events: symmetric data is cut symmetrically.
            if best is None or score > gain * (1 + 1e-9) or (
                    score >= gain * (1 - 1e-9) and face.peeled < best.peeled):
                best, gain = face, score
        if best is None:
            break
        removed[best.group] = True
        remaining -= len(best.group)
        best.peeled += len(best.group)
        for face in faces:
            # Only ends whose events were just left out need looking at again.
            if face is best or removed[face.group].any() or (face.next_event >= 0 and removed[face.next_event]):
                face.look(removed)
    lower = np.array([faces[2 * axis].value for axis in range(columns)])
    upper = np.array([faces[2 * axis + 1].value for axis in range(columns)])
    return lower, upper


def _narrow(events: Events, lower: npt.NDArray[np.float64], upper: npt.NDArray[np.float64],
            needed: int, cancelled: Callable[[], bool] | None) -> None:
    """Step 2 of ``crop_box``, in place."""
    columns = events.shape[1]
    for _ in range(NARROW_ROUNDS):
        narrowed = False
        for axis in range(columns):
            _check(cancelled)
            others = [other for other in range(columns) if other != axis]
            inside = np.all((events[:, others] >= lower[others]) & (events[:, others] <= upper[others]), axis=1)
            values = np.sort(events[inside, axis])
            if len(values) < needed:
                continue
            low, high = shortest_window(values, needed)
            if high - low < upper[axis] - lower[axis]:
                lower[axis], upper[axis] = low, high
                narrowed = True
        if not narrowed:
            return


def display_sample(count: int, cap: int = DISPLAY_CAP, seed: int = 0) -> npt.NDArray[np.intp]:
    """Row indices to draw: all of them up to ``cap``, else a fixed-seed random sample
    (sorted). Only for display; the analysed data is never the sample."""
    if count <= cap:
        return np.arange(count)
    return np.sort(np.random.default_rng(seed).choice(count, size=cap, replace=False))


def counts_per_shot(view: DatasetView, shots: Iterable[int] | None = None
                    ) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:
    """(shot numbers, events per shot) of the chosen shots (default: all), ascending by shot."""
    chosen = list(view.shots if shots is None else shots)
    shots = np.fromiter(chosen, dtype=np.int64, count=len(chosen))
    counts = np.fromiter((len(view.shots[int(shot)]) for shot in shots), dtype=np.int64, count=len(shots))
    return shots, counts


def shortest_range(values: npt.NDArray[np.float64], keep: float = DEFAULT_KEEP) -> tuple[float, float]:
    """The exact shortest interval holding ceil(keep · n) of the values (a sorted sliding
    window); the full extent when ``keep`` ≥ 1. (nan, nan) for no values."""
    if len(values) == 0:
        return math.nan, math.nan
    needed = max(1, math.ceil(min(max(keep, 0.0), 1.0) * len(values)))
    return shortest_window(np.sort(values), needed)


def freedman_diaconis_bins(values: npt.NDArray[np.float64], lower: float, upper: float) -> int:
    """Bins over [lower, upper] of width 2·IQR·n^(-1/3); Sturges' rule when the IQR is 0.
    Clamped to 1…MAX_BINS."""
    inside = values[(values >= lower) & (values <= upper)]
    n = len(inside)
    if n < 2 or not upper > lower:
        return 1
    q1, q3 = np.percentile(inside, [25, 75])
    width = 2 * float(q3 - q1) * n ** (-1 / 3)
    bins = math.ceil((upper - lower) / width) if width > 0 else math.ceil(math.log2(n) + 1)
    return min(max(bins, 1), MAX_BINS)


@dataclass(frozen=True)
class Histogram:
    axis: str
    edges: npt.NDArray[np.float64]
    counts: npt.NDArray[np.int64]
    total: int
    outside: int  # events outside [edges[0], edges[-1]]
    automatic_bins: bool


def histogram(values: npt.NDArray[np.float64], axis: str, keep: float = DEFAULT_KEEP,
              bins: int = 0, bounds: tuple[float, float] | None = None) -> Histogram:
    """A histogram over the shortest range holding ``keep`` of the values, or over ``bounds``
    when given. ``bins`` 0 picks the count automatically (Freedman–Diaconis).
    counts.sum() + outside == total."""
    total = len(values)
    lower, upper = bounds if bounds is not None else shortest_range(values, keep)
    if total == 0:
        edges = np.array([lower, upper]) if bounds is not None and upper > lower else np.array([0.0, 1.0])
        return Histogram(axis, edges, np.zeros(1, dtype=np.int64), 0, 0, bins <= 0)
    if not upper > lower:  # all values equal: one bin around them
        lower, upper = lower - 0.5, upper + 0.5
    count = bins if bins > 0 else freedman_diaconis_bins(values, lower, upper)
    counts, edges = np.histogram(values, bins=count, range=(lower, upper))
    counts = counts.astype(np.int64)
    return Histogram(axis, edges, counts, total, total - int(counts.sum()), bins <= 0)
