import pytest
from PyQt6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot


def test_widget_visibility(qtbot: QtBot) -> None:
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()
    assert widget.isVisible()
    print("Widget is visible!")