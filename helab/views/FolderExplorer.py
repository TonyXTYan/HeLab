"""Folder browser backed by isolated I/O and memory snapshots."""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
import logging
import os
from typing import Any, Iterator

import numpy as np
import numpy.typing as npt
from PyQt6.QtCore import QItemSelection, QItemSelectionModel, QModelIndex, QPoint, QRect, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit, QMenu, QProgressBar,
                             QPushButton, QStyledItemDelegate, QStyleOptionViewItem, QTreeView,
                             QStyle, QVBoxLayout, QWidget)
from helab.models.SnapshotFileSystemModel import FolderNode, SnapshotFileSystemModel
from helab.models.StatusReport import StatusReport
from helab.utils.io_service import IORequest
from helab.utils.folder_cache import Dataset
from helab.utils.caching_setup import load_cache_param
from helab.utils.constants import DEFAULT_LOAD_MODE, DIR_CACHES


def paint_spinner(painter: QPainter, rect: QRect, angle: int, selected: bool = False) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("white" if selected else "#3989c9"), 2.5))
    painter.drawArc(rect, angle * 16, 260 * 16)
    painter.restore()


def paint_queued(painter: QPainter, rect: QRect, selected: bool = False) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("white" if selected else "#8a8a8a"), 1.5, Qt.PenStyle.DotLine))
    painter.drawEllipse(rect)
    painter.restore()


class ScanDelegate(QStyledItemDelegate):
    angle = 0

    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem | None, index: QModelIndex) -> None:
        if painter is None or option is None:
            return
        super().paint(painter, option, index)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        rect = QRect(option.rect.left() + 7, option.rect.top() + (option.rect.height() - 10) // 2, 10, 10)
        if index.data(SnapshotFileSystemModel.BUSY_ROLE):
            paint_spinner(painter, rect, self.angle, selected)
        elif index.data(SnapshotFileSystemModel.LOAD_QUEUED_ROLE):
            paint_queued(painter, rect, selected)
        extras = index.data(SnapshotFileSystemModel.STATUS_EXTRA_ICONS_ROLE)
        if isinstance(extras, list):
            for i, icon in enumerate(extras):
                if isinstance(icon, QIcon):
                    icon.paint(painter, QRect(option.rect.left() + 24 + i * 18,
                                             option.rect.top() + (option.rect.height() - 16) // 2, 16, 16))


class FolderExplorer(QWidget):
    rootPathChanged = pyqtSignal(str)
    itemExpandedSignal = pyqtSignal(QModelIndex)
    selectionPathChanged = pyqtSignal(str)
    loadStateChanged = pyqtSignal()
    dataLoaded = pyqtSignal(str)
    DWELL_MS = 3000
    MAX_BACKGROUND_LOADS = 8

    def __init__(self, model_root_path: str, target_path: str, view_path: str,
                 columns_to_show: list[int], parent: QWidget | None = None,
                 set_initial_expand_to_parent_level: bool = True,
                 default_candidates: list[str] | None = None) -> None:
        super().__init__(parent)
        self.model_root_path = os.path.abspath(target_path or view_path or model_root_path)
        self.target_path = self.view_path = self.selected_path_globally = self.model_root_path
        self.tab_title_str = ""
        self.auto_load_ram = True
        self.folder_opened_data: dict[int, npt.NDArray[np.float64]] | None = None
        self.folder_opened_path: str | None = None
        self.back_button_enabled = False
        self.closed = False
        self.loading = False
        self.load_progress: float | None = None
        self.load_queued = False
        self.load_attempt = 1
        self.load_files = 0
        self.load_total_files: int | None = None
        self.load_failed_files = 0
        self.load_source = ""
        self.load_cache_reason = ""
        self.load_cache_warning = ""
        self.load_error = ""
        self.load_bytes = 0
        self._load_path: str | None = None
        self._cancelled_load_path: str | None = None
        self._loading_data: dict[int, npt.NDArray[np.float64]] = {}
        self._loaded_signature = ""
        self._deep: list[tuple[Iterator[FolderNode], int]] = []
        self._deep_depth: dict[str, int] = {}
        self.load_mode = DEFAULT_LOAD_MODE
        # Loads this tab no longer shows, in queue order; they only fill the caches.
        self._bg_paths: OrderedDict[str, None] = OrderedDict()
        self._dwell = QTimer(self)
        self._dwell.setSingleShot(True)
        self._dwell.timeout.connect(self._dwell_elapsed)
        self._dwell_path: str | None = None
        self.model = SnapshotFileSystemModel(self)
        self.bg_owner = f"{self.model.owner}:bg"
        self.tree = QTreeView(self)
        self.tree.setModel(self.model)
        self.model.view = self.tree
        self.tree.setUniformRowHeights(True)
        self.tree.setStyleSheet("QTreeView::item { min-height: 16px; max-height: 16px; padding: 0px; }")
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 300)
        for column in range(self.model.columnCount()):
            self.tree.setColumnHidden(column, column not in columns_to_show)
        self.tree.setColumnWidth(self.model.COLUMN_STATUS_ICON, 150)
        self.delegate = ScanDelegate(self.tree)
        self.tree.setItemDelegateForColumn(self.model.COLUMN_STATUS_ICON, self.delegate)
        self.path_edit = QLineEdit(self.view_path, self)
        self.path_edit.returnPressed.connect(self._navigate_input)
        self.back_button = QPushButton("Up", self)
        self.back_button.clicked.connect(self.on_back_button_clicked)
        self.retry_button = QPushButton("Retry", self)
        self.retry_button.clicked.connect(self._retry)
        self.scan_label = QLabel(self)
        self.spinner_label = QLabel(self)
        self.spinner_label.setFixedSize(16, 16)
        self.spinner_label.hide()
        self.progress = QProgressBar(self)
        self.progress.setMaximumWidth(150)
        self.progress.hide()
        controls = QHBoxLayout()
        for widget in (self.back_button, self.path_edit, self.retry_button):
            controls.addWidget(widget)
        status = QHBoxLayout()
        status.addWidget(self.spinner_label)
        status.addWidget(self.scan_label, 1)
        status.addWidget(self.progress)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(controls)
        layout.addWidget(self.tree, 1)
        layout.addLayout(status)
        self.get_selection_model().selectionChanged.connect(self.on_selection_changed)
        self.tree.expanded.connect(self._expanded)
        self.tree.doubleClicked.connect(self.on_double_click)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        self.model.statusReady.connect(self._status_ready)
        self.model.directoryLoaded.connect(self._directory_loaded)
        self.model.cache.resultReady.connect(self._io_event)
        self.model.cache.datasetChanged.connect(self._shared_dataset_changed)
        self.model.activityChanged.connect(self._update_activity)
        self.animation = QTimer(self)
        self.animation.timeout.connect(self._animate)
        self.animation.start(80)
        self.deep_timer = QTimer(self)
        self.deep_timer.timeout.connect(self._dispatch_deep)
        self.deep_timer.start(50)
        # Startup happens after the main window installs its signal handlers.
        if default_candidates:
            QTimer.singleShot(0, lambda: self._resolve_default(default_candidates))
        else:
            QTimer.singleShot(0, lambda: self.open_to_path(self.target_path))

    def _resolve_default(self, candidates: list[str]) -> None:
        if not self.closed:
            self.scan_label.setText("Finding default folder…")
            self.model.cache.submit(self.model.owner, self.model.generation, self.target_path,
                                      "resolve", {"candidates": candidates}, priority=True)

    def open_to_path(self, path: str) -> None:
        if self.closed or not path.strip():
            return
        self._deep.clear()
        self._deep_depth.clear()
        self._release_load()
        self._cancelled_load_path = None
        self.target_path = self.view_path = self.model_root_path = os.path.abspath(os.path.expanduser(path))
        self.selected_path_globally = self.view_path
        self.path_edit.setText(self.view_path)
        self.tree.setRootIndex(self.model.setRootPath(self.view_path))
        self.update_back_button_state()
        self.emit_root_path_changed()
        self.selectionPathChanged.emit(self.view_path)
        self.loadStateChanged.emit()

    def _navigate_input(self) -> None:
        self.open_to_path(self.path_edit.text())

    def _retry(self) -> None:
        if self.load_error:
            self.load_to_ram_cache(self.selected_path_globally, dwell=False)
        else:
            self.model.request_scan(self.selected_path_globally, priority=True, force=True)
            self.model.rescan(True)

    def _expanded(self, index: QModelIndex) -> None:
        node = self.model.node(index)
        if node:
            self.model.request_scan(node.path, priority=True)
        self.itemExpandedSignal.emit(index)

    def on_selection_changed(self, selected: QItemSelection, deselected: QItemSelection) -> None:
        indexes = selected.indexes()
        if indexes:
            path = self.model.filePath(indexes[0])
            if path != self.selected_path_globally:
                self._release_load()
                self._cancelled_load_path = None
                self.selected_path_globally = path
            self.model.request_scan(path, priority=True)
            self.selectionPathChanged.emit(path)

    def _status_ready(self, path: str) -> None:
        if path == self.selected_path_globally:
            node = self.model.nodes.get(path)
            if node and self.folder_opened_path == path and node.signature != self._loaded_signature:
                # Keep the displayed data while a fresh load replaces it.
                self.folder_opened_path = None
            self.selectionPathChanged.emit(path)

    @property
    def load_waiting(self) -> bool:
        """The selected folder will be queued if it stays selected."""
        return self._dwell.isActive()

    @property
    def can_cancel_loading(self) -> bool:
        return not self.closed and bool(self.loading or self.load_waiting or self._bg_paths)

    def _stop_dwell(self) -> None:
        self._dwell.stop()
        self._dwell_path = None

    def _dwell_elapsed(self) -> None:
        path, self._dwell_path = self._dwell_path, None
        if not self.closed and path is not None and path == self.selected_path_globally:
            self.load_to_ram_cache(path, dwell=False)
        self.loadStateChanged.emit()

    def _release_load(self) -> None:
        """Stop showing the current load; depending on the mode it continues in the background."""
        self._stop_dwell()
        path = self._load_path
        if path is not None and self.loading and (
                self.load_mode == "queue" or (self.load_mode == "finish" and not self.load_queued)):
            self._bg_paths[path] = None
            if self.model.cache.transfer(self.model.owner, self.model.generation, path, self.bg_owner, 0):
                self._trim_background()
            else:
                del self._bg_paths[path]
        self.model.cache.cancel(self.model.owner, "load")
        if path is not None and path not in self._bg_paths:
            self.model.set_load_state(path, "")
        self._load_path = None
        self._loading_data.clear()
        self.loading = False
        self.load_error = ""

    def _trim_background(self) -> None:
        queued = [p for p in self._bg_paths if self.model.load_states.get(p) == "queued"]
        for path in queued[:max(0, len(queued) - self.MAX_BACKGROUND_LOADS)]:
            self.model.cache.cancel(self.bg_owner, "load", path)

    def _begin_load(self, path: str) -> None:
        self.loading, self.load_progress, self.load_error = True, None, ""
        self.load_queued = True
        self.load_attempt = 1
        self.load_files = self.load_failed_files = 0
        self.load_total_files = None
        self.load_source = ""
        self.load_cache_reason = ""
        self.load_cache_warning = ""
        self._load_path = path
        self._loading_data.clear()
        self.model.set_load_state(path, "queued")

    def _load_payload(self, path: str) -> dict[str, Any]:
        node = self.model.nodes.get(path)
        cache = {"directory": os.path.join(DIR_CACHES, "data_ram_cache"),
                 "params": dict(load_cache_param("data_ram_cache"))}
        return {"cache": cache, "signature": node.signature if node else ""}

    def _has_data(self, path: str) -> bool:
        report = self.model.fetch_status(path)
        return report.status in StatusReport.STATUS_CONTAINS_DATA_HERE and bool(report.d_txy_shots)

    def load_to_ram_cache(self, path: str, *, dwell: bool = True) -> bool:
        """Show this folder's data, loading it as the tab's visible load."""
        # A scan finishing after Cancel must not restart automatic loading.
        if dwell and path == self._cancelled_load_path:
            return False
        if not dwell:
            self._cancelled_load_path = None
        if not self._has_data(path):
            return False
        if self.folder_opened_path == path and self.folder_opened_data is not None:
            self.dataLoaded.emit(path)
            return False
        if self.loading and self._load_path == path:
            return True
        node = self.model.nodes.get(path)
        in_memory = node is not None and self.model.cache.dataset(path, node.signature) is not None
        if (dwell and self.load_mode == "queue" and path not in self._bg_paths
                and not in_memory and self.model.service.load_busy()):
            # Browsing past folders must not fill the queue.
            if self._dwell_path != path or not self._dwell.isActive():
                self._dwell_path = path
                self._dwell.start(self.DWELL_MS)
                self._update_activity()
                self.loadStateChanged.emit()
            return True
        self._release_load()
        self._begin_load(path)
        if path in self._bg_paths:
            del self._bg_paths[path]
            if self.model.cache.transfer(self.bg_owner, 0, path, self.model.owner, self.model.generation):
                self.model.cache.promote(path)
                self.loadStateChanged.emit()
                return True
        accepted = self.model.cache.submit(self.model.owner, self.model.generation, path, "load",
                                           self._load_payload(path), priority=True)
        if accepted and self.load_mode != "cancel":
            self.model.cache.promote(path)
        if not accepted:
            self.loading = False
            self.load_error = "Load queue full — Retry"
            self.model.set_load_state(path, "")
        self.loadStateChanged.emit()
        return accepted

    def queue_load(self, path: str) -> bool:
        """Explicit load: never cancels another load; runs now when idle, otherwise queues."""
        if path == self.selected_path_globally:
            return self.load_to_ram_cache(path, dwell=False)
        if path in self._bg_paths or (self.loading and self._load_path == path):
            return True
        if not self._has_data(path):
            return False
        self._bg_paths[path] = None
        if not self.model.cache.submit(self.bg_owner, 0, path, "load", self._load_payload(path), priority=True):
            self._bg_paths.pop(path, None)
            self.model.set_load_state(path, "")
            return False
        self._trim_background()
        self._update_activity()
        self.loadStateChanged.emit()
        return True

    def _background_event(self, request: IORequest, event: dict[str, Any]) -> None:
        path = request.path
        if request.operation != "load" or path not in self._bg_paths:
            return
        kind = event["kind"]
        if kind in ("queued", "started"):
            self.model.set_load_state(path, "queued" if kind == "queued" else "loading")
        elif kind in ("loaded", "error", "cancelled"):
            del self._bg_paths[path]
            self.model.set_load_state(path, "")
            if kind == "error":
                logging.warning("Background load %s: %s", path, event.get("message", ""))
        else:
            return
        self._update_activity()
        self.loadStateChanged.emit()

    def _io_event(self, request: IORequest, event: dict[str, Any]) -> None:
        if not self.closed and request.owner == self.bg_owner:
            self._background_event(request, event)
            return
        if self.closed or request.owner != self.model.owner or request.generation != self.model.generation:
            return
        kind = event["kind"]
        if request.operation == "resolve":
            if kind == "resolved":
                self.open_to_path(event["path"])
            elif kind == "error":
                self.tree.setRootIndex(self.model.setRootPath(self.target_path, scan=False))
                if self.model.root:
                    self.model.root.state = "error"
                    self.model.root.error = event["message"]
                    self.model.changed(self.model.root)
                self.scan_label.setText(event["message"])
                self.emit_root_path_changed()
                self.selectionPathChanged.emit(self.target_path)
            return
        if request.operation == "invalidate":
            if kind == "done":
                self.load_error = ""
                if self.folder_opened_path == request.path:
                    self.folder_opened_path = None
                self.model.request_scan(request.path, priority=True, force=True)
            elif kind == "error":
                self.load_error = event["message"]
                self.loadStateChanged.emit()
            return
        if request.operation != "load" or request.path != self._load_path:
            return
        if kind in ("queued", "started"):
            self.load_queued = kind == "queued"
            self.model.set_load_state(request.path, "queued" if self.load_queued else "loading")
            self.load_attempt = event.get("attempt", self.load_attempt)
            if event.get("retry"):
                self.load_progress = None
                self.load_files = self.load_failed_files = 0
                self.load_total_files = None
                self.load_source = self.load_cache_reason = self.load_cache_warning = ""
        elif kind == "file_started":
            self.load_attempt = event.get("attempt", self.load_attempt)
        elif kind == "progress":
            self.load_progress = event["progress"]
            self.load_files = event.get("loaded_files", self.load_files)
            self.load_total_files = event.get("total_files", self.load_total_files)
            self.load_failed_files = event.get("failed_files", self.load_failed_files)
        elif kind == "load_source":
            self.load_source = event["source"]
            self.load_cache_reason = event.get("cache_reason", "")
            logging.info("Folder load %s: source=%s; cache=%s; reason=%s", request.path,
                         self.load_source, request.payload.get("cache", {}).get("directory", ""),
                         self.load_cache_reason or "cache hit")
        elif kind == "cache_warning":
            self.load_cache_warning = event["message"]
            logging.warning("Folder cache %s: %s", request.path, self.load_cache_warning)
        elif kind == "loaded":
            self.load_source = event.get("source", "")
            self.load_cache_reason = event.get("cache_reason", "")
            dataset = event["dataset"]
            assert isinstance(dataset, Dataset)
            self.model.cache.retain(self.model.owner, dataset)
            self.folder_opened_data = dict(dataset.data)
            self.folder_opened_path = request.path
            self.model.folder_opened_path = request.path
            self.load_bytes = event["bytes"]
            self.loading = False
            report = self.model.fetch_status(request.path)
            report.problematic_txy_ns = event["problematic"]
            report.loaded_txy_files_count = event["files"]
            report.loaded_txy_rows_count = event["rows"]
            report.time_load_ram = datetime.now()
            report.data_dict_bytes = event["bytes"]
            report.extra_icons = ["ram_opened"]
            self.model.set_load_state(request.path, "")
            node = self.model.nodes.get(request.path)
            if node:
                self._loaded_signature = event.get("signature", node.signature)
                self.model.changed(node)
            self.dataLoaded.emit(request.path)
        elif kind in ("error", "cancelled"):
            self.loading = False
            self._loading_data.clear()
            self.load_error = event.get("message", "Cancelled — Retry")
            self.model.set_load_state(request.path, "")
        self._update_activity()
        self.loadStateChanged.emit()

    def _shared_dataset_changed(self, path: str) -> None:
        if path == self.selected_path_globally:
            node = self.model.nodes.get(path)
            dataset = self.model.cache.current_dataset(path)
            if dataset is None:
                if self.folder_opened_path == path:
                    self.folder_opened_path = None
                # Keep the previous arrays/plots until a successful replacement.
            elif node and dataset.signature == node.signature and self.auto_load_ram:
                self.selectionPathChanged.emit(path)

    @property
    def loading_message(self) -> str:
        if self.load_queued:
            return "Queued"
        if self.load_progress is None:
            if self.load_attempt > 1:
                return f"Retrying… (attempt {self.load_attempt} of 3)"
            return "Preparing…"
        percent = f"{self.load_progress:.0%}"
        if self.load_total_files is None:
            return percent
        message = f"{self.load_files} of {self.load_total_files} files loaded ({percent})"
        if self.load_failed_files:
            message += f" · {self.load_failed_files} unreadable"
        return message

    @property
    def loading_tooltip(self) -> str:
        parts = [self.loading_message] if self.loading else []
        if self.loading and self.load_attempt > 1:
            parts.append(f"Attempt {self.load_attempt} of 3")
        if self.load_waiting:
            parts.append(f"Queues this folder if it stays selected for {self.DWELL_MS // 1000} s")
        paths = self.model.service.queued_load_paths()
        if paths:
            parts.append("Queued folders:\n" + "\n".join(paths))
        if self._bg_paths:
            parts.append("Loading in the background:\n" + "\n".join(self._bg_paths))
        reason = self.load_cache_warning or self.load_cache_reason
        if reason:
            parts.append(reason)
        return "\n\n".join(parts)

    def _update_activity(self) -> None:
        if self.closed:
            return
        requests = self.model.cache.requests(self.model.owner)
        queued = sum(r.operation == "scan" and self.model.nodes.get(r.path) is not None
                     and self.model.nodes[r.path].state == "queued" for r in requests)
        active = max(0, len(requests) - queued)
        node = self.model.nodes.get(self.selected_path_globally)
        error = self.load_error or (node.error if node else "")
        root_error = self.model.root.error if self.model.root else ""
        scans = any(r.operation == "scan" for r in requests)
        resolving = any(r.operation == "resolve" for r in requests)
        loading_action = {"disk": "Loading from disk cache", "files": "Reading TXY files",
                          "merged": "Reading new TXY files into disk cache",
                          "updated": "Reading new TXY files",
                          "memory": "Reusing data in memory"}.get(self.load_source, "Checking for cached data")
        ready = "Ready"
        if self.folder_opened_path == self.selected_path_globally:
            origin = {"disk": "disk cache", "files": "TXY files", "merged": "disk cache + new TXY files",
                      "updated": "memory + new TXY files", "memory": "memory"}.get(self.load_source)
            if origin:
                ready = f"Ready · Loaded from {origin}"
                # The merge counts are long; they stay in the tooltip only.
                if self.load_cache_reason and self.load_source not in ("merged", "updated"):
                    ready += f" · {self.load_cache_reason}"
        action = ("Queued" if self.loading and self.load_queued else
                  "Finding default folder…" if resolving else loading_action if self.loading
                  else "Checking for changes" if scans and node and node.loaded else "Scanning folders")
        status = "Queued" if self.loading and self.load_queued else f"{action} · {queued} queued"
        background = len(self._bg_paths)
        text = " · ".join(filter(None, (
            status if requests or self.loading else "" if self.load_waiting else ready,
            f"Waiting {self.DWELL_MS // 1000} s before queueing" if self.load_waiting else "",
            f"{background} loading in background" if background else "")))
        self.scan_label.setText(error or root_error or text)
        self.scan_label.setToolTip(self.loading_tooltip)
        self.progress.setToolTip(self.loading_tooltip)
        busy = self.loading or bool(active or queued or background)
        self.spinner_label.setVisible(busy)
        if busy:
            pixel_ratio = self.spinner_label.devicePixelRatioF()
            pixmap = QPixmap(round(16 * pixel_ratio), round(16 * pixel_ratio))
            pixmap.setDevicePixelRatio(pixel_ratio)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            paint_spinner(painter, QRect(3, 3, 10, 10), self.delegate.angle)
            painter.end()
            self.spinner_label.setPixmap(pixmap)
        self.retry_button.setVisible(bool(error or root_error))
        self.progress.setVisible(busy)
        if not self.loading and (active or queued or background):
            self.progress.setRange(0, 0)
        if self.loading:
            if self.load_progress is None:
                self.progress.setRange(0, 0)
            else:
                self.progress.setRange(0, 100)
                self.progress.setValue(round(self.load_progress * 100))

    def _animate(self) -> None:
        self.delegate.angle = (self.delegate.angle + 30) % 360
        if self.model.service.active or self.model.service.pending:
            viewport = self.tree.viewport()
            if viewport:
                viewport.update()
        self._update_activity()

    def _directory_loaded(self, path: str) -> None:
        depth = self._deep_depth.pop(path, 0)
        node = self.model.nodes.get(path)
        if depth > 0 and node:
            self._deep.append((iter(node.children), depth - 1))

    def _dispatch_deep(self) -> None:
        if self.closed or len(self.model.service.pending) >= 16:
            return
        for _ in range(2):
            while self._deep:
                source, depth = self._deep[-1]
                node = next(source, None)
                if node is None:
                    self._deep.pop()
                    continue
                self._deep_depth[node.path] = max(depth, self._deep_depth.get(node.path, 0))
                self.model.request_scan(node.path, force=True)
                break

    def context_menu_action_deep_calc_status(self, path: str, max_depth: int = 0,
                                            invalidate_cache: bool = True) -> None:
        node = self.model.nodes.get(path)
        if node:
            self._deep.append((iter((node,)), max_depth))

    def show_context_menu(self, position: QPoint) -> None:
        index = self.tree.indexAt(position)
        if not index.isValid():
            return
        self.tree.setCurrentIndex(index)
        path = self.model.filePath(index)
        menu = QMenu(self)
        menu.addAction("Open folder", lambda: self.open_to_path(path))
        menu.addAction("Open in File Manager", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
        clipboard = QApplication.clipboard()
        if clipboard:
            menu.addAction("Copy Pathname", lambda: clipboard.setText(path))
        menu.addAction("Retry / Refresh", lambda: self.model.request_scan(path, priority=True, force=True))
        submenu = menu.addMenu("Recalculate Status")
        if submenu:
            for depth in (0, 1, 2, 3, 32768):
                submenu.addAction("All subfolders" if depth == 32768 else f"Depth {depth}", lambda checked=False, d=depth: self.context_menu_action_deep_calc_status(path, d))
        menu.addAction("Load data", lambda: self.queue_load(path))
        menu.addAction("Clear loaded data cache", lambda: self.clear_data_cache(path))
        cancel_action = menu.addAction("Cancel Loading", self.cancel_loading)
        if cancel_action:
            cancel_action.setEnabled(self.can_cancel_loading)
        viewport = self.tree.viewport()
        if viewport:
            menu.exec(viewport.mapToGlobal(position))

    def clear_data_cache(self, path: str) -> None:
        self.model.cache.cancel(self.model.owner, "load")
        self.load_error = ""
        cache = {"directory": os.path.join(DIR_CACHES, "data_ram_cache"),
                 "params": dict(load_cache_param("data_ram_cache"))}
        if not self.model.cache.submit(self.model.owner, self.model.generation, path, "invalidate",
                                         {"cache": cache}, priority=True):
            self.load_error = "Cache request queue full — Retry"
        self.loadStateChanged.emit()

    def on_double_click(self, index: QModelIndex) -> None:
        self.open_to_path(self.model.filePath(index))

    def on_back_button_clicked(self) -> None:
        self.open_to_path(os.path.dirname(self.view_path))

    def update_back_button_state(self) -> None:
        self.back_button_enabled = os.path.dirname(self.view_path) != self.view_path
        self.back_button.setEnabled(self.back_button_enabled)

    def get_selection_model(self) -> QItemSelectionModel:
        selection = self.tree.selectionModel()
        assert selection is not None
        return selection

    def get_selected_path_from_model(self) -> str:
        return self.selected_path_globally

    def emit_selection_changed(self) -> None:
        self.selectionPathChanged.emit(self.selected_path_globally)

    def clear_selection(self) -> None:
        self.get_selection_model().clearSelection()

    def emit_root_path_changed(self) -> None:
        self.rootPathChanged.emit(self.view_path)

    def tab_title_update(self) -> str:
        self.tab_title_str = os.path.basename(self.view_path.rstrip(os.sep)) or self.view_path
        return self.tab_title_str

    def rescan(self, user_intend: bool = False) -> None:
        self.model.request_scan(self.selected_path_globally, priority=True, force=True)
        self.model.rescan(user_intend)

    def refresh(self) -> None:
        self.rescan(True)

    def _cancel_background(self) -> None:
        self._stop_dwell()
        self.model.cache.cancel(self.bg_owner, "load")
        for path in self._bg_paths:
            self.model.set_load_state(path, "")
        self._bg_paths.clear()

    def cancel_loading(self) -> None:
        """Cancel this tab's load subscriptions, keeping scans and other tabs alive."""
        if not self.can_cancel_loading:
            return
        visible_load = self.loading or self.load_waiting
        self._cancelled_load_path = self.selected_path_globally
        self._cancel_background()
        self.model.cache.cancel(self.model.owner, "load")
        if self._load_path is not None:
            self.model.set_load_state(self._load_path, "")
        self._load_path = None
        self.loading = self.load_queued = False
        self._loading_data.clear()
        if visible_load:
            self.load_error = "Cancelled — Retry"
        self._update_activity()
        self.loadStateChanged.emit()

    def on_stop_button_clicked(self) -> None:
        self._deep.clear()
        self._deep_depth.clear()
        self.cancel_loading()
        self.model.stop_all_scans()
        self.loading = False
        self._loading_data.clear()
        self.loadStateChanged.emit()

    def close_cleanup(self) -> None:
        if self.closed:
            return
        self._cancel_background()
        self.closed = True
        self.animation.stop()
        self.deep_timer.stop()
        self.model.close_cleanup()
        self.model.cache.resultReady.disconnect(self._io_event)
        self.model.cache.datasetChanged.disconnect(self._shared_dataset_changed)
        self.model.cache.release(self.model.owner)
        self.folder_opened_data = None
        self._loading_data.clear()
