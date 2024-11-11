# tests/test_main.py
import pytest
from PyQt6.QtWidgets import QApplication
import sys
import os

from helab.resources.icons import IconsInitUtil
# Add the root directory to the Python path
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from helab.views.helabMainWindow import MainWindow


@pytest.fixture
def app():
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    IconsInitUtil.initialise_icons()
    return app

def test_main_window_creation(app):
    main_window = MainWindow()
    assert main_window is not None
    assert main_window.isVisible() == False

