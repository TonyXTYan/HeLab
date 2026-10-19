"""Mean position and width of X and Y against T (the DLD front panel's ``dld_avg_pos_plots``):
for T bins of exactly the width set, the mean and SD of the X and Y of the events in each bin,
in mm, with their standard errors, over the chosen shots; optionally the spectrum of each
mean-position trace (atom-laser pointing and breathing, sloshing).

The events are those inside the plot's view range (auto-crop or manual, over T, X and Y), and
the T bins start at the range's start. A bin with fewer events than the minimum is left out:
a gap in the traces, counted in the plot's note. Standard errors: SD/√n for a mean and
SD/√(2(n−1)) for an SD (normal data). For the spectrum, the trace runs from its first kept bin
to its last, gaps inside filled by straight lines (said so); its mean is subtracted and it is
windowed (``helab.analysis.spectrum``).

Unlike the old GUI (its legacy bugs 4–6): the bins are exactly the width asked (it made them
about twice as wide), the width is in seconds, empty bins are gaps rather than NaN spectra,
any trace length works, X/Y are labelled in the unit they are drawn in, and X/Y aren't
rotated (Tony, 2026-10-20).
"""
from __future__ import annotations

import html
import math
from dataclasses import dataclass, field, replace
from typing import Any, List, Mapping, Optional, cast

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from helab.analysis.dataset_view import DatasetView
from helab.analysis.display_units import LENGTH_SCALE, LENGTH_UNIT, frequency_text, si_text, time_text, time_unit
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.follow import LivePolicy
from helab.analysis.parameters import ParameterSpec
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import (SHOT_SPECS, keep_fraction, manual, manual_box, range_brief, range_specs,
                                      range_warnings, select_shots, selection_text, shots_brief, shots_text)
from helab.analysis.spectrum import Spectrum, amplitude_spectrum, find_spectrum_peaks, peak_specs, window_spec
from helab.analysis.stats import CropBox, crop_box
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.standard import group

RANGE = range_specs(
    "The box holding this share of the events, as the 3D scatter's auto-crop: the T bins span its T range "
    "and only events inside it count. 100 % keeps every event.")
BINS_GROUP = "T bins"
BIN_WIDTH = ParameterSpec(
    "t_bin", "T bin width (0 = auto)", "float", 0.0, (0.0, 10.0), " s", group=BINS_GROUP, si=True,
    tip="Each bin is exactly this wide, from the start of the range. 0 = automatic: about 100 events per bin "
        "on average, 10–1,000 bins.")
MIN_EVENTS = ParameterSpec(
    "min_events", "Minimum events per bin", "int", 10, (2, 1_000_000), group=BINS_GROUP,
    tip="Bins with fewer events are left out: gaps in the traces, counted in the plot's note.")
SPECTRUM_GROUP = "Spectrum"
SPECTRUM = ParameterSpec(
    "spectrum", "Spectrum of the mean position", "bool", False, group=SPECTRUM_GROUP,
    tip="The amplitude spectrum of the mean X and mean Y against T (sloshing, breathing): mean subtracted, "
        "windowed, gaps filled by straight lines.")
WHEN_SPECTRUM = (SPECTRUM.name, "True")
WINDOW = window_spec(SPECTRUM_GROUP, WHEN_SPECTRUM)
LOG = ParameterSpec("spectrum_log", "Log amplitude", "bool", True, group=SPECTRUM_GROUP, when=WHEN_SPECTRUM,
                    tip="Logarithmic amplitude axis.")
PEAKS, THRESHOLD, PEAKS_ABOVE = peak_specs(SPECTRUM_GROUP, 3, WHEN_SPECTRUM)
PARAMETERS = (*SHOT_SPECS, *RANGE, BIN_WIDTH, MIN_EVENTS, SPECTRUM, WINDOW, LOG, PEAKS, THRESHOLD, PEAKS_ABOVE)

AUTO_EVENTS = 100  # automatic bins: about this many events per bin on average …
AUTO_BINS = (10, 1000)  # … and at least / at most this many bins
MAX_BINS = 100_000
MIN_SPECTRUM_BINS = 8  # a trace this long, first kept bin to last, at least
POINT_SPAN = 5e-4  # a range with no T extent (one event, equal T) is widened by this each way
COLOURS = {"X": (40, 90, 170), "Y": (214, 95, 20)}


@dataclass(frozen=True)
class Trace:
    """One axis's per-bin statistics in mm; NaN in bins left out."""
    axis: str
    mean: npt.NDArray[np.float64]
    mean_se: npt.NDArray[np.float64]
    sd: npt.NDArray[np.float64]
    sd_se: npt.NDArray[np.float64]


@dataclass(frozen=True)
class PositionProfile:
    shots: tuple[int, ...]
    total_shots: int
    total: int  # events in the chosen shots
    events: int = 0  # of them, inside the view range
    edges: npt.NDArray[np.float64] = field(default_factory=lambda: np.empty(0))  # T (s), exactly the width apart
    counts: npt.NDArray[np.int64] = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    traces: tuple[Trace, ...] = ()  # X and Y
    width: float = math.nan  # the T bin width (s)
    automatic: bool = True
    minimum: int = 10  # bins with fewer events are left out
    time_unit: str = "ms"
    box: CropBox | None = None
    warnings: tuple[str, ...] = ()  # settings not followed as given
    notes: tuple[str, ...] = ()  # what else the plot should say (bins left out, gaps filled)
    spectra: tuple[Spectrum, ...] = ()  # of the mean X and Y traces (empty: off, or too short)
    spectrum_asked: bool = False

    @property
    def kept(self) -> npt.NDArray[np.bool_]:
        return self.counts >= self.minimum

    @property
    def centres(self) -> npt.NDArray[np.float64]:
        return (self.edges[:-1] + self.edges[1:]) / 2

    @property
    def left_out(self) -> int:
        return int(len(self.counts) - np.count_nonzero(self.kept))


def bin_width(events: int, span: float, given: float) -> tuple[float, bool, str]:
    """The T bin width: as given, else automatic (about ``AUTO_EVENTS`` per bin, ``AUTO_BINS``
    bins); widened to stay within ``MAX_BINS``. (width, automatic, what it says when widened)."""
    if given > 0:
        if span / given > MAX_BINS:
            wider = span / MAX_BINS
            return wider, False, (f"T bin width {time_text(given)} gives over {MAX_BINS:,} bins: using "
                                  f"{time_text(wider)}")
        return given, False, ""
    low, high = AUTO_BINS
    return span / min(max(events // AUTO_EVENTS, low), high), True, ""


def bin_statistics(values: npt.NDArray[np.float64], index: npt.NDArray[np.intp], counts: npt.NDArray[np.int64],
                   kept: npt.NDArray[np.bool_], axis: str) -> Trace:
    """Per-bin mean and SD of ``values`` (in their unit), with standard errors, from sums of
    deviations from their overall mean (no cancellation for data far from 0)."""
    reference = float(values.mean()) if len(values) else 0.0
    deviations = values - reference
    bins = len(counts)
    first = np.bincount(index, weights=deviations, minlength=bins)
    second = np.bincount(index, weights=deviations * deviations, minlength=bins)
    n = counts.astype(np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = first / n
        variance = np.maximum(second - first * mean, 0.0) / (n - 1)
        sd = np.sqrt(variance)
        mean_se = sd / np.sqrt(n)
        sd_se = sd / np.sqrt(2 * (n - 1))
    gap = ~kept
    arrays = [reference + mean, mean_se, sd, sd_se]
    for array in arrays:
        array[gap] = np.nan
    return Trace(axis, *arrays)


def filled(centres: npt.NDArray[np.float64], trace: npt.NDArray[np.float64]) -> tuple[npt.NDArray[np.float64], int]:
    """The trace from its first finite value to its last, the gaps inside filled by straight
    lines, and how many were filled."""
    finite = np.flatnonzero(np.isfinite(trace))
    if not len(finite):
        return np.empty(0), 0
    span = slice(int(finite[0]), int(finite[-1]) + 1)
    part, where = trace[span], centres[span]
    good = np.isfinite(part)
    gaps = int(len(part) - np.count_nonzero(good))
    if gaps:
        part = np.interp(where, where[good], part[good])
    return cast(npt.NDArray[np.float64], np.asarray(part, dtype=np.float64)), gaps


def empty_reason(data: PositionProfile) -> str:
    """Why there is nothing to draw ("" when there is)."""
    text = empty_text(data.total_shots, len(data.shots), data.total)
    if text:
        return text
    warned = "".join(f" · ⚠ {warning}" for warning in data.warnings)
    if not data.events:
        return (f"None of the {data.total:,} events in the chosen shots is inside the view range "
                f"(View range settings){warned}")
    if not data.kept.any():
        return (f"No T bin holds {data.minimum:,} events or more: {data.events:,} events in {len(data.counts):,} "
                f"bins of {time_text(data.width)} (T bins settings){warned}")
    return ""


def peak_text(spectrum: Spectrum, axis: str) -> str:
    if not spectrum.peaks:
        return f"mean {axis}: no peak"
    peaks = ", ".join(f"{frequency_text(peak.frequency)} ({si_text(peak.value * 1e-3, 'm', 3)})"
                      for peak in spectrum.peaks)
    return f"mean {axis}: {peaks}"


def titles(result: AnalysisResult, data: PositionProfile) -> tuple[str, str]:
    """The figure's two title lines: what it shows, then its bins, notes and warnings."""
    bins = len(data.counts)
    how = "auto" if data.automatic else "set"
    first = (f"{result.input.short()} · {shots_text(data.shots, data.total_shots)} · {data.events:,} of "
             f"{data.total:,} events in range")
    second = [f"{bins:,} T bins of {time_text(data.width)} ({how})", *data.notes]
    second += [f"⚠ {warning}" for warning in data.warnings]
    return first, " · ".join(second)


class PositionPlot(QWidget):
    """Mean X/Y and their SDs against T, optionally with their spectrum below (``graphics``, a
    PyQtGraph layout); ``show_data`` draws a newer result in place, keeping zoom and pan."""

    def __init__(self, spectrum: bool, log: bool, unit: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.graphics: Any = pg.GraphicsLayoutWidget(self)
        self.graphics.setBackground("w")
        layout.addWidget(self.graphics)
        self.key = (spectrum, log, unit)
        self.title: Any = self.graphics.addLabel("", row=0, col=0)
        self.means: Any = self.graphics.addPlot(row=1, col=0, title="Mean position ± SE")
        self.widths: Any = self.graphics.addPlot(row=2, col=0, title="SD ± SE")
        self.widths.setXLink(self.means)
        self.curves: dict[tuple[str, str], Any] = {}
        self.bars: dict[tuple[str, str], Any] = {}
        for plot, kind, label in ((self.means, "mean", "Mean"), (self.widths, "sd", "SD")):
            plot.setLabel("bottom", f"T ({unit})")
            plot.setLabel("left", f"{label} ({LENGTH_UNIT})")
            plot.showGrid(x=True, y=True, alpha=0.3)
            plot.addLegend(offset=(-10, 10))
            for axis, colour in COLOURS.items():
                bars = pg.ErrorBarItem(x=np.empty(0), y=np.empty(0), height=np.empty(0),
                                       pen=pg.mkPen((*colour, 140)))
                plot.addItem(bars)
                self.bars[axis, kind] = bars
                self.curves[axis, kind] = plot.plot([], [], name=f"{axis}", connect="finite",
                                                    pen=pg.mkPen(colour, width=1.5), symbol="o", symbolSize=4,
                                                    symbolBrush=colour, symbolPen=None)
        self.spectrum: Any = None
        self.spectrum_curves: dict[str, Any] = {}
        self.markers: list[Any] = []
        self.peaks_label: Any = None
        if spectrum:
            self.spectrum = self.graphics.addPlot(row=3, col=0, title="Spectrum of the mean position")
            self.spectrum.setLabel("bottom", "Frequency", units="Hz")
            self.spectrum.setLabel("left", f"Amplitude ({LENGTH_UNIT})")
            self.spectrum.showGrid(x=True, y=True, alpha=0.3)
            self.spectrum.addLegend(offset=(-10, 10))
            if log:
                self.spectrum.setLogMode(x=False, y=True)
            for axis, colour in COLOURS.items():
                self.spectrum_curves[axis] = self.spectrum.plot([], [], name=f"mean {axis}", connect="finite",
                                                                pen=pg.mkPen(colour, width=1.2))
            self.peaks_label = self.graphics.addLabel("", row=4, col=0)

    def show_data(self, result: AnalysisResult, data: PositionProfile) -> None:
        unit_scale = 1e3 if data.time_unit == "ms" else 1.0
        first, second = titles(result, data)
        self.title.setText(f"{html.escape(first)}<br>{html.escape(second)}")
        centres = data.centres * unit_scale
        kept = data.kept
        for trace in data.traces:
            for kind, values, errors in (("mean", trace.mean, trace.mean_se), ("sd", trace.sd, trace.sd_se)):
                self.curves[trace.axis, kind].setData(centres, values)
                self.bars[trace.axis, kind].setData(x=centres[kept], y=values[kept], height=2 * errors[kept])
        if self.spectrum is None:
            return
        for marker in self.markers:
            self.spectrum.removeItem(marker)
        self.markers = []
        log = self.key[1]
        lines = []
        for axis, spectrum in zip(COLOURS, data.spectra):
            frequencies, values = spectrum.frequencies[1:], spectrum.values[1:]
            shown = np.where(values > 0, values, np.nan) if log else values
            self.spectrum_curves[axis].setData(frequencies, shown)
            for rank, peak in enumerate(spectrum.peaks, start=1):
                label = pg.TextItem(f"{axis}{rank}", color=COLOURS[axis], anchor=(0.5, 1))
                height = peak.value if not log else math.log10(peak.value) if peak.value > 0 else 0.0
                label.setPos(peak.frequency, height)
                self.spectrum.addItem(label)
                self.markers.append(label)
            lines.append(peak_text(spectrum, axis))
        if not data.spectra:
            for curve in self.spectrum_curves.values():
                curve.setData([], [])
        text = " · ".join(lines) if lines else next((note for note in data.notes if "spectrum" in note), "")
        self.peaks_label.setText(html.escape(f"Peaks: {text}" if lines else text))


class MeanPositionVsT(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Mean X, Y against T",
            description="Mean position and width (SD) of X and Y in T bins, with standard errors, and optionally "
                        "their spectrum; from the DLD front panel's average-position plots",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.mean_position_vs_t",
            version="1",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*PARAMETERS]

    def live_policy(self, action_name: str) -> LivePolicy:
        # The auto-crop of a large folder takes a second or more (as the density images'): at
        # most one rerun every 2 s while Live adds shots.
        return LivePolicy(min_delay=2.0)

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        width = float(values[BIN_WIDTH.name])
        spectrum = ""
        if values[SPECTRUM.name]:
            spectrum = f"spectrum {values[WINDOW.name]}"
            spectrum += ", log" if values[LOG.name] else ""
        settings = (shots_brief(values), range_brief(values), f"T bins {time_text(width)}" if width else "",
                    f"≥ {int(values[MIN_EVENTS.name]):,} events per bin", spectrum)
        return selection_text(view, values), " · ".join(part for part in settings if part)

    def describe_result(self, action_name: str, result: AnalysisResult) -> str:
        data = result.data
        if not isinstance(data, PositionProfile) or not len(data.counts):
            return ""
        parts = [f"T bins {time_text(data.width)} (auto)" if data.automatic else ""]
        if data.left_out:
            parts.append(f"{data.left_out:,} of {len(data.counts):,} bins left out")
        if data.spectra:
            parts.append(f"Δf {frequency_text(data.spectra[0].resolution)}, Nyquist "
                         f"{frequency_text(data.spectra[0].nyquist)}")
        return " · ".join(part for part in parts if part)

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        return list(range_warnings(values))

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        values, view = context.parameters, context.view
        shots = select_shots(view, values)
        events = view.events(shots)
        minimum = int(values[MIN_EVENTS.name])
        empty = PositionProfile(shots, len(view.shots), len(events), minimum=minimum,
                                warnings=range_warnings(values), spectrum_asked=bool(values[SPECTRUM.name]))
        context.check()
        if not len(events):
            return empty
        box = manual_box(events, values) if manual(values) else crop_box(events, keep_fraction(values),
                                                                         context.cancelled)
        context.check()
        inside = events[box.contains(events)]
        if not len(inside):
            return replace(empty, box=box)
        lower, upper = box.lower[0], box.upper[0]
        if not upper > lower:
            lower, upper = lower - POINT_SPAN, upper + POINT_SPAN
        width, automatic, widened = bin_width(len(inside), upper - lower, float(values[BIN_WIDTH.name]))
        bins = max(1, math.ceil((upper - lower) / width * (1 - 1e-12)))
        edges = (lower + width * np.arange(bins + 1)).astype(np.float64)
        index = np.minimum(((inside[:, 0] - lower) / width).astype(np.intp), bins - 1)
        counts = np.bincount(index, minlength=bins).astype(np.int64)
        kept = counts >= minimum
        traces = []
        for column, axis in ((1, "X"), (2, "Y")):
            context.check()
            traces.append(bin_statistics(inside[:, column] * LENGTH_SCALE, index, counts, kept, axis))
        notes: list[str] = []
        left_out = int(bins - np.count_nonzero(kept))
        if left_out and kept.any():
            notes.append(f"{left_out:,} of {bins:,} bins with fewer than {minimum:,} events left out")
        data = PositionProfile(shots, len(view.shots), len(events), len(inside), edges, counts, tuple(traces), width,
                               automatic, minimum, time_unit(lower, upper)[0], box,
                               range_warnings(values) + ((widened,) if widened else ()), tuple(notes),
                               spectrum_asked=bool(values[SPECTRUM.name]))
        if not values[SPECTRUM.name] or not kept.any():
            return data
        context.check()
        centres = data.centres
        spectra, gaps = [], 0
        for trace in traces:
            part, filled_here = filled(centres, trace.mean)
            if len(part) < MIN_SPECTRUM_BINS:
                notes.append(f"no spectrum: the traces have {len(part):,} bins from the first kept to the last, "
                             f"under {MIN_SPECTRUM_BINS}")
                return replace(data, notes=tuple(notes))
            gaps = max(gaps, filled_here)
            spectrum = amplitude_spectrum(part, width, str(values[WINDOW.name]))
            spectra.append(find_spectrum_peaks(spectrum, int(values[PEAKS.name]), float(values[PEAKS_ABOVE.name]),
                                               float(values[THRESHOLD.name])))
        if gaps:
            notes.append(f"{gaps:,} gap bin{'' if gaps == 1 else 's'} filled by straight lines for the spectrum")
        return replace(data, notes=tuple(notes), spectra=tuple(spectra))

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: PositionProfile = result.data
        reason = empty_reason(data)
        if reason:
            return empty_pane(reason, parent)
        widget = PositionPlot(data.spectrum_asked, bool(result.parameters.get(LOG.name, LOG.default)),
                              data.time_unit, parent)
        widget.show_data(result, data)
        return widget

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """A rerun (e.g. Live's next shots) draws in place, keeping zoom and pan, while the
        spectrum (shown, log) and T's unit stay; otherwise, or to or from an empty plot, anew."""
        data: PositionProfile = result.data
        if not isinstance(widget, PositionPlot) or empty_reason(data):
            return False
        if widget.key != (data.spectrum_asked, bool(result.parameters.get(LOG.name, LOG.default)), data.time_unit):
            return False
        widget.show_data(result, data)
        return True

