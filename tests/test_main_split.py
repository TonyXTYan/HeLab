"""Q33.2: the main window's split gives the plots the room (folders ~380 px, settings ~320 px), keeps the
user's widths across restarts (``main_window_split``), and a plot opening never narrows the folder panel."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before any QApplication: the main window)
from PyQt6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from helab.utils.settings_defaults import MAIN_SPLIT_SETTING, read_setting
from helab.utils.settings_store import app_settings
from helab.views.FolderExplorer import FolderExplorer
from helab.views.HelabMainWindow import HelabMainWindow
from test_debug_runner_menu import load, plot, run_folder

pytestmark = pytest.mark.no_auto_data_root


def opened(qtbot: QtBot) -> HelabMainWindow:
    made = HelabMainWindow()
    qtbot.addWidget(made)
    made.show()
    qtbot.waitUntil(lambda: isinstance(made.tab_widget.currentWidget(), FolderExplorer), timeout=10_000)
    return made


def closed(qtbot: QtBot, window: HelabMainWindow) -> None:
    window.close()
    qtbot.waitUntil(lambda: window._closing, timeout=30_000)


@pytest.fixture
def window(qtbot: QtBot) -> Iterator[HelabMainWindow]:
    made = opened(qtbot)
    yield made
    if not made._closing:
        closed(qtbot, made)


def test_the_default_split_gives_the_plots_the_room_and_a_plot_keeps_it(
        window: HelabMainWindow, qtbot: QtBot, tmp_path: Path) -> None:
    left, middle, right = window.splitter.sizes()
    assert left == 380 and abs(right - 320) <= 20 and middle == window.splitter.width() - left - right - 2 * window.splitter.handleWidth()
    load(window, qtbot, run_folder(tmp_path))
    plot(window, qtbot, "Counts per shot")
    plot(window, qtbot, "T, X, Y histograms")
    qtbot.wait(50)
    after = window.splitter.sizes()
    # The folder panel keeps its width, and no plot setting widens the settings panel past ~320 px (Q33.2).
    assert after[0] == left and abs(after[2] - 320) <= 20 and after[1] >= middle - 20


def test_a_wider_window_widens_the_plots_only(window: HelabMainWindow, qtbot: QtBot) -> None:
    left, middle, right = window.splitter.sizes()
    window.resize(window.width() + 200, window.height())
    qtbot.waitUntil(lambda: window.splitter.sizes()[1] == middle + 200)
    assert window.splitter.sizes() == [left, middle + 200, right]


def test_the_users_widths_last_to_the_next_start(qtbot: QtBot) -> None:
    first = opened(qtbot)
    total = sum(first.splitter.sizes())
    first.splitter.setSizes([500, total - 900, 400])
    closed(qtbot, first)
    assert read_setting(app_settings(), MAIN_SPLIT_SETTING) == "500,400"
    second = opened(qtbot)
    try:
        assert second.splitter.sizes()[0] == 500 and second.splitter.sizes()[2] == 400
    finally:
        closed(qtbot, second)


def test_a_collapsed_panel_saves_the_width_it_had(window: HelabMainWindow, qtbot: QtBot) -> None:
    total = sum(window.splitter.sizes())
    window.splitter.setSizes([450, total - 800, 350])
    window._live_panel(True)  # Live on collapses the folder panel (Q18.3).
    assert window.splitter.sizes()[0] == 0
    closed(qtbot, window)
    assert read_setting(app_settings(), MAIN_SPLIT_SETTING) == "450,350"


@pytest.mark.parametrize("saved, expected", [
    ("500,400", (500, 400)), ("", (380, 320)), ("500", (380, 320)), ("a,b", (380, 320)),
    ("79,400", (380, 320)), ("500,4001", (380, 320)), ("80,4000", (80, 4000)),
])
def test_read_split_takes_two_widths_in_range_else_the_default(tmp_path: Path, saved: str,
                                                               expected: tuple[int, int]) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    if saved:
        settings.setValue(MAIN_SPLIT_SETTING, saved)
    assert HelabMainWindow.read_split(settings) == expected
