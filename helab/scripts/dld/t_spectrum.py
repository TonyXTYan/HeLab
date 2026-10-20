"""Spectrum of the T profile summed over the chosen shots, with a peak list (the lab's 1D FFT,
``TOF_averaged`` and Core's ``fft_tx``): the pulse-train rate, mains or other noise pickup,
and trap frequencies in summed arrival times.

The events inside the plot's view range (auto-crop or manual, over T, X and Y) are histogrammed
finely in T, from the range's start, in whole bins of exactly the width set (events past the
last whole bin are left out, said so); automatic: from the data rate, about ``AUTO_EVENTS``
(10) events per bin on average, so a bin's shot noise is about a third of it and Nyquist is a
twentieth of the summed events' mean rate, between 256 and 16,384 bins (narrow the range or
set the width for higher frequencies; the dock line says when a limit applies). The profile is
the rate per shot (kHz per shot, the front panel's "kHz/File") or the summed counts. Its mean
is subtracted, it is windowed (Hann by default) and transformed (``helab.analysis.spectrum``:
amplitudes normalised as ``fft_tx``, corrected for the bins' averaging, optional zero padding),
and the most prominent peaks are listed with their frequency, amplitude and prominence, in the
plot, the dock's record and the result. The bin spacing Δf (1 over the profile's length), the
resolution (≈ the window's ENBW · Δf) and Nyquist (half the bins' rate) are in the dock's
settings line.

Not done yet (see the session notes): a Welch PSD, and Lomb–Scargle for uneven samples (the
T profile's are even).
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

from helab.analysis.dataset_view import DatasetView, Events
from helab.analysis.display_units import T_SCALE, WIDTH_DIGITS, axis_label, frequency_text, time_text
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.masks import MASK_SPECS, all_masked_text, mask_brief, mask_from, mask_warnings, masked_text
from helab.analysis.follow import LivePolicy
from helab.analysis.parameters import ParameterSpec
from helab.analysis.plot_axes import GroupedAxis
from helab.analysis.plot_text import add_label, add_plot, lines_html
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import (SHOT_SPECS, keep_fraction, manual, manual_box, range_brief, range_specs,
                                      range_warnings, select_shots, selection_text, shots_brief, shots_text)
from helab.analysis.spectrum import (AMPLITUDE, MAX_PADDING, POWER, Spectrum, amplitude_spectrum, dropped_text,
                                     find_spectrum_peaks, padding_for, peak_specs, spectrum_text, whole_bins,
                                     window_spec)
from helab.analysis.stats import CropBox, crop_box
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.dld import group

RANGE = range_specs(
    "The box holding this share of the events, as the 3D scatter's auto-crop: the T profile spans its T range "
    "and only events inside it count. 100 % keeps every event.", fixed=True)
PROFILE_GROUP = "T profile"
BIN_WIDTH = ParameterSpec(
    "t_bin", "T bin width (0 = auto)", "float", 0.0, (0.0, 10.0), " s", group=PROFILE_GROUP, si=True,
    unit_prefix="m",
    tip="Each bin is exactly this wide, from the start of the range; the spectrum reaches half the bins' rate "
        "(Nyquist). 0 = automatic, from the data rate: about 10 events per bin on average, 256–16,384 bins.")
RATE, COUNTS = "rate per shot", "counts"
UNITS = ParameterSpec(
    "profile_units", "Profile", "choice", RATE, choices=(RATE, COUNTS), group=PROFILE_GROUP,
    tip="Rate per shot: events per bin width per shot, in kHz (the front panel's kHz/File); counts: events per "
        "bin summed over the shots. The spectrum's amplitude is in the same unit.")
SPECTRUM_GROUP = "Spectrum"
WINDOW = window_spec(SPECTRUM_GROUP)
SCALE = ParameterSpec("spectrum_scale", "Spectrum", "choice", AMPLITUDE, choices=(AMPLITUDE, POWER),
                      group=SPECTRUM_GROUP, tip="Amplitude, or power (the amplitude squared; not per Hz).")
LOG = ParameterSpec("spectrum_log", "Log Y", "bool", True, group=SPECTRUM_GROUP,
                    tip="Logarithmic amplitude (or power) axis.")
PADDING = ParameterSpec(
    "padding", "Zero padding ×", "int", 1, (1, MAX_PADDING), group=SPECTRUM_GROUP,
    tip="The transform is this many times the profile's length: the spectrum is drawn more finely, and peaks "
        "located better between bins, but its resolution stays 1 over the profile's length.")
PEAKS, THRESHOLD, PEAKS_ABOVE = peak_specs(SPECTRUM_GROUP, 5)
PARAMETERS = (*SHOT_SPECS, *RANGE, *MASK_SPECS,
              BIN_WIDTH, UNITS, WINDOW, SCALE, LOG, PADDING, PEAKS, THRESHOLD, PEAKS_ABOVE)

AUTO_EVENTS = 10  # automatic bins: about this many events per bin on average …
AUTO_BINS = (256, 16_384)  # … and at least / at most this many bins
MAX_BINS = 1 << 20
MIN_EVENTS = 10  # a spectrum needs at least this many events in the range …
MIN_BINS = 16  # … and this many bins
POINT_SPAN = 5e-4  # a range with no T extent is widened by this each way
COLOUR = (40, 90, 170)
PEAK_COLOUR = (214, 39, 40)


@dataclass(frozen=True)
class ProfileSpectrum:
    shots: tuple[int, ...]
    total_shots: int
    total: int  # events in the chosen shots
    events: int = 0  # of them, inside the view range
    lower: float = math.nan  # the profile's start (s)
    width: float = math.nan  # its bin width (s)
    automatic: bool = True
    clamp: str = ""  # automatic, and at a bin limit: "at least" or "at most" (else "")
    counts: npt.NDArray[np.int64] = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    per_shot: bool = True
    box: CropBox | None = None
    spectrum: Spectrum | None = None
    warnings: tuple[str, ...] = ()  # settings not followed as given
    short: str = ""  # why there is no spectrum (too few events or bins)
    notes: tuple[str, ...] = ()  # what else the plot says (events past the last whole bin)
    masked: int = 0  # events the mask took out of the chosen shots (before the view range)

    @property
    def profile(self) -> npt.NDArray[np.float64]:
        """The T profile: kHz per shot, or events per bin."""
        counts = self.counts.astype(np.float64)
        if not self.per_shot or not len(self.shots):
            return counts
        return counts / (self.width * len(self.shots)) / 1e3

    @property
    def centres(self) -> npt.NDArray[np.float64]:
        return cast(npt.NDArray[np.float64], self.lower + self.width * (np.arange(len(self.counts)) + 0.5))

    @property
    def unit(self) -> str:
        return "kHz per shot" if self.per_shot else "events"


def bin_width(events: int, span: float, given: float) -> tuple[float, bool, str, str]:
    """The T bin width: as given, else automatic (``AUTO_EVENTS`` per bin, ``AUTO_BINS``); widened
    to stay within ``MAX_BINS``. (width, automatic, the automatic limit reached: "at least",
    "at most" or "", what it says when widened)."""
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


def auto_text(data: ProfileSpectrum) -> str:
    """Why the automatic width: ``~10 events per bin``, or the limit reached and the events per bin."""
    if not data.clamp:
        return f"~{AUTO_EVENTS} events per bin"
    limit = AUTO_BINS[0] if data.clamp == "at least" else AUTO_BINS[1]
    per_bin = data.events / max(len(data.counts), 1)
    return f"{data.clamp} {limit:,} bins, ~{per_bin:.3g} events per bin"


def empty_reason(data: ProfileSpectrum) -> str:
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
    return data.short + warned if data.short else ""


def value_unit(data: ProfileSpectrum) -> str:
    power = data.spectrum is not None and data.spectrum.power
    if not power:
        return data.unit
    return "kHz² per shot²" if data.per_shot else "events²"


def peak_lines(data: ProfileSpectrum) -> list[str]:
    spectrum = data.spectrum
    if spectrum is None:
        return []
    unit = value_unit(data)
    return [f"{rank}. {frequency_text(peak.frequency)} · {peak.value:.3g} {unit} · prominence "
            f"{peak.prominence:.3g} {data.unit}" for rank, peak in enumerate(spectrum.peaks, start=1)]


def titles(result: AnalysisResult, data: ProfileSpectrum) -> tuple[str, ...]:
    """The figure's title lines: what it shows, its bins and spectrum, then one line per note and
    warning."""
    first = (f"{result.input.short()} · {shots_text(data.shots, data.total_shots)} · {data.events:,} of "
             f"{data.total:,} events in range{masked_text(data.masked)}")
    second = [f"{len(data.counts):,} T bins of {time_text(data.width, WIDTH_DIGITS)} "
              f"({'auto' if data.automatic else 'set'})"]
    if data.spectrum is not None:
        spectrum = data.spectrum
        second.append(spectrum_text(spectrum))
        second.append(f"{spectrum.window} window" + (f", zero padding ×{spectrum.padding}" if spectrum.padding > 1
                                                     else ""))
    return (first, " · ".join(second), *data.notes, *(f"⚠ {warning}" for warning in data.warnings))


def result_brief(data: ProfileSpectrum) -> str:
    """The automatic bins and the spectrum's frequencies, for the settings line."""
    parts = []
    if data.automatic:
        parts.append(f"T bins {time_text(data.width, WIDTH_DIGITS)} (auto: {auto_text(data)})")
    if data.spectrum is not None:
        parts.append(spectrum_text(data.spectrum))
    return " · ".join(parts)


def record_lines(data: ProfileSpectrum) -> list[str]:
    """The bins, the spectrum's frequencies and the peak list, for the dock's record."""
    how = f"auto: {auto_text(data)}" if data.automatic else "set"
    lines = [f"T profile: {len(data.counts):,} bins of {time_text(data.width, WIDTH_DIGITS)} ({how}), "
             f"{data.events:,} events", *data.notes]
    spectrum = data.spectrum
    if spectrum is None:
        return [*lines, data.short] if data.short else lines
    lines.append(f"Spectrum: {spectrum.window} window, {spectrum_text(spectrum)}, corrected for the bins' "
                 f"averaging (÷ sinc(f · bin width))")
    peaks = peak_lines(data)
    if peaks:
        lines.append(f"Peaks (prominence ≥ {spectrum.threshold:.3g} {data.unit}):")
        lines += [f"  {line}" for line in peaks]
    elif spectrum.threshold:
        lines.append(f"No peak with a prominence of {spectrum.threshold:.3g} {data.unit} or more")
    return lines


class SpectrumPlot(QWidget):
    """The summed T profile above its spectrum with the peaks marked, and the peak list
    (``graphics``, a PyQtGraph layout); ``show_data`` draws a newer result in place."""

    def __init__(self, key: tuple[bool, bool, bool], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.graphics: Any = pg.GraphicsLayoutWidget(self)
        self.graphics.setBackground("w")
        layout.addWidget(self.graphics)
        self.key = key
        log, power, per_shot = key
        self.title: Any = add_label(self.graphics, row=0, col=0)
        self.profile_plot: Any = add_plot(self.graphics, "T profile, summed over the shots",
                                          row=1, col=0, axisItems={"bottom": GroupedAxis("bottom")})
        self.profile_plot.setLabel("bottom", axis_label("T"))
        self.profile_plot.setLabel("left", "Rate (kHz per shot)" if per_shot else "Events per bin")
        self.profile_plot.showGrid(x=True, y=True, alpha=0.3)
        self.profile: Any = self.profile_plot.plot([], [], pen=pg.mkPen(COLOUR))
        self.profile.setDownsampling(auto=True, method="peak")
        self.profile.setClipToView(True)
        self.spectrum_plot: Any = add_plot(self.graphics, "Spectrum",
                                           row=2, col=0, axisItems={"left": GroupedAxis("left")})
        self.spectrum_plot.setLabel("bottom", "Frequency", units="Hz")
        quantity = "Power" if power else "Amplitude"
        unit = ("kHz² per shot²" if power else "kHz per shot") if per_shot else ("events²" if power else "events")
        self.spectrum_plot.setLabel("left", f"{quantity} ({unit})")
        self.spectrum_plot.showGrid(x=True, y=True, alpha=0.3)
        if log:
            self.spectrum_plot.setLogMode(x=False, y=True)
        self.spectrum: Any = self.spectrum_plot.plot([], [], pen=pg.mkPen(COLOUR, width=1))
        self.spectrum.setDownsampling(auto=True, method="peak")
        self.spectrum.setClipToView(True)
        self.markers: Any = self.spectrum_plot.plot([], [], pen=None, symbol="o", symbolSize=7,
                                                    symbolBrush=None, symbolPen=pg.mkPen(PEAK_COLOUR, width=1.5))
        self.labels: list[Any] = []
        self.peaks_label: Any = add_label(self.graphics, row=3, col=0, justify="left")
        self.graphics.ci.layout.setRowStretchFactor(1, 2)
        self.graphics.ci.layout.setRowStretchFactor(2, 3)

    def show_data(self, result: AnalysisResult, data: ProfileSpectrum) -> None:
        log = self.key[0]
        self.title.setText(lines_html(titles(result, data)))
        self.profile.setData(data.centres * T_SCALE, data.profile)
        for label in self.labels:
            self.spectrum_plot.removeItem(label)
        self.labels = []
        spectrum = data.spectrum
        if spectrum is None:
            self.spectrum.setData([], [])
            self.markers.setData([], [])
            self.peaks_label.setText("")
            return
        values = spectrum.values[1:]  # DC is 0: the mean is subtracted
        self.spectrum.setData(spectrum.frequencies[1:], np.where(values > 0, values, np.nan) if log else values)
        peaks = [peak for peak in spectrum.peaks if peak.value > 0 or not log]
        self.markers.setData([peak.frequency for peak in peaks], [peak.value for peak in peaks])
        for rank, peak in enumerate(spectrum.peaks, start=1):
            label = pg.TextItem(str(rank), color=PEAK_COLOUR, anchor=(0.5, 1.2))
            label.setPos(peak.frequency, math.log10(peak.value) if log and peak.value > 0 else peak.value)
            self.spectrum_plot.addItem(label)
            self.labels.append(label)
        lines = peak_lines(data)
        if lines:
            text = "Peaks: " + "<br>".join(html.escape(line) for line in lines)
        elif spectrum.threshold:
            # The threshold is in amplitude, also for power (Peak prominence's tip).
            text = html.escape(f"No peak with a prominence of {spectrum.threshold:.3g} {data.unit} or more "
                               f"(Peaks settings)")
        else:
            text = ""
        self.peaks_label.setText(text)


class TProfileSpectrum(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="T spectrum",
            description="Spectrum of the T profile summed over the shots, with its peaks (pulse rate, noise, trap "
                        "frequencies); the lab's 1D FFT and TOF_averaged",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.t_spectrum",
            version="2",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*PARAMETERS]

    def live_policy(self, action_name: str) -> LivePolicy:
        # The auto-crop of a large folder takes a second or more: at most one rerun every 2 s.
        return LivePolicy(min_delay=2.0)

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        width = float(values[BIN_WIDTH.name])
        padding = int(values[PADDING.name])
        spectrum = f"{values[WINDOW.name]} window" + (f", ×{padding} padding" if padding > 1 else "")
        settings = (shots_brief(values), range_brief(values, fixed=True), mask_brief(values),
                    f"T bins {time_text(width, WIDTH_DIGITS)}" if width else "",
                    "counts" if values[UNITS.name] == COUNTS else "", spectrum,
                    "power" if values[SCALE.name] == POWER else "", "log" if values[LOG.name] else "",
                    f"{int(values[PEAKS.name]):,} peaks")
        return selection_text(view, values), " · ".join(part for part in settings if part)

    def describe_result(self, action_name: str, result: AnalysisResult) -> str:
        """The run's ``brief`` (``result_found``): kept when the plot is released."""
        return str(result.found.get("brief", ""))

    def result_found(self, action_name: str, data: Any) -> dict[str, Any]:
        """For the dock: ``brief`` (the automatic bins, the spectrum's frequencies) and
        ``record_lines`` (the bins, the spectrum's frequencies and the peak list)."""
        if not isinstance(data, ProfileSpectrum) or not len(data.counts):
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

    def _compute(self, context: AnalysisContext, shots: tuple[int, ...], events: Events) -> ProfileSpectrum:
        values, view = context.parameters, context.view
        per_shot = values[UNITS.name] == RATE
        empty = ProfileSpectrum(shots, len(view.shots), len(events), per_shot=per_shot,
                                warnings=range_warnings(values))
        context.check()
        if not len(events):
            return empty
        box = manual_box(events, values) if manual(values) else crop_box(events, keep_fraction(values),
                                                                         context.cancelled)
        context.check()
        times = events[box.contains(events), 0]
        if not len(times):
            return replace(empty, box=box)
        lower, upper = box.lower[0], box.upper[0]
        if not upper > lower:
            lower, upper = lower - POINT_SPAN, upper + POINT_SPAN
        width, automatic, clamp, widened = bin_width(len(times), upper - lower, float(values[BIN_WIDTH.name]))
        binned = whole_bins(times, lower, upper, width)
        bins = binned.bins
        counts = np.bincount(binned.index, minlength=bins).astype(np.int64)
        warnings = range_warnings(values) + ((widened,) if widened else ())
        dropped = dropped_text(binned)
        data = ProfileSpectrum(shots, len(view.shots), len(events), len(times) - binned.dropped, lower, width,
                               automatic, clamp, counts, per_shot, box,
                               warnings=warnings, notes=(dropped,) if dropped else ())
        times = times[binned.kept]
        if len(times) < MIN_EVENTS:
            return replace(data, short=f"Only {len(times):,} event{'' if len(times) == 1 else 's'} in the view "
                                       f"range: a spectrum needs {MIN_EVENTS} or more")
        if bins < MIN_BINS:
            return replace(data, short=f"Only {bins:,} T bin{'' if bins == 1 else 's'} of "
                                       f"{time_text(width, WIDTH_DIGITS)} in "
                                       f"the view range: a spectrum needs {MIN_BINS} or more (T bin width setting)")
        context.check()
        padding, lowered = padding_for(bins, int(values[PADDING.name]))
        if lowered:
            warnings += (lowered,)
        spectrum = amplitude_spectrum(data.profile, width, str(values[WINDOW.name]), padding,
                                      values[SCALE.name] == POWER, binned=True)
        context.check()
        spectrum = find_spectrum_peaks(spectrum, int(values[PEAKS.name]), float(values[PEAKS_ABOVE.name]),
                                       float(values[THRESHOLD.name]))
        return replace(data, spectrum=spectrum, warnings=warnings)

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: ProfileSpectrum = result.data
        reason = empty_reason(data)
        if reason:
            return empty_pane(reason, parent)
        widget = SpectrumPlot(self.key(result, data), parent)
        widget.show_data(result, data)
        return widget

    @staticmethod
    def key(result: AnalysisResult, data: ProfileSpectrum) -> tuple[bool, bool, bool]:
        """What the plot's axes are: log, power, per shot."""
        return (bool(result.parameters.get(LOG.name, LOG.default)), result.parameters.get(SCALE.name) == POWER,
                data.per_shot)

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """A rerun (e.g. Live's next shots) draws in place, keeping zoom and pan, while the axes
        (log, power, units) stay; otherwise, or to or from an empty plot, anew."""
        data: ProfileSpectrum = result.data
        if not isinstance(widget, SpectrumPlot) or empty_reason(data) or widget.key != self.key(result, data):
            return False
        widget.show_data(result, data)
        return True

