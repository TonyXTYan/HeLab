"""A plot's dock: ``AnalysisDock`` (the plot, with its settings section beside it while it
floats: ``FloatingSettings``, ``SettingsToggle``) and ``DockTabCloser`` (close buttons on
tabbed plots' tabs)."""
from __future__ import annotations

from typing import Callable, Optional, cast

from PyQt6 import sip
from PyQt6.QtCore import QObject, QRect, QSize, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QFocusEvent, QPainter, QPaintEvent
from PyQt6.QtWidgets import (QAbstractButton, QDockWidget, QMainWindow, QSizePolicy, QSplitter, QTabBar,
                             QVBoxLayout, QWidget)


# A wrapped object's C++ address (PyQt6's stub types it as returning None).
address_of = cast(Callable[[QObject], int], sip.unwrapinstance)


# Qt's largest widget size (QWIDGETSIZE_MAX), which PyQt6 doesn't export.
WIDGET_SIZE_MAX = (1 << 24) - 1


class SettingsToggle(QAbstractButton):
    """The header of a floating plot's settings section, which opens and closes it (a click,
    or Space): open, one line across the top, "▾", the plot's name and its settings summary,
    cut at the edge (the tooltip has it all); closed, a slim strip with "▸" and the same text
    running down it."""

    PADDING = 6

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)  # Repainted as the pointer enters and leaves.
        self.name = ""
        self.summary = ""
        self._keyboard_focus = False  # Its focus frame shows only then, not as its window activates.
        self.toggled.connect(self._fit)
        self._fit()

    def set_text(self, name: Optional[str] = None, summary: Optional[str] = None) -> None:
        """The plot's name and settings summary (None: as before)."""
        name = self.name if name is None else name
        summary = self.summary if summary is None else summary
        if (name, summary) != (self.name, self.summary):
            self.name, self.summary = name, summary
            self._fit()

    def text_shown(self) -> str:
        return " · ".join(filter(None, (self.name, self.summary)))

    def strip_width(self) -> int:
        return self.fontMetrics().height() + self.PADDING

    def sizeHint(self) -> QSize:
        across = self.strip_width()
        along = self.fontMetrics().horizontalAdvance(f"▾  {self.text_shown()}") + 2 * self.PADDING
        return QSize(along, across) if self.isChecked() else QSize(across, along)

    def minimumSizeHint(self) -> QSize:
        return QSize(self.strip_width(), self.strip_width())

    def _fit(self) -> None:
        policy = QSizePolicy.Policy
        if self.isChecked():
            self.setSizePolicy(policy.Ignored, policy.Fixed)
            action = "Hide this plot's settings"
        else:
            self.setSizePolicy(policy.Fixed, policy.Ignored)
            action = "Show this plot's settings"
        self.setToolTip("\n".join(filter(None, (action, self.name, self.summary))))
        self.updateGeometry()
        self.update()

    def focusInEvent(self, e: Optional[QFocusEvent]) -> None:
        reasons = (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)
        self._keyboard_focus = e is not None and e.reason() in reasons
        super().focusInEvent(e)

    def paintEvent(self, e: Optional[QPaintEvent]) -> None:
        painter = QPainter(self)
        palette = self.palette()
        hovered = self.underMouse() or self.isDown()
        painter.fillRect(self.rect(), palette.midlight() if hovered else palette.button())
        painter.setPen(palette.buttonText().color())
        if self.hasFocus() and self._keyboard_focus:
            painter.save()
            painter.setPen(palette.highlight().color())
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
            painter.restore()
        metrics, centred = self.fontMetrics(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        if self.isChecked():
            room = QRect(self.PADDING, 0, max(0, self.width() - 2 * self.PADDING), self.height())
            painter.drawText(room, centred, metrics.elidedText(
                f"▾  {self.text_shown()}", Qt.TextElideMode.ElideRight, room.width()))
            return
        # Closed: the arrow upright at the top, the text running down the strip below it.
        arrow = QRect(0, self.PADDING, self.width(), metrics.height())
        painter.drawText(arrow, Qt.AlignmentFlag.AlignCenter, "▸")
        start = arrow.bottom() + self.PADDING
        painter.translate(self.width(), start)
        painter.rotate(90)
        room = QRect(0, 0, max(0, self.height() - start - self.PADDING), self.width())
        painter.drawText(room, centred, metrics.elidedText(self.text_shown(), Qt.TextElideMode.ElideRight, room.width()))


class FloatingSettings(QWidget):
    """A floating plot's settings section, right of the plot in its window (``AnalysisDock``):
    the toggle, then the plot's settings page (``hold``, from the Settings panel) while open.
    It starts closed, a slim strip. Whether it is open and its width open are the plot's for
    the session: they last as long as its dock, floated and docked again."""

    MIN_WIDTH = 160
    DEFAULT_WIDTH = 300

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.toggle = SettingsToggle(self)
        self._layout.addWidget(self.toggle)
        self.page: Optional[QWidget] = None
        self.open_width = self.DEFAULT_WIDTH
        self._fit()

    @property
    def is_open(self) -> bool:
        return self.toggle.isChecked()

    def hold(self, page: QWidget) -> None:
        """Show ``page`` here (the plot floats); it keeps its edits."""
        self.page = page
        self._layout.addWidget(page, 1)
        self._fit()
        self.show()

    def release(self) -> Optional[QWidget]:
        """The page goes back to the Settings panel (the plot docks again, or closes)."""
        page, self.page = self.page, None
        if page is not None and sip.isdeleted(page):
            page = None
        if page is not None:
            self._layout.removeWidget(page)
        self.hide()
        return page

    def set_open(self, open_: bool) -> None:
        self.toggle.setChecked(open_)
        self._fit()

    def _fit(self) -> None:
        """Open: as wide as the splitter makes it; closed, the strip alone."""
        if self.is_open:
            self.setMinimumWidth(self.MIN_WIDTH)
            self.setMaximumWidth(WIDGET_SIZE_MAX)
        else:
            self.setFixedWidth(self.toggle.strip_width())
        if self.page is not None and not sip.isdeleted(self.page):
            self.page.setVisible(self.is_open)


class AnalysisDock(QDockWidget):
    """A plot dock that says when the user closes it (hiding, e.g. behind another tabbed
    dock, is not closing).

    Its widget (``widget()``, ``setWidget``) is the plot. Around it is a frame, a splitter
    with the plot's settings section (``settings``) on its right, shown only while the plot
    floats: the Settings panel moves the plot's page there and back (``PlotSettingsPanel``).
    Opening or closing the section widens or narrows the floating window by its width, so
    the plot keeps its size; the splitter sets the width open."""
    closed = pyqtSignal()

    def __init__(self, title: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(title, parent)
        self.frame = QSplitter(Qt.Orientation.Horizontal)
        self.frame.setChildrenCollapsible(False)
        self._body_holder = QWidget()
        self._body_layout = QVBoxLayout(self._body_holder)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(0)
        self._body: Optional[QWidget] = None
        self.settings = FloatingSettings()
        self.settings.hide()
        self.frame.addWidget(self._body_holder)
        self.frame.addWidget(self.settings)
        self.frame.setStretchFactor(0, 1)
        self.frame.setStretchFactor(1, 0)
        self.frame.splitterMoved.connect(self._splitter_moved)
        self.settings.toggle.clicked.connect(self.set_settings_open)
        self._fit_handle()
        super().setWidget(self.frame)

    def set_minimum_plot_size(self, width: int, height: int) -> None:
        """The least size of the plot's area (the plot with its source lines; the script's
        ``minimum_size``): docked, the window keeps room for it; floating, its window does."""
        self._body_holder.setMinimumSize(width, height)

    def widget(self) -> Optional[QWidget]:
        """The plot (not the frame around it)."""
        return self._body if self._body is not None and not sip.isdeleted(self._body) else None

    def setWidget(self, widget: Optional[QWidget]) -> None:
        """Show ``widget`` as the plot. As in Qt's own, the plot before it stays a (hidden)
        child of the dock until its owner deletes it, unless ``widget`` took it in (a wrapper
        around it): then it stays as it is, inside ``widget``."""
        old = self.widget()
        if old is widget:
            return
        if old is not None and old.parentWidget() is self._body_holder:
            self._body_layout.removeWidget(old)
            old.hide()
        self._body = widget
        if widget is not None:
            self._body_layout.addWidget(widget)
            widget.show()

    def hold_settings(self, page: QWidget) -> None:
        """Show the plot's settings ``page`` beside it (it floats), open or closed as last
        time, at its width (the plot gives up the room)."""
        self.settings.hold(page)
        self._fit_handle()
        width = self.settings.open_width if self.settings.is_open else self.settings.toggle.strip_width()
        self.frame.setSizes([max(1, self.frame.width() - self.frame.handleWidth() - width), width])

    @pyqtSlot(bool)
    def set_settings_open(self, open_: bool) -> None:
        """Open or close the settings section. While floating, the window widens or narrows by
        the change (within its screen), so the plot keeps its size; the width open is kept."""
        side = self.settings
        if not side.isVisible():
            side.set_open(open_)
            self._fit_handle()
            return
        before = side.width()  # The toggle has flipped already; the section hasn't.
        if not open_ and before > side.toggle.strip_width():
            side.open_width = before
        width = side.open_width if open_ else side.toggle.strip_width()
        side.setFixedWidth(width)  # While the window changes, the plot takes the difference.
        if self.isFloating():
            self._widen(width - before)
        side.set_open(open_)
        self._fit_handle()
        # The splitter's own sizes don't follow the section's new width when the window shrinks.
        self.frame.setSizes([max(1, self.frame.width() - self.frame.handleWidth() - width), width])

    def _widen(self, delta: int) -> None:
        geometry = self.geometry()
        width = max(self.minimumSizeHint().width(), geometry.width() + delta)
        left = geometry.x()
        screen = self.screen()
        if delta > 0 and screen is not None:  # Wider: kept on its screen, moved left if need be.
            available = screen.availableGeometry()
            width = min(width, available.width())
            left = max(available.left(), min(left, available.right() + 1 - width))
        self.setGeometry(left, geometry.y(), width, geometry.height())

    def _fit_handle(self) -> None:
        """The splitter's handle moves the section's edge only while it is open."""
        handle = self.frame.handle(1)
        if handle is not None:
            handle.setEnabled(self.settings.is_open)
            handle.setCursor(Qt.CursorShape.SplitHCursor if self.settings.is_open else Qt.CursorShape.ArrowCursor)

    @pyqtSlot(int, int)
    def _splitter_moved(self, pos: int, index: int) -> None:
        if self.settings.is_open:
            self.settings.open_width = self.settings.width()

    def closeEvent(self, event: QCloseEvent | None) -> None:
        super().closeEvent(event)
        self.closed.emit()


class DockTabCloser(QObject):
    """Gives the tabs of docks tabbed together in ``area`` a close button that closes that dock.
    Qt makes those tab bars itself as docks are tabbed; they are fitted on the next pass of the
    event loop after a watched dock is added, moved, floated, docked, shown or hidden (dock
    signals, no event filter). A tab is matched to its dock by identity: Qt's dock tab bars
    keep each tab's dock widget as its tab data (its address). Titles needn't be unique."""

    def __init__(self, area: QMainWindow) -> None:
        super().__init__(area)
        self.area = area
        self._fit_soon = QTimer(self)
        self._fit_soon.setSingleShot(True)
        self._fit_soon.setInterval(0)
        self._fit_soon.timeout.connect(self.fit)

    def watch(self, dock: QDockWidget) -> None:
        for signal in (dock.dockLocationChanged, dock.topLevelChanged, dock.visibilityChanged):
            signal.connect(self.schedule_fit)
        self.schedule_fit()

    @pyqtSlot()
    def schedule_fit(self) -> None:
        self._fit_soon.start()

    def fit(self) -> None:
        layout = self.area.layout()
        if layout is not None:
            layout.activate()  # Qt makes or reuses the tab bars as it lays the docks out.
        for bar in self.area.findChildren(QTabBar, options=Qt.FindChildOption.FindDirectChildrenOnly):
            if not bar.property("helabClosable"):
                bar.setProperty("helabClosable", True)
                bar.setTabsClosable(True)
                bar.tabCloseRequested.connect(lambda index, bar=bar: self.close_tab(bar, index))

    def close_tab(self, bar: QTabBar, index: int) -> None:
        dock = self.dock_at(bar, index)
        if dock is not None:
            dock.close()

    def dock_at(self, bar: QTabBar, index: int) -> Optional[QDockWidget]:
        """The dock of tab ``index`` (None if Qt ever stops keeping it as the tab data)."""
        address = bar.tabData(index)
        for dock in self.area.findChildren(QDockWidget):
            if address_of(dock) == address:
                return dock
        return None


