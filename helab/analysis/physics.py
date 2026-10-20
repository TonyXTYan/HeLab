"""Physical constants and lab parameters for the DLD analyses, in one table, with the few
conversions every fit needs (fall time, thermal temperature from a width).

Each value carries where it came from and whether it is confirmed on the current setup
(roadmaps/dld-front-panel-port.md: legacy hardware values are starting points, not
defaults to trust). Values are layered (F0b builds the settings that fill the layers):

1. the defaults in ``CONSTANTS``;
2. **lab** parameters (Settings, app-wide);
3. **folder** settings (per data root, in HeLab's store);
4. **plot** overrides.

A few rows have no default: they come "from the data" (``Constant.optional``: the release time,
the arrival of the cloud at rest and the trap's XY origin, which the Release time plot detects).
Unset in every layer, they resolve to nan with the origin "detected": a plot then detects the
value itself, or assumes one (the origin: 0, 0), and records which (``helab.analysis.release``).
Set in a layer, they resolve like any other row. ``Constant.signed`` rows (the origin's
positions) take any finite value, zero and negative included; the others must be positive.

``resolve`` merges them when a run starts (compute does no I/O) into a frozen
``ResolvedConstants`` that the run records in its result (``as_record``, JSON values only).
The conversions take the run's ``ResolvedConstants``, never the defaults, so every number a
result shows comes from constants it recorded.
No Qt and no I/O, so it runs in the analysis worker and in tests. SI units throughout.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import Any, Iterable, Literal, Mapping, cast, get_args

import scipy.constants as codata

from helab.analysis.display_units import length_text, time_text
from helab.analysis.estimates import Estimate

Level = Literal["lab", "folder"]
# Where a resolved value came from: the table's default, one of the layers, derived from
# other values (the fall time from the distance and g), or "detected": an optional row no
# layer sets, whose value (nan here) a run takes from the data.
Origin = Literal["default", "lab", "folder", "plot", "derived", "detected"]
ORIGINS: tuple[str, ...] = get_args(Origin)
LAYERS: tuple[Origin, ...] = ("lab", "folder", "plot")

# The He-4 atomic mass (AME2020, 4.002 603 254 13(6) u); helium's standard atomic weight,
# 4.002602, is a different number. The metastable state's ~20 eV/c² is negligible (2e-8).
HE4_MASS_U = 4.00260325413
# A fall time set by hand that differs from √(2h/g) by more than this (relative) is noted.
FALL_TIME_TOLERANCE = 1e-3


@dataclass(frozen=True)
class Constant:
    """One row of the table. ``value`` nan means derived (the fall time, unless set), or for an
    ``optional`` row, no default: "from the data"."""
    key: str
    title: str
    unit: str
    value: float
    source: str
    level: Level  # where F0b lets the user set it
    unconfirmed: bool = False  # a borrowed legacy value, not yet checked on the current setup
    shown_only: bool = False  # displayed (and used for flags), never in a physics formula
    codata: bool = False  # a fundamental constant from scipy.constants
    optional: bool = False  # no default: unset, a run detects it from the data (origin "detected")
    signed: bool = False  # any finite value (a time or a position); otherwise positive only

    @property
    def derived(self) -> bool:
        return math.isnan(self.value) and not self.optional

    def accepts(self, value: float) -> bool:
        """Whether a layer may set this row to ``value``: finite, and positive unless ``signed``."""
        return math.isfinite(value) and (self.signed or value > 0)


CONSTANTS: tuple[Constant, ...] = (
    Constant("hbar", "Reduced Planck constant ħ", "J s", codata.hbar, "CODATA (scipy.constants)", "lab",
             codata=True),
    Constant("k_B", "Boltzmann constant k_B", "J/K", codata.k, "CODATA (scipy.constants)", "lab", codata=True),
    Constant("u", "Atomic mass constant u", "kg", codata.atomic_mass, "CODATA (scipy.constants)", "lab",
             codata=True),
    Constant("mass", "He* mass", "kg", HE4_MASS_U * codata.atomic_mass,
             f"He-4 atomic mass, {HE4_MASS_U} u (AME2020) × CODATA u. The legacy front panel had 6.6464e-27 kg",
             "lab"),
    Constant("g", "Gravitational acceleration g", "m/s²", 9.79602,
             "Canberra, Core hebec_constants (9.7960207 − 78e-8, GGMplus at the ANU)", "lab"),
    Constant("scattering_length", "He* scattering length a", "m", 7.512e-9,
             "Spin-polarised He* (m = +1), Moal et al., PRL 96, 023203 (2006); Core hebec_constants", "lab"),
    Constant("fall_distance", "Fall distance h", "m", 0.848,
             "Tony 2026-10-20, for now: Momentum_Bells_test lib/monitor_halos.m (2024) and the front panel. "
             "monitor_momentum.m has 0.852925545 m; measure from a cloud released at rest", "folder",
             unconfirmed=True),
    Constant("fall_time", "Fall time t_f", "s", math.nan,
             "Derived, √(2h/g) (0.4161 s at 0.848 m), unless set by hand. The legacy scripts' 0.417 s went "
             "with 0.8529 m", "folder", unconfirmed=True),
    Constant("trap_radial", "Trap frequency, radial", "Hz", 500.0, "Front panel, 2017 only: stale", "folder",
             unconfirmed=True),
    Constant("trap_axial", "Trap frequency, axial", "Hz", 50.0, "Front panel, 2017 only: stale", "folder",
             unconfirmed=True),
    Constant("dld_trigger", "DLD trigger", "s", 20.5, "monitor_momentum.m, since 2023-09 (sequence time)", "lab",
             unconfirmed=True, shown_only=True),
    Constant("dld_acquisition", "DLD acquisition", "s", 2.0,
             "monitor_momentum.m, 2026-09; a shot whose last count is earlier is incomplete", "lab",
             unconfirmed=True, shown_only=True),
    # D8: from the data (the Release time plot), or set by hand. Its "Use for this folder" saves the
    # arrival and the origin, not t_r: each plot then takes t_r = t_a − t_f with its own fall time
    # (helab.analysis.release.layer_release_time), so a cloud at rest stays at v_z = 0.
    Constant("release_time", "Release time t_r", "s", math.nan,
             "From the data: one cloud's arrival − t_f (the Release time plot), in DLD time; set by hand to "
             "fix it (it then wins over a saved arrival at the same level). The front panel's switch-off, "
             "22.954 s, is out of date", "folder", optional=True),
    Constant("arrival_time", "Arrival at rest t_a", "s", math.nan,
             "From the data: when the cloud released at rest arrives, in DLD time (the Release time plot's Use "
             "for this folder); plots take t_r = t_a − t_f with their own fall time", "folder", optional=True),
    Constant("trap_x", "Trap origin X x₀", "m", math.nan,
             "From the data: the X of the cloud released at rest (the Release time plot); unset and not "
             "detected, 0 (the trap above X = 0)", "folder", optional=True, signed=True),
    Constant("trap_y", "Trap origin Y y₀", "m", math.nan,
             "From the data: the Y of the cloud released at rest (the Release time plot); unset and not "
             "detected, 0 (the trap above Y = 0)", "folder", optional=True, signed=True),
)
TABLE: Mapping[str, Constant] = MappingProxyType({constant.key: constant for constant in CONSTANTS})
OPTIONAL: tuple[str, ...] = tuple(constant.key for constant in CONSTANTS if constant.optional)


def fall_time(distance: float, g: float) -> float:
    """√(2h/g): the time to fall ``distance`` from rest. nan unless both are positive."""
    if not (distance > 0 and g > 0) or not math.isfinite(distance * g):
        return math.nan
    return math.sqrt(2 * distance / g)


@dataclass(frozen=True, eq=False)
class ResolvedConstants:
    """The values a run used, one attribute per ``TABLE`` key, and where each came from.
    Hashable by its values (``origins`` is compared, not hashed). An optional row no layer set is
    nan, origin "detected" (``is_set``); such nans compare equal (``__eq__``, ``__hash__``)."""
    hbar: float
    k_B: float
    u: float
    mass: float
    g: float
    scattering_length: float
    fall_distance: float
    fall_time: float
    trap_radial: float
    trap_axial: float
    dld_trigger: float
    dld_acquisition: float
    release_time: float
    arrival_time: float
    trap_x: float
    trap_y: float
    origins: Mapping[str, Origin] = field(hash=False)

    def value(self, key: str) -> float:
        if key not in TABLE:
            raise KeyError(key)
        return float(getattr(self, key))

    def _values(self) -> tuple[float | None, ...]:
        """The values in table order, an unset optional row's (nan) as None: what equality and
        the hash compare (nan never equals itself)."""
        return tuple(self.value(key) if self.is_set(key) else None for key in TABLE)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ResolvedConstants):
            return NotImplemented
        return self._values() == other._values() and dict(self.origins) == dict(other.origins)

    def __hash__(self) -> int:
        return hash(self._values())

    def is_set(self, key: str) -> bool:
        """Whether ``key`` has a value: false only for an optional row no layer set ("detected")."""
        return self.origins[key] != "detected"

    @property
    def unconfirmed(self) -> tuple[str, ...]:
        """Keys still at a borrowed legacy default (or derived from one), table order."""
        def borrowed(key: str) -> bool:
            if self.origins[key] == "derived":
                return any(borrowed(other) for other in ("fall_distance", "g"))
            return self.origins[key] == "default" and TABLE[key].unconfirmed
        return tuple(key for key in TABLE if borrowed(key))

    @property
    def notes(self) -> tuple[str, ...]:
        """Disagreements to show beside the values: a fall time set by hand more than
        ``FALL_TIME_TOLERANCE`` from √(2h/g) of the distance and g in use."""
        expected = fall_time(self.fall_distance, self.g)
        if self.origins["fall_time"] == "derived" or not math.isfinite(expected):
            return ()
        if abs(self.fall_time - expected) <= FALL_TIME_TOLERANCE * expected:
            return ()
        return (f"fall time and distance disagree: t_f {time_text(self.fall_time)} ({self.origins['fall_time']}), "
                f"but √(2h/g) is {time_text(expected)} for h {length_text(self.fall_distance)} "
                f"({self.origins['fall_distance']}) and g {self.g:.6g} m/s² ({self.origins['g']})",)

    def as_record(self, keys: Iterable[str] | None = None) -> dict[str, Any]:
        """JSON values only, for a result's record:
        ``{"values": …, "origins": …, "unconfirmed": […], "notes": […]}``; an unset optional
        row's value is None. With ``keys``, only those (table order; the fall-time note only with
        ``fall_time``), so rows an analysis doesn't use never change its record; ``from_record``
        reads back the whole record only."""
        wanted = set(TABLE if keys is None else keys)
        chosen = [key for key in TABLE if key in wanted]
        return {"values": {key: self.value(key) if self.is_set(key) else None for key in chosen},
                "origins": {key: self.origins[key] for key in chosen},
                "unconfirmed": [key for key in self.unconfirmed if key in wanted],
                "notes": list(self.notes) if "fall_time" in wanted else []}

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> ResolvedConstants:
        """Read back ``as_record``. Every ``TABLE`` key needs a value its row accepts and a known
        origin (else ``ValueError``), except an optional row: "detected" with no value (None),
        also when the record lacks it (an older version's). Keys the table doesn't have (a newer
        version's) are ignored, and ``unconfirmed`` and ``notes`` are recomputed, not read."""
        values, origins = dict(record["values"]), dict(record["origins"])
        for key in OPTIONAL:
            if key not in values and key not in origins:
                values[key], origins[key] = None, "detected"
        missing = [key for key in TABLE if key not in values or key not in origins]
        if missing:
            raise ValueError(f"constants record lacks {', '.join(missing)}")

        def good(key: str) -> bool:
            if origins[key] not in ORIGINS:
                return False
            if origins[key] == "detected":
                return TABLE[key].optional and values[key] is None
            return values[key] is not None and TABLE[key].accepts(float(values[key]))
        bad = [key for key in TABLE if not good(key)]
        if bad:
            raise ValueError(f"constants record has bad values or origins for {', '.join(bad)}")
        return cls(**{key: math.nan if values[key] is None else float(values[key]) for key in TABLE},
                   origins=MappingProxyType({key: cast(Origin, origins[key]) for key in TABLE}))


def resolve(lab: Mapping[str, float] | None = None, folder: Mapping[str, float] | None = None,
            plot: Mapping[str, float] | None = None) -> ResolvedConstants:
    """The table's defaults, overridden by the lab, then folder, then plot layers (more
    specific wins). Every value must be finite, and positive unless its row is ``signed``; an
    unknown key or a bad value raises ``ValueError`` (F0b validates input before it gets here).
    An optional row no layer sets is nan, origin "detected".

    The fall time is derived, √(2h/g), from the effective distance and g, unless a layer at
    least as specific as the one that set the distance (or g) sets it by hand: a folder's new
    fall distance isn't silently paired with a lab-wide fall time. A fall time kept by hand
    that disagrees with √(2h/g) is noted (``ResolvedConstants.notes``)."""
    chosen: dict[str, tuple[float, Origin]] = {
        key: (math.nan, "detected") if constant.optional else (constant.value, "default")
        for key, constant in TABLE.items()}
    rank = {"default": 0, **{layer: index + 1 for index, layer in enumerate(LAYERS)}}
    for layer, given in zip(LAYERS, (lab, folder, plot)):
        for key, value in (given or {}).items():
            if key not in TABLE:
                raise ValueError(f"unknown constant {key!r}")
            number = float(value)
            if not TABLE[key].accepts(number):
                kind = "finite" if TABLE[key].signed else "finite and positive"
                raise ValueError(f"{TABLE[key].title} must be {kind}, not {value!r}")
            chosen[key] = (number, layer)
    _, time_origin = chosen["fall_time"]
    if time_origin == "default" or rank[time_origin] < max(rank[chosen[key][1]] for key in ("fall_distance", "g")):
        chosen["fall_time"] = (fall_time(chosen["fall_distance"][0], chosen["g"][0]), "derived")
    return ResolvedConstants(**{key: value for key, (value, _) in chosen.items()},
                             origins=MappingProxyType({key: origin for key, (_, origin) in chosen.items()}))


assert {item.name for item in fields(ResolvedConstants)} - {"origins"} == set(TABLE), \
    "ResolvedConstants and TABLE must list the same keys"
DEFAULTS = resolve()


# Temperature from a cloud's width: ideal gas, pure expansion (the initial cloud size is
# neglected, so the width after the fall is the velocity spread's alone).
# - Along T: with z up and the detector h below the trap, z(t) = h + v_z t − ½ g t². An atom
#   released at rest arrives at t_f = √(2h/g), moving at −g t_f. A small upward v_z moves it
#   by v_z t_f by then, so it arrives δt = v_z t_f / (g t_f) = v_z / g later: σ_v = g σ_t.
#   (An initial height spread σ_z0 would add σ_z0 / (g t_f); neglected.)
# - Along X/Y: x = v_x t_f, so σ_v = σ_x / t_f.
# - Each axis's Maxwell–Boltzmann velocity spread is σ_v² = k_B T / m.
# Each takes the run's constants, so the numbers match what its result records.


def sigma_v_from_arrival_width(sigma_t: float, constants: ResolvedConstants) -> float:
    """σ_v = g σ_t, from the width of the arrival-time (T) profile."""
    return constants.g * sigma_t


def sigma_v_from_transverse_width(sigma_x: float, constants: ResolvedConstants) -> float:
    """σ_v = σ_x / t_f, from the width of an X or Y profile after the fall."""
    return sigma_x / constants.fall_time if constants.fall_time > 0 else math.nan


def thermal_temperature(sigma_v: float, constants: ResolvedConstants) -> float:
    """T = m σ_v² / k_B, in kelvin: the temperature whose velocity spread along one axis is σ_v."""
    return constants.mass * sigma_v ** 2 / constants.k_B


def temperature_estimate(sigma_v: Estimate, constants: ResolvedConstants) -> Estimate:
    """``thermal_temperature`` with its standard error: T ∝ σ_v², so SE(T) = 2 T · SE(σ_v)/σ_v
    (first order), i.e. 2 m |σ_v| SE(σ_v) / k_B."""
    return Estimate(thermal_temperature(sigma_v.value, constants),
                    2 * constants.mass * abs(sigma_v.value) * sigma_v.se / constants.k_B)
