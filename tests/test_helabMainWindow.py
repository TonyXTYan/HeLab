# tests/test_helabMainWindow.py
import signal
from typing import Generator, Any
from unittest.mock import patch

import pytest
from PyQt6.QtGui import QIcon, QResizeEvent
from pytestqt.qtbot import QtBot
from PyQt6.QtWidgets import QApplication, QMessageBox, QListWidget, QMenu, QWidget
from PyQt6.QtCore import Qt

from helab.resources.icons import StatusIcons, ToolIcons, PercentageIcon
from helab.views.DebugIconsWindow import DebugIconsWindow
from helab.views.FolderExplorer import FolderExplorer
from helab.views.HelabMainWindow import HelabMainWindow
from helab.views.SettingsDialog import SettingsDialog


def test_qtbot_add_widget(qtbot: QtBot) -> None:
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()
    assert widget.isVisible()


@pytest.fixture
def main_window(qtbot: QtBot) -> Any:
    window = HelabMainWindow()
    assert (isinstance(window, QWidget))
    qtbot.addWidget(window)
    window.show()
    # return window
    yield window
    try:
        window.close()
    except Exception:
        pass

@pytest.fixture(autouse=True)
def disable_warnings() -> Any:
    with patch.object(QMessageBox, 'warning'):
        yield


def test_initial_state_main_window(main_window: HelabMainWindow) -> None:
    assert main_window.width() == main_window.DEFAULT_WIDTH
    assert main_window.height() == main_window.DEFAULT_HEIGHT
    assert main_window.status_bar is not None


def test_toggle_left_panel(main_window: HelabMainWindow) -> None:
    initial_sizes = main_window.splitter.sizes()
    main_window.toggle_left_panel(False)
    collapsed_sizes = main_window.splitter.sizes()
    assert collapsed_sizes[0] == 0
    main_window.toggle_left_panel(True)
    expanded_sizes = main_window.splitter.sizes()
    assert expanded_sizes[0] != 0
    assert expanded_sizes[0] == main_window.left_panel_width or expanded_sizes[0] > 0


def test_toggle_right_panel(main_window: HelabMainWindow) -> None:
    initial_sizes = main_window.splitter.sizes()
    main_window.toggle_right_panel(False)
    collapsed_sizes = main_window.splitter.sizes()
    assert collapsed_sizes[2] == 0
    main_window.toggle_right_panel(True)
    expanded_sizes = main_window.splitter.sizes()
    assert expanded_sizes[2] != 0
    assert expanded_sizes[2] == main_window.right_panel_width or expanded_sizes[2] > 0


def test_add_new_folder_explorer_tab(main_window: HelabMainWindow) -> None:
    initial_count = main_window.tab_widget.count()
    main_window.add_new_folder_explorer_tab()
    assert main_window.tab_widget.count() == initial_count + 1


def test_on_back_button_clicked(main_window: HelabMainWindow) -> None:
    main_window.on_back_button_clicked()
    assert True


def test_close_event_main_window(main_window: HelabMainWindow, qtbot: QtBot) -> None:
    QApplication.processEvents()
    qtbot.wait(1000)
    main_window.close()
    qtbot.wait(1000)
    assert not main_window.isVisible()

# def test_create_menus_main_window(main_window: HelabMainWindow) -> None:
#     menubar = main_window.menu_bar
#     assert menubar is not None
#
#     file_menu = menubar.findChild(QMenu, 'File')
#     assert file_menu is not None
#     assert file_menu.title() == 'File'
#     assert file_menu.actions()[0].text().strip() == 'Open'
#     assert any(action.text().strip().startswith('Open Drives') for action in file_menu.actions())
#
#     view_menu = menubar.findChild(QMenu, 'View')
#     assert view_menu is not None
#     assert view_menu.title() == 'View'
#     view_actions = view_menu.actions()
#     expected_view_actions = [
#         'Toggle Left Toolbar',
#         'Toggle Right Toolbar',
#         'Toggle Status Bar',
#         'Toggle Thread Status Auto Pop-up',
#         'Toggle Auto Load to RAM',
#         'Toggle Left Panel',
#         'Toggle Right Panel'
#     ]
#     for expected_action in expected_view_actions:
#         assert any(action.text().strip() == expected_action for action in view_actions)
#
#     debug_menu = menubar.findChild(QMenu, 'Debug')
#     assert debug_menu is not None
#     assert debug_menu.title() == 'Debug'
#     debug_actions = debug_menu.actions()
#     expected_debug_actions = [
#         'Clear Status Cache',
#         'Draw a line in debug console',
#         'Show all Icons',
#         'Show Memory Usage',
#         'Debug 3',
#         'Debug 4',
#         'gc.collect()'
#     ]
#     for expected_action in expected_debug_actions:
#         assert any(action.text().strip() == expected_action for action in debug_actions)


# def test_show_settings_dialog(main_window: HelabMainWindow, qtbot: QtBot) -> None:
#     with patch.object(main_window, 'show_settings_dialog') as mock_show_settings:
#         settings_action = main_window.menu_bar.findChild(QMenu, 'File').actions()[-2]
#         qtbot.mouseClick(settings_action, Qt.MouseButton.LeftButton)
#         mock_show_settings.assert_called_once()


# def test_toggle_auto_load_ram(main_window: HelabMainWindow, qtbot: QtBot) -> None:
#     current_folder_explorer = main_window.tab_widget.currentWidget()
#     if isinstance(current_folder_explorer, FolderExplorer):
#         original_state = current_folder_explorer.auto_load_ram
#         main_window.toggle_auto_load_ram()
#         assert current_folder_explorer.auto_load_ram == (not original_state)
#     else:
#         pytest.skip("Current widget is not FolderExplorer")


# def test_on_live_button_clicked_start(main_window: HelabMainWindow, qtbot: QtBot) -> None:
#     main_window.action_tab_live_checked = False
#     with patch.object(main_window, 'toggle_left_panel') as mock_toggle:
#         qtbot.mouseClick(main_window.action_tab_live, Qt.MouseButton.LeftButton)
#         assert main_window.action_tab_live_checked is True
#         mock_toggle.assert_called_once_with(False)
#         assert main_window.tab_widget.isEnabled() is False
#         assert not main_window.action_tab_refresh.isEnabled()
#         assert not main_window.action_tab_new.isEnabled()
#         assert not main_window.action_tab_rescan.isEnabled()
#         assert not main_window.action_tab_folder_up.isEnabled()


# def test_on_live_button_clicked_stop(main_window: HelabMainWindow, qtbot: QtBot) -> None:
#     main_window.action_tab_live_checked = True
#     with patch.object(main_window, 'toggle_left_panel') as mock_toggle:
#         qtbot.mouseClick(main_window.action_tab_live, Qt.MouseButton.LeftButton)
#         assert main_window.action_tab_live_checked is False
#         mock_toggle.assert_called_once_with(main_window.action_tab_live_was_left_panel_open_before_clicking_live)
#         assert main_window.tab_widget.isEnabled() is True
#         assert main_window.action_tab_refresh.isEnabled()
#         assert main_window.action_tab_new.isEnabled()
#         assert main_window.action_tab_rescan.isEnabled()
#         assert main_window.action_tab_folder_up.isEnabled()


# def test_resize_event_main_window(main_window: HelabMainWindow, qtbot: QtBot) -> None:
#     with patch.object(main_window, 'setUpdatesEnabled') as mock_set_updates:
#         resize_event = QResizeEvent(main_window.size(), main_window.size())
#         main_window.resizeEvent(resize_event)
#         mock_set_updates.assert_any_call(False)
#         mock_set_updates.assert_any_call(True)


def test_handle_exit_main_window(main_window: HelabMainWindow, qtbot: QtBot) -> None:
    with patch.object(main_window, 'close') as mock_close:
        main_window.handle_exit(signal.SIGINT, None)
        mock_close.assert_called_once()

