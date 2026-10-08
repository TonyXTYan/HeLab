"""A filesystem tree whose Qt queries only read memory.

Directory discovery and status computation belong to IOService's helper
processes. Native icons are supplied by a separate helper and held in memory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
import os
import time
from typing import Any, Iterator, cast, overload
from uuid import uuid4

from PyQt6.QtCore import QAbstractItemModel, QModelIndex, QObject, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import QApplication, QStyle, QTreeView

from helab.models.StatusReport import StatusReport
from helab.resources.icons import StatusIcons
from helab.utils.io_service import IORequest, IOService, get_io_service
from helab.utils.folder_cache import SCANS, get_folder_cache
from helab.utils.caching_setup import load_cache_param
from helab.utils.constants import DIR_CACHES
from helab.utils.time_format import relative_age
from helab.utils.scan_history import folder_identity
from helab.utils.cache_freshness import CacheFreshness, cache_freshness, data_as_of, freshness_tooltip, metadata_date


@dataclass(eq=False)
class FolderNode:
    path: str
    parent: FolderNode | None = None
    row: int = 0
    children: list[FolderNode] = field(default_factory=list)
    loaded: bool = False
    state: str = "idle"
    error: str = ""
    modified: float | None = None
    modified_observed_at: float | None = None
    scanned_at: float | None = None
    report: StatusReport | None = None
    signature: str = ""
    checked_at: float = 0
    empty: bool | None = None
    cached_report: bool = False
    raw_count: int = 0
    txy_count: int = 0
    identity: list[int] | None = None
    scan_skipped: bool = False
    # A manual retry with no timeout: when it was requested, and entries listed so far.
    retry_since: float | None = None
    listed: int = 0


class SnapshotFileSystemModel(QAbstractItemModel):
    COLUMN_NAME = 0
    COLUMN_SIZE = 1
    COLUMN_TYPE = 2
    COLUMN_DATE_MODIFIED = 3
    COLUMN_STATUS_NUMBER = 4
    COLUMN_STATUS_ICON = 5
    COLUMN_RIGHTFILL = 6
    STATUS_EXTRA_ICONS_ROLE = int(Qt.ItemDataRole.UserRole) + 1
    BUSY_ROLE = int(Qt.ItemDataRole.UserRole) + 10
    LOAD_QUEUED_ROLE = int(Qt.ItemDataRole.UserRole) + 11
    statusReady = pyqtSignal(str)
    directoryLoaded = pyqtSignal(str)
    rootPathChanged = pyqtSignal(str)
    activityChanged = pyqtSignal()
    refreshStateChanged = pyqtSignal()

    def __init__(self, parent: QObject | None = None, service: IOService | None = None) -> None:
        super().__init__(parent)
        self.service = service or get_io_service()
        self.cache = get_folder_cache(self.service)
        style = QApplication.style()
        self._folder_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon) if style else QIcon()
        self._cache_options: dict[str, Any] = {"directory": os.path.join(DIR_CACHES, "data_ram_cache"),
                                               "params": dict(load_cache_param("data_ram_cache"))}
        self.owner = uuid4().hex
        self.generation = 0
        self.root: FolderNode | None = None
        self.nodes: dict[str, FolderNode] = {}
        self.view: QTreeView | None = None
        self.closed = False
        self._refresh_sequence = 0
        self._refresh_paths: set[str] = set()
        self._refresh_submitting = False
        # Folder names each request has listed; None when it joined a running job
        # and missed earlier names, so it must not prune children.
        self._scan_seen: dict[IORequest, set[str] | None] = {}
        self._tree_requests: dict[str, IORequest] = {}
        # Folders whose details (browse step 2) wait for Refresh to finish.
        self._refresh_details: set[str] = set()
        self.folder_opened_path: str | None = None
        # Dataset loads by path ("queued", "loading" or "paused"); kept across root changes
        # because background loads outlive the visible tree.
        self.load_states: dict[str, str] = {}
        self.cache.resultReady.connect(self._on_event)
        self.cache.snapshotChanged.connect(self._shared_snapshot_changed)
        self.cache.datasetChanged.connect(self._shared_dataset_changed)
        self.cache.diskCacheChanged.connect(self._shared_dataset_changed)
        self.cache.scanHistoryChanged.connect(self._shared_dataset_changed)
        self.cache.folderIconChanged.connect(self._folder_icon_changed)

    def node(self, index: QModelIndex) -> FolderNode | None:
        return cast(FolderNode, index.internalPointer()) if index.isValid() else None

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if row < 0 or column < 0 or column >= self.columnCount() or parent.column() > 0:
            return QModelIndex()
        node = self.node(parent)
        children = node.children if node else ([self.root] if self.root else [])
        if row >= len(children):
            return QModelIndex()
        return self.createIndex(row, column, children[row])

    @overload
    def parent(self, child: QModelIndex) -> QModelIndex: ...

    @overload
    def parent(self) -> QObject | None: ...

    def parent(self, child: QModelIndex | None = None) -> QObject | QModelIndex | None:
        if child is None:
            return QObject.parent(self)
        node = self.node(child)
        if node is None or node.parent is None:
            return QModelIndex()
        return self.createIndex(node.parent.row, 0, node.parent)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.column() > 0:
            return 0
        node = self.node(parent)
        return len(node.children) if node else int(self.root is not None)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 7

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:
        if parent.column() > 0:
            return False
        node = self.node(parent)
        return (bool(node.children) or not node.loaded) if node else self.root is not None

    def canFetchMore(self, parent: QModelIndex) -> bool:
        node = self.node(parent)
        return bool(node and not node.loaded and node.state == "idle")

    def fetchMore(self, parent: QModelIndex) -> None:
        node = self.node(parent)
        if node is not None:
            self.request_scan(node.path)

    def status_freshness(self, node: FolderNode) -> CacheFreshness:
        return cache_freshness(node.scanned_at, node.modified)

    def data_freshness(self, node: FolderNode) -> CacheFreshness:
        info = self.cache.cache_status(node.path).info
        as_of = data_as_of(info)
        changed = bool(not node.cached_report and node.scanned_at is not None and as_of is not None
                       and node.scanned_at >= as_of and node.signature and info.get("signature")
                       and node.signature != info["signature"])
        return cache_freshness(as_of, node.modified, changed=changed)

    def observe_modified(self, path: str, modified: object, observed_at: object) -> None:
        """A folder modification time seen outside browsing, e.g. by a load's check."""
        node = self.nodes.get(path)
        if node is not None:
            self._observe_modified(node, modified, observed_at)
            self.changed(node)

    @staticmethod
    def _observe_modified(node: FolderNode, modified: object, observed_at: object) -> None:
        observed = metadata_date(observed_at)
        if node.modified_observed_at is not None and (observed is None or observed < node.modified_observed_at):
            return
        node.modified = metadata_date(modified)
        node.modified_observed_at = observed

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> object:
        node = self.node(index)
        if node is None:
            return None
        column = index.column()
        load_state = self.load_states.get(node.path, "")
        if role == self.BUSY_ROLE:
            return load_state == "loading" or node.state in ("queued", "running")
        if role == self.LOAD_QUEUED_ROLE:
            # A paused load waits like a queued one.
            return load_state in ("queued", "paused")
        if role == int(Qt.ItemDataRole.ToolTipRole):
            from helab.utils.scan_history import history_tooltip
            cached = ("\nShared RAM dataset available (read-only arrays)" if self.cache.current_dataset(node.path)
                      else "\nCached on disk; not loaded into RAM.\nCache freshness is checked when loading."
                      if self.cache.disk_cached(node.path) else "")
            verification = ("\nPrevious scan; checking for changes" if node.cached_report and node.state in ("queued", "running")
                            else "\nPrevious scan; use Check folder status to recheck" if node.cached_report
                            else "\nCached snapshot; checking for changes" if node.loaded and node.state in ("queued", "running")
                            else "\nCached snapshot; use Check folder status to recheck" if node.loaded and time.monotonic() - node.checked_at >= self.cache.FRESH_SECONDS
                            else "")
            report = node.report
            scan_age = (f"\nScan results cached {relative_age(time.monotonic() - node.checked_at)}"
                        f"\nLast scan: {report.time_last_updated.strftime('%Y-%m-%d %H:%M:%S')}" if report else "")
            if report and node.scanned_at is None:
                scan_age = "\nScan date not recorded"
            freshness = ""
            if report:
                freshness += "\n" + freshness_tooltip("Status scan", node.scanned_at, node.modified,
                    self.status_freshness(node), "Use Check folder status to recheck counts and status.")
            if self.cache.disk_cached(node.path):
                info = self.cache.cache_status(node.path).info
                freshness += "\n" + freshness_tooltip("Data cache saved", info.get("saved_at"), node.modified,
                    self.data_freshness(node), "Use Load data to validate and update the data cache.",
                    as_of=data_as_of(info))
            history = history_tooltip(self.cache.scan_history(node.path), time.time())
            if history:
                freshness += "\n" + history
            if warning := self.cache.scan_history_errors.get(node.path):
                freshness += "\n" + warning
            if node.error:
                return f"{node.path}\n{node.error}\nPrevious results retained; Retry to refresh.{scan_age}{cached}{freshness}"
            details = (f"\nStatus: {report.status}\nRaw shots: {node.raw_count}"
                       f"\nConverted shots: {node.txy_count}" if report else "")
            activity = {"loading": "Loading dataset", "queued": "Queued to load dataset",
                        "paused": "Loading paused while the current tab browses or loads"}.get(load_state, node.state)
            return f"{node.path}\n{activity}{details}{scan_age}{cached}{verification}{freshness}"
        if role == int(Qt.ItemDataRole.ForegroundRole) and node.error:
            return QColor("#b86c1d")
        if role == int(Qt.ItemDataRole.DisplayRole):
            if column == self.COLUMN_NAME:
                return os.path.basename(node.path.rstrip(os.sep)) or node.path
            if column == self.COLUMN_DATE_MODIFIED and node.modified is not None:
                return datetime.fromtimestamp(node.modified).strftime("%Y-%m-%d %H:%M:%S")
            if column == self.COLUMN_STATUS_NUMBER:
                return str(node.report.count) if node.report and node.report.count >= 0 else ""
            if column == self.COLUMN_STATUS_ICON and node.error:
                if node.state != "error":
                    return "Cancelled"
                # The scan-failed badge says this; the error stays in the tooltip.
                return "" if self.cache.scan_history(node.path)["blocked"] else "Unavailable"
        if role == int(Qt.ItemDataRole.DecorationRole) and column == self.COLUMN_NAME:
            icon = self.cache.folder_icons.get(node.path)
            return icon if icon is not None and not icon.isNull() else self._folder_icon
        if role == int(Qt.ItemDataRole.DecorationRole) and column == self.COLUMN_STATUS_ICON:
            if not load_state and node.state not in ("queued", "running") and node.report:
                icons = (StatusIcons.ICONS_STATUS_OLDER if self.status_freshness(node) == CacheFreshness.POSSIBLY_OLD
                         else StatusIcons.ICONS_STATUS)
                return icons.get(node.report.status)
        if role == self.STATUS_EXTRA_ICONS_ROLE:
            # Build icons from in-memory values; never call methods that update caches.
            extras = [k for k in (node.report.extra_icons if node.report else [])
                      if k not in ("ram", "ram_single", "ram_opened", "cached", "cached_older", "scan_failed")]
            if self.cache.scan_history(node.path)["blocked"]:
                extras.append("scan_failed")
            older = self.data_freshness(node) in (CacheFreshness.POSSIBLY_OLD, CacheFreshness.CHANGED)
            if self.cache.current_dataset(node.path):
                extras.append("ram_opened")
                if self.cache.disk_cached(node.path) and older:
                    extras.append("cached_older")
            elif self.cache.disk_cached(node.path):
                extras.append("cached_older" if older else "cached")
            return [StatusIcons.ICONS_EXTRA[k] for k in extras
                    if k in StatusIcons.ICONS_EXTRA]
        return None

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = int(Qt.ItemDataRole.DisplayRole)) -> object:
        if orientation == Qt.Orientation.Horizontal and role == int(Qt.ItemDataRole.DisplayRole):
            return ["Name", "Size", "Type", "Modified", "Counts", "Status", ""][section]
        return None

    def filePath(self, index: QModelIndex) -> str:
        node = self.node(index)
        return node.path if node else ""

    def path_index(self, path: str, column: int = 0) -> QModelIndex:
        node = self.nodes.get(os.path.abspath(path))
        return self.createIndex(node.row, column, node) if node else QModelIndex()

    def rootPath(self) -> str:
        return self.root.path if self.root else ""

    def setRootPath(self, path: str, *, scan: bool = True) -> QModelIndex:
        self.cache.cancel(self.owner)
        self._reset_refresh()
        self._scan_seen.clear()
        self._tree_requests.clear()
        self.generation += 1
        self.beginResetModel()
        self.root = FolderNode(os.path.abspath(path))
        self.nodes = {self.root.path: self.root}
        self.endResetModel()
        self.rootPathChanged.emit(self.root.path)
        if scan:
            self.request_scan(self.root.path, priority=True)
        return self.path_index(self.root.path)

    def fetch_status(self, path: str) -> StatusReport:
        node = self.nodes.get(path)
        if node and node.report:
            return node.report
        return StatusReport(path, "loading" if node and node.state in ("queued", "running") else "unknown", -1, [])

    def set_load_state(self, path: str, state: str) -> None:
        if state:
            self.load_states[path] = state
        elif self.load_states.pop(path, None) is None:
            return
        node = self.nodes.get(path)
        if node:
            self.changed(node)

    def changed(self, node: FolderNode) -> None:
        self.dataChanged.emit(self.path_index(node.path), self.path_index(node.path, 6))
        self.activityChanged.emit()

    def request_folder_icons(self, paths: list[str]) -> bool:
        """Called after viewport changes, never by data() or other render queries."""
        if self.closed or self.root is None:
            return False
        missing = [path for path in dict.fromkeys(paths)
                   if path in self.nodes and path not in self.cache.folder_icons][:64]
        if not missing:
            return True
        return self.cache.submit(self.owner, self.generation, self.root.path, "icons",
                                 {"paths": missing}, timeout=5.0)

    def _folder_icon_changed(self, path: str) -> None:
        if not self.closed and path in self.nodes:
            index = self.path_index(path)
            self.dataChanged.emit(index, index, [int(Qt.ItemDataRole.DecorationRole)])

    def request_scan(self, path: str, *, priority: bool = False, force: bool = False,
                     metadata_only: bool = False, automatic: bool = False, no_timeout: bool = False,
                     listing_only: bool = False) -> bool:
        """Browse a folder (list names, then details in the background) or, with
        ``metadata_only``, run a folder status check. ``no_timeout`` is for a manual retry of
        one folder: it runs until done or cancelled. ``listing_only`` refreshes
        tree entries without details, status updates or automatic dataset loads.
        """
        node = self.nodes.get(path)
        if self.closed or node is None:
            return False
        listing_only = listing_only or path in self.cache.listing_notifications
        metadata_only = not listing_only and (metadata_only or path in self.cache.metadata_notifications)
        if no_timeout and self.refresh_pending(path):
            return False
        if self.refreshing and not listing_only and (automatic or metadata_only and not force):
            return False
        operation = "scan" if metadata_only else "list"
        job = self.cache.jobs.get((operation, self.cache.key(path)))
        if force and not automatic and not listing_only and job:
            # A manual check joining automatic work is now a manual subscription.
            for request in self.cache.requests(self.owner):
                if request.path == path and request.operation == operation:
                    request.payload.update(scan_manual=True, automatic=False)
        if node.state in ("queued", "running"):
            if priority and job:
                self.service.promote(job.owner)
            if no_timeout and job:
                # Lift the running scan's limit instead of starting another helper.
                self.service.set_timeout(job.owner, math.inf)
                if node.retry_since is None:
                    node.retry_since = time.monotonic()
                self.changed(node)
            if force and (operation, path) not in self.cache.jobs:
                self.cache.cancel(self.owner, operation, path)
            elif self.cache.has_request(self.owner, operation, path) or job is None:
                return True
        node.error = ""
        node.scan_skipped = False
        node.listed = 0
        node.retry_since = time.monotonic() if no_timeout else None
        payload = {"cache": self._cache_options, "metadata_only": metadata_only,
                   "scan_manual": force and not automatic, "automatic": automatic or metadata_only and not force,
                   "identity": node.identity, "listing_only": listing_only}
        if not self.cache.submit(self.owner, self.generation, path, operation, payload,
                                 priority=priority, force=force, timeout=math.inf if no_timeout else None):
            node.state, node.error = "error", "Scan queue full — Retry"
            node.retry_since = None
            self.changed(node)
            return False
        return True

    def _request_details(self, node: FolderNode, *, manual: bool) -> None:
        """Browse step 2 in the background: signature, dates and subfolder details."""
        if self.refreshing and not manual:
            self._refresh_details.add(node.path)
            return
        key = self.cache.key(node.path)
        snapshot = self.cache.snapshots.get(key)
        # A load of a folder without subfolders lists and fingerprints everything a
        # details scan would, and saves the summary. Subfolder dates need step 2.
        loading = ("load", key) in self.cache.jobs and not node.children
        if (snapshot and snapshot.status.get("details") or loading
                or self.cache.has_request(self.owner, "details", key)):
            return
        payload = {"cache": self._cache_options, "scan_manual": manual, "identity": node.identity}
        self.cache.submit(self.owner, self.generation, node.path, "details", payload)

    @staticmethod
    def _same_folder(node: FolderNode, summary: dict[str, Any]) -> bool:
        """A saved summary for another directory at this path must not be restored."""
        saved = folder_identity(summary.get("identity"))
        return saved is None or node.identity is None or saved == node.identity

    def _restore_summary(self, node: FolderNode, status: dict[str, Any]) -> None:
        node.scanned_at = metadata_date(status.get("scanned_at"))
        self._observe_modified(node, status.get("modified"), node.scanned_at)
        scanned_at = status.get("scanned_at", time.time())
        node.checked_at = time.monotonic() - max(0, time.time() - scanned_at)
        node.report = StatusReport(node.path, status["status"], status["count"], [],
                                   list(status.get("raw", [])), list(status.get("txy", [])),
                                   datetime.fromtimestamp(scanned_at))
        node.raw_count = status.get("raw_count", len(status.get("raw", [])))
        node.txy_count = status.get("txy_count", len(status.get("txy", [])))
        node.signature = status.get("signature", "")
        node.empty = status.get("empty")
        node.cached_report = True

    def _on_event(self, request: IORequest, event: dict[str, Any]) -> None:
        if (self.closed or request.owner != self.owner or request.generation != self.generation
                or request.operation not in SCANS):
            return
        node = self.nodes.get(request.path)
        kind = event["kind"]
        if (request.operation == "list" and kind in ("done", "error", "cancelled")
                and request.payload.get("refresh_sequence") == self._refresh_sequence):
            if request.path in self._refresh_paths:
                self._refresh_paths.discard(request.path)
                self._refresh_changed()
        if node is None:
            self._scan_seen.pop(request, None)
            return
        if kind == "queued":
            if request not in self._scan_seen:
                self._tree_requests[node.path] = request
            self._scan_seen[request] = set()
        elif kind == "started" and request not in self._scan_seen:
            # Joined another tab's running job: it is now this row's activity.
            self._tree_requests[node.path] = request
            self._scan_seen[request] = None
        seen = self._scan_seen.get(request)
        if kind in ("done", "error", "cancelled"):
            self._scan_seen.pop(request, None)
        owns_tree = self._tree_requests.get(node.path) is request
        if kind == "cancelled" and request.payload.get("refresh_cancelled"):
            # Refresh discards optional automatic work without presenting a failure.
            if owns_tree:
                self._release_row(node)
            node.error = ""
            self.changed(node)
            return
        if request.operation == "details":
            # Browse step 2 runs in the background: it fills in the listing but is
            # not the row's activity, and its completion does not prune children.
            if kind in ("queued", "started", "scan_mode", "heartbeat", "cancelled", "done"):
                if kind == "done":
                    self.changed(node)
                return
            if kind == "error":
                if node.state not in ("queued", "running"):
                    node.state, node.error = "error", event.get("message", "Folder details failed — Retry")
                self.changed(node)
                return
        if kind == "scan_mode":
            node.scan_skipped = event["mode"] == "skipped"
        if kind in ("done", "error", "cancelled"):
            node.retry_since = None
        if kind == "heartbeat":
            node.listed = int(event.get("entries", node.listed))
        elif kind in ("queued", "started"):
            if owns_tree:
                node.state = "queued" if kind == "queued" else "running"
        elif kind == "scan_cached":
            if node.report is None:
                self._restore_summary(node, event["status"])
        elif kind == "entries":
            if seen is not None:
                seen.update(entry["path"] for entry in event["entries"])
            if not owns_tree:
                return  # A newer listing/check owns the folder names in this view.
            new: list[FolderNode] = []
            for entry in event["entries"]:
                path = entry["path"]
                child = self.nodes.get(path)
                if child is None:
                    # A names-only listing has no dates; the details scan adds them.
                    child = FolderNode(path, node, len(node.children) + len(new))
                    child.identity = entry.get("identity")
                    if "modified" in entry:
                        self._observe_modified(child, entry["modified"], entry.get("modified_observed_at"))
                    cached = self.cache.snapshot(path)
                    if cached and (child.identity is None or cached.status.get("identity") in (None, child.identity)):
                        status = cached.status
                        child.report = StatusReport(path, status["status"], status["count"], [],
                                                    list(status["raw"]), list(status["txy"]),
                                                    datetime.fromtimestamp(time.time() - max(0, time.monotonic() - cached.checked_at)))
                        child.signature = status.get("signature", "")
                        child.checked_at = cached.checked_at
                        child.scanned_at = metadata_date(status.get("scanned_at"))
                        child.empty = status.get("empty")
                        child.raw_count, child.txy_count = len(status["raw"]), len(status["txy"])
                        child.loaded = not cached.entries
                    elif summary := entry.get("scan_status") or self.cache.scan_summaries.get(path):
                        self._restore_summary(child, summary)
                        if child.identity is None:
                            # Provisional until a details entry reports the folder's identity;
                            # a different folder at this path then drops the saved summary.
                            child.identity = folder_identity(summary.get("identity"))
                    new.append(child)
                    self.nodes[path] = child
                else:
                    if child.identity is not None and entry.get("identity") is not None and child.identity != entry["identity"]:
                        child.report, child.signature = None, ""
                        child.raw_count = child.txy_count = 0
                        child.scanned_at, child.checked_at = None, 0
                    child.identity = entry.get("identity", child.identity)
                    if "modified" in entry:
                        self._observe_modified(child, entry["modified"], entry.get("modified_observed_at"))
                    summary = entry.get("scan_status") or self.cache.scan_summaries.get(path)
                    if child.report is None and summary and self._same_folder(child, summary):
                        self._restore_summary(child, summary)
                    self.changed(child)
            if new:
                self.beginInsertRows(self.path_index(node.path), len(node.children), len(node.children) + len(new) - 1)
                node.children.extend(new)
                self.endInsertRows()
                if self.refreshing and request.payload.get("listing_only"):
                    self._refresh_details.add(node.path)  # Dates for the new subfolders.
        elif kind == "status":
            if request.payload.get("listing_only"):
                # Refresh changes the tree, not the last checked status or dataset.
                node.empty = event.get("empty", node.empty)
                self.changed(node)
                return
            node.cached_report = False
            node.identity = event.get("identity", node.identity)
            node.raw_count, node.txy_count = len(event["raw"]), len(event["txy"])
            extras = list(node.report.extra_icons) if node.report else []
            node.checked_at = event.get("checked_at", time.monotonic())
            node.report = StatusReport(node.path, event["status"], event["count"], extras,
                                       list(event["raw"]), list(event["txy"]),
                                       datetime.fromtimestamp(time.time() - max(0, time.monotonic() - node.checked_at)))
            node.scanned_at = metadata_date(event.get("scanned_at"))
            if "modified" in event:
                self._observe_modified(node, event["modified"], node.scanned_at)
            # Unknown ("") after a names-only listing until details or a load supply it.
            node.signature = event.get("signature", "")
            node.empty = event.get("empty")
            if not event.get("metadata_only"):
                self.statusReady.emit(node.path)
        elif kind == "done":
            if node.scan_skipped or event.get("scan_skipped"):
                if owns_tree:
                    self._release_row(node)
                elif node.path not in self._tree_requests:
                    node.state = "idle"
                self.changed(node)
                return
            if owns_tree:
                node.loaded = True
                self._release_row(node)
            # Preserve stable nodes/selection during refresh; remove vanished
            # branches after the complete scan, never on a failed partial scan.
            # A request that joined a running job missed earlier names.
            if owns_tree and seen is not None:
                for row in range(len(node.children) - 1, -1, -1):
                    child = node.children[row]
                    if child.path not in seen:
                        self.beginRemoveRows(self.path_index(node.path), row, row)
                        removed = node.children.pop(row)
                        self._forget(removed)
                        self.endRemoveRows()
            for row, child in enumerate(node.children):
                child.row = row
            if not request.payload.get("listing_only"):
                self.directoryLoaded.emit(node.path)
            if request.operation == "list" and not request.payload.get("listing_only"):
                self._request_details(node, manual=bool(request.payload.get("scan_manual")))
        elif kind in ("error", "cancelled"):
            node.state = "error" if kind == "error" else "cancelled"
            node.error = event.get("message", "Cancelled — Retry")
        self.changed(node)

    def _release_row(self, node: FolderNode) -> None:
        """The row's request ended: the newest of this tab's other active requests
        for the folder (e.g. a check still running after Refresh's listing) takes
        the row, else it is idle."""
        active = self.cache.requests(self.owner)
        # A request FolderCache replaced (e.g. resubmitted after a cache clear)
        # never finishes; it must not take the row back.
        for stale in [r for r in self._scan_seen if r.path == node.path and r not in active]:
            del self._scan_seen[stale]
        previous = next((r for r in reversed(self._scan_seen)
                         if r.path == node.path and not r.cancelled.is_set()), None)
        if previous is None:
            self._tree_requests.pop(node.path, None)
            node.state = "idle"
            return
        self._tree_requests[node.path] = previous
        job = self.cache.jobs.get((previous.operation, node.path))
        # Details (browse step 2) fill in names and dates but are not the row's activity.
        node.state = ("idle" if previous.operation == "details"
                      else "running" if job and job.state == "started" else "queued")

    def _shared_snapshot_changed(self, path: str) -> None:
        if path in self.nodes and not any(self.cache.has_request(self.owner, operation, path) for operation in SCANS):
            snapshot = self.cache.snapshot(path)
            self.request_scan(path, force=bool(snapshot and snapshot.checked_at == 0
                                               and not self.cache.scan_history(path)["blocked"]), automatic=True)

    def _shared_dataset_changed(self, path: str) -> None:
        node = self.nodes.get(path)
        if node:
            # A load completes a names-only listing's signature (FolderCache adopts it).
            snapshot = self.cache.snapshots.get(self.cache.key(path))
            if not node.signature and snapshot and snapshot.status.get("signature"):
                node.signature = snapshot.status["signature"]
            self.changed(node)

    def _forget(self, node: FolderNode) -> None:
        self.nodes.pop(node.path, None)
        self._tree_requests.pop(node.path, None)
        for child in node.children:
            self._forget(child)

    def _visible_rows(self) -> Iterator[tuple[QModelIndex, str]]:
        # Only visit branches expanded in this view; hasChildren() never probes.
        if self.root is None:
            return
        yield self.path_index(self.root.path), self.root.path
        pending = [iter(self.root.children)]
        while pending:
            node = next(pending[-1], None)
            if node is None:
                pending.pop()
                continue
            index = self.path_index(node.path)
            yield index, node.path
            if self.view is not None and self.view.isExpanded(index):
                pending.append(iter(node.children))

    def get_visible_rows(self) -> list[tuple[QModelIndex, str]]:
        return list(self._visible_rows())

    def viewport_paths(self) -> list[str]:
        if self.view is None:
            return []
        viewport = self.view.viewport()
        if viewport is None:
            return []
        index = self.view.indexAt(QPoint(3, 1))
        paths: list[str] = []
        for _ in range(512):
            if not index.isValid() or self.view.visualRect(index).top() >= viewport.height():
                break
            paths.append(self.filePath(index))
            index = self.view.indexBelow(index)
        return paths

    def rescan(self, user_requested_scan: bool = False) -> None:
        if self.root:
            self.cache.refresh_folder_icons([self.root.path, *self.viewport_paths()])
            self.request_scan(self.root.path, priority=True, force=True)
        self._refresh_sequence += 1
        sequence, generation = self._refresh_sequence, self.generation
        rows = iter(self.viewport_paths())

        def batch() -> None:
            if self.closed or sequence != self._refresh_sequence or generation != self.generation:
                return
            for _ in range(128):
                row = next(rows, None)
                if row is None:
                    return
                self.request_scan(row, force=True)
            QTimer.singleShot(0, batch)

        QTimer.singleShot(0, batch)

    @property
    def refreshing(self) -> bool:
        return self._refresh_submitting or bool(self._refresh_paths)

    def refresh_pending(self, path: str) -> bool:
        return path in self._refresh_paths

    def _reset_refresh(self) -> None:
        self._refresh_sequence += 1
        self._refresh_paths.clear()
        self._refresh_details.clear()
        self._refresh_submitting = False
        self.refreshStateChanged.emit()

    def _refresh_changed(self) -> None:
        if not self.refreshing and self._refresh_details:
            # After the finishing listing's own event (it may still prune children).
            QTimer.singleShot(0, self._request_refresh_details)
        self.refreshStateChanged.emit()

    def _request_refresh_details(self) -> None:
        """Details cancelled or deferred by Refresh, and folders it found new
        subfolders in, get their dates, signature and identities."""
        if self.closed or self.refreshing:
            return
        paths, self._refresh_details = self._refresh_details, set()
        for path in paths:
            node = self.nodes.get(path)
            if node is not None and node.state != "error":
                self._request_details(node, manual=False)

    def refresh(self) -> None:
        """Relist the root and expanded branches on screen, without checking files."""
        if self.closed or self.root is None:
            return
        root_path = self.root.path
        visible = self.viewport_paths()
        self.cache.refresh_folder_icons([root_path, *visible])
        paths = {root_path: None}
        for path in visible:
            node = self.nodes.get(path)
            while node is not None and node is not self.root:
                if self.view is not None and self.view.isExpanded(self.path_index(node.path)):
                    paths[node.path] = None
                node = node.parent
        self._refresh_sequence += 1
        sequence, generation = self._refresh_sequence, self.generation
        self._refresh_submitting = True
        self._refresh_details.update(request.path for request in self.cache.cancel_automatic_scans(self.owner)
                                     if request.operation == "details")
        self._refresh_paths = set(paths)
        self.refreshStateChanged.emit()
        rows = list(paths)
        position = 0

        def batch() -> None:
            nonlocal position
            if self.closed or self.service.closed or sequence != self._refresh_sequence or generation != self.generation:
                return
            for _ in range(16):
                if position >= len(rows):
                    self._refresh_submitting = False
                    self._refresh_changed()
                    return
                if len(self.service.pending) >= 16:
                    QTimer.singleShot(50, batch)
                    return
                path = rows[position]
                position += 1
                if path not in self.nodes or not self.request_scan(
                        path, priority=path == root_path, force=True, listing_only=True):
                    self._refresh_paths.discard(path)
                else:
                    for request in self.cache.requests(self.owner):
                        if request.path == path and request.operation == "list":
                            request.payload["refresh_sequence"] = sequence
            QTimer.singleShot(0, batch)

        batch()

    def stop_all_scans(self) -> None:
        self._reset_refresh()
        for operation in SCANS:
            self.cache.cancel(self.owner, operation)

    def close_cleanup(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._reset_refresh()
        self._scan_seen.clear()
        self._tree_requests.clear()
        self.generation += 1
        self.cache.cancel(self.owner)
        self.cache.resultReady.disconnect(self._on_event)
        self.cache.snapshotChanged.disconnect(self._shared_snapshot_changed)
        self.cache.datasetChanged.disconnect(self._shared_dataset_changed)
        self.cache.diskCacheChanged.disconnect(self._shared_dataset_changed)
        self.cache.folderIconChanged.disconnect(self._folder_icon_changed)
