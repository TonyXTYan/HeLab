"""Release time (D8): when the atoms left the trap, in DLD time, and where the trap is above the
detector, from one cloud released at rest (roadmaps/dld-front-panel-port.md, Decided:
"Release-time detection").

The chosen shots' events within Search T go to ``release.bootstrap_release_time``: the tallest T
peak is the cloud, its arrival is fitted with the arrival-time profile (a Gaussian, then the mean,
as fallbacks, noted), the fall time t_f = √(2h/g) (the run's constants: h, g or a t_f set by hand)
is subtracted, and the shot bootstrap (``N_BOOT`` resamples of whole shots, ``N_BOOT_DEFAULT`` = 100
by default; ``release.RELEASE_N_BOOT`` is 200 for other callers) gives
the error over shots, the shot-to-shot jitter included; the fit's own (within-run) SE is in the
record. The same cloud's mean X and Y, within an XY window about their median, is the trap's
origin on the detector, with the background's share.

The plot shows the T histogram of the searched events with the release and arrival marked, the
arrival up close with the fitted profile and its window, and the X and Y histograms of the
cloud's T slice with the origin and its window. The title says ``release t_r = 20,031.2 ± 0.3 ms
(shot bootstrap) · arrival 20,447.3 ms · t_f 416.09 ms (h 848 mm)`` and ``origin (3.00 ± 0.04,
−2.00 ± 0.04) mm · background 0.2 %``, then the notes (unsure, a fit's fallback, the skew of a
wide cloud, few shots) in amber.

**Use for this folder…** saves the arrival at rest t_a (not t_r) and the origin as the folder's
constants (Folder constants…: ``FolderCache.set_folder_constants``, merged with what the folder sets
already, dropping a t_r set by hand there), after the user confirms, so the velocity plots use them,
each taking t_r = t_a − t_f with its own fall time (``release.layer_release_time``); never
automatically. A folder that sets them still
shows this plot's detection (the plot always detects: it is how they are measured).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, List, Mapping, Optional

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PyQt6 import sip
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from helab.analysis import result_types
from helab.analysis.result_codec import Declared
from helab.analysis.constant_layers import (clean_layer, constants_specs, describe_constants, origin_text,
                                           resolve_for_run, value_and_origin)
from helab.analysis.dataset_view import DatasetView, txy
from helab.analysis.display_units import (LENGTH_SCALE, T_SCALE, WIDTH_DIGITS, axis_label, group_digits, length_text,
                                          number_text, range_text, time_text)
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.estimates import Estimate, format_fixed
from helab.analysis.follow import LivePolicy
from helab.analysis.parameters import ParameterSpec
from helab.analysis.physics import TABLE, ResolvedConstants, resolve
from helab.analysis.plot_axes import grouped_axes
from helab.analysis.plot_text import add_label, add_plot, lines_html, short_note
from helab.analysis.release import ReleaseTime, bootstrap_release_time, detect_release_time
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import SHOT_SPECS, select_shots, selection_text, shots_brief, shots_text
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.dld import group
from helab.utils.colours import AMBER

if TYPE_CHECKING:
    from helab.utils.folder_cache import FolderCache

SEARCH_GROUP = "Search"
SEARCH_MIN = ParameterSpec("search_min", "Search T from (0 = first)", "float", 0.0, (0.0, 100.0), " s",
                           group=SEARCH_GROUP, si=True, unit_prefix="m",
                           tip="The cloud is looked for between these times; 0 leaves that end open. The tallest peak "
                               "here is taken as the cloud released at rest: narrow the range when another is taller.")
SEARCH_MAX = ParameterSpec("search_max", "Search T to (0 = last)", "float", 0.0, (0.0, 100.0), " s",
                           group=SEARCH_GROUP, si=True, unit_prefix="m",
                           tip="See Search T from. A From at or above To searches every event, and the plot says so.")
ERROR_GROUP = "Error"
# Each resample is a whole detection: 100 took 5 s on 20 shots of 2,200 events and 32 s on 100 shots
# of 5,500 (the XY origin's medians dominate), and the SE's own error is about 7 % (5 % at 200).
N_BOOT_DEFAULT = 100  # proposed, for Tony (release.RELEASE_N_BOOT is 200)
N_BOOT = ParameterSpec("n_boot", "Shot bootstrap resamples (0 = off)", "int", N_BOOT_DEFAULT, (0, 5000),
                       group=ERROR_GROUP,
                       tip="The error over shots: the detection rerun on this many resamples of whole shots, so it "
                           "includes the shot-to-shot jitter of the release and the trap. Each resample is a "
                           "detection: 100 take about 5 s on 40,000 events, 30 s on 500,000. 0: the fit's own SE "
                           "only, within run, which leaves the jitter out.")
CONSTANT_KEYS = ("fall_distance", "fall_time", "g")
CONSTANTS = tuple(constants_specs(CONSTANT_KEYS))
PARAMETERS = (*SHOT_SPECS, SEARCH_MIN, SEARCH_MAX, N_BOOT, *CONSTANTS)
LIVE_NOTE = ("Live rerun: shot bootstrap skipped, so the SE is the fit's alone (within run), without the "
             "shot-to-shot jitter; Rerun (or Live's end) runs it")

OVERVIEW_BINS = 400
MAX_ZOOM_BINS = 600
ZOOM_REACHES = 3.0  # the close-up spans the fit window this many times over
XY_BINS = 60
XY_FRAMES = 2.0  # the X/Y histograms span the origin's window this many times over
COLOUR = (40, 90, 170)
FIT_COLOUR = (214, 39, 40)
RELEASE_COLOUR = (44, 160, 44)
WINDOW_COLOUR = (120, 120, 120)

Histogram = tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]  # (edges, counts)


def no_histogram() -> Histogram:
    return np.empty(0), np.empty(0)


@dataclass(frozen=True)
class ReleaseData:
    shots: tuple[int, ...]
    total_shots: int
    events: int  # in the chosen shots
    constants: ResolvedConstants
    n_boot: int
    searched: int = 0  # of them, in Search T
    search: tuple[float | None, float | None] = (None, None)
    release: ReleaseTime | None = None
    warnings: tuple[str, ...] = ()  # settings not followed as given
    notes: tuple[str, ...] = ()  # the plot's own (the error used); the release's are in ``release.notes``
    overview: Histogram = field(default_factory=no_histogram)
    zoom: Histogram = field(default_factory=no_histogram)
    curve: tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]] = field(default_factory=no_histogram)
    x_hist: Histogram = field(default_factory=no_histogram)
    y_hist: Histogram = field(default_factory=no_histogram)
    live_skipped: bool = False  # a Live rerun: the bootstrap was skipped (``LIVE_NOTE``)

    @property
    def ok(self) -> bool:
        return self.release is not None and self.release.ok

    def all_notes(self) -> tuple[str, ...]:
        found = self.release.notes if self.release is not None else ()
        return (*found, *self.notes)


def search_range(values: Mapping[str, Any]) -> tuple[float | None, float | None, tuple[str, ...]]:
    """Search T's ends (None: open) and a warning when they cross."""
    lower = float(values.get(SEARCH_MIN.name, 0.0)) or None
    upper = float(values.get(SEARCH_MAX.name, 0.0)) or None
    if lower is not None and upper is not None and lower >= upper:
        return None, None, (f"Search T: from {time_text(lower)} is at or above to {time_text(upper)}: "
                            "searching every event",)
    return lower, upper, ()


def search_text(lower: float | None, upper: float | None) -> str:
    """``T 20,400–20,600 ms``, ``T from 20,400 ms``, ``T to 20,600 ms``; "" for every event."""
    if lower is not None and upper is not None:
        return range_text("T", lower, upper)
    if lower is not None:
        return f"T from {time_text(lower)}"
    return f"T to {time_text(upper)}" if upper is not None else ""


def estimate_number(estimate: Estimate, scale: float) -> str:
    """``20,031.2 ± 0.3``: a value and its SE (2 digits), grouped; the value alone without an SE."""
    if not math.isfinite(estimate.se):
        return group_digits(format_fixed(estimate.value * scale, math.nan, "pm", "", 2)).split(" ±")[0]
    return group_digits(format_fixed(estimate.value * scale, estimate.se * scale, "pm", "", 2))


def fall_text(constants: ResolvedConstants) -> str:
    """``t_f 416.0908 ms (h 848 mm)`` when derived, else with where the fall time came from."""
    where = (f"h {length_text(constants.fall_distance)}" if constants.origins["fall_time"] == "derived"
             else origin_text(constants, "fall_time"))
    return f"t_f {time_text(constants.fall_time)} ({where})"


def release_line(data: ReleaseData) -> str:
    """``release t_r = 20,031.2 ± 0.3 ms (shot bootstrap) · arrival 20,447.3 ms · t_f …``, or why not."""
    found = data.release
    if found is None:
        return ""
    if not found.ok:
        return f"⚠ no release time: {found.failure}"
    error = f" ({found.error})" if found.error != "none" else ""
    return (f"release t_r = {estimate_number(found.value, T_SCALE)} ms{error} · arrival "
            f"{time_text(found.arrival.value)} · {fall_text(data.constants)}")


def origin_line(found: ReleaseTime | None) -> str:
    """``origin (3.00 ± 0.04, −2.00 ± 0.04) mm · background 0.2 %``, or that it wasn't found."""
    if found is None or not found.ok:
        return ""
    if not found.origin_found:
        return "origin not found: velocities assume the trap above X = Y = 0"
    x, y = (estimate_number(axis, LENGTH_SCALE) for axis in found.origin)
    share = found.origin_background
    background = f"background {share:.1%}".replace("%", " %") if math.isfinite(share) else "background unknown"
    return f"origin ({x}, {y}) mm · {background}"


def titles(result: AnalysisResult, data: ReleaseData) -> tuple[str, ...]:
    """The figure's title lines: what it searched, the release time, the origin, then one line per
    warning and note (amber, shortened: the record has them whole)."""
    where = search_text(*data.search)
    first = (f"{result.input.short()} · {shots_text(data.shots, data.total_shots)} · "
             + (f"{data.searched:,} of {data.events:,} events in Search T ({where})" if where
                else f"{data.events:,} events"))
    return (first, release_line(data), origin_line(data.release),
            *(f"⚠ {warning}" for warning in data.warnings),
            *(f"⚠ {short_note(note)}" for note in data.all_notes()))


def brief(data: ReleaseData) -> str:
    """For the settings line: ``t_r 20,031.2 ± 0.3 ms · origin (3, −2) mm``."""
    found = data.release
    if found is None or not found.ok:
        return ""
    text = f"t_r {estimate_number(found.value, T_SCALE)} ms"
    if found.origin_found:
        x, y = (number_text(axis.value * LENGTH_SCALE, WIDTH_DIGITS) for axis in found.origin)
        text += f" · origin ({x}, {y}) mm"
    return text


def record_lines(data: ReleaseData) -> list[str]:
    """The release, its errors, the arrival's fit and the origin, with every note whole."""
    found = data.release
    if found is None:
        return []
    lines: list[str] = []
    if not found.ok:
        lines.append(f"No release time: {found.failure} ({found.events:,} events searched)")
    else:
        se = found.within_run_se
        lines.append(f"Release time t_r = {estimate_number(found.value, T_SCALE)} ms ({found.error}); the fit's "
                     f"SE alone, within run: {time_text(se, WIDTH_DIGITS) if math.isfinite(se) else 'none'}")
        if found.bootstrap is not None:
            lines.append(f"Shot bootstrap: {found.bootstrap.n_boot:,} resamples of {len(data.shots):,} shots, "
                         f"seed {found.bootstrap.seed}")
        lines.append(f"Arrival {estimate_number(found.arrival, T_SCALE)} ms, σ_t "
                     f"{estimate_number(found.width, T_SCALE)} ms; {fall_text(data.constants)}, taken as exact "
                     "(its error is systematic, the same for every shot)")
        fit = found.fit
        if fit is not None and fit.ok:
            low, high = found.fit_window
            lines.append(f"Fit: {fit.model.title}, {range_text('T', low, high)}, χ²/dof {fit.reduced_chi2:.3g}")
        if found.origin_found:
            lines.append(f"{origin_line(found)} · {found.origin_events:,} events within "
                         f"{time_text(found.origin_half, WIDTH_DIGITS)} of the arrival")
        else:
            lines.append(origin_line(found))
    lines += [f"Note: {note}" for note in (*data.warnings, *data.all_notes())]
    return lines


def _histogram(values: npt.NDArray[np.float64], low: float, high: float, bins: int) -> Histogram:
    if not (math.isfinite(low) and math.isfinite(high) and high > low and bins > 0):
        return no_histogram()
    counts, edges = np.histogram(values, bins=bins, range=(low, high))
    return edges.astype(np.float64), counts.astype(np.float64)


def _close_up(times: npt.NDArray[np.float64], found: ReleaseTime
              ) -> tuple[Histogram, tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]]:
    """The arrival up close (its fit window ``ZOOM_REACHES`` times over) in the fit's bins, and the
    fitted profile over its window, in counts per such bin."""
    low, high = found.fit_window
    reach = (high - low) / 2
    if not (math.isfinite(reach) and reach > 0):
        reach = 4 * found.width.value if math.isfinite(found.width.value) and found.width.value > 0 else math.nan
    if not math.isfinite(reach):
        return no_histogram(), no_histogram()
    centre = found.arrival.value
    fit = found.fit
    fit_width = float(fit.x[1] - fit.x[0]) if fit is not None and fit.ok and len(fit.x) > 1 else 2 * reach / 40
    span = 2 * ZOOM_REACHES * reach
    bins = min(max(int(round(span / fit_width)), 10), MAX_ZOOM_BINS)
    zoom = _histogram(times, centre - span / 2, centre + span / 2, bins)
    if fit is None or not fit.ok or not math.isfinite(low):
        return zoom, no_histogram()
    x = np.linspace(low, high, 400)
    width = span / bins
    return zoom, (x, fit.evaluate(x) * (width / fit_width))


def _slices(events: npt.NDArray[np.float64], found: ReleaseTime) -> tuple[Histogram, Histogram]:
    """X and Y histograms of the cloud's T slice (the origin's events, before its XY window),
    spanning the window ``XY_FRAMES`` times over (else the slice's extent)."""
    if not math.isfinite(found.origin_half):
        return no_histogram(), no_histogram()
    near = events[np.abs(events[:, 0] - found.arrival.value) <= found.origin_half]
    near = near[np.all(np.isfinite(near[:, 1:3]), axis=1)]
    out: list[Histogram] = []
    for axis, (low, high) in zip((1, 2), found.origin_window):
        column = near[:, axis]
        if math.isfinite(low) and math.isfinite(high) and high > low:
            middle, half = (low + high) / 2, XY_FRAMES * (high - low) / 2
            low, high = middle - half, middle + half
        elif len(column):
            low, high = float(column.min()), float(column.max())
        out.append(_histogram(column, low, high, XY_BINS))
    return out[0], out[1]


def folder_values(found: ReleaseTime) -> dict[str, float]:
    """What "Use for this folder" saves: the arrival of the cloud at rest (s), not t_r, so each plot
    takes t_r = t_a − t_f with its own fall time (``release.layer_release_time``), and when found,
    the origin (m)."""
    if not found.ok or not math.isfinite(found.arrival.value):
        return {}
    values = {"arrival_time": found.arrival.value}
    if found.origin_found:
        values |= {"trap_x": found.origin[0].value, "trap_y": found.origin[1].value}
    return values


def merged_values(own: Mapping[str, float], found: ReleaseTime) -> dict[str, float]:
    """The folder's constants after "Use for this folder": its own, without a t_r set by hand (the
    saved arrival replaces it: a t_r by hand would win over it), with ``folder_values``."""
    return {**{key: value for key, value in own.items() if key != "release_time"}, **folder_values(found)}


FALL_KEYS = ("fall_distance", "g", "fall_time")


def fall_differs(plot: ResolvedConstants, folder: ResolvedConstants) -> bool:
    """Whether the run's fall time (its h, g or t_f, maybe this plot's own) isn't the folder's."""
    return not math.isclose(plot.fall_time, folder.fall_time, rel_tol=1e-9)


def confirmation_text(path: str, found: ReleaseTime, now: ResolvedConstants, after: ResolvedConstants,
                      plot: ResolvedConstants, replaces_by_hand: bool) -> str:
    """The question "Use for this folder" asks: each value and what it is now, the t_r this folder's
    plots get from it (with the folder's fall time, ``after``), and warnings: the run's fall time
    isn't the folder's (``plot``), unsure, or a within-run error."""
    name = os.path.basename(path.rstrip("/\\")) or path
    values = folder_values(found)
    lines = [f"Save these as constants of {name} (and of its subfolders that don't set their own)?", ""]
    for key, value in values.items():
        text = time_text(value) if key == "arrival_time" else length_text(value)
        lines.append(f"{TABLE[key].title}: {text}   (now: {value_and_origin(now, key)})")
    if not found.origin_found:
        lines.append("The trap origin wasn't found: the folder's stays as it is.")
    t_r = found.arrival.value - after.fall_time
    lines += ["", f"Plots of this folder then take t_r = t_a − t_f = {time_text(t_r)} with their own fall time "
                  f"(this folder's: {fall_text(after)})."]
    if replaces_by_hand:
        lines.append(f"It replaces the folder's release time set by hand ({value_and_origin(now, 'release_time')}).")
    if fall_differs(plot, after):
        lines += ["", f"⚠ This run's fall time isn't the folder's: {fall_text(plot)} here, so its t_r "
                      f"{time_text(found.value.value)} differs from what the folder's plots will use."]
    if found.unsure:
        lines += ["", "⚠ The detection is unsure: another peak may be the cloud released at rest."]
    if found.error != "shot bootstrap":
        lines += ["", "⚠ Its error is the fit's alone (within run), without the shot-to-shot jitter."]
    lines += ["", "Plots of this folder use them from their next run. Folder constants… changes or restores them."]
    return "\n".join(lines)


class ReleasePlot(QWidget):
    """The T histogram with the release and arrival, the arrival up close with its fit, the X and Y
    of the cloud's slice with the origin, and Use for this folder…; ``show_data`` draws a newer
    result in place."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.graphics: Any = pg.GraphicsLayoutWidget(self)
        self.graphics.setBackground("w")
        layout.addWidget(self.graphics, 1)
        self.title: Any = add_label(self.graphics, row=0, col=0, colspan=2)
        self.overview: Any = add_plot(self.graphics, "T, the events searched",
                                      row=1, col=0, colspan=2, axisItems=grouped_axes("bottom", "left"))
        self.overview.setLabel("bottom", axis_label("T"))
        self.overview.setLabel("left", "Events per bin")
        self.zoom: Any = add_plot(self.graphics, "The arrival, with the fitted profile",
                                  row=2, col=0, colspan=2, axisItems=grouped_axes("bottom", "left"))
        self.zoom.setLabel("bottom", axis_label("T"))
        self.zoom.setLabel("left", "Events per bin")
        self.x_plot: Any = add_plot(self.graphics, "X at the arrival",
                                    row=3, col=0, axisItems=grouped_axes("bottom", "left"))
        self.x_plot.setLabel("bottom", axis_label("X"))
        self.y_plot: Any = add_plot(self.graphics, "Y at the arrival",
                                    row=3, col=1, axisItems=grouped_axes("bottom", "left"))
        self.y_plot.setLabel("bottom", axis_label("Y"))
        for plot in (self.overview, self.zoom, self.x_plot, self.y_plot):
            plot.showGrid(x=True, y=True, alpha=0.3)
        row = QHBoxLayout()
        row.setContentsMargins(6, 2, 6, 4)
        self.use_button = QPushButton("Use for this folder…")
        self.use_button.setToolTip("Save t_r and the trap origin as this folder's constants (Folder constants…), "
                                   "for the velocity plots. Asks first.")
        self.use_button.clicked.connect(self.use_for_folder)
        row.addWidget(self.use_button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        row.addWidget(self.status, 1)
        layout.addLayout(row)
        self.data: ReleaseData | None = None
        self.path = ""
        self.cache: FolderCache | None = None  # the app's unless set (tests)
        self.owner = f"release-plot:{id(self)}"
        self._listening = False

    def show_data(self, result: AnalysisResult, data: ReleaseData) -> None:
        self.data, self.path = data, result.input.identity.source_path
        self.title.setText(lines_html(titles(result, data)))
        found = data.release
        for plot in (self.overview, self.zoom, self.x_plot, self.y_plot):
            plot.clear()
        self._steps(self.overview, data.overview, T_SCALE)
        self._steps(self.zoom, data.zoom, T_SCALE)
        self._steps(self.x_plot, data.x_hist, LENGTH_SCALE)
        self._steps(self.y_plot, data.y_hist, LENGTH_SCALE)
        if found is not None and found.ok:
            arrival = found.arrival.value * T_SCALE
            self.overview.addItem(self._line(arrival, FIT_COLOUR, "arrival"))
            self.overview.addItem(self._line(found.value.value * T_SCALE, RELEASE_COLOUR, "release t_r"))
            if all(math.isfinite(end) for end in found.fit_window):
                region = pg.LinearRegionItem([end * T_SCALE for end in found.fit_window], movable=False,
                                             brush=pg.mkBrush(*FIT_COLOUR, 30), pen=pg.mkPen(None))
                self.zoom.addItem(region)
            x, y = data.curve
            if len(x):
                self.zoom.plot(x * T_SCALE, y, pen=pg.mkPen(FIT_COLOUR, width=2))
            self.zoom.addItem(self._line(arrival, FIT_COLOUR, "arrival"))
            for plot, axis, window in zip((self.x_plot, self.y_plot), found.origin, found.origin_window):
                for end in window:
                    if math.isfinite(end):
                        plot.addItem(self._line(end * LENGTH_SCALE, WINDOW_COLOUR, "", dashed=True))
                if math.isfinite(axis.value):
                    plot.addItem(self._line(axis.value * LENGTH_SCALE, FIT_COLOUR, "origin"))
        self.use_button.setEnabled(bool(folder_values(found)) if found is not None else False)
        self.status.setText("")

    @staticmethod
    def _steps(plot: Any, histogram: Histogram, scale: float) -> None:
        edges, counts = histogram
        if len(counts):
            plot.plot(edges * scale, counts, stepMode="center", fillLevel=0, brush=pg.mkBrush(*COLOUR, 60),
                      pen=pg.mkPen(COLOUR))

    @staticmethod
    def _line(position: float, colour: tuple[int, int, int], label: str, dashed: bool = False) -> Any:
        pen = pg.mkPen(colour, width=1.5, style=pg.QtCore.Qt.PenStyle.DashLine if dashed else
                       pg.QtCore.Qt.PenStyle.SolidLine)
        options = {"label": label, "labelOpts": {"color": colour, "position": 0.9}} if label else {}
        return pg.InfiniteLine(position, angle=90, movable=False, pen=pen, **options)

    def folder_cache(self) -> FolderCache:
        if self.cache is None:
            from helab.utils.folder_cache import get_folder_cache
            from helab.utils.io_service import get_io_service
            self.cache = get_folder_cache(get_io_service())
        return self.cache

    def confirm(self, text: str, unsure: bool) -> bool:
        """Ask before saving (Cancel the default when the detection is unsure or the fall times
        differ). False if the plot closed meanwhile."""
        box = QMessageBox(QMessageBox.Icon.Question, "Use for this folder", text,
                          QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel, self)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel if unsure else QMessageBox.StandardButton.Save)
        answer = box.exec()
        return not sip.isdeleted(self) and answer == QMessageBox.StandardButton.Save

    @pyqtSlot()
    def use_for_folder(self) -> bool:
        """Save the detected t_r and origin as the folder's constants, once the user confirms; on the
        GUI thread, from what the cache holds in memory (a helper saves them). Whether it was set."""
        found = self.data.release if self.data is not None else None
        values = folder_values(found) if found is not None else {}
        if found is None or not values or not self.path:
            return False
        cache = self.folder_cache()
        folder = clean_layer(cache.effective_folder_constants(self.path))
        now = resolve(lab=clean_layer(cache.lab_constants), folder=folder)
        own = cache.folder_constants(self.path)
        replaces = "release_time" in own
        after = resolve(lab=clean_layer(cache.lab_constants),
                        folder={**{key: value for key, value in folder.items() if key != "release_time" or not replaces},
                                **values})
        assert self.data is not None
        differs = fall_differs(self.data.constants, after)
        text = confirmation_text(self.path, found, now, after, self.data.constants, replaces)
        if not self.confirm(text, found.unsure or differs):
            return False
        if not self._listening:
            cache.folderConstantsFailed.connect(self._failed)
            self._listening = True
        own = cache.folder_constants(self.path)  # Again: the question may have waited a while.
        if not cache.set_folder_constants(self.path, merged_values(own, found), owner=self.owner):
            return False
        session = cache.constants_session_only(self.path)
        self._say(f"Set for this folder · RAM only, for this session: {session}" if session
                  else "Set for this folder (Folder constants…)", bool(session))
        return True

    @pyqtSlot(str, str, str)
    def _failed(self, path: str, message: str, owner: str) -> None:
        if sip.isdeleted(self) or owner != self.owner:
            return
        self._say(f"⚠ Couldn't save the constants for this folder: {message}. Try again.", True)

    def _say(self, text: str, warn: bool) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {AMBER};" if warn else "")


class ReleaseTimePlot(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Release time",
            description="When the atoms left the trap (one cloud's arrival − the fall time) and the trap's XY "
                        "origin, with the shot bootstrap's error; Use for this folder saves them for the velocity "
                        "plots",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.release_time",
            version="1",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*PARAMETERS]

    def constant_keys(self, action_name: str) -> tuple[str, ...]:
        return CONSTANT_KEYS

    def live_policy(self, action_name: str) -> LivePolicy:
        # Live reruns skip the bootstrap (``LIVE_NOTE``): one detection, under a second on 500,000
        # events; still at most one every 5 s.
        return LivePolicy(min_delay=5.0)

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        lower, upper, _ = search_range(values)
        boots = int(values.get(N_BOOT.name, N_BOOT.default))
        search = search_text(lower, upper)
        settings = (shots_brief(values), f"search {search}" if search else "",
                    f"bootstrap {boots:,}" if boots else "fit SE only")
        return selection_text(view, values), " · ".join(part for part in settings if part)

    def describe_result(self, action_name: str, result: AnalysisResult) -> str:
        return str(result.found.get("brief", ""))

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        return list(search_range(values)[2])

    def result_found(self, action_name: str, data: Any) -> dict[str, Any]:
        """``release`` (the full ``ReleaseTime.as_record``), ``brief`` and ``record_lines``."""
        if not isinstance(data, ReleaseData) or data.release is None:
            return {}
        return {"release": data.release.as_record(), "brief": brief(data), "record_lines": record_lines(data),
                "constants": describe_constants(data.constants, CONSTANT_KEYS, every=True),
                # A Live rerun's result (no bootstrap) is no reuse for a deliberate run's.
                "reuse": {"bootstrap_skipped": data.live_skipped}}

    # Disk-cached results (R2): the shot bootstrap repeats the detection n_boot times.

    def cache_supported(self, action_name: str) -> bool:
        return True

    def cache_types(self, action_name: str) -> List[Declared]:
        return [ReleaseData, *result_types.COMMON]

    def cache_result(self, action_name: str, result: AnalysisResult) -> bool:
        data = result.data
        return isinstance(data, ReleaseData) and not data.live_skipped

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        values, view = context.parameters, context.view
        shots = select_shots(view, values)
        lower, upper, warnings = search_range(values)
        constants = context.resolved_constants
        if constants is None:  # Run without the runner: resolved here, the same way.
            constants = resolve_for_run(values, context.constants.get("lab"), context.constants.get("folder"))
        boots = int(values.get(N_BOOT.name, N_BOOT.default))
        per_shot = [txy(view.shots[shot]) for shot in shots]
        events = np.concatenate(per_shot) if per_shot else np.empty((0, 3))
        data = ReleaseData(tuple(shots), len(view.shots), len(events), constants, boots, search=(lower, upper),
                           warnings=warnings)
        if not len(events):
            return data
        times = events[:, 0]
        inside = np.isfinite(times)
        if lower is not None:
            inside &= times >= lower
        if upper is not None:
            inside &= times <= upper
        searched = events[inside]
        context.check()
        notes: tuple[str, ...] = ()
        # A Live rerun skips the bootstrap: n_boot detections each time would keep the one analysis
        # worker busy (31 s a run on 100 shots × 5,000 events). Rerun, or Live's end, runs it.
        skipped = context.live and boots > 0 and len(shots) >= 2
        if boots > 0 and len(shots) >= 2 and not skipped:
            found = bootstrap_release_time(per_shot, constants, lower, upper, n_boot=boots,
                                           cancelled=context.cancelled)
        else:
            found = detect_release_time(times, constants, lower, upper, positions=events[:, 1:3])
            if found.ok:
                notes = (LIVE_NOTE if skipped else
                         "one shot: no shot bootstrap, so the SE is the fit's alone (within run)" if boots
                         else "shot bootstrap off: the SE is the fit's alone (within run), without the shot-to-shot "
                              "jitter",)
        context.check()
        low = float(searched[:, 0].min()) if len(searched) else math.nan
        high = float(searched[:, 0].max()) if len(searched) else math.nan
        if found.ok:
            low = min(low, found.value.value)
        data = replace(data, searched=len(searched), release=found, notes=notes, live_skipped=skipped,
                       overview=_histogram(searched[:, 0], low, high, OVERVIEW_BINS))
        if not found.ok:
            return data
        zoom, curve = _close_up(searched[:, 0], found)
        x_hist, y_hist = _slices(searched, found)
        return replace(data, zoom=zoom, curve=curve, x_hist=x_hist, y_hist=y_hist)

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: ReleaseData = result.data
        reason = empty_text(data.total_shots, len(data.shots), data.events)
        if reason:
            return empty_pane(reason, parent)
        widget = ReleasePlot(parent)
        widget.show_data(result, data)
        return widget

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """A rerun (Live's next shots) draws in place, keeping zoom and pan; to or from an empty plot,
        anew."""
        data: ReleaseData = result.data
        if not isinstance(widget, ReleasePlot) or empty_text(data.total_shots, len(data.shots), data.events):
            return False
        widget.show_data(result, data)
        return True


__all__ = ["ReleaseData", "ReleasePlot", "ReleaseTimePlot"]
