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
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, cast

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget
from scipy.signal import find_peaks, peak_widths

from helab.analysis.dataset_view import DatasetView
from helab.analysis.parameters import ParameterSpec
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
                         "fills in.")
EACH_SIDE = ParameterSpec("orders_each_side", "Orders each side", "int", 2, (1, 6), group=ORDERS_GROUP,
                          tip="Orders −N…+N are counted; +1 arrives later than 0.")
CENTRE = ParameterSpec("centre", "Order 0 at", "float", 2.1375, (0.0, 100.0), " s", group=ORDERS_GROUP,
                       when=(MODE.name, MANUAL), si=True, tip="Arrival time of order 0.")
SPACING = ParameterSpec("spacing", "Spacing", "float", 0.0125, (1e-6, 10.0), " s", group=ORDERS_GROUP,
                        when=(MODE.name, MANUAL), si=True, tip="Time between neighbouring orders.")
HALF_WIDTH = ParameterSpec("half_width", "Window ± (0 = half spacing)", "float", 0.0, (0.0, 10.0), " s",
                           group=ORDERS_GROUP, si=True,
                           tip="Each order's window is its time ± this; 0 makes neighbouring windows touch.")
SEARCH_MIN = ParameterSpec("search_min", "Search T from", "float", 0.0, (0.0, 100.0), " s", group=ORDERS_GROUP,
                           when=(MODE.name, AUTO), si=True,
                           tip="Auto looks for the orders between these times; leave both 0 for every event.")
SEARCH_MAX = ParameterSpec("search_max", "Search T to", "float", 0.0, (0.0, 100.0), " s", group=ORDERS_GROUP,
                           when=(MODE.name, AUTO), si=True, tip="See Search T from.")
BOX_GROUP = "Counting"
XY_HALF = ParameterSpec("xy_half", "XY box ±", "float", 0.03, (0.0, 1.0), " m", group=BOX_GROUP, si=True,
                        tip="Only events with |X| and |Y| within this count (0 = no XY limit); keeps a hot spot "
                            "out of the counts.")
MIN_COUNTS = ParameterSpec("min_counts", "Minimum counts", "int", 50, (0, 10_000_000), group=BOX_GROUP,
                           tip="Shots with no more events than this in the XY box are left out.")
PARAMETERS = (*SHOT_SPECS, MODE, EACH_SIDE, CENTRE, SPACING, HALF_WIDTH, SEARCH_MIN, SEARCH_MAX, XY_HALF,
              MIN_COUNTS)
MAX_DETECTION_BINS = 20_000
SMOOTHING_BINS = 1.5  # Gaussian sigma
SIDE_PEAK_SHARE = 0.02  # a side peak's least prominence, as a share of order 0's height …
SIDE_PEAK_COUNTS = 4.0  # … and in (smoothed) events per bin, against noise in sparse bins
SIDE_PEAK_FWHMS = 2.0  # how far a side peak must be from order 0, in order 0's full widths


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


def detect(times: npt.NDArray[np.float64], lower: float, upper: float, each_side: int) -> Detection:
    """Order 0 at the tallest peak of the smoothed T histogram (bins from the Freedman–Diaconis
    width of the densest 99 %), refined to the mean time near it; the spacing from the clear
    side peaks (beyond two of order 0's full widths), as their offsets over their order."""
    dense_low, dense_high = shortest_range(times, 0.99)
    dense = times[(times >= dense_low) & (times <= dense_high)]
    q1, q3 = np.percentile(dense, [25, 75])
    width = 2 * float(q3 - q1) * len(dense) ** (-1 / 3)
    bins = min(max(math.ceil((upper - lower) / width) if width > 0 else 50, 50), MAX_DETECTION_BINS)
    counts, edges = np.histogram(times, bins=bins, range=(lower, upper))
    smoothed = smooth(counts.astype(np.float64))
    middles = (edges[:-1] + edges[1:]) / 2
    step = float(edges[1] - edges[0])
    top = int(np.argmax(smoothed))
    fwhm = float(peak_widths(smoothed, [top], rel_height=0.5)[0][0]) * step
    prominence = max(float(smoothed[top]) * SIDE_PEAK_SHARE, SIDE_PEAK_COUNTS)
    peaks, _ = find_peaks(smoothed, prominence=prominence)
    centre = refine(times, float(middles[top]), fwhm)
    sides = [float(middles[p]) for p in peaks if abs(middles[p] - centre) > SIDE_PEAK_FWHMS * fwhm]
    if not sides:
        return Detection(centre, None, edges, counts.astype(np.float64))
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
    return Detection(centre, spacing, edges, counts.astype(np.float64))


def refine(times: npt.NDArray[np.float64], position: float, reach: float) -> float:
    """The mean time within ``reach`` of ``position``, repeated so that a start off the peak's
    middle doesn't pull it."""
    for _ in range(3):
        near = times[np.abs(times - position) <= reach]
        position = float(near.mean()) if len(near) else position
    return position


def count_orders(times: npt.NDArray[np.float64], orders: Orders) -> npt.NDArray[np.int64]:
    ordered = np.sort(times)
    counts = []
    for order in orders.numbers:
        low, high = orders.window(order)
        counts.append(int(np.searchsorted(ordered, high, "right") - np.searchsorted(ordered, low, "left")))
    return np.array(counts, dtype=np.int64)


class TransferFractions(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Transfer fractions",
            description="Share of each shot's atoms in each order (found in the T histogram), against shot "
                        "number; from Momentum_Bells_test's monitor_momentum.m",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.transfer_fractions",
            version="1",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*PARAMETERS]

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        each = int(values[EACH_SIDE.name])
        how = "auto orders" if values[MODE.name] == AUTO else "manual orders"
        half = float(values[XY_HALF.name])
        box = f"XY ±{half * 1e3:g} mm" if half > 0 else "no XY limit"
        settings = (shots_brief(values), f"{how} ±{each}", box, f"> {int(values[MIN_COUNTS.name]):,} counts")
        return selection_text(view, values), " · ".join(part for part in settings if part)

    def detected_parameters(self, action_name: str, result: AnalysisResult) -> dict[str, Any]:
        data = result.data
        if not isinstance(data, Fractions) or not data.auto:
            return {}
        return {CENTRE.name: data.orders.centre, SPACING.name: data.orders.spacing}

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        values = context.parameters
        view = context.view
        chosen = select_shots(view, values)
        half, minimum = float(values[XY_HALF.name]), int(values[MIN_COUNTS.name])
        each_side = int(values[EACH_SIDE.name])
        boxed: dict[int, npt.NDArray[np.float64]] = {}
        for shot in chosen:
            context.check()
            events = in_box(np.asarray(view.shots[shot], dtype=np.float64), half)
            if len(events) > minimum:
                boxed[shot] = np.ascontiguousarray(events[:, 0])
        notes: list[str] = []
        skipped = len(chosen) - len(boxed)
        if skipped:
            notes.append(f"{skipped:,} shot{'' if skipped == 1 else 's'} with ≤ {minimum:,} counts left out")
        times = np.concatenate(list(boxed.values())) if boxed else np.empty(0)
        auto = values[MODE.name] == AUTO
        centre, spacing = float(values[CENTRE.name]), float(values[SPACING.name])
        if auto and len(times):
            low, high = float(values[SEARCH_MIN.name]), float(values[SEARCH_MAX.name])
            searched = times[(times >= low) & (times <= high)] if high > low else times
            if len(searched):
                low, high = (low, high) if high > low else (float(searched.min()), float(searched.max()))
                found = detect(searched, low, high if high > low else low + 1e-6, each_side)
                centre = found.centre
                if found.spacing is None:
                    notes.append("no side peak found: spacing as set")
                else:
                    spacing = found.spacing
            else:
                notes.append("no events in the search range: orders as set")
        width = float(values[HALF_WIDTH.name]) or spacing / 2
        orders = Orders(centre, spacing, width, each_side)
        counts = np.array([count_orders(boxed[shot], orders) for shot in boxed], dtype=np.int64)
        span = (each_side + 1) * spacing
        around = times[np.abs(times - centre) <= span]
        histogram = np.histogram(around, bins=400, range=(centre - span, centre + span)) if len(times) else None
        return Fractions(orders, np.fromiter(boxed, dtype=np.int64, count=len(boxed)),
                         counts.reshape(len(boxed), len(orders.numbers)), len(chosen), len(view.shots), auto,
                         tuple(notes),
                         (histogram[1], histogram[0].astype(np.float64)) if histogram else (np.empty(0), np.empty(0)))

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: Fractions = result.data
        orders = data.orders
        widget: Any = pg.GraphicsLayoutWidget(parent)
        widget.setBackground("w")
        found = "found" if data.auto else "set"
        title = (f"{result.input.short()} · {shots_text(data.shots.tolist(), data.total_shots)} · order 0 at "
                 f"{orders.centre:.6g} s, spacing {orders.spacing * 1e3:.4g} ms, window ±{orders.half_width * 1e3:.3g} ms "
                 f"({found})")
        widget.addLabel(" · ".join((title, *data.notes)), row=0, col=0)
        colours = [pg.intColor(i, hues=len(orders.numbers), values=1, maxValue=200) for i in range(len(orders.numbers))]
        plot = widget.addPlot(row=1, col=0)
        plot.setLabel("bottom", "Shot number")
        plot.setLabel("left", "Transfer fraction")
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.addLegend(offset=(-10, 10))
        fractions = data.fractions
        for column, order in enumerate(orders.numbers):
            colour = colours[column]
            plot.plot(data.shots, fractions[:, column], name=f"order {order_label(order)}",
                      pen=pg.mkPen(colour, width=1.5), symbol="o", symbolSize=4, symbolBrush=colour, symbolPen=None)
        edges, counts = data.histogram
        times = widget.addPlot(row=2, col=0, title="T around the orders, with their windows")
        times.setLabel("bottom", "T (s)")
        times.setLabel("left", "Events")
        if len(counts):
            times.addItem(pg.PlotDataItem(edges, counts, stepMode="center", fillLevel=0,
                                          pen=pg.mkPen((60, 60, 60)), brush=(60, 60, 60, 60)))
        for column, order in enumerate(orders.numbers):
            region = pg.LinearRegionItem(orders.window(order), movable=False,
                                         brush=(*colours[column].getRgb()[:3], 50), pen=pg.mkPen(None))
            times.addItem(region)
            label = pg.TextItem(order_label(order), color=colours[column], anchor=(0.5, 0))
            label.setPos(orders.centre + order * orders.spacing, float(counts.max()) if len(counts) else 1.0)
            times.addItem(label)
        widget.ci.layout.setRowStretchFactor(1, 3)
        widget.ci.layout.setRowStretchFactor(2, 2)
        return cast(QWidget, widget)
