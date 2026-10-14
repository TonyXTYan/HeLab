# FILE: helab/views/test_settingsDialog.py
import pytest
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QTreeWidget, QWidget
from pytestqt.qtbot import QtBot

from helab.resources.icons import StatusIcons, ToolIcons, PercentageIcon, IconsInitUtil
from helab.views.DebugIconsWindow import ACTIVITY, DEPRECATED, DebugIconsWindow



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
    assert len(debug_icons_window.findChildren(QTreeWidget)) == 5
    assert debug_icons_window.status_list.isVisible()
    assert debug_icons_window.activity_list.isVisible()
    assert debug_icons_window.tool_list.isVisible()
    assert debug_icons_window.deprecated_list.isHidden()
    assert debug_icons_window.percentage_list.isHidden()


def test_status_list_population(debug_icons_window: DebugIconsWindow) -> None:
    # 'loading' (ICON_LOADING) and 'paused' (ICON_PAUSED) are listed under Deprecated instead,
    # with their older-status variants.
    assert debug_icons_window.status_list.topLevelItemCount() == (
        len({**StatusIcons.ICONS_STATUS, **StatusIcons.ICONS_EXTRA}) + len(StatusIcons.ICONS_STATUS_OLDER) - 4)
    names = [item.text(0) for row in range(debug_icons_window.status_list.topLevelItemCount())
             if (item := debug_icons_window.status_list.topLevelItem(row)) is not None]
    for name in ("loading", "paused"):
        assert name not in names and f"{name} (older status cache)" not in names
    assert "load_paused" in names and "load_queued" in names


def test_activity_and_deprecated_groups(debug_icons_window: DebugIconsWindow) -> None:
    activity = debug_icons_window.activity_list
    assert activity.topLevelItemCount() == len(ACTIVITY)
    for row in range(activity.topLevelItemCount()):
        item = activity.topLevelItem(row)
        assert item is not None and not item.icon(0).isNull() and item.toolTip(0)
    deprecated = debug_icons_window.deprecated_list
    assert deprecated.topLevelItemCount() == len(DEPRECATED)
    for row, (name, attribute) in enumerate((("loading", "ICON_LOADING"), ("paused", "ICON_PAUSED"))):
        item = deprecated.topLevelItem(row)
        assert item is not None and (item.text(0), item.text(1)) == (name, attribute)
        assert item.icon(0).cacheKey() == getattr(StatusIcons, attribute).cacheKey()


def test_scan_failure_option_b_is_in_status_group(debug_icons_window: DebugIconsWindow) -> None:
    view = debug_icons_window.status_list
    items = [view.topLevelItem(row) for row in range(view.topLevelItemCount())]
    item = next(item for item in items if item is not None and item.text(0) == "scan_failed")
    assert item is not None and item.text(1) == "ICON_SCAN_FAILED"
    assert not item.icon(0).isNull()
    assert "Magnifying glass + exclamation mark" in item.toolTip(0)
    assert "retry manually" in item.toolTip(1)


def test_tool_list_population(debug_icons_window: DebugIconsWindow) -> None:
    expected_count = sum(1 for attr in dir(ToolIcons) if attr.startswith('ICON_') and isinstance(getattr(ToolIcons, attr), QIcon))
    assert debug_icons_window.tool_list.topLevelItemCount() == expected_count


def test_percentage_list_population(debug_icons_window: DebugIconsWindow) -> None:
    assert debug_icons_window.percentage_list.topLevelItemCount() == PercentageIcon._DIVS_COARSE + 1


def test_all_icon_groups_have_same_row_height(debug_icons_window: DebugIconsWindow) -> None:
    debug_icons_window.percentage_group.toggle.click()
    debug_icons_window.deprecated_group.toggle.click()
    heights: set[int] = set()
    views = (debug_icons_window.status_list, debug_icons_window.activity_list, debug_icons_window.tool_list,
             debug_icons_window.deprecated_list, debug_icons_window.percentage_list)
    for icons in views:
        for row in range(icons.topLevelItemCount()):
            item = icons.topLevelItem(row)
            assert item is not None
            heights.add(icons.visualItemRect(item).height())
    assert len(heights) == 1
    assert next(iter(heights)) > 0
    assert len({view.columnWidth(0) for view in views}) == 1


def test_group_headings_toggle_each_view(debug_icons_window: DebugIconsWindow) -> None:
    for group in (debug_icons_window.status_group, debug_icons_window.activity_group, debug_icons_window.tool_group,
                  debug_icons_window.deprecated_group, debug_icons_window.percentage_group):
        expanded = group.toggle.isChecked()
        group.toggle.click()
        assert group.icon_list.isHidden() is expanded
        group.toggle.click()
        assert group.icon_list.isVisible() is expanded
