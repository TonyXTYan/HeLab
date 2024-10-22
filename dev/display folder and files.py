import sys
import os
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QTreeView,
    QVBoxLayout,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QHeaderView,
    QPushButton,
)
from PyQt6.QtCore import (
    QModelIndex,
    QDir,
    Qt,
    QRect,
    QSize,
    QTimer,
)
from PyQt6.QtGui import (
    QFileSystemModel,
    QColor,
    QIcon,
    QPainter,
    QFont,
)
from pytablericons import TablerIcons, OutlineIcon
import random
import logging

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

STATUS_DATA_ROLE = Qt.ItemDataRole.UserRole + 1

class CustomFileSystemModel(QFileSystemModel):
    COLUMN_NAME = 0
    COLUMN_SIZE = 1
    COLUMN_TYPE = 2
    COLUMN_DATE_MODIFIED = 3
    COLUMN_STATUS_NUMBER = 4
    COLUMN_STATUS_ICON = 5
    COLUMN_RIGHTFILL = 6

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cache the standard icons
        style = QApplication.style()
        # self.icon_ok = style.standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        # self.icon_warning = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        # self.icon_critical = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical)
        self.icon_ok =       QIcon(TablerIcons.load(OutlineIcon.CIRCLE_CHECK, color='#00bb39').toqpixmap().scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.icon_critical = QIcon(TablerIcons.load(OutlineIcon.XBOX_X,       color='#e50000').toqpixmap().scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.icon_warning =  QIcon(TablerIcons.load(OutlineIcon.ALERT_CIRCLE, color='#f8c350').toqpixmap().scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.icon_loading =  QIcon(TablerIcons.load(OutlineIcon.LOADER,       color='#000000').toqpixmap().scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.icon_live =     QIcon(TablerIcons.load(OutlineIcon.LIVE_PHOTO,   color='#000000').toqpixmap().scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

        self.status_icons = {
            'ok': self.icon_ok,
            'warning': self.icon_warning,
            'critical': self.icon_critical,
            'loading': self.icon_loading
        }

    def columnCount(self, parent=QModelIndex()):
        return super().columnCount(parent) + 3  # Add three extra columns

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        column = index.column()
        file_info = self.fileInfo(index)

        if column == self.COLUMN_DATE_MODIFIED:
            if role == Qt.ItemDataRole.DisplayRole:
                date_time = file_info.lastModified()
                return date_time.toString("yyyy-MM-dd HH:mm:ss")
            else:
                return None
        elif column == self.COLUMN_STATUS_NUMBER:
            if role == Qt.ItemDataRole.DisplayRole:
                status, count = self.get_status(file_info.absoluteFilePath())
                return str(count)
            elif role == Qt.ItemDataRole.TextAlignmentRole:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            else:
                return None
        elif column == self.COLUMN_STATUS_ICON:
            if role == Qt.ItemDataRole.DecorationRole:
                status, _ = self.get_status(file_info.absoluteFilePath())
                icon = self.status_icons.get(status)
                return icon
            else:
                return None
        elif column == self.COLUMN_RIGHTFILL:
            return None
        else:
            # For other columns, default behavior
            if role == Qt.ItemDataRole.ForegroundRole:
                if file_info.isHidden():
                    return QColor(Qt.GlobalColor.gray)
            return super().data(index, role)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                if section == self.COLUMN_STATUS_NUMBER:
                    return "Number"
                elif section == self.COLUMN_STATUS_ICON:
                    return "Status"
        return super().headerData(section, orientation, role)

    def get_status(self, file_or_folder_path):
        # ok_num = self.get_ok_num(file_or_folder_path)
        # warning_num = self.get_warning_num(file_or_folder_path)
        # critical_num = self.get_critical_num(file_or_folder_path)
        # if critical_num > 0:
        #     return ('critical', critical_num)
        # elif warning_num > 0:
        #     return ('warning', warning_num)
        # else:
        #     return ('ok', ok_num)
        statuses = ['ok', 'warning', 'critical', 'loading']
        status = random.choice(statuses)
        # count = random.randint(0, 99999)
        count = random.randint(10**(length := random.randint(0, 5)), 10**(length + 1) - 1)
        return (status, count)

    # def get_ok_num(self, file_or_folder_path):
    #     # Placeholder function to compute ok_num
    #     return 9999 + len(file_or_folder_path)  # For testing purposes
    #
    # def get_warning_num(self, file_or_folder_path):
    #     # Placeholder function to compute warn_num
    #     # Replace with actual computation
    #     return random.randint(0, 1000)  # For testing purposes
    #
    # def get_critical_num(self, file_or_folder_path):
    #     # Placeholder function to compute critical_num
    #     # Replace with actual computation
    #     return file_or_folder_path.count('a')  # For testing purposes


class CenteredIconDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        # Clear the icon to prevent the default drawing
        option.icon = QIcon()

    def paint(self, painter, option, index):
        # Call the base class paint method (which won't draw the icon now)
        super().paint(painter, option, index)
        # Draw your centered icon
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon:
            rect = option.rect
            icon_size = icon.actualSize(option.decorationSize)
            x = rect.left() + (rect.width() - icon_size.width()) // 2
            y = rect.top() + (rect.height() - icon_size.height()) // 2
            icon.paint(painter, QRect(x, y, icon_size.width(), icon_size.height()))
        # If no icon, nothing else to do

    def sizeHint(self, option, index):
        # Ensure the size hint accommodates the icon
        size = super().sizeHint(option, index)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon:
            icon_size = icon.actualSize(option.decorationSize)
            size.setHeight(max(size.height(), icon_size.height()))
        return size



class FileSystemView(QWidget):
    def __init__(self, dir_path, target_path, columns_to_show=None):
        super().__init__()
        appWidth = 800
        appHeight = 800

        self.setWindowTitle('File System Viewer')
        self.setGeometry(300, 300, appWidth, appHeight)

        self.model = CustomFileSystemModel()
        self.model.setRootPath(dir_path)
        self.model.setReadOnly(True)
        self.model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden)

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(dir_path))
        self.tree.setColumnWidth(CustomFileSystemModel.COLUMN_NAME, 250)
        self.tree.setColumnWidth(CustomFileSystemModel.COLUMN_DATE_MODIFIED, 160)
        self.tree.setColumnWidth(CustomFileSystemModel.COLUMN_STATUS_NUMBER, 80)
        self.tree.setColumnWidth(CustomFileSystemModel.COLUMN_STATUS_ICON, 60)
        self.tree.setColumnWidth(CustomFileSystemModel.COLUMN_RIGHTFILL, 0)
        self.tree.setAlternatingRowColors(True)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setUniformRowHeights(True)

        # Set the custom delegate for the icon column
        icon_delegate = CenteredIconDelegate(self.tree)
        self.tree.setItemDelegateForColumn(CustomFileSystemModel.COLUMN_STATUS_ICON, icon_delegate)

        # Control which columns to show
        if columns_to_show is not None:
            total_columns = self.model.columnCount()
            for col in range(total_columns):
                if col not in columns_to_show:
                    self.tree.setColumnHidden(col, True)

        header = self.tree.header()
        # Make the first column auto-resizable
        header.setSectionResizeMode(CustomFileSystemModel.COLUMN_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(CustomFileSystemModel.COLUMN_NAME, QHeaderView.ResizeMode.Interactive)
        # Other columns resize to contents
        header.setSectionResizeMode(CustomFileSystemModel.COLUMN_SIZE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(CustomFileSystemModel.COLUMN_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(CustomFileSystemModel.COLUMN_DATE_MODIFIED, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(CustomFileSystemModel.COLUMN_STATUS_NUMBER, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(CustomFileSystemModel.COLUMN_STATUS_ICON, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(CustomFileSystemModel.COLUMN_RIGHTFILL, QHeaderView.ResizeMode.ResizeToContents)
        # self.tree.setColumnWidth(CustomFileSystemModel.COLUMN_STATUS_ICON, 60)
        # self.tree.setColumnWidth(CustomFileSystemModel.COLUMN_RIGHTFILL, 0)

        # Create a back button
        self.back_button = QPushButton('Back')
        self.back_button.clicked.connect(self.on_back_button_clicked)

        layout = QVBoxLayout()
        layout.addWidget(self.back_button)
        layout.addWidget(self.tree)
        self.setLayout(layout)

        # Connect the selectionChanged signal to the slot
        self.tree.selectionModel().selectionChanged.connect(self.on_selection_changed)

        # Connect the double-click signal to open directories
        self.tree.doubleClicked.connect(self.on_double_click)

        # Update back button state
        self.update_back_button_state()

        # Automatically expand the view to the desired path
        # QTimer.singleShot(1000, lambda: self.expand_to_path(target_path))
        self.expand_to_path(target_path)


    def on_selection_changed(self, selected, deselected):
        indexes = self.tree.selectionModel().selectedRows()
        for index in indexes:
            file_path = self.model.filePath(index)
            logging.debug(f"Selected file path: {file_path}")

    def expand_to_path(self, path):
        index = self.model.index(path)
        if not index.isValid():
            logging.warning(f"Invalid path: {path}")
            return
        # Expand all parent items
        parent_index = index.parent()
        while parent_index.isValid():
            self.tree.expand(parent_index)
            parent_index = parent_index.parent()
        # Expand the target index
        self.tree.expand(index)
        # Set the current selection to the target index
        self.tree.setCurrentIndex(index)
        # Update the tree view to ensure it's fully rendered
        # self.tree.update()
        # QTimer.singleShot(1000, lambda: self.tree.update())
        # Scroll to the target index
        # self.tree.scrollTo(index, QTreeView.ScrollHint.PositionAtCenter)
        self.tree.scrollTo(index, QTreeView.ScrollHint.EnsureVisible)
        # QTimer.singleShot(1000, lambda: self.tree.scrollTo(index, QTreeView.ScrollHint.EnsureVisible))

        # self.tree.setFocus()

    def on_double_click(self, index):
        file_info = self.model.fileInfo(index)
        if file_info.isDir():
            # Set this directory as the new root
            self.tree.setRootIndex(index)
            # Update the back button enabled state
            self.update_back_button_state()

    def on_back_button_clicked(self):
        current_root_index = self.tree.rootIndex()
        parent_index = current_root_index.parent()
        if parent_index.isValid():
            self.tree.setRootIndex(parent_index)
        else:
            # If no parent, set to the model's root
            self.tree.setRootIndex(self.model.index(self.model.rootPath()))
        # Update the back button enabled state
        self.update_back_button_state()

    def update_back_button_state(self):
        current_root_index = self.tree.rootIndex()
        if current_root_index == self.model.index(self.model.rootPath()):
            self.back_button.setEnabled(False)
        else:
            self.back_button.setEnabled(True)


if __name__ == '__main__':

    font = QFont("SF Mono")

    app = QApplication(sys.argv)
    app.setFont(font)

    dirPath = r''  # Replace with your directory path
    target_path = r'/Users/tonyyan/Downloads'  # Replace with the path you want to view

    # Specify columns to show; show Name, Date Modified, Number, and Status Icon columns
    columns_to_show = [
        CustomFileSystemModel.COLUMN_NAME,
        CustomFileSystemModel.COLUMN_DATE_MODIFIED,
        CustomFileSystemModel.COLUMN_STATUS_NUMBER,
        CustomFileSystemModel.COLUMN_STATUS_ICON,
        CustomFileSystemModel.COLUMN_RIGHTFILL
    ]
    demo = FileSystemView(dirPath, target_path, columns_to_show)
    demo.show()
    sys.exit(app.exec())
