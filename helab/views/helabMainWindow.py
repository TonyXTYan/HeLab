import logging
import os

from PyQt6.QtCore import Qt, QDir, QSize
from PyQt6.QtGui import QAction, QIcon, QPalette, QColor
from PyQt6.QtWidgets import QMainWindow, QDockWidget, QStatusBar, QMenuBar, QWidget, QVBoxLayout, QTabWidget, QSplitter, \
    QLabel, QToolBar, QStyle, QSizePolicy, QToolTip, QApplication, QStyleFactory
from pytablericons import TablerIcons, OutlineIcon

from helab.models.helabFileSystemModel import CustomFileSystemModel
from helab.resources.icons import ToolIcons
from helab.views.folderExplorer import FolderExplorer


class MainWindow(QMainWindow):
    DEFAULT_WIDTH = 1800
    DEFAULT_HEIGHT = 1000

    def __init__(self):
        super().__init__()

        self.setWindowTitle('HeLab')
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

        # Create Menubar
        self.menu_bar = self.menuBar()
        self.create_menus()

        # Create Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Create Central Widget Area with Dock Widgets
        self.setup_central_widgets()

        # Create Left Panel (File Tree View)
        # self.setup_file_tree_view()
        self.add_new_folder_explorer_tab()

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
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self.splitter)
        # self.splitter.setStyleSheet("""
        #     QSplitter::handle {
        #         background: none;
        #     },
        #     QSplitter::handle:horizontal {
        #         width: 3px;
        #     },
        # """)
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background: #cccccc;  /* Light gray background for the handle */
            }
            QSplitter::handle:horizontal {
                width: 5px;
            }
            QSplitter::handle:vertical {
                height: 5px;
            }
            QSplitter::handle:hover {
                background: #000000;  /* Darker gray when hovered */
            }
        """)

        # Create a palette and set the color for the splitter handle
        # palette = QPalette()
        # palette.setColor(QPalette.ColorRole.Window, QColor('#aaaaaa'))
        # splitter.setPalette(palette)

        # Add a toolbar with a toggle button for the left panel
        self.sidebar_toolbar = QToolBar("Sidebar Toolbar", self)
        self.sidebar_toolbar.setIconSize(QSize(24, 24))
        toggle_left_panel_action = QAction(ToolIcons.ICON_LEFT_COLLAPSE, "Toggle Left Panel", self)
        toggle_left_panel_action.setCheckable(True)
        toggle_left_panel_action.setChecked(True)
        toggle_left_panel_action.triggered.connect(self.toggle_left_panel)
        self.sidebar_toolbar.addAction(toggle_left_panel_action)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, self.sidebar_toolbar)
        self.sidebar_toolbar.setMovable(False)

        # Left panel
        left_panel = QWidget()
        self.left_panel_width = 700  # Store the width of the left panel
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        # Create a splitter to hold the tab_widget and bottom_panel
        self.left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_layout.addWidget(self.left_splitter)
        left_panel.setLayout(left_layout)


        # Create and add the toolbar to the left panel
        # toolbar = QToolBar("Main Toolbar", self)
        # toolbar.setContentsMargins(0, 0, 0, 0)
        # toolbar.setIconSize(QSize(16, 16))
        # random_icon = QIcon(
        #     TablerIcons.load(OutlineIcon.SQUARE_ROUNDED_PLUS, color='000000')
        #     .toqpixmap()
        #     .scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        # )
        action_tab_new = QAction(ToolIcons.ICON_PLUS, "New Tab", self)
        action_tab_refresh = QAction(ToolIcons.ICON_REFRESH, "Refresh", self)
        action_tab_folder_up = QAction(ToolIcons.ICON_FOLDER_UP, "Up Dir", self)

        action_tab_new.setToolTip("This thing is for...")
        action_tab_new.setWhatsThis("What's this? r") # literally don't know where this will show up memm
        action_tab_refresh.setToolTip("to be implemented")
        action_tab_folder_up.setToolTip("to be implemented")

        action_tab_new.triggered.connect(self.add_new_folder_explorer_tab)
        action_tab_folder_up.triggered.connect(self.on_back_button_clicked)


        # toolbar.addAction(action_tab_new)
        # toolbar.addAction(action_tab_refresh)
        # toolbar.addAction(action_tab_folder_up)
        self.sidebar_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        self.sidebar_toolbar.setStyleSheet("""
            QToolBar {
                background: none;
                border: none;
                spacing: 5px;
            }
            QToolButton:checked {
                background-color: #000000;  # Color when checked
            }
            # QToolButton {
            #     background: none;
            #     border: none;
            #     padding: 5px;
            # }
            QToolButton:hover {
                background: #d4d4d4;
            }
            QToolButton:pressed {
                background: #999999;
            }
        """)
        # left_layout.addWidget(self.sidebar_toolbar)

        self.sidebar_toolbar.addAction(action_tab_new)
        self.sidebar_toolbar.addAction(action_tab_refresh)
        self.sidebar_toolbar.addAction(action_tab_folder_up)

        # Create the tab widget and add it to the left panel
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.tab_widget.removeTab)
        # left_layout.addWidget(self.tab_widget)
        self.left_splitter.addWidget(self.tab_widget)

        # # Load the icons using pytablericons
        # close_icon = TablerIcons.load(OutlineIcon.SQUARE_ROUNDED_X, color='#000000').toqpixmap()
        # close_icon_hover = TablerIcons.load(OutlineIcon.SQUARE_ROUNDED_X, color='#ff0000').toqpixmap()
        # close_icon_pressed = TablerIcons.load(OutlineIcon.SQUARE_ROUNDED_X, color='#00ff00').toqpixmap()
        #
        # # Set the stylesheet for the tab widget
        # self.tab_widget.setStyleSheet(f"""
        #     QTabBar::close-button {{
        #         image: url({close_icon});
        #         subcontrol-position: right;
        #         margin: 2px;
        #     }}
        #     QTabBar::close-button:hover {{
        #         image: url({close_icon_hover});
        #     }}
        #     QTabBar::close-button:pressed {{
        #         image: url({close_icon_pressed});
        #     }}
        # """)

        # Add a spacer widget to push the toggle button to the bottom
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.sidebar_toolbar.addWidget(spacer)

        # Add a button to the bottom of sidebar_toolbar
        toggle_panel_action = QAction(ToolIcons.ICON_BOTTOM_EXPAND, "Toggle Panel", self)
        toggle_panel_action.setCheckable(True)
        toggle_panel_action.setChecked(False)
        self.sidebar_toolbar.addAction(toggle_panel_action)

        # Create a panel below the tab_widget
        self.bottom_panel = QWidget()
        self.bottom_panel_layout = QVBoxLayout(self.bottom_panel)
        self.bottom_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.bottom_panel_label = QLabel("Placeholder")
        self.bottom_panel_layout.addWidget(self.bottom_panel_label)
        self.bottom_panel.setVisible(False)

        # Add the bottom panel to the left_layout
        # left_layout.addWidget(self.bottom_panel)
        self.left_splitter.addWidget(self.bottom_panel)

        # Connect the button to a function that toggles the visibility of the panel
        toggle_panel_action.triggered.connect(self.toggle_bottom_panel)

        self.left_splitter.setSizes([400, 100])


        # Add the left panel to the splitter
        self.splitter.addWidget(left_panel)

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
        self.splitter.addWidget(middle_mainwindow)

        # Right panel
        right_panel = QWidget()
        self.right_panel_width = 500
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        # Placeholder content
        right_layout.addWidget(QLabel("Right Panel Placeholder"))

        # Add the right panel to the splitter
        self.splitter.addWidget(right_panel)

        # Set the initial sizes of the panels
        self.splitter.setSizes([
            self.left_panel_width,
            self.DEFAULT_WIDTH-self.left_panel_width-self.right_panel_width,
            self.right_panel_width
        ])


        # Make the left and right panels collapsible
        left_panel.setMinimumWidth(0)
        right_panel.setMinimumWidth(0)

        # Set stretch factors
        self.splitter.setStretchFactor(0, 1)  # Left panel
        self.splitter.setStretchFactor(1, 1)  # Middle area
        self.splitter.setStretchFactor(2, 1)  # Right panel

        # Save references for later use
        self.left_panel = left_panel
        self.right_panel = right_panel
        self.middle_mainwindow = middle_mainwindow

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

    def update_placeholder_visibility(self, *args):
        # Check if any dock widgets are visible
        any_visible = any(dock_widget.isVisible() for dock_widget in self.dock_widgets)
        if any_visible:
            self.central_placeholder.hide()
        else:
            self.central_placeholder.show()

    def setup_file_tree_view_depreciated(self):
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
        self.add_new_folder_explorer_tab()
        # folder_explorer = FolderExplorer(dirPath, target_path, view_path, columns_to_show)
        # folder_explorer.setContentsMargins(0, 0, 0, 0)
        # folder_explorer.setMinimumWidth(300)
        # folder_explorer.setMinimumHeight(300)
        # folder_explorer.setMaximumWidth(1000)
        # folder_explorer.setFixedWidth(600)
        # folder_explorer.resize(600, folder_explorer.height())

        # Add the FolderExplorer as a new tab
        # self.tab_widget.addTab(folder_explorer, 'File Explorer')

        # # Add it as a dock widget
        # dock = QDockWidget('File Explorer', self)
        # dock.setWidget(folder_explorer)
        # # self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        # self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def add_new_folder_explorer_tab(self):
        # Create a new FolderExplorer instance
        dirPath = QDir.rootPath()
        view_path = dirPath
        target_path = r'/Volumes/tonyNVME Gold/dld output'
        try:
            if not os.path.commonpath([dirPath, target_path]) == os.path.abspath(dirPath):
                logging.warning(
                    f"Target path {target_path} is not under the root path {dirPath}. Adjusting dirPath accordingly.")
                dirPath = os.path.dirname(target_path)
        except ValueError as e:
            logging.error(f"Error validating target path: {e}")
            dirPath = QDir.rootPath()
            target_path = QDir.rootPath()

        columns_to_show = [
            CustomFileSystemModel.COLUMN_NAME,
            CustomFileSystemModel.COLUMN_DATE_MODIFIED,
            CustomFileSystemModel.COLUMN_STATUS_NUMBER,
            CustomFileSystemModel.COLUMN_STATUS_ICON,
            CustomFileSystemModel.COLUMN_RIGHTFILL
        ]
        folder_explorer = FolderExplorer(dirPath, target_path, view_path, columns_to_show)
        index = self.tab_widget.addTab(folder_explorer, 'File Explorer')

        folder_explorer.rootPathChanged.connect(lambda path, idx=index: self.update_folder_explorer_tab_title(path, idx))
        folder_explorer.emit_root_path_changed()

        # Add the FolderExplorer as a new tab
        # self.tab_widget.addTab(folder_explorer, 'File Explorer')

    def update_folder_explorer_tab_title(self, path, index):
        logging.debug(f"Updating tab title for index {index} to {path}")
        # self.tab_widget.setTabText(index, os.path.basename(path))
        if path == "/":
            self.tab_widget.setTabText(index, "Path /")
        else:
            self.tab_widget.setTabText(index, os.path.basename(path))

    def on_back_button_clicked(self):
        # Get the current folder explorer
        current_folder_explorer = self.tab_widget.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.on_back_button_clicked()

    def toggle_left_panel(self, checked):
        if checked:
            # self.splitter.setSizes([self.left_panel_width, self.splitter.sizes()[1], self.splitter.sizes()[2]])
            self.splitter.setSizes([
                self.left_panel_width,
                # self.splitter.sizes()[1],
                self.width()-self.left_panel_width-self.right_panel_width,
                self.right_panel_width
            ])
            self.sidebar_toolbar.actions()[0].setIcon(ToolIcons.ICON_LEFT_COLLAPSE)
        else:
            self.left_panel_width = self.left_panel.width() if self.left_panel.width() > 600 else self.left_panel_width
            self.right_panel_width = self.right_panel.width() if self.right_panel.width() > 300 else self.right_panel_width
            self.splitter.setSizes([0, self.splitter.sizes()[1], self.splitter.sizes()[2]])
            self.sidebar_toolbar.actions()[0].setIcon(ToolIcons.ICON_LEFT_EXPAND)

        # Update the bottom panel icon based on its visibility and the state of the left panel
        # if self.bottom_panel.isVisible():
        #     self.sidebar_toolbar.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_COLLAPSE)
        # else:
        if self.splitter.sizes()[0] == 0:  # Check if the left panel is hidden
            self.sidebar_toolbar.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_INACTIVE)
        else:
            if self.bottom_panel.isVisible():
                self.sidebar_toolbar.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_COLLAPSE)
            else:
                self.sidebar_toolbar.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_EXPAND)

    def toggle_bottom_panel(self, checked):
        if checked:
            self.bottom_panel.setVisible(True)
            self.sidebar_toolbar.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_COLLAPSE)
        else:
            self.bottom_panel.setVisible(False)
            if self.splitter.sizes()[0] == 0:  # Check if the left panel is hidden
                self.sidebar_toolbar.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_INACTIVE)
            else:
                self.sidebar_toolbar.actions()[-1].setIcon(ToolIcons.ICON_BOTTOM_EXPAND)

    # def enterEvent(self, event):
    #     # Display the tooltip immediately when mouse enters the widget area
    #     QToolTip.showText(event.globalPosition().toPoint(), self.toolTip(), self, self.rect())
    #     super().enterEvent(event)