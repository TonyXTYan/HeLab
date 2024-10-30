from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from pytablericons import TablerIcons


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

def tablerIcon(icon, color, size=128):
    return QIcon(
        TablerIcons
        .load(icon, color=color)
        .toqpixmap()
        .scaled(size, size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
                )
    )

