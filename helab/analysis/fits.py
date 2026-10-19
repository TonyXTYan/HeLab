"""Bounded least-squares fits of 1D histograms, for the T/X/Y fits of the DLD port (D1, D4).

``fit_histogram(centres, counts, model)`` fits one of the registered ``MODELS`` with
``scipy.optimize.curve_fit`` and returns a ``FitResult``: each parameter's value ± SE (from
the covariance), the model curve, χ² per degree of freedom and, when the fit can't be
trusted, a ``failure`` reason. Failures (no data, too few points, everything in one bin, no
convergence, an undetermined parameter) are results with a note, never exceptions, so a
plot can say why it shows no fit.

How a fit runs:
- Weights: counts are Poisson. ``weights="poisson"`` (the default) first fits with each
  bin's error √max(n, 1), then refits with the model's own variance until the parameters
  settle: the Poisson maximum-likelihood fit (``_reweight`` says why: the first fit alone
  biases widths low). ``"counts"`` stops after the first fit. Either way the covariance is
  absolute (the SEs don't scale with χ²; a poor model shows as a large reduced χ², noted).
  ``"none"`` fits unweighted and scales the covariance by the residuals instead.
- Scaling: x and counts are mapped to order one before fitting (a T profile is ~0.4 s wide
  ~0.1 ms, counts ~10³), each parameter by its role (a position, a width, a height or a
  dimensionless shape), and mapped back with the covariance.
- Starting points come from moments (each model's ``guesses``); a model may give several,
  and the converged one with the lowest χ² is kept.

Models are derived from the physics, not copied from the MATLAB code (which has bugs:
roadmaps/dld-front-panel-port.md). Registered now: Gaussian + offset, the Thomas–Fermi
projection (1 − u²)^p + offset, and bimodal TF^p + Gaussian with a shared centre. D1/D4 add
the arrival-time ("Yavin") thermal profile and the Bose-enhanced g_{5/2} part with
``register``. Pure NumPy/SciPy, no Qt.
"""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Literal, Mapping, Sequence, cast

import numpy as np
import numpy.typing as npt
from scipy.optimize import OptimizeWarning, curve_fit
from scipy.special import gammaln

from helab.analysis.estimates import Estimate, propagate

Array = npt.NDArray[np.float64]
Role = Literal["position", "width", "height", "shape"]
Weights = Literal["poisson", "counts", "none"]
MAX_EVALUATIONS = 4000
REWEIGHT_ROUNDS = 10
SETTLED = 0.01  # reweighting stops once no parameter moves more than this many SEs
VARIANCE_FLOOR = 0.1  # counts: the least variance a bin is given when the model is near zero there
CHI2_NOTE = 3.0  # a reduced χ² above this gets a note: the model doesn't describe the data well


@dataclass(frozen=True)
class ModelParameter:
    name: str
    title: str
    role: Role  # how it scales with x and the counts: position and width with x, height with counts


@dataclass(frozen=True)
class FitModel:
    """A model y = function(x, *parameters), with how to start and bound a fit of it.

    ``guesses`` and ``bounds`` get the cleaned (centres, counts) and work in data units.
    ``areas`` gives each component's integral over x (counts × x units: divide by the bin
    width for counts), without the offset; D4's condensate fraction comes from these."""
    key: str
    title: str
    parameters: tuple[ModelParameter, ...]
    function: Callable[..., Array]
    guesses: Callable[[Array, Array], list[Array]]
    bounds: Callable[[Array, Array], tuple[Array, Array]]
    areas: Callable[[Array], dict[str, float]] | None = None
    min_bins: int = 2  # fewer bins with counts than this: "all counts in one bin"

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(parameter.name for parameter in self.parameters)

    def __call__(self, x: npt.ArrayLike, values: Sequence[float] | Array) -> Array:
        return self.function(np.asarray(x, dtype=np.float64), *np.asarray(values, dtype=np.float64))


MODELS: dict[str, FitModel] = {}


def register(model: FitModel) -> FitModel:
    """Add a model to ``MODELS`` under its key (a key can be registered once)."""
    if model.key in MODELS:
        raise ValueError(f"fit model {model.key!r} is already registered")
    MODELS[model.key] = model
    return model


@dataclass(frozen=True)
class FitResult:
    """A fit's outcome. ``failure`` is "" when it worked; otherwise it says why, and the
    estimates (nan when nothing was fitted) shouldn't be shown as results. ``notes`` are
    warnings about a fit that worked (a parameter at its bound, a large reduced χ²)."""
    model: FitModel = field(repr=False)
    failure: str
    estimates: Mapping[str, Estimate]
    covariance: Array | None = field(repr=False)
    x: Array = field(repr=False)
    curve: Array = field(repr=False)  # the model at ``x`` (empty without a fit)
    chi2: float = math.nan
    dof: int = 0
    points: int = 0  # bins fitted (after leaving out non-finite ones)
    notes: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failure

    @property
    def reduced_chi2(self) -> float:
        return self.chi2 / self.dof if self.dof > 0 else math.nan

    @property
    def values(self) -> Array:
        return np.array([self.estimates[name].value for name in self.model.names])

    def __getitem__(self, name: str) -> Estimate:
        return self.estimates[name]

    def evaluate(self, x: npt.ArrayLike) -> Array:
        """The fitted model at ``x`` (a finer grid to draw it smoothly); nan without a fit."""
        x = np.asarray(x, dtype=np.float64)
        if not np.all(np.isfinite(self.values)):
            return np.full(x.shape, math.nan)
        return self.model(x, self.values)

    def derived(self, function: Callable[[Array], float]) -> Estimate:
        """A number computed from the fitted parameters (in ``model.names`` order), with its
        SE from the covariance to first order; nan SE without a usable covariance."""
        covariance = self.covariance if self.covariance is not None else np.full((len(self.values),) * 2, math.nan)
        return propagate(function, self.values, covariance)


def bin_centres(edges: npt.ArrayLike) -> Array:
    edges = np.asarray(edges, dtype=np.float64)
    return cast(Array, (edges[:-1] + edges[1:]) / 2)


def fit_histogram(centres: npt.ArrayLike, counts: npt.ArrayLike, model: str | FitModel = "gaussian", *,
                  weights: Weights = "poisson", sigma: npt.ArrayLike | None = None,
                  max_evaluations: int = MAX_EVALUATIONS) -> FitResult:
    """Fit ``model`` (a ``MODELS`` key or a ``FitModel``) to a histogram's bin centres and
    counts. ``sigma``, when given, is each bin's error (absolute) and replaces ``weights``.
    Bins with a non-finite centre, count or error are left out (noted)."""
    fit_model = MODELS[model] if isinstance(model, str) else model
    x = np.asarray(centres, dtype=np.float64).ravel()
    y = np.asarray(counts, dtype=np.float64).ravel()
    if len(x) != len(y):
        raise ValueError("centres and counts must have the same length")
    absolute = sigma is not None or weights != "none"
    if sigma is not None:
        errors = np.broadcast_to(np.asarray(sigma, dtype=np.float64), y.shape).ravel()
    elif weights != "none":
        errors = np.sqrt(np.maximum(np.where(np.isfinite(y), y, 0.0), 1.0))
    else:
        errors = np.ones_like(y)
    finite = np.isfinite(x) & np.isfinite(y) & np.isfinite(errors) & (errors > 0)
    notes: list[str] = []
    if not finite.all():
        notes.append(f"{int((~finite).sum()):,} bins with non-finite values left out")
    x, y, errors = x[finite], y[finite], errors[finite]
    count = len(fit_model.parameters)

    def failed(reason: str) -> FitResult:
        nan = MappingProxyType({name: Estimate(math.nan, math.nan) for name in fit_model.names})
        return FitResult(fit_model, reason, nan, None, x, np.empty(0), points=len(x), notes=tuple(notes))

    if len(x) == 0:
        return failed("no data to fit")
    if not np.any(y != 0):
        return failed("no counts to fit")
    if len(x) <= count:
        return failed(f"too few bins to fit: {len(x)} for {count} parameters")
    if np.count_nonzero(y != 0) < fit_model.min_bins:
        return failed("all counts in one bin: no width to fit")

    order = np.argsort(x, kind="stable")
    x, y, errors = x[order], y[order], errors[order]
    centre, span = (float(x[0]) + float(x[-1])) / 2, float(x[-1] - x[0]) or 1.0
    height = float(np.max(np.abs(y))) or 1.0
    scale = np.array([span if parameter.role in ("position", "width") else
                      height if parameter.role == "height" else 1.0 for parameter in fit_model.parameters])
    shift = np.array([centre if parameter.role == "position" else 0.0 for parameter in fit_model.parameters])

    def to_data(normalised: Array) -> Array:
        return cast(Array, shift + scale * normalised)

    def normalised_model(u: Array, *normalised: float) -> Array:
        return fit_model.function(centre + span * u, *to_data(np.asarray(normalised))) / height

    lower, upper = (np.asarray(bound, dtype=np.float64) for bound in fit_model.bounds(x, y))
    lower_n, upper_n = (lower - shift) / scale, (upper - shift) / scale
    u, y_n, errors_n = (x - centre) / span, y / height, errors / height
    room = np.where(np.isfinite(upper_n - lower_n), 1e-6 * (upper_n - lower_n), 1e-6)

    def solve(start_n: Array, errors_n: Array) -> tuple[float, Array, Array] | str:
        """(χ², parameters, covariance), normalised, or why curve_fit gave none."""
        start_n = np.clip(np.nan_to_num(start_n), lower_n + room, upper_n - room)  # or curve_fit refuses
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", OptimizeWarning)
            warnings.simplefilter("ignore", RuntimeWarning)
            try:
                found, covariance = cast(tuple[Array, Array], curve_fit(
                    normalised_model, u, y_n, p0=start_n, sigma=errors_n, absolute_sigma=absolute,
                    bounds=(lower_n, upper_n), method="trf", max_nfev=max_evaluations))
            except RuntimeError:
                return "the fit did not converge"
            except ValueError as error:
                return f"the fit could not run: {error}"
        chi2 = float(np.sum(((y_n - normalised_model(u, *found)) / errors_n) ** 2))
        return (chi2, np.asarray(found), np.asarray(covariance)) if math.isfinite(chi2) else "the fit did not converge"

    best: tuple[float, Array, Array] | None = None
    reasons: list[str] = []
    for start in fit_model.guesses(x, y):
        outcome = solve((np.asarray(start, dtype=np.float64) - shift) / scale, errors_n)
        if isinstance(outcome, str):
            reasons.append(outcome)
        elif best is None or outcome[0] < best[0]:
            best = outcome
    if best is None:
        return failed(reasons[0] if reasons else "the fit did not converge")
    if sigma is None and weights == "poisson":
        best = _reweight(best, solve, lambda found: normalised_model(u, *found) * height, height)

    chi2, found, covariance_n = best
    values = to_data(found)
    covariance = covariance_n * np.outer(scale, scale)
    dof = len(x) - count
    failure = ""
    # SciPy's pseudo-inverse gives a parameter the data don't determine a variance of exactly
    # 0, or inf: either way it has no usable SE.
    usable = bool(np.all(np.isfinite(covariance)))
    undetermined = [parameter.title for parameter, variance in zip(fit_model.parameters, np.diag(covariance))
                    if not (math.isfinite(variance) and variance > 0)]
    if undetermined or not usable:
        failure = (f"not determined by the data: {', '.join(undetermined) or 'the covariance is not finite'} "
                   "(no usable SE)")
    width = np.where(np.isfinite(upper_n - lower_n), upper_n - lower_n, np.maximum(np.abs(found), 1.0))
    at_bound = [parameter.title for parameter, value, low, high, room in
                zip(fit_model.parameters, found, lower_n, upper_n, width)
                if value - low <= 1e-6 * room or high - value <= 1e-6 * room]
    if at_bound:
        notes.append(f"at its bound: {', '.join(at_bound)} (its SE is not reliable)")
    if absolute and dof > 0 and chi2 / dof > CHI2_NOTE:
        notes.append(f"reduced χ² {chi2 / dof:.3g}: the model doesn't describe the data well")
    variances = np.diag(covariance) if usable else np.full(count, math.nan)
    estimates = MappingProxyType({name: Estimate(float(value), math.sqrt(variance) if variance > 0 else math.nan)
                                  for name, value, variance in zip(fit_model.names, values, variances)})
    return FitResult(fit_model, failure, estimates, covariance, x, fit_model.function(x, *values), chi2, dof,
                     len(x), tuple(notes))


def _reweight(best: tuple[float, Array, Array], solve: Callable[[Array, Array], tuple[float, Array, Array] | str],
              curve: Callable[[Array], Array], height: float) -> tuple[float, Array, Array]:
    """Refit with each bin's variance from the model instead of its count, until the
    parameters settle. Errors of √max(n, 1) pull a fit towards the bins with fewer counts
    (Neyman's χ²: a Gaussian's σ comes out about one SE low at 500 events); with the model's
    variance, the fixed point solves Σ (n − μ)/μ · ∂μ/∂θ = 0, the Poisson likelihood's own
    equations, so the result is the Poisson maximum-likelihood fit and its covariance the
    inverse Fisher information. Bins where the model is below ``VARIANCE_FLOOR`` use that.
    The variances come from the mean of the last two fits' parameters: the plain iteration
    overshoots and oscillates (mostly in the offset, through the near-empty tails), and the
    mean damps it to a few rounds."""
    previous = best[1]
    for _ in range(REWEIGHT_ROUNDS):
        _, found, _ = best
        errors_n = np.sqrt(np.maximum(curve((found + previous) / 2), VARIANCE_FLOOR)) / height
        outcome = solve(found, errors_n)
        if isinstance(outcome, str):
            return best
        spread = np.sqrt(np.abs(np.diag(outcome[2]))) if np.all(np.isfinite(outcome[2])) else np.abs(found) + 1
        settled = bool(np.all(np.abs(outcome[1] - found) <= SETTLED * np.maximum(spread, 1e-12)))
        previous, best = found, outcome
        if settled:
            break
    return best


# Models

def _moments(x: Array, y: Array) -> tuple[float, float, float, float]:
    """(baseline, peak height above it, mean, standard deviation) of the counts above the
    lowest bin, for starting points. The width is at least half a bin."""
    baseline = float(np.min(y))
    weight = np.clip(y - baseline, 0, None)
    if not weight.sum() > 0:
        weight = np.ones_like(y)
    mean = float(np.dot(weight, x) / weight.sum())
    spread = math.sqrt(float(np.dot(weight, (x - mean) ** 2) / weight.sum()))
    step = float(np.min(np.diff(x))) if len(x) > 1 else 1.0
    return baseline, float(np.max(y)) - baseline, mean, max(spread, step / 2)


def _extent(x: Array) -> tuple[float, float, float, float]:
    """(lowest x, highest x, span, smallest bin step) of sorted centres."""
    span = float(x[-1] - x[0]) or 1.0
    step = float(np.min(np.diff(x))) if len(x) > 1 else span
    return float(x[0]), float(x[-1]), span, step


def gaussian(x: Array, amplitude: float, centre: float, sigma: float, offset: float) -> Array:
    return amplitude * np.exp(-0.5 * ((x - centre) / sigma) ** 2) + offset


def gaussian_area(amplitude: float, sigma: float) -> float:
    """∫ A exp(−(x − μ)²/2σ²) dx = A σ √(2π)."""
    return amplitude * abs(sigma) * math.sqrt(2 * math.pi)


def _position_bounds(x: Array) -> tuple[float, float]:
    low, high, span, _ = _extent(x)
    return low - span, high + span


def _gaussian_guesses(x: Array, y: Array) -> list[Array]:
    baseline, peak, mean, spread = _moments(x, y)
    return [np.array([peak, mean, spread, baseline])]


def _gaussian_bounds(x: Array, y: Array) -> tuple[Array, Array]:
    low, high = _position_bounds(x)
    _, _, span, step = _extent(x)
    top = float(np.max(np.abs(y)))
    return np.array([0.0, low, step / 100, -top]), np.array([np.inf, high, 10 * span, top])


register(FitModel(
    "gaussian", "Gaussian + offset",
    (ModelParameter("amplitude", "Amplitude", "height"), ModelParameter("centre", "Centre", "position"),
     ModelParameter("sigma", "σ", "width"), ModelParameter("offset", "Offset", "height")),
    gaussian, _gaussian_guesses, _gaussian_bounds,
    areas=lambda p: {"gaussian": gaussian_area(float(p[0]), float(p[2]))}, min_bins=2))


# Thomas–Fermi. A condensate's 3D density in the Thomas–Fermi limit is an inverted
# parabola, n ∝ max(0, 1 − Σ xᵢ²/Rᵢ²), and keeps that shape through a time-of-flight
# expansion (Castin–Dum scaling: only the radii grow). Integrating it over k of the other
# axes, inside the ellipse, raises the power by k/2 per axis:
#   ∫ (1 − x² − y²)₊ dy ∝ (1 − x²)^{3/2},   ∫∫ (1 − x² − y² − z²)₊ dy dz ∝ (1 − x²)².
# The DLD records every atom in 3D, so a T, X or Y histogram of all events integrates over
# both other axes: p = 2 on each. p = 3/2 is a profile through a narrow slice of one other
# axis (an X histogram of a thin T window), or a 2D image's cut. Area of A (1 − u²)^p with
# u = (x − x₀)/R: A R ∫₋₁¹ (1 − u²)^p du = A R √π Γ(p + 1) / Γ(p + 3/2) (16/15 A R at p = 2).


def thomas_fermi(x: Array, amplitude: float, centre: float, radius: float, offset: float, power: float = 2.0
                 ) -> Array:
    inside = np.clip(1 - ((x - centre) / radius) ** 2, 0, None)
    return amplitude * inside ** power + offset


def thomas_fermi_area(amplitude: float, radius: float, power: float = 2.0) -> float:
    return amplitude * abs(radius) * math.sqrt(math.pi) * math.exp(gammaln(power + 1) - gammaln(power + 1.5))


def _power_text(power: float) -> str:
    return f"{power:g}".replace(".", "_")


def thomas_fermi_model(power: float) -> FitModel:
    """A (1 − (x − x₀)²/R²)₊^p + offset, with a fixed power p."""
    def function(x: Array, amplitude: float, centre: float, radius: float, offset: float) -> Array:
        return thomas_fermi(x, amplitude, centre, radius, offset, power)

    def guesses(x: Array, y: Array) -> list[Array]:
        baseline, peak, mean, spread = _moments(x, y)
        # The variance of (1 − u²)^p is R²/(2p + 3).
        return [np.array([peak, mean, spread * math.sqrt(2 * power + 3), baseline])]

    def bounds(x: Array, y: Array) -> tuple[Array, Array]:
        low, high = _position_bounds(x)
        _, _, span, step = _extent(x)
        top = float(np.max(np.abs(y)))
        return np.array([0.0, low, step / 10, -top]), np.array([np.inf, high, 10 * span, top])

    return FitModel(
        f"thomas_fermi_{_power_text(power)}", f"Thomas–Fermi (1 − u²)^{power:g} + offset",
        (ModelParameter("amplitude", "Amplitude", "height"), ModelParameter("centre", "Centre", "position"),
         ModelParameter("radius", "R", "width"), ModelParameter("offset", "Offset", "height")),
        function, guesses, bounds,
        areas=lambda p: {"thomas_fermi": thomas_fermi_area(float(p[0]), float(p[2]), power)}, min_bins=2)


def bimodal_model(power: float) -> FitModel:
    """A condensate on a thermal cloud, one centre: A_c (1 − u²)₊^p + A_t exp(−(x − x₀)²/2σ²)
    + offset. Started from a Gaussian fit, from three splits of it between the parts."""
    def function(x: Array, condensate: float, centre: float, radius: float, thermal: float, sigma: float,
                 offset: float) -> Array:
        return thomas_fermi(x, condensate, centre, radius, 0.0, power) + gaussian(x, thermal, centre, sigma, offset)

    def guesses(x: Array, y: Array) -> list[Array]:
        single = fit_histogram(x, y, "gaussian")
        if single.ok:
            peak, mean, spread, baseline = (single[name].value for name in ("amplitude", "centre", "sigma", "offset"))
        else:
            baseline, peak, mean, spread = _moments(x, y)
        # (condensate share of the peak, R / σ_gauss, σ_thermal / σ_gauss)
        splits = ((0.8, 2.0, 2.0), (0.5, 1.5, 1.5), (0.3, 1.0, 1.2))
        return [np.array([share * peak, mean, r * spread, (1 - share) * peak, s * spread, baseline])
                for share, r, s in splits]

    def bounds(x: Array, y: Array) -> tuple[Array, Array]:
        low, high = _position_bounds(x)
        _, _, span, step = _extent(x)
        top = float(np.max(np.abs(y)))
        return (np.array([0.0, low, step / 10, 0.0, step / 100, -top]),
                np.array([np.inf, high, 10 * span, np.inf, 10 * span, top]))

    def areas(p: Array) -> dict[str, float]:
        return {"thomas_fermi": thomas_fermi_area(float(p[0]), float(p[2]), power),
                "gaussian": gaussian_area(float(p[3]), float(p[4]))}

    return FitModel(
        f"bimodal_tf{_power_text(power)}_gaussian", f"Bimodal: Thomas–Fermi (1 − u²)^{power:g} + Gaussian",
        (ModelParameter("condensate", "Condensate amplitude", "height"),
         ModelParameter("centre", "Centre", "position"), ModelParameter("radius", "R", "width"),
         ModelParameter("thermal", "Thermal amplitude", "height"), ModelParameter("sigma", "σ thermal", "width"),
         ModelParameter("offset", "Offset", "height")),
        function, guesses, bounds, areas=areas, min_bins=3)


for _power in (2.0, 1.5):
    register(thomas_fermi_model(_power))
    register(bimodal_model(_power))
