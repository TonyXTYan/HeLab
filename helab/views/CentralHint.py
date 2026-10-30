"""The plot area's background when no plot is open: a one-line hint, a dimmed second line,
and a usage tip that changes now and then (click it for the next)."""
from __future__ import annotations

import random

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from helab.utils.accessible import identify

TIPS = (
    "Data already cached shows at once when you select its folder, then is checked for changes.",
    "Live (toolbar) adds new shots to the selected folder as they arrive; Rerun a plot to include them.",
    "A plot keeps the data it ran on: press Rerun with these settings, or its Plot button, for the newest shots.",
    "Shots → From shot starts any plot at a given shot number; Last N gives a rolling window.",
    "Double-click a plot's title to float it, and view several side by side: Settings follows the plot you click.",
    "Close a plot with the × on its tab, or the ✕ beside the Settings chooser.",
    "Number boxes take plain numbers: type 95, not 95 %; 5 in a box showing 4 mm means 5 mm.",
    "Transfer fractions finds the orders itself; switch Orders to manual to adjust its centre and spacing.",
    "The 3D scatter's Open in browser shows the same plot where the plot pane stays black.",
    "Folder details, below the tree, shows a load's progress, time left and all I/O.",
    "Hover a folder to see when it was checked and what is cached for it.",
    "Right-click a folder → Retry / Refresh checks every file again.",
    "Right-click a folder → Don't cache or Don't auto-load this folder.",
    "File › Place .helab-root… at the top of a data drive lets HeLab cache its folders on disk.",
    "Settings → Cache sets the disk and RAM budgets; nothing is deleted without asking.",
)
TIP_SECONDS = 30


class ClickableLabel(QLabel):
    clicked = pyqtSignal()

    def mousePressEvent(self, ev: QMouseEvent | None) -> None:
        super().mousePressEvent(ev)
        self.clicked.emit()


class CentralHint(QWidget):
    """A hint line and a usage tip (``TIPS``, every ``TIP_SECONDS``).

    Callers set text only; the layout stays centred whatever is shown.
    """

    def __init__(self, hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.addStretch(1)
        self.hint = identify(QLabel(hint), "central_hint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)
        self._layout.addWidget(self.hint)
        self.tip = identify(ClickableLabel(), "central_tip", description="Show another tip")
        self.tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tip.setWordWrap(True)
        self.tip.setStyleSheet("color: #888;")  # Dimmed, but enabled: it takes clicks.
        self.tip.setToolTip("Click for another tip")
        self.tip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tip.clicked.connect(self._next_tip_clicked)
        self._layout.addSpacing(12)
        self._layout.addWidget(self.tip)
        self._layout.addStretch(1)
        self._tips = list(TIPS)
        random.shuffle(self._tips)
        self._tip_index = -1
        self.tip_timer = QTimer(self)
        self.tip_timer.setInterval(TIP_SECONDS * 1000)
        self.tip_timer.timeout.connect(self.next_tip)
        self.tip_timer.start()
        self.next_tip()

    def set_hint(self, text: str, tooltip: str = "") -> None:
        self.hint.setText(text)
        self.hint.setToolTip(tooltip)

    def next_tip(self) -> None:
        """The next usage tip, in a shuffled order. The timer moves on only while the hint is
        on screen, so a tip isn't skipped unseen behind a plot."""
        if self._tip_index < 0 or self.isVisible():
            self._tip_index = (self._tip_index + 1) % len(self._tips)
            self.tip.setText(f"Tip: {self._tips[self._tip_index]}")

    def _next_tip_clicked(self) -> None:
        self.next_tip()
        self.tip_timer.start()  # A full interval to read it.

    def text(self) -> str:
        return self.hint.text()
