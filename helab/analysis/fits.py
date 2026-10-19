"""Bounded least-squares fits of 1D histograms, for the T/X/Y fits of the DLD port (D1, D4).

``fit_histogram(centres, counts, model)`` fits one of the registered ``MODELS`` with
``scipy.optimize.curve_fit`` and returns a ``FitResult``: each parameter's value ± SE (from
the covariance), the model curve, χ² per degree of freedom and, when the fit can't be
trusted, a ``failure`` reason. Failures (no data, too few points, everything in one bin, no
convergence, an undetermined parameter) are results with a note, never exceptions, so a
plot can say why it shows no fit.

How a fit runs:
- Input: raw counts per bin, or anything else with its errors given as ``sigma=`` (rates,
  smoothed counts). The count weights assume whole-number counts and say so otherwise.
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
- Components: a parameter that only shapes one part of a model (a TF radius) names that
  part's amplitude as its ``gate``. When the amplitude is consistent with 0 (within 2 SE)
  the fit says so in a note and the parameter's SE is nan, instead of failing.

Models are derived from the physics, not copied from the MATLAB code (which has bugs:
roadmaps/dld-front-panel-port.md). Registered now: Gaussian + offset, the Thomas–Fermi
projection (1 − u²)^p + offset, and bimodal TF^p + Gaussian with a shared centre. D1/D4 add
the arrival-time ("Yavin") thermal profile and the Bose-enhanced g_{5/2} part with
``register``. Pure NumPy/SciPy, no Qt. Fits run in the analysis worker thread, so nothing
here changes warning filters per call (``warnings.catch_warnings`` isn't thread-safe).
"""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Literal, Mapping, Sequence, cast

import numpy as np
import numpy.typing as npt
from scipy.optimize import OptimizeWarning, curve_fit
from scipy.special import gammaln

from helab.analysis.estimates import Estimate, finite_or_none, propagate

Array = npt.NDArray[np.float64]
Role = Literal["position", "width", "height", "shape"]
Weights = Literal["poisson", "counts", "none"]
MAX_EVALUATIONS = 4000
REWEIGHT_ROUNDS = 10
SETTLED = 0.01  # reweighting stops once no parameter moves more than this many SEs
VARIANCE_FLOOR = 0.1  # counts: the least variance a bin is given when the model is near zero there
CHI2_NOTE = 3.0  # a reduced χ² above this gets a note: the model doesn't describe the data well
ZERO_SE = 2.0  # an amplitude within this many SEs of 0 is "consistent with 0"
# The bimodal model's R / σ_thermal is at most this; see ``bimodal_model``.
MAX_RADIUS_RATIO = 2.0
MIN_RADIUS_RATIO = 0.02

# curve_fit warns when it can't estimate a covariance; the result's checks report that
# instead. Set once here, for SciPy's optimizer only: per-call filters aren't thread-safe.
warnings.filterwarnings("ignore", category=OptimizeWarning, module=r"scipy\.optimize")


@dataclass(frozen=True)
class ModelParameter:
    name: str
    title: str
    role: Role  # how it scales with x and the counts: position and width with x, height with counts
    # Amplitudes of the parts this parameter shapes: when any is consistent with 0, this one
    # is undetermined by design (nan SE and a note, not a failure).
    gates: tuple[str, ...] = ()


@dataclass(frozen=True)
class Extra:
    """A number computed from the parameters and reported beside them, with its SE from the
    covariance (a bimodal fit's R, fitted as a ratio)."""
    name: str
    title: str
    function: Callable[[Array], float]
    gates: tuple[str, ...] = ()


@dataclass(frozen=True)
class FitModel:
    """A model y = function(x, *parameters), with how to start and bound a fit of it.

    ``guesses`` gets the cleaned (centres, counts, errors) and ``bounds`` (centres, counts);
    both work in data units. ``areas`` gives each component's integral over x (counts × x
    units: divide by the bin width for counts), without the offset; D4's condensate fraction
    comes from these. ``extras`` are reported in the result's estimates too."""
    key: str
    title: str
    parameters: tuple[ModelParameter, ...]
    function: Callable[..., Array]
    guesses: Callable[[Array, Array, Array], list[Array]]
    bounds: Callable[[Array, Array], tuple[Array, Array]]
    areas: Callable[[Array], dict[str, float]] | None = None
    min_bins: int = 3  # fewer bins with counts than this: too few to fit a width
    extras: tuple[Extra, ...] = ()

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
    warnings about a fit that worked (a parameter at its bound, a large reduced χ², a part
    consistent with 0). ``estimates`` has the parameters, then the model's extras. Its
    arrays are read-only."""
    model: FitModel = field(repr=False)
    failure: str
    estimates: Mapping[str, Estimate]
    covariance: Array | None = field(repr=False)
    x: Array = field(repr=False)
    curve: Array = field(repr=False)  # the model at ``x`` (empty without a fit)
    chi2: float = math.nan
    dof: int = 0
    points: int = 0  # bins fitted (after leaving out unusable ones)
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for array in (self.covariance, self.x, self.curve):
            if array is not None:
                array.flags.writeable = False

    @property
    def ok(self) -> bool:
        return not self.failure

    @property
    def reduced_chi2(self) -> float:
        return self.chi2 / self.dof if self.dof > 0 else math.nan

    @property
    def values(self) -> Array:
        """The fitted parameters in ``model.names`` order (extras left out)."""
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

    def as_record(self) -> dict[str, Any]:
        """Strict JSON (nan and inf as None) for a result's record; the curve is left out
        (``evaluate`` redraws it from the model and estimates)."""
        return {"model": self.model.key, "failure": self.failure, "notes": list(self.notes),
                "estimates": {name: estimate.as_record() for name, estimate in self.estimates.items()},
                "chi2": finite_or_none(self.chi2), "dof": self.dof, "points": self.points,
                "reduced_chi2": finite_or_none(self.reduced_chi2)}


def bin_centres(edges: npt.ArrayLike) -> Array:
    edges = np.asarray(edges, dtype=np.float64)
    return cast(Array, (edges[:-1] + edges[1:]) / 2)


def fit_histogram(centres: npt.ArrayLike, counts: npt.ArrayLike, model: str | FitModel = "gaussian", *,
                  weights: Weights = "poisson", sigma: npt.ArrayLike | None = None,
                  max_evaluations: int = MAX_EVALUATIONS) -> FitResult:
    """Fit ``model`` (a ``MODELS`` key or a ``FitModel``) to a histogram's bin centres and
    raw counts. ``sigma``, when given, is each bin's error (absolute) and replaces
    ``weights``: pass it for anything that isn't raw counts. Bins with a non-finite centre,
    count or error, or an error ≤ 0, are left out (noted)."""
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
    notes: list[str] = []
    finite = np.isfinite(x) & np.isfinite(y)
    positive = np.isfinite(errors) & (errors > 0)
    if not finite.all():
        notes.append(f"{int((~finite).sum()):,} bins with a non-finite centre or count left out")
    if not positive[finite].all():
        notes.append(f"{int((~positive[finite]).sum()):,} bins with an error that isn't finite and > 0 left out")
    usable = finite & positive
    x, y, errors = x[usable], y[usable], errors[usable]
    if sigma is None and weights != "none" and not np.all(y == np.round(y)):
        notes.append("the counts aren't whole numbers: Poisson weights assume raw counts "
                     "(give errors as sigma for rates or smoothed counts)")
    count = len(fit_model.parameters)

    def failed(reason: str) -> FitResult:
        nan = MappingProxyType({name: Estimate(math.nan, math.nan)
                                for name in (*fit_model.names, *(extra.name for extra in fit_model.extras))})
        return FitResult(fit_model, reason, nan, None, x, np.empty(0), points=len(x), notes=tuple(notes))

    if len(x) == 0:
        return failed("no data to fit")
    if not np.any(y != 0):
        return failed("no counts to fit")
    if len(x) <= count:
        return failed(f"too few bins to fit: {len(x)} for {count} parameters")
    filled = int(np.count_nonzero(y != 0))
    if filled < fit_model.min_bins:
        return failed("all counts in one bin: no width to fit" if filled == 1 else
                      f"counts in only {filled} bins: too few to fit this model (it needs {fit_model.min_bins})")

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
        with np.errstate(all="ignore"):  # overflow in a trial step's exp; np.errstate is thread-local
            try:
                found, covariance = cast(tuple[Array, Array], curve_fit(
                    normalised_model, u, y_n, p0=start_n, sigma=errors_n, absolute_sigma=absolute,
                    bounds=(lower_n, upper_n), method="trf", max_nfev=max_evaluations))
            except RuntimeError:
                return f"the fit did not converge in {max_evaluations:,} evaluations"
            except ValueError as error:
                return f"the fit could not run: {error}"
            chi2 = float(np.sum(((y_n - normalised_model(u, *found)) / errors_n) ** 2))
        return (chi2, np.asarray(found), np.asarray(covariance)) if math.isfinite(chi2) else \
            "the fit gave a non-finite χ²"

    best: tuple[float, Array, Array] | None = None
    reasons: list[str] = []
    for start in fit_model.guesses(x, y, errors):
        outcome = solve((np.asarray(start, dtype=np.float64) - shift) / scale, errors_n)
        if isinstance(outcome, str):
            reasons.append(outcome)
        elif best is None or outcome[0] < best[0]:
            best = outcome
    if best is None:
        return failed(reasons[0] if reasons else "the model gave no starting point")
    if sigma is None and weights == "poisson":
        best, moving = _reweight(best, solve, lambda found: normalised_model(u, *found) * height, height)
        if moving:
            notes.append(f"the Poisson weights did not settle in {REWEIGHT_ROUNDS} rounds (the parameters "
                         f"still moved up to {moving:.2g} SE per round)")

    chi2, found, covariance_n = best
    values = to_data(found)
    covariance = covariance_n * np.outer(scale, scale)
    dof = len(x) - count
    finite_covariance = bool(np.all(np.isfinite(covariance)))
    variances = np.diag(covariance) if finite_covariance else np.full(count, math.nan)
    ses = {name: math.sqrt(variance) if variance > 0 else math.nan
           for name, variance in zip(fit_model.names, variances)}
    zero = _zero_parts(fit_model, values, ses, found, lower_n, room)
    gated = {parameter.name for parameter in fit_model.parameters if set(parameter.gates) & zero}
    if zero:
        titles = {parameter.name: parameter.title for parameter in fit_model.parameters}
        shaped = [titles[name] for name in fit_model.names if name in gated]
        notes.append(f"{', '.join(titles[name] for name in fit_model.names if name in zero)} consistent with 0 "
                     f"(within {ZERO_SE:g} SE)" + (f": {', '.join(shaped)} not determined" if shaped else ""))
    # SciPy's pseudo-inverse gives a parameter the data don't determine a variance of exactly
    # 0, or inf: either way it has no usable SE. A gated one is expected, and was noted.
    undetermined = [parameter.title for parameter in fit_model.parameters
                    if parameter.name not in gated and math.isnan(ses[parameter.name])]
    failure = ""
    if undetermined or not finite_covariance:
        failure = (f"not determined by the data: {', '.join(undetermined) or 'the covariance is not finite'} "
                   "(no usable SE)")
    width = np.where(np.isfinite(upper_n - lower_n), upper_n - lower_n, np.maximum(np.abs(found), 1.0))
    at_bound = [parameter.title for parameter, value, low, high, size in
                zip(fit_model.parameters, found, lower_n, upper_n, width)
                if parameter.name not in zero and parameter.name not in gated
                and (value - low <= 1e-6 * size or high - value <= 1e-6 * size)]
    if at_bound:
        notes.append(f"at its bound: {', '.join(at_bound)} (its SE is not reliable)")
    if absolute and dof > 0 and chi2 / dof > CHI2_NOTE:
        notes.append(f"reduced χ² {chi2 / dof:.3g}: the model doesn't describe the data well")
    estimates = {name: Estimate(float(value), math.nan if name in gated else ses[name])
                 for name, value in zip(fit_model.names, values)}
    for extra in fit_model.extras:
        estimate = propagate(extra.function, values, covariance if finite_covariance else
                             np.full((count, count), math.nan))
        estimates[extra.name] = Estimate(estimate.value, math.nan if set(extra.gates) & zero else estimate.se)
    return FitResult(fit_model, failure, MappingProxyType(estimates), covariance, x,
                     fit_model.function(x, *values), chi2, dof, len(x), tuple(notes))


def _zero_parts(model: FitModel, values: Array, ses: Mapping[str, float], found: Array, lower_n: Array,
                room: Array) -> set[str]:
    """The gate amplitudes consistent with 0: within ``ZERO_SE`` SEs of it, or at their lower
    bound of 0 without a usable SE."""
    gates = {gate for parameter in model.parameters for gate in parameter.gates}
    zero: set[str] = set()
    for index, name in enumerate(model.names):
        if name not in gates:
            continue
        se = ses[name]
        at_zero = found[index] - lower_n[index] <= 10 * room[index]
        if (math.isfinite(se) and values[index] <= ZERO_SE * se) or (not math.isfinite(se) and at_zero):
            zero.add(name)
    return zero


def _reweight(best: tuple[float, Array, Array], solve: Callable[[Array, Array], tuple[float, Array, Array] | str],
              curve: Callable[[Array], Array], height: float) -> tuple[tuple[float, Array, Array], float]:
    """Refit with each bin's variance from the model instead of its count, until the
    parameters settle. Errors of √max(n, 1) pull a fit towards the bins with fewer counts
    (Neyman's χ²: a Gaussian's σ comes out about one SE low at 500 events); with the model's
    variance, the fixed point solves Σ (n − μ)/μ · ∂μ/∂θ = 0, the Poisson likelihood's own
    equations, so the result is the Poisson maximum-likelihood fit and its covariance the
    inverse Fisher information. Bins where the model is below ``VARIANCE_FLOOR`` use that.
    The variances come from the mean of the last two fits' parameters: the plain iteration
    overshoots and oscillates (mostly in the offset, through the near-empty tails), and the
    mean damps it to a few rounds.

    Returns the last fit and 0, or, when ``REWEIGHT_ROUNDS`` rounds don't settle (a model
    that doesn't describe the data can keep moving), the fit whose round moved least and how
    many SEs it moved, for a note."""
    previous = best[1]
    calmest: tuple[float, tuple[float, Array, Array]] | None = None
    for _ in range(REWEIGHT_ROUNDS):
        _, found, _ = best
        errors_n = np.sqrt(np.maximum(curve((found + previous) / 2), VARIANCE_FLOOR)) / height
        outcome = solve(found, errors_n)
        if isinstance(outcome, str):
            return best, 0.0
        spread = np.sqrt(np.abs(np.diag(outcome[2]))) if np.all(np.isfinite(outcome[2])) else np.abs(found) + 1
        moved = float(np.max(np.abs(outcome[1] - found) / np.maximum(spread, 1e-12)))
        previous, best = found, outcome
        if moved <= SETTLED:
            return best, 0.0
        if calmest is None or moved < calmest[0]:
            calmest = (moved, outcome)
    assert calmest is not None
    return calmest[1], calmest[0]


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


def _gaussian_guesses(x: Array, y: Array, errors: Array) -> list[Array]:
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
    areas=lambda p: {"gaussian": gaussian_area(float(p[0]), float(p[2]))}))


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

    def guesses(x: Array, y: Array, errors: Array) -> list[Array]:
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
        areas=lambda p: {"thomas_fermi": thomas_fermi_area(float(p[0]), float(p[2]), power)})


# The bimodal model fits R as a ratio to the thermal width, r = R/σ_th ≤ MAX_RADIUS_RATIO.
# Unconstrained, a TF part and a Gaussian sum to a shape close to either alone: on a purely
# thermal cloud the fit invented a condensate wider than the Gaussian (R/σ 2–4, N0/N up to
# 0.15), and on a pure condensate the "thermal" part became a narrow spike inside the TF.
# The bound follows the physics: after a time of flight t both widths grow with t,
# σ_th = √(k_B T/m)·t and R = √(2μ/m)·t (a TF cloud expands at its sound-speed scale), so
# R/σ_th = √(2μ/k_B T): 2 at μ = 2 k_B T. Colder clouds than that have so few thermal atoms
# that the Gaussian part isn't measurable anyway (and its amplitude then reads consistent
# with 0). Each part's shape parameters are gated by its amplitude.


def bimodal_model(power: float) -> FitModel:
    """A condensate on a thermal cloud, one centre:
    A_c (1 − u²)₊^p + A_t exp(−(x − x₀)²/2σ²) + offset, u = (x − x₀)/R, R = r σ with
    r = R/σ in [MIN_RADIUS_RATIO, MAX_RADIUS_RATIO]. R is reported as an extra. Started from
    a Gaussian fit (count weights, or the caller's errors), split three ways."""
    def function(x: Array, condensate: float, centre: float, ratio: float, thermal: float, sigma: float,
                 offset: float) -> Array:
        return (thomas_fermi(x, condensate, centre, ratio * sigma, 0.0, power)
                + gaussian(x, thermal, centre, sigma, offset))

    def guesses(x: Array, y: Array, errors: Array) -> list[Array]:
        single = fit_histogram(x, y, "gaussian", sigma=errors)
        if single.ok:
            peak, mean, spread, baseline = (single[name].value for name in ("amplitude", "centre", "sigma", "offset"))
        else:
            baseline, peak, mean, spread = _moments(x, y)
        # (condensate share of the peak, R/σ_thermal, σ_thermal / σ_gauss)
        splits = ((0.7, 1.5, 1.4), (0.5, 1.0, 1.3), (0.3, 0.6, 1.1))
        return [np.array([share * peak, mean, ratio, (1 - share) * peak, s * spread, baseline])
                for share, ratio, s in splits]

    def bounds(x: Array, y: Array) -> tuple[Array, Array]:
        low, high = _position_bounds(x)
        _, _, span, step = _extent(x)
        top = float(np.max(np.abs(y)))
        return (np.array([0.0, low, MIN_RADIUS_RATIO, 0.0, step / 10, -top]),
                np.array([np.inf, high, MAX_RADIUS_RATIO, np.inf, 10 * span, top]))

    def areas(p: Array) -> dict[str, float]:
        return {"thomas_fermi": thomas_fermi_area(float(p[0]), float(p[2] * p[4]), power),
                "gaussian": gaussian_area(float(p[3]), float(p[4]))}

    return FitModel(
        f"bimodal_tf{_power_text(power)}_gaussian", f"Bimodal: Thomas–Fermi (1 − u²)^{power:g} + Gaussian",
        (ModelParameter("condensate", "Condensate amplitude", "height"),
         ModelParameter("centre", "Centre", "position"),
         ModelParameter("ratio", "R / σ thermal", "shape", gates=("condensate", "thermal")),
         ModelParameter("thermal", "Thermal amplitude", "height"),
         ModelParameter("sigma", "σ thermal", "width", gates=("thermal",)),
         ModelParameter("offset", "Offset", "height")),
        function, guesses, bounds, areas=areas, min_bins=4,
        extras=(Extra("radius", "R", lambda p: float(p[2] * p[4]), gates=("condensate",)),))


for _power in (2.0, 1.5):
    register(thomas_fermi_model(_power))
    register(bimodal_model(_power))
