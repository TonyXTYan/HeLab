"""The three layers of constants a run resolves (``physics.resolve``), as plots and settings use them.

- **Lab** values (Settings → Lab parameters, app-wide) and **folder** values (per folder, in
  HeLab's store, inherited by subfolders that don't set their own) are plain ``{key: float}``
  mappings, cleaned with ``clean_layer`` wherever they are read.
- **Plot overrides** are parameters of the plot: ``constants_specs(keys)`` gives a "Constants"
  group with, for each key, a choice (use the lab/folder value, or set it for this plot) and the
  plot's own value, shown only when set here. ``plot_overrides(values)`` reads them back.
- ``resolve_for_run`` merges the three when a run is submitted, on the GUI thread, from what is
  in memory (compute does no I/O); the run records the result (``ResolvedConstants.as_record``).

A script that uses constants adds ``constants_specs(KEYS)`` to its ``parameters`` and reads
``context.resolved_constants`` in ``compute``; ``context.constants`` holds the lab and folder layers
the run was given (``helab/scripts/base.py``: ``constant_keys``, ``run_constants``). No Qt, no I/O.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

from helab.analysis.display_units import length_text, number_text, si_text, time_text
from helab.analysis.parameters import SI_FACTORS, ParameterSpec
from helab.analysis.physics import DEFAULTS, TABLE, Origin, ResolvedConstants, resolve

PREFIX = "const."
FROM_SUFFIX = ".from"
GROUP = "Constants"
USE_LAYERS = "lab/folder"
SET_HERE = "this plot"
CHOICES = (USE_LAYERS, SET_HERE)
# Shown beside a value: where it came from.
ORIGIN_TEXT: Mapping[Origin, str] = {"default": "default", "lab": "lab", "folder": "folder",
                                     "plot": "this plot", "derived": "derived", "detected": "from the data"}
FROM_THE_DATA = ORIGIN_TEXT["detected"]
# Units whose values are shown with SI prefixes (4 mm, 416 ms); the others in scientific form.
SI_UNITS = ("m", "s", "Hz")
# Of those, the ones always shown in one prefix, as the plots' axes (ms and mm: Tony, 2026-10-20).
FIXED_PREFIX = {"s": "m", "m": "m"}
# Rows shown in another fixed prefix than their unit's: a wavelength in nm.
KEY_PREFIX: Mapping[str, str] = {"recoil_wavelength": "n"}
LIMITS = (1e-60, 1e60)
SIGNED_LIMITS = (-1e60, 1e60)  # a signed row's (``Constant.signed``: the origin's positions)
OPTIONAL_LIMITS = (0.0, 1e60)  # an optional time's: 0 until a value is typed
# Short symbols for a plot's source line.
SYMBOLS: Mapping[str, str] = {
    "hbar": "ħ", "k_B": "k_B", "u": "u", "mass": "m", "g": "g", "scattering_length": "a",
    "fall_distance": "h", "fall_time": "t_f", "trap_radial": "f_r", "trap_axial": "f_z",
    "detector_qe": "QE", "trap_axial_axis": "axial axis", "dld_trigger": "trigger", "dld_acquisition": "acquisition",
    "release_time": "t_r", "arrival_time": "t_a", "trap_x": "x₀", "trap_y": "y₀",
    "recoil_wavelength": "λ"}


def fixed_prefix(key: str) -> str | None:
    """The one SI prefix ``key``'s values are shown and typed in (mm, ms; a wavelength in nm), or
    None when the prefix follows the value."""
    return KEY_PREFIX.get(key, FIXED_PREFIX.get(TABLE[key].unit))


def value_name(key: str) -> str:
    """The plot parameter holding the plot's own value of ``key``."""
    return f"{PREFIX}{key}"


def source_name(key: str) -> str:
    """The plot parameter choosing where ``key`` comes from (``USE_LAYERS`` or ``SET_HERE``)."""
    return f"{PREFIX}{key}{FROM_SUFFIX}"


def default_value(key: str) -> float:
    """The table's value of ``key`` (the fall time derived from the defaults); 0 for an optional
    row, which has none (what a plot's own value starts from)."""
    return DEFAULTS.value(key) if DEFAULTS.is_set(key) else 0.0


def limits(key: str) -> tuple[float, float]:
    """The values an editor of ``key`` allows (at most the row's maximum): any for a signed row,
    else positive ones; for an
    optional time also 0, which shows it has no value yet (``clean_layer`` leaves 0 out)."""
    constant = TABLE[key]
    low, high = SIGNED_LIMITS if constant.signed else OPTIONAL_LIMITS if constant.optional else LIMITS
    return low, min(high, constant.maximum)


def is_constant(spec: ParameterSpec) -> bool:
    return spec.name.startswith(PREFIX)


def without_constants(specs: Iterable[ParameterSpec]) -> list[ParameterSpec]:
    """``specs`` without the Constants group (for a settings line or record that shows the
    resolved constants separately)."""
    return [spec for spec in specs if not is_constant(spec)]


def constants_specs(keys: Sequence[str], *, group: str = GROUP, page: str = "") -> list[ParameterSpec]:
    """The Constants group for ``keys`` (table order is the caller's): for each, a choice
    titled with the constant's name, defaulting to the lab/folder value, and the plot's own
    value (the table's default to start), shown only when set for this plot."""
    specs: list[ParameterSpec] = []
    for key in keys:
        constant = TABLE[key]
        if source_name(key) in (spec.name for spec in specs):
            raise ValueError(f"{key} listed twice")
        tip = f"{constant.source}." + (" Unconfirmed: a borrowed value, not yet checked on the current setup."
                                       if constant.unconfirmed else "")
        if constant.shown_only:
            tip += " Shown only: never used in a physics formula."
        specs.append(ParameterSpec(source_name(key), constant.title, "choice", USE_LAYERS, choices=CHOICES,
                                   group=group, page=page,
                                   tip=f"Where the run takes {constant.title} from. {tip}"))
        if constant.choices:  # a coded row: its code, a whole number (its labels are in the tip)
            labels = ", ".join(f"{code:g} = {label}" for code, label in constant.choices.items())
            specs.append(ParameterSpec(value_name(key), f"{constant.title}, this plot", "int", int(default_value(key)),
                                       limits=(min(constant.choices), max(constant.choices)), group=group,
                                       page=page, when=(source_name(key), SET_HERE),
                                       tip=f"This plot's own value: {labels}. {tip}"))
            continue
        specs.append(ParameterSpec(value_name(key), f"{constant.title}, this plot", "float", default_value(key),
                                   limits=limits(key), suffix=constant.unit, group=group, page=page,
                                   when=(source_name(key), SET_HERE), si=constant.unit in SI_UNITS,
                                   # Times in ms and lengths in mm, as in the plots (Tony, 2026-10-20).
                                   unit_prefix=fixed_prefix(key),
                                   tip=f"This plot's own value. {tip}"))
    return specs


def constant_keys(specs: Iterable[ParameterSpec]) -> tuple[str, ...]:
    """The constants a plot's parameters let it override, in declaration order."""
    return tuple(spec.name[len(PREFIX):-len(FROM_SUFFIX)] for spec in specs
                 if is_constant(spec) and spec.name.endswith(FROM_SUFFIX) and spec.kind == "choice")


def clean_layer(values: object, keys: Iterable[str] | None = None) -> dict[str, float]:
    """A layer's values that ``resolve`` accepts: known keys (of ``keys``, if given) with finite
    numbers that the row allows (``Constant.allows``: positive unless signed, at most its maximum;
    a coded row's codes). Anything else (a newer HeLab's key, text, nan, a QE above 1) is left out."""
    if not isinstance(values, Mapping):
        return {}
    allowed = set(TABLE if keys is None else keys) & set(TABLE)
    cleaned: dict[str, float] = {}
    for key, value in values.items():
        if key not in allowed or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if TABLE[str(key)].allows(number):
            cleaned[str(key)] = number
    return cleaned


def folder_layer(found: Mapping[str, tuple[float, str]]) -> dict[str, float]:
    """The folder layer from inherited values (each key's value and the nearest folder at or above
    that sets it, as paths): their values, except a fall time set further up than the nearest fall
    distance. That one isn't paired with a distance set below it (as ``resolve`` keeps a lab fall
    time from a folder's distance): the run derives it, √(2h/g), instead. Likewise a release time
    by hand and a saved arrival at rest (two ways of giving t_r) set in different folders: the
    nearer folder's is kept, so a subfolder's "Use for this folder" wins over a t_r set above it
    (``release.layer_release_time`` breaks a tie in one folder for the t_r by hand)."""
    values = {key: value for key, (value, _) in found.items()}
    if "fall_time" in found and "fall_distance" in found and (
            len(found["fall_distance"][1]) > len(found["fall_time"][1])):
        del values["fall_time"]
    if "release_time" in found and "arrival_time" in found:
        by_hand, saved = len(found["release_time"][1]), len(found["arrival_time"][1])
        if by_hand != saved:
            del values["release_time" if saved > by_hand else "arrival_time"]
    return values


def plot_overrides(values: Mapping[str, Any]) -> dict[str, float]:
    """The values a plot sets for itself: each key whose choice is ``SET_HERE``."""
    chosen = {name[len(PREFIX):-len(FROM_SUFFIX)]: value for name, value in values.items()
              if name.startswith(PREFIX) and name.endswith(FROM_SUFFIX)}
    return clean_layer({key: values.get(value_name(key)) for key, choice in chosen.items() if choice == SET_HERE})


def resolve_for_run(values: Mapping[str, Any], lab: Mapping[str, float] | None = None,
                    folder: Mapping[str, float] | None = None) -> ResolvedConstants:
    """The constants a run uses: the table, then ``lab``, ``folder`` and the plot's own values
    (from its parameter ``values``). Bad layer values are left out (``clean_layer``), never raised."""
    return resolve(lab=clean_layer(lab), folder=clean_layer(folder), plot=plot_overrides(values))


def value_text(key: str, value: float) -> str:
    """``value`` with its unit, short: 848 mm, 416.101 ms, 20,500 ms, 9.79602 m/s², 500 Hz,
    6.64648e-27 kg: lengths in mm and times in ms (``FIXED_PREFIX``, as the plots and the settings
    show them), a wavelength in nm (``KEY_PREFIX``: 1,083.331 nm), Hz with an SI prefix, the
    others in scientific form; "from the data" for an optional row without a value (nan)."""
    unit = TABLE[key].unit
    if math.isnan(value) and TABLE[key].optional:
        return FROM_THE_DATA
    if TABLE[key].choices:
        return TABLE[key].label(value) or f"{value:g}"
    if key in KEY_PREFIX:
        prefix = KEY_PREFIX[key]
        return f"{number_text(value / SI_FACTORS[prefix], 7)} {prefix}{unit}"
    if unit == "s":
        return time_text(value)
    if unit == "m":
        return length_text(value)
    if unit in SI_UNITS:
        return si_text(value, unit, 6)
    return f"{value:.6g} {unit}" if unit else f"{value:.6g}"


def origin_text(constants: ResolvedConstants, key: str) -> str:
    """Where ``key``'s value came from, for display: "folder", "default, unconfirmed"…"""
    text = ORIGIN_TEXT[constants.origins[key]]
    return f"{text}, unconfirmed" if key in constants.unconfirmed else text


def value_and_origin(constants: ResolvedConstants, key: str) -> str:
    """``848 mm (folder)``; ``from the data`` for an optional row no layer set."""
    if not constants.is_set(key):
        return FROM_THE_DATA
    return f"{value_text(key, constants.value(key))} ({origin_text(constants, key)})"


def describe_constants(constants: ResolvedConstants, keys: Iterable[str], *, every: bool = False) -> str:
    """``h 0.85 m (folder) · t_f 0.416 s (derived)``: the ``keys`` a plot uses, for its source line.
    Without ``every``, only values not from the table's defaults (the record has them all)."""
    shown = [f"{SYMBOLS.get(key, key)} {value_and_origin(constants, key)}"
             for key in keys if every or not from_defaults(constants, key)]
    return " · ".join(shown)


def from_defaults(constants: ResolvedConstants, key: str) -> bool:
    """Whether ``key`` is the table's default (a derived fall time: when its distance and g are; an
    optional row no layer set, which a run takes from the data: yes)."""
    origin = constants.origins[key]
    if origin == "detected":
        return True
    if origin == "derived":
        return all(constants.origins[other] == "default" for other in ("fall_distance", "g"))
    return origin == "default"


def record_text(constants: ResolvedConstants, keys: Iterable[str] | None = None) -> str:
    """The constants an analysis uses (``keys``; every constant without), each with its origin, one
    line, for a result's record (the tooltip), then any notes."""
    text = ", ".join(f"{SYMBOLS.get(key, key)} " + (f"= {value_and_origin(constants, key)}" if constants.is_set(key)
                                                    else FROM_THE_DATA)
                     for key in (TABLE if keys is None else keys))
    return text + "".join(f"\nNote: {note}" for note in constants.notes)


def changed_keys(old: ResolvedConstants, new: ResolvedConstants, keys: Iterable[str] | None = None) -> list[str]:
    """The keys (all, or of ``keys``) whose value or origin differs (two unset optional rows, nan
    both, don't)."""
    def same(key: str) -> bool:
        before, after = old.value(key), new.value(key)
        return (before == after or (math.isnan(before) and math.isnan(after))) and old.origins[key] == new.origins[key]
    return [key for key in (TABLE if keys is None else keys) if not same(key)]
