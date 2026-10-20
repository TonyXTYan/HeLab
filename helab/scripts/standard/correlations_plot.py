"""Correlations (D12, D13): g² of pairs of atoms in velocity space, in-shot pairs over between-shot
pairs (``helab.analysis.correlations``), with the shot bootstrap's errors and a peak fit.

Three kinds: **1D** g²(Δv along one axis, the other two components within ± a window), **radial**
g²(|Δv|), and **back-to-back** (D13) on either: g²(v₁ + v₂ − 2v₀) about a source velocity v₀ (0,
the source at rest at the trap, or set here). A halo's per-shot centring isn't built: **Re-centre
each shot** moves each shot's robust centre to 0 first (for back-to-back, v₀ is then relative to
each shot's centre), which also takes out pointing jitter (the numerics' notes).

The events: the chosen shots (Shots), the mask's (Mask), inside the plot's own view range in TXY
(auto-crop or manual; an auto-crop box is kept from this plot's earlier run while the new one fits
inside it, so Live's next shots keep it), then velocities (``velocity.txy_to_velocity``) with
this run's constants. The release time t_r comes from the layers (``release.layer_release_time``:
set by hand, or a saved arrival − this run's t_f), else it is detected in the run (one detection
of the chosen shots' events within Release search T, its within-run SE, noted); the trap origin
from the layers, else the same detection's, else assumed (0, 0) (said in amber). Never another
plot's t_r. A detection within its SE of this plot's previous one keeps the previous one, so the
held pair counts stay valid (noted).

Live: each plot holds one ``PairCounts`` and one in-shot cache (``_PlotState``, by the plot's
owner), so a rerun counts only the new shots against the held ones; the spec's ``events_key``
holds everything that changes the velocities but not the TXY fingerprints (t_r, h, g, the
origin, the mask's circles, the view-range box), so a change there starts again. A time budget
stops adding shots; the result then covers the shots counted (noted) and the next run (Rerun, or
Live's next shots) continues. ``plot_closed`` drops the plot's state; another folder starts anew.

Settings in velocity are in mm/s whatever the unit the plot is drawn in (mm/s, ħk or 2ħk:
proposed, for Tony), so a unit change redraws without counting again.
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import Any, List, Mapping, Optional

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from helab.analysis import trends
from helab.analysis.constant_layers import constants_specs, describe_constants, resolve_for_run
from helab.analysis.correlations import (Baseline, CacheKey, CorrelationResult, CorrelationSpec, InShot, PairCounts,
                                         ShotEvents, correlate, linear_edges, radial_edges)
from helab.analysis.dataset_view import DatasetView, Events, txy
from helab.analysis.display_units import WIDTH_DIGITS, length_text, number_text, time_text
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.estimates import Estimate, finite_or_none
from helab.analysis.follow import LivePolicy
from helab.analysis.masks import (MASK_SPECS, Mask, all_masked_text, mask_brief, mask_from, mask_warnings,
                                  masked_text)
from helab.analysis.parameters import ParameterSpec
from helab.analysis.physics import ResolvedConstants
from helab.analysis.plot_axes import grouped_axes
from helab.analysis.plot_text import add_label, lines_html, short_note
from helab.analysis.release import (ReleaseTime, detect_release_time, layer_origin,
                                    layer_release_time, velocity_origin)
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import (SHOT_SPECS, keep_fraction, manual, manual_box, range_brief, range_specs,
                                      range_warnings, select_shots, selection_text, shots_brief, shots_text)
from helab.analysis.stats import CropBox, crop_box
from helab.analysis.velocity import (RECOIL_WAVELENGTH, RECOIL_WAVELENGTH_UNCONFIRMED, VELOCITY_AXES,
                                     effective_fall_distance, txy_to_velocity, unit_velocity)
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.standard import group

Array = npt.NDArray[np.float64]
MM_S = 1e-3  # one mm/s in m/s

RANGE = range_specs(
    "The TXY box holding this share of the chosen shots' events (after the mask): only events inside it are "
    "paired. An auto-crop box is kept from this plot's earlier run while the new one fits well inside it, so "
    "Live's next shots don't start the count again.")

G2_PAGE = "g²"
KIND_GROUP = "Correlation"
ONE_D, RADIAL = "1D", "radial"
COLLINEAR, BACK_TO_BACK = "collinear", "back-to-back"
TYPE = ParameterSpec("corr_type", "Type", "choice", ONE_D, choices=(ONE_D, RADIAL), group=KIND_GROUP, page=G2_PAGE,
                     tip="1D: g² of one velocity component's difference, the other two within ± the window. "
                         "Radial: g² of the length of the difference |Δv|.")
MODE = ParameterSpec("corr_mode", "Pairs", "choice", COLLINEAR, choices=(COLLINEAR, BACK_TO_BACK), group=KIND_GROUP,
                     page=G2_PAGE,
                     tip="Collinear: Δ = v₁ − v₂ (bunching). Back-to-back (halos, D13): Δ = v₁ + v₂ − 2v₀, pairs "
                         "emitted in opposite directions from a source moving at v₀.")
AXIS = ParameterSpec("corr_axis", "Axis", "choice", VELOCITY_AXES[0], choices=VELOCITY_AXES, group=KIND_GROUP,
                     page=G2_PAGE, when=(TYPE.name, ONE_D),
                     tip="The velocity component histogrammed (v_z up; v_x, v_y along the detector's X and Y).")
REACH = ParameterSpec("corr_range", "Range (max |Δ|)", "float", 0.02, (1e-6, 10.0), " m/s", group=KIND_GROUP,
                      page=G2_PAGE, si=True, unit_prefix="m",
                      tip="The separations histogrammed: from −range to +range (1D), or 0 to range (radial), in mm/s "
                          "whatever the plot's unit. Make it at least 3× the correlation length, or the fit finds "
                          "a slope, not a peak.")
BINS = ParameterSpec("corr_bins", "Bins", "int", 40, (2, 1000), group=KIND_GROUP, page=G2_PAGE,
                     tip="Bins over the range.")
WINDOW = ParameterSpec("corr_window", "Window ± (other components)", "float", 0.002, (1e-7, 10.0), " m/s",
                       group=KIND_GROUP, page=G2_PAGE, si=True, unit_prefix="m", when=(TYPE.name, ONE_D),
                       tip="1D: pairs count only when each other component of Δ is within ± this (a half-width). "
                           "Much narrower than the correlation length, or the peak is diluted (by about "
                           "1 − w²/6σ² per windowed axis).")
EQUAL_WIDTH, EQUAL_VOLUME = "equal width", "equal volume"
SHELLS = ParameterSpec("corr_shells", "Radial bins", "choice", EQUAL_WIDTH, choices=(EQUAL_WIDTH, EQUAL_VOLUME),
                       group=KIND_GROUP, page=G2_PAGE, when=(TYPE.name, RADIAL),
                       tip="Equal-width shells, or equal-volume shells (about the same number of pairs in each; "
                           "the first ones are wide, which the fit allows for).")
AT_REST, SET_HERE = "0 (at rest)", "set here"
SOURCE = ParameterSpec("bb_source", "Back-to-back source v₀", "choice", AT_REST, choices=(AT_REST, SET_HERE),
                       group=KIND_GROUP, page=G2_PAGE, when=(MODE.name, BACK_TO_BACK),
                       tip="The velocity of the source the pairs fly apart from (a halo's centre). 0: at rest at "
                           "the trap. A source moving at v₀ puts the peak at 2v₀ unless v₀ is set here. With "
                           "re-centring, relative to each shot's centre.")
SOURCE_V = tuple(ParameterSpec(f"bb_v{name[2:]}", f"v₀ {name}", "float", 0.0, (-10.0, 10.0), " m/s", group=KIND_GROUP,
                               page=G2_PAGE, si=True, unit_prefix="m", when=(SOURCE.name, SET_HERE),
                               tip=f"The back-to-back source's {name}, in mm/s.")
                 for name in VELOCITY_AXES)
RECENTRE = ParameterSpec("recentre", "Re-centre each shot", "bool", False, group=KIND_GROUP, page=G2_PAGE,
                         tip="Move each shot's robust centre (its events within 3 robust σ of the median) to 0 "
                             "before pairing: takes out pointing jitter (a moving cloud reads as a broad bump "
                             "otherwise) and stands in for a halo's per-shot centring (not built yet). g² near 0 "
                             "then dips by about 1.5/n (n events per shot).")
REFERENCE_GROUP = "Reference and fit"
ALL_SHOTS, NEIGHBOURS = "all shots", "neighbouring shots"
PARTNERS = ParameterSpec("partners", "Between-shot pairs", "choice", ALL_SHOTS, choices=(ALL_SHOTS, NEIGHBOURS),
                         group=REFERENCE_GROUP, page=G2_PAGE,
                         tip="The reference: pairs of every shot with every other, or with the K shots either side "
                             "of it only (faster for hundreds of shots, closer to each shot's conditions under a "
                             "slow drift, noisier).")
PARTNERS_K = ParameterSpec("partners_k", "K shots either side", "int", 10, (1, 100_000), group=REFERENCE_GROUP,
                           page=G2_PAGE, when=(PARTNERS.name, NEIGHBOURS))
FREE, FIXED = "free", "fixed at 1"
BASELINE = ParameterSpec("baseline", "Fit baseline", "choice", FREE, choices=(FREE, FIXED), group=REFERENCE_GROUP,
                         page=G2_PAGE,
                         tip="Free: b + A·Gaussian, g²(0) = (b + A)/b (a reference that doesn't quite match the "
                             "shots shows as b ≠ 1, noted). Fixed: 1 + A·Gaussian, as the old GUI.")
N_BOOT = ParameterSpec("n_boot", "Shot bootstrap resamples (0 = off)", "int", 200, (0, 5000), group=REFERENCE_GROUP,
                       page=G2_PAGE,
                       tip="Errors from resampling whole shots (no pairs recounted). 0: pair-counting errors, which "
                           "are too small (pairs share events).")
BUDGET = ParameterSpec("budget", "Time budget (0 = none)", "float", 30.0, (0.0, 3600.0), " s", group=REFERENCE_GROUP,
                       page=G2_PAGE,
                       tip="Stop counting pairs after this long: g² then covers the shots counted (said so), and "
                           "Rerun or Live's next shots continue from them.")

VELOCITY_PAGE = "Velocity"
VELOCITY_GROUP = "Velocity"
MM_PER_S, RECOIL, BRAGG = "mm/s", "ħk", "2ħk"
UNIT = ParameterSpec("velocity_unit", "Plot in", "choice", MM_PER_S, choices=(MM_PER_S, RECOIL, BRAGG),
                     group=VELOCITY_GROUP, page=VELOCITY_PAGE,
                     tip="The unit the plot is drawn in: mm/s, one photon's recoil ħk/m at 1083 nm, or one Bragg "
                         "order 2ħk/m. Settings stay in mm/s.")
SEARCH_MIN = ParameterSpec("release_search_min", "Release search T from (0 = first)", "float", 0.0, (0.0, 100.0),
                           " s", group=VELOCITY_GROUP, page=VELOCITY_PAGE, si=True, unit_prefix="m",
                           tip="When no release time is set (Folder constants…, or this plot's Constants), it is "
                               "detected from the tallest T peak of the chosen shots between these times (the cloud "
                               "released at rest); 0 leaves that end open.")
SEARCH_MAX = ParameterSpec("release_search_max", "Release search T to (0 = last)", "float", 0.0, (0.0, 100.0), " s",
                           group=VELOCITY_GROUP, page=VELOCITY_PAGE, si=True, unit_prefix="m",
                           tip="See Release search T from.")
CONSTANT_KEYS = ("fall_distance", "fall_time", "g", "release_time", "arrival_time", "trap_x", "trap_y")
CONSTANTS = tuple(constants_specs(CONSTANT_KEYS, page=VELOCITY_PAGE))
PARAMETERS = (*SHOT_SPECS, *RANGE, *MASK_SPECS, TYPE, MODE, AXIS, REACH, BINS, WINDOW, SHELLS, SOURCE, *SOURCE_V,
              RECENTRE, PARTNERS, PARTNERS_K, BASELINE, N_BOOT, BUDGET, UNIT, SEARCH_MIN, SEARCH_MAX, *CONSTANTS)

POINT_COLOUR = (40, 90, 170)
FIT_COLOUR = (214, 39, 40)
REFERENCE_COLOUR = (120, 120, 120)
CURVE_POINTS = 400
CLOCK = time.monotonic  # the time budget's clock (tests replace it)
CLOSED_LIMIT = 4096  # owners of closed plots remembered, so a late run doesn't bring their state back
LIVE_NOTE = ("Live rerun: shot bootstrap skipped, so the bars are pair counting's (too small: pairs share events) "
             "and g²(0)'s error the delete-one-shot jackknife's; Rerun (or Live's end) runs it")


# ---- per-plot state (Live) ----

@dataclass
class _PlotState:
    """What one plot keeps between its runs: its folder, the pair counts and in-shot cache of
    its spec, its auto-crop box and its last release detection. Used by one run at a time (the
    analysis worker); ``plot_closed`` drops it."""
    folder: str
    counts: PairCounts | None = None
    cache: dict[CacheKey, InShot] = field(default_factory=dict)
    box: tuple[str, tuple[float, ...], tuple[float, ...]] | None = None  # (its key, lower, upper)
    detection: tuple[str, ReleaseTime] | None = None  # (its key, the detection used)


_STATES: dict[str, _PlotState] = {}
_CLOSED: OrderedDict[str, None] = OrderedDict()
_LOCK = threading.Lock()


def plot_state(owner: str, folder: str) -> _PlotState:
    """The state the plot ``owner`` keeps for ``folder`` (a new one for another folder); a fresh,
    unkept one for a run no plot asked for or a plot already closed."""
    with _LOCK:
        if not owner or owner in _CLOSED:
            return _PlotState(folder)
        state = _STATES.get(owner)
        if state is None or state.folder != folder:
            state = _STATES[owner] = _PlotState(folder)
        return state


def drop_state(owner: str) -> None:
    with _LOCK:
        _STATES.pop(owner, None)
        _CLOSED[owner] = None
        while len(_CLOSED) > CLOSED_LIMIT:
            _CLOSED.popitem(last=False)


def held_states() -> int:
    with _LOCK:
        return len(_STATES)


# ---- the data a run gives ----

@dataclass(frozen=True)
class CorrelationData:
    shots: tuple[int, ...]
    total_shots: int
    events: int  # in the chosen shots, before the mask
    constants: ResolvedConstants
    unit: str = MM_PER_S
    unit_value: float = MM_S  # one plot unit in m/s (nan when unknown)
    masked: int = 0
    inside: int = 0  # of the events kept by the mask, inside the view range
    used: int = 0  # of them, with a velocity
    box: CropBox | None = None
    box_kept: bool = False  # the auto-crop box is this plot's previous one
    release: ReleaseTime | None = None  # what t_r came from (manual: from the layers)
    release_how: str = ""  # "folder", "plot", "lab", "detected", "detected, kept"
    origin: tuple[float, float] = (0.0, 0.0)
    origin_how: str = ""  # release.OriginSource, ", kept" when a held detection's
    result: CorrelationResult | None = None
    failure: str = ""  # why there are no velocities
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()  # the plot's own; the result's are in ``result.notes``
    reused: int = 0  # shots whose counts were held from this plot's earlier run
    added: int = 0  # shots counted in this run
    seconds: float = math.nan  # spent counting and fitting
    kind: tuple[str, str, int] = (ONE_D, COLLINEAR, 0)  # type, mode, axis
    window: float = math.nan  # m/s (1D)
    source: tuple[float, float, float] | None = None  # the BB source v₀ (m/s), None for collinear
    recentred: bool = False
    live_skipped: bool = False  # a Live rerun: the bootstrap was skipped (``LIVE_NOTE``)

    def all_notes(self) -> tuple[str, ...]:
        found = self.result.notes if self.result is not None else ()
        release = self.release.notes if self.release is not None else ()
        return (*release, *self.notes, *found)


def unit_value(unit: str, constants: ResolvedConstants) -> float:
    """One plot unit in m/s."""
    if unit == MM_PER_S:
        return MM_S
    return unit_velocity("2ħk" if unit == BRAGG else "ħk", constants)


def velocity_text(value: float, digits: int = WIDTH_DIGITS) -> str:
    """``20 mm/s``: a velocity setting as the settings show it."""
    return f"{number_text(value / MM_S, digits)} mm/s"


def kind_of(values: Mapping[str, Any]) -> tuple[str, str, int]:
    axis = VELOCITY_AXES.index(str(values.get(AXIS.name, AXIS.default)))
    return str(values.get(TYPE.name, TYPE.default)), str(values.get(MODE.name, MODE.default)), axis


def source_of(values: Mapping[str, Any]) -> tuple[float, float, float] | None:
    """The BB source velocity (m/s), (0, 0, 0) at rest; None for collinear pairs."""
    if values.get(MODE.name) != BACK_TO_BACK:
        return None
    if values.get(SOURCE.name) != SET_HERE:
        return 0.0, 0.0, 0.0
    vz, vx, vy = (float(values.get(spec.name, 0.0)) for spec in SOURCE_V)
    return vz, vx, vy


def separation_name(kind: tuple[str, str, int], source: tuple[float, float, float] | None) -> str:
    """``Δv_z``, ``|Δv|``, ``v_z₁ + v_z₂``, ``|v₁ + v₂ − 2v₀|``."""
    geometry, mode, axis = kind
    shifted = source is not None and any(source)
    if mode == BACK_TO_BACK:
        component = VELOCITY_AXES[axis] if geometry == ONE_D else "v"
        text = f"{component}₁ + {component}₂" + (" − 2v₀" if shifted else "")
        return text if geometry == ONE_D else f"|{text}|"
    return f"Δ{VELOCITY_AXES[axis]}" if geometry == ONE_D else "|Δv|"


def kind_text(data: CorrelationData) -> str:
    """``1D g²(Δv_z), window ± 2 mm/s``, ``back-to-back g²(|v₁ + v₂|)``, …"""
    geometry = data.kind[0]
    name = separation_name(data.kind, data.source)
    text = f"{'back-to-back ' if data.kind[1] == BACK_TO_BACK else ''}{'1D ' if geometry == ONE_D else ''}g²({name})"
    if geometry == ONE_D and math.isfinite(data.window):
        text += f", window ± {velocity_text(data.window)}"
    return text + (", each shot re-centred" if data.recentred else "")


def spec_for(values: Mapping[str, Any], events_key: str) -> CorrelationSpec:
    """The numerics' spec for the settings (edges in m/s)."""
    geometry, mode, axis = kind_of(values)
    reach, bins = float(values[REACH.name]), int(values[BINS.name])
    if geometry == ONE_D:
        edges = linear_edges(-reach, reach, bins)
    elif values.get(SHELLS.name) == EQUAL_VOLUME:
        edges = radial_edges(reach, bins)
    else:
        edges = linear_edges(0.0, reach, bins)
    partners = int(values[PARTNERS_K.name]) if values.get(PARTNERS.name) == NEIGHBOURS else None
    return CorrelationSpec("1d" if geometry == ONE_D else "radial", edges, "bb" if mode == BACK_TO_BACK else "cl",
                           axis, float(values[WINDOW.name]) if geometry == ONE_D else math.inf,
                           source_of(values), partners, events_key, bool(values.get(RECENTRE.name, False)))


def search_range(values: Mapping[str, Any]) -> tuple[float | None, float | None, tuple[str, ...]]:
    lower = float(values.get(SEARCH_MIN.name, 0.0)) or None
    upper = float(values.get(SEARCH_MAX.name, 0.0)) or None
    if lower is not None and upper is not None and lower >= upper:
        return None, None, (f"Release search T: from {time_text(lower)} is at or above to {time_text(upper)}: "
                            "searching every event",)
    return lower, upper, ()


# ---- the release time and origin ----

@dataclass(frozen=True)
class VelocitySource:
    """What the run converts with: t_r (and where from), the origin (and how), notes; or why not."""
    release: ReleaseTime | None
    release_how: str
    origin: tuple[float, float]
    origin_how: str
    notes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    failure: str = ""
    detection: ReleaseTime | None = None  # the detection used, to hold for the next run


def _close(new: Estimate, held: Estimate) -> bool:
    """Whether a new detection is within its SE (the larger of the two) of the held one."""
    if not (math.isfinite(new.value) and math.isfinite(held.value)):
        return math.isnan(new.value) and math.isnan(held.value)
    se = max(new.se if math.isfinite(new.se) else 0.0, held.se if math.isfinite(held.se) else 0.0)
    return abs(new.value - held.value) <= se


def steady_detection(new: ReleaseTime, held: ReleaseTime | None, uses_time: bool) -> ReleaseTime | None:
    """The held detection when the new one is within its SE of it (t_r when the run uses it, and the
    origin), else None."""
    if held is None or not held.ok or not new.ok:
        return None
    if uses_time and not _close(new.value, held.value):
        return None
    if new.origin_found != held.origin_found:
        return None
    if new.origin_found and not all(_close(a, b) for a, b in zip(new.origin, held.origin)):
        return None
    return held


def velocities_for(events: Events, constants: ResolvedConstants, values: Mapping[str, Any],
                   held: tuple[str, ReleaseTime] | None, key: str) -> VelocitySource:
    """t_r and the origin for this run (module docstring): the layers', else one detection of
    ``events`` (the chosen shots' masked TXY events) in Release search T, kept from ``held`` (the
    plot's previous detection under the same ``key``) when within its SE."""
    given = layer_release_time(constants)
    manual_origin = layer_origin(constants)
    lower, upper, warnings = search_range(values)
    notes: list[str] = []
    detection: ReleaseTime | None = None
    kept = False
    if given is None or manual_origin is None:
        new = detect_release_time(events[:, 0], constants, lower, upper, positions=events[:, 1:3]) \
            if len(events) else None
        if new is not None:
            steady = steady_detection(new, held[1] if held is not None and held[0] == key else None,
                                      uses_time=given is None)
            detection, kept = (steady, True) if steady is not None else (new, False)
    if given is not None and not given.ok:
        return VelocitySource(None, "", (0.0, 0.0), "", failure=f"no release time: {given.failure}")
    if given is None:
        if detection is None or not detection.ok:
            why = detection.failure if detection is not None else "no events"
            return VelocitySource(None, "", (0.0, 0.0), "", warnings=warnings,
                              failure=f"no release time: none set, and none detected ({why}). Set it for the folder "
                                      "with the Release time plot (Use for this folder…), or for this plot "
                                      "(Constants)")
        release, how = detection, "detected, kept" if kept else "detected"
        notes.append(f"t_r detected in this run (SE {time_text(detection.value.se, WIDTH_DIGITS)} within run): "
                     "the Release time plot's Use for this folder… sets it for every plot")
    else:
        release = given
        how = (constants.origins["arrival_time"] if math.isfinite(given.arrival.value)
               else constants.origins["release_time"])
    found = detection if detection is not None and detection.ok else None
    origin, origin_how = velocity_origin(found, manual_origin)
    how_origin: str = origin_how
    if origin_how.startswith("detected") and kept:
        how_origin += ", kept"
    if kept:
        notes.append("t_r and the origin kept from this plot's previous detection (this run's is within its SE), so "
                     "the pairs counted stay valid")
    if origin_how == "detected (unsure)":
        warnings += ("the origin's detection is unsure: another T peak may be the cloud at rest",)
    return VelocitySource(release, how, origin, how_origin, tuple(notes), warnings, "", detection)


# ---- the view range ----

def steady_box(found: CropBox, held: tuple[str, tuple[float, ...], tuple[float, ...]] | None, key: str
               ) -> tuple[tuple[float, ...], tuple[float, ...], bool]:
    """An auto-crop box made steady: per axis, the held one while the new one lies inside it and
    fills at least 1/``trends.KEEP_SLACK`` of it, else the new one rounded out
    (``trends.snapped``). (lower, upper, whether all of the held one was kept)."""
    lower, upper = list(found.lower), list(found.upper)
    previous = held if held is not None and held[0] == key else None
    kept = previous is not None
    for axis, (low, high) in enumerate(zip(found.lower, found.upper)):
        if previous is not None:
            old_low, old_high = previous[1][axis], previous[2][axis]
            if old_low <= low and high <= old_high and old_high - old_low <= trends.KEEP_SLACK * (high - low):
                lower[axis], upper[axis] = old_low, old_high
                continue
        kept = False
        lower[axis], upper[axis] = trends.snapped(low, high)
    return tuple(lower), tuple(upper), kept


# ---- the run ----

def mask_record(mask: Mask) -> list[list[float]]:
    return [[circle.x, circle.y, circle.r, float(circle.keep)] for circle in mask.circles]


def compute_correlations(context: AnalysisContext) -> CorrelationData:
    values, view = context.parameters, context.view
    shots = select_shots(view, values)
    mask = mask_from(values)  # Circles that can't be read fail the run, saying which.
    constants = context.resolved_constants
    if constants is None:  # Run without the runner: resolved here, the same way.
        constants = resolve_for_run(values, context.constants.get("lab"), context.constants.get("folder"))
    unit = str(values.get(UNIT.name, UNIT.default))
    per_shot: dict[int, Events] = {}
    total = masked = 0
    for shot in shots:
        events = txy(view.shots[shot])
        total += len(events)
        kept, out = mask.apply(events)
        masked += out
        per_shot[shot] = kept
    kind = kind_of(values)
    data = CorrelationData(shots, len(view.shots), total, constants, unit, unit_value(unit, constants), masked,
                           warnings=(*range_warnings(values), *mask_warnings(values)), kind=kind,
                           window=float(values[WINDOW.name]) if kind[0] == ONE_D else math.nan,
                           source=source_of(values), recentred=bool(values.get(RECENTRE.name, False)))
    if unit != MM_PER_S and not math.isfinite(data.unit_value):
        data = replace(data, unit=MM_PER_S, unit_value=MM_S,
                       warnings=data.warnings + ("no recoil velocity from these constants: drawn in mm/s",))
    chosen = np.concatenate(list(per_shot.values())) if per_shot else np.empty((0, 3))
    if not len(chosen):
        return data
    context.check()
    state = plot_state(context.owner, view.identity.source_path)
    # The view range, in TXY.
    if manual(values):
        box = manual_box(chosen, values)
        box_kept = False
    else:
        found = crop_box(chosen, keep_fraction(values), context.cancelled)
        box_key = json.dumps({"keep": keep_fraction(values), "mask": mask_record(mask),
                              "shots": [values.get(spec.name) for spec in SHOT_SPECS]})
        lower, upper, box_kept = steady_box(found, state.box, box_key)
        state.box = (box_key, lower, upper)
        box = CropBox(lower, upper, 0, len(chosen), found.keep, 0)
    context.check()
    # t_r and the origin.
    lower_t, upper_t, _ = search_range(values)
    detection_key = json.dumps({"constants": constants.as_record(CONSTANT_KEYS), "search": [lower_t, upper_t],
                                "mask": mask_record(mask)}, sort_keys=True)
    found_velocities = velocities_for(chosen, constants, values, state.detection, detection_key)
    data = replace(data, warnings=data.warnings + found_velocities.warnings, box=box, box_kept=box_kept,
                   release=found_velocities.release, release_how=found_velocities.release_how,
                   origin=found_velocities.origin, origin_how=found_velocities.origin_how,
                   notes=found_velocities.notes)
    if found_velocities.failure or found_velocities.release is None:
        return replace(data, failure=found_velocities.failure or "no release time")
    if found_velocities.detection is not None and found_velocities.detection.ok:
        state.detection = (detection_key, found_velocities.detection)
    release_time = found_velocities.release.value.value
    shot_events: list[ShotEvents] = []
    inside = used = 0
    for shot, events in per_shot.items():
        events = events[box.contains(events)] if len(events) else events
        inside += len(events)
        velocities = txy_to_velocity(events, release_time, constants, found_velocities.origin)
        good = velocities.values[velocities.valid]
        used += len(good)
        fingerprint = view.fingerprints.get(shot) or ("revision", view.revision)
        shot_events.append(ShotEvents(shot, fingerprint, good))
    box = replace(box, kept=inside, left_out=len(chosen) - inside)
    data = replace(data, box=box, inside=inside, used=used)
    if not used:
        return data
    events_key = json.dumps({"t_r": release_time, "h": effective_fall_distance(constants), "g": constants.g,
                             "origin": list(found_velocities.origin), "mask": mask_record(mask),
                             "box": [list(box.lower), list(box.upper)]}, sort_keys=True)
    spec = spec_for(values, events_key)
    if state.counts is None or state.counts.spec != spec:
        key = spec.key()
        state.cache = {cached: value for cached, value in state.cache.items() if cached[2] == key}
        state.counts = PairCounts(spec, state.cache)
    held = state.counts.fingerprints
    reused = sum(1 for shot in shot_events if held.get(shot.shot, None) == shot.fingerprint)
    budget = float(values[BUDGET.name])
    started = time.monotonic()
    baseline: Baseline = "fixed" if values.get(BASELINE.name) == FIXED else "free"
    boots = int(values[N_BOOT.name])
    skipped = context.live and boots > 0  # Live reruns skip the costly bootstrap, as the Release time plot does.
    result = correlate(shot_events, spec, cache=state.cache, state=state.counts, cancelled=context.cancelled,
                       budget=budget if budget > 0 else None, clock=CLOCK, n_boot=0 if skipped else boots,
                       baseline=baseline)
    notes = list(data.notes)
    if skipped:
        notes.append(LIVE_NOTE)
    if not result.complete:
        notes.append("Rerun or Live's next shots continue counting from the shots counted")
    if unit != MM_PER_S and RECOIL_WAVELENGTH_UNCONFIRMED:
        notes.append(f"{unit} from He* at {number_text(RECOIL_WAVELENGTH * 1e9, 6)} nm: unconfirmed which beams set "
                     "the recoil unit")
    return replace(data, result=result, reused=reused, added=len(result.shots_used) - reused,
                   seconds=time.monotonic() - started, notes=tuple(notes), live_skipped=skipped)


# ---- text ----

def zero_line(data: CorrelationData) -> str:
    """``g²(0) = 2.01 ± 0.05 · baseline 0.995 ± 0.004 · σ 5.0 ± 0.3 mm/s``, ``no peak: g² near 0 is
    1.00 ± 0.02``, or why there is no g²."""
    if data.failure:
        return f"⚠ {data.failure}"
    result = data.result
    if result is None:
        return ""
    if not result.ok:
        return f"⚠ no g²: {result.failure}"
    if math.isfinite(result.g2_zero.value):
        text = f"g²(0) = {result.g2_zero.text(digits=2)}"
        if result.baseline_mode == "free" and math.isfinite(result.baseline.value):
            text += f" over baseline {result.baseline.text(digits=2)}"
        if result.fit is not None and result.fit.ok:
            sigma = result.fit["sigma"]
            scale = data.unit_value
            text += f" · σ {Estimate(sigma.value / scale, sigma.se / scale).text(si=False)} {data.unit}"
        return text
    if math.isfinite(result.near_zero.value):
        return f"no peak: g² near 0 is {result.near_zero.text(digits=2)}"
    return "no peak"


def velocity_line(data: CorrelationData) -> str:
    """``t_r 20,031.2 ms (folder) · origin (3, −2) mm (manual)``, the assumed origin last, in amber."""
    if data.release is None:
        return ""
    x0, y0 = (number_text(axis * 1e3, WIDTH_DIGITS) for axis in data.origin)
    text = f"t_r {time_text(data.release.value.value)} ({data.release_how})"
    if data.unit != MM_PER_S:
        text += f" · 1 {data.unit} = {velocity_text(data.unit_value)}"
    if data.origin_how == "assumed":
        return text + " · ⚠ origin assumed (0, 0) mm: the trap above X = Y = 0"
    return text + f" · origin ({x0}, {y0}) mm ({data.origin_how})"


def counts_line(data: CorrelationData) -> str:
    """``pairs 12,345 in-shot, 1,234,567 between shots · 39 shots held, 1 counted · 0.8 s``."""
    result = data.result
    if result is None:
        return ""
    text = f"pairs in range {int(result.in_counts.sum()):,} in-shot, {int(result.between_counts.sum()):,} between shots"
    text += f" · {data.reused:,} shot{'' if data.reused == 1 else 's'} held, {data.added:,} counted"
    if math.isfinite(data.seconds):
        text += f" · {data.seconds:.1f} s"
    return text


def titles(result: AnalysisResult, data: CorrelationData) -> tuple[str, ...]:
    first = (f"{result.input.short()} · {shots_text(data.shots, data.total_shots)} · {data.used:,} of "
             f"{data.events:,} events with velocities in range{masked_text(data.masked)} · {kind_text(data)}")
    return (first, zero_line(data), velocity_line(data), counts_line(data),
            *(f"⚠ {warning}" for warning in data.warnings),
            *(f"⚠ {short_note(note)}" for note in data.all_notes()))


def brief(data: CorrelationData) -> str:
    """For the settings line: ``g²(0) 2.01 ± 0.05``, ``no peak (g² near 0: 1.00 ± 0.02)``, the budget."""
    result = data.result
    if result is None or not result.ok:
        return ""
    if math.isfinite(result.g2_zero.value):
        text = f"g²(0) {result.g2_zero.text(digits=2)}"
    elif math.isfinite(result.near_zero.value):
        text = f"no peak (g² near 0: {result.near_zero.text(digits=2)})"
    else:
        text = "no peak"
    if not result.complete:
        text += f" · {len(result.shots_used):,} of {result.shots_total:,} shots (time budget)"
    return text


def record_lines(data: CorrelationData) -> list[str]:
    lines = [f"Correlation: {kind_text(data)}; settings in mm/s, drawn in {data.unit}"]
    if data.release is not None:
        lines.append(f"Velocities: t_r = {time_text(data.release.value.value)} ({data.release_how}), origin "
                     f"({length_text(data.origin[0])}, {length_text(data.origin[1])}) ({data.origin_how}), "
                     f"h {length_text(effective_fall_distance(data.constants))}, g {data.constants.g:g} m/s²")
    if data.box is not None:
        bounds = ", ".join(f"{axis} {low:.9g}–{high:.9g}" for axis, low, high in zip("TXY", data.box.lower,
                                                                                    data.box.upper))
        lines.append(f"View range ({'manual' if data.box.manual else 'auto-crop'}"
                     f"{', kept from the previous run' if data.box_kept else ''}): {bounds} (s, m)")
    result = data.result
    if result is not None:
        lines.append(f"Errors: {result.se_method}; g²(0)'s: {result.g2_zero_method or 'none'}")
        lines.append(f"{counts_line(data)}; pair totals {result.in_pairs:,} in-shot, {result.between_pairs:,} "
                     f"between shots")
    lines += [f"Note: {note}" for note in (*data.warnings, *data.all_notes())]
    if data.failure:
        lines.append(f"Failure: {data.failure}")
    return lines


def velocity_record(data: CorrelationData) -> dict[str, Any]:
    release = data.release
    return {"release_time": finite_or_none(release.value.value) if release is not None else None,
            "release_time_from": data.release_how,
            "release": release.as_record() if release is not None else None,
            "origin": list(data.origin), "origin_from": data.origin_how,
            "fall_distance": finite_or_none(effective_fall_distance(data.constants)), "g": data.constants.g,
            "unit": data.unit, "unit_m_per_s": finite_or_none(data.unit_value),
            "recoil_wavelength": RECOIL_WAVELENGTH if data.unit != MM_PER_S else None,
            "view_range": ({"lower": list(data.box.lower), "upper": list(data.box.upper), "manual": data.box.manual,
                            "kept": data.box_kept} if data.box is not None else None),
            "events": data.events, "masked": data.masked, "inside": data.inside, "used": data.used}


def empty_reason(data: CorrelationData) -> str:
    """Why there is nothing to draw ("" when there is)."""
    text = empty_text(data.total_shots, len(data.shots), data.events)
    if text:
        return text
    if data.masked and data.masked == data.events:
        return all_masked_text(data.masked)
    if data.failure:
        return f"No velocities: {data.failure}"
    if not data.used:
        return (f"None of the {data.events - data.masked:,} events kept is inside the view range with a velocity "
                "(View range settings, release time)")
    if data.result is not None and not data.result.ok:
        return f"No g²: {data.result.failure}"
    return ""


# ---- drawing ----

class CorrelationPlot(QWidget):
    """g² ± SE with the fitted peak and its baseline, and the pairs per bin below; ``show_data``
    draws a newer result in place, keeping zoom and pan."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.graphics: Any = pg.GraphicsLayoutWidget(self)
        self.graphics.setBackground("w")
        layout.addWidget(self.graphics)
        self.title: Any = add_label(self.graphics, row=0, col=0)
        self.g2: Any = self.graphics.addPlot(row=1, col=0, title="g² ± SE, with the fitted peak",
                                             axisItems=grouped_axes("bottom", "left"))
        self.g2.setLabel("left", "g²")
        self.pairs: Any = self.graphics.addPlot(row=2, col=0,
                                                title="Pairs per bin: in-shot, and between shots × P_in/P_between",
                                                axisItems=grouped_axes("bottom", "left"))
        self.pairs.setLabel("left", "Pairs")
        self.pairs.setXLink(self.g2)
        self.graphics.ci.layout.setRowStretchFactor(1, 3)
        self.graphics.ci.layout.setRowStretchFactor(2, 1)
        for plot in (self.g2, self.pairs):
            plot.showGrid(x=True, y=True, alpha=0.3)
        self.pairs.addLegend(offset=(-10, 10))
        self.bars: Any = pg.ErrorBarItem(x=np.empty(0), y=np.empty(0), height=np.empty(0),
                                         pen=pg.mkPen((*POINT_COLOUR, 160)))
        self.g2.addItem(self.bars)
        self.points: Any = self.g2.plot([], [], pen=None, symbol="o", symbolSize=5, symbolBrush=POINT_COLOUR,
                                        symbolPen=None)
        self.curve: Any = self.g2.plot([], [], pen=pg.mkPen(FIT_COLOUR, width=2))
        self.one: Any = pg.InfiniteLine(1.0, angle=0, movable=False,
                                        pen=pg.mkPen(REFERENCE_COLOUR, width=1, style=pg.QtCore.Qt.PenStyle.DotLine))
        self.g2.addItem(self.one)
        self.level: Any = pg.InfiniteLine(1.0, angle=0, movable=False,
                                          pen=pg.mkPen(FIT_COLOUR, width=1, style=pg.QtCore.Qt.PenStyle.DashLine))
        self.g2.addItem(self.level)
        self.inside: Any = self.pairs.plot([], [], name="in-shot", stepMode="center", pen=pg.mkPen(POINT_COLOUR))
        self.between: Any = self.pairs.plot([], [], name="between shots, scaled", stepMode="center",
                                            pen=pg.mkPen(REFERENCE_COLOUR, style=pg.QtCore.Qt.PenStyle.DashLine))

    def show_data(self, result: AnalysisResult, data: CorrelationData) -> None:
        self.title.setText(lines_html(titles(result, data)))
        found = data.result
        name = f"{separation_name(data.kind, data.source)} ({data.unit})"
        for plot in (self.g2, self.pairs):
            plot.setLabel("bottom", name)
        if found is None:
            return
        scale = data.unit_value
        centres, edges = found.centres / scale, found.edges / scale
        good = np.isfinite(found.g2) & np.isfinite(found.se)
        self.points.setData(centres[np.isfinite(found.g2)], found.g2[np.isfinite(found.g2)])
        self.bars.setData(x=centres[good], y=found.g2[good], height=2 * found.se[good])
        grid = np.linspace(float(found.edges[0]), float(found.edges[-1]), CURVE_POINTS)
        curve = found.curve(grid)
        shown = np.isfinite(curve)
        self.curve.setData(grid[shown] / scale, curve[shown])
        level = found.baseline.value
        self.level.setVisible(math.isfinite(level) and found.fit is not None and found.fit.ok)
        if math.isfinite(level):
            self.level.setValue(level)
        scaled = found.between_counts * (found.in_pairs / found.between_pairs) if found.between_pairs else \
            np.zeros(len(found.between_counts))
        self.inside.setData(edges, found.in_counts.astype(np.float64))
        self.between.setData(edges, np.asarray(scaled, dtype=np.float64))


class Correlations(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Correlations",
            description="g² of pairs in velocity space (in-shot over between-shot pairs): 1D, radial and "
                        "back-to-back, with shot bootstrap errors and a peak fit; Live counts only new shots",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.correlations",
            version="1",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*PARAMETERS]

    def constant_keys(self, action_name: str) -> tuple[str, ...]:
        return CONSTANT_KEYS

    def live_policy(self, action_name: str) -> LivePolicy:
        # Each rerun counts only the new shots, but refits 200 bootstrap replicates and the
        # delete-one curves (1–5 s): at most one every 5 s (proposed, for Tony).
        return LivePolicy(min_delay=5.0)

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        geometry, mode, axis = kind_of(values)
        reach = float(values[REACH.name])
        parts = [shots_brief(values), range_brief(values), mask_brief(values),
                 f"{'back-to-back ' if mode == BACK_TO_BACK else ''}"
                 f"{f'1D {VELOCITY_AXES[axis]}' if geometry == ONE_D else 'radial'}",
                 f"± {velocity_text(reach)}" if geometry == ONE_D else f"0–{velocity_text(reach)}",
                 f"{int(values[BINS.name]):,} bins"
                 + (" (equal volume)" if geometry == RADIAL and values.get(SHELLS.name) == EQUAL_VOLUME else ""),
                 f"window ± {velocity_text(float(values[WINDOW.name]))}" if geometry == ONE_D else ""]
        source = source_of(values)
        if source is not None and any(source):
            parts.append("v₀ (" + ", ".join(number_text(v / MM_S, WIDTH_DIGITS) for v in source) + ") mm/s")
        if values.get(RECENTRE.name):
            parts.append("re-centred")
        if values.get(PARTNERS.name) == NEIGHBOURS:
            parts.append(f"reference ± {int(values[PARTNERS_K.name]):,} shots")
        if values.get(BASELINE.name) == FIXED:
            parts.append("baseline 1")
        boots = int(values[N_BOOT.name])
        parts.append(f"bootstrap {boots:,}" if boots else "no bootstrap")
        budget = float(values[BUDGET.name])
        parts.append(f"budget {budget:g} s" if budget else "no budget")
        if values.get(UNIT.name, MM_PER_S) != MM_PER_S:
            parts.append(f"in {values[UNIT.name]}")
        return selection_text(view, values), " · ".join(part for part in parts if part)

    def describe_result(self, action_name: str, result: AnalysisResult) -> str:
        return str(result.found.get("brief", ""))

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        return [*range_warnings(values), *mask_warnings(values), *search_range(values)[2]]

    def result_found(self, action_name: str, data: Any) -> dict[str, Any]:
        """``correlation`` (``CorrelationResult.as_record``), ``velocity`` (t_r, the origin and where
        each came from, the unit, the view range), ``brief``, ``record_lines``, ``constants``; and in
        ``reuse`` what the run took from the plot's history (the kept box and detection, the shots
        counted within the budget)."""
        if not isinstance(data, CorrelationData):
            return {}
        result = data.result
        velocity = velocity_record(data)
        return {"correlation": result.as_record() if result is not None else None, "velocity": velocity,
                "brief": brief(data), "record_lines": record_lines(data),
                "constants": describe_constants(data.constants, CONSTANT_KEYS, every=True),
                "reuse": {"release_time": velocity["release_time"], "origin": velocity["origin"],
                          "view_range": velocity["view_range"], "bootstrap_skipped": data.live_skipped,
                          "shots_used": list(result.shots_used) if result is not None else []}}

    def plot_closed(self, action_name: str, owner: str, path: str) -> None:
        """Drop the plot's pair counts, in-shot cache, box and detection."""
        drop_state(owner)

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        return compute_correlations(context)

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: CorrelationData = result.data
        reason = empty_reason(data)
        if reason:
            return empty_pane(reason, parent)
        widget = CorrelationPlot(parent)
        widget.show_data(result, data)
        return widget

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """A rerun (Live's next shots) draws in place, keeping zoom and pan; to or from an empty
        plot, anew."""
        data: CorrelationData = result.data
        if not isinstance(widget, CorrelationPlot) or empty_reason(data):
            return False
        widget.show_data(result, data)
        return True


__all__ = ["CorrelationData", "CorrelationPlot", "Correlations", "compute_correlations", "drop_state",
           "held_states", "plot_state"]
