"""The ``dir_caches`` setting, written as a cache move's cutover needs it (roadmap S9).

QtCore only: the startup recovery helper writes it too, without a QApplication.
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QSettings


def write_cache_setting(settings: QSettings, path: str) -> bool:
    """Saved, synced and read back, or it didn't happen (still before the cutover)."""
    settings.setValue("dir_caches", path)
    settings.sync()
    return settings.status() == QSettings.Status.NoError and settings.value("dir_caches", type=str) == path


def settings_spec(settings: QSettings) -> dict[str, Any]:
    """How a helper opens the same settings: the file for an ini (tests), else org and app."""
    if settings.format() == QSettings.Format.IniFormat:
        return {"file": settings.fileName()}
    return {"org": settings.organizationName(), "app": settings.applicationName()}


def open_settings(spec: dict[str, Any]) -> QSettings:
    if spec.get("file"):
        return QSettings(str(spec["file"]), QSettings.Format.IniFormat)
    return QSettings(str(spec["org"]), str(spec["app"]))
