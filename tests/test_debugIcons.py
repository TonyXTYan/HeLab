# FILE: helab/views/test_settingsDialog.py
import pytest
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QTreeWidget, QWidget
from pytestqt.qtbot import QtBot

from helab.resources.icons import StatusIcons, ToolIcons, PercentageIcon, IconsInitUtil
from helab.views.DebugIconsWindow import DebugIconsWindow



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
    assert len(debug_icons_window.findChildren(QTreeWidget)) == 3
    assert debug_icons_window.status_list.isVisible()
    assert debug_icons_window.tool_list.isVisible()
    assert debug_icons_window.percentage_list.isHidden()


def test_status_list_population(debug_icons_window: DebugIconsWindow) -> None:
    assert debug_icons_window.status_list.topLevelItemCount() == len({**StatusIcons.ICONS_STATUS, **StatusIcons.ICONS_EXTRA})


def test_tool_list_population(debug_icons_window: DebugIconsWindow) -> None:
    expected_count = sum(1 for attr in dir(ToolIcons) if attr.startswith('ICON_') and isinstance(getattr(ToolIcons, attr), QIcon))
    assert debug_icons_window.tool_list.topLevelItemCount() == expected_count


def test_percentage_list_population(debug_icons_window: DebugIconsWindow) -> None:
    assert debug_icons_window.percentage_list.topLevelItemCount() == PercentageIcon._DIVS_COARSE + 1


def test_all_icon_groups_have_same_row_height(debug_icons_window: DebugIconsWindow) -> None:
    debug_icons_window.percentage_group.toggle.click()
    heights: set[int] = set()
    views = (debug_icons_window.status_list, debug_icons_window.tool_list, debug_icons_window.percentage_list)
    for icons in views:
        for row in range(icons.topLevelItemCount()):
            item = icons.topLevelItem(row)
            assert item is not None
            heights.add(icons.visualItemRect(item).height())
    assert len(heights) == 1
    assert next(iter(heights)) > 0
    assert len({view.columnWidth(0) for view in views}) == 1


def test_group_headings_toggle_each_view(debug_icons_window: DebugIconsWindow) -> None:
    for group in (debug_icons_window.status_group, debug_icons_window.tool_group,
                  debug_icons_window.percentage_group):
        expanded = group.toggle.isChecked()
        group.toggle.click()
        assert group.icon_list.isHidden() is expanded
        group.toggle.click()
        assert group.icon_list.isVisible() is expanded
