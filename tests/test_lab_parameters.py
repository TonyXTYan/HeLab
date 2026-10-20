"""F0b Settings → Lab parameters: lab-level constants saved in QSettings (a tmp ini file here,
never the native store), with Restore default; CODATA values read-only."""
from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtCore import QSettings

from helab.analysis.physics import TABLE
from helab.utils.lab_parameters import lab_rows, read_lab_constants, setting_key, write_lab_constants
from helab.views.LabParametersTab import LabParametersTab
from helab.views.SettingsDialog import SettingsDialog


def ini(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


def test_lab_rows_are_the_tables_lab_level_rows() -> None:
    assert [row.key for row in lab_rows()] == ["hbar", "k_B", "u", "mass", "g", "scattering_length",
                                              "dld_trigger", "dld_acquisition"]


def test_values_persist_and_bad_ones_are_ignored(tmp_path: Path) -> None:
    settings = ini(tmp_path)
    write_lab_constants(settings, {"g": 9.8, "hbar": 1.0, "fall_distance": 0.9, "mass": -1.0})
    settings.sync()
    again = ini(tmp_path)  # A restart.
    assert read_lab_constants(again) == {"g": 9.8}  # CODATA, folder-level and bad values aren't lab values.
    again.setValue(setting_key("scattering_length"), "text")
    again.setValue(setting_key("dld_trigger"), "nan")
    assert read_lab_constants(again) == {"g": 9.8}
    write_lab_constants(again, {})  # Restore default for every row: the keys go.
    assert again.value(setting_key("g")) is None and read_lab_constants(again) == {}


def test_times_and_lengths_show_in_ms_and_mm_as_in_the_plots(qtbot: QtBot) -> None:
    from helab.views.LabParametersTab import constant_editor
    for key, value, text in (("dld_trigger", 20.5, "20,500 ms"), ("fall_distance", 0.848, "848 mm"),
                             ("trap_radial", 500.0, "500 Hz")):
        box = constant_editor(TABLE[key], value)
        qtbot.addWidget(box)
        assert box.text() == text and box.value() == pytest.approx(value)


def test_editors_are_wide_enough_for_their_values(qtbot: QtBot) -> None:
    """A spin box is at least as wide as its value shown, and grows for a longer one."""
    from helab.views.LabParametersTab import constant_editor
    box = constant_editor(TABLE["fall_time"], 0.41609078)
    qtbot.addWidget(box)
    box.show()
    assert box.text() == "416.09078 ms"
    assert box.minimumWidth() >= box.fontMetrics().horizontalAdvance("416.09078 ms") + 20
    narrow = box.minimumWidth()
    box.setValue(123456.123456)  # A much longer number.
    assert box.minimumWidth() >= box.fontMetrics().horizontalAdvance(box.text()) and box.minimumWidth() >= narrow


def test_the_tab_edits_restores_and_saves(qtbot: QtBot, tmp_path: Path) -> None:
    settings = ini(tmp_path)
    write_lab_constants(settings, {"g": 9.8})
    tab = LabParametersTab(settings)
    qtbot.addWidget(tab)
    assert set(tab.editors) == {"mass", "g", "scattering_length", "dld_trigger", "dld_acquisition"}
    assert set(tab.read_only) == {"hbar", "k_B", "u"} and tab.status_text("hbar") == "CODATA, read-only"
    assert tab.editor_value("g") == 9.8 and tab.status_text("g") == "set here"
    assert tab.restore_buttons["g"].isEnabled() and not tab.restore_buttons["mass"].isEnabled()
    assert tab.status_text("dld_trigger") == "default · shown only · unconfirmed"
    assert tab.status_text("mass") == "default"
    tab.editors["scattering_length"].setValue(7.5e-9)
    tab.restore("g")
    assert tab.editor_value("g") == TABLE["g"].value and tab.status_text("g") == "default"
    assert tab.values() == {"scattering_length": 7.5e-9}
    tab.save(settings)
    assert read_lab_constants(settings) == {"scattering_length": pytest.approx(7.5e-9)}


def test_the_settings_dialog_has_the_tab_and_saves_and_resets_it(qtbot: QtBot, tmp_path: Path) -> None:
    settings = ini(tmp_path)
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)
    assert dialog.tabs.tabText(1) == "Lab parameters"
    dialog.lab_tab.editors["g"].setValue(9.81)
    dialog._write_settings()
    assert read_lab_constants(settings) == {"g": 9.81}
    dialog.cache_tab.confirm = lambda *args: True
    dialog.reset_settings()
    assert read_lab_constants(settings) == {} and dialog.lab_tab.editor_value("g") == TABLE["g"].value
