"""The plot area's background when no plot is open: a one-line hint, plus room for more."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget


class CentralHint(QWidget):
    """A hint line and an optional second line (e.g. tips or a quote of the day, see the roadmap).

    Callers set text only; the layout stays centred whatever is shown. Further
    widgets can be added with ``add_widget`` without changing the hint.
    """

    def __init__(self, hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.addStretch(1)
        self.hint = QLabel(hint)
        self.extra = QLabel()
        for label in (self.hint, self.extra):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            self._layout.addWidget(label)
        self.extra.setEnabled(False)  # Dimmed, secondary to the hint.
        self.extra.hide()
        self._layout.addStretch(1)

    def set_hint(self, text: str, tooltip: str = "") -> None:
        self.hint.setText(text)
        self.hint.setToolTip(tooltip)

    def set_extra(self, text: str) -> None:
        self.extra.setText(text)
        self.extra.setVisible(bool(text))

    def add_widget(self, widget: QWidget) -> None:
        """Add a widget under the hint lines, above the bottom stretch."""
        self._layout.insertWidget(self._layout.count() - 1, widget)

    def text(self) -> str:
        return self.hint.text()
