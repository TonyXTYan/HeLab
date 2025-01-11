# tests/test_icons.py
import os
import sys
import time
import unittest

from PyQt6.QtCore import QThreadPool, QCoreApplication
from PyQt6.QtGui import QIcon
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pytablericons import OutlineIcon

from helab.resources.icons import tablerIcon, StatusIcons, ToolIcons, IconsInitUtil


class TestIcons(unittest.TestCase):
    app: QCoreApplication
    thread_pool: QThreadPool

    @classmethod
    def setUpClass(cls) -> None:
        app = QApplication.instance()
        if app is None: app = QApplication([])
        cls.app = app
        if not cls.app:
            cls.app = QApplication([])
        IconsInitUtil.initialise_icons()
        thread_pool = QThreadPool.globalInstance()
        cls.thread_pool = thread_pool if thread_pool is not None else QThreadPool()

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.app:
            while cls.thread_pool.activeThreadCount() > 0: time.sleep(0.05)
            cls.app.quit()
            del cls.app

    def test_tabler_icon(self) -> None:
        icon = tablerIcon(OutlineIcon.ABC, '#00bb39', size=128)
        self.assertIsInstance(icon, QIcon)

    def test_status_icons_initialisation(self) -> None:
        try:
            self.assertIsNotNone(StatusIcons.ICONS_STATUS)
            for icon_name in StatusIcons.ICONS_STATUS:
                self.assertIsInstance(StatusIcons.ICONS_STATUS[icon_name], QIcon)

            self.assertIsNotNone(StatusIcons.ICONS_EXTRA)
            for icon_name in StatusIcons.ICONS_EXTRA:
                self.assertIsInstance(StatusIcons.ICONS_EXTRA[icon_name], QIcon)
        except Exception as e:
            self.fail(f"Failed to initialise StatusIcons: {e}")

    def test_icons_status_not_empty(self) -> None:
        self.assertTrue(StatusIcons.ICONS_STATUS)
        for name, icon in StatusIcons.ICONS_STATUS.items():
            self.assertIsInstance(icon, QIcon, msg=f"{name} icon is not QIcon")

    def test_icons_extra_not_empty(self) -> None:
        self.assertTrue(StatusIcons.ICONS_EXTRA)
        for name, icon in StatusIcons.ICONS_EXTRA.items():
            self.assertIsInstance(icon, QIcon, msg=f"{name} icon is not QIcon")

    def test_known_status_names(self) -> None:
        for name in StatusIcons.STATUS_ICONS_NAME:
            self.assertIn(name, StatusIcons.ICONS_STATUS, msg=f"Missing status icon for {name}")

    def test_known_extra_names(self) -> None:
        for name in StatusIcons.STATUS_ICONS_EXTRA_NAME:
            self.assertIn(name, StatusIcons.ICONS_EXTRA, msg=f"Missing extra icon for {name}")
            
if __name__ == '__main__':
    unittest.main()