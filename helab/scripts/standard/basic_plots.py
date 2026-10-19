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
from helab.analysis.stats import AXES, DEFAULT_KEEP, MAX_BINS, UNITS, Histogram, counts_per_shot, histogram
from helab.scripts.base import DatasetAnalysis, ScriptMetadata

RANGE = ParameterSpec(
    "keep_percent", "Range: keep", "float", DEFAULT_KEEP * 100, (50.0, 100.0), " %",
    "Each histogram covers the shortest range holding this share of its axis's events. "
    "100 % covers every event.")
BINS = ParameterSpec(
    "bins", "Bins (0 = automatic)", "int", 0, (0, MAX_BINS), "",
    "0 picks the bin count from the data (Freedman–Diaconis: width 2·IQR·n^-1/3).")


@dataclass(frozen=True)
class ShotCounts:
    shots: npt.NDArray[np.int64]
    counts: npt.NDArray[np.int64]
    unsettled_files: int

    @property
    def total(self) -> int:
        return int(self.counts.sum())


def counts_title(data: ShotCounts) -> str:
    title = f"{len(data.shots):,} shots · {data.total:,} events"
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
            version="1",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        shots, counts = counts_per_shot(context.view)
        return ShotCounts(shots, counts, context.view.provenance.unsettled_files)

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: ShotCounts = result.data
        plot: Any = pg.PlotWidget(parent)
        plot.setBackground("w")
        plot.setTitle(source_title(result, counts_title(data)))
        plot.setLabel("bottom", "Shot number")
        plot.setLabel("left", "Events")
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.plot(data.shots, data.counts, pen=pg.mkPen((40, 90, 170), width=1),
                  symbol="o", symbolSize=4, symbolBrush=(40, 90, 170), symbolPen=None)
        return cast(QWidget, plot)


class TxyHistograms(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="T, X, Y histograms",
            description="Distributions of the loaded events' T, X and Y",
            group="Plots",
            file_path=__file__,
            analysis_id="helab.txy_histograms",
            version="1",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [RANGE, BINS]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        events = context.view.events()
        keep = float(context.parameters[RANGE.name]) / 100
        bins = int(context.parameters[BINS.name])
        return tuple(histogram(np.ascontiguousarray(events[:, i]), AXES[i], keep, bins) for i in range(len(AXES)))

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        items: tuple[Histogram, ...] = result.data
        widget: Any = pg.GraphicsLayoutWidget(parent)
        widget.setBackground("w")
        widget.addLabel(source_title(result, f"{items[0].total:,} events" if items else ""), row=0, col=0)
        for row, item in enumerate(items, start=1):
            plot = widget.addPlot(row=row, col=0, title=histogram_title(item))
            plot.setLabel("bottom", f"{item.axis} ({UNITS[AXES.index(item.axis)]})")
            plot.setLabel("left", "Events")
            plot.addItem(pg.PlotDataItem(item.edges, item.counts, stepMode="center", fillLevel=0,
                                         pen=pg.mkPen((40, 90, 170)), brush=(40, 90, 170, 90)))
        return cast(QWidget, widget)
