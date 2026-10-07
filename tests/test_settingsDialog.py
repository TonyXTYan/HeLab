import pytest
from pathlib import Path
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from helab.views.SettingsDialog import SettingsDialog
from helab.utils.constants import (
    AUTO_SCAN_VISIBLE_SETTING, SIMULTANEOUS_IO_SETTING,
    read_io_concurrency,
)

@pytest.fixture
def app(qapp: QApplication) -> QApplication:
    """Create QApplication fixture"""
    return qapp

@pytest.fixture
def settings_dialog(app: QApplication, tmp_path: Path) -> SettingsDialog:
    """Create SettingsDialog fixture"""
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    dialog = SettingsDialog(settings=settings)
    return dialog

def test_settings_dialog_creation(qtbot: QtBot, settings_dialog: SettingsDialog) -> None:
    """Test basic dialog creation and properties"""
    # Add widget to qtbot
    qtbot.addWidget(settings_dialog)
    
    # Verify window properties
    assert settings_dialog.windowTitle() == "Settings"
    assert settings_dialog.minimumSize().width() == 800
    assert settings_dialog.minimumSize().height() == 500

def test_settings_dialog_tab_widget(qtbot: QtBot, settings_dialog: SettingsDialog) -> None:
    """Test tab widget setup"""
    qtbot.addWidget(settings_dialog)
    
    # Verify tab widget exists
    assert settings_dialog.tabs is not None
    
    # Verify default tabs
    expected_tabs = ["General", "Scripts", "Cache"] 
    assert [settings_dialog.tabs.tabText(i) for i in range(settings_dialog.tabs.count())] == expected_tabs

def test_cache_tab_controls(qtbot: QtBot, settings_dialog: SettingsDialog) -> None:
    """Test cache tab controls"""
    qtbot.addWidget(settings_dialog)
    
    # Verify cache tab widgets
    assert settings_dialog.cache_tab is not None
    assert settings_dialog.cache_layout is not None
    assert settings_dialog.cache_widgets is not None
    assert isinstance(settings_dialog.cache_params_ui, dict)

def test_settings_dialog_buttons(qtbot: QtBot, settings_dialog : SettingsDialog) -> None:
    """Test dialog buttons"""
    qtbot.addWidget(settings_dialog)
    
    # Verify button existence
    assert settings_dialog.save_button is not None
    assert settings_dialog.cancel_button is not None 
    assert settings_dialog.reset_button is not None
    
    # Test button labels
    assert settings_dialog.save_button.text() == "Save"
    assert settings_dialog.cancel_button.text() == "Cancel"
    assert settings_dialog.reset_button.text() == "Reset"


def test_folder_io_settings_defaults_persistence_and_reset(
    qtbot: QtBot, settings_dialog: SettingsDialog,
) -> None:
    dialog = settings_dialog
    qtbot.addWidget(dialog)
    assert dialog.simultaneous_io_spin.value() == 1
    assert not dialog.auto_scan_visible_checkbox.isChecked()
    dialog.simultaneous_io_spin.setValue(3)
    dialog.auto_scan_visible_checkbox.setChecked(True)
    dialog.save_settings()
    restored = SettingsDialog(settings=dialog.settings)
    qtbot.addWidget(restored)
    assert restored.simultaneous_io_spin.value() == 3
    assert restored.auto_scan_visible_checkbox.isChecked()
    assert dialog.settings.value(AUTO_SCAN_VISIBLE_SETTING, type=bool)
    assert read_io_concurrency(dialog.settings) == 3
    restored.reset_settings()
    assert restored.simultaneous_io_spin.value() == 1
    assert not restored.auto_scan_visible_checkbox.isChecked()


@pytest.mark.parametrize("value, expected", [(None, 1), ("invalid", 1), (0, 1), (-2, 1), (1000, 32)])
def test_saved_concurrency_is_bounded(tmp_path: Path, value: object, expected: int) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    if value is not None:
        settings.setValue(SIMULTANEOUS_IO_SETTING, value)
    assert read_io_concurrency(settings) == expected


def test_shared_limit_defaults_safely_when_only_legacy_limits_exist(
    qtbot: QtBot, tmp_path: Path,
) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("simultaneous_folder_scans", 4)
    settings.setValue("simultaneous_folder_loads", 3)
    assert read_io_concurrency(settings) == 1
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)
    assert dialog.simultaneous_io_spin.value() == 1
    dialog.simultaneous_io_spin.setValue(2)
    dialog.save_settings()
    assert read_io_concurrency(settings) == 2
    assert not settings.contains("simultaneous_folder_scans")
    assert not settings.contains("simultaneous_folder_loads")
