"""Values with standard errors: how they are written (``format_uncertainty``), combined
(``pooled_mean_and_std``, ``sewm``) and carried through a formula (``propagate``).

Pure NumPy, no Qt. Written for plot titles and dock lines: ``50.12 ± 0.15``,
``8.5479(10)``, ``(416.12 ± 0.12) ms``. Shot bootstrap errors are D10's, not here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Literal, Sequence

import numpy as np
import numpy.typing as npt

Style = Literal["pm", "paren"]
MINUS = "−"  # U+2212, as the dock lines write negative numbers (selection.range_text)
# SI prefixes by exponent, as pyqtgraph's ``siScale`` (UnitSpinBox and ParameterSpec's ``si``)
# picks them: the same letters, micro as "µ" (U+00B5), and the same range, 10⁻²⁴…10²⁴.
SI_PREFIX_BY_EXPONENT = {-24: "y", -21: "z", -18: "a", -15: "f", -12: "p", -9: "n", -6: "µ", -3: "m",
                         0: "", 3: "k", 6: "M", 9: "G", 12: "T", 15: "P", 18: "E", 21: "Z", 24: "Y"}
# Without a unit, a number this large or small (by its decimal exponent) gets ×10ⁿ.
PLAIN_EXPONENTS = range(-3, 5)
SUPERSCRIPTS = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


@dataclass(frozen=True)
class Estimate:
    """A value and its standard error (nan when unknown)."""
    value: float
    se: float = math.nan

    def text(self, style: Style = "pm", unit: str = "", si: bool = True, digits: int = 2) -> str:
        return format_uncertainty(self.value, self.se, style, unit, si, digits)

    def as_record(self) -> dict[str, float]:
        """JSON-ready; ``json`` writes nan and inf as NaN and Infinity."""
        return {"value": float(self.value), "se": float(self.se)}


def si_prefix(value: float) -> tuple[int, str]:
    """(exponent, prefix) that writes ``value`` with 1–3 digits before the point, the way
    pyqtgraph's ``siScale`` does: (0, "") for 0 and non-finite values, clamped to y…Y."""
    if value == 0 or not math.isfinite(value):
        return 0, ""
    exponent = min(max(int(math.floor(math.log10(abs(value)) / 3)) * 3, -24), 24)
    return exponent, SI_PREFIX_BY_EXPONENT[exponent]


def format_uncertainty(value: float, se: float, style: Style = "pm", unit: str = "", si: bool = True,
                       digits: int = 2) -> str:
    """``value`` and its standard error, the error rounded to ``digits`` significant digits
    and the value to the same decimal place (Core's ``string_value_with_unc``):

    - ``style`` "pm": ``50.12 ± 0.15``; "paren": ``8.5479(10)`` (the error in the last digits).
    - ``unit``: appended; with ``si`` it takes an SI prefix chosen from the larger of the
      value and its error: ``(416.12 ± 0.12) ms``, ``416.12(12) ms``. Pass ``si=False`` for
      units that take no prefix (kg). Without a prefix, numbers (the larger again) outside
      10⁻³…10⁵ are written ``(6.6465 ± 0.0002)×10⁻²⁷``.
    - An error of 0 writes the value to 6 significant digits, ``± 0``; a nan or infinite
      error ``± nan`` / ``± ∞``, likewise. A negative error is taken as its size.
    - Negative numbers use "−" (U+2212).
    """
    digits = max(int(digits), 1)
    se = abs(se)
    if not math.isfinite(value):
        return _join(_special(value), _plain(se) if math.isfinite(se) else _special(se), style, "", unit)
    reference = max(abs(value), se if math.isfinite(se) else 0.0)
    if unit and si:
        exponent, prefix = si_prefix(reference)
        text_value, text_se = _numbers(value / 10 ** exponent, se / 10 ** exponent, digits)
        if abs(float(text_value.replace(MINUS, "-"))) >= 1000 and exponent < 24:
            # 999.96 ms rounded to 1000.0 ms: the next prefix up
            exponent += 3
            prefix = SI_PREFIX_BY_EXPONENT[exponent]
            text_value, text_se = _numbers(value / 10 ** exponent, se / 10 ** exponent, digits)
        return _join(text_value, text_se, style, "", prefix + unit)
    exponent = int(math.floor(math.log10(reference))) if reference > 0 else 0
    if exponent in PLAIN_EXPONENTS:
        exponent = 0
    text_value, text_se = _numbers(value / 10 ** exponent, se / 10 ** exponent, digits)
    power = f"×10{str(exponent).translate(SUPERSCRIPTS)}" if exponent else ""
    return _join(text_value, text_se, style, power, unit)


def _numbers(value: float, se: float, digits: int) -> tuple[str, str]:
    """The value and error as text, rounded together; the error's text is what goes after
    ``±`` (``_join`` makes the bracket form)."""
    if not math.isfinite(se) or se == 0:
        return _plain(value), _special(se) if not math.isfinite(se) else "0"
    place = digits - 1 - int(math.floor(math.log10(se)))  # decimals to keep
    if abs(float(_fixed(se, place))) >= 10 ** (digits - place):  # 0.0996 → 0.10, not 0.100
        place -= 1
    return _fixed(value, place), _fixed(se, place)


def _fixed(value: float, place: int) -> str:
    """``value`` rounded to ``place`` decimals (negative: to tens, hundreds…), "−" for minus,
    no sign on a zero."""
    text = f"{value:.{place}f}" if place >= 0 else f"{round(value, place):.0f}"
    if text.startswith("-") and float(text) == 0:
        text = text[1:]
    return text.replace("-", MINUS)


def _plain(value: float) -> str:
    """6 significant digits, for a value whose error doesn't set its precision."""
    if not math.isfinite(value):
        return _special(value)
    text = f"{value:.6g}"
    return ("0" if float(text) == 0 else text).replace("-", MINUS)


def _special(value: float) -> str:
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "∞" if value > 0 else MINUS + "∞"
    return _plain(value)


def _join(value: str, se: str, style: Style, power: str, unit: str) -> str:
    unit_text = f" {unit}" if unit else ""
    if style == "paren":
        return f"{value}({_bracket(value, se)}){power}{unit_text}"
    core = f"{value} ± {se}"
    return f"({core}){power}{unit_text}" if power or unit else core


def _bracket(value: str, se: str) -> str:
    """The error as digits in the value's last places: 0.0010 beside 8.5479 → "10". An
    error with no decimals, or a special one, is written as it is: 1234(56), 12300(1200)."""
    if "." not in se or "." not in value or not se.replace(".", "").isdigit():
        return se
    return str(int(se.replace(".", "")))


def pooled_mean_and_std(means: Sequence[float] | npt.ArrayLike, stds: Sequence[float] | npt.ArrayLike,
                        counts: Sequence[int] | npt.ArrayLike, ddof: int = 1) -> tuple[float, float, int]:
    """(mean, standard deviation, count) of the groups' data taken together, from each
    group's mean, standard deviation (with ``ddof``) and size: what ``np.mean`` and
    ``np.std(ddof=ddof)`` give on the concatenated data. Groups of size 0 are ignored, and
    a group too small for its own deviation (size ≤ ddof) adds only its mean's spread.
    nan when there are no data, or too few for ``ddof``."""
    mean_array = np.asarray(means, dtype=np.float64).ravel()
    std_array = np.asarray(stds, dtype=np.float64).ravel()
    count_array = np.asarray(counts, dtype=np.float64).ravel()
    if not len(mean_array) == len(std_array) == len(count_array):
        raise ValueError("means, stds and counts must have the same length")
    used = count_array > 0
    mean_array, std_array, count_array = mean_array[used], std_array[used], count_array[used]
    total = int(count_array.sum())
    if total == 0:
        return math.nan, math.nan, 0
    mean = float(np.dot(count_array, mean_array) / total)
    within = np.where(count_array > ddof, (count_array - ddof) * np.nan_to_num(std_array) ** 2, 0.0)
    squares = float(within.sum() + np.dot(count_array, (mean_array - mean) ** 2))
    std = math.sqrt(squares / (total - ddof)) if total > ddof else math.nan
    return mean, std, total


def sewm(values: Sequence[float] | npt.ArrayLike, weights: Sequence[float] | npt.ArrayLike) -> Estimate:
    """The weighted mean and its standard error (Cochran 1977, as in Gatz & Smith 1995 and
    Core's ``sewm``): SE² = n / ((n − 1)(Σw)²) · Σ w² (x − x̄_w)². With equal weights this is
    the usual s/√n. Points with a non-finite value or weight are left out; the SE is nan for
    fewer than 2 points, and both are nan when the weights don't sum to a positive number."""
    value_array = np.asarray(values, dtype=np.float64).ravel()
    weight_array = np.asarray(weights, dtype=np.float64).ravel()
    if len(value_array) != len(weight_array):
        raise ValueError("values and weights must have the same length")
    used = np.isfinite(value_array) & np.isfinite(weight_array)
    value_array, weight_array = value_array[used], weight_array[used]
    total = float(weight_array.sum())
    if not total > 0:
        return Estimate(math.nan, math.nan)
    mean = float(np.dot(weight_array, value_array) / total)
    n = len(value_array)
    if n < 2:
        return Estimate(mean, math.nan)
    variance = n / ((n - 1) * total ** 2) * float(np.sum(weight_array ** 2 * (value_array - mean) ** 2))
    return Estimate(mean, math.sqrt(variance))


def propagate(function: Callable[[npt.NDArray[np.float64]], float], values: Sequence[float] | npt.ArrayLike,
              covariance: npt.ArrayLike) -> Estimate:
    """``function(values)`` with its standard error to first order (the delta method,
    √(∇fᵀ C ∇f)), the gradient by central differences: for numbers derived from a fit, such
    as a condensate fraction from its components' areas. The SE is nan when the covariance
    isn't finite or the function isn't finite near ``values``."""
    point = np.asarray(values, dtype=np.float64).ravel()
    matrix = np.asarray(covariance, dtype=np.float64)
    result = float(function(point.copy()))
    if matrix.shape != (len(point), len(point)) or not np.all(np.isfinite(matrix)) or not math.isfinite(result):
        return Estimate(result, math.nan)
    gradient = np.zeros(len(point))
    for index in range(len(point)):
        spread = math.sqrt(max(float(matrix[index, index]), 0.0))
        step = 1e-3 * spread if spread > 0 else 1e-8 * max(abs(float(point[index])), 1.0)
        above, below = point.copy(), point.copy()
        above[index] += step
        below[index] -= step
        gradient[index] = (float(function(above)) - float(function(below))) / (2 * step)
    variance = float(gradient @ matrix @ gradient)
    return Estimate(result, math.sqrt(variance) if math.isfinite(variance) and variance >= 0 else math.nan)
