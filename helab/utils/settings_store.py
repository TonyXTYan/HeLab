"""The app's settings store: one place opens it (``app_settings``).

HeLab's settings are ``QSettings`` with org ``ANU_HE_BEC_GROUP`` and app ``HeLab`` (macOS plist
``~/Library/Preferences/com.anu-he-bec-group.HeLab.plist``). Every part of the app opens them
here, never with ``QSettings(org, app)`` itself (``tests/test_settings_store.py`` checks).

Test seam: with ``HELAB_TEST_SETTINGS_FILE=<path>`` (``tests/conftest.py`` sets one per test),
``app_settings`` opens that ini file instead, so tests never read or write the native store.
Helpers open the same store from ``cache_setting.settings_spec`` (a file for an ini).

QtCore only, and nothing of HeLab's: ``helab.utils.constants`` reads it while it is imported.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QSettings

QSETTINGS_ORG_NAME = "ANU_HE_BEC_GROUP"
QSETTINGS_APP_NAME = "HeLab"


def app_settings() -> QSettings:
    """HeLab's settings (a new ``QSettings`` on the same store each call, as Qt intends)."""
    test_file = os.environ.get("HELAB_TEST_SETTINGS_FILE")
    if test_file:
        return QSettings(test_file, QSettings.Format.IniFormat)
    return QSettings(QSETTINGS_ORG_NAME, QSETTINGS_APP_NAME)
