"""Q33.2: the main window's split gives the plots the room (folders ~380 px, settings ~320 px), keeps the
user's widths across restarts (``main_window_split``), and a plot opening never narrows the folder panel."""
from __future__ import annotations

from pathlib import Path
import sys
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


def wide_parts(window: HelabMainWindow) -> str:
    """The settings panel's widgets whose least width passes 320 px, for a failure's message: what holds it
    wider on this OS's fonts (Windows CI's held it at ~548 px before its least width was set)."""
    from PyQt6.QtWidgets import QWidget
    rows = [f"{widget.minimumSizeHint().width()} {type(widget).__name__} {widget.objectName()}"
            for widget in window.right_panel.findChildren(QWidget)
            if widget.isVisibleTo(window.right_panel) and widget.minimumSizeHint().width() > 320]
    return "; ".join(rows) or "none over 320 px"


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
    assert left == 380 and right == 320, wide_parts(window)
    assert middle == window.splitter.width() - left - right - 2 * window.splitter.handleWidth()
    load(window, qtbot, run_folder(tmp_path))
    plot(window, qtbot, "Counts per shot")
    plot(window, qtbot, "T, X, Y histograms")
    qtbot.wait(50)
    after = window.splitter.sizes()
    # The folder panel keeps its width, and no plot setting widens the settings panel past ~320 px (Q33.2).
    assert after == [left, middle, right], wide_parts(window)


def test_a_settings_row_wider_than_the_panel_doesnt_widen_it(window: HelabMainWindow, qtbot: QtBot) -> None:
    """Whatever a row needs in the system's font (wider fonts on Windows CI held the panel at ~548 px), the
    panel keeps its width: its least width is set (MIN_SETTINGS_WIDTH), so the row is cut, not the folders."""
    from PyQt6.QtWidgets import QPushButton
    sizes = window.splitter.sizes()
    wide = QPushButton("x" * 200)  # Far wider than 320 px in any font.
    wide.setMinimumWidth(wide.sizeHint().width())
    window.panel_right_bottom_script_selector.layout().addWidget(wide)  # type: ignore[union-attr]
    qtbot.wait(20)
    assert wide.minimumSizeHint().width() > 320 and window.splitter.sizes() == sizes


def test_the_default_split_holds_in_a_wider_font(qtbot: QtBot, tmp_path: Path) -> None:
    """As on Windows CI, where the system's font made the panel's rows ~1.8 times as wide: twice the font."""
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    font = app.font()
    wider = QFont(font)
    wider.setPointSizeF(font.pointSizeF() * 2)
    app.setFont(wider)
    try:
        window = opened(qtbot)
        try:
            load(window, qtbot, run_folder(tmp_path))
            plot(window, qtbot, "Counts per shot")
            qtbot.wait(20)
            # The settings panel never takes its contents' width (984 px on Windows CI with this font): at most
            # its 320 px. (Both panels may give way to the plots' own least width, which a doubled font widens: on
            # Windows CI's narrower window they did, to 214 and 154 px.)
            left, _, right = window.splitter.sizes()
            assert right <= 320, wide_parts(window)
        finally:
            closed(qtbot, window)
    finally:
        app.setFont(font)


@pytest.mark.skipif(sys.platform != "darwin", reason=(
    "250 px is measured at macOS's default font; the least width is fixed, not the contents' (review R2-2), and "
    "CI's fonts are wider elsewhere: on Windows CI Load Scripts... alone is 188 px, on Ubuntu Delete... runs 3 px over"))
def test_the_settings_panel_goes_no_narrower_than_its_controls_need(window: HelabMainWindow, qtbot: QtBot,
                                                                     tmp_path: Path) -> None:
    """Review R2-2: dragged as narrow as it goes, the settings panel stops at MIN_SETTINGS_WIDTH (250 px), where
    none of its controls is cut at this font, a plot open: none runs past the panel's edge, and no button is
    narrower than its text. (The plot's settings tree scrolls sideways: its rows aren't counted.)"""
    from PyQt6.QtWidgets import QAbstractButton, QAbstractScrollArea, QComboBox, QWidget
    load(window, qtbot, run_folder(tmp_path))
    plot(window, qtbot, "Counts per shot")
    left, middle, right = window.splitter.sizes()
    window.splitter.setSizes([left, middle + right - 10, 10])
    qtbot.wait(20)
    assert window.splitter.sizes()[2] == HelabMainWindow.MIN_SETTINGS_WIDTH == 250
    panel = window.right_panel

    def scrolls(control: QWidget) -> bool:
        parent = control.parentWidget()
        while parent is not None and parent is not panel:
            if isinstance(parent, QAbstractScrollArea):
                return True
            parent = parent.parentWidget()
        return False

    def cut(control: QAbstractButton | QComboBox) -> bool:
        past = control.mapTo(panel, control.rect().topRight()).x() >= panel.width()
        text = control.fontMetrics().horizontalAdvance(control.text()) if isinstance(control, QAbstractButton) else 0
        return past or control.width() < text

    controls: list[QAbstractButton | QComboBox] = [*panel.findChildren(QAbstractButton), *panel.findChildren(QComboBox)]
    assert [f"{type(control).__name__} {control.objectName()} (right edge "
            f"{control.mapTo(panel, control.rect().topRight()).x()} of {panel.width()}, width {control.width()})"
            for control in controls if control.isVisibleTo(panel) and not scrolls(control) and cut(control)] == []


def test_a_wider_window_widens_the_plots_only(window: HelabMainWindow, qtbot: QtBot) -> None:
    left, middle, right = window.splitter.sizes()
    window.resize(window.width() + 200, window.height())
    qtbot.waitUntil(lambda: window.splitter.sizes()[1] == middle + 200)
    assert window.splitter.sizes() == [left, middle + 200, right]


def test_the_users_widths_last_to_the_next_start(qtbot: QtBot) -> None:
    first = opened(qtbot)
    total = sum(first.splitter.sizes())
    first.splitter.setSizes([420, total - 780, 360])  # (What fits Windows CI's narrower window too.)
    closed(qtbot, first)
    assert read_setting(app_settings(), MAIN_SPLIT_SETTING) == "420,360", wide_parts(first)
    second = opened(qtbot)
    try:
        assert second.splitter.sizes()[0] == 420 and second.splitter.sizes()[2] == 360, wide_parts(second)
    finally:
        closed(qtbot, second)


def test_a_collapsed_panel_saves_the_width_it_had(window: HelabMainWindow, qtbot: QtBot) -> None:
    total = sum(window.splitter.sizes())
    window.splitter.setSizes([450, total - 800, 350])
    window._live_panel(True)  # Live on collapses the folder panel (Q18.3).
    assert window.splitter.sizes()[0] == 0
    parts = wide_parts(window)
    closed(qtbot, window)
    assert read_setting(app_settings(), MAIN_SPLIT_SETTING) == "450,350", parts


@pytest.mark.parametrize("saved, expected", [
    ("500,400", (500, 400)), ("", (380, 320)), ("500", (380, 320)), ("a,b", (380, 320)),
    ("79,400", (380, 320)), ("500,4001", (380, 320)), ("80,4000", (80, 4000)), ("80,249", (380, 320)),
    ("80,250", (80, 250)),
])
def test_read_split_takes_two_widths_in_range_else_the_default(tmp_path: Path, saved: str,
                                                               expected: tuple[int, int]) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    if saved:
        settings.setValue(MAIN_SPLIT_SETTING, saved)
    assert HelabMainWindow.read_split(settings) == expected
