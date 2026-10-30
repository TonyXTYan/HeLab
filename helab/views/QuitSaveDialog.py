"""Quitting waits for disk cache saves still running (roadmaps/live-monitoring.md).

Live's new shots, a finished load's background save (``disk_cache_pending``), a folder's flags
or constants still being written, a plot's result being saved (its run's save, or Make room for
it), presets being written and the converted TXY's last uses loads didn't write (Q~3) are saved
before HeLab quits. This window names the folders,
closes by itself when the saves end (each stops itself after the usual no-progress timeout), and
offers Quit now, which skips them. Nothing is lost either way: the source files remain, the next
check reads what wasn't saved, and a plot whose result wasn't saved computes it again. Results
waiting for Make room aren't waited for: they stay in the disk cache for the next session.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from helab.utils.folder_cache import PRESETS_SAVING, TXY_LAST_USED, FolderCache

QUIT_NOW_TOOLTIP = ("Quit without waiting. The folders' TXY files stay where they are: the next check of "
                    "each reads the shots that weren't saved.")


class QuitSaveDialog(QDialog):
    """Saving before quitting: the folders, and Quit now. Accepted when the saves have ended;
    rejected by Quit now (``skipped``). Esc and the close button keep waiting."""
    POLL_MS = 250

    def __init__(self, cache: FolderCache, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cache = cache
        self.skipped = False
        self.setWindowTitle("Saving before quitting")
        self.setModal(True)
        layout = QVBoxLayout(self)
        self.label = QLabel()
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.folders = QListWidget()
        layout.addWidget(self.folders)
        note = QLabel("HeLab quits when they are saved. A save that makes no progress for a minute or two "
                      "stops by itself.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox()
        quit_now = buttons.addButton("Quit now", QDialogButtonBox.ButtonRole.DestructiveRole)
        assert quit_now is not None
        quit_now.setToolTip(QUIT_NOW_TOOLTIP)
        quit_now.setAutoDefault(False)
        quit_now.clicked.connect(self.quit_now)
        self.quit_now_button = quit_now
        layout.addWidget(buttons)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(self.POLL_MS)
        cache.quitSavesChanged.connect(self.refresh)
        self.resize(480, 260)
        # Shown at once; it closes from the event loop (its owner connects ``finished`` first).
        self._show(cache.quit_saves())

    def state(self, path: str) -> str:
        if path == PRESETS_SAVING and self.cache.presets_saving():
            return "saving"
        if path == TXY_LAST_USED:
            return "recording when HeLab's converted TXY were last used"
        if self.cache.disk_cache_saving(path):
            return "writing the disk cache"
        if ("load", self.cache.key(path)) in self.cache.jobs:
            return "reading its new shots"
        if self.cache.folder_settings_saving(path):
            return "saving its flags or constants"
        if self.cache.result_saving(path):
            return "saving a plot's result"
        return "waiting for its previous save"

    def refresh(self) -> None:
        if not self.timer.isActive():
            return
        paths = self.cache.quit_saves()
        if paths:
            self._show(paths)
        else:
            self._end(skipped=False)

    def _show(self, paths: list[str]) -> None:
        count = len([path for path in paths if path not in (PRESETS_SAVING, TXY_LAST_USED)])  # (Their own entries.)
        saving = " and ".join(filter(None, (f"{count:,} folder{'' if count == 1 else 's'}" if count else "",
                                            "presets" if PRESETS_SAVING in paths else "")))
        # (The converted TXY's index may be under the temp folder, not the disk cache: Q~3, Nit-10.)
        doing = " and ".join(filter(None, (f"saving {saving} to the disk cache" if saving else "",
                                           "recording when converted TXY were last used"
                                           if TXY_LAST_USED in paths else "")))
        self.label.setText(f"{doing[:1].upper()}{doing[1:]} before HeLab quits:")
        self.folders.clear()
        for path in paths:
            name = os.path.basename(path.rstrip("/\\")) or path
            item = QListWidgetItem(f"{name} — {self.state(path)}")
            item.setToolTip(path)
            self.folders.addItem(item)

    def quit_now(self) -> None:
        self._end(skipped=True)

    def _end(self, *, skipped: bool) -> None:
        if self.timer.isActive():
            self.timer.stop()
            self.cache.quitSavesChanged.disconnect(self.refresh)
            self.skipped = skipped
            self.done(QDialog.DialogCode.Rejected if skipped else QDialog.DialogCode.Accepted)

    def reject(self) -> None:
        """Esc or the close button: keep waiting (Quit now skips the saves)."""
