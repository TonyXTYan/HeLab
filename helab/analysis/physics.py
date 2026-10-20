"""Physical constants and lab parameters for the DLD analyses, in one table, with the few
conversions every fit needs (fall time, thermal temperature from a width).

Each value carries where it came from and whether it is confirmed on the current setup
(roadmaps/dld-front-panel-port.md: legacy hardware values are starting points, not
defaults to trust). Values are layered (F0b builds the settings that fill the layers):

1. the defaults in ``CONSTANTS``;
2. **lab** parameters (Settings, app-wide);
3. **folder** settings (per data root, in HeLab's store);
4. **plot** overrides.

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
from typing import Any, Literal, Mapping, cast, get_args

import scipy.constants as codata

from helab.analysis.display_units import length_text, time_text
from helab.analysis.estimates import Estimate

Level = Literal["lab", "folder"]
# Where a resolved value came from: the table's default, one of the layers, or derived
# from other values (the fall time from the distance and g).
Origin = Literal["default", "lab", "folder", "plot", "derived"]
ORIGINS: tuple[str, ...] = get_args(Origin)
LAYERS: tuple[Origin, ...] = ("lab", "folder", "plot")

# The He-4 atomic mass (AME2020, 4.002 603 254 13(6) u); helium's standard atomic weight,
# 4.002602, is a different number. The metastable state's ~20 eV/c² is negligible (2e-8).
HE4_MASS_U = 4.00260325413
# A fall time set by hand that differs from √(2h/g) by more than this (relative) is noted.
FALL_TIME_TOLERANCE = 1e-3


@dataclass(frozen=True)
class Constant:
    """One row of the table. ``value`` nan means derived (the fall time, unless set)."""
    key: str
    title: str
    unit: str
    value: float
    source: str
    level: Level  # where F0b lets the user set it
    unconfirmed: bool = False  # a borrowed legacy value, not yet checked on the current setup
    shown_only: bool = False  # displayed (and used for flags), never in a physics formula
    codata: bool = False  # a fundamental constant from scipy.constants

    @property
    def derived(self) -> bool:
        return math.isnan(self.value)


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
)
TABLE: Mapping[str, Constant] = MappingProxyType({constant.key: constant for constant in CONSTANTS})


def fall_time(distance: float, g: float) -> float:
    """√(2h/g): the time to fall ``distance`` from rest. nan unless both are positive."""
    if not (distance > 0 and g > 0) or not math.isfinite(distance * g):
        return math.nan
    return math.sqrt(2 * distance / g)


@dataclass(frozen=True)
class ResolvedConstants:
    """The values a run used, one attribute per ``TABLE`` key, and where each came from.
    Hashable by its values (``origins`` is compared, not hashed)."""
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
    origins: Mapping[str, Origin] = field(hash=False)

    def value(self, key: str) -> float:
        if key not in TABLE:
            raise KeyError(key)
        return float(getattr(self, key))

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

    def as_record(self) -> dict[str, Any]:
        """JSON values only, for a result's record:
        ``{"values": …, "origins": …, "unconfirmed": […], "notes": […]}``."""
        return {"values": {key: self.value(key) for key in TABLE}, "origins": dict(self.origins),
                "unconfirmed": list(self.unconfirmed), "notes": list(self.notes)}

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> ResolvedConstants:
        """Read back ``as_record``. Every ``TABLE`` key needs a finite value and a known
        origin (else ``ValueError``); keys the table doesn't have (a newer version's) are
        ignored, and ``unconfirmed`` and ``notes`` are recomputed, not read."""
        values, origins = record["values"], record["origins"]
        missing = [key for key in TABLE if key not in values or key not in origins]
        if missing:
            raise ValueError(f"constants record lacks {', '.join(missing)}")
        bad = [key for key in TABLE if origins[key] not in ORIGINS or not math.isfinite(float(values[key]))]
        if bad:
            raise ValueError(f"constants record has bad values or origins for {', '.join(bad)}")
        return cls(**{key: float(values[key]) for key in TABLE},
                   origins=MappingProxyType({key: cast(Origin, origins[key]) for key in TABLE}))


def resolve(lab: Mapping[str, float] | None = None, folder: Mapping[str, float] | None = None,
            plot: Mapping[str, float] | None = None) -> ResolvedConstants:
    """The table's defaults, overridden by the lab, then folder, then plot layers (more
    specific wins). Every value must be finite and positive; an unknown key or a bad value
    raises ``ValueError`` (F0b validates input before it gets here).

    The fall time is derived, √(2h/g), from the effective distance and g, unless a layer at
    least as specific as the one that set the distance (or g) sets it by hand: a folder's new
    fall distance isn't silently paired with a lab-wide fall time. A fall time kept by hand
    that disagrees with √(2h/g) is noted (``ResolvedConstants.notes``)."""
    chosen: dict[str, tuple[float, Origin]] = {key: (constant.value, "default") for key, constant in TABLE.items()}
    rank = {"default": 0, **{layer: index + 1 for index, layer in enumerate(LAYERS)}}
    for layer, given in zip(LAYERS, (lab, folder, plot)):
        for key, value in (given or {}).items():
            if key not in TABLE:
                raise ValueError(f"unknown constant {key!r}")
            number = float(value)
            if not (math.isfinite(number) and number > 0):
                raise ValueError(f"{TABLE[key].title} must be finite and positive, not {value!r}")
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
