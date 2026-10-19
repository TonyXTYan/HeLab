"""Counts per shot and T/X/Y histograms of a loaded folder (PyQtGraph: native Qt drawing,
fast to redraw when Live adds shots, and painted on lab PCs that can't paint QtWebEngine)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, cast

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget

from helab.analysis.parameters import ParameterSpec
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import (SHOT_SPECS, keep_fraction, manual, manual_bounds, range_specs, select_shots,
                                      shots_text)
from helab.analysis.stats import AXES, MAX_BINS, UNITS, Histogram, counts_per_shot, histogram
from helab.scripts.base import DatasetAnalysis, ScriptMetadata

RANGE = range_specs(
    "Each histogram covers the exact shortest range holding this share of its axis's events. "
    "100 % covers every event.")
BINS_GROUP = "Histogram"
BINS = ParameterSpec(
    "bins", "Bins", "int", 0, (0, MAX_BINS), "", group=BINS_GROUP,
    tip="0 = automatic: the bin count comes from the data (Freedman–Diaconis: width 2·IQR·n^-1/3).")
LOG_Y = ParameterSpec("log_y", "Log Y", "bool", False, group=BINS_GROUP,
                      tip="Logarithmic event axis; empty bins are left out.")
COLOUR = (40, 90, 170)


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


def counts_title(data: ShotCounts) -> str:
    title = f"{shots_text(data.shots.tolist(), data.total_shots or len(data.shots))} · {data.total:,} events"
    if data.unsettled_files:
        title += f" · {data.unsettled_files} files still being written left out"
    return title


def histogram_title(item: Histogram) -> str:
    bins = len(item.counts)
    how = "automatic, Freedman–Diaconis" if item.automatic_bins else "set"
    title = f"{item.axis} · {bins:,} bins ({how}) · {item.total - item.outside:,} of {item.total:,} events"
    return title + (f" · {item.outside:,} outside the range" if item.outside else "")


def source_title(result: AnalysisResult, text: str) -> str:
    return f"{result.input.short()} · {text}"


class CountsPerShot(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Counts per shot",
            description="Number of events in each loaded shot, against shot number",
            group="Plots",
            file_path=__file__,
            analysis_id="helab.counts_per_shot",
            version="2",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*SHOT_SPECS]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        chosen = select_shots(context.view, context.parameters)
        shots, counts = counts_per_shot(context.view, chosen)
        return ShotCounts(shots, counts, context.view.provenance.unsettled_files, len(context.view.shots))

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: ShotCounts = result.data
        plot: Any = pg.PlotWidget(parent)
        plot.setBackground("w")
        plot.setTitle(source_title(result, counts_title(data)))
        plot.setLabel("bottom", "Shot number")
        plot.setLabel("left", "Events")
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.plot(data.shots, data.counts, pen=pg.mkPen(COLOUR, width=1),
                  symbol="o", symbolSize=4, symbolBrush=COLOUR, symbolPen=None)
        return cast(QWidget, plot)


class TxyHistograms(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="T, X, Y histograms",
            description="Distributions of the loaded events' T, X and Y",
            group="Plots",
            file_path=__file__,
            analysis_id="helab.txy_histograms",
            version="2",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*SHOT_SPECS, *RANGE, BINS, LOG_Y]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        values = context.parameters
        shots = select_shots(context.view, values)
        events = context.view.events(shots)
        keep = keep_fraction(values)
        bins = int(values[BINS.name])
        bounds = manual_bounds(values) if manual(values) else (None,) * len(AXES)
        items = []
        for i, axis in enumerate(AXES):
            context.check()
            column = np.ascontiguousarray(events[:, i])
            given = bounds[i]
            if manual(values) and given is None and len(column):
                given = (float(column.min()), float(column.max()))
            items.append(histogram(column, axis, keep, bins, given))
        return Histograms(tuple(items), shots, len(context.view.shots))

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: Histograms = result.data
        items = data.items
        log_y = bool(result.parameters.get(LOG_Y.name, False))
        widget: Any = pg.GraphicsLayoutWidget(parent)
        widget.setBackground("w")
        events = f"{items[0].total:,} events" if items else ""
        widget.addLabel(source_title(result, f"{shots_text(data.shots, data.total_shots)} · {events}"), row=0, col=0)
        for row, item in enumerate(items, start=1):
            plot = widget.addPlot(row=row, col=0, title=histogram_title(item))
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
        return cast(QWidget, widget)
