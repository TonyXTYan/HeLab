from PyQt6.QtCore import Qt, QSize, QRect
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

from helium.models.heliumFileSystemModel import CustomFileSystemModel


class StatusIconDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        # Clear the icon to prevent the default drawing
        option.icon = QIcon()

    def paint(self, painter, option, index):
        # Paint the base item (text, etc.) without the default decoration
        option_copy = QStyleOptionViewItem(option)
        option_copy.decorationSize = QSize(0, 0)  # Prevent default decoration
        super().paint(painter, option_copy, index)

        # Retrieve the main status icon
        status_icon = index.data(Qt.ItemDataRole.DecorationRole)
        # Retrieve the extra icons
        extra_icons = index.data(CustomFileSystemModel.STATUS_EXTRA_ICONS_ROLE)
        rect = option.rect
        x = rect.left() + 5  # Some padding from the left
        y = rect.top() + (rect.height() - option.decorationSize.height()) // 2

        # Draw the status icon
        if status_icon:
            icon_size = option.decorationSize
            status_icon.paint(painter, QRect(x, y, icon_size.width(), icon_size.height()))
            x += icon_size.width() + 2  # Spacing between icons

        # Draw the extra icons
        if extra_icons:
            for icon in extra_icons:
                if icon:
                    icon_size = option.decorationSize
                    icon.paint(painter, QRect(x, y, icon_size.width(), icon_size.height()))
                    x += icon_size.width() + 2  # Spacing between icons

    def sizeHint(self, option, index):
        # Ensure the size hint accommodates all icons
        base_size = super().sizeHint(option, index)
        status_icon = index.data(Qt.ItemDataRole.DecorationRole)
        extra_icons = index.data(CustomFileSystemModel.STATUS_EXTRA_ICONS_ROLE)
        total_width = base_size.width()
        if status_icon:
            total_width += option.decorationSize.width() + 4  # Status icon and spacing
        if extra_icons:
            total_width += len(extra_icons) * (option.decorationSize.width() + 4)  # Extra icons and spacing
        return QSize(total_width, base_size.height())
