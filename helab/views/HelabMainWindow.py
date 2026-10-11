import gc
import logging
import os
import platform
import re
import signal
import subprocess
import sys
import tempfile
import types
import warnings
import threading
import time
from helab.utils.io_service import IORequest, get_io_service
from helab.utils.folder_cache import get_folder_cache, set_disk_budget, store_options
from helab.utils.gui_watchdog import GUIWatchdog
from datetime import datetime, timedelta
from sys import getsizeof
from typing import Any, List, Optional

import psutil
from PyQt6.QtCore import Qt, QSize, QTimer, QThreadPool, QFileInfo, QItemSelection, QModelIndex, QUrl, QEvent, QPoint, \
    QDir, QDateTime, QSettings, QStorageInfo, QRect
from PyQt6.QtGui import QAction, QActionGroup, QIcon, QCloseEvent, QPainter, QPixmap, QResizeEvent, QKeySequence
from PyQt6.QtWidgets import QMainWindow, QDockWidget, QStatusBar, QMenuBar, QWidget, QVBoxLayout, QSplitter, \
    QLabel, QToolBar, QSizePolicy, QFileDialog, QToolTip, QMenu, QApplication, QCheckBox, QTabWidget, QHBoxLayout, \
    QPushButton, QTreeWidget, QTreeWidgetItem, QInputDialog, QProgressBar, QToolButton, QMessageBox
from humanfriendly.terminal import message
# from numpy.f2py.crackfortran import include_paths
from pyqtgraph.parametertree import ParameterTree, Parameter
from typing_extensions import no_type_check

from helab.models.ScriptTreeSelector import TreePanelWidget, ParamTreeTabWidget
from helab.resources.icons import ToolIcons
from helab.utils.constants import *
from helab.utils.number_format import byte_size, fnum
from helab.views.CacheDialogs import CacheDialogs
from helab.views.CentralHint import CentralHint
from helab.views.ElidedLabel import ElidedLabel
from helab.views.FolderDetailsPanel import FolderDetailsPanel
from helab.views.HoverMenuToolButton import HoverMenuToolButton
from helab.views.FolderExplorer import (
    AUTO_LOAD_OFF_TOOLTIP, AUTO_LOAD_PAUSED, AUTO_LOAD_PAUSED_TOOLTIP, LARGE_TOOLTIP, REFUSED_TOOLTIP, FolderExplorer, large_text, paint_spinner,
)
from helab.views.FolderTabWidget import FolderTabWidget
from helab.views.MemoryUsageWindow import MemoryUsageWindow
from helab.views.SettingsDialog import SettingsDialog
from helab.views.DebugIconsWindow import DebugIconsWindow

from PyQt6.QtWebEngineWidgets import QWebEngineView
# sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'scripts'))
# from helab.scripts.legacy_plotly.scattering_proj_monitori_dld import fig_txt_density
import plotly
import pyqtgraph as pg
import pyqtgraph.parametertree as ptree


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
        self.watchdog = GUIWatchdog(self)
        # logging.debug(f"Current directory is {CURRENT_WORKING_DIRECTORY}")
        if not os.path.exists(DIR_TEMPS): os.makedirs(DIR_TEMPS)

        self.current_tracking_folder_path = '/'
        self.named_temp_files: List[tempfile._TemporaryFileWrapper[bytes]] = [] #TODO: dev code, remove these in prod

        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGTERM, self.handle_exit)

        self.process = psutil.Process()
        icon_path = os.path.abspath("./helab/resources/ai-icon.icns")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            logging.error(f"Icon file not found: {icon_path}")

        self.setWindowTitle(f"HeLab GUI Loading... v{APP_VERSION} ({APP_COMMIT_HASH})")
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.setMinimumSize(1000, 600)

        # Create Central Widget Area with Dock Widgets
        self._setup_central_widgets()

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
        if not self.action_tab_live_checked:
            self.set_tools_and_tabs_enable()
        self.status_bar_message_last_update = datetime.now()

    def _spinner_pixmap(self) -> QPixmap:
        ratio = self.status_bar_spinner.devicePixelRatioF()
        pixmap = QPixmap(round(16 * ratio), round(16 * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        paint_spinner(painter, QRect(3, 3, 10, 10), self.status_bar_spinner_angle)
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

            settings = QSettings(QSETTINGS_ORG_NAME, QSETTINGS_APP_NAME)
            self.view_toggle_thread_status = QAction('Toggle Thread Status Auto Pop-up', self)
            self.view_toggle_thread_status.setCheckable(True)
            self.view_toggle_thread_status.setChecked(settings.value("view_toggle_thread_status", type=bool, defaultValue=True))
            self.view_toggle_thread_status.triggered.connect(lambda checked: settings.setValue("view_toggle_thread_status", checked))
            menu_view.addAction(self.view_toggle_thread_status)

            menu_view.addSeparator()

            self.view_toggle_auto_scan_visible = QAction('Automatically Check Folder Status in View', self)
            self.view_toggle_auto_scan_visible.setCheckable(True)
            self.view_toggle_auto_scan_visible.setToolTip(
                "Scan visible folders that have no saved scan results; use Check folder status to recheck cached folders.")
            self.view_toggle_auto_scan_visible.setChecked(settings.value(AUTO_SCAN_VISIBLE_SETTING, False, type=bool))
            self.view_toggle_auto_scan_visible.triggered.connect(self.set_auto_scan_visible)
            menu_view.addAction(self.view_toggle_auto_scan_visible)
            get_io_service().configure_concurrency(
                read_io_concurrency(settings))
            set_disk_budget(read_disk_budget(settings))
            get_folder_cache(get_io_service()).set_ram_budget(read_ram_budget(settings))

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
        if purge:
            self.settings_dialog.show_purge()
        self.settings_dialog.exec()
        settings = QSettings(QSETTINGS_ORG_NAME, QSETTINGS_APP_NAME)
        self.apply_load_mode(read_load_mode(settings))
        get_io_service().configure_concurrency(
            read_io_concurrency(settings))
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
        self.apply_auto_scan_visible(settings.value(AUTO_SCAN_VISIBLE_SETTING, False, type=bool))

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
        # FolderExplorer has no live monitor yet; do not imply that polling is active.
        self.action_tab_live.setEnabled(False)
        self.action_tab_live_checked = False
        self.action_tab_live_was_left_panel_open_before_clicking_live = True

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
        self.action_tab_live.setToolTip("Live updates unavailable\nUse Check folder status to check for new files.")

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
        self.panel_right_top_params_tab_widget = ParamTreeTabWidget(parent=self)
        self.panel_right_top_params_tab_widget.add_example_tab()

        self.panel_right_bottom_script_selector = TreePanelWidget(helab_main_window=self)
        self.panel_right_bottom_script_selector.add_example_groups_and_items()

        self.panel_right_bottom_script_selector.setVisible(True)
        # Add the bottom panel to the right_layout
        # Add a button to the bottom of sidebar_toolbar_right
        toggle_right_bottom_panel_action = QAction(ToolIcons.ICON_BOTTOM_EXPAND, "Toggle Right Bottom Panel", self)
        toggle_right_bottom_panel_action.setCheckable(True)
        toggle_right_bottom_panel_action.setChecked(True)
        toggle_right_bottom_panel_action.triggered.connect(self.toggle_right_bottom_panel)
        self.sidebar_toolbar_right.addAction(toggle_right_bottom_panel_action)

        self.right_splitter.addWidget(self.panel_right_top_params_tab_widget)
        self.right_splitter.addWidget(self.panel_right_bottom_script_selector)
        self.right_splitter.setSizes([400, 300])

        # Add the right panel to the splitter
        self.splitter.addWidget(self.right_panel)


    def _setup_middle_area(self) -> None:
        self.middle_mainwindow = QMainWindow()
        # Set a central widget for the middle main window
        # Load details are in Folder details; the plot area keeps a short hint.
        self.central_placeholder = CentralHint("Select a data folder to begin")
        self.middle_mainwindow.setCentralWidget(self.central_placeholder)
        self.dock_widgets: List[QDockWidget] = []


        self.central_placeholder_timer = QTimer(self)
        self.central_placeholder_timer.timeout.connect(self._update_folder_details)
        self.central_placeholder_timer.start(self.INTERVAL_UPDATE_CENTRAL_LOADING_INDICATOR)
        self.current_tracking_folder_path_is_loading: Optional[bool] = None
        """ True is loading, False is loaded, None is not loadable"""

        # Add the middle main window to the splitter
        self.splitter.addWidget(self.middle_mainwindow)

        self.update_placeholder_visibility()

    def update_placeholder_visibility(self) -> None:
        # Check if any dock widgets are visible
        logging.debug(f"update_placeholder_visibility: called")
        any_visible = any(dock_widget.isVisible() for dock_widget in self.dock_widgets)
        if any_visible:
            self.central_placeholder.hide()
        else:
            self.central_placeholder.show()

    def _set_plot_source(self, dock: QDockWidget, explorer: FolderExplorer) -> None:
        """Attach provenance to a plot at creation, before the selection changes."""
        dataset = explorer.displayed_dataset
        content = dock.widget()
        if dataset is None or content is None:
            return
        dock.setProperty("dataSourcePath", dataset.path)
        dock.setProperty("dataSourceSignature", dataset.signature)
        wrapper = QWidget(dock)
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(4, 4, 4, 4)
        label = QLabel(wrapper)
        label.setObjectName("plot_data_source")
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addWidget(content, 1)
        dock.setWidget(wrapper)
        HelabMainWindow._update_plot_source_label(dock, explorer)

    @staticmethod
    def _update_plot_source_label(dock: QDockWidget, explorer: FolderExplorer) -> None:
        path = dock.property("dataSourcePath")
        if not isinstance(path, str):
            return
        label = dock.findChild(QLabel, "plot_data_source")
        if label is None:
            return
        node = explorer.model.nodes.get(explorer.selected_path_globally)
        # A names-only listing has no signature; the explorer compares shot lists then.
        current = (path == explorer.selected_path_globally and node is not None
                   and (not node.signature or dock.property("dataSourceSignature") == node.signature)
                   and explorer.folder_opened_path == path)
        prefix = "Data source" if current else "Showing previously loaded data"
        label.setText(f"{prefix}: {os.path.basename(path.rstrip(os.sep)) or path}")
        label.setToolTip(path)

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

    def load_folder_to_ram(self, current_folder_explorer: FolderExplorer, file_info: QFileInfo) -> None:
        current_folder_explorer.load_to_ram_cache(file_info.absoluteFilePath())

    def _snapshot_data_loaded(self, explorer: FolderExplorer, path: str) -> None:
        if self.tab_widget.currentWidget() is explorer and path == explorer.selected_path_globally:
            self.current_tracking_folder_path_is_loading = False
            self._update_folder_details()
            self.update_placeholder_visibility()

    def _explorers(self) -> list[tuple[int, FolderExplorer]]:
        return [(index, widget) for index in range(self.tab_widget.count())
                if isinstance(widget := self.tab_widget.widget(index), FolderExplorer)]

    def _load_tabs(self, producer: IORequest) -> tuple[list[tuple[int, FolderExplorer]], str]:
        """The tabs a running load is for (in tab order), and its progress note."""
        owners, note = get_folder_cache(get_io_service()).load_note(producer)
        tabs = [(index, explorer) for index, explorer in self._explorers()
                if explorer.model.owner in owners or explorer.bg_owner in owners]
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
            self.central_placeholder.set_hint("Select a data folder to begin")
            return
        for dock in self.dock_widgets:
            HelabMainWindow._update_plot_source_label(dock, explorer)
        self.current_tracking_folder_path_is_loading = explorer.loading
        self.central_placeholder.set_hint(*HelabMainWindow.central_hint(explorer))

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
            current_folder_explorer.loadStateChanged.connect(self._update_folder_details)
            current_folder_explorer.loadStateChanged.connect(self._update_cancel_loading_action)
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
        available = isinstance(explorer, FolderExplorer) and not explorer.closed
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
            self.action_tab_folder_up.setEnabled(current_folder_explorer.back_button_enabled)
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

    def connect_folder_explorer_signals(self, index: QModelIndex) -> None:
        current_folder_explorer = self.tab_widget.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.itemExpandedSignal.connect(self.update_tool_enabled_state)
            QTimer.singleShot(50, self.update_status_bar_left)

    def on_live_button_clicked(self) -> None:
        if self.action_tab_live_checked:
            logging.debug("on_live_button_clicked: set to unchecked (stop tracking)")
            self.action_tab_live.setChecked(False)
            self.action_tab_live_checked = False
            self.tab_widget.setEnabled(True)
            if self.splitter.sizes()[0] == 0:
                self.toggle_left_panel( self.action_tab_live_was_left_panel_open_before_clicking_live )
            self.set_tools_and_tabs_enable()
            self.update_tool_enabled_state()
        else:
            logging.debug("on_live_button_clicked: set to checked (start tracking)")
            # logging.fatal(f"debug: {self.splitter.sizes()[0] > 0 = }")
            self.action_tab_live_was_left_panel_open_before_clicking_live = self.splitter.sizes()[0] > 0
            self.action_tab_live.setChecked(True)
            self.action_tab_live_checked = True
            self.tab_widget.setEnabled(False)
            self.toggle_left_panel(False)
            self.action_tab_refresh.setEnabled(False)
            self.action_tab_new.setEnabled(False)
            self.action_tab_rescan.setEnabled(False)
            self.action_tab_folder_up.setEnabled(False)

        current_folder_explorer = self.tab_widget.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            # current_folder_explorer.toggle_live_update()
            pass

    def set_load_mode(self, mode: str) -> None:
        QSettings(QSETTINGS_ORG_NAME, QSETTINGS_APP_NAME).setValue(LOAD_MODE_SETTING, mode)
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
        QSettings(QSETTINGS_ORG_NAME, QSETTINGS_APP_NAME).setValue(AUTO_SCAN_VISIBLE_SETTING, enabled)
        self.apply_auto_scan_visible(enabled)

    def apply_auto_scan_visible(self, enabled: bool) -> None:
        self.view_toggle_auto_scan_visible.setChecked(enabled)
        for index in range(self.tab_widget.count()):
            explorer = self.tab_widget.widget(index)
            if isinstance(explorer, FolderExplorer):
                explorer.set_auto_scan_visible(enabled)


    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        self.setUpdatesEnabled(False)
        super().resizeEvent(a0)
        QTimer.singleShot(100, self._reenable_updates_after_resize)

    def _reenable_updates_after_resize(self) -> None:
        try:
            self.setUpdatesEnabled(True)
        except RuntimeError:
            logging.debug("HelabMainWindow._reenable_updates_after_resize: window has been deleted, skipping.")

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        if self._closing:
            if a0 is not None:
                a0.accept()
            return
        self._closing = True
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

    def handle_exit(self, signum: int, frame: Optional[types.FrameType]) -> None:
        # self.closeEvent(None)
        logging.info("handle_exit: called")
        self.close()
