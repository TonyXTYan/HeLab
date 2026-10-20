"""The hot-spot finder's placeholder (D15): bins of the XY image summed over the chosen shots that
stand out from their **local** background beyond chance, grouped into circles a user reviews and
may copy into a plot's Mask (``masks``). It never applies them itself.

The rule (proposed, for Tony):
- **image:** the events' X and Y in square bins of a set width (0.5 mm by default) over the view
  range (at most ``MAX_BINS`` a side);
- **filled area:** the bins where the image, smoothed over 2 bins, has events at least half as
  often as in its well-filled parts: the detector's disc, not the empty corners around it. Only
  these bins are tested and used as background;
- **local background** λ: the image smoothed with a Gaussian of the background scale (1 mm by
  default) over the filled area, leaving out bins already found in a spot (and a bin around
  them), as a normalised convolution, so uneven gain, the detector's edge and an atom cloud's
  wings set their own level;
- **test:** a bin is significant when P(N ≥ n | λ) (Poisson) is below α / N_bins, α being the
  false spots allowed per image (0.01 by default) and N_bins the filled bins tested (the
  look-elsewhere correction); its spot then grows over touching bins with P < ``GROW_P``;
- three passes: each recomputes λ without the spots found so far, so a spot doesn't raise its
  own background;
- **a spot** is kept with at least 2 bins or an excess of at least the minimum (20 events by
  default) over λ: centre = the excess-weighted mean of its bin centres, radius = its farthest
  bin centre plus half a bin's diagonal, rounded up to 0.01 mm.

It still finds anything sharper than the background scale: a narrow atom cloud's core can be a
"spot", so use a T window without atoms (manual View range). Spots wider than a few background
scales are found only at their edges. The real finder (persistence across shots) is designed
later on the current detector's data."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy import ndimage, stats

from helab.analysis.masks import Circle, format_circles

DEFAULT_BIN = 0.5e-3  # m
DEFAULT_SCALE = 1e-3  # m: the background's Gaussian σ
DEFAULT_ALPHA = 0.01  # false spots allowed per image
DEFAULT_MIN_EXCESS = 20  # events: a one-bin spot needs this excess
GROW_P = 1e-3  # a spot grows over touching bins this unlikely under the background
FILLED_SHARE = 0.5  # filled area: occupancy at least this share of the well-filled parts'
PASSES = 3
MAX_BINS = 1000  # per axis: wider bins beyond it (the plot says so)
MAX_SPOTS = 50  # the strongest spots offered; the rest are counted
EIGHT = np.ones((3, 3), dtype=bool)  # touching: sides or corners

Bins = npt.NDArray[np.float64]
Flags = npt.NDArray[np.bool_]


@dataclass(frozen=True)
class HotSpot:
    circle: Circle  # a cut circle, in m
    bins: int  # bins in it
    counts: int  # events in its bins
    excess: float  # of them, above the local background
    p_value: float  # its most significant bin's P(N ≥ n | λ)


@dataclass(frozen=True)
class HotSpotSearch:
    image: Bins  # (x bins, y bins): events per bin
    edges_x: Bins
    edges_y: Bins
    background: Bins  # the local background λ per bin (nan outside the filled area)
    tested: int  # filled bins tested
    alpha: float
    scale: float  # the background's σ (m)
    spots: tuple[HotSpot, ...]  # strongest first, at most MAX_SPOTS
    flagged: int = 0  # bins in all spots found (before the minimum)
    dropped: int = 0  # spots left out by the minimum (one bin, small excess)
    left_out: int = 0  # spots beyond MAX_SPOTS
    notes: tuple[str, ...] = ()  # how the bins were chosen (plain notes, not warnings)

    @property
    def circles(self) -> tuple[Circle, ...]:
        return tuple(spot.circle for spot in self.spots)

    @property
    def found(self) -> int:
        return len(self.spots) + self.left_out

    @property
    def p_limit(self) -> float:
        """The per-bin P a significant bin is below: α / bins tested."""
        return self.alpha / max(self.tested, 1)

    def text(self) -> str:
        """The spots as a Mask's custom circles (cut), one per line."""
        return format_circles(self.circles)


def bin_edges(low: float, high: float, width: float) -> tuple[Bins, bool]:
    """Edges of bins ``width`` wide from ``low`` past ``high`` (at most ``MAX_BINS``: then
    wider, and True)."""
    span = max(high - low, width)
    count = max(1, math.ceil(span / width - 1e-9))
    widened = count > MAX_BINS
    if widened:
        count, width = MAX_BINS, span / MAX_BINS
    return (low + width * np.arange(count + 1)).astype(np.float64), widened


def filled_area(image: Bins) -> Flags:
    """The bins where events come at least ``FILLED_SHARE`` as often as in the image's well-filled
    parts (the 90th percentile of the occupancy smoothed over 2 bins): the detector, not the
    empty space around it."""
    occupied = ndimage.gaussian_filter((image > 0).astype(np.float64), 2.0, mode="constant")
    positive = occupied[occupied > 1e-6]
    if not positive.size:
        return np.zeros(image.shape, dtype=bool)
    return np.asarray(occupied >= FILLED_SHARE * float(np.percentile(positive, 90)))


def local_background(image: Bins, used: Flags, sigma_bins: float) -> Bins:
    """λ per bin: the Gaussian-weighted mean of the ``used`` bins around it (nan where none)."""
    weights = used.astype(np.float64)
    total = ndimage.gaussian_filter(image * weights, sigma_bins, mode="constant")
    norm = ndimage.gaussian_filter(weights, sigma_bins, mode="constant")
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(norm > 1e-3, total / norm, np.nan)


def tail(image: Bins, background: Bins) -> Bins:
    """P(N ≥ n | λ) per bin (1 where λ is unknown or n is 0)."""
    known = np.isfinite(background) & (image > 0)
    p = np.ones(image.shape)
    p[known] = stats.poisson.sf(image[known] - 1, np.maximum(background[known], 1e-9))
    return p


def find_hot_spots(x: npt.NDArray[np.float64], y: npt.NDArray[np.float64], span_x: tuple[float, float],
                   span_y: tuple[float, float], width: float = DEFAULT_BIN, scale: float = DEFAULT_SCALE,
                   alpha: float = DEFAULT_ALPHA, min_excess: float = DEFAULT_MIN_EXCESS) -> HotSpotSearch:
    """Hot spots in the XY image of ``x``, ``y`` (m) over the spans, in bins ``width`` wide."""
    edges_x, wide_x = bin_edges(*span_x, width)
    edges_y, wide_y = bin_edges(*span_y, width)
    image = np.histogram2d(x, y, bins=(edges_x, edges_y))[0]
    notes: list[str] = []
    if wide_x or wide_y:
        notes.append(f"bins widened to keep the image at most {MAX_BINS:,} bins a side")
    width_x, width_y = float(edges_x[1] - edges_x[0]), float(edges_y[1] - edges_y[0])
    sigma_bins = max(scale / min(width_x, width_y), 0.5)
    filled = filled_area(image)
    tested = int(filled.sum())
    limit = alpha / max(tested, 1)
    spots_mask = np.zeros(image.shape, dtype=bool)
    background = np.full(image.shape, np.nan)
    p = np.ones(image.shape)
    for _ in range(PASSES):
        exclude: Flags = (np.asarray(ndimage.binary_dilation(spots_mask, EIGHT), dtype=bool) if spots_mask.any()
                          else spots_mask)
        background = local_background(image, filled & ~exclude, sigma_bins)
        p = tail(image, background)
        seeds = filled & (p < limit)
        spread: Flags = np.asarray(ndimage.binary_propagation(seeds, structure=EIGHT, mask=filled & (p < GROW_P)),
                                   dtype=bool)
        grown = spread | seeds
        if np.array_equal(grown, spots_mask):
            break
        spots_mask = grown
    background = np.where(filled, background, np.nan)
    if not spots_mask.any():
        return HotSpotSearch(image, edges_x, edges_y, background, tested, alpha, scale, (), notes=tuple(notes))
    labelled: Any = ndimage.label(spots_mask, structure=EIGHT)
    labels: npt.NDArray[np.intp] = np.asarray(labelled[0], dtype=np.intp)
    count = int(labelled[1])
    ix, iy = np.nonzero(spots_mask)
    ids: npt.NDArray[np.intp] = labels[ix, iy] - 1
    cx = ((edges_x[:-1] + edges_x[1:]) / 2)[ix]
    cy = ((edges_y[:-1] + edges_y[1:]) / 2)[iy]
    counts = image[ix, iy]
    excess = np.maximum(counts - np.nan_to_num(background[ix, iy]), 0.0) + 1e-12
    total = np.bincount(ids, weights=excess, minlength=count)
    centre_x = np.bincount(ids, weights=excess * cx, minlength=count) / total
    centre_y = np.bincount(ids, weights=excess * cy, minlength=count) / total
    reach = np.zeros(count)
    np.maximum.at(reach, ids, np.hypot(cx - centre_x[ids], cy - centre_y[ids]))
    radius = reach + math.hypot(width_x, width_y) / 2
    bins = np.bincount(ids, minlength=count)
    events = np.bincount(ids, weights=counts, minlength=count)
    best = np.ones(count)
    np.minimum.at(best, ids, p[ix, iy])
    kept = [i for i in np.argsort(-total, kind="stable") if bins[i] >= 2 or total[i] >= min_excess]
    spots = tuple(HotSpot(Circle(float(centre_x[i]), float(centre_y[i]), _round_up(float(radius[i]))),
                          int(bins[i]), int(events[i]), float(total[i]), float(best[i]))
                  for i in kept[:MAX_SPOTS])
    return HotSpotSearch(image, edges_x, edges_y, background, tested, alpha, scale, spots, int(spots_mask.sum()),
                         count - len(kept), max(0, len(kept) - MAX_SPOTS), tuple(notes))


def _round_up(radius: float) -> float:
    """A radius rounded up to 0.01 mm (the circle never shrinks in the text)."""
    return math.ceil(radius * 1e5 - 1e-9) / 1e5


def plural(count: int, word: str) -> str:
    return f"{count:,} {word}{'' if count == 1 else 's'}"


def search_lines(search: HotSpotSearch) -> list[str]:
    """For the record: the rule, then each spot."""
    lines = [f"Hot-spot search: bins of {_mm(float(search.edges_x[1] - search.edges_x[0]))} mm, local background "
             f"σ {_mm(search.scale)} mm, significant when P(N ≥ n | background) < {search.alpha:g} / "
             f"{search.tested:,} filled bins = {search.p_limit:.2g}: {plural(search.found, 'spot')}"
             + (f" ({plural(search.dropped, 'one-bin spot')} under the minimum excess left out)" if search.dropped
                else ""), *search.notes]
    for number, spot in enumerate(search.spots, start=1):
        circle = spot.circle
        lines.append(f"Spot {number}: x {_mm(circle.x)} mm, y {_mm(circle.y)} mm, r {_mm(circle.r)} mm · "
                     f"{plural(spot.bins, 'bin')}, {plural(spot.counts, 'event')} ({spot.excess:,.0f} above "
                     f"background), P {spot.p_value:.2g}")
    if search.left_out:
        lines.append(f"{search.left_out:,} weaker spots not listed (at most {MAX_SPOTS})")
    return lines


def _mm(metres: float) -> str:
    """A length in mm to 0.01 mm, with the plots' minus sign."""
    return f"{metres * 1e3:,.2f}".replace("-", "−")
