"""Counts per shot and T/X/Y histograms of a loaded folder, the DLD front panel port's versions
(helab.dld.*; "Basic plots v1" keeps its own in helab.scripts.standard) (PyQtGraph: native Qt drawing,
fast to redraw when Live adds shots, and painted on lab PCs that can't paint QtWebEngine).

The histograms show X and Y in mm and T in ms (``display_units``), as counts or
a rate per shot, optionally smoothed, and can fit each axis (D1: off by default, so the plot
stays fast) for its centre, width and temperature (``helab.analysis.profiles``)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, List, Mapping, Optional, cast

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget

from helab.analysis.bec_readout import AUTO, SOURCES, BecReadout, readout
from helab.analysis.constant_layers import constants_specs, describe_constants, resolve_for_run
from helab.analysis.display_units import WIDTH_DIGITS, axis_label, axis_scale, axis_text
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.follow import LivePolicy
from helab.analysis.masks import (MASK_SPECS, all_masked_text, mask_brief, mask_from, mask_warnings,
                                  masked_counts_per_shot, masked_text)
from helab.analysis.overlay import OverlayView, overlay_newest, update_newest
from helab.analysis.parameters import ParameterSpec
from helab.analysis.physics import ResolvedConstants
from helab.analysis.plot_axes import GroupedAxis
from helab.analysis.plot_text import add_label, line_html, lines_html, notes_html, set_plot_title
from helab.analysis.profiles import (BIMODALS, CONDENSATE, COUNTS, NO_CONDENSATE, RATE, SMOOTHED, T_MODELS,
                                     TF_EXPONENT_TIP, UNSMOOTHED, XY_MODELS, AxisFit, fit_axis, rate_factor, smooth, smoothing_bins, value_label)
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.dataset_view import DatasetView
from helab.analysis.selection import (SHOT_SPECS, keep_fraction, manual, manual_bounds, newest_brief, newest_colour,
                                      newest_events, newest_shot, newest_specs, range_brief, range_specs,
                                      range_warnings, reversed_axes, select_shots, selection_text, shots_brief,
                                      shots_text)
from helab.analysis.stats import AXES, MAX_BINS, Histogram, counts_per_shot, histogram, shortest_range
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.dld import group
from helab.utils.colours import AMBER

RANGE = range_specs(
    "Each histogram covers the exact shortest range holding this share of its axis's events. "
    "100 % covers every event.", fixed=True)
BINS_GROUP = "Histogram"
BINS = ParameterSpec(
    "bins", "Bins (0 = auto)", "int", 0, (0, MAX_BINS), "", group=BINS_GROUP,
    tip="0 = automatic: the bin count comes from the data (Freedman–Diaconis: width 2·IQR·n^-1/3). "
        "Smoothing sets its own bins (σ/5).")
LOG_Y = ParameterSpec("log_y", "Log Y", "bool", False, group=BINS_GROUP,
                      tip="Logarithmic event axis; empty bins are left out.")
VALUES = ParameterSpec("units", "Units", "choice", COUNTS, choices=(COUNTS, RATE), group=BINS_GROUP,
                       tip="Counts per bin, or a rate per shot: counts / bin width / number of shots, T in kHz "
                           "per shot (counts per ms) and X and Y per mm per shot (the front panel's units, with "
                           "X and Y divided by the number of shots too).")
BOX = ParameterSpec("box_first", "Only events inside all three ranges", "bool", False, group=BINS_GROUP,
                    tip="Each histogram counts only the events inside the other two axes' ranges as well (the "
                        "box, as the front panel did): X and Y only from T's window, say. Off: each axis "
                        "counts every event in its own range.")
SMOOTH_GROUP = "Smoothing"
SMOOTH = ParameterSpec("smooth", "Smooth", "bool", False, group=SMOOTH_GROUP,
                       tip="Smooth each histogram with a Gaussian of σ, over bins of σ/5 (the front panel's "
                           "profiles). Fits still use the unsmoothed counts unless Fit to says otherwise.")
SMOOTH_T = ParameterSpec("smooth_t", "σ, T", "float", 1e-4, (1e-9, 10.0), " s", group=SMOOTH_GROUP,
                         when=(SMOOTH.name, "True"), si=True, unit_prefix="m",
                         tip="The smoothing Gaussian's σ along T.")
SMOOTH_XY = ParameterSpec("smooth_xy", "σ, X and Y", "float", 2e-4, (1e-9, 1.0), " m", group=SMOOTH_GROUP,
                          when=(SMOOTH.name, "True"), si=True, unit_prefix="m",
                          tip="The smoothing Gaussian's σ along X and Y.")
HIGHLIGHT, NEWEST_COLOUR = newest_specs(BINS_GROUP)

FITS_PAGE = FITS_GROUP = "Fits"
TEMPERATURE_TIP = ("The temperature is the ideal-gas, pure-expansion one (the initial cloud size is neglected): "
                   "σ_v = g σ along T, σ / t_f along X and Y, and T = m σ_v² / k_B, with the Constants below.")
FIT_SPECS: dict[str, tuple[ParameterSpec, ParameterSpec]] = {}
for _axis, _models, _extra in (
        ("T", T_MODELS, " Arrival-time thermal: the exact profile of atoms falling the fall distance with "
                        "Maxwell–Boltzmann vertical velocities (skewed, not a Gaussian), its centre the arrival "
                        "of v = 0. It uses g and the fall distance, or ½ g t_f² when the fall time is set by "
                        "hand (Constants), so that v = 0 arrives t_f after release."),
        ("X", XY_MODELS, ""), ("Y", XY_MODELS, "")):
    _toggle = ParameterSpec(f"fit_{_axis.lower()}", f"Fit {_axis}", "bool", False, group=FITS_GROUP, page=FITS_PAGE,
                            tip=f"Fit the {_axis} histogram: its centre, width and temperature ± SE, drawn over "
                                f"it. {TEMPERATURE_TIP}")
    FIT_SPECS[_axis] = (_toggle, ParameterSpec(
        f"fit_{_axis.lower()}_model", f"{_axis} model", "choice", _models[0], choices=_models, group=FITS_GROUP,
        page=FITS_PAGE, when=(_toggle.name, "True"),
        tip="Gaussian + offset; Bose g_5/2 or g_2 thermal; bimodal Thomas–Fermi (1 − u²)^p + Gaussian or Bose "
            "thermal with one centre, its temperature from the thermal σ and N0/N from the parts' areas (the "
            "title says \"no condensate (z = …)\" when the TF + Bose choices find none). " + TF_EXPONENT_TIP
            + _extra))
FIT_DATA = ParameterSpec("fit_data", "Fit to", "choice", UNSMOOTHED, choices=(UNSMOOTHED, SMOOTHED),
                         group=FITS_GROUP, page=FITS_PAGE, when=(SMOOTH.name, "True"),
                         tip="The unsmoothed counts (Poisson weights; the default), or the smoothed curve (as the "
                             "front panel did), with the same smoothing applied to the model: the results are "
                             "the unsmoothed profile's (no correction for the smoothing), and their SEs count "
                             "that smoothed bins share counts. Shown while Smooth is on; it applies to every fit.")
BEC = ParameterSpec(
    "bec_properties", "Show BEC properties", "bool", False, group=FITS_GROUP, page=FITS_PAGE,
    tip="From one axis's fit (BEC properties from): the atoms per shot N = events / shots / detector QE, N0 and "
        "N0/N from a bimodal fit's parts, T, Tc (ideal; with the finite-size shift; with interactions too), T/Tc, "
        "μ/k_B, the in-trap Thomas–Fermi radii R(0) and the peak density n0 from N0 and the trap, and two checks "
        "of the QE: the one the fitted R(0) implies (N0 ∝ R(0)⁵, no QE needed) and the one the saturated thermal "
        "cloud implies (ζ(3)(k_B T/ħω̄)³ atoms). Each ± its SE, from the fit's covariance (Poisson only: the "
        "constants' own uncertainty isn't in it). Constants still at a borrowed value (the QE, the trap "
        "frequencies) are flagged in amber. A slice fit (TF^3/2, g_2) gives only T and R(0). The record has "
        "every number and note.")
BEC_AXIS = ParameterSpec(
    "bec_axis", "BEC properties from", "choice", AUTO, choices=SOURCES, group=FITS_GROUP, page=FITS_PAGE,
    when=(BEC.name, "True"),
    tip="The fit the properties come from. auto: a fit that reports a condensate first, then a full projection "
        "over a slice, then an axis along a radial trap axis (T, unless Trap axial axis along says otherwise), "
        "then T, X, Y in order.")


def bec_constants_used(values: Mapping[str, Any]) -> bool:
    """Whether a run with ``values`` uses the trap's constants: some fit is on, and BEC properties
    are shown or a fitted axis has a bimodal model (its R/σ_th cap and, for TF + Bose, its condensate
    check use the trap, the QE and the scattering length)."""
    fitted = [str(values.get(model.name, model.default)) for toggle, model in FIT_SPECS.values()
              if values.get(toggle.name)]
    return bool(fitted) and (bool(values.get(BEC.name)) or any(choice in BIMODALS for choice in fitted))


# The fall distance and time (F0b's Constants group): the lab's or folder's, or this plot's own. X and
# Y temperatures use the fall time; the arrival-time model on T uses g and the effective fall
# distance, ½ g t_f² when the fall time is set by hand (else h), so its v = 0 arrives t_f after release.
# With BEC properties or a bimodal fit on, the trap's constants too (``bec_constants_used``).
FALL_KEYS = ("fall_distance", "fall_time")
BEC_OVERRIDES = ("detector_qe", "trap_radial", "trap_axial", "trap_axial_axis", "scattering_length")
CONSTANTS = [spec if spec.name.split(".")[1] in FALL_KEYS else replace(spec, shown_with=bec_constants_used)
             for spec in constants_specs((*FALL_KEYS, *BEC_OVERRIDES), page=FITS_PAGE)]
# What the fits use, so a lab or folder change of any of them marks the plot: always, and with
# ``bec_constants_used``, the trap's (``TxyHistograms.run_constant_keys``).
FIT_KEYS = ("fall_distance", "fall_time", "g", "mass", "k_B")
BEC_KEYS = ("detector_qe", "trap_radial", "trap_axial", "trap_axial_axis", "scattering_length", "hbar")
CONSTANT_KEYS = (*FIT_KEYS, *BEC_KEYS)
COLOUR = (40, 90, 170)
SMOOTH_COLOUR = (20, 50, 120)  # the smoothed curve, darker than the bars behind it
FIT_COLOUR = (0, 0, 0)
NOTE_COLOUR = AMBER  # notes and warnings: the app's amber
NEWEST_SIZE = 9  # the newest shot's marker in Counts per shot


class DecadeLogAxis(GroupedAxis):
    """The histograms' log Y axis: ``GroupedAxis``'s decade-only log ticks."""


@dataclass(frozen=True)
class ShotCounts:
    shots: npt.NDArray[np.int64]
    counts: npt.NDArray[np.int64]
    unsettled_files: int
    total_shots: int = 0  # the shots loaded (``shots`` are the chosen ones)
    newest_shot: int | None = None  # the highlighted newest shot (None: off)
    colour: tuple[int, int, int] = (214, 39, 40)
    masked: int = 0  # events the mask took out of the chosen shots

    @property
    def total(self) -> int:
        return int(self.counts.sum())


@dataclass(frozen=True)
class Histograms:
    items: tuple[Histogram, ...]
    shots: tuple[int, ...]
    total_shots: int
    reversed: tuple[str, ...] = ()  # axes whose manual min > max: shown over their full extent
    # The highlighted newest shot (None: off): its counts in each item's bins, drawn over them.
    newest_shot: int | None = None
    newest: tuple[npt.NDArray[np.int64], ...] = ()
    colour: tuple[int, int, int] = (214, 39, 40)
    units: str = COUNTS
    # Per item: what turns its counts into the values shown (1 for counts, ``rate_factor``).
    factors: tuple[float, ...] = ()
    # Per item, with smoothing on: the smoothed counts (per bin) and the σ (s or m); else empty.
    smoothed: tuple[npt.NDArray[np.float64], ...] = ()
    smoothing: tuple[float, ...] = ()
    # Per item: its fit (None: not fitted) and notes on its bins (widened for smoothing).
    fits: tuple[AxisFit | None, ...] = ()
    bin_notes: tuple[tuple[str, ...], ...] = ()
    box: bool = False  # each histogram counts only the events inside the other axes' ranges
    constants: ResolvedConstants | None = field(default=None, compare=False)
    masked: int = 0  # events the mask took out of the chosen shots
    bec: BecReadout | None = None  # with Show BEC properties on
    # The constants the run used (``TxyHistograms.run_constant_keys``): the header names these.
    constant_keys: tuple[str, ...] = FIT_KEYS

    def factor(self, index: int) -> float:
        return self.factors[index] if index < len(self.factors) else 1.0

    def fit(self, index: int) -> AxisFit | None:
        return self.fits[index] if index < len(self.fits) else None

    def fitted(self) -> bool:
        return any(fit is not None for fit in self.fits)

    def record(self) -> dict[str, Any]:
        """Strict JSON for the result's record: each fit's (``AxisFit.as_record``, with the
        ``FitResult``'s), the BEC properties (``BecReadout.as_record``) and, with any fit, the
        constants the run used (``as_record`` of ``constant_keys``)."""
        fits = {item.axis: fit.as_record() for item, fit in zip(self.items, self.fits) if fit is not None}
        record: dict[str, Any] = {"units": self.units, "box": self.box, "fits": fits,
                                  "smoothing": {item.axis: sigma for item, sigma in zip(self.items, self.smoothing)}}
        if self.bec is not None:
            record["bec"] = self.bec.as_record()
        if fits and self.constants is not None:
            # The keys the run used, as the result's own record (``AnalysisResult.constants_record``).
            record["constants"] = self.constants.as_record(self.constant_keys)
        record["record_lines"] = self.record_lines()
        return record

    def record_lines(self) -> list[str]:
        """For the dock's record: each fit (its numbers, reduced χ² and notes) and the notes on
        its bins, whole (the plot's titles show them without their details)."""
        lines = []
        for index, (item, fit) in enumerate(zip(self.items, self.fits)):
            bin_notes = self.bin_notes[index] if index < len(self.bin_notes) else ()
            if bin_notes:
                lines.append(f"{item.axis} bins: {'; '.join(bin_notes)}")
            if fit is None:
                continue
            chi2 = fit.fit.reduced_chi2
            extra = f" · reduced χ² {chi2:.3g}" if fit.ok and math.isfinite(chi2) else ""
            notes = f" · notes: {'; '.join(fit.notes)}" if fit.notes else ""
            lines.append(f"Fit {item.axis}: {fit.text()}{extra}{notes}")
        if self.bec is not None:
            lines += self.bec.record_lines()
        return lines  # The constants are in the record once, from the run (``AnalysisResult.describe``).


def counts_title(data: ShotCounts) -> str:
    title = (f"{shots_text(data.shots.tolist(), data.total_shots or len(data.shots))} · {data.total:,} events"
             f"{masked_text(data.masked)}")
    if data.unsettled_files:
        title += f" · {data.unsettled_files} files still being written left out"
    if data.newest_shot is not None:
        title += f" · shot {data.newest_shot} highlighted"
    return title


def histogram_title(item: Histogram, reversed_range: bool = False, how: str = "") -> str:
    """``T · 40 bins (set) · 1,000 of 1,020 events · 20 outside the range``; ``how`` says how the
    bins were chosen when not by the Bins setting (smoothing's σ/5). Automatic bins are "auto"
    (Freedman–Diaconis, as the Bins setting's tip says)."""
    bins = len(item.counts)
    how = how or ("auto" if item.automatic_bins else "set")
    title = f"{item.axis} · {bins:,} bins ({how}) · {item.total - item.outside:,} of {item.total:,} events"
    title += f" · {item.outside:,} outside the range" if item.outside else ""
    return title + (" · ⚠ min > max, using full extent" if reversed_range else "")


def source_title(result: AnalysisResult, text: str) -> str:
    return f"{result.input.short()} · {text}"


COUNTS_HIGHLIGHT, COUNTS_NEWEST_COLOUR = newest_specs("Plot")


class CountsPlot(pg.PlotWidget):  # type: ignore[misc]
    """Counts per shot, with the newest shot marked when highlighted; ``show_data`` draws a
    newer result in place (Live), keeping zoom and pan."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setBackground("w")
        plot: Any = self.getPlotItem()
        plot.setLabel("bottom", "Shot number")
        plot.setLabel("left", "Events")
        plot.showGrid(x=True, y=True, alpha=0.3)
        self.curve: Any = plot.plot([], [], pen=pg.mkPen(COLOUR, width=1), symbol="o", symbolSize=4,
                                    symbolBrush=COLOUR, symbolPen=None)
        self.newest: Any = plot.plot([], [], pen=None, symbol="o", symbolSize=NEWEST_SIZE, symbolPen=None)
        self.title: Any = set_plot_title(plot, "")

    def show_data(self, result: AnalysisResult, data: ShotCounts) -> None:
        set_plot_title(self.getPlotItem(), line_html(source_title(result, counts_title(data))))
        self.curve.setData(data.shots, data.counts)
        index = (np.flatnonzero(data.shots == data.newest_shot) if data.newest_shot is not None
                 else np.empty(0, dtype=np.intp))
        if len(index):
            self.newest.setData(data.shots[index], data.counts[index], symbolBrush=pg.mkBrush(data.colour))
        else:
            self.newest.setData([], [])


class CountsPerShot(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Counts per shot",
            description="Number of events in each loaded shot, against shot number",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.dld.counts_per_shot",
            version="1",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*SHOT_SPECS, *MASK_SPECS, COUNTS_HIGHLIGHT, COUNTS_NEWEST_COLOUR]

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        settings = (shots_brief(values), mask_brief(values), newest_brief(values))
        return selection_text(view, values), " · ".join(part for part in settings if part)

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        return list(mask_warnings(values))

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        chosen = select_shots(context.view, context.parameters)
        mask = mask_from(context.parameters)  # Circles that can't be read fail the run, saying which.
        if mask.active:
            shots, counts, masked = masked_counts_per_shot(context.view, chosen, mask)
        else:
            (shots, counts), masked = counts_per_shot(context.view, chosen), 0
        return ShotCounts(shots, counts, context.view.provenance.unsettled_files, len(context.view.shots),
                          newest_shot(context.parameters, chosen), newest_colour(context.parameters), masked)

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: ShotCounts = result.data
        if not data.total:
            # No shots, none chosen, or chosen shots without events: say which, not a flat line.
            if data.masked and len(data.shots):
                return empty_pane(all_masked_text(data.masked), parent)
            return empty_pane(empty_text(data.total_shots, len(data.shots), 0), parent)
        widget = CountsPlot(parent)
        widget.show_data(result, data)
        return cast(QWidget, widget)

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """Live's next shots go into the plot already drawn: zoom and pan stay."""
        data: ShotCounts = result.data
        if not isinstance(widget, CountsPlot) or not data.total:
            return False
        widget.show_data(result, data)
        return True


def _inside_others(events: npt.NDArray[np.float64], ranges: list[tuple[float, float] | None],
                   axis: int) -> npt.NDArray[np.bool_]:
    """The events inside every other axis's range (an axis without one keeps all)."""
    inside = np.ones(len(events), dtype=bool)
    for other, bounds in enumerate(ranges):
        if other != axis and bounds is not None:
            inside &= (events[:, other] >= bounds[0]) & (events[:, other] <= bounds[1])
    return inside


def fits_brief(values: Mapping[str, Any]) -> str:
    """``fit T arrival-time thermal, X Gaussian`` for the dock's settings line; "" without fits."""
    parts = [f"{axis} {values.get(model.name, model.default)}" for axis, (toggle, model) in FIT_SPECS.items()
             if values.get(toggle.name)]
    return f"fit {', '.join(parts)}" if parts else ""


HistogramsKey = tuple[bool, bool, bool, tuple[bool, ...], str]


def histograms_key(result: AnalysisResult, data: Histograms) -> HistogramsKey:
    """What a drawing's items are: log Y, smoothing, the newest shot, which axes are fitted and
    the units. A rerun with the same key draws in place; any other is drawn anew."""
    return (bool(result.parameters.get(LOG_Y.name, False)), bool(data.smoothed),
            data.newest_shot is not None and bool(data.newest), tuple(fit is not None for fit in data.fits),
            data.units)


def histograms_empty(data: Histograms) -> bool:
    return not data.items or not data.items[0].total


class HistogramsWidget(pg.GraphicsLayoutWidget):  # type: ignore[misc]
    """The header and one plot per axis, with their items, so a rerun (Live) sets their data in
    place, keeping zoom and pan (``show_data``); ``key`` (``histograms_key``) says what they are."""

    def __init__(self, key: HistogramsKey, axes: tuple[str, ...], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setBackground("w")
        self.key = key
        log_y, smoothing, highlighted, fitted, _ = key
        layout: Any = self.ci  # (The widget passes addLabel and addPlot to it.)
        self.header = add_label(layout, row=0, col=0)
        self.plots: list[Any] = []
        self.bars: list[Any] = []
        self.curves: list[Any] = []  # smoothed curves (with smoothing)
        self.fit_lines: list[Any] = []  # fit lines (None where that axis isn't fitted)
        self.scaled: list[Any] = []  # the newest shot at the histogram's scale, transparent (highlight)
        self.newest_views: list[OverlayView] = []  # Kept with the widget (they live in its scene).
        # With smoothing, the bars are faint behind the smoothed curve.
        pen, brush = (pg.mkPen((*COLOUR, 45)), (*COLOUR, 30)) if smoothing else (pg.mkPen(COLOUR), (*COLOUR, 90))
        for row, axis in enumerate(axes, start=1):
            # A right axis only for the newest shot's counts (pyqtgraph shows any axis it is given).
            items: dict[str, Any] = {"bottom": GroupedAxis("bottom")}
            if log_y:
                items.update({"left": DecadeLogAxis("left"), **({"right": DecadeLogAxis("right")} if highlighted else {})})
            plot = layout.addPlot(row=row, col=0, axisItems=items)
            set_plot_title(plot, "")
            plot.setLabel("bottom", axis_label(axis))
            if log_y:
                # Empty bins have no logarithm: they are left out of the bars.
                plot.setLogMode(x=False, y=True)
                bars = pg.PlotDataItem([0.0, 1.0], [np.nan], stepMode="center", connect="finite", pen=pen)
            else:
                bars = pg.PlotDataItem([0.0, 1.0], [0.0], stepMode="center", fillLevel=0, pen=pen, brush=brush)
            plot.addItem(bars)
            self.bars.append(bars)
            if smoothing:
                curve = pg.PlotDataItem([], [], connect="finite", pen=pg.mkPen(SMOOTH_COLOUR, width=2))
                plot.addItem(curve)
                self.curves.append(curve)
            line = None
            if row - 1 < len(fitted) and fitted[row - 1]:
                line = pg.PlotDataItem([], [], connect="finite", pen=pg.mkPen(FIT_COLOUR, width=2))
                plot.addItem(line)
            self.fit_lines.append(line)
            if highlighted:
                # One shot is a small share of all: drawn to the histogram's scale (its total over
                # the shot's), its shape compares; its own axis on the right reads its real counts.
                left = plot.getAxis("left")
                left.setPen(pg.mkPen(COLOUR))
                left.setTextPen(pg.mkPen(COLOUR))
                # The scaled line, transparent (hidden items don't count), keeps the plot's own
                # range (and its Auto) holding the overlay.
                scaled = pg.PlotDataItem([0.0, 1.0], [np.nan], stepMode="center", connect="finite",
                                         pen=pg.mkPen((0, 0, 0, 0)))
                plot.addItem(scaled)
                self.scaled.append(scaled)
            self.plots.append(plot)

    def show_data(self, result: AnalysisResult, data: Histograms) -> None:
        log_y, smoothing, highlighted, _, _ = self.key
        items = data.items
        events = f"{items[0].total:,} events"
        newest = (f" · shot {data.newest_shot} highlighted ({int(data.newest[0].sum()):,} in range, right axis)"
                  if highlighted else "")
        header = line_html(source_title(result, f"{shots_text(data.shots, data.total_shots)} · {events}"
                                                f"{masked_text(data.masked)}{newest}"))
        if data.fitted() and data.constants is not None:
            # Only the values not at their defaults (the record has them all), so the header stays short.
            used = describe_constants(data.constants, data.constant_keys)
            header += "<br>" + line_html(f"Fits with {used}" if used else "Fits with the default constants")
            header += notes_html(data.constants.notes)
        if data.bec is not None:  # The compact block (it wraps); every number and note is in the record.
            header += "<br>" + lines_html(data.bec.title_lines()) + notes_html(data.bec.warnings(), short=True)
        self.header.setText(header)
        for index, (item, plot) in enumerate(zip(items, self.plots)):
            x_factor = axis_scale(item.axis)
            sigma = data.smoothing[index] if index < len(data.smoothing) else None
            how = f"σ/5 for smoothing σ {axis_text(item.axis, sigma, WIDTH_DIGITS)}" if sigma is not None else ""
            title = line_html(histogram_title(item, item.axis in data.reversed, how))
            fit = data.fit(index)
            notes: list[str] = list(data.bin_notes[index]) if index < len(data.bin_notes) else []
            if fit is not None and fit.ok:
                title += "<br>" + line_html(fit.text())
                # The decision when it found or ruled out a condensate is the fit line's (the record
                # has why); a "possible condensate … not reported: why" stays, in amber.
                notes = [*(note for note in fit.notes if not note.startswith((CONDENSATE, NO_CONDENSATE))), *notes]
            elif fit is not None:  # Why there is no fit, in amber.
                notes = [fit.text(), *fit.notes, *notes]
            # One note per line, without their details (the dock's record has them whole).
            set_plot_title(plot, title + notes_html(notes, short=True))
            plot.setLabel("left", value_label(item.axis, data.units))
            edges = item.edges * x_factor
            y_factor = data.factor(index)
            shown = item.counts.astype(np.float64) * y_factor
            self.bars[index].setData(edges, np.where(shown > 0, shown, np.nan) if log_y else shown)
            centres = (edges[:-1] + edges[1:]) / 2
            if smoothing and index < len(self.curves):
                smoothed = data.smoothed[index] * y_factor
                self.curves[index].setData(centres, np.where(smoothed > 0, smoothed, np.nan) if log_y else smoothed)
            line = self.fit_lines[index]
            if line is not None:
                if fit is not None and fit.ok and len(fit.x):
                    values = fit.y * y_factor
                    line.setData(fit.x * x_factor, np.where(values > 0, values, np.nan) if log_y else values)
                else:
                    line.setData([], [])
            if not highlighted or index >= len(data.newest):
                continue
            plot.setLabel("left", value_label(item.axis, data.units, every=True), color=pg.mkColor(COLOUR).name())
            counts_new = data.newest[index]
            scale = float(shown.sum()) / float(counts_new.sum()) if counts_new.sum() > 0 else 1.0
            scaled = counts_new * scale
            self.scaled[index].setData(edges, np.where(scaled > 0, scaled, np.nan) if log_y else scaled)
            name = f"shot {data.newest_shot}"
            if index < len(self.newest_views):
                update_newest(plot, self.newest_views[index], edges, counts_new, scale, data.colour, log_y, name)
            else:
                self.newest_views.append(overlay_newest(plot, edges, counts_new, scale, data.colour, log_y, name))


class TxyHistograms(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="T, X, Y histograms",
            description="Distributions of the loaded events' T, X and Y, with optional fits and temperatures",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.dld.txy_histograms",
            version="1",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        fits = [spec for pair in FIT_SPECS.values() for spec in pair]
        return [*SHOT_SPECS, *RANGE, *MASK_SPECS, BINS, LOG_Y, VALUES, BOX, HIGHLIGHT, NEWEST_COLOUR, SMOOTH, SMOOTH_T, SMOOTH_XY,
                *fits, FIT_DATA, BEC, BEC_AXIS, *CONSTANTS]

    def constant_keys(self, action_name: str) -> tuple[str, ...]:
        return CONSTANT_KEYS

    def run_constant_keys(self, action_name: str, values: Mapping[str, Any]) -> tuple[str, ...]:
        """The fits' constants, and the trap's only while BEC properties or a bimodal fit use them."""
        return CONSTANT_KEYS if bec_constants_used(values) else FIT_KEYS

    def run_constants(self, action_name: str, values: Mapping[str, Any],
                      layers: Mapping[str, Mapping[str, float]]) -> ResolvedConstants | None:
        """The constants the fits use; None when no fit is on (the histograms alone use none, so
        they are neither keyed on constants nor marked when one changes)."""
        if not any(values.get(toggle.name) for toggle, _ in FIT_SPECS.values()):
            return None
        return resolve_for_run(values, layers.get("lab"), layers.get("folder"))

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        bins = int(values[BINS.name])
        smoothing = bool(values.get(SMOOTH.name))
        fitted = fits_brief(values)
        settings = (shots_brief(values), range_brief(values, fixed=True), mask_brief(values),
                    "" if smoothing else (f"bins {bins:,}" if bins else "bins auto"),
                    f"smoothed σ {axis_text('T', float(values[SMOOTH_T.name]), WIDTH_DIGITS)} / "
                    f"{axis_text('X', float(values[SMOOTH_XY.name]), WIDTH_DIGITS)}" if smoothing else "",
                    RATE if values.get(VALUES.name) == RATE else "", "box" if values.get(BOX.name) else "",
                    "log Y" if values[LOG_Y.name] else "", newest_brief(values), fitted,
                    "on the smoothed curve" if fitted and smoothing and values.get(FIT_DATA.name) == SMOOTHED else "",
                    f"BEC properties ({values.get(BEC_AXIS.name, AUTO)})" if values.get(BEC.name) else "")
        return selection_text(view, values), " · ".join(part for part in settings if part)

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        warnings = [*range_warnings(values), *mask_warnings(values)]
        if values.get(BEC.name) and not any(values.get(toggle.name) for toggle, _ in FIT_SPECS.values()):
            warnings.append("BEC properties need a fit: turn on Fit T, X or Y")
        return warnings

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        values = context.parameters
        shots = select_shots(context.view, values)
        mask = mask_from(values)  # Circles that can't be read fail the run, saying which.
        events, masked = mask.apply(context.view.events(shots))
        keep = keep_fraction(values)
        bins = int(values[BINS.name])
        is_manual = manual(values)
        bounds = manual_bounds(values) if is_manual else (None,) * len(AXES)
        box = bool(values.get(BOX.name, False))
        units = str(values.get(VALUES.name, COUNTS))
        smoothing = bool(values.get(SMOOTH.name, False))
        on_smoothed = smoothing and values.get(FIT_DATA.name) == SMOOTHED
        newest = newest_shot(values, shots)
        fresh = mask.apply(newest_events(context.view, newest))[0]
        constants = context.resolved_constants
        if constants is None:  # Run without the runner (or no fit on): resolved here, the same way.
            constants = resolve_for_run(values, context.constants.get("lab"), context.constants.get("folder"))
        # Each axis's range first (the manual bounds, its full extent, or auto-crop's shortest
        # range): with the box on, every histogram counts only events inside the others' ranges.
        ranges: list[tuple[float, float] | None] = []
        for i in range(len(AXES)):
            context.check()
            column = events[:, i]
            given = bounds[i]
            if given is None and len(column):
                given = (float(column.min()), float(column.max())) if is_manual else shortest_range(column, keep)
            ranges.append(given)
        items, newest_counts, factors, smoothed, sigmas, bin_notes = [], [], [], [], [], []
        fits: list[AxisFit | None] = []
        for i, axis in enumerate(AXES):
            context.check()
            column, fresh_column = events[:, i], fresh[:, i]
            if box:
                column, fresh_column = column[_inside_others(events, ranges, i)], \
                    fresh_column[_inside_others(fresh, ranges, i)]
            sigma = float(values[(SMOOTH_T if axis == "T" else SMOOTH_XY).name]) if smoothing else None
            count, note = bins, ""
            if sigma is not None and ranges[i] is not None:
                count, note = smoothing_bins(*cast(tuple[float, float], ranges[i]), sigma, axis)
            item = histogram(np.ascontiguousarray(column), axis, keep, count, ranges[i])
            items.append(item)
            bin_notes.append((note,) if note else ())
            width = float(item.edges[1] - item.edges[0])
            factors.append(rate_factor(width, len(shots)) if units == RATE else 1.0)
            if sigma is not None:
                smoothed.append(smooth(item.counts, sigma / width))
                sigmas.append(sigma)
            if newest is not None:
                newest_counts.append(np.histogram(fresh_column, bins=item.edges)[0].astype(np.int64))
            toggle, model = FIT_SPECS[axis]
            if values.get(toggle.name):
                context.check()
                # The shots the histogram sums: the condensate decision's μ/k_BT check needs them.
                fits.append(fit_axis(axis, item.edges, item.counts, str(values.get(model.name, model.default)),
                                     constants, smoothing=sigma if on_smoothed else None, shots=len(shots)))
            else:
                fits.append(None)
        bec = None
        if values.get(BEC.name):
            context.check()
            bec = readout(fits, AXES, [float(np.mean(np.diff(item.edges))) for item in items], len(shots), constants,
                          str(values.get(BEC_AXIS.name, AUTO)))
        return Histograms(tuple(items), shots, len(context.view.shots), reversed_axes(values), newest,
                          tuple(newest_counts), newest_colour(values), units, tuple(factors), tuple(smoothed),
                          tuple(sigmas), tuple(fits), tuple(bin_notes), box, constants, masked, bec,
                          self.run_constant_keys(action_name, values))

    def result_found(self, action_name: str, data: Any) -> dict[str, Any]:
        """With any fit: ``Histograms.record()`` (each fit's record and the constants used),
        whose ``record_lines`` the dock's record shows."""
        return data.record() if isinstance(data, Histograms) and (data.fitted() or data.bec is not None) else {}

    def live_policy(self, action_name: str) -> LivePolicy:
        # Measured on 294k events (D4 wiring, whole compute): Gaussian fits on three axes 0.3 s, a
        # bimodal TF + Bose fit 0.6–2.4 s per axis (it fits the free-z partner too; slowest on a
        # thermal axis), 2.0 s with one and 3.3 s with three, the BEC readout ~2 ms. A run is never
        # cancelled for new data and the analysis worker is shared, so 2 s apart, as the other heavy
        # plots (the policy is per plot, fits on or off; its Live settings can lower it).
        return LivePolicy(min_delay=2.0)

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: Histograms = result.data
        if histograms_empty(data):
            if data.masked and data.shots:
                return empty_pane(all_masked_text(data.masked), parent)
            return empty_pane(empty_text(data.total_shots, len(data.shots), 0), parent)
        widget = HistogramsWidget(histograms_key(result, data), tuple(item.axis for item in data.items), parent)
        widget.show_data(result, data)
        return cast(QWidget, widget)

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """A rerun (e.g. Live's next shots) sets the plots' data in place, keeping zoom and pan,
        while log Y, smoothing, the newest shot, the fits and the units stay; otherwise anew."""
        data: Histograms = result.data
        if (not isinstance(widget, HistogramsWidget) or histograms_empty(data)
                or widget.key != histograms_key(result, data) or len(widget.plots) != len(data.items)):
            return False
        widget.show_data(result, data)
        return True
