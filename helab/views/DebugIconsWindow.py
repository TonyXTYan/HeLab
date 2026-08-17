import logging
import stat

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem, QSizePolicy, QSplitter
from PyQt6.QtGui import QIcon, QCloseEvent

from helab.resources.icons import StatusIcons, ToolIcons, PercentageIcon

class DebugIconsWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Debug Icons")
        self.resize(600, 800)
        self.setup_ui()

    def setup_ui(self) -> None:
        layout = QVBoxLayout()

        splitter = QSplitter(Qt.Orientation.Vertical)

        # Status Icons
        status_widget = QWidget()
        status_layout = QVBoxLayout()
        status_label = QLabel("Status Icons")
        status_layout.addWidget(status_label)

        self.status_list = QListWidget()
        self.status_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        status_icons_dir = {**StatusIcons.ICONS_STATUS, **StatusIcons.ICONS_EXTRA}.items()
        status_icons_dir2 = dir(StatusIcons.ICONS_STATUS)
        status_icons_dir_len = len(status_icons_dir)
        for name, icon in status_icons_dir:
            text = name
            for attr in dir(StatusIcons):
                if attr.startswith('ICON_'):
                    icon2 = getattr(StatusIcons, attr)
                    if isinstance(icon2, QIcon):
                        if icon2 == icon:
                            text = name + "\t" + attr
            item = QListWidgetItem()
            item.setText(text)
            item.setIcon(icon)
            self.status_list.addItem(item)
            


        status_layout.addWidget(self.status_list)
        status_widget.setLayout(status_layout)
        splitter.addWidget(status_widget)

        # Tool Icons
        tool_widget = QWidget()
        tool_layout = QVBoxLayout()
        tool_label = QLabel("Tool Icons")
        tool_layout.addWidget(tool_label)

        self.tool_list = QListWidget()
        self.tool_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.tool_list_dir = dir(ToolIcons)
        self.tool_list_dir_len = 0
        for attr in self.tool_list_dir:
            if attr.startswith('ICON_'):
                self.tool_list_dir_len += 1
                icon = getattr(ToolIcons, attr)
                if isinstance(icon, QIcon):
                    item = QListWidgetItem()
                    item.setText(attr)
                    item.setIcon(icon)
                    self.tool_list.addItem(item)
        tool_layout.addWidget(self.tool_list)
        tool_widget.setLayout(tool_layout)
        splitter.addWidget(tool_widget)

        # Percentage Icons
        percentage_widget = QWidget()
        percentage_layout = QVBoxLayout()
        percentage_label = QLabel("Percentage Icons (DO NOT USE)")
        percentage_layout.addWidget(percentage_label)

        self.percentage_list = QListWidget()
        self.percentage_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # self.percentage_list_dir = dir(PercentageIcon)
        # self.percentage_list_dir_len = 0
        # for attr in self.percentage_list_dir:
        #     if attr.startswith('ICON_'):
        #         self.percentage_list_dir_len += 1
        #         icon = getattr(PercentageIcon, attr)
        #         if isinstance(icon, QIcon):
        #             item = QListWidgetItem()
        #             item.setText(attr)
        #             item.setIcon(icon)
        #             self.percentage_list.addItem(item)
        for div, qicon in PercentageIcon.ICONS.items():
            item = QListWidgetItem()
            item.setText(f"divID = {div} = {round(div * (360 / PercentageIcon._DIVS_COARSE))}deg ="
                         f" {round(div * (100 / PercentageIcon._DIVS_COARSE))}%")
            item.setIcon(qicon)
            self.percentage_list.addItem(item)
        self.percentage_list_dir_len = len(PercentageIcon.ICONS)
        percentage_layout.addWidget(self.percentage_list)
        percentage_widget.setLayout(percentage_layout)
        splitter.addWidget(percentage_widget)

        # layout.setStretchFactor(self.status_list, status_icons_dir_len)
        # layout.setStretchFactor(self.tool_list, self.tool_list_dir_len)
        # layout.setStretchFactor(percentage_label, self.percentage_list_dir_len)
        #
        self.status_list.setMinimumHeight(200)
        self.tool_list.setMinimumHeight(200)
        self.percentage_list.setMinimumHeight(200)

        logging.debug(f"{len(status_icons_dir)} status icons, {self.tool_list_dir_len} tool icons, {self.percentage_list_dir_len} percentage icons")

        layout.addWidget(splitter)
        self.setLayout(layout)

    def closeEvent(self, a0: QCloseEvent|None) -> None:
        logging.debug("DebugIconsWindow.closeEvent")
        super().closeEvent(a0)
        self.deleteLater()
