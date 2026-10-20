"""Peaks in a histogram of arrival times (T), for the release-time detection (D8).

The method is Transfer fractions' order detection's (``transfer_fractions.detect``): bins
half the shortest T interval holding a tenth of the events (inside the tallest peak, whatever
the spread of stray events), a light Gaussian smoothing, ``scipy.signal.find_peaks`` with a
prominence floor, each peak's full width at half maximum on its nearer side, and its position
refined to the mean time of the events near it. It is written here on its own rather than
imported, so the plot keeps its behaviour and its module; Transfer fractions could switch to
it later (proposed for Tony: the only part the two may share). Where it differs:
- few events: the bins are half the shortest interval holding ``DENSEST_EVENTS``, and
  ``MIN_BINS`` gives way to ``MIN_EVENTS_PER_BIN``, so a sparse cloud's top still clears the
  prominence floor;
- times recorded on a coarse grid (rounded) get bins of whole grid steps, centred on the
  grid, never finer than one step;
- a peak in the first or last bin counts, and peaks that refine to within half a FWHM of a
  taller one are that one (bumps on a broad peak);
- the smoothing keeps the histogram's length when the kernel is longer than it.

Pure NumPy/SciPy, no Qt. Inputs are never written to.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import cast

import numpy as np
import numpy.typing as npt
from scipy.signal import find_peaks

from helab.analysis.stats import shortest_range

Array = npt.NDArray[np.float64]
DENSEST_SHARE = 0.1  # the bin width is half the shortest interval holding this share of the events …
# … or this many events, if more: with few events, a tenth of them gives bins too fine for the
# top to clear PROMINENCE_COUNTS (a 50-event cloud's top bin would hold ~2 events).
DENSEST_EVENTS = 40
MIN_EVENTS_PER_BIN = 8  # MIN_BINS gives way to this many events per bin on average, for few events
QUANTISED_STEPS = 20  # bins narrower than this many of the times' resolution are whole steps of it
MIN_BINS = 50
MAX_BINS = 20_000
DENSE_SHARE = 0.99  # with the bins capped, bin only the shortest interval holding this share
SMOOTHING_BINS = 1.5  # Gaussian σ of the smoothing, in bins
PROMINENCE_SHARE = 0.02  # a peak's least prominence, as a share of the tallest's height …
PROMINENCE_COUNTS = 4.0  # … and in smoothed events per bin, against noise in sparse bins


@dataclass(frozen=True)
class Peak:
    position: float  # the mean time of the events within one FWHM of the top
    top: float  # the top bin's middle
    height: float  # smoothed events per bin at the top
    fwhm: float  # full width at half maximum, from the nearer side (s)
    events: int  # events within half a FWHM of ``position``


@dataclass(frozen=True)
class PeakSearch:
    """Peaks tallest first, and the histogram they were found in (read-only arrays)."""
    peaks: tuple[Peak, ...]
    edges: Array = field(repr=False)
    counts: Array = field(repr=False)
    smoothed: Array = field(repr=False)
    events: int  # events in the histogram's range

    def __post_init__(self) -> None:
        for array in (self.edges, self.counts, self.smoothed):
            array.flags.writeable = False

    @property
    def step(self) -> float:
        return float(self.edges[1] - self.edges[0]) if len(self.edges) > 1 else math.nan


def smooth(counts: Array, sigma: float = SMOOTHING_BINS) -> Array:
    radius = int(math.ceil(3 * sigma))
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    # "full", then the middle: np.convolve's "same" is as long as the kernel when that's longer.
    return cast(Array, np.convolve(counts, kernel / kernel.sum(), mode="full")[radius:radius + len(counts)])


def half_maximum_width(smoothed: Array, top: int) -> float:
    """Twice the distance, in bins, from ``top`` to where the histogram first falls to half its
    height, on the nearer side (a neighbouring peak above half widens only its own side). At
    least one bin; the whole histogram when it never falls to half."""
    half = float(smoothed[top]) / 2
    distances = []
    for direction in (-1, 1):
        index = top
        while 0 <= index + direction < len(smoothed) and smoothed[index + direction] > half:
            index += direction
        beyond = index + direction
        if 0 <= beyond < len(smoothed):
            above, below = float(smoothed[index]), float(smoothed[beyond])
            distances.append(abs(index - top) + (above - half) / (above - below))
    return 2 * max(min(distances), 0.5) if distances else float(len(smoothed))


def refine(times: Array, position: float, reach: float) -> float:
    """The mean time within ``reach`` of ``position``, repeated so a start off the middle
    doesn't pull it."""
    for _ in range(3):
        near = times[np.abs(times - position) <= reach]
        position = float(near.mean()) if len(near) else position
    return position


def resolution(values: Array) -> float:
    """The smallest gap between distinct values: the grid step of times recorded on one (tiny,
    so it changes nothing, for times that aren't); 0 for fewer than two distinct values."""
    distinct = np.unique(values)
    return float(np.min(np.diff(distinct))) if len(distinct) > 1 else 0.0


def find_time_peaks(times: npt.ArrayLike, lower: float | None = None, upper: float | None = None) -> PeakSearch:
    """The peaks of the T histogram of ``times`` over [lower, upper] (the events' extent where
    not given). Non-finite times are left out. No peaks for no events."""
    values = np.asarray(times, dtype=np.float64).ravel()
    values = values[np.isfinite(values)]
    low = float(values.min()) if lower is None and len(values) else (lower if lower is not None else 0.0)
    high = float(values.max()) if upper is None and len(values) else (upper if upper is not None else 1.0)
    values = values[(values >= low) & (values <= high)]
    if len(values) == 0 or not high > low:
        edges = np.array([low, high if high > low else low + 1.0])
        empty = np.zeros(1)
        return PeakSearch((), edges, empty, empty.copy(), len(values))
    share = max(DENSEST_SHARE, min(DENSEST_EVENTS / len(values), 1.0))
    densest_low, densest_high = shortest_range(values, share)
    width = (densest_high - densest_low) / 2
    wanted = math.ceil((high - low) / width) if width > 0 else MAX_BINS
    if wanted > MAX_BINS:  # stray events far out: bin only where nearly all the events are
        dense_low, dense_high = shortest_range(values, DENSE_SHARE)
        pad = (dense_high - dense_low) * 0.05
        low, high = max(low, dense_low - pad), min(high, dense_high + pad)
        wanted = math.ceil((high - low) / width) if width > 0 else MAX_BINS
    grid = resolution(values)
    if grid > 0 and width < QUANTISED_STEPS * grid:  # times on a grid: whole steps, centred on it
        width = max(1, round(width / grid)) * grid
        low -= grid / 2
        bins = min(max(math.ceil((high - low) / width), 1), MAX_BINS)
        high = low + bins * width
    else:
        bins = min(max(wanted, min(MIN_BINS, len(values) // MIN_EVENTS_PER_BIN)), MAX_BINS)
    counts, edges = np.histogram(values, bins=bins, range=(low, high))
    counts_f = counts.astype(np.float64)
    smoothed = smooth(counts_f)
    middles = (edges[:-1] + edges[1:]) / 2
    step = float(edges[1] - edges[0])
    tallest = float(smoothed.max())
    prominence = max(tallest * PROMINENCE_SHARE, PROMINENCE_COUNTS)
    # Pad with zeros so a peak in the first or last bin still counts.
    found, _ = find_peaks(np.concatenate(([0.0], smoothed, [0.0])), prominence=prominence)
    peaks = []
    for index in (int(p) - 1 for p in found):
        fwhm = half_maximum_width(smoothed, index) * step
        position = refine(values, float(middles[index]), fwhm)
        events = int(np.count_nonzero(np.abs(values - position) <= fwhm / 2))
        peaks.append(Peak(position, float(middles[index]), float(smoothed[index]), fwhm, events))
    peaks.sort(key=lambda peak: -peak.height)
    # Bumps on one broad peak refine to the same place: keep the tallest of those.
    kept: list[Peak] = []
    for peak in peaks:
        if all(abs(peak.position - other.position) > min(peak.fwhm, other.fwhm) / 2 for other in kept):
            kept.append(peak)
    peaks = kept
    return PeakSearch(tuple(peaks), edges, counts_f, smoothed, int(counts.sum()))
