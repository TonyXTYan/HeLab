"""Counts per shot and T/X/Y histograms of a loaded folder. Drawn with PyQtGraph by default
(native Qt drawing, fast to redraw when Live adds shots, and painted on lab PCs that can't paint
QtWebEngine), or with Plotly or Matplotlib (Drawing › Library)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, cast

import numpy as np
import numpy.typing as npt
import plotly.graph_objs as go
import pyqtgraph as pg
from plotly.subplots import make_subplots
from PyQt6.QtCore import QRectF, pyqtSlot
from PyQt6.QtWidgets import QWidget

from helab.analysis.backends import (MATPLOTLIB, PLOTLY, PYQTGRAPH, MatplotlibPane, mpl_colour, mpl_figure,
                                     rgb)
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.panes import PlotlyPane
from helab.analysis.parameters import ParameterSpec
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.dataset_view import DatasetView
from helab.analysis.selection import (SHOT_SPECS, keep_fraction, manual, manual_bounds, newest_brief, newest_colour,
                                      newest_events, newest_shot, newest_specs, range_brief, range_specs,
                                      range_warnings, reversed_axes, select_shots, selection_text, shots_brief,
                                      shots_text)
from helab.analysis.stats import AXES, MAX_BINS, UNITS, Histogram, counts_per_shot, histogram
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.standard import group

RANGE = range_specs(
    "Each histogram covers the exact shortest range holding this share of its axis's events. "
    "100 % covers every event.")
BINS_GROUP = "Histogram"
BINS = ParameterSpec(
    "bins", "Bins", "int", 0, (0, MAX_BINS), "", group=BINS_GROUP,
    tip="0 = automatic: the bin count comes from the data (Freedman–Diaconis: width 2·IQR·n^-1/3).")
LOG_Y = ParameterSpec("log_y", "Log Y", "bool", False, group=BINS_GROUP,
                      tip="Logarithmic event axis; empty bins are left out.")
HIGHLIGHT, NEWEST_COLOUR = newest_specs(BINS_GROUP)
COLOUR = (40, 90, 170)


class DecadeLogAxis(pg.AxisItem):  # type: ignore[misc]
    """A log axis that labels whole decades only, with unlabelled 2…9 ticks between them.
    pyqtgraph labels the 2…9 ticks too when the axis spans under about two decades, and
    those labels overlap. With no whole decade in view it keeps pyqtgraph's own ticks."""

    def logTickValues(self, minVal: float, maxVal: float, size: float,
                      stdTicks: list[tuple[float, list[float]]]) -> list[tuple[float | None, list[float]]]:
        decades = [float(v) for v in range(math.ceil(minVal), math.floor(maxVal) + 1)]
        if not decades:
            return cast(list[tuple[float | None, list[float]]],
                        super().logTickValues(minVal, maxVal, size, stdTicks))
        minor = [v + math.log10(k) for v in range(math.floor(minVal), math.ceil(maxVal)) for k in range(2, 10)]
        self.setStyle(maxTextLevel=0)
        return [(1.0, decades), (None, [v for v in minor if minVal < v < maxVal])]


class OverlayView(pg.ViewBox):  # type: ignore[misc]
    """A view drawn over a plot (``source``, its ViewBox) that leaves the mouse to the plot below
    (its zoom, pan and menu): it only follows the plot's geometry and ranges, its y range the
    plot's divided by ``ratio`` (log Y: shifted by log10 of it). ``follow`` is a Qt slot, so
    the plot's signals hold no Python reference to it and Qt ends the connections when either
    is destroyed: nothing outlives the widget."""

    def __init__(self, source: Any, ratio: float, log_y: bool) -> None:
        super().__init__(enableMenu=False)
        self.setMouseEnabled(x=False, y=False)  # Wheel events then pass to the plot below.
        # (Not ``scale``: that is QGraphicsItem.scale(), which Qt and pyqtgraph call.)
        self._source, self._ratio, self._log_y = source, ratio, log_y
        self._shift = math.log10(ratio) if log_y and ratio > 0 else 0.0
        source.sigResized.connect(self.follow)
        source.sigYRangeChanged.connect(self.follow)

    @pyqtSlot()
    def follow(self) -> None:
        source = self._source
        # The plot's exact geometry (its scene bounding rect is half a pixel larger, which shifts
        # the x link, mapped by pixel, by a pixel where rounding differs).
        self.setGeometry(QRectF(source.scenePos(), source.size()))
        self.linkedViewChanged(source, self.XAxis)  # The x link maps by pixel: again at the new size.
        low, high = source.viewRange()[1]
        if self._log_y:
            self.setYRange(low - self._shift, high - self._shift, padding=0)
        else:
            self.setYRange(low / self._ratio, high / self._ratio, padding=0)

    def mouseDragEvent(self, ev: Any, axis: Any = None) -> None:
        ev.ignore()

    def mouseClickEvent(self, ev: Any) -> None:
        ev.ignore()


def overlay_newest(plot: Any, edges: npt.NDArray[np.float64], counts: npt.NDArray[np.int64], scale: float,
                   colour: tuple[int, int, int], log_y: bool, name: str) -> OverlayView:
    """The newest shot's real counts over ``plot`` in a view of their own, linked on x, with the
    right axis (in ``colour``) reading them. Its y range follows the plot's divided by ``scale``
    (the histogram's total over the shot's; with log Y, shifted by log10 of it), so the line sits
    where the shot's histogram scaled to the same total would."""
    view = OverlayView(plot.vb, scale, log_y)
    plot.scene().addItem(view)
    axis = plot.getAxis("right")
    plot.showAxis("right")
    axis.linkToView(view)
    view.setXLink(plot.vb)
    hex_colour = pg.mkColor(colour).name()
    axis.setPen(pg.mkPen(colour))
    axis.setTextPen(pg.mkPen(colour))
    plot.setLabel("right", f"{name} events", color=hex_colour)
    values = counts.astype(np.float64)
    if log_y:
        values[values <= 0] = np.nan
    curve = pg.PlotDataItem(edges, values, stepMode="center", connect="finite", pen=pg.mkPen(colour, width=2),
                            name=name)
    if log_y:
        curve.setLogMode(False, True)
    view.addItem(curve)
    view.follow()
    return view


@dataclass(frozen=True)
class ShotCounts:
    shots: npt.NDArray[np.int64]
    counts: npt.NDArray[np.int64]
    unsettled_files: int
    total_shots: int = 0  # the shots loaded (``shots`` are the chosen ones)

    @property
    def total(self) -> int:
        return int(self.counts.sum())


@dataclass(frozen=True)
class Histograms:
    items: tuple[Histogram, ...]
    shots: tuple[int, ...]
    total_shots: int
    reversed: tuple[str, ...] = ()  # axes whose manual min > max: shown over their full extent
    # The highlighted newest shot (None: off): its counts in each item's bins, drawn over them.
    newest_shot: int | None = None
    newest: tuple[npt.NDArray[np.int64], ...] = ()
    colour: tuple[int, int, int] = (214, 39, 40)


def counts_title(data: ShotCounts) -> str:
    title = f"{shots_text(data.shots.tolist(), data.total_shots or len(data.shots))} · {data.total:,} events"
    if data.unsettled_files:
        title += f" · {data.unsettled_files} files still being written left out"
    return title


def histogram_title(item: Histogram, reversed_range: bool = False) -> str:
    bins = len(item.counts)
    how = "automatic, Freedman–Diaconis" if item.automatic_bins else "set"
    title = f"{item.axis} · {bins:,} bins ({how}) · {item.total - item.outside:,} of {item.total:,} events"
    title += f" · {item.outside:,} outside the range" if item.outside else ""
    return title + (" · ⚠ min > max, using full extent" if reversed_range else "")


def source_title(result: AnalysisResult, text: str) -> str:
    return f"{result.input.short()} · {text}"


BACKENDS = (PYQTGRAPH, PLOTLY, MATPLOTLIB)
UI_REVISION = "helab.basic_plots"  # Constant: a newer Plotly figure keeps the user's zoom and pan.


def plotly_update(widget: QWidget, figure: Optional[go.Figure]) -> bool:
    """A newer Plotly figure shown in place, on the page already drawn (``PlotlyPane``)."""
    if not isinstance(widget, PlotlyPane) or figure is None:
        return False
    widget.update_figure(figure)
    return True


class CountsPerShot(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Counts per shot",
            description="Number of events in each loaded shot, against shot number",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.counts_per_shot",
            version="2",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*SHOT_SPECS]

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        return selection_text(view, values), shots_brief(values)

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        chosen = select_shots(context.view, context.parameters)
        shots, counts = counts_per_shot(context.view, chosen)
        return ShotCounts(shots, counts, context.view.provenance.unsettled_files, len(context.view.shots))

    def backends(self, action_name: str) -> Sequence[str]:
        return BACKENDS

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        return self.draw(result, PYQTGRAPH, parent)

    def draw(self, result: AnalysisResult, backend: str, parent: Optional[QWidget] = None) -> QWidget:
        data: ShotCounts = result.data
        if not data.total:
            # No shots, none chosen, or chosen shots without events: say which, not a flat line.
            return empty_pane(empty_text(data.total_shots, len(data.shots), 0), parent)
        if backend == PLOTLY:
            return PlotlyPane(counts_plotly(result), parent=parent)
        if backend == MATPLOTLIB:
            return MatplotlibPane(counts_matplotlib(result), parent)
        plot: Any = pg.PlotWidget(parent)
        plot.setBackground("w")
        plot.setTitle(source_title(result, counts_title(data)))
        plot.setLabel("bottom", "Shot number")
        plot.setLabel("left", "Events")
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.plot(data.shots, data.counts, pen=pg.mkPen(COLOUR, width=1),
                  symbol="o", symbolSize=4, symbolBrush=COLOUR, symbolPen=None)
        return cast(QWidget, plot)

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """A rerun (e.g. Live's next shots) updates a Plotly page in place: zoom and pan stay."""
        data: ShotCounts = result.data
        return plotly_update(widget, counts_plotly(result) if data.total else None)


def counts_plotly(result: AnalysisResult) -> go.Figure:
    data: ShotCounts = result.data
    figure = go.Figure(go.Scatter(x=data.shots, y=data.counts, mode="lines+markers", name="events",
                                  line=dict(color=rgb(COLOUR), width=1), marker=dict(size=5, color=rgb(COLOUR)),
                                  hovertemplate="shot %{x}<br>%{y:,} events<extra></extra>"))
    figure.update_layout(title=dict(text=source_title(result, counts_title(data)), x=0.01, font=dict(size=13)),
                         xaxis_title="Shot number", yaxis_title="Events", template="plotly_white",
                         margin=dict(l=60, r=20, t=50, b=50), uirevision=UI_REVISION)
    return figure


def counts_matplotlib(result: AnalysisResult) -> Any:
    data: ShotCounts = result.data
    figure = mpl_figure()
    axes = figure.add_subplot()
    axes.plot(data.shots, data.counts, "-o", color=mpl_colour(COLOUR), linewidth=1, markersize=3)
    axes.set_xlabel("Shot number")
    axes.set_ylabel("Events")
    axes.grid(True, alpha=0.3)
    figure.suptitle(source_title(result, counts_title(data)), fontsize=9, wrap=True)
    return figure


class TxyHistograms(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="T, X, Y histograms",
            description="Distributions of the loaded events' T, X and Y",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.txy_histograms",
            version="3",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*SHOT_SPECS, *RANGE, BINS, LOG_Y, HIGHLIGHT, NEWEST_COLOUR]

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        bins = int(values[BINS.name])
        settings = (shots_brief(values), range_brief(values), f"bins {bins:,}" if bins else "bins auto",
                    "log Y" if values[LOG_Y.name] else "", newest_brief(values))
        return selection_text(view, values), " · ".join(part for part in settings if part)

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        return list(range_warnings(values))

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        values = context.parameters
        shots = select_shots(context.view, values)
        events = context.view.events(shots)
        keep = keep_fraction(values)
        bins = int(values[BINS.name])
        bounds = manual_bounds(values) if manual(values) else (None,) * len(AXES)
        items = []
        newest = newest_shot(values, shots)
        fresh = newest_events(context.view, newest)
        newest_counts = []
        for i, axis in enumerate(AXES):
            context.check()
            column = np.ascontiguousarray(events[:, i])
            given = bounds[i]
            if manual(values) and given is None and len(column):
                given = (float(column.min()), float(column.max()))
            item = histogram(column, axis, keep, bins, given)
            items.append(item)
            if newest is not None:
                newest_counts.append(np.histogram(fresh[:, i], bins=item.edges)[0].astype(np.int64))
        return Histograms(tuple(items), shots, len(context.view.shots), reversed_axes(values), newest,
                          tuple(newest_counts), newest_colour(values))

    def backends(self, action_name: str) -> Sequence[str]:
        return BACKENDS

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        return self.draw(result, PYQTGRAPH, parent)

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """A rerun (e.g. Live's next shots) updates a Plotly page in place: zoom and pan stay."""
        data: Histograms = result.data
        return plotly_update(widget, histograms_plotly(result) if data.items and data.items[0].total else None)

    def draw(self, result: AnalysisResult, backend: str, parent: Optional[QWidget] = None) -> QWidget:
        data: Histograms = result.data
        items = data.items
        if not items or not items[0].total:
            return empty_pane(empty_text(data.total_shots, len(data.shots), 0), parent)
        if backend == PLOTLY:
            return PlotlyPane(histograms_plotly(result), parent=parent)
        if backend == MATPLOTLIB:
            return MatplotlibPane(histograms_matplotlib(result), parent)
        log_y = bool(result.parameters.get(LOG_Y.name, False))
        widget: Any = pg.GraphicsLayoutWidget(parent)
        widget.setBackground("w")
        widget.addLabel(histograms_title(result), row=0, col=0)
        overlays = []
        for row, item in enumerate(items, start=1):
            highlighted = data.newest_shot is not None and row - 1 < len(data.newest)
            # A right axis only for the newest shot's counts (pyqtgraph shows any axis it is given).
            axes = ({"left": DecadeLogAxis("left"), **({"right": DecadeLogAxis("right")} if highlighted else {})}
                    if log_y else None)
            plot = widget.addPlot(row=row, col=0, title=histogram_title(item, item.axis in data.reversed),
                                  axisItems=axes)
            plot.setLabel("bottom", f"{item.axis} ({UNITS[AXES.index(item.axis)]})")
            plot.setLabel("left", "Events")
            if log_y:
                # Empty bins have no logarithm: they are left out of the bars.
                counts = item.counts.astype(np.float64)
                counts[counts <= 0] = np.nan
                plot.setLogMode(x=False, y=True)
                plot.addItem(pg.PlotDataItem(item.edges, counts, stepMode="center", connect="finite",
                                             pen=pg.mkPen(COLOUR)))
            else:
                plot.addItem(pg.PlotDataItem(item.edges, item.counts, stepMode="center", fillLevel=0,
                                             pen=pg.mkPen(COLOUR), brush=(*COLOUR, 90)))
            if highlighted:
                # One shot is a small share of all: drawn to the histogram's scale (its total over
                # the shot's), its shape compares; its own axis on the right reads its real counts.
                left = plot.getAxis("left")
                left.setPen(pg.mkPen(COLOUR))
                left.setTextPen(pg.mkPen(COLOUR))
                plot.setLabel("left", "Events (all)", color=pg.mkColor(COLOUR).name())
                counts_new = data.newest[row - 1]
                scale = float(item.counts.sum()) / float(counts_new.sum()) if counts_new.sum() > 0 else 1.0
                # The scaled line, transparent (hidden items don't count), keeps the plot's own range
                # (and its Auto) holding the overlay.
                scaled = counts_new * scale
                if log_y:
                    scaled = np.where(scaled > 0, scaled, np.nan)
                plot.addItem(pg.PlotDataItem(item.edges, scaled, stepMode="center", connect="finite",
                                             pen=pg.mkPen((0, 0, 0, 0))))
                overlays.append(overlay_newest(plot, item.edges, counts_new, scale, data.colour, log_y,
                                               f"shot {data.newest_shot}"))
        widget.newest_views = overlays  # Kept with the widget (they live in its scene).
        return cast(QWidget, widget)


def histograms_title(result: AnalysisResult, where: str = "right axis") -> str:
    data: Histograms = result.data
    items = data.items
    events = f"{items[0].total:,} events" if items else ""
    newest = (f" · shot {data.newest_shot} highlighted ({int(data.newest[0].sum()):,} in range, {where})"
              if data.newest_shot is not None and data.newest else "")
    return source_title(result, f"{shots_text(data.shots, data.total_shots)} · {events}{newest}")


def newest_scale(item: Histogram, counts: npt.NDArray[np.int64]) -> float:
    """The histogram's total over the newest shot's: the shot drawn to the same total compares
    in shape."""
    return float(item.counts.sum()) / float(counts.sum()) if counts.sum() > 0 else 1.0


def histograms_plotly(result: AnalysisResult) -> go.Figure:
    """The histograms in three rows. The newest shot is drawn to each histogram's scale, its real
    counts in its hover text (a Plotly axis can't follow another's zoom at a ratio)."""
    data: Histograms = result.data
    log_y = bool(result.parameters.get(LOG_Y.name, False))
    titles = [histogram_title(item, item.axis in data.reversed) for item in data.items]
    figure = make_subplots(rows=len(data.items), cols=1, subplot_titles=titles, vertical_spacing=0.09)
    for row, item in enumerate(data.items, start=1):
        counts = item.counts.astype(np.float64)
        if log_y:
            counts[counts <= 0] = np.nan  # Empty bins have no logarithm.
        # A step line over the edges: each bin's count from its left edge to the next.
        figure.add_trace(go.Scatter(
            x=item.edges, y=np.append(counts, counts[-1] if len(counts) else np.nan), mode="lines",
            line=dict(shape="hv", color=rgb(COLOUR), width=1), fill=None if log_y else "tozeroy",
            fillcolor=rgb(COLOUR, 0.35), name=f"{item.axis}: all chosen shots", showlegend=row == 1,
            legendgroup="all", hovertemplate=f"{item.axis} %{{x:.6g}}<br>%{{y:,}} events<extra></extra>"),
            row=row, col=1)
        if data.newest_shot is not None and row - 1 < len(data.newest):
            fresh = data.newest[row - 1]
            scale = newest_scale(item, fresh)
            scaled = fresh * scale
            if log_y:
                scaled = np.where(scaled > 0, scaled, np.nan)
            figure.add_trace(go.Scatter(
                x=item.edges, y=np.append(scaled, scaled[-1] if len(scaled) else np.nan),
                customdata=np.append(fresh, fresh[-1] if len(fresh) else 0), mode="lines",
                line=dict(shape="hv", color=rgb(data.colour), width=2),
                name=f"shot {data.newest_shot} (×{scale:.3g} to the same total)", showlegend=row == 1,
                legendgroup="newest",
                hovertemplate=f"{item.axis} %{{x:.6g}}<br>shot {data.newest_shot}: %{{customdata:,}} events"
                              f"<extra></extra>"),
                row=row, col=1)
        figure.update_xaxes(title_text=f"{item.axis} ({UNITS[AXES.index(item.axis)]})", row=row, col=1)
        figure.update_yaxes(title_text="Events", type="log" if log_y else "linear", row=row, col=1)
    figure.update_annotations(font_size=11)
    figure.update_layout(title=dict(text=histograms_title(result, "scaled; hover for its counts"), x=0.01,
                                    font=dict(size=13)),
                         template="plotly_white", margin=dict(l=60, r=20, t=80, b=40), uirevision=UI_REVISION,
                         legend=dict(x=0.99, xanchor="right", y=1.0, yanchor="bottom", orientation="h"),
                         showlegend=data.newest_shot is not None)
    return figure


def histograms_matplotlib(result: AnalysisResult) -> Any:
    """The histograms in three rows; the newest shot on a right axis reading its real counts,
    which follows the left one's zoom at the histogram's scale."""
    data: Histograms = result.data
    log_y = bool(result.parameters.get(LOG_Y.name, False))
    figure = mpl_figure()
    rows = figure.subplots(len(data.items), 1, squeeze=False)[:, 0]
    for row, (axes, item) in enumerate(zip(rows, data.items)):
        counts = item.counts.astype(np.float64)
        if log_y:
            counts[counts <= 0] = np.nan
            axes.set_yscale("log")
            axes.stairs(counts, item.edges, color=mpl_colour(COLOUR), baseline=None)
        else:
            axes.stairs(counts, item.edges, fill=True, color=mpl_colour(COLOUR, 0.35),
                        edgecolor=mpl_colour(COLOUR))
        axes.set_title(histogram_title(item, item.axis in data.reversed), fontsize=8)
        axes.set_xlabel(f"{item.axis} ({UNITS[AXES.index(item.axis)]})", fontsize=8)
        axes.set_ylabel("Events (all)" if data.newest_shot is not None else "Events", fontsize=8)
        axes.tick_params(labelsize=7)
        if data.newest_shot is not None and row < len(data.newest):
            fresh = data.newest[row]
            scale = newest_scale(item, fresh)
            right = axes.twinx()
            if log_y:
                right.set_yscale("log")
            values = fresh.astype(np.float64)
            if log_y:
                values[values <= 0] = np.nan
            right.stairs(values, item.edges, color=mpl_colour(data.colour), linewidth=1.5, baseline=None,
                         label=f"shot {data.newest_shot}")
            right.set_ylabel(f"shot {data.newest_shot} events", color=mpl_colour(data.colour), fontsize=8)
            right.tick_params(axis="y", colors=mpl_colour(data.colour), labelsize=7)

            def follow(left: Any, right: Any = right, scale: float = scale) -> None:
                low, high = left.get_ylim()
                right.set_ylim(low / scale, high / scale)

            follow(axes)
            axes.callbacks.connect("ylim_changed", follow)
    figure.suptitle(histograms_title(result), fontsize=9, wrap=True)
    return figure
