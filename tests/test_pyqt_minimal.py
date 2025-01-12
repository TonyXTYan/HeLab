import pytest
from PyQt6.QtWidgets import QApplication, QWidget

def test_widget_visibility(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()
    assert widget.isVisible()
    print("Widget is visible!")