"""Transfer fractions: the share of each shot's atoms in each diffraction order (or magnetic
state), against shot number, with the orders found in the arrival-time histogram.

Ported from ``monitor_momentum.m`` and ``lib/fraction_calc.m`` in the lab's MATLAB analysis,
https://github.com/HeBECANU/Momentum_Bells_test (``legacy/Momentum_Bells_test``). There the
time windows of the states were typed into the script; here they are found from the data:
the tallest peak of the T histogram is order 0, the clear side peaks near whole multiples of the
Reference spacing (15 ms, as in those windows) give the spacing, and order k's window is ``centre + k·spacing ± half-width`` (+k arrives later). Switching
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

import html
import math
from typing import Any, List, Mapping, Optional, Sequence, cast

import numpy as np
import numpy.typing as npt
import plotly.graph_objs as go
import pyqtgraph as pg
from plotly.subplots import make_subplots
from PyQt6.QtWidgets import QWidget

from helab.analysis.dataset_view import DatasetView, txy
from helab.analysis.backends import (FOLLOWER, MATPLOTLIB, PLOTLY, PYQTGRAPH, MatplotlibPane, WrappingLabel,
                                     matplotlib_pane, mpl_colour, mpl_figure, rgb, set_title)
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.orders import (DEFAULT_CENTRE, REFERENCE_SLACK, Fractions, Orders, chosen_by_search, count_orders,
                                   detect, in_box, jump, order_label, unsure, window_half)
from helab.analysis.overlay import overlay_newest
from helab.analysis.panes import PlotlyPane
from helab.analysis.parameters import ParameterSpec
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import (SHOT_SPECS, newest_brief, newest_colour, newest_shot, newest_specs, select_shots,
                                      selection_text, shots_brief, shots_text)
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.standard import group

AUTO, MANUAL = "auto", "manual"
ORDERS_GROUP = "Orders"
MODE = ParameterSpec("orders_mode", "Orders", "choice", AUTO, choices=(AUTO, MANUAL), group=ORDERS_GROUP,
                     tip="Auto finds order 0 (the tallest peak in T) and the spacing (the clear side peaks "
                         "near multiples of the reference spacing) on each run; manual uses the centre and spacing below, which each auto run "
                         "fills in (not the centre when order 0 jumped a whole order: the plot warns).")
EACH_SIDE = ParameterSpec("orders_each_side", "Orders each side", "int", 2, (1, 6), group=ORDERS_GROUP,
                          tip="Orders −N…+N are counted; +1 arrives later than 0.")
CENTRE = ParameterSpec("centre", "Order 0 at", "float", DEFAULT_CENTRE, (0.0, 100.0), " s", group=ORDERS_GROUP,
                       when=(MODE.name, MANUAL), si=True, tip="Arrival time of order 0.")
SPACING = ParameterSpec("spacing", "Spacing", "float", 0.015, (1e-6, 10.0), " s", group=ORDERS_GROUP,
                        when=(MODE.name, MANUAL), si=True, tip="Time between neighbouring orders.")
REFERENCE = ParameterSpec("reference_spacing", "Reference spacing", "float", 0.015, (1e-6, 10.0), " s",
                          group=ORDERS_GROUP, when=(MODE.name, AUTO), si=True,
                          tip="Roughly the time between neighbouring orders. Auto takes order ±k only from a clear "
                              "peak within 30 % of a spacing from k spacings away (starting from this one, then "
                              "the spacing found so far), so a bump between the orders isn't taken for one.")
HALF_WIDTH = ParameterSpec("half_width", "Window ± (0 = half spacing)", "float", 0.0, (0.0, 10.0), " s",
                           group=ORDERS_GROUP, si=True,
                           tip="Each order's window is its time ± this; 0 makes neighbouring windows touch. Over "
                               "half the spacing it is clipped to that (the plot says so): windows never overlap.")
SEARCH_MIN = ParameterSpec("search_min", "Search T from (0 = first)", "float", 0.0, (0.0, 100.0), " s",
                           group=ORDERS_GROUP, when=(MODE.name, AUTO), si=True,
                           tip="Auto looks for the orders between these times; 0 leaves that end open. Put order 0 "
                               "inside: the tallest peak here is taken as order 0. With both ends set, the plot "
                               "doesn't warn about orders outside it.")
SEARCH_MAX = ParameterSpec("search_max", "Search T to (0 = last)", "float", 0.0, (0.0, 100.0), " s",
                           group=ORDERS_GROUP, when=(MODE.name, AUTO), si=True,
                           tip="See Search T from. A From at or above To searches every event, and the plot says so.")
BOX_GROUP = "Counting"
XY_HALF = ParameterSpec("xy_half", "XY box ±", "float", 0.03, (0.0, 1.0), " m", group=BOX_GROUP, si=True,
                        tip="Only events with |X| and |Y| within this count (0 = no XY limit); keeps a hot spot "
                            "out of the counts.")
MIN_COUNTS = ParameterSpec("min_counts", "Minimum counts", "int", 50, (0, 10_000_000), group=BOX_GROUP,
                           tip="Shots with no more events than this in the XY box are left out.")
HIGHLIGHT, NEWEST_COLOUR = newest_specs("T histogram")
PARAMETERS = (*SHOT_SPECS, MODE, EACH_SIDE, CENTRE, SPACING, REFERENCE, HALF_WIDTH, SEARCH_MIN, SEARCH_MAX, XY_HALF,
              MIN_COUNTS, HIGHLIGHT, NEWEST_COLOUR)


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
            analysis_id="helab.transfer_fractions",
            version="8",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*PARAMETERS]

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        each = int(values[EACH_SIDE.name])
        how = f"manual orders ±{each}"
        if values[MODE.name] == AUTO:
            how = f"auto orders ±{each} ~{float(values[REFERENCE.name]) * 1e3:.3g} ms"
        half = float(values[XY_HALF.name])
        box = f"XY ±{half * 1e3:g} mm" if half > 0 else "no XY limit"
        settings = (shots_brief(values), how, box, f"> {int(values[MIN_COUNTS.name]):,} counts",
                    newest_brief(values))
        return selection_text(view, values), " · ".join(part for part in settings if part)

    def detected_parameters(self, action_name: str, result: AnalysisResult) -> dict[str, Any]:
        data = result.data
        if not isinstance(data, Fractions) or not data.auto or not data.detected:
            return {}
        if data.jumped:  # The last detection's order 0 stays: the warning stays too, and manual starts there.
            return {SPACING.name: data.orders.spacing}
        return {CENTRE.name: data.orders.centre, SPACING.name: data.orders.spacing}

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        if values[MODE.name] == AUTO:
            return list(search_warnings(values))  # The spacing, and so the window's limit, is found later.
        _, clipped = window_half(float(values[HALF_WIDTH.name]), float(values[SPACING.name]))
        return [clipped] if clipped else []

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        values = context.parameters
        view = context.view
        chosen = select_shots(view, values)
        half, minimum = float(values[XY_HALF.name]), int(values[MIN_COUNTS.name])
        each_side = int(values[EACH_SIDE.name])
        boxed: dict[int, npt.NDArray[np.float64]] = {}
        events_total = not_finite = 0
        for shot in chosen:
            context.check()
            events = txy(np.asarray(view.shots[shot], dtype=np.float64))
            events_total += len(events)
            finite = np.isfinite(events[:, 0])
            if not finite.all():
                not_finite += len(events) - int(np.count_nonzero(finite))
                events = events[finite]
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
                reference = float(values[REFERENCE.name])
                found = detect(searched, lower, upper if upper > lower else lower + 1e-6, each_side, reference)
                centre, detected = found.centre, True
                if found.spacing is None:
                    coarse = (f"; T bins of {found.edges[1] - found.edges[0]:.2g} s are coarse for order 0, narrow "
                              f"Search T") if found.coarse else ""
                    notes.append(f"no side peak found beyond order 0's width ({found.fwhm * 1e3:.3g} ms) within "
                                 f"{REFERENCE_SLACK * 100:.0f} % of k × the reference spacing ({reference * 1e3:.3g} ms): "
                                 f"spacing as set{coarse}")
                else:
                    spacing = found.spacing
                if found.fwhm > spacing / 2:
                    notes.append(f"orders overlap: order 0's width (FWHM {found.fwhm * 1e3:.3g} ms) is over half the "
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
                notes.append(f"order 0 now at {centre:.6g} s; the last detection, {previous:.6g} s, was outside "
                             f"Search T")
            if jumped:
                notes.append(f"⚠ order 0 moved by {order_label(jumped)} order{'' if abs(jumped) == 1 else 's'} "
                             f"from the last detection ({previous:.6g} s → {centre:.6g} s): a strong transfer can "
                             f"make another order the tallest. Manual starts from the last one; to accept the new "
                             f"one, set Order 0 at {centre:.6g} s in manual mode, Rerun, then back to Auto")
        empty = int(np.count_nonzero(counts.sum(axis=1) == 0))
        if empty and empty < len(boxed):
            notes.append(f"{empty:,} shot{'' if empty == 1 else 's'} with no events in the windows: no fractions")
        span = (each_side + 1) * spacing
        around = times[np.abs(times - centre) <= span]
        histogram = np.histogram(around, bins=400, range=(centre - span, centre + span)) if len(times) else None
        # The newest chosen shot, even one Minimum counts left out (a bad shot is worth seeing).
        newest = newest_shot(values, chosen) if histogram is not None else None
        fresh = np.empty(0)
        if newest is not None and histogram is not None:
            shot_times = boxed[newest] if newest in boxed else in_box(txy(np.asarray(view.shots[newest])), half)[:, 0]
            fresh = np.histogram(shot_times[np.isfinite(shot_times)], bins=histogram[1])[0].astype(np.float64)
        return Fractions(orders, np.fromiter(boxed, dtype=np.int64, count=len(boxed)), counts, len(chosen),
                         len(view.shots), auto, tuple(notes),
                         (histogram[1], histogram[0].astype(np.float64)) if histogram else (np.empty(0), np.empty(0)),
                         detected, minimum, events_total,
                         (float(times.min()), float(times.max())) if len(times) else (math.nan, math.nan),
                         jumped, newest, fresh, newest is not None and newest not in boxed, newest_colour(values))

    def backends(self, action_name: str) -> Sequence[str]:
        return (PYQTGRAPH, PLOTLY, MATPLOTLIB)

    def minimum_size(self, action_name: str) -> tuple[int, int]:
        return 240, 360  # Two plots stacked under a title and notes.

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        return self.draw(result, PYQTGRAPH, parent)

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """A rerun (e.g. Live's next shots) updates the plot in place, in every library: a zoom
        or pan stays, else the axes follow the new data. PyQtGraph draws anew when the number of
        orders, the highlight or its colour changed."""
        data: Fractions = result.data
        if empty_reason(data):
            return False
        if isinstance(widget, PlotlyPane):
            widget.update_figure(plotly_figure(result))
            return True
        if isinstance(widget, pg.GraphicsLayoutWidget):
            if getattr(widget, "order_numbers", None) != pyqtgraph_layout(data):
                return False
            fill_pyqtgraph(widget, result)
            return True
        pane = matplotlib_pane(widget)
        if pane is None:
            return False
        pane.redraw(lambda figure: matplotlib_figure(result, figure))
        return True

    def draw(self, result: AnalysisResult, backend: str, parent: Optional[QWidget] = None) -> QWidget:
        data: Fractions = result.data
        orders = data.orders
        if text := empty_reason(data):
            return empty_pane(text, parent)
        if backend == PLOTLY:
            return PlotlyPane(plotly_figure(result), parent=parent)
        if backend == MATPLOTLIB:
            return MatplotlibPane(matplotlib_figure(result), parent)
        widget: Any = pg.GraphicsLayoutWidget(parent)
        widget.setBackground("w")
        widget.title_label = WrappingLabel("")
        widget.addItem(widget.title_label, row=0, col=0)
        colours = [pg.mkColor(colour) for colour in order_colours(orders)]
        plot = widget.addPlot(row=1, col=0)
        plot.setLabel("bottom", "Shot number")
        plot.setLabel("left", "Transfer fraction")
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.addLegend(offset=(-10, 10))
        widget.fraction_curves = [
            plot.plot(name=f"order {order_label(order)}", connect="finite", pen=pg.mkPen(colour, width=1.5),
                      symbol="o", symbolSize=4, symbolBrush=colour, symbolPen=None)
            for order, colour in zip(orders.numbers, colours)]
        times = widget.addPlot(row=2, col=0)
        widget.times_plot = times
        times.setLabel("bottom", "T (s)")
        times.setLabel("left", "Events")
        widget.times_curve = pg.PlotDataItem(stepMode="center", fillLevel=0, pen=pg.mkPen((60, 60, 60)),
                                             brush=(60, 60, 60, 60))
        times.addItem(widget.times_curve)
        widget.newest_view = widget.newest_scaled = None
        if data.newest_shot is not None:
            # As in the T/X/Y histograms: the shot drawn to the histogram's total (a transparent
            # line keeping the plot's range holding it), its real counts on the right axis.
            left = times.getAxis("left")
            left.setPen(pg.mkPen((60, 60, 60)))
            left.setTextPen(pg.mkPen((60, 60, 60)))
            times.setLabel("left", "Events (all)")
            edges, counts = data.histogram
            scale = newest_scale(counts, data.newest)
            widget.newest_scaled = pg.PlotDataItem(edges, data.newest * scale, stepMode="center",
                                                   pen=pg.mkPen((0, 0, 0, 0)))
            times.addItem(widget.newest_scaled)
            widget.newest_view = overlay_newest(times, edges, data.newest.astype(np.int64), scale, data.colour,
                                                False, f"shot {data.newest_shot}")
        widget.order_windows = []
        for column, order in enumerate(orders.numbers):
            region = pg.LinearRegionItem(orders.window(order), movable=False,
                                         brush=(*colours[column].getRgb()[:3], 50), pen=pg.mkPen(None))
            times.addItem(region)
            label = pg.TextItem(order_label(order), color=colours[column], anchor=(0.5, 0))
            times.addItem(label)
            widget.order_windows.append((region, label))
        widget.ci.layout.setRowStretchFactor(1, 3)
        widget.ci.layout.setRowStretchFactor(2, 2)
        widget.order_numbers = pyqtgraph_layout(data)
        fill_pyqtgraph(widget, result)
        return cast(QWidget, widget)


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
        text = (f"No events in the orders' windows: order 0 at {orders.centre:.6g} s, spacing "
                f"{orders.spacing * 1e3:.4g} ms, and the events counted are at T {first:.6g}–{last:.6g} s "
                f"(Orders settings)")
        return " · ".join((text, *data.notes))
    return ""


def fractions_title(result: AnalysisResult) -> str:
    data: Fractions = result.data
    orders = data.orders
    found = "found" if data.auto else "set"
    return (f"{result.input.short()} · {shots_text(data.shots.tolist(), data.total_shots)} · order 0 at "
            f"{orders.centre:.6g} s, spacing {orders.spacing * 1e3:.4g} ms, window ±{orders.half_width * 1e3:.3g} ms "
            f"({found})")


def order_colours(orders: Orders) -> list[tuple[int, int, int]]:
    """One colour per order, the same in every library."""
    count = len(orders.numbers)
    return [cast(tuple[int, int, int], tuple(pg.intColor(i, hues=count, values=1, maxValue=200).getRgb()[:3]))
            for i in range(count)]


def plotly_figure(result: AnalysisResult) -> go.Figure:
    data: Fractions = result.data
    orders = data.orders
    colours = order_colours(orders)
    figure = make_subplots(rows=2, cols=1, row_heights=[0.6, 0.4], vertical_spacing=0.12,
                           subplot_titles=("", times_title(data)))
    fractions = data.fractions
    for column, order in enumerate(orders.numbers):
        colour = rgb(colours[column])
        figure.add_trace(go.Scatter(x=data.shots, y=fractions[:, column], mode="lines+markers",
                                    name=f"order {order_label(order)}", line=dict(color=colour, width=1.5),
                                    marker=dict(size=5, color=colour), connectgaps=False,
                                    hovertemplate=f"shot %{{x}}<br>order {order_label(order)}: %{{y:.3f}}"
                                                  f"<extra></extra>"),
                         row=1, col=1)
    edges, counts = data.histogram
    if len(counts):
        figure.add_trace(go.Scatter(x=edges, y=np.append(counts, counts[-1]), mode="lines", showlegend=False,
                                    line=dict(shape="hv", color="rgb(60, 60, 60)", width=1), fill="tozeroy",
                                    fillcolor="rgba(60, 60, 60, 0.25)",
                                    hovertemplate="T %{x:.6g} s<br>%{y:,} events<extra></extra>"),
                         row=2, col=1)
    if data.newest_shot is not None and len(counts):
        # Drawn to the histogram's scale (an axis can't follow another's zoom at a ratio in Plotly),
        # its real counts in the hover text.
        scale = newest_scale(counts, data.newest)
        scaled = data.newest * scale
        figure.add_trace(go.Scatter(
            x=edges, y=np.append(scaled, scaled[-1]), customdata=np.append(data.newest, data.newest[-1]),
            mode="lines", line=dict(shape="hv", color=rgb(data.colour), width=2),
            name=f"shot {data.newest_shot} (×{scale:.3g} to the same total)",
            hovertemplate=f"T %{{x:.6g}} s<br>shot {data.newest_shot}: %{{customdata:,}} events<extra></extra>"),
            row=2, col=1)
    top = float(counts.max()) if len(counts) else 1.0
    for column, order in enumerate(orders.numbers):
        low, high = orders.window(order)
        cast(Any, figure).add_vrect(x0=low, x1=high, fillcolor=rgb(colours[column]), opacity=0.2, line_width=0,
                                    row=2, col=1)
        figure.add_annotation(x=orders.centre + order * orders.spacing, y=top, text=order_label(order),
                              showarrow=False, yanchor="bottom", font=dict(color=rgb(colours[column])),
                              row=2, col=1)
    figure.update_xaxes(title_text="Shot number", row=1, col=1)
    figure.update_yaxes(title_text="Transfer fraction", row=1, col=1)
    figure.update_xaxes(title_text="T (s)", row=2, col=1)
    figure.update_yaxes(title_text="Events", row=2, col=1)
    notes = " · ".join(data.notes)
    title = html.escape(fractions_title(result))
    if notes:
        title += f'<br><span style="color: #b06000; font-size: 11px">{html.escape(notes)}</span>'
    figure.update_layout(title=dict(text=title, x=0.01, font=dict(size=13)), template="plotly_white",
                         margin=dict(l=60, r=20, t=90 if notes else 60, b=40), uirevision="helab.transfer_fractions")
    return figure


def matplotlib_figure(result: AnalysisResult, figure: Any = None) -> Any:
    data: Fractions = result.data
    orders = data.orders
    colours = order_colours(orders)
    figure = mpl_figure(figure)
    shares, times = figure.subplots(2, 1, height_ratios=[3, 2])
    fractions = data.fractions
    for column, order in enumerate(orders.numbers):
        shares.plot(data.shots, fractions[:, column], "-o", color=mpl_colour(colours[column]), linewidth=1.5,
                    markersize=3, label=f"order {order_label(order)}")
    shares.set_xlabel("Shot number", fontsize=8)
    shares.set_ylabel("Transfer fraction", fontsize=8)
    shares.grid(True, alpha=0.3)
    shares.legend(fontsize=7, loc="upper right")
    edges, counts = data.histogram
    if len(counts):
        times.stairs(counts, edges, fill=True, color=(60 / 255, 60 / 255, 60 / 255, 0.25),
                     edgecolor=(60 / 255, 60 / 255, 60 / 255))
    top = float(counts.max()) if len(counts) else 1.0
    for column, order in enumerate(orders.numbers):
        times.axvspan(*orders.window(order), color=mpl_colour(colours[column], 0.2), linewidth=0)
        times.text(orders.centre + order * orders.spacing, top, order_label(order), ha="center", va="bottom",
                   color=mpl_colour(colours[column]), fontsize=8)
    times.set_title(times_title(data), fontsize=8)
    times.set_xlabel("T (s)", fontsize=8)
    times.set_ylabel("Events (all)" if data.newest_shot is not None else "Events", fontsize=8)
    if data.newest_shot is not None and len(counts):
        # As in the T/X/Y histograms: a right axis reading the shot's real counts, following the
        # left one's zoom at the histogram's scale.
        scale = newest_scale(counts, data.newest)
        right = times.twinx()
        setattr(right, FOLLOWER, True)
        right.stairs(data.newest, edges, color=mpl_colour(data.colour), linewidth=1.5, baseline=None)
        right.set_ylabel(f"shot {data.newest_shot} events", color=mpl_colour(data.colour), fontsize=8)
        right.tick_params(axis="y", colors=mpl_colour(data.colour), labelsize=7)

        def follow(left: Any, right: Any = right, scale: float = scale) -> None:
            low, high = left.get_ylim()
            right.set_ylim(low / scale, high / scale)

        follow(times)
        times.callbacks.connect("ylim_changed", follow)
    for axes in (shares, times):
        axes.tick_params(labelsize=7)
    title = fractions_title(result)
    figure.suptitle(title, fontsize=9, wrap=True)
    if data.notes:
        shares.set_title(" · ".join(data.notes), fontsize=7, color=(0.69, 0.38, 0.0), wrap=True)
    return figure


def fill_pyqtgraph(widget: Any, result: AnalysisResult) -> None:
    """``result`` in a PyQtGraph drawing built for its orders (``widget.order_numbers``)."""
    data: Fractions = result.data
    orders = data.orders
    notes = ' · '.join(data.notes)
    notes = f'<br><span style="color: #b06000">{html.escape(notes)}</span>' if notes else ""
    widget.title_label.setText(html.escape(fractions_title(result)) + notes)
    fractions = data.fractions
    for column, curve in enumerate(widget.fraction_curves):
        curve.setData(data.shots, fractions[:, column])
    edges, counts = data.histogram
    set_title(widget.times_plot, times_title(data))
    if len(counts):
        widget.times_curve.setData(edges, counts)
    else:
        widget.times_curve.clear()
    if widget.newest_view is not None:
        scale = newest_scale(counts, data.newest)
        widget.newest_scaled.setData(edges, data.newest * scale)
        widget.newest_view.curve.setData(edges, data.newest)
        widget.times_plot.setLabel("right", f"shot {data.newest_shot} events", color=pg.mkColor(data.colour).name())
        widget.newest_view.set_ratio(scale)
    top = float(counts.max()) if len(counts) else 1.0
    for order, (region, label) in zip(orders.numbers, widget.order_windows):
        region.setRegion(orders.window(order))
        label.setPos(orders.centre + order * orders.spacing, top)


def pyqtgraph_layout(data: Fractions) -> tuple[Any, ...]:
    """What a PyQtGraph drawing is built for: a newer result with the same is shown in it."""
    return data.orders.numbers, data.newest_shot is not None, data.colour if data.newest_shot is not None else None


def newest_scale(counts: npt.NDArray[np.float64], fresh: npt.NDArray[np.float64]) -> float:
    """The histogram's total over the newest shot's: drawn to the same total, its shape compares."""
    return float(counts.sum()) / float(fresh.sum()) if fresh.sum() > 0 else 1.0


def times_title(data: Fractions) -> str:
    title = "T around the orders, with their windows"
    if data.newest_shot is None:
        return title
    left_out = f"; left out: ≤ {data.minimum:,} counts" if data.newest_left_out else ""
    return f"{title} · shot {data.newest_shot} highlighted ({int(data.newest.sum()):,} in range{left_out})"
