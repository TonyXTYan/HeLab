"""Mean position and width of X and Y against T (the DLD front panel's ``dld_avg_pos_plots``):
for T bins of exactly the width set, the mean and SD of the X and Y of the events in each bin,
in mm, with their standard errors, over the chosen shots; optionally the spectrum of each
mean-position trace (atom-laser pointing and breathing, sloshing).

The events are those inside the plot's view range (auto-crop or manual, over T, X and Y), and
the T bins start at the range's start; a remainder shorter than a bin is a last, partial bin
(in the traces, centred on its own extent, but not in the evenly spaced spectrum). A bin with fewer events than the minimum is left out: a gap in the traces, counted
in the plot's note. Standard errors: SD/√n for a mean and SD/√(2(n−1)) for an SD (normal
data). For the spectrum, the trace runs from its first kept bin to its last, gaps inside
filled by straight lines (said so) while they are at most ``MAX_FILLED`` (20 %) of it; past
that, the longest stretch without gaps is used if it has ``MIN_SPECTRUM_BINS`` bins, else there
is no spectrum, and the plot says which. Its mean is subtracted, it is windowed, and the bins'
averaging is corrected for (``helab.analysis.spectrum``, ``binned``).

Unlike the old GUI (its legacy bugs 4–6): the bins are exactly the width asked (it made them
about twice as wide), the width is a time (shown in ms), empty bins are gaps rather than NaN spectra,
any trace length works, X/Y are labelled in the unit they are drawn in, and X/Y aren't
rotated (Tony, 2026-10-20).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, List, Mapping, Optional, cast

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from helab.analysis.dataset_view import DatasetView, Events
from helab.analysis.display_units import (LENGTH_SCALE, LENGTH_UNIT, T_SCALE, WIDTH_DIGITS, axis_label, frequency_text,
                                          number_text, range_text, time_text)
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.masks import MASK_SPECS, all_masked_text, mask_brief, mask_from, mask_warnings, masked_text
from helab.analysis.follow import LivePolicy
from helab.analysis.parameters import ParameterSpec
from helab.analysis.plot_axes import GroupedAxis
from helab.analysis.plot_text import add_label, line_html, lines_html
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import (SHOT_SPECS, keep_fraction, manual, manual_box, range_brief, range_specs,
                                      range_warnings, select_shots, selection_text, shots_brief, shots_text)
from helab.analysis.spectrum import (Spectrum, amplitude_spectrum, find_spectrum_peaks, peak_specs,
                                     spectrum_text, whole_bins, window_spec)
from helab.analysis.stats import CropBox, crop_box
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.dld import group

RANGE = range_specs(
    "The box holding this share of the events, as the 3D scatter's auto-crop: the T bins span its T range "
    "and only events inside it count. 100 % keeps every event.", fixed=True)
BINS_GROUP = "T bins"
BIN_WIDTH = ParameterSpec(
    "t_bin", "T bin width (0 = auto)", "float", 0.0, (0.0, 10.0), " s", group=BINS_GROUP, si=True, unit_prefix="m",
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
LOG = ParameterSpec("spectrum_log", "Log Y", "bool", True, group=SPECTRUM_GROUP, when=WHEN_SPECTRUM,
                    tip="Logarithmic amplitude axis.")
PEAKS, THRESHOLD, PEAKS_ABOVE = peak_specs(SPECTRUM_GROUP, 3, WHEN_SPECTRUM)
PARAMETERS = (*SHOT_SPECS, *RANGE, *MASK_SPECS,
              BIN_WIDTH, MIN_EVENTS, SPECTRUM, WINDOW, LOG, PEAKS, THRESHOLD, PEAKS_ABOVE)

AUTO_EVENTS = 100  # automatic bins: about this many events per bin on average …
AUTO_BINS = (10, 1000)  # … and at least / at most this many bins
MAX_BINS = 100_000
MIN_SPECTRUM_BINS = 8  # a trace this long, first kept bin to last, at least
MAX_FILLED = 0.2  # gaps filled by straight lines for the spectrum: at most this share of the trace
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
    clamp: str = ""  # automatic, and at a bin limit: "at least" or "at most" (else "")
    minimum: int = 10  # bins with fewer events are left out
    box: CropBox | None = None
    warnings: tuple[str, ...] = ()  # settings not followed as given
    notes: tuple[str, ...] = ()  # what else the plot should say (bins left out, gaps filled)
    spectra: tuple[Spectrum, ...] = ()  # of the mean X and Y traces (empty: off, or too short)
    spectrum_asked: bool = False
    masked: int = 0  # events the mask took out of the chosen shots (before the view range)

    @property
    def kept(self) -> npt.NDArray[np.bool_]:
        return self.counts >= self.minimum

    @property
    def centres(self) -> npt.NDArray[np.float64]:
        return (self.edges[:-1] + self.edges[1:]) / 2

    @property
    def left_out(self) -> int:
        return int(len(self.counts) - np.count_nonzero(self.kept))


def bin_width(events: int, span: float, given: float) -> tuple[float, bool, str, str]:
    """The T bin width: as given, else automatic (about ``AUTO_EVENTS`` per bin, ``AUTO_BINS``
    bins); widened to stay within ``MAX_BINS``. (width, automatic, the automatic limit reached:
    "at least", "at most" or "", what it says when widened)."""
    if given > 0:
        if given > span:
            return span, False, "", (f"T bin width {time_text(given, WIDTH_DIGITS)} is wider than the range "
                                     f"({time_text(span, WIDTH_DIGITS)}): using one bin of the range")
        if span / given > MAX_BINS:
            wider = span / MAX_BINS
            return wider, False, "", (f"T bin width {time_text(given, WIDTH_DIGITS)} gives over {MAX_BINS:,} bins: "
                                      f"using {time_text(wider, WIDTH_DIGITS)}")
        return given, False, "", ""
    low, high = AUTO_BINS
    wanted = events // AUTO_EVENTS
    clamp = "at least" if wanted < low else "at most" if wanted > high else ""
    return span / min(max(wanted, low), high), True, clamp, ""


def auto_text(data: PositionProfile) -> str:
    """Why the automatic width: ``~100 events per bin``, or the limit reached and the events per bin."""
    if not data.clamp:
        return f"~{AUTO_EVENTS} events per bin"
    limit = AUTO_BINS[0] if data.clamp == "at least" else AUTO_BINS[1]
    return f"{data.clamp} {limit:,} bins, ~{data.events / max(len(data.counts), 1):.3g} events per bin"


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


@dataclass(frozen=True)
class Stretch:
    """The bins a spectrum uses (``start`` to ``stop``, exclusive) and how many of them are
    gaps filled by straight lines; ``note`` says what was done ("" for a whole trace without
    gaps), and an empty stretch (start = stop) means no spectrum."""
    start: int
    stop: int
    filled: int
    note: str


def longest_run(kept: npt.NDArray[np.bool_]) -> tuple[int, int]:
    """The longest stretch of consecutive kept bins: (start, stop)."""
    padded = np.concatenate([[False], kept, [False]]).astype(np.int8)
    changes = np.flatnonzero(np.diff(padded))
    starts, stops = changes[::2], changes[1::2]
    if not len(starts):
        return 0, 0
    longest = int(np.argmax(stops - starts))
    return int(starts[longest]), int(stops[longest])


def stretch(kept: npt.NDArray[np.bool_], centres: npt.NDArray[np.float64]) -> Stretch:
    """Which bins the spectrum uses (module docstring): from the first kept bin to the last with
    the gaps filled while they are at most ``MAX_FILLED`` of it, else the longest stretch
    without gaps when it is long enough, else none."""
    where = np.flatnonzero(kept)
    if not len(where):
        return Stretch(0, 0, 0, "no spectrum: no bin kept")
    start, stop = int(where[0]), int(where[-1]) + 1
    gaps = (stop - start) - len(where)
    if stop - start < MIN_SPECTRUM_BINS:
        return Stretch(0, 0, 0, f"no spectrum: the traces have {stop - start:,} bins from the first kept to the "
                                f"last, under {MIN_SPECTRUM_BINS}")
    share = gaps / (stop - start)
    if share <= MAX_FILLED:
        note = f"{gaps:,} gap bin{'' if gaps == 1 else 's'} filled by straight lines for the spectrum" if gaps else ""
        return Stretch(start, stop, gaps, note)
    low, high = longest_run(kept)
    if high - low >= MIN_SPECTRUM_BINS:
        return Stretch(low, high, 0, f"gaps are {share * 100:.0f} % of the traces (over {MAX_FILLED * 100:.0f} %): spectrum of the "
                                     f"longest stretch without gaps, {range_text('T', centres[low], centres[high - 1])} "
                                     f"({high - low:,} bins)")
    return Stretch(0, 0, 0, f"no spectrum: gaps are {share * 100:.0f} % of the traces (over {MAX_FILLED * 100:.0f} %) and the "
                            f"longest stretch without gaps has {high - low:,} bins, under {MIN_SPECTRUM_BINS}")


def filled(centres: npt.NDArray[np.float64], trace: npt.NDArray[np.float64], part: Stretch
           ) -> npt.NDArray[np.float64]:
    """The trace over the stretch, its gaps filled by straight lines."""
    values, where = trace[part.start:part.stop], centres[part.start:part.stop]
    good = np.isfinite(values)
    if not good.all():
        values = np.interp(where, where[good], values[good])
    return cast(npt.NDArray[np.float64], np.asarray(values, dtype=np.float64))


def left_out_note(left_out: int, bins: int, minimum: int) -> str:
    """The plot's note on bins with too few events."""
    return f"{left_out:,} of {bins:,} bins with fewer than {minimum:,} events left out"


def empty_reason(data: PositionProfile) -> str:
    """Why there is nothing to draw ("" when there is)."""
    text = empty_text(data.total_shots, len(data.shots), data.total)
    if text and data.masked and data.shots:
        return all_masked_text(data.masked)
    if text:
        return text
    warned = "".join(f" · ⚠ {warning}" for warning in data.warnings)
    if not data.events:
        return (f"None of the {data.total:,} events in the chosen shots is inside the view range "
                f"(View range settings){warned}")
    if not data.kept.any():
        return (f"No T bin holds {data.minimum:,} events or more: {data.events:,} events in {len(data.counts):,} "
                f"bins of {time_text(data.width, WIDTH_DIGITS)} (T bins settings){warned}")
    return ""


def peak_text(spectrum: Spectrum, axis: str) -> str:
    if not spectrum.peaks:
        return f"mean {axis}: no peak"
    peaks = ", ".join(f"{frequency_text(peak.frequency)} ({number_text(peak.value, 3)} {LENGTH_UNIT})"
                      for peak in spectrum.peaks)
    return f"mean {axis}: {peaks}"


def titles(result: AnalysisResult, data: PositionProfile) -> tuple[str, ...]:
    """The figure's title lines: what it shows, its bins, then one line per note and warning."""
    bins = len(data.counts)
    how = "auto" if data.automatic else "set"
    first = (f"{result.input.short()} · {shots_text(data.shots, data.total_shots)} · {data.events:,} of "
             f"{data.total:,} events in range{masked_text(data.masked)}")
    second = f"{bins:,} T bins of {time_text(data.width, WIDTH_DIGITS)} ({how})"
    return (first, second, *data.notes, *(f"⚠ {warning}" for warning in data.warnings))


def result_brief(data: PositionProfile) -> str:
    """The automatic bins, bins left out and the spectrum's frequencies, for the settings line."""
    parts = [f"T bins {time_text(data.width, WIDTH_DIGITS)} (auto: {auto_text(data)})" if data.automatic else ""]
    if data.left_out:
        parts.append(f"{data.left_out:,} of {len(data.counts):,} bins left out")
    if data.spectra:
        parts.append(spectrum_text(data.spectra[0]))
    return " · ".join(part for part in parts if part)


def record_lines(data: PositionProfile) -> list[str]:
    """The bins (left out, filled), the spectrum's frequencies and its peaks, for the dock's record."""
    how = f"auto: {auto_text(data)}" if data.automatic else "set"
    # The bins left out once, here: not again from the plot's notes.
    lines = [f"T bins: {len(data.counts):,} of {time_text(data.width, WIDTH_DIGITS)} ({how}), {data.events:,} events; "
             f"{data.left_out:,} with fewer than {data.minimum:,} events left out",
             *(note for note in data.notes if note != left_out_note(data.left_out, len(data.counts), data.minimum))]
    if data.spectra:
        first = data.spectra[0]
        lines.append(f"Spectrum: {first.window} window, {spectrum_text(first)}, corrected for the bins' "
                     f"averaging (÷ sinc(f · bin width))")
        for axis, spectrum in zip(COLOURS, data.spectra):
            lines.append(f"Peaks, {peak_text(spectrum, axis)}")
    return lines


class PositionPlot(QWidget):
    """Mean X/Y and their SDs against T, optionally with their spectrum below (``graphics``, a
    PyQtGraph layout); ``show_data`` draws a newer result in place, keeping zoom and pan."""

    def __init__(self, spectrum: bool, log: bool, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.graphics: Any = pg.GraphicsLayoutWidget(self)
        self.graphics.setBackground("w")
        layout.addWidget(self.graphics)
        self.key = (spectrum, log)
        self.title: Any = add_label(self.graphics, row=0, col=0)
        self.means: Any = self.graphics.addPlot(row=1, col=0, title="Mean position ± SE",
                                                axisItems={"bottom": GroupedAxis("bottom"), "left": GroupedAxis("left")})
        self.widths: Any = self.graphics.addPlot(row=2, col=0, title="SD ± SE",
                                                 axisItems={"bottom": GroupedAxis("bottom"), "left": GroupedAxis("left")})
        self.widths.setXLink(self.means)
        self.curves: dict[tuple[str, str], Any] = {}
        self.bars: dict[tuple[str, str], Any] = {}
        for plot, kind, label in ((self.means, "mean", "Mean"), (self.widths, "sd", "SD")):
            plot.setLabel("bottom", axis_label("T"))
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
            self.spectrum = self.graphics.addPlot(row=3, col=0, title="Spectrum of the mean position",
                                                  axisItems={"left": GroupedAxis("left")})
            self.spectrum.setLabel("bottom", "Frequency", units="Hz")
            self.spectrum.setLabel("left", f"Amplitude ({LENGTH_UNIT})")
            self.spectrum.showGrid(x=True, y=True, alpha=0.3)
            self.spectrum.addLegend(offset=(-10, 10))
            if log:
                self.spectrum.setLogMode(x=False, y=True)
            for axis, colour in COLOURS.items():
                self.spectrum_curves[axis] = self.spectrum.plot([], [], name=f"mean {axis}", connect="finite",
                                                                pen=pg.mkPen(colour, width=1.2))
            self.peaks_label = add_label(self.graphics, row=4, col=0)

    def show_data(self, result: AnalysisResult, data: PositionProfile) -> None:
        self.title.setText(lines_html(titles(result, data)))
        centres = data.centres * T_SCALE
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
        self.peaks_label.setText(line_html(f"Peaks: {text}" if lines else text))


class MeanPositionVsT(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Mean X, Y against T",
            description="Mean position and width (SD) of X and Y in T bins, with standard errors, and optionally "
                        "their spectrum; from the DLD front panel's average-position plots",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.mean_position_vs_t",
            version="2",
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
        settings = (shots_brief(values), range_brief(values, fixed=True), mask_brief(values),
                    f"T bins {time_text(width, WIDTH_DIGITS)}" if width else "",
                    f"≥ {int(values[MIN_EVENTS.name]):,} events per bin", spectrum)
        return selection_text(view, values), " · ".join(part for part in settings if part)

    def describe_result(self, action_name: str, result: AnalysisResult) -> str:
        """The run's ``brief`` (``result_found``): kept when the plot is released."""
        return str(result.found.get("brief", ""))

    def result_found(self, action_name: str, data: Any) -> dict[str, Any]:
        """For the dock: ``brief`` (the settings line's addition: the automatic bins, bins left out,
        the spectrum's frequencies) and ``record_lines`` (the bins, the spectrum and its peaks)."""
        if not isinstance(data, PositionProfile) or not len(data.counts):
            return {}
        return {"brief": result_brief(data), "record_lines": record_lines(data)}

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        return [*range_warnings(values), *mask_warnings(values)]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        values = context.parameters
        shots = select_shots(context.view, values)
        mask = mask_from(values)  # Circles that can't be read fail the run, saying which.
        events, masked = mask.apply(context.view.events(shots))
        return replace(self._compute(context, shots, events), masked=masked)

    def _compute(self, context: AnalysisContext, shots: tuple[int, ...], events: Events) -> PositionProfile:
        values, view = context.parameters, context.view
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
        width, automatic, clamp, widened = bin_width(len(inside), upper - lower, float(values[BIN_WIDTH.name]))
        whole = whole_bins(inside[:, 0], lower, upper, width)
        # A partial last bin (the range's remainder past the last whole one) is kept for the
        # traces, centred on its own extent; the spectrum's evenly spaced samples leave it out.
        partial = whole.remainder > 0
        bins = whole.bins + int(partial)
        index = np.clip(np.floor((inside[:, 0] - lower) / width).astype(np.intp), 0, bins - 1)
        edges = (lower + width * np.arange(whole.bins + 1)).astype(np.float64)
        if partial:
            edges = np.append(edges, upper)
        counts = np.bincount(index, minlength=bins).astype(np.int64)
        kept = counts >= minimum
        traces = []
        for column, axis in ((1, "X"), (2, "Y")):
            context.check()
            traces.append(bin_statistics(inside[:, column] * LENGTH_SCALE, index, counts, kept, axis))
        notes: list[str] = []
        left_out = int(bins - np.count_nonzero(kept))
        if left_out and kept.any():
            notes.append(left_out_note(left_out, bins, minimum))
        data = PositionProfile(shots, len(view.shots), len(events), len(inside), edges, counts, tuple(traces), width,
                               automatic, clamp, minimum, box,
                               range_warnings(values) + ((widened,) if widened else ()), tuple(notes),
                               spectrum_asked=bool(values[SPECTRUM.name]))
        if not values[SPECTRUM.name] or not kept.any():
            return data
        context.check()
        centres = data.centres
        evenly = kept.copy()
        if partial:
            evenly[-1] = False  # not evenly spaced
            notes.append(f"the last bin is {time_text(whole.remainder, WIDTH_DIGITS)} wide (partial): in the traces, not in "
                         f"the spectrum")
        part = stretch(evenly, centres)  # X's and Y's gaps are the same bins
        if part.note:
            notes.append(part.note)
        if part.stop == part.start:
            return replace(data, notes=tuple(notes))
        spectra = []
        for trace in traces:
            spectrum = amplitude_spectrum(filled(centres, trace.mean, part), width, str(values[WINDOW.name]),
                                          binned=True)
            spectra.append(find_spectrum_peaks(spectrum, int(values[PEAKS.name]), float(values[PEAKS_ABOVE.name]),
                                               float(values[THRESHOLD.name])))
        return replace(data, notes=tuple(notes), spectra=tuple(spectra))

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: PositionProfile = result.data
        reason = empty_reason(data)
        if reason:
            return empty_pane(reason, parent)
        widget = PositionPlot(data.spectrum_asked, bool(result.parameters.get(LOG.name, LOG.default)), parent)
        widget.show_data(result, data)
        return widget

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """A rerun (e.g. Live's next shots) draws in place, keeping zoom and pan, while the
        spectrum (shown, log) stays; otherwise, or to or from an empty plot, anew."""
        data: PositionProfile = result.data
        if not isinstance(widget, PositionPlot) or empty_reason(data):
            return False
        if widget.key != (data.spectrum_asked, bool(result.parameters.get(LOG.name, LOG.default))):
            return False
        widget.show_data(result, data)
        return True

