"""Lists the folders whose cached data doesn't match them, in one window for the whole app.

TXY files are written once and never deleted, so shots HeLab cached (or loaded) that a folder no
longer has mean another folder now sits at that path, or files were deleted or renamed. A load
stops before reading anything (``io_helper.load``'s ``shots_missing``) and a scan reports it
(``cache_mismatch``); ``FolderCache.mismatched`` keeps them for the session. New folders are added
to this window as they are found, instead of one popup each. When the session's count reaches
2, 4, 8…, loads and scans are held (``IOService.mismatch_hold``) until the user resumes, cancels
them or (from ``FolderCache.SKIP_MISMATCHED_FROM``) skips mismatched folders for the session.
"""
from __future__ import annotations

from datetime import datetime
import os
from typing import Any

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QShowEvent
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from helab.utils.folder_cache import FolderCache

INTRO = ("TXY files are written once and never deleted, so shots missing from a folder HeLab cached mean "
         "another folder may have been moved to that path, or files were deleted or renamed. Nothing was "
         "loaded from these folders, and their cached data isn't shown.")
LOAD_TIP = ("Read the selected folders' TXY files as they are now, and replace their old cached data with "
            "the result. Shots no longer in a folder are dropped. The selected folder in the current tab "
            "loads at once; others are queued.")
SKIP_TIP = ("Load nothing from the selected folders for now. They stay listed, and their old cached data "
            "stays on disk, unused this session. Retry or Load data checks a folder again.")
RESUME_TIP = "Let the paused loads and scans go on. Mismatched folders found later are added here."
CANCEL_TIP = ("Cancel every load and scan, running, paused or queued. Browsing and cached data stay "
              "available; loads already saving their cached data finish.")
SKIP_ALL_TIP = ("For the rest of this session, list mismatched folders here without opening this window or "
                "pausing loads and scans again. Their data is still not loaded; the status bar shows how many.")
ANSWERS = {"": "Not answered", "dont_load": "Not loaded", "load": "Loading as it is now"}


def _name(path: str) -> str:
    return os.path.basename(path.rstrip("/\\")) or path


def _plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def missing_text(path: str, entry: dict[str, Any]) -> str:
    """What was found in one folder, for its row's tooltip."""
    missing = [int(shot) for shot in entry.get("missing", [])]
    count = int(entry.get("missing_count", len(missing)))
    shown = ", ".join(str(shot) for shot in missing[:10]) + (", …" if count > min(10, len(missing)) else "")
    found_by = "a folder status check" if entry.get("source") == "scan" else "a load"
    return (f"{path}\n{count} of the {int(entry.get('known_count', count))} shots HeLab had for it (cached or "
            f"loaded) are no longer in the folder: {'shot' if count == 1 else 'shots'} {shown}. "
            f"It now has {_plural(int(entry.get('listed_count', 0)), 'TXY file')}. Found by {found_by}.")


class MissingShotsWindow(QDialog):
    """Mismatched folders (newest first) with the user's answer for each, and the hold of loads
    and scans. Not modal: browsing goes on while it is open, and new folders are appended."""
    # Folders to load as they are now: the main window asks the current tab to load them.
    loadRequested = pyqtSignal(list)
    COLUMNS = ("Folder", "Missing shots", "Folder now", "Found", "Answer")
    # Changes are applied at most this often while the window is open (a large scan may find
    # many folders), and when it opens.
    REFRESH_MS = 200

    def __init__(self, cache: FolderCache, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cache = cache
        # Closed by the user: folders found later don't open it again until the next warning.
        self.dismissed = False
        self.setWindowTitle("Cached data doesn't match these folders")
        self.setModal(False)
        self.resize(760, 360)
        layout = QVBoxLayout(self)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet("QLabel { background: #fff3cd; color: #5c4400; padding: 6px; }")
        layout.addWidget(self.banner)
        banner_buttons = QHBoxLayout()
        self.resume_button = QPushButton("Resume")
        self.resume_button.setToolTip(RESUME_TIP)
        self.cancel_button = QPushButton("Cancel all loads and scans")
        self.cancel_button.setToolTip(CANCEL_TIP)
        self.skip_all_button = QPushButton("Skip mismatched folders and keep going")
        self.skip_all_button.setToolTip(SKIP_ALL_TIP)
        for button in (self.resume_button, self.cancel_button, self.skip_all_button):
            banner_buttons.addWidget(button)
        banner_buttons.addStretch(1)
        layout.addLayout(banner_buttons)
        self.intro = QLabel(INTRO)
        self.intro.setWordWrap(True)
        layout.addWidget(self.intro)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(list(self.COLUMNS))
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.tree, 1)
        buttons = QHBoxLayout()
        self.load_button = QPushButton("Load as it is now")
        self.load_button.setToolTip(LOAD_TIP)
        self.skip_button = QPushButton("Don't load")
        self.skip_button.setToolTip(SKIP_TIP)
        self.close_button = QPushButton("Close")
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.skip_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self.resume_button.clicked.connect(cache.resume_after_mismatch)
        self.cancel_button.clicked.connect(cache.cancel_held_io)
        self.skip_all_button.clicked.connect(cache.skip_mismatches)
        self.load_button.clicked.connect(self._load)
        self.skip_button.clicked.connect(lambda: cache.answer_mismatches(self.selected_paths(), "dont_load"))
        self.close_button.clicked.connect(self.close)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh)
        cache.mismatchesChanged.connect(self._schedule_refresh)
        cache.mismatchFound.connect(self._found)
        cache.mismatchWarning.connect(self._warning)
        self.refresh()

    def selected_paths(self) -> list[str]:
        return [str(item.data(0, Qt.ItemDataRole.UserRole)) for item in self.tree.selectedItems()]

    def show_list(self, activate: bool = True) -> None:
        """Show the window; ``activate`` also brings it to the front with the keyboard focus (a
        folder found while browsing only appears, without taking the focus)."""
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, not activate)
        self.show()
        if activate:
            self.raise_()
            self.activateWindow()

    def _found(self, _path: str) -> None:
        if not (self.dismissed or self.cache.skip_mismatched):
            self.show_list(activate=False)

    def _warning(self, _count: int) -> None:
        self.dismissed = False
        self.show_list(activate=True)

    def _schedule_refresh(self) -> None:
        if self.isVisible() and not self._refresh_timer.isActive():
            self._refresh_timer.start(self.REFRESH_MS)

    def showEvent(self, a0: QShowEvent | None) -> None:
        self.refresh()
        super().showEvent(a0)

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        self.dismissed = True
        super().closeEvent(a0)

    def _load(self) -> None:
        paths = self.selected_paths()
        if paths:
            self.loadRequested.emit(paths)

    def refresh(self) -> None:
        cache = self.cache
        held = cache.service.mismatch_hold
        count = cache.mismatch_count
        if held:
            self.banner.setText(
                f"⚠ Cached data doesn't match {_plural(count, 'folder')} this session, so loads and scans are "
                "paused. Check that the right drive is mounted and that run folders haven't been moved, "
                "then Resume or cancel them.")
        elif cache.skip_mismatched:
            self.banner.setText("Skipping mismatched folders for this session: they are listed here, and loads "
                                "and scans aren't paused for them.")
        self.banner.setVisible(held or cache.skip_mismatched)
        self.resume_button.setVisible(held)
        self.cancel_button.setVisible(held)
        self.skip_all_button.setVisible(held and count >= cache.SKIP_MISMATCHED_FROM)
        selected = set(self.selected_paths())
        self.tree.clear()
        for path, entry in reversed(cache.mismatched.items()):  # Newest first.
            found = datetime.fromtimestamp(float(entry.get("found_at", 0)))
            item = QTreeWidgetItem([
                _name(path),
                f"{int(entry.get('missing_count', 0)):,} of {int(entry.get('known_count', 0)):,}",
                _plural(int(entry.get("listed_count", 0)), "TXY file"),
                f"{found:%H:%M:%S} · {'scan' if entry.get('source') == 'scan' else 'load'}",
                ANSWERS.get(str(entry.get("answer", "")), "")])
            item.setData(0, Qt.ItemDataRole.UserRole, path)
            tip = missing_text(path, entry)
            for column in range(len(self.COLUMNS)):
                item.setToolTip(column, tip)
            self.tree.addTopLevelItem(item)
            item.setSelected(path in selected)
        for column in range(len(self.COLUMNS) - 1):
            self.tree.resizeColumnToContents(column)
        self._update_buttons()

    def _update_buttons(self) -> None:
        any_selected = bool(self.tree.selectedItems())
        self.load_button.setEnabled(any_selected)
        self.skip_button.setEnabled(any_selected)
