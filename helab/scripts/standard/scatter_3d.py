"""The 3D scatter of a loaded folder's T/X/Y events (Plotly, served by the Dash server)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

import numpy as np
import numpy.typing as npt
import plotly.graph_objs as go
from PyQt6.QtWidgets import QWidget

from helab.analysis.panes import PlotlyPane
from helab.analysis.parameters import ParameterSpec
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.stats import AXES, DEFAULT_KEEP, DISPLAY_CAP, UNITS, CropBox, axis_text, crop_box, display_sample
from helab.scripts.base import DatasetAnalysis, ScriptMetadata

KEEP = ParameterSpec(
    "keep_percent", "Auto-crop: keep", "float", DEFAULT_KEEP * 100, (50.0, 100.0), " %",
    "Crop to a box holding this share of the events: the shortest interval of T, X and Y "
    "each, widened together until the box holds that share. 100 % keeps every event.")


@dataclass(frozen=True)
class ScatterData:
    crop: CropBox
    points: npt.NDArray[np.float64]  # the displayed sample of the events inside the crop
    shots: int

    @property
    def analysed(self) -> int:
        return self.crop.kept


def sample_text(data: ScatterData, cap: int = DISPLAY_CAP) -> str:
    shown, analysed = len(data.points), data.analysed
    if shown == analysed:
        return f"Showing all {analysed:,} events in the crop"
    return (f"Showing a random sample of {shown:,} of {analysed:,} events in the crop "
            f"(display cap {cap:,}; the analysis uses all of them)")


def crop_text(crop: CropBox) -> str:
    if crop.total == 0:
        return "No events"
    bounds = " · ".join(axis_text(i, crop.lower[i], crop.upper[i]) for i in range(len(AXES)))
    return f"Auto-crop keeps {crop.fraction:.1%} ({crop.kept:,} of {crop.total:,} events): {bounds}"


class Scatter3D(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="3D scatter",
            description="T/X/Y events of the loaded folder, cropped to the region holding most events",
            group="Plots",
            file_path=__file__,
            analysis_id="helab.scatter_3d",
            version="1",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [KEEP]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        events = context.view.events()
        crop = crop_box(events, float(context.parameters[KEEP.name]) / 100)
        inside = events[crop.contains(events)] if len(events) else events
        points = inside[display_sample(len(inside))]
        return ScatterData(crop, points, len(context.view.shots))

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: ScatterData = result.data
        return PlotlyPane(figure(result, data), f"{sample_text(data)}\n{crop_text(data.crop)}", parent)


def figure(result: AnalysisResult, data: ScatterData) -> go.Figure:
    points, crop = data.points, data.crop
    scatter = go.Scatter3d(x=points[:, 1], y=points[:, 2], z=points[:, 0], mode="markers",
                           marker=dict(size=1.5, opacity=0.5), hoverinfo="x+y+z")

    def axis(index: int) -> dict[str, Any]:
        settings: dict[str, Any] = {"title": f"{AXES[index]} ({UNITS[index]})"}
        if crop.total:
            settings["range"] = (crop.lower[index], crop.upper[index])
        return settings

    layout = go.Layout(
        title=dict(text=f"{result.input.short()} · {result.analysis.short()}<br>"
                        f"<sup>{sample_text(data)}<br>{crop_text(crop)}</sup>", x=0.01),
        scene=dict(xaxis=axis(1), yaxis=axis(2), zaxis=axis(0)),
        margin=dict(l=0, r=0, b=0, t=90))
    return go.Figure(data=[scatter], layout=layout)
