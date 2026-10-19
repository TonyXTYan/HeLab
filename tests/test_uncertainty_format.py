"""Value ± SE formatting, pooled statistics, the weighted mean's SE and error propagation."""
from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt
import pyqtgraph.functions as pg_functions
import pytest

from helab.analysis.estimates import (Estimate, Style, format_uncertainty, pooled_mean_and_std, propagate, sewm,
                                      si_prefix)


@pytest.mark.parametrize("value,se,style,expected", [
    (50.1234, 0.1523, "pm", "50.12 ± 0.15"),
    (8.54791, 0.00101, "paren", "8.5479(10)"),
    (8.54791, 0.00101, "pm", "8.5479 ± 0.0010"),
    (50.1234, 0.1523, "paren", "50.12(15)"),
    (12.34, 1.23, "paren", "12.3(12)"),  # the error in the last digits, as CODATA writes it
    (1234.0, 56.0, "paren", "1234(56)"),
    (12345.0, 1234.0, "pm", "12300 ± 1200"),
    (12345.0, 1234.0, "paren", "12300(1200)"),
    (0.0996, 0.0996, "pm", "0.10 ± 0.10"),  # the error rounds up a digit: still two
    (-3.2, 0.15, "pm", "−3.20 ± 0.15"),
    (-0.0004, 0.05, "pm", "0.000 ± 0.050"),  # no "−0.000"
    (0.0, 0.05, "pm", "0.000 ± 0.050"),
    (0.5, 3.0, "pm", "0.5 ± 3.0"),
    (5.0, -0.2, "pm", "5.00 ± 0.20"),  # a negative error is taken as its size
    (1.0, 0.0, "pm", "1 ± 0"),
    (1.2345678, 0.0, "paren", "1.23457(0)"),
    (1.0, math.nan, "pm", "1 ± nan"),
    (1.0, math.inf, "pm", "1 ± ∞"),
    (1.0, math.inf, "paren", "1(∞)"),
    (math.nan, 0.1, "pm", "nan ± 0.1"),
    (-math.inf, math.nan, "pm", "−∞ ± nan"),
    (1.23456e8, 2.3e5, "pm", "(1.2346 ± 0.0023)×10⁸"),
    (1.23456e8, 2.3e5, "paren", "1.2346(23)×10⁸"),
    (3.2e-7, 1.1e-8, "pm", "(3.20 ± 0.11)×10⁻⁷"),
    (2.5e-3, 1e-4, "pm", "0.00250 ± 0.00010"),  # 10⁻³ is still written plainly
])
def test_formatting(value: float, se: float, style: Style, expected: str) -> None:
    assert format_uncertainty(value, se, style) == expected


@pytest.mark.parametrize("value,se,style,unit,si,expected", [
    (0.41612, 0.000123, "pm", "s", True, "(416.12 ± 0.12) ms"),
    (0.41612, 0.000123, "paren", "s", True, "416.12(12) ms"),
    (9.89e-5, 1.1e-6, "paren", "s", True, "98.9(11) µs"),
    (0.99996, 0.00001, "pm", "s", True, "(999.960 ± 0.010) ms"),
    (0.9999996, 0.0001, "pm", "s", True, "(1.00000 ± 0.00010) s"),  # 1000.00 ms: the next prefix
    (0.0, 2e-6, "pm", "m", True, "(0.0 ± 2.0) µm"),  # the prefix from the error when the value is 0
    (-2.5e-3, 1e-4, "pm", "m", True, "(−2.50 ± 0.10) mm"),
    (4e-4, 0.05, "pm", "m", True, "(0 ± 50) mm"),  # the prefix from the larger: the error
    (2.0e-7, 1e-8, "pm", "K", True, "(200 ± 10) nK"),
    (6.6465e-27, 2e-31, "pm", "kg", False, "(6.64650 ± 0.00020)×10⁻²⁷ kg"),
    (5.0, 0.2, "pm", "kg", False, "(5.00 ± 0.20) kg"),
    (1.0, math.nan, "pm", "s", True, "(1 ± nan) s"),
    (math.inf, 1.0, "pm", "s", True, "(∞ ± 1) s"),
])
def test_formatting_with_units(value: float, se: float, style: Style, unit: str, si: bool, expected: str) -> None:
    assert format_uncertainty(value, se, style, unit, si) == expected


def test_prefix_clamps_beyond_yocto_and_yotta() -> None:
    assert si_prefix(1e-30) == (-24, "y") and si_prefix(1e30) == (24, "Y")


def test_digits_and_estimates() -> None:
    assert format_uncertainty(50.1234, 0.1523, digits=1) == "50.1 ± 0.2"
    assert format_uncertainty(50.1234, 0.1523, digits=3) == "50.123 ± 0.152"
    assert Estimate(0.41612, 0.000123).text("paren", "s") == "416.12(12) ms"
    record = Estimate(1.5, 0.25).as_record()
    assert record == {"value": 1.5, "se": 0.25}


@pytest.mark.parametrize("value", [0.0, 1.0, -1.0, 999.0, 1000.0, -2.5e-3, math.nan]
                         + list(np.geomspace(1.1e-24, 9e26, 61)))
def test_prefix_matches_pyqtgraph(value: float) -> None:
    """The prefix the spin boxes (pyqtgraph's siScale) would show for the same number, over
    y…Y. Beyond them pyqtgraph writes no prefix (below 10⁻²⁵) or "e27"; here they clamp."""
    exponent, prefix = si_prefix(value)
    if not math.isfinite(value) or value == 0:
        assert (exponent, prefix) == (0, "")
        return
    factor, expected = pg_functions.siScale(value)
    assert prefix == expected
    assert 10.0 ** -exponent == pytest.approx(factor)


def test_pooled_matches_numpy_on_the_joined_data() -> None:
    rng = np.random.default_rng(4)
    groups = [rng.normal(rng.uniform(-3, 3), rng.uniform(0.5, 2), int(size)) for size in (1, 2, 5, 40, 300, 0)]
    joined = np.concatenate(groups)
    for ddof in (0, 1):
        means = [float(group.mean()) if len(group) else math.nan for group in groups]
        stds = [float(group.std(ddof=ddof)) if len(group) > ddof else math.nan for group in groups]
        mean, std, count = pooled_mean_and_std(means, stds, [len(group) for group in groups], ddof=ddof)
        assert count == len(joined)
        assert mean == pytest.approx(float(joined.mean()))
        assert std == pytest.approx(float(joined.std(ddof=ddof)))


def test_pooled_edge_cases() -> None:
    mean, std, count = pooled_mean_and_std([], [], [])
    assert math.isnan(mean) and math.isnan(std) and count == 0
    mean, std, count = pooled_mean_and_std([2.0], [math.nan], [1])
    assert (mean, count) == (2.0, 1) and math.isnan(std)
    with pytest.raises(ValueError):
        pooled_mean_and_std([1.0], [1.0, 2.0], [1])


def gatz_smith(values: npt.NDArray[np.float64], weights: npt.NDArray[np.float64]) -> float:
    """Cochran's SE of the weighted mean as Gatz & Smith (1995) write it, term by term."""
    n, mean_weight = len(values), float(weights.mean())
    mean = float(np.dot(weights, values) / weights.sum())
    a, b = weights * values - mean_weight * mean, weights - mean_weight
    bracket = float(np.sum(a ** 2) - 2 * mean * np.sum(b * a) + mean ** 2 * np.sum(b ** 2))
    return math.sqrt(n / ((n - 1) * float(weights.sum()) ** 2) * bracket)


def test_sewm() -> None:
    rng = np.random.default_rng(5)
    values = rng.normal(10, 2, 50)
    plain = sewm(values, np.ones(50))
    assert plain.value == pytest.approx(float(values.mean()))
    assert plain.se == pytest.approx(float(values.std(ddof=1)) / math.sqrt(50))
    weights = rng.uniform(0.1, 5, 50)
    weighted = sewm(values, weights)
    assert weighted.value == pytest.approx(float(np.average(values, weights=weights)))
    assert weighted.se == pytest.approx(gatz_smith(values, weights))
    assert math.isnan(sewm([1.0], [2.0]).se) and sewm([1.0], [2.0]).value == 1.0
    assert math.isnan(sewm([1.0, 2.0], [0.0, 0.0]).value)
    assert sewm([1.0, 2.0, math.nan], [1.0, 1.0, 1.0]).value == 1.5
    with pytest.raises(ValueError):
        sewm([1.0], [1.0, 2.0])


def test_propagate() -> None:
    covariance = np.array([[0.04, 0.01], [0.01, 0.09]])
    linear = propagate(lambda p: float(2 * p[0] - p[1]), [1.0, 3.0], covariance)
    assert linear.value == pytest.approx(-1.0)
    assert linear.se == pytest.approx(math.sqrt(4 * 0.04 - 4 * 0.01 + 0.09))
    ratio = propagate(lambda p: float(p[0] / p[1]), [2.0, 4.0], np.diag([0.01, 0.04]))
    assert ratio.se == pytest.approx(0.5 * math.sqrt((0.1 / 2) ** 2 + (0.2 / 4) ** 2), rel=1e-5)
    assert math.isnan(propagate(lambda p: float(p[0]), [1.0], [[math.inf]]).se)
    assert math.isnan(propagate(lambda p: float(p[0]), [1.0, 2.0], np.eye(3)).se)
