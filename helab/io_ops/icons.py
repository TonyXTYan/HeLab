"""Native folder icons for visible rows (``icons``): the only helper that imports Qt."""
from __future__ import annotations

import base64
import os

from helab.io_ops.infra import Emit, Pause, _trace, emit


def folder_icons(paths: list[str], send: Emit = emit) -> None:
    """Resolve OS icons only in this disposable process, never while listing.

    Keep the native platform plugin: offscreen Qt does not provide macOS custom
    or volume icons. No windows are created, and macOS helpers stay out of the Dock.
    """
    os.environ.setdefault("QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM", "1")
    from PyQt6.QtCore import QBuffer, QByteArray, QFileInfo, QIODevice
    from PyQt6.QtWidgets import QApplication, QFileIconProvider

    app = QApplication.instance() or QApplication(["helab-folder-icons"])
    provider = QFileIconProvider()
    for path in paths[:64]:
        Pause.checkpoint(send)
        encoded = ""
        # (The OS looks the folder and its custom icon up: calls Python can't see, so one line.)
        _trace("icon", path, "folder icon")
        try:
            pixmap = provider.icon(QFileInfo(path)).pixmap(32, 32)
            data = QByteArray()
            buffer = QBuffer(data)
            if buffer.open(QIODevice.OpenModeFlag.WriteOnly) and pixmap.save(buffer, "PNG"):
                encoded = base64.b64encode(data.data()).decode("ascii")
            buffer.close()
        except Exception:
            pass  # Cosmetic lookup failures leave the generic folder icon.
        send({"kind": "folder_icon", "path": path, "png": encoded})
    # Keep the QApplication alive until every pixmap and buffer has been used.
    _ = app
