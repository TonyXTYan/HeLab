import logging

from PyQt6.QtCore import Qt, QModelIndex, QTimer, QEvent, QRect, QPoint, QObject
from PyQt6.QtGui import QMouseEvent, QFocusEvent
from PyQt6.QtWidgets import QTreeView, QWidget, QVBoxLayout, QPushButton, QLabel, QHBoxLayout

from helab.models.helabFileSystemModel import helabFileSystemModel


class StatusHoverIconInfo(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        # Update window flags to include WindowStaysOnTopHint and remove FramelessWindowHint
        self.setWindowFlags(
            Qt.WindowType.Popup |
            Qt.WindowType.WindowStaysOnTopHint
        )
        # self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        layout = QVBoxLayout()
        # Reduce the margins and spacing to minimize padding
        layout.setContentsMargins(8, 6, 8, 2)  # left, top, right, bottom
        layout.setSpacing(4)  # space between widgets

        self.label = QLabel("Detailed Info")
        self.button1 = QPushButton("Action 1")
        self.button2 = QPushButton("Action 2")

        # Connect buttons to placeholder functions
        self.button1.clicked.connect(self.action1)
        self.button2.clicked.connect(self.action2)

        layout.addWidget(self.label)

        button_layout = QHBoxLayout()
        # Remove margins and reduce spacing between buttons
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(2)

        button_layout.addWidget(self.button1)
        button_layout.addWidget(self.button2)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def set_info(self, info_text: str) -> None:
        self.label.setText(info_text)

    # Placeholder function for Action 1
    def action1(self) -> None:
        logging.debug("Action 1 triggered")
        # You can replace the print statement with actual functionality later

    # Placeholder function for Action 2
    def action2(self) -> None:
        logging.debug("Action 2 triggered")
        # You can replace the print statement with actual functionality later


class StatusTreeView(QTreeView):
    def __init__(self, parent: QTreeView | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.popup = StatusHoverIconInfo()
        self.popup.setParent(None)  # Make it a top-level window
        self.popup.installEventFilter(self)
        self.current_hover_index = QModelIndex()
        self.popup_visible = False

        # Timer to delay hiding the popup
        self.hover_timer = QTimer()
        self.hover_timer.setSingleShot(True)
        self.hover_timer.timeout.connect(self.hide_popup)

        self.popup.installEventFilter(self)

    def eventFilter(self, object: QObject | None, event: QEvent | None) -> bool:
        if event is None: return False
        if object == self.popup:
            if event.type() == QEvent.Type.Enter:
                # Stop the hide timer when cursor enters the popup
                self.hover_timer.stop()
            elif event.type() == QEvent.Type.Leave:
                # Start the hide timer when cursor leaves the popup
                self.hover_timer.start(500)  # Delay hiding by 500 ms
        return super().eventFilter(object, event)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None: return
        pos = event.pos()
        index = self.indexAt(pos)
        if index.isValid() and index.column() == helabFileSystemModel.COLUMN_STATUS_ICON:
            # Determine if the mouse is over the icon area
            rect = self.visualRect(index)
            icon_size = self.iconSize()
            padding = 5  # Adjust based on your delegate's padding
            status_icon_rect = QRect(
                rect.left() + padding,
                rect.top() + (rect.height() - icon_size.height()) // 2,
                icon_size.width(),
                icon_size.height()
            )
            extra_icons = index.data(helabFileSystemModel.STATUS_EXTRA_ICONS_ROLE)
            extra_icon_rects = []
            if extra_icons:
                x_offset = status_icon_rect.right() + 2  # 2px spacing between icons
                for _ in extra_icons:
                    extra_rect = QRect(
                        x_offset,
                        rect.top() + (rect.height() - icon_size.height()) // 2,
                        icon_size.width(),
                        icon_size.height()
                    )
                    extra_icon_rects.append(extra_rect)
                    x_offset += icon_size.width() + 2

            # Check if the mouse is within any icon rect
            over_icon = False
            if status_icon_rect.contains(event.pos()):
                over_icon = True
            else:
                for extra_rect in extra_icon_rects:
                    if extra_rect.contains(event.pos()):
                        over_icon = True
                        break

            if over_icon:
                if index != self.current_hover_index:
                    self.current_hover_index = index
                    self.show_popup(event.globalPosition().toPoint(), index)
            else:
                self.hover_timer.start(300)  # Delay hiding by 300ms
        else:
            self.hover_timer.start(300)  # Delay hiding by 300ms
        super().mouseMoveEvent(event)

    def leaveEvent(self, a0: QEvent | None) -> None:
        if a0 is None: return
        self.hover_timer.start(300)  # Delay hiding by 300ms
        super().leaveEvent(a0)

    def show_popup(self, global_pos: QPoint, index: QModelIndex) -> None:
        if not index.isValid():
            return
        model = self.model()
        if model is None or not hasattr(model, 'filePath') or not hasattr(model, 'fetch_status'):
            logging.error("show_popup: model is bad")
            return
        if not isinstance(model, helabFileSystemModel):
            logging.error("show_popup: model is not helabFileSystemModel")
            return
        # Get data from the model
        file_path = model.filePath(index)
        # status, count, extra_icons = self.model().get_status(file_path)
        status, count, extra_icons = model.fetch_status(file_path)
        info_text = f"Path: {file_path}\nStatus: {status}\nCount: {count}\nExtra Icons: {', '.join(extra_icons) if extra_icons else 'None'}"
        self.popup.set_info(info_text)
        # Position the popup near the cursor
        # self.popup.move(global_pos + QPoint(10, 10))  # Slight offset
        self.popup.move(global_pos - QPoint(1, 1))  # Slight offset
        self.popup.show()
        self.popup_visible = True

    def hide_popup(self) -> None:
        if self.popup_visible and self.popup is not None:
            try:
                self.popup.hide()
            except RuntimeError:
                logging.error("Attempted to hide a deleted popup")
            # self.popup.hide()
            self.popup_visible = False
            self.current_hover_index = QModelIndex()

    def focusOutEvent(self, e: QFocusEvent | None) -> None:
        if e is None: return
        super().focusOutEvent(e)
        self.hide_popup()
