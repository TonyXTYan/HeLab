# tests/test_icons.py
import os
import sys
import unittest

from PyQt6.QtCore import QThreadPool
from PyQt6.QtGui import QIcon
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pytablericons import OutlineIcon

from helab.resources.icons import tablerIcon, StatusIcons, ToolIcons, IconsInitUtil


class TestIcons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if not cls.app:
            cls.app = QApplication([])
        IconsInitUtil.initialise_icons()

    @classmethod
    def tearDownClass(cls):
        if cls.app:
            while not QThreadPool.globalInstance().activeThreadCount() == 0: QTest.qWait(10)
            cls.app.quit()
            cls.app = None

    def test_tabler_icon(self):
        icon = tablerIcon(OutlineIcon.ABC, '#00bb39', size=128)
        self.assertIsInstance(icon, QIcon)

    def test_status_icons_initialisation(self):
        try:
            self.assertIsNotNone(StatusIcons.ICONS_STATUS)
            for icon_name in StatusIcons.ICONS_STATUS:
                self.assertIsInstance(StatusIcons.ICONS_STATUS[icon_name], QIcon)

            self.assertIsNotNone(StatusIcons.ICONS_EXTRA)
            for icon_name in StatusIcons.ICONS_EXTRA:
                self.assertIsInstance(StatusIcons.ICONS_EXTRA[icon_name], QIcon)
        except Exception as e:
            self.fail(f"Failed to initialise StatusIcons: {e}")

if __name__ == '__main__':
    unittest.main()