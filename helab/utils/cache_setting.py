"""The ``dir_caches`` setting, written as a cache move's cutover needs it (roadmap S9), and caching
v2's store switch (``store_v4_enabled``, Q28.3).

QtCore only: the startup recovery helper writes it too, without a QApplication.
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QSettings

from helab.utils.settings_defaults import DIR_CACHES_SETTING, STORE_V4_SETTING, read_setting


def write_cache_setting(settings: QSettings, path: str) -> bool:
    """Saved, synced and read back, or it didn't happen (still before the cutover)."""
    settings.setValue(DIR_CACHES_SETTING, path)
    settings.sync()
    return (settings.status() == QSettings.Status.NoError
            and read_setting(settings, DIR_CACHES_SETTING, typed=True) == path)


def store_v4_enabled(settings: QSettings) -> bool:
    """Caching v2's switch (Q28.3): the disk cache lives in store-v4. Off unless set by hand."""
    return bool(read_setting(settings, STORE_V4_SETTING, typed=True))


def settings_spec(settings: QSettings) -> dict[str, Any]:
    """How a helper opens the same settings: the file for an ini (tests), else org and app."""
    if settings.format() == QSettings.Format.IniFormat:
        return {"file": settings.fileName()}
    return {"org": settings.organizationName(), "app": settings.applicationName()}


def open_settings(spec: dict[str, Any]) -> QSettings:
    if spec.get("file"):
        return QSettings(str(spec["file"]), QSettings.Format.IniFormat)
    return QSettings(str(spec["org"]), str(spec["app"]))
