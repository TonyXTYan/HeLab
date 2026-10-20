"""The hot-spot finder's placeholder (D15): bins of the XY image summed over the chosen shots that
stand far above the image's median, grouped into circles a user reviews and may copy into a
plot's Mask (``masks``). It never applies them itself.

The rule (the roadmap's placeholder, with a noise floor added; proposed, for Tony):
- the image: the events' X and Y in bins of a set width (0.5 mm by default) over the view range;
- the background: the median over the image's bins, or, when more than half the bins are empty,
  over the bins with events (the plot says so);
- a bin is flagged when its count is above ``factor`` × the background (5 by default) **and**
  above the background + ``NOISE_SIGMAS`` (5) × √background, so Poisson noise on a sparse image
  (a background of a few counts) isn't flagged;
- flagged bins that touch (sides or corners) form one spot: its centre is the mean of their bin
  centres weighted by their excess over the background, its radius reaches the farthest flagged
  bin's centre plus half a bin's diagonal, so the circle covers every flagged bin's centre and
  most of each bin.

It finds anything bright: an atom cloud in the window is a "spot" too, so use a T window without
atoms (manual View range), as the roadmap's finder will. The real finder (persistence across
shots, a smoothed background) is designed later on the current detector's data."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy import ndimage

from helab.analysis.masks import Circle, format_circles

DEFAULT_FACTOR = 5.0
NOISE_SIGMAS = 5.0
DEFAULT_BIN = 0.5e-3  # m
MAX_BINS = 1000  # per axis: wider bins beyond it (the plot says so)
MAX_SPOTS = 50  # the strongest spots offered; the rest are counted


@dataclass(frozen=True)
class HotSpot:
    circle: Circle  # a cut circle, in m
    bins: int  # flagged bins in it
    counts: int  # events in its flagged bins
    excess: float  # of them, above the background
    peak: float  # its brightest bin over the background (× median)


@dataclass(frozen=True)
class HotSpotSearch:
    image: npt.NDArray[np.float64]  # (x bins, y bins): events per bin
    edges_x: npt.NDArray[np.float64]
    edges_y: npt.NDArray[np.float64]
    background: float  # the median the threshold is a multiple of
    threshold: float  # bins above it are flagged
    factor: float
    spots: tuple[HotSpot, ...]  # strongest first, at most MAX_SPOTS
    flagged: int = 0  # flagged bins in all
    left_out: int = 0  # spots beyond MAX_SPOTS
    notes: tuple[str, ...] = ()  # how the background or bins were chosen

    @property
    def circles(self) -> tuple[Circle, ...]:
        return tuple(spot.circle for spot in self.spots)

    def text(self) -> str:
        """The spots as a Mask's custom circles (cut), one per line."""
        return format_circles(self.circles)


def background_of(image: npt.NDArray[np.float64]) -> tuple[float, str]:
    """The image's median, or with more than half its bins empty, the median of the others (and a
    note saying so); 0 for an empty image."""
    values = image.ravel()
    median = float(np.median(values)) if values.size else 0.0
    if median > 0:
        return median, ""
    filled = values[values > 0]
    if not filled.size:
        return 0.0, ""
    return float(np.median(filled)), "most bins empty: background = median of the bins with events"


def threshold_of(background: float, factor: float) -> float:
    """Counts a bin must exceed: ``factor`` × background and background + 5 √background (at least
    one event: a bin of one event in an empty image isn't a spot)."""
    return max(factor * background, background + NOISE_SIGMAS * math.sqrt(background), 1.0)


def bin_edges(low: float, high: float, width: float) -> tuple[npt.NDArray[np.float64], bool]:
    """Edges of bins ``width`` wide from ``low`` past ``high`` (at most ``MAX_BINS``: then
    wider, and True)."""
    span = max(high - low, width)
    count = max(1, math.ceil(span / width - 1e-9))
    widened = count > MAX_BINS
    if widened:
        count, width = MAX_BINS, span / MAX_BINS
    return (low + width * np.arange(count + 1)).astype(np.float64), widened


def find_hot_spots(x: npt.NDArray[np.float64], y: npt.NDArray[np.float64], span_x: tuple[float, float],
                   span_y: tuple[float, float], width: float = DEFAULT_BIN, factor: float = DEFAULT_FACTOR
                   ) -> HotSpotSearch:
    """Hot spots in the XY image of ``x``, ``y`` (m) over the spans, in bins ``width`` wide."""
    edges_x, wide_x = bin_edges(*span_x, width)
    edges_y, wide_y = bin_edges(*span_y, width)
    image = np.histogram2d(x, y, bins=(edges_x, edges_y))[0]
    notes: list[str] = []
    if wide_x or wide_y:
        notes.append(f"bins widened to keep the image at most {MAX_BINS:,} bins a side")
    background, note = background_of(image)
    if note:
        notes.append(note)
    threshold = threshold_of(background, factor)
    flagged = image > threshold
    labelled: Any = ndimage.label(flagged, structure=np.ones((3, 3), dtype=bool))
    labels: npt.NDArray[np.intp] = np.asarray(labelled[0], dtype=np.intp)
    count = int(labelled[1])
    if not count:
        return HotSpotSearch(image, edges_x, edges_y, background, threshold, factor, (), 0, 0, tuple(notes))
    ix, iy = np.nonzero(flagged)
    ids: npt.NDArray[np.intp] = labels[ix, iy] - 1
    cx = ((edges_x[:-1] + edges_x[1:]) / 2)[ix]
    cy = ((edges_y[:-1] + edges_y[1:]) / 2)[iy]
    counts = image[ix, iy]
    excess = counts - background
    total = np.bincount(ids, weights=excess, minlength=count)
    centre_x = np.bincount(ids, weights=excess * cx, minlength=count) / total
    centre_y = np.bincount(ids, weights=excess * cy, minlength=count) / total
    reach = np.zeros(count)
    np.maximum.at(reach, ids, np.hypot(cx - centre_x[ids], cy - centre_y[ids]))
    half_diagonal = math.hypot(float(edges_x[1] - edges_x[0]), float(edges_y[1] - edges_y[0])) / 2
    radius = reach + half_diagonal
    bins = np.bincount(ids, minlength=count)
    events = np.bincount(ids, weights=counts, minlength=count)
    peak = np.zeros(count)
    np.maximum.at(peak, ids, counts)
    order = np.argsort(-total, kind="stable")
    spots = tuple(HotSpot(Circle(float(centre_x[i]), float(centre_y[i]), _round_up(float(radius[i]))),
                          int(bins[i]), int(events[i]), float(total[i]),
                          float(peak[i] / background) if background > 0 else math.inf)
                  for i in order[:MAX_SPOTS])
    return HotSpotSearch(image, edges_x, edges_y, background, threshold, factor, spots, int(flagged.sum()),
                         max(0, count - MAX_SPOTS), tuple(notes))


def _round_up(radius: float) -> float:
    """A radius rounded up to 0.01 mm (the circle never shrinks in the text)."""
    return math.ceil(radius * 1e5 - 1e-9) / 1e5


def search_lines(search: HotSpotSearch) -> list[str]:
    """For the record: the rule, then each spot."""
    lines = [f"Hot-spot search: bins of {_mm(float(search.edges_x[1] - search.edges_x[0]))} mm, background "
             f"(median) {search.background:,.3g} events per bin, flagged above {search.threshold:,.3g} "
             f"({search.factor:g} × median and median + {NOISE_SIGMAS:g} √median): {search.flagged:,} bins, "
             f"{len(search.spots) + search.left_out:,} spots", *search.notes]
    for number, spot in enumerate(search.spots, start=1):
        circle = spot.circle
        lines.append(f"Spot {number}: x {_mm(circle.x)} mm, y {_mm(circle.y)} mm, r {_mm(circle.r)} mm · "
                     f"{spot.bins:,} bins, {spot.counts:,} events ({spot.excess:,.0f} above background), "
                     f"peak {spot.peak:,.3g} × median")
    if search.left_out:
        lines.append(f"{search.left_out:,} weaker spots not listed (at most {MAX_SPOTS})")
    return lines


def _mm(metres: float) -> str:
    """A length in mm to 0.01 mm, with the plots' minus sign."""
    return f"{metres * 1e3:,.2f}".replace("-", "−")
