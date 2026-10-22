import gc
import logging
import os
import platform
import signal
import sys
import tempfile
import types
import threading
import time
from helab.utils.io_service import IORequest, delete_io_traces, get_io_service, io_trace_folder, io_trace_refused
from helab.utils.folder_cache import get_folder_cache, set_disk_budget, store_options
from helab.utils.gui_watchdog import GUIWatchdog
from helab.utils.lab_parameters import read_lab_constants
from helab.utils import events
from datetime import datetime
from sys import getsizeof
from typing import Any, Callable, List, Optional

import psutil
from PyQt6.QtCore import Qt, QSize, QTimer, QItemSelection, QUrl, QDateTime, QSettings, QRect
from PyQt6.QtGui import QAction, QActionGroup, QIcon, QCloseEvent, QGuiApplication, QPainter, QPixmap, QKeySequence
from PyQt6.QtWidgets import QMainWindow, QStatusBar, QMenuBar, QWidget, QVBoxLayout, QSplitter, \
    QLabel, QToolBar, QSizePolicy, QMenu, QApplication, QInputDialog, QProgressBar, QToolButton, QMessageBox

from helab.views.plots.script_tree import TreePanelWidget
from helab.views.plots.workspace import PlotWorkspace
from helab.resources.icons import ToolIcons
from helab.utils.constants import (
    APP_BUILD_INFO, APP_COMMIT_HASH, APP_VERSION, DEFAULT_LOAD_MODE, DIR_TEMPS, LOAD_MODE_LABELS,
    QSPLITTER_STYLESHEET, TOOLBAR_STYLESHEET_LR, assert_warn, cache_dir_refused, read_check_level,
    read_disk_budget, read_io_concurrency, read_live_autosave, read_live_interval, read_load_mode,
    read_plot_auto_reload, read_ram_budget,
)
from helab.utils.number_format import byte_size, fnum
from helab.utils.settings_defaults import (
    AUTO_SCAN_VISIBLE_SETTING, LOAD_MODE_SETTING, THREAD_STATUS_SETTING, read_setting)
from helab.utils.settings_store import app_settings
from helab.views.CacheDialogs import CacheDialogs
from helab.views.ElidedLabel import ElidedLabel
from helab.views.FolderDetailsPanel import FolderDetailsPanel
from helab.views.HoverMenuToolButton import HoverMenuToolButton
from helab.views.FolderExplorer import (
    AUTO_LOAD_OFF_TOOLTIP, AUTO_LOAD_PAUSED, AUTO_LOAD_PAUSED_TOOLTIP, LARGE_TOOLTIP, REFUSED_TOOLTIP, IO_SPINNER, FolderExplorer,
    paint_spinner,
)
from helab.views.explorer_text import large_text
from helab.views.FolderTabWidget import FolderTabWidget
from helab.views.MemoryUsageWindow import MemoryUsageWindow
from helab.views.MissingShotsWindow import MissingShotsWindow
from helab.views.QuitSaveDialog import QuitSaveDialog
from helab.views.RootDuplicatesWindow import RootDuplicatesWindow
from helab.views.SettingsDialog import SettingsDialog
from helab.views.DebugIconsWindow import DebugIconsWindow

# QtWebEngine must be imported before the QApplication exists; main.py imports this module first.
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401

PLACE_ROOT_MENU = " Place .helab-root…"


class HelabMainWindow(QMainWindow):
    DEFAULT_WIDTH = 1600
    DEFAULT_HEIGHT = 900

    FOLDER_STATUS_TOOLTIP = (
        "Check folder status\n"
        "Check counts and status without loading TXY data.\n"
        "Icon: check folders in view.\n"
        "Arrow below: choose which folders to check."
    )

    INTERVAL_UPDATE_STATUS_BAR_LEFT = 100
    INTERVAL_UPDATE_STATUS_BAR_RIGHT = 1000
    INTERVAL_UPDATE_CENTRAL_LOADING_INDICATOR = 100

    STATUS_LEFT_MISSED_REFRESH_HANG_THRESHOLD_COUNTS = 10
    STATUS_LEFT_MISSED_REFRESH_HANG_THRESHOLD_SECS = 10
    STATUS_LEFT_DEBUG_PRINT_HANG_THRESHOLD_MS = 999

    def __init__(self) -> None:
        super().__init__()
        self._closing = False
        # Quitting waits for disk cache saves (QuitSaveDialog) unless Quit now, or none are left.
        self._quit_dialog: QuitSaveDialog | None = None
        self._quit_now = False
        self._cache_dialogs_detached = False
        self.watchdog = GUIWatchdog(self)
        # logging.debug(f"Current directory is {CURRENT_WORKING_DIRECTORY}")
        if not os.path.exists(DIR_TEMPS): os.makedirs(DIR_TEMPS)

        self.current_tracking_folder_path = '/'
        self.named_temp_files: List[tempfile._TemporaryFileWrapper[bytes]] = [] #TODO: dev code, remove these in prod

        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGTERM, self.handle_exit)

        self.process = psutil.Process()
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "ai-icon.icns")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            logging.error(f"Icon file not found: {icon_path}")

        self.setWindowTitle(f"HeLab GUI Loading... v{APP_VERSION} ({APP_COMMIT_HASH})")
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.setMinimumSize(1000, 600)

        # Create Central Widget Area with Dock Widgets
        self._setup_central_widgets()
        self._start_with_rhi_surface()

        self.status_bar = QStatusBar()
        self._create_status_bar()

        # Create Menubar
        menubar = self.menuBar()
        if menubar is None:
            logging.fatal("QMainWindow.menuBar() returned None.")
            sys.exit(1)
        self.menu_bar: QMenuBar = menubar
        self.create_menus()

        # The disk cache's questions (Make room, Save update, 80% full), one at a time.
        cache = get_folder_cache(get_io_service())
        self.cache_dialogs = CacheDialogs(cache, self, lambda: self.show_settings_dialog(purge=True),
                                          self.show_status_notice)
        cache.autoLoadPauseChanged.connect(self._auto_load_pause_changed)
        # Folders whose cached data doesn't match them: one list for the app, and its status-bar button.
        self.missing_shots = MissingShotsWindow(cache, self)
        self.missing_shots.loadRequested.connect(self._load_mismatched)
        self.mismatch_button.clicked.connect(lambda: self.missing_shots.show_list(activate=True))
        cache.mismatchesChanged.connect(self._update_mismatch_button)
        # Locations whose .helab-root is also elsewhere: same folder or a copy? (data roots, D4)
        self.root_duplicates = RootDuplicatesWindow(cache, self)
        self.roots_button.clicked.connect(lambda: self.review_root(None))
        cache.rootDuplicatesChanged.connect(self._update_roots_button)
        self.plots.setup_ram_budget(cache, app_settings())

        # Create Left Panel (File Tree View)
        self.tab_widget.currentChanged.connect(self.on_current_tab_changed)

        # Delay the execution of add_new_folder_explorer_tab until the GUI is loaded
        QTimer.singleShot(10, self.add_new_folder_explorer_tab)
        QTimer.singleShot(50, self.update_tool_enabled_state)
        # QTimer.singleShot(20, self.on_folder_explorer_selection_changed)
        # Initial discovery is owned by the explorer; avoid duplicate refreshes.

    def _create_status_bar(self) -> None:
        # Create Status Bar
        self.status_bar.setStyleSheet("QStatusBar { border-top: 1px solid #d8d8d8; }")

        self.setStatusBar(self.status_bar)
        # The current tab's activity, then app-wide I/O. The spinner keeps its
        # space when idle so the text does not shift.
        self.status_bar_spinner = QLabel()
        self.status_bar_spinner.setFixedSize(16, 16)
        self.status_bar_spinner_angle = 0
        self.status_bar.addWidget(self.status_bar_spinner)
        self.status_bar_message_left = ElidedLabel("...")
        self.status_bar.addWidget(self.status_bar_message_left, 1)
        self.status_bar_progress = QProgressBar()
        self.status_bar_progress.setFixedSize(120, min(16, self.status_bar_message_left.fontMetrics().height()))
        self.status_bar_progress.setTextVisible(False)
        self.status_bar_progress.hide()
        self.status_bar.addWidget(self.status_bar_progress)
        self.status_bar_message_right = QLabel(f"Please wait. GUI loading... v{APP_VERSION} ({APP_COMMIT_HASH})")
        self.status_bar_message_last_update = datetime.now()
        # A one-time notice shown before the tab's activity until it expires (monotonic time).
        self._status_notice: tuple[str, float] | None = None

        # Shown while folders' cached data doesn't match them; opens their list.
        self.mismatch_button = QToolButton()
        self.mismatch_button.setAutoRaise(True)
        self.mismatch_button.hide()
        self.status_bar.addPermanentWidget(self.mismatch_button)
        self.roots_button = QToolButton()
        self.roots_button.setAutoRaise(True)
        self.roots_button.hide()
        self.status_bar.addPermanentWidget(self.roots_button)
        # Shown from 50 % of the RAM budget (loaded folders and plots); opens their sizes.
        self.status_bar.addPermanentWidget(self.plots.ram_button)
        # Shown while Help › Record I/O trace is on.
        self.io_trace_label = QLabel("● I/O trace")
        self.io_trace_label.hide()
        self.status_bar.addPermanentWidget(self.io_trace_label)
        self.status_bar.addPermanentWidget(self.status_bar_message_right)
        self.status_bar_message_right.setToolTip("(App resource usage) / (system total resource usage)")

        # Setup a timer to update the status bar with thread status
        self.status_timer_thread_status = QTimer(self)
        self.status_timer_thread_status.timeout.connect(self.update_status_bar_left)
        self.status_timer_thread_status.start(self.INTERVAL_UPDATE_STATUS_BAR_LEFT)
        self.status_timer_threadpool_hang_counts = 0
        self.status_timer_threadpool_hang_timestamp: Optional[QDateTime] = None


        self.status_timer_cpu_ram = QTimer(self)
        self.status_timer_cpu_ram.timeout.connect(self.update_status_bar_right)
        self.status_timer_cpu_ram.start(self.INTERVAL_UPDATE_STATUS_BAR_RIGHT)
        # Deletes the old diskcache folders and expired cache files in a helper.
        get_folder_cache(get_io_service()).clean_up_cache()
        if cache_dir_refused():
            QTimer.singleShot(0, lambda: QMessageBox.warning(self, "Cache folder not used", cache_dir_refused()))

    def review_root(self, location: str | None) -> None:
        """Same folder or a copy?, at ``location``. From Settings (a modal dialog) the window is
        modal too, else it couldn't take input until Settings closed."""
        window = self.root_duplicates
        modal = QApplication.activeModalWidget()
        self._set_root_window_modality(Qt.WindowModality.ApplicationModal if modal is not None and modal is not window
                                       else Qt.WindowModality.NonModal)
        window.show_list(activate=True, select=location)

    def _set_root_window_modality(self, wanted: Qt.WindowModality) -> None:
        """Modality changes only while hidden; a window open stays open. NonModal again once
        Settings closes, so a later automatic sighting never blocks the main window."""
        window: RootDuplicatesWindow | None = getattr(self, "root_duplicates", None)
        if window is None or window.windowModality() == wanted:
            return
        shown = window.isVisible()
        window.hide()
        window.setWindowModality(wanted)
        if shown:
            window.show()

    def _place_root_target(self) -> tuple[FolderExplorer, str] | None:
        """The current tab and its selected folder (at first the tab's top folder)."""
        current = self.tab_widget.currentWidget()
        if not isinstance(current, FolderExplorer) or current.closed:
            return None
        return current, current.selected_path_globally or current.model_root_path

    def update_place_root_action(self) -> None:
        """File › Place .helab-root…: named for its folder, enabled as the tree's menu item would be."""
        target = self._place_root_target()
        if target is None:
            self.action_place_root.setText(PLACE_ROOT_MENU)
            self.action_place_root.setEnabled(False)
            self.action_place_root.setToolTip("Open a folder tab first")
            return
        explorer, path = target
        name = os.path.basename(path.rstrip("/\\")) or path  # A drive's top keeps its path, Z:\.
        if len(name) > 40:
            name = f"{name[:24]}…{name[-15:]}"
        enabled, tooltip = explorer.place_root_state(path)
        self.action_place_root.setText(f" Place .helab-root in “{name}”…")
        self.action_place_root.setEnabled(enabled)
        self.action_place_root.setToolTip(f"{path}\n{tooltip}")

    def place_root_in_current_tab(self) -> bool:
        """As the tree's Place .helab-root here… does, for the current tab's selected folder."""
        target = self._place_root_target()
        if target is None or not target[0].place_root_state(target[1])[0]:
            return False
        return target[0].place_root(target[1])

    def update_status_bar_left(self) -> None:
        if self._closing:
            return
        service = get_io_service()
        current = self.tab_widget.currentWidget()
        explorer = current if isinstance(current, FolderExplorer) else None
        # Short: this tab's main activity and app-wide counts; Folder details and the tooltip have the rest.
        tab = explorer.activity_brief if explorer else ""
        if self._status_notice is not None and time.monotonic() > self._status_notice[1]:
            self._status_notice = None
        notice = self._status_notice[0] if self._status_notice else ""
        app = service.activity_counts()
        self.status_bar_message_left.setText("  │  ".join(filter(None, (notice, tab, app))))
        # A load's tooltip already lists the queue and this tab's background loads.
        loading = bool(explorer and explorer.loading)
        summary = service.activity_summary()
        self.status_bar_message_left.setToolTip("\n\n".join(filter(None, (
            explorer.loading_tooltip if explorer and loading else "",
            explorer.activity_text if explorer else "",
            explorer.activity_tooltip if explorer and not loading else "",
            "" if summary == "Ready" else summary,
            "" if loading else service.queue_tooltip()))))
        busy = bool(explorer and explorer.activity_busy or service.active or service.pending or service.retired)
        self.status_bar_spinner_angle = (self.status_bar_spinner_angle + 30) % 360 if busy else 0
        self.status_bar_spinner.setPixmap(self._spinner_pixmap() if busy else QPixmap())
        # The selected load's progress; its counts are in the explorer's summary.
        self.status_bar_progress.setVisible(loading)
        if explorer and loading:
            if explorer.load_progress is None:
                self.status_bar_progress.setRange(0, 0)
            else:
                self.status_bar_progress.setRange(0, 100)
                self.status_bar_progress.setValue(round(explorer.load_progress * 100))
            self.status_bar_progress.setToolTip(explorer.loading_tooltip)
        self._update_cancel_loading_action()
        self.tab_widget.set_tab_switching_enable()
        self._update_live_action()
        self.status_bar_message_last_update = datetime.now()

    def _spinner_pixmap(self) -> QPixmap:
        ratio = self.status_bar_spinner.devicePixelRatioF()
        pixmap = QPixmap(round(16 * ratio), round(16 * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        paint_spinner(painter, QRect(3, 3, 10, 10), self.status_bar_spinner_angle, colors=IO_SPINNER)
        painter.end()
        return pixmap

    def update_status_bar_right(self) -> None:
        # Update the right message with CPU and RAM usage
        cpu_usage_app = self.process.cpu_percent()
        cpu_usage_total = sum(psutil.cpu_percent(percpu=True))
        ram_usage_app = self.process.memory_info().rss  # in bytes
        ram_usage_total = psutil.virtual_memory().used  # total used RAM in bytes
        ram_usage_app_gb = ram_usage_app / (1024 ** 3)
        ram_usage_total_gb = ram_usage_total / (1024 ** 3)

        # HeLab's own use; the system totals are in the tooltip.
        self.status_bar_message_right.setText(f"CPU {cpu_usage_app:.0f}% · RAM {ram_usage_app_gb:.1f} GB")
        self.status_bar_message_right.setToolTip(
            f"HeLab: CPU {cpu_usage_app:.1f}% · RAM {ram_usage_app_gb:.2f} GB\n"
            f"System: CPU {cpu_usage_total:.1f}% (summed over cores) · RAM {ram_usage_total_gb:.1f} GB used")

        # self.status_bar_message_right.setToolTip("(App resource usage) / (system total resource usage)")

    
    def create_menus(self) -> None:
        # Add menus and actions
        # 
        menu_file = self.menu_bar.addMenu('File')
        if menu_file is not None:
            # Create actions
            open_action = QAction(' Open', self)
            open_action.triggered.connect(self.open_folder_path_dialog)
            menu_file.addAction(open_action)

            if platform.system() == "Windows":
                self._drive_menu = QMenu("Open Drives", self)
                menu_file.addMenu(self._drive_menu)
                self._drive_owner = f"drives-{id(self)}"
                service = get_io_service()
                service.resultReady.connect(self._on_drive_result)
                QTimer.singleShot(0, lambda: service.submit(self._drive_owner, 0, "", "drives"))

            # The tab's top folder isn't a tree row (a drive's top can't be right-clicked): this
            # places one in the tab's selected folder, which starts as its top folder.
            self.action_place_root = QAction(PLACE_ROOT_MENU, self)
            self.action_place_root.setEnabled(False)  # Until the menu shows (aboutToShow).
            self.action_place_root.triggered.connect(self.place_root_in_current_tab)
            menu_file.addAction(self.action_place_root)
            menu_file.setToolTipsVisible(True)
            menu_file.aboutToShow.connect(self.update_place_root_action)

            menu_file.addSeparator()

            menu_file.addAction(self.action_tab_cancel)

            menu_file.addSeparator()

            menu_action_settings = QAction(' Settings...', self)
            menu_action_settings.triggered.connect(lambda: self.show_settings_dialog())
            menu_file.addAction(menu_action_settings)

            menu_file.addSeparator()

            exit_action = QAction(' Quit', self)
            exit_action.triggered.connect(self.close)
            menu_file.addAction(exit_action)
        else :
            logging.error("menu_file is None")

        menu_view = self.menu_bar.addMenu('View')
        if menu_view is not None:
            self.view_toggle_toolbar_left = QAction('Toggle Left Toolbar', self)
            self.view_toggle_toolbar_left.setCheckable(True)
            self.view_toggle_toolbar_left.setChecked(True)
            if (tv := self.sidebar_toolbar_left.toggleViewAction()): self.view_toggle_toolbar_left.triggered.connect(tv.trigger)
            # self.view_toggle_toolbar_left.triggered.connect(self.sidebar_toolbar_left.toggleViewAction().trigger)
            # self.view_toggle_toolbar_left.triggered.connect(lambda: self.toggle)
            menu_view.addAction(self.view_toggle_toolbar_left)

            self.view_toggle_toolbar_right = QAction('Toggle Right Toolbar', self)
            self.view_toggle_toolbar_right.setCheckable(True)
            self.view_toggle_toolbar_right.setChecked(True)
            if (tv := self.sidebar_toolbar_right.toggleViewAction()): self.view_toggle_toolbar_right.triggered.connect(tv.trigger)
            # view_toggle_toolbar_right.triggered.connect(self.sidebar_toolbar_right.toggleViewAction().trigger)
            menu_view.addAction(self.view_toggle_toolbar_right)

            menu_view.addSeparator()

            self.view_toggle_status_bar = QAction('Toggle Status Bar', self)
            self.view_toggle_status_bar.setCheckable(True)
            self.view_toggle_status_bar.setChecked(True)
            self.view_toggle_status_bar.triggered.connect(lambda: self.status_bar.setVisible(not self.status_bar.isVisible()))
            menu_view.addAction(self.view_toggle_status_bar)

            settings = app_settings()
            self.view_toggle_thread_status = QAction('Toggle Thread Status Auto Pop-up', self)
            self.view_toggle_thread_status.setCheckable(True)
            self.view_toggle_thread_status.setChecked(read_setting(settings, THREAD_STATUS_SETTING, typed=True))
            self.view_toggle_thread_status.triggered.connect(lambda checked: settings.setValue(THREAD_STATUS_SETTING, checked))
            menu_view.addAction(self.view_toggle_thread_status)

            menu_view.addSeparator()

            self.view_toggle_auto_scan_visible = QAction('Automatically Check Folder Status in View', self)
            self.view_toggle_auto_scan_visible.setCheckable(True)
            self.view_toggle_auto_scan_visible.setToolTip(
                "Scan visible folders that have no saved scan results; use Check folder status to recheck cached folders.")
            self.view_toggle_auto_scan_visible.setChecked(read_setting(settings, AUTO_SCAN_VISIBLE_SETTING, typed=True))
            self.view_toggle_auto_scan_visible.triggered.connect(self.set_auto_scan_visible)
            menu_view.addAction(self.view_toggle_auto_scan_visible)
            get_io_service().configure_concurrency(
                read_io_concurrency(settings))
            set_disk_budget(read_disk_budget(settings))
            get_folder_cache(get_io_service()).set_ram_budget(read_ram_budget(settings))
            get_folder_cache(get_io_service()).check_level = read_check_level(settings)
            self._apply_live_settings(settings)
            get_folder_cache(get_io_service()).set_lab_constants(read_lab_constants(settings))

            self.view_toggle_auto_load_ram = QAction('Toggle Auto Load to RAM', self)
            self.view_toggle_auto_load_ram.setCheckable(True)
            self.view_toggle_auto_load_ram.setChecked(True)
            self.view_toggle_auto_load_ram.triggered.connect(self.toggle_auto_load_ram)
            menu_view.addAction(self.view_toggle_auto_load_ram)

            menu_load_mode = menu_view.addMenu('When Selecting Another Folder')
            self.load_mode_group = QActionGroup(self)
            self.load_mode_actions: dict[str, QAction] = {}
            for mode, label in LOAD_MODE_LABELS.items():
                action = QAction(label, self)
                action.setCheckable(True)
                action.triggered.connect(lambda checked=False, m=mode: self.set_load_mode(m))
                self.load_mode_group.addAction(action)
                if menu_load_mode:
                    menu_load_mode.addAction(action)
                self.load_mode_actions[mode] = action
            # Tabs do not exist yet; new tabs take this mode when added.
            self.load_mode = read_load_mode(settings)
            self.load_mode_actions[self.load_mode].setChecked(True)

            menu_view.addSeparator()

            self.view_toggle_left_panel = QAction('Toggle Left Panel', self)
            self.view_toggle_left_panel.setCheckable(True)
            self.view_toggle_left_panel.setChecked(True)
            self.view_toggle_left_panel.triggered.connect(self.toggle_left_panel)
            menu_view.addAction(self.view_toggle_left_panel)

            self.view_toggle_right_panel = QAction('Toggle Right Panel', self)
            self.view_toggle_right_panel.setCheckable(True)
            self.view_toggle_right_panel.setChecked(True)
            self.view_toggle_right_panel.triggered.connect(self.toggle_right_panel)
            menu_view.addAction(self.view_toggle_right_panel)


        
        menu_debug = self.menu_bar.addMenu('Debug')
        if menu_debug is not None:
            debug_action_2 = QAction('Draw a line in debug console', self)
            debug_action_2.triggered.connect(lambda: logging.debug("="*80))

            menu_debug.addAction(debug_action_2)

            menu_debug.addSeparator()

            action_debug_icons = QAction("Show all Icons", self)
            action_debug_icons.triggered.connect(self.show_debug_icons_window)
            menu_debug.addAction(action_debug_icons)

            action_debug_memory_usage_window = QAction('Show Memory Usage', self)
            action_debug_memory_usage_window.triggered.connect(self.show_memory_usage_window)
            menu_debug.addAction(action_debug_memory_usage_window)

            menu_debug.addSeparator()

            action_debug_3 = QAction('Debug - validate tab status', self)
            action_debug_3.triggered.connect(self.action_debug_validate_tab_status)
            menu_debug.addAction(action_debug_3)


            action_debug_4 = QAction('Debug - show current visible rows', self)
            action_debug_4.triggered.connect(self.action_debug_show_current_visible_rows)
            menu_debug.addAction(action_debug_4)

            action_debug_gc_collect = QAction('gc.collect()', self)
            action_debug_gc_collect.triggered.connect(gc.collect)
            menu_debug.addAction(action_debug_gc_collect)

            action_debug_6 = QAction('Debug - 6', self)
            action_debug_6.triggered.connect(lambda: logging.debug("Debug action 6"))
            menu_debug.addAction(action_debug_6)



        else:
            logging.error("menu_debug is None")

        menu_help = self.menu_bar.addMenu("Help")
        if menu_help is not None:
            action_about = QAction("About HeLab", self)
            action_about.triggered.connect(self.show_about_dialog)
            menu_help.addAction(action_about)
            menu_help.addSeparator()
            # Off at every start and never saved.
            # The temp-folder check before the I/O trace starts (``trace_check``): its owner, and the
            # generation of the one waited for (None: none). Replaceable in tests: None asks with a
            # message box (``_ask_delete_old_traces``).
            self._trace_owner = f"io-trace-{id(self)}"
            self._trace_generation = 0
            self._trace_check: int | None = None
            self.ask_delete_old_traces: Callable[[int, int, str], bool] | None = None
            self.action_io_trace = QAction("Record I/O trace (this session)", self)
            self.action_io_trace.setCheckable(True)
            self.action_io_trace.setToolTip("Record every operation HeLab's helpers make on source folders "
                                            "(listings, stats, reads) in HeLab's temp folder, until turned off")
            self.action_io_trace.toggled.connect(self._toggle_io_trace)
            get_io_service().resultReady.connect(self._on_trace_check)
            menu_help.addAction(self.action_io_trace)
            action_trace_folder = QAction("Show I/O trace folder", self)
            action_trace_folder.triggered.connect(self._show_io_trace_folder)
            menu_help.addAction(action_trace_folder)

    def show_about_dialog(self) -> None:
        QMessageBox.about(self, "About HeLab", APP_BUILD_INFO.description())

    def _toggle_io_trace(self, on: bool) -> None:
        """Help › Record I/O trace (this session): a new recording folder in the temp folder's io-traces
        folder; earlier recordings are kept unless the user deletes them when asked. A local-lane helper
        checks the temp folder first (``trace_check``: its network/synced check reads the mount table,
        which can stall on a disconnected network drive), never the GUI thread; 10 s without an answer
        and the trace isn't started."""
        service = get_io_service()
        if not on:
            if self._trace_check is not None:
                self._trace_check = None
                service.cancel(self._trace_owner)
            service.stop_io_trace()
            self.io_trace_label.hide()
            return
        self._trace_generation += 1
        self._trace_check = self._trace_generation
        service.submit(self._trace_owner, self._trace_generation, DIR_TEMPS, "trace_check",
                       {"temps": DIR_TEMPS, "folder": io_trace_folder(DIR_TEMPS)}, timeout=10.0)

    def _on_trace_check(self, request: IORequest, event: dict[str, Any]) -> None:
        if (self._closing or request.owner != self._trace_owner or request.generation != self._trace_check
                or event["kind"] not in ("trace_folder", "error")):
            return
        self._trace_check = None
        if event["kind"] == "error":
            self._refuse_io_trace(f"HeLab couldn't check its temp folder {DIR_TEMPS}: {event.get('message', '')}")
            return
        if event["problem"]:
            self._refuse_io_trace(io_trace_refused(DIR_TEMPS, event["problem"]))
            return
        folder = io_trace_folder(DIR_TEMPS)
        earlier: list[dict[str, Any]] = event["earlier"]
        ask = self.ask_delete_old_traces or self._ask_delete_old_traces
        if earlier and ask(len(earlier), sum(int(recording["size"]) for recording in earlier), folder):
            # (Only earlier recordings: the new one doesn't exist yet.)
            if kept := delete_io_traces(earlier):
                QMessageBox.information(self, "I/O trace", (
                    f"{len(kept):,} trace file{'' if len(kept) == 1 else 's'} couldn't be deleted (still open by "
                    f"a running helper, or protected) and {'was' if len(kept) == 1 else 'were'} kept in {folder}."))
        if not self.action_io_trace.isChecked():
            return  # (Unticked while asked.)
        path = get_io_service().start_io_trace(DIR_TEMPS)
        self.io_trace_label.setToolTip(f"Recording the I/O trace in\n{path}\nHelp › Record I/O trace to stop.")
        self.io_trace_label.show()

    def _refuse_io_trace(self, reason: str) -> None:
        self.action_io_trace.blockSignals(True)
        self.action_io_trace.setChecked(False)
        self.action_io_trace.blockSignals(False)
        QMessageBox.warning(self, "I/O trace", f"The I/O trace isn't recorded. {reason}")

    def _ask_delete_old_traces(self, count: int, size: int, folder: str) -> bool:
        """Whether to delete the ``count`` earlier recordings (``size`` bytes; Keep is the default)."""
        box = QMessageBox(QMessageBox.Icon.Question, "I/O trace",
                          f"{count:,} earlier I/O trace{'' if count == 1 else 's'} "
                          f"({byte_size(size)}) in {folder}.", QMessageBox.StandardButton.NoButton, self)
        keep = box.addButton("Keep", QMessageBox.ButtonRole.RejectRole)
        delete = box.addButton("Delete old traces", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(keep)
        box.exec()
        return box.clickedButton() is delete

    def _show_io_trace_folder(self) -> None:
        from PyQt6.QtGui import QDesktopServices
        folder = io_trace_folder(DIR_TEMPS)
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _on_drive_result(self, request: IORequest, event: dict[str, Any]) -> None:
        if self._closing or request.owner != self._drive_owner or event["kind"] != "drives":
            return
        for path in event["paths"]:
            action = QAction(path, self)
            action.triggered.connect(lambda checked=False, p=path: self.add_new_folder_explorer_tab(target_path=p))
            self._drive_menu.addAction(action)

    def action_debug_validate_tab_status(self) -> None:
        logging.info("action_debug_validate_tab_status: called")
        logging.info(f"  {self.current_tracking_folder_path = }")
        logging.info(f"  {self.tab_widget.count() = }")
        logging.info(f"  {self.tab_widget.currentIndex() = }")
        ic = self.tab_widget.currentIndex()
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if isinstance(tab, FolderExplorer):
                ps = tab.selected_path_globally
                op = tab.folder_opened_path
                od = tab.folder_opened_data
                logging.info(f"  tab {i}: {ps = }, {op = }, {fnum(getsizeof(od)) = }B")
                assert_warn(ps == self.current_tracking_folder_path, f"tab {i} {ps = } != {self.current_tracking_folder_path = }")
                if i == ic:
                    assert_warn(op == self.current_tracking_folder_path, f"tab {i} {op = } != {self.current_tracking_folder_path = }")
                    assert_warn(ps == self.current_tracking_folder_path, f"tab {i} {ps = } != {self.current_tracking_folder_path = }")
                    assert_warn(od is not None, f"tab {i} {od = } is None")

            else:
                logging.warning(f"action_debug_validate_tab_status: tab {i} is not a FolderExplorer")

        pass

    def action_debug_show_current_visible_rows(self) -> None:
        current_file_explorer = self.tab_widget.currentWidget()
        if isinstance(current_file_explorer, FolderExplorer):
            logging.info(f"{current_file_explorer.model.rootPath() = }")
            rows = current_file_explorer.model.get_visible_rows()
            for r in rows:
                logging.info(f"{r = }")


    def show_settings_dialog(self, purge: bool = False) -> None:
        if self._closing or QApplication.activeModalWidget() is not None:
            return
        cache = get_folder_cache(get_io_service())
        self.settings_dialog = SettingsDialog(self, cache=cache)
        if (roots := getattr(self.settings_dialog, "roots_tab", None)) is not None:
            roots.reviewRequested.connect(self.review_root)
        if purge:
            self.settings_dialog.show_purge()
        self.settings_dialog.exec()
        self._set_root_window_modality(Qt.WindowModality.NonModal)  # Review… from Settings made it modal.
        settings = app_settings()
        self.apply_load_mode(read_load_mode(settings))
        get_io_service().configure_concurrency(
            read_io_concurrency(settings))
        cache.check_level = read_check_level(settings)
        self._apply_live_settings(settings)
        cache.set_lab_constants(read_lab_constants(settings))
        if read_disk_budget(settings) != store_options().get("budget"):
            # Saved without Save (e.g. Reset, then Cancel): the store is told until it has it.
            # (After Save it already has it: Settings saves a new disk budget only then.)
            set_disk_budget(read_disk_budget(settings))
            cache.sync_budget()
            # Saves waiting for an answer get room plans for the new budget.
            cache.cache_admin("inventory")
        cache.update_auto_load_pause()
        dropped = cache.set_ram_budget(read_ram_budget(settings))
        if dropped:
            size = sum(int(dataset.metadata.get("bytes", 0)) for dataset in dropped)
            self.show_status_notice(f"RAM budget lowered: dropped {len(dropped)} loaded "
                                    f"folder{'' if len(dropped) == 1 else 's'} ({byte_size(size)}) not shown in tabs")
        if (budget := self.plots.ram_budget) is not None:
            budget.auto_reload = read_plot_auto_reload(settings)
            budget.check()  # The plots' share of a new budget.
        self.apply_auto_scan_visible(read_setting(settings, AUTO_SCAN_VISIBLE_SETTING, typed=True))

    @staticmethod
    def _apply_live_settings(settings: QSettings) -> None:
        cache = get_folder_cache(get_io_service())
        cache.live_interval = read_live_interval(settings)
        cache.live_autosave_shots = read_live_autosave(settings)

    def show_status_notice(self, text: str, seconds: float = 10.0) -> None:
        self._status_notice = (text, time.monotonic() + seconds)
        self.update_status_bar_left()

    def _auto_load_pause_changed(self, paused: bool) -> None:
        cache = get_folder_cache(get_io_service())
        if not paused and not cache.disk_nearly_full():
            self.show_status_notice("Disk cache below 80% — automatic loading resumed")
        self._update_folder_details()

    def show_memory_usage_window(self) -> None:
        self.memory_usage_window = MemoryUsageWindow()
        self.memory_usage_window.show()

    def show_debug_icons_window(self) -> None:
        self.debug_icons_window = DebugIconsWindow()
        self.debug_icons_window.show()

    def open_folder_path_dialog(self) -> None:
        # Native file dialogs can themselves block on remote mount metadata.
        # Direct path entry and the asynchronous tree perform no GUI filesystem I/O.
        folder_path, accepted = QInputDialog.getText(self, "Open Folder", "Folder path:",
                                                   text=self.current_tracking_folder_path)
        if accepted and folder_path.strip():
            self.add_new_folder_explorer_tab(target_path=folder_path)

    def _setup_central_widgets(self) -> None:
        # Create the main horizontal splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self.splitter)
        self.splitter.setStyleSheet(QSPLITTER_STYLESHEET)

        self._setup_left_toolbar()
        self._setup_left_side()
        self._setup_middle_area()
        self._setup_right_side()


        # Set the initial sizes of the panels
        self.splitter.setSizes([
            self.left_panel_width,
            self.DEFAULT_WIDTH-self.left_panel_width-self.right_panel_width,
            self.right_panel_width
        ])


        # Make the left and right panels collapsible
        self.left_panel.setMinimumWidth(0)
        self.right_panel.setMinimumWidth(0)

        # Set stretch factors
        self.splitter.setStretchFactor(0, 1)  # Left panel
        self.splitter.setStretchFactor(1, 1)  # Middle area
        self.splitter.setStretchFactor(2, 1)  # Right panel

        self.splitter.splitterMoved.connect(self.on_splitter_moved)

    def _setup_left_toolbar(self) -> None:
        # Add a toolbar with a toggle button for the left panel
        self.sidebar_toolbar_left = QToolBar("Sidebar Toolbar Left", self)

        self.sidebar_toolbar_left.setMovable(False)
        self.sidebar_toolbar_left.setIconSize(QSize(24, 24))
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, self.sidebar_toolbar_left)
        self.sidebar_toolbar_right = QToolBar("Sidebar Toolbar Right", self)
        self.sidebar_toolbar_right.setIconSize(QSize(24, 24))
        self.sidebar_toolbar_right.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.RightToolBarArea, self.sidebar_toolbar_right)

        self.toggle_left_panel_action = QAction(ToolIcons.ICON_LEFT_COLLAPSE, "Toggle Left Panel", self)
        self.toggle_left_panel_action.setCheckable(True)
        self.toggle_left_panel_action.setChecked(True)
        self.toggle_left_panel_action.triggered.connect(self.toggle_left_panel)
        self.sidebar_toolbar_left.addAction(self.toggle_left_panel_action)

        # Left panel
        self.left_panel = QWidget()
        self.left_panel_width = 700  # Store the width of the left panel
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        # Create a splitter to hold the tab_widget and folder_details
        self.left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_layout.addWidget(self.left_splitter)
        self.left_panel.setLayout(left_layout)

        # Create and add the toolbar to the left panel
        # toolbar = QToolBar("Main Toolbar", self)
        # toolbar.setContentsMargins(0, 0, 0, 0)
        # toolbar.setIconSize(QSize(16, 16))
        # random_icon = QIcon(
        #     TablerIcons.load(OutlineIcon.SQUARE_ROUNDED_PLUS, color='000000')
        #     .toqpixmap()
        #     .scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        # )
        self.action_tab_new = QAction(ToolIcons.ICON_PLUS, "New Tab", self)
        self.action_tab_folder_up = QAction(ToolIcons.ICON_FOLDER_UP, "Up Dir", self)
        self.action_tab_refresh = QAction(ToolIcons.ICON_REFRESH, "Refresh", self)
        self.action_tab_rescan = QAction(ToolIcons.ICON_ZOOM_SCAN, "Check folder status", self)
        self.action_tab_rescan.setEnabled(False)
        self.action_tab_rescan.triggered.connect(self._check_folder_status_clicked)
        self.folder_status_menu = QMenu(self)
        self.folder_status_menu.addAction("Folders in view", lambda: self._check_folder_status("view"))
        self.folder_status_menu.addAction("Current folder", lambda: self._check_folder_status("current"))
        self.folder_status_menu.addAction("Recursive depth…", self._choose_folder_status_depth)
        self.folder_status_menu.addAction("All subfolders", lambda: self._check_folder_status("recursive", 32768))
        self.action_tab_cancel = QAction(ToolIcons.ICON_ZOOM_CANCEL, "Cancel Loading", self)
        self.action_tab_cancel.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        self.action_tab_cancel.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.action_tab_cancel.setAutoRepeat(False)
        self.action_tab_cancel.setEnabled(False)
        self.action_tab_cancel.triggered.connect(self._cancel_current_tab_loading)
        # Keep Esc available when the toolbar is hidden.
        self.addAction(self.action_tab_cancel)
        self.action_tab_live = QAction(ToolIcons.ICON_LIVE, "Live", self)
        self.action_tab_live.setCheckable(True)
        # Enabled for the current tab's selected folder once its data is shown (_update_live_action).
        self.action_tab_live.setEnabled(False)

        self.action_tab_new.setToolTip("New Tab")
        self.action_tab_new.setWhatsThis(
            "New Tab??? plz let me know if you see this text")  # literally don't know where this will show up memm
        # self.action_tab_new.set
        self.action_tab_refresh.setToolTip(
            "Refresh folder list\nUpdate folder names and expanded folders in view.\n"
            "Use Check folder status to update counts and status.")
        self.action_tab_folder_up.setToolTip("Navigate up one directory")
        self.action_tab_rescan.setToolTip(self.FOLDER_STATUS_TOOLTIP)
        self.action_tab_cancel.setToolTip("Cancel loading in this tab (Esc)")
        self.action_tab_live.setToolTip(
            "Live\nSelect a folder with loaded data, or with no shots yet, to watch it for new shots.")

        # action_tab_new.triggered.connect(self.add_new_folder_explorer_tab)
        # action_tab_folder_up.triggered.connect(self.on_back_button_clicked)

        # toolbar.addAction(action_tab_new)
        # toolbar.addAction(action_tab_refresh)
        # toolbar.addAction(action_tab_folder_up)
        self.sidebar_toolbar_left.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        self.sidebar_toolbar_left.setStyleSheet(TOOLBAR_STYLESHEET_LR)
        self.sidebar_toolbar_right.setStyleSheet(TOOLBAR_STYLESHEET_LR)
        # left_layout.addWidget(self.sidebar_toolbar_left)

        self.sidebar_toolbar_left.addAction(self.action_tab_new)
        self.sidebar_toolbar_left.addAction(self.action_tab_folder_up)
        self.sidebar_toolbar_left.addAction(self.action_tab_refresh)
        # Separate widgets keep both click targets and hover feedback independent
        # across native styles, without adding another toolbar column.
        status_control = QWidget(self.sidebar_toolbar_left)
        status_layout = QVBoxLayout(status_control)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(0)
        self.folder_status_button = QToolButton(status_control)
        self.folder_status_button.setAutoRaise(True)
        self.folder_status_button.setDefaultAction(self.action_tab_rescan)
        self.folder_status_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.folder_status_button.setIconSize(self.sidebar_toolbar_left.iconSize())
        up_button = self.sidebar_toolbar_left.widgetForAction(self.action_tab_folder_up)
        button_size = up_button.sizeHint() if up_button is not None else QSize(32, 32)
        self.folder_status_button.setFixedSize(button_size)
        self.folder_status_scope_button = HoverMenuToolButton(status_control)
        arrow_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "menu-right.svg")
        self.folder_status_scope_button.setIcon(QIcon(arrow_path))
        self.folder_status_scope_button.setIconSize(QSize(6, 8))
        self.folder_status_scope_button.setFixedSize(button_size.width(), 12)
        self.folder_status_scope_button.setMenu(self.folder_status_menu)
        self.folder_status_scope_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.folder_status_scope_button.setToolTip(
            "Choose folders to check\nHover or click to open the status check options.")
        self.folder_status_scope_button.setAccessibleName("Choose folders to check")
        self.action_tab_rescan.changed.connect(
            lambda: self.folder_status_scope_button.setEnabled(self.action_tab_rescan.isEnabled()))
        self.folder_status_scope_button.setEnabled(self.action_tab_rescan.isEnabled())
        status_layout.addWidget(self.folder_status_button)
        status_layout.addWidget(self.folder_status_scope_button)
        self.sidebar_toolbar_left.addWidget(status_control)
        self.sidebar_toolbar_left.addAction(self.action_tab_cancel)
        self.sidebar_toolbar_left.addAction(self.action_tab_live)

    def _setup_left_side(self) -> None:

        # Create the tab widget and add it to the left panel
        self.tab_widget = FolderTabWidget()
        # self.tab_widget.setTabsClosable(True)
        # self.tab_widget.tabCloseRequested.connect(self.tab_widget.removeTab)
        # left_layout.addWidget(self.tab_widget)
        self.left_splitter.addWidget(self.tab_widget)


        # action_tab_new.triggered.connect(self.tab_widget.add_new_folder_explorer_tab)
        # self.action_tab_new.triggered.connect(self.add_new_folder_explorer_tab)
        self.action_tab_new.triggered.connect(lambda _ : self.add_new_folder_explorer_tab())
        # action_tab_folder_up.triggered.connect(self.tab_widget.on_back_button_clicked)
        self.action_tab_folder_up.triggered.connect(self.on_back_button_clicked)
        self.action_tab_refresh.triggered.connect(self.tab_widget.refresh_current_folder_explorer)
        self.action_tab_folder_up.setEnabled(self.tab_widget.tab_back_button_enabled)
        self.action_tab_live.triggered.connect(self.on_live_button_clicked)

        self.sidebar_toolbar_left.addSeparator()

        # Add a spacer_left widget to push the toggle button to the bottom
        spacer_left = QWidget()
        spacer_left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.sidebar_toolbar_left.addWidget(spacer_left)

        self.sidebar_toolbar_left.addSeparator()

        action_settings = QAction(ToolIcons.ICON_SETTINGS, "Settings", self)
        action_settings.triggered.connect(self.show_settings_dialog)
        self.sidebar_toolbar_left.addAction(action_settings)

        self.sidebar_toolbar_left.addSeparator()

        # Add a button to the bottom of sidebar_toolbar_left
        self.toggle_folder_details_action = QAction(ToolIcons.ICON_BOTTOM_EXPAND, "Toggle Folder Details", self)
        self.toggle_folder_details_action.setCheckable(True)
        self.toggle_folder_details_action.setChecked(True)
        self.sidebar_toolbar_left.addAction(self.toggle_folder_details_action)
        self.toggle_folder_details_action.triggered.connect(self.toggle_folder_details)

        # Folder details below the tab_widget: the current tab's selected folder, load and I/O.
        self.folder_details = FolderDetailsPanel()
        self.folder_details.revealRequested.connect(self.reveal_load)
        self.folder_details.reviewRootRequested.connect(self.review_root)
        get_io_service().request_note = self._request_note
        self.folder_details.setVisible(True)
        self.left_splitter.addWidget(self.folder_details)
        self.left_splitter.setSizes([400, 170])  # Room for a load's Folder details rows.
        self.splitter.addWidget(self.left_panel)

    def _setup_right_side(self) -> None:
        self.toggle_right_panel_action = QAction(ToolIcons.ICON_RIGHT_COLLAPSE, "Toggle Right Panel", self)
        self.toggle_right_panel_action.setCheckable(True)
        self.toggle_right_panel_action.setChecked(True)
        self.toggle_right_panel_action.triggered.connect(self.toggle_right_panel)
        self.sidebar_toolbar_right.addAction(self.toggle_right_panel_action)
        spacer_right = QWidget()
        spacer_right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.sidebar_toolbar_right.addWidget(spacer_right)

        # Right panel
        self.right_panel = QWidget()
        self.right_panel_width = 500
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        # Placeholder content
        # right_layout.addWidget(QLabel("Right Panel Placeholder"))
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_layout.addWidget(self.right_splitter)
        self.right_panel.setLayout(right_layout)

        # right_top_widget = QLabel("Right Top Placeholder")
        # right_top_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.panel_right_bottom_script_selector = TreePanelWidget(self.plots)

        self.panel_right_bottom_script_selector.setVisible(True)
        # Add the bottom panel to the right_layout
        # Add a button to the bottom of sidebar_toolbar_right
        toggle_right_bottom_panel_action = QAction(ToolIcons.ICON_BOTTOM_EXPAND, "Toggle Right Bottom Panel", self)
        toggle_right_bottom_panel_action.setCheckable(True)
        toggle_right_bottom_panel_action.setChecked(True)
        toggle_right_bottom_panel_action.triggered.connect(self.toggle_right_bottom_panel)
        self.sidebar_toolbar_right.addAction(toggle_right_bottom_panel_action)

        self.right_splitter.addWidget(self.plots.panel_right_top_plot_settings)
        self.right_splitter.addWidget(self.panel_right_bottom_script_selector)
        self.right_splitter.setSizes([400, 300])

        # Add the right panel to the splitter
        self.splitter.addWidget(self.right_panel)


    def _setup_middle_area(self) -> None:
        # The plot area: its docks, hint, Settings panel, Live feed and RAM budget.
        self.plots = PlotWorkspace(self, current_explorer=self.current_explorer,
                                   explorers=lambda: [explorer for _, explorer in self._explorers()],
                                   notice=self.show_status_notice, show_settings=self.show_settings_dialog,
                                   closing=lambda: self._closing)
        # Desktop notifications without a system tray (helab/utils/events.py) go to the status bar.
        events.hub().desktop.set_status_sink(self.show_status_notice)


        self.central_placeholder_timer = QTimer(self)
        self.central_placeholder_timer.timeout.connect(self._update_folder_details)
        self.central_placeholder_timer.start(self.INTERVAL_UPDATE_CENTRAL_LOADING_INDICATOR)
        self.current_tracking_folder_path_is_loading: Optional[bool] = None
        """ True is loading, False is loaded, None is not loadable"""

        # Add the middle main window to the splitter
        self.splitter.addWidget(self.plots.middle_mainwindow)

        self.plots.update_placeholder_visibility()

    def _start_with_rhi_surface(self) -> None:
        """The 3D scatter's web view needs the window drawn through Qt's RHI; Qt switches a shown
        window by destroying and recreating it, so the whole window closed and reopened when
        the first such plot opened. A hidden QQuickWidget child, made before the window is
        shown, makes it start that way. macOS only until checked on the lab PCs, whose GPUs
        can't paint QtWebEngine (``needs_rhi_surface``)."""
        if HelabMainWindow.needs_rhi_surface():
            from PyQt6.QtQuickWidgets import QQuickWidget  # Loaded only where it is used.
            self._rhi_surface = QQuickWidget(self)
            self._rhi_surface.hide()

    @staticmethod
    def needs_rhi_surface(system: str = sys.platform, qpa: str | None = None) -> bool:
        """Whether the window starts with the hidden RHI surface: on macOS's own windows
        (Qt's cocoa platform) only. Nothing is made on Windows or Linux, nor offscreen (tests),
        where no window is recreated on screen."""
        if qpa is None:
            qpa = QGuiApplication.platformName()
        return system == "darwin" and qpa == "cocoa"

    def toggle_left_panel(self, checked: bool) -> None:
        if checked: # Expand the left panel
            # self.splitter.setSizes([self.left_panel_width, self.splitter.sizes()[1], self.splitter.sizes()[2]])
            self.splitter.setSizes([
                self.left_panel_width,
                # self.splitter.sizes()[1],
                self.width()-self.left_panel_width-self.right_panel_width,
                self.right_panel_width
            ])
            self.toggle_left_panel_action.setIcon(ToolIcons.ICON_LEFT_COLLAPSE)
            self.toggle_left_panel_action.setChecked(True)
            self.view_toggle_left_panel.setChecked(True)
        else: # Collapse the left panel
            self.left_panel_width = self.left_panel.width() if self.left_panel.width() > 600 else self.left_panel_width
            self.right_panel_width = self.right_panel.width() if self.right_panel.width() > 300 else self.right_panel_width
            self.splitter.setSizes([0, self.splitter.sizes()[1], self.splitter.sizes()[2]])
            self.toggle_left_panel_action.setIcon(ToolIcons.ICON_LEFT_EXPAND)
            self.toggle_left_panel_action.setChecked(False)
            self.view_toggle_left_panel.setChecked(False)


        # Update the bottom panel icon based on its visibility and the state of the left panel
        # if self.folder_details.isVisible():
        #     self.toggle_folder_details_action.setIcon(ToolIcons.ICON_BOTTOM_COLLAPSE)
        # else:
        if self.splitter.sizes()[0] == 0:  # Check if the left panel is hidden
            self.toggle_folder_details_action.setIcon(ToolIcons.ICON_BOTTOM_INACTIVE)
            self.toggle_folder_details_action.setChecked(False)
        else:
            if self.folder_details.isVisible():
                self.toggle_folder_details_action.setIcon(ToolIcons.ICON_BOTTOM_COLLAPSE)
                self.toggle_folder_details_action.setChecked(True)
            else:
                self.toggle_folder_details_action.setIcon(ToolIcons.ICON_BOTTOM_EXPAND)
                self.toggle_folder_details_action.setChecked(False)

    def on_splitter_moved(self, pos: int, index: int) -> None:
        # Update the left panel width when the splitter is moved
        # self.left_panel_width = self.splitter.sizes()[0]
        # self.right_panel_width = self.splitter.sizes()[2]
        logging.debug(f"on_splitter_moved: {pos = }, {index = }, {self.splitter.sizes() = }")

        if self.splitter.sizes()[0] == 0:  # Check if the left panel is hidden
            self.toggle_left_panel_action.setIcon(ToolIcons.ICON_LEFT_EXPAND)
            self.toggle_left_panel_action.setChecked(False)
            self.toggle_folder_details_action.setIcon(ToolIcons.ICON_BOTTOM_INACTIVE)
            self.toggle_folder_details_action.setChecked(False)
            self.view_toggle_left_panel.setChecked(False)
        else:
            self.toggle_left_panel_action.setIcon(ToolIcons.ICON_LEFT_COLLAPSE)
            self.toggle_left_panel_action.setChecked(True)
            self.view_toggle_left_panel.setChecked(True)
            if self.folder_details.isVisible():
                self.toggle_folder_details_action.setIcon(ToolIcons.ICON_BOTTOM_COLLAPSE)
                self.toggle_folder_details_action.setChecked(True)
            else:
                self.toggle_folder_details_action.setIcon(ToolIcons.ICON_BOTTOM_EXPAND)
                self.toggle_folder_details_action.setChecked(False)

    def toggle_folder_details(self, checked: bool) -> None:
        if checked:
            self.folder_details.setVisible(True)
            self._update_folder_details()  # Skipped while hidden, so it may be stale.
            self.toggle_folder_details_action.setIcon(ToolIcons.ICON_BOTTOM_COLLAPSE)

        else:
            self.folder_details.setVisible(False)
            if self.splitter.sizes()[0] == 0:  # Check if the left panel is hidden
                self.toggle_folder_details_action.setIcon(ToolIcons.ICON_BOTTOM_INACTIVE)
            else:
                self.toggle_folder_details_action.setIcon(ToolIcons.ICON_BOTTOM_EXPAND)

    # def enterEvent(self, a0):
    #     # Display the tooltip immediately when mouse enters the widget area
    #     QToolTip.showText(a0.globalPosition().toPoint(), self.toolTip(), self, self.rect())
    #     super().enterEvent(a0)

    def toggle_right_panel(self, checked: bool) -> None:
        if checked:
            self.splitter.setSizes([
                self.splitter.sizes()[0],
                self.width()-self.left_panel_width-self.right_panel_width,
                self.right_panel_width
            ])
            self.sidebar_toolbar_right.actions()[0].setIcon(ToolIcons.ICON_RIGHT_COLLAPSE)
            self.toggle_right_panel_action.setChecked(True)
            self.view_toggle_right_panel.setChecked(True)
        else:
            self.right_panel_width = self.right_panel.width() if self.right_panel.width() > 300 else self.right_panel_width
            self.splitter.setSizes([
                self.splitter.sizes()[0],
                self.width()-self.left_panel_width,
                0
            ])
            self.sidebar_toolbar_right.actions()[0].setIcon(ToolIcons.ICON_RIGHT_EXPAND)
            self.toggle_right_panel_action.setChecked(False)
            self.view_toggle_right_panel.setChecked(False)

    def toggle_right_bottom_panel(self, checked: bool) -> None:
        if checked:
            self.panel_right_bottom_script_selector.setVisible(True)
            self.sidebar_toolbar_right.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_COLLAPSE)
        else:
            self.panel_right_bottom_script_selector.setVisible(False)
            self.sidebar_toolbar_right.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_EXPAND)

    def on_back_button_clicked(self) -> None:
        self.tab_widget.on_back_button_clicked()
        logging.info(f"heLabMainWindow.on_back_button_clicked: {self.tab_widget.tab_back_button_enabled = }")
        self.action_tab_folder_up.setEnabled(self.tab_widget.tab_back_button_enabled)

    def on_current_tab_changed(self, index: int) -> None:
        # self.tab_widget.on_current_tab_changed(index)
        logging.debug(f"helabMainWindow.on_current_tab_changed: to index {index}")
        # self.action_tab_folder_up.setEnabled(self.tab_widget.tab_back_button_enabled)
        self.update_tool_enabled_state()
        current_folder_explorer = self.tab_widget.currentWidget()
        for _, explorer in self._explorers():
            if explorer is not current_folder_explorer and explorer.live is not None:
                explorer.stop_live()  # Switching tabs turns Live off; its new shots are saved.
        self._update_live_action()
        if isinstance(current_folder_explorer, FolderExplorer):
            # selection_model = current_folder_explorer.get_selection_model()
            # Connect the selectionChanged signal to the slot
            # selection_model.selectionChanged.connect(self.on_folder_explorer_selection_changed)
            current_folder_explorer.emit_selection_changed()
            # self.on_folder_explorer_selection_changed(current_folder_explorer.get_selection_model().selection())


    def on_folder_explorer_selection_changed(self, selected: QItemSelection,
                                             explorer: FolderExplorer | None = None) -> None:
        if explorer is None:
            current = self.tab_widget.currentWidget()
            if not isinstance(current, FolderExplorer):
                return
            explorer = current
        if not isinstance(explorer, FolderExplorer) or explorer.closed or self._closing:
            return
        path = explorer.selected_path_globally
        if explorer is self.tab_widget.currentWidget():
            self.current_tracking_folder_path = path
            self.setWindowTitle(f"HeLab — {os.path.basename(path.rstrip(os.sep)) or path}")
        if self.view_toggle_auto_load_ram.isChecked():
            explorer.load_to_ram_cache(path)
        self._update_folder_details()

    def _snapshot_data_loaded(self, explorer: FolderExplorer, path: str) -> None:
        if self.tab_widget.currentWidget() is explorer and path == explorer.selected_path_globally:
            self.current_tracking_folder_path_is_loading = False
            self._update_folder_details()
            self.plots.update_placeholder_visibility()

    def _update_roots_button(self) -> None:
        count = len(get_folder_cache(get_io_service()).root_duplicates)
        self.roots_button.setText(f"⚓ {count:,} to confirm")
        self.roots_button.setToolTip(
            f"{count:,} location{'' if count == 1 else 's'} whose .helab-root is also elsewhere: say whether "
            "each is the same folder or a copy (RAM only until then). Click to see the list.")
        self.roots_button.setVisible(bool(count))

    def _update_mismatch_button(self) -> None:
        cache = get_folder_cache(get_io_service())
        count = len(cache.mismatched)
        held = cache.service.mismatch_hold
        self.mismatch_button.setText(f"⚠ {count:,} mismatched" + (" · loads paused" if held else ""))
        self.mismatch_button.setToolTip(
            f"Cached data doesn't match {count:,} folder{'' if count == 1 else 's'}"
            + (": loads and scans are paused until you answer" if held else "") + ". Click to see the list.")
        self.mismatch_button.setVisible(bool(count) or held)

    def _load_mismatched(self, paths: list[str]) -> None:
        """Load the chosen mismatched folders as they are now, from the current tab."""
        current = self.tab_widget.currentWidget()
        if not isinstance(current, FolderExplorer):
            get_folder_cache(get_io_service()).answer_mismatches(paths, "load")  # Their next load does.
            return
        for path in paths:
            current.load_as_it_is_now(path)

    def current_explorer(self) -> FolderExplorer | None:
        """The current tab's folder browser (None: no tab, or another kind)."""
        current = self.tab_widget.currentWidget()
        return current if isinstance(current, FolderExplorer) else None

    def _explorers(self) -> list[tuple[int, FolderExplorer]]:
        return [(index, widget) for index in range(self.tab_widget.count())
                if isinstance(widget := self.tab_widget.widget(index), FolderExplorer)]

    def _load_tabs(self, producer: IORequest) -> tuple[list[tuple[int, FolderExplorer]], str]:
        """The tabs a running load is for (in tab order), and its progress note."""
        owners, note = get_folder_cache(get_io_service()).load_note(producer)
        tabs = [(index, explorer) for index, explorer in self._explorers()
                if {explorer.model.owner, explorer.bg_owner, explorer.live_owner, explorer.live_save_owner} & set(owners)]
        return tabs, note

    def _request_note(self, request: IORequest) -> str:
        """For the I/O tooltip: a load's tab(s), progress, current file and time (memory only)."""
        tabs, note = self._load_tabs(request)
        names = ", ".join(f'"{self.tab_widget.tabText(index)}"' for index, _ in tabs)
        return " · ".join(filter(None, (f"tab {names}" if names else "", note)))

    def reveal_load(self, producer_owner: str, path: str) -> None:
        """Folder details' All I/O row was clicked: show that load's folder in its tab."""
        request = next((r for r in get_io_service().running_loads() if r.owner == producer_owner), None)
        tabs = self._load_tabs(request)[0] if request is not None else []
        if not tabs:
            return
        index, explorer = next(((i, e) for i, e in tabs if i == self.tab_widget.currentIndex()), tabs[0])
        self.tab_widget.setCurrentIndex(index)
        explorer.reveal(path)

    def _update_folder_details(self) -> None:
        """Folder details, the plot area's hint and the plot docks' source labels (memory only)."""
        if self._closing:
            return
        current = self.tab_widget.currentWidget()
        explorer = current if isinstance(current, FolderExplorer) else None
        if not self.folder_details.isHidden():
            self.folder_details.show_explorer(explorer, explorer.model.service if explorer else None)
        if explorer is None:
            self.plots.central_placeholder.set_hint("Select a data folder to begin")
            return
        for dock in self.plots.dock_widgets:
            PlotWorkspace._update_plot_source_label(dock, explorer)
        self.current_tracking_folder_path_is_loading = explorer.loading
        self.plots.central_placeholder.set_hint(*HelabMainWindow.central_hint(explorer))

    @staticmethod
    def central_hint(explorer: FolderExplorer) -> tuple[str, str]:
        """One line for the plot area; the details are in Folder details."""
        path = explorer.selected_path_globally
        name = os.path.basename(path.rstrip(os.sep)) or path
        dataset = explorer.displayed_dataset
        shown = dataset is not None and dataset.path == path
        if explorer.loading and explorer.load_path == path:
            text = (f"Queued {name}…" if explorer.load_queued else
                    f"{'Check' if explorer.load_is_check else 'Loading'} paused: {name}…" if explorer.load_paused else
                    f"Checking {name} for changes…" if explorer.load_is_check else f"Loading {name}…")
            return text, explorer.loading_tooltip
        if explorer.live is not None:
            live = explorer.live
            return ((f"Live stopped: {name} — Retry in the folder summary", live.error) if live.error else
                    (f"Live: watching {name} · " + (f"{live.new:,} new shot{'' if live.new == 1 else 's'}"
                                                     if live.shots else "waiting for the first shot"), ""))
        if explorer.load_error:
            verb = "check" if explorer.shows_unchecked(path) else "load"
            return f"Could not {verb} {name} — see Folder details", explorer.load_error
        if explorer.load_waiting:
            return f"Waiting to load {name}…", ""
        if explorer.auto_load_paused_path == path and not shown:
            return f"{name}: {AUTO_LOAD_PAUSED[0].lower()}{AUTO_LOAD_PAUSED[1:]} — right-click it › Load data", \
                AUTO_LOAD_PAUSED_TOOLTIP
        if explorer.auto_load_off(path) and not shown:
            return f"{name}: auto-load off for this folder — right-click it › Load data", AUTO_LOAD_OFF_TOOLTIP
        if (large := explorer.large_state(path)) is not None and not shown:
            text = large_text(*large)
            return (f"{name}: {text[0].lower()}{text[1:]}" + ("" if large[1] else " — Load anyway… asks first"),
                    REFUSED_TOOLTIP if large[1] else LARGE_TOOLTIP)
        if explorer.folder_opened_path == path:
            return f"Loaded {name} — run a script to plot it", ""
        if shown:
            return f"Showing previous data for {name} — see Folder details", ""
        node = explorer.model.nodes.get(path)
        if node is not None and node.report is not None and not node.error and not explorer.scan_message:
            if node.txy_count or node.report.d_txy_shots:
                return f"{name} is not loaded — right-click it › Load data", ""
            return f"No TXY files in {name} — select a data folder", ""
        return "Select a data folder to begin", ""

    def add_new_folder_explorer_tab(self,
                                    model_root_path: str|None = None,
                                    view_path: str|None = None,
                                    target_path: str|None = None,
                                    set_initial_expand_to_parent_level:bool = True,
                                    ) -> None:
        if self._closing:
            return
        logging.debug(f"helabMainWindow.add_new_folder_explorer_tab: {model_root_path = }, {view_path = }, {target_path = }, {set_initial_expand_to_parent_level = }")
        self.tab_widget.add_new_folder_explorer_tab(
            model_root_path = model_root_path,
            view_path = view_path,
            target_path = target_path,
            set_initial_expand_to_parent_level = set_initial_expand_to_parent_level,
        )
        self.update_tool_enabled_state()
        current_folder_explorer = self.tab_widget.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.auto_load_ram = self.view_toggle_auto_load_ram.isChecked()
            current_folder_explorer.load_mode = self.load_mode
            current_folder_explorer.set_auto_scan_visible(self.view_toggle_auto_scan_visible.isChecked())
            current_folder_explorer.rootPathChanged.connect(self.update_tool_enabled_state)
            logging.debug(f"add_new_folder_explorer_tab: {current_folder_explorer.selected_path_globally = }")
            current_folder_explorer.selectionPathChanged.connect(
                lambda _, fe=current_folder_explorer: self.on_folder_explorer_selection_changed(QItemSelection(), fe))
            current_folder_explorer.reviewMismatchRequested.connect(
                lambda path: self.missing_shots.show_list(activate=True, select=path))
            current_folder_explorer.reviewRootRequested.connect(self.review_root)
            current_folder_explorer.loadStateChanged.connect(self._update_folder_details)
            current_folder_explorer.loadStateChanged.connect(self._update_cancel_loading_action)
            current_folder_explorer.liveChanged.connect(self._update_live_action)
            current_folder_explorer.liveChanged.connect(lambda fe=current_folder_explorer: self.plots.follow_live(fe))
            current_folder_explorer.dataLoaded.connect(lambda _, fe=current_folder_explorer: self.plots.follow_live(fe))
            current_folder_explorer.dataLoaded.connect(
                lambda p, fe=current_folder_explorer: self._snapshot_data_loaded(fe, p))
        else:
            logging.error("add_new_folder_explorer_tab: current_folder_explorer is not FolderExplorer")

    def _cancel_current_tab_loading(self) -> None:
        if QApplication.activeModalWidget() is not None:
            return
        explorer = self.tab_widget.currentWidget()
        if isinstance(explorer, FolderExplorer):
            explorer.cancel_loading()
        self._update_cancel_loading_action()

    def _update_cancel_loading_action(self) -> None:
        explorer = self.tab_widget.currentWidget()
        self.action_tab_cancel.setEnabled(
            isinstance(explorer, FolderExplorer) and explorer.can_cancel_loading)
        self._update_folder_status_action()

    def _check_folder_status_clicked(self) -> None:
        explorer = self.tab_widget.currentWidget()
        if isinstance(explorer, FolderExplorer) and explorer._basic_active:
            explorer.cancel_basic_scan()
            self._update_folder_status_action()
        else:
            self._check_folder_status("view")

    def _check_folder_status(self, scope: str, depth: int = 0) -> None:
        explorer = self.tab_widget.currentWidget()
        if isinstance(explorer, FolderExplorer) and not explorer.closed:
            explorer.start_basic_scan(scope, depth)
        self._update_folder_status_action()

    def _choose_folder_status_depth(self) -> None:
        explorer = self.tab_widget.currentWidget()
        if isinstance(explorer, FolderExplorer) and not explorer.closed:
            explorer._choose_scan_depth()
        self._update_folder_status_action()

    def _update_folder_status_action(self) -> None:
        explorer = self.tab_widget.currentWidget()
        # Live locks the tab's folder tree: no status checks of it meanwhile.
        available = isinstance(explorer, FolderExplorer) and not explorer.closed and explorer.live is None
        active = isinstance(explorer, FolderExplorer) and not explorer.closed and explorer._basic_active
        self.action_tab_rescan.setEnabled(available)
        title = "Cancel check" if active else "Check folder status"
        if self.action_tab_rescan.text() != title:
            self.action_tab_rescan.setText(title)
            self.action_tab_rescan.setIcon(ToolIcons.ICON_ZOOM_CANCEL if active else ToolIcons.ICON_ZOOM_SCAN)
            self.action_tab_rescan.setToolTip(
                "Cancel check\nCancel this tab's folder status check.\n"
                "Arrow below: choose which folders to check."
                if active else self.FOLDER_STATUS_TOOLTIP)
        self.folder_status_menu.setEnabled(available)

    def update_tool_enabled_state(self) -> None:
        self._update_cancel_loading_action()
        current_folder_explorer = self.tab_widget.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.update_back_button_state()
            self.action_tab_folder_up.setEnabled(current_folder_explorer.back_button_enabled
                                                 and current_folder_explorer.live is None)
        else:
            self.action_tab_folder_up.setEnabled(False)

    def set_tools_and_tabs_enable(self) -> None:
        # logging.debug("set_tools_and_tabs_enable")
        self.action_tab_new.setEnabled(True)
        # self.action_tab_folder_up.setEnabled(True)
        self.action_tab_refresh.setEnabled(True)
        self.action_tab_rescan.setEnabled(True)
        self.update_tool_enabled_state()

    def set_tools_and_tabs_disable(self) -> None:
        # logging.debug("set_tools_and_tabs_disable")
        # self.action_tab_new.setEnabled(False)
        # self.action_tab_folder_up.setEnabled(False)
        self.action_tab_refresh.setEnabled(False)
        self.action_tab_rescan.setEnabled(False)

    def on_live_button_clicked(self) -> None:
        """Live on or off for the current tab's selected folder (roadmaps/live-monitoring.md)."""
        explorer = self.tab_widget.currentWidget()
        if isinstance(explorer, FolderExplorer) and not explorer.closed:
            if explorer.live is not None:
                explorer.stop_live()
            elif not explorer.start_live():
                self.show_status_notice(explorer.live_unavailable(explorer.selected_path_globally)
                                        or "Live couldn't start")
        self._update_live_action()

    def _update_live_action(self) -> None:
        """The toolbar's Live follows the current tab. While it is on, the tab's folder tree is
        locked, and so are Up, Refresh and Check folder status; switching tabs turns it off."""
        if self._closing:
            return
        current = self.tab_widget.currentWidget()
        explorer = current if isinstance(current, FolderExplorer) and not current.closed else None
        enabled, tooltip = explorer.live_state() if explorer is not None else (False, "Live\nOpen a folder tab first.")
        live = explorer is not None and explorer.live is not None
        self.action_tab_live.setEnabled(enabled)
        self.action_tab_live.setChecked(live)
        if self.action_tab_live.toolTip() != tooltip:
            self.action_tab_live.setToolTip(tooltip)
        if live:
            self.set_tools_and_tabs_disable()
            self.action_tab_folder_up.setEnabled(False)
        else:
            self.set_tools_and_tabs_enable()

    def set_load_mode(self, mode: str) -> None:
        app_settings().setValue(LOAD_MODE_SETTING, mode)
        self.apply_load_mode(mode)

    def apply_load_mode(self, mode: str) -> None:
        self.load_mode = mode if mode in LOAD_MODE_LABELS else DEFAULT_LOAD_MODE
        self.load_mode_actions[self.load_mode].setChecked(True)
        for index in range(self.tab_widget.count()):
            explorer = self.tab_widget.widget(index)
            if isinstance(explorer, FolderExplorer):
                explorer.load_mode = self.load_mode

    def toggle_auto_load_ram(self) -> None:
        toggled_on = self.view_toggle_auto_load_ram.isChecked()
        logging.debug(f"toggle_auto_load_ram: called {toggled_on = }")
        for index in range(self.tab_widget.count()):
            explorer = self.tab_widget.widget(index)
            if isinstance(explorer, FolderExplorer):
                explorer.auto_load_ram = toggled_on

    def set_auto_scan_visible(self, enabled: bool) -> None:
        app_settings().setValue(AUTO_SCAN_VISIBLE_SETTING, enabled)
        self.apply_auto_scan_visible(enabled)

    def apply_auto_scan_visible(self, enabled: bool) -> None:
        self.view_toggle_auto_scan_visible.setChecked(enabled)
        for index in range(self.tab_widget.count()):
            explorer = self.tab_widget.widget(index)
            if isinstance(explorer, FolderExplorer):
                explorer.set_auto_scan_visible(enabled)

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        if self._closing:
            if a0 is not None:
                a0.accept()
            return
        if self._quit_dialog is not None or (not self._quit_now and self._wait_for_saves()):
            # The quit window decides: when the saves end, or Quit now.
            if a0 is not None:
                a0.ignore()
            return
        self._closing = True
        self.plots.close_plots()
        self.plots.detach()  # The RAM budget, then the Settings panel.
        if not self._cache_dialogs_detached:
            self.cache_dialogs.detach()
        self.watchdog.stop()
        for timer in self.findChildren(QTimer):
            timer.stop()
        self.tab_widget.closeEvent(None)
        get_io_service().shutdown()
        # Local file cleanup never waits in the GUI.
        def cleanup() -> None:
            for temp_file in self.named_temp_files:
                temp_file.close()
                try:
                    os.remove(temp_file.name)
                except OSError:
                    pass
        threading.Thread(target=cleanup, daemon=True, name="HeLab-shutdown").start()
        if a0 is not None:
            a0.accept()
        QApplication.quit()

    def _wait_for_saves(self) -> bool:
        """Quitting turns Live off (it never survives a restart), which saves its new shots. If
        any folder is being saved to the disk cache (that, or a finished load's background save),
        a window names them and quitting waits, with Quit now. Whether it waits."""
        for _, explorer in self._explorers():
            explorer.stop_live()
        cache = get_folder_cache(get_io_service())
        if not cache.quit_saves():
            return False
        # Nothing else will be shown: the saves get the I/O. The cache's questions (Make room,
        # Save update) wait for the next session.
        cache.cancel_for_quit()
        self.cache_dialogs.detach()
        self._cache_dialogs_detached = True
        self._quit_dialog = QuitSaveDialog(cache, self)
        self._quit_dialog.finished.connect(self._quit_after_saves)
        self._quit_dialog.open()
        return True

    def _quit_after_saves(self, result: int) -> None:
        """The saves ended (or Quit now): quit."""
        self._quit_dialog = None
        self._quit_now = True
        QTimer.singleShot(0, self.close)

    def handle_exit(self, signum: int, frame: Optional[types.FrameType]) -> None:
        # self.closeEvent(None)
        logging.info("handle_exit: called")
        self.close()
