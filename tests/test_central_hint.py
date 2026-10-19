"""The plot area's hint shows a usage tip that changes on a timer while shown, or on a click."""
from __future__ import annotations

import PyQt6.QtWebEngineWidgets  # noqa: F401  # Before the QApplication: conftest imports the plot code.
from pytestqt.qtbot import QtBot
from PyQt6.QtCore import Qt

from helab.views.CentralHint import TIPS, CentralHint


def test_tips_rotate_while_shown_and_on_click(qtbot: QtBot) -> None:
    hint = CentralHint("Select a data folder to begin")
    qtbot.addWidget(hint)
    first = hint.tip.text()
    assert first.startswith("Tip: ") and first[5:] in TIPS
    hint.next_tip()  # Hidden: the timer doesn't move on unseen.
    assert hint.tip.text() == first
    hint.show()
    qtbot.waitExposed(hint)
    hint.next_tip()
    second = hint.tip.text()
    assert second != first and second[5:] in TIPS
    qtbot.mouseClick(hint.tip, Qt.MouseButton.LeftButton)  # type: ignore[no-untyped-call]
    assert hint.tip.text() not in (first, second) and hint.tip_timer.isActive()
    seen = {hint.tip.text()}
    for _ in range(len(TIPS) - 1):
        hint.next_tip()
        seen.add(hint.tip.text())
    assert len(seen) == len(TIPS)  # Every tip comes round before any repeats.
    assert hint.text() == "Select a data folder to begin"
