"""Transfer fractions: the share of each shot's atoms in each diffraction order (or magnetic
state), against shot number, with the orders found in the arrival-time histogram.

Ported from ``monitor_momentum.m`` and ``lib/fraction_calc.m`` in the lab's MATLAB analysis,
https://github.com/HeBECANU/Momentum_Bells_test (``legacy/Momentum_Bells_test``). There the
time windows of the states were typed into the script; here they are found from the data:
the tallest peak of the T histogram is order 0, the nearest clear side peak gives the spacing,
and order k's window is ``centre + k·spacing ± half-width`` (+k arrives later). Switching
Orders to manual starts from the last detection, which can then be edited. Like
``fraction_calc``, a shot counts only events inside the XY box and only when it has more than
the minimum counts there; each fraction is the order's count over the sum of all the orders'.
Where this differs from ``fraction_calc`` on purpose (fractions over the orders' sum, not a
wide window; shots left out by their counts in the counting box, not the import box;
half-open windows; no X/Y rotation): ``tests/test_transfer_fractions_matlab.py``. On rotation:
``monitor_momentum.m`` rotates X/Y by ``dld_xy_rot`` = 0.61 rad before its ±35 mm import box
and ±30 mm counting box; HeLab boxes X/Y as loaded, unrotated (Tony, 2026-10-20: no rotation
is expected to change the counts; a hot spot near the box's edge is to be looked at later,
the lab's detector having changed since that MATLAB was written).

The T histogram alone can't say which peak is order 0, and auto takes the tallest. The plot
says order 0 is unsure when another order holds at least half as many events (comparable
peaks, or a Search T that leaves the real order 0 out), and that it moved when it lands a whole
number of spacings from the last detection (Live, a scan; the hidden centre then keeps the last
one). A first run with a transfer over about 2/3 can still take +1 for order 0 without a note:
set both ends of Search T around order 0, or the orders by hand. A Search T with both ends set
is the user's word on order 0: an order outside it gets a plain line, not the warning, and a
last detection outside it is replaced without a "moved" warning (a plain line says so).
Under its title the plot also says when the orders overlap or no side peak was found, and
which events were left out.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, cast

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget
from scipy.signal import find_peaks

from helab.analysis.dataset_view import DatasetView, txy
from helab.analysis.display_units import T_SCALE, WIDTH_DIGITS, axis_label, length_text, range_text, time_text
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.masks import MASK_SPECS, mask_brief, mask_from, mask_warnings, masked_text
from helab.analysis.parameters import ParameterSpec
from helab.analysis.plot_axes import GroupedAxis
from helab.analysis.plot_text import add_label, line_html, notes_html
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import SHOT_SPECS, select_shots, selection_text, shots_brief, shots_text
from helab.analysis.stats import shortest_range
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.standard import group

AUTO, MANUAL = "auto", "manual"
ORDERS_GROUP = "Orders"
MODE = ParameterSpec("orders_mode", "Orders", "choice", AUTO, choices=(AUTO, MANUAL), group=ORDERS_GROUP,
                     tip="Auto finds order 0 (the tallest peak in T) and the spacing (the nearest clear side "
                         "peak) on each run; manual uses the centre and spacing below, which each auto run "
                         "fills in (not the centre when order 0 jumped a whole order: the plot warns).")
EACH_SIDE = ParameterSpec("orders_each_side", "Orders each side", "int", 2, (1, 6), group=ORDERS_GROUP,
                          tip="Orders −N…+N are counted; +1 arrives later than 0.")
CENTRE = ParameterSpec("centre", "Order 0 at", "float", 2.1375, (0.0, 100.0), " s", group=ORDERS_GROUP,
                       when=(MODE.name, MANUAL), si=True, unit_prefix="m", tip="Arrival time of order 0.")
SPACING = ParameterSpec("spacing", "Spacing", "float", 0.0125, (1e-6, 10.0), " s", group=ORDERS_GROUP,
                        when=(MODE.name, MANUAL), si=True, unit_prefix="m", tip="Time between neighbouring orders.")
HALF_WIDTH = ParameterSpec("half_width", "Window ± (0 = half spacing)", "float", 0.0, (0.0, 10.0), " s",
                           group=ORDERS_GROUP, si=True, unit_prefix="m",
                           tip="Each order's window is its time ± this; 0 makes neighbouring windows touch. Over "
                               "half the spacing it is clipped to that (the plot says so): windows never overlap.")
SEARCH_MIN = ParameterSpec("search_min", "Search T from (0 = first)", "float", 0.0, (0.0, 100.0), " s",
                           group=ORDERS_GROUP, when=(MODE.name, AUTO), si=True, unit_prefix="m",
                           tip="Auto looks for the orders between these times; 0 leaves that end open. Put order 0 "
                               "inside: the tallest peak here is taken as order 0. With both ends set, the plot "
                               "doesn't warn about orders outside it.")
SEARCH_MAX = ParameterSpec("search_max", "Search T to (0 = last)", "float", 0.0, (0.0, 100.0), " s",
                           group=ORDERS_GROUP, when=(MODE.name, AUTO), si=True, unit_prefix="m",
                           tip="See Search T from. A From at or above To searches every event, and the plot says so.")
BOX_GROUP = "Counting"
XY_HALF = ParameterSpec("xy_half", "XY box ±", "float", 0.03, (0.0, 1.0), " m", group=BOX_GROUP, si=True,
                        unit_prefix="m",
                        tip="Only events with |X| and |Y| within this count (0 = no XY limit); keeps a hot spot "
                            "out of the counts.")
MIN_COUNTS = ParameterSpec("min_counts", "Minimum counts", "int", 50, (0, 10_000_000), group=BOX_GROUP,
                           tip="Shots with no more events than this in the XY box are left out.")
PARAMETERS = (*SHOT_SPECS, MODE, EACH_SIDE, CENTRE, SPACING, HALF_WIDTH, SEARCH_MIN, SEARCH_MAX, XY_HALF,
              MIN_COUNTS, *MASK_SPECS)
MAX_DETECTION_BINS = 20_000
MIN_DETECTION_BINS = 50
DENSEST_SHARE = 0.1  # the bin width is half the shortest T interval holding this share of the events
SMOOTHING_BINS = 1.5  # Gaussian sigma
DENSE_SHARE = 0.99  # with the bins capped, the histogram narrows to the shortest interval holding this share
COARSE_FACTOR = 4  # bins still this many times wider than wanted are too coarse to tell orders apart
SIDE_PEAK_SHARE = 0.02  # a side peak's least prominence, as a share of order 0's height …
SIDE_PEAK_COUNTS = 4.0  # … and in (smoothed) events per bin, against noise in sparse bins
SIDE_PEAK_FWHMS = 0.5  # how far a side peak must be from order 0, in order 0's full widths
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
    masked: int = 0  # events the mask took out of the chosen shots (before the XY box)

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


def half_maximum_width(smoothed: npt.NDArray[np.float64], top: int) -> float:
    """Twice the distance, in bins, from ``top`` to where the histogram first falls to half its
    height, on the nearer side: a neighbouring order above half the height widens only its own
    side. At least one bin."""
    half = float(smoothed[top]) / 2
    distances = []
    for direction in (-1, 1):
        index = top
        while 0 <= index + direction < len(smoothed) and smoothed[index + direction] > half:
            index += direction
        beyond = index + direction
        if 0 <= beyond < len(smoothed):  # interpolate between the last bin above half and the first below
            above, below = float(smoothed[index]), float(smoothed[beyond])
            distances.append(abs(index - top) + (above - half) / (above - below))
    return 2 * max(min(distances), 0.5) if distances else float(len(smoothed))


def detect(times: npt.NDArray[np.float64], lower: float, upper: float, each_side: int) -> Detection:
    """Order 0 at the tallest peak of the smoothed T histogram, refined to the mean time near
    it; the spacing from the clear side peaks (beyond half of order 0's full width), as their
    offsets over their order. The bins are half the shortest interval holding a tenth of the
    events, which lies inside the tallest peak whatever the spread of stray events, between
    MIN_DETECTION_BINS and MAX_DETECTION_BINS over [lower, upper]; past the cap, over the
    shortest interval holding DENSE_SHARE of the events instead."""
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
    peaks, _ = find_peaks(smoothed, prominence=prominence)
    centre = refine(times, float(middles[top]), fwhm)
    sides = [float(middles[p]) for p in peaks if abs(middles[p] - centre) > SIDE_PEAK_FWHMS * fwhm]
    if not sides:
        return Detection(centre, None, edges, counts.astype(np.float64), fwhm, coarse)
    nearest = min(abs(side - centre) for side in sides)
    offsets, weights = [], []
    for side in sides:
        order = round((side - centre) / nearest)
        if order == 0 or abs(order) > each_side:
            continue
        near = times[np.abs(times - side) <= min(nearest / 4, fwhm)]
        offsets.append((refine(times, side, min(nearest / 4, fwhm)) - centre) / order)
        weights.append(len(near))
    spacing = float(np.average(offsets, weights=weights)) if offsets and sum(weights) else nearest
    return Detection(centre, spacing, edges, counts.astype(np.float64), fwhm, coarse)


def refine(times: npt.NDArray[np.float64], position: float, reach: float) -> float:
    """The mean time within ``reach`` of ``position``, repeated so that a start off the peak's
    middle doesn't pull it."""
    for _ in range(3):
        near = times[np.abs(times - position) <= reach]
        position = float(near.mean()) if len(near) else position
    return position


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
        return spacing / 2, (f"Window ± {time_text(half_width, WIDTH_DIGITS)} is over half the spacing: using "
                             f"{time_text(spacing / 2, WIDTH_DIGITS)}, so neighbouring windows touch without sharing events")
    return half_width or spacing / 2, ""


def search_bounds(values: Mapping[str, Any]) -> tuple[float, float]:
    """Where auto looks for the orders: Search T from/to, 0 leaving that end open; a From at or
    above To (both set) searches every event, which ``search_warnings`` reports."""
    low, high = float(values[SEARCH_MIN.name]), float(values[SEARCH_MAX.name])
    if low and high and low >= high:
        return -math.inf, math.inf
    return low or -math.inf, high or math.inf


def search_warnings(values: Mapping[str, Any]) -> tuple[str, ...]:
    """What auto did differently from the Search T settings (in auto mode only)."""
    low, high = float(values[SEARCH_MIN.name]), float(values[SEARCH_MAX.name])
    if values[MODE.name] == AUTO and low and high and low >= high:
        return ("Search T: from ≥ to, searching every event",)
    return ()


def jump(previous: float, centre: float, spacing: float, each_side: int) -> int:
    """How many orders auto's order 0 moved from the last detection (the hidden manual centre):
    a whole number of spacings, n with 1 ≤ |n| ≤ each_side + 1, within JUMP_SLACK; else 0. A
    strong transfer can make another order the tallest peak from one run to the next (Live, an
    amplitude scan). The default centre is no detection: 0."""
    if previous == CENTRE.default or not spacing > 0:
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


class TransferFractions(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Transfer fractions",
            description="Share of each shot's atoms in each order (found in the T histogram), against shot "
                        "number; from Momentum_Bells_test's monitor_momentum.m",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.transfer_fractions",
            version="7",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*PARAMETERS]

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        each = int(values[EACH_SIDE.name])
        how = "auto orders" if values[MODE.name] == AUTO else "manual orders"
        half = float(values[XY_HALF.name])
        box = f"XY ±{length_text(half)}" if half > 0 else "no XY limit"
        settings = (shots_brief(values), f"{how} ±{each}", box, f"> {int(values[MIN_COUNTS.name]):,} counts",
                    mask_brief(values))
        return selection_text(view, values), " · ".join(part for part in settings if part)

    def detected_parameters(self, action_name: str, result: AnalysisResult) -> dict[str, Any]:
        data = result.data
        if not isinstance(data, Fractions) or not data.auto or not data.detected:
            return {}
        if data.jumped:  # The last detection's order 0 stays: the warning stays too, and manual starts there.
            return {SPACING.name: data.orders.spacing}
        return {CENTRE.name: data.orders.centre, SPACING.name: data.orders.spacing}

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        masking = list(mask_warnings(values))
        if values[MODE.name] == AUTO:
            # The spacing, and so the window's limit, is found later.
            return [*search_warnings(values), *masking]
        _, clipped = window_half(float(values[HALF_WIDTH.name]), float(values[SPACING.name]))
        return [clipped, *masking] if clipped else masking

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        values = context.parameters
        view = context.view
        chosen = select_shots(view, values)
        half, minimum = float(values[XY_HALF.name]), int(values[MIN_COUNTS.name])
        each_side = int(values[EACH_SIDE.name])
        mask = mask_from(values)  # Circles that can't be read fail the run, saying which.
        boxed: dict[int, npt.NDArray[np.float64]] = {}
        events_total = not_finite = masked = 0
        for shot in chosen:
            context.check()
            events = txy(np.asarray(view.shots[shot], dtype=np.float64))
            events_total += len(events)
            finite = np.isfinite(events[:, 0])
            if not finite.all():
                not_finite += len(events) - int(np.count_nonzero(finite))
                events = events[finite]
            events, dropped = mask.apply(events)
            masked += dropped
            events = in_box(events, half)
            if len(events) > minimum:
                boxed[shot] = np.ascontiguousarray(events[:, 0])
        notes: list[str] = []
        if not_finite:
            notes.append(f"{not_finite:,} event{'' if not_finite == 1 else 's'} with T not a number left out")
        skipped = len(chosen) - len(boxed)
        if skipped:
            notes.append(f"{skipped:,} shot{'' if skipped == 1 else 's'} with ≤ {minimum:,} counts left out")
        times = np.concatenate(list(boxed.values())) if boxed else np.empty(0)
        auto = values[MODE.name] == AUTO
        centre, spacing = float(values[CENTRE.name]), float(values[SPACING.name])
        previous, detected, jumped = centre, False, 0
        low, high = search_bounds(values)
        if auto and len(times):
            notes.extend(search_warnings(values))
            searched = times[(times >= low) & (times <= high)]
            if len(searched):
                lower, upper = float(searched.min()), float(searched.max())
                found = detect(searched, lower, upper if upper > lower else lower + 1e-6, each_side)
                centre, detected = found.centre, True
                if found.spacing is None:
                    coarse = (f"; T bins of {time_text(found.edges[1] - found.edges[0], 2)} are coarse for order 0, narrow "
                              f"Search T") if found.coarse else ""
                    notes.append(f"no side peak found beyond order 0's width ({time_text(found.fwhm, 3)}): "
                                 f"spacing as set{coarse}")
                else:
                    spacing = found.spacing
                if found.fwhm > spacing / 2:
                    notes.append(f"orders overlap: order 0's width (FWHM {time_text(found.fwhm, 3)}) is over half the "
                                 f"spacing, so neighbouring orders share events")
            else:
                notes.append("no events in the search range: orders as set")
        width, clipped = window_half(float(values[HALF_WIDTH.name]), spacing)
        if clipped:
            notes.append(clipped)
        orders = Orders(centre, spacing, width, each_side)
        counts = np.array([count_orders(boxed[shot], orders) for shot in boxed], dtype=np.int64)
        counts = counts.reshape(len(boxed), len(orders.numbers))
        if detected:
            notes.extend(unsure(orders, counts.sum(axis=0), low, high))
            replaced = chosen_by_search(previous, low, high) and previous != CENTRE.default
            jumped = 0 if chosen_by_search(previous, low, high) else jump(previous, centre, spacing, each_side)
            if replaced:  # The user's word on order 0, but say what it replaced.
                notes.append(f"order 0 now at {time_text(centre)}; the last detection, {time_text(previous)}, was outside "
                             f"Search T")
            if jumped:
                notes.append(f"⚠ order 0 moved by {order_label(jumped)} order{'' if abs(jumped) == 1 else 's'} "
                             f"from the last detection ({time_text(previous)} → {time_text(centre)}): a strong transfer can "
                             f"make another order the tallest. Manual starts from the last one; to accept the new "
                             f"one, set Order 0 at {time_text(centre)} in manual mode, Rerun, then back to Auto")
        empty = int(np.count_nonzero(counts.sum(axis=1) == 0))
        if empty and empty < len(boxed):
            notes.append(f"{empty:,} shot{'' if empty == 1 else 's'} with no events in the windows: no fractions")
        span = (each_side + 1) * spacing
        around = times[np.abs(times - centre) <= span]
        histogram = np.histogram(around, bins=400, range=(centre - span, centre + span)) if len(times) else None
        return Fractions(orders, np.fromiter(boxed, dtype=np.int64, count=len(boxed)), counts, len(chosen),
                         len(view.shots), auto, tuple(notes),
                         (histogram[1], histogram[0].astype(np.float64)) if histogram else (np.empty(0), np.empty(0)),
                         detected, minimum, events_total,
                         (float(times.min()), float(times.max())) if len(times) else (math.nan, math.nan),
                         jumped, masked)

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: Fractions = result.data
        orders = data.orders
        if not len(data.shots):
            text = empty_text(data.total_shots, data.chosen, data.events)  # No events: nothing to add
            said = () if text else data.notes
            text = text or f"No shot has more than {data.minimum:,} counts in the XY box (Counting settings)"
            return empty_pane(" · ".join((text, *said)), parent)
        if not data.counts.any():
            first, last = data.extent
            text = (f"No events in the orders' windows: order 0 at {time_text(orders.centre)}, spacing "
                    f"{time_text(orders.spacing, WIDTH_DIGITS)}, and the events counted are at {range_text('T', first, last)} "
                    f"(Orders settings)")
            return empty_pane(" · ".join((text, *data.notes)), parent)
        widget: Any = pg.GraphicsLayoutWidget(parent)
        widget.setBackground("w")
        found = "found" if data.auto else "set"
        title = (f"{result.input.short()} · {shots_text(data.shots.tolist(), data.total_shots)} · order 0 at "
                 f"{time_text(orders.centre)}, spacing {time_text(orders.spacing, WIDTH_DIGITS)}, window ±{time_text(orders.half_width, WIDTH_DIGITS)} "
                 f"({found}){masked_text(data.masked)}")
        add_label(widget, line_html(title) + notes_html(data.notes), row=0, col=0)  # One note per line.
        colours = [pg.intColor(i, hues=len(orders.numbers), values=1, maxValue=200) for i in range(len(orders.numbers))]
        plot = widget.addPlot(row=1, col=0)
        plot.setLabel("bottom", "Shot number")
        plot.setLabel("left", "Transfer fraction")
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.addLegend(offset=(-10, 10))
        fractions = data.fractions
        for column, order in enumerate(orders.numbers):
            colour = colours[column]
            plot.plot(data.shots, fractions[:, column], name=f"order {order_label(order)}", connect="finite",
                      pen=pg.mkPen(colour, width=1.5), symbol="o", symbolSize=4, symbolBrush=colour, symbolPen=None)
        edges, counts = data.histogram
        times = widget.addPlot(row=2, col=0, title="T around the orders, with their windows",
                               axisItems={"bottom": GroupedAxis("bottom")})
        times.setLabel("bottom", axis_label("T"))
        times.setLabel("left", "Events")
        if len(counts):
            times.addItem(pg.PlotDataItem(edges * T_SCALE, counts, stepMode="center", fillLevel=0,
                                          pen=pg.mkPen((60, 60, 60)), brush=(60, 60, 60, 60)))
        for column, order in enumerate(orders.numbers):
            low, high = orders.window(order)
            region = pg.LinearRegionItem((low * T_SCALE, high * T_SCALE), movable=False,
                                         brush=(*colours[column].getRgb()[:3], 50), pen=pg.mkPen(None))
            times.addItem(region)
            label = pg.TextItem(order_label(order), color=colours[column], anchor=(0.5, 0))
            label.setPos((orders.centre + order * orders.spacing) * T_SCALE, float(counts.max()) if len(counts) else 1.0)
            times.addItem(label)
        widget.ci.layout.setRowStretchFactor(1, 3)
        widget.ci.layout.setRowStretchFactor(2, 2)
        return cast(QWidget, widget)
