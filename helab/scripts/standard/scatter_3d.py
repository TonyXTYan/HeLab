"""The 3D scatter of a loaded folder's T/X/Y events: Plotly (served by the Dash server) by
default, or Matplotlib's 3D axes, or PyQtGraph's OpenGL view (Drawing › Library)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Sequence, cast

import numpy as np
import numpy.typing as npt
import plotly.graph_objs as go
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from helab.analysis.backends import (MATPLOTLIB, PLOTLY, PYQTGRAPH, MatplotlibPane, mpl_colour, mpl_figure,
                                     opengl_available)
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.follow import LivePolicy
from helab.analysis.panes import PlotlyPane
from helab.analysis.parameters import ParameterSpec
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.dataset_view import DatasetView, txy
from helab.analysis.selection import (SHOT_SPECS, keep_fraction, manual, manual_box, newest_brief, newest_colour,
                                      newest_shot, newest_specs, range_brief, range_specs, range_warnings,
                                      select_shots, selection_text, shots_brief, shots_text)
from helab.analysis.stats import AXES, DISPLAY_CAP, UNITS, CropBox, axis_text, crop_box, display_sample
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.standard import group

RANGE = range_specs(
    "Crop to a box holding at least this share of the events, found by a heuristic (not the "
    "narrowest possible box): sparse ends of T, X and Y are left out first, then each axis is "
    "narrowed to its shortest window over the events inside the others. 100 % keeps every event.")
KEEP = RANGE[1]
POINTS = "Points"
POINT_SIZE = ParameterSpec("point_size", "Point size", "float", 1.5, (0.5, 10.0), " px", group=POINTS,
                           tip="Marker size in pixels.")
OPACITY = ParameterSpec("opacity", "Opacity", "float", 0.5, (0.05, 1.0), group=POINTS,
                        tip="Marker opacity: lower shows density in dense regions.")
CAP = ParameterSpec("display_cap", "Display cap", "int", DISPLAY_CAP, (1_000, 2_000_000), group=POINTS,
                    tip="At most this many events are drawn (a fixed random sample of the events in the "
                        "range); the crop and the counts use all of them.")
HIGHLIGHT, NEWEST_COLOUR = newest_specs(POINTS)


UI_REVISION = "helab.scatter_3d"


@dataclass(frozen=True)
class ScatterData:
    crop: CropBox
    points: npt.NDArray[np.float64]  # the displayed sample of the events inside the crop
    shots: tuple[int, ...]  # the shot numbers used
    total_shots: int  # the shots loaded
    cap: int = DISPLAY_CAP
    warnings: tuple[str, ...] = ()  # settings not followed as given (``range_warnings``)
    # The highlighted newest shot (None: off) and its events inside the crop, drawn apart.
    newest_shot: int | None = None
    newest: npt.NDArray[np.float64] = field(default_factory=lambda: np.empty((0, 3)))
    colour: tuple[int, int, int] = (214, 39, 40)

    @property
    def analysed(self) -> int:
        return self.crop.kept

    @property
    def shown(self) -> int:
        return len(self.points) + len(self.newest)


def sample_text(data: ScatterData) -> str:
    shown, analysed = data.shown, data.analysed
    if shown == analysed:
        return f"Showing all {analysed:,} events in the range"
    return (f"Showing a random sample of {shown:,} of {analysed:,} events in the range "
            f"(display cap {data.cap:,}; the analysis uses all of them)")


def crop_text(crop: CropBox, warnings: tuple[str, ...] = ()) -> str:
    warning = "".join(f" · ⚠ {text}" for text in warnings)
    if crop.total == 0:
        return "No events" + warning
    bounds = " · ".join(axis_text(i, crop.lower[i], crop.upper[i]) for i in range(len(AXES)))
    how = "Manual range" if crop.manual else "Auto-crop (heuristic box)"
    return f"{how} keeps {crop.fraction:.1%} ({crop.kept:,} of {crop.total:,} events): {bounds}{warning}"


def note_text(data: ScatterData) -> str:
    """One line above the plot; the full sample and crop text are in its tooltip and the figure."""
    shown = (f"All {data.analysed:,} events in range shown" if data.shown == data.analysed else
             f"Display sample: {data.shown:,} of {data.analysed:,} events in range")
    how = "manual range" if data.crop.manual else "crop"
    text = f"{shown} · {how} keeps {data.crop.fraction:.1%} of {data.crop.total:,} · {shots_text(data.shots, data.total_shots)}"
    if data.newest_shot is not None:
        text += f" · shot {data.newest_shot} highlighted ({len(data.newest):,} events)"
    return text + "".join(f" · ⚠ {warning}" for warning in data.warnings)


class Scatter3D(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="3D scatter",
            description="T/X/Y events of the loaded folder, cropped to the region holding most events",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.scatter_3d",
            version="3",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*SHOT_SPECS, *RANGE, POINT_SIZE, OPACITY, CAP, HIGHLIGHT, NEWEST_COLOUR]

    def live_policy(self, action_name: str) -> LivePolicy:
        # Each rerun reloads the figure's page (up to the display cap's points) and the crop of a
        # large folder takes seconds: at most one rerun every 5 s while Live adds shots.
        return LivePolicy(min_delay=5.0)

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        points = f"points {float(values[POINT_SIZE.name]):g} px, opacity {float(values[OPACITY.name]):g}"
        if int(values[CAP.name]) != CAP.default:
            points += f", cap {int(values[CAP.name]):,}"
        settings = (shots_brief(values), range_brief(values), points, newest_brief(values))
        return selection_text(view, values), " · ".join(part for part in settings if part)

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        return list(range_warnings(values))

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        values = context.parameters
        shots = select_shots(context.view, values)
        events = context.view.events(shots)
        context.check()
        if manual(values):
            crop = manual_box(events, values)
        else:
            crop = crop_box(events, keep_fraction(values), context.cancelled)
        context.check()
        mask = crop.contains(events) if len(events) else np.zeros(0, dtype=bool)
        inside = events[mask]
        cap = int(values[CAP.name])
        newest = newest_shot(values, shots)
        if newest is None:
            points = inside[display_sample(len(inside), cap)]
            return ScatterData(crop, points, shots, len(context.view.shots), cap, range_warnings(values))
        # The newest shot's events come last in ``events`` (shots ascending): drawn apart, all of
        # them up to the cap, and the sample of the rest fills what the cap leaves.
        is_newest = np.zeros(len(events), dtype=bool)
        is_newest[len(events) - len(txy(context.view.shots[newest])):] = True
        fresh, rest = inside[is_newest[mask]], inside[~is_newest[mask]]
        fresh = fresh[display_sample(len(fresh), cap)]
        points = rest[display_sample(len(rest), cap - len(fresh))]
        return ScatterData(crop, points, shots, len(context.view.shots), cap, range_warnings(values), newest,
                           fresh, newest_colour(values))

    def backends(self, action_name: str) -> Sequence[str]:
        return (PLOTLY, PYQTGRAPH, MATPLOTLIB)

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        return self.draw(result, PLOTLY, parent)

    def draw(self, result: AnalysisResult, backend: str, parent: Optional[QWidget] = None) -> QWidget:
        data: ScatterData = result.data
        if not data.crop.total:
            return empty_pane(empty_text(data.total_shots, len(data.shots), 0), parent)
        if backend == MATPLOTLIB:
            return noted(MatplotlibPane(matplotlib_figure(result, data)), data, parent)
        if backend == PYQTGRAPH:
            if not opengl_available():
                return empty_pane("PyQtGraph's 3D view needs OpenGL, which this PC can't provide: choose Plotly "
                                  "or Matplotlib (Drawing › Library)", parent)
            return noted(opengl_view(result, data), data, parent)
        pane = PlotlyPane(figure(result, data), note_text(data), parent)
        pane.note.setToolTip(f"{sample_text(data)}\n{crop_text(data.crop, data.warnings)}")
        return pane

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """A rerun (e.g. Live's next shots) updates the page in place: the camera stays."""
        data: ScatterData = result.data
        if not isinstance(widget, PlotlyPane) or not data.crop.total:
            return False
        widget.update_figure(figure(result, data), note_text(data))
        widget.note.setToolTip(f"{sample_text(data)}\n{crop_text(data.crop, data.warnings)}")
        return True


def figure(result: AnalysisResult, data: ScatterData) -> go.Figure:
    points, crop = data.points, data.crop
    size = float(result.parameters.get(POINT_SIZE.name, POINT_SIZE.default))
    opacity = float(result.parameters.get(OPACITY.name, OPACITY.default))
    traces = [go.Scatter3d(x=points[:, 1], y=points[:, 2], z=points[:, 0], mode="markers",
                           marker=dict(size=size, opacity=opacity), hoverinfo="x+y+z", name="earlier shots")]
    if data.newest_shot is not None:
        fresh = data.newest
        traces.append(go.Scatter3d(x=fresh[:, 1], y=fresh[:, 2], z=fresh[:, 0], mode="markers",
                                   marker=dict(size=size, opacity=max(opacity, 0.8), color=f"rgb{data.colour}"),
                                   hoverinfo="x+y+z", name=f"shot {data.newest_shot} (newest)"))

    def axis(index: int) -> dict[str, Any]:
        settings: dict[str, Any] = {"title": f"{AXES[index]} ({UNITS[index]})"}
        if crop.total:
            settings["range"] = (crop.lower[index], crop.upper[index])
        return settings

    layout = go.Layout(
        title=dict(text=f"{result.input.short()} · {result.analysis.short()} · {shots_text(data.shots, data.total_shots)}"
                        f"<br><sup>{sample_text(data)}<br>{crop_text(crop, data.warnings)}</sup>", x=0.01),
        scene=dict(xaxis=axis(1), yaxis=axis(2), zaxis=axis(0)),
        margin=dict(l=0, r=0, b=0, t=90),
        # Constant: a newer figure on the same page keeps the user's rotation, zoom and pan.
        uirevision=UI_REVISION, showlegend=data.newest_shot is not None,
        legend=dict(x=0.99, xanchor="right", y=0.99))
    return go.Figure(data=traces, layout=layout)


def noted(plot: QWidget, data: ScatterData, parent: Optional[QWidget]) -> QWidget:
    """``plot`` under the note line the Plotly pane has (sample, crop and shots)."""
    widget = QWidget(parent)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    note = QLabel(note_text(data), widget)
    note.setObjectName("plot_note")
    note.setToolTip(f"{sample_text(data)}\n{crop_text(data.crop, data.warnings)}")
    layout.addWidget(note)
    plot.setParent(widget)
    layout.addWidget(plot, 1)
    return widget


def matplotlib_figure(result: AnalysisResult, data: ScatterData) -> Any:
    """Matplotlib's 3D axes: X, Y across, T up, as in the Plotly figure. Slow to turn with many
    points: lower the display cap if it lags."""
    points, crop = data.points, data.crop
    size = float(result.parameters.get(POINT_SIZE.name, POINT_SIZE.default))
    opacity = float(result.parameters.get(OPACITY.name, OPACITY.default))
    figure = mpl_figure()
    axes = figure.add_subplot(projection="3d")
    # Matplotlib's marker size is an area in points²; Plotly's a diameter in pixels.
    axes.scatter(points[:, 1], points[:, 2], points[:, 0], s=size ** 2, alpha=opacity, linewidths=0,
                 depthshade=False, label="earlier shots")
    if data.newest_shot is not None:
        fresh = data.newest
        axes.scatter(fresh[:, 1], fresh[:, 2], fresh[:, 0], s=size ** 2, alpha=max(opacity, 0.8), linewidths=0,
                     depthshade=False, color=mpl_colour(data.colour), label=f"shot {data.newest_shot} (newest)")
        axes.legend(loc="upper right", fontsize=8)
    for index, (label, limits) in enumerate(((axes.set_xlabel, axes.set_xlim), (axes.set_ylabel, axes.set_ylim),
                                             (axes.set_zlabel, axes.set_zlim))):
        axis = (1, 2, 0)[index]
        label(f"{AXES[axis]} ({UNITS[axis]})", fontsize=8)
        if crop.lower[axis] < crop.upper[axis]:
            limits(crop.lower[axis], crop.upper[axis])
    axes.tick_params(labelsize=7)
    figure.suptitle(f"{result.input.short()} · {result.analysis.short()} · {shots_text(data.shots, data.total_shots)}",
                    fontsize=9, wrap=True)
    return figure


def unit_box(points: npt.NDArray[np.float64], crop: CropBox) -> npt.NDArray[np.float32]:
    """``points`` (T, X, Y) as (X, Y, T) in a unit cube spanning the crop: OpenGL draws one scale
    for all three axes, and T (s) and X, Y (m) have unrelated ranges."""
    order = (1, 2, 0)
    lower = np.array([crop.lower[i] for i in order], dtype=np.float64)
    span = np.array([crop.upper[i] - crop.lower[i] for i in order], dtype=np.float64)
    span[span <= 0] = 1.0
    return ((points[:, order] - lower) / span - 0.5).astype(np.float32)


def opengl_view(result: AnalysisResult, data: ScatterData) -> QWidget:
    """PyQtGraph's OpenGL view: fast to turn with many points. Its axes span the crop, each scaled
    to the same length (labelled with their ranges)."""
    import pyqtgraph.opengl as gl

    size = float(result.parameters.get(POINT_SIZE.name, POINT_SIZE.default))
    opacity = float(result.parameters.get(OPACITY.name, OPACITY.default))
    view = gl.GLViewWidget()
    view.setBackgroundColor("w")
    view.setCameraPosition(distance=2.2, elevation=20, azimuth=45)
    view.addItem(gl.GLScatterPlotItem(pos=unit_box(data.points, data.crop), size=size,
                                      color=(40 / 255, 90 / 255, 170 / 255, opacity), pxMode=True))
    if data.newest_shot is not None and len(data.newest):
        view.addItem(gl.GLScatterPlotItem(pos=unit_box(data.newest, data.crop), size=size,
                                          color=mpl_colour(data.colour, max(opacity, 0.8)), pxMode=True))
    box = gl.GLBoxItem(color=(0, 0, 0, 80))
    box.setSize(1, 1, 1)
    box.translate(-0.5, -0.5, -0.5)
    view.addItem(box)
    crop = data.crop
    for axis, position in ((1, (0.0, -0.6, -0.55)), (2, (-0.6, 0.0, -0.55)), (0, (-0.6, -0.6, 0.0))):
        view.addItem(gl.GLTextItem(pos=position, text=axis_text(axis, crop.lower[axis], crop.upper[axis]),
                                   color=(0, 0, 0, 255)))
    return cast(QWidget, view)
