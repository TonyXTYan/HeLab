import pytest
from PyQt6.QtWidgets import QApplication
from helab.views.settingsDialog import SettingsDialog

@pytest.fixture
def app(qapp):
    """Create QApplication fixture"""
    return qapp

@pytest.fixture
def settings_dialog(app):
    """Create SettingsDialog fixture"""
    dialog = SettingsDialog()
    return dialog

def test_settings_dialog_creation(qtbot, settings_dialog):
    """Test basic dialog creation and properties"""
    # Add widget to qtbot
    qtbot.addWidget(settings_dialog)
    
    # Verify window properties
    assert settings_dialog.windowTitle() == "Settings"
    assert settings_dialog.minimumSize().width() == 800
    assert settings_dialog.minimumSize().height() == 500

def test_settings_dialog_tab_widget(qtbot, settings_dialog):
    """Test tab widget setup"""
    qtbot.addWidget(settings_dialog)
    
    # Verify tab widget exists
    assert settings_dialog.tabs is not None
    
    # Verify default tabs
    expected_tabs = ["General", "Scripts", "Cache"] 
    assert [settings_dialog.tabs.tabText(i) for i in range(settings_dialog.tabs.count())] == expected_tabs

def test_cache_tab_controls(qtbot, settings_dialog):
    """Test cache tab controls"""
    qtbot.addWidget(settings_dialog)
    
    # Verify cache tab widgets
    assert settings_dialog.cache_tab is not None
    assert settings_dialog.cache_layout is not None
    assert settings_dialog.cache_widgets is not None
    assert isinstance(settings_dialog.cache_params_ui, dict)

def test_settings_dialog_buttons(qtbot, settings_dialog):
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