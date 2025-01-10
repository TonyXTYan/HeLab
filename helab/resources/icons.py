import functools
from enum import IntEnum, Enum
# from functools import lru_cache
from typing import Dict

from PIL.ImageQt import ImageQt
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QIcon, QPixmap, QImage, QPainter, QFont, QColor, QPen, QBrush
from pytablericons import TablerIcons, OutlineIcon, FilledIcon

# from helab.utils.constants import helab_mono_font

from functools import lru_cache as functools_lru_cache

# def tablerIcon_old(icon: OutlineIcon | FilledIcon, color: str, size: int=128) -> QIcon:
#     return QIcon(
#         TablerIcons
#         .load(icon, color=color)
#         .toqpixmap()
#         .scaled(size, size,
#                 Qt.AspectRatioMode.KeepAspectRatio,
#                 Qt.TransformationMode.SmoothTransformation
#                 )
#     )

def tablerIcon(icon: OutlineIcon | FilledIcon, color: str, size: int=128) -> QIcon:
    image = TablerIcons.load(icon, color=color)
    pixmap = QPixmap.fromImage(ImageQt(image))
    pixmap = pixmap.scaled(size, size,
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    return QIcon(pixmap)


class StatusIcons:
    STATUS_ICONS_NAME = [
        'ok',
        'fixable',
        'warning',
        'critical',
        'loading',
        'nothing',
        'something',
        'unknown',
        'missing',
        'cancelled',
        'paused'
    ]
    STATUS_ICONS_EXTRA_NAME = [
        'database',
        'report',
        'chart3d',
        'ram',
        'ram_single',
        'ram_opened',
        'live',
        'waiting',
        'loading',
        'loading_ram',
        'progress',
        'progress_ram'
    ]
    STATUS_ICONS_EXTRA_NAME_SORT_KEY = {
        'database':     230,
        'report':       240,
        'chart3d':      250,
        'ram':           11,
        'ram_single':    12,
        'ram_opened':    13,
        'progress_ram':  11,
        'loading_ram':   10,
        'loading':        0,
        'progress':       1,
        'live':         100,
        'waiting':        1,
    }
    ICON_OK = QIcon()
    ICON_FIXABLE = QIcon()
    ICON_CRITICAL = QIcon()
    ICON_WARNING = QIcon()
    ICON_LOADING = QIcon()
    ICON_LIVE = QIcon()
    ICON_NOTHING = QIcon()
    ICON_SOMETHING = QIcon()
    ICON_UNKNOWN = QIcon()
    ICON_MISSING = QIcon()
    ICON_CANCELLED = QIcon()
    ICON_PAUSED = QIcon()
    ICON_MAYBE = QIcon()

    ICONS_STATUS: Dict[str, QIcon] = {}

    ICON_WAITING = QIcon()
    ICON_DATABASE = QIcon()
    ICON_REPORT = QIcon()
    ICON_CHART3D = QIcon()
    ICON_RAM = QIcon()
    ICON_RAM_SINGLE = QIcon()
    ICON_RAM_OPENED = QIcon()
    ICON_CIRCLE = QIcon()

    ICONS_EXTRA: Dict[str, QIcon] = {}


    # ICON_OK = tablerIcon(OutlineIcon.CIRCLE_CHECK, '#00bb39')
    @staticmethod
    def initialise_icons() -> None:
        StatusIcons.ICON_OK = tablerIcon(OutlineIcon.CIRCLE_CHECK, '#00bb39')
        StatusIcons.ICON_FIXABLE = tablerIcon(OutlineIcon.HELP_CIRCLE, '#B8D20E')
        StatusIcons.ICON_CRITICAL = tablerIcon(OutlineIcon.XBOX_X, '#e50000')
        StatusIcons.ICON_WARNING = tablerIcon(OutlineIcon.ALERT_CIRCLE, '#f8c350')
        StatusIcons.ICON_LOADING = tablerIcon(OutlineIcon.LOADER, '#000000')  # TODO: replace this with PERCENTAGE
        StatusIcons.ICON_LIVE = tablerIcon(OutlineIcon.EYE, '#000000')
        StatusIcons.ICON_NOTHING = tablerIcon(FilledIcon.POINT, '#bbbbbb')
        StatusIcons.ICON_SOMETHING = tablerIcon(OutlineIcon.CIRCLE_DOT, '#bbbbbb')
        StatusIcons.ICON_UNKNOWN = tablerIcon(OutlineIcon.CIRCLE_DASHED, '#bbbbbb')
        StatusIcons.ICON_MISSING = tablerIcon(OutlineIcon.ERROR_404, '#bbbbbb')
        StatusIcons.ICON_CANCELLED = tablerIcon(OutlineIcon.PROGRESS_X, '#9923bd')
        StatusIcons.ICON_PAUSED = tablerIcon(OutlineIcon.PLAYER_PAUSE, '#000000')
        StatusIcons.ICON_MAYBE = tablerIcon(OutlineIcon.PROGRESS_HELP, '#000000')
        StatusIcons.ICONS_STATUS = {
            'ok': StatusIcons.ICON_OK,
            'fixable': StatusIcons.ICON_FIXABLE,
            'warning': StatusIcons.ICON_WARNING,
            'critical': StatusIcons.ICON_CRITICAL,
            'loading': StatusIcons.ICON_LOADING,
            'nothing': StatusIcons.ICON_NOTHING,
            'something': StatusIcons.ICON_SOMETHING,
            'unknown': StatusIcons.ICON_UNKNOWN,
            'missing': StatusIcons.ICON_MISSING,
            'cancelled': StatusIcons.ICON_CANCELLED,
            'paused': StatusIcons.ICON_PAUSED,
            'maybe': StatusIcons.ICON_MAYBE,
        }
        StatusIcons.ICON_WAITING = tablerIcon(OutlineIcon.HOURGLASS, '#888888')
        StatusIcons.ICON_DATABASE = tablerIcon(OutlineIcon.DATABASE, '#888888')
        StatusIcons.ICON_REPORT = tablerIcon(OutlineIcon.REPORT_ANALYTICS, '#888888')
        StatusIcons.ICON_CHART3D = tablerIcon(OutlineIcon.CHART_SCATTER_3D, '#888888')
        StatusIcons.ICON_RAM = tablerIcon(OutlineIcon.CONTAINER, '#888888')
        StatusIcons.ICON_RAM_SINGLE = tablerIcon(OutlineIcon.CONTAINER, '#FF44BB')
        StatusIcons.ICON_RAM_OPENED = tablerIcon(OutlineIcon.CONTAINER, '#00FF00')
        StatusIcons.ICON_CIRCLE = tablerIcon(OutlineIcon.CIRCLE, '#888888')
        StatusIcons.ICONS_EXTRA = {
            'database': StatusIcons.ICON_DATABASE,
            'report': StatusIcons.ICON_REPORT,
            'chart3d': StatusIcons.ICON_CHART3D,
            'ram': StatusIcons.ICON_RAM,
            'ram_single': StatusIcons.ICON_RAM_SINGLE,
            'ram_opened': StatusIcons.ICON_RAM_OPENED,
            'live': StatusIcons.ICON_LIVE,
            'waiting': StatusIcons.ICON_WAITING,
            'loading': StatusIcons.ICON_LOADING,
            'loading_ram': StatusIcons.ICON_WAITING,
            'progress': StatusIcons.ICON_CIRCLE,
            'progress_ram': StatusIcons.ICON_CIRCLE,
        }

class ToolIcons:
    ICON_PLUS = QIcon()
    ICON_MINUS = QIcon()
    ICON_TAB_PLUS = QIcon()
    ICON_TAB_MINUS = QIcon()
    ICON_STACK2 = QIcon()
    ICON_STACK3 = QIcon()
    ICON_STACK4 = QIcon()
    ICON_SETTINGS = QIcon()
    ICON_REFRESH = QIcon()
    ICON_FOLDER_UP = QIcon()
    ICON_LEFT_COLLAPSE = QIcon()
    ICON_LEFT_EXPAND = QIcon()
    ICON_RIGHT_COLLAPSE = QIcon()
    ICON_RIGHT_EXPAND = QIcon()
    ICON_BOTTOM_COLLAPSE = QIcon()
    ICON_BOTTOM_EXPAND = QIcon()
    ICON_BOTTOM_INACTIVE = QIcon()
    ICON_ZOOM_CANCEL = QIcon()
    ICON_ZOOM_SCAN = QIcon()
    ICON_ZOOM_REPLACE = QIcon()
    ICON_LIVE = QIcon()


    @staticmethod
    def initialise_icons() -> None:
        ToolIcons.ICON_PLUS = tablerIcon(OutlineIcon.LIBRARY_PLUS, '#000000')
        ToolIcons.ICON_MINUS = tablerIcon(OutlineIcon.LIBRARY_MINUS, '#000000')
        ToolIcons.ICON_TAB_PLUS = tablerIcon(OutlineIcon.BROWSER_PLUS, '#000000')
        ToolIcons.ICON_TAB_MINUS = tablerIcon(OutlineIcon.BROWSER_X, '#000000')
        ToolIcons.ICON_STACK2 = tablerIcon(OutlineIcon.STACK, '#000000')
        ToolIcons.ICON_STACK3 = tablerIcon(OutlineIcon.STACK_2, '#000000')
        ToolIcons.ICON_STACK4 = tablerIcon(OutlineIcon.STACK_3, '#000000')

        ToolIcons.ICON_SETTINGS = tablerIcon(OutlineIcon.SETTINGS, '#000000')

        ToolIcons.ICON_REFRESH = tablerIcon(OutlineIcon.RELOAD, '#000000')

        ToolIcons.ICON_FOLDER_UP = tablerIcon(OutlineIcon.FOLDER_UP, '#000000')

        ToolIcons.ICON_LEFT_COLLAPSE = tablerIcon(OutlineIcon.LAYOUT_SIDEBAR_LEFT_COLLAPSE, '#000000')
        ToolIcons.ICON_LEFT_EXPAND = tablerIcon(OutlineIcon.LAYOUT_SIDEBAR_LEFT_EXPAND, '#000000')
        ToolIcons.ICON_RIGHT_COLLAPSE = tablerIcon(OutlineIcon.LAYOUT_SIDEBAR_RIGHT_COLLAPSE, '#000000')
        ToolIcons.ICON_RIGHT_EXPAND = tablerIcon(OutlineIcon.LAYOUT_SIDEBAR_RIGHT_EXPAND, '#000000')


        ToolIcons.ICON_BOTTOM_COLLAPSE = tablerIcon(OutlineIcon.LAYOUT_BOTTOMBAR_COLLAPSE, '#000000')
        ToolIcons.ICON_BOTTOM_EXPAND = tablerIcon(OutlineIcon.LAYOUT_BOTTOMBAR_EXPAND, '#000000')
        ToolIcons.ICON_BOTTOM_INACTIVE = tablerIcon(OutlineIcon.LAYOUT_BOTTOMBAR_INACTIVE, '#000000')

        ToolIcons.ICON_ZOOM_CANCEL = tablerIcon(OutlineIcon.ZOOM_CANCEL, '#000000')
        ToolIcons.ICON_ZOOM_SCAN = tablerIcon(OutlineIcon.ZOOM_SCAN, '#000000')
        ToolIcons.ICON_ZOOM_REPLACE = tablerIcon(OutlineIcon.ZOOM_REPLACE, '#000000')

        ToolIcons.ICON_LIVE = tablerIcon(OutlineIcon.SCAN_EYE, '#000000')

class PercentageIcon:
    ICON_10 = QIcon()

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

def str_to_QIcon(text: str, size: int = 128*4, scaled: int = 128) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setPen(Qt.GlobalColor.black)
    painter.setFont(QFont("Monospaced", 128*2))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    pixmap = pixmap.scaled(scaled, scaled,
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    return QIcon(pixmap)


def circular_progress_QIcon_cached(progress: float) -> QIcon:
    return circular_progress_QIcon_cached_helper(round(progress * 720))

@functools_lru_cache(maxsize=720+1)
def circular_progress_QIcon_cached_helper(progress: int) -> QIcon:
    return circular_progress_QIcon(float(progress / 720))

def circular_progress_QIcon(
    progress: float,
    size: int = 128,
    outline_thickness: float = 12.0,
    outer_padding: float = 12.0,
    outline_color: QColor = QColor("#888888"),
    fill_color: QColor = QColor("#888888")
) -> QIcon:
    """
    Draws a circular outline and fills a pie wedge from the top-center (12 o’clock)
    clockwise to represent 'progress' (from 0.0 to 1.0).

    :param progress: Fraction of circle to fill [0.0, 1.0].
    :param size: Size (width & height) of the returned QIcon’s pixmap.
    :param outline_thickness: Thickness of the circle’s outline.
    :param outer_padding: Extra space between the icon boundary and the circle.
    :param outline_color: Color for the circle’s outline.
    :param fill_color: Color of the pie fill.
    :return: QIcon containing the rendered circle+pie image.
    """
    # Create a transparent pixmap.
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # margin includes both outer_padding and half of the outline thickness
    # so the outline will not be cut off.
    margin = int(outer_padding + (outline_thickness / 2.0))

    # The drawing rectangle where we’ll draw the circle/arc.
    rect = QRect(margin, margin, size - 2 * margin, size - 2 * margin)

    # 1) Draw the circle outline.
    outline_pen = QPen(outline_color, outline_thickness)
    painter.setPen(outline_pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(rect)

    # 2) Fill the pie wedge (from top-center, clockwise).
    fill_angle = int(progress * 360 * 16)
    fill_brush = QBrush(fill_color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fill_brush)

    # Start at top-center (90° in painter’s coordinates) and move clockwise by -angle.
    painter.drawPie(rect, 90 * 16, -fill_angle)

    painter.end()
    return QIcon(pixmap)