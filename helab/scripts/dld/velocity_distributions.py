"""Velocity distributions (D8 part 2): the chosen shots' events as velocities at release, z up
(``helab.analysis.velocity``), as v_z, v_x and v_y histograms and, optionally, a v_x–v_y or v_x–v_z
density image.

What it converts: the chosen shots' events (Shots), less the Mask's (D9), inside the View range,
a box over T, X and Y (auto-crop or manual bounds, as the density images'), so a T window picks a
Bragg order, say. Velocities use the run's constants:

- **t_r**, the release time in DLD time, from ``release.layer_release_time``: a t_r set by hand,
  or a saved arrival of the cloud at rest t_a (the Release time plot's "Use for this folder") minus
  *this run's* fall time, so the cloud at rest is at v_z = 0 whatever h, g or t_f this plot uses.
  Never another plot's t_r. With neither set anywhere, t_r is detected in this run from the events
  in Search T (``release.detect_release_time``: one detection, the fit's SE, within run, no shot
  bootstrap), and the title says so in amber.
- the **trap origin** (x₀, y₀) that X and Y are measured from: the layers' (``trap_x``,
  ``trap_y``), else the one detected from the cloud at rest (the same detection), else (0, 0),
  assumed, said in amber.
- h, g and t_f (``velocity.effective_fall_distance``), the mass, ħ and the recoil wavelength for
  the recoil units (``recoil_wavelength``, a lab-level row, unconfirmed).

Units: mm/s (the default: a µK cloud's σ_v is tens of mm/s), m/s, or recoils, ħk/m (one photon's)
or 2ħk/m (one Bragg order). The optional Gaussian fits give each axis's centre and σ_v ± SE and the
temperature T = m σ_v² / k_B (the expansion's alone: the cloud's initial size is neglected). The
record holds t_r and where it came from, the origin and how it was found, and every fit.

Each histogram spans the shortest range holding 99 % of its velocities (Histogram range: keep),
saying how many fall outside: a dark count just after t_r has a velocity without bound (τ → 0).
A Live rerun keeps the detection and the auto-crop box of the plot's last run while the folder,
settings and constants are the same (``KeptRuns``), and says so; a run the user starts finds both
again. The newest shot can be highlighted, as in the T, X, Y histograms.
"""
from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass, field, replace
from typing import Any, List, Mapping, Optional, cast

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget

from helab.analysis.constant_layers import (ORIGIN_TEXT, constants_specs, describe_constants, origin_text,
                                           resolve_for_run)
from helab.analysis.dataset_view import DatasetView
from helab.analysis.display_units import (LENGTH_SCALE, T_SCALE, WIDTH_DIGITS, group_digits, length_text,
                                          number_text, range_text, time_text)
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.estimates import Estimate, finite_or_none, format_fixed
from helab.analysis.fits import FitResult, bin_centres, fit_histogram
from helab.analysis.follow import LivePolicy
from helab.analysis.masks import MASK_SPECS, all_masked_text, mask_brief, mask_from, mask_warnings, masked_text
from helab.analysis.parameters import ParameterSpec
from helab.analysis.physics import Origin, ResolvedConstants, temperature_estimate
from helab.analysis.plot_axes import GroupedAxis
from helab.analysis.plot_text import add_label, line_html, lines_html, notes_html, set_plot_title, short_note
from helab.analysis.release import OriginSource, ReleaseTime, detect_release_time, run_velocity_source
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import (SHOT_SPECS, keep_fraction, manual, manual_box, newest_brief, newest_colour,
                                      newest_events, newest_shot, newest_specs, range_brief, range_specs,
                                      range_warnings, select_shots, selection_text, shots_brief, shots_text)
from helab.analysis.stats import MAX_BINS, CropBox, crop_box, histogram, shortest_range
from helab.analysis.velocity import VELOCITY_AXES, recoil_velocity, valid_velocities
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.dld import group
from helab.scripts.dld.basic_plots import OverlayView, overlay_newest, update_newest
from helab.scripts.dld.density_images import (DECADES, GAMMA, LINEAR, SCALE, automatic_bins, colour_map,
                                                   display_image, viridis_lut)

Array = npt.NDArray[np.float64]

RANGE = range_specs(
    "The events converted are those inside a box over T, X and Y holding at least this share of them (found "
    "as the density images find theirs). Set T by hand to pick one cloud or Bragg order. 100 % converts "
    "every event.", fixed=True)
VELOCITY_GROUP = "Velocity"
MM_S, M_S, RECOIL, BRAGG = "mm/s", "m/s", "ħk/m", "2ħk/m"
UNIT = ParameterSpec("velocity_unit", "Unit", "choice", MM_S, choices=(MM_S, M_S, RECOIL, BRAGG),
                     group=VELOCITY_GROUP,
                     tip="mm/s or m/s, or recoils: ħk/m is one photon's recoil at the recoil wavelength (Constants: "
                         "≈ 92 mm/s for He* at 1,083 nm), 2ħk/m one Bragg order (counter-propagating beams).")
KEEP = ParameterSpec("velocity_keep", "Histogram range: keep", "float", 99.0, (50.0, 100.0), " %",
                     group=VELOCITY_GROUP,
                     tip="Each histogram spans the shortest velocity range holding this share of the events (the "
                         "titles say how many fall outside): a dark count arriving just after t_r has a huge "
                         "velocity (τ → 0), so the full extent hides the cloud. 100 % shows every velocity.")
BINS = ParameterSpec("bins", "Bins (0 = auto)", "int", 0, (0, MAX_BINS), group=VELOCITY_GROUP,
                     tip="Bins of each histogram, over its range (Histogram range). 0 = automatic (Freedman–"
                         "Diaconis: width 2·IQR·n^-1/3).")
FIT = ParameterSpec("fit", "Fit Gaussians", "bool", False, group=VELOCITY_GROUP,
                    tip="Fit each histogram with a Gaussian + offset: its centre and σ_v ± SE, and the temperature "
                        "T = m σ_v² / k_B (ideal gas, pure expansion: the cloud's initial size is neglected). The "
                        "offset is approximate: a dark count uniform in T, X and Y is not flat in velocity "
                        "(v_x = (x − x₀)/τ spreads it as 1/τ), so a strong background bends the fit.")
HIGHLIGHT, NEWEST_COLOUR = newest_specs(VELOCITY_GROUP)
DENSITY_GROUP = "Density"
OFF, VX_VY, VX_VZ = "off", "v_x–v_y", "v_x–v_z"
DENSITY_AXES = {VX_VY: (1, 2), VX_VZ: (1, 0)}  # (horizontal, vertical) as velocity columns (v_z, v_x, v_y)
DENSITY = ParameterSpec("density", "2D density", "choice", OFF, choices=(OFF, VX_VY, VX_VZ), group=DENSITY_GROUP,
                        tip="A density image of the same velocities below the histograms: v_x–v_y (the detector's "
                            "plane, square bins) or v_x–v_z (z up).")
MAX_DENSITY_BINS = 1000
DENSITY_BINS = ParameterSpec("density_bins", "Image bins per axis (0 = auto)", "int", 0, (0, MAX_DENSITY_BINS),
                             group=DENSITY_GROUP,
                             tip="Bins along each axis of the image; 0 = automatic (Freedman–Diaconis, at most 400).")
# The density images' colour compression (only the colours: the colour bar reads real counts).
COLOUR_SPECS = tuple(replace(spec, group=DENSITY_GROUP) for spec in (SCALE, GAMMA, DECADES))
CONSTANTS_PAGE = "Release & constants"
RELEASE_GROUP = "Release time"
SEARCH_MIN = ParameterSpec("search_min", "Search T from (0 = first)", "float", 0.0, (0.0, 100.0), " s",
                           group=RELEASE_GROUP, si=True, unit_prefix="m", page=CONSTANTS_PAGE,
                           tip="Only when no t_r or arrival is set (folder, lab or this plot): t_r is detected from "
                               "the tallest T peak between these times, the cloud taken as released at rest, and the "
                               "trap origin from it when none is set. 0 leaves that end open.")
SEARCH_MAX = ParameterSpec("search_max", "Search T to (0 = last)", "float", 0.0, (0.0, 100.0), " s",
                           group=RELEASE_GROUP, si=True, unit_prefix="m", page=CONSTANTS_PAGE,
                           tip="See Search T from. A From at or above To searches every event, and the plot says so.")
# The constants a plot may set for itself, and all it uses (ħ, the mass and k_B for the recoil
# unit and temperatures), so a lab or folder change of any of them marks the plot.
OWN_KEYS = ("fall_distance", "fall_time", "g", "release_time", "arrival_time", "trap_x", "trap_y",
            "recoil_wavelength")
CONSTANT_KEYS = (*OWN_KEYS, "mass", "k_B", "hbar")
CONSTANTS = tuple(constants_specs(OWN_KEYS, page=CONSTANTS_PAGE))
PARAMETERS = (*SHOT_SPECS, *RANGE, *MASK_SPECS, UNIT, KEEP, BINS, FIT, HIGHLIGHT, NEWEST_COLOUR, DENSITY, DENSITY_BINS, *COLOUR_SPECS, SEARCH_MIN,
              SEARCH_MAX, *CONSTANTS)

DETECTED_NOTE = ("t_r detected in this run (one detection, its SE within run, no shot bootstrap): the Release time "
                 "plot measures it over shots and saves the arrival for the folder (Use for this folder…)")
ASSUMED_NOTE = ("origin assumed (0, 0): no trap origin set or detected, so X and Y are measured from X = Y = 0 "
                "(set it: Release time plot › Use for this folder…, or this plot's Constants)")
# A detection note kept in the record only: said of most clean clouds, it isn't a warning.
RECORD_ONLY = ("XY origin: background share unknown",)
COLOUR = (40, 90, 170)
FIT_COLOUR = (0, 0, 0)
ZERO_COLOUR = (120, 120, 120)

Histogram = tuple[Array, Array]  # (edges in m/s, counts)


@dataclass(frozen=True)
class AxisData:
    """One velocity axis: its histogram (edges in m/s), how its bins were chosen, and its fit."""
    axis: str  # "v_z", "v_x" or "v_y"
    edges: Array
    counts: Array
    automatic: bool
    fit: FitResult | None = field(default=None, compare=False)
    temperature: Estimate = Estimate(math.nan)
    outside: int = 0  # velocities outside the histogram's range (Histogram range: keep)
    newest: Array | None = field(default=None, compare=False)  # the highlighted shot's counts in these bins

    @property
    def total(self) -> int:
        return int(self.counts.sum())

    @property
    def sigma(self) -> Estimate:
        """σ_v (m/s), positive."""
        if self.fit is None or not self.fit.ok:
            return Estimate(math.nan)
        sigma = self.fit["sigma"]
        return Estimate(abs(sigma.value), sigma.se)


@dataclass(frozen=True)
class Density:
    mode: str  # VX_VY or VX_VZ
    edges_h: Array  # m/s
    edges_v: Array
    image: Array  # (horizontal bins, vertical bins), counts
    automatic: bool
    outside: int = 0  # velocities outside the image (the histograms' ranges)


@dataclass(frozen=True)
class VelocityData:
    shots: tuple[int, ...]
    total_shots: int
    events: int  # in the chosen shots, after the mask
    masked: int  # events the mask took out
    constants: ResolvedConstants
    unit: str
    factor: float  # m/s per display unit (``unit_factor``)
    search: tuple[float | None, float | None] = (None, None)
    release: ReleaseTime | None = None  # the t_r used (from the layers, or detected here)
    release_source: str = ""  # "lab", "folder", "plot" or "detected"
    release_from: str = ""  # "release_time" (by hand), "arrival_time" (saved t_a − t_f) or "data"
    detection: ReleaseTime | None = None  # this run's detection, when it made one
    origin: tuple[float, float] = (0.0, 0.0)  # (x₀, y₀) (m)
    origin_how: OriginSource = "assumed"
    origin_source: str = ""  # the layer that set it ("lab", "folder", "plot"), for "manual"
    box: CropBox | None = None  # the view range (None: not reached)
    converted: int = 0  # events in the view range
    invalid: int = 0  # of them, with no velocity (arrived before t_r, or not finite)
    axes: tuple[AxisData, ...] = ()
    density: Density | None = None
    fitted: bool = False
    warnings: tuple[str, ...] = ()  # settings not followed as given
    # A Live rerun that kept the detection and view range of an earlier run of this plot
    # (``Kept``): that run's revision; 0 when this run found its own.
    kept_from: int = 0
    newest_shot: int | None = None  # the highlighted shot (None: off)
    colour: tuple[int, int, int] = (214, 39, 40)

    @property
    def failure(self) -> str:
        """Why there are no velocities: no release time ("" when there is one)."""
        if self.release is None:
            return ""
        return self.release.failure

    @property
    def velocities(self) -> int:
        return self.converted - self.invalid

    def notes(self, record: bool = False) -> tuple[str, ...]:
        """Amber notes, in order: an assumed origin, a detected t_r, the detection's own notes, events
        without a velocity, the constants' notes. The title leaves out the detection's XY origin
        notes when the origin wasn't detected, and ``RECORD_ONLY`` ones always; ``record`` keeps
        them all."""
        notes: list[str] = []
        if self.origin_how == "assumed":
            notes.append(ASSUMED_NOTE)
        elif self.origin_how == "detected (unsure)":
            notes.append("origin detected from an unsure cloud: another peak may be the one at rest")
        if self.release_source == "detected":
            notes.append(DETECTED_NOTE)
        if self.detection is not None and (self.release_source == "detected" or self.origin_how != "manual"):
            notes.extend(note for note in self.detection.notes
                         if record or not (note.startswith(RECORD_ONLY)
                                           or (self.origin_how == "manual" and note.startswith("XY origin"))))
        if self.release is not None and self.release_source != "detected":
            notes.extend(note for note in self.release.notes if not note.startswith("t_r from the saved arrival"))
        if self.invalid:
            notes.append(f"{self.invalid:,} event{'' if self.invalid == 1 else 's'} in range arrived before t_r (or "
                         "aren't finite): no velocity")
        notes.extend(self.constants.notes)
        return tuple(notes)


# Units and text


def unit_factor(unit: str, constants: ResolvedConstants) -> float:
    """One display ``unit`` in m/s: 1e-3 for mm/s, 1 for m/s, ħk/m or 2ħk/m (the constants' recoil
    wavelength and mass); nan for a recoil without a usable wavelength."""
    if unit == MM_S:
        return 1e-3
    if unit == RECOIL:
        return recoil_velocity(constants)
    if unit == BRAGG:
        return 2 * recoil_velocity(constants)
    return 1.0


def velocity_text(value: float, data: VelocityData, digits: int = WIDTH_DIGITS) -> str:
    """``45.7 mm/s``, ``−0.5 ħk/m``: a velocity (m/s) in the plot's unit."""
    return f"{number_text(value / data.factor, digits)} {data.unit}"


def estimate_velocity(estimate: Estimate, data: VelocityData) -> str:
    """``(45.7 ± 0.3) mm/s``: a velocity ± SE (m/s) in the plot's unit, the SE to 2 digits."""
    if not math.isfinite(estimate.se):
        return velocity_text(estimate.value, data)
    return group_digits(format_fixed(estimate.value / data.factor, estimate.se / data.factor, "pm", data.unit, 2))


def axis_title(axis: str, unit: str) -> str:
    """``v_z (mm/s)``."""
    return f"{axis} ({unit})"


def search_range(values: Mapping[str, Any]) -> tuple[float | None, float | None, tuple[str, ...]]:
    """Search T's ends (None: open) and a warning when they cross."""
    lower = float(values.get(SEARCH_MIN.name, 0.0)) or None
    upper = float(values.get(SEARCH_MAX.name, 0.0)) or None
    if lower is not None and upper is not None and lower >= upper:
        return None, None, (f"Search T: from {time_text(lower)} is at or above to {time_text(upper)}: "
                            "searching every event",)
    return lower, upper, ()


def layer_text(source: str) -> str:
    """``folder``, ``this plot``: a layer's name as the settings show it."""
    return ORIGIN_TEXT.get(cast(Origin, source), source)


def release_source_text(data: VelocityData) -> str:
    """Where t_r came from: ``folder: saved arrival t_a − this run's t_f``, ``this plot, by hand``,
    ``detected in this run (within run)``."""
    if data.release_source == "detected":
        return "detected in this run, within run"
    where = layer_text(data.release_source)
    if data.release_from == "arrival_time":
        return f"{where}: saved arrival t_a − this run's t_f"
    return f"{where}, by hand"


def release_line(data: VelocityData) -> str:
    """``t_r 20,031.2 ms (folder: saved arrival t_a − this run's t_f) · t_f 416.0908 ms (h 848 mm)``."""
    found = data.release
    if found is None:
        return ""
    if not found.ok:
        return f"⚠ no release time: {found.failure}"
    value = (group_digits(format_fixed(found.value.value * T_SCALE, found.value.se * T_SCALE, "pm", "ms", 2))
             if math.isfinite(found.value.se) else time_text(found.value.value))
    constants = data.constants
    fall = (f"h {length_text(constants.fall_distance)}" if constants.origins["fall_time"] == "derived"
            else origin_text(constants, "fall_time"))
    return f"t_r {value} ({release_source_text(data)}) · t_f {time_text(constants.fall_time)} ({fall})"


def origin_line(data: VelocityData) -> str:
    """``origin (3, −2) mm (folder)``, ``origin (3.01, −1.99) mm (detected)``; "" when assumed
    (``ASSUMED_NOTE`` says so, in amber)."""
    if data.origin_how == "assumed":
        return ""
    x, y = (number_text(axis * LENGTH_SCALE, WIDTH_DIGITS) for axis in data.origin)
    how = layer_text(data.origin_source) if data.origin_how == "manual" else data.origin_how
    return f"origin ({x}, {y}) mm ({how})"


def titles(result: AnalysisResult, data: VelocityData) -> tuple[str, ...]:
    """The figure's title lines: what was converted, t_r and t_f, the origin, then each warning and
    note (amber, shortened: the record has them whole)."""
    box = data.box
    where = (f"{data.converted:,} of {data.events:,} events in range" if box is not None
             else f"{data.events:,} events")
    first = f"{result.input.short()} · {shots_text(data.shots, data.total_shots)} · {where}{masked_text(data.masked)}"
    parts = [release_line(data), origin_line(data)]
    if data.unit in (RECOIL, BRAGG):
        parts.append(f"{data.unit} = {number_text(data.factor * 1e3, 5)} mm/s")
    second = " · ".join(part for part in parts if part)
    if second.startswith("⚠"):  # No release time: the origin and unit after it are moot.
        second = parts[0]
    kept = kept_text(data)
    return (first, second, *((kept,) if kept else ()), *(f"⚠ {warning}" for warning in data.warnings),
            *(f"⚠ {short_note(note)}" for note in data.notes()))


def fit_text(item: AxisData, data: VelocityData) -> str:
    """``centre (0.1 ± 0.3) mm/s · σ_v (45.7 ± 0.3) mm/s · T (1.52 ± 0.02) µK``, or why no fit."""
    fit = item.fit
    if fit is None:
        return ""
    if not fit.ok:
        return f"⚠ Gaussian fit failed: {fit.failure}"
    return (f"centre {estimate_velocity(fit['centre'], data)} · σ_v {estimate_velocity(item.sigma, data)} · "
            f"T {item.temperature.text(unit='K')}")


def axis_heading(item: AxisData, data: VelocityData) -> str:
    """``v_z · 80 bins (auto) · 12,345 events · 120 outside``."""
    outside = f" · {item.outside:,} outside" if item.outside else ""
    newest = (f" · shot {data.newest_shot}: {int(item.newest.sum()):,} (right axis)"
              if data.newest_shot is not None and item.newest is not None else "")
    return (f"{item.axis} · {len(item.counts):,} bins ({'auto' if item.automatic else 'set'}) · "
            f"{item.total:,} events{outside}{newest}")


def kept_text(data: VelocityData) -> str:
    """``Live: t_r detection and view range kept from rev 3 (found again on a deliberate run)``."""
    if not data.kept_from:
        return ""
    what = " and ".join(part for part in (
        "t_r detection" if data.detection is not None else "", "view range" if data.box is not None else "") if part)
    return f"Live: {what or 'nothing'} kept from rev {data.kept_from} (found again on a run you start)"


def brief(data: VelocityData) -> str:
    """For the settings line: ``t_r 20,031.2 ms (folder) · origin (3, −2) mm (folder)``."""
    found = data.release
    if found is None or not found.ok:
        return ""
    source = "detected" if data.release_source == "detected" else layer_text(data.release_source)
    origin = "origin assumed (0, 0)" if data.origin_how == "assumed" else origin_line(data)
    return f"t_r {time_text(found.value.value)} ({source}) · {origin}"


def record_lines(data: VelocityData) -> list[str]:
    """t_r and where it came from, the origin, each fit, and every note whole."""
    found = data.release
    lines: list[str] = []
    if found is not None and found.ok:
        lines.append(f"Release time {release_line(data)}")
        if math.isfinite(found.arrival.value):
            lines.append(f"Arrival at rest t_a {time_text(found.arrival.value)}")
    elif found is not None:
        lines.append(f"No release time: {found.failure}")
    if data.origin_how == "assumed":
        lines.append("Origin assumed (0, 0)")
    else:
        x, y = (length_text(axis) for axis in data.origin)
        lines.append(f"Origin ({x}, {y}): {data.origin_how}"
                     + (f" ({layer_text(data.origin_source)})" if data.origin_how == "manual" else ""))
    if data.kept_from:
        lines.append(kept_text(data))
    if data.unit in (RECOIL, BRAGG):
        lines.append(f"{data.unit} = {number_text(data.factor * 1e3, 7)} mm/s "
                     f"(λ {number_text(data.constants.recoil_wavelength * 1e9, 7)} nm)")
    for item in data.axes:
        text = fit_text(item, data)
        if text:
            chi2 = item.fit.reduced_chi2 if item.fit is not None else math.nan
            extra = f" · reduced χ² {chi2:.3g}" if math.isfinite(chi2) else ""
            notes = f" · notes: {'; '.join(item.fit.notes)}" if item.fit is not None and item.fit.notes else ""
            lines.append(f"Fit {item.axis}: {text}{extra}{notes}")
    lines += [f"Note: {note}" for note in (*data.warnings, *data.notes(record=True))]
    return lines


def record(data: VelocityData) -> dict[str, Any]:
    """Strict JSON for the result's ``found``: t_r and its source, the detection, the origin, the
    fits (in m/s, with T), and the record's lines."""
    found = data.release
    fits = {item.axis: {"fit": item.fit.as_record(), "sigma_v": item.sigma.as_record(),
                        "temperature": item.temperature.as_record()}
            for item in data.axes if item.fit is not None}
    return {
        "release": None if found is None else {
            "value": found.value.as_record(), "source": data.release_source, "from": data.release_from,
            "error": found.error, "arrival": found.arrival.as_record(), "failure": found.failure,
            "notes": list(found.notes)},
        "detection": data.detection.as_record() if data.detection is not None else None,
        "origin": {"x": data.origin[0], "y": data.origin[1], "how": data.origin_how, "source": data.origin_source},
        "unit": data.unit, "unit_m_per_s": finite_or_none(data.factor), "converted": data.converted,
        "invalid": data.invalid, "outside": {item.axis: item.outside for item in data.axes},
        "fits": fits, "brief": brief(data), "record_lines": record_lines(data),
        # What a Live rerun kept from an earlier run (its revision; 0: found its own).
        "reuse": {"kept_from": data.kept_from},
        "constants": describe_constants(data.constants, CONSTANT_KEYS, every=True)}


def empty_reason(data: VelocityData) -> str:
    """Why there is nothing to draw ("" when there is)."""
    text = empty_text(data.total_shots, len(data.shots), data.events + data.masked)
    if text:
        return text
    if not data.events:
        return all_masked_text(data.masked)
    if data.failure:
        return (f"No release time: {data.failure}. Set t_r or the arrival at rest for this folder (Release time "
                "plot › Use for this folder…) or in this plot's Constants")
    if data.box is not None and not data.converted:
        warned = "".join(f" · ⚠ {warning}" for warning in data.warnings)
        return (f"None of the {data.events:,} events in the chosen shots is inside the view range "
                f"(View range settings){warned}")
    if not data.velocities:
        return (f"None of the {data.converted:,} events in the view range arrived after t_r "
                f"{time_text(data.release.value.value) if data.release is not None else ''}: no velocities")
    return ""


# Computation


def _span(values: Array, keep: float) -> tuple[float, float]:
    """The shortest range holding ``keep`` of ``values`` (all of them at 1), widened when empty."""
    low, high = shortest_range(values, keep)
    if not high > low:
        low, high = low - 1e-3, high + 1e-3
    return low, high


def _density(mode: str, velocities: Array, bins: int, spans: tuple[tuple[float, float], ...]) -> Density:
    """The image over the histograms' ranges (``spans``, per velocity column)."""
    h, v = DENSITY_AXES[mode]
    along_h, along_v = velocities[:, h], velocities[:, v]
    span_h, span_v = spans[h], spans[v]
    counts_h, counts_v = (bins, bins) if bins else automatic_bins(along_h, along_v, span_h, span_v, mode == VX_VY)
    image, edges_h, edges_v = np.histogram2d(along_h, along_v, bins=(counts_h, counts_v), range=(span_h, span_v))
    return Density(mode, edges_h, edges_v, image, bins == 0, len(velocities) - int(image.sum()))


def _axis(axis: str, values: Array, bins: int, fit: bool, constants: ResolvedConstants,
          span: tuple[float, float], newest: Array | None) -> AxisData:
    item = histogram(values, axis, 1.0, bins, bounds=span)
    counts = item.counts.astype(np.float64)
    fresh = None if newest is None else np.histogram(newest, bins=item.edges)[0].astype(np.float64)
    data = AxisData(axis, item.edges, counts, item.automatic_bins, outside=item.outside, newest=fresh)
    if not fit:
        return data
    result = fit_histogram(bin_centres(item.edges), counts, "gaussian", edges=item.edges)
    data = replace(data, fit=result)
    if not result.ok:
        return data
    return replace(data, temperature=temperature_estimate(data.sigma, constants))


@dataclass(frozen=True)
class Kept:
    """What a plot's last run found that a Live rerun keeps: the detection (when it made one) and
    the auto-crop box (when it cropped), for ``key`` (the folder, the settings and the constants)
    at ``revision``."""
    key: str
    revision: int
    detection: ReleaseTime | None
    box: CropBox | None


class KeptRuns:
    """Each plot's ``Kept`` (by ``AnalysisContext.owner``), thread-safe; dropped when the plot
    closes. A Live rerun of the same folder, settings and constants keeps the detection and the
    view range, the costly steps (on 5 M events: crop 7.7 s, detection 4.2 s, of 11–19 s), and
    says so; a run the user starts finds both again."""

    def __init__(self) -> None:
        self._items: dict[str, Kept] = {}
        self._lock = threading.Lock()

    def get(self, owner: str, key: str) -> Kept | None:
        with self._lock:
            found = self._items.get(owner)
        return found if found is not None and found.key == key else None

    def put(self, owner: str, kept: Kept) -> None:
        if owner:
            with self._lock:
                self._items[owner] = kept

    def drop(self, owner: str) -> None:
        with self._lock:
            self._items.pop(owner, None)


KEPT = KeptRuns()


def kept_key(context: AnalysisContext, constants: ResolvedConstants) -> str:
    """The folder, every setting and the constants a Live rerun's kept steps must match."""
    return json.dumps([context.view.identity.source_path, context.view.identity.root_key,
                       dict(context.parameters), constants.as_record(CONSTANT_KEYS)], sort_keys=True, default=repr)


# The plot


class VelocityWidget(pg.GraphicsLayoutWidget):  # type: ignore[misc]
    """The title, one histogram per velocity axis and, with ``density``, the image and its colour bar;
    a rerun (Live) sets their data in place, keeping zoom and pan (``show_data``). ``key``: whether
    fitted, which density and whether the newest shot is highlighted, which a rerun must keep to
    draw in place. The newest shot is drawn as the T, X, Y histograms draw it: scaled to the
    histogram's total, its real counts on a right axis in its colour."""

    def __init__(self, key: tuple[bool, str, bool], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setBackground("w")
        self.key = key
        fitted, density, highlighted = key
        span = 2 if density != OFF else 1
        layout: Any = self.ci
        self.title = add_label(layout, row=0, col=0, colspan=span)
        self.plots: list[Any] = []
        self.bars: list[Any] = []
        self.fit_lines: list[Any] = []
        self.scaled: list[Any] = []  # the newest shot at the histogram's scale, transparent (highlight)
        self.newest_views: list[OverlayView] = []  # Kept with the widget (they live in its scene).
        for row, axis in enumerate(VELOCITY_AXES, start=1):
            plot = layout.addPlot(row=row, col=0, colspan=span,
                                  axisItems={"bottom": GroupedAxis("bottom"), "left": GroupedAxis("left")})
            set_plot_title(plot, "")
            plot.setLabel("left", "Events per bin")
            plot.showGrid(x=True, y=True, alpha=0.3)
            plot.addItem(pg.InfiniteLine(0.0, angle=90, movable=False,
                                         pen=pg.mkPen(ZERO_COLOUR, width=1, style=pg.QtCore.Qt.PenStyle.DashLine)))
            bars = pg.PlotDataItem([0.0, 1.0], [0.0], stepMode="center", fillLevel=0, pen=pg.mkPen(COLOUR),
                                   brush=(*COLOUR, 90))
            plot.addItem(bars)
            self.bars.append(bars)
            line = None
            if fitted:
                line = pg.PlotDataItem([], [], connect="finite", pen=pg.mkPen(FIT_COLOUR, width=2))
                plot.addItem(line)
            self.fit_lines.append(line)
            if highlighted:
                # Transparent: keeps the plot's own range holding the overlay (as the T, X, Y histograms).
                scaled = pg.PlotDataItem([0.0, 1.0], [np.nan], stepMode="center", connect="finite",
                                         pen=pg.mkPen((0, 0, 0, 0)))
                plot.addItem(scaled)
                self.scaled.append(scaled)
            self.plots.append(plot)
        self.density_plot: Any = None
        self.image: Any = None
        self.bar: Any = None
        self.scale_key: tuple[str, float, int] = ("", 0.0, 0)
        if density != OFF:
            self.density_plot = layout.addPlot(row=len(VELOCITY_AXES) + 1, col=0,
                                               axisItems={"bottom": GroupedAxis("bottom"), "left": GroupedAxis("left")})
            set_plot_title(self.density_plot, "")
            self.density_plot.setAspectLocked(density == VX_VY)
            self.image = pg.ImageItem(axisOrder="col-major")
            self.image.setLookupTable(viridis_lut())
            self.density_plot.addItem(self.image)

    def show_data(self, result: AnalysisResult, data: VelocityData) -> None:
        self.title.setText(lines_html(titles(result, data)))
        for index, (item, plot, bars, line) in enumerate(zip(data.axes, self.plots, self.bars, self.fit_lines)):
            heading = line_html(axis_heading(item, data))
            text = fit_text(item, data)
            notes = list(item.fit.notes) if item.fit is not None else []
            if text.startswith("⚠"):
                notes, text = [text[2:], *notes], ""
            set_plot_title(plot, heading + ("<br>" + line_html(text) if text else "") + notes_html(notes, short=True))
            plot.setLabel("bottom", axis_title(item.axis, data.unit))
            edges = item.edges / data.factor
            bars.setData(edges, item.counts)
            if line is not None:
                if item.fit is not None and item.fit.ok:
                    x = np.linspace(item.edges[0], item.edges[-1], 400)
                    line.setData(x / data.factor, item.fit.evaluate(x))
                else:
                    line.setData([], [])
            if self.key[2] and index < len(self.scaled):
                self._show_newest(index, plot, edges, item, data)
        if self.density_plot is not None and data.density is not None:
            self._show_density(result, data, data.density)

    def _show_newest(self, index: int, plot: Any, edges: Array, item: AxisData, data: VelocityData) -> None:
        counts = item.newest if item.newest is not None else np.zeros(len(item.counts))
        scale = float(item.counts.sum()) / float(counts.sum()) if counts.sum() > 0 else 1.0
        self.scaled[index].setData(edges, counts * scale)
        name = f"shot {data.newest_shot}"
        whole = counts.astype(np.int64)
        if index < len(self.newest_views):
            update_newest(plot, self.newest_views[index], edges, whole, scale, data.colour, False, name)
        else:
            self.newest_views.append(overlay_newest(plot, edges, whole, scale, data.colour, False, name))

    def _show_density(self, result: AnalysisResult, data: VelocityData, density: Density) -> None:
        values = result.parameters
        h, v = DENSITY_AXES[density.mode]
        names = VELOCITY_AXES
        bins = density.image.shape
        outside = f" · {density.outside:,} outside" if density.outside else ""
        set_plot_title(self.density_plot, line_html(
            f"{density.mode} · {bins[0]:,} × {bins[1]:,} bins ({'auto' if density.automatic else 'set'}){outside}"))
        self.density_plot.setLabel("bottom", axis_title(names[h], data.unit))
        self.density_plot.setLabel("left", axis_title(names[v], data.unit))
        peak = float(density.image.max()) if density.image.size else 0.0
        levels = (0.0, peak if peak > 0 else 1.0)
        key = (str(values.get(SCALE.name, LINEAR)), float(values.get(GAMMA.name, GAMMA.default)),
               int(values.get(DECADES.name, DECADES.default)))
        self.image.setImage(display_image(density.image, peak, *key), levels=(0.0, 1.0))
        eh, ev = density.edges_h / data.factor, density.edges_v / data.factor
        self.image.setRect(pg.QtCore.QRectF(eh[0], ev[0], eh[-1] - eh[0], ev[-1] - ev[0]))
        label = "Events per bin" + ("" if key[0] == LINEAR else f" · colours {key[0]}, values linear")
        if self.bar is None:
            self.bar = pg.ColorBarItem(values=levels, colorMap=colour_map(*key), interactive=False, label=label)
            self.ci.addItem(self.bar, row=len(VELOCITY_AXES) + 1, col=1)
        else:
            if key != self.scale_key:
                self.bar.setColorMap(colour_map(*key))
            self.bar.setLevels(levels)
            self.bar.getAxis("left").setLabel(label)
        self.scale_key = key


def widget_key(result: AnalysisResult, data: VelocityData) -> tuple[bool, str, bool]:
    return data.fitted, data.density.mode if data.density is not None else OFF, data.newest_shot is not None


class VelocityDistributions(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Velocity distributions",
            description="The events' velocities at release (z up): v_z, v_x and v_y histograms in mm/s, m/s or "
                        "recoils, with optional Gaussian fits and temperatures, and a 2D density",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.velocity_distributions",
            version="1",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*PARAMETERS]

    def constant_keys(self, action_name: str) -> tuple[str, ...]:
        return CONSTANT_KEYS

    def live_policy(self, action_name: str) -> LivePolicy:
        # Measured on 5 M events (40 shots, 4 cores): a first run takes 9–16 s (crop 7.7 s, t_r
        # detection 4.2 s); a Live rerun keeps both (``KeptRuns``) and takes 2.4–4.2 s (the
        # conversion, three shortest-range sorts, the fits and the density). One analysis worker
        # serves every plot, so 5 s between runs leaves the others room (the Release time plot's wait).
        return LivePolicy(min_delay=5.0)

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        bins = int(values.get(BINS.name, 0))
        density = str(values.get(DENSITY.name, OFF))
        lower, upper, _ = search_range(values)
        search = (range_text("T", lower, upper) if lower is not None and upper is not None
                  else f"T from {time_text(lower)}" if lower is not None
                  else f"T to {time_text(upper)}" if upper is not None else "")
        keep = float(values.get(KEEP.name, KEEP.default))
        settings = (shots_brief(values), range_brief(values, fixed=True), mask_brief(values), str(values.get(UNIT.name, MM_S)),
                    f"histograms {number_text(keep, 3)} %" if keep < 100 else "histograms 100 %",
                    f"bins {bins:,}" if bins else "bins auto", newest_brief(values), "fit Gaussians" if values.get(FIT.name) else "",
                    f"density {density}" if density != OFF else "", f"search {search}" if search else "")
        return selection_text(view, values), " · ".join(part for part in settings if part)

    def describe_result(self, action_name: str, result: AnalysisResult) -> str:
        return str(result.found.get("brief", ""))

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        return [*range_warnings(values), *mask_warnings(values), *search_range(values)[2]]

    def result_found(self, action_name: str, data: Any) -> dict[str, Any]:
        return record(data) if isinstance(data, VelocityData) and data.release is not None else {}

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        values, view = context.parameters, context.view
        shots = select_shots(view, values)
        mask = mask_from(values)  # Circles that can't be read fail the run, saying which.
        events, masked = mask.apply(view.events(shots))
        constants = context.resolved_constants
        if constants is None:  # Run without the runner: resolved here, the same way.
            constants = resolve_for_run(values, context.constants.get("lab"), context.constants.get("folder"))
        unit = str(values.get(UNIT.name, MM_S))
        lower, upper, search_warnings = search_range(values)
        warnings = (*range_warnings(values), *search_warnings)
        factor = unit_factor(unit, constants)
        if not (math.isfinite(factor) and factor > 0):
            warnings += (f"the recoil wavelength gives no {unit}: using mm/s",)
            unit, factor = MM_S, 1e-3
        newest = newest_shot(values, shots)
        data = VelocityData(tuple(shots), len(view.shots), len(events), masked, constants, unit, factor,
                            (lower, upper), warnings=warnings, fitted=bool(values.get(FIT.name)),
                            newest_shot=newest, colour=newest_colour(values))
        if not len(events):
            return data
        context.check()
        # A Live rerun keeps the detection and the auto-crop box of this plot's last run when the
        # folder, settings and constants are the same (``KeptRuns``); any other run finds its own.
        key = kept_key(context, constants)
        kept = KEPT.get(context.owner, key) if context.live else None
        # t_r: the layers' (by hand, or a saved arrival − this run's t_f), else detected here; the
        # origin: the layers', else detected (the same detection), else assumed.

        def detect() -> ReleaseTime:
            if kept is not None and kept.detection is not None:
                return kept.detection
            found = detect_release_time(events[:, 0], constants, lower, upper, positions=events[:, 1:3])
            context.check()
            return found
        source = run_velocity_source(constants, detect)
        release, detection, origin = source.release, source.detection, source.origin
        data = replace(data, release=release, release_source=source.release_source,
                       release_from=source.release_from, detection=detection, origin=origin,
                       origin_how=source.origin_how, origin_source=source.origin_source)
        if not release.ok:
            return data
        cropped = not manual(values)
        if cropped and kept is not None and kept.box is not None:
            box = kept.box
        else:
            box = crop_box(events, keep_fraction(values), context.cancelled) if cropped else manual_box(events, values)
        context.check()
        reused = kept is not None and ((detection is not None and detection is kept.detection)
                                       or (cropped and box is kept.box))
        if not reused:
            KEPT.put(context.owner, Kept(key, view.revision, detection, box if cropped else None))
        inside = events[box.contains(events)] if box.kept else np.empty((0, 3))
        good, invalid = valid_velocities(inside, release.value.value, constants, origin)
        data = replace(data, box=box, converted=len(inside), invalid=invalid,
                       kept_from=kept.revision if reused and kept is not None else 0)
        if not len(good):
            return data
        fresh = None
        if newest is not None:
            shot_events = mask.apply(newest_events(view, newest))[0]
            shot_inside = shot_events[box.contains(shot_events)] if box.kept else np.empty((0, 3))
            fresh = valid_velocities(shot_inside, release.value.value, constants, origin)[0]
        bins = int(values.get(BINS.name, 0))
        keep = float(values.get(KEEP.name, KEEP.default)) / 100
        axes, spans = [], []
        for column, axis in enumerate(VELOCITY_AXES):
            context.check()
            column_values = np.ascontiguousarray(good[:, column])
            span = _span(column_values, keep)
            spans.append(span)
            axes.append(_axis(axis, column_values, bins, data.fitted, constants, span,
                              None if fresh is None else fresh[:, column]))
        density = None
        mode = str(values.get(DENSITY.name, OFF))
        if mode in DENSITY_AXES:
            context.check()
            density = _density(mode, good, int(values.get(DENSITY_BINS.name, 0)), tuple(spans))
        return replace(data, axes=tuple(axes), density=density)

    def plot_closed(self, action_name: str, owner: str, path: str) -> None:
        """Forget what the plot's last run kept for Live reruns."""
        KEPT.drop(owner)

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: VelocityData = result.data
        reason = empty_reason(data)
        if reason:
            return empty_pane(reason, parent)
        widget = VelocityWidget(widget_key(result, data), parent)
        widget.show_data(result, data)
        return cast(QWidget, widget)

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """A rerun (Live's next shots) draws in place, keeping zoom and pan, while the fits and the
        density stay as they were; to or from an empty plot, or otherwise, anew."""
        data: VelocityData = result.data
        if (not isinstance(widget, VelocityWidget) or empty_reason(data)
                or widget.key != widget_key(result, data)):
            return False
        widget.show_data(result, data)
        return True


__all__ = ["VelocityData", "VelocityDistributions", "VelocityWidget"]
