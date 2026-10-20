"""Transfer fractions' order detection and counting (Basic plots v1's ``transfer_fractions``):
order 0 at the tallest peak of the T histogram, the spacing from the clear side peaks near whole
multiples of a reference spacing (``guided_spacing``), each order's events in a half-open window
(``count_orders``), and the checks on order 0 (``unsure``, ``jump``, ``chosen_by_search``). The
plot's parameters, its text and its drawing stay in the script.

``half_maximum_width`` and ``refine`` are ``helab.analysis.peaks``'s (the same code). The
smoothing is this module's own: ``peaks.smooth`` differs (it keeps the histogram's length when
the kernel is longer than it), and so do the bin choices of ``peaks.find_time_peaks``, so the
detection constants here are this module's too.

Pure NumPy/SciPy, no Qt.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence, cast

import numpy as np
import numpy.typing as npt
from scipy.signal import find_peaks

from helab.analysis.peaks import half_maximum_width, refine
from helab.analysis.stats import shortest_range

DEFAULT_CENTRE = 2.1375  # the default of the plot's "Order 0 at" (s), which ``jump`` takes for no detection
MAX_DETECTION_BINS = 20_000
MIN_DETECTION_BINS = 50
DENSEST_SHARE = 0.1  # the bin width is half the shortest T interval holding this share of the events
SMOOTHING_BINS = 1.5  # Gaussian sigma
DENSE_SHARE = 0.99  # with the bins capped, the histogram narrows to the shortest interval holding this share
COARSE_FACTOR = 4  # bins still this many times wider than wanted are too coarse to tell orders apart
SIDE_PEAK_SHARE = 0.02  # a side peak's least prominence, as a share of order 0's height …
SIDE_PEAK_COUNTS = 4.0  # … and in (smoothed) events per bin, against noise in sparse bins
SIDE_PEAK_FWHMS = 0.5  # how far a side peak must be from order 0, in order 0's full widths
REFERENCE_SLACK = 0.3  # order k's peak is within this many spacings of k spacings from order 0
UNSURE_SHARE = 0.5  # another order with at least this share of order 0's events makes order 0 unsure
JUMP_SLACK = 0.3  # a centre within this many spacings of a whole number (≥ 1) from the last one has jumped


@dataclass(frozen=True)
class Orders:
    centre: float
    spacing: float
    half_width: float
    each_side: int

    @property
    def numbers(self) -> tuple[int, ...]:
        return tuple(range(-self.each_side, self.each_side + 1))

    def window(self, order: int) -> tuple[float, float]:
        middle = self.centre + order * self.spacing
        return middle - self.half_width, middle + self.half_width


@dataclass(frozen=True)
class Detection:
    centre: float
    spacing: float | None  # None: no side peak found
    edges: npt.NDArray[np.float64]
    counts: npt.NDArray[np.float64]
    fwhm: float = math.nan  # order 0's full width at half maximum, in the smoothed histogram
    coarse: bool = False  # the bins were capped at over COARSE_FACTOR times the width wanted


@dataclass(frozen=True)
class Fractions:
    orders: Orders
    shots: npt.NDArray[np.int64]  # the shots counted
    counts: npt.NDArray[np.int64]  # (shots, orders)
    chosen: int  # shots chosen by Shots
    total_shots: int
    auto: bool
    notes: tuple[str, ...] = ()
    histogram: tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]] = field(
        default=(np.empty(0), np.empty(0)))  # (edges, counts) of T around the orders
    detected: bool = False  # Auto found order 0 in this run's events (it had some to search)
    minimum: int = 0  # Shots with no more counts than this in the XY box were left out
    events: int = 0  # events in the chosen shots, before the XY box
    extent: tuple[float, float] = (math.nan, math.nan)  # T of the events counted, first to last
    jumped: int = 0  # auto's order 0 is this many orders from the last detection (``jump``)
    # The highlighted newest shot (None: off): the newest chosen shot's T in the XY box, in the
    # histogram's bins, drawn over it; ``newest_left_out`` when Minimum counts left it out.
    newest_shot: int | None = None
    newest: npt.NDArray[np.float64] = field(default_factory=lambda: np.empty(0))
    newest_left_out: bool = False
    colour: tuple[int, int, int] = (214, 39, 40)

    @property
    def fractions(self) -> npt.NDArray[np.float64]:
        totals = self.counts.sum(axis=1, keepdims=True).astype(np.float64)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(totals > 0, self.counts / totals, np.nan)


def order_label(order: int) -> str:
    return f"+{order}" if order > 0 else "0" if order == 0 else f"−{-order}"


def in_box(events: npt.NDArray[np.float64], half: float) -> npt.NDArray[np.float64]:
    if half <= 0:
        return events
    return events[(np.abs(events[:, 1]) <= half) & (np.abs(events[:, 2]) <= half)]


def smooth(counts: npt.NDArray[np.float64], sigma: float = SMOOTHING_BINS) -> npt.NDArray[np.float64]:
    radius = int(math.ceil(3 * sigma))
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    return cast(npt.NDArray[np.float64], np.convolve(counts, kernel / kernel.sum(), mode="same"))


def detect(times: npt.NDArray[np.float64], lower: float, upper: float, each_side: int,
           reference: float) -> Detection:
    """Order 0 at the tallest peak of the smoothed T histogram, refined to the mean time near
    it; the spacing from the clear side peaks (beyond half of order 0's full width) that
    ``guided_spacing`` takes for orders, guided by the ``reference`` spacing. The bins are half
    the shortest interval holding a tenth of the events, which lies inside the tallest peak
    whatever the spread of stray events, between MIN_DETECTION_BINS and MAX_DETECTION_BINS over
    [lower, upper]; past the cap, over the shortest interval holding DENSE_SHARE of the events
    instead."""
    densest_low, densest_high = shortest_range(times, DENSEST_SHARE)
    width = (densest_high - densest_low) / 2
    wanted = math.ceil((upper - lower) / width) if width > 0 else MIN_DETECTION_BINS
    if wanted > MAX_DETECTION_BINS:  # stray events far out: bin only where nearly all the events are
        dense_low, dense_high = shortest_range(times, DENSE_SHARE)
        pad = (dense_high - dense_low) * 0.05
        lower, upper = max(lower, dense_low - pad), min(upper, dense_high + pad)
        wanted = math.ceil((upper - lower) / width)
    bins = min(max(wanted, MIN_DETECTION_BINS), MAX_DETECTION_BINS)
    counts, edges = np.histogram(times, bins=bins, range=(lower, upper))
    smoothed = smooth(counts.astype(np.float64))
    middles = (edges[:-1] + edges[1:]) / 2
    step = float(edges[1] - edges[0])
    top = int(np.argmax(smoothed))
    fwhm = half_maximum_width(smoothed, top) * step
    coarse = wanted > COARSE_FACTOR * MAX_DETECTION_BINS
    prominence = max(float(smoothed[top]) * SIDE_PEAK_SHARE, SIDE_PEAK_COUNTS)
    peaks, properties = find_peaks(smoothed, prominence=prominence)
    centre = refine(times, float(middles[top]), fwhm)
    sides = [(float(middles[p]), float(strength)) for p, strength in zip(peaks, properties["prominences"])
             if abs(middles[p] - centre) > SIDE_PEAK_FWHMS * fwhm]
    spacing = guided_spacing(times, centre, sides, reference, each_side, fwhm)
    return Detection(centre, spacing, edges, counts.astype(np.float64), fwhm, coarse)


def guided_spacing(times: npt.NDArray[np.float64], centre: float, sides: Sequence[tuple[float, float]],
                   reference: float, each_side: int, fwhm: float) -> float | None:
    """The spacing from the side peaks ``sides`` ((time, prominence)), working outwards from
    order 0: order ±k is the most prominent peak within REFERENCE_SLACK spacings of k spacings
    away, the spacing being the reference for ±1 and then the weighted mean of the offsets over
    their order found so far. None when no peak is near any order (a bump between the orders,
    say 5 ms from order 0 with a 15 ms reference, is never one). The nearest peak alone would
    take such a bump, and the real ±1 at 15 ms would then count as ±3 of a 5 ms spacing."""
    estimate = reference
    offsets: list[float] = []
    weights: list[int] = []
    for step in range(1, each_side + 1):
        for order in (step, -step):
            target, slack = centre + order * estimate, REFERENCE_SLACK * estimate
            near = [(strength, side) for side, strength in sides if abs(side - target) <= slack]
            if not near:
                continue
            reach = min(estimate / 4, fwhm)
            side = refine(times, max(near)[1], reach)
            offsets.append((side - centre) / order)
            weights.append(int(np.count_nonzero(np.abs(times - side) <= reach)))
        if offsets:
            estimate = float(np.average(offsets, weights=weights)) if sum(weights) else float(np.mean(offsets))
    return estimate if offsets else None


def count_orders(times: npt.NDArray[np.float64], orders: Orders) -> npt.NDArray[np.int64]:
    """Events per order window, each window half-open [low, high), so windows that touch never
    share an event."""
    ordered = np.sort(times)
    counts = []
    for order in orders.numbers:
        low, high = orders.window(order)
        counts.append(int(np.searchsorted(ordered, high, "left") - np.searchsorted(ordered, low, "left")))
    return np.array(counts, dtype=np.int64)


def window_half(half_width: float, spacing: float) -> tuple[float, str]:
    """The window ± used: as set, half the spacing for 0, and clipped to half the spacing when
    set wider, so neighbouring windows never overlap (each event counts once); with what it says."""
    if half_width > spacing / 2:
        return spacing / 2, (f"Window ± {half_width * 1e3:.3g} ms is over half the spacing: using "
                             f"{spacing / 2 * 1e3:.3g} ms, so neighbouring windows touch without sharing events")
    return half_width or spacing / 2, ""


def jump(previous: float, centre: float, spacing: float, each_side: int) -> int:
    """How many orders auto's order 0 moved from the last detection (the hidden manual centre):
    a whole number of spacings, n with 1 ≤ |n| ≤ each_side + 1, within JUMP_SLACK; else 0. A
    strong transfer can make another order the tallest peak from one run to the next (Live, an
    amplitude scan). The default centre is no detection: 0."""
    if previous == DEFAULT_CENTRE or not spacing > 0:
        return 0
    moved = (centre - previous) / spacing
    orders = round(moved)
    return orders if 1 <= abs(orders) <= each_side + 1 and abs(moved - orders) <= JUMP_SLACK else 0


def unsure(orders: Orders, totals: npt.NDArray[np.int64], low: float, high: float) -> tuple[str, ...]:
    """A note when auto's order 0 may be another order: one of the others holds at least
    UNSURE_SHARE of its events (order 0 is the tallest peak, which a strong transfer, or a search
    range that leaves the real order 0 out, makes another order). A Search T with both ends set
    is the user's word on where order 0 is: such orders outside it get a plain line instead."""
    zero = int(totals[orders.each_side])
    bounded = math.isfinite(low) and math.isfinite(high)
    rivals = [(int(total), order) for order, total in zip(orders.numbers, totals)
              if order and total > 0 and total >= UNSURE_SHARE * zero]
    outside = [(total, order) for total, order in rivals
               if not low <= orders.centre + order * orders.spacing <= high]
    warned = [rival for rival in rivals if not bounded or rival not in outside]
    notes: list[str] = []
    if warned:
        total, order = max(warned)
        share = f"{total / zero:.0%} as many events as" if zero else "events, none in"
        where = " (outside Search T)" if (total, order) in outside else ""
        notes.append(f"⚠ order 0 unsure: order {order_label(order)}{where} holds {share} order 0; set both ends "
                     f"of Search T around order 0, or the orders by hand")
    if bounded and outside:
        total, order = max(outside)
        share = "is taller than" if total > zero else f"holds {total / zero:.0%} as many events as"
        notes.append(f"order {order_label(order)} (outside Search T) {share} order 0")
    return tuple(notes)


def chosen_by_search(previous: float, low: float, high: float) -> bool:
    """Whether a Search T with both ends set leaves out the last detection's order 0: the new
    one, found inside it, replaces it without a jump warning (a plain line says so)."""
    return math.isfinite(low) and math.isfinite(high) and not low <= previous <= high
