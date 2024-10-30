# tests/test_main.py
import pytest
from helium.views.heliumMainWindow import MainWindow
from PyQt6.QtWidgets import QApplication
import sys

@pytest.fixture
def app():
    app = QApplication(sys.argv)
    yield app
    app.quit()

def test_main_window_creation(app):
    main_window = MainWindow()
    assert main_window is not None
    assert main_window.isVisible() == False