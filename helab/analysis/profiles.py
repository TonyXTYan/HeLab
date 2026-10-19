"""T/X/Y profiles for the histogram plot (D1): display units, rates per shot, Gaussian
smoothing, and the fits with their temperatures.

roadmaps/dld-front-panel-port.md (Decided) sets the units and the rate method, after the
front panel's ``dld_plot_tof.m`` with its bug fixed:
- **Axes:** X and Y in mm; T in ms or s, chosen from its range (``display_unit``).
- **Rates:** counts / bin width / number of shots, after the view range (and, when chosen,
  the whole box) has picked the events: T in kHz per shot (per ms), X and Y per mm per shot
  (the front panel divided X and Y by the bin width only).
- **Smoothing** (optional): a Gaussian of σ over bins of σ/5 (the front panel's
  ``bin_factor``). Fits use the unsmoothed counts unless the smoothed curve is chosen.

Fits are in the data's own units (s, m) on counts per bin; drawing scales the fitted curve by
the same factor as the bars. No Qt and no I/O: runs in the analysis worker and in tests.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from helab.analysis.estimates import Estimate, si_prefix
from helab.analysis.fits import MODELS, FitModel, FitResult, arrival_time_model, bin_centres, fit_histogram
from helab.analysis.physics import (TABLE, ResolvedConstants, sigma_v_from_arrival_width,
                                    sigma_v_from_transverse_width, temperature_estimate)

Array = npt.NDArray[np.float64]

# Units

COUNTS, RATE = "counts", "rate per shot"
# Bin widths, in the data's s and m, to the rate's ms and mm: T per ms is kHz.
RATE_UNITS = {"T": "kHz per shot", "X": "per mm per shot", "Y": "per mm per shot"}
RATE_SCALE = 1e3
# T below this span (s) is shown in ms, else in s.
T_SECONDS_FROM = 1.0


def display_unit(axis: str, low: float, high: float) -> tuple[float, str]:
    """(factor, unit) to show an axis's values (data in s and m): X and Y in mm, T in ms when
    its range spans under ``T_SECONDS_FROM`` (1 s), else in s."""
    if axis != "T":
        return 1e3, "mm"
    span = high - low
    return (1e3, "ms") if math.isfinite(span) and span < T_SECONDS_FROM else (1.0, "s")


def unit_of(axis: str) -> str:
    """The data's unit of an axis: s for T, m for X and Y (``Estimate.text`` adds the prefix)."""
    return "s" if axis == "T" else "m"


def rate_factor(bin_width: float, shots: int) -> float:
    """What turns counts per bin into a rate per shot: 1 / (bin width in ms or mm × shots).
    nan without shots or a positive width."""
    if shots <= 0 or not bin_width > 0:
        return math.nan
    return 1.0 / (bin_width * RATE_SCALE * shots)


def value_label(axis: str, units: str, every: bool = False) -> str:
    """The y axis's title: ``Events`` (per bin) or ``Rate (kHz per shot)``; ``every`` (beside
    one highlighted shot's axis): ``Events (all)``, ``Rate, all (kHz per shot)``."""
    if units == RATE:
        return f"Rate{', all' if every else ''} ({RATE_UNITS[axis]})"
    return "Events (all)" if every else "Events"


# Smoothing

SMOOTH_BIN_FACTOR = 5  # bins of σ/5
SMOOTH_MAX_BINS = 5000  # more would be needed: the bins are widened to fit, and the plot says so
KERNEL_HALF_WIDTH = 4.0  # the kernel is cut at ±4 σ (and normalised)


def si_text(value: float, unit: str) -> str:
    """``0.1 ms``, ``200 µm``: a value with an SI prefix, 3 significant digits."""
    exponent, prefix = si_prefix(value)
    return f"{value / 10 ** exponent:.3g} {prefix}{unit}"


def smoothing_bins(low: float, high: float, sigma: float, unit: str = "") -> tuple[int, str]:
    """The bin count giving bins of σ/5 over [low, high], at most ``SMOOTH_MAX_BINS``, and a
    note when that cap widened them (``unit``: the data's, for the note)."""
    if not (high > low and sigma > 0):
        return 1, ""
    wanted = math.ceil((high - low) / (sigma / SMOOTH_BIN_FACTOR))
    if wanted <= SMOOTH_MAX_BINS:
        return max(wanted, 1), ""
    return SMOOTH_MAX_BINS, (f"bins widened to {si_text((high - low) / SMOOTH_MAX_BINS, unit)} (σ/5 would "
                             f"need {wanted:,} bins; at most {SMOOTH_MAX_BINS:,})")


def gaussian_kernel(sigma_bins: float) -> Array:
    """A normalised Gaussian of ``sigma_bins`` bins, cut at ±4 σ (odd length, centred)."""
    half = max(int(math.ceil(KERNEL_HALF_WIDTH * sigma_bins)), 1)
    offsets = np.arange(-half, half + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (offsets / max(sigma_bins, 1e-12)) ** 2)
    return np.asarray(kernel / kernel.sum(), dtype=np.float64)


def _convolve(values: Array, kernel: Array) -> Array:
    """``values`` convolved with ``kernel``, the edges reflected (the bins beyond an edge mirror
    those inside), so what spreads past an edge folds back in and the total is kept."""
    half = len(kernel) // 2
    padded = np.pad(values, half, mode="symmetric")
    return np.asarray(np.convolve(padded, kernel, mode="valid"), dtype=np.float64)


def smooth(counts: npt.ArrayLike, sigma_bins: float) -> Array:
    """Counts smoothed with a Gaussian of ``sigma_bins`` bins; their sum is kept."""
    return _convolve(np.asarray(counts, dtype=np.float64), gaussian_kernel(sigma_bins))


def smoothed_errors(counts: npt.ArrayLike, sigma_bins: float) -> Array:
    """Each smoothed bin's Poisson error, √(Σ k² n) (at least the error of one count spread
    by the kernel, so empty stretches keep a weight). Neighbouring smoothed bins share counts,
    so they are correlated: a fit treating them as independent gets approximate SEs."""
    kernel = gaussian_kernel(sigma_bins)
    variance = _convolve(np.asarray(counts, dtype=np.float64), kernel ** 2)
    floor = float(np.sum(kernel ** 2))
    return np.asarray(np.sqrt(np.maximum(variance, floor)), dtype=np.float64)


# Fits

GAUSSIAN, ARRIVAL, BIMODAL = "Gaussian", "Arrival-time thermal", "Bimodal TF² + Gaussian"
T_MODELS = (GAUSSIAN, ARRIVAL, BIMODAL)
XY_MODELS = (GAUSSIAN, BIMODAL)
MODEL_KEYS = {GAUSSIAN: "gaussian", ARRIVAL: "arrival_time", BIMODAL: "bimodal_tf2_gaussian"}
UNSMOOTHED, SMOOTHED = "unsmoothed counts", "smoothed curve"
CURVE_POINTS = 600  # the drawn fit's samples across the range


def model_for(choice: str, constants: ResolvedConstants) -> FitModel:
    """The fit model a choice names; the arrival-time profile with the run's fall distance and g."""
    if choice == ARRIVAL:
        return arrival_time_model(constants.fall_distance, constants.g)
    return MODELS[MODEL_KEYS.get(choice, "gaussian")]


@dataclass(frozen=True)
class AxisFit:
    """One axis's fit: the ``FitResult`` (in s or m, counts per bin), the centre and width
    (σ; a bimodal fit's thermal σ) with the velocity spread and temperature they give, and
    the curve to draw (``x``, ``y`` in counts per bin)."""
    axis: str
    choice: str
    fit: FitResult
    centre: Estimate
    width: Estimate
    sigma_v: Estimate
    temperature: Estimate
    x: Array
    y: Array
    notes: tuple[str, ...] = ()
    on_smoothed: bool = False

    def __post_init__(self) -> None:
        for array in (self.x, self.y):
            array.flags.writeable = False

    @property
    def ok(self) -> bool:
        return self.fit.ok

    @property
    def failure(self) -> str:
        return self.fit.failure

    def text(self) -> str:
        """``Gaussian: centre (416.12 ± 0.12) ms · σ (4.65 ± 0.05) ms · T (1.00 ± 0.02) µK``, or
        why there is no fit."""
        if not self.ok:
            return f"{self.choice} fit failed: {self.failure}"
        unit = unit_of(self.axis)
        width = "σ thermal" if self.choice == BIMODAL else ("σ_v/g" if self.choice == ARRIVAL else "σ")
        parts = [f"centre {self.centre.text(unit=unit)}", f"{width} {self.width.text(unit=unit)}",
                 f"T {self.temperature.text(unit='K')}"]
        if self.choice == BIMODAL and "radius" in self.fit.estimates:
            parts.insert(2, f"R {self.fit['radius'].text(unit=unit)}")
        return f"{self.choice}: " + " · ".join(parts)

    def as_record(self) -> dict[str, Any]:
        """Strict JSON: the fit's record and the numbers derived from it."""
        return {"axis": self.axis, "model": self.choice, "fit": self.fit.as_record(),
                "centre": self.centre.as_record(), "width": self.width.as_record(),
                "sigma_v": self.sigma_v.as_record(), "temperature": self.temperature.as_record(),
                "on_smoothed": self.on_smoothed, "notes": list(self.notes)}


def _scaled(estimate: Estimate, factor: float) -> Estimate:
    return Estimate(estimate.value * factor, abs(estimate.se * factor))


def fit_axis(axis: str, edges: npt.ArrayLike, counts: npt.ArrayLike, choice: str, constants: ResolvedConstants,
             smoothing: float | None = None) -> AxisFit:
    """Fit one histogram (``edges`` in s or m, raw ``counts``) with the model ``choice`` names.

    ``smoothing`` (σ in the data's units) fits the smoothed curve instead, with each bin's
    propagated error; the fitted width then includes the smoothing, which is taken out in
    quadrature (√(σ² − σ_s²), exact for a Gaussian) before the temperature, with a note.
    Temperatures are the ideal-gas, pure-expansion ones (``physics``): along T σ_v = g σ, along
    X and Y σ_v = σ / t_f, each with the run's constants."""
    edges = np.asarray(edges, dtype=np.float64)
    raw = np.asarray(counts, dtype=np.float64)
    centres = bin_centres(edges)
    model = model_for(choice, constants)
    notes: list[str] = []
    width_bins = float(np.mean(np.diff(edges))) if len(edges) > 1 else math.nan
    if smoothing is not None and width_bins > 0:
        sigma_bins = smoothing / width_bins
        fit = fit_histogram(centres, smooth(raw, sigma_bins), model, sigma=smoothed_errors(raw, sigma_bins))
        if fit.ok:
            notes.append("fitted to the smoothed curve: neighbouring bins are correlated, so the SEs are "
                         "approximate")
    else:
        smoothing = None
        fit = fit_histogram(centres, raw, model)
    nan = Estimate(math.nan, math.nan)
    if not fit.ok:
        return AxisFit(axis, choice, fit, nan, nan, nan, nan, np.empty(0), np.empty(0), (*fit.notes, *notes),
                       smoothing is not None)
    centre, width = fit["centre"], fit["sigma"]
    if smoothing is not None:
        squared = width.value ** 2 - smoothing ** 2
        if squared > 0:
            corrected = math.sqrt(squared)
            width = Estimate(corrected, width.se * width.value / corrected)
            notes.append(f"σ corrected for the smoothing σ_s {Estimate(smoothing, 0.0).text(unit=unit_of(axis))}: "
                         "√(σ² − σ_s²)")
        else:
            width = nan
            notes.append("the fitted width is no wider than the smoothing: no temperature")
    if axis == "T":
        sigma_v = _scaled(width, sigma_v_from_arrival_width(1.0, constants))
    else:
        sigma_v = _scaled(width, sigma_v_from_transverse_width(1.0, constants))
    temperature = temperature_estimate(sigma_v, constants) if math.isfinite(sigma_v.value) else nan
    x = np.linspace(float(edges[0]), float(edges[-1]), CURVE_POINTS)
    return AxisFit(axis, choice, fit, centre, width, sigma_v, temperature, x, fit.evaluate(x),
                   (*fit.notes, *notes), smoothing is not None)


CONSTANT_NAMES = {"fall_distance": "fall distance", "fall_time": "fall time", "g": "g", "mass": "mass"}
ORIGIN_TEXT = {"default": "default", "lab": "lab", "folder": "folder", "plot": "this plot", "derived": "derived"}


def constants_text(constants: ResolvedConstants, keys: tuple[str, ...] = ("fall_distance", "fall_time", "g")) -> str:
    """``fall distance 0.848 m (default, unconfirmed) · fall time 0.416101 s (derived,
    unconfirmed) · g 9.79602 m/s² (default)``: each value used, where it came from, and the
    borrowed legacy values not yet confirmed on the current setup."""
    unconfirmed = set(constants.unconfirmed)
    parts = []
    for key in keys:
        flag = ", unconfirmed" if key in unconfirmed else ""
        parts.append(f"{CONSTANT_NAMES.get(key, key)} {constants.value(key):.6g} {TABLE[key].unit} "
                     f"({ORIGIN_TEXT[constants.origins[key]]}{flag})")
    return " · ".join(parts)
