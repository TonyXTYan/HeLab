"""Settings → Data roots: the .helab-root locations HeLab has seen on this computer.

Like the Cache tab, it never opens the store: the list comes from a ``cache_admin inventory``
helper job, and Forget location is a ``forget_root`` job (``FolderCache.cache_admin``).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

from helab.utils.folder_cache import FolderCache, marker_path, store_options

INTRO = ("Folders holding a .helab-root that HeLab has seen on this computer. Each one identifies its folder "
         "and subfolders in the disk cache, whichever drive or share reaches them. Folders without one use "
         "RAM only.")
FORGET = "Forget location…"
FORGET_TOOLTIP = ("Forget location (found again if its .helab-root is still there). Its cached data and the "
                  "file itself stay.")
DECISIONS = {"confirmed": "In use", "pending": "Waiting: same folder or a copy?"}


class DataRootsTab(QWidget):
    COLUMNS = ("Data root", "Folder", "Status", "Last seen")

    def __init__(self, cache: FolderCache | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cache = cache
        self.enabled = bool(cache is not None and store_options())
        self.roots: list[dict[str, Any]] | None = None
        self.message = ""
        self._inventory_owner = ""
        self._job = ""
        self.confirm: Callable[[str, str, str], bool] = self._confirm
        layout = QVBoxLayout(self)
        layout.setSpacing(2)
        intro = QLabel(INTRO)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.list = QTreeWidget()
        self.list.setHeaderLabels(list(self.COLUMNS))
        self.list.setRootIsDecorated(False)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemSelectionChanged.connect(self._update)
        layout.addWidget(self.list, 1)
        footer = QHBoxLayout()
        self.status_label = QLabel("Checking…")
        footer.addWidget(self.status_label, 1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        footer.addWidget(self.refresh_button)
        self.forget_button = QPushButton(FORGET)
        self.forget_button.setToolTip(FORGET_TOOLTIP)
        self.forget_button.clicked.connect(self.forget_selected)
        footer.addWidget(self.forget_button)
        layout.addLayout(footer)
        if cache is not None:
            cache.cacheAdminResult.connect(self._on_result)
            cache.cacheAdminDone.connect(self._on_done)
        self._update()
        self.refresh()

    def detach(self) -> None:
        if self.cache is not None:
            self.cache.cacheAdminResult.disconnect(self._on_result)
            self.cache.cacheAdminDone.disconnect(self._on_done)
            self.cache = None

    def _confirm(self, title: str, text: str, verb: str) -> bool:
        box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=self)
        accept = box.addButton(verb, QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return box.clickedButton() is accept

    def refresh(self) -> None:
        if self.cache is None or not self.enabled or self._inventory_owner:
            return
        self._inventory_owner = self.cache.cache_admin("inventory")
        if not self._inventory_owner:
            self.message = "Disk cache queue full — Refresh to try again"
        self._update()

    def selected(self) -> dict[str, Any] | None:
        items = self.list.selectedItems()
        row = items[0].data(0, Qt.ItemDataRole.UserRole) if items else None
        return row if isinstance(row, dict) else None

    def forget_selected(self) -> None:
        row = self.selected()
        if row is None or self.cache is None or self._job:
            return
        where = row["path"] or row["location"]
        mounted = (f"\n\nIts .helab-root is still in that folder, so the next listing of it finds this location "
                   "again. Remove or rename the file there to stop using it.") if row["path"] else ""
        if not self.confirm("Forget this location?",
                            f"Forgets that data root “{row['label']}” was seen at {where}. Its cached data and "
                            f"the .helab-root file stay; folders there use RAM only until it is found again."
                            f"{mounted}", "Forget"):
            return
        self._job = self.cache.cache_admin("forget_root", location=row["location"])
        self.message = "" if self._job else "Disk cache queue full — try again"
        self._update()

    def _on_result(self, action: str, event: dict[str, Any]) -> None:
        if action == "inventory" and event.get("kind") == "inventory":
            roots = event["inventory"].get("roots")
            if roots is None:
                self.message = "Could not read the data roots"
            else:
                self.roots = list(roots)
            self._fill()

    def _on_done(self, owner: str, action: str, message: str) -> None:
        if owner == self._inventory_owner:
            self._inventory_owner = ""
            if message:
                self.message = f"Could not read the disk cache: {message}"
        elif owner == self._job:
            self._job = ""
            self.message = f"Forget location failed: {message}" if message else ""
            self.refresh()
        else:
            return
        self._update()

    def _fill(self) -> None:
        self.list.clear()
        for row in self.roots or ():
            folder = row["path"]
            item = QTreeWidgetItem([
                row["label"], folder or f"Not mounted · {row['location']}",
                DECISIONS.get(row["decision"], row["decision"]),
                f"{datetime.fromtimestamp(row['last_seen']):%Y-%m-%d %H:%M}"])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            item.setToolTip(0, f"{row['label']} · {row['uuid']}")
            item.setToolTip(1, "\n".join(filter(None, (marker_path(folder) if folder else "",
                                                        f"Location: {row['location']}"))))
            first = datetime.fromtimestamp(row["first_seen"])
            item.setToolTip(3, f"First seen {first:%Y-%m-%d %H:%M}")
            self.list.addTopLevelItem(item)
        for column in range(len(self.COLUMNS)):
            self.list.resizeColumnToContents(column)
        self._update()

    def _update(self) -> None:
        if not self.enabled:
            text = "The disk cache is off for this session"
        elif self.message:
            text = self.message
        elif self.roots is None:
            text = "Checking…"
        else:
            count = len(self.roots)
            text = f"{count:,} location{'' if count == 1 else 's'}" if count else (
                "None yet: right-click a folder › Place .helab-root here…")
        self.status_label.setText(text)
        idle = self.enabled and not self._job and not self._inventory_owner
        self.refresh_button.setEnabled(self.enabled and not self._inventory_owner)
        self.forget_button.setEnabled(idle and self.selected() is not None)
