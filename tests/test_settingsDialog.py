import pytest
from pathlib import Path
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from helab.views.SettingsDialog import SettingsDialog
from helab.utils.folder_cache import get_folder_cache
from helab.utils.io_service import get_io_service
from helab.utils.constants import (
    AUTO_SCAN_VISIBLE_SETTING, DISK_BUDGET_SETTING, SIMULTANEOUS_IO_SETTING, read_disk_budget,
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
    expected_tabs = ["General", "Lab parameters", "TXY converter", "Scripts", "Cache", "Data roots"]
    assert [settings_dialog.tabs.tabText(i) for i in range(settings_dialog.tabs.count())] == expected_tabs

def test_cache_tab_controls(qtbot: QtBot, settings_dialog: SettingsDialog) -> None:
    """Test cache tab controls"""
    qtbot.addWidget(settings_dialog)
    
    # Without the app's folder cache (no helper to ask), it names the folder and
    # leaves every action disabled; tests/test_cache_tab.py covers the working tab.
    tab = settings_dialog.cache_tab
    assert tab.location_label.text().endswith("store-v3")
    assert tab.inventory is None and not tab.enabled
    assert all(not button.isEnabled() for button in (*tab.kind_buttons.values(), tab.clear_all_button,
                                                     tab.purge_datasets_button, tab.purge_records_button))

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
    assert settings_dialog.reset_button.text() == "Reset all settings…"


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
    asked: list[str] = []

    def decline(title: str, text: str, verb: str) -> bool:
        asked.append(title)
        return False
    restored.cache_tab.confirm = decline
    restored.reset_settings()  # Declined: nothing changes.
    assert asked == ["Reset all settings?"] and restored.simultaneous_io_spin.value() == 3
    restored.cache_tab.confirm = lambda title, text, verb: True
    restored.reset_settings()
    assert restored.simultaneous_io_spin.value() == 1
    assert not restored.auto_scan_visible_checkbox.isChecked()


def test_declining_to_lower_the_disk_budget_saves_nothing(qtbot: QtBot, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    dialog = SettingsDialog(settings=settings, cache=get_folder_cache(get_io_service()))
    qtbot.addWidget(dialog)
    asked: list[str] = []

    def decline(title: str, text: str, verb: str) -> bool:
        asked.append(title)
        return False
    dialog.cache_tab.confirm = decline
    dialog.simultaneous_io_spin.setValue(7)
    dialog.cache_tab.disk_budget.setValue(1.0)  # Below use: the inventory is still unknown.
    dialog.save_settings()
    assert asked == ["Lower the disk cache budget?"] and dialog.tabs.currentWidget() is dialog.cache_tab
    assert read_io_concurrency(settings) == 1 and not settings.contains(DISK_BUDGET_SETTING)
    dialog.reject()


def test_without_a_disk_cache_the_budget_is_just_saved(qtbot: QtBot, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    dialog = SettingsDialog(settings=settings)  # No cache: no store to tell.
    qtbot.addWidget(dialog)
    dialog.cache_tab.disk_budget.setValue(12.0)
    dialog.save_settings()
    assert read_disk_budget(settings) == 12 * 10**9


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


def test_the_placeholder_settings_are_gone_and_their_saved_values_removed(
    qtbot: QtBot, tmp_path: Path,
) -> None:
    """Settings → General had two placeholders ("Enable feature X", "Example Text"); a value an older
    HeLab saved for them is removed when settings are saved (R-13)."""
    from PyQt6.QtWidgets import QCheckBox, QLineEdit
    from helab.utils.settings_defaults import RETIRED
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("example_checkbox", True)
    settings.setValue("example_text", "hello")
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)
    assert not any(box.text() == "Enable feature X" for box in dialog.general_tab.findChildren(QCheckBox))
    assert not any(edit.placeholderText() == "Enter some text" for edit in dialog.general_tab.findChildren(QLineEdit))
    assert {"example_checkbox", "example_text"} <= set(RETIRED)
    dialog.save_settings()
    assert not settings.contains("example_checkbox") and not settings.contains("example_text")


def test_the_temp_folder_row_is_worded_like_the_cache_folders(qtbot: QtBot, settings_dialog: SettingsDialog) -> None:
    """A33.3: prose, not the constant's name ("DIR_TEMPS:")."""
    from PyQt6.QtWidgets import QLabel
    qtbot.addWidget(settings_dialog)
    labels = [label.text() for label in settings_dialog.dir_scroll_content.findChildren(QLabel)]
    assert "Temp folder (a change applies at the next start):" in labels
    assert "Cache folder (moving it keeps its contents):" in labels
    assert not any("DIR_" in text for text in labels)
