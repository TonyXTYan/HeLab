"""Q33.3: a plot floated (not dragged) opens FLOAT_STEP right of and below the plot floated last, at
FLOAT_SIZE, kept on its screen; Q33.4: a floating plot's Dock button puts it back."""
from __future__ import annotations

from typing import cast

import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QApplication, QLineEdit

from helab.views.plots.dock import AnalysisDock
from test_plot_settings_panel import Plots, let_go, plots  # noqa: F401  (the fixtures)


def available(dock: AnalysisDock) -> QRect:
    screen = dock.screen()
    assert screen is not None
    return screen.availableGeometry()


def float_(dock: AnalysisDock, qtbot: QtBot) -> AnalysisDock:
    dock.setFloating(True)
    qtbot.waitUntil(dock.settings.isVisible)
    return dock


@pytest.fixture
def small(monkeypatch: pytest.MonkeyPatch) -> QSize:
    """A float size with room around it on the offscreen screen (800×800)."""
    size = QSize(300, 200)
    monkeypatch.setattr(AnalysisDock, "FLOAT_SIZE", size)
    return size


def test_each_plot_floated_opens_a_step_from_the_last_one(plots: Plots, qtbot: QtBot, small: QSize) -> None:
    one, two, three = (cast(AnalysisDock, plots.add()) for _ in range(3))
    plots.area.move(60, 50)
    plots.show(qtbot)
    docked_at = one.mapToGlobal(QPoint(0, 0))
    step = QPoint(AnalysisDock.FLOAT_STEP, AnalysisDock.FLOAT_STEP)
    float_(one, qtbot)
    assert one.geometry() == QRect(docked_at + step, small)  # The first: a step from its docked place.
    float_(two, qtbot)
    assert two.geometry() == QRect(one.geometry().topLeft() + step, small)
    one.move(100, 300)  # The user moved the first: the next goes from the last floated, wherever it is.
    float_(three, qtbot)
    assert three.geometry() == QRect(two.geometry().topLeft() + step, small)


def test_a_floated_plot_is_kept_on_its_screen(plots: Plots, qtbot: QtBot, small: QSize) -> None:
    one, two = (cast(AnalysisDock, plots.add()) for _ in range(2))
    plots.show(qtbot)
    float_(one, qtbot)
    room = available(one)
    one.move(room.right() - 100, room.bottom() - 50)  # Near the corner: the next can't go a step further.
    float_(two, qtbot)
    assert room.contains(two.geometry()) and two.size() == small
    assert two.geometry().bottomRight() == room.bottomRight()


def test_the_float_size_is_less_on_a_smaller_screen(plots: Plots, qtbot: QtBot) -> None:
    one = cast(AnalysisDock, plots.add())
    plots.show(qtbot)
    float_(one, qtbot)
    room = available(one)
    expected = AnalysisDock.FLOAT_SIZE.boundedTo(room.size()).expandedTo(one.minimumSizeHint())
    frame = 2  # (The offscreen platform keeps a top-level window this far from the screen's edge.)
    assert one.size() == expected and room.adjusted(0, 0, frame, frame).contains(one.geometry())


def test_a_dragged_plot_stays_where_it_is_let_go(plots: Plots, qtbot: QtBot, small: QSize,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    one = cast(AnalysisDock, plots.add())
    plots.show(qtbot)
    monkeypatch.setattr("helab.views.plots.dock.mouse_held", lambda: True)
    placed: list[bool] = []
    monkeypatch.setattr(AnalysisDock, "place_floating", lambda self: placed.append(True))
    one.setFloating(True)
    assert one.isFloating() and not placed and one.floated_turn > 0


def test_a_double_click_on_the_title_floats_and_places_it(plots: Plots, qtbot: QtBot, small: QSize,
                                                          let_go: None) -> None:
    """Qt floats a dock on the double-click's press, the button still down: placed all the same, not taken
    for a drag (review Low 1)."""
    one = cast(AnalysisDock, plots.add())
    plots.area.move(60, 50)
    plots.show(qtbot)
    docked_at = one.mapToGlobal(QPoint(0, 0))
    qtbot.mouseDClick(one, Qt.MouseButton.LeftButton, pos=QPoint(one.width() // 2, 5))  # type: ignore[no-untyped-call]
    qtbot.waitUntil(one.isFloating)
    qtbot.wait(20)
    step = QPoint(AnalysisDock.FLOAT_STEP, AnalysisDock.FLOAT_STEP)
    assert one.geometry() == QRect(docked_at + step, small) and not one._double_clicked
    if QApplication.mouseButtons() != Qt.MouseButton.NoButton:  # (The release went to its new window.)
        qtbot.mouseRelease(one, Qt.MouseButton.LeftButton)  # type: ignore[no-untyped-call]
    qtbot.waitUntil(one.settings.isVisible)  # Its page follows once let go.


def test_the_dock_button_puts_a_floating_plot_back_with_its_settings(plots: Plots, qtbot: QtBot) -> None:
    page = QLineEdit("edited")
    one = cast(AnalysisDock, plots.add(page=page))
    plots.show(qtbot)
    float_(one, qtbot)
    button = one.settings.dock_button
    assert button.isVisible() and button.objectName() == "plot_dock" and button.accessibleName() == "Dock plot"
    assert button.text() == "⇲"  # The section closed: the strip's width.
    one.set_settings_open(True)
    assert button.text() == "⇲ Dock"
    button.click()
    qtbot.waitUntil(one.settings.isHidden)
    assert not one.isFloating() and page.parentWidget() is plots.panel.stack and page.text() == "edited"
