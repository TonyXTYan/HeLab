"""Shot times (D7): events per shot against when each shot was taken, and the gaps between
consecutive shots, which show stalls (PyQtGraph, a date axis).

A shot's time is its raw ``d<N>.txt`` file's mtime (Tony, 2026-10-20; ``DatasetView.shot_time``).
Without one it is its TXY file's mtime, which is when it was converted, so a converter catching
up gives many shots the same time: those are drawn as amber triangles and counted in the title
and the dock's first line.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, List, Mapping, Optional, cast

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget

from helab.analysis.dataset_view import DatasetView
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.masks import MASK_SPECS, Mask, mask_brief, mask_from, mask_warnings, masked_counts_per_shot
from helab.analysis.parameters import ParameterSpec
from helab.analysis.plot_text import add_label, line_html
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import (SHOT_SPECS, newest_brief, newest_colour, newest_shot, newest_specs, select_shots,
                                      selection_text, shots_brief, shots_text)
from helab.analysis.stats import counts_per_shot
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.standard import group
from helab.scripts.standard.basic_plots import NEWEST_SIZE, source_title

BOTH, COUNTS, GAPS = "counts and gaps", "counts", "gaps"
PLOT_GROUP = "Plot"
PANELS = ParameterSpec("panels", "Show", "choice", BOTH, choices=(BOTH, COUNTS, GAPS), group=PLOT_GROUP,
                       tip="Events per shot against its time, the time since the previous shot, or both "
                           "(stacked, sharing the time axis).")
LOG_GAPS = ParameterSpec("log_gaps", "Log Y (gaps)", "bool", False, group=PLOT_GROUP,
                         tip="Logarithmic gap axis: seconds and hours on one plot.")
HIGHLIGHT, NEWEST_COLOUR = newest_specs(PLOT_GROUP)
COLOUR = (40, 90, 170)
FALLBACK_COLOUR = (230, 140, 0)
TOOLTIP = ("A shot's time is its raw d<N>.txt file's modification time; amber triangles have no raw "
           "file, so their time is the TXY file's: when it was converted.\nA copied or rewritten file "
           "has a new modification time.")


@dataclass(frozen=True)
class ShotTimes:
    shots: npt.NDArray[np.int64]  # the chosen shots with a time, ascending by number
    times: npt.NDArray[np.float64]  # s since the epoch
    fallback: npt.NDArray[np.bool_]  # the time is the TXY file's (no raw file)
    counts: npt.NDArray[np.int64]
    # s since the previous shot (by number); nan for the first. Negative: taken before it.
    gaps: npt.NDArray[np.float64]
    total_shots: int  # the shots loaded
    chosen: int = 0  # the shots the Shots settings chose (some may have no time)
    unsettled_files: int = 0
    newest_shot: int | None = None  # the highlighted newest shot (None: off)
    colour: tuple[int, int, int] = (214, 39, 40)
    masked: int = 0  # events the mask took out of these shots

    @property
    def fallbacks(self) -> int:
        return int(self.fallback.sum())

    @property
    def untimed(self) -> int:
        return self.chosen - len(self.shots)

    @property
    def gap_fallback(self) -> npt.NDArray[np.bool_]:
        """Gaps measured from or to a TXY time."""
        if not len(self.fallback):
            return self.fallback
        return self.fallback | np.concatenate(([False], self.fallback[:-1]))

    def longest_gap(self) -> tuple[int, float] | None:
        """(shot, seconds since the previous one) of the longest gap between raw times (a TXY time,
        a conversion's, would make up a stall), else between any; None with fewer than 2 shots."""
        if len(self.gaps) < 2:
            return None
        measured = np.where(self.gap_fallback, np.nan, self.gaps)
        gaps = measured if np.isfinite(measured).any() else self.gaps
        index = int(np.nanargmax(gaps))
        return int(self.shots[index]), float(gaps[index])


def shot_times(view: DatasetView, shots: tuple[int, ...], unsettled_files: int = 0, mask: Mask | None = None
               ) -> ShotTimes:
    """The chosen shots' times, events (those ``mask`` keeps) and gaps (``ShotTimes``)."""
    timed = view.shot_times(shots)
    numbers = np.fromiter(timed, dtype=np.int64, count=len(timed))
    times = np.fromiter(timed.values(), dtype=np.float64, count=len(timed))
    fallbacks = set(view.fallback_times(timed))
    fallback = np.fromiter((int(shot) in fallbacks for shot in numbers), dtype=np.bool_, count=len(numbers))
    masked = 0
    if mask is not None and mask.active:
        _, counts, masked = masked_counts_per_shot(view, numbers.tolist(), mask)
    else:
        _, counts = counts_per_shot(view, numbers.tolist())
    gaps = np.concatenate(([np.nan], np.diff(times))) if len(times) else np.empty(0)
    return ShotTimes(numbers, times, fallback, counts, gaps, len(view.shots), len(shots), unsettled_files,
                     masked=masked)


def gap_text(seconds: float) -> str:
    """A gap in a unit that reads at a glance: ``0.84 s``, ``42 s``, ``12.5 min``, ``3.2 h``, ``2.0 d``."""
    size = abs(seconds)
    sign = "−" if seconds < 0 else ""
    if size < 10:
        return f"{sign}{size:.2g} s" if size < 1 else f"{sign}{size:.1f} s"
    if size < 120:
        return f"{sign}{size:.0f} s"
    if size < 7200:
        return f"{sign}{size / 60:.1f} min"
    if size < 2 * 86400:
        return f"{sign}{size / 3600:.1f} h"
    return f"{sign}{size / 86400:.1f} d"


def fallback_text(count: int) -> str:
    return f"{count:,} TXY time{'' if count == 1 else 's'} (no raw file)"


def title_text(data: ShotTimes) -> str:
    parts = [shots_text(data.shots.tolist(), data.total_shots), f"{int(data.counts.sum()):,} events"]
    if data.masked:
        parts.append(f"{data.masked:,} masked out")
    longest = data.longest_gap()
    if longest is not None:
        parts.append(f"longest gap {gap_text(longest[1])} before shot {longest[0]}")
    if data.fallbacks:
        parts.append(f"⚠ {fallback_text(data.fallbacks)}")
    if data.untimed:
        parts.append(f"{data.untimed:,} without a time left out")
    if data.unsettled_files:
        files = data.unsettled_files
        parts.append(f"{files:,} file{'' if files == 1 else 's'} still being written left out")
    return " · ".join(parts)


def key_html(data: ShotTimes, shown: bool) -> str:
    """The plots' key, below the title (a legend inside a plot covered its latest points):
    the raw-time points, the TXY-time triangles when any is drawn, and the newest shot."""
    parts = [f'<span style="color: {pg.mkColor(COLOUR).name()}">●</span> raw file time']
    if shown:
        parts.append(f'<span style="color: {pg.mkColor(FALLBACK_COLOUR).name()}">▼</span> TXY file time (no raw file)')
    if data.newest_shot is not None:
        parts.append(f'<span style="color: {pg.mkColor(data.colour).name()}">●</span> shot {data.newest_shot} (newest)')
    return " · ".join(parts)


class ShotTimesWidget(pg.GraphicsLayoutWidget):  # type: ignore[misc]
    """The plots and their items, so a rerun (Live) updates them in place, keeping zoom and pan."""

    def __init__(self, panels: str, log_gaps: bool, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.panels, self.log_gaps = panels, log_gaps
        self.setBackground("w")
        layout: Any = self.ci  # (The widget passes addLabel and addPlot to it.)
        self.title = add_label(layout, row=0, col=0)
        self.key_label = add_label(layout, row=1, col=0)
        self.setToolTip(TOOLTIP)
        self.points: list[tuple[Any, Any]] = []  # (raw-time points, TXY-time points) per plot
        self.newest: list[Any] = []  # the newest shot's point per plot (highlight)
        self.plots: list[Any] = []
        row = 2
        for kind in (COUNTS, GAPS):
            if panels not in (kind, BOTH):
                continue
            plot = layout.addPlot(row=row, col=0, axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
            row += 1
            plot.showGrid(x=True, y=True, alpha=0.3)
            plot.setLabel("left", "Events" if kind == COUNTS else "Time since the previous shot (s)")
            plot.setLabel("bottom", "Shot time")
            if kind == GAPS and log_gaps:
                plot.setLogMode(x=False, y=True)
            # Points only (no line), as data items: they follow the plot's log mode (Log gaps), which
            # a ScatterPlotItem doesn't (it would draw seconds as exponents).
            measured = pg.PlotDataItem(pen=None, symbol="o", symbolSize=6, symbolPen=None,
                                       symbolBrush=pg.mkBrush(COLOUR))
            fallback = pg.PlotDataItem(pen=None, symbol="t", symbolSize=9, symbolPen=None,
                                       symbolBrush=pg.mkBrush(FALLBACK_COLOUR))
            newest = pg.PlotDataItem(pen=None, symbol="o", symbolSize=NEWEST_SIZE, symbolPen=None)
            plot.addItem(measured)
            plot.addItem(fallback)
            plot.addItem(newest)
            plot.kind = kind
            if self.plots:
                plot.setXLink(self.plots[0])
            self.plots.append(plot)
            self.points.append((measured, fallback))
            self.newest.append(newest)

    def show_data(self, result: AnalysisResult, data: ShotTimes) -> None:
        self.title.setText(line_html(source_title(result, title_text(data))))
        any_fallback = False
        for plot, (measured, fallback), newest in zip(self.plots, self.points, self.newest):
            if plot.kind == COUNTS:
                values, flagged = data.counts.astype(np.float64), data.fallback
            else:
                values, flagged = data.gaps.copy(), data.gap_fallback
                if self.log_gaps:
                    values[values <= 0] = np.nan  # No logarithm: left out.
            shown = np.isfinite(values)
            measured.setData(data.times[shown & ~flagged], values[shown & ~flagged])
            fallback.setData(data.times[shown & flagged], values[shown & flagged])
            any_fallback = any_fallback or bool((shown & flagged).any())
            lit = shown & (data.shots == data.newest_shot) if data.newest_shot is not None else np.zeros(0, bool)
            if lit.any():
                newest.setData(data.times[lit], values[lit], symbolBrush=pg.mkBrush(data.colour))
            else:
                newest.setData([], [])
        # The key lists only what is drawn: the amber entry appears with a TXY time.
        self.key_label.setText(key_html(data, any_fallback))


class ShotTimesPlot(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Shot times",
            description="Events per shot against when it was taken (its raw file's time), and the gaps "
                        "between shots",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.shot_times",
            version="3",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*SHOT_SPECS, *MASK_SPECS, PANELS, LOG_GAPS, HIGHLIGHT, NEWEST_COLOUR]

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        chosen = select_shots(view, values)
        fallbacks = len(view.fallback_times(chosen))
        used = selection_text(view, values) + (f" · ⚠ {fallback_text(fallbacks)}" if fallbacks else "")
        panels = str(values.get(PANELS.name, BOTH))
        settings = (shots_brief(values), mask_brief(values), "" if panels == BOTH else panels,
                    "log gaps" if values.get(LOG_GAPS.name) and panels != COUNTS else "", newest_brief(values))
        return used, " · ".join(part for part in settings if part)

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        return list(mask_warnings(values))

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        values = context.parameters
        chosen = select_shots(context.view, values)
        mask = mask_from(values)  # Circles that can't be read fail the run, saying which.
        times = shot_times(context.view, chosen, context.view.provenance.unsettled_files, mask)
        lit = newest_shot(values, chosen)
        return replace(times, newest_shot=lit, colour=newest_colour(values)) if lit is not None else times

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: ShotTimes = result.data
        if not len(data.shots):
            # No shots, none chosen (a shot without events still has a time: it is drawn at 0).
            text = empty_text(data.total_shots, data.chosen) or "None of the chosen shots has a time"
            return empty_pane(text, parent)
        widget = ShotTimesWidget(str(result.parameters.get(PANELS.name, BOTH)),
                                 bool(result.parameters.get(LOG_GAPS.name, False)), parent)
        widget.show_data(result, data)
        return cast(QWidget, widget)

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """Live's next shots go into the plots already drawn: zoom and pan stay."""
        data: ShotTimes = result.data
        panels = str(result.parameters.get(PANELS.name, BOTH))
        log_gaps = bool(result.parameters.get(LOG_GAPS.name, False))
        if (not isinstance(widget, ShotTimesWidget) or not len(data.shots)
                or (widget.panels, widget.log_gaps) != (panels, log_gaps)):
            return False
        widget.show_data(result, data)
        return True
