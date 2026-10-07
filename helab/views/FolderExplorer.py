"""Folder browser backed by isolated I/O and memory snapshots."""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
import logging
import os
import time
from typing import Any, Iterator

import numpy as np
import numpy.typing as npt
from PyQt6.QtCore import QEvent, QObject, QItemSelection, QItemSelectionModel, QModelIndex, QPoint, QRect, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFontMetrics, QIcon, QPainter, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit, QMenu, QProgressBar,
                             QPushButton, QStyledItemDelegate, QStyleOptionViewItem, QTreeView, QInputDialog,
                             QStyle, QToolButton, QVBoxLayout, QWidget, QSizePolicy)
from helab.models.SnapshotFileSystemModel import FolderNode, SnapshotFileSystemModel
from helab.models.StatusReport import StatusReport
from helab.utils.io_service import IORequest
from helab.utils.folder_cache import Dataset
from helab.utils.caching_setup import load_cache_param
from helab.utils.constants import DEFAULT_LOAD_MODE, DIR_CACHES
from helab.utils.time_format import duration, relative_age
from helab.utils.cache_freshness import CacheFreshness, data_as_of, freshness_tooltip, metadata_date
from helab.utils.scan_history import history_tooltip


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
        extras = index.data(SnapshotFileSystemModel.STATUS_EXTRA_ICONS_ROLE)
        icons = [icon for icon in extras if isinstance(icon, QIcon)] if isinstance(extras, list) else []
        item = QStyleOptionViewItem(option)
        self.initStyleOption(item, index)
        text = item.text
        if icons:
            item.text = ""  # Drawn after the badges below so they never overlap.
        style = item.widget.style() if item.widget else QApplication.style()
        if style:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, item, painter, item.widget)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        rect = QRect(option.rect.left() + 7, option.rect.top() + (option.rect.height() - 10) // 2, 10, 10)
        if index.data(SnapshotFileSystemModel.BUSY_ROLE):
            paint_spinner(painter, rect, self.angle, selected)
        elif index.data(SnapshotFileSystemModel.LOAD_QUEUED_ROLE):
            paint_queued(painter, rect, selected)
        for i, icon in enumerate(icons):
            icon.paint(painter, QRect(option.rect.left() + 24 + i * 18,
                                     option.rect.top() + (option.rect.height() - 16) // 2, 16, 16))
        if icons and text:
            left = option.rect.left() + 24 + len(icons) * 18 + 2
            rect = QRect(left, option.rect.top(), max(0, option.rect.right() - left), option.rect.height())
            role = QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
            painter.save()
            painter.setFont(item.font)
            painter.setPen(item.palette.color(role))
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                             QFontMetrics(item.font).elidedText(text, Qt.TextElideMode.ElideRight, rect.width()))
            painter.restore()


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
        # Kept with the displayed arrays when navigation or refresh retains old data.
        self.displayed_dataset: Dataset | None = None
        self.back_button_enabled = False
        self.closed = False
        self.loading = False
        self.load_progress: float | None = None
        self.load_queued = False
        # The selected load waits while this tab lists a folder (cooperative pause).
        self.load_paused = False
        self.load_attempt = 1
        # Listing/stat heartbeats before the first file, e.g. "Listing files… 3,200".
        self.load_listing = ""
        self.load_files = 0
        self.load_total_files: int | None = None
        self.load_failed_files = 0
        self.load_source = ""
        self.load_counts: dict[str, int] = {}
        self._load_cache_pending = False
        self.load_cache_reason = ""
        self.load_cache_warning = ""
        self.load_error = ""
        self.load_bytes = 0
        self._load_path: str | None = None
        self._cancelled_load_path: str | None = None
        self._loading_data: dict[int, npt.NDArray[np.float64]] = {}
        self._deep: list[tuple[Iterator[FolderNode], int]] = []
        self._deep_depth: dict[str, int] = {}
        self._basic_active = False
        self._basic_seen: set[str] = set()
        self._basic_roots: set[str] = set()
        self._basic_completed = self._basic_failed = 0
        self._basic_result = ""
        self._visible_seen: set[str] = set()
        self.auto_scan_visible = False
        self._load_mode = DEFAULT_LOAD_MODE
        # Loads this tab no longer shows, in queue order; they only fill the caches.
        self._bg_paths: OrderedDict[str, None] = OrderedDict()
        self._dwell = QTimer(self)
        self._dwell.setSingleShot(True)
        self._dwell.timeout.connect(self._dwell_elapsed)
        self._dwell_path: str | None = None
        self.model = SnapshotFileSystemModel(self)
        self.bg_owner = f"{self.model.owner}:bg"
        if not self.model.cache.foreground_owners:
            # The first tab; FolderTabWidget hands the foreground to the current tab.
            self.claim_foreground()
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
        self.basic_scan_button = QToolButton(self)
        self.basic_scan_button.setText("Basic scan")
        self.basic_scan_button.setToolTip("Check folder counts and status without loading TXY data")
        self.basic_scan_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        scan_menu = QMenu(self.basic_scan_button)
        scan_menu.addAction("Folders in view", lambda: self.start_basic_scan("view"))
        scan_menu.addAction("Current folder", lambda: self.start_basic_scan("current"))
        scan_menu.addAction("Recursive depth…", self._choose_scan_depth)
        scan_menu.addAction("All subfolders", lambda: self.start_basic_scan("recursive", 32768))
        self.basic_scan_button.setMenu(scan_menu)
        self.basic_scan_button.clicked.connect(self._basic_scan_clicked)
        self.back_button.clicked.connect(self.on_back_button_clicked)
        self.retry_button = QPushButton("Retry", self)
        self.retry_button.clicked.connect(self._retry)
        self.scan_label = QLabel(self)
        self.summary_widget = QWidget(self)
        self.selected_folder_row = QWidget(self.summary_widget)
        self.folder_counts_row = QWidget(self.summary_widget)
        self.selected_folder_label = QLabel(self)
        self.deselect_button = QToolButton(self.selected_folder_row)
        self.deselect_button.setText("Deselect")
        self.deselect_button.setToolTip("Clear subfolder selection and view the displayed path")
        self.deselect_button.clicked.connect(self.clear_selection)
        self.cancel_load_button = QToolButton(self.folder_counts_row)
        self.cancel_load_button.setText("Cancel")
        self.cancel_load_button.setToolTip("Cancel loading in this tab (Esc)")
        self.cancel_load_button.clicked.connect(self.cancel_loading)
        self.cancel_load_button.hide()
        self.folder_summary_label = QLabel("Scanning folder content for TXY files…", self)
        self.folder_cache_label = QLabel(self)
        self.folder_freshness_label = QLabel("Live updates off", self)
        for label in (self.selected_folder_label, self.folder_summary_label,
                      self.folder_cache_label, self.folder_freshness_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setMinimumWidth(0)
        self.selected_folder_row.hide()
        self.selected_folder_label.hide()
        self.deselect_button.hide()
        self.selected_folder_label.setWordWrap(False)
        summary_font = self.folder_summary_label.font()
        summary_font.setBold(True)
        self.folder_summary_label.setFont(summary_font)
        freshness_font = self.folder_freshness_label.font()
        freshness_font.setPointSizeF(max(8.0, freshness_font.pointSizeF() - 1.0))
        self.folder_freshness_label.setFont(freshness_font)
        self.folder_cache_label.setFont(freshness_font)
        line_height = max(label.fontMetrics().height() for label in (
            self.selected_folder_label, self.folder_summary_label,
            self.folder_cache_label, self.folder_freshness_label))
        for label in (self.selected_folder_label, self.folder_summary_label,
                      self.folder_cache_label, self.folder_freshness_label):
            label.setMinimumHeight(line_height)
        for label in (self.folder_cache_label, self.folder_freshness_label):
            label.setWordWrap(False)
            label.setFixedHeight(line_height)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.selected_folder_row.setFixedHeight(line_height)
        for button in (self.deselect_button, self.cancel_load_button):
            button.setFont(freshness_font)
            button.setFixedHeight(line_height)
            button.setStyleSheet("""
                QToolButton { padding: 0px 3px; border: 1px solid palette(mid); border-radius: 2px; }
                QToolButton:hover { background: palette(midlight); }
                QToolButton:pressed { background: palette(mid); }
                QToolButton:focus { border-color: palette(highlight); }
            """)
        self._summary_button_width = max(button.sizeHint().width() for button in (
            self.deselect_button, self.cancel_load_button))
        for button in (self.deselect_button, self.cancel_load_button):
            button.setFixedWidth(self._summary_button_width)
        selected_layout = QHBoxLayout(self.selected_folder_row)
        selected_layout.setContentsMargins(0, 0, 0, 0)
        selected_layout.setSpacing(4)
        selected_layout.addWidget(self.selected_folder_label, 1)
        selected_layout.addWidget(self.deselect_button)
        counts_layout = QHBoxLayout(self.folder_counts_row)
        counts_layout.setContentsMargins(0, 0, 0, 0)
        counts_layout.setSpacing(4)
        counts_layout.addWidget(self.folder_summary_label, 1)
        counts_layout.addWidget(self.cancel_load_button, 0, Qt.AlignmentFlag.AlignTop)
        summary_layout = QVBoxLayout(self.summary_widget)
        summary_layout.setContentsMargins(8, 0, 0, 0)
        summary_layout.setSpacing(0)
        summary_layout.addWidget(self.selected_folder_row)
        summary_layout.addWidget(self.folder_counts_row)
        summary_layout.addWidget(self.folder_cache_label)
        summary_layout.addWidget(self.folder_freshness_label)
        self.spinner_label = QLabel(self)
        self.spinner_label.setFixedSize(16, 16)
        self.spinner_label.hide()
        self.progress = QProgressBar(self)
        self.progress.setMaximumWidth(150)
        self.progress.hide()
        controls = QHBoxLayout()
        controls.addWidget(self.basic_scan_button)
        for widget in (self.back_button, self.path_edit, self.retry_button):
            controls.addWidget(widget)
        status = QHBoxLayout()
        status.addWidget(self.spinner_label)
        status.addWidget(self.scan_label, 1)
        status.addWidget(self.progress)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(controls)
        layout.addWidget(self.summary_widget)
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
        self.visible_timer = QTimer(self)
        self.visible_timer.setSingleShot(True)
        self.visible_timer.timeout.connect(self._check_visible_folders)
        scroll_bar = self.tree.verticalScrollBar()
        if scroll_bar:
            scroll_bar.valueChanged.connect(self._schedule_visible_checks)
        self.tree.collapsed.connect(self._schedule_visible_checks)
        self.model.rowsInserted.connect(self._schedule_visible_checks)
        viewport = self.tree.viewport()
        if viewport:
            viewport.installEventFilter(self)
        # Startup happens after the main window installs its signal handlers.
        if default_candidates:
            QTimer.singleShot(0, lambda: self._resolve_default(default_candidates))
        else:
            QTimer.singleShot(0, lambda: self.open_to_path(self.target_path))

    @property
    def load_mode(self) -> str:
        return self._load_mode

    @load_mode.setter
    def load_mode(self, mode: str) -> None:
        self._load_mode = mode
        if self.is_foreground:
            self.claim_foreground()

    def foreground_owners(self) -> set[str]:
        """In queue mode this tab's queued loads run one by one in the foreground lane."""
        return {self.model.owner} | ({self.bg_owner} if self.load_mode == "queue" else set())

    @property
    def is_foreground(self) -> bool:
        return not self.closed and self.model.owner in self.model.cache.foreground_owners

    def claim_foreground(self) -> None:
        """Run this tab's browsing and selected load in the foreground I/O lane.

        Called when the tab becomes current or its load mode changes; the
        previous tab's work continues as background work.
        """
        if not self.closed:
            self.model.cache.set_foreground(self.foreground_owners())

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
        self._basic_active = False
        self._basic_result = ""
        self._visible_seen.clear()
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
        # A load retry keeps its per-file timeouts; a hung read is genuinely stuck.
        if self.load_error:
            self.load_to_ram_cache(self.selected_path_globally, dwell=False)
        else:
            self.model.request_scan(self.selected_path_globally, priority=True, force=True, no_timeout=True)
            self.model.rescan(True)

    def _expanded(self, index: QModelIndex) -> None:
        node = self.model.node(index)
        if node:
            self.model.request_scan(node.path, priority=True)
        self.itemExpandedSignal.emit(index)
        self._schedule_visible_checks()

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
        if path == self.selected_path_globally and not (
                self._basic_active and path in self._basic_seen | self._basic_roots):
            node = self.model.nodes.get(path)
            dataset = self.displayed_dataset
            if (node and self.folder_opened_path == path and dataset is not None and dataset.path == path
                    and self._changed_since_load(node, dataset)):
                # Keep the displayed data while a fresh load replaces it.
                self.folder_opened_path = None
            self.selectionPathChanged.emit(path)

    @staticmethod
    def _changed_since_load(node: FolderNode, dataset: Dataset) -> bool:
        """Whether the folder no longer matches a loaded dataset.

        After a names-only listing the signature is unknown until the details scan
        or a load supplies it; the TXY shot list still shows added or removed files.
        """
        if node.signature:
            return node.signature != dataset.signature
        loaded = sorted(int(entry[0]) for entry in dataset.metadata.get("fingerprint", ()))
        return node.report is not None and bool(loaded) and sorted(node.report.d_txy_shots or []) != loaded

    @property
    def load_waiting(self) -> bool:
        """The selected folder will be queued if it stays selected."""
        return self._dwell.isActive()

    @property
    def can_cancel_loading(self) -> bool:
        """Loads in this tab, or a manual folder-listing retry, which has no timeout."""
        return not self.closed and bool(self.loading or self.load_waiting or self._bg_paths
                                        or self.retrying_scan is not None)

    @property
    def retrying_scan(self) -> FolderNode | None:
        """The selected folder's running manual retry, which only Cancel can stop."""
        node = self.model.nodes.get(self.selected_path_globally)
        return node if node and node.retry_since is not None and node.state in ("queued", "running") else None

    @staticmethod
    def retry_message(node: FolderNode) -> str:
        assert node.retry_since is not None
        text = f"Retrying… {duration(time.monotonic() - node.retry_since)}"
        return text + (f" · {node.listed:,} entries" if node.listed else "")

    @property
    def deselect_tooltip(self) -> str:
        path = self.selected_path_globally
        prefix = "View the displayed path. "
        if self.load_waiting and self._dwell_path == path:
            return prefix + "The selected folder will not be queued."
        if self.loading and self._load_path == path:
            if self.load_mode == "cancel":
                return prefix + "This tab's load of the selected folder will be cancelled."
            if self.load_mode == "finish":
                return prefix + ("The selected folder will be removed from this tab's load queue."
                                 if self.load_queued else "The selected folder will finish loading in the background.")
            return prefix + ("The selected folder will remain queued in the background." if self.load_queued else
                             "The selected folder will continue loading in the background.")
        if path in self._bg_paths:
            return prefix + ("The selected folder will remain queued in the background."
                             if self.model.load_states.get(path) == "queued" else
                             "The selected folder will continue loading in the background.")
        return "Clear selection and view the displayed path."

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
        self.loading = self.load_paused = False
        self.load_error = ""

    def _trim_background(self) -> None:
        queued = [p for p in self._bg_paths if self.model.load_states.get(p) == "queued"]
        for path in queued[:max(0, len(queued) - self.MAX_BACKGROUND_LOADS)]:
            self.model.cache.cancel(self.bg_owner, "load", path)

    def _begin_load(self, path: str) -> None:
        self.loading, self.load_progress, self.load_error = True, None, ""
        self.load_queued = True
        self.load_paused = False
        self.load_attempt = 1
        self.load_listing = ""
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
        node = self.model.nodes.get(path)
        if node and node.cached_report:
            return False
        report = self.model.fetch_status(path)
        return report.status in StatusReport.STATUS_CONTAINS_DATA_HERE and bool(report.d_txy_shots)

    def load_to_ram_cache(self, path: str, *, dwell: bool = True, explicit: bool = False) -> bool:
        """Show this folder's data, loading it as the tab's visible load."""
        # A scan finishing after Cancel must not restart automatic loading.
        if dwell and path == self._cancelled_load_path:
            return False
        if not dwell:
            self._cancelled_load_path = None
        if not explicit and not self._has_data(path):
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
            return self.load_to_ram_cache(path, dwell=False, explicit=True)
        if path in self._bg_paths or (self.loading and self._load_path == path):
            return True
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
        if kind in ("queued", "started", "resumed"):
            self.model.set_load_state(path, "queued" if kind == "queued" else "loading")
        elif kind == "paused":
            self.model.set_load_state(path, "paused")
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
        if request.operation in ("list", "details", "scan"):
            if request.operation == "scan" and kind in ("error", "cancelled"):
                self._finish_basic_folder(request.path, failed=True)
            return
        if request.operation != "load" or request.path != self._load_path:
            return
        if kind in ("paused", "resumed"):
            self.load_paused = kind == "paused"
            if not self.load_queued:
                self.model.set_load_state(request.path, "paused" if self.load_paused else "loading")
        elif kind in ("queued", "started"):
            self.load_queued = kind == "queued"
            self.load_paused = False
            self.model.set_load_state(request.path, "queued" if self.load_queued else "loading")
            self.load_attempt = event.get("attempt", self.load_attempt)
            if event.get("retry"):
                self.load_progress = None
                self.load_listing = ""
                self.load_files = self.load_failed_files = 0
                self.load_total_files = None
                self.load_source = self.load_cache_reason = self.load_cache_warning = ""
        elif kind == "file_started":
            self.load_attempt = event.get("attempt", self.load_attempt)
        elif kind == "heartbeat":
            if self.load_progress is None:
                verb = "Listing" if event.get("phase") == "listing" else "Checking"
                self.load_listing = f"{verb} files… {int(event.get('entries', 0)):,}"
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
            self.load_paused = False
            self.load_source = event.get("source", "")
            self.load_counts = dict(event.get("load_counts", {}))
            self._load_cache_pending = bool(event.get("disk_cache_pending"))
            self.load_cache_reason = event.get("cache_reason", "")
            dataset = event["dataset"]
            assert isinstance(dataset, Dataset)
            self.model.cache.retain(self.model.owner, dataset)
            self.displayed_dataset = dataset
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
                self.model.changed(node)
            self.dataLoaded.emit(request.path)
        elif kind in ("error", "cancelled"):
            self.loading = self.load_paused = False
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
            elif (node and dataset.signature == node.signature and self.auto_load_ram
                  and not (self._basic_active and path in self._basic_seen | self._basic_roots)):
                self.selectionPathChanged.emit(path)

    @property
    def loading_message(self) -> str:
        if self.load_queued:
            return "Queued"
        paused = " · Paused" if self.load_paused else ""
        if self.load_progress is None:
            parts = [f"Retrying… (attempt {self.load_attempt} of 3)"] if self.load_attempt > 1 else []
            parts.append(self.load_listing or ("" if parts else "Preparing…"))
            return " · ".join(filter(None, parts)) + paused
        percent = f"{self.load_progress:.0%}"
        if self.load_total_files is None:
            return percent + paused
        message = f"{self.load_files} of {self.load_total_files} files loaded ({percent})"
        if self.load_failed_files:
            message += f" · {self.load_failed_files} unreadable"
        return message + paused

    @property
    def loading_tooltip(self) -> str:
        parts = [self.loading_message] if self.loading else []
        if self.loading and self.load_attempt > 1:
            parts.append(f"Attempt {self.load_attempt} of 3")
        if self.load_waiting:
            parts.append(f"Queues this folder if it stays selected for {self.DWELL_MS // 1000} s")
        queue_details = self.model.service.queue_tooltip()
        if queue_details:
            parts.append(queue_details)
        if self._bg_paths:
            parts.append("Loading in the background:\n" + "\n".join(self._bg_paths))
        reason = self.load_cache_warning or self.load_cache_reason
        if reason:
            parts.append(reason)
        return "\n\n".join(parts)

    def _update_activity(self) -> None:
        if self.closed:
            return
        self._update_folder_summary()
        requests = self.model.cache.requests(self.model.owner)
        queued = sum(r.operation in ("list", "scan") and self.model.nodes.get(r.path) is not None
                     and self.model.nodes[r.path].state == "queued" for r in requests)
        active = max(0, len(requests) - queued)
        node = self.model.nodes.get(self.selected_path_globally)
        error = self.load_error or (node.error if node else "")
        root_error = self.model.root.error if self.model.root else ""
        scans = any(r.operation in ("list", "details", "scan") for r in requests)
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
        status = "Queued" if self.loading and self.load_queued else action
        background = len(self._bg_paths)
        text = " · ".join(filter(None, (
            status if requests or self.loading else "" if self.load_waiting else ready,
            f"Waiting {self.DWELL_MS // 1000} s before queueing" if self.load_waiting else "",
            f"{background} loading in background" if background else "")))
        self.basic_scan_button.setText("Cancel scan" if self._basic_active else "Basic scan")
        if self._basic_active:
            text = f"Basic scan: {self._basic_completed:,} scanned · {len(self._deep_depth):,} checking"
            if self._basic_failed:
                text += f" · {self._basic_failed:,} failed"
        elif self._basic_result and not (requests or self.loading):
            text = self._basic_result
        # Retries held behind a stopping helper are described by the stopping summary.
        queued_count = len(self.model.service.queued_operations(include_held=False))
        stopping_count = len(self.model.service.retired)
        if stopping := self.model.service.stopping_summary():
            if self.model.service.pending and not self.model.service.active:
                text = stopping
            else:
                text += f" · {stopping}"
        if queued_count:
            text += f" · {queued_count} queued"
        self.scan_label.setText(self.load_error or text if self._basic_active or self._basic_result
                                else error or root_error or text)
        self.scan_label.setToolTip(self.loading_tooltip)
        self.progress.setToolTip(self.loading_tooltip)
        busy = self.loading or bool(active or queued or background or queued_count or stopping_count)
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
        if not self.loading and (active or queued or background or queued_count or stopping_count):
            self.progress.setRange(0, 0)
        if self.loading:
            if self.load_progress is None:
                self.progress.setRange(0, 0)
            else:
                self.progress.setRange(0, 100)
                self.progress.setValue(round(self.load_progress * 100))

    def _update_folder_summary(self) -> None:
        """Describe the active folder from memory; never probe the filesystem."""
        path = self.selected_path_globally
        node = self.model.nodes.get(path)
        report = node.report if node else None
        selected = path != self.view_path
        self.selected_folder_row.setVisible(selected)
        self.selected_folder_label.setVisible(selected)
        self.deselect_button.setVisible(selected)
        self.deselect_button.setToolTip(self.deselect_tooltip)
        self.cancel_load_button.setVisible(self.can_cancel_loading)
        retrying = self.retrying_scan
        self.cancel_load_button.setToolTip(
            "Cancel the folder listing retry (Esc)" if retrying and not (self.loading or self.load_waiting)
            else "Cancel loading in this tab (Esc)")
        if selected:
            metrics = self.selected_folder_label.fontMetrics()
            scope = metrics.elidedText(os.path.relpath(path, self.view_path), Qt.TextElideMode.ElideMiddle,
                                       max(0, self.width() - 8 - self._summary_button_width
                                           - 4 - metrics.horizontalAdvance("Selected: ")))
            self.selected_folder_label.setText(f"Selected: {scope}")
        else:
            self.selected_folder_label.clear()
        self.selected_folder_label.setToolTip(path)
        scanning = node is not None and node.state in ("queued", "running")
        scan_error = node.error if node else ""
        history = self.model.cache.scan_history(path)
        dataset = self.displayed_dataset
        shown = dataset is not None and dataset.path == path
        changed = bool(shown and node and report and not node.cached_report and
                       self._changed_since_load(node, dataset)) if dataset else False
        if shown and dataset is not None and not (self.loading and self._load_path == path):
            failed = int(dataset.metadata.get("failed_files", 0))
            loaded = int(dataset.metadata["files"])
            found = (len(report.d_txy_shots or []) if changed and report else
                     int(dataset.metadata.get("total_files", loaded + failed)))
            text = f"{found:,} TXY found · {loaded:,} {'previously loaded' if changed else 'loaded'}"
            if failed:
                text += f" · {failed:,} unreadable"
            if changed:
                text += " · Changes detected"
            elif self.folder_opened_path != path:
                text += " · Previous data"
            if self.load_error:
                text += f" · {self.load_error}"
        elif report is None:
            text = (self.retry_message(retrying) if retrying else
                    "TXY count not checked · Retry manually" if history["blocked"] or node and node.scan_skipped else
                    "Could not check folder · Retry" if scan_error else
                    f"Listing… {node.listed:,} entries" if node and scanning and node.listed else
                    "Scanning folder content for TXY files…")
        elif report.d_txy_shots or node and node.txy_count:
            found = (self.load_total_files if self.loading and self._load_path == path
                     and self.load_total_files is not None else node.txy_count if node else len(report.d_txy_shots or []))
            text = f"{found:,} TXY found"
            if self.loading and self._load_path == path:
                if self.load_queued or self.load_progress is None:
                    text += f" · {self.loading_message}"
                else:
                    text += f" · {self.load_files:,} loaded ({self.load_progress:.0%})"
                    if self.load_failed_files:
                        text += f" · {self.load_failed_files:,} unreadable"
                    if self.load_paused:
                        text += " · Paused"
            elif dataset and dataset.path == path:
                loaded = int(dataset.metadata["files"])
                text += f" · {loaded:,} loaded"
                failed = int(dataset.metadata.get("failed_files", 0))
                if failed:
                    text += f" · {failed:,} unreadable"
                if self.folder_opened_path != path:
                    text += " · Previous data"
            else:
                text += " · Not loaded"
            if self.load_error:
                text += f" · {self.load_error}"
            elif self.load_waiting:
                text += f" · Waiting {self.DWELL_MS // 1000} s before queueing"
        elif report.d_dld_shots or node and node.raw_count:
            raw = node.raw_count if node else len(report.d_dld_shots or [])
            text = f"{raw:,} raw shot{'s' if raw != 1 else ''} found · No converted TXY files"
        elif node and node.loaded and node.empty:
            text = "Folder is empty"
        elif node and node.loaded and node.children:
            text = "No TXY files here · Select a subfolder to load data"
        else:
            text = "No TXY files in this folder"
        if report is not None:
            if scan_error:
                text += " · Refresh failed · Retry"
            elif retrying:
                text += f" · {self.retry_message(retrying)}"
            elif scanning:
                text += " · Checking for changes…"
        self.folder_summary_label.setText(text)
        load_details = ""
        if shown and dataset is not None:
            rows = int(dataset.metadata.get("rows", 0))
            loaded_at = dataset.metadata.get("loaded_at")
            load_details = f"{rows:,} data rows loaded"
            if isinstance(loaded_at, (int, float)):
                load_details += f"\nData loaded: {datetime.fromtimestamp(loaded_at).astimezone():%Y-%m-%d %H:%M:%S %Z}"
            problematic = dataset.metadata.get("problematic", [])
            if problematic:
                load_details += f"\nShots with content/read errors: {', '.join(map(str, problematic[:20]))}"
            if changed:
                load_details += "\nLoaded data belongs to the previous folder contents. Load data to update it."
        self.folder_summary_label.setToolTip("\n".join(filter(None, (
            path, load_details, scan_error, self.load_error, self.loading_tooltip))))
        self._update_cache_summary(path, report)
        checked_at = node.checked_at if node else 0
        if checked_at and node and node.scanned_at is not None:
            ago = self._relative_age(time.monotonic() - checked_at)
            checked = f"Status scan: {ago} · "
        else:
            checked = "Status scan: " if report else ""
        status_freshness = self.model.status_freshness(node) if node else CacheFreshness.UNKNOWN
        if report and status_freshness.value:
            checked += f"{status_freshness.value} · "
        self.folder_freshness_label.setText(f"{checked}Live updates off")
        if history["blocked"]:
            failed_at = history["failures"][-1]["failed_at"]
            self.folder_freshness_label.setText(
                f"Basic scan failed {self._relative_age(time.time() - failed_at)} · Retry manually")
        self.folder_freshness_label.setToolTip("\n".join(filter(None, (history_tooltip(history, time.time()),
            self.model.cache.scan_history_errors.get(path), freshness_tooltip(
            "Last successful status scan", node.scanned_at if node else None, node.modified if node else None,
            status_freshness, "Use Basic scan / Refresh to recheck counts and status.")))))

    @staticmethod
    def _relative_age(seconds: float) -> str:
        return relative_age(seconds)

    def _update_cache_summary(self, path: str, report: StatusReport | None) -> None:
        cache = self.model.cache
        node = self.model.nodes.get(path)
        visible = cache.disk_cache_known(path) and (cache.disk_cached(path) or report is None
                  or bool(report.d_txy_shots) or bool(node and node.txy_count))
        self.folder_cache_label.setVisible(visible)
        if not visible:
            self.folder_cache_label.clear()
            return
        dataset = self.displayed_dataset
        current = bool(dataset and dataset.path == path and self.folder_opened_path == path)
        state = cache.cache_status(path)
        saved_at = metadata_date(state.info.get("saved_at"))
        ago = self._relative_age(time.time() - saved_at) if isinstance(saved_at, (int, float)) else ""
        suffix = f" · Cached {ago}" if ago else ""
        if cache.disk_cache_saving(path):
            text = "Updating cache…" if cache.disk_cached(path) else "Creating cache…"
        elif state.error:
            text = "Cache update failed" if cache.disk_cached(path) else "Cache creation failed"
        elif (current and self._load_cache_pending and dataset is not None
              and state.info.get("signature") == dataset.signature and ago):
            action = "updated" if state.info.get("action") == "updated" else "created"
            text = f"Cache {action} {ago}"
        elif cache.disk_cached(path):
            reused = current and (self.load_source in ("disk", "memory") or
                                  self.load_counts.get("read") == 0 and
                                  self.load_counts.get("reused_memory", 0) +
                                  self.load_counts.get("reused_disk", 0) > 0)
            text = ("Cached data loaded" if reused else "Cached data found") + suffix
        else:
            text = "No cached data"
        freshness = self.model.data_freshness(node) if node else CacheFreshness.UNKNOWN
        if cache.disk_cached(path) and freshness.value:
            text += f" · {freshness.value}"
        self.folder_cache_label.setText(text)
        origin = {"disk": "disk cache", "files": "TXY files", "merged": "disk cache + new TXY files",
                  "updated": "memory + new TXY files", "memory": "memory"}.get(self.load_source)
        counts = self.load_counts if current else {}
        details = [f"{counts[key]:,} {label.replace('files', 'file') if counts[key] == 1 else label}"
                   for key, label in (
                       ("reused_memory", "reused from memory"), ("reused_disk", "reused from cache"),
                       ("new_loaded", "new files loaded"), ("modified_loaded", "modified files loaded"),
                       ("removed", "files removed"), ("read", "TXY files read")) if counts.get(key)]
        exact = (datetime.fromtimestamp(saved_at).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
                 if isinstance(saved_at, (int, float)) else "")
        self.folder_cache_label.setToolTip("\n".join(filter(None, (
            f"Loaded from {origin}" if origin and current else "",
            " · ".join(details),
            f"Last successful cache save: {exact}" if exact else
            "Cache date not recorded" if cache.disk_cached(path) else "",
            state.error,
            freshness_tooltip("Data cache saved", saved_at, node.modified if node else None,
                freshness, "Use Load data to validate and update the data cache.",
                as_of=data_as_of(state.info)) if cache.disk_cached(path) else "",
            "Cache availability is the last observed status. Disk cache freshness is checked when loading."))))

    def _animate(self) -> None:
        self.delegate.angle = (self.delegate.angle + 30) % 360
        if self.model.service.active or self.model.service.pending:
            viewport = self.tree.viewport()
            if viewport:
                viewport.update()
        self._update_activity()

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 and a1.type() in (QEvent.Type.Show, QEvent.Type.Resize):
            self._schedule_visible_checks()
        return super().eventFilter(a0, a1)

    def _schedule_visible_checks(self, *args: Any) -> None:
        if not self.closed and self.auto_scan_visible:
            self.visible_timer.start(150)

    def set_auto_scan_visible(self, enabled: bool) -> None:
        self.auto_scan_visible = enabled
        self._visible_seen.clear()
        if enabled:
            self._schedule_visible_checks()
        else:
            self.visible_timer.stop()

    def _viewport_paths(self) -> list[str]:
        """Only rows on screen; indexBelow/visualRect query the memory model."""
        return self.model.viewport_paths()

    def _check_visible_folders(self) -> None:
        if self.closed or not self.auto_scan_visible or not self.isVisible():
            return
        paths = self._viewport_paths()
        self._visible_seen.intersection_update(paths)
        for path in paths:
            if path in self._visible_seen:
                continue
            node = self.model.nodes.get(path)
            if node is None:
                continue
            # Automatic discovery fills missing metadata only. Persisted scan
            # results remain useful regardless of age until explicitly refreshed.
            if node.report is not None or self.model.cache.scan_history(path)["blocked"]:
                self._visible_seen.add(path)
                continue
            scans = sum(r.operation == "scan" for r in self.model.cache.requests(self.model.owner))
            if scans >= self.model.service.max_operations or len(self.model.service.pending) >= 16:
                self.visible_timer.start(150)
                return
            if self.model.request_scan(path, metadata_only=True):
                self._visible_seen.add(path)

    def _basic_scan_clicked(self) -> None:
        if self._basic_active:
            self.cancel_basic_scan()
        else:
            self.start_basic_scan("view")

    def _choose_scan_depth(self) -> None:
        self._choose_scan_depth_for(self.selected_path_globally)

    def _choose_scan_depth_for(self, path: str) -> None:
        depth, accepted = QInputDialog.getInt(self, "Basic scan", "Subfolder levels (0 = current folder):", 1, 0, 32768)
        if accepted:
            self.context_menu_action_deep_calc_status(path, depth)

    def start_basic_scan(self, scope: str = "view", depth: int = 0) -> None:
        self.cancel_basic_scan()
        if scope == "view":
            paths = [self.view_path, *self._viewport_paths()]
        else:
            paths = [self.selected_path_globally]
        nodes = [self.model.nodes[path] for path in paths if path in self.model.nodes]
        self._basic_seen.clear()
        self._basic_roots = set(paths)
        self._basic_completed = self._basic_failed = 0
        self._basic_result = ""
        self._basic_active = bool(nodes)
        self._deep = [(iter(nodes), max(0, depth) if scope == "recursive" else 0)]
        self._update_activity()

    def cancel_basic_scan(self) -> None:
        active = self._basic_active
        self._basic_active = False
        self._deep.clear()
        paths = tuple(self._deep_depth)
        self._deep_depth.clear()
        for path in paths:
            self.model.cache.cancel(self.model.owner, "scan", path)
        if active:
            self._basic_result = f"Basic scan cancelled · {self._basic_completed:,} scanned"
        if hasattr(self, "basic_scan_button"):
            self._update_activity()

    def _directory_loaded(self, path: str) -> None:
        self._finish_basic_folder(path)
        self._schedule_visible_checks()

    def _finish_basic_folder(self, path: str, *, failed: bool = False) -> None:
        if path not in self._deep_depth:
            return
        depth = self._deep_depth.pop(path)
        self._basic_completed += int(not failed)
        self._basic_failed += int(failed)
        node = self.model.nodes.get(path)
        if depth > 0 and node and not failed:
            self._deep.append((iter(node.children), depth - 1))

    def _dispatch_deep(self) -> None:
        limit = self.model.service.max_operations
        if self.closed or not self._basic_active or len(self.model.service.pending) >= 16 or len(self._deep_depth) >= limit:
            return
        for _ in range(min(2, limit - len(self._deep_depth))):
            while self._deep:
                source, depth = self._deep[-1]
                node = next(source, None)
                if node is None:
                    self._deep.pop()
                    continue
                if node.path in self._basic_seen or node.path not in self.model.nodes:
                    continue
                self._basic_seen.add(node.path)
                self._deep_depth[node.path] = depth
                if not self.model.request_scan(node.path, force=True, metadata_only=True):
                    self._finish_basic_folder(node.path, failed=True)
                break
        if not self._deep and not self._deep_depth:
            self._basic_active = False
            self._basic_result = f"Basic scan complete · {self._basic_completed:,} scanned · {self._basic_failed:,} failed"
        self._update_activity()

    def context_menu_action_deep_calc_status(self, path: str, max_depth: int = 0,
                                            invalidate_cache: bool = True) -> None:
        node = self.model.nodes.get(path)
        if node:
            self.cancel_basic_scan()
            self._basic_active = True
            self._basic_seen.clear()
            self._basic_roots = {path}
            self._basic_completed = self._basic_failed = 0
            self._basic_result = ""
            self._deep.append((iter((node,)), max_depth))

    def show_context_menu(self, position: QPoint) -> None:
        index = self.tree.indexAt(position)
        if not index.isValid():
            return
        path = self.model.filePath(index)
        menu = QMenu(self)
        menu.addAction("Open folder", lambda: self.open_to_path(path))
        menu.addAction("Open in File Manager", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
        clipboard = QApplication.clipboard()
        if clipboard:
            menu.addAction("Copy Pathname", lambda: clipboard.setText(path))
        # One folder the user asked for: no timeout, with elapsed time and Cancel.
        menu.addAction("Retry / Refresh", lambda: self.model.request_scan(path, priority=True, force=True,
                                                                         no_timeout=True))
        submenu = menu.addMenu("Basic scan")
        if submenu:
            for depth in (0, 1, 2, 3, 32768):
                submenu.addAction("All subfolders" if depth == 32768 else f"Depth {depth}", lambda checked=False, d=depth: self.context_menu_action_deep_calc_status(path, d))
            submenu.addAction("Custom depth…", lambda: self._choose_scan_depth_for(path))
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
        """Return to the displayed path without resetting the tree or its expansion."""
        if self.closed:
            return
        self._release_load()
        self._cancelled_load_path = None
        self.get_selection_model().clear()
        self.selected_path_globally = self.view_path
        self.model.request_scan(self.view_path, priority=True)
        self.selectionPathChanged.emit(self.view_path)
        self._update_activity()
        self.loadStateChanged.emit()

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
        """Cancel this tab's load subscriptions and a manual listing retry, keeping other scans and tabs alive."""
        if not self.can_cancel_loading:
            return
        retrying = self.retrying_scan
        if retrying is not None:
            self.model.cache.cancel(self.model.owner, "list", retrying.path)
            if not (self.loading or self.load_waiting or self._bg_paths):
                self._update_activity()
                return
        visible_load = self.loading or self.load_waiting
        self._cancelled_load_path = self.selected_path_globally
        self._cancel_background()
        self.model.cache.cancel(self.model.owner, "load")
        if self._load_path is not None:
            self.model.set_load_state(self._load_path, "")
        self._load_path = None
        self.loading = self.load_queued = self.load_paused = False
        self._loading_data.clear()
        if visible_load:
            self.load_error = "Cancelled — Retry"
        self._update_activity()
        self.loadStateChanged.emit()

    def on_stop_button_clicked(self) -> None:
        self.cancel_basic_scan()
        self.cancel_loading()
        self.model.stop_all_scans()
        self.loading = False
        self._loading_data.clear()
        self.loadStateChanged.emit()

    def close_cleanup(self) -> None:
        if self.closed:
            return
        if self.is_foreground:
            self.model.cache.set_foreground(set())
        self._cancel_background()
        self.closed = True
        self.visible_timer.stop()
        self.cancel_basic_scan()
        self.animation.stop()
        self.deep_timer.stop()
        self.model.close_cleanup()
        self.model.cache.resultReady.disconnect(self._io_event)
        self.model.cache.datasetChanged.disconnect(self._shared_dataset_changed)
        self.model.cache.release(self.model.owner)
        self.folder_opened_data = None
        self.displayed_dataset = None
        self._loading_data.clear()
