"""A filesystem tree whose Qt queries only read memory.

Directory discovery and status computation belong to IOService's helper
processes. There is no QFileSystemModel gatherer or filesystem icon provider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import os
import time
from typing import Any, Iterator, cast, overload
from uuid import uuid4

from PyQt6.QtCore import QAbstractItemModel, QModelIndex, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QTreeView

from helab.models.StatusReport import StatusReport
from helab.resources.icons import StatusIcons
from helab.utils.io_service import IORequest, IOService, get_io_service
from helab.utils.folder_cache import get_folder_cache
from helab.utils.caching_setup import load_cache_param
from helab.utils.constants import DIR_CACHES


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
    report: StatusReport | None = None
    seen: set[str] = field(default_factory=set)
    signature: str = ""
    loading: bool = False
    checked_at: float = 0


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
    statusReady = pyqtSignal(str)
    directoryLoaded = pyqtSignal(str)
    rootPathChanged = pyqtSignal(str)
    activityChanged = pyqtSignal()

    def __init__(self, parent: QObject | None = None, service: IOService | None = None) -> None:
        super().__init__(parent)
        self.service = service or get_io_service()
        self.cache = get_folder_cache(self.service)
        self._cache_options = {"directory": os.path.join(DIR_CACHES, "data_ram_cache"),
                               "params": dict(load_cache_param("data_ram_cache"))}
        self.owner = uuid4().hex
        self.generation = 0
        self.root: FolderNode | None = None
        self.nodes: dict[str, FolderNode] = {}
        self.view: QTreeView | None = None
        self.closed = False
        self._refresh_sequence = 0
        self.folder_opened_path: str | None = None
        self.cache.resultReady.connect(self._on_event)
        self.cache.snapshotChanged.connect(self._shared_snapshot_changed)
        self.cache.datasetChanged.connect(self._shared_dataset_changed)
        self.cache.diskCacheChanged.connect(self._shared_dataset_changed)

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

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> object:
        node = self.node(index)
        if node is None:
            return None
        column = index.column()
        if role == self.BUSY_ROLE:
            return node.loading or node.state in ("queued", "running")
        if role == int(Qt.ItemDataRole.ToolTipRole):
            cached = ("\nShared RAM dataset available (read-only arrays)" if self.cache.current_dataset(node.path)
                      else "\nCached on disk; not loaded into RAM.\nCache freshness is checked when loading."
                      if self.cache.disk_cached(node.path) else "")
            verification = ("\nCached snapshot; checking for changes" if node.loaded and node.state in ("queued", "running")
                            else "\nCached snapshot; validation on next access" if node.loaded and time.monotonic() - node.checked_at >= self.cache.FRESH_SECONDS
                            else "")
            if node.error:
                return f"{node.path}\n{node.error}\nPrevious results retained; Retry to refresh.{cached}"
            report = node.report
            details = (f"\nStatus: {report.status}\nRaw shots: {len(report.d_dld_shots or [])}"
                       f"\nConverted shots: {len(report.d_txy_shots or [])}" if report else "")
            return f"{node.path}\n{'Loading dataset' if node.loading else node.state}{details}{cached}{verification}"
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
                return "Unavailable" if node.state == "error" else "Cancelled"
        if role == int(Qt.ItemDataRole.DecorationRole) and column == self.COLUMN_STATUS_ICON:
            if not node.loading and node.state not in ("queued", "running") and node.report:
                return StatusIcons.ICONS_STATUS.get(node.report.status)
        if role == self.STATUS_EXTRA_ICONS_ROLE:
            # Build icons from in-memory values; never call methods that update caches.
            extras = [k for k in (node.report.extra_icons if node.report else [])
                      if k not in ("ram", "ram_single", "ram_opened", "cached")]
            if self.cache.current_dataset(node.path):
                extras.append("ram_opened")
            elif self.cache.disk_cached(node.path):
                extras.append("cached")
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

    def changed(self, node: FolderNode) -> None:
        self.dataChanged.emit(self.path_index(node.path), self.path_index(node.path, 6))
        self.activityChanged.emit()

    def request_scan(self, path: str, *, priority: bool = False, force: bool = False) -> None:
        node = self.nodes.get(path)
        if self.closed or node is None:
            return
        if node.state in ("queued", "running"):
            if force and ("scan", path) not in self.cache.jobs:
                self.cache.cancel(self.owner, "scan", path)
            else:
                return
        node.seen.clear()
        node.error = ""
        if not self.cache.submit(self.owner, self.generation, path, "scan", {"cache": self._cache_options},
                                 priority=priority, force=force):
            node.state, node.error = "error", "Scan queue full — Retry"
            self.changed(node)

    def _on_event(self, request: IORequest, event: dict[str, Any]) -> None:
        if self.closed or request.owner != self.owner or request.generation != self.generation or request.operation != "scan":
            return
        node = self.nodes.get(request.path)
        if node is None:
            return
        kind = event["kind"]
        if kind in ("queued", "started"):
            node.state = "queued" if kind == "queued" else "running"
        elif kind == "entries":
            new: list[FolderNode] = []
            for entry in event["entries"]:
                path = entry["path"]
                node.seen.add(path)
                child = self.nodes.get(path)
                if child is None:
                    child = FolderNode(path, node, len(node.children) + len(new), modified=entry["modified"])
                    cached = self.cache.snapshot(path)
                    if cached:
                        status = cached.status
                        child.report = StatusReport(path, status["status"], status["count"], [],
                                                    list(status["raw"]), list(status["txy"]), datetime.now())
                        child.signature = status.get("signature", "")
                        child.checked_at = cached.checked_at
                        child.loaded = not cached.entries
                    new.append(child)
                    self.nodes[path] = child
                else:
                    child.modified = entry["modified"]
            if new:
                self.beginInsertRows(self.path_index(node.path), len(node.children), len(node.children) + len(new) - 1)
                node.children.extend(new)
                self.endInsertRows()
        elif kind == "status":
            extras = list(node.report.extra_icons) if node.report else []
            node.report = StatusReport(node.path, event["status"], event["count"], extras,
                                       list(event["raw"]), list(event["txy"]), datetime.now())
            node.modified = event["modified"]
            node.signature = event.get("signature", "")
            node.checked_at = event.get("checked_at", time.monotonic())
            self.statusReady.emit(node.path)
        elif kind == "done":
            node.state, node.loaded = "idle", True
            # Preserve stable nodes/selection during refresh; remove vanished
            # branches after the complete scan, never on a failed partial scan.
            for row in range(len(node.children) - 1, -1, -1):
                child = node.children[row]
                if child.path not in node.seen:
                    self.beginRemoveRows(self.path_index(node.path), row, row)
                    removed = node.children.pop(row)
                    self._forget(removed)
                    self.endRemoveRows()
            for row, child in enumerate(node.children):
                child.row = row
            self.directoryLoaded.emit(node.path)
        elif kind in ("error", "cancelled"):
            node.state = "error" if kind == "error" else "cancelled"
            node.error = event.get("message", "Cancelled — Retry")
        self.changed(node)

    def _shared_snapshot_changed(self, path: str) -> None:
        if path in self.nodes and not self.cache.has_request(self.owner, "scan", path):
            snapshot = self.cache.snapshot(path)
            self.request_scan(path, force=bool(snapshot and snapshot.checked_at == 0))

    def _shared_dataset_changed(self, path: str) -> None:
        node = self.nodes.get(path)
        if node:
            self.changed(node)

    def _forget(self, node: FolderNode) -> None:
        self.nodes.pop(node.path, None)
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

    def rescan(self, user_requested_scan: bool = False) -> None:
        if self.root:
            self.request_scan(self.root.path, priority=True, force=True)
        self._refresh_sequence += 1
        sequence, generation = self._refresh_sequence, self.generation
        rows = self._visible_rows()

        def batch() -> None:
            if self.closed or sequence != self._refresh_sequence or generation != self.generation:
                return
            for _ in range(128):
                row = next(rows, None)
                if row is None:
                    return
                index, path = row
                if self.view is not None and self.view.isExpanded(index):
                    self.request_scan(path, force=True)
            QTimer.singleShot(0, batch)

        QTimer.singleShot(0, batch)

    def refresh(self) -> None:
        self.rescan(True)

    def stop_all_scans(self) -> None:
        self._refresh_sequence += 1
        self.cache.cancel(self.owner)

    def close_cleanup(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.generation += 1
        self.cache.cancel(self.owner)
        self.cache.resultReady.disconnect(self._on_event)
        self.cache.snapshotChanged.disconnect(self._shared_snapshot_changed)
        self.cache.datasetChanged.disconnect(self._shared_dataset_changed)
        self.cache.diskCacheChanged.disconnect(self._shared_dataset_changed)
