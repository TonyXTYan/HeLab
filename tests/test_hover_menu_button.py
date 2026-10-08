from PyQt6 import QtWebEngineWidgets  # Shared worker cleanup imports WebEngine; preload before QApplication.
from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtWidgets import QMenu, QVBoxLayout, QWidget
import pytest
from pytestqt.qtbot import QtBot

from helab.views.HoverMenuToolButton import HoverMenuToolButton


def make_button(qtbot: QtBot) -> tuple[QWidget, HoverMenuToolButton, QMenu]:
    window = QWidget()
    qtbot.addWidget(window)
    window.resize(200, 120)
    layout = QVBoxLayout(window)
    button = HoverMenuToolButton(window)
    button.setFixedSize(32, 12)
    menu = QMenu(window)
    menu.addAction("Current folder")
    button.setMenu(menu)
    layout.addWidget(button)
    window.show()
    qtbot.waitUntil(button.isVisible)
    qtbot.mouseMove(window, QPoint(180, 100))  # type: ignore[no-untyped-call]
    return window, button, menu


def test_hover_opens_options_without_triggering_an_action(qtbot: QtBot) -> None:
    window, button, menu = make_button(qtbot)
    triggered: list[bool] = []
    menu.actions()[0].triggered.connect(lambda: triggered.append(True))
    qtbot.mouseMove(button, button.rect().center())  # type: ignore[no-untyped-call]
    qtbot.waitUntil(menu.isVisible)
    assert not triggered
    # Leaving the triangle for the menu must keep the options accessible.
    qtbot.mouseMove(menu, menu.actionGeometry(menu.actions()[0]).center())  # type: ignore[no-untyped-call]
    assert menu.isVisible()
    menu.close()
    qtbot.mouseMove(window, QPoint(180, 100))  # type: ignore[no-untyped-call]
    qtbot.wait(250)
    assert not menu.isVisible()


def test_passing_over_or_disabling_triangle_does_not_open_options(qtbot: QtBot) -> None:
    window, button, menu = make_button(qtbot)
    qtbot.mouseMove(button, button.rect().center())  # type: ignore[no-untyped-call]
    qtbot.mouseMove(window, QPoint(180, 100))  # type: ignore[no-untyped-call]
    qtbot.wait(250)
    assert not menu.isVisible()
    qtbot.mouseMove(button, button.rect().center())  # type: ignore[no-untyped-call]
    button.setEnabled(False)
    qtbot.wait(250)
    assert not menu.isVisible()


def test_menu_dismisses_after_half_second_outside(qtbot: QtBot) -> None:
    window, button, menu = make_button(qtbot)
    qtbot.mouseMove(button, button.rect().center())  # type: ignore[no-untyped-call]
    qtbot.waitUntil(menu.isVisible)
    qtbot.mouseMove(menu, menu.actionGeometry(menu.actions()[0]).center())  # type: ignore[no-untyped-call]
    qtbot.wait(1100)
    assert menu.isVisible()
    qtbot.mouseMove(window, QPoint(180, 100))  # type: ignore[no-untyped-call]
    qtbot.wait(300)
    assert menu.isVisible()
    qtbot.waitUntil(lambda: not menu.isVisible(), timeout=1000)


@pytest.mark.parametrize("return_to", ["triangle", "menu"])
def test_returning_cancels_dismissal_and_next_leave_restarts_delay(qtbot: QtBot, return_to: str) -> None:
    window, button, menu = make_button(qtbot)
    qtbot.mouseMove(button, button.rect().center())  # type: ignore[no-untyped-call]
    qtbot.waitUntil(menu.isVisible)
    qtbot.mouseMove(menu, menu.actionGeometry(menu.actions()[0]).center())  # type: ignore[no-untyped-call]
    qtbot.mouseMove(window, QPoint(180, 100))  # type: ignore[no-untyped-call]
    qtbot.wait(300)
    target = button if return_to == "triangle" else menu
    qtbot.mouseMove(target, target.rect().center())  # type: ignore[no-untyped-call]
    qtbot.wait(300)
    assert menu.isVisible()
    qtbot.mouseMove(window, QPoint(180, 100))  # type: ignore[no-untyped-call]
    qtbot.wait(300)
    assert menu.isVisible()
    qtbot.waitUntil(lambda: not menu.isVisible(), timeout=1000)


@pytest.mark.parametrize("opened_by", ["click", "keyboard", "show_menu"])
def test_click_keyboard_and_accessible_popups_open_options_to_the_right(qtbot: QtBot, opened_by: str) -> None:
    # Agents without a mouse use clicks, keys or the accessible showMenu action.
    window, button, menu = make_button(qtbot)
    positions: list[QPoint] = []

    def record_and_close() -> None:
        positions.append(menu.geometry().topLeft())
        menu.close()
    QTimer.singleShot(0, record_and_close)
    if opened_by == "click":
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton, pos=button.rect().center())  # type: ignore[no-untyped-call]
    elif opened_by == "keyboard":
        button.setFocus()
        qtbot.keyClick(button, Qt.Key.Key_Space)  # type: ignore[no-untyped-call]
    else:
        button.showMenu()
    assert positions == [button.mapToGlobal(QPoint(button.width(), 0))]


def test_options_open_left_of_the_triangle_at_the_screen_edge(qtbot: QtBot) -> None:
    window, button, menu = make_button(qtbot)
    screen = button.screen()
    assert screen is not None
    area = screen.availableGeometry()
    window.move(area.right() + 1 - window.frameGeometry().width(), area.top() + 100)
    qtbot.waitUntil(lambda: button.mapToGlobal(QPoint(button.width(), 0)).x() + menu.sizeHint().width()
                    > area.right() + 1)
    qtbot.mouseMove(button, button.rect().center())  # type: ignore[no-untyped-call]
    qtbot.waitUntil(menu.isVisible)
    assert menu.geometry().right() < button.mapToGlobal(QPoint(0, 0)).x()
