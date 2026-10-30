"""The Debug menu's items for a test runner (roadmaps/smoke-automation.md, items 1 and 2): run a
plot, pick the script group, show and close a plot tab, open each Settings tab, and save a window's
screenshot. Each item does what its control does; submenus are filled as they show."""
from __future__ import annotations

import gc
import os
import time
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Iterator

import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before any QApplication: the main window)
from PyQt6.QtGui import QAction, QImage
from PyQt6.QtWidgets import QMenu, QWidget
from pytestqt.qtbot import QtBot

from helab.views.FolderExplorer import FolderExplorer
from helab.views.HelabMainWindow import HelabMainWindow
from helab.views.SettingsDialog import SettingsDialog

# Folders here have no data root: RAM only, so no disk cache or result save is left for a quit to
# wait for when a test ends (a quit waiting on one timed out once on Windows CI: handoff A~5).
# Nothing here checks caching.
pytestmark = pytest.mark.no_auto_data_root


def run_folder(root: Path, shots: int = 3) -> Path:
    """A synthetic TXY folder, settled (modified a minute ago)."""
    run = root / "run"
    run.mkdir()
    old = time.time() - 60
    for shot in range(1, shots + 1):
        path = run / f"d_txy_forc{shot}.txt"
        path.write_text("".join(f"{0.1 + i * 1e-3:.6f},{(i % 7) * 1e-3:.6f},{(i % 5) * 1e-3:.6f}\n"
                                for i in range(300)))
        os.utime(path, (old, old))
    return run


@pytest.fixture
def window(qtbot: QtBot) -> Iterator[HelabMainWindow]:
    made = HelabMainWindow()
    qtbot.addWidget(made)
    made.show()
    qtbot.waitUntil(lambda: isinstance(made.tab_widget.currentWidget(), FolderExplorer), timeout=10_000)
    yield made
    made.close()
    try:
        qtbot.waitUntil(lambda: made._closing, timeout=30_000)
    except Exception as error:  # Name what quitting still waited for (a Windows CI rerun, handoff A~5).
        from helab.utils.folder_cache import get_folder_cache
        from helab.utils.io_service import get_io_service
        raise AssertionError(f"Quitting still waits for {get_folder_cache(get_io_service()).quit_entries()}") from error


def load(window: HelabMainWindow, qtbot: QtBot, run: Path) -> None:
    window.add_new_folder_explorer_tab(target_path=str(run))
    explorer = window.tab_widget.currentWidget()
    assert isinstance(explorer, FolderExplorer)
    qtbot.waitUntil(lambda: explorer.displayed_dataset is not None
                    and explorer.displayed_dataset.path == str(run), timeout=30_000)


def submenu(window: HelabMainWindow, title: str) -> QMenu:
    """Debug › ``title``, filled as showing it fills it."""
    debug = next(action.menu() for action in window.menu_bar.actions() if action.text() == "Debug")
    assert isinstance(debug, QMenu)
    found = next(action.menu() for action in debug.actions() if action.text() == title)
    assert isinstance(found, QMenu)
    found.aboutToShow.emit()
    return found


def items(menu: QMenu) -> dict[str, QAction]:
    return {action.text(): action for action in menu.actions() if not action.isSeparator()}


def plot(window: HelabMainWindow, qtbot: QtBot, name: str) -> None:
    scripts = window.panel_right_bottom_script_selector
    before = len(scripts.instances())
    items(submenu(window, "Run Plot"))[f"Plot {name}"].trigger()
    qtbot.waitUntil(lambda: len(scripts.instances()) == before + 1
                    and all(instance.shown is not None for instance in scripts.instances()), timeout=30_000)


def test_run_plot_lists_the_groups_run_buttons_and_runs_one_once_data_is_shown(
        window: HelabMainWindow, qtbot: QtBot, tmp_path: Path) -> None:
    menu = items(submenu(window, "Run Plot"))
    assert "(load a folder's data first)" in menu and not menu["(load a folder's data first)"].isEnabled()
    assert "Plot Counts per shot" in menu and not menu["Plot Counts per shot"].isEnabled()
    load(window, qtbot, run_folder(tmp_path))
    menu = items(submenu(window, "Run Plot"))
    assert "(load a folder's data first)" not in menu and menu["Plot Counts per shot"].isEnabled()
    plot(window, qtbot, "Counts per shot")
    [instance] = window.panel_right_bottom_script_selector.instances()
    assert instance.name == "Counts per shot" and instance.path == str(tmp_path / "run")


def test_script_group_sets_the_group_selector(window: HelabMainWindow) -> None:
    selector = window.panel_right_bottom_script_selector.group_selector
    menu = items(submenu(window, "Script Group"))
    assert list(menu) == [selector.itemText(index) for index in range(selector.count())]
    assert menu[selector.currentText()].isChecked()
    other = next(name for name in menu if name != selector.currentText())
    menu[other].trigger()
    assert selector.currentText() == other
    tree = window.panel_right_bottom_script_selector.tree_widget
    group = tree.topLevelItem(0)
    assert group is not None and group.text(0) == other  # The Scripts panel lists that group now.
    assert items(submenu(window, "Script Group"))[other].isChecked()


def test_show_and_close_plot_tab(window: HelabMainWindow, qtbot: QtBot, tmp_path: Path) -> None:
    for title in ("Show Plot Tab", "Close Plot Tab"):
        assert [action.isEnabled() for action in items(submenu(window, title)).values()] == [False]
    load(window, qtbot, run_folder(tmp_path))
    plot(window, qtbot, "Counts per shot")
    plot(window, qtbot, "T, X, Y histograms")
    first, second = (instance.dock_widget for instance in window.panel_right_bottom_script_selector.instances())
    assert first is not None and second is not None
    settings = window.plots.panel_right_top_plot_settings
    shown = items(submenu(window, "Show Plot Tab"))
    assert list(shown) == [first.windowTitle(), second.windowTitle()] and shown[second.windowTitle()].isChecked()
    shown[first.windowTitle()].trigger()
    assert settings.current_plot() is first
    items(submenu(window, "Close Plot Tab"))[first.windowTitle()].trigger()
    [left] = window.panel_right_bottom_script_selector.instances()
    assert left.dock_widget is second and list(items(submenu(window, "Close Plot Tab"))) == [second.windowTitle()]


def test_settings_tab_opens_settings_at_that_tab(
        window: HelabMainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(SettingsDialog, "exec", lambda self: opened.append(self.tabs.tabText(self.tabs.currentIndex())))
    menu = items(submenu(window, "Settings Tab"))
    assert tuple(menu) == SettingsDialog.TAB_TITLES
    menu["Cache"].trigger()
    menu["Lab parameters"].trigger()
    assert opened == ["Cache", "Lab parameters"]
    dialog = window.settings_dialog
    assert tuple(dialog.tabs.tabText(index) for index in range(dialog.tabs.count())) == SettingsDialog.TAB_TITLES


def test_screenshot_saves_the_front_window_as_a_png(
        window: HelabMainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "shot.png"
    offered: list[str] = []

    def save_dialog(parent: object, caption: str, directory: str, filter: str) -> tuple[str, str]:
        offered.append(directory)
        return str(path), filter

    monkeypatch.setattr("helab.views.HelabMainWindow.QFileDialog.getSaveFileName", save_dialog)
    assert window.screenshot_target() is window
    window.action_screenshot.trigger()
    image = QImage(str(path))
    assert not image.isNull() and image.width() >= window.width()
    folder, name = os.path.split(offered[0])
    assert folder.endswith("screenshots") and name.startswith("helab-") and name.endswith(".png")
    # Cancelled: nothing written.
    monkeypatch.setattr("helab.views.HelabMainWindow.QFileDialog.getSaveFileName", lambda *args: ("", ""))
    assert window.save_window_screenshot(window) == ""


def test_the_screenshot_target_is_the_window_in_front_as_the_menu_opens(
        window: HelabMainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from helab.views.MemoryUsageWindow import MemoryUsageWindow
    tool = MemoryUsageWindow()
    qtbot.addWidget(tool)
    tool.show()
    monkeypatch.setattr("helab.views.HelabMainWindow.QApplication.activeWindow", lambda: tool)
    window._remember_screenshot_target()
    assert window.screenshot_target() is tool
    listed = items(submenu(window, "Save Screenshot of Window"))
    assert window.windowTitle() in listed and tool.windowTitle() in listed
    assert window.save_window_screenshot(tool, str(tmp_path / "tool.png")) == str(tmp_path / "tool.png")
    tool.close()
    assert window.screenshot_target() is window  # (No longer shown.)


def test_dump_state_saves_what_the_window_shows_from_memory(
        window: HelabMainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import json
    from helab.utils.io_service import IOService
    from helab.views.state_dump import SCHEMA
    run = run_folder(tmp_path)
    load(window, qtbot, run)
    plot(window, qtbot, "Counts per shot")

    def no_io(*args: object, **kwargs: object) -> bool:
        raise AssertionError("Dump state submitted I/O")

    monkeypatch.setattr(IOService, "submit", no_io)
    path = tmp_path / "state.json"
    monkeypatch.setattr("helab.views.HelabMainWindow.QFileDialog.getSaveFileName", lambda *args: (str(path), ""))
    window.action_dump_state.trigger()
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["schema"] == SCHEMA and state["pid"] == os.getpid()
    [first, current] = state["folder_tabs"]
    assert not first["current"] and current["current"] and current["selected_path"] == str(run)
    assert current["id"] == "folder_tab_2" and current["shown_data"] == str(run) and current["live"] is None
    explorer = window.tab_widget.currentWidget()
    assert isinstance(explorer, FolderExplorer)
    assert current["summary"]["counts"]["text"] == explorer.folder_summary_label.text()
    assert state["folder_details"]["folder"]["shown"] and state["status_bar"]["activity"]["shown"]
    assert state["plot_count"] == 1
    [shown] = state["plots"]
    assert shown["script"] == "helab.counts_per_shot" and shown["path"] == str(run) and shown["shown_in_settings"]
    assert shown["source"]["text"].startswith("Data source: run") and not shown["released"]
    assert state["script_group"] == window.panel_right_bottom_script_selector.group_selector.currentText()


def test_a_plot_tabs_close_button_closes_that_plot_when_clicked(
        window: HelabMainWindow, qtbot: QtBot, tmp_path: Path) -> None:
    """A mouse click on a plot tab's × closes its plot, also after a full garbage collection with
    nothing holding the bar's wrapper (known-issues: until 0.0.7a1 the × went dead then, its lambda
    emptied by the collector). (A press by accessibility can't reach it: Qt's tab bar doesn't expose
    its close buttons; Debug › Close Plot Tab and the Settings panel's Close plot do it.)"""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QTabBar
    load(window, qtbot, run_folder(tmp_path))
    plot(window, qtbot, "Counts per shot")
    plot(window, qtbot, "T, X, Y histograms")
    first, second = window.panel_right_bottom_script_selector.instances()
    qtbot.waitUntil(lambda: window.plots.middle_mainwindow.findChild(QTabBar, "plot_tabs_1") is not None)
    bar = window.plots.middle_mainwindow.findChild(QTabBar, "plot_tabs_1")
    assert isinstance(bar, QTabBar)
    button = bar.findChild(QWidget, f"close_plot_tab_{first.instance_id}")
    del bar
    gc.collect()
    assert button is not None and first.dock_widget is not None
    assert button.accessibleName() == f"Close plot tab: {first.dock_widget.windowTitle()}"
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)  # type: ignore[no-untyped-call]
    qtbot.waitUntil(lambda: first.is_closed)
    assert window.panel_right_bottom_script_selector.instances() == [second]


def test_show_and_close_folder_tab(window: HelabMainWindow, qtbot: QtBot, tmp_path: Path) -> None:
    """Debug › Show Folder Tab and Close Folder Tab (Q~3): each folder tab by its title, with IDs from
    the tab's number; showing one is a click on its tab, closing one its ×. The folder has no data
    root, so nothing of it is saved: the tab's closing leaves nothing for quitting to wait for."""
    from helab.utils.folder_cache import get_folder_cache
    from helab.utils.io_service import get_io_service
    first = window.tab_widget.widget(0)
    run = run_folder(tmp_path)
    load(window, qtbot, run)
    second = window.tab_widget.currentWidget()
    assert isinstance(first, FolderExplorer) and isinstance(second, FolderExplorer)
    shown = submenu(window, "Show Folder Tab")
    titles = [window.tab_widget.tabText(index) for index in range(2)]
    assert list(items(shown)) == titles and items(shown)[titles[1]].isChecked()
    assert [action.objectName() for action in shown.actions()] == [
        f"debug_show_{first.objectName()}", f"debug_show_{second.objectName()}"]
    items(shown)[titles[0]].trigger()
    assert window.tab_widget.currentWidget() is first
    window.tab_widget.tabBar().moveTab(0, 1)  # type: ignore[union-attr]  # (Found where it is now.)
    closing = submenu(window, "Close Folder Tab")
    assert [action.objectName() for action in closing.actions()] == [
        f"debug_close_{second.objectName()}", f"debug_close_{first.objectName()}"]
    items(closing)[titles[1]].trigger()
    assert window.tab_widget.count() == 1 and window.tab_widget.widget(0) is first and second.closed
    assert list(items(submenu(window, "Close Folder Tab"))) == [titles[0]]
    cache = get_folder_cache(get_io_service())
    assert not [entry for entry in cache.quit_entries() if entry.path == str(run)]
    try:  # (Nothing left for the teardown's quit to wait for: Wren's round 5, R5-1.)
        qtbot.waitUntil(lambda: not cache.quit_saves(), timeout=60_000)
    except Exception as error:
        raise AssertionError(f"Still saving: {cache.quit_entries()}") from error


def test_screenshot_to_the_temp_folder_asks_nothing(
        window: HelabMainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
        tmp_path: Path) -> None:
    """Debug › Save Window Screenshot to Temp Folder (Q~1): no dialog; ``helab-<window>-<time>.png`` in the
    temp folder's screenshots, a second one in the same second ``-2``; logged and in the status bar."""
    import logging
    from helab.views import HelabMainWindow as module

    def no_dialog(*args: object) -> tuple[str, str]:
        raise AssertionError("A dialog was opened")

    monkeypatch.setattr("helab.views.HelabMainWindow.QFileDialog.getSaveFileName", no_dialog)
    class Frozen(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> "Frozen":
            return cls(2026, 10, 30, 9, 15, 0)

    monkeypatch.setattr(module, "datetime", Frozen)
    monkeypatch.setattr(module, "DIR_TEMPS", str(tmp_path))  # The test's own: a rerun finds no file of its first run.
    with caplog.at_level(logging.INFO):
        window.action_screenshot_temp.trigger()
        second = window.save_window_screenshot_to_temp()
    from helab.utils.accessible import id_part
    folder = os.path.join(str(tmp_path), "screenshots")
    first = os.path.join(folder, f"helab-{id_part(window.windowTitle()).lower()[:40]}-20261030-091500.png")
    assert os.path.isfile(first) and second == first[:-4] + "-2.png" and os.path.isfile(second)
    assert not QImage(first).isNull() and f"Screenshot saved: {first}" in caplog.text
    assert f"Screenshot saved: {second}" in window.status_bar_message_left.text()


def test_the_debug_menu_has_the_runners_items_and_no_placeholders(window: HelabMainWindow) -> None:
    """Q33.5: "Debug - 6", "Draw a line in debug console" and "Debug - validate tab status" are gone."""
    debug = next(action.menu() for action in window.menu_bar.actions() if action.text() == "Debug")
    assert isinstance(debug, QMenu)
    names = list(items(debug))
    assert not {"Debug - 6", "Draw a line in debug console", "Debug - validate tab status"} & set(names)
    assert {"Run Plot", "Script Group", "Show Plot Tab", "Close Plot Tab", "Settings Tab", "Show all Icons",
            "Show Memory Usage"} <= set(names)
