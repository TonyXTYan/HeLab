import logging

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
                            QHeaderView, QToolButton, QSizePolicy)
from PyQt6.QtGui import QIcon, QCloseEvent

from helab.resources.icons import StatusIcons, ToolIcons, PercentageIcon


class _IconGroup(QWidget):
    def __init__(self, title: str, expanded: bool) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QHBoxLayout()
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        heading.addWidget(self.toggle)
        heading.addStretch()
        layout.addLayout(heading)

        self.icon_list = QTreeWidget()
        self.icon_list.setRootIsDecorated(False)
        self.icon_list.setUniformRowHeights(True)
        self.icon_list.setIconSize(QSize(20, 20))
        self.icon_list.setHeaderLabels(["Icon", "Attribute"])
        header = self.icon_list.header()
        if header is not None:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.icon_list)
        self.toggle.toggled.connect(self._set_expanded)
        self._set_expanded(expanded)

    def _set_expanded(self, expanded: bool) -> None:
        self.icon_list.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding if expanded else QSizePolicy.Policy.Maximum)


class DebugIconsWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Debug Icons")
        self.resize(600, 800)
        self.setup_ui()

    def setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.status_group = _IconGroup("Status Icons", expanded=True)
        self.tool_group = _IconGroup("Tool Icons", expanded=True)
        self.percentage_group = _IconGroup("Percentage Icons (DO NOT USE)", expanded=False)
        groups = (self.status_group, self.tool_group, self.percentage_group)
        for group in groups:
            layout.addWidget(group)
        self.status_list = self.status_group.icon_list
        self.tool_list = self.tool_group.icon_list
        self.percentage_list = self.percentage_group.icon_list

        status_icons = {**StatusIcons.ICONS_STATUS, **StatusIcons.ICONS_EXTRA}
        for name, icon in status_icons.items():
            attribute = ""
            for attr in dir(StatusIcons):
                if attr.startswith("ICON_"):
                    candidate = getattr(StatusIcons, attr)
                    if isinstance(candidate, QIcon) and candidate == icon:
                        attribute = attr
            self._add_icon(self.status_list, name, attribute, icon)

        tool_count = 0
        for attr in dir(ToolIcons):
            if attr.startswith("ICON_"):
                icon = getattr(ToolIcons, attr)
                if isinstance(icon, QIcon):
                    self._add_icon(self.tool_list, attr.removeprefix("ICON_").lower(), attr, icon)
                    tool_count += 1

        for div, icon in PercentageIcon.ICONS.items():
            percent = round(div * 100 / PercentageIcon._DIVS_COARSE)
            degrees = round(div * 360 / PercentageIcon._DIVS_COARSE)
            item = self._add_icon(self.percentage_list, f"{percent}% circular progress",
                                  f"PercentageIcon.ICONS[{div}]", icon)
            item.setToolTip(0, f"{degrees} degrees")

        # All three views share the width required by the longest icon name.
        for group in groups:
            group.icon_list.resizeColumnToContents(0)
        name_width = max(group.icon_list.columnWidth(0) for group in groups)
        for group in groups:
            group.icon_list.setColumnWidth(0, name_width)

        logging.debug("%s status icons, %s tool icons, %s percentage icons",
                      len(status_icons), tool_count, len(PercentageIcon.ICONS))

    @staticmethod
    def _add_icon(view: QTreeWidget, name: str, attribute: str, icon: QIcon) -> QTreeWidgetItem:
        item = QTreeWidgetItem([name, attribute])
        item.setIcon(0, icon)
        view.addTopLevelItem(item)
        return item

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        logging.debug("DebugIconsWindow.closeEvent")
        super().closeEvent(a0)
        self.deleteLater()
