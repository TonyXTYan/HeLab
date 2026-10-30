"""The warning that this computer's clock and a folder's server disagree (R-22, Tony 2026-10-22).

A helper that finds a folder's files dated more than ``fingerprints.FUTURE_SECONDS`` ahead of this
computer's clock sends ``clock_skew``; ``FolderCache.clockSkew`` passes it on once per share or
volume per session, and this shows it in a window over the main window (not modal: work goes on).
Such files count as still being written, so they aren't read until the clocks agree; Live stops on
them like on an error (``io_ops.live``). Hooks hear of it through ``helab.utils.events``.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QMessageBox, QWidget

from helab.utils import events
from helab.utils.folder_cache import FolderCache
from helab.utils.time_format import span
from helab.views.accessible import identify_buttons

TITLE = "Computer clocks out of sync"
TEXT = ("Files in {folder} are dated {skew} ahead of this computer's clock: this computer's clock and the "
        "clock of the computer or server holding the folder are out of sync.")
DETAIL = ("HeLab treats files dated in the future as still being written, so it doesn't read them until this "
          "computer's clock catches up, and Live stops on them. Set both computers to set their time "
          "automatically, then Retry.")


class ClockSkewWarning(QObject):
    """Shows ``FolderCache.clockSkew`` over ``parent``; a newer one replaces the open one."""

    def __init__(self, cache: FolderCache, parent: QWidget) -> None:
        super().__init__(parent)
        self.cache = cache
        self.parent_widget = parent
        self.dialog: QMessageBox | None = None
        self._attached = True
        cache.clockSkew.connect(self.show_skew)

    def detach(self) -> None:
        """The window is closing: no more warnings."""
        if self._attached:
            self._attached = False
            self.cache.clockSkew.disconnect(self.show_skew)

    def show_skew(self, path: str, seconds: float) -> None:
        text = TEXT.format(folder=os.path.normpath(path), skew=span(seconds))
        events.notify(events.CLOCK_SKEW, text, path=path, seconds=seconds)  # For hooks; no desktop notification.
        if self.dialog is not None:
            self.dialog.close()
        box = QMessageBox(QMessageBox.Icon.Warning, TITLE, text, QMessageBox.StandardButton.Ok, self.parent_widget)
        box.setInformativeText(DETAIL)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.finished.connect(lambda _: self._closed(box))
        box.setWindowModality(Qt.WindowModality.NonModal)  # (A warning: work goes on behind it.)
        self.dialog = box
        identify_buttons(box, "clock_skew")
        box.show()

    def _closed(self, box: QMessageBox) -> None:
        if self.dialog is box:
            self.dialog = None
