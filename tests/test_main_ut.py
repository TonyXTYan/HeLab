import time
import unittest

from PyQt6.QtCore import QThreadPool, QCoreApplication
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from helab.resources.icons import IconsInitUtil
from helab.views.helabMainWindow import MainWindow


class TestMainWindow(unittest.TestCase):
    app: QCoreApplication
    thread_pool: QThreadPool

    @classmethod
    def setUpClass(cls) -> None:
        # IconsInitUtil.initialise_icons()
        cls.app = QApplication([])
        thread_pool = QThreadPool.globalInstance()
        cls.thread_pool = thread_pool if thread_pool is not None else QThreadPool()

    def setUp(self) -> None:
        IconsInitUtil.initialise_icons()
        self.main_window = MainWindow()
        # QThreadPool.globalInstance().waitForDone()
        self.main_window.show()

    def tearDown(self) -> None:
        time.sleep(0.1)
        # QThreadPool.globalInstance().waitForDone()
        while not self.thread_pool.activeThreadCount() == 0: time.sleep(0.05)
        time.sleep(0.05)
        self.main_window.close()

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
        self.assertIsNotNone(self.main_window.splitter)
        self.assertIsNotNone(self.main_window.left_panel)
        self.assertIsNotNone(self.main_window.middle_mainwindow)
        self.assertIsNotNone(self.main_window.right_panel)
        # QThreadPool.globalInstance().waitForDone()

if __name__ == '__main__':
    unittest.main()