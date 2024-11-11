from enum import IntEnum, Enum
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from pytablericons import TablerIcons, OutlineIcon, FilledIcon


def tablerIcon(icon: OutlineIcon, color: str, size: int=128) -> QIcon: 
    return QIcon(
        TablerIcons
        .load(icon, color=color)
        .toqpixmap()
        .scaled(size, size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
                )
    )


class StatusIcons:
    STATUS_ICONS_NAME = ['ok', 'warning', 'critical', 'loading', 'nothing']
    STATUS_ICONS_EXTRA_NAME = ['database', 'report', 'chart3d', 'ram', 'live']
    STATUS_ICONS_EXTRA_NAME_SORT_KEY = {
        'database': 10,
        'report': 31,
        'chart3d': 30,
        'ram': 11,
        'live': 0,
    }

    # ICON_OK = tablerIcon(OutlineIcon.CIRCLE_CHECK, '#00bb39')
    @staticmethod
    def initialise_icons() -> None:
        StatusIcons.ICON_OK = tablerIcon(OutlineIcon.CIRCLE_CHECK, '#00bb39')
        StatusIcons.ICON_CRITICAL = tablerIcon(OutlineIcon.XBOX_X, '#e50000')
        StatusIcons.ICON_WARNING = tablerIcon(OutlineIcon.ALERT_CIRCLE, '#f8c350')
        StatusIcons.ICON_LOADING = tablerIcon(OutlineIcon.LOADER, '#000000')  # TODO: replace this with PERCENTAGE
        StatusIcons.ICON_LIVE = tablerIcon(OutlineIcon.LIVE_PHOTO, '#000000')
        StatusIcons.ICON_NOTHING = tablerIcon(FilledIcon.POINT, '#bbbbbb')
        StatusIcons.ICONS_STATUS = {
            'ok': StatusIcons.ICON_OK,
            'warning': StatusIcons.ICON_WARNING,
            'critical': StatusIcons.ICON_CRITICAL,
            'loading': StatusIcons.ICON_LOADING,
            'nothing': StatusIcons.ICON_NOTHING,
        }
        StatusIcons.ICON_DATABASE = tablerIcon(OutlineIcon.DATABASE, '#444444')
        StatusIcons.ICON_REPORT = tablerIcon(OutlineIcon.REPORT_ANALYTICS, '#444444')
        StatusIcons.ICON_CHART3D = tablerIcon(OutlineIcon.CHART_SCATTER_3D, '#444444')
        StatusIcons.ICON_RAM = tablerIcon(OutlineIcon.CONTAINER, '#444444')
        StatusIcons.ICONS_EXTRA = {
            'database': StatusIcons.ICON_DATABASE,
            'report': StatusIcons.ICON_REPORT,
            'chart3d': StatusIcons.ICON_CHART3D,
            'ram': StatusIcons.ICON_RAM,
            'live': StatusIcons.ICON_LIVE,
        }

class ToolIcons:
    @staticmethod
    def initialise_icons() -> None:
        ToolIcons.ICON_PLUS = tablerIcon(OutlineIcon.LIBRARY_PLUS, '#000000')
        ToolIcons.ICON_MINUS = tablerIcon(OutlineIcon.LIBRARY_MINUS, '#000000')
        ToolIcons.ICON_TAB_PLUS = tablerIcon(OutlineIcon.BROWSER_PLUS, '#000000')
        ToolIcons.ICON_TAB_MINUS = tablerIcon(OutlineIcon.BROWSER_X, '#000000')
        ToolIcons.ICON_STACK2 = tablerIcon(OutlineIcon.STACK, '#000000')
        ToolIcons.ICON_STACK3 = tablerIcon(OutlineIcon.STACK_2, '#000000')
        ToolIcons.ICON_STACK4 = tablerIcon(OutlineIcon.STACK_3, '#000000')

        ToolIcons.ICON_SETTING = tablerIcon(OutlineIcon.SETTINGS, '#000000')

        ToolIcons.ICON_REFRESH = tablerIcon(OutlineIcon.REFRESH, '#000000')

        ToolIcons.ICON_FOLDER_UP = tablerIcon(OutlineIcon.FOLDER_UP, '#000000')

        ToolIcons.ICON_LEFT_COLLAPSE = tablerIcon(OutlineIcon.LAYOUT_SIDEBAR_LEFT_COLLAPSE, '#000000')
        ToolIcons.ICON_LEFT_EXPAND = tablerIcon(OutlineIcon.LAYOUT_SIDEBAR_LEFT_EXPAND, '#000000')

        ToolIcons.ICON_BOTTOM_COLLAPSE = tablerIcon(OutlineIcon.LAYOUT_BOTTOMBAR_COLLAPSE, '#000000')
        ToolIcons.ICON_BOTTOM_EXPAND = tablerIcon(OutlineIcon.LAYOUT_BOTTOMBAR_EXPAND, '#000000')
        ToolIcons.ICON_BOTTOM_INACTIVE = tablerIcon(OutlineIcon.LAYOUT_BOTTOMBAR_INACTIVE, '#000000')

        ToolIcons.ICON_ZOOM_CANCEL = tablerIcon(OutlineIcon.ZOOM_CANCEL, '#000000')

class PercentageIcon:
    @staticmethod
    def initialise_icons() -> None:
        # THIS IS NOT THE INTENDED PERCENTAGE ICON
        # NEED PYTABLERICONS TO UPDATE
        PercentageIcon.ICON_10 = tablerIcon(OutlineIcon.PERCENTAGE, '#000000')

class IconsInitUtil:
    @staticmethod
    def initialise_icons() -> None:
        StatusIcons.initialise_icons()
        ToolIcons.initialise_icons()
        PercentageIcon.initialise_icons()