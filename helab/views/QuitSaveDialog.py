"""Quitting waits for disk cache saves still running (roadmaps/live-monitoring.md).

Live's new shots, a finished load's background save (``disk_cache_pending``), a folder's flags
or constants still being written, a plot's result being saved (its run's save, or Make room for
it), presets being written, the converted TXY's last uses loads didn't write (Q~3, its own ~5 s
no-progress limit) and a conversion still running are finished before HeLab quits. This window lists
each of them (``FolderCache.quit_entries``) by folder, kind, state and how long it has run, from
memory, closes by itself when they all end (each stops itself after the usual no-progress timeout), and
offers Quit now, which skips them. Nothing is lost either way: the source files remain, the next
check reads what wasn't saved, and a plot whose result wasn't saved computes it again. Results
waiting for Make room aren't waited for: they stay in the disk cache for the next session.
"""
from __future__ import annotations

import os
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from helab.utils.accessible import identify
from helab.utils.folder_cache import (
    PRESETS_SAVING, QUIT_CONSTANTS, QUIT_CONVERT, QUIT_FLAGS, QUIT_LAST_USED, QUIT_LIVE, QUIT_MAKE_ROOM, QUIT_PRESETS,
    QUIT_RESULT, QUIT_SAVE, RESULTS_SAVING, TXY_LAST_USED, FolderCache, QuitSave)
from helab.utils.time_format import clock as stopwatch

# What each kind of operation is (``FolderCache.quit_entries``), and its state's words.
KINDS = {QUIT_LIVE: "Live's new shots", QUIT_SAVE: "its data", QUIT_FLAGS: "its flags", QUIT_CONSTANTS: "its constants",
         QUIT_RESULT: "a plot's result", QUIT_MAKE_ROOM: "making room for a plot's result", QUIT_PRESETS: "",
         QUIT_LAST_USED: "", QUIT_CONVERT: "converting raw files"}
STATES = {("", "reading"): "reading", ("", "writing"): "writing", ("", "waiting"): "waiting for its previous save",
          ("", "held"): "waiting for the disk cache's identity check", ("", "converting"): "",
          (QUIT_LIVE, "reading"): "reading them again", (QUIT_PRESETS, "waiting"): "waiting for the saved presets",
          (QUIT_LAST_USED, "writing"): "recording when HeLab's converted TXY were last used"}

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
        self.folders = identify(QListWidget(), "quit_saves", "Saves before quitting", "What HeLab is still saving")
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
        self.quit_now_button = identify(quit_now, "quit_now")
        layout.addWidget(buttons)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(self.POLL_MS)
        cache.quitSavesChanged.connect(self.refresh)
        self.resize(480, 260)
        # Shown at once; it closes from the event loop (its owner connects ``finished`` first).
        self._show(cache.quit_entries())

    @staticmethod
    def entry_text(save: QuitSave, now: float) -> str:
        """One operation's line: its folder, what it is and does, and how long it has run."""
        name = (save.path if save.path in (PRESETS_SAVING, TXY_LAST_USED, RESULTS_SAVING)
                else os.path.basename(save.path.rstrip("/\\")) or save.path)
        what = KINDS.get(save.kind, "")
        doing = STATES.get((save.kind, save.state)) or STATES.get(("", save.state), save.state)
        ran = f" · {stopwatch(now - save.started)}" if save.started is not None else ""
        return f"{name} — {', '.join(filter(None, (what, doing)))}{ran}"

    def refresh(self) -> None:
        if not self.timer.isActive():
            return
        entries = self.cache.quit_entries()
        if entries:
            self._show(entries)
        else:
            self._end(skipped=False)

    def _show(self, entries: list[QuitSave]) -> None:
        """The operations, each a line updated in place (from memory, every ``POLL_MS``)."""
        paths = list(dict.fromkeys(save.path for save in entries))
        count = len([path for path in paths if path not in (PRESETS_SAVING, TXY_LAST_USED)])  # (Their own entries.)
        saving = " and ".join(filter(None, (f"{count:,} folder{'' if count == 1 else 's'}" if count else "",
                                            "presets" if PRESETS_SAVING in paths else "")))
        # (The converted TXY's index may be under the temp folder, not the disk cache: Q~3, Nit-10.)
        doing = " and ".join(filter(None, (f"saving {saving} to the disk cache" if saving else "",
                                           "recording when converted TXY were last used"
                                           if TXY_LAST_USED in paths else "")))
        self.label.setText(f"{doing[:1].upper()}{doing[1:]} before HeLab quits:")
        now = time.monotonic()
        while self.folders.count() > len(entries):
            self.folders.takeItem(self.folders.count() - 1)
        for row, save in enumerate(entries):
            item = self.folders.item(row)
            if item is None:
                item = QListWidgetItem()
                self.folders.addItem(item)
            text = self.entry_text(save, now)
            if item.text() != text:
                item.setText(text)
            item.setToolTip(save.path)

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
