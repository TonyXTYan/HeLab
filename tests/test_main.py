# tests/test_main.py
import pytest
from PyQt6.QtWidgets import QApplication
import sys
import os

# Add the root directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from helium.views.heliumMainWindow import MainWindow


@pytest.fixture
def app():
    app = QApplication(sys.argv)
    yield app
    app.quit()

def test_main_window_creation(app):
    main_window = MainWindow()
    assert main_window is not None
    assert main_window.isVisible() == False

