"""Transfer fractions (the DLD front panel port's version, helab.dld.transfer_fractions: ms, masks,
wrapped titles; "Basic plots v1" keeps its own): the share of each shot's atoms in each diffraction order (or magnetic
state), against shot number, with the orders found in the arrival-time histogram.

Ported from ``monitor_momentum.m`` and ``lib/fraction_calc.m`` in the lab's MATLAB analysis,
https://github.com/HeBECANU/Momentum_Bells_test (``legacy/Momentum_Bells_test``). There the
time windows of the states were typed into the script; here they are found from the data:
the tallest peak of the T histogram is order 0, the clear side peaks near whole multiples of the
Reference spacing (15 ms, as in those windows) give the spacing, as in Basic plots v1
(``helab.analysis.orders.detect``), and order k's window is ``centre + k·spacing ± half-width``
(+k arrives later). Switching
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
which events were left out. T histogram › Highlight the newest shot draws the newest chosen
shot over the T histogram as in the T/X/Y histograms (to the histogram's total, its real counts
on a right axis in its colour), even when Minimum counts left it out, which its title says. A
Live rerun updates the plots in place, keeping zoom and pan, unless the orders shown or the
highlight (on or off) change.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget

from helab.analysis.dataset_view import DatasetView, txy
from helab.analysis.display_units import T_SCALE, WIDTH_DIGITS, axis_label, length_text, range_text, time_text
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.masks import MASK_SPECS, mask_brief, mask_from, mask_warnings, masked_text
from helab.analysis.parameters import ParameterSpec
from helab.analysis.plot_axes import grouped_axes
from helab.analysis.plot_text import add_label, add_plot, line_html, notes_html, set_plot_title
from helab.analysis.orders import (REFERENCE_SLACK, Orders, Fractions as OrderFractions, chosen_by_search,
                                   count_orders, detect, in_box, jump, order_label, unsure)
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import (SHOT_SPECS, newest_brief, newest_colour, newest_shot, newest_specs, select_shots,
                                      selection_text, shots_brief, shots_text)
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.dld import group
from helab.scripts.dld.basic_plots import OverlayView, overlay_newest, update_newest

AUTO, MANUAL = "auto", "manual"
ORDERS_GROUP = "Orders"
MODE = ParameterSpec("orders_mode", "Orders", "choice", AUTO, choices=(AUTO, MANUAL), group=ORDERS_GROUP,
                     tip="Auto finds order 0 (the tallest peak in T) and the spacing (the clear side peaks "
                         "near multiples of the reference spacing) on each run; manual uses the centre and "
                         "spacing below, which each auto run fills in (not the centre when order 0 jumped a "
                         "whole order: the plot warns).")
EACH_SIDE = ParameterSpec("orders_each_side", "Orders each side", "int", 2, (1, 6), group=ORDERS_GROUP,
                          tip="Orders −N…+N are counted; +1 arrives later than 0.")
CENTRE = ParameterSpec("centre", "Order 0 at", "float", 2.1375, (0.0, 100.0), " s", group=ORDERS_GROUP,
                       when=(MODE.name, MANUAL), si=True, unit_prefix="m", tip="Arrival time of order 0.")
SPACING = ParameterSpec("spacing", "Spacing", "float", 0.0125, (1e-6, 10.0), " s", group=ORDERS_GROUP,
                        when=(MODE.name, MANUAL), si=True, unit_prefix="m", tip="Time between neighbouring orders.")
REFERENCE = ParameterSpec("reference_spacing", "Reference spacing", "float", 0.015, (1e-6, 10.0), " s",
                          group=ORDERS_GROUP, when=(MODE.name, AUTO), si=True, unit_prefix="m",
                          tip="Roughly the time between neighbouring orders. Auto takes order ±k only from a clear "
                              "peak within 30 % of a spacing from k spacings away (starting from this one, then "
                              "the spacing found so far), so a bump between the orders isn't taken for one.")
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
HIGHLIGHT, NEWEST_COLOUR = newest_specs("T histogram")
PARAMETERS = (*SHOT_SPECS, MODE, EACH_SIDE, CENTRE, SPACING, REFERENCE, HALF_WIDTH, SEARCH_MIN, SEARCH_MAX, XY_HALF,
              MIN_COUNTS, HIGHLIGHT, NEWEST_COLOUR, *MASK_SPECS)
@dataclass(frozen=True)
class Fractions(OrderFractions):
    """The shared record (``helab.analysis.orders``), with what the DLD port's Mask took out."""
    masked: int = 0  # events the mask took out of the chosen shots (before the XY box)


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


class TransferFractions(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Transfer fractions",
            description="Share of each shot's atoms in each order (found in the T histogram), against shot "
                        "number; from Momentum_Bells_test's monitor_momentum.m",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.dld.transfer_fractions",
            version="3",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*PARAMETERS]

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        each = int(values[EACH_SIDE.name])
        how = f"manual orders ±{each}"
        if values[MODE.name] == AUTO:
            how = f"auto orders ±{each} ~{time_text(float(values[REFERENCE.name]), WIDTH_DIGITS)}"
        half = float(values[XY_HALF.name])
        box = f"XY ±{length_text(half)}" if half > 0 else "no XY limit"
        settings = (shots_brief(values), how, box, f"> {int(values[MIN_COUNTS.name]):,} counts",
                    mask_brief(values), newest_brief(values))
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
        # The newest chosen shot, even one Minimum counts left out (a bad shot is worth seeing).
        newest = newest_shot(values, chosen)
        newest_times = np.empty(0)
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
            if shot == newest:
                newest_times = np.ascontiguousarray(events[:, 0])
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
                reference = float(values[REFERENCE.name])
                found = detect(searched, lower, upper if upper > lower else lower + 1e-6, each_side, reference)
                centre, detected = found.centre, True
                if found.spacing is None:
                    coarse = (f"; T bins of {time_text(found.edges[1] - found.edges[0], 2)} are coarse for order 0, narrow "
                              f"Search T") if found.coarse else ""
                    notes.append(f"no side peak found beyond order 0's width ({time_text(found.fwhm, 3)}) within "
                                 f"{REFERENCE_SLACK * 100:.0f} % of k × the reference spacing "
                                 f"({time_text(reference, WIDTH_DIGITS)}): spacing as set{coarse}")
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
        fresh = (np.histogram(newest_times, bins=histogram[1])[0].astype(np.float64) if histogram is not None
                 else np.empty(0))
        newest = newest if histogram is not None else None
        return Fractions(orders, np.fromiter(boxed, dtype=np.int64, count=len(boxed)), counts, len(chosen),
                         len(view.shots), auto, tuple(notes),
                         (histogram[1], histogram[0].astype(np.float64)) if histogram else (np.empty(0), np.empty(0)),
                         detected, minimum, events_total,
                         (float(times.min()), float(times.max())) if len(times) else (math.nan, math.nan),
                         jumped, newest, fresh, newest is not None and newest not in boxed,
                         newest_colour(values), masked=masked)

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: Fractions = result.data
        if text := empty_reason(data):
            return empty_pane(text, parent)
        widget = FractionsPlot(layout_key(data), parent)
        widget.show_data(result, data)
        return widget

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """A rerun (e.g. Live's next shots) sets the data in the plots already drawn, keeping zoom
        and pan, while the orders shown and the highlight (on or off) stay; otherwise, or to or
        from an empty plot, anew."""
        data: Fractions = result.data
        if not isinstance(widget, FractionsPlot) or empty_reason(data) or widget.key != layout_key(data):
            return False
        widget.show_data(result, data)
        return True


def empty_reason(data: Fractions) -> str:
    """Why there is nothing to draw ("" when there is)."""
    orders = data.orders
    if not len(data.shots):
        text = empty_text(data.total_shots, data.chosen, data.events)  # No events: nothing to add
        said = () if text else data.notes
        text = text or f"No shot has more than {data.minimum:,} counts in the XY box (Counting settings)"
        return " · ".join((text, *said))
    if not data.counts.any():
        first, last = data.extent
        text = (f"No events in the orders' windows: order 0 at {time_text(orders.centre)}, spacing "
                f"{time_text(orders.spacing, WIDTH_DIGITS)}, and the events counted are at "
                f"{range_text('T', first, last)} (Orders settings)")
        return " · ".join((text, *data.notes))
    return ""


def layout_key(data: Fractions) -> tuple[Any, ...]:
    """What a drawing is built for: a newer result with the same is shown in it."""
    return data.orders.numbers, data.newest_shot is not None


def newest_scale(counts: npt.NDArray[np.float64], fresh: npt.NDArray[np.float64]) -> float:
    """The histogram's total over the newest shot's: drawn to the same total, its shape compares."""
    return float(counts.sum()) / float(fresh.sum()) if fresh.sum() > 0 else 1.0


def times_title(data: Fractions) -> str:
    title = "T around the orders, with their windows"
    if data.newest_shot is None:
        return title
    left_out = f"; left out: ≤ {data.minimum:,} counts" if data.newest_left_out else ""
    return (f"{title} · shot {data.newest_shot} highlighted ({int(data.newest.sum()):,} in range, right axis"
            f"{left_out})")


class FractionsPlot(pg.GraphicsLayoutWidget):  # type: ignore[misc]
    """Each order's share per shot over the T histogram around the orders with their windows
    (and, highlighted, the newest shot: drawn to the histogram's total, its real counts on a right
    axis in its colour, as in the T/X/Y histograms); ``show_data`` draws a newer result with the
    same orders and highlight in place, keeping zoom and pan."""

    def __init__(self, key: tuple[Any, ...], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setBackground("w")
        self.key = key
        numbers, highlighted = key
        self.title: Any = add_label(self, row=0, col=0)
        self.colours = [pg.intColor(i, hues=len(numbers), values=1, maxValue=200) for i in range(len(numbers))]
        layout: Any = self  # (pyqtgraph forwards addPlot and ci to its central item: untyped.)
        plot: Any = layout.addPlot(row=1, col=0, axisItems=grouped_axes("bottom", "left"))
        self.fractions_plot = plot
        plot.setLabel("bottom", "Shot number")
        plot.setLabel("left", "Transfer fraction")
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.addLegend(offset=(-10, 10))
        self.fraction_curves = [
            plot.plot([], [], name=f"order {order_label(order)}", connect="finite", pen=pg.mkPen(colour, width=1.5),
                      symbol="o", symbolSize=4, symbolBrush=colour, symbolPen=None)
            for order, colour in zip(numbers, self.colours)]
        times: Any = add_plot(self, "T around the orders, with their windows", row=2, col=0,
                              axisItems=grouped_axes("bottom", "left", *(("right",) if highlighted else ())))
        self.times_plot = times
        times.setLabel("bottom", axis_label("T"))
        times.setLabel("left", "Events (all)" if highlighted else "Events")
        self.times_curve = pg.PlotDataItem(stepMode="center", fillLevel=0, pen=pg.mkPen((60, 60, 60)),
                                           brush=(60, 60, 60, 60))
        times.addItem(self.times_curve)
        # The newest shot drawn to the histogram's total (a transparent line, so the plot's range
        # holds it), its real counts in the overlay (``overlay_newest``, made with the first data).
        self.newest_scaled: Any = None
        self.newest_view: OverlayView | None = None
        if highlighted:
            self.newest_scaled = pg.PlotDataItem(stepMode="center", pen=pg.mkPen((0, 0, 0, 0)))
            times.addItem(self.newest_scaled)
        self.order_windows: list[tuple[Any, Any]] = []
        for column, order in enumerate(numbers):
            region = pg.LinearRegionItem((0.0, 1.0), movable=False, brush=(*self.colours[column].getRgb()[:3], 50),
                                         pen=pg.mkPen(None))
            times.addItem(region)
            label = pg.TextItem(order_label(order), color=self.colours[column], anchor=(0.5, 0))
            times.addItem(label)
            self.order_windows.append((region, label))
        layout.ci.layout.setRowStretchFactor(1, 3)
        layout.ci.layout.setRowStretchFactor(2, 2)

    def show_data(self, result: AnalysisResult, data: Fractions) -> None:
        orders = data.orders
        found = "found" if data.auto else "set"
        title = (f"{result.input.short()} · {shots_text(data.shots.tolist(), data.total_shots)} · order 0 at "
                 f"{time_text(orders.centre)}, spacing {time_text(orders.spacing, WIDTH_DIGITS)}, window "
                 f"±{time_text(orders.half_width, WIDTH_DIGITS)} ({found}){masked_text(data.masked)}")
        self.title.setText(line_html(title) + notes_html(data.notes))  # One note per line.
        fractions = data.fractions
        for column, curve in enumerate(self.fraction_curves):
            curve.setData(data.shots, fractions[:, column])
        edges, counts = data.histogram
        edges = edges * T_SCALE
        set_plot_title(self.times_plot, line_html(times_title(data)))
        if len(counts):
            self.times_curve.setData(edges, counts)
        else:
            self.times_curve.clear()
        if self.newest_scaled is not None and data.newest_shot is not None and len(counts):
            scale = newest_scale(counts, data.newest)
            self.newest_scaled.setData(edges, data.newest * scale)
            name = f"shot {data.newest_shot}"
            fresh = data.newest.astype(np.int64)
            if self.newest_view is None:
                self.newest_view = overlay_newest(self.times_plot, edges, fresh, scale, data.colour, False, name)
            else:
                update_newest(self.times_plot, self.newest_view, edges, fresh, scale, data.colour, False, name)
        top = float(counts.max()) if len(counts) else 1.0
        for order, (region, label) in zip(orders.numbers, self.order_windows):
            low, high = orders.window(order)
            region.setRegion((low * T_SCALE, high * T_SCALE))
            label.setPos((orders.centre + order * orders.spacing) * T_SCALE, top)
