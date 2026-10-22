"""Folder browser backed by isolated I/O and memory snapshots."""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
import logging
import math
import os
import time
from typing import Any, Callable, Iterator

import numpy as np
import numpy.typing as npt
from PyQt6.QtCore import QEvent, QObject, QItemSelection, QItemSelectionModel, QModelIndex, QPoint, QRect, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QDesktopServices, QFontMetrics, QIcon, QPainter, QPalette, QPen, QResizeEvent
from PyQt6.QtWidgets import (QApplication, QMessageBox, QHBoxLayout, QLineEdit, QMenu, QPushButton, QStyledItemDelegate, QStyleOptionViewItem, QToolTip, QTreeView, QInputDialog,
                             QStyle, QToolButton, QVBoxLayout, QWidget, QSizePolicy)
from helab.models.SnapshotFileSystemModel import FolderNode, SnapshotFileSystemModel
from helab.models.StatusReport import StatusReport
from helab.resources.icons import CHECK_COLOR, LOAD_COLOR, StatusIcons
from helab.utils.io_service import IORequest
from helab.utils import large_folder
from helab.utils.colours import AMBER as AMBER  # Shared; the views import it from here too.
from helab.utils.folder_cache import (NEEDS_ROOT_TOOLTIP, PENDING_ROOT_TOOLTIP, PENDING_SUMMARY, PLACE_ROOT_ACTION,
                                      PLACE_ROOT_TOOLTIP, REVIEW_ROOT_TOOLTIP, Dataset, pending_root_text,
                                      marker_path, store_options)
from helab.utils.number_format import byte_size
from helab.utils.constants import DEFAULT_LOAD_MODE
from helab.utils.load_clock import LoadClock
from helab.utils.time_format import byte_rate, clock as stopwatch, duration, relative_age
from helab.utils.cache_freshness import CacheFreshness, data_as_of, freshness_tooltip, metadata_date
from helab.utils.scan_history import history_tooltip
from helab.views.ElidedLabel import ElidedLabel
from helab.views.explorer_live import LiveController, LiveSession
from helab.views.explorer_text import large_text, plural

# Where a load's data came from, as the cache summary and Folder details name it.
LOAD_ORIGINS = {"disk": "disk cache", "files": "TXY files", "merged": "disk cache + new TXY files",
                "updated": "memory + new TXY files", "memory": "memory"}
# A folder without cached data that wasn't loaded automatically: the disk cache is 80% full.
AUTO_LOAD_PAUSED = "Auto-load paused — disk cache 80% full"
AUTO_LOAD_PAUSED_TOOLTIP = ("Load this folder now. Automatic loading of folders without cached data is paused "
                            "while the disk cache is 80% full; free space in Settings → Cache.")
# A folder whose data would take too much RAM (roadmap S8): automatic loads never start it.
LARGE_TOOLTIP = ("Automatic loads skip folders larger than the RAM budget or 10% of RAM (their TXY files' size). "
                 "Load anyway… asks first.")
REFUSED_TOOLTIP = "Folders larger than 30% of RAM are never loaded."
# The user's choice for a folder (S10): selecting it loads nothing.
AUTO_LOAD_OFF = "Auto-load off for this folder"
AUTO_LOAD_OFF_TOOLTIP = ("Load this folder now. You chose not to load it automatically "
                         "(right-click › Don't auto-load this folder).")
MISMATCH_RETRY_TOOLTIP = ("Check this folder again. If the wrong drive was mounted, mount the right one first: "
                          "its cached shots are then found and it loads as usual.")
MISMATCH_REVIEW_TOOLTIP = ("Cached data doesn't match this folder: shots it had are missing now. Show it in the "
                           "list of mismatched folders, where you can load it as it is now.")
LIVE_RETRY_TOOLTIP = "Check the folder again and go on watching it"

# Spinner colours: a listing or status check is blue, a load green; lighter on a selected row.
# The status bar's spinner, for all I/O, is grey.
CHECK_SPINNER = (CHECK_COLOR, "white")
LOAD_SPINNER = (LOAD_COLOR, "#b4f0c2")
IO_SPINNER = ("#8a8a8a", "white")


def paint_spinner(painter: QPainter, rect: QRect, angle: int, selected: bool = False,
                  colors: tuple[str, str] = CHECK_SPINNER, width: float = 2.5) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(colors[selected]), width))
    painter.drawArc(rect, angle * 16, 260 * 16)
    painter.restore()


def paint_check(painter: QPainter, cell: QRect, angle: int, selected: bool = False, queued: bool = False) -> None:
    """A first check, in the status icon's place: a spinner, or a still dotted ring while queued."""
    if not queued:
        paint_spinner(painter, QRect(cell.left() + 7, cell.top() + (cell.height() - 10) // 2, 10, 10), angle, selected)
    elif selected:
        # The blue ring would vanish on the highlight.
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("white"), 1.5, Qt.PenStyle.DotLine))
        painter.drawEllipse(QRect(cell.left() + 7, cell.top() + (cell.height() - 10) // 2, 10, 10))
        painter.restore()
    else:
        StatusIcons.ICON_CHECK_QUEUED.paint(painter, QRect(cell.left() + 4, cell.top() + (cell.height() - 16) // 2, 16, 16))


def paint_check_badge(painter: QPainter, icon: QRect, angle: int, queued: bool = False) -> None:
    """A recheck, at the status icon's bottom right like its outdated clock: a small spinner on a
    white disc, or a still dotted ring while queued."""
    size = max(6, icon.width() // 2)
    disc = QRect(icon.right() + 1 - size, icon.bottom() + 1 - size, size, size)
    if queued:
        StatusIcons.ICON_CHECK_QUEUED_BADGE.paint(painter, disc.adjusted(-1, -1, 0, 0))
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("white"))
    painter.drawEllipse(disc.adjusted(-1, -1, 0, 0))
    painter.restore()
    paint_spinner(painter, disc.adjusted(1, 1, -1, -1), angle, width=1.5)


class ScanDelegate(QStyledItemDelegate):
    angle = 0

    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem | None, index: QModelIndex) -> None:
        if painter is None or option is None:
            return
        extras = index.data(SnapshotFileSystemModel.STATUS_EXTRA_ICONS_ROLE)
        # QIcons, and "load" for the load's spinner in the RAM badge's place.
        icons = [icon for icon in extras if isinstance(icon, (QIcon, str))] if isinstance(extras, list) else []
        item = QStyleOptionViewItem(option)
        self.initStyleOption(item, index)
        text = item.text
        if icons:
            item.text = ""  # Drawn after the badges below so they never overlap.
        style = item.widget.style() if item.widget else QApplication.style()
        if style:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, item, painter, item.widget)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        activity = index.data(SnapshotFileSystemModel.ACTIVITY_ROLE)
        if activity in ("check", "check_queued"):
            queued = activity == "check_queued"
            icon_rect = (style.subElementRect(QStyle.SubElement.SE_ItemViewItemDecoration, item, item.widget)
                         if style and index.data(Qt.ItemDataRole.DecorationRole) is not None else QRect())
            if icon_rect.isValid():
                # A recheck: the last status stays, with a small spinner or ring on it.
                paint_check_badge(painter, icon_rect, self.angle, queued)
            else:
                # A first check takes the status icon's place.
                paint_check(painter, option.rect, self.angle, selected, queued)
        for i, icon in enumerate(icons):
            rect = QRect(option.rect.left() + 24 + i * 18, option.rect.top() + (option.rect.height() - 16) // 2, 16, 16)
            if isinstance(icon, QIcon):
                icon.paint(painter, rect)
            else:
                paint_spinner(painter, rect.adjusted(3, 3, -3, -3), self.angle, selected, LOAD_SPINNER)
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
    # Review… for a folder whose cached data doesn't match it: the main window shows its row in the list.
    reviewMismatchRequested = pyqtSignal(str)
    reviewRootRequested = pyqtSignal(str)  # A pending location: Same folder or a copy?
    # Live turned on or off, or stopped by an error (the toolbar's Live action follows).
    liveChanged = pyqtSignal()
    DWELL_MS = 3000
    # Finish and Cancel modes: while loads are busy (running, queued or stopping, or one started
    # moments ago), an automatic load waits until the selection has stayed this long, plus
    # SETTLE_STEP for each queued I/O task, at most SETTLE_MAX seconds; when idle it starts at once.
    SETTLE_SECONDS = 0.3
    SETTLE_STEP = 0.1
    SETTLE_MAX = 1.0
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
        # Current listing/checking/verification phase, including after file reads.
        self.load_listing = ""
        self.load_filename = ""
        self.load_checked_files = 0
        self.load_files = 0
        self.load_total_files: int | None = None
        self.load_failed_files = 0
        self.load_unsettled_files = 0
        self.load_source = ""
        self.load_counts: dict[str, int] = {}
        self._load_cache_pending = False
        self.load_cache_reason = ""
        self.load_cache_warning = ""
        self.load_error = ""
        self.load_bytes = 0
        # Folder whose displayed data came from memory or the disk cache and has
        # not been checked against the folder since it was selected.
        self._unchecked_path: str | None = None
        # Folders whose next load compares every file with the cache (Retry / Refresh), not
        # just the folder's mtime: a file rewritten in place doesn't change the folder's mtime.
        self._full_check_paths: set[str] = set()
        # Folders whose selection wasn't listed (``_check_replaces_listing``): their load's result
        # updates the row.
        self._listing_replaced: set[str] = set()
        # The disk cache is read at most once per selection of a folder, or once more after its
        # volume is verified if the first read waited for that (``_volumes_verified``).
        self._cache_read_path: str | None = None
        self._cache_read_waits: str | None = None
        self._load_path: str | None = None
        self._cancelled_load_path: str | None = None
        # Large folders (S8): the folder the user just said yes to, only while the call that asked
        # submits its request. Whether a request was asked for (``deliberate``) and allowed
        # (``allow_large``) travels with the request, so neither outlives it.
        self._allowing: str | None = None
        # Bumped by Cancel: a large-folder question scheduled before it is dropped.
        self._cancel_count = 0
        # The latest helper stop for being large, per folder: (estimate, when, what was in RAM).
        self._large_stops: dict[str, tuple[int, float, tuple[str, int, int] | None]] = {}
        # Replaceable in tests; None asks with LargeFolderDialog. (Not a bound method: that
        # would keep this widget's wrapper alive after Qt deletes it.)
        self.confirm_large: Callable[[str, int], bool] | None = None
        self.ask_remove_cached: Callable[[str, int | None], bool] | None = None
        self.report_flag_failure: Callable[[str, str], None] | None = None
        self._auto_load_off_paths: set[str] = set()
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
        # Seconds the current wait lasts when it is the short settle wait (Finish, Cancel); 0 for Queue's.
        self._settle_wait = 0.0
        # When this tab last started an automatic load or cached read (monotonic).
        self._auto_load_at = -math.inf
        self.model = SnapshotFileSystemModel(self)
        self.bg_owner = f"{self.model.owner}:bg"
        # Live: checks run in the foreground lane (this tab's), saves in the background.
        self.live_owner = f"{self.model.owner}:live"
        self.live_save_owner = f"{self.model.owner}:live-save"
        # Live's sessions, its timer (a child of this tab) and its checks and saves.
        self.live_control = LiveController(self)
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
        # Tab activity (basic scans, background loads) is shown in the main window's status bar.
        self.activity_text = ""
        self.activity_tooltip = ""
        self.activity_busy = False
        # Three fixed-height lines: the tree's rows never move when the summary changes.
        self.summary_widget = QWidget(self)
        self.folder_counts_row = QWidget(self.summary_widget)
        self.selected_folder_label = ElidedLabel("", self.folder_counts_row, Qt.TextElideMode.ElideMiddle)
        self.folder_summary_label = ElidedLabel("Scanning folder content for TXY files…", self.folder_counts_row)
        # _fit_selected_label sets its width; the counts label takes the rest of the line.
        self.selected_folder_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.folder_cache_label = ElidedLabel("Cache not checked", self.summary_widget)
        self.folder_freshness_label = ElidedLabel("Live updates off", self.summary_widget)
        self.cancel_load_button = QToolButton(self.folder_counts_row)
        self.cancel_load_button.setText("Cancel")
        self.cancel_load_button.setToolTip("Cancel loading in this tab (Esc)")
        self.cancel_load_button.clicked.connect(self.cancel_loading)
        self.retry_button = QToolButton(self.folder_counts_row)
        self.retry_button.setText("Retry")
        self.retry_button.clicked.connect(self._retry)
        # Shown with Retry while the selected folder's cached data doesn't match it (shots missing).
        self.review_button = QToolButton(self.folder_counts_row)
        self.review_button.setText("Review…")
        self.review_button.setToolTip(MISMATCH_REVIEW_TOOLTIP)
        self.review_button.clicked.connect(lambda: self.reviewMismatchRequested.emit(self.selected_path_globally))
        # The selected folder is below a location whose .helab-root is also elsewhere (pending).
        self.root_review_button = QToolButton(self.folder_counts_row)
        self.root_review_button.setText("Review…")
        self.root_review_button.setToolTip(REVIEW_ROOT_TOOLTIP)
        self.root_review_button.clicked.connect(self._review_root)
        # Offered with the large-folder warning (S10): stop it coming up at all.
        self.no_auto_load_button = QToolButton(self.folder_counts_row)
        self.no_auto_load_button.setText("No auto-load")
        self.no_auto_load_button.setToolTip("Don't auto-load this folder: selecting it won't load it again "
                                            "(right-click to change).")
        self.no_auto_load_button.clicked.connect(
            lambda: self.set_folder_flag(self.selected_path_globally, "no_auto_load", True))
        self.deselect_button = QToolButton(self.folder_counts_row)
        self.deselect_button.setText("Deselect")
        self.deselect_button.setToolTip("Clear subfolder selection and view the displayed path")
        self.deselect_button.clicked.connect(self.clear_selection)
        self.summary_buttons = (self.cancel_load_button, self.retry_button, self.review_button,
                                self.root_review_button, self.no_auto_load_button, self.deselect_button)
        for hidden in (self.selected_folder_label, *self.summary_buttons):
            hidden.hide()
        summary_font = self.folder_summary_label.font()
        summary_font.setBold(True)
        self.folder_summary_label.setFont(summary_font)
        small_font = self.folder_freshness_label.font()
        small_font.setPointSizeF(max(8.0, small_font.pointSizeF() - 1.0))
        self.folder_freshness_label.setFont(small_font)
        self.folder_cache_label.setFont(small_font)
        line_height = max(label.fontMetrics().height() for label in (
            self.selected_folder_label, self.folder_summary_label,
            self.folder_cache_label, self.folder_freshness_label))
        for line in (self.folder_counts_row, self.selected_folder_label, self.folder_summary_label,
                     self.folder_cache_label, self.folder_freshness_label):
            line.setFixedHeight(line_height)
        for button in self.summary_buttons:
            button.setFont(small_font)
            button.setFixedHeight(line_height)
            button.setStyleSheet("""
                QToolButton { padding: 0px 3px; border: 1px solid palette(mid); border-radius: 2px; }
                QToolButton:hover { background: palette(midlight); }
                QToolButton:pressed { background: palette(mid); }
                QToolButton:focus { border-color: palette(highlight); }
            """)
        self._summary_button_width = max(button.sizeHint().width() for button in self.summary_buttons)
        for button in self.summary_buttons:
            button.setFixedWidth(self._summary_button_width)
        counts_layout = QHBoxLayout(self.folder_counts_row)
        counts_layout.setContentsMargins(0, 0, 0, 0)
        counts_layout.setSpacing(4)
        counts_layout.addWidget(self.selected_folder_label)
        counts_layout.addWidget(self.folder_summary_label, 1)
        for button in self.summary_buttons:
            counts_layout.addWidget(button)
        summary_layout = QVBoxLayout(self.summary_widget)
        summary_layout.setContentsMargins(8, 0, 0, 0)
        summary_layout.setSpacing(0)
        summary_layout.addWidget(self.folder_counts_row)
        summary_layout.addWidget(self.folder_cache_label)
        summary_layout.addWidget(self.folder_freshness_label)
        self.summary_widget.setFixedHeight(3 * line_height)
        self.summary_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.path_edit)
        layout.addWidget(self.summary_widget)
        layout.addWidget(self.tree, 1)
        self.get_selection_model().selectionChanged.connect(self.on_selection_changed)
        self.tree.expanded.connect(self._expanded)
        self.model.dataChanged.connect(self._refresh_open_tooltip)
        self.tree.doubleClicked.connect(self.on_double_click)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        self.model.statusReady.connect(self._status_ready)
        self.model.directoryLoaded.connect(self._directory_loaded)
        self.model.cache.resultReady.connect(self._io_event)
        self.model.cache.datasetChanged.connect(self._shared_dataset_changed)
        self.model.cache.autoLoadPauseChanged.connect(self._auto_load_pause_changed)
        self.model.cache.folderPrefsChanged.connect(self._folder_prefs_changed)
        self.model.cache.folderPrefsFailed.connect(self._folder_prefs_failed)
        self.model.cache.folderConstantsFailed.connect(self._folder_constants_failed)
        self.model.cache.mountWarningChanged.connect(self._mount_warning_changed)
        self.model.cache.volumesVerified.connect(self._volumes_verified)
        self.model.cache.rootDecided.connect(self._root_decided)
        self.model.cache.rootDuplicatesChanged.connect(self._update_activity)
        self.model.cache.saveEnded.connect(self._live_save_ended)
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
        self.icon_timer = QTimer(self)
        self.icon_timer.setSingleShot(True)
        self.icon_timer.timeout.connect(self._load_visible_icons)
        self.model.refreshStateChanged.connect(self._refresh_state_changed)
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
        """In queue mode this tab's queued loads run one by one in the foreground lane. Live
        checks run there too; Live's saves are background work."""
        return {self.model.owner, self.live_owner} | ({self.bg_owner} if self.load_mode == "queue" else set())

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
            self.model.cache.submit(self.model.owner, self.model.generation, self.target_path,
                                      "resolve", {"candidates": candidates}, priority=True)

    def open_to_path(self, path: str) -> None:
        if self.closed or not path.strip():
            return
        self.stop_live()
        self._deep.clear()
        self._deep_depth.clear()
        self._listing_replaced.clear()
        self._basic_active = False
        self._basic_result = ""
        self._visible_seen.clear()
        self._release_load()
        self._cancelled_load_path = self._cache_read_path = None
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

    def refresh_folder(self, path: str) -> None:
        """Right-click Retry / Refresh: list the folder again (no timeout), and check its cached
        or shown data file by file. The selected folder's shown data is checked now."""
        self.model.request_scan(path, priority=True, force=True, no_timeout=True)
        if not (self.model.cache.disk_cached(path) or self.folder_opened_path == path):
            return
        self._full_check_paths.add(path)
        if path == self.selected_path_globally and self.folder_opened_path == path and self.folder_opened_data is not None:
            unchecked, self._unchecked_path = self._unchecked_path, path  # "Checking for changes…"
            if not self.load_to_ram_cache(path, dwell=False) and not (self.loading and self._load_path == path):
                self._unchecked_path = unchecked  # Nothing will check it (e.g. auto-load is off).

    def _retry(self) -> None:
        if self.live is not None:
            self.resume_live()
            return
        # A load retry keeps its per-file timeouts; a hung read is genuinely stuck.
        if (self.load_error or self.auto_load_paused_path == self.selected_path_globally
                or self.large_state(self.selected_path_globally) or self.auto_load_off(self.selected_path_globally)):
            # Deliberate: it loads even while automatic loads are paused.
            self.load_to_ram_cache(self.selected_path_globally, dwell=False, explicit=True)
        else:
            self.model.request_scan(self.listing_retry_path, priority=True, force=True, no_timeout=True)

    @property
    def listing_retry_path(self) -> str:
        node = self.model.nodes.get(self.selected_path_globally)
        if not (node and node.error) and self.model.root and self.model.root.error:
            return self.view_path
        return self.selected_path_globally

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
            if self.live is not None and path != self.live.path:
                self.stop_live()  # Another folder selected (the tree is locked: e.g. Show in tab).
            if path != self.selected_path_globally:
                self._release_load()
                self._cancelled_load_path = self._cache_read_path = None
                self.auto_load_paused_path = None
                self.selected_path_globally = path
                dataset = self.displayed_dataset
                node = self.model.nodes.get(path)
                if (self.folder_opened_path == path and dataset is not None and dataset.path == path
                        and not self.model.cache.counts_as_checked(dataset, node.signature if node else "")):
                    # Back at the folder still shown: its data is checked again, as from memory.
                    self._unchecked_path = path
            if self._check_replaces_listing(path):
                self._listing_replaced.add(path)
            else:
                self.model.request_scan(path, priority=True)
            self.selectionPathChanged.emit(path)

    def _refresh_open_tooltip(self, top_left: QModelIndex, bottom_right: QModelIndex) -> None:
        """Qt builds a tooltip only when it is shown; rebuild an open one when its row changes."""
        if not QToolTip.isVisible():
            return
        viewport = self.tree.viewport()
        if viewport is None:
            return
        position = viewport.mapFromGlobal(QCursor.pos())
        index = self.tree.indexAt(position)
        if (index.isValid() and index.parent() == top_left.parent()
                and top_left.row() <= index.row() <= bottom_right.row()):
            text = index.data(Qt.ItemDataRole.ToolTipRole)
            if isinstance(text, str) and text != QToolTip.text():
                QToolTip.showText(QCursor.pos(), text, viewport, self.tree.visualRect(index))

    def _check_replaces_listing(self, path: str) -> bool:
        """Selecting a folder with saved counts and a disk cache does not list it:
        the cached data is shown, and loading checks the folder (one stat when
        unmodified). Nor does selecting a folder without subfolders whose checked
        data is in RAM: its load's quick check covers it (``memory_check``). If the
        check finds changes, the load's own listing updates the row. Expanding a
        folder still lists it."""
        node = self.model.nodes.get(path)
        cache = self.model.cache
        if not (self.auto_load_ram and node is not None and node.report is not None):
            return False
        if cache.disk_cached(path):
            return True
        dataset = cache.latest_dataset(path)
        return (node.has_dirs is False and dataset is not None and cache.verified(dataset)
                and bool(dataset.metadata.get("listed_at")) and path not in cache.mismatched
                and not cache.folder_prefs(path)["no_auto_load"])

    def _status_ready(self, path: str) -> None:
        if path == self.selected_path_globally and not (
                self._basic_active and path in self._basic_seen | self._basic_roots):
            node = self.model.nodes.get(path)
            dataset = self.displayed_dataset
            if (node and self.folder_opened_path == path and not self.watching(path) and dataset is not None and dataset.path == path
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
        action = "Retry queued" if node.state == "queued" else "Retrying…"
        text = f"{action} {duration(time.monotonic() - node.retry_since)}"
        return text + (f" · {node.listed:,} entries" if node.listed else "")

    @property
    def deselect_tooltip(self) -> str:
        path = self.selected_path_globally
        prefix = "View the displayed path. "
        if self.load_waiting and self._dwell_path == path:
            return prefix + ("The selected folder will not be loaded." if self._settle_wait else
                             "The selected folder will not be queued.")
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
        self._settle_wait = 0.0

    def _dwell_elapsed(self) -> None:
        path, self._dwell_path = self._dwell_path, None
        self._settle_wait = 0.0
        if not self.closed and path is not None and path == self.selected_path_globally:
            self.load_to_ram_cache(path, dwell=False)
        self.loadStateChanged.emit()

    def _release_load(self, keep: str | None = None) -> None:
        """Stop showing the current load; depending on the mode it continues in the background.

        A check beside the folder's cached read (``cache_base``) needs that read's shots. While it
        is only checking (no files to read found yet) it is cancelled with the read: the cache
        holds the data, and the next visit checks again. Once it reads new files it is a real load,
        and moves to the background with its read."""
        self._stop_dwell()
        path = self._load_path
        cache = self.model.cache
        beside_read = path is not None and any(
            request.operation == "load" and request.path == path and request.payload.get("cache_base")
            for request in cache.requests(self.model.owner))
        clock = cache.load_clock(path) if path is not None else None
        only_checking = beside_read and not (clock is not None and clock.total_bytes)
        if path is not None and self.loading and not only_checking and (
                self.load_mode == "queue" or (self.load_mode == "finish" and not self.load_queued)):
            self._bg_paths[path] = None
            if cache.transfer(self.model.owner, self.model.generation, path, self.bg_owner, 0):
                if beside_read:
                    cache.transfer(self.model.owner, self.model.generation, path, self.bg_owner, 0, "cached")
                self._trim_background()
            else:
                del self._bg_paths[path]
        cache.cancel(self.model.owner, "load")
        for request in tuple(self.model.cache.requests(self.model.owner)):
            # The cached read of the folder about to be checked runs beside that check.
            if request.operation == "cached" and request.path != keep:
                self.model.cache.cancel(self.model.owner, "cached", request.path)
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
        self.load_filename = ""
        self.load_checked_files = self.load_unsettled_files = 0
        self.load_files = self.load_failed_files = 0
        self.load_total_files = None
        if not self._checking(path):
            # A check of shown data keeps that data's source until it completes.
            self.load_source = ""
            self.load_cache_reason = ""
        self.load_cache_warning = ""
        self._load_path = path
        self._loading_data.clear()
        self.model.set_load_state(path, "queued")

    def _checking(self, path: str) -> bool:
        """Whether this folder's shown data came from memory or the disk cache and awaits its check."""
        return self.folder_opened_path == path and self._unchecked_path == path

    def shows_unchecked(self, path: str) -> bool:
        """Public form of ``_checking``: the shown data is not yet checked against the folder."""
        return self._checking(path)

    def _load_payload(self, path: str, deliberate: bool = False) -> dict[str, Any]:
        node = self.model.nodes.get(path)
        full_check = path in self._full_check_paths
        self._full_check_paths.discard(path)
        # The user's answer in the mismatched-folders window (``MissingShotsWindow``).
        allow_missing = self.model.cache.take_allow_missing(path)
        return {"cache": store_options(), "signature": node.signature if node else "",
                "no_cache": self.model.cache.folder_prefs(path)["no_cache"], "full_check": full_check,
                # Its cached read runs now: the check counts those shots as held (see io_ops.loading.load).
                "cache_base": self.model.cache.has_request(self.model.owner, "cached", path),
                "check_level": self.model.cache.check_level, "allow_missing": allow_missing,
                **self._large_payload(path, deliberate)}

    def _large_payload(self, path: str, deliberate: bool) -> dict[str, Any]:
        """The large-folder thresholds, whether the user asked for this request (asked about if
        its helper finds it large) and whether they just said yes to it."""
        return {"limits": self.model.cache.large_limits(), "deliberate": deliberate,
                "allow_large": self._allowing == path}

    def _has_data(self, path: str) -> bool:
        node = self.model.nodes.get(path)
        if node and node.cached_report:
            return False
        report = self.model.fetch_status(path)
        return report.status in StatusReport.STATUS_CONTAINS_DATA_HERE and bool(report.d_txy_shots)

    def load_to_ram_cache(self, path: str, *, dwell: bool = True, explicit: bool = False) -> bool:
        """Show this folder's data, loading it as the tab's visible load."""
        try:
            return self._load_to_ram_cache(path, dwell, explicit)
        finally:
            self._allowing = None  # A yes covers only what this call submitted.

    def _load_to_ram_cache(self, path: str, dwell: bool, explicit: bool) -> bool:
        if self.watching(path):
            return False  # Live keeps its data current.
        # A scan finishing after Cancel must not restart automatic loading.
        if dwell and path == self._cancelled_load_path:
            return False
        if not dwell:
            self._cancelled_load_path = None
        if not explicit and self.model.cache.folder_prefs(path)["no_auto_load"]:
            # The user's choice: selecting this folder loads nothing, cached or not.
            if path == self.selected_path_globally:
                self._update_activity()
                self.loadStateChanged.emit()
            return False
        if self._large_blocked(path, explicit):
            return False
        cached = self.model.cache.disk_cached(path)
        if dwell and not explicit and self.settling and self._dwell_path == path:
            # Already waiting for this selection to settle: a status update meanwhile keeps the
            # deadline, even if loads went idle since. Only a new selection restarts the wait.
            # Data that reached RAM meanwhile (another tab's load) shows at once, without a read.
            if self.folder_opened_path != path or self.folder_opened_data is None:
                self._show_cached(path, explicit, read=False)
            if (self.folder_opened_path == path and self.folder_opened_data is not None
                    and self._unchecked_path != path):
                # Checked moments ago: nothing is left to wait for.
                self._stop_dwell()
                self._update_activity()
                self.loadStateChanged.emit()
                return False
            return True
        # Selections changing quickly, or loads busy: wait for the selection to settle (Finish, Cancel).
        settle = (self.settle_seconds(path) if dwell and not explicit and self.load_mode != "queue"
                  and path not in self._bg_paths and not (self.loading and self._load_path == path) else 0.0)
        if self.folder_opened_path != path or self.folder_opened_data is None:
            # Show data from memory or the local disk cache at once; it never waits for
            # source-folder I/O. The check below runs beside a cached read, not after it.
            # While the selection settles, only data in RAM shows.
            self._show_cached(path, explicit, read=not settle)
        if not explicit and not cached and not self._has_data(path):
            return False
        if (self.folder_opened_path == path and self.folder_opened_data is not None
                and self._unchecked_path != path):
            self.dataLoaded.emit(path)
            return False
        if self.loading and self._load_path == path:
            return True
        node = self.model.nodes.get(path)
        in_memory = node is not None and self.model.cache.dataset(path, node.signature) is not None
        if (not explicit and not cached and not in_memory and path not in self._bg_paths
                and self.model.cache.auto_load_paused):
            # Over 80% of the disk cache budget, new folders load only when asked.
            if self.auto_load_paused_path != path:
                self.auto_load_paused_path = path
                self._update_activity()
                self.loadStateChanged.emit()
            return False
        self.auto_load_paused_path = None
        if (dwell and self.load_mode == "queue" and path not in self._bg_paths
                and not in_memory and self.model.service.load_busy()):
            # Browsing past folders must not fill the queue.
            if self._dwell_path != path or not self._dwell.isActive():
                self._dwell_path = path
                self._settle_wait = 0.0
                self._dwell.start(self.DWELL_MS)
                self._update_activity()
                self.loadStateChanged.emit()
            return True
        if settle:
            # Each new selection restarts the wait (selecting stops it); folders passed on the way start nothing.
            self._dwell_path, self._settle_wait = path, settle
            self._dwell.start(round(settle * 1000))
            self._update_activity()
            self.loadStateChanged.emit()
            return True
        self._auto_load_at = time.monotonic()
        self._release_load(keep=path)
        self._begin_load(path)
        if path in self._bg_paths:
            del self._bg_paths[path]
            if self.model.cache.transfer(self.bg_owner, 0, path, self.model.owner, self.model.generation):
                # Its cached read, if it moved with it, comes back too.
                self.model.cache.transfer(self.bg_owner, 0, path, self.model.owner, self.model.generation, "cached")
                self.model.cache.promote(path)
                self.loadStateChanged.emit()
                return True
        accepted = self.model.cache.submit(self.model.owner, self.model.generation, path, "load",
                                           self._load_payload(path, explicit), priority=True)
        if accepted and self.load_mode != "cancel":
            self.model.cache.promote(path)
        if not accepted:
            self.loading = False
            self.load_error = "Load queue full — Retry"
            self.model.set_load_state(path, "")
        self.loadStateChanged.emit()
        return accepted

    def large_state(self, path: str | None) -> tuple[int, bool] | None:
        """(estimate, refused) if ``path``'s load stopped, or wasn't started, for being large."""
        return self.model.large_paths.get(path) if path else None

    def _set_large(self, path: str, state: tuple[int, bool] | None) -> None:
        if state is None:
            if self.model.large_paths.pop(path, None) is None:
                return
        else:
            self.model.large_paths[path] = state
        node = self.model.nodes.get(path)
        if node:
            self.model.changed(node)

    def _large_estimate(self, path: str, held: bool) -> int | None:
        """What loading ``path`` would add to RAM, as far as memory knows. A helper's stop is the
        newest word until the folder or its cached data is measured again, or the data in RAM
        changes; data already held is otherwise left to the helper, which counts only what a
        load would add."""
        stop = self._large_stops.get(path)
        if stop is not None and not self._measured_since(path, stop[1]) and stop[2] == self._held_key(path):
            return stop[0]
        return None if held else self.model.cache.large_estimate(path)

    def _held_key(self, path: str) -> tuple[str, int, int] | None:
        """Which of the folder's data is in RAM: a stop's estimate is what a load would add to
        it, so it no longer counts once that changes (e.g. a cached read brought the data)."""
        cache = self.model.cache
        dataset = cache.current_dataset(path) or cache.latest_dataset(path)
        return None if dataset is None else (dataset.signature, dataset.epoch, len(dataset.data))

    def _measured_since(self, path: str, since: float) -> bool:
        cache = self.model.cache
        snapshot = cache.snapshots.get(path)
        dates = [status.get("scanned_at") for status in (cache.scan_summaries.get(path),
                                                         snapshot.status if snapshot else None) if status]
        if cache.disk_cached(path):
            dates.append(cache.cache_status(path).info.get("saved_at"))
        return any(isinstance(date, (int, float)) and date > since for date in dates)

    def _large_blocked(self, path: str, explicit: bool) -> bool:
        """Whether a load of ``path`` mustn't start for being large (S8), from what memory knows.

        Automatic loads above the warning threshold don't start and show "Load anyway…";
        deliberate ones ask first. Above 30% of RAM nothing loads. For data already in RAM only
        a helper's stop counts (what a load would add to it).
        """
        cache = self.model.cache
        held = cache.current_dataset(path) is not None or cache.latest_dataset(path) is not None
        estimate = self._large_estimate(path, held)
        verdict = large_folder.verdict(estimate, cache.large_limits(), self._allowing == path)
        if not verdict or estimate is None:
            self._set_large(path, None)
            return False
        if verdict == "large" and explicit and (self.confirm_large or self._confirm_large)(path, estimate):
            self._allowing = path
            self._set_large(path, None)
            return False
        self._set_large(path, (estimate, verdict == "refused"))
        if path == self.selected_path_globally:
            self._update_activity()
            self.loadStateChanged.emit()
        return True

    def _shots_missing(self, request: IORequest, event: dict[str, Any], *, background: bool = False) -> None:
        """The folder no longer has shots cached or loaded from it: nothing was read. Its cached
        data isn't shown (it may be another folder's); ``FolderCache`` lists it for the user's answer
        (``MissingShotsWindow``)."""
        path = request.path
        if not background:
            self.model.cache.cancel(self.model.owner, "cached", path)
            self.loading = self.load_paused = False
            self._loading_data.clear()
            self.model.set_load_state(path, "")
            count = int(event.get("missing_count", 0))
            self.load_error = (f"{count} cached shot{'' if count == 1 else 's'} missing — Retry after checking "
                               "the drive, or Review…")
            self._cancelled_load_path = path  # No automatic load tries again; Retry or the answer does.
            shown = self.displayed_dataset
            if self.folder_opened_path == path or (shown is not None and shown.path == path):
                self.model.cache.release(self.model.owner)
                self.folder_opened_path = self.model.folder_opened_path = None
                self.folder_opened_data = self.displayed_dataset = None
                self._unchecked_path = None
                self.dataLoaded.emit(path)

    def load_as_it_is_now(self, path: str) -> None:
        """Load a mismatched folder as it is now (the user's answer): at once if it is the selected
        folder, else queued like any explicit load. Its old cached data is replaced by the result."""
        self.model.cache.answer_mismatches([path], "load")
        self.queue_load(path)

    def _confirm_large(self, path: str, estimate: int) -> bool:
        from helab.views.LargeFolderDialog import confirm_large
        cache = self.model.cache
        return confirm_large(path, estimate, cache.max_data_bytes, cache.total_ram, self)

    def _stopped_large(self, request: IORequest, event: dict[str, Any], *, background: bool = False) -> None:
        """A helper stopped before reading: the data would take ``estimate`` bytes of RAM."""
        path = request.path
        estimate, refused = int(event.get("estimate", 0)), bool(event.get("refused"))
        self._large_stops[path] = (estimate, time.time(), self._held_key(path))
        self._set_large(path, (estimate, refused))
        if not refused and request.payload.get("deliberate"):
            # Asked for: ask about the size, then load again (unless cancelled meanwhile).
            cancels = self._cancel_count
            QTimer.singleShot(0, lambda: self._load_again(path, background, cancels))

    def _load_again(self, path: str, background: bool, cancels: int) -> None:
        if self.closed or cancels != self._cancel_count:
            return
        if background:
            if path not in self._bg_paths and path != self.selected_path_globally:
                self.queue_load(path)
        elif path == self.selected_path_globally:
            self.load_to_ram_cache(path, dwell=False, explicit=True)

    @property
    def auto_load_paused_path(self) -> str | None:
        """The selected folder whose automatic load waits: the disk cache is 80% full."""
        return self.model.auto_load_paused_path

    @auto_load_paused_path.setter
    def auto_load_paused_path(self, path: str | None) -> None:
        previous, self.model.auto_load_paused_path = self.model.auto_load_paused_path, path
        for changed in {previous, path} - {None}:
            node = self.model.nodes.get(changed) if changed else None
            if node:
                self.model.changed(node)

    def _auto_load_pause_changed(self, paused: bool) -> None:
        """Below 80% again (or Ignore): the selected folder's automatic load starts by itself."""
        path = self.auto_load_paused_path
        if paused or self.closed or path is None:
            return
        self.auto_load_paused_path = None
        if path == self.selected_path_globally and self.auto_load_ram:
            self.load_to_ram_cache(path)
        self._update_activity()
        self.loadStateChanged.emit()

    def settle_seconds(self, path: str) -> float:
        """How long an automatic load of ``path`` waits for the selection to settle: 0 when no load
        is running, queued or stopping and none started in the last SETTLE_SECONDS; otherwise
        SETTLE_SECONDS plus SETTLE_STEP per queued I/O task (not this folder's own), at most SETTLE_MAX."""
        service = self.model.service
        if not (service.load_busy() or service.load_stopping()
                or time.monotonic() - self._auto_load_at < self.SETTLE_SECONDS):
            return 0.0
        queued = sum(1 for request in service.pending if request.path != path)
        return min(self.SETTLE_MAX, self.SETTLE_SECONDS + self.SETTLE_STEP * queued)

    def _show_cached(self, path: str, deliberate: bool = False, read: bool = True) -> bool:
        """Display this folder's dataset from memory, or start reading it from the
        disk cache (unless not ``read``). True while that read is pending: the check
        waits for it, so it can reuse the shots instead of reading files."""
        cache = self.model.cache
        if path in cache.mismatched:
            return False  # Its cached data may be another folder's: nothing shows until a load completes.
        if cache.has_request(self.model.owner, "cached", path):
            return True
        dataset = cache.current_dataset(path) or cache.latest_dataset(path)
        if dataset is not None:
            self.load_source, self.load_cache_reason, self._load_cache_pending = "memory", "", False
            self.load_counts = {"reused_memory": len(dataset.data), "reused_disk": 0, "read": 0}
            # Data checked moments ago needs no check, by the same rule that answers a load from
            # memory (``counts_as_checked``); older data is checked again (one folder stat when
            # nothing changed).
            node = self.model.nodes.get(path)
            matches = cache.counts_as_checked(dataset, node.signature if node else "")
            self._display(path, dataset, {"verified": matches})
            return False
        if (not read or not cache.disk_cached(path) or path == self._cache_read_path
                or cache.folder_prefs(path)["no_cache"]):
            # Not yet (the selection settles first); read (or unreadable) already, or not cached
            # by choice: the load reads the files.
            return False
        if large_folder.verdict(cache.cached_estimate(path), cache.large_limits(), self._allowing == path):
            # Too large to read whole: the load decides by the folder's own size, and reads
            # its files instead of unpacking the cache if that is what fits.
            return False
        self._cache_read_path = path
        self._auto_load_at = time.monotonic()
        return cache.submit(self.model.owner, self.model.generation, path, "cached",
                            {"cache": store_options(), "verified_volumes": cache.verified_volumes(),
                             **self._large_payload(path, deliberate)}, priority=True)

    def _volumes_verified(self) -> None:
        """A cached read that waited for its volume's verification runs now, if the folder is
        still selected and shows nothing yet (its load, from the folder itself, may still run)."""
        path, self._cache_read_waits = self._cache_read_waits, None
        if (self.closed or path is None or path != self.selected_path_globally
                or path != self._cache_read_path
                or (self.folder_opened_path == path and self.folder_opened_data is not None)):
            return
        self._cache_read_path = None
        self._show_cached(path)
        self._update_activity()
        self.loadStateChanged.emit()

    def _display(self, path: str, dataset: Dataset, event: dict[str, Any] | None = None) -> None:
        """Show a dataset; data not from a completed load stays unchecked until one completes."""
        self.model.cache.retain(self.model.owner, dataset)
        self.displayed_dataset = dataset
        self.folder_opened_data = dict(dataset.data)
        self.folder_opened_path = path
        self.model.folder_opened_path = path
        self.load_bytes = int(dataset.metadata.get("bytes", 0))
        self._unchecked_path = path if event is None or event.get("verified") is False else None
        report = self.model.fetch_status(path)
        report.problematic_txy_ns = list(dataset.metadata.get("problematic", []))
        report.loaded_txy_files_count = int(dataset.metadata.get("files", 0))
        report.loaded_txy_rows_count = int(dataset.metadata.get("rows", 0))
        report.data_dict_bytes = self.load_bytes
        report.extra_icons = ["ram_opened"]
        node = self.model.nodes.get(path)
        if node:
            self.model.changed(node)
        self.dataLoaded.emit(path)

    def _cached_event(self, request: IORequest, event: dict[str, Any]) -> None:
        kind, path = event["kind"], request.path
        if kind == "loaded":
            checked = self.folder_opened_path == path and self._unchecked_path != path
            if path == self.selected_path_globally and not checked:
                self.load_source, self.load_cache_reason, self._load_cache_pending = "disk", "", False
                self.load_counts = dict(event.get("load_counts", {}))
                self._display(path, event["dataset"], event)
        elif kind == "error":
            logging.info("Cached data %s: %s", path, event.get("message", ""))
            if event.get("unverified"):
                self._cache_read_waits = path  # Read again once verification checks its volume.
            # Its check counted those shots as held: a load of the files follows instead.
            self._drop_check_beside_read(path)
        elif kind == "too_large":
            self._drop_check_beside_read(path)
            self._stopped_large(request, event)
        deliberate = bool(request.payload.get("deliberate"))
        if kind in ("loaded", "error") and path == self.selected_path_globally and (self.auto_load_ram or deliberate):
            # Check the folder if that isn't running already (it starts beside the read), reusing the
            # shots just shown; a deliberate read's check is deliberate too (unless Cancel comes first).
            cancels = self._cancel_count
            QTimer.singleShot(0, lambda: self.selected_path_globally == path and not self.closed
                              and cancels == self._cancel_count
                              and self.load_to_ram_cache(path, dwell=not deliberate, explicit=deliberate))
        self._update_activity()
        self.loadStateChanged.emit()

    def _drop_check_beside_read(self, path: str) -> None:
        """Stop the check that ran beside this folder's cached read (it counted the cached shots
        as held), when that read won't deliver them: too large, or the folder isn't cached now."""
        if any(request.operation == "load" and request.path == path and request.payload.get("cache_base")
               for request in self.model.cache.requests(self.model.owner)):
            self.model.cache.cancel(self.model.owner, "load", path)
            self.loading = self.load_paused = False
            self.model.set_load_state(path, "")

    def queue_load(self, path: str) -> bool:
        """Explicit load: never cancels another load; runs now when idle, otherwise queues."""
        if path == self.selected_path_globally:
            return self.load_to_ram_cache(path, dwell=False, explicit=True)
        if path in self._bg_paths or (self.loading and self._load_path == path):
            return True
        try:
            if self._large_blocked(path, True):
                return False
            payload = self._load_payload(path, deliberate=True)
        finally:
            self._allowing = None
        self._bg_paths[path] = None
        if not self.model.cache.submit(self.bg_owner, 0, path, "load", payload, priority=True):
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
        elif kind in ("loaded", "error", "cancelled", "too_large", "shots_missing"):
            del self._bg_paths[path]
            self.model.set_load_state(path, "")
            # The cached read that moved here with its check (``_release_load``) goes with it.
            self.model.cache.cancel(self.bg_owner, "cached", path)
            if kind == "error":
                logging.warning("Background load %s: %s", path, event.get("message", ""))
            if kind == "too_large":
                self._stopped_large(request, event, background=True)
            elif kind == "shots_missing":
                self._shots_missing(request, event, background=True)
            elif kind == "loaded":
                self._large_stops.pop(path, None)
        else:
            return
        self._update_activity()
        self.loadStateChanged.emit()

    def _io_event(self, request: IORequest, event: dict[str, Any]) -> None:
        if not self.closed and request.owner in (self.live_owner, self.live_save_owner):
            self.live_control._live_event(request, event)
            return
        if not self.closed and request.owner == self.bg_owner:
            self._background_event(request, event)
            return
        if self.closed or request.owner != self.model.owner or request.generation != self.model.generation:
            return
        kind = event["kind"]
        if request.operation == "icons":
            if kind in ("done", "error", "cancelled"):
                self._schedule_visible_checks()
            return
        if request.operation == "cached":
            self._cached_event(request, event)
            return
        if request.operation == "root_create":
            self._root_create_event(request, event)
            return
        if request.operation == "resolve":
            if kind == "resolved":
                self.open_to_path(event["path"])
            elif kind == "error":
                self.tree.setRootIndex(self.model.setRootPath(self.target_path, scan=False))
                if self.model.root:
                    self.model.root.state = "error"
                    self.model.root.error = event["message"]
                    self.model.changed(self.model.root)
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
            if request.payload.get("listing_only") and kind == "done":
                self._schedule_visible_checks()
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
                self.load_filename = ""
                self.load_checked_files = self.load_unsettled_files = 0
                self.load_files = self.load_failed_files = 0
                self.load_total_files = None
                self.load_source = self.load_cache_reason = self.load_cache_warning = ""
        elif kind == "file_started":
            self.load_attempt = event.get("attempt", self.load_attempt)
            self.load_filename = event.get("filename", "")
            self.load_listing = ""
        elif kind == "file_finished":
            self.load_attempt = 1
            self.load_filename = ""
        elif kind == "heartbeat":
            count = int(event.get("entries", 0))
            phase = event.get("phase")
            self.load_listing = (f"Listing folder… {count:,} entries" if phase == "listing" else
                                 f"Verifying files… {count:,}" if phase == "verifying" else
                                 f"Checking files… {count:,}")
        elif kind == "progress":
            self.load_listing = ""
            progress: float = event["progress"]
            self.load_progress = progress
            self.load_files = event.get("loaded_files", self.load_files)
            self.load_total_files = event.get("total_files", self.load_total_files)
            self.load_failed_files = event.get("failed_files", self.load_failed_files)
            self.load_checked_files = event.get("checked_files", round(
                progress * self.load_total_files) if self.load_total_files is not None else 0)
            self.load_unsettled_files = event.get("unsettled_files", self.load_unsettled_files)
        elif kind == "load_source":
            if not self._checking(request.path):
                self.load_source = event["source"]
                self.load_cache_reason = event.get("cache_reason", "")
            logging.info("Folder load %s: source=%s; cache=%s; reason=%s", request.path,
                         event["source"], request.payload.get("cache", {}).get("directory", ""),
                         event.get("cache_reason", "") or "cache hit")
        elif kind == "cache_warning":
            self.load_cache_warning = event["message"]
            logging.warning("Folder cache %s: %s", request.path, self.load_cache_warning)
        elif kind == "loaded":
            self.load_paused = False
            if not (event.get("unchanged") and self._checking(request.path)):
                # An unchanged folder keeps the shown data's source and counts.
                self.load_source = event.get("source", "")
                self.load_counts = dict(event.get("load_counts", {}))
                self.load_cache_reason = event.get("cache_reason", "")
            self._load_cache_pending = bool(event.get("disk_cache_pending"))
            if "modified" in event:
                self.model.observe_modified(request.path, event["modified"],
                                            event.get("modified_observed_at", time.time()))
            dataset = event["dataset"]
            assert isinstance(dataset, Dataset)
            self.loading = False
            self.model.set_load_state(request.path, "")
            self._large_stops.pop(request.path, None)
            self._set_large(request.path, None)
            self._display(request.path, dataset, event)
            node = self.model.nodes.get(request.path)
            replaced = request.path in self._listing_replaced
            self._listing_replaced.discard(request.path)
            if node and (node.cached_report or replaced) and not event.get("unchanged"):
                # The folder changed since its saved counts, or since the row's status when its
                # selection didn't list it. This load's own listing and fingerprint are its status
                # (unless it has subfolders, whose names a listing brings).
                summary = self.model.cache.scan_summaries.get(request.path)
                if not (summary and summary.get("signature") == event.get("signature")
                        and self.model.adopt_load_status(request.path, summary)):
                    self.model.request_scan(request.path, priority=True)
        elif kind in ("error", "cancelled"):
            self.loading = self.load_paused = False
            self._loading_data.clear()
            self.load_error = event.get("message", "Cancelled — Retry")
            self.model.set_load_state(request.path, "")
            if request.path in self._listing_replaced:
                self._listing_replaced.discard(request.path)
                if kind == "error":
                    self.model.request_scan(request.path, priority=True)  # The row shows what's there.
        elif kind == "too_large":
            # Stopped before reading anything (S8).
            self.loading = self.load_paused = False
            self._loading_data.clear()
            self.model.set_load_state(request.path, "")
            self._stopped_large(request, event)
        elif kind == "shots_missing":
            self._shots_missing(request, event)
        self._update_activity()
        self.loadStateChanged.emit()

    # Live (roadmaps/live-monitoring.md): ``LiveController`` (helab/views/explorer_live.py) owns it;
    # these are the tab's Live interface for the main window, Folder details and the summary.

    @property
    def live(self) -> LiveSession | None:
        """The session of the folder watched while Live is on (None while off)."""
        return self.live_control.live

    @live.setter
    def live(self, session: LiveSession | None) -> None:
        self.live_control.live = session

    def watching(self, path: str | None) -> bool:
        """Live is on for ``path`` (checking, or stopped by an error until Retry)."""
        return self.live_control.watching(path)

    def live_unavailable(self, path: str) -> str:
        """Why Live can't watch ``path`` now ("" if it can)."""
        return self.live_control.live_unavailable(path)

    def live_state(self) -> tuple[bool, str]:
        """Whether the toolbar's Live can be used now (to turn Live on or off), and its tooltip."""
        return self.live_control.live_state()

    def start_live(self) -> bool:
        """Turn Live on for the selected folder. Whether it started."""
        return self.live_control.start_live()

    def stop_live(self, save: bool = True) -> None:
        """Turn Live off; its new shots are saved in the background unless not ``save``."""
        self.live_control.stop_live(save)

    def resume_live(self) -> None:
        """Retry after an error: check the folder again (listing it) and go on."""
        self.live_control.resume_live()

    def live_reread_note(self, path: str) -> str:
        """Shots of ``path`` that Live read again in the last minute ("" if none)."""
        return self.live_control.live_reread_note(path)

    def _live_save_ended(self, path: str, outcome: str) -> None:
        """``FolderCache.saveEnded``, connected to this tab (so it ends with the tab) for Live."""
        self.live_control._live_save_ended(path, outcome)

    def _shared_dataset_changed(self, path: str) -> None:
        if path == self.selected_path_globally:
            node = self.model.nodes.get(path)
            dataset = self.model.cache.current_dataset(path)
            if dataset is None:
                # Only when the shown data was dropped (cache cleared, folder changed);
                # cached data shown before its check is not the folder's current dataset.
                shown = self.displayed_dataset
                if (self.folder_opened_path == path and not self.watching(path)
                        and (shown is None or not self.model.cache.holds(shown))):
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
        parts = [f"Retrying file… (attempt {self.load_attempt} of 3)"] \
            if self.load_attempt > 1 and self.load_filename else []
        if self.load_listing:
            parts.append(self.load_listing)
        if self.load_progress is not None:
            parts.append(self.loading_progress_message)
        return " · ".join(parts or ["Preparing…"]) + paused

    @property
    def loading_progress_message(self) -> str:
        assert self.load_progress is not None
        percent = f"{self.load_progress:.0%}"
        if self.load_total_files is None:
            return f"Loading… {percent}"
        message = (f"{self.load_checked_files} of {self.load_total_files} files checked ({percent})"
                   f" · {self.load_files} loaded")
        if self.load_failed_files:
            message += f" · {self.load_failed_files} unreadable"
        if self.load_unsettled_files:
            message += f" · {self.load_unsettled_files} still being written"
        return message

    @property
    def load_path(self) -> str | None:
        """The folder this tab is loading for display, if any."""
        return self._load_path

    @property
    def load_is_check(self) -> bool:
        """The selected load is the check of data shown from memory or the disk cache."""
        return self.loading and self._load_path is not None and self._checking(self._load_path)

    @property
    def load_verb(self) -> str:
        """How the selected load is named while it runs: Checking, Loading or Paused."""
        return "Paused" if self.load_paused else "Checking" if self.load_is_check else "Loading"

    @property
    def settling(self) -> bool:
        """The selected folder waits for the selection to settle (Finish, Cancel), not Queue's 3 s."""
        return self.load_waiting and bool(self._settle_wait)

    @property
    def waiting_note(self) -> str:
        """Why the selected folder hasn't started loading yet (``load_waiting``)."""
        if self._settle_wait:
            return (f"Loads this folder if it stays selected for {self._settle_wait:.1f} s: selections are changing "
                    "quickly or I/O is busy, so folders passed on the way don't start loading")
        return f"Queues this folder if it stays selected for {self.DWELL_MS // 1000} s"

    @property
    def dwell_seconds_left(self) -> int:
        """Seconds until a folder waiting to load is queued (memory only)."""
        # Rounded: a coarse timer can report a little over its interval just after starting.
        return max(1, round(self._dwell.remainingTime() / 1000)) if self._dwell.isActive() else 0

    @property
    def load_count_details(self) -> list[str]:
        """Where the shown data's shots came from, e.g. "12 TXY files read"."""
        counts = self.load_counts
        return [f"{counts[key]:,} {label.replace('files', 'file') if counts[key] == 1 else label}"
                for key, label in (
                    ("reused_memory", "reused from memory"), ("reused_disk", "reused from cache"),
                    ("new_loaded", "new files loaded"), ("modified_loaded", "modified files loaded"),
                    ("removed", "files removed"), ("read", "TXY files read")) if counts.get(key)]

    @property
    def load_clock(self) -> LoadClock | None:
        """The selected load's shared clock (memory only)."""
        return self.model.cache.load_clock(self._load_path) if self.loading and self._load_path else None

    @property
    def loading_timing_message(self) -> str:
        """Running time (paused and queued time excluded) and, once measurable, the time left."""
        clock = self.load_clock
        if clock is None or self.load_queued:
            return ""
        text = f"{stopwatch(clock.elapsed())} elapsed"
        if self.load_paused:
            return text  # The estimate resumes with the load.
        stalled = clock.stalled_for()
        remaining = clock.remaining()
        if clock.done_reading:
            text += " · finishing…"
        elif stalled:
            text += f" · no progress for {stopwatch(stalled)}"
        elif remaining is not None:
            text += f" · ~{stopwatch(max(1.0, remaining))} left"
        elif clock.total_bytes:
            text += " · estimating…"
        return text

    @property
    def loading_rate_message(self) -> str:
        """Read rate over the clock's window: TXY bytes actually read, and files checked."""
        clock = self.load_clock
        rates = clock.rates() if clock is not None and not self.load_paused and not clock.done_reading else None
        if not rates or (rates[0] <= 0 and rates[1] <= 0):
            return ""
        files = f"{rates[1]:.1f}" if 0 < rates[1] < 10 else f"{rates[1]:,.0f}"
        return f"{byte_rate(rates[0])} · {files} files/s"

    @property
    def activity_brief(self) -> str:
        """This tab's most important activity in a few words, for the main status bar."""
        if self.live is not None:
            name = os.path.basename(self.live.path.rstrip(os.sep)) or self.live.path
            return f"Live stopped: {name}" if self.live.error else f"Live {name} · {plural(self.live.new, 'new shot')}"
        if self.loading and self._load_path:
            name = os.path.basename(self._load_path.rstrip(os.sep)) or self._load_path
            if self.load_queued:
                return f"Queued {name}"
            parts = [f"{self.load_verb} {name}"]
            if self.load_progress is not None:
                parts.append(f"{self.load_progress:.0%}")
            clock = self.load_clock
            remaining = clock.remaining() if clock is not None and not self.load_paused else None
            if remaining is not None and clock is not None and not clock.done_reading:
                parts.append(f"~{stopwatch(max(1.0, remaining))} left")
            elif clock is not None and not self.load_paused:
                parts.append(stopwatch(clock.elapsed()))
            return " · ".join(parts)
        if any(r.operation == "resolve" for r in self.model.cache.requests(self.model.owner)):
            return "Finding default folder…"
        if self._basic_active:
            text = f"Checking folder status · {self._basic_completed:,} checked"
            return text + (f" · {self._basic_failed:,} failed" if self._basic_failed else "")
        if self._basic_result:
            return self._basic_result.split(" · ")[0]
        if self._bg_paths:
            count = len(self._bg_paths)
            return f"{count} background load{'' if count == 1 else 's'}"
        large = self.large_state(self.selected_path_globally)
        if large is not None and not self.loading:
            return large_text(*large)
        warning = self.model.cache.mount_warning(self.selected_path_globally)
        if warning is not None:
            return warning[0]
        return ""

    @property
    def loading_tooltip(self) -> str:
        parts = [self.loading_message] if self.loading else []
        if self.loading and (timing := self.loading_timing_message):
            parts[0] += f"\n{timing}"
        if self.loading and self.load_attempt > 1 and self.load_filename:
            parts.append(f"Retrying file: {os.path.basename(self.load_filename)}\n"
                         f"Attempt {self.load_attempt} of 3 for this file")
        if self.load_waiting:
            parts.append(self.waiting_note)
        queue_details = self.model.service.queue_tooltip()
        if queue_details:
            parts.append(queue_details)
        if self._bg_paths:
            parts.append("Loading in the background:\n" + "\n".join(self._bg_paths))
        reason = self.load_cache_warning or self.load_cache_reason
        if reason:
            parts.append(reason)
        if warning := self.model.cache.mount_warning(self.selected_path_globally):
            parts.append(warning[1])
        return "\n\n".join(parts)

    def _update_activity(self) -> None:
        """Refresh the summary and this tab's part of the main window's status bar."""
        if self.closed:
            return
        self._update_folder_summary()
        requests = self.model.cache.requests(self.model.owner)
        parts: list[str] = []
        if any(r.operation == "resolve" for r in requests):
            parts.append("Finding default folder…")
        if self._basic_active:
            parts.append(self._basic_progress())
        elif self._basic_result:
            # Folder errors are on the summary's first line, so this never hides them.
            parts.append(self._basic_result)
        if self._bg_paths:
            parts.append(self._background_summary())
        self.activity_text = " · ".join(parts)
        self.activity_tooltip = ("Loading in the background:\n" + "\n".join(
            f"{path} ({self.model.load_states.get(path) or 'queued'})" for path in self._bg_paths)
            if self._bg_paths else "")
        if warning := self.model.cache.mount_warning(self.selected_path_globally):
            self.activity_tooltip = "\n\n".join(filter(None, (self.activity_tooltip, warning[1])))
        self.activity_busy = bool(requests or self.loading or self._bg_paths or self._basic_active)

    def _mount_warning_changed(self, _path: str) -> None:
        self._update_activity()

    def _basic_progress(self) -> str:
        """Submitted folders may still be queued or paused; only started ones are scanning."""
        scanning = paused = queued = 0
        for path in self._deep_depth:
            job = next((job for operation in ("scan", "details", "list")
                        if (job := self.model.cache.jobs.get((operation, path))) is not None), None)
            if job is not None and job.paused:
                paused += 1
            elif job is not None and job.state == "started":
                scanning += 1
            else:
                queued += 1
        counts = ((self._basic_completed, "scanned"), (scanning, "scanning"), (paused, "paused"),
                  (queued, "queued"), (self._basic_failed, "failed"))
        return "Checking folder status: " + " · ".join(f"{count:,} {label}" for count, label in counts
                                           if count or label == "scanned")

    def _background_summary(self) -> str:
        states = [self.model.load_states.get(path) or "queued" for path in self._bg_paths]
        terms = [f"{states.count(state)} {state}" for state in ("loading", "paused", "queued")
                 if states.count(state)]
        noun = "background load" if len(states) == 1 else "background loads"
        return f"{len(states)} {noun}: " + ", ".join(terms)

    @property
    def scan_message(self) -> str:
        """Selected-folder scan activity from memory, shared by summary and centre."""
        path = self.selected_path_globally
        node = self.model.nodes.get(path)
        job = next((job for operation in ("list", "scan")
                    if (job := self.model.cache.jobs.get((operation, path))) is not None), None)
        if job is not None and job.paused:
            return "Scan paused"
        state = job.state if job is not None else node.state if node else "idle"
        if state == "queued":
            return "Scan queued"
        if state not in ("started", "running"):
            return ""
        if job is not None and job.operation == "list":
            return f"Listing folder… {node.listed:,} entries" if node and node.listed else "Listing folder…"
        return "Scanning: checking file counts and status…"

    def _update_folder_summary(self) -> None:
        """Describe the active folder from memory; never probe the filesystem."""
        path = self.selected_path_globally
        node = self.model.nodes.get(path)
        report = node.report if node else None
        selected = path != self.view_path
        retrying = self.retrying_scan
        scan_error = node.error if node else ""
        root_error = self.model.root.error if self.model.root else ""
        self.selected_folder_label.setVisible(selected)
        self.selected_folder_label.setText(f"{os.path.relpath(path, self.view_path)} ›" if selected else "")
        self.selected_folder_label.setToolTip(f"Selected: {path}" if selected else "")
        self.deselect_button.setVisible(selected)
        self.deselect_button.setToolTip(self.deselect_tooltip)
        self.cancel_load_button.setVisible(self.can_cancel_loading)
        self.cancel_load_button.setToolTip(
            "Cancel the folder listing retry (Esc)" if retrying and not (self.loading or self.load_waiting)
            else "Cancel loading in this tab (Esc)")
        paused = self.auto_load_paused_path == path
        off = self.auto_load_off(path)
        large = self.large_state(path) if path == self.selected_path_globally else None
        offer_large = large is not None and not large[1] and not self.load_error
        idle = not (self.loading or self.load_waiting or retrying)
        live_error = bool(self.live is not None and self.live.error)
        self.retry_button.setVisible(bool(self.load_error or scan_error or root_error or paused or offer_large or off
                                          or live_error) and idle)
        retry_path = self.listing_retry_path
        self.retry_button.setText("Retry" if live_error else "Load anyway…" if offer_large else
                                  "Load" if (paused or off) and not self.load_error else "Retry")
        self.retry_button.setEnabled(bool(self.load_error) or paused or offer_large or off or live_error
                                     or not self.model.refresh_pending(retry_path))
        self.no_auto_load_button.setVisible(large is not None and not off and idle and bool(store_options()))
        mismatched = path in self.model.cache.mismatched
        self.review_button.setVisible(mismatched and idle)
        self.root_review_button.setVisible(self.model.cache.pending_root(path) is not None and not mismatched)
        self.retry_button.setToolTip(LIVE_RETRY_TOOLTIP if live_error else
                                     MISMATCH_RETRY_TOOLTIP if mismatched and self.load_error else
                                     "Load this folder again" if self.load_error else
                                     LARGE_TOOLTIP if offer_large else
                                     AUTO_LOAD_PAUSED_TOOLTIP if paused else
                                     AUTO_LOAD_OFF_TOOLTIP if off else
                                     "Wait for this folder's refresh to finish" if not self.retry_button.isEnabled() else
                                     "List this folder again, without a time limit")
        watching = self.watching(path)
        # (Live's own relisting of the tree is no news: its data is the folder's, as of its last check.)
        scan_message = "" if watching else self.scan_message
        history = self.model.cache.scan_history(path)
        dataset = self.displayed_dataset
        shown = dataset is not None and dataset.path == path
        changed = bool(shown and node and report and not node.cached_report and not watching and
                       self._changed_since_load(node, dataset)) if dataset else False
        unchecked = shown and self.folder_opened_path == path and self._unchecked_path == path
        # Data shown before its check keeps its counts while the check runs.
        if shown and dataset is not None and (unchecked or not (self.loading and self._load_path == path)):
            failed = int(dataset.metadata.get("failed_files", 0))
            unsettled = int(dataset.metadata.get("unsettled_files", 0))
            loaded = int(dataset.metadata["files"])
            found = (len(report.d_txy_shots or []) if changed and report else
                     int(dataset.metadata.get("total_files", loaded + failed + unsettled)))
            label = "previously loaded" if changed else "loaded (cached)" if unchecked else "loaded"
            text = f"{found:,} TXY found · {loaded:,} {label}"
            if failed:
                text += f" · {failed:,} unreadable"
            if unsettled:
                text += f" · {unsettled:,} still being written"
            if changed:
                text += " · Changes detected"
            elif self.folder_opened_path != path:
                text += " · Previous data"
            if self.load_error:
                text += f" · {self.load_error}"
            elif large is not None and not (self.loading and self._load_path == path):
                # Why the update didn't load: the shown data stays.
                text += f" · {large_text(*large)}"
        elif report is None:
            text = (self.retry_message(retrying) if retrying else
                    f"Loading · {self.loading_message}" if self.loading and self._load_path == path else
                    "TXY count not checked · Retry manually" if history["blocked"] or node and node.scan_skipped else
                    "Could not check folder · Retry" if scan_error else
                    scan_message or "TXY count not checked")
        elif report.d_txy_shots or node and node.txy_count:
            found = (self.load_total_files if self.loading and self._load_path == path
                     and self.load_total_files is not None else node.txy_count if node else len(report.d_txy_shots or []))
            text = f"{found:,} TXY found"
            if self.loading and self._load_path == path:
                text += f" · {self.loading_message}"
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
                text += (" · Waiting for the selection to settle" if self._settle_wait
                         else f" · Waiting {self.DWELL_MS // 1000} s before queueing")
            elif self.auto_load_paused_path == path:
                text += f" · {AUTO_LOAD_PAUSED}"
            elif off and not (self.loading and self._load_path == path):
                text += f" · {AUTO_LOAD_OFF}"
            elif large is not None and not (self.loading and self._load_path == path):
                text += f" · {large_text(*large)}"
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
            elif scan_message:
                text += f" · {scan_message}"
        self.folder_summary_label.setText(text)
        # Amber while the selected folder is too large to load automatically, like freshness warnings.
        self.folder_summary_label.setStyleSheet(f"color: {AMBER};" if large is not None and large_text(*large) in text
                                                else "")
        self._fit_selected_label()
        load_details = ""
        if shown and dataset is not None:
            rows = int(dataset.metadata.get("rows", 0))
            loaded_at = dataset.metadata.get("loaded_at")
            load_details = f"{rows:,} data rows loaded"
            if isinstance(loaded_at, (int, float)):
                load_details += f"\nData loaded: {datetime.fromtimestamp(loaded_at).astimezone():%Y-%m-%d %H:%M:%S %Z}"
            problematic = dataset.metadata.get("problematic", [])
            if problematic:
                load_details += f"\nShots unreadable or with invalid rows: {', '.join(map(str, problematic[:20]))}"
            if changed:
                load_details += "\nLoaded data belongs to the previous folder contents. Load data to update it."
        self.folder_summary_label.setToolTip("\n".join(filter(None, (
            path, load_details, scan_error, self.load_error, self.loading_tooltip,
            (mount_notice[1] if (mount_notice := self.model.cache.mount_warning(path)) else ""),
            (REFUSED_TOOLTIP if large[1] else LARGE_TOOLTIP) if large else ""))))
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
                f"Folder status check failed {self._relative_age(time.time() - failed_at)} · Retry manually")
        self.folder_freshness_label.setToolTip("\n".join(filter(None, (history_tooltip(history, time.time()),
            self.model.cache.scan_history_errors.get(path),
            f"Saved results unknown: {warning}" if (warning := self.model.cache.cache_read_errors.get(path)) else "",
            freshness_tooltip(
            "Last successful status scan", node.scanned_at if node else None, node.modified if node else None,
            status_freshness, "Use Check folder status to recheck counts and status.")))))
        live = self.live_control.session(path)
        stopped = False
        if live is not None:
            # Live replaces the line: what it checked, found and saved.
            text, tooltip, stopped = self.live_control.live_line(live)
            self.folder_freshness_label.setText(text)
            self.folder_freshness_label.setToolTip(tooltip)
        elif reread := self.live_reread_note(path):
            # Live has stopped, and its last save read shots again: said for a minute here too.
            self.folder_freshness_label.setText(f"{self.folder_freshness_label.text()} · {reread}")
        style = f"color: {AMBER};" if stopped else ""
        if self.folder_freshness_label.styleSheet() != style:
            self.folder_freshness_label.setStyleSheet(style)

    def _fit_selected_label(self) -> None:
        """Share line 1: the selected path gets its full width or at least 2/5 of the free space."""
        if self.selected_folder_label.isHidden():
            return
        buttons = sum(self._summary_button_width + 4 for button in self.summary_buttons if not button.isHidden())
        free = max(0, self.folder_counts_row.width() - buttons - 4)
        room = max(free * 2 // 5, free - self.folder_summary_label.natural_width())
        self.selected_folder_label.setFixedWidth(min(self.selected_folder_label.natural_width(), room))

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        self._fit_selected_label()

    @staticmethod
    def _relative_age(seconds: float) -> str:
        return relative_age(seconds)

    def _update_cache_summary(self, path: str, report: StatusReport | None) -> None:
        cache = self.model.cache
        node = self.model.nodes.get(path)
        # The line is always shown, so the summary keeps its height.
        if (pending := cache.pending_root(path)) is not None:
            self.folder_cache_label.setText(PENDING_SUMMARY)
            self.folder_cache_label.setToolTip(f"{pending_root_text(pending)}\n\n{PENDING_ROOT_TOOLTIP}")
            return
        if not cache.disk_cache_known(path):
            self.folder_cache_label.setText("Cache not checked")
            self.folder_cache_label.setToolTip("Cache availability is reported by the folder listing or a load.")
            return
        if not (cache.disk_cached(path) or report is None or report.d_txy_shots or node and node.txy_count):
            self.folder_cache_label.setText("No data to cache")
            self.folder_cache_label.setToolTip("This folder has no TXY files.")
            return
        dataset = self.displayed_dataset
        current = bool(dataset and dataset.path == path and self.folder_opened_path == path)
        unchecked = current and self._unchecked_path == path
        state = cache.cache_status(path)
        saved_at = metadata_date(state.info.get("saved_at"))
        ago = self._relative_age(time.time() - saved_at) if isinstance(saved_at, (int, float)) else ""
        suffix = f" · Cached {ago}" if ago else ""
        if cache.disk_cache_saving(path):
            text = "Updating cache…" if cache.disk_cached(path) else "Creating cache…"
        elif path in cache.pending_saves and state.error:
            text = state.error  # Waiting for the user's answer (Make room / Save update).
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
        if unchecked:
            text += " · Check failed" if self.load_error else " · Checking for changes…"
        elif cache.disk_cached(path) and freshness.value:
            text += f" · {freshness.value}"
        self.folder_cache_label.setText(text)
        origin = LOAD_ORIGINS.get(self.load_source)
        details = self.load_count_details if current else []
        exact = (datetime.fromtimestamp(saved_at).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
                 if isinstance(saved_at, (int, float)) else "")
        self.folder_cache_label.setToolTip("\n".join(filter(None, (
            f"Loaded from {origin}" if origin and current else "",
            ("Not yet checked against the folder: " + (self.load_error or "the check is queued or running"))
            if unchecked else "",
            self.load_cache_reason if current else "",
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
        if not self.closed:
            self.icon_timer.start(150)
        if not self.closed and self.auto_scan_visible and not self.model.refreshing:
            self.visible_timer.start(150)

    def _refresh_state_changed(self) -> None:
        if self.closed:
            return
        if self.model.refreshing:
            self.visible_timer.stop()
            self._visible_seen.clear()
        else:
            self._schedule_visible_checks()
        self._update_activity()
        self.loadStateChanged.emit()

    def _load_visible_icons(self) -> None:
        if self.closed or not self.isVisible():
            return
        paths = [self.model.rootPath(), *self._viewport_paths()]
        if not self.model.request_folder_icons(paths):
            self.icon_timer.start(250)

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
        if self.closed or self.model.refreshing or not self.auto_scan_visible or not self.isVisible():
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

    def _choose_scan_depth(self) -> None:
        self._choose_scan_depth_for(self.selected_path_globally)

    def _choose_scan_depth_for(self, path: str) -> None:
        depth, accepted = QInputDialog.getInt(self, "Check folder status", "Subfolder levels (0 = current folder):", 1, 0, 32768)
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
            self._basic_result = f"Folder status check cancelled · {self._basic_completed:,} scanned"
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
            self._basic_result = f"Folder status check complete · {self._basic_completed:,} scanned · {self._basic_failed:,} failed"
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
        retry = menu.addAction("Retry / Refresh", lambda: self.refresh_folder(path))
        if retry:
            retry.setEnabled(not self.model.refresh_pending(path))
        submenu = menu.addMenu("Check folder status")
        if submenu:
            for depth in (0, 1, 2, 3, 32768):
                submenu.addAction("All subfolders" if depth == 32768 else f"Depth {depth}", lambda checked=False, d=depth: self.context_menu_action_deep_calc_status(path, d))
            submenu.addAction("Custom depth…", lambda: self._choose_scan_depth_for(path))
        menu.addAction("Load data", lambda: self.queue_load(path))
        prefs = self.model.cache.folder_prefs(path)
        # Folder flags and cached data live in the disk cache: a RAM-only folder has neither.
        ram_only = self.model.cache.no_root(path) is not None
        for key, label in (("no_cache", "Don't cache this folder"), ("no_auto_load", "Don't auto-load this folder")):
            flag = menu.addAction(label)
            if flag:
                flag.setCheckable(True)
                flag.setChecked(prefs[key])
                flag.setToolTip(NEEDS_ROOT_TOOLTIP if ram_only else "This folder only, never its subfolders")
                flag.setEnabled(not ram_only)
                flag.toggled.connect(lambda on, k=key: self.set_folder_flag(path, k, on))
        constants = menu.addAction("Folder constants…", lambda: self.show_folder_constants(path))
        if constants:
            constants.setToolTip("Fall distance, fall time and trap frequencies for this folder and its "
                                 "subfolders" + (" (RAM only: this session)" if ram_only else ""))
        clear = menu.addAction("Clear loaded data cache", lambda: self.clear_data_cache(path))
        if clear and ram_only:
            clear.setEnabled(False)
            clear.setToolTip(NEEDS_ROOT_TOOLTIP)
        menu.addSeparator()
        place = menu.addAction(PLACE_ROOT_ACTION, lambda: self.place_root(path))
        if place:
            enabled, tooltip = self.place_root_state(path)
            place.setEnabled(enabled)
            place.setToolTip(tooltip)
        menu.setToolTipsVisible(True)
        cancel_action = menu.addAction("Cancel Loading", self.cancel_loading)
        if cancel_action:
            cancel_action.setEnabled(self.can_cancel_loading)
        viewport = self.tree.viewport()
        if viewport:
            menu.exec(viewport.mapToGlobal(position))

    def place_root_state(self, path: str) -> tuple[bool, str]:
        """Whether Place .helab-root here… is offered for this folder, and its tooltip (memory only)."""
        cache = self.model.cache
        if not store_options():
            return False, "The disk cache is off for this session"
        root = cache.root_of(path)
        if root is not None and root[0] == path:
            return False, "This folder already has a .helab-root"
        if root is not None:
            return True, (f"Inside data root “{root[2] or os.path.basename(root[0])}” ({marker_path(root[0])}). "
                          "A .helab-root here would give this folder its own identity.")
        return True, PLACE_ROOT_TOOLTIP

    def place_root(self, path: str) -> bool:
        """Right-click › Place .helab-root here…: confirm (with the checks' warnings), then write the
        marker in the chosen folder, or adopt the one there. Whether it was submitted."""
        from helab.views.DataRootDialogs import ask_place_root
        if self.closed or not store_options():
            return False
        target = ask_place_root(self, self.model.cache, path)
        if target is None:
            return False
        # The folder right-clicked is listed again too when the marker went to its drive's top.
        return self.model.cache.submit(self.model.owner, self.model.generation, target, "root_create",
                                       {"cache": store_options(), "clicked": path}, priority=True)

    def _review_root(self) -> None:
        if (pending := self.model.cache.pending_root(self.selected_path_globally)) is not None:
            self.reviewRootRequested.emit(str(pending["location"]))

    def _root_decided(self, paths: list[str]) -> None:
        """Same folder, Copy or Delete .helab-root took effect: list those folders again where this
        tab shows them, and its top and selected folders inside them, so ⚓ and RAM only update."""
        if self.closed:
            return
        shown = (self.model.rootPath(), self.selected_path_globally)
        again = [path for path in paths if path in self.model.nodes]
        again += [folder for folder in shown if folder in self.model.nodes and any(
            folder.startswith(path.rstrip("/\\") + os.sep) for path in paths)]
        for path in dict.fromkeys(again):
            self.refresh_folder(path)
        self._update_activity()

    def _root_create_event(self, request: IORequest, event: dict[str, Any]) -> None:
        from helab.views.DataRootDialogs import TITLE, ManualMarkerDialog
        kind, path = event["kind"], request.path
        if kind == "root_manual":
            # Non-modal: the user places the file, then Retry / Refresh finds it.
            ManualMarkerDialog(self, self.model.cache, str(event["path"]), str(event["name"]),
                               str(event["contents"]), str(event.get("reason", ""))).show()
        elif kind in ("root_created", "root_adopted"):
            # Its listing (and the subfolders' saved results) under the new root; folders not in
            # this tab's tree are skipped.
            for folder in dict.fromkeys((path, str(request.payload.get("clicked") or path))):
                if folder in self.model.nodes:
                    self.refresh_folder(folder)
        elif kind == "error":
            box = QMessageBox(QMessageBox.Icon.Warning, TITLE,
                              f"{path}\n\n{event.get('message', 'The .helab-root could not be placed')}", parent=self)
            box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            box.open()
        self._update_activity()

    def auto_load_off(self, path: str | None) -> bool:
        """The user chose not to auto-load this folder, and its data isn't open here."""
        return bool(path) and self.model.cache.folder_prefs(str(path))["no_auto_load"] and (
            self.folder_opened_path != path)

    def set_folder_flag(self, path: str, key: str, on: bool) -> None:
        """Right-click › Don't cache / Don't auto-load this folder (this folder only). Ticking
        Don't cache offers to remove the folder's cached data."""
        cache = self.model.cache
        prefs = {**cache.folder_prefs(path), key: on}
        remove = False
        if key == "no_cache" and on and cache.disk_cached(path):
            size = cache.cache_status(path).info.get("disk_bytes")
            remove = (self.ask_remove_cached or self._ask_remove_cached)(
                path, size if isinstance(size, int) else None)
        cache.set_folder_prefs(path, no_cache=prefs["no_cache"], no_auto_load=prefs["no_auto_load"],
                               remove_cached=remove, owner=self.model.owner)
        self.loadStateChanged.emit()

    def show_folder_constants(self, path: str) -> None:
        """Right-click › Folder constants… (window-modal; saved by a helper on Save)."""
        from helab.views.FolderConstantsDialog import FolderConstantsDialog
        dialog = FolderConstantsDialog(path, self.model.cache, owner=self.model.owner, parent=self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.open()

    def _folder_constants_failed(self, path: str, message: str, owner: str) -> None:
        """Constants this tab set couldn't be saved; FolderCache has put the saved ones back."""
        if self.closed or owner != self.model.owner:
            return
        name = os.path.basename(path.rstrip(os.sep)) or path
        text = f"HeLab couldn't save the constants for {name}: {message}. Try again."
        if self.report_flag_failure is not None:
            self.report_flag_failure(path, text)
        else:
            QMessageBox.warning(self, "Folder constants not saved", text)

    def _ask_remove_cached(self, path: str, size: int | None) -> bool:
        name = os.path.basename(path.rstrip(os.sep)) or path
        box = QMessageBox(QMessageBox.Icon.Question, "Don't cache this folder",
                          f"{name} won't be cached from now on. Remove its cached data"
                          f"{f' ({byte_size(size)})' if size else ''}?", parent=self)
        remove = box.addButton("Remove cached data", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Keep it", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is remove

    def _drop_automatic(self, path: str, operations: tuple[str, ...]) -> set[str]:
        """A flag just set for ``path``: stop this tab's automatic work it rules out (queued or
        running); work the user asked for stays. Returns the operations stopped."""
        cache = self.model.cache
        dropped: set[str] = set()
        for owner in (self.model.owner, self.bg_owner):
            for request in cache.requests(owner):
                if (request.path == path and request.operation in operations
                        and not request.payload.get("deliberate")):
                    cache.cancel(owner, request.operation, path)
                    dropped.add(request.operation)
        if path in self._bg_paths and not any(
                r.path == path and r.operation == "load" for r in cache.requests(self.bg_owner)):
            del self._bg_paths[path]
            self.model.set_load_state(path, "")
        if path == self._load_path and not self.loading:
            self.load_error = ""  # Stopped by the user's choice, not a failure.
        return dropped

    def _folder_prefs_changed(self, path: str) -> None:
        if self.closed:
            return
        prefs = self.model.cache.folder_prefs(path)
        if prefs["no_auto_load"]:
            self._drop_automatic(path, ("load", "cached"))
        if prefs["no_cache"] and "cached" in self._drop_automatic(path, ("cached",)) and (
                path == self.selected_path_globally and self.auto_load_ram and not prefs["no_auto_load"]):
            # Not from the cache, then: from the folder itself.
            self._drop_check_beside_read(path)
            self._cache_read_path = None
            QTimer.singleShot(0, lambda: self.selected_path_globally == path and not self.closed
                              and self.load_to_ram_cache(path))
        node = self.model.nodes.get(path)
        if node:
            self.model.changed(node)
        off = self.model.cache.folder_prefs(path)["no_auto_load"]
        was_off = path in self._auto_load_off_paths
        if off:
            self._auto_load_off_paths.add(path)
        else:
            self._auto_load_off_paths.discard(path)
        if path == self.selected_path_globally:
            if was_off and not off and self.auto_load_ram and not self.loading:
                self.load_to_ram_cache(path)  # Auto-load is on again for the selected folder.
            self._update_activity()
            self.loadStateChanged.emit()

    def _folder_prefs_failed(self, path: str, message: str, owner: str) -> None:
        """A flag this tab set couldn't be saved; FolderCache has put the saved state back."""
        if self.closed or owner != self.model.owner:
            return
        name = os.path.basename(path.rstrip(os.sep)) or path
        text = f"HeLab couldn't save your choice for {name}: {message}. Try again."
        if self.report_flag_failure is not None:
            self.report_flag_failure(path, text)
        else:
            QMessageBox.warning(self, "Folder setting not saved", text)

    def reveal(self, path: str) -> None:
        """Show ``path`` (e.g. a load's folder): select its row if this tab has it, else open it."""
        node = self.model.nodes.get(path)
        index = self.model.path_index(path) if node is not None else QModelIndex()
        if index.isValid():
            self.tree.setCurrentIndex(index)
            self.tree.scrollTo(index)
        else:
            self.open_to_path(path)

    def clear_data_cache(self, path: str) -> None:
        self.model.cache.cancel(self.model.owner, "load")
        self.load_error = ""
        if not self.model.cache.submit(self.model.owner, self.model.generation, path, "invalidate",
                                         {"cache": store_options()}, priority=True):
            self.load_error = "Cache request queue full — Retry"
        self.loadStateChanged.emit()

    def on_double_click(self, index: QModelIndex) -> None:
        self.open_to_path(self.model.filePath(index))

    def on_back_button_clicked(self) -> None:
        self.open_to_path(os.path.dirname(self.view_path))

    def update_back_button_state(self) -> None:
        self.back_button_enabled = os.path.dirname(self.view_path) != self.view_path

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
        self.stop_live()
        self._release_load()
        self._cancelled_load_path = self._cache_read_path = None
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
        self.model.refresh()

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
        self._cancel_count += 1
        self._cancelled_load_path = self.selected_path_globally
        self._cancel_background()
        self.model.cache.cancel(self.model.owner, "load")
        self.model.cache.cancel(self.model.owner, "cached")
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
        # Closing a tab stops Live; its new shots are saved in the background all the same.
        self.stop_live()
        self.live_control._live_timer.stop()
        if self.is_foreground:
            self.model.cache.set_foreground(set())
        self._cancel_background()
        self.closed = True
        self.visible_timer.stop()
        self.icon_timer.stop()
        self.cancel_basic_scan()
        self.animation.stop()
        self.deep_timer.stop()
        self.model.close_cleanup()
        self.model.cache.resultReady.disconnect(self._io_event)
        self.model.cache.datasetChanged.disconnect(self._shared_dataset_changed)
        self.model.cache.autoLoadPauseChanged.disconnect(self._auto_load_pause_changed)
        self.model.cache.folderPrefsChanged.disconnect(self._folder_prefs_changed)
        self.model.cache.folderPrefsFailed.disconnect(self._folder_prefs_failed)
        self.model.cache.folderConstantsFailed.disconnect(self._folder_constants_failed)
        self.model.cache.mountWarningChanged.disconnect(self._mount_warning_changed)
        self.model.cache.volumesVerified.disconnect(self._volumes_verified)
        self.model.cache.rootDecided.disconnect(self._root_decided)
        self.model.cache.rootDuplicatesChanged.disconnect(self._update_activity)
        self.model.cache.saveEnded.disconnect(self._live_save_ended)
        self.model.cache.release(self.model.owner)
        self.folder_opened_data = None
        self.displayed_dataset = None
        self._loading_data.clear()
