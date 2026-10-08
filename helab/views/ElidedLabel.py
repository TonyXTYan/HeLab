"""Single-line label that elides to its width instead of wrapping or widening its parent."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtWidgets import QLabel, QSizePolicy, QWidget


class ElidedLabel(QLabel):
    """``text()`` returns the full text; the label shows as much as fits.

    Its height never depends on the text, so status rows keep their height and
    the widgets below them do not move.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None,
                 mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight) -> None:
        super().__init__(parent)
        self._full = ""
        self._mode = mode
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(False)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setText(text)

    def setText(self, a0: str | None) -> None:
        self._full = a0 or ""
        self._elide()

    def text(self) -> str:
        return self._full

    def clear(self) -> None:
        self.setText("")

    def natural_width(self) -> int:
        """Width of the full text, for rows that share their width between labels."""
        margins = self.contentsMargins()
        return self.fontMetrics().horizontalAdvance(self._full) + margins.left() + margins.right() + 1

    def changeEvent(self, a0: QEvent | None) -> None:
        super().changeEvent(a0)
        if a0 is not None and a0.type() == QEvent.Type.FontChange:
            self._elide()

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        self._elide()

    def _elide(self) -> None:
        width = max(0, self.contentsRect().width())
        super().setText(self.fontMetrics().elidedText(self._full, self._mode, width))
