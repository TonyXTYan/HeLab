"""One settings factory (``helab.utils.settings_store.app_settings``): the app opens its native
settings only there, and tests get an ini file of their own instead (``tests/conftest.py``)."""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings

from helab.utils.settings_store import QSETTINGS_APP_NAME, QSETTINGS_ORG_NAME, app_settings

HELAB = Path(__file__).resolve().parents[1] / "helab"
# The factory itself, and a helper reopening the store the app named (``settings_spec``).
ALLOWED = {HELAB / "utils" / "settings_store.py", HELAB / "utils" / "cache_setting.py"}


def native_stores(path: Path) -> list[int]:
    """Lines of ``path`` that construct a ``QSettings`` other than an ini file."""
    lines = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), str(path))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        if name != "QSettings":
            continue
        ini = any(isinstance(arg, ast.Attribute) and arg.attr == "IniFormat" for arg in node.args[1:])
        if not ini:
            lines.append(node.lineno)
    return lines


def test_only_the_factory_opens_the_native_settings() -> None:
    found = {str(path.relative_to(HELAB.parent)): lines for path in sorted(HELAB.rglob("*.py"))
             if path not in ALLOWED and (lines := native_stores(path))}
    assert found == {}, f"Open the app's settings with settings_store.app_settings(): {found}"


def test_the_check_finds_a_native_store(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("from PyQt6.QtCore import QSettings\n"
                      "a = QSettings('ANU_HE_BEC_GROUP', 'HeLab')\n"
                      "b = QSettings()\n"
                      "c = QSettings('x.ini', QSettings.Format.IniFormat)\n", encoding="utf-8")
    assert native_stores(sample) == [2, 3]


def test_tests_get_an_ini_file_of_their_own() -> None:
    settings = app_settings()
    assert settings.format() == QSettings.Format.IniFormat
    assert settings.fileName() == os.environ["HELAB_TEST_SETTINGS_FILE"]
    settings.setValue("probe", 1)
    assert app_settings().value("probe", type=int) == 1


def test_without_the_seam_it_is_the_native_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Org and app, Qt's native format and user scope (recorded, never opened: tests don't
    create native stores)."""
    made: list[tuple[object, ...]] = []

    def record(*args: object) -> tuple[object, ...]:
        made.append(args)
        return args

    monkeypatch.setattr("helab.utils.settings_store.QSettings", record)
    monkeypatch.delenv("HELAB_TEST_SETTINGS_FILE")
    app_settings()
    assert made == [(QSETTINGS_ORG_NAME, QSETTINGS_APP_NAME)]
