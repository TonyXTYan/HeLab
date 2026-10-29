"""Settings → Data roots: the .helab-root locations HeLab has seen on this computer.

Like the Cache tab, it never opens the store: the list comes from a ``cache_admin inventory``
helper job, Forget location is a ``forget_root`` job (``FolderCache.cache_admin``), and Delete
.helab-root… a foreground ``root_remove`` job. Show in Finder only launches the file manager.
"""
from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, Callable

from PyQt6.QtCore import QPoint, QProcess, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
                             QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from helab.utils import folder_cache
from helab.utils.folder_cache import OFFLINE_TOOLTIP, FolderCache, marker_path
from helab.utils.number_format import byte_size
from helab.utils.io_service import IORequest

INTRO = ("Folders holding a .helab-root that HeLab has seen on this computer. Each one identifies its folder "
         "and subfolders in the disk cache, whichever drive or share reaches them. Folders without one use "
         "RAM only.")
FORGET = "Forget location…"
FORGET_TOOLTIP = ("Forget location (found again if its .helab-root is still there). Its cached data and the "
                  "file itself stay.")
DECISIONS = {"confirmed": "In use", "pending": "Waiting: same folder or a copy?"}
DELETE = "Delete .helab-root…"
DELETE_TOOLTIP = "Delete this folder's .helab-root file: the folder and its subfolders use RAM only until one is placed again"
NOT_MOUNTED_TOOLTIP = "Not mounted on this computer now"
DELETE_TEXT = ("Deletes {marker}. This folder and its subfolders use RAM only on every computer until a "
               ".helab-root is placed again. Their cached data stays on this computer under this root's ID; "
               "a new marker gets a new ID and starts fresh. Other computers that use this drive lose their "
               "disk cache for it too.")
CLEAR = "Clear cached data…"
CLEAR_TOOLTIP = ("Clear what this computer cached below this data root (datasets and saved folder status). "
                 "The .helab-root, folder flags and cached analysis stay.")
# Saved analysis results below the root (result caching R2), apart from its cached data (Tony, 2026-10-22).
CLEAR_RESULTS = "Clear cached analysis…"
CLEAR_RESULTS_TOOLTIP = ("Clear the analysis results this computer saved below this data root (plots compute them "
                         "again). Its cached data and the .helab-root stay.")
REVIEW = "Review…"
REVIEW_TOOLTIP = "Same folder or a copy? This location uses RAM only until answered"
DETAIL_NONE = "Select a location to see its .helab-root's path and UUID"
NOT_MOUNTED = "Not mounted"
REFUSED_TEXT = ("HeLab can't delete {file} ({reason}). Delete it by hand ({show} finds it), then Refresh "
                "this list.")


def show_label() -> str:
    return {"darwin": "Show in Finder", "win32": "Show in File Explorer"}.get(sys.platform, "Show in File Manager")


def show_tooltip() -> str:
    hidden = {"darwin": "press Cmd+Shift+. in Finder to see it",
              "win32": "View › Show › Hidden items shows it"}.get(sys.platform, "show hidden files to see it")
    return f"Shows the .helab-root file, which is hidden: {hidden}"


def show_command(marker: str) -> tuple[str, list[str]] | None:
    """The file manager revealing ``marker``; None to open its folder instead (Linux)."""
    if sys.platform == "darwin":
        return "open", ["-R", marker]
    if sys.platform == "win32":
        return "explorer", ["/select,", marker]
    return None


class DataRootsTab(QWidget):
    # No folder column (Tony, 2026-10-19): the long path would scroll the list sideways. The two lines
    # below the list show the selected row's full path and UUID.
    COLUMNS = ("Data root", "Status", "Last seen", "Cached")
    LABEL, STATUS, SEEN, CACHED = range(4)
    reviewRequested = pyqtSignal(str)  # A pending location: RootDuplicatesWindow at it.

    def __init__(self, cache: FolderCache | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cache = cache
        self.enabled = bool(cache is not None and folder_cache.store_options())
        self.roots: list[dict[str, Any]] | None = None
        self.message = ""
        self._inventory_owner = ""
        self._job = ""
        self._job_name = ""
        self._remove_job = ""
        self.owner = f"data-roots-{id(self)}"
        self.confirm: Callable[[str, str, str], bool] = self._confirm
        # Replaceable in tests: launching the file manager (never waited for), and a message box.
        self.launch: Callable[[str, list[str]], bool] = lambda program, arguments: QProcess.startDetached(
            program, arguments)[0]
        self.open_folder: Callable[[str], bool] = lambda folder: QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        self.alert: Callable[[str], None] = self._alert
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
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.list, 1)
        # Read-only and frameless: lines that select and scroll, whatever the path's length.
        self.path_line, self.uuid_line = QLineEdit(), QLineEdit()
        for line in (self.path_line, self.uuid_line):
            line.setReadOnly(True)
            line.setFrame(False)
            line.setStyleSheet("background: transparent")
            layout.addWidget(line)
        self.path_line.setPlaceholderText(DETAIL_NONE)
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
        self.delete_button = QPushButton(DELETE)
        self.delete_button.setToolTip(DELETE_TOOLTIP)
        self.delete_button.clicked.connect(self.delete_selected)
        footer.addWidget(self.delete_button)
        self.clear_button = QPushButton(CLEAR)
        self.clear_button.setToolTip(CLEAR_TOOLTIP)
        self.clear_button.clicked.connect(self.clear_selected)
        footer.addWidget(self.clear_button)
        self.clear_results_button = QPushButton(CLEAR_RESULTS)
        self.clear_results_button.setToolTip(CLEAR_RESULTS_TOOLTIP)
        self.clear_results_button.clicked.connect(self.clear_results_selected)
        footer.addWidget(self.clear_results_button)
        self.review_button = QPushButton(REVIEW)
        self.review_button.setToolTip(REVIEW_TOOLTIP)
        self.review_button.clicked.connect(self.review_selected)
        footer.addWidget(self.review_button)
        layout.addLayout(footer)
        if cache is not None:
            cache.cacheAdminResult.connect(self._on_result)
            cache.cacheAdminDone.connect(self._on_done)
            cache.resultReady.connect(self._on_remove)
            cache.offlineChanged.connect(self._offline_changed)
        self._update()
        self.refresh()

    def detach(self) -> None:
        if self.cache is not None:
            self.cache.cacheAdminResult.disconnect(self._on_result)
            self.cache.cacheAdminDone.disconnect(self._on_done)
            self.cache.resultReady.disconnect(self._on_remove)
            self.cache.offlineChanged.disconnect(self._offline_changed)
            self.cache = None

    @property
    def offline(self) -> bool:
        """Work Offline: Show in Finder and Delete .helab-root… would reach the folder (D6)."""
        return self.cache is not None and self.cache.offline

    def _offline_changed(self, _offline: bool) -> None:
        self._update()

    def _confirm(self, title: str, text: str, verb: str) -> bool:
        box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=self)
        accept = box.addButton(verb, QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton(QMessageBox.StandardButton.Cancel)
        if cancel is not None:
            box.setDefaultButton(cancel)  # Return never forgets or deletes.
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
        row = items[0].data(self.LABEL, Qt.ItemDataRole.UserRole) if items else None
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
        self._job_name = "Forget location"
        self.message = "" if self._job else "Disk cache queue full — try again"
        self._update()

    def _alert(self, text: str) -> None:
        box = QMessageBox(QMessageBox.Icon.Warning, DELETE.removesuffix("…"), text, parent=self)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.open()

    def _context_menu(self, position: QPoint) -> None:
        item = self.list.itemAt(position)
        if item is None:
            return
        self.list.setCurrentItem(item)
        if (viewport := self.list.viewport()) is not None:
            self.context_menu().exec(viewport.mapToGlobal(position))

    def context_menu(self) -> QMenu:
        """The selected row's menu: Show, Copy path, Forget location…, Delete .helab-root…."""
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        row = self.selected()
        mounted = bool(row and row["path"])
        show = menu.addAction(show_label(), self.show_selected)
        copy = menu.addAction("Copy path", self.copy_selected)
        menu.addSeparator()
        review = menu.addAction(REVIEW, self.review_selected) if self.review_button.isEnabled() else None
        clear = menu.addAction(CLEAR, self.clear_selected)
        clear_results = menu.addAction(CLEAR_RESULTS, self.clear_results_selected)
        forget = menu.addAction(FORGET, self.forget_selected)
        delete = menu.addAction(DELETE, self.delete_selected)
        for action, enabled, tooltip in (
                (show, mounted and not self.offline, OFFLINE_TOOLTIP if self.offline else
                 show_tooltip() if mounted else NOT_MOUNTED_TOOLTIP),
                (copy, row is not None, "The .helab-root file's path" if mounted else "The location"),
                (review, True, REVIEW_TOOLTIP),
                (clear, self.clear_button.isEnabled(), CLEAR_TOOLTIP),
                (clear_results, self.clear_results_button.isEnabled(), CLEAR_RESULTS_TOOLTIP),
                (forget, self.forget_button.isEnabled(), FORGET_TOOLTIP),
                (delete, self.delete_button.isEnabled(), OFFLINE_TOOLTIP if self.offline else
                 DELETE_TOOLTIP if mounted else NOT_MOUNTED_TOOLTIP)):
            if action is not None:
                action.setEnabled(enabled)
                action.setToolTip(tooltip)
        return menu

    def show_selected(self) -> bool:
        """Reveal the row's marker in the file manager, without waiting or touching the folder."""
        row = self.selected()
        if row is None or not row["path"] or self.offline:
            return False
        marker = marker_path(row["path"])
        command = show_command(marker)
        return self.launch(*command) if command is not None else self.open_folder(row["path"])

    def copy_selected(self) -> None:
        row = self.selected()
        if row is not None and (clipboard := QApplication.clipboard()) is not None:
            clipboard.setText(marker_path(row["path"]) if row["path"] else row["location"])

    def review_selected(self) -> None:
        if (row := self.selected()) is not None and row["decision"] == "pending":
            self.reviewRequested.emit(row["location"])

    def clear_selected(self) -> None:
        row = self.selected()
        if row is None or self.cache is None or self._job:
            return
        cached = row.get("cached")
        what = (f"{cached['folders']:,} cached folder{'' if cached['folders'] == 1 else 's'} "
                f"({byte_size(cached['bytes'], 'disk')})" if cached else "the cached data")
        if not self.confirm("Clear this data root's cached data?",
                            f"Clears {what} for data root “{row['label']}” on this computer. "
                            "The .helab-root, folder flags and cached analysis stay.", "Clear"):
            return
        self._job = self.cache.cache_admin("clear_root", uuid=row["uuid"])
        self._job_name = "Clear cached data"
        self.message = "" if self._job else "Disk cache queue full — try again"
        self._update()

    def clear_results_selected(self) -> None:
        """Clear cached analysis: the results saved below this root, nothing else (asks first)."""
        row = self.selected()
        if row is None or self.cache is None or self._job:
            return
        cached = row.get("cached") or {}
        count = int(cached.get("results", 0))
        what = (f"{count:,} saved result{'' if count == 1 else 's'} ({byte_size(int(cached.get('result_bytes', 0)), 'disk')})"
                if count else "the saved analysis results")
        if not self.confirm("Clear this data root's cached analysis?",
                            f"Clears {what} for data root “{row['label']}” on this computer: plots compute them "
                            "again. Its cached data, the .helab-root and folder flags stay.", "Clear"):
            return
        self._job = self.cache.cache_admin("clear_root_results", uuid=row["uuid"])
        self._job_name = "Clear cached analysis"
        self.message = "" if self._job else "Disk cache queue full — try again"
        self._update()

    def delete_selected(self) -> None:
        row = self.selected()
        if row is None or not row["path"] or self.cache is None or self._job or self.offline:
            return
        if not self.confirm("Delete this .helab-root?", DELETE_TEXT.format(marker=marker_path(row["path"])),
                            "Delete"):
            return
        if self.cache.remove_root(self.owner, row["path"], row["uuid"], row["location"]):
            self._job = self._remove_job = row["path"]
            self.message = ""
        else:
            self.message = "The I/O queue is full — try again"
        self._update()

    def _on_remove(self, request: IORequest, event: dict[str, Any]) -> None:
        if request.owner != self.owner or request.operation != "root_remove":
            return
        kind = event["kind"]
        if kind == "root_removed":
            self.message = f"Deleted {marker_path(str(event['path']))}"
        elif kind == "root_remove_refused":
            text = REFUSED_TEXT.format(file=event["file"], reason=event["reason"], show=show_label())
            self.message = f"Could not delete {event['file']}"
            self.alert(text)
        elif kind == "error":
            self.message = f"Delete .helab-root failed: {event.get('message', '')}"
            self.alert(str(event.get("message", "")))
        if kind in ("done", "error", "cancelled") and self._job == self._remove_job:
            self._job = self._remove_job = ""
            self.refresh()
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
            self.message = f"{self._job_name} failed: {message}" if message else ""
            self.refresh()
        else:
            return
        self._update()

    def _fill(self) -> None:
        self.list.clear()
        for row in self.roots or ():
            folder = row["path"]
            status = DECISIONS.get(row["decision"], row["decision"])
            item = QTreeWidgetItem([
                row["label"], status if folder or row["decision"] != "confirmed" else NOT_MOUNTED,
                f"{datetime.fromtimestamp(row['last_seen']):%Y-%m-%d %H:%M}",
                byte_size(row["cached"]["bytes"], "disk") if row.get("cached") and row["cached"]["folders"] else "—"])
            item.setData(self.LABEL, Qt.ItemDataRole.UserRole, row)
            item.setToolTip(self.LABEL, marker_path(folder) if folder
                            else f"{NOT_MOUNTED_TOOLTIP} · {row['location']}")
            if not folder:  # Greyed: not mounted now.
                for column in range(len(self.COLUMNS)):
                    item.setForeground(column, self.palette().placeholderText())
            first = datetime.fromtimestamp(row["first_seen"])
            item.setToolTip(self.SEEN, f"First seen {first:%Y-%m-%d %H:%M}")
            cached = row.get("cached")
            results = int(cached.get("results", 0)) if cached else 0
            item.setToolTip(self.CACHED, (f"{cached['folders']:,} folders cached below this data root on this "
                                          "computer" if cached and cached["folders"] else
                                          "No data cached below this data root on this computer")
                            + (f"\nCached analysis: {results:,} saved result{'' if results == 1 else 's'} "
                               f"({byte_size(int(cached.get('result_bytes', 0)), 'disk')})" if cached and results else ""))
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
                "None yet: right-click a folder › Place .helab-root here…, or File › Place .helab-root…")
        self.status_label.setText(text)
        idle = self.enabled and not self._job and not self._inventory_owner
        self.refresh_button.setEnabled(self.enabled and not self._inventory_owner)
        row = self.selected()
        self.forget_button.setEnabled(idle and row is not None)
        self.delete_button.setEnabled(idle and row is not None and bool(row["path"]) and not self.offline)
        self.delete_button.setToolTip(OFFLINE_TOOLTIP if self.offline else
                                      DELETE_TOOLTIP if row is None or row["path"] else NOT_MOUNTED_TOOLTIP)
        self.clear_button.setEnabled(idle and row is not None)
        self.clear_results_button.setEnabled(idle and row is not None)
        self.review_button.setEnabled(row is not None and row["decision"] == "pending")
        for line, text in zip((self.path_line, self.uuid_line), self.detail_lines(row)):
            if line.text() != text:
                line.setText(text)
                line.setCursorPosition(0)
        self.path_line.setToolTip(f"Location: {row['location']}" if row is not None else "")

    @staticmethod
    def detail_lines(row: dict[str, Any] | None) -> tuple[str, str]:
        """The selected row's full .helab-root path (or where it was last seen), and its UUID."""
        if row is None:
            return "", ""
        path = marker_path(row["path"]) if row["path"] else f"{NOT_MOUNTED} · last seen at {row['location']}"
        return path, f"UUID {row['uuid']}"
