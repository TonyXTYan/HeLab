"""Same folder or a copy? One window for the whole app listing the locations whose .helab-root is
also at another location (data roots, D4).

A listing that finds a marker whose UUID another confirmed location already has records the new
location as pending (``io_ops.markers._discover_root``'s ``root_duplicate``): it uses RAM only until the
user answers here. Same folder confirms it (``cache_admin root_same``); It's a copy… gives one side a
new marker (``root_reassign``), and the side keeping the original UUID keeps the cached data.
The window opens once per location per session (``FolderCache.rootDuplicateFound``); Later reopens
it at that location's next sighting, Remind me next session keeps it quiet until then.
"""
from __future__ import annotations

from datetime import datetime
import os
from typing import Any
from uuid import uuid4

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (QAbstractItemView, QButtonGroup, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                             QMessageBox, QPushButton, QRadioButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                             QWidget)

from helab.utils.accessible import identify, identify_buttons
from helab.utils.folder_cache import OFFLINE_TOOLTIP, FolderCache
from helab.utils.io_service import IORequest

TITLE = "Same folder or a copy?"
INTRO = ("HeLab found the same .helab-root at more than one location. If they are the same folder (another "
         "share, mapped drive or server name), they share one disk cache. If one is a copy, it gets its own "
         ".helab-root. Until you answer, the new location uses RAM only.")
SAME_TIP = "Both locations use one disk cache."
COPY_TIP = "Choose which location keeps the cached data; the other gets a new .helab-root and starts empty."
LATER_TIP = "Close; this asks again the next time HeLab finds that location this session."
SNOOZE_TIP = ("Don't ask again this session. The status bar still shows how many are waiting; the location "
              "stays RAM only.")
COPY_TEXT = "The other gets a new .helab-root and starts with an empty cache."
ANSWERS = {"": "Not answered", "later": "Later", "snoozed": "Next session"}


def _where(path: str, location: str) -> str:
    return f"{path}  ({location})" if path else f"Not mounted  ({location})"


def _server(location: str) -> str:
    scheme, _, rest = location.partition("://")
    return f"{scheme}://{rest.split('/', 1)[0]}"


def duplicate_hints(entry: dict[str, Any]) -> str:
    """Hints whether the locations are one folder: server and the marker files' details. The user decides.

    A copy keeps the marker's size and modified time (cp -p, rsync -a, Finder), so identical markers
    aren't evidence of one folder. The file number is, but only on one server: device numbers differ
    for every mount, and other servers number their files independently."""
    others = entry.get("others") or []
    if not others:
        return ""
    other = others[0]
    same_server = _server(str(entry["location"])) == _server(str(other["location"]))
    hints = ["same server" if same_server else "different server"]
    mine, theirs = entry.get("marker"), other.get("marker")
    if isinstance(mine, dict) and isinstance(theirs, dict):
        if same_server and mine.get("ino") and theirs.get("ino"):
            hints.append("same file number on the server" if mine["ino"] == theirs["ino"]
                         else "different file number on the server")
        if mine["size"] == theirs["size"] and abs(float(mine["mtime"]) - float(theirs["mtime"])) < 1.0:
            hints.append("marker identical (a copy would be too)")
        else:
            hints.append("markers differ")
    return " · ".join(hints)


class CopyRootDialog(QDialog):
    """It's a copy…: which location keeps the cached data (the known one by default)."""

    def __init__(self, parent: QWidget | None, entry: dict[str, Any]) -> None:
        super().__init__(parent)
        self.setWindowTitle("It's a copy")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Keep the cached data with:"))
        self.group = QButtonGroup(self)
        self.choices: dict[QRadioButton, str] = {}
        known = (entry.get("others") or [{}])[0]
        mounted = any(other.get("path") for other in entry.get("others") or [])
        for ident, (location, path, enabled) in zip(("keep_known", "keep_new"), (
                (str(known.get("location", "")), str(known.get("path", "")), True),
                (str(entry["location"]), str(entry["path"]), mounted))):
            button = identify(QRadioButton(_where(path, location)), f"copy_{ident}")
            button.setEnabled(enabled and bool(location))
            if not enabled:
                button.setToolTip("Keeping it here gives the known folder a new .helab-root, but it isn't "
                                  "mounted now.")
            self.group.addButton(button)
            self.choices[button] = location
            layout.addWidget(button)
        first = next(iter(self.choices))
        first.setChecked(first.isEnabled())
        layout.addWidget(QLabel(COPY_TEXT))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        make = buttons.addButton("Make it a copy", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.make = make
        identify_buttons(buttons, "copy")
        layout.addWidget(buttons)

    def keep(self) -> str | None:
        checked = self.group.checkedButton()
        return self.choices.get(checked) if isinstance(checked, QRadioButton) else None


class RootDuplicatesWindow(QDialog):
    COLUMNS = ("Data root", "New location", "Known at", "Hints", "Answer")

    def __init__(self, cache: FolderCache, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cache = cache
        self.owner = f"root-duplicates-{uuid4().hex}"
        self.setWindowTitle(TITLE)
        self.setModal(False)
        self.resize(820, 320)
        layout = QVBoxLayout(self)
        intro = QLabel(INTRO)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.tree = identify(QTreeWidget(), "root_duplicates_list", "Data roots to confirm",
                             "The locations whose .helab-root is also elsewhere")
        self.tree.setHeaderLabels(list(self.COLUMNS))
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.tree, 1)
        buttons = QHBoxLayout()
        self.same_button = identify(QPushButton("Same folder"), "root_same")
        self.same_button.setToolTip(SAME_TIP)
        self.copy_button = identify(QPushButton("It's a copy…"), "root_copy")
        self.copy_button.setToolTip(COPY_TIP)
        self.later_button = identify(QPushButton("Later"), "root_later")
        self.later_button.setToolTip(LATER_TIP)
        self.snooze_button = identify(QPushButton("Remind me next session"), "root_snooze")
        self.snooze_button.setToolTip(SNOOZE_TIP)
        for button in (self.same_button, self.copy_button, self.later_button, self.snooze_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        close = identify(QPushButton("Close"), "root_close")
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.same_button.clicked.connect(self.same)
        self.copy_button.clicked.connect(self.copy)
        self.later_button.clicked.connect(lambda: self._answer("later"))
        self.snooze_button.clicked.connect(lambda: self._answer("snoozed"))
        close.clicked.connect(self.close)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        cache.rootDuplicatesChanged.connect(self.refresh)
        cache.rootDuplicateFound.connect(self._found)
        cache.resultReady.connect(self._result)
        # Work Offline: It's a copy… writes a marker in the folder (D6).
        cache.offlineChanged.connect(self._offline_changed)
        # Replaceable in tests: It's a copy…'s choice of the location keeping the data.
        self.choose_keep = self._choose_keep
        self.refresh()

    def selected(self) -> str | None:
        items = self.tree.selectedItems()
        return str(items[0].data(0, Qt.ItemDataRole.UserRole)) if items else None

    def show_list(self, activate: bool = True, select: str | None = None) -> None:
        """Show the window; a location found while browsing only appears, without taking the focus."""
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, not activate)
        self.show()
        self.refresh()
        if select is not None or self.selected() is None:
            for index in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(index)
                if item is not None and (select is None or item.data(0, Qt.ItemDataRole.UserRole) == select):
                    self.tree.setCurrentItem(item)
                    break
        if activate:
            self.raise_()
            self.activateWindow()

    def _found(self, location: str) -> None:
        self.show_list(activate=False, select=location)

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        # Closed unanswered: as Later, so each asks again at its next sighting.
        for location, entry in list(self.cache.root_duplicates.items()):
            if not entry["answer"]:
                self.cache.answer_root_duplicate(location, "later")
        super().closeEvent(a0)

    def _answer(self, answer: str) -> None:
        if (location := self.selected()) is not None:
            self.cache.answer_root_duplicate(location, answer)
            if not any(not entry["answer"] for entry in self.cache.root_duplicates.values()):
                self.hide()  # Nothing left to answer now; hiding doesn't mark the rest Later.

    def same(self) -> None:
        if (location := self.selected()) is not None and not self.cache.same_root(location):
            QMessageBox.warning(self, TITLE, "The disk cache is busy; try again.")

    def _choose_keep(self, entry: dict[str, Any]) -> str | None:
        dialog = CopyRootDialog(self, entry)
        return dialog.keep() if dialog.exec() == QDialog.DialogCode.Accepted else None

    def copy(self) -> None:
        location = self.selected()
        entry = self.cache.root_duplicates.get(location or "")
        if location is None or entry is None or self.cache.offline:
            return
        keep = self.choose_keep(entry)
        if keep and not self.cache.reassign_root(self.owner, 0, location, keep):
            QMessageBox.warning(self, TITLE, "The folder to give a new .helab-root isn't mounted now.")

    def _result(self, request: IORequest, event: dict[str, Any]) -> None:
        if request.owner != self.owner:
            return
        from helab.views.DataRootDialogs import ManualMarkerDialog
        if event["kind"] == "root_manual":
            ManualMarkerDialog(self, self.cache, str(event["path"]), str(event["name"]),
                               str(event["contents"]), str(event.get("reason", ""))).show()
        elif event["kind"] == "error":
            box = QMessageBox(QMessageBox.Icon.Warning, TITLE, str(event.get("message", "")), parent=self)
            box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            box.open()

    def refresh(self) -> None:
        selected = self.selected()
        self.tree.clear()
        for location, entry in reversed(self.cache.root_duplicates.items()):  # Newest first.
            others = entry.get("others") or []
            known = "\n".join(_where(str(other.get("path", "")), str(other["location"])) for other in others)
            label = str(entry.get("label") or os.path.basename(str(entry["path"])))
            item = QTreeWidgetItem([label, _where(str(entry["path"]), location), known.split("\n")[0],
                                    duplicate_hints(entry), ANSWERS.get(str(entry["answer"]), "")])
            item.setData(0, Qt.ItemDataRole.UserRole, location)
            found = datetime.fromtimestamp(float(entry.get("found_at", 0)))
            tip = (f"{label}: this .helab-root is also at another location\nNew: "
                   f"{_where(str(entry['path']), location)}\nKnown: {known}\nFound {found:%H:%M:%S}")
            for column in range(len(self.COLUMNS)):
                item.setToolTip(column, tip)
            self.tree.addTopLevelItem(item)
            if location == selected:
                self.tree.setCurrentItem(item)
        for column in range(len(self.COLUMNS) - 1):
            self.tree.resizeColumnToContents(column)
        self._update_buttons()

    def _offline_changed(self, _offline: bool) -> None:
        self._update_buttons()

    def _update_buttons(self) -> None:
        chosen = self.selected() is not None
        for button in (self.same_button, self.copy_button, self.later_button, self.snooze_button):
            button.setEnabled(chosen)
        if self.cache.offline:
            self.copy_button.setEnabled(False)
        self.copy_button.setToolTip(OFFLINE_TOOLTIP if self.cache.offline else COPY_TIP)
