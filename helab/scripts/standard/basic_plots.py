"""Counts per shot and T/X/Y histograms of a loaded folder (PyQtGraph: native Qt drawing,
fast to redraw when Live adds shots, and painted on lab PCs that can't paint QtWebEngine).

The histograms show X and Y in mm and T in ms (``display_units``), as counts or
a rate per shot, optionally smoothed, and can fit each axis (D1: off by default, so the plot
stays fast) for its centre, width and temperature (``helab.analysis.profiles``)."""
from __future__ import annotations

import html
import math
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, cast

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PyQt6.QtCore import QRectF, pyqtSlot
from PyQt6.QtWidgets import QWidget

from helab.analysis.constant_layers import constants_specs, describe_constants, resolve_for_run
from helab.analysis.display_units import WIDTH_DIGITS, axis_label, axis_scale, axis_text
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.parameters import ParameterSpec
from helab.analysis.physics import ResolvedConstants
from helab.analysis.plot_axes import GroupedAxis
from helab.analysis.profiles import (COUNTS, RATE, SMOOTHED, T_MODELS, TF_EXPONENT_TIP, UNSMOOTHED, XY_MODELS,
                                     AxisFit, fit_axis, rate_factor, smooth, smoothing_bins, value_label)
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.dataset_view import DatasetView
from helab.analysis.selection import (SHOT_SPECS, keep_fraction, manual, manual_bounds, newest_brief, newest_colour,
                                      newest_events, newest_shot, newest_specs, range_brief, range_specs,
                                      range_warnings, reversed_axes, select_shots, selection_text, shots_brief,
                                      shots_text)
from helab.analysis.stats import AXES, MAX_BINS, Histogram, counts_per_shot, histogram, shortest_range
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.standard import group

RANGE = range_specs(
    "Each histogram covers the exact shortest range holding this share of its axis's events. "
    "100 % covers every event.")
BINS_GROUP = "Histogram"
BINS = ParameterSpec(
    "bins", "Bins", "int", 0, (0, MAX_BINS), "", group=BINS_GROUP,
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
        tip="Gaussian + offset; bimodal Thomas–Fermi (1 − u²)^p + Gaussian with one centre, its temperature from "
            "the thermal σ (the condensate fraction is the BEC fit's, later). " + TF_EXPONENT_TIP + _extra))
FIT_DATA = ParameterSpec("fit_data", "Fit to", "choice", UNSMOOTHED, choices=(UNSMOOTHED, SMOOTHED),
                         group=FITS_GROUP, page=FITS_PAGE, when=(SMOOTH.name, "True"),
                         tip="The unsmoothed counts (Poisson weights; the default), or the smoothed curve (as the "
                             "front panel did), with the same smoothing applied to the model: the results are "
                             "the unsmoothed profile's (no correction for the smoothing), and their SEs count "
                             "that smoothed bins share counts. Shown while Smooth is on; it applies to every fit.")
# The fall distance and time (F0b's Constants group): the lab's or folder's, or this plot's own. X and
# Y temperatures use the fall time; the arrival-time model on T uses g and the effective fall
# distance, ½ g t_f² when the fall time is set by hand (else h), so its v = 0 arrives t_f after release.
CONSTANTS = constants_specs(("fall_distance", "fall_time"), page=FITS_PAGE)
# What the fits use, so a lab or folder change of any of them marks the plot.
CONSTANT_KEYS = ("fall_distance", "fall_time", "g", "mass", "k_B")
COLOUR = (40, 90, 170)
SMOOTH_COLOUR = (20, 50, 120)  # the smoothed curve, darker than the bars behind it
FIT_COLOUR = (0, 0, 0)
NOTE_COLOUR = "#b06000"  # amber, as Transfer fractions' notes


class DecadeLogAxis(GroupedAxis):
    """The histograms' log Y axis: ``GroupedAxis``'s decade-only log ticks."""


class OverlayView(pg.ViewBox):  # type: ignore[misc]
    """A view drawn over a plot (``source``, its ViewBox) that leaves the mouse to the plot below
    (its zoom, pan and menu): it only follows the plot's geometry and ranges, its y range the
    plot's divided by ``ratio`` (log Y: shifted by log10 of it). ``follow`` is a Qt slot, so
    the plot's signals hold no Python reference to it and Qt ends the connections when either
    is destroyed: nothing outlives the widget."""

    def __init__(self, source: Any, ratio: float, log_y: bool) -> None:
        super().__init__(enableMenu=False)
        self.setMouseEnabled(x=False, y=False)  # Wheel events then pass to the plot below.
        # (Not ``scale``: that is QGraphicsItem.scale(), which Qt and pyqtgraph call.)
        self._source, self._ratio, self._log_y = source, ratio, log_y
        self._shift = math.log10(ratio) if log_y and ratio > 0 else 0.0
        source.sigResized.connect(self.follow)
        source.sigYRangeChanged.connect(self.follow)

    @pyqtSlot()
    def follow(self) -> None:
        source = self._source
        # The plot's exact geometry (its scene bounding rect is half a pixel larger, which shifts
        # the x link, mapped by pixel, by a pixel where rounding differs).
        self.setGeometry(QRectF(source.scenePos(), source.size()))
        self.linkedViewChanged(source, self.XAxis)  # The x link maps by pixel: again at the new size.
        low, high = source.viewRange()[1]
        if self._log_y:
            self.setYRange(low - self._shift, high - self._shift, padding=0)
        else:
            self.setYRange(low / self._ratio, high / self._ratio, padding=0)

    def mouseDragEvent(self, ev: Any, axis: Any = None) -> None:
        ev.ignore()

    def mouseClickEvent(self, ev: Any) -> None:
        ev.ignore()


def overlay_newest(plot: Any, edges: npt.NDArray[np.float64], counts: npt.NDArray[np.int64], scale: float,
                   colour: tuple[int, int, int], log_y: bool, name: str) -> OverlayView:
    """The newest shot's real counts over ``plot`` in a view of their own, linked on x, with the
    right axis (in ``colour``) reading them. Its y range follows the plot's divided by ``scale``
    (the histogram's total over the shot's; with log Y, shifted by log10 of it), so the line sits
    where the shot's histogram scaled to the same total would."""
    view = OverlayView(plot.vb, scale, log_y)
    plot.scene().addItem(view)
    axis = plot.getAxis("right")
    plot.showAxis("right")
    axis.linkToView(view)
    view.setXLink(plot.vb)
    hex_colour = pg.mkColor(colour).name()
    axis.setPen(pg.mkPen(colour))
    axis.setTextPen(pg.mkPen(colour))
    plot.setLabel("right", f"{name} events", color=hex_colour)
    values = counts.astype(np.float64)
    if log_y:
        values[values <= 0] = np.nan
    curve = pg.PlotDataItem(edges, values, stepMode="center", connect="finite", pen=pg.mkPen(colour, width=2),
                            name=name)
    if log_y:
        curve.setLogMode(False, True)
    view.addItem(curve)
    view.follow()
    return view


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

    def factor(self, index: int) -> float:
        return self.factors[index] if index < len(self.factors) else 1.0

    def fit(self, index: int) -> AxisFit | None:
        return self.fits[index] if index < len(self.fits) else None

    def fitted(self) -> bool:
        return any(fit is not None for fit in self.fits)

    def record(self) -> dict[str, Any]:
        """Strict JSON for the result's record: each fit's (``AxisFit.as_record``, with the
        ``FitResult``'s) and, with any fit, the constants the run used (``as_record``)."""
        fits = {item.axis: fit.as_record() for item, fit in zip(self.items, self.fits) if fit is not None}
        record: dict[str, Any] = {"units": self.units, "box": self.box, "fits": fits,
                                  "smoothing": {item.axis: sigma for item, sigma in zip(self.items, self.smoothing)}}
        if fits and self.constants is not None:
            record["constants"] = self.constants.as_record()
        record["record_lines"] = self.record_lines()
        return record

    def record_lines(self) -> list[str]:
        """For the dock's record: each fit (its numbers, reduced χ² and notes)."""
        lines = []
        for item, fit in zip(self.items, self.fits):
            if fit is None:
                continue
            chi2 = fit.fit.reduced_chi2
            extra = f" · reduced χ² {chi2:.3g}" if fit.ok and math.isfinite(chi2) else ""
            notes = f" · notes: {'; '.join(fit.notes)}" if fit.notes else ""
            lines.append(f"Fit {item.axis}: {fit.text()}{extra}{notes}")
        return lines  # The constants are in the record once, from the run (``AnalysisResult.describe``).


def counts_title(data: ShotCounts) -> str:
    title = f"{shots_text(data.shots.tolist(), data.total_shots or len(data.shots))} · {data.total:,} events"
    if data.unsettled_files:
        title += f" · {data.unsettled_files} files still being written left out"
    return title


def histogram_title(item: Histogram, reversed_range: bool = False, how: str = "") -> str:
    """``T · 40 bins (set) · 1,000 of 1,020 events · 20 outside the range``; ``how`` says how the
    bins were chosen when not by the Bins setting (smoothing's σ/5)."""
    bins = len(item.counts)
    how = how or ("automatic, Freedman–Diaconis" if item.automatic_bins else "set")
    title = f"{item.axis} · {bins:,} bins ({how}) · {item.total - item.outside:,} of {item.total:,} events"
    title += f" · {item.outside:,} outside the range" if item.outside else ""
    return title + (" · ⚠ min > max, using full extent" if reversed_range else "")


def source_title(result: AnalysisResult, text: str) -> str:
    return f"{result.input.short()} · {text}"


class CountsPerShot(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Counts per shot",
            description="Number of events in each loaded shot, against shot number",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.counts_per_shot",
            version="2",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*SHOT_SPECS]

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        return selection_text(view, values), shots_brief(values)

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        chosen = select_shots(context.view, context.parameters)
        shots, counts = counts_per_shot(context.view, chosen)
        return ShotCounts(shots, counts, context.view.provenance.unsettled_files, len(context.view.shots))

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: ShotCounts = result.data
        if not data.total:
            # No shots, none chosen, or chosen shots without events: say which, not a flat line.
            return empty_pane(empty_text(data.total_shots, len(data.shots), 0), parent)
        plot: Any = pg.PlotWidget(parent)
        plot.setBackground("w")
        plot.setTitle(source_title(result, counts_title(data)))
        plot.setLabel("bottom", "Shot number")
        plot.setLabel("left", "Events")
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.plot(data.shots, data.counts, pen=pg.mkPen(COLOUR, width=1),
                  symbol="o", symbolSize=4, symbolBrush=COLOUR, symbolPen=None)
        return cast(QWidget, plot)


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


def notes_html(notes: Any) -> str:
    """Notes in amber, escaped, on a line of their own ("" for none)."""
    text = " · ".join(str(note) for note in notes if note)
    return f'<br><span style="color: {NOTE_COLOUR}">{html.escape(text)}</span>' if text else ""


class TxyHistograms(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="T, X, Y histograms",
            description="Distributions of the loaded events' T, X and Y, with optional fits and temperatures",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.txy_histograms",
            version="5",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        fits = [spec for pair in FIT_SPECS.values() for spec in pair]
        return [*SHOT_SPECS, *RANGE, BINS, LOG_Y, VALUES, BOX, HIGHLIGHT, NEWEST_COLOUR, SMOOTH, SMOOTH_T, SMOOTH_XY,
                *fits, FIT_DATA, *CONSTANTS]

    def constant_keys(self, action_name: str) -> tuple[str, ...]:
        return CONSTANT_KEYS

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
        settings = (shots_brief(values), range_brief(values),
                    "" if smoothing else (f"bins {bins:,}" if bins else "bins auto"),
                    f"smoothed σ {axis_text('T', float(values[SMOOTH_T.name]), WIDTH_DIGITS)} / "
                    f"{axis_text('X', float(values[SMOOTH_XY.name]), WIDTH_DIGITS)}" if smoothing else "",
                    RATE if values.get(VALUES.name) == RATE else "", "box" if values.get(BOX.name) else "",
                    "log Y" if values[LOG_Y.name] else "", newest_brief(values), fitted,
                    "on the smoothed curve" if fitted and smoothing and values.get(FIT_DATA.name) == SMOOTHED else "")
        return selection_text(view, values), " · ".join(part for part in settings if part)

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        return list(range_warnings(values))

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        values = context.parameters
        shots = select_shots(context.view, values)
        events = context.view.events(shots)
        keep = keep_fraction(values)
        bins = int(values[BINS.name])
        is_manual = manual(values)
        bounds = manual_bounds(values) if is_manual else (None,) * len(AXES)
        box = bool(values.get(BOX.name, False))
        units = str(values.get(VALUES.name, COUNTS))
        smoothing = bool(values.get(SMOOTH.name, False))
        on_smoothed = smoothing and values.get(FIT_DATA.name) == SMOOTHED
        newest = newest_shot(values, shots)
        fresh = newest_events(context.view, newest)
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
                fits.append(fit_axis(axis, item.edges, item.counts, str(values.get(model.name, model.default)),
                                     constants, smoothing=sigma if on_smoothed else None))
            else:
                fits.append(None)
        return Histograms(tuple(items), shots, len(context.view.shots), reversed_axes(values), newest,
                          tuple(newest_counts), newest_colour(values), units, tuple(factors), tuple(smoothed),
                          tuple(sigmas), tuple(fits), tuple(bin_notes), box, constants)

    def result_found(self, action_name: str, data: Any) -> dict[str, Any]:
        """With any fit: ``Histograms.record()`` (each fit's record and the constants used),
        whose ``record_lines`` the dock's record shows."""
        return data.record() if isinstance(data, Histograms) and data.fitted() else {}

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: Histograms = result.data
        items = data.items
        if not items or not items[0].total:
            return empty_pane(empty_text(data.total_shots, len(data.shots), 0), parent)
        log_y = bool(result.parameters.get(LOG_Y.name, False))
        widget: Any = pg.GraphicsLayoutWidget(parent)
        widget.setBackground("w")
        events = f"{items[0].total:,} events" if items else ""
        newest = (f" · shot {data.newest_shot} highlighted ({int(data.newest[0].sum()):,} in range, right axis)"
                  if data.newest_shot is not None and data.newest else "")
        header = html.escape(source_title(result, f"{shots_text(data.shots, data.total_shots)} · {events}{newest}"))
        if data.fitted() and data.constants is not None:
            # Only the values not at their defaults (the record has them all), so the header stays short.
            used = describe_constants(data.constants, CONSTANT_KEYS)
            header += f"<br>Fits with {html.escape(used)}" if used else "<br>Fits with the default constants"
            header += notes_html(data.constants.notes)
        widget.addLabel(header, row=0, col=0)
        overlays = []
        for row, item in enumerate(items, start=1):
            index = row - 1
            highlighted = data.newest_shot is not None and index < len(data.newest)
            # A right axis only for the newest shot's counts (pyqtgraph shows any axis it is given).
            axes: dict[str, Any] = {"bottom": GroupedAxis("bottom")}
            if log_y:
                axes.update({"left": DecadeLogAxis("left"), **({"right": DecadeLogAxis("right")} if highlighted else {})})
            x_factor = axis_scale(item.axis)
            sigma = data.smoothing[index] if index < len(data.smoothing) else None
            how = (f"σ/5 for smoothing σ {axis_text(item.axis, sigma, WIDTH_DIGITS)}"
                   if sigma is not None else "")
            title = html.escape(histogram_title(item, item.axis in data.reversed, how))
            fit = data.fit(index)
            notes: list[str] = list(data.bin_notes[index]) if index < len(data.bin_notes) else []
            if fit is not None and fit.ok:
                title += "<br>" + html.escape(fit.text())
                notes = [*fit.notes, *notes]
            elif fit is not None:  # Why there is no fit, in amber.
                notes = [fit.text(), *fit.notes, *notes]
            title += notes_html(notes)
            plot = widget.addPlot(row=row, col=0, title=title, axisItems=axes)
            plot.setLabel("bottom", axis_label(item.axis))
            label = value_label(item.axis, data.units)
            plot.setLabel("left", label)
            edges = item.edges * x_factor
            y_factor = data.factor(index)
            shown = item.counts.astype(np.float64) * y_factor
            smoothed = data.smoothed[index] * y_factor if sigma is not None else None
            # With smoothing, the bars are faint behind the smoothed curve.
            pen, brush = (pg.mkPen((*COLOUR, 45)), (*COLOUR, 30)) if smoothed is not None else \
                (pg.mkPen(COLOUR), (*COLOUR, 90))
            if log_y:
                # Empty bins have no logarithm: they are left out of the bars.
                bars = np.where(shown > 0, shown, np.nan)
                plot.setLogMode(x=False, y=True)
                plot.addItem(pg.PlotDataItem(edges, bars, stepMode="center", connect="finite", pen=pen))
            else:
                plot.addItem(pg.PlotDataItem(edges, shown, stepMode="center", fillLevel=0, pen=pen, brush=brush))
            centres = (edges[:-1] + edges[1:]) / 2
            if smoothed is not None:
                curve = np.where(smoothed > 0, smoothed, np.nan) if log_y else smoothed
                plot.addItem(pg.PlotDataItem(centres, curve, connect="finite", pen=pg.mkPen(SMOOTH_COLOUR, width=2)))
            if fit is not None and fit.ok and len(fit.x):
                line = fit.y * y_factor
                if log_y:
                    line = np.where(line > 0, line, np.nan)
                plot.addItem(pg.PlotDataItem(fit.x * x_factor, line, connect="finite",
                                             pen=pg.mkPen(FIT_COLOUR, width=2)))
            if highlighted:
                # One shot is a small share of all: drawn to the histogram's scale (its total over
                # the shot's), its shape compares; its own axis on the right reads its real counts.
                left = plot.getAxis("left")
                left.setPen(pg.mkPen(COLOUR))
                left.setTextPen(pg.mkPen(COLOUR))
                plot.setLabel("left", value_label(item.axis, data.units, every=True),
                              color=pg.mkColor(COLOUR).name())
                counts_new = data.newest[index]
                scale = float(shown.sum()) / float(counts_new.sum()) if counts_new.sum() > 0 else 1.0
                # The scaled line, transparent (hidden items don't count), keeps the plot's own range
                # (and its Auto) holding the overlay.
                scaled = counts_new * scale
                if log_y:
                    scaled = np.where(scaled > 0, scaled, np.nan)
                plot.addItem(pg.PlotDataItem(edges, scaled, stepMode="center", connect="finite",
                                             pen=pg.mkPen((0, 0, 0, 0))))
                overlays.append(overlay_newest(plot, edges, counts_new, scale, data.colour, log_y,
                                               f"shot {data.newest_shot}"))
        widget.newest_views = overlays  # Kept with the widget (they live in its scene).
        return cast(QWidget, widget)
