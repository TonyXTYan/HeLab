"""Values with standard errors: how they are written (``format_uncertainty``), combined
(``pooled_mean_and_std``, ``sewm``) and carried through a formula (``propagate``).

Pure NumPy, no Qt. Written for plot titles and dock lines: ``50.12 ± 0.15``,
``8.5479(10)``, ``(416.12 ± 0.12) ms``. Shot bootstrap errors are D10's, not here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
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

    def as_record(self) -> dict[str, float | None]:
        """Strict JSON: a nan or infinite value or error is None."""
        return {"value": finite_or_none(self.value), "se": finite_or_none(self.se)}


def finite_or_none(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def decimal_exponent(value: float) -> int:
    """The power of ten of ``value``'s leading digit (0 for 0 and non-finite values), exact
    for subnormals too (no log10 rounding)."""
    if value == 0 or not math.isfinite(value):
        return 0
    return int(f"{abs(value):e}".split("e")[1])


def _scaled(value: float, exponent: int) -> float:
    """value × 10^−exponent, exactly rounded, without 10**exponent under- or overflowing."""
    if not math.isfinite(value) or value == 0:
        return value
    return float(Decimal(value).scaleb(-exponent))


def si_prefix(value: float) -> tuple[int, str]:
    """(exponent, prefix) that writes ``value`` with 1–3 digits before the point, the way
    pyqtgraph's ``siScale`` does: (0, "") for 0 and non-finite values, clamped to y…Y."""
    if value == 0 or not math.isfinite(value):
        return 0, ""
    exponent = min(max(decimal_exponent(value) // 3 * 3, -24), 24)
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
      error ``± nan`` / ``± ∞``, likewise. A negative error is taken as its size. An error
      below the value's float precision (10⁻¹⁵ of it) is written to 2 significant digits on
      its own (``1 ± 1e−20``) rather than as 20 decimals.
    - When rounding carries a number up a digit (999.96 ms → 1000.0 ms, 9.999×10⁷ → 10.00×10⁷,
      the value's or the error's), the next prefix or power is used.
    - Negative numbers use "−" (U+2212).
    """
    digits = max(int(digits), 1)
    se = abs(se)
    if not math.isfinite(value):
        return _join(_special(value), _plain(se) if math.isfinite(se) else _special(se), style, "", unit)
    reference = max(abs(value), se if math.isfinite(se) else 0.0)

    def render(exponent: int) -> tuple[str, str]:
        return _numbers(_scaled(value, exponent), _scaled(se, exponent), digits)

    if unit and si:
        exponent, _ = si_prefix(reference)
        texts = render(exponent)
        if _largest(texts) >= 1000 and exponent < 24:
            exponent += 3
            texts = render(exponent)
        return _join(*texts, style, "", SI_PREFIX_BY_EXPONENT[exponent] + unit)
    exponent = decimal_exponent(reference)
    if exponent in PLAIN_EXPONENTS:
        exponent = 0
    texts = render(exponent)
    if exponent and _largest(texts) >= 10:
        exponent += 1
        texts = render(exponent)
    elif not exponent and _largest(texts) >= 10 ** PLAIN_EXPONENTS.stop:  # 99999.7 → 100000
        exponent = PLAIN_EXPONENTS.stop
        texts = render(exponent)
    power = f"×10{str(exponent).translate(SUPERSCRIPTS)}" if exponent else ""
    return _join(*texts, style, power, unit)


def _largest(texts: tuple[str, str]) -> float:
    """The larger size of the written value and error (specials count as 0)."""
    sizes = [abs(float(text.replace(MINUS, "-"))) for text in texts if text not in ("nan", "∞", MINUS + "∞")]
    return max(sizes, default=0.0)


def _numbers(value: float, se: float, digits: int) -> tuple[str, str]:
    """The value and error as text, rounded together; the error's text is what goes after
    ``±`` (``_join`` makes the bracket form)."""
    if not math.isfinite(se) or se == 0:
        return _plain(value), _special(se) if not math.isfinite(se) else "0"
    if se < abs(value) * 1e-15:
        return _plain(value), f"{se:.{digits}g}".replace("-", MINUS)
    place = digits - 1 - decimal_exponent(se)  # decimals to keep
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
    ``np.std(ddof=ddof)`` give on the concatenated data. Counts must be whole numbers ≥ 0
    (else ``ValueError``). Groups of size 0 are ignored, and a group too small for its own
    deviation (size ≤ ddof) adds only its mean's spread; any other group's nan deviation
    makes the pooled one nan (its spread is unknown, not 0). nan when there are no data, or
    too few for ``ddof``."""
    mean_array = np.asarray(means, dtype=np.float64).ravel()
    std_array = np.asarray(stds, dtype=np.float64).ravel()
    count_array = np.asarray(counts, dtype=np.float64).ravel()
    if not len(mean_array) == len(std_array) == len(count_array):
        raise ValueError("means, stds and counts must have the same length")
    if not np.all((count_array >= 0) & (count_array == np.floor(count_array))):
        raise ValueError("counts must be whole numbers ≥ 0")
    used = count_array > 0
    mean_array, std_array, count_array = mean_array[used], std_array[used], count_array[used]
    total = int(count_array.sum())
    if total == 0:
        return math.nan, math.nan, 0
    mean = float(np.dot(count_array, mean_array) / total)
    own = count_array > ddof
    if not np.all(np.isfinite(std_array[own])):
        return mean, math.nan, total
    within = np.where(own, (count_array - ddof) * np.where(own, std_array, 0.0) ** 2, 0.0)
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
