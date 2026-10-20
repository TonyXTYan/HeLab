"""Display units (Tony, 2026-10-20): T always in ms, X and Y in mm, digits grouped by thousands
with "," and "." whatever the locale, in text, axis ticks and settings; stored values in s and m."""
from __future__ import annotations

import math
from typing import Any

import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401  Before the app starts, if this file runs alone.
from PyQt6.QtCore import QLocale
from pytestqt.qtbot import QtBot

from helab.analysis import display_units as du
from helab.analysis import selection
from helab.analysis.estimates import Estimate, format_fixed
from helab.analysis.parameter_tree import UnitSpinBox, build_tree, parameter_of, settings_widget, tree_values
from helab.analysis.parameters import ParameterSpec
from helab.analysis.plot_axes import GroupedAxis, grouped_axes
from helab.scripts.standard import basic_plots, mean_position, shot_trends, t_spectrum, transfer_fractions

GERMAN = QLocale(QLocale.Language.German, QLocale.Country.Germany)
ENGLISH = QLocale(QLocale.Language.English, QLocale.Country.Australia)


@pytest.mark.parametrize(("seconds", "text"), [
    (0.0005, "0.5 ms"), (0.9999, "999.9 ms"), (1.0, "1,000 ms"), (20.4501234, "20,450.1234 ms"),
    (-1.5, "−1,500 ms"), (-0.0004, "−0.4 ms"), (0.0, "0 ms"), (123.456789, "123,456.789 ms"),
    (2.137475777, "2,137.4758 ms"),  # a position keeps at most 4 decimals (0.1 µs)
    (math.nan, "– ms")])
def test_times_are_in_ms_grouped_by_thousands(seconds: float, text: str) -> None:
    assert du.time_text(seconds) == text


def test_widths_lengths_and_ranges() -> None:
    assert du.time_text(1.23456e-4, du.WIDTH_DIGITS) == "0.1235 ms"
    assert du.time_text(5e-8, du.WIDTH_DIGITS) == "0.00005 ms"  # a width keeps the digits it needs
    assert du.length_text(-0.0025) == "−2.5 mm" and du.length_text(1.5) == "1,500 mm"
    assert du.range_text("T", 20.45, 20.55) == "T 20,450–20,550 ms"
    assert du.range_text(1, -0.002, 0.0035) == "X −2–3.5 mm"
    assert du.axis_label(0) == "T (ms)" and du.axis_label("Y") == "Y (mm)"
    assert du.number_text(-0.0) == "0" and du.grouped(-0.0001, 2) == "0.00" and du.grouped(-1234.5, 1) == "−1,234.5"


def test_estimates_in_a_fixed_unit_are_grouped_after_rounding() -> None:
    assert du.estimate_text("T", Estimate(20.91612345, 1.2e-7)) == "(20,916.12345 ± 0.00012) ms"
    assert du.estimate_text("T", Estimate(20.91612, 1.2e-4)) == "(20,916.12 ± 0.12) ms"
    assert du.estimate_text("T", Estimate(20.91612, 1.2e-4), "paren") == "20,916.12(12) ms"
    assert du.estimate_text("X", Estimate(-1.2345, 0.0021)) == "(−1,234.5 ± 2.1) mm"
    assert du.estimate_text("T", Estimate(123.4, 0.5)) == "(123,400 ± 500) ms"  # no power of ten
    assert du.estimate_text("T", Estimate(0.4161, math.nan)) == "(416.1 ± nan) ms"
    # The numbers are rounded before they are grouped (an error rounding up carries over).
    assert format_fixed(9999.996, 0.04, unit="ms", digits=1) == "(10000.00 ± 0.04) ms"
    assert du.group_digits("(10000.00 ± 0.04) ms") == "(10,000.00 ± 0.04) ms"
    assert du.group_digits("0.12345 and 12345.6789") == "0.12345 and 12,345.6789"


@pytest.mark.parametrize(("values", "spacing", "texts"), [
    ([20_400.0, 20_500.0], 100.0, ["20,400", "20,500"]),
    ([20_450.0, 20_450.5], 0.5, ["20,450.0", "20,450.5"]),
    ([12_000.0, 12_002.5], 2.5, ["12,000.0", "12,002.5"]),
    ([0.5, 0.75], 0.25, ["0.50", "0.75"]),
    ([-1_000.0, 0.0, 1_000.0], 1_000.0, ["−1,000", "0", "1,000"]),
    ([999.9, 1_000.0], 0.1, ["999.9", "1,000.0"]),
])
def test_tick_labels_take_their_decimals_from_the_spacing(values: list[float], spacing: float,
                                                         texts: list[str]) -> None:
    assert du.tick_strings(values, 1.0, spacing) == texts


def test_the_grouped_axis_labels_ticks_and_never_rescales(qtbot: QtBot) -> None:
    axis = GroupedAxis("bottom")
    assert axis.tickStrings([20_400.0, 20_500.0], 1.0, 100.0) == ["20,400", "20,500"]
    assert not axis.autoSIPrefix
    assert set(grouped_axes("bottom", "left")) == {"bottom", "left"}


@pytest.mark.parametrize(("value", "unit", "text"), [
    (0.99999e-3, "s", "1 ms"), (999.6e-6, "m", "999.6 µm"), (-2e-4, "s", "−200 µs"), (1e-12, "s", "1 ps"),
    (0.0, "m", "0 m"), (math.nan, "s", "–"), (0.848, "m", "848 mm"), (1250.0, "Hz", "1.25 kHz"),
    (1e-30, "s", "1e−06 ys")])
def test_si_text_rounds_before_its_prefix_over_y_to_Y(value: float, unit: str, text: str) -> None:
    assert du.si_text(value, unit) == text


def spin(qtbot: QtBot, value: float, locale: QLocale | None = None, suffix: str = "s") -> UnitSpinBox:
    box = UnitSpinBox()
    qtbot.addWidget(box)
    if locale is not None:
        box.setLocale(locale)
    box.setOpts(value=value, suffix=suffix, siPrefix=True, dec=True, step=0.1, decimals=6, fixedPrefix="m")
    return box


@pytest.mark.parametrize(("text", "value"), [
    ("20,450.5", 20.4505), ("20450.5", 20.4505), ("5", 0.005), ("-1,000", -1.0), ("5 s", 5.0),
    ("1,000 ms", 1.0), ("2 µs", 2e-6), ("1,0000", None), ("12,34", None), ("0,450", None)])
def test_a_fixed_prefix_box_reads_grouped_numbers(qtbot: QtBot, text: str, value: float | None) -> None:
    box = spin(qtbot, 20.4501234)
    assert box.text() == "20,450.1234 ms"
    parsed = box.parse(text)
    assert (parsed is None) if value is None else float(parsed) == pytest.approx(value)


@pytest.mark.parametrize("locale", [GERMAN, ENGLISH], ids=["de_DE", "en"])
@pytest.mark.parametrize(("text", "value"), [
    ("20,5", None), ("20,500", 20.5), ("0,450", None), ("20,450.5", 20.4505), ("1,23", None),
    ("−5", -0.005), ("-5", -0.005), ("20.5", 0.0205), ("1,000,000", 1000.0), ("20,450,5", None),
    ("−1,000.5 ms", -1.0005)])
def test_in_a_fixed_prefix_box_a_comma_only_ever_groups_thousands(qtbot: QtBot, locale: QLocale, text: str,
                                                                  value: float | None) -> None:
    """Whatever the locale (Tony): "," is only a thousands separator and "." the only decimal
    point, so a comma can never change a value 1,000× silently: "20,5" and "0,450" are invalid."""
    box = spin(qtbot, 20.4501234, locale)
    assert box.text() == "20,450.1234 ms"
    parsed = box.parse(text)
    assert (parsed is None) if value is None else float(parsed) == pytest.approx(value)


def test_a_fixed_prefix_box_shows_minus_and_extremes(qtbot: QtBot) -> None:
    box = spin(qtbot, 0.0)
    assert box.text() == "0 ms"
    millimetres = spin(qtbot, -0.0025, suffix="m")
    assert millimetres.text() == "−2.5 mm" and float(millimetres.parse("3")) == pytest.approx(0.003)
    assert float(millimetres.parse(millimetres.text())) == pytest.approx(-0.0025)
    box.setValue(1e-60)
    assert box.text() == "1e−57 ms" and float(box.parse(box.text())) == pytest.approx(1e-60)
    box.setValue(1e60)
    assert box.text() == "1e+63 ms" and len(box.text()) < 20
    box.setValue(5.925e-7)
    assert box.text() == "0.0005925 ms"
    assert box.toolTip().endswith("0.0005925 ms = 592.5 ns")  # a µs/ns hint for a tiny width
    box.setToolTip("Its own tip")
    box.setValue(2e-6)
    assert box.toolTip() == "Its own tip\n0.002 ms = 2 µs"
    box.setValue(2.0)
    assert box.toolTip() == "Its own tip"


def test_view_range_bounds_show_ms_and_mm_and_keep_si_values(qtbot: QtBot) -> None:
    """The manual T bounds show in ms (X/Y in mm), grouped; the values stay in s and m, so saved
    settings keep their meaning."""
    specs = list(selection.range_specs("tip"))
    t_min, x_max = (next(spec for spec in specs if spec.name == name) for name in ("t_min", "x_max"))
    assert t_min.unit_prefix == "m" and t_min.tree_item(20.45)["fixedPrefix"] == "m"
    root = build_tree(specs)
    tree = settings_widget(root, specs)
    qtbot.addWidget(tree)
    tree.show()
    parameter_of(root, selection.RANGE_MODE).setValue(selection.MANUAL)
    parameter_of(root, t_min).setValue(20.4501234)
    parameter_of(root, x_max).setValue(0.0035)
    widget: Any = next(iter(parameter_of(root, t_min).items)).widget
    assert widget.text() == "20,450.1234 ms"
    assert next(iter(parameter_of(root, x_max).items)).widget.text() == "3.5 mm"
    values = tree_values(root, specs)
    assert values["t_min"] == pytest.approx(20.4501234) and values["x_max"] == pytest.approx(0.0035)
    assert t_min.text(20.4501234) == "T min 20,450.1234 ms" and x_max.text(0.0035) == "X max 3.5 mm"
    plain = ParameterSpec("t", "T", "float", 0.0, None, " s", si=True)
    assert plain.text(0.5) == "T 0.5 s" and "fixedPrefix" not in plain.tree_item()


def test_constants_and_their_notes_read_in_ms_and_mm() -> None:
    from helab.analysis import constant_layers, physics
    assert physics.resolve(plot={"fall_time": 0.5}).notes == (
        "fall time and distance disagree: t_f 500 ms (plot), but √(2h/g) is 416.0908 ms for h 848 mm "
        "(default) and g 9.79602 m/s² (default)",)
    assert constant_layers.value_text("dld_trigger", 20.5) == "20,500 ms"
    assert constant_layers.value_text("trap_radial", 500.0) == "500 Hz"


def test_every_t_and_xy_setting_of_the_plots_is_in_ms_or_mm() -> None:
    """Positions and widths along T, X and Y (bounds, bin widths, σ, orders' times, the XY box)."""
    names = {basic_plots.TxyHistograms(): ("t_min", "x_min", "y_max", "smooth_t", "smooth_xy", "const.fall_time"),
             mean_position.MeanPositionVsT(): ("t_bin",), t_spectrum.TProfileSpectrum(): ("t_bin",),
             transfer_fractions.TransferFractions(): ("centre", "spacing", "half_width", "search_min",
                                                      "search_max", "xy_half"),
             shot_trends.ShotTrends(): ("t_min", "x_max", "const.fall_time", "const.fall_distance")}
    for script, wanted in names.items():
        specs = {spec.name: spec for spec in script.parameters("Plot")}
        for name in wanted:
            assert specs[name].unit_prefix == "m", (script, name)
    fall = {spec.name: spec for spec in basic_plots.TxyHistograms().parameters("Plot")}["const.fall_distance"]
    assert fall.unit_prefix == "m"  # lengths in mm, as the plots show them
