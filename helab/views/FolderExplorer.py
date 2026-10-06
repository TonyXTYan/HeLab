"""Folder browser backed by isolated I/O and memory snapshots."""
from __future__ import annotations

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
from helab.utils.constants import DIR_CACHES


def paint_spinner(painter: QPainter, rect: QRect, angle: int, selected: bool = False) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("white" if selected else "#3989c9"), 2.5))
    painter.drawArc(rect, angle * 16, 260 * 16)
    painter.restore()


class ScanDelegate(QStyledItemDelegate):
    angle = 0

    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem | None, index: QModelIndex) -> None:
        if painter is None or option is None:
            return
        super().paint(painter, option, index)
        if index.data(SnapshotFileSystemModel.BUSY_ROLE):
            selected = bool(option.state & QStyle.StateFlag.State_Selected)
            rect = QRect(option.rect.left() + 7, option.rect.top() + (option.rect.height() - 10) // 2, 10, 10)
            paint_spinner(painter, rect, self.angle, selected)
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
        self._loading_data: dict[int, npt.NDArray[np.float64]] = {}
        self._loaded_signature = ""
        self._deep: list[tuple[Iterator[FolderNode], int]] = []
        self._deep_depth: dict[str, int] = {}
        self.model = SnapshotFileSystemModel(self)
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
        self.stop_button = QPushButton("Cancel", self)
        self.stop_button.clicked.connect(self.on_stop_button_clicked)
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
        for widget in (self.back_button, self.path_edit, self.retry_button, self.stop_button):
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
        self.loading = False
        self._loading_data.clear()
        self._load_path = None
        self.load_error = ""
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
            self.load_to_ram_cache(self.selected_path_globally)
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
                self.model.cache.cancel(self.model.owner, "load")
                self._load_path = None
                self._loading_data.clear()
                self.loading = False
                self.load_error = ""
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

    def load_to_ram_cache(self, path: str) -> bool:
        report = self.model.fetch_status(path)
        if report.status not in StatusReport.STATUS_CONTAINS_DATA_HERE or not report.d_txy_shots:
            return False
        if self.folder_opened_path == path and self.folder_opened_data is not None:
            self.dataLoaded.emit(path)
            return False
        if self.loading and self._load_path == path:
            return True
        self.model.cache.cancel(self.model.owner, "load")
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
        node = self.model.nodes.get(path)
        if node:
            node.loading = True
            self.model.changed(node)
        cache = {"directory": os.path.join(DIR_CACHES, "data_ram_cache"),
                 "params": dict(load_cache_param("data_ram_cache"))}
        accepted = self.model.cache.submit(self.model.owner, self.model.generation, path, "load",
                                           {"cache": cache, "signature": node.signature if node else ""},
                                           priority=True)
        if not accepted:
            self.loading = False
            self.load_error = "Load queue full — Retry"
            if node:
                node.loading = False
        self.loadStateChanged.emit()
        return accepted

    def _io_event(self, request: IORequest, event: dict[str, Any]) -> None:
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
            node = self.model.nodes.get(request.path)
            if node:
                node.loading = False
                self._loaded_signature = event.get("signature", node.signature)
                self.model.changed(node)
            self.dataLoaded.emit(request.path)
        elif kind in ("error", "cancelled"):
            self.loading = False
            self._loading_data.clear()
            self.load_error = event.get("message", "Cancelled — Retry")
            node = self.model.nodes.get(request.path)
            if node:
                node.loading = False
                self.model.changed(node)
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
        paths = self.model.service.queued_load_paths()
        if paths:
            parts.append("Queued folders:\n" + "\n".join(paths))
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
        self.scan_label.setText(error or root_error or (status if requests or self.loading else ready))
        self.scan_label.setToolTip(self.loading_tooltip)
        self.progress.setToolTip(self.loading_tooltip)
        busy = self.loading or bool(active or queued)
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
        self.stop_button.setEnabled(bool(active or queued or self._deep or self.loading))
        self.progress.setVisible(busy)
        if not self.loading and (active or queued):
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
        menu.addAction("Load data", lambda: self.load_to_ram_cache(path))
        menu.addAction("Clear loaded data cache", lambda: self.clear_data_cache(path))
        menu.addAction("Cancel", self.on_stop_button_clicked)
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

    def on_stop_button_clicked(self) -> None:
        self._deep.clear()
        self._deep_depth.clear()
        self.model.stop_all_scans()
        self.loading = False
        self._loading_data.clear()
        self.loadStateChanged.emit()

    def close_cleanup(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.animation.stop()
        self.deep_timer.stop()
        self.model.close_cleanup()
        self.model.cache.resultReady.disconnect(self._io_event)
        self.model.cache.datasetChanged.disconnect(self._shared_dataset_changed)
        self.model.cache.release(self.model.owner)
        self.folder_opened_data = None
        self._loading_data.clear()
