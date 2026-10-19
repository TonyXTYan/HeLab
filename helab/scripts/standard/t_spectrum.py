"""Spectrum of the T profile summed over the chosen shots, with a peak list (the lab's 1D FFT,
``TOF_averaged`` and Core's ``fft_tx``): the pulse-train rate, mains or other noise pickup,
and trap frequencies in summed arrival times.

The events inside the plot's view range (auto-crop or manual, over T, X and Y) are histogrammed
finely in T, from the range's start, in bins of exactly the width set; automatic: from the
data rate, about ``AUTO_EVENTS`` (10) events per bin on average, so a bin's shot noise is
about a third of it and Nyquist is a twentieth of the summed events' mean rate, between 256 and
16,384 bins (narrow the range or set the width for higher frequencies). The profile is the rate per shot (kHz per shot, the front panel's
"kHz/File") or the summed counts. Its mean is subtracted, it is windowed (Hann by default)
and transformed (``helab.analysis.spectrum``: amplitudes normalised as ``fft_tx``, optional
zero padding), and the most prominent peaks are listed with their frequency, amplitude and
prominence, in the plot and in the result. The frequency resolution (1 over the profile's
length) and Nyquist frequency (half the bins' rate) are in the dock's settings line.

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

from helab.analysis.dataset_view import DatasetView
from helab.analysis.display_units import frequency_text, time_text, time_unit
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.follow import LivePolicy
from helab.analysis.parameters import ParameterSpec
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import (SHOT_SPECS, keep_fraction, manual, manual_box, range_brief, range_specs,
                                      range_warnings, select_shots, selection_text, shots_brief, shots_text)
from helab.analysis.spectrum import (AMPLITUDE, MAX_PADDING, POWER, Spectrum, amplitude_spectrum,
                                     find_spectrum_peaks, padding_for, peak_specs, window_spec)
from helab.analysis.stats import CropBox, crop_box
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.standard import group

RANGE = range_specs(
    "The box holding this share of the events, as the 3D scatter's auto-crop: the T profile spans its T range "
    "and only events inside it count. 100 % keeps every event.")
PROFILE_GROUP = "T profile"
BIN_WIDTH = ParameterSpec(
    "t_bin", "T bin width (0 = auto)", "float", 0.0, (0.0, 10.0), " s", group=PROFILE_GROUP, si=True,
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
LOG = ParameterSpec("spectrum_log", "Log scale", "bool", True, group=SPECTRUM_GROUP,
                    tip="Logarithmic amplitude (or power) axis.")
PADDING = ParameterSpec(
    "padding", "Zero padding ×", "int", 1, (1, MAX_PADDING), group=SPECTRUM_GROUP,
    tip="The transform is this many times the profile's length: the spectrum is drawn more finely, and peaks "
        "located better between bins, but its resolution stays 1 over the profile's length.")
PEAKS, THRESHOLD, PEAKS_ABOVE = peak_specs(SPECTRUM_GROUP, 5)
PARAMETERS = (*SHOT_SPECS, *RANGE, BIN_WIDTH, UNITS, WINDOW, SCALE, LOG, PADDING, PEAKS, THRESHOLD, PEAKS_ABOVE)

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
    capped: bool = False  # automatic, and at the most bins
    counts: npt.NDArray[np.int64] = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    per_shot: bool = True
    time_unit: str = "ms"
    box: CropBox | None = None
    spectrum: Spectrum | None = None
    warnings: tuple[str, ...] = ()  # settings not followed as given
    short: str = ""  # why there is no spectrum (too few events or bins)

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
        return "kHz/shot" if self.per_shot else "events"


def bin_width(events: int, span: float, given: float) -> tuple[float, bool, bool, str]:
    """The T bin width: as given, else automatic (``AUTO_EVENTS`` per bin, ``AUTO_BINS``); widened
    to stay within ``MAX_BINS``. (width, automatic, capped, what it says when widened)."""
    if given > 0:
        if span / given > MAX_BINS:
            wider = span / MAX_BINS
            return wider, False, False, (f"T bin width {time_text(given)} gives over {MAX_BINS:,} bins: using "
                                         f"{time_text(wider)}")
        return given, False, False, ""
    low, high = AUTO_BINS
    wanted = events // AUTO_EVENTS
    return span / min(max(wanted, low), high), True, wanted > high, ""


def empty_reason(data: ProfileSpectrum) -> str:
    """Why there is nothing to draw ("" when there is)."""
    text = empty_text(data.total_shots, len(data.shots), data.total)
    if text:
        return text
    warned = "".join(f" · ⚠ {warning}" for warning in data.warnings)
    if not data.events:
        return (f"None of the {data.total:,} events in the chosen shots is inside the view range "
                f"(View range settings){warned}")
    return data.short + warned if data.short else ""


def value_unit(data: ProfileSpectrum) -> str:
    power = data.spectrum is not None and data.spectrum.power
    return f"({data.unit})²" if power else data.unit


def peak_lines(data: ProfileSpectrum) -> list[str]:
    spectrum = data.spectrum
    if spectrum is None:
        return []
    unit = value_unit(data)
    return [f"{rank}. {frequency_text(peak.frequency)} · {peak.value:.3g} {unit} · prominence "
            f"{peak.prominence:.3g}" for rank, peak in enumerate(spectrum.peaks, start=1)]


def titles(result: AnalysisResult, data: ProfileSpectrum) -> tuple[str, str]:
    first = (f"{result.input.short()} · {shots_text(data.shots, data.total_shots)} · {data.events:,} of "
             f"{data.total:,} events in range")
    second = [f"{len(data.counts):,} T bins of {time_text(data.width)} ({'auto' if data.automatic else 'set'})"]
    if data.spectrum is not None:
        spectrum = data.spectrum
        second.append(f"Δf {frequency_text(spectrum.resolution)}, Nyquist {frequency_text(spectrum.nyquist)}")
        second.append(f"{spectrum.window} window" + (f", zero padding ×{spectrum.padding}" if spectrum.padding > 1
                                                     else ""))
    second += [f"⚠ {warning}" for warning in data.warnings]
    return first, " · ".join(second)


class SpectrumPlot(QWidget):
    """The summed T profile above its spectrum with the peaks marked, and the peak list
    (``graphics``, a PyQtGraph layout); ``show_data`` draws a newer result in place."""

    def __init__(self, key: tuple[bool, bool, bool, str], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.graphics: Any = pg.GraphicsLayoutWidget(self)
        self.graphics.setBackground("w")
        layout.addWidget(self.graphics)
        self.key = key
        log, power, per_shot, unit = key
        self.title: Any = self.graphics.addLabel("", row=0, col=0)
        self.profile_plot: Any = self.graphics.addPlot(row=1, col=0, title="T profile, summed over the shots")
        self.profile_plot.setLabel("bottom", f"T ({unit})")
        self.profile_plot.setLabel("left", "Rate (kHz per shot)" if per_shot else "Events per bin")
        self.profile_plot.showGrid(x=True, y=True, alpha=0.3)
        self.profile: Any = self.profile_plot.plot([], [], pen=pg.mkPen(COLOUR))
        self.profile.setDownsampling(auto=True, method="peak")
        self.profile.setClipToView(True)
        self.spectrum_plot: Any = self.graphics.addPlot(row=2, col=0, title="Spectrum")
        self.spectrum_plot.setLabel("bottom", "Frequency", units="Hz")
        quantity = "Power" if power else "Amplitude"
        self.spectrum_plot.setLabel("left", f"{quantity} ({'kHz/shot' if per_shot else 'events'}"
                                            f"{')²' if power else ')'}")
        self.spectrum_plot.showGrid(x=True, y=True, alpha=0.3)
        if log:
            self.spectrum_plot.setLogMode(x=False, y=True)
        self.spectrum: Any = self.spectrum_plot.plot([], [], pen=pg.mkPen(COLOUR, width=1))
        self.spectrum.setDownsampling(auto=True, method="peak")
        self.spectrum.setClipToView(True)
        self.markers: Any = self.spectrum_plot.plot([], [], pen=None, symbol="o", symbolSize=7,
                                                    symbolBrush=None, symbolPen=pg.mkPen(PEAK_COLOUR, width=1.5))
        self.labels: list[Any] = []
        self.peaks_label: Any = self.graphics.addLabel("", row=3, col=0, justify="left")
        self.graphics.ci.layout.setRowStretchFactor(1, 2)
        self.graphics.ci.layout.setRowStretchFactor(2, 3)

    def show_data(self, result: AnalysisResult, data: ProfileSpectrum) -> None:
        log = self.key[0]
        first, second = titles(result, data)
        self.title.setText(f"{html.escape(first)}<br>{html.escape(second)}")
        scale = 1e3 if data.time_unit == "ms" else 1.0
        self.profile.setData(data.centres * scale, data.profile)
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
            text = html.escape(f"No peak with a prominence of {spectrum.threshold:.3g} {value_unit(data)} or more "
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
            version="1",
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
        settings = (shots_brief(values), range_brief(values), f"T bins {time_text(width)}" if width else "",
                    "counts" if values[UNITS.name] == COUNTS else "", spectrum,
                    "power" if values[SCALE.name] == POWER else "", "log" if values[LOG.name] else "",
                    f"{int(values[PEAKS.name]):,} peaks")
        return selection_text(view, values), " · ".join(part for part in settings if part)

    def describe_result(self, action_name: str, result: AnalysisResult) -> str:
        data = result.data
        if not isinstance(data, ProfileSpectrum) or not len(data.counts):
            return ""
        parts = []
        if data.automatic:
            why = f"capped at {AUTO_BINS[1]:,} bins" if data.capped else f"~{AUTO_EVENTS} events per bin"
            parts.append(f"T bins {time_text(data.width)} (auto: {why})")
        if data.spectrum is not None:
            parts.append(f"Δf {frequency_text(data.spectrum.resolution)} · Nyquist "
                         f"{frequency_text(data.spectrum.nyquist)}")
        return " · ".join(parts)

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        return list(range_warnings(values))

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        values, view = context.parameters, context.view
        shots = select_shots(view, values)
        events = view.events(shots)
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
        width, automatic, capped, widened = bin_width(len(times), upper - lower, float(values[BIN_WIDTH.name]))
        bins = max(1, math.ceil((upper - lower) / width * (1 - 1e-12)))
        index = np.minimum(((times - lower) / width).astype(np.intp), bins - 1)
        counts = np.bincount(index, minlength=bins).astype(np.int64)
        warnings = range_warnings(values) + ((widened,) if widened else ())
        data = ProfileSpectrum(shots, len(view.shots), len(events), len(times), lower, width, automatic, capped,
                               counts, per_shot, time_unit(lower, upper)[0], box, warnings=warnings)
        if len(times) < MIN_EVENTS:
            return replace(data, short=f"Only {len(times):,} event{'' if len(times) == 1 else 's'} in the view "
                                       f"range: a spectrum needs {MIN_EVENTS} or more")
        if bins < MIN_BINS:
            return replace(data, short=f"Only {bins:,} T bin{'' if bins == 1 else 's'} of {time_text(width)} in "
                                       f"the view range: a spectrum needs {MIN_BINS} or more (T bin width setting)")
        context.check()
        padding, lowered = padding_for(bins, int(values[PADDING.name]))
        if lowered:
            warnings += (lowered,)
        spectrum = amplitude_spectrum(data.profile, width, str(values[WINDOW.name]), padding,
                                      values[SCALE.name] == POWER)
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
    def key(result: AnalysisResult, data: ProfileSpectrum) -> tuple[bool, bool, bool, str]:
        """What the plot's axes are: log, power, per shot, T's unit."""
        return (bool(result.parameters.get(LOG.name, LOG.default)), result.parameters.get(SCALE.name) == POWER,
                data.per_shot, data.time_unit)

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """A rerun (e.g. Live's next shots) draws in place, keeping zoom and pan, while the axes
        (log, power, units, T's unit) stay; otherwise, or to or from an empty plot, anew."""
        data: ProfileSpectrum = result.data
        if not isinstance(widget, SpectrumPlot) or empty_reason(data) or widget.key != self.key(result, data):
            return False
        widget.show_data(result, data)
        return True

