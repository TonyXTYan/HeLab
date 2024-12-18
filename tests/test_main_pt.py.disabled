# tests/test_main.py
import time
from typing import Generator, cast

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

def setup_thread_pool() -> QThreadPool:
    thread_pool_helper = QThreadPool.globalInstance()
    if thread_pool_helper is None:
        thread_pool_helper = QThreadPool()
    thread_pool: QThreadPool = thread_pool_helper
    return thread_pool

def wait_thread_pool_complete(thread_pool: QThreadPool) -> None:
    time.sleep(0.05)
    while not thread_pool.activeThreadCount() == 0: time.sleep(0.005)
    time.sleep(0.05)

@pytest.fixture
def app() -> Generator[QApplication, None, None]:
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    else:
        app = cast(QApplication, app)
    IconsInitUtil.initialise_icons()
    try:
        yield app
    finally:
        app.processEvents()  # Process remaining events
        QCoreApplication.quit()

def test_main_window_creation(app: QApplication) -> None:
    thread_pool = setup_thread_pool()
    main_window = MainWindow()
    # QTest.qWait(QTEST_WAIT_MS)  # Wait for 100ms to process events
    # QThreadPool.globalInstance().waitForDone()
    wait_thread_pool_complete(thread_pool)
    assert main_window is not None
    assert main_window.isVisible() == False




def test_main_window_title(app: QApplication) -> None:
    thread_pool = setup_thread_pool()
    main_window = MainWindow()
    # QThreadPool.globalInstance().waitForDone()
    # QTest.qWait(QTEST_WAIT_MS_SHORT)
    wait_thread_pool_complete(thread_pool)
    assert "HeLab" in main_window.windowTitle()

def test_main_window_size(app: QApplication) -> None:
    thread_pool = setup_thread_pool()
    main_window = MainWindow()
    # QThreadPool.globalInstance().waitForDone()
    # QTest.qWait(QTEST_WAIT_MS_SHORT)
    wait_thread_pool_complete(thread_pool)
    assert main_window.size().width() == MainWindow.DEFAULT_WIDTH
    assert main_window.size().height() == MainWindow.DEFAULT_HEIGHT

def test_main_window_initial_state(app : QApplication) -> None:
    thread_pool = setup_thread_pool()
    main_window = MainWindow()
    # QThreadPool.globalInstance().waitForDone()
    # QTest.qWait(QTEST_WAIT_MS_SHORT)
    wait_thread_pool_complete(thread_pool)
    assert main_window.isMaximized() == False
    assert main_window.isMinimized() == False