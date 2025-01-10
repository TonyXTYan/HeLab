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
from typing import List, Optional

import psutil
from PyQt6.QtCore import Qt, QSize, QTimer, QThreadPool, QFileInfo, QItemSelection, QModelIndex, QUrl, QEvent, QPoint, \
    QDir, QDateTime, QSettings
from PyQt6.QtGui import QAction, QIcon, QCloseEvent, QPixmap, QResizeEvent
from PyQt6.QtWidgets import QMainWindow, QDockWidget, QStatusBar, QMenuBar, QWidget, QVBoxLayout, QSplitter, \
    QLabel, QToolBar, QSizePolicy, QFileDialog, QToolTip, QMenu, QApplication, QCheckBox
from humanfriendly.terminal import message
from numpy.f2py.crackfortran import include_paths

from helab.resources.icons import ToolIcons
from helab.utils.cachingSetup import status_cache, hasChildren_cache
from helab.utils.constants import *
# from helab.utils.os_cached import , os_scandir_cache, os_isdir_cache, os_listdir, os_scandir, os_isdir, os_scandir_cache
from helab.utils.os_cached import *
from helab.utils.cachingSetup import *
from helab.utils.threadingSetup import *
from helab.views.folderExplorer import FolderExplorer
from helab.views.folderTabsWidget import FolderTabWidget
from helab.views.memoryUsageWindow import MemoryUsageWindow
from helab.views.settingsDialog import SettingsDialog
from helab.views.debugIcons import DebugIconsWindow

from PyQt6.QtWebEngineWidgets import QWebEngineView
# sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'scripts'))
# from helab.scripts.legacy_plotly.scattering_proj_monitori_dld import fig_txt_density
import plotly


# noinspection PyUnresolvedReferences
class MainWindow(QMainWindow):
    DEFAULT_WIDTH = 1600
    DEFAULT_HEIGHT = 900

    # noinspection PyUnresolvedReferences
    def __init__(self) -> None:
        super().__init__()
        logging.debug(f"Current directory is {CURRENT_WORKING_DIRECTORY}")
        if not os.path.exists(DIR_TEMPS): os.makedirs(DIR_TEMPS)

        self.current_tracking_folder_path = '/'
        self.named_temp_files: List[tempfile._TemporaryFileWrapper[bytes]] = []


        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGTERM, self.handle_exit)

        # current directory is

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

        # Create Menubar
        menubar = self.menuBar()
        if menubar is None:
            logging.fatal("QMainWindow.menuBar() returned None.")
            sys.exit(1)
        self.menu_bar: QMenuBar = menubar
        self.create_menus()

        # Create Status Bar
        self.status_bar.setStyleSheet("QStatusBar { border-top: 1px solid #d8d8d8; }")

        # status_bar_padding = QWidget()
        # status_bar_padding.setMaximumWidth(2)
        # self.status_bar.addWidget(status_bar_padding)
        #
        # self.status_bar_checkbox = QCheckBox("")
        # self.status_bar_checkbox.setChecked(True)
        # self.status_bar_checkbox.setToolTip("Toggle threads status pop up info visibility")
        # self.status_bar.addWidget(self.status_bar_checkbox)


        self.setStatusBar(self.status_bar)
        self.status_bar_message_left = QLabel("...")
        self.status_bar.addWidget(self.status_bar_message_left)
        self.status_bar_message_right = QLabel(f"Please wait. GUI loading... v{APP_VERSION} ({APP_COMMIT_HASH})")

        # status_bar_left_spacer = QWidget()
        # status_bar_left_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # self.status_bar.addWidget(status_bar_left_spacer)

        # self.status_bar_message_middle = QLabel(f"HeLab v{APP_VERSION} ({APP_COMMIT_HASH})")
        # self.status_bar_message_middle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # self.status_bar.addWidget(self.status_bar_message_middle)

        # status_bar_right_spacer = QWidget()
        # status_bar_right_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # self.status_bar.addWidget(status_bar_right_spacer)

        # self.status_bar_message_right = QLabel("GUI initialising...")
        self.status_bar.addPermanentWidget(self.status_bar_message_right)
        self.status_bar_message_right.setToolTip("(App resource usage) / (system total resource usage)")

        # self.status_bar_message_left.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        # self.status_bar_message_middle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # self.status_bar_message_right.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)


        # Setup a timer to update the status bar with thread status
        self.status_timer_thread_status = QTimer(self)
        self.status_timer_thread_status.timeout.connect(self.update_status_bar_left)
        self.status_timer_thread_status.start(200)  # Update every 200ms
        self.status_timer_threadpool_hang_counts = 0
        self.status_timer_threadpool_hang_timestamp: Optional[QDateTime] = None


        self.status_timer_cpu_ram = QTimer(self)
        self.status_timer_cpu_ram.timeout.connect(self.update_status_bar_right)
        self.status_timer_cpu_ram.start(1000)  # Update every 1000ms

        # self.status_icon_loading = QPixmap(TablerIcons.load(OutlineIcon.LOADER_2,color='000000').toqpixmap().scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        # self.status_icon_loading_angle = 0
        # self.status_icon_checked = QPixmap(TablerIcons.load(OutlineIcon.CIRCLE_CHECK, color='005500').toqpixmap().scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        # self.status_icon = QLabel()
        # self.status_bar.addPermanentWidget(self.status_icon)

        # self.update_status_bar_left()
        # self.update_status_bar_right()

        # Create Left Panel (File Tree View)
        # self.setup_file_tree_view()
        self.tab_widget.currentChanged.connect(self.on_current_tab_changed)
        # self.tab_widget.add_new_folder_explorer_tab()
        # self.add_new_folder_explorer_tab()
        # Delay the execution of add_new_folder_explorer_tab until the GUI is loaded
        QTimer.singleShot(10, self.add_new_folder_explorer_tab)
        QTimer.singleShot(50, self.update_tool_enabled_state)
        # QTimer.singleShot(20, self.on_folder_explorer_selection_changed)
        QTimer.singleShot(100, self.action_tab_refresh.trigger)



    def update_status_bar_left(self) -> None:
        active_threads = all_pools_total_activeThreadCount()
        # self.status_bar.showMessage(f"{active_threads}, {QThreadPool.globalInstance().stackSize()}, {len(self.tab_widget.running_workers_status)}")
        # queue_depth = len(self.tab_widget.running_workers_status) + len(self.tab_widget.running_workers_deep) + len(self.tab_widget.running_workers_hasChildren)
        queue_depths = running_worker_queues_len()

        if not self.isActiveWindow():
            QToolTip.hideText()

        # def _cache_status_stirng_old_cachetools() -> str:
        #     # return "TODO"
        #     cache_str = "Cache status:\n"
        #     cache_str += f"  tab_widget.status_cache:      {len(self.tab_widget.status_cache)} items\n"
        #     cache_str += f"  tab_widget.hasChildren_cache: {len(self.tab_widget.hasChildren_cache)} items\n"
        #     cache_str += f"  os_listdir_cache: {os_listdir.cache_info()}\n"           # type: ignore[attr-defined]
        #     cache_str += f"  os_scandir_cache: {os_scandir_list.cache_info()}\n"      # type: ignore[attr-defined]
        #     cache_str += f"  os_isdir_cache:   {os_isdir.cache_info()}\n"             # type: ignore[attr-defined]
        #     return cache_str

        tooltip_string = "Threadpool status: "
        if sum(queue_depths) > 0:
            indicator_dot = INDICATOR_DOTS[self.status_timer_threadpool_hang_counts % 10]

            self.status_bar_message_left.setText(f" {indicator_dot} Active: {active_threads}, Queued: {queue_depths}")
            self.action_tab_cancel.setEnabled(True)
            self.tab_widget.set_tab_switching_disable()
            self.set_tools_and_tabs_disable()

            tooltip_string += "\n"
            tooltip_string += f"  Number of active threads in threadpool: {active_threads}\n"
            tooltip_string += f"  Number of queued threads with tracking: {sum(queue_depths)}\n\n"

            def make_tooltip_string(worker_name: str, worker_keys: List[str]) -> str:
                tooltip_string = ""
                if len(worker_keys) > 3:
                    tooltip_string += f"  {worker_name} working on: \n"
                    for key in worker_keys[:3]:
                        tooltip_string += f"    {key}\n"
                    tooltip_string += f"    ... and {len(worker_keys)-3} more\n"
                elif len(worker_keys) > 0:
                    tooltip_string += f"  {worker_name} working on: \n"
                    for key in worker_keys:
                        tooltip_string += f"    {key}\n"
                else:
                    tooltip_string += f"  {worker_name} is empty\n"
                tooltip_string += "\n"
                return tooltip_string

            tooltip_string += make_tooltip_string("running_workers_status", list(running_workers_status.keys()))
            tooltip_string += make_tooltip_string("running_workers_deep", list(running_workers_deep.keys()))
            tooltip_string += make_tooltip_string("running_workers_hasChildren", list(running_workers_hasChildren.keys()))
            tooltip_string += make_tooltip_string("running_workers_ramLoading", list(running_workers_ramLoading.keys()))

            tooltip_string += cache_status_string()

            self.status_bar_message_left.setToolTip(tooltip_string)
            # self.status_bar_message_left.installEventFilter(self)
            tooltip_string_num_lines = len(tooltip_string.split("\n"))

            if self.status_timer_threadpool_hang_counts == 0:
                self.status_timer_threadpool_hang_timestamp = QDateTime.currentDateTime()
            self.status_timer_threadpool_hang_counts += 1

            if (self.isActiveWindow()
                # and self.status_bar_checkbox.isChecked()
                and self.view_toggle_thread_status.isChecked()  # type: ignore[has-type] # I personally guarantee this is fine
                and (self.status_timer_threadpool_hang_counts >= 10
                  or  (self.status_timer_threadpool_hang_timestamp is not None
                    and QDateTime.currentDateTime().toSecsSinceEpoch() - self.status_timer_threadpool_hang_timestamp.toSecsSinceEpoch() > 3)
            )):
                QToolTip.showText(self.status_bar_message_left.mapToGlobal(
                    QPoint(40, -60 + self.status_bar_message_left.height() - round(tooltip_string_num_lines * 15) ) ),
                    tooltip_string,
                    self.status_bar_message_left)
            # if self.status_timer_threadpool_hang_counts >= 50:
            #     # at least 50*0.2 = 10 seconds
            #     logging.warning("Long compute time detected, GUI may be unresponsive")
            #     logging.warning(f"Tooltip string: \n{tooltip_string}")
            #
            else:
                # QToolTip.hideText()
                pass

        else:
            tooltip_string += "all done\n"
            tooltip_string += "No active threads in threadpool\n"
            tooltip_string += cache_status_string()
            self.status_bar_message_left.setToolTip(tooltip_string)
            self.status_bar_message_left.setText(f" Threads Pool Standby")
            # self.status_bar_message_left.setToolTip("No active threads in threadpool")
            if self.status_timer_threadpool_hang_counts > 0:
                self.status_timer_threadpool_hang_counts = 0
                self.status_timer_threadpool_hang_timestamp = None
                QToolTip.hideText()
            # self.status_bar.setPixmap(self.status_icon_checked)
            self.action_tab_cancel.setEnabled(False)
            self.tab_widget.set_tab_switching_enable()
            if not self.action_tab_live_checked:
                self.set_tools_and_tabs_enable()

    def update_status_bar_right(self) -> None:
        # Update the right message with CPU and RAM usage
        cpu_usage_app = self.process.cpu_percent()
        cpu_usage_total = sum(psutil.cpu_percent(percpu=True))
        ram_usage_app = self.process.memory_info().rss  # in bytes
        ram_usage_total = psutil.virtual_memory().used  # total used RAM in bytes
        ram_usage_app_gb = ram_usage_app / (1024 ** 3)
        ram_usage_total_gb = ram_usage_total / (1024 ** 3)

        # Update the status bar message
        self.status_bar_message_right.setText(
            f"CPU {cpu_usage_app:.1f}% / {cpu_usage_total:.1f}%   RAM {ram_usage_app_gb:.1f}GB / {ram_usage_total_gb:.1f}GB")

        # self.status_bar_message_right.setToolTip("(App resource usage) / (system total resource usage)")

    # noinspection PyUnresolvedReferences
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
                open_drives_action = QMenu(' Open Drives', self)
                drives = QDir.drives()
                for drive in drives:
                    drive_path = drive.absolutePath()
                    action_drive = QAction(drive_path, self)
                    # model_root_path = model_root_path = os.path.splitdrive(drive_path)[0] + os.sep
                    logging.debug(f"create_menus: drives submenu added {drive_path = }")
                    # action_drive.triggered.connect(lambda _,dp = drive_path: self.tab_widget.add_new_folder_explorer_tab(
                    #     model_root_path=dp,
                    #     view_path=dp,
                    #     target_path=dp,
                    #     set_initial_expand_to_parent_level=False,
                    # ))
                    action_drive.triggered.connect(lambda _,dp = drive_path: self.add_new_folder_explorer_tab(
                        model_root_path = dp,
                        view_path = dp,
                        target_path = dp,
                        set_initial_expand_to_parent_level = False,
                    ))
                    open_drives_action.addAction(action_drive)
                menu_file.addMenu(open_drives_action)


            menu_file.addSeparator()

            menu_action_settings = QAction(' Settings...', self)
            menu_action_settings.triggered.connect(self.show_settings_dialog)
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

            settings = QSettings("ANU", "HeLab")
            self.view_toggle_thread_status = QAction('Toggle Thread Status Auto Pop-up', self)
            self.view_toggle_thread_status.setCheckable(True)
            self.view_toggle_thread_status.setChecked(settings.value("view_toggle_thread_status", type=bool, defaultValue=True))
            self.view_toggle_thread_status.triggered.connect(lambda checked: settings.setValue("view_toggle_thread_status", checked))
            menu_view.addAction(self.view_toggle_thread_status)

            menu_view.addSeparator()

            self.view_toggle_auto_load_ram = QAction('Toggle Auto Load to RAM', self)
            self.view_toggle_auto_load_ram.setCheckable(True)
            self.view_toggle_auto_load_ram.setChecked(True)
            self.view_toggle_auto_load_ram.triggered.connect(self.toggle_auto_load_ram)
            menu_view.addAction(self.view_toggle_auto_load_ram)

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
            debug_action_1 = QAction('Clear Status Cache', self)
            debug_action_1.triggered.connect(self.tab_widget.clear_status_cache)
            debug_action_2 = QAction('Draw a line in debug console', self)
            debug_action_2.triggered.connect(lambda: logging.debug("="*80))

            menu_debug.addAction(debug_action_1)
            menu_debug.addSeparator()
            menu_debug.addAction(debug_action_2)

            menu_debug.addSeparator()

            action_debug_icons = QAction("Show all Icons", self)
            action_debug_icons.triggered.connect(self.show_debug_icons_window)
            menu_debug.addAction(action_debug_icons)

            action_debug_memory_usage_window = QAction('Show Memory Usage', self)
            action_debug_memory_usage_window.triggered.connect(self.show_memory_usage_window)
            menu_debug.addAction(action_debug_memory_usage_window)

            menu_debug.addSeparator()

            action_debug_3 = QAction('Debug 3', self)
            action_debug_3.triggered.connect(self.action_debug_3_run)
            menu_debug.addAction(action_debug_3)


            action_debug_4 = QAction('Debug 4', self)
            action_debug_4.triggered.connect(self.action_debug_4_run)
            menu_debug.addAction(action_debug_4)

            action_debug_gc_collect = QAction('gc.collect()', self)
            action_debug_gc_collect.triggered.connect(gc.collect)
            menu_debug.addAction(action_debug_gc_collect)



        else:
            logging.error("menu_debug is None")
            
    def action_debug_3_run(self) -> None:
        logging.info("action_debug_3_run: called")
        logging.info(f"{os_listdir_cache.__dict__}")
        logging.info(f"_os_listdir_cache = {os_listdir_cache.__dict__}")

        pass

    def action_debug_4_run(self) -> None:
        current_file_explorer = self.tab_widget.currentWidget()
        if isinstance(current_file_explorer, FolderExplorer):
            logging.info(f"{current_file_explorer.model.rootPath() = }")
            rows = current_file_explorer.model.get_visible_rows()
            for r in rows:
                logging.info(f"{r = }")


    def show_settings_dialog(self) -> None:
        # pass
        self.settings_dialog = SettingsDialog(self)
        self.settings_dialog.exec()

    def show_memory_usage_window(self) -> None:
        self.memory_usage_window = MemoryUsageWindow()
        self.memory_usage_window.show()

    def show_debug_icons_window(self) -> None:
        self.debug_icons_window = DebugIconsWindow()
        self.debug_icons_window.show()

    def open_folder_path_dialog(self) -> None:
        options = QFileDialog.Option.ShowDirsOnly
        folder_path = QFileDialog.getExistingDirectory(self, "Select Folder", "", options=options)
        logging.debug(f"open_folder_path_dialog: selected {folder_path = }")
        if folder_path:
            # Handle the selected folder path as needed
            # self.current_tab.setPath(folder_path)
            # current_tab = self.tab_widget.currentWidget()
            # if hasattr(current_tab, 'setPath'):
            #     current_tab.setPath(folder_path)
            # if isinstance(current_tab, FolderExplorer):
            #     current_tab.open_to_path(folder_path)

            model_root_path = os.path.splitdrive(folder_path)[0] + os.sep
            logging.info(f"open_folder_path_dialog: {model_root_path = }")

            # self.tab_widget.add_new_folder_explorer_tab(
            #     model_root_path = model_root_path,
            #     view_path = folder_path,
            #     target_path = folder_path,
            #     set_initial_expand_to_parent_level = False,
            # )
            self.add_new_folder_explorer_tab(
                model_root_path = model_root_path,
                view_path = folder_path,
                target_path = folder_path,
                set_initial_expand_to_parent_level = False,
            )
        else:
            logging.debug("open_folder_path_dialog: no folder selected")

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
        # Create a splitter to hold the tab_widget and panel_left_bottom
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
        self.action_tab_rescan = QAction(ToolIcons.ICON_ZOOM_REPLACE, "Rescan", self)
        self.action_tab_cancel = QAction(ToolIcons.ICON_ZOOM_CANCEL, "Cancel", self)
        self.action_tab_live = QAction(ToolIcons.ICON_LIVE, "Live", self)
        self.action_tab_live.setCheckable(True)
        self.action_tab_live_checked = False
        self.action_tab_live_was_left_panel_open_before_clicking_live = True

        self.action_tab_new.setToolTip("New Tab")
        self.action_tab_new.setWhatsThis(
            "New Tab??? plz let me know if you see this text")  # literally don't know where this will show up memm
        # self.action_tab_new.set
        self.action_tab_refresh.setToolTip("Refresh file list view")
        self.action_tab_folder_up.setToolTip("Navigate up one directory")
        self.action_tab_rescan.setToolTip("Rescan the current directory")
        self.action_tab_cancel.setToolTip("Cancel background tasks")
        self.action_tab_live.setToolTip("Live update the current directory")

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
        self.sidebar_toolbar_left.addAction(self.action_tab_rescan)
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
        self.action_tab_rescan.triggered.connect(self.tab_widget.rescan_current_folder_explorer)
        self.action_tab_cancel.triggered.connect(self.tab_widget.on_stop_button_clicked)
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
        self.toggle_panel_left_bottom_action = QAction(ToolIcons.ICON_BOTTOM_EXPAND, "Toggle Panel", self)
        self.toggle_panel_left_bottom_action.setCheckable(True)
        self.toggle_panel_left_bottom_action.setChecked(True)
        self.sidebar_toolbar_left.addAction(self.toggle_panel_left_bottom_action)
        self.toggle_panel_left_bottom_action.triggered.connect(self.toggle_left_bottom_panel)

        # Create a panel below the tab_widget
        self.panel_left_bottom = QWidget()
        self.panel_layout_left_bottom = QVBoxLayout(self.panel_left_bottom)
        self.panel_layout_left_bottom.setContentsMargins(0, 0, 0, 0)
        self.panel_label_left_bottom = QLabel("Left Bottom Placeholder\n"+"Folder grouping and statistics (?)")
        self.panel_label_left_bottom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.panel_layout_left_bottom.addWidget(self.panel_label_left_bottom)
        self.panel_left_bottom.setVisible(True)

        # Add the bottom panel to the left_layout
        # left_layout.addWidget(self.panel_left_bottom)
        self.left_splitter.addWidget(self.panel_left_bottom)
        self.left_splitter.setSizes([400, 100])
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

        right_top_widget = QLabel("Right Top Placeholder")
        right_top_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Right bottom panel
        self.panel_right_bottom = QWidget()
        self.panel_layout_right_bottom = QVBoxLayout(self.panel_right_bottom)
        self.panel_layout_right_bottom.setContentsMargins(0, 0, 0, 0)
        self.panel_label_right_bottom = QLabel("Right Bottom Placeholder")
        self.panel_label_right_bottom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.panel_layout_right_bottom.addWidget(self.panel_label_right_bottom)
        self.panel_right_bottom.setVisible(True)
        # Add the bottom panel to the right_layout
        # Add a button to the bottom of sidebar_toolbar_right
        toggle_right_bottom_panel_action = QAction(ToolIcons.ICON_BOTTOM_EXPAND, "Toggle Right Bottom Panel", self)
        toggle_right_bottom_panel_action.setCheckable(True)
        toggle_right_bottom_panel_action.setChecked(True)
        toggle_right_bottom_panel_action.triggered.connect(self.toggle_right_bottom_panel)
        self.sidebar_toolbar_right.addAction(toggle_right_bottom_panel_action)

        self.right_splitter.addWidget(right_top_widget)
        self.right_splitter.addWidget(self.panel_right_bottom)
        self.right_splitter.setSizes([400, 300])

        # Add the right panel to the splitter
        self.splitter.addWidget(self.right_panel)


    # REVIEW: these can be moved somewhere else
    # def plotly_to_dock_widget(self, plotly_fig: plotly.graph_objs.Figure, dock_widget_title: str) -> (tempfile.NamedTemporaryFile, QDockWidget):
    def _setup_legacy_plotly_to_dock_widget(self, plotly_fig: plotly.graph_objs.Figure, dock_widget_title: str) -> None:
        plotly_fig_html = plotly_fig.to_html()
        plotly_view = QWebEngineView()
        plotly_temp = tempfile.NamedTemporaryFile(prefix="plotly_", suffix='.html', dir=DIR_TEMPS)
        self.named_temp_files.append(plotly_temp)
        plotly_temp.write(plotly_fig_html.encode('utf-8'))
        plotly_temp_html_filename = plotly_temp.name
        logging.debug(f"plotly_to_dock_widget: title: {dock_widget_title}, tempfile: {plotly_temp_html_filename}")
        plotly_view.load(QUrl.fromLocalFile(plotly_temp_html_filename))
        plotly_dock_widget = QDockWidget(dock_widget_title, self)
        plotly_dock_widget.setWidget(plotly_view)
        # return plotly_temp, plotly_dock_widget
        self.middle_mainwindow.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, plotly_dock_widget)
        self.dock_widgets.append(plotly_dock_widget)
        # self.named_temp_files.append(plotly_temp)


    def _setup_middle_area(self) -> None:
        # Middle area (main content area)
        self.middle_mainwindow = QMainWindow()
        # Set a central widget for the middle main window
        self.central_placeholder = QLabel("Main Content Area")
        self.central_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.middle_mainwindow.setCentralWidget(self.central_placeholder)
        self.dock_widgets: List[QDockWidget] = []

        try:
            from helab.scripts.legacy_plotly.scattering_proj_monitori_dld import fig_txt_density, fig_txy_3d, fig_shots_scan, fig_pulse_eff_fitted, fig_shots_transfer
            self._setup_legacy_plotly_to_dock_widget(fig_txt_density, "fig_txt_density")
            self._setup_legacy_plotly_to_dock_widget(fig_txy_3d, "fig_txy_3d")
            self._setup_legacy_plotly_to_dock_widget(fig_shots_scan, "fig_shots_scan")
            self._setup_legacy_plotly_to_dock_widget(fig_shots_transfer, "fig_shots_transfer")
            self._setup_legacy_plotly_to_dock_widget(fig_pulse_eff_fitted, "fig_pulse_eff_fitted")
        except Exception as e:
            logging.error(f"Failed to load legacy_plotly.scattering_proj_monitori_dld: {e}")
            # Add placeholder dock widgets to the middle main window
            dock_widget1 = QDockWidget("Dock Widget 1", self)
            dock_widget_placeholder_label_1 = QLabel("Content of Dock Widget 1")
            dock_widget_placeholder_label_1.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dock_widget1.setWidget(dock_widget_placeholder_label_1)
            self.middle_mainwindow.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock_widget1)
            self.dock_widgets.append(dock_widget1)

            dock_widget2 = QDockWidget("Dock Widget 2", self)
            dock_widget_placeholder_label_2 = QLabel("Content of Dock Widget 2")
            dock_widget_placeholder_label_2.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dock_widget2.setWidget(dock_widget_placeholder_label_2)
            self.middle_mainwindow.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock_widget2)
            self.dock_widgets.append(dock_widget2)

            dock_widget3 = QDockWidget("Dock Widget 3", self)
            dock_widget_placeholder_label_3 = QLabel("Content of Dock Widget 3")
            dock_widget_placeholder_label_3.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dock_widget3.setWidget(dock_widget_placeholder_label_3)
            self.middle_mainwindow.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock_widget3)
            self.dock_widgets.append(dock_widget3)


        # Add the middle main window to the splitter
        self.splitter.addWidget(self.middle_mainwindow)

        # Keep track of dock widgets
        # self.dock_widgets = [dock_widget1, dock_widget2, dock_widget3, txy_density_dock_widget]

        # Connect signals to check if dock widgets are closed
        for dock_widget in self.dock_widgets:
            dock_widget.visibilityChanged.connect(self.update_placeholder_visibility)
            # dock_widget.
            dock_widget.setStyleSheet(QDOCKWIDGET_STYLESHEET)

        # Initial check to set placeholder visibility
        self.update_placeholder_visibility()


    def update_placeholder_visibility(self) -> None:
        # Check if any dock widgets are visible
        logging.debug(f"update_placeholder_visibility: called")
        any_visible = any(dock_widget.isVisible() for dock_widget in self.dock_widgets)
        if any_visible:
            self.central_placeholder.hide()
        else:
            self.central_placeholder.show()


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
        # if self.panel_left_bottom.isVisible():
        #     self.toggle_panel_left_bottom_action.setIcon(ToolIcons.ICON_BOTTOM_COLLAPSE)
        # else:
        if self.splitter.sizes()[0] == 0:  # Check if the left panel is hidden
            self.toggle_panel_left_bottom_action.setIcon(ToolIcons.ICON_BOTTOM_INACTIVE)
            self.toggle_panel_left_bottom_action.setChecked(False)
        else:
            if self.panel_left_bottom.isVisible():
                self.toggle_panel_left_bottom_action.setIcon(ToolIcons.ICON_BOTTOM_COLLAPSE)
                self.toggle_panel_left_bottom_action.setChecked(True)
            else:
                self.toggle_panel_left_bottom_action.setIcon(ToolIcons.ICON_BOTTOM_EXPAND)
                self.toggle_panel_left_bottom_action.setChecked(False)

    def on_splitter_moved(self, pos: int, index: int) -> None:
        # Update the left panel width when the splitter is moved
        # self.left_panel_width = self.splitter.sizes()[0]
        # self.right_panel_width = self.splitter.sizes()[2]
        logging.debug(f"on_splitter_moved: {pos = }, {index = }, {self.splitter.sizes() = }")

        if self.splitter.sizes()[0] == 0:  # Check if the left panel is hidden
            self.toggle_left_panel_action.setIcon(ToolIcons.ICON_LEFT_EXPAND)
            self.toggle_left_panel_action.setChecked(False)
            self.toggle_panel_left_bottom_action.setIcon(ToolIcons.ICON_BOTTOM_INACTIVE)
            self.toggle_panel_left_bottom_action.setChecked(False)
            self.view_toggle_left_panel.setChecked(False)
        else:
            self.toggle_left_panel_action.setIcon(ToolIcons.ICON_LEFT_COLLAPSE)
            self.toggle_left_panel_action.setChecked(True)
            self.view_toggle_left_panel.setChecked(True)
            if self.panel_left_bottom.isVisible():
                self.toggle_panel_left_bottom_action.setIcon(ToolIcons.ICON_BOTTOM_COLLAPSE)
                self.toggle_panel_left_bottom_action.setChecked(True)
            else:
                self.toggle_panel_left_bottom_action.setIcon(ToolIcons.ICON_BOTTOM_EXPAND)
                self.toggle_panel_left_bottom_action.setChecked(False)

    def toggle_left_bottom_panel(self, checked: bool) -> None:
        if checked:
            self.panel_left_bottom.setVisible(True)
            self.toggle_panel_left_bottom_action.setIcon(ToolIcons.ICON_BOTTOM_COLLAPSE)

        else:
            self.panel_left_bottom.setVisible(False)
            if self.splitter.sizes()[0] == 0:  # Check if the left panel is hidden
                self.toggle_panel_left_bottom_action.setIcon(ToolIcons.ICON_BOTTOM_INACTIVE)
            else:
                self.toggle_panel_left_bottom_action.setIcon(ToolIcons.ICON_BOTTOM_EXPAND)

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
            self.panel_right_bottom.setVisible(True)
            self.sidebar_toolbar_right.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_COLLAPSE)
        else:
            self.panel_right_bottom.setVisible(False)
            self.sidebar_toolbar_right.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_EXPAND)

    def on_back_button_clicked(self) -> None:
        self.tab_widget.on_back_button_clicked()
        logging.debug(f"heLabMainWindow.on_back_button_clicked: {self.tab_widget.tab_back_button_enabled = }")
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


    def on_folder_explorer_selection_changed(self, selected: QItemSelection) -> None:
        # Update the window title with the selected path
        current_folder_explorer = self.tab_widget.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            selected_path = current_folder_explorer.selected_path
            file_info = QFileInfo(selected_path)
            if file_info.isDir():
                folder_name = file_info.fileName()
                logging.debug(f"on_folder_explorer_selection_changed: {selected_path = }, {folder_name = }")
                self.current_tracking_folder_path = selected_path
                if folder_name == '':
                    self.setWindowTitle(f"HeLab  -  {selected_path}")
                else:
                    self.setWindowTitle(f"HeLab  -  {folder_name}")
            else:
                self.setWindowTitle(f"HeLab    Invalid Path (?)")
                logging.warning(f"on_folder_explorer_selection_changed: not a directory: {selected_path}")
        else:
            self.setWindowTitle(    f"HeLab    No Folder Selected")
        logging.debug(f"on_folder_explorer_selection_changed: done")

    def add_new_folder_explorer_tab(self,
                                    model_root_path: str|None = None,
                                    view_path: str|None = None,
                                    target_path: str|None = None,
                                    set_initial_expand_to_parent_level:bool = True,
                                    ) -> None:
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
            current_folder_explorer.rootPathChanged.connect(self.update_tool_enabled_state)
            logging.debug(f"add_new_folder_explorer_tab: {current_folder_explorer.selected_path = }")
            selection_model = current_folder_explorer.get_selection_model()
            selection_model.selectionChanged.connect(self.on_folder_explorer_selection_changed)
        else:
            logging.error("add_new_folder_explorer_tab: current_folder_explorer is not FolderExplorer")

    def update_tool_enabled_state(self) -> None:
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

    def toggle_auto_load_ram(self) -> None:
        toggled_on = self.view_toggle_auto_load_ram.isChecked()
        logging.debug(f"toggle_auto_load_ram: called {toggled_on = }")
        current_folder_explorer = self.tab_widget.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.auto_load_ram = toggled_on
        else:
            logging.error("toggle_auto_load_ram: current_folder_explorer is not FolderExplorer")


    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        self.setUpdatesEnabled(False)
        super().resizeEvent(a0)
        QTimer.singleShot(100, lambda: self.setUpdatesEnabled(True))

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        logging.info("MainWindow closeEvent")

        cancel_all_workers()

        for temp_file in self.named_temp_files:
            temp_file.close()

        for dock_widget in self.dock_widgets:
            dock_widget.close()

        self.tab_widget.closeEvent(a0)

        os_listdir_cache.close()
        os_scandir_cache.close()
        os_isdir_cache.close()
        status_cache.close()
        hasChildren_cache.close()

        # Save settings
        # settings = QSettings("ANU", "HeLab")
        # settings.setValue("geometry", self.saveGeometry())
        # settings.setValue("windowState", self.saveState())
        # super().closeEvent(a0)

        logging.info("MainWindow closeEvent done")
        QApplication.quit()
        pass

    def handle_exit(self, signum: int, frame: Optional[types.FrameType]) -> None:
        # self.closeEvent(None)
        logging.info("handle_exit: called")
        self.close()





