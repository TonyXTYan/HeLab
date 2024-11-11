# tests/test_main.py
import pytest
from PyQt6.QtCore import QCoreApplication, QThreadPool
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
import sys
import os

from helab.resources.icons import IconsInitUtil
# Add the root directory to the Python path
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from helab.views.helabMainWindow import MainWindow

QTEST_WAIT_MS = 5000
QTEST_WAIT_MS_SHORT = 3000


# @pytest.fixture
# def app():
#     app = QApplication.instance()
#     if not app:
#         app = QApplication([])
#     IconsInitUtil.initialise_icons()
#     yield app
#     # return app
#     QCoreApplication.quit()

@pytest.fixture
def app():
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    IconsInitUtil.initialise_icons()
    try:
        yield app
    finally:
        app.processEvents()  # Process remaining events
        QCoreApplication.quit()

def test_main_window_creation(app):
    main_window = MainWindow()
    # QTest.qWait(QTEST_WAIT_MS)  # Wait for 100ms to process events
    # QThreadPool.globalInstance().waitForDone()
    while not QThreadPool.globalInstance().activeThreadCount() == 0: QTest.qWait(10)
    assert main_window is not None
    assert main_window.isVisible() == False

def test_main_window_title(app):
    main_window = MainWindow()
    # QThreadPool.globalInstance().waitForDone()
    # QTest.qWait(QTEST_WAIT_MS_SHORT)
    while not QThreadPool.globalInstance().activeThreadCount() == 0: QTest.qWait(10)
    assert main_window.windowTitle() == "HeLab"

def test_main_window_size(app):
    main_window = MainWindow()
    # QThreadPool.globalInstance().waitForDone()
    # QTest.qWait(QTEST_WAIT_MS_SHORT)
    while not QThreadPool.globalInstance().activeThreadCount() == 0: QTest.qWait(10)
    assert main_window.size().width() == MainWindow.DEFAULT_WIDTH
    assert main_window.size().height() == MainWindow.DEFAULT_HEIGHT

def test_main_window_initial_state(app):
    main_window = MainWindow()
    # QThreadPool.globalInstance().waitForDone()
    # QTest.qWait(QTEST_WAIT_MS_SHORT)
    while not QThreadPool.globalInstance().activeThreadCount() == 0: QTest.qWait(10)
    assert main_window.isMaximized() == False
    assert main_window.isMinimized() == False