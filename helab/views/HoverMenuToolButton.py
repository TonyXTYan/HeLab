"""A native toolbar button whose menu also opens after a brief hover."""
from PyQt6.QtCore import QEvent, QObject, QPoint, QSize, QTimer
from PyQt6.QtGui import QCursor, QEnterEvent, QPaintEvent
from PyQt6.QtWidgets import QMenu, QStyle, QStyleOptionToolButton, QStylePainter, QToolButton, QWidget


class HoverMenuToolButton(QToolButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAutoRaise(True)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(200)
        self._hover_timer.timeout.connect(self._open_hover_menu)
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.setInterval(500)
        self._dismiss_timer.timeout.connect(self._dismiss_if_outside)

    def setMenu(self, menu: QMenu | None) -> None:
        previous = self.menu()
        if previous is not None:
            previous.removeEventFilter(self)
            previous.aboutToHide.disconnect(self._menu_closing)
        self._dismiss_timer.stop()
        super().setMenu(menu)
        if menu is not None:
            menu.installEventFilter(self)
            menu.aboutToHide.connect(self._menu_closing)

    def _menu_closing(self) -> None:
        self._dismiss_timer.stop()
        self._hover_timer.stop()

    def _pointer_inside(self) -> bool:
        position = QCursor.pos()
        menu = self.menu()
        return (self.isVisible() and self.rect().contains(self.mapFromGlobal(position))) or (
            menu is not None and menu.isVisible() and menu.rect().contains(menu.mapFromGlobal(position)))

    def _update_dismiss_timer(self) -> None:
        menu = self.menu()
        if menu is None or not menu.isVisible() or self._pointer_inside():
            self._dismiss_timer.stop()
        elif not self._dismiss_timer.isActive():
            self._dismiss_timer.start()

    def _dismiss_if_outside(self) -> None:
        menu = self.menu()
        if menu is not None and menu.isVisible() and not self._pointer_inside():
            menu.close()

    def _menu_position(self, size: QSize) -> QPoint:
        """Right of the button, or left of it when the screen has no room."""
        position = self.mapToGlobal(QPoint(self.width(), 0))
        screen = self.screen()
        if screen is not None:
            area = screen.availableGeometry()
            if position.x() + size.width() > area.right() + 1:
                position.setX(self.mapToGlobal(QPoint(0, 0)).x() - size.width())
            position.setY(max(area.top(), min(position.y(), area.bottom() + 1 - size.height())))
        return position

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        menu = self.menu()
        if a0 is menu and menu is not None and a1 is not None:
            if a1.type() == QEvent.Type.Show:
                # Click and keyboard popups (Qt places them below) open where hover does.
                menu.move(self._menu_position(menu.size()))
            elif a1.type() in (QEvent.Type.Enter, QEvent.Type.Leave, QEvent.Type.MouseMove):
                self._update_dismiss_timer()
        return super().eventFilter(a0, a1)

    def enterEvent(self, a0: QEnterEvent | None) -> None:
        super().enterEvent(a0)
        self._dismiss_timer.stop()
        if self.isEnabled():
            self._hover_timer.start()

    def leaveEvent(self, a0: QEvent | None) -> None:
        self._hover_timer.stop()
        super().leaveEvent(a0)
        self._update_dismiss_timer()

    def _open_hover_menu(self) -> None:
        menu = self.menu()
        if self.isEnabled() and self.isVisible() and self.underMouse() and menu is not None and not menu.isVisible():
            menu.popup(self._menu_position(menu.sizeHint()))

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        # The icon is already a triangle. Hide Qt's additional menu indicator
        # while retaining the native toolbar hover, pressed and disabled states.
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.features &= ~QStyleOptionToolButton.ToolButtonFeature.HasMenu
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option)
