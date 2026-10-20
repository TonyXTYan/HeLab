"""Per-shot trends (D2): each shot's counts in a box, its centre and width along T, X and Y,
moving means ± SD over the shots, and the low-count rules. No Qt and no I/O: the Shot trends
plot computes with these in the analysis worker, and tests call them directly.

Centre and width, per shot and axis, from the shot's histogram of the events inside the box:
- **Gaussian fit** (``fits.fit_histogram``, Poisson weights): the fitted centre and σ, ± SE.
- **Threshold edges** (the legacy ``find_dist_cen``, its bugs left behind): the outermost
  points where the histogram crosses a fraction of its highest bin, interpolated linearly
  between bin centres; the centre is their midpoint and the width their distance. No SE. Its
  Gaussian-equivalent σ (a Gaussian's full width at fraction f is 2σ√(2 ln 1/f)) gives the
  temperature.

Per-shot results are reused (``ShotCache``): keyed by the folder, the shot's number and
fingerprint and every setting that changes them (the box included), so Live's next revision
estimates only its new shots. A range found in the data (auto-crop) is rounded out and kept
from run to run while the data's range stays inside it (``ShotCache.stable_range``), so new
shots don't move the box. The cache is bounded and thread-safe (the worker computes; a
test or a second plot may read).
"""
from __future__ import annotations

import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Hashable, Optional, Sequence

import numpy as np
import numpy.typing as npt

from helab.analysis.estimates import Estimate
from helab.analysis.fits import bin_centres, fit_histogram
from helab.analysis.stats import histogram

Array = npt.NDArray[np.float64]
Bounds = tuple[float, float]

FIT, EDGES = "Gaussian fit", "threshold edges"
METHODS = (EDGES, FIT)
NAN = Estimate(math.nan, math.nan)


# One shot

@dataclass(frozen=True)
class AxisEstimate:
    """One shot's centre and width along one axis (s or m), and the σ a temperature uses: the
    fitted σ, or the threshold width's Gaussian-equivalent σ. ``failure`` says why there is none."""
    centre: Estimate = NAN
    width: Estimate = NAN
    sigma: Estimate = NAN
    failure: str = ""

    @property
    def ok(self) -> bool:
        return not self.failure


@dataclass(frozen=True)
class ShotEstimate:
    count: int  # events inside the box
    axes: tuple[AxisEstimate, ...]  # T, X, Y


def gaussian_equivalent(width: float, fraction: float) -> float:
    """The σ of a Gaussian whose full width at ``fraction`` of its peak is ``width``."""
    if not 0 < fraction < 1:
        return math.nan
    return width / (2 * math.sqrt(2 * math.log(1 / fraction)))


def threshold_edges(edges: npt.ArrayLike, counts: npt.ArrayLike, fraction: float) -> tuple[float, float, str]:
    """(centre, width, failure) from where the histogram crosses ``fraction`` of its highest bin:
    the outermost bins at or above that level, each edge interpolated between its bin's centre
    and the next one out (the histogram's own edge when the bin is the first or last)."""
    edges = np.asarray(edges, dtype=np.float64)
    values = np.asarray(counts, dtype=np.float64)
    if not len(values) or not values.max() > 0:
        return math.nan, math.nan, "no counts"
    if not 0 < fraction < 1:
        return math.nan, math.nan, "the threshold must be between 0 and 100 %"
    centres = bin_centres(edges)
    level = fraction * float(values.max())
    above = np.flatnonzero(values >= level)
    first, last = int(above[0]), int(above[-1])

    def crossing(inside: int, outside: int, fallback: float) -> float:
        if not 0 <= outside < len(values):
            return fallback
        low, high = values[outside], values[inside]
        share = (level - low) / (high - low) if high > low else 0.0
        return float(centres[outside] + share * (centres[inside] - centres[outside]))

    left = crossing(first, first - 1, float(edges[0]))
    right = crossing(last, last + 1, float(edges[-1]))
    return (left + right) / 2, right - left, ""


def estimate_axis(values: Array, bounds: Bounds, method: str, bins: int = 0, fraction: float = 0.5,
                  min_events: int = 20) -> AxisEstimate:
    """One shot's centre and width along one axis from its events ``values`` (inside the box)."""
    if len(values) < max(min_events, 2):
        return AxisEstimate(failure=f"fewer than {max(min_events, 2):,} events")
    item = histogram(np.ascontiguousarray(values), "", bins=bins, bounds=bounds)
    if method == FIT:
        fit = fit_histogram(bin_centres(item.edges), item.counts, "gaussian")
        if not fit.ok:
            return AxisEstimate(failure=fit.failure)
        sigma = fit["sigma"]
        return AxisEstimate(fit["centre"], sigma, sigma)
    centre, width, failure = threshold_edges(item.edges, item.counts, fraction)
    if failure:
        return AxisEstimate(failure=failure)
    return AxisEstimate(Estimate(centre), Estimate(width), Estimate(gaussian_equivalent(width, fraction)))


def estimate_shot(events: Array, box: Sequence[Bounds], method: str, bins: int = 0, fraction: float = 0.5,
                  min_events: int = 20) -> ShotEstimate:
    """A shot's events (n, 3) inside ``box`` (one (low, high) per axis): their count and, per
    axis, ``estimate_axis``."""
    inside = np.ones(len(events), dtype=bool)
    for axis, (low, high) in enumerate(box):
        inside &= (events[:, axis] >= low) & (events[:, axis] <= high)
    kept = events[inside]
    axes = tuple(estimate_axis(kept[:, axis], box[axis], method, bins, fraction, min_events)
                 for axis in range(len(box)))
    return ShotEstimate(int(inside.sum()), axes)


class ShotCache:
    """Per-shot estimates by key (its first item the folder), least recently used dropped beyond
    ``limit``, and the ranges each plot keeps (``stable_range``, keys starting with the plot's
    owner); thread-safe. A plot that closes drops its ranges, and its folder's estimates when no
    other plot uses that folder (``plot_closed``). Outside the RAM budget, so kept small: an
    estimate is about 2 KB of Python objects, so ``limit`` 8,000 is about 16 MB."""

    def __init__(self, limit: int = 8_000) -> None:
        self.limit = limit
        self._items: OrderedDict[Hashable, ShotEstimate] = OrderedDict()
        self._ranges: OrderedDict[Hashable, Bounds] = OrderedDict()
        self._owners: dict[str, Hashable] = {}  # plot → the folder it last ran on
        self._lock = threading.Lock()

    def note_owner(self, owner: str, folder: Hashable) -> None:
        """``owner`` (a plot) uses ``folder``'s estimates."""
        if owner:
            with self._lock:
                self._owners[owner] = folder

    def plot_closed(self, owner: str) -> None:
        """Drop the ranges ``owner`` kept and, when no other plot uses its folder, that folder's
        estimates."""
        with self._lock:
            folder = self._owners.pop(owner, None)
            for key in [key for key in self._ranges if isinstance(key, tuple) and key and key[0] == owner]:
                del self._ranges[key]
            if folder is None or folder in self._owners.values():
                return
            for key in [key for key in self._items if isinstance(key, tuple) and key and key[0] == folder]:
                del self._items[key]

    def get(self, key: Hashable) -> Optional[ShotEstimate]:
        with self._lock:
            found = self._items.get(key)
            if found is not None:
                self._items.move_to_end(key)
            return found

    def put(self, key: Hashable, value: ShotEstimate) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self.limit:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._ranges.clear()

    def stable_range(self, key: Hashable, low: float, high: float) -> tuple[Bounds, bool]:
        """A data-derived range for the run ``key`` names (the plot, its folder, the axis and the
        settings that find it, the Shots selection included): that plot's previous run's while [low, high] still lies inside it and fills at least ``1 / KEEP_SLACK`` of it,
        else ``snapped(low, high)``. Whether the previous one was kept. Live's next shots then
        keep the box, and their per-shot results (keyed on it) are reused."""
        with self._lock:
            previous = self._ranges.get(key)
            if previous is not None and previous[0] <= low and high <= previous[1] \
                    and previous[1] - previous[0] <= KEEP_SLACK * (high - low):
                self._ranges.move_to_end(key)
                return previous, True
            found = snapped(low, high)
            self._ranges[key] = found
            self._ranges.move_to_end(key)
            while len(self._ranges) > RANGE_LIMIT:
                self._ranges.popitem(last=False)
            return found, False

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


CACHE = ShotCache()


# The box

SNAP_STEPS = 20  # a data-derived range is rounded out to steps of about 1/20 of its width
KEEP_SLACK = 1.5  # … and kept while the data's range fills at least 2/3 of it (``ShotCache.stable_range``)
RANGE_LIMIT = 1024


def nice_step(size: float) -> float:
    """The largest 1, 2 or 5 × 10^k not above ``size`` (nan for none)."""
    if not size > 0 or not math.isfinite(size):
        return math.nan
    power = 10.0 ** math.floor(math.log10(size))
    return max(step * power for step in (1.0, 2.0, 5.0) if step * power <= size * (1 + 1e-12))


def snapped(low: float, high: float, steps: int = SNAP_STEPS) -> Bounds:
    """[low, high] rounded out to a multiple of ``nice_step(width / steps)``, with one more step
    each side: a range found in the data then holds a little more than the data, so new shots
    seldom move it (``ShotCache.stable_range``). Unchanged when it has no width."""
    step = nice_step((high - low) / steps)
    if not math.isfinite(step):
        return low, high
    return math.floor(low / step) * step - step, math.ceil(high / step) * step + step


# Over the shots

def moving_stats(values: npt.ArrayLike, window: int) -> tuple[Array, Array]:
    """The trailing moving mean and SD (n − 1) over the last ``window`` shots, each shot's own
    included; values that aren't finite are left out of their windows. The mean is nan where a
    window has no value, the SD where it has fewer than two."""
    data = np.asarray(values, dtype=np.float64)
    count = len(data)
    if not count:
        return np.empty(0), np.empty(0)
    finite = np.isfinite(data)
    reference = float(data[finite][0]) if finite.any() else 0.0  # sums of offsets: no cancellation
    offsets = np.where(finite, data - reference, 0.0)
    sums = np.concatenate(([0.0], np.cumsum(offsets)))
    squares = np.concatenate(([0.0], np.cumsum(offsets * offsets)))
    numbers = np.concatenate(([0.0], np.cumsum(finite.astype(np.float64))))
    high = np.arange(1, count + 1)
    low = np.maximum(0, high - max(int(window), 1))
    total, total_squares, n = sums[high] - sums[low], squares[high] - squares[low], numbers[high] - numbers[low]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(n > 0, total / n + reference, np.nan)
        variance = np.where(n > 1, (total_squares - total * total / n) / (n - 1), np.nan)
    return mean, np.sqrt(np.clip(variance, 0.0, None))


def previous_means(counts: npt.ArrayLike, window: int) -> Array:
    """Each shot's reference for the fraction rule: the mean count of the ``window`` shots before
    it (itself left out); nan for the first."""
    data = np.asarray(counts, dtype=np.float64)
    if not len(data):
        return np.empty(0)
    sums = np.concatenate(([0.0], np.cumsum(data)))
    high = np.arange(len(data))
    low = np.maximum(0, high - max(int(window), 1))
    n = high - low
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0, (sums[high] - sums[low]) / np.maximum(n, 1), np.nan)


@dataclass(frozen=True)
class LowFlags:
    """Which shots are low, by either enabled rule: fewer than ``absolute`` events, or below
    ``fraction`` of the mean of the ``window`` shots before (``reference``)."""
    low: npt.NDArray[np.bool_]
    below_count: npt.NDArray[np.bool_]
    below_fraction: npt.NDArray[np.bool_]
    reference: Array
    absolute: Optional[int]
    fraction: Optional[float]
    window: int

    @property
    def count(self) -> int:
        return int(self.low.sum())

    def rules_text(self) -> str:
        """``fewer than 50 events or below 50 % of the last 100 shots' mean``; "" with neither."""
        parts = []
        if self.absolute is not None:
            parts.append(f"fewer than {self.absolute:,} events")
        if self.fraction is not None:
            parts.append(f"below {self.fraction * 100:g} % of the last {self.window:,} shots' mean")
        return " or ".join(parts)

    def why(self, index: int) -> str:
        """Why shot ``index`` is low: ``below 50; below 50 % of the last 100 shots' mean (840)``."""
        parts = []
        if self.below_count[index] and self.absolute is not None:
            parts.append(f"below {self.absolute:,}")
        if self.below_fraction[index] and self.fraction is not None:
            parts.append(f"below {self.fraction * 100:g} % of the last {self.window:,} shots' mean "
                         f"({self.reference[index]:,.0f})")
        return "; ".join(parts)


def low_flags(counts: npt.ArrayLike, absolute: Optional[int] = None, fraction: Optional[float] = None,
              window: int = 100) -> LowFlags:
    """The low-count rules (either or both; None turns one off) on counts in shot order."""
    data = np.asarray(counts, dtype=np.float64)
    reference = previous_means(data, window)
    below_count = data < absolute if absolute is not None else np.zeros(len(data), dtype=bool)
    with np.errstate(invalid="ignore"):
        below_fraction = (np.where(np.isfinite(reference), data < fraction * reference, False)
                          if fraction is not None else np.zeros(len(data), dtype=bool))
    below_fraction = np.asarray(below_fraction, dtype=bool)
    return LowFlags(below_count | below_fraction, below_count, below_fraction, reference, absolute, fraction,
                    max(int(window), 1))


def summary(values: npt.ArrayLike) -> tuple[float, float, int]:
    """(mean, SD (n − 1), number) of the finite values; nan where undefined."""
    data = np.asarray(values, dtype=np.float64)
    data = data[np.isfinite(data)]
    if not len(data):
        return math.nan, math.nan, 0
    return float(data.mean()), float(data.std(ddof=1)) if len(data) > 1 else math.nan, len(data)


def json_list(values: npt.ArrayLike) -> list[Any]:
    """Strict JSON: nan and inf as None."""
    return [float(value) if math.isfinite(value) else None for value in np.asarray(values, dtype=np.float64)]
