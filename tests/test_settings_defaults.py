"""Every QSettings key HeLab reads is in one table with its default (helab/utils/settings_defaults.py):
a read of a key the table doesn't list, or with a default of its own, fails here."""
from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import Any, Iterator

import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before any QApplication: two tests build the main window)
from PyQt6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from helab.analysis.physics import CONSTANTS
from helab.utils import constants, lab_parameters, settings_defaults
from helab.utils.settings_defaults import PREFIXES, RETIRED, SETTINGS, read_setting, setting, setting_default

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "helab" / "utils" / "settings_defaults.py"
WRITES = {"setValue", "remove", "contains"}


def test_the_table_is_well_formed() -> None:
    keys = [row.key for row in SETTINGS]
    assert len(keys) == len(set(keys))
    for row in SETTINGS:
        assert type(row.default) is row.type, row  # (bool isn't taken for int, nor int for float)
        assert row.description.strip(), row
    assert not set(keys) & set(RETIRED)
    for prefix in PREFIXES:
        assert prefix.key.endswith("/") and prefix.default is None and not any(k.startswith(prefix.key) for k in keys)


def test_constants_defaults_are_the_tables() -> None:
    assert constants.DEFAULT_LOAD_MODE == setting_default(constants.LOAD_MODE_SETTING) == "finish"
    assert constants.DEFAULT_CHECK_LEVEL == setting_default(constants.CHECK_LEVEL_SETTING) == "medium"
    assert constants.DEFAULT_SIMULTANEOUS_IO == setting_default(constants.SIMULTANEOUS_IO_SETTING) == 1
    assert constants.DEFAULT_DISK_BUDGET == setting_default(constants.DISK_BUDGET_SETTING) == 8 << 30
    assert constants.DEFAULT_RAM_STEPS == setting_default(constants.RAM_BUDGET_SETTING) == 16
    assert constants.DEFAULT_LIVE_INTERVAL == setting_default(constants.LIVE_INTERVAL_SETTING) == 3.0
    assert constants.DEFAULT_LIVE_AUTOSAVE == setting_default(constants.LIVE_AUTOSAVE_SETTING) == 10
    assert constants.DEFAULT_LOAD_MODE in constants.LOAD_MODE_LABELS
    assert constants.DEFAULT_CHECK_LEVEL in constants.CHECK_LEVEL_LABELS


def test_lab_constants_are_the_prefix_rows() -> None:
    assert lab_parameters.setting_key("g") == PREFIXES[0].key + "g"
    for constant in CONSTANTS:
        if lab_parameters.editable(constant):
            assert setting(lab_parameters.setting_key(constant.key)) is PREFIXES[0]
    with pytest.raises(KeyError):
        setting(PREFIXES[0].key)  # (A prefix alone is no key.)


def test_a_key_not_in_the_table_cant_be_read(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    with pytest.raises(KeyError, match="not in HeLab's settings table"):
        read_setting(settings, "no_such_setting")


def test_large_numbers_read_untyped(tmp_path: Path) -> None:
    """PyQt's type=int reads 8 GiB as 0, so the disk budget is read as saved."""
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    assert settings.value("anything", 8 << 30, type=int) == 0  # (Why: PyQt's 32-bit int.)
    settings.setValue(constants.DISK_BUDGET_SETTING, 20 << 30)
    assert constants.read_disk_budget(settings) == 20 << 30


def test_unset_reads_give_the_tables_defaults(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    for row in SETTINGS:
        assert read_setting(settings, row.key) == row.default
        if row.type in (bool, str):
            assert read_setting(settings, row.key, typed=True) == row.default
        else:
            with pytest.raises(ValueError, match="read it untyped"):
                read_setting(settings, row.key, typed=True)
    assert constants.read_disk_budget(settings) == 8 << 30
    assert constants.read_io_concurrency(settings) == 1
    assert constants.read_check_level(settings) == "medium" and constants.read_load_mode(settings) == "finish"
    assert constants.read_live_interval(settings) == 3.0 and constants.read_live_autosave(settings) == 10
    assert constants.read_plot_auto_reload(settings) is True
    assert lab_parameters.read_lab_constants(settings) == {}


def _keys(node: ast.expr, module: Any) -> list[str] | None:
    """The key a call passes, if it can be told without running it (None if not)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name) and isinstance(getattr(module, node.id, None), str):
        return [getattr(module, node.id)]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "setting_key":
        return [lab_parameters.setting_key("g")]
    return None


def _settings_calls() -> Iterator[tuple[str, int, str, list[str] | None]]:
    """(file, line, method, keys) for each settings call in helab/: ``.value``, ``.setValue``,
    ``.remove`` and ``.contains`` on something named settings, and ``read_setting``."""
    for file in sorted((ROOT / "helab").rglob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        name = ".".join(file.relative_to(ROOT).with_suffix("").parts)
        module: Any = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id == "read_setting":
                method, key = "read_setting", node.args[1]
            elif (isinstance(func, ast.Attribute) and func.attr in WRITES | {"value"}
                  and "settings" in ast.unparse(func.value).lower()):
                method, key = func.attr, node.args[0]
            else:
                continue
            if module is None:
                module = importlib.import_module(name)
            yield file.relative_to(ROOT).as_posix(), node.lineno, method, _keys(key, module)


def test_no_read_bypasses_the_table() -> None:
    calls = list(_settings_calls())
    direct = [(file, line) for file, line, method, _ in calls
              if method == "value" and file != TABLE.relative_to(ROOT).as_posix()]
    assert not direct, f"read these through settings_defaults.read_setting: {direct}"
    assert sum(method == "read_setting" for _, _, method, _ in calls) >= 20  # (The scan finds them.)


def test_every_key_read_or_written_is_listed() -> None:
    unlisted = []
    for file, line, method, keys in _settings_calls():
        for key in keys or ():
            try:
                setting(key)
            except KeyError:
                if not (method == "remove" and key in RETIRED):
                    unlisted.append((file, line, method, key))
    assert not unlisted


def test_a_real_window_and_settings_read_only_listed_keys_with_their_defaults(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """At run time too: the main window and the Settings dialog, opened on the test's settings."""
    from helab.views.HelabMainWindow import HelabMainWindow
    from helab.views.SettingsDialog import SettingsDialog
    reads: list[tuple[str, Any]] = []
    original = QSettings.value

    def value(self: QSettings, key: str, defaultValue: Any = None, type: Any = None) -> Any:
        reads.append((key, defaultValue))
        return original(self, key, defaultValue) if type is None else original(self, key, defaultValue, type=type)

    monkeypatch.setattr(QSettings, "value", value)
    window = HelabMainWindow()
    qtbot.addWidget(window)
    dialog = SettingsDialog(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(dialog)
    window.close()
    assert {key for key, _ in reads} >= {row.key for row in SETTINGS} - {
        settings_defaults.DIR_TEMPS_SETTING, settings_defaults.DIR_CACHES_SETTING}  # (Overridden in tests.)
    for key, default in reads:
        assert default == setting(key).default, key
