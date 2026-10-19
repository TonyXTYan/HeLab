"""Parameters every plot shares: which shots go in (Shots) and the view range (auto-crop or
manual T/X/Y bounds), with the helpers that apply them. Live will use "last N" later."""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

from helab.analysis.dataset_view import DatasetView, Events
from helab.analysis.parameters import ParameterSpec
from helab.analysis.stats import AXES, DEFAULT_KEEP, UNITS, CropBox

# Shots

ALL, LAST_N, RANGE = "all", "last N", "range"
SHOTS_GROUP = "Shots"
SHOTS = ParameterSpec("shots", "Shots", "choice", ALL, choices=(ALL, LAST_N, RANGE), group=SHOTS_GROUP,
                      tip="Which of the loaded shots the plot uses: all of them, the last N by shot "
                          "number, or a range of shot numbers.")
LAST_SHOTS = ParameterSpec("last_shots", "Last N", "int", 50, (1, 1_000_000), group=SHOTS_GROUP,
                           when=(SHOTS.name, LAST_N), tip="The N highest shot numbers loaded.")
FIRST_SHOT = ParameterSpec("first_shot", "From shot", "int", 1, (0, 1_000_000_000), group=SHOTS_GROUP,
                           when=(SHOTS.name, RANGE), tip="The first shot number to include.")
LAST_SHOT = ParameterSpec("last_shot", "To shot (0 = last)", "int", 0, (0, 1_000_000_000), group=SHOTS_GROUP,
                          when=(SHOTS.name, RANGE), tip="The last shot number to include; 0 means up to the last one.")
SHOT_SPECS: tuple[ParameterSpec, ...] = (SHOTS, LAST_SHOTS, FIRST_SHOT, LAST_SHOT)


def select_shots(view: DatasetView, values: Mapping[str, Any]) -> tuple[int, ...]:
    """The view's shot numbers the Shots parameters choose, ascending."""
    numbers = view.shot_numbers
    mode = values.get(SHOTS.name, ALL)
    if mode == LAST_N:
        count = int(values.get(LAST_SHOTS.name, LAST_SHOTS.default))
        return numbers[-count:] if count else ()
    if mode == RANGE:
        first = int(values.get(FIRST_SHOT.name, FIRST_SHOT.default))
        last = int(values.get(LAST_SHOT.name, LAST_SHOT.default))
        return tuple(shot for shot in numbers if shot >= first and (last == 0 or shot <= last))
    return numbers


def shots_text(selected: Sequence[int], total: int) -> str:
    """``60 shots``, or which of them when not all: ``last 10 of 60 shots``, ``shots 5–20 (16 of 60)``."""
    if len(selected) == total:
        return f"{total:,} shot{'' if total == 1 else 's'}"
    if not selected:
        return f"none of {total:,} shots"
    return f"shots {selected[0]}–{selected[-1]} ({len(selected):,} of {total:,})"


# View range

AUTO, MANUAL = "auto-crop", "manual"
RANGE_GROUP = "View range"
RANGE_MODE = ParameterSpec("range_mode", "Range", "choice", AUTO, choices=(AUTO, MANUAL), group=RANGE_GROUP,
                           tip="Auto-crop finds the range holding most events; manual uses the T, X "
                               "and Y bounds below.")
BOUNDS: tuple[tuple[ParameterSpec, ParameterSpec], ...] = tuple(
    (ParameterSpec(f"{axis.lower()}_min", f"{axis} min", "float", 0.0, None, f" {UNITS[i]}", group=RANGE_GROUP,
                   when=(RANGE_MODE.name, MANUAL), si=True,
                   tip=f"Lower bound of {axis}. Leave min and max equal for {axis}'s full extent; a min "
                       f"above the max also uses the full extent, and the plot says so."),
     ParameterSpec(f"{axis.lower()}_max", f"{axis} max", "float", 0.0, None, f" {UNITS[i]}", group=RANGE_GROUP,
                   when=(RANGE_MODE.name, MANUAL), si=True, tip=f"Upper bound of {axis}."))
    for i, axis in enumerate(AXES))


def keep_spec(tip: str) -> ParameterSpec:
    """The auto-crop share, with the plot's own description of what it crops."""
    return ParameterSpec("keep_percent", "Auto-crop: keep", "float", DEFAULT_KEEP * 100, (50.0, 100.0), " %",
                         tip, group=RANGE_GROUP, when=(RANGE_MODE.name, AUTO))


def range_specs(keep_tip: str) -> tuple[ParameterSpec, ...]:
    return (RANGE_MODE, keep_spec(keep_tip), *(spec for pair in BOUNDS for spec in pair))


def manual(values: Mapping[str, Any]) -> bool:
    return values.get(RANGE_MODE.name) == MANUAL


def keep_fraction(values: Mapping[str, Any]) -> float:
    return float(values.get("keep_percent", DEFAULT_KEEP * 100)) / 100


def manual_bounds(values: Mapping[str, Any]) -> tuple[tuple[float, float] | None, ...]:
    """Per axis, the (min, max) the user set, or None for that axis's full extent: when min = max
    (unset), and when min > max (reversed), which ``range_warnings`` then reports."""
    bounds: list[tuple[float, float] | None] = []
    for low_spec, high_spec in BOUNDS:
        low, high = float(values.get(low_spec.name, 0.0)), float(values.get(high_spec.name, 0.0))
        bounds.append((low, high) if high > low else None)
    return tuple(bounds)


def reversed_axes(values: Mapping[str, Any]) -> tuple[str, ...]:
    """The axes whose manual min is above their max, when the range is manual."""
    if not manual(values):
        return ()
    return tuple(axis for axis, (low_spec, high_spec) in zip(AXES, BOUNDS)
                 if float(values.get(low_spec.name, 0.0)) > float(values.get(high_spec.name, 0.0)))


def range_warnings(values: Mapping[str, Any]) -> tuple[str, ...]:
    """What the plot did differently from the settings: a reversed manual axis uses its full
    extent. Shown on the figure, in the dock's source line and record, and in the settings tab."""
    return tuple(f"{axis}: min > max, using full extent" for axis in reversed_axes(values))


def manual_box(events: Events, values: Mapping[str, Any]) -> CropBox:
    """The box of the manual bounds, each unset axis spanning its events' full extent."""
    events = np.asarray(events, dtype=np.float64)
    total = len(events)
    columns = events.shape[1] if events.ndim == 2 else len(AXES)
    bounds = manual_bounds(values)
    lower = [math.nan] * columns
    upper = [math.nan] * columns
    for axis in range(columns):
        given = bounds[axis] if axis < len(bounds) else None
        if given is not None:
            lower[axis], upper[axis] = given
        elif total:
            lower[axis], upper[axis] = float(events[:, axis].min()), float(events[:, axis].max())
    box = CropBox(tuple(lower), tuple(upper), 0, total, math.nan, 0, manual=True)
    kept = int(np.count_nonzero(box.contains(events))) if total else 0
    return CropBox(box.lower, box.upper, kept, total, math.nan, total - kept, manual=True)
