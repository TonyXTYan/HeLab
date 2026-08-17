# FILE: helab/views/test_settingsDialog.py
from typing import Any

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QListWidget, QWidget
from pytestqt.qtbot import QtBot

from helab.resources.icons import StatusIcons, ToolIcons, PercentageIcon, IconsInitUtil
from helab.views.DebugIconsWindow import DebugIconsWindow
from helab.views.SettingsDialog import SettingsDialog



@pytest.fixture
def debug_icons_window(qtbot: QtBot) -> DebugIconsWindow:
    IconsInitUtil.initialise_icons()
    window = DebugIconsWindow()
    assert isinstance(window, QWidget)
    qtbot.addWidget(window)
    window.show()
    return window


def test_initial_state_debug_icons_window(debug_icons_window: DebugIconsWindow) -> None:
    assert debug_icons_window.windowTitle() == "Debug Icons"
    assert debug_icons_window.width() == 600
    assert debug_icons_window.height() == 800


def test_status_list_population(debug_icons_window: DebugIconsWindow) -> None:
    # status_list = debug_icons_window.findChild(QListWidget, "status_list")
    status_list = debug_icons_window.status_list
    assert status_list is not None
    # assert status_list.count() ==  len(set(StatusIcons.ICONS_STATUS.values()).union(set(StatusIcons.ICONS_EXTRA.values())))
    # assert status_list.count() == len(StatusIcons.ICONS_STATUS) + len(StatusIcons.ICONS_EXTRA)
    assert status_list.count() == len({**StatusIcons.ICONS_STATUS, **StatusIcons.ICONS_EXTRA}.items())


def test_tool_list_population(debug_icons_window: DebugIconsWindow) -> None:
    # tool_lists = debug_icons_window.findChildren(QListWidget, "tool_list")
    tool_lists = debug_icons_window.tool_list
    # tool_list = tool_lists[1] if len(tool_lists) > 1 else None
    # tool_list = tool_lists if isinstance(tool_lists, QListWidget) else tool_lists[1] if len(tool_lists) > 1 else None
    tool_list = tool_lists if isinstance(tool_lists, QListWidget) else None
    assert tool_list is not None
    expected_count = sum(1 for attr in dir(ToolIcons) if attr.startswith('ICON_') and isinstance(getattr(ToolIcons, attr), QIcon))
    assert tool_list.count() == expected_count


def test_percentage_list_population(debug_icons_window: DebugIconsWindow) -> None:
    # percentage_lists = debug_icons_window.findChildren(QListWidget, "percentage_list")
    percentage_lists = debug_icons_window.percentage_list
    # percentage_list = percentage_lists[2] if len(percentage_lists) > 2 else None
    # percentage_list = percentage_lists if isinstance(percentage_lists, QListWidget) else percentage_lists[2] if len(percentage_lists) > 2 else None
    percentage_list = percentage_lists if isinstance(percentage_lists, QListWidget) else None
    assert percentage_list is not None
    assert percentage_list.count() == PercentageIcon._DIVS_COARSE + 1


