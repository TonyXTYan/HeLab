import logging

from typing import Callable

from PyQt6.QtCore import QRect, QRectF, QSize, Qt
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
                            QHeaderView, QToolButton, QSizePolicy)
from PyQt6.QtGui import QColor, QIcon, QCloseEvent, QPainter, QPixmap

from helab.resources.icons import StatusIcons, ToolIcons, PercentageIcon
from helab.views.FolderDetailsPanel import paint_load_bar
from helab.views.FolderExplorer import IO_SPINNER, LOAD_SPINNER, paint_check, paint_check_badge, paint_spinner


def _painted(paint: Callable[[QPainter], None]) -> QIcon:
    """A still frame of something painted live (16 × 16 logical, at 2x), as in the rows."""
    pixmap = QPixmap(32, 32)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    paint(painter)
    painter.end()
    return QIcon(pixmap)


def _bar(fraction: float | None, paused: bool) -> Callable[[QPainter], None]:
    return lambda painter: paint_load_bar(painter, QRectF(0, 5, 16, 6), QColor("black"), fraction, paused, 0.5)


def _recheck(icon: Callable[[], QIcon], queued: bool = False) -> Callable[[QPainter], None]:
    """A recheck's small spinner or ring on a status icon (looked up when painted, after icon setup)."""
    def paint(painter: QPainter) -> None:
        icon().paint(painter, QRect(0, 0, 16, 16))
        paint_check_badge(painter, QRect(0, 0, 16, 16), 60, queued)
    return paint


def _first_check(selected: bool = False, queued: bool = False) -> Callable[[QPainter], None]:
    return lambda painter: paint_check(painter, QRect(-4, 0, 24, 16), 60, selected, queued)


def _icon(icon: Callable[[], QIcon]) -> Callable[[QPainter], None]:
    return lambda painter: icon().paint(painter, QRect(0, 0, 16, 16))


def _selected(paint: Callable[[QPainter], None]) -> Callable[[QPainter], None]:
    """On a selected row's highlight."""
    def painted(painter: QPainter) -> None:
        painter.fillRect(QRect(0, 0, 16, 16), QApplication.palette().highlight())
        paint(painter)
    return painted


def _spinner(colors: tuple[str, str], selected: bool = False) -> Callable[[QPainter], None]:
    return lambda painter: paint_spinner(painter, QRect(3, 3, 10, 10), 60, selected, colors)


RECHECK = ("Small blue spinner at the status icon's bottom right: a folder with a status is listed or checked "
           "again (select/expand, Check folder status or Retry/Refresh; the row's tooltip says which). "
           "The last status stays until the check finishes.")
QUEUED = " Queued for more than 0.5 s: a still dotted ring instead of the spinner (shorter waits spin)."
# Painted each frame (spinners rotate), so not QIcons: (name, what draws it, when it shows, paint).
ACTIVITY: tuple[tuple[str, str, str, Callable[[QPainter], None]], ...] = (
    ("first check", "paint_check",
     "Blue spinner in the status icon's place: the folder's first listing or status check, before it has a status.",
     _first_check()),
    ("first check, selected row", "paint_check(selected)", "A first check on the selected row: white.",
     _selected(_first_check(True))),
    ("first check, queued", "paint_check(queued): ICON_CHECK_QUEUED", "A first check waiting in the queue." + QUEUED,
     _first_check(queued=True)),
    ("first check, queued, selected row", "paint_check(selected, queued)",
     "A queued first check on the selected row: a white dotted ring.", _selected(_first_check(True, True))),
    ("recheck", "paint_check_badge", RECHECK, _recheck(lambda: StatusIcons.ICONS_STATUS["ok"])),
    ("recheck, queued", "paint_check_badge(queued): ICON_CHECK_QUEUED_BADGE", RECHECK + QUEUED,
     _recheck(lambda: StatusIcons.ICONS_STATUS["ok"], queued=True)),
    ("recheck, outdated status", "paint_check_badge",
     RECHECK + " On an outdated status the spinner covers the amber clock.",
     _recheck(lambda: StatusIcons.ICONS_STATUS_OLDER["fixable"])),
    ("recheck, queued, outdated status", "paint_check_badge(queued)",
     RECHECK + QUEUED + " On an outdated status the ring covers the amber clock.",
     _recheck(lambda: StatusIcons.ICONS_STATUS_OLDER["fixable"], queued=True)),
    ("recheck, status from subfolders", "paint_check_badge",
     RECHECK + " The same on a status derived from the subfolders (something / nothing).",
     _recheck(lambda: StatusIcons.ICONS_STATUS["something"])),
    ("recheck, queued, status from subfolders", "paint_check_badge(queued)",
     RECHECK + QUEUED + " The same on a status derived from the subfolders (something / nothing).",
     _recheck(lambda: StatusIcons.ICONS_STATUS["something"], queued=True)),
    ("recheck, selected row", "paint_check_badge", RECHECK + " On the selected row the badge keeps its white disc.",
     _selected(_recheck(lambda: StatusIcons.ICONS_STATUS["warning"]))),
    ("recheck, queued, selected row", "paint_check_badge(queued)",
     RECHECK + QUEUED + " On the selected row the ring keeps its white disc.",
     _selected(_recheck(lambda: StatusIcons.ICONS_STATUS["warning"], queued=True))),
    ("load", "paint_spinner(LOAD_SPINNER)",
     "Green spinner in the RAM badge's place: the folder's data is loading. RAM replaces it when done; "
     "queued and paused loads show load_queued / load_paused there.",
     _spinner(LOAD_SPINNER)),
    ("load, selected row", "paint_spinner(LOAD_SPINNER, selected)", "A load on the selected row: light green.",
     _selected(_spinner(LOAD_SPINNER, True))),
    ("load, queued", "ICON_LOAD_QUEUED", "A load waiting in the queue, in the RAM badge's place." + QUEUED,
     _icon(lambda: StatusIcons.ICON_LOAD_QUEUED)),
    ("load, paused", "ICON_LOAD_PAUSED",
     "A load paused while the current tab browses or loads, in the RAM badge's place.",
     _icon(lambda: StatusIcons.ICON_LOAD_PAUSED)),
    ("all I/O (status bar)", "paint_spinner(IO_SPINNER)",
     "Grey spinner at the left of the status bar: any I/O running in the app.",
     _spinner(IO_SPINNER)),
    ("load bar", "LoadBar (paint_load_bar)", "Folder details: the selected load's progress, in the load's green.",
     _bar(0.6, False)),
    ("load bar, paused", "LoadBar (paint_load_bar)", "Folder details: a paused load keeps its progress, in grey.",
     _bar(0.6, True)),
    ("load bar, busy", "LoadBar (paint_load_bar)",
     "Folder details: listing or checking before the first file is counted; the green segment slides across.",
     _bar(None, False)),
)
# Kept for older code, no longer shown by the folder browser: (name, attribute, why).
DEPRECATED: tuple[tuple[str, str, str], ...] = (
    ("loading", "ICON_LOADING",
     "Not shown by the folder browser: rows paint their activity (see Activity (painted)). Still in "
     "ICONS_STATUS / ICONS_EXTRA / ICONS_STATUS_OLDER as 'loading'."),
    ("paused", "ICON_PAUSED",
     "Not shown by the folder browser: a paused load shows load_paused (green circle-pause) in the RAM "
     "badge's place. Still in ICONS_STATUS / ICONS_STATUS_OLDER as 'paused'. Not the grey pause of "
     "no_auto_load (ICON_NO_AUTO_LOAD)."),
)


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
        self.activity_group = _IconGroup("Activity (painted)", expanded=True)
        self.tool_group = _IconGroup("Tool Icons", expanded=True)
        self.deprecated_group = _IconGroup("Deprecated Icons", expanded=False)
        self.percentage_group = _IconGroup("Percentage Icons (DO NOT USE)", expanded=False)
        groups = (self.status_group, self.activity_group, self.tool_group, self.deprecated_group,
                  self.percentage_group)
        for group in groups:
            layout.addWidget(group)
        self.status_list = self.status_group.icon_list
        self.activity_list = self.activity_group.icon_list
        self.tool_list = self.tool_group.icon_list
        self.deprecated_list = self.deprecated_group.icon_list
        self.percentage_list = self.percentage_group.icon_list

        deprecated = {getattr(StatusIcons, attribute) for _, attribute, _ in DEPRECATED}
        status_icons = {name: icon for name, icon in {**StatusIcons.ICONS_STATUS, **StatusIcons.ICONS_EXTRA}.items()
                        if icon not in deprecated}
        for name, icon in status_icons.items():
            attribute = ""
            for attr in dir(StatusIcons):
                if attr.startswith("ICON_"):
                    candidate = getattr(StatusIcons, attr)
                    if isinstance(candidate, QIcon) and candidate == icon:
                        attribute = attr
            item = self._add_icon(self.status_list, name, attribute, icon)
            if name == "cached_older":
                tooltip = ("Package + clock: folder modification time is newer than the cache save time.\n"
                           "Data cache may be outdated, or a later folder status check confirmed changed TXY fingerprints.\n"
                           "Use Load data to validate and update the data cache.")
                item.setToolTip(0, tooltip)
                item.setToolTip(1, tooltip)
            elif name == "status_cache_older":
                tooltip = ("Amber clock badge: folder modification time is newer than the last folder status check.\n"
                           "Cached counts and status may be outdated. Use Check folder status to recheck.")
                item.setToolTip(0, tooltip)
                item.setToolTip(1, tooltip)
            elif name == "report":
                tooltip = ("Report (folder row, after the data cache's badge): the folder has saved analysis results\n"
                           "that reuse will use (Settings → Cache › Reuse saved analysis results). The row tooltip\n"
                           "and Folder details say how many and their size.")
                item.setToolTip(0, tooltip)
                item.setToolTip(1, tooltip)
            elif name == "scan_failed":
                tooltip = ("Magnifying glass + exclamation mark: the last folder status check failed.\n"
                           "Automatic folder status checks are skipped. Use Check folder status to retry manually.\n"
                           "Previous counts, status and loaded data remain available.")
                item.setToolTip(0, tooltip)
                item.setToolTip(1, tooltip)

        for name, icon in StatusIcons.ICONS_STATUS_OLDER.items():
            if StatusIcons.ICONS_STATUS.get(name) in deprecated:
                continue
            item = self._add_icon(self.status_list, f"{name} (older status cache)",
                                  f'StatusIcons.ICONS_STATUS_OLDER["{name}"]', icon)
            tooltip = (f"Preserves the '{name}' status icon with an amber clock for possibly outdated scan results.\n"
                       "Use Check folder status to recheck counts and status.")
            item.setToolTip(0, tooltip)
            item.setToolTip(1, tooltip)

        for name, attribute, tooltip, paint in ACTIVITY:
            item = self._add_icon(self.activity_list, name, attribute, _painted(paint))
            item.setToolTip(0, tooltip)
            item.setToolTip(1, tooltip)

        for name, attribute, tooltip in DEPRECATED:
            item = self._add_icon(self.deprecated_list, name, attribute, getattr(StatusIcons, attribute))
            item.setToolTip(0, tooltip)
            item.setToolTip(1, tooltip)

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

        # All views share the width required by the longest icon name.
        for group in groups:
            group.icon_list.resizeColumnToContents(0)
        name_width = max(group.icon_list.columnWidth(0) for group in groups)
        for group in groups:
            group.icon_list.setColumnWidth(0, name_width)

        logging.debug("%s status icons, %s activity, %s tool icons, %s deprecated, %s percentage icons",
                      self.status_list.topLevelItemCount(), len(ACTIVITY), tool_count, len(DEPRECATED),
                      len(PercentageIcon.ICONS))

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
