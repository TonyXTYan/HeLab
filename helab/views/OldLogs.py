"""Old log files, at startup (Tony, 2026-10-22): the oldest beyond Settings → General → Log files to
keep go (the setting counts as the user asking), and if what is left passes ``app_log.ASK_BYTES``
the user is asked, once per session, whether to delete old ones down to ``app_log.TRIM_BYTES``.

The scan and the deletes run on a thread of their own, never the GUI thread: the log folder is local
(the app folder), but startup and rendering don't wait for it. Running HeLabs' files are never
deleted (``app_log.deletable``).
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

from PyQt6.QtCore import QObject, pyqtBoundSignal, pyqtSignal
from PyQt6.QtWidgets import QAbstractButton, QMessageBox, QWidget

from helab.utils import app_log
from helab.utils.accessible import identify_buttons

QUESTION = "Log files use {size} {unit}. Delete old ones?"


class OldLogs(QObject):
    """Tidies the log folder of the app folder ``folder`` once, at startup (``start``)."""

    scanned = pyqtSignal(int)  # The bytes of logs left after the count rule (from the thread).

    def __init__(self, folder: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.folder = folder
        self.parent_widget = parent
        self.box: QMessageBox | None = None
        self.delete_button: QAbstractButton | None = None
        self.keep_button: QAbstractButton | None = None
        self.asked = False  # This session: asked once, whatever the answer (Keep lasts the session).
        self.threads: list[threading.Thread] = []
        self.scanned.connect(self._scanned)

    def start(self, keep: int) -> None:
        """Delete the oldest log files beyond ``keep``, then ask if the rest pass ``ASK_BYTES``."""
        self._run(lambda: self._emit(self.scanned, app_log.tidy_logs(self.folder, keep)), "old-logs")

    def _run(self, work: Callable[[], object], name: str) -> None:
        def run() -> None:
            try:
                work()
            except Exception:
                logging.exception("Old log files couldn't be tidied")
        thread = threading.Thread(target=run, name=name, daemon=True)
        self.threads.append(thread)
        thread.start()

    @staticmethod
    def _emit(signal: pyqtBoundSignal, size: int) -> None:
        try:
            signal.emit(size)
        except RuntimeError:  # (The window, and this, closed meanwhile.)
            pass

    def _scanned(self, size: int) -> None:
        if size <= app_log.ASK_BYTES or self.asked:
            return
        self.asked = True
        box = QMessageBox(QMessageBox.Icon.Question, "HeLab", QUESTION.format(size=round(size / app_log.MB), unit=app_log.MB_UNIT),
                          QMessageBox.StandardButton.NoButton, self.parent_widget)
        self.delete_button = box.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
        self.keep_button = keep = box.addButton("Keep", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep)
        box.setEscapeButton(keep)
        box.buttonClicked.connect(self._answered)
        self.box = box
        identify_buttons(box, "old_logs")
        box.show()

    def _answered(self, button: QAbstractButton) -> None:
        self.box = None
        if button is self.delete_button:
            self._run(lambda: app_log.trim_logs(self.folder), "old-logs-delete")
