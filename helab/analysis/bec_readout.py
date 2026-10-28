"""The "BEC properties" readout of the T, X, Y histograms (D4/D14 wiring): one axis's fit through
``bec.from_fit`` (N, N0, N0/N, T, Tc, T/Tc, μ, the TF radii, n0 and the two QE checks, each ± SE),
written as a compact block for the plot's header and in full for its record.

Which fit (``choose``): the one the setting names, or by default (``AUTO``, proposed, for Tony)
the best of the fitted axes: a fit that reports a condensate first, then a full projection over a
slice, then an axis along a radial trap axis (T by default; X or Y only once the Trap axial axis
says which is which), then T, X, Y in order. A slice fit holds only part of the cloud, so it gives
only T and R(0) (``bec.from_fit``). Constants still at a borrowed value (the detector QE, the trap
frequencies) are flagged in amber, with what scales with them.

No Qt, no I/O: built in the analysis worker (``from_fit`` solves one ODE, a few ms).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence, cast

from helab.analysis.bec import Axis, BecProperties, axis_roles, from_fit
from helab.analysis.display_units import si_text
from helab.analysis.estimates import Estimate
from helab.analysis.fits import SLICE_NOTE
from helab.analysis.physics import ResolvedConstants
from helab.analysis.profiles import BIMODALS, AxisFit

WARNING = "⚠"  # plot_text.WARNING: what follows it in a title line is amber
AUTO = "auto"
SOURCES = (AUTO, "T", "X", "Y")
# Notes that explain rather than warn: in the record only (the header keeps its warnings).
EXPLANATIONS = ("N and N0 per shot", "T from ", "QE from the thermal cloud:", "N0 is counted:",
                "trap frequencies unconfirmed", "detector QE unconfirmed", SLICE_NOTE)
CM3 = 1e-6  # m⁻³ to cm⁻³, the customary unit of a peak density


def has_condensate(fit: AxisFit) -> bool:
    """A bimodal fit that kept its condensate (the TF + Bose choices' decision reported one)."""
    return fit.ok and fit.choice in BIMODALS and "radius" in fit.fit.estimates


def choose(fits: Mapping[str, AxisFit | None], constants: ResolvedConstants, wanted: str = AUTO
           ) -> tuple[str, str]:
    """(axis, "") for the fit the readout uses, or ("", why there is none)."""
    if wanted != AUTO:
        fit = fits.get(wanted)
        if fit is None:
            return "", f"no fit on {wanted}: turn on Fit {wanted}"
        if not fit.ok:
            return "", f"the {wanted} fit failed"
        return wanted, ""
    usable = [axis for axis in ("T", "X", "Y") if (fit := fits.get(axis)) is not None and fit.ok]
    if not usable:
        return "", ("the fits failed" if any(fit is not None for fit in fits.values())
                    else "need a fit: turn on Fit T, X or Y")
    roles = axis_roles(constants)

    def rank(axis: str) -> tuple[bool, bool, bool]:
        fit = cast(AxisFit, fits[axis])
        return has_condensate(fit), not fit.fit.model.slice, roles[cast(Axis, axis)] == "radial"
    return max(usable, key=lambda axis: (rank(axis), -usable.index(axis))), ""


def _number(estimate: Estimate) -> str:
    return estimate.text()


def _kelvin(estimate: Estimate) -> str:
    return estimate.text(unit="K")


def _metres(estimate: Estimate) -> str:
    return estimate.text(unit="m")


def _density(estimate: Estimate) -> str:
    return Estimate(estimate.value * CM3, estimate.se * CM3).text(unit="cm⁻³", si=False)


def _energy_kelvin(estimate: Estimate, constants: ResolvedConstants) -> Estimate:
    return Estimate(estimate.value / constants.k_B, estimate.se / constants.k_B)


@dataclass(frozen=True)
class BecReadout:
    """One readout: the axis and model it came from and ``properties`` (None, with ``reason``,
    when there is no usable fit)."""
    wanted: str
    axis: str = ""
    model: str = ""
    properties: BecProperties | None = None
    reason: str = ""
    slice: bool = False
    constants: ResolvedConstants | None = field(default=None, compare=False, repr=False)

    @property
    def unconfirmed(self) -> tuple[str, ...]:
        """The borrowed constants the shown numbers lean on: the QE (not for a slice: it gives no
        atom numbers) and the trap frequencies."""
        if self.properties is None or self.constants is None:
            return ()
        keys = ("trap_radial", "trap_axial") if self.slice else ("detector_qe", "trap_radial", "trap_axial")
        return tuple(key for key in keys if key in self.constants.unconfirmed)

    def items(self, full: bool = False) -> list[str]:
        """``name value`` pairs, those with a value; ``full`` adds the Tc steps, T/Tc0 from N0/N,
        μ/k_BT, the saturated thermal number and the radius check's steps."""
        props, constants = self.properties, self.constants
        if props is None or constants is None:
            return []
        pairs: list[tuple[str, Estimate, Any]] = []
        condensed = props.condensed.value > 0
        if not self.slice:
            pairs.append(("N", props.atoms, _number))
            if condensed:
                pairs += [("N0", props.condensed, _number), ("N0/N", props.fraction, _number)]
            elif math.isfinite(props.atoms.value):
                pairs.append(("no condensate", Estimate(0.0), lambda _: "(thermal fit)"))
        pairs.append(("T", props.temperature, _kelvin))
        if not self.slice:
            pairs.append(("Tc", props.tc, _kelvin))
            if full:
                pairs += [("Tc ideal", props.tc_ideal, _kelvin), ("Tc finite size", props.tc_finite_size, _kelvin)]
            else:
                pairs.append(("Tc0", props.tc_ideal, _kelvin))
            pairs.append(("T/Tc", props.t_over_tc, _number))
            if full:
                pairs.append(("T/Tc0 from N0/N", props.t_over_tc_ideal, _number))
            pairs.append(("μ/k_B", _energy_kelvin(props.chemical_potential, constants), _kelvin))
            if full:
                pairs.append(("μ/k_BT", props.mu_over_kt, _number))
            radial, _, axial = props.radii
            pairs += [("R(0) ⊥", radial, _metres), ("R(0) z", axial, _metres), ("n0", props.peak_density, _density)]
            if full:
                pairs.append(("saturated thermal N", props.saturated_thermal, _number))
        check = props.from_radius
        if check is not None:
            if full:
                pairs.append((f"R(t_f) fitted on {check.axis}", check.at_detector, _metres))
            pairs.append((f"R(0) fitted on {check.axis}", check.in_trap, _metres))
            if full:
                pairs += [("μ/k_B from R", _energy_kelvin(check.chemical_potential, constants), _kelvin),
                          ("N0 from R", check.condensed, _number)]
            pairs.append(("QE from R", check.implied_qe, _number))
        if not self.slice:
            pairs.append(("QE from thermal", props.implied_qe_thermal, _number))
        return [f"{name} {format_(estimate)}" for name, estimate, format_ in pairs if math.isfinite(estimate.value)]

    def heading(self) -> str:
        if self.properties is None:
            return "BEC properties"
        return f"BEC properties from {self.axis} ({self.model}{', slice: T and R(0) only' if self.slice else ''})"

    def unconfirmed_text(self) -> str:
        """``⚠ unconfirmed: QE 0.1, trap 500 Hz / 50 Hz: …`` ("" when every one is confirmed)."""
        keys, constants = self.unconfirmed, self.constants
        if not keys or constants is None:
            return ""
        parts = []
        if "detector_qe" in keys:
            parts.append(f"QE {constants.detector_qe:g} (N, N0 ∝ 1/QE)")
        if "trap_radial" in keys or "trap_axial" in keys:
            parts.append(f"trap {constants.trap_radial:g} Hz / {constants.trap_axial:g} Hz (Tc, μ, R(0), n0)")
        return f"{WARNING} unconfirmed: {', '.join(parts)}"

    def warnings(self) -> list[str]:
        """The notes that warn (the explanations are in the record)."""
        if self.properties is None:
            return [f"BEC properties: {self.reason}"]
        return [note for note in self.properties.notes if not note.startswith(EXPLANATIONS)]

    def title_lines(self) -> list[str]:
        """The header's block: the numbers (one line: the header wraps it), the unconfirmed
        constants in amber; ``warnings`` go after it, in amber, one per line."""
        if self.properties is None:
            return []
        return [f"{self.heading()}: {' · '.join(self.items())}", self.unconfirmed_text()]

    def record_lines(self) -> list[str]:
        """Every number and note, for the dock's record."""
        if self.properties is None:
            return [f"BEC properties: {self.reason}"]
        props = self.properties
        lines = [f"{self.heading()}: {', '.join(self.items(full=True))}",
                 f"BEC trap: ω̄ = 2π × {si_text(props.mean_frequency / (2 * math.pi), 'Hz')}, a_ho = "
                 f"{si_text(props.oscillator_length, 'm')}"]
        if unconfirmed := self.unconfirmed_text():
            lines.append(f"BEC constants: {unconfirmed.lstrip(WARNING).strip()}")
        lines += [f"BEC note: {note}" for note in props.notes]
        return lines

    def as_record(self) -> dict[str, Any]:
        """Strict JSON: what was asked and used, and ``BecProperties.as_record``."""
        record: dict[str, Any] = {"wanted": self.wanted, "axis": self.axis or None, "model": self.model or None,
                                  "reason": self.reason, "slice": self.slice, "unconfirmed": list(self.unconfirmed)}
        if self.properties is not None:
            record["properties"] = self.properties.as_record()
        return record


def readout(fits: Sequence[AxisFit | None], axes: Sequence[str], bin_widths: Sequence[float], shots: int,
            constants: ResolvedConstants, wanted: str = AUTO) -> BecReadout:
    """The readout from the histograms' fits (per axis, None where not fitted), their bins' widths
    (s or m) and the shots they sum."""
    by_axis = dict(zip(axes, fits))
    axis, reason = choose(by_axis, constants, wanted)
    if not axis:
        return BecReadout(wanted, reason=reason, constants=constants)
    fit = cast(AxisFit, by_axis[axis])
    width = bin_widths[list(axes).index(axis)]
    properties = from_fit(fit.fit, cast(Axis, axis), constants, width, shots)
    if not (math.isfinite(properties.temperature.value) or math.isfinite(properties.atoms.value)):
        return BecReadout(wanted, axis, fit.choice, reason=next(iter(properties.notes), "no properties"),
                          constants=constants)
    return BecReadout(wanted, axis, fit.choice, properties, slice=fit.fit.model.slice, constants=constants)
