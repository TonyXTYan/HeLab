# tests/test_icons.py
import os
import sys

import pytest
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
from pytablericons import OutlineIcon

# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from helab.resources.icons import tablerIcon, StatusIcons

@pytest.fixture(scope="module", autouse=True)
def app():
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    StatusIcons.initialise_icons()
    return app

def test_tabler_icon():
    icon = tablerIcon(OutlineIcon.ABC, '#00bb39', size=128)
    assert isinstance(icon, QIcon)


def test_status_icons_initialisation():
    try:
        assert StatusIcons.ICONS_STATUS is not None
        for icon_name in StatusIcons.ICONS_STATUS:
            assert isinstance(StatusIcons.ICONS_STATUS[icon_name], QIcon)

        assert StatusIcons.ICONS_EXTRA is not None
        for icon_name in StatusIcons.ICONS_EXTRA:
            assert isinstance(StatusIcons.ICONS_EXTRA[icon_name], QIcon)
    except Exception as e:
        pytest.fail(f"Failed to initialise StatusIcons: {e}")