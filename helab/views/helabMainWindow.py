import logging
import os

from PyQt6.QtCore import Qt, QDir
from PyQt6.QtGui import QAction, QIcon, QPalette, QColor
from PyQt6.QtWidgets import QMainWindow, QDockWidget, QStatusBar, QMenuBar, QWidget, QVBoxLayout, QTabWidget, QSplitter, \
    QLabel, QToolBar, QStyle
from pytablericons import TablerIcons, OutlineIcon

from helab.models.helabFileSystemModel import CustomFileSystemModel
from helab.resources.icons import ToolIcons
from helab.views.folderExplorer import FolderExplorer


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle('HeLab')
        self.resize(1800, 1000)

        # Create Menubar
        self.menu_bar = self.menuBar()
        self.create_menus()

        # Create Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Create Central Widget Area with Dock Widgets
        self.setup_central_widgets()

        # Create Left Panel (File Tree View)
        self.setup_file_tree_view()

    def create_menus(self):
        # Add menus and actions
        file_menu = self.menu_bar.addMenu('File')
        # Create actions
        open_action = QAction('Open', self)
        exit_action = QAction('Exit', self)
        exit_action.triggered.connect(self.close)
        # Add actions to the menu
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        file_menu.addAction(exit_action)

        # Similarly, create other menus

    def setup_central_widgets_old(self):
        # You can set a central widget or use dock widgets
        # pass
        # Example: Create a central widget with multiple dock widgets
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # Create the main layout
        central_layout = QVBoxLayout(self.central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)

        # Create a QSplitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Create and add the toolbar
        toolbar = QToolBar("Main Toolbar", self)
        toolbar.setContentsMargins(0,0,0,0)
        random_icon = QIcon(TablerIcons.load(OutlineIcon.SQUARE_ROUNDED_PLUS, color='000000').toqpixmap().scaled(64, 64,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        # random_icon = QIcon(TablerIcons.load(OutlineIcon.SQUARE_ROUNDED_PLUS, color='000000').toqpixmap())
        action_new = QAction(random_icon, "New", self)
        action_open = QAction("Open", self)
        action_new.setToolTip("This thing is for...")
        toolbar.addAction(action_new)
        toolbar.addAction(action_open)
        central_layout.addWidget(toolbar)
        toolbar.setStyleSheet("""
                    QToolBar {
                        background: #e5e5e5;
                        border: none;
                        spacing: 5px;
                    }
                    QToolButton {
                        background: none;
                        border: none;
                        padding: 5px;
                    }
                    QToolButton:hover {
                        background: #d4d4d4;
                    }
                """)

        # Create the tab widget and add it to the central layout
        self.tab_widget = QTabWidget()
        # self.tab_widget.setMinimumWidth(300)
        # self.tab_widget.setMinimumHeight(300)
        # self.tab_widget.resize(300, self.tab_widget.height())
        central_layout.addWidget(self.tab_widget)
        self.tab_widget.resize(600, self.tab_widget.height())  # Set initial width to 400 pixels

        # central_layout.addWidget(splitter)
        # central_layout.setStretch(1, 1)

        # Create and add placeholder dock widgets
        dock_widget1 = QDockWidget("Dock Widget 1", self)
        dock_widget1.setWidget(QLabel("Content of Dock Widget 1"))
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock_widget1)

        dock_widget2 = QDockWidget("Dock Widget 2", self)
        dock_widget2.setWidget(QLabel("Content of Dock Widget 2"))
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock_widget2)

        dock_widget3 = QDockWidget("Dock Widget 3", self)
        dock_widget3.setWidget(QLabel("Content of Dock Widget 3"))
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock_widget3)

    def setup_central_widgets_old2(self):
        # Create the main horizontal splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # Left panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Create and add the toolbar to the left panel
        toolbar = QToolBar("Main Toolbar", self)
        toolbar.setContentsMargins(0, 0, 0, 0)
        random_icon = QIcon(
            TablerIcons.load(OutlineIcon.SQUARE_ROUNDED_PLUS, color='000000')
            .toqpixmap()
            .scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )
        action_new = QAction(random_icon, "New", self)
        action_open = QAction("Open", self)
        action_new.setToolTip("This thing is for...")
        toolbar.addAction(action_new)
        toolbar.addAction(action_open)
        toolbar.setStyleSheet("""
            QToolBar {
                background: #e5e5e5;
                border: none;
                spacing: 5px;
            }
            QToolButton {
                background: none;
                border: none;
                padding: 5px;
            }
            QToolButton:hover {
                background: #d4d4d4;
            }
        """)
        left_layout.addWidget(toolbar)

        # Create the tab widget and add it to the left panel
        self.tab_widget = QTabWidget()
        left_layout.addWidget(self.tab_widget)

        # Add the left panel to the splitter
        splitter.addWidget(left_panel)

        # Middle area (main content area)
        middle_mainwindow = QMainWindow()
        # Set a central widget for the middle main window
        central_widget = QWidget()
        middle_mainwindow.setCentralWidget(central_widget)
        # Placeholder content
        central_layout = QVBoxLayout(central_widget)
        central_layout.addWidget(QLabel("Main Content Area"))

        # Add dock widgets to the middle main window
        dock_widget1 = QDockWidget("Dock Widget 1", self)
        dock_widget1.setWidget(QLabel("Content of Dock Widget 1"))
        middle_mainwindow.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock_widget1)

        dock_widget2 = QDockWidget("Dock Widget 2", self)
        dock_widget2.setWidget(QLabel("Content of Dock Widget 2"))
        middle_mainwindow.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock_widget2)

        dock_widget3 = QDockWidget("Dock Widget 3", self)
        dock_widget3.setWidget(QLabel("Content of Dock Widget 3"))
        middle_mainwindow.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock_widget3)

        # Add the middle main window to the splitter
        splitter.addWidget(middle_mainwindow)

        # Right panel
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        # Placeholder content
        right_layout.addWidget(QLabel("Right Panel Placeholder"))

        # Add the right panel to the splitter
        splitter.addWidget(right_panel)

        # Set the initial sizes of the panels
        splitter.setSizes([200, 800, 200])

        # Make the left and right panels collapsible
        left_panel.setMinimumWidth(0)
        right_panel.setMinimumWidth(0)

        # Set stretch factors
        splitter.setStretchFactor(0, 0)  # Left panel
        splitter.setStretchFactor(1, 1)  # Middle area
        splitter.setStretchFactor(2, 0)  # Right panel

        # Save references for later use
        self.left_panel = left_panel
        self.right_panel = right_panel

    def setup_central_widgets(self):
        # Create the main horizontal splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background: #aaaaaa;
            },
            QSplitter::handle:horizontal {
                width: 3px;
            },
        """)

        # Create a palette and set the color for the splitter handle
        # palette = QPalette()
        # palette.setColor(QPalette.ColorRole.Window, QColor('#aaaaaa'))
        # splitter.setPalette(palette)

        # Left panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Create and add the toolbar to the left panel
        toolbar = QToolBar("Main Toolbar", self)
        toolbar.setContentsMargins(0, 0, 0, 0)
        # random_icon = QIcon(
        #     TablerIcons.load(OutlineIcon.SQUARE_ROUNDED_PLUS, color='000000')
        #     .toqpixmap()
        #     .scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        # )
        action_new = QAction(ToolIcons.ICON_PLUS, "New", self)
        action_open = QAction("Open", self)
        action_new.setToolTip("This thing is for...")
        action_open.setToolTip("to be implemented")
        toolbar.addAction(action_new)
        toolbar.addAction(action_open)
        # toolbar.setStyleSheet("""
        #     QToolBar {
        #         background: #e5e5e5;
        #         border: none;
        #         spacing: 5px;
        #     }
        #     QToolButton {
        #         background: none;
        #         border: none;
        #         padding: 5px;
        #     }
        #     QToolButton:hover {
        #         background: #d4d4d4;
        #     }
        # """)
        left_layout.addWidget(toolbar)

        # Create the tab widget and add it to the left panel
        self.tab_widget = QTabWidget()
        left_layout.addWidget(self.tab_widget)

        # Add the left panel to the splitter
        splitter.addWidget(left_panel)

        # Middle area (main content area)
        middle_mainwindow = QMainWindow()
        # Set a central widget for the middle main window
        self.central_placeholder = QLabel("Main Content Area")
        self.central_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        middle_mainwindow.setCentralWidget(self.central_placeholder)

        # Add dock widgets to the middle main window
        dock_widget1 = QDockWidget("Dock Widget 1", self)
        dock_widget1.setWidget(QLabel("Content of Dock Widget 1"))
        middle_mainwindow.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock_widget1)

        dock_widget2 = QDockWidget("Dock Widget 2", self)
        dock_widget2.setWidget(QLabel("Content of Dock Widget 2"))
        middle_mainwindow.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock_widget2)

        dock_widget3 = QDockWidget("Dock Widget 3", self)
        dock_widget3.setWidget(QLabel("Content of Dock Widget 3"))
        middle_mainwindow.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock_widget3)

        # Add the middle main window to the splitter
        splitter.addWidget(middle_mainwindow)

        # Right panel
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        # Placeholder content
        right_layout.addWidget(QLabel("Right Panel Placeholder"))

        # Add the right panel to the splitter
        splitter.addWidget(right_panel)

        # Set the initial sizes of the panels
        splitter.setSizes([600, 400, 300])

        # Make the left and right panels collapsible
        left_panel.setMinimumWidth(0)
        right_panel.setMinimumWidth(0)

        # Set stretch factors
        splitter.setStretchFactor(0, 0)  # Left panel
        splitter.setStretchFactor(1, 1)  # Middle area
        splitter.setStretchFactor(2, 0)  # Right panel

        # Save references for later use
        self.left_panel = left_panel
        self.right_panel = right_panel
        self.middle_mainwindow = middle_mainwindow

        # Keep track of dock widgets
        self.dock_widgets = [dock_widget1, dock_widget2, dock_widget3]

        # Connect signals to check if dock widgets are closed
        for dock_widget in self.dock_widgets:
            dock_widget.visibilityChanged.connect(self.update_placeholder_visibility)

        # Initial check to set placeholder visibility
        self.update_placeholder_visibility()

    def update_placeholder_visibility(self, *args):
        # Check if any dock widgets are visible
        any_visible = any(dock_widget.isVisible() for dock_widget in self.dock_widgets)
        if any_visible:
            self.central_placeholder.hide()
        else:
            self.central_placeholder.show()

    def setup_file_tree_view(self):
        # Create the FolderExplorer widget
        # self.folder_explorer = FolderExplorer(...)
        dirPath = QDir.rootPath()  # Start from the root directory
        # target_path = r'/Users/tonyyan/Library/CloudStorage/OneDrive-AustralianNationalUniversity/_He_BEC_data_root_copy'
        # view_path = r'/Users/tonyyan/Library/CloudStorage/OneDrive-AustralianNationalUniversity'
        view_path = dirPath
        target_path = r'/Volumes/tonyNVME Gold/dld output'

        logging.debug(f"Root path: {dirPath}")
        logging.debug(f"Target path: {target_path}")
        # Validate that target_path is under dirPath
        try: 
            if not os.path.commonpath([dirPath, target_path]) == os.path.abspath(dirPath):
                logging.warning(
                    f"Target path {target_path} is not under the root path {dirPath}. Adjusting dirPath accordingly.")
                dirPath = os.path.dirname(target_path)
        except ValueError as e:
            logging.error(f"Error validating target path: {e}")
            dirPath = QDir.rootPath()
            target_path = QDir.rootPath()

        # Specify columns to show; show Name, Date Modified, Number, and Status Icon columns
        columns_to_show = [
            CustomFileSystemModel.COLUMN_NAME,
            CustomFileSystemModel.COLUMN_DATE_MODIFIED,
            CustomFileSystemModel.COLUMN_STATUS_NUMBER,
            CustomFileSystemModel.COLUMN_STATUS_ICON,
            CustomFileSystemModel.COLUMN_RIGHTFILL
        ]
        folder_explorer = FolderExplorer(dirPath, target_path, view_path, columns_to_show)
        # folder_explorer.setContentsMargins(0, 0, 0, 0)
        # folder_explorer.setMinimumWidth(300)
        # folder_explorer.setMinimumHeight(300)
        # folder_explorer.setMaximumWidth(1000)
        # folder_explorer.setFixedWidth(600)
        # folder_explorer.resize(600, folder_explorer.height())

        # Add the FolderExplorer as a new tab
        self.tab_widget.addTab(folder_explorer, 'File Explorer')

        # # Add it as a dock widget
        # dock = QDockWidget('File Explorer', self)
        # dock.setWidget(folder_explorer)
        # # self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        # self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

