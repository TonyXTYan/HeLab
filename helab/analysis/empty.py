"""What a plot shows when it has nothing to draw: a clear message instead of an error or an
empty frame. A view has no shots when Live started before the folder's first shot; the Shots
settings may choose none of them; chosen shots may hold no events."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget

NO_SHOTS = "No shots yet"


def empty_text(total_shots: int, chosen: int, events: int = 1) -> str:
    """Why there is nothing to draw ("" when there is): no shots, none chosen, or no events."""
    if total_shots == 0:
        return NO_SHOTS
    if chosen == 0:
        return f"None of the {total_shots:,} shot{'' if total_shots == 1 else 's'} is chosen (Shots settings)"
    if events == 0:
        return "No events in the chosen shots"
    return ""


def empty_pane(text: str, parent: Optional[QWidget] = None) -> QLabel:
    """The plot's place, saying why it is empty."""
    label = QLabel(text, parent)
    label.setObjectName("plot_empty")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(True)
    label.setStyleSheet("color: palette(mid); font-size: 15px;")
    return label
