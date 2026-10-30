"""``--geometry WxH+X+Y``: the main window's size and place for this run only (a test runner's fixed
coordinates; roadmaps/smoke-automation.md, item 6's fixed geometry)."""
from __future__ import annotations

import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before any QApplication: the main window)
from PyQt6.QtCore import QRect
from pytestqt.qtbot import QtBot

from helab.views.HelabMainWindow import HelabMainWindow


@pytest.mark.parametrize("argv, geometry, rest", [
    (["helab"], None, ["helab"]),
    (["helab", "--geometry", "1600x928+0+39"], QRect(0, 39, 1600, 928), ["helab"]),
    (["helab", "--geometry=1200x800-1280+10", "-x"], QRect(-1280, 10, 1200, 800), ["helab", "-x"]),
    (["helab", "--geometry", "big"], None, ["helab"]),  # Ignored (and logged), and not passed to Qt.
    (["helab", "--geometry"], None, ["helab"]),
    (["helab", "--geometry", "-x"], None, ["helab", "-x"]),  # Another option: kept for Qt.
    (["helab", "--geometry", "1600x928"], None, ["helab"]),
])
def test_the_option_is_read_and_taken_out(argv: list[str], geometry: QRect | None, rest: list[str]) -> None:
    assert HelabMainWindow.take_geometry(argv) == (geometry, rest)


def test_the_window_opens_at_that_size_and_place(qtbot: QtBot) -> None:
    window = HelabMainWindow()
    qtbot.addWidget(window)
    try:
        window.apply_geometry(QRect(40, 60, 1300, 700))
        window.show()
        assert (window.width(), window.height()) == (1300, 700)
        assert (window.frameGeometry().x(), window.frameGeometry().y()) == (40, 60)
        window.apply_geometry(QRect(0, 0, 200, 100))  # Never below its minimum size.
        assert (window.width(), window.height()) == (1000, 600)
    finally:
        window.close()
        qtbot.waitUntil(lambda: window._closing, timeout=30_000)
