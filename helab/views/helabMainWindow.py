import logging
import os
import re
import subprocess
import sys

import psutil
from PyQt6.QtCore import Qt, QDir, QSize, QTimer, QThreadPool, QSettings, QEvent, QFileInfo, QItemSelection
from PyQt6.QtGui import QAction, QIcon, QPalette, QColor, QPixmap, QTransform, QCloseEvent
from PyQt6.QtWidgets import QMainWindow, QDockWidget, QStatusBar, QMenuBar, QWidget, QVBoxLayout, QTabWidget, QSplitter, \
    QLabel, QToolBar, QStyle, QSizePolicy, QToolTip, QApplication, QStyleFactory, QFileDialog
from pytablericons import TablerIcons, OutlineIcon

from helab.models.helabFileSystemModel import helabFileSystemModel
from helab.resources.icons import ToolIcons
from helab.views.folderExplorer import FolderExplorer
from helab.views.folderTabsWidget import FolderTabWidget
from helab.views.settingsDialog import SettingsDialog

# TOOLBAR_STYLESHEET_LR = """
# QToolBar {
#     background: none;
#     border: none;
#     spacing: 5px;
# }
# """
TOOLBAR_STYLESHEET_LR = """
QToolBar {
    spacing: 5px;
    padding: 2px;
}
"""


# Function to extract version from setup.py
def get_version() -> str:
    with open('setup.py', 'r', encoding='utf-8') as f:
        content = f.read()
        match = re.search(r'version\s*=\s*[\'"]([^\'"]+)[\'"]', content)
        if match:
            return match.group(1)
    return '0.0.0'  # Default version if not found

def get_git_commit_hash() -> str:
    try:
        commit_hash = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'],
            stderr=subprocess.STDOUT
        ).decode('utf-8').strip()
        return commit_hash[:6].upper()  # Return only the first 6 characters
    except Exception:
        return 'unknown'



APP_VERSION = get_version()
APP_COMMIT_HASH = get_git_commit_hash()



class MainWindow(QMainWindow):
    DEFAULT_WIDTH = 1600
    DEFAULT_HEIGHT = 900

    def __init__(self) -> None:
        super().__init__()


        # current directory is
        logging.debug(f"Current directory is {os.getcwd()}")

        self.process = psutil.Process()
        self.setWindowIcon(QIcon("./helab/resources/icons/ai-icon.icns")) # this doesn't do anything on macos (?)

        self.setWindowTitle(f"HeLab    v{APP_VERSION} ({APP_COMMIT_HASH})")
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
        self.setStatusBar(self.status_bar)
        self.status_bar_message_left = QLabel("Please wait...")
        self.status_bar.addWidget(self.status_bar_message_left)
        # self.status_bar_message_right = QLabel(f"v{APP_VERSION} ({APP_COMMIT_HASH})")
        self.status_bar_message_right = QLabel("GUI initialising...")
        self.status_bar.addPermanentWidget(self.status_bar_message_right)
        self.status_bar_message_right.setToolTip("(App resource usage) / (system total resource usage)")



        # Setup a timer to update the status bar with thread status
        self.status_timer_threadpool = QTimer(self)
        self.status_timer_threadpool.timeout.connect(self.update_status_bar_left)
        self.status_timer_threadpool.start(200)  # Update every 200ms


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
        QTimer.singleShot(15, self.update_tool_enabled_state)
        # QTimer.singleShot(20, self.on_folder_explorer_selection_changed)



    def update_status_bar_left(self) -> None:
        thread_pool = QThreadPool.globalInstance()
        if thread_pool is None:
            logging.error("QThreadPool.globalInstance() returned None.")
            return
        active_threads = thread_pool.activeThreadCount()
        # self.status_bar.showMessage(f"{active_threads}, {QThreadPool.globalInstance().stackSize()}, {len(self.tab_widget.running_workers_status)}")
        queue_depth = len(self.tab_widget.running_workers_status) + len(self.tab_widget.running_workers_deep)
        if queue_depth > 0:
            # transform = QTransform().rotate(self.status_icon_loading_angle)
            # center = self.status_icon_loading.rect().center()
            # transform = QTransform().translate(center.x(), center.y()).rotate(self.status_icon_loading_angle).translate(-center.x(), -center.y())
            # rotated_pixmap = self.status_icon_loading.transformed(transform)
            # self.status_icon.setPixmap(rotated_pixmap)
            # self.status_icon_loading_angle = (self.status_icon_loading_angle + 10) % 360
            self.status_bar_message_left.setText(f"Working: {active_threads}, Queued: {queue_depth}")
            self.action_tab_cancel.setEnabled(True)
            self.tab_widget.set_tab_switching_disable()
            self.set_tools_and_tabs_disable()

        else:
            self.status_bar_message_left.setText(f"Threads Pool Standby")
            # self.status_bar.setPixmap(self.status_icon_checked)
            self.action_tab_cancel.setEnabled(False)
            self.tab_widget.set_tab_switching_enable()
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


    def create_menus(self) -> None:
        # Add menus and actions
        # 
        menu_file = self.menu_bar.addMenu('File')
        if menu_file is not None:
            # Create actions
            open_action = QAction(' Open', self)
            open_action.triggered.connect(self.open_folder_path_dialog)
            exit_action = QAction(' Quit', self)
            exit_action.triggered.connect(self.close)
            menu_action_settings = QAction(' Settings...', self)
            menu_action_settings.triggered.connect(self.show_settings_dialog)


            menu_file.addAction(open_action)
            menu_file.addAction(menu_action_settings)
            menu_file.addSeparator()
            menu_file.addAction(exit_action)
        else :
            logging.error("menu_file is None")

        menu_view = self.menu_bar.addMenu('View')
        if menu_view is not None:
            view_toggle_toolbar_left = QAction('Toggle Left Toolbar', self)
            if (tv := self.sidebar_toolbar_left.toggleViewAction()): view_toggle_toolbar_left.triggered.connect(tv.trigger)
            # view_toggle_toolbar_left.triggered.connect(self.sidebar_toolbar_left.toggleViewAction().trigger)
            menu_view.addAction(view_toggle_toolbar_left)

            view_toggle_toolbar_right = QAction('Toggle Right Toolbar', self)
            if (tv := self.sidebar_toolbar_right.toggleViewAction()): view_toggle_toolbar_right.triggered.connect(tv.trigger)
            # view_toggle_toolbar_right.triggered.connect(self.sidebar_toolbar_right.toggleViewAction().trigger)
            menu_view.addAction(view_toggle_toolbar_right)

            menu_view.addSeparator()

            view_toggle_status_bar = QAction('Toggle Status Bar', self)
            view_toggle_status_bar.triggered.connect(lambda: self.status_bar.setVisible(not self.status_bar.isVisible()))
            menu_view.addAction(view_toggle_status_bar)

            menu_view.addSeparator()

            view_toggle_left_panel = QAction('Toggle Left Panel', self)
            view_toggle_left_panel.triggered.connect(self.toggle_left_panel)
            menu_view.addAction(view_toggle_left_panel)

            view_toggle_right_panel = QAction('Toggle Right Panel', self)
            view_toggle_right_panel.triggered.connect(self.toggle_right_panel)
            menu_view.addAction(view_toggle_right_panel)

        
        menu_debug = self.menu_bar.addMenu('Debug')
        if menu_debug is not None:
            debug_action_1 = QAction('Clear Status Cache', self)
            debug_action_1.triggered.connect(self.tab_widget.clear_status_cache)
            debug_action_2 = QAction('Draw a line in debug console', self)
            debug_action_2.triggered.connect(lambda: logging.debug("="*80))

            menu_debug.addAction(debug_action_1)
            menu_debug.addSeparator()
            menu_debug.addAction(debug_action_2)
        else:
            logging.error("menu_debug is None")
            

    def show_settings_dialog(self) -> None:
        # pass
        settings_dialog = SettingsDialog(self)
        settings_dialog.exec()

    def open_folder_path_dialog(self) -> None:
        options = QFileDialog.Option.ShowDirsOnly
        folder_path = QFileDialog.getExistingDirectory(self, "Select Folder", "", options=options)
        if folder_path:
            # Handle the selected folder path as needed
            # self.current_tab.setPath(folder_path)
            current_tab = self.tab_widget.currentWidget()
            # if hasattr(current_tab, 'setPath'):
            #     current_tab.setPath(folder_path)
            if isinstance(current_tab, FolderExplorer):
                current_tab.open_to_path(folder_path)

    def _setup_central_widgets(self) -> None:
        # Create the main horizontal splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self.splitter)
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background: #d8d8d8;  /* Light gray background for the handle */
            }
            QSplitter::handle:horizontal {
                width: 4px;
            }
            QSplitter::handle:vertical {
                height: 4px;
            }
            QSplitter::handle:hover {
                background: #000000;  /* Darker gray when hovered */
            }
        """)

        self._setup_left_toolbar()
        self._setup_left_side()
        self._setup_right_side()
        self._setup_middle_area()


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

        toggle_left_panel_action = QAction(ToolIcons.ICON_LEFT_COLLAPSE, "Toggle Left Panel", self)
        toggle_left_panel_action.setCheckable(True)
        toggle_left_panel_action.setChecked(True)
        toggle_left_panel_action.triggered.connect(self.toggle_left_panel)
        self.sidebar_toolbar_left.addAction(toggle_left_panel_action)

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

        self.action_tab_new.setToolTip("New Tab")
        self.action_tab_new.setWhatsThis(
            "New Tab??? plz let me know if you see this text")  # literally don't know where this will show up memm
        self.action_tab_refresh.setToolTip("Refresh file list view")
        self.action_tab_folder_up.setToolTip("Navigate up one directory")
        self.action_tab_rescan.setToolTip("Rescan the current directory")
        self.action_tab_cancel.setToolTip("Cancel background tasks")

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

    def _setup_left_side(self) -> None:

        # Create the tab widget and add it to the left panel
        self.tab_widget = FolderTabWidget()
        # self.tab_widget.setTabsClosable(True)
        # self.tab_widget.tabCloseRequested.connect(self.tab_widget.removeTab)
        # left_layout.addWidget(self.tab_widget)
        self.left_splitter.addWidget(self.tab_widget)


        # action_tab_new.triggered.connect(self.tab_widget.add_new_folder_explorer_tab)
        self.action_tab_new.triggered.connect(self.add_new_folder_explorer_tab)
        # action_tab_folder_up.triggered.connect(self.tab_widget.on_back_button_clicked)
        self.action_tab_folder_up.triggered.connect(self.on_back_button_clicked)
        self.action_tab_refresh.triggered.connect(self.tab_widget.refresh_current_folder_explorer)
        self.action_tab_folder_up.setEnabled(self.tab_widget.tab_back_button_enabled)
        self.action_tab_rescan.triggered.connect(self.tab_widget.rescan_current_folder_explorer)

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
        toggle_panel_left_bottom_action = QAction(ToolIcons.ICON_BOTTOM_EXPAND, "Toggle Panel", self)
        toggle_panel_left_bottom_action.setCheckable(True)
        toggle_panel_left_bottom_action.setChecked(True)
        self.sidebar_toolbar_left.addAction(toggle_panel_left_bottom_action)
        toggle_panel_left_bottom_action.triggered.connect(self.toggle_left_bottom_panel)

        # Create a panel below the tab_widget
        self.panel_left_bottom = QWidget()
        self.panel_layout_left_bottom = QVBoxLayout(self.panel_left_bottom)
        self.panel_layout_left_bottom.setContentsMargins(0, 0, 0, 0)
        self.panel_label_left_bottom = QLabel("Left Bottom Placeholder")
        self.panel_label_left_bottom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.panel_layout_left_bottom.addWidget(self.panel_label_left_bottom)
        self.panel_left_bottom.setVisible(True)

        # Add the bottom panel to the left_layout
        # left_layout.addWidget(self.panel_left_bottom)
        self.left_splitter.addWidget(self.panel_left_bottom)
        self.left_splitter.setSizes([400, 100])
        self.splitter.addWidget(self.left_panel)

    def _setup_right_side(self) -> None:
        toggle_right_panel_action = QAction(ToolIcons.ICON_RIGHT_COLLAPSE, "Toggle Right Panel", self)
        toggle_right_panel_action.setCheckable(True)
        toggle_right_panel_action.setChecked(True)
        toggle_right_panel_action.triggered.connect(self.toggle_right_panel)
        self.sidebar_toolbar_right.addAction(toggle_right_panel_action)
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


    def _setup_middle_area(self) -> None:
        # Middle area (main content area)
        self.middle_mainwindow = QMainWindow()
        # Set a central widget for the middle main window
        self.central_placeholder = QLabel("Main Content Area")
        self.central_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.middle_mainwindow.setCentralWidget(self.central_placeholder)

        # Add dock widgets to the middle main window
        dock_widget1 = QDockWidget("Dock Widget 1", self)
        dock_widget_placeholder_label_1 = QLabel("Content of Dock Widget 1")
        dock_widget_placeholder_label_1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dock_widget1.setWidget(dock_widget_placeholder_label_1)
        self.middle_mainwindow.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock_widget1)

        dock_widget2 = QDockWidget("Dock Widget 2", self)
        dock_widget_placeholder_label_2 = QLabel("Content of Dock Widget 2")
        dock_widget_placeholder_label_2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dock_widget2.setWidget(dock_widget_placeholder_label_2)
        self.middle_mainwindow.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock_widget2)

        dock_widget3 = QDockWidget("Dock Widget 3", self)
        dock_widget_placeholder_label_3 = QLabel("Content of Dock Widget 3")
        dock_widget_placeholder_label_3.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dock_widget3.setWidget(dock_widget_placeholder_label_3)
        self.middle_mainwindow.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock_widget3)

        # Add the middle main window to the splitter
        self.splitter.addWidget(self.middle_mainwindow)

        # Keep track of dock widgets
        self.dock_widgets = [dock_widget1, dock_widget2, dock_widget3]

        # Connect signals to check if dock widgets are closed
        for dock_widget in self.dock_widgets:
            dock_widget.visibilityChanged.connect(self.update_placeholder_visibility)
            dock_widget.setStyleSheet("""
                    QDockWidget {
                        background: #f0f0f0;  /* Light gray background */
                        border: 0px solid #cccccc;  /* Light gray border */
                    }
                    QDockWidget::title {
                        background: #e0e0e0;  /* Slightly darker gray for the title */
                        padding: 2px;
                    }
                    QDockWidget::close-button, QDockWidget::float-button {
                        border: none;
                        background: transparent;
                    }
                    QDockWidget::close-button:hover, QDockWidget::float-button:hover {
                        background: #d0d0d0;  /* Darker gray when hovered */
                    }
                    QDockWidget:hover {
                        border: 1px solid #000000;  /* Black border when hovered */
                    }
                """)

        # Initial check to set placeholder visibility
        self.update_placeholder_visibility()


    def update_placeholder_visibility(self) -> None:
        # Check if any dock widgets are visible
        any_visible = any(dock_widget.isVisible() for dock_widget in self.dock_widgets)
        if any_visible:
            self.central_placeholder.hide()
        else:
            self.central_placeholder.show()


    def toggle_left_panel(self, checked: bool) -> None:
        if checked:
            # self.splitter.setSizes([self.left_panel_width, self.splitter.sizes()[1], self.splitter.sizes()[2]])
            self.splitter.setSizes([
                self.left_panel_width,
                # self.splitter.sizes()[1],
                self.width()-self.left_panel_width-self.right_panel_width,
                self.right_panel_width
            ])
            self.sidebar_toolbar_left.actions()[0].setIcon(ToolIcons.ICON_LEFT_COLLAPSE)
        else:
            self.left_panel_width = self.left_panel.width() if self.left_panel.width() > 600 else self.left_panel_width
            self.right_panel_width = self.right_panel.width() if self.right_panel.width() > 300 else self.right_panel_width
            self.splitter.setSizes([0, self.splitter.sizes()[1], self.splitter.sizes()[2]])
            self.sidebar_toolbar_left.actions()[0].setIcon(ToolIcons.ICON_LEFT_EXPAND)

        # Update the bottom panel icon based on its visibility and the state of the left panel
        # if self.panel_left_bottom.isVisible():
        #     self.sidebar_toolbar_left.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_COLLAPSE)
        # else:
        if self.splitter.sizes()[0] == 0:  # Check if the left panel is hidden
            self.sidebar_toolbar_left.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_INACTIVE)
        else:
            if self.panel_left_bottom.isVisible():
                self.sidebar_toolbar_left.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_COLLAPSE)
            else:
                self.sidebar_toolbar_left.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_EXPAND)

    def toggle_left_bottom_panel(self, checked: bool) -> None:
        if checked:
            self.panel_left_bottom.setVisible(True)
            self.sidebar_toolbar_left.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_COLLAPSE)
        else:
            self.panel_left_bottom.setVisible(False)
            if self.splitter.sizes()[0] == 0:  # Check if the left panel is hidden
                self.sidebar_toolbar_left.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_INACTIVE)
            else:
                self.sidebar_toolbar_left.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_EXPAND)

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
        else:
            self.right_panel_width = self.right_panel.width() if self.right_panel.width() > 300 else self.right_panel_width
            self.splitter.setSizes([
                self.splitter.sizes()[0],
                self.width()-self.left_panel_width,
                0
            ])
            self.sidebar_toolbar_right.actions()[0].setIcon(ToolIcons.ICON_RIGHT_EXPAND)

    def toggle_right_bottom_panel(self, checked: bool) -> None:
        if checked:
            self.panel_right_bottom.setVisible(True)
            self.sidebar_toolbar_right.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_COLLAPSE)
        else:
            self.panel_right_bottom.setVisible(False)
            self.sidebar_toolbar_right.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_EXPAND)

    def on_back_button_clicked(self) -> None:
        self.tab_widget.on_back_button_clicked()
        self.action_tab_folder_up.setEnabled(self.tab_widget.tab_back_button_enabled)

    def on_current_tab_changed(self, index: int) -> None:
        # self.tab_widget.on_current_tab_changed(index)
        logging.debug(f"(MainWindow) Current tab changed to index {index}")
        # self.action_tab_folder_up.setEnabled(self.tab_widget.tab_back_button_enabled)
        self.update_tool_enabled_state()
        current_folder_explorer = self.tab_widget.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            # selection_model = current_folder_explorer.get_selection_model()
            # Connect the selectionChanged signal to the slot
            # selection_model.selectionChanged.connect(self.on_folder_explorer_selection_changed)
            current_folder_explorer.emit_selection_changed()


    def on_folder_explorer_selection_changed(self, selected: QItemSelection) -> None:
        # Update the window title with the selected path
        current_folder_explorer = self.tab_widget.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            selected_path = current_folder_explorer.selected_path
            file_info = QFileInfo(selected_path)
            if file_info.isDir():
                folder_name = file_info.fileName()
                self.setWindowTitle(f"HeLab    v{APP_VERSION} ({APP_COMMIT_HASH})    Folder: {folder_name}")
            else:
                self.setWindowTitle(f"HeLab    v{APP_VERSION} ({APP_COMMIT_HASH})    Invalid Path (?)")
                logging.warning(f"on_folder_explorer_selection_changed: not a directory: {selected_path}")
        else:
            self.setWindowTitle(f"HeLab    v{APP_VERSION} ({APP_COMMIT_HASH})    No Folder Selected")

    def add_new_folder_explorer_tab(self) -> None:
        self.tab_widget.add_new_folder_explorer_tab()
        self.update_tool_enabled_state()
        current_folder_explorer = self.tab_widget.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.rootPathChanged.connect(self.update_tool_enabled_state)
            selection_model = current_folder_explorer.get_selection_model()
            selection_model.selectionChanged.connect(self.on_folder_explorer_selection_changed)

    def update_tool_enabled_state(self) -> None:
        current_folder_explorer = self.tab_widget.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.update_back_button_state()
            self.action_tab_folder_up.setEnabled(current_folder_explorer.back_button_enabled)
        else:
            self.action_tab_folder_up.setEnabled(False)

    def set_tools_and_tabs_enable(self) -> None:
        self.action_tab_new.setEnabled(True)
        self.action_tab_folder_up.setEnabled(True)
        self.action_tab_refresh.setEnabled(True)
        self.action_tab_rescan.setEnabled(True)

    def set_tools_and_tabs_disable(self) -> None:
        self.action_tab_new.setEnabled(False)
        self.action_tab_folder_up.setEnabled(False)
        self.action_tab_refresh.setEnabled(False)
        self.action_tab_rescan.setEnabled(False)




    def closeEvent(self, a0: QCloseEvent | None) -> None:
        logging.info("MainWindow closeEvent")

        # Save settings
        # settings = QSettings("ANU", "HeLab")
        # settings.setValue("geometry", self.saveGeometry())
        # settings.setValue("windowState", self.saveState())
        # super().closeEvent(a0)
        pass







