import logging
import os

from PyQt6.QtCore import Qt, QDir
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMainWindow, QDockWidget, QStatusBar, QMenuBar, QWidget, QVBoxLayout

from helium.models.heliumFileSystemModel import CustomFileSystemModel
from helium.views.folderExplorer import FolderExplorer
# ... other imports

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle('Your Application Title')
        self.resize(1200, 800)

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

    def setup_central_widgets(self):
        # You can set a central widget or use dock widgets
        # pass
        # Example: Create a central widget with multiple dock widgets
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # Create a layout for the central widget
        central_layout = QVBoxLayout(self.central_widget)
        # ... add widgets or layouts to central_layout

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
        if not os.path.commonpath([dirPath, target_path]) == os.path.abspath(dirPath):
            logging.warning(
                f"Target path {target_path} is not under the root path {dirPath}. Adjusting dirPath accordingly.")
            dirPath = os.path.dirname(target_path)

        # Specify columns to show; show Name, Date Modified, Number, and Status Icon columns
        columns_to_show = [
            CustomFileSystemModel.COLUMN_NAME,
            CustomFileSystemModel.COLUMN_DATE_MODIFIED,
            CustomFileSystemModel.COLUMN_STATUS_NUMBER,
            CustomFileSystemModel.COLUMN_STATUS_ICON,
            CustomFileSystemModel.COLUMN_RIGHTFILL
        ]
        self.folder_explorer = FolderExplorer(dirPath, target_path, view_path, columns_to_show)



        # Add it as a dock widget
        dock = QDockWidget('File Explorer', self)
        dock.setWidget(self.folder_explorer)
        # self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)