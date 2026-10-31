import gc
import json
import logging
import os
import platform
import re
import signal
import sys
import types
import time
from helab.utils.accessible import id_part, identify, identify_action, identify_buttons
from helab.utils.io_service import IORequest, delete_io_traces, get_io_service, io_trace_folder, io_trace_refused
from helab.utils.folder_cache import OFFLINE_TOOLTIP, get_folder_cache, set_disk_budget, store_options
from helab.utils.gui_watchdog import GUIWatchdog
from helab.utils.lab_parameters import read_lab_constants
from helab.utils import app_log, events
from datetime import datetime
from typing import Any, Callable, Optional

import psutil
from PyQt6 import sip
from PyQt6.QtCore import Qt, QSize, QTimer, QItemSelection, QUrl, QDateTime, QSettings, QRect
from PyQt6.QtGui import QAction, QActionGroup, QIcon, QCloseEvent, QGuiApplication, QPainter, QPixmap, QKeySequence, QShowEvent
from PyQt6.QtWidgets import QMainWindow, QStatusBar, QMenuBar, QWidget, QVBoxLayout, QSplitter, \
    QLabel, QToolBar, QSizePolicy, QMenu, QApplication, QInputDialog, QProgressBar, QToolButton, QMessageBox, \
    QDockWidget, QFileDialog, QPushButton

from helab.views.plots.arrangement import PlotReopen
from helab.views.plots.presets import ArrangementPresets
from helab.views.PresetsInspector import set_script_finder
from helab.views.plots.script_tree import TreePanelWidget
from helab.views.plots.workspace import PlotWorkspace
from helab.resources.icons import ToolIcons
from helab.utils.constants import (
    APP_BUILD_INFO, APP_COMMIT_HASH, APP_VERSION, DEFAULT_LOAD_MODE, DIR_TEMPS, LOAD_MODE_LABELS,
    QSPLITTER_STYLESHEET, TOOLBAR_STYLESHEET_LR, cache_dir_refused, read_check_level,
    read_disk_budget, read_io_concurrency, read_live_autosave, read_live_interval, read_load_mode,
    app_folder, read_convert_profile, read_plot_auto_reload, read_ram_budget, read_txy_source,
)
from helab.utils.number_format import byte_size, byte_unit
from helab.utils.settings_defaults import (
    AUTO_SCAN_VISIBLE_SETTING, LOAD_MODE_SETTING, MAIN_SPLIT_SETTING, WORK_OFFLINE_SETTING, read_setting,
    setting_default)
from helab.utils.settings_store import app_settings
from helab.views.CacheDialogs import CacheDialogs
from helab.views.CacheTab import read_result_reuse
from helab.views.ClockSkewWarning import ClockSkewWarning
from helab.views.OldLogs import OldLogs
from helab.views.ElidedLabel import ElidedLabel
from helab.views.FolderDetailsPanel import FolderDetailsPanel
from helab.views.HoverMenuToolButton import HoverMenuToolButton
from helab.views.FolderExplorer import (
    AUTO_LOAD_OFF_TOOLTIP, AUTO_LOAD_PAUSED, AUTO_LOAD_PAUSED_TOOLTIP, LARGE_TOOLTIP, REFUSED_TOOLTIP,
    IO_SPINNER, FolderExplorer, paint_spinner,
)
from helab.views.explorer_text import large_text
from helab.views.FolderTabWidget import FolderTabWidget
from helab.views import live_launch, state_dump
from helab.views.MemoryUsageWindow import MemoryUsageWindow
from helab.views.MissingShotsWindow import MissingShotsWindow
from helab.views.QuitSaveDialog import QuitSaveDialog
from helab.views.RootDuplicatesWindow import RootDuplicatesWindow
from helab.views.SettingsDialog import SettingsDialog, read_settle_seconds
from helab.views.DebugIconsWindow import DebugIconsWindow

# QtWebEngine must be imported before the QApplication exists; main.py imports this module first.
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401

PLACE_ROOT_MENU = " Place .helab-root…"

# Work Offline (cache-only browsing; Tony named it, 2026-10-26: D2).
WORK_OFFLINE_TOOLTIP = ("Browse and analyse cached data only: HeLab reads no source folder and no server until you "
                        "turn this off. Remembered at the next start.")
OFFLINE_STATUS = "Offline · cached data only"
OFFLINE_STATUS_TOOLTIP = ("Working offline (File › Work Offline): folders show what was saved when they were last "
                          "listed, checked or loaded. Click to work online.")
REFRESH_TOOLTIP = ("Refresh folder list\nUpdate folder names and expanded folders in view.\n"
                   "Use Check folder status to update counts and status.")


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
        # Work Offline is remembered (D2): on from the start, before any tab lists a folder.
        cache.offlineChanged.connect(self._offline_changed)
        if read_setting(app_settings(), WORK_OFFLINE_SETTING, typed=True):
            cache.set_offline(True)
        self._offline_changed(cache.offline)
        self.cache_dialogs = CacheDialogs(cache, self, lambda: self.show_settings_dialog(purge=True),
                                          self.show_status_notice)
        # A folder's files dated ahead of this computer's clock: once per share or volume per session.
        self.clock_skew_warning = ClockSkewWarning(cache, self)
        # Old log files: tidied once at startup (``main`` calls its ``start``), off the GUI thread.
        self.old_logs = OldLogs(app_folder(), self)
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
        # The plots open last time reopen at start (Settings → General), after the first tab
        # opens; recorded as plots open and close, and at quit. Presets of a folder and its plots.
        self.plot_reopen = PlotReopen(self.plots, self.panel_right_bottom_script_selector)
        self.arrangement_presets = ArrangementPresets(self.plots, self.panel_right_bottom_script_selector,
                                                      self.current_explorer, self, cache)
        self.menu_presets.aboutToShow.connect(lambda: self.arrangement_presets.fill_menu(self.menu_presets))
        self.arrangement_presets.fill_menu(self.menu_presets, read=False)  # (It has asked for them.)
        set_script_finder(self.panel_right_bottom_script_selector.find_script)  # Settings → Cache › Presets…

        # Create Left Panel (File Tree View)
        self.tab_widget.currentChanged.connect(self.on_current_tab_changed)

        # Delay the execution of add_new_folder_explorer_tab until the GUI is loaded
        QTimer.singleShot(10, self._open_first_tab)
        QTimer.singleShot(30, self.plot_reopen.restore)
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
        self.status_bar_message_left = identify(ElidedLabel("..."), "status_activity")
        self.status_bar.addWidget(self.status_bar_message_left, 1)
        self.status_bar_progress = QProgressBar()
        self.status_bar_progress.setFixedSize(120, min(16, self.status_bar_message_left.fontMetrics().height()))
        self.status_bar_progress.setTextVisible(False)
        self.status_bar_progress.hide()
        self.status_bar.addWidget(self.status_bar_progress)
        self.status_bar_message_right = identify(
            QLabel(f"Please wait. GUI loading... v{APP_VERSION} ({APP_COMMIT_HASH})"), "status_resources")
        self.status_bar_message_last_update = datetime.now()
        # A one-time notice shown before the tab's activity until it expires (monotonic time).
        self._status_notice: tuple[str, float] | None = None

        # Shown while folders' cached data doesn't match them; opens their list.
        self.mismatch_button = identify(QToolButton(), "mismatched_folders", "Mismatched folders",
                                        "Show the folders whose cached data doesn't match them")
        self.mismatch_button.setAutoRaise(True)
        self.mismatch_button.hide()
        self.status_bar.addPermanentWidget(self.mismatch_button)
        self.roots_button = identify(QToolButton(), "roots_to_confirm", "Data roots to confirm",
                                     "Show the locations whose .helab-root is also elsewhere")
        self.roots_button.setAutoRaise(True)
        self.roots_button.hide()
        self.status_bar.addPermanentWidget(self.roots_button)
        # Shown while working offline (File › Work Offline); a click offers Work Online.
        self.offline_button = identify(QToolButton(), "work_online", description="Offer to work online again")
        self.offline_button.setAutoRaise(True)
        self.offline_button.setText(OFFLINE_STATUS)
        self.offline_button.setToolTip(OFFLINE_STATUS_TOOLTIP)
        self.offline_button.hide()
        self.offline_button.clicked.connect(self._offline_button_clicked)
        self.status_bar.addPermanentWidget(self.offline_button)
        # Shown from 50 % of the RAM budget (loaded folders and plots); opens their sizes.
        self.status_bar.addPermanentWidget(self.plots.ram_button)
        # Shown while Help › Record I/O trace is on.
        self.io_trace_label = identify(QLabel("● I/O trace"), "status_io_trace")
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
        gib, unit = byte_unit(3, "ram")  # (GiB: RAM is in powers of 1024 on every OS, Q26.1)
        ram_usage_app_gb = ram_usage_app / gib
        ram_usage_total_gb = ram_usage_total / gib

        # HeLab's own use; the system totals are in the tooltip.
        self.status_bar_message_right.setText(f"CPU {cpu_usage_app:.0f}% · RAM {ram_usage_app_gb:.1f} {unit}")
        self.status_bar_message_right.setToolTip(
            f"HeLab: CPU {cpu_usage_app:.1f}% · RAM {ram_usage_app_gb:.2f} {unit}\n"
            f"System: CPU {cpu_usage_total:.1f}% (summed over cores) · RAM {ram_usage_total_gb:.1f} {unit} used")

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

            # Cache-only browsing (D2): no source folder or server is read while it is on.
            self.action_work_offline = QAction(" Work Offline", self)
            self.action_work_offline.setCheckable(True)
            self.action_work_offline.setToolTip(WORK_OFFLINE_TOOLTIP)
            self.action_work_offline.triggered.connect(self.set_work_offline)
            menu_file.addAction(self.action_work_offline)

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


        
        # Presets of a folder and its plots (helab/views/plots/presets.py), filled as it shows.
        menu_presets = self.menu_bar.addMenu("Presets")
        assert menu_presets is not None
        self.menu_presets: QMenu = menu_presets

        menu_debug = self.menu_bar.addMenu('Debug')
        if menu_debug is not None:
            self._create_runner_menus(menu_debug)
            menu_debug.addSeparator()

            action_debug_icons = QAction("Show all Icons", self)
            action_debug_icons.triggered.connect(self.show_debug_icons_window)
            menu_debug.addAction(action_debug_icons)

            action_debug_memory_usage_window = QAction('Show Memory Usage', self)
            action_debug_memory_usage_window.triggered.connect(self.show_memory_usage_window)
            menu_debug.addAction(action_debug_memory_usage_window)

            menu_debug.addSeparator()

            action_debug_4 = QAction('Debug - show current visible rows', self)
            action_debug_4.triggered.connect(self.action_debug_show_current_visible_rows)
            menu_debug.addAction(action_debug_4)

            action_debug_gc_collect = QAction('gc.collect()', self)
            action_debug_gc_collect.triggered.connect(gc.collect)
            menu_debug.addAction(action_debug_gc_collect)

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
            action_log_folder = QAction("Show log folder", self)
            action_log_folder.triggered.connect(self._show_log_folder)
            menu_help.addAction(action_log_folder)

    # Items for a test runner (roadmaps/smoke-automation.md, items 1 and 2): a menu bar item works with
    # no cursor and no popup. Each submenu is filled from memory as it shows, and each item calls the
    # code path of the control it stands for.

    def _create_runner_menus(self, menu: QMenu) -> None:
        menu.setToolTipsVisible(True)
        menu.aboutToShow.connect(self._remember_screenshot_target)
        for title, fill in (("Run Plot", self._fill_run_menu), ("Script Group", self._fill_group_menu),
                            ("Show Plot Tab", self._fill_show_plot_menu), ("Close Plot Tab", self._fill_close_plot_menu),
                            ("Show Folder Tab", self._fill_show_folder_menu),
                            ("Close Folder Tab", self._fill_close_folder_menu),
                            ("Settings Tab", self._fill_settings_tab_menu)):
            submenu = menu.addMenu(title)
            if submenu is not None:
                submenu.setToolTipsVisible(True)
                submenu.aboutToShow.connect(lambda fill=fill, submenu=submenu: fill(submenu))
                # Filled now too, so it is never empty (not in a test's window without the Scripts panel).
                if hasattr(self, "panel_right_bottom_script_selector"):
                    fill(submenu)
        menu.addSeparator()
        self.action_screenshot = QAction("Save Window Screenshot…", self)
        self.action_screenshot.setToolTip("Save a picture of the HeLab window in front (when this menu opened) "
                                          "as a PNG file")
        self.action_screenshot.setObjectName("debug_save_screenshot")
        self.action_screenshot.triggered.connect(lambda: self.save_window_screenshot(self.screenshot_target()))
        menu.addAction(self.action_screenshot)
        # Q~1 (Tony): no dialog, for a runner: the same window, a fixed name in the temp folder's screenshots.
        self.action_screenshot_temp = QAction("Save Window Screenshot to Temp Folder", self)
        self.action_screenshot_temp.setObjectName("debug_save_screenshot_temp")
        self.action_screenshot_temp.setToolTip("Save a picture of the HeLab window in front (when this menu opened) "
                                               "in the temp folder's screenshots folder, without asking where; "
                                               "the status bar and the log name the file")
        self.action_screenshot_temp.triggered.connect(lambda: self.save_window_screenshot_to_temp())
        menu.addAction(self.action_screenshot_temp)
        screenshot_of = menu.addMenu("Save Screenshot of Window")
        if screenshot_of is not None:
            screenshot_of.aboutToShow.connect(lambda: self._fill_screenshot_menu(screenshot_of))
        self.action_dump_state = QAction("Dump State…", self)
        self.action_dump_state.setObjectName("debug_dump_state")
        self.action_dump_state.setToolTip("Save what this window shows (summary lines, Folder details, the status "
                                          "bar, folder and plot tabs, Live) as a JSON file, from memory")
        self.action_dump_state.triggered.connect(lambda: self.dump_state())
        menu.addAction(self.action_dump_state)
        menu.addSeparator()
        self._screenshot_target: QWidget | None = None

    @staticmethod
    def _unavailable(menu: QMenu, reason: str) -> None:
        """A menu with nothing to do now says why, in a disabled item."""
        action = menu.addAction(f"({reason})")
        if action is not None:
            action.setEnabled(False)

    def _fill_run_menu(self, menu: QMenu) -> None:
        """Debug › Run Plot: the Scripts panel's run buttons for the shown group ("Plot Counts per
        shot"); each clicks its button. Disabled until the current tab shows a folder's data."""
        menu.clear()
        tree = self.panel_right_bottom_script_selector.tree_widget
        loaded = self.plots.current_dataset_view() is not None
        if not loaded:
            self._unavailable(menu, "load a folder's data first")
        groups = [tree.topLevelItem(index) for index in range(tree.topLevelItemCount())]
        items = [group.child(index) for group in groups if group is not None for index in range(group.childCount())]
        buttons = [tree.itemWidget(item, column) for item in items if item is not None for column in (1, 2)]
        for button in buttons:
            if isinstance(button, QPushButton):
                action = menu.addAction(button.accessibleName() or button.text())
                if action is not None:
                    action.setEnabled(loaded and button.isEnabled())
                    # (An item pressed without the menu opening may outlive its button: then nothing.)
                    action.triggered.connect(lambda _=False, b=button: None if sip.isdeleted(b) else b.click())
        if menu.isEmpty():
            self._unavailable(menu, "no scripts in this group")

    def _fill_group_menu(self, menu: QMenu) -> None:
        """Debug › Script Group: the Scripts panel's groups; one sets its Group selector."""
        menu.clear()
        selector = self.panel_right_bottom_script_selector.group_selector
        for index in range(selector.count()):
            action = menu.addAction(selector.itemText(index))
            if action is not None:
                action.setCheckable(True)
                action.setChecked(index == selector.currentIndex())
                action.triggered.connect(lambda _=False, i=index: selector.setCurrentIndex(i))

    def _open_plot_docks(self) -> list[QDockWidget]:
        return [instance.dock_widget for instance in self.panel_right_bottom_script_selector.instances()
                if instance.dock_widget is not None]

    def _fill_show_plot_menu(self, menu: QMenu) -> None:
        """Debug › Show Plot Tab: each open plot; one shows it, as picking it in the Settings panel does."""
        menu.clear()
        settings = self.plots.panel_right_top_plot_settings
        for dock in self._open_plot_docks():
            action = menu.addAction(dock.windowTitle())
            if action is not None:
                action.setObjectName(f"debug_show_plot_tab_{getattr(dock, 'plot_id', '')}")
                action.setCheckable(True)
                action.setChecked(dock is settings.current_plot())
                action.triggered.connect(
                    lambda _=False, d=dock: None if sip.isdeleted(d) else settings.show_plot(d, raise_dock=True))
        if menu.isEmpty():
            self._unavailable(menu, "no plots open")

    def _fill_close_plot_menu(self, menu: QMenu) -> None:
        """Debug › Close Plot Tab: each open plot; one closes it, as its tab's × does."""
        menu.clear()
        for dock in self._open_plot_docks():
            action = menu.addAction(dock.windowTitle())
            if action is not None:
                action.setObjectName(f"debug_close_plot_tab_{getattr(dock, 'plot_id', '')}")
                action.triggered.connect(lambda _=False, d=dock: None if sip.isdeleted(d) else d.close())
        if menu.isEmpty():
            self._unavailable(menu, "no plots open")

    def _fill_show_folder_menu(self, menu: QMenu) -> None:
        """Debug › Show Folder Tab: each folder tab; one shows it, as clicking its tab does."""
        menu.clear()
        for index, explorer in self._explorers():
            action = menu.addAction(self.tab_widget.tabText(index))
            if action is not None:
                action.setObjectName(f"debug_show_{explorer.objectName()}")  # debug_show_folder_tab_<n>
                action.setCheckable(True)
                action.setChecked(explorer is self.tab_widget.currentWidget())
                action.triggered.connect(lambda _=False, e=explorer: self._folder_tab_action(e, close=False))
        if menu.isEmpty():
            self._unavailable(menu, "no folder tabs open")

    def _fill_close_folder_menu(self, menu: QMenu) -> None:
        """Debug › Close Folder Tab: each folder tab; one closes it, as its tab's × does."""
        menu.clear()
        for index, explorer in self._explorers():
            action = menu.addAction(self.tab_widget.tabText(index))
            if action is not None:
                action.setObjectName(f"debug_close_{explorer.objectName()}")  # debug_close_folder_tab_<n>
                action.triggered.connect(lambda _=False, e=explorer: self._folder_tab_action(e, close=True))
        if menu.isEmpty():
            self._unavailable(menu, "no folder tabs open")

    def _folder_tab_action(self, explorer: FolderExplorer, *, close: bool) -> None:
        """Show or close ``explorer``'s tab where it is now (tabs move), by the tab's own paths: the tab
        widget's current tab (a click on the tab), or its close request (the tab's ×). Nothing if it
        has closed meanwhile."""
        index = -1 if sip.isdeleted(explorer) else self.tab_widget.indexOf(explorer)
        if index < 0:
            return
        if close:
            self.tab_widget.tabCloseRequested.emit(index)
        else:
            self.tab_widget.setCurrentIndex(index)

    def _fill_settings_tab_menu(self, menu: QMenu) -> None:
        """Debug › Settings Tab: Settings opened on each tab (File › Settings… with that tab shown)."""
        menu.clear()
        available = not self._closing and QApplication.activeModalWidget() is None
        if not available:
            self._unavailable(menu, "close the open dialog first")
        for title in SettingsDialog.TAB_TITLES:
            action = menu.addAction(title)
            if action is not None:
                action.setEnabled(available)
                action.triggered.connect(lambda _=False, t=title: self.show_settings_dialog(tab=t))

    def _remember_screenshot_target(self) -> None:
        """The HeLab window in front as the Debug menu opens: on macOS the menu bar leaves it in front
        (a floating plot, a tool window); elsewhere the menu is the main window's own, so it is this
        window (Save Screenshot of Window › picks another)."""
        active = QApplication.activeWindow()
        self._screenshot_target = active if active is not None and not isinstance(active, QMenu) else None

    def screenshot_target(self) -> QWidget:
        target = self._screenshot_target
        return target if target is not None and not sip.isdeleted(target) and target.isVisible() else self

    def _screenshot_windows(self) -> list[QWidget]:
        """HeLab's visible windows (this one first): floating plots, tool windows, dialogs."""
        windows = [widget for widget in QApplication.topLevelWidgets()
                   if widget is not self and widget.isVisible() and not isinstance(widget, QMenu)
                   and widget.windowType() in (Qt.WindowType.Window, Qt.WindowType.Dialog, Qt.WindowType.Tool)]
        return [self, *windows]

    def _fill_screenshot_menu(self, menu: QMenu) -> None:
        menu.clear()
        for window in self._screenshot_windows():
            action = menu.addAction(window.windowTitle() or type(window).__name__)
            if action is not None:
                action.triggered.connect(
                    lambda _=False, w=window: None if sip.isdeleted(w) else self.save_window_screenshot(w))

    def save_window_screenshot(self, window: QWidget, path: str = "") -> str:
        """Debug › Save Window Screenshot…: ``window.grab()`` as a PNG, to ``path`` or one chosen in a
        save dialog (first offered in the temp folder's ``screenshots``). Plots come out as shown,
        QtWebEngine's (Plotly) too; where QtWebEngine can't paint (the lab PCs) they are black there as
        on screen. A floating plot is a window of its own. The file written ("": none)."""
        path = path or self._runner_file_path("Save window screenshot", window.windowTitle() or type(window).__name__,
                                              "png", "PNG images (*.png)")
        if not path:
            return ""
        if not window.grab().save(path, "PNG"):
            QMessageBox.warning(self, "Screenshot", f"The screenshot couldn't be saved to {path}.")
            return ""
        self.show_status_notice(f"Screenshot saved: {path}")
        return path

    def save_window_screenshot_to_temp(self) -> str:
        """Debug › Save Window Screenshot to Temp Folder (Q~1): as Save Window Screenshot…, without a
        dialog: ``helab-<window>-<time>.png`` in the temp folder's ``screenshots`` (``-2``, ``-3`` … if
        that name is taken), logged and named in the status bar. The file written ("": none)."""
        window = self.screenshot_target()
        path = self._runner_file_path("", window.windowTitle() or type(window).__name__, "png", "", ask=False)
        written = self.save_window_screenshot(window, path)
        if written:
            logging.info("Screenshot saved: %s", written)
        return written

    def dump_state(self, path: str = "") -> str:
        """Debug › Dump State…: ``state_dump.dump_state`` (memory only) as JSON, to ``path`` or one
        chosen as for a screenshot. The file written ("": none)."""
        state = state_dump.dump_state(self)  # Taken before the save dialog shows.
        path = path or self._runner_file_path("Save HeLab's state", "state", "json", "JSON (*.json)")
        if not path:
            return ""
        try:
            with open(path, "w", encoding="utf-8") as file:
                json.dump(state, file, indent=2, ensure_ascii=False)
        except OSError as error:
            QMessageBox.warning(self, "Dump state", f"The state couldn't be saved to {path}: {error}")
            return ""
        self.show_status_notice(f"State saved: {path}")
        return path

    def _runner_file_path(self, caption: str, name: str, suffix: str, filter: str, *, ask: bool = True) -> str:
        """A file for a runner's screenshot or state, chosen in a save dialog that offers
        ``helab-<name>-<time>.<suffix>`` in the temp folder's ``screenshots`` ("": cancelled), or
        without ``ask``, that name itself (``-2``, ``-3`` … if taken)."""
        # On the GUI thread: one folder in HeLab's own temp folder and one small file the user asked for
        # (a debug item, as Settings' profile export), never a source folder or the store.
        folder = os.path.join(DIR_TEMPS, "screenshots")
        os.makedirs(folder, exist_ok=True)
        stem = os.path.join(folder, f"helab-{id_part(name).lower()[:40]}-{datetime.now():%Y%m%d-%H%M%S}")
        suggested = f"{stem}.{suffix}"
        if not ask:
            taken = 1
            while os.path.exists(suggested):
                taken += 1
                suggested = f"{stem}-{taken}.{suffix}"
            return suggested
        return QFileDialog.getSaveFileName(self, caption, suggested, filter)[0]

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
                          f"({byte_size(size, 'disk')}) in {folder}.", QMessageBox.StandardButton.NoButton, self)
        keep = box.addButton("Keep", QMessageBox.ButtonRole.RejectRole)
        delete = box.addButton("Delete old traces", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(keep)
        identify_buttons(box, "io_trace_old")
        box.exec()
        return box.clickedButton() is delete

    def _show_io_trace_folder(self) -> None:
        from PyQt6.QtGui import QDesktopServices
        folder = io_trace_folder(DIR_TEMPS)
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _show_log_folder(self) -> None:
        """Help › Show log folder: the app folder's ``logs``, where each HeLab writes its log."""
        from PyQt6.QtGui import QDesktopServices
        folder = app_log.log_folder(app_folder())
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _on_drive_result(self, request: IORequest, event: dict[str, Any]) -> None:
        if self._closing or request.owner != self._drive_owner or event["kind"] != "drives":
            return
        for path in event["paths"]:
            action = QAction(path, self)
            action.triggered.connect(lambda checked=False, p=path: self.add_new_folder_explorer_tab(target_path=p))
            self._drive_menu.addAction(action)

    def action_debug_show_current_visible_rows(self) -> None:
        current_file_explorer = self.tab_widget.currentWidget()
        if isinstance(current_file_explorer, FolderExplorer):
            logging.info(f"{current_file_explorer.model.rootPath() = }")
            rows = current_file_explorer.model.get_visible_rows()
            for r in rows:
                logging.info(f"{r = }")


    def show_settings_dialog(self, purge: bool = False, *, tab: str = "") -> None:
        """Settings, modal: at its Cache tab's Remove old entries (``purge``), or at the tab titled
        ``tab`` (Debug › Settings Tab)."""
        if self._closing or QApplication.activeModalWidget() is not None:
            return
        cache = get_folder_cache(get_io_service())
        self.settings_dialog = SettingsDialog(self, cache=cache)
        if (roots := getattr(self.settings_dialog, "roots_tab", None)) is not None:
            roots.reviewRequested.connect(self.review_root)
        if purge:
            self.settings_dialog.show_purge()
        elif tab:
            self.settings_dialog.show_tab(tab)
        self.settings_dialog.exec()
        self._set_root_window_modality(Qt.WindowModality.NonModal)  # Review… from Settings made it modal.
        settings = app_settings()
        self.apply_load_mode(read_load_mode(settings))
        get_io_service().configure_concurrency(
            read_io_concurrency(settings))
        cache.check_level = read_check_level(settings)
        self._apply_live_settings(settings)
        cache.set_lab_constants(read_lab_constants(settings))
        # What only Save applies, again from the settings: Reset, then Cancel, has already cleared them.
        cache.set_convert_profile(read_convert_profile(settings))
        cache.set_tab_source(read_txy_source(settings))
        cache.set_result_reuse(read_result_reuse(settings))
        # Reset while working offline, "go online now" (Q43.1): the setting was cleared, the session follows.
        if bool(read_setting(settings, WORK_OFFLINE_SETTING, typed=True)) != cache.offline:
            self.set_work_offline(not cache.offline)
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
                                    f"folder{'' if len(dropped) == 1 else 's'} ({byte_size(size, 'ram')}) not shown in tabs")
        if (budget := self.plots.ram_budget) is not None:
            budget.auto_reload = read_plot_auto_reload(settings)
            budget.check()  # The plots' share of a new budget.
        self.apply_auto_scan_visible(read_setting(settings, AUTO_SCAN_VISIBLE_SETTING, typed=True))

    @staticmethod
    def _apply_live_settings(settings: QSettings) -> None:
        """Live's interval and autosave, and the settle time every helper uses (Q33.7)."""
        cache = get_folder_cache(get_io_service())
        cache.live_interval = read_live_interval(settings)
        cache.live_autosave_shots = read_live_autosave(settings)
        get_io_service().settle_seconds = read_settle_seconds(settings)

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


        # The folder and settings panels' widths as the user left them (Q33.2), the plots the rest; applied
        # again from the splitter's real width when the window first shows (``showEvent``).
        self.left_panel_width, self.right_panel_width = self.read_split(app_settings())
        self._split_shown = False
        self.splitter.setSizes([
            self.left_panel_width,
            self.DEFAULT_WIDTH-self.left_panel_width-self.right_panel_width,
            self.right_panel_width
        ])


        # Make the left and right panels collapsible
        self.left_panel.setMinimumWidth(0)
        # The settings panel's least width is set, not its contents': the splitter keeps the width the user
        # (or the default) gave it, whatever a row's text needs in the system's font (on Windows CI a row
        # held it at ~548 px); a row that doesn't fit is cut until the panel is widened (Q33.2).
        self.right_panel.setMinimumWidth(self.MIN_SETTINGS_WIDTH)

        # A change in the window's width goes to the plots; the panels keep theirs.
        self.splitter.setStretchFactor(0, 0)  # Left panel
        self.splitter.setStretchFactor(1, 1)  # Middle area
        self.splitter.setStretchFactor(2, 0)  # Right panel

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
        identify_action(self.sidebar_toolbar_left, self.toggle_left_panel_action, "toggle_left_panel",
                        "Show or hide the folder panel")

        # Left panel
        self.left_panel = QWidget()
        self._live_collapsed_panel = False  # Live collapsed it (``_live_panel``): Live off restores it.
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
        self.action_tab_refresh.setToolTip(REFRESH_TOOLTIP)
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
        self.folder_status_button = identify(QToolButton(status_control), "check_folder_status",
                                             description="Check the folders in view, or cancel a check")
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
        identify(self.folder_status_scope_button, "check_folder_status_scope", "Choose folders to check",
                 "Open the folder status check options")
        self.action_tab_rescan.changed.connect(
            lambda: self.folder_status_scope_button.setEnabled(self.action_tab_rescan.isEnabled()))
        self.folder_status_scope_button.setEnabled(self.action_tab_rescan.isEnabled())
        status_layout.addWidget(self.folder_status_button)
        status_layout.addWidget(self.folder_status_scope_button)
        self.sidebar_toolbar_left.addWidget(status_control)
        self.sidebar_toolbar_left.addAction(self.action_tab_cancel)
        self.sidebar_toolbar_left.addAction(self.action_tab_live)
        for action, ident, description in (
                (self.action_tab_new, "new_tab", "Open a new folder tab"),
                (self.action_tab_folder_up, "folder_up", "Show the folder above in this tab"),
                (self.action_tab_refresh, "refresh", "Update the folder names and expanded folders in view"),
                (self.action_tab_cancel, "cancel_loading", "Cancel loading in this tab"),
                (self.action_tab_live, "live", "Watch the selected folder for new shots, or stop")):
            identify_action(self.sidebar_toolbar_left, action, ident, description)

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
        identify_action(self.sidebar_toolbar_left, action_settings, "settings", "Open Settings")

        self.sidebar_toolbar_left.addSeparator()

        # Add a button to the bottom of sidebar_toolbar_left
        self.toggle_folder_details_action = QAction(ToolIcons.ICON_BOTTOM_EXPAND, "Toggle Folder Details", self)
        self.toggle_folder_details_action.setCheckable(True)
        self.toggle_folder_details_action.setChecked(True)
        self.sidebar_toolbar_left.addAction(self.toggle_folder_details_action)
        identify_action(self.sidebar_toolbar_left, self.toggle_folder_details_action, "toggle_folder_details",
                        "Show or hide Folder details")
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
        identify_action(self.sidebar_toolbar_right, self.toggle_right_panel_action, "toggle_right_panel",
                        "Show or hide the plot settings and scripts panel")
        spacer_right = QWidget()
        spacer_right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.sidebar_toolbar_right.addWidget(spacer_right)

        # Right panel
        self.right_panel = QWidget()
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
        identify_action(self.sidebar_toolbar_right, toggle_right_bottom_panel_action, "toggle_scripts_panel",
                        "Show or hide the Scripts panel")

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

    # A panel narrower than this isn't a width to restore (the user dragged it nearly shut).
    MIN_PANEL_WIDTH, MAX_PANEL_WIDTH = 80, 4000
    # The settings panel's least width (review R2-2): the narrowest at which none of its controls is cut at
    # macOS's default font (Load Scripts… and Delete… start to be at 240), below the 320 px default so the
    # default split holds where the system's font is wider (Windows), set rather than taken from the contents.
    MIN_SETTINGS_WIDTH = 250
    # The plots' least width when the panels' widths don't fit the window (app-2: a split saved on a wider
    # screen narrows both panels in proportion, rather than leaving the plots 0 px). Below what the default
    # split leaves in Windows CI's 976 px splitter (268 px), so the default 380/320 holds there (Q33.2).
    MIN_PLOTS_WIDTH = 240
    _split_shown = True  # (False from ``_setup_central_widgets`` until the first show applies the widths.)
    # Panels the window narrowed (splitter index: (width shown, width chosen)), not saved as the user's.
    _narrowed: dict[int, tuple[int, int]] = {}

    @classmethod
    def read_split(cls, settings: QSettings) -> tuple[int, int]:
        """The folder and settings panels' saved widths (``main_window_split``, "<folders>,<settings>"); the
        row's default for a value that isn't two widths up to MAX_PANEL_WIDTH, the folders' at least
        MIN_PANEL_WIDTH and the settings' at least MIN_SETTINGS_WIDTH."""
        def widths(text: object) -> tuple[int, int] | None:
            try:
                left, right = (int(part) for part in str(text).split(","))
            except ValueError:
                return None
            fits = (cls.MIN_PANEL_WIDTH <= left <= cls.MAX_PANEL_WIDTH
                    and cls.MIN_SETTINGS_WIDTH <= right <= cls.MAX_PANEL_WIDTH)
            return (left, right) if fits else None
        saved = widths(read_setting(settings, MAIN_SPLIT_SETTING))
        if saved is not None:
            return saved
        default = widths(setting_default(MAIN_SPLIT_SETTING))
        assert default is not None
        return default

    def showEvent(self, a0: QShowEvent | None) -> None:
        """The first time it shows: the panels at their widths, the plots taking what the window really has
        (before, the splitter shared out a width it only guessed, and gave a panel its contents' size hint)."""
        super().showEvent(a0)
        if not self._split_shown:
            self._split_shown = True
            self._set_split(self.left_panel_width, self.right_panel_width, self.splitter.width())

    @classmethod
    def fitted(cls, left: int, right: int, total: int) -> tuple[int, int]:
        """The panels' widths ``left`` and ``right`` (0: collapsed) in a splitter ``total`` wide: as they are
        when the plots keep MIN_PLOTS_WIDTH; else each shown panel keeps its least width and the room above
        those is shared in proportion to what each had above its own (one held at its least width narrows
        the other)."""
        room = total - cls.MIN_PLOTS_WIDTH
        if left + right <= room:
            return left, right
        least_left, least_right = min(left, cls.MIN_PANEL_WIDTH), min(right, cls.MIN_SETTINGS_WIDTH)
        above_left, above_right = left - least_left, right - least_right
        spare = max(0, room - least_left - least_right)
        share = round(spare * above_left / (above_left + above_right)) if above_left + above_right else 0
        return least_left + share, least_right + min(spare - share, above_right)

    def _set_split(self, left: int, right: int, total: int) -> None:
        """The panels ``left`` and ``right`` wide (0: collapsed), the plots the rest of ``total``. Where the
        plots would get less than MIN_PLOTS_WIDTH, the shown panels are narrowed in proportion (to no less
        than their least widths) for this window only: the widths chosen stay the ones saved."""
        chosen = {0: left, 2: right}
        left, right = self.fitted(left, right, total)
        self.splitter.setSizes([left, max(0, total - left - right), right])
        sizes = self.splitter.sizes()
        self._narrowed = {index: (sizes[index], width) for index, width in chosen.items() if sizes[index] < width}

    def save_split(self) -> None:
        """Keep the panels' widths for the next start (as HeLab quits). A shown panel's width is its own; a
        collapsed one's, the width it had (``--geometry`` sizes the window for one run only: Q33.2)."""
        self._remember_panel_widths()
        app_settings().setValue(MAIN_SPLIT_SETTING, f"{self.left_panel_width},{self.right_panel_width}")

    def _chosen_sizes(self) -> list[int]:
        """The splitter's sizes, a panel the window narrowed (``_set_split``) and still that wide at the
        width chosen for it."""
        sizes = self.splitter.sizes()
        for index, (shown, chosen) in self._narrowed.items():
            if sizes[index] == shown:
                sizes[index] = chosen
        return sizes

    def _remember_panel_widths(self) -> None:
        """The panels' widths to restore (toggle back, next start): each shown panel's current width, or the
        one chosen for it while the window narrows it."""
        left, _, right = self._chosen_sizes()
        if left >= self.MIN_PANEL_WIDTH:
            self.left_panel_width = min(left, self.MAX_PANEL_WIDTH)
        if right >= self.MIN_SETTINGS_WIDTH:
            self.right_panel_width = min(right, self.MAX_PANEL_WIDTH)

    GEOMETRY = re.compile(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)")

    @staticmethod
    def take_geometry(argv: list[str]) -> tuple[Optional[QRect], list[str]]:
        """``--geometry WxH+X+Y`` (or ``--geometry=WxH+X+Y``) in ``argv``: the main window's size W×H and
        its frame's top-left at X,Y (screen points; a sign each, "-" for a screen left of or above the
        main one), for this run only. The rectangle (None: not given, or not of that form, which is
        logged) and ``argv`` without the option (Qt reads its own ``-geometry`` on Linux)."""
        rest, value, found = [], None, False
        args = iter(argv)
        for arg in args:
            if arg == "--geometry":
                value, found = next(args, ""), True
                if value.startswith("-") and not HelabMainWindow.GEOMETRY.fullmatch(value):
                    rest.append(value)  # (Another option, not a value: kept.)
                    value = ""
            elif arg.startswith("--geometry="):
                value, found = arg.partition("=")[2], True
            else:
                rest.append(arg)
        if not found:
            return None, rest
        match = HelabMainWindow.GEOMETRY.fullmatch(value or "")
        if match is None:
            logging.warning("--geometry %r ignored: give WxH+X+Y, e.g. 1600x928+0+39", value)
            return None, rest
        width, height, x, y = (int(group) for group in match.groups())
        return QRect(x, y, width, height), rest

    def apply_geometry(self, geometry: QRect) -> None:
        """Size and place the window as ``--geometry`` asks (no less than its minimum size); nothing
        is saved."""
        self.resize(geometry.size())
        self.move(geometry.topLeft())

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
            self._set_split(self.left_panel_width, self._chosen_sizes()[2], self.splitter.width())
            self.toggle_left_panel_action.setIcon(ToolIcons.ICON_LEFT_COLLAPSE)
            self.toggle_left_panel_action.setChecked(True)
            self.view_toggle_left_panel.setChecked(True)
        else: # Collapse the left panel
            self._remember_panel_widths()
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
            self._set_split(self._chosen_sizes()[0], self.right_panel_width, self.splitter.width())
            self.sidebar_toolbar_right.actions()[0].setIcon(ToolIcons.ICON_RIGHT_COLLAPSE)
            self.toggle_right_panel_action.setChecked(True)
            self.view_toggle_right_panel.setChecked(True)
        else:
            self._remember_panel_widths()
            # Its width goes to the plots; the folders keep the width shown (which the window may narrow).
            left, middle, right = self.splitter.sizes()
            self.splitter.setSizes([left, middle + right, 0])
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

    def set_work_offline(self, on: bool) -> None:
        """File › Work Offline (cache-only browsing; Tony, 2026-10-26: D1–D10). On: Live turns off in
        every tab (its save finishes), then no source folder is read until it is turned off. Off:
        every tab lists its shown folders again (Refresh, D8) and the current tab's selected folder
        is checked as usual. Remembered across restarts."""
        cache = get_folder_cache(get_io_service())
        app_settings().setValue(WORK_OFFLINE_SETTING, bool(on))
        if on == cache.offline:
            self._offline_changed(on)
            return
        tabs = [widget for index in range(self.tab_widget.count())
                if isinstance(widget := self.tab_widget.widget(index), FolderExplorer) and not widget.closed]
        if on:
            for explorer in tabs:
                if explorer.live is not None:
                    explorer.stop_live()
            cache.set_offline(True)
            return
        cache.set_offline(False)
        for explorer in tabs:
            explorer.refresh()
        current = self.tab_widget.currentWidget()
        if isinstance(current, FolderExplorer) and not current.closed and current.selected_path_globally:
            current.load_to_ram_cache(current.selected_path_globally)

    def _offline_button_clicked(self) -> None:
        if QMessageBox.question(self, "Work online?", "Work online again? HeLab lists the folders in every tab "
                                "again and checks the selected folder's data.",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                QMessageBox.StandardButton.Yes) == QMessageBox.StandardButton.Yes:
            self.set_work_offline(False)

    def _offline_changed(self, offline: bool) -> None:
        """The File menu's check, the status-bar button and the tools that read source folders."""
        if self._closing:
            return
        self.action_work_offline.setChecked(offline)
        self.offline_button.setVisible(offline)
        self._update_live_action()
        self._update_folder_status_action()

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
        # Working offline, no folder is checked either (cache-only browsing).
        available = (isinstance(explorer, FolderExplorer) and not explorer.closed and explorer.live is None
                     and not get_folder_cache(get_io_service()).offline)
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
        offline = get_folder_cache(get_io_service()).offline
        # Working offline, Refresh and Check folder status would read folders (cache-only browsing).
        self.action_tab_refresh.setEnabled(not offline)
        self.action_tab_rescan.setEnabled(not offline)
        self.action_tab_refresh.setToolTip(f"Refresh folder list\n{OFFLINE_TOOLTIP}." if offline else REFRESH_TOOLTIP)
        self.action_tab_rescan.setToolTip(f"Check folder status\n{OFFLINE_TOOLTIP}." if offline
                                          else self.FOLDER_STATUS_TOOLTIP)
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
        session = explorer.live if explorer is not None else None
        self._live_panel(session is not None and not session.error)

    def _open_first_tab(self) -> None:
        """The usual first tab, or, when a folder is set to start Live at launch, that folder's tab alone
        (Q18.3: such an instance opens no other folder tab; ``live_launch``)."""
        if live_launch.opens_at_launch():
            live_launch.start(self)
        else:
            self.add_new_folder_explorer_tab()

    def _live_panel(self, watching: bool) -> None:
        """Turning Live on collapses the file explorer panel (the left panel), giving its room to the plots;
        Live off restores it (Q18.3), as does an error stopping its checks (the Live line has Retry). A panel
        the user had collapsed stays so; one the user opened again while Live is on stays open."""
        collapsed = self.splitter.sizes()[0] == 0
        if watching:
            if not self._live_collapsed_panel and not collapsed:
                self._live_collapsed_panel = True
                self.toggle_left_panel(False)
        elif self._live_collapsed_panel:
            self._live_collapsed_panel = False
            if collapsed:
                self.toggle_left_panel(True)

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
        self.save_split()
        self.plot_reopen.quit()  # The open plots are recorded before they close.
        self.plots.close_plots()
        self.plots.detach()  # The RAM budget, then the Settings panel.
        if not self._cache_dialogs_detached:
            self.cache_dialogs.detach()
        self.clock_skew_warning.detach()
        self.watchdog.stop()
        for timer in self.findChildren(QTimer):
            timer.stop()
        self.tab_widget.closeEvent(None)
        get_io_service().shutdown()
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
        cache.flush_txy_marks()  # Converted TXY's last uses loads didn't write (Q30.3): a save like the others.
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
