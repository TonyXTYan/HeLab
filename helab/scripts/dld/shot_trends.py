"""Shot trends (D2): per shot, its events in the plot's View range and its centre and width (and,
when shown, temperature) along T, X and Y, against shot number or shot time, with a moving
mean ± SD band; low-count shots in amber (PyQtGraph).

- **Counts** are the events inside the View range's box (all three axes). Auto-crop's range is
  rounded out to a twentieth of its width and kept while the events stay inside it
  (``trends.ShotCache.stable_range``), so it stays put while Live adds shots and their per-shot
  results are reused (``trends.CACHE``).
- **Centre and width** per shot and axis: a Gaussian fit (± SE) or threshold edges (the legacy
  ``find_dist_cen``: the outermost crossings of a fraction of the peak), ``helab.analysis.trends``.
  Temperatures are the histograms' (``physics``: σ_v = g σ along T, σ / t_f along X and Y), with
  the run's constants.
- **Low counts** (roadmaps/dld-front-panel-port.md, Decided): fewer than a count and/or below a
  fraction of the last N shots' mean, each a checkbox (50 and 50 % proposed, N = 100). With
  **Notify during Live** on, a newest shot that Live just added and that is low sends one
  desktop notification through ``helab.utils.events`` (once per shot, rate limited), never for
  shots shown before or outside Live.
- Units: T in ms, X and Y in mm (``display_units``), ticks grouped by thousands (``GroupedAxis``).
"""
from __future__ import annotations

import html
import math
from dataclasses import dataclass, field, replace
from typing import Any, List, Mapping, Optional, cast

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PyQt6.QtCore import pyqtSlot
from PyQt6.QtWidgets import QWidget

from helab.analysis import trends
from helab.analysis.constant_layers import constants_specs, describe_constants, resolve_for_run
from helab.analysis.dataset_view import DatasetView, ViewIdentity, txy
from helab.analysis.display_units import WIDTH_DIGITS, axis_scale, axis_text, axis_unit, number_text, range_text
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.estimates import Estimate
from helab.analysis.masks import MASK_SPECS, Mask, all_masked_text, mask_brief, mask_from, mask_warnings
from helab.analysis.parameters import ParameterSpec
from helab.analysis.physics import (ResolvedConstants, sigma_v_from_arrival_width, sigma_v_from_transverse_width,
                                    temperature_estimate)
from helab.analysis.plot_axes import GroupedAxis
from helab.analysis.plot_text import add_label, line_html, notes_html
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import (SHOT_SPECS, keep_fraction, manual, manual_bounds, range_brief, range_specs,
                                      range_warnings, select_shots, selection_text, shots_brief, shots_text)
from helab.analysis.stats import AXES, MAX_BINS, shortest_range
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.dld import group
from helab.scripts.dld.basic_plots import source_title
from helab.scripts.dld.shot_times import fallback_text
from helab.utils import events
from helab.utils.colours import AMBER

RANGE = range_specs(
    "Counts and the per-shot estimates use the events inside the shortest range holding this share of "
    "each axis's events (all chosen shots), rounded out to a twentieth of its width and kept while the "
    "events stay inside it, so that it stays put while Live adds shots.", fixed=True)

PLOT_GROUP = "Plot"
SHOT_NUMBER, SHOT_TIME = "shot number", "shot time"
X_AXIS = ParameterSpec("x_axis", "Against", "choice", SHOT_NUMBER, choices=(SHOT_NUMBER, SHOT_TIME),
                       group=PLOT_GROUP,
                       tip="Shot number, or when the shot was taken: its raw d<N>.txt file's time, else its TXY "
                           "file's (triangles; when it was converted). Shots without a time are left out.")
CENTRES = ParameterSpec("show_centres", "Centres", "bool", True, group=PLOT_GROUP,
                        tip="Each shot's centre along T, X and Y.")
WIDTHS = ParameterSpec("show_widths", "Widths", "bool", True, group=PLOT_GROUP,
                       tip="Each shot's width along T, X and Y: the fitted σ, or the threshold edges' distance.")
TEMPERATURES = ParameterSpec("show_temperatures", "Temperatures", "bool", False, group=PLOT_GROUP,
                             tip="Each shot's temperature from its width along T, X and Y (ideal gas, pure "
                                 "expansion: σ_v = g σ along T, σ / t_f along X and Y, T = m σ_v² / k_B), with "
                                 "the Constants below. Threshold edges use their Gaussian-equivalent σ.")
BAND = ParameterSpec("band", "Moving mean ± SD", "bool", True, group=PLOT_GROUP,
                     tip="The mean ± SD of the last N shots (Window N), each shot's own included, as a band.")
WINDOW = ParameterSpec("window", "Window N (shots)", "int", 100, (1, 100_000), group=PLOT_GROUP,
                       tip="The shots the moving mean ± SD and the low-count fraction rule use.")

ESTIMATE_GROUP = "Centre and width"
METHOD = ParameterSpec("method", "Method", "choice", trends.EDGES, choices=trends.METHODS, group=ESTIMATE_GROUP,
                       tip="Threshold edges (the legacy find_dist_cen): the outermost points where each shot's "
                           "histogram crosses a fraction of its highest bin; the centre is their midpoint, the "
                           "width their distance (no SE). Fast. Gaussian fit: the fitted centre and σ ± SE "
                           "(Poisson weights); about 15 ms per shot and axis, done once per shot.")
FRACTION = ParameterSpec("edge_percent", "Threshold", "float", 50.0, (1.0, 99.0), " %", group=ESTIMATE_GROUP,
                         when=(METHOD.name, trends.EDGES),
                         tip="The share of the highest bin the edges are found at (50 %: the full width at half "
                             "maximum).")
BINS = ParameterSpec("bins", "Bins", "int", 0, (0, MAX_BINS), group=ESTIMATE_GROUP,
                     tip="Bins of each shot's histogram over the View range; 0 = automatic (Freedman–Diaconis, "
                         "per shot).")
MIN_EVENTS = ParameterSpec("min_events", "At least (events)", "int", 20, (2, 1_000_000), group=ESTIMATE_GROUP,
                           tip="Shots with fewer events in the View range get no centre or width.")

LOW_GROUP = "Low counts"
LOW_ABSOLUTE = ParameterSpec("low_absolute", "Fewer than a count", "bool", True, group=LOW_GROUP,
                             tip="Flag (amber) shots with fewer events in the View range than this.")
LOW_COUNT = ParameterSpec("low_count", "Count", "int", 50, (1, 1_000_000_000), group=LOW_GROUP,
                          when=(LOW_ABSOLUTE.name, "True"),
                          tip="Proposed 50: the current monitor's num_lim.")
LOW_RELATIVE = ParameterSpec("low_relative", "Below a fraction of the recent mean", "bool", True, group=LOW_GROUP,
                             tip="Flag shots below this share of the mean of the Window N shots before them.")
LOW_PERCENT = ParameterSpec("low_percent", "Fraction", "float", 50.0, (1.0, 100.0), " %", group=LOW_GROUP,
                            when=(LOW_RELATIVE.name, "True"), tip="Proposed 50 %.")
NOTIFY = ParameterSpec("notify_low", "Notify during Live", "bool", False, group=LOW_GROUP,
                       tip="While Live adds shots to this plot's folder, a desktop notification when the newest "
                           "shot is low by the rules on (once per shot). Never "
                           "for shots already shown, nor outside Live.")
# The constants only the temperatures use: shown while Temperatures is on.
CONSTANTS = [replace(spec, when=(TEMPERATURES.name, "True")) if spec.when is None else spec
             for spec in constants_specs(("fall_distance", "fall_time"))]
CONSTANT_KEYS = ("fall_distance", "fall_time", "g", "mass", "k_B")

COLOUR = (40, 90, 170)
LOW_COLOUR = AMBER  # the app's amber, as the notes and warnings
BAND_COLOUR = (40, 90, 170, 40)
MEAN_COLOUR = (40, 90, 170, 160)
TOOLTIP = ("Amber: a low-count shot. Triangles: the shot's time is its TXY file's (no raw file). The band is "
           "the moving mean ± SD of the last N shots.")


@dataclass(frozen=True)
class Series:
    """One quantity per shot (in the data's units: s, m or K), its SE and its moving mean ± SD."""
    name: str
    values: npt.NDArray[np.float64]
    se: npt.NDArray[np.float64]
    mean: npt.NDArray[np.float64]
    sd: npt.NDArray[np.float64]


@dataclass(frozen=True)
class Trends:
    shots: npt.NDArray[np.int64]  # the chosen shots, ascending
    counts: npt.NDArray[np.int64]  # events inside the box
    times: npt.NDArray[np.float64]  # s since the epoch; nan without one
    fallback: npt.NDArray[np.bool_]  # the time is the TXY file's
    low: trends.LowFlags
    counts_series: Series
    # Per axis (T, X, Y): centres, widths and, when computed, temperatures.
    centres: tuple[Series, ...]
    widths: tuple[Series, ...]
    temperatures: tuple[Series, ...]
    failures: tuple[int, ...]  # per axis: shots without an estimate
    box: tuple[tuple[float, float], ...]  # () without events
    method: str
    fraction: float
    total_shots: int
    computed: int = 0  # shots estimated in this run (the rest were reused)
    added: tuple[int, ...] = ()  # the shots this revision added (Live)
    newest_fingerprint: tuple[int, int, int] | None = None
    notify: bool = False
    window: int = 100
    notes: tuple[str, ...] = ()
    unsettled_files: int = 0
    constants: ResolvedConstants | None = field(default=None, compare=False)
    masked: int = 0  # with no box: the events the mask took (all of them)

    @property
    def reused(self) -> int:
        return len(self.shots) - self.computed

    @property
    def fallbacks(self) -> int:
        return int(self.fallback.sum())

    @property
    def untimed(self) -> int:
        return int((~np.isfinite(self.times)).sum())

    def record(self) -> dict[str, Any]:
        """Strict JSON for the result's record: the box, the counts and each quantity's summary,
        the low shots (at most 100 listed), notes and, with temperatures, the constants."""
        mean, sd, _ = trends.summary(self.counts)
        low = self.shots[self.low.low].tolist()
        quantities: dict[str, Any] = {}
        for series in (*self.centres, *self.widths, *self.temperatures):
            value, spread, number = trends.summary(series.values)
            finite = series.values[np.isfinite(series.values)]
            quantities[series.name] = {"mean": trends.json_list([value])[0], "sd": trends.json_list([spread])[0],
                                       "shots": number,
                                       "first": trends.json_list(finite[:1])[0] if len(finite) else None,
                                       "last": trends.json_list(finite[-1:])[0] if len(finite) else None}
        record: dict[str, Any] = {
            "method": self.method, "threshold": self.fraction if self.method == trends.EDGES else None,
            "box": {axis: list(bounds) for axis, bounds in zip(AXES, self.box)},
            "counts": {"total": int(self.counts.sum()), "mean": trends.json_list([mean])[0],
                       "sd": trends.json_list([sd])[0]},
            "low": {"rules": self.low.rules_text(), "count": len(low), "shots": low[:100]},
            "quantities": quantities, "failures": dict(zip(AXES, self.failures)), "notes": list(self.notes),
            "computed": self.computed, "reused": self.reused}
        if self.constants is not None:
            record["constants"] = self.constants.as_record()
        # The box may be kept from an earlier run of the plot: a reuse must match it too.
        record["reuse"] = {"box": [list(bounds) for bounds in self.box]}
        record["record_lines"] = self.record_lines()
        return record

    def record_lines(self) -> list[str]:
        """For the dock's record: the counts, the low shots, each quantity's mean ± SD and notes
        (the constants are in the record once, from the run)."""
        mean, sd, _ = trends.summary(self.counts)
        lines = [f"Counts in the View range: {int(self.counts.sum()):,} in {len(self.shots):,} shots, "
                 f"{number_text(mean, 4)} ± {number_text(sd, 4)} (SD) per shot"]
        if self.box:
            lines.append("View range used: " + ", ".join(range_text(axis, low, high)
                                                         for axis, (low, high) in zip(AXES, self.box)))
        rules = self.low.rules_text()
        if rules:
            low = self.shots[self.low.low].tolist()
            listed = ", ".join(str(shot) for shot in low[:20]) + (" …" if len(low) > 20 else "")
            lines.append(f"Low ({rules}): {len(low):,} shot{'' if len(low) == 1 else 's'}"
                         + (f" ({listed})" if low else ""))
        for series in (*self.centres, *self.widths):
            value, spread, number = trends.summary(series.values)
            axis = series.name.split()[-1]
            lines.append(f"{series.name}: {axis_text(axis, value)} ± {axis_text(axis, spread, WIDTH_DIGITS)} (SD) "
                         f"over {number:,} shots")
        for series in self.temperatures:
            value, spread, number = trends.summary(series.values)
            lines.append(f"{series.name}: {Estimate(value, spread).text(unit='K')} (mean ± SD) over {number:,} shots")
        lines.append(f"Per-shot estimates: {self.computed:,} computed, {self.reused:,} reused")
        lines.extend(f"Note: {note}" for note in self.notes)
        return lines


def method_text(method: str, fraction: float) -> str:
    return f"edges at {fraction * 100:g} %" if method == trends.EDGES else "Gaussian fits"


def width_name(method: str, fraction: float) -> str:
    return "σ" if method == trends.FIT else f"full width at {fraction * 100:g} %"


def low_rules(values: Mapping[str, Any]) -> tuple[Optional[int], Optional[float]]:
    absolute = int(values.get(LOW_COUNT.name, LOW_COUNT.default)) if values.get(LOW_ABSOLUTE.name) else None
    fraction = (float(values.get(LOW_PERCENT.name, LOW_PERCENT.default)) / 100
                if values.get(LOW_RELATIVE.name) else None)
    return absolute, fraction


def view_box(view: DatasetView, shots: tuple[int, ...], values: Mapping[str, Any],
             cache: trends.ShotCache = trends.CACHE, owner: str = "", mask: Mask = Mask()
             ) -> tuple[tuple[tuple[float, float], ...], tuple[str, ...]]:
    """The box counts and estimates use, and notes on it: manual bounds as set; an axis without
    one (auto-crop, or a manual axis left at its full extent) from the chosen events, rounded out
    and, for a plot (``owner``), kept from an earlier run of this plot with the same range and
    Shots settings while the events stay inside it (``ShotCache.stable_range``). Without an
    owner nothing is kept: the box comes from this run's input alone. Only the events ``mask``
    keeps count."""
    events = mask.apply(view.events(shots))[0]
    if not len(events):
        return (), ()
    keep = keep_fraction(values)
    given = manual_bounds(values) if manual(values) else (None,) * len(AXES)
    identity = view.identity.root_key or view.identity.source_path
    box, found, kept = [], False, False
    for axis in range(len(AXES)):
        bounds = given[axis]
        if bounds is None:
            column = events[:, axis]
            low, high = ((float(column.min()), float(column.max())) if manual(values)
                         else shortest_range(column, keep))
            if not high > low:  # every event at one value
                low, high = low - 0.5e-9, high + 0.5e-9
            if owner:
                selection = tuple(values.get(spec.name, spec.default) for spec in SHOT_SPECS)
                bounds, previous = cache.stable_range((owner, identity, axis, manual(values), round(keep, 9),
                                                       selection, mask.circles), low, high)
            else:
                bounds, previous = trends.snapped(low, high), False
            found, kept = True, kept or previous
        box.append((float(bounds[0]), float(bounds[1])))
    notes = ((f"ranges found in the data are rounded out"
              f"{' and kept from an earlier run of this plot' if kept else ''}, so Live reuses per-shot "
              f"results"),) if found else ()
    return tuple(box), notes


def temperature_series(name: str, axis: str, sigma: npt.NDArray[np.float64],
                       sigma_se: npt.NDArray[np.float64], constants: ResolvedConstants, window: int) -> Series:
    factor = (sigma_v_from_arrival_width(1.0, constants) if axis == "T"
              else sigma_v_from_transverse_width(1.0, constants))
    values = np.full(len(sigma), np.nan)
    errors = np.full(len(sigma), np.nan)
    for index, (value, se) in enumerate(zip(sigma, sigma_se)):
        if math.isfinite(value):
            found = temperature_estimate(Estimate(value * factor, abs(se * factor)), constants)
            values[index], errors[index] = found.value, found.se
    mean, sd = trends.moving_stats(values, window)
    return Series(name, values, errors, mean, sd)


def compute_trends(context: AnalysisContext, cache: trends.ShotCache = trends.CACHE) -> Trends:
    view, values = context.view, context.parameters
    shots = select_shots(view, values)
    window = int(values.get(WINDOW.name, WINDOW.default))
    method = str(values.get(METHOD.name, METHOD.default))
    fraction = float(values.get(FRACTION.name, FRACTION.default)) / 100
    bins = int(values.get(BINS.name, BINS.default))
    min_events = int(values.get(MIN_EVENTS.name, MIN_EVENTS.default))
    mask = mask_from(values)  # Circles that can't be read fail the run, saying which.
    box, notes = view_box(view, shots, values, cache, context.owner, mask)
    notes = (*range_warnings(values), *notes)
    # The mask's circles key the per-shot estimates too: a changed mask never reuses one.
    settings = (method, round(fraction, 9) if method == trends.EDGES else None, bins, min_events, box,
                mask.circles)
    identity = view.identity.root_key or view.identity.source_path
    cache.note_owner(context.owner, identity)
    count = len(shots)
    counts = np.zeros(count, dtype=np.int64)
    centre = np.full((len(AXES), count), np.nan)
    centre_se, width, width_se, sigma, sigma_se = (np.full((len(AXES), count), np.nan) for _ in range(5))
    failures = [0] * len(AXES)
    computed = 0
    for index, shot in enumerate(shots):
        context.check()
        fingerprint = view.fingerprints.get(shot)
        key = (identity, shot, fingerprint, settings) if fingerprint is not None and box else None
        found = cache.get(key) if key is not None else None
        if found is None:
            if box:
                found = trends.estimate_shot(mask.apply(txy(view.shots[shot]))[0], box, method, bins, fraction,
                                             min_events)
            else:
                found = trends.ShotEstimate(0, tuple(trends.AxisEstimate(failure="no events")
                                                     for _ in AXES))
            computed += 1
            if key is not None:
                cache.put(key, found)
        counts[index] = found.count
        for axis, estimate in enumerate(found.axes):
            if not estimate.ok:
                failures[axis] += 1
                continue
            centre[axis, index], centre_se[axis, index] = estimate.centre.value, estimate.centre.se
            width[axis, index], width_se[axis, index] = estimate.width.value, estimate.width.se
            sigma[axis, index], sigma_se[axis, index] = estimate.sigma.value, estimate.sigma.se
    timed = view.shot_times(shots)
    times = np.array([timed.get(shot, math.nan) for shot in shots], dtype=np.float64)
    fallbacks = set(view.fallback_times(shots))
    fallback = np.array([shot in fallbacks for shot in shots], dtype=bool)
    absolute, low_fraction = low_rules(values)
    low = trends.low_flags(counts, absolute, low_fraction, window)

    def series(name: str, data: npt.NDArray[np.float64], errors: npt.NDArray[np.float64]) -> Series:
        mean, sd = trends.moving_stats(data, window)
        return Series(name, data, errors, mean, sd)

    centres = tuple(series(f"Centre {axis}", centre[i], centre_se[i]) for i, axis in enumerate(AXES))
    widths = tuple(series(f"Width {axis}", width[i], width_se[i]) for i, axis in enumerate(AXES))
    constants = context.resolved_constants
    temperatures: tuple[Series, ...] = ()
    if values.get(TEMPERATURES.name):
        if constants is None:
            constants = resolve_for_run(values, context.constants.get("lab"), context.constants.get("folder"))
        temperatures = tuple(temperature_series(f"Temperature from {axis}", axis, sigma[i], sigma_se[i],
                                                constants, window) for i, axis in enumerate(AXES))
        if method == trends.EDGES:
            notes = (*notes, "temperatures from the threshold widths' Gaussian-equivalent σ")
    counts_mean, counts_sd = trends.moving_stats(counts, window)
    newest = shots[-1] if shots else None
    masked = sum(len(view.shots[shot]) for shot in shots) if not box and mask.active else 0
    return Trends(np.array(shots, dtype=np.int64), counts, times, fallback, low,
                  Series("Counts", counts.astype(np.float64), np.full(count, np.nan), counts_mean, counts_sd),
                  centres, widths, temperatures, tuple(failures), box, method, fraction, len(view.shots), computed,
                  tuple(view.added_shots), view.fingerprints.get(newest) if newest is not None else None,
                  bool(values.get(NOTIFY.name)), window, tuple(notes), view.provenance.unsettled_files,
                  constants if temperatures else None, masked)


# Notifications

def low_alert(data: Trends, path: str) -> tuple[Any, str] | None:
    """(key, message) when the plot notifies and its newest shot is one this revision added
    (Live's) and low; None otherwise (a shot shown before is never notified)."""
    if not data.notify or not len(data.shots) or not data.low.low[-1]:
        return None
    newest = int(data.shots[-1])
    if newest not in data.added:
        return None
    name = path.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1] or path
    message = (f"Shot {newest} of {name}: {int(data.counts[-1]):,} events in the View range "
               f"({data.low.why(len(data.shots) - 1)})")
    return (events.LOW_COUNTS, path, newest, data.newest_fingerprint), message


# Per plot (``AnalysisResult.owner``): the input it last drew (identity, revision), so only a
# newer revision of the same data (Live's next) can notify. Each view chain has its own identity
# (``ViewIdentity.chain``), so a new chain's revisions notify from its second on, whatever the old one's. GUI thread; ``plot_closed`` drops it.
_drawn: dict[str, tuple[ViewIdentity, int]] = {}


def newer_than_drawn(result: AnalysisResult) -> bool:
    """Whether ``result``'s input is a later revision of the data its plot drew last (and note it
    as drawn): False for a plot's first drawing (a plot opened during Live), a rerun of the same
    revision (settings, a reload) and other data; always False without an owner (no plot)."""
    owner = result.owner
    if not owner:
        return False
    identity, revision = result.input.identity, result.input.revision
    before = _drawn.get(owner)
    if before is None or before[0] != identity or revision > before[1]:
        _drawn[owner] = (identity, revision)
    return before is not None and before[0] == identity and revision > before[1]


def notify_low(result: AnalysisResult) -> Optional[events.Event]:
    """The low-count notification for a result's newest shot, if any (GUI thread, as its plot is
    drawn): only for a later revision than the plot drew before (``newer_than_drawn``) while Live
    watches the folder (``events.hub().is_live``)."""
    data = result.data
    path = result.input.identity.source_path
    newer = newer_than_drawn(result)
    if not isinstance(data, Trends) or not newer or not events.hub().is_live(path):
        return None
    alert = low_alert(data, path)
    if alert is None:
        return None
    key, message = alert
    return events.notify(events.LOW_COUNTS, message, title="HeLab: low counts", key=key, desktop=True,
                         path=path, shot=int(data.shots[-1]), count=int(data.counts[-1]))


# Drawing

def layout_key(values: Mapping[str, Any]) -> tuple[Any, ...]:
    """What the drawn plots depend on (their panels, axes and labels): an update in place keeps them."""
    return tuple(bool(values.get(spec.name, spec.default)) for spec in (CENTRES, WIDTHS, TEMPERATURES, BAND)) \
        + tuple(str(values.get(spec.name, spec.default)) for spec in (X_AXIS, METHOD, FRACTION))


def title_text(data: Trends) -> str:
    mean, sd, _ = trends.summary(data.counts)
    parts = [shots_text(data.shots.tolist(), data.total_shots),
             f"{int(data.counts.sum()):,} events in range, {number_text(mean, 4)} ± {number_text(sd, 4)} (SD) "
             f"per shot",
             method_text(data.method, data.fraction)]
    if data.low.count:
        parts.append(f"⚠ {data.low.count:,} low (amber)")
    return " · ".join(parts)


def key_html(data: Trends, time_axis: bool) -> str:
    """The plots' key, below the title (no legend inside a plot, where it would cover points)."""
    def mark(colour: Any, symbol: str) -> str:
        return f'<span style="color: {pg.mkColor(colour).name()}">{symbol}</span>'

    parts = [f"{mark(COLOUR, '●')} shot"]
    if data.low.count:
        parts.append(f"{mark(LOW_COLOUR, '●')} low counts ({html.escape(data.low.rules_text())})")
    if time_axis and data.fallbacks:
        parts.append(f"{mark(COLOUR, '▼')} TXY file time (no raw file)")
    parts.append(f"{mark(MEAN_COLOUR[:3], '━')} mean ± SD of the last {data.window:,} shots")
    return " · ".join(parts)


class Panel:
    """One plot of one quantity: its band, mean line, error bars and points."""

    def __init__(self, plot: Any, scale: float, band: bool) -> None:
        self.plot, self.scale = plot, scale
        self.upper = pg.PlotDataItem(pen=pg.mkPen((0, 0, 0, 0)))
        self.lower = pg.PlotDataItem(pen=pg.mkPen((0, 0, 0, 0)))
        self.mean = pg.PlotDataItem(pen=pg.mkPen(MEAN_COLOUR, width=1.5))
        self.band = pg.FillBetweenItem(self.upper, self.lower, brush=pg.mkBrush(BAND_COLOUR))
        self.errors = pg.ErrorBarItem(x=np.empty(0), y=np.empty(0), height=np.empty(0), beam=0,
                                      pen=pg.mkPen((*COLOUR, 120)))
        self.points = pg.ScatterPlotItem(size=6, pen=None)
        if band:
            for item in (self.upper, self.lower, self.band, self.mean):
                plot.addItem(item)
        plot.addItem(self.errors)
        plot.addItem(self.points)

    def show(self, x: npt.NDArray[np.float64], series: Series, low: npt.NDArray[np.bool_],
             fallback: npt.NDArray[np.bool_]) -> None:
        y = series.values * self.scale
        shown = np.isfinite(x) & np.isfinite(y)
        normal, amber = pg.mkBrush(COLOUR), pg.mkBrush(LOW_COLOUR)
        brushes = [amber if flagged else normal for flagged in low[shown]]
        symbols = ["t" if flagged else "o" for flagged in fallback[shown]]
        self.points.setData(x=x[shown], y=y[shown], brush=brushes, symbol=symbols)
        se = series.se * self.scale
        bars = shown & np.isfinite(se)
        self.errors.setData(x=x[bars], y=y[bars], height=2 * se[bars])
        # The band follows the shots in x order (a shot time may come before the previous shot's).
        order = np.argsort(x, kind="stable")
        x, mean, sd = x[order], series.mean[order] * self.scale, series.sd[order] * self.scale
        line = np.isfinite(x) & np.isfinite(mean)
        self.mean.setData(x[line], mean[line])
        spread = line & np.isfinite(sd)
        self.upper.setData(x[spread], (mean + sd)[spread])
        self.lower.setData(x[spread], (mean - sd)[spread])


class TrendsWidget(pg.GraphicsLayoutWidget):  # type: ignore[misc]
    """The plots, so a rerun (Live) updates them in place, keeping zoom and pan."""

    def __init__(self, key: tuple[Any, ...], data: Trends, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.key = key
        centres, widths, temperatures, band, against = key[:5]
        self.setBackground("w")
        self.setToolTip(TOOLTIP)
        layout: Any = self.ci
        self.title = add_label(layout, row=0, col=0, colspan=3)
        self.key_label = add_label(layout, row=1, col=0, colspan=3)
        self.panels: list[tuple[Panel, str, int]] = []  # (panel, quantity, axis)
        self.time_axis = against == SHOT_TIME

        def bottom() -> Any:
            return pg.DateAxisItem(orientation="bottom") if self.time_axis else GroupedAxis("bottom")

        def axes() -> dict[str, Any]:
            return {"bottom": bottom(), "left": GroupedAxis("left")}

        counts_plot = layout.addPlot(row=2, col=0, colspan=3, axisItems=axes())
        counts_plot.setLabel("left", "Events in range")
        self._dress(counts_plot)
        self.panels.append((Panel(counts_plot, 1.0, band), "counts", 0))
        self.counts_plot = counts_plot
        row = 3
        width = width_name(data.method, data.fraction)
        for quantity, on in (("centres", centres), ("widths", widths), ("temperatures", temperatures)):
            if not on:
                continue
            for axis_index, axis in enumerate(AXES):
                if quantity == "temperatures":
                    # In K with pyqtgraph's SI prefix (µK, nK), as D1's temperatures are written.
                    plot = layout.addPlot(row=row, col=axis_index, axisItems={"bottom": bottom()})
                    plot.setLabel("left", f"Temperature from {axis}", units="K")
                    scale = 1.0
                else:
                    plot = layout.addPlot(row=row, col=axis_index, axisItems=axes())
                    name = "Centre" if quantity == "centres" else f"Width, {width},"
                    plot.setLabel("left", f"{name} {axis} ({axis_unit(axis)})")
                    scale = axis_scale(axis)
                self._dress(plot)
                self.panels.append((Panel(plot, scale, band), quantity, axis_index))
            row += 1
        # One shot range for all: pyqtgraph's own x link lines plots up by pixel, which a wide
        # plot over three narrow ones defeats, so any x change in one (a zoom, a pan, its auto
        # range as Live adds shots) is copied to the others.
        self._syncing = False
        for panel, _, _ in self.panels:
            panel.plot.vb.sigXRangeChanged.connect(self._sync_x)

    @pyqtSlot()
    def _sync_x(self) -> None:
        source = self.sender()
        if self._syncing or source is None:
            return
        self._syncing = True
        try:
            low, high = cast(Any, source).viewRange()[0]
            for panel, _, _ in self.panels:
                if panel.plot.vb is not source:
                    panel.plot.setXRange(low, high, padding=0)
        finally:
            self._syncing = False

    def _dress(self, plot: Any) -> None:
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.setLabel("bottom", "Shot time" if self.time_axis else "Shot number")

    def show_data(self, result: AnalysisResult, data: Trends) -> None:
        header = line_html(source_title(result, title_text(data)))
        if data.constants is not None:
            used = describe_constants(data.constants, CONSTANT_KEYS)
            header += f"<br>Temperatures with {html.escape(used)}" if used else \
                "<br>Temperatures with the default constants"
        notes = list(data.notes)
        if self.time_axis and data.fallbacks:
            notes.append(fallback_text(data.fallbacks))
        if self.time_axis and data.untimed:
            notes.append(f"{data.untimed:,} without a time left out")
        failed = [f"{axis} {count:,}" for axis, count in zip(AXES, data.failures) if count]
        if failed:
            notes.append(f"shots without a centre/width: {', '.join(failed)}")
        if data.unsettled_files:
            notes.append(f"{data.unsettled_files:,} files still being written left out")
        if data.constants is not None:
            notes.extend(data.constants.notes)
        self.title.setText(header + notes_html(notes))
        self.key_label.setText(key_html(data, self.time_axis))
        x = data.times if self.time_axis else data.shots.astype(np.float64)
        for panel, quantity, axis in self.panels:
            series = (data.counts_series if quantity == "counts" else data.centres[axis] if quantity == "centres"
                      else data.widths[axis] if quantity == "widths" else data.temperatures[axis])
            panel.show(x, series, data.low.low, data.fallback if self.time_axis else np.zeros(len(x), dtype=bool))


class ShotTrends(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Shot trends",
            description="Per shot: events in the View range and the centre, width and temperature along T, X "
                        "and Y, with a moving mean ± SD; low-count shots flagged",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.shot_trends",
            version="2",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*SHOT_SPECS, *RANGE, *MASK_SPECS, X_AXIS, CENTRES, WIDTHS, TEMPERATURES, BAND, WINDOW, METHOD, FRACTION, BINS,
                MIN_EVENTS, LOW_ABSOLUTE, LOW_COUNT, LOW_RELATIVE, LOW_PERCENT, NOTIFY, *CONSTANTS]

    def constant_keys(self, action_name: str) -> tuple[str, ...]:
        return CONSTANT_KEYS

    def run_constants(self, action_name: str, values: Mapping[str, Any],
                      layers: Mapping[str, Mapping[str, float]]) -> ResolvedConstants | None:
        """The constants the temperatures use; None when they aren't shown."""
        if not values.get(TEMPERATURES.name):
            return None
        return resolve_for_run(values, layers.get("lab"), layers.get("folder"))

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        used = selection_text(view, values)
        if values.get(X_AXIS.name) == SHOT_TIME:
            fallbacks = len(view.fallback_times(select_shots(view, values)))
            used += f" · ⚠ {fallback_text(fallbacks)}" if fallbacks else ""
        method = str(values.get(METHOD.name, METHOD.default))
        absolute, fraction = low_rules(values)
        rules = trends.LowFlags(np.empty(0, dtype=bool), np.empty(0, dtype=bool), np.empty(0, dtype=bool),
                                np.empty(0), absolute, fraction,
                                int(values.get(WINDOW.name, WINDOW.default))).rules_text()
        settings = (shots_brief(values), range_brief(values, fixed=True), mask_brief(values),
                    method_text(method, float(values.get(FRACTION.name, FRACTION.default)) / 100),
                    "against shot time" if values.get(X_AXIS.name) == SHOT_TIME else "",
                    f"window {int(values.get(WINDOW.name, WINDOW.default)):,}",
                    f"low: {rules}" if rules else "",
                    "notify during Live" if values.get(NOTIFY.name) and rules else "")
        return used, " · ".join(part for part in settings if part)

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        warnings = [*range_warnings(values), *mask_warnings(values)]
        if values.get(NOTIFY.name) and not any(low_rules(values)):
            warnings.append("Notify during Live is on but no low-count rule is: nothing is notified")
        return warnings

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        return compute_trends(context)

    def plot_closed(self, action_name: str, owner: str, path: str) -> None:
        """Forget what the plot drew and its kept ranges; its folder's per-shot estimates go when no
        other Shot trends plot uses that folder."""
        _drawn.pop(owner, None)
        trends.CACHE.plot_closed(owner)

    def result_found(self, action_name: str, data: Any) -> dict[str, Any]:
        return data.record() if isinstance(data, Trends) else {}

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: Trends = result.data
        if not len(data.shots) or not data.box:
            if data.masked and len(data.shots):
                return empty_pane(all_masked_text(data.masked), parent)
            return empty_pane(empty_text(data.total_shots, len(data.shots), 0), parent)
        notify_low(result)
        widget = TrendsWidget(layout_key(result.parameters), data, parent)
        widget.show_data(result, data)
        return cast(QWidget, widget)

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """Live's next shots go into the plots already drawn: zoom and pan stay."""
        data: Trends = result.data
        if (not isinstance(widget, TrendsWidget) or not len(data.shots) or not data.box
                or widget.key != layout_key(result.parameters)):
            return False
        notify_low(result)
        widget.show_data(result, data)
        return True
