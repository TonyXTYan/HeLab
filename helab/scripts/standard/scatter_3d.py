"""The 3D scatter of a loaded folder's T/X/Y events (Plotly, served by the Dash server)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional

import numpy as np
import numpy.typing as npt
import plotly.graph_objs as go
from PyQt6.QtWidgets import QWidget

from helab.analysis.panes import PlotlyPane
from helab.analysis.parameters import ParameterSpec
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import (SHOT_SPECS, keep_fraction, manual, manual_box, range_specs, range_warnings,
                                      select_shots, shots_text)
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


@dataclass(frozen=True)
class ScatterData:
    crop: CropBox
    points: npt.NDArray[np.float64]  # the displayed sample of the events inside the crop
    shots: tuple[int, ...]  # the shot numbers used
    total_shots: int  # the shots loaded
    cap: int = DISPLAY_CAP
    warnings: tuple[str, ...] = ()  # settings not followed as given (``range_warnings``)

    @property
    def analysed(self) -> int:
        return self.crop.kept


def sample_text(data: ScatterData) -> str:
    shown, analysed = len(data.points), data.analysed
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
    shown = (f"All {data.analysed:,} events in range shown" if len(data.points) == data.analysed else
             f"Display sample: {len(data.points):,} of {data.analysed:,} events in range")
    how = "manual range" if data.crop.manual else "crop"
    text = f"{shown} · {how} keeps {data.crop.fraction:.1%} of {data.crop.total:,} · {shots_text(data.shots, data.total_shots)}"
    return text + "".join(f" · ⚠ {warning}" for warning in data.warnings)


class Scatter3D(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="3D scatter",
            description="T/X/Y events of the loaded folder, cropped to the region holding most events",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.scatter_3d",
            version="2",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*SHOT_SPECS, *RANGE, POINT_SIZE, OPACITY, CAP]

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
        inside = events[crop.contains(events)] if len(events) else events
        cap = int(values[CAP.name])
        points = inside[display_sample(len(inside), cap)]
        return ScatterData(crop, points, shots, len(context.view.shots), cap, range_warnings(values))

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: ScatterData = result.data
        pane = PlotlyPane(figure(result, data), note_text(data), parent)
        pane.note.setToolTip(f"{sample_text(data)}\n{crop_text(data.crop, data.warnings)}")
        return pane


def figure(result: AnalysisResult, data: ScatterData) -> go.Figure:
    points, crop = data.points, data.crop
    size = float(result.parameters.get(POINT_SIZE.name, POINT_SIZE.default))
    opacity = float(result.parameters.get(OPACITY.name, OPACITY.default))
    scatter = go.Scatter3d(x=points[:, 1], y=points[:, 2], z=points[:, 0], mode="markers",
                           marker=dict(size=size, opacity=opacity), hoverinfo="x+y+z")

    def axis(index: int) -> dict[str, Any]:
        settings: dict[str, Any] = {"title": f"{AXES[index]} ({UNITS[index]})"}
        if crop.total:
            settings["range"] = (crop.lower[index], crop.upper[index])
        return settings

    layout = go.Layout(
        title=dict(text=f"{result.input.short()} · {result.analysis.short()} · {shots_text(data.shots, data.total_shots)}"
                        f"<br><sup>{sample_text(data)}<br>{crop_text(crop, data.warnings)}</sup>", x=0.01),
        scene=dict(xaxis=axis(1), yaxis=axis(2), zaxis=axis(0)),
        margin=dict(l=0, r=0, b=0, t=90))
    return go.Figure(data=[scatter], layout=layout)
