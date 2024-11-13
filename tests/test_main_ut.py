# tests/test_main_ut.py
import logging
import time
import unittest

from PyQt6.QtCore import QThreadPool, QCoreApplication
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from helab.resources.icons import IconsInitUtil
from helab.views.helabMainWindow import MainWindow


class TestMainWindow(unittest.TestCase):
    app: QCoreApplication | QApplication | None
    thread_pool: QThreadPool

    @classmethod
    def setUpClass(cls) -> None:
        # IconsInitUtil.initialise_icons()
        if not QCoreApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QCoreApplication.instance()
        thread_pool = QThreadPool.globalInstance()
        cls.thread_pool = thread_pool if thread_pool is not None else QThreadPool()

    @classmethod
    def tearDownClass(cls) -> None:
        if isinstance(cls.app, QApplication):
            cls.app.quit()
        # QThreadPool.globalInstance().waitFor
        while cls.thread_pool.activeThreadCount() > 0: time.sleep(0.05)
        return

    def setUp(self) -> None:
        IconsInitUtil.initialise_icons()
        self.main_window = MainWindow()
        # QThreadPool.globalInstance().waitForDone()
        self.main_window.show()
        # QTest.qWaitForWindowExposed(self.main_window)
        time.sleep(0.1)

    def tearDown(self) -> None:
        try:
            time.sleep(0.1)
            # self.main_window.close()
            # QThreadPool.globalInstance().waitForDone()
            while self.thread_pool.activeThreadCount() > 0: time.sleep(0.05)
            # self.app.quit()
            if isinstance(self.app, QApplication):
                self.app.quit()
            time.sleep(0.5)
            # self.main_window.close()
        except Exception as e:
            # self.fail(f"Error in tearDown: {e}")
            logging.error(f"Error in tearDown: {e}")
            pass

    def test_window_title(self) -> None:
        self.assertEqual(self.main_window.windowTitle(), 'HeLab')
        # QThreadPool.globalInstance().waitForDone()

    def test_default_size(self) -> None:
        self.assertEqual(self.main_window.width(), MainWindow.DEFAULT_WIDTH)
        self.assertEqual(self.main_window.height(), MainWindow.DEFAULT_HEIGHT)
        # QThreadPool.globalInstance().waitForDone()

    def test_menus_created(self) -> None:
        menus = self.main_window.menu_bar.actions()
        menu_titles = [menu.text() for menu in menus]
        self.assertIn('File', menu_titles)
        # QThreadPool.globalInstance().waitForDone()

    def test_central_widget_setup(self) -> None:
        time.sleep(0.05)
        self.assertIsNotNone(self.main_window.splitter)
        self.assertIsNotNone(self.main_window.left_panel)
        self.assertIsNotNone(self.main_window.middle_mainwindow)
        self.assertIsNotNone(self.main_window.right_panel)
        time.sleep(0.05)
        # QThreadPool.globalInstance().waitForDone()

if __name__ == '__main__':
    unittest.main()