"""Numbers typed into plot settings (``UnitSpinBox``): with or without the unit or an SI
prefix, negative, empty or invalid, with a locale's decimal comma, and beyond the limits."""
from __future__ import annotations

from typing import Any

import pytest
from pytestqt.qtbot import QtBot
from PyQt6 import QtWebEngineWidgets  # noqa: F401  Before the app starts, if this file runs alone.
from PyQt6.QtCore import QLocale, Qt

from helab.analysis.parameter_tree import UnitSpinBox, build_tree, parameter_of, settings_widget
from helab.analysis.parameters import ParameterSpec

SECONDS: dict[str, Any] = dict(suffix="s", siPrefix=True, dec=True, step=0.1, decimals=6)
PERCENT: dict[str, Any] = dict(suffix="%", min=0, max=100)
WHOLE: dict[str, Any] = dict(int=True, min=1, max=10, step=1, minStep=1)
GERMAN = QLocale(QLocale.Language.German, QLocale.Country.Germany)
ENGLISH = QLocale(QLocale.Language.English, QLocale.Country.Australia)


def box(qtbot: QtBot, value: float, locale: QLocale = ENGLISH, **options: Any) -> UnitSpinBox:
    made = UnitSpinBox()
    qtbot.addWidget(made)
    made.setLocale(locale)
    made.setOpts(value=value, **options)
    made.show()
    return made


def typed(qtbot: QtBot, spin: UnitSpinBox, text: str) -> tuple[float, str]:
    """Select all, type ``text`` and press Enter: the value and the text shown."""
    edit = spin.lineEdit()
    assert edit is not None
    edit.selectAll()
    if text:
        qtbot.keyClicks(edit, text)  # type: ignore[no-untyped-call]
    else:
        qtbot.keyClick(edit, Qt.Key.Key_Delete)  # type: ignore[no-untyped-call]
    qtbot.keyClick(edit, Qt.Key.Key_Return)  # type: ignore[no-untyped-call]
    return spin.value(), str(edit.text())


def assert_typed(qtbot: QtBot, spin: UnitSpinBox, text: str, value: float, shown: str) -> None:
    result, text_shown = typed(qtbot, spin, text)
    assert result == pytest.approx(value) and text_shown == shown


@pytest.mark.parametrize(("text", "value", "shown"), [
    ("5", 0.005, "5 ms"),  # A bare number is in the unit shown...
    ("-5", -0.005, "-5 ms"),
    (" 7 ", 0.007, "7 ms"),
    ("5.5", 0.0055, "5.5 ms"),
    ("1e-3", 1e-6, "1 µs"),  # ...exponent included.
    ("5 m", 0.005, "5 ms"),  # A prefix without the unit.
    ("5 u", 5e-6, "5 µs"),
    ("5 k", 5000.0, "5 ks"),
    ("5 s", 5.0, "5 s"),  # With the unit, as written.
    ("5 ms", 0.005, "5 ms"),
    ("5 µs", 5e-6, "5 µs"),
    ("5 us", 5e-6, "5 µs"),
    ("-2 ns", -2e-9, "-2 ns"),
    # Invalid: the value comes back.
    ("", 0.004, "4 ms"), ("abc", 0.004, "4 ms"), ("5 abc", 0.004, "4 ms"), ("5 x", 0.004, "4 ms"),
    ("inf", 0.004, "4 ms"), ("5,5", 0.004, "4 ms"), ("1,000", 0.004, "4 ms"), ("5 mss", 0.004, "4 ms"),
    ("--5", 0.004, "4 ms"), ("5e", 0.004, "4 ms"),
])
def test_seconds_with_si_prefixes(qtbot: QtBot, text: str, value: float, shown: str) -> None:
    spin = box(qtbot, 0.004, **SECONDS)
    assert spin.lineEdit() is not None and spin.text() == "4 ms"
    assert_typed(qtbot, spin, text, value, shown)


@pytest.mark.parametrize(("start", "shown", "text", "value"), [
    (0.0, "0 ms", "5", 0.005),  # Zero shows the prefix of a step.
    (-0.004, "-4 mm", "5", 0.005),
    (-0.004, "-4 mm", "-5", -0.005),
    (-0.004, "-4 mm", "5 m", 5.0),  # In a metres box "m" is the unit.
    (-0.004, "-4 mm", "5 mm", 0.005),
    (2.5, "2.5 m", "3", 3.0),
    (3e-6, "3 µm", "4", 4e-6),
    (2e3, "2 km", "-1", -1e3),
])
def test_each_shown_prefix(qtbot: QtBot, start: float, shown: str, text: str, value: float) -> None:
    spin = box(qtbot, start, **{**SECONDS, "suffix": "s" if shown.endswith("s") else "m"})
    assert spin.text() == shown
    assert typed(qtbot, spin, text)[0] == pytest.approx(value)


@pytest.mark.parametrize(("text", "value", "shown"), [
    ("95", 95.0, "95 %"), ("95 %", 95.0, "95 %"), ("95%", 95.0, "95 %"), ("95.5", 95.5, "95.5 %"),
    ("0", 0.0, "0 %"), ("100", 100.0, "100 %"),
    ("150", 100.0, "100 %"), ("-5", 0.0, "0 %"), ("1e3", 100.0, "100 %"),  # Beyond the limits: the nearest.
    ("", 99.0, "99 %"), ("95,5", 99.0, "99 %"), ("95 k", 99.0, "99 %"), ("95 m", 99.0, "99 %"),
])
def test_percent_with_limits(qtbot: QtBot, text: str, value: float, shown: str) -> None:
    assert_typed(qtbot, box(qtbot, 99.0, **PERCENT), text, value, shown)


@pytest.mark.parametrize(("text", "value"), [
    ("4", 4), ("+4", 4), ("4.0", 4), ("15", 10), ("-3", 1), ("0", 1),
    ("4.5", 2), ("1,000", 2), ("", 2), ("4 k", 2), ("four", 2),
])
def test_whole_numbers(qtbot: QtBot, text: str, value: int) -> None:
    spin = box(qtbot, 2, **WHOLE)
    result, _ = typed(qtbot, spin, text)
    assert result == value and isinstance(spin.interpret(), (int, bool))


@pytest.mark.parametrize(("text", "value", "shown"), [
    ("5,5", 0.0055, "5,5 ms"), ("5.5", 0.0055, "5,5 ms"), ("5", 0.005, "5 ms"), ("-0,5", -0.0005, "-500 µs"),
    ("5,5 ms", 0.0055, "5,5 ms"), ("1,5,5", 0.0385, "38,5 ms"),
])
def test_decimal_comma_locale(qtbot: QtBot, text: str, value: float, shown: str) -> None:
    """Where the comma is the decimal mark (German, as some Windows PCs are set), it is read as
    one; "." is read too, as the box never shows thousands separators."""
    spin = box(qtbot, 0.0385, locale=GERMAN, **SECONDS)
    assert spin.text() == "38,5 ms"
    assert_typed(qtbot, spin, text, value, shown)
    percent = box(qtbot, 99.0, locale=GERMAN, **PERCENT)
    assert_typed(qtbot, percent, "95,5", 95.5, "95,5 %")


def test_typed_values_reach_the_parameter(qtbot: QtBot) -> None:
    """Through the settings tree: a typed number is the parameter's value, clamped to its limits."""
    specs = [ParameterSpec("t_min", "T min", "float", 0.004, suffix="s", si=True),
             ParameterSpec("keep", "Keep", "float", 99.0, (50.0, 100.0), suffix="%"),
             ParameterSpec("bins", "Bins", "int", 100, (10, 1000))]
    root = build_tree(specs)
    tree = settings_widget(root, specs)
    qtbot.addWidget(tree)
    tree.show()

    def spin_of(spec: ParameterSpec) -> UnitSpinBox:
        widget = next(iter(parameter_of(root, spec).items)).widget
        assert isinstance(widget, UnitSpinBox)
        return widget

    typed(qtbot, spin_of(specs[0]), "-5 m")
    typed(qtbot, spin_of(specs[1]), "20")
    typed(qtbot, spin_of(specs[2]), "5000")
    assert parameter_of(root, specs[0]).value() == pytest.approx(-0.005)
    assert parameter_of(root, specs[1]).value() == 50.0
    assert parameter_of(root, specs[2]).value() == 1000 and isinstance(parameter_of(root, specs[2]).value(), int)


def test_red_outline_while_typing(qtbot: QtBot) -> None:
    """Beyond the limits or not a number: the box outlines red while typing; the edit's end
    clears it (set to the nearest limit, or back to the value)."""
    spin = box(qtbot, 99.0, **PERCENT)
    edit = spin.lineEdit()
    assert edit is not None
    for text, ended in (("150", 100.0), ("9x", 100.0)):
        before = spin.value()
        edit.selectAll()
        qtbot.keyClicks(edit, text)  # type: ignore[no-untyped-call]
        assert not spin.textValid and spin.errorBox.isVisibleTo(spin) and spin.value() == before
        qtbot.keyClick(edit, Qt.Key.Key_Return)  # type: ignore[no-untyped-call]
        assert spin.textValid and not spin.errorBox.isVisibleTo(spin) and spin.value() == ended
