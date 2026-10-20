"""The one Settings panel (``PlotSettingsPanel``): the active plot's settings page, moved
into a floating plot's window and back (``DragEnd`` waits for a dragged plot)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QGuiApplication, QWindow
from PyQt6.QtWidgets import (QApplication, QComboBox, QDockWidget, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                             QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from helab.views.plots.dock import AnalysisDock


def mouse_held() -> bool:
    """Whether a mouse button is down (as of the last mouse event Qt had)."""
    return QGuiApplication.mouseButtons() != Qt.MouseButton.NoButton


class DragEnd(QObject):
    """Says when the user lets go of plot docks being dragged (``ended``). Qt floats a dock as
    a drag of it starts and docks it at the drop, so whether it floats is settled only then.
    While waiting for a dock it filters that dock's events, and only its own: the first mouse
    event it gets with no button down (the release, or a move, hover, enter or leave after a
    release it didn't see, as when a system move of its window ended) ends the wait and the
    filter. Nothing runs between drags."""

    ended = pyqtSignal(QDockWidget)
    MOUSE = {QEvent.Type.MouseButtonRelease, QEvent.Type.NonClientAreaMouseButtonRelease,
             QEvent.Type.MouseMove, QEvent.Type.NonClientAreaMouseMove, QEvent.Type.HoverMove,
             QEvent.Type.Enter, QEvent.Type.Leave}

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._waiting: List[QDockWidget] = []

    def wait(self, dock: QDockWidget) -> None:
        if dock not in self._waiting:
            self._waiting.append(dock)
            dock.installEventFilter(self)

    def waiting(self, dock: QDockWidget) -> bool:
        return dock in self._waiting

    def stop(self, dock: QDockWidget) -> None:
        if dock in self._waiting:
            self._waiting.remove(dock)
            if not sip.isdeleted(dock):
                dock.removeEventFilter(self)

    def eventFilter(self, a0: Optional[QObject], a1: Optional[QEvent]) -> bool:
        if (isinstance(a0, QDockWidget) and a1 is not None and a1.type() in self.MOUSE
                and a0 in self._waiting and not mouse_held()):
            self.stop(a0)
            self.ended.emit(a0)
        return False


class PlotSettingsPanel(QWidget):
    """The settings of the active plot: one page per open plot, showing the page of the plot
    last clicked, focused or brought to the front among tabbed docks, floating ones included.
    The chooser on top names it and picks another plot (raising its dock). A page keeps its
    edits while another plot's page shows. With no plot open, a hint shows instead.

    It follows Qt's own signals, which fire only when something changes: the app's focus
    (a click anywhere in a plot focuses it, as its dock takes click focus), the active window
    (a floating plot), the plot area's tab activations and the plots' visibility (the shown
    plot hidden: the most recently shown plot still visible shows, as when it closes). No
    Python runs per event (no event filter, but on a plot being dragged, until it is let go:
    ``DragEnd``), and the connections end with the panel or ``detach()``. Whenever a plot shows, focus left in another plot moves to it, so focus is
    never in a plot other than the shown one, and a click in any other plot changes focus.

    A floating plot's page moves into its window (``AnalysisDock.settings``: the same
    editors, with their edits and Rerun) and back when it docks again; while it is the shown
    plot, the panel says so, with a button that raises its window. A plot being dragged
    (out, and maybe back) keeps its page where it is until the user lets go (``DragEnd``):
    then it moves once, or not at all if the plot is docked again.

    ``plotShown`` says when a plot becomes the shown one (a released plot may reload then);
    clicks in the plot already shown don't repeat it."""

    plotShown = pyqtSignal(QDockWidget)

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.chooser = QComboBox()
        self.chooser.setToolTip("The plot these settings are for; click a plot to show its settings")
        self.chooser.activated.connect(lambda index: self.show_plot(self._order[index], raise_dock=True))
        self.close_button = QToolButton()
        self.close_button.setText("✕")
        self.close_button.setToolTip("Close this plot")
        self.close_button.clicked.connect(self.close_current)
        self.chooser_row = QWidget()
        row = QHBoxLayout(self.chooser_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        row.addWidget(self.chooser, 1)
        row.addWidget(self.close_button)
        layout.addWidget(self.chooser_row)
        self.stack = QStackedWidget()
        self.hint = QLabel("Run a plot from Scripts below; its settings appear here.")
        self.hint.setWordWrap(True)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.stack.addWidget(self.hint)
        self.away = QWidget()  # The shown plot floats: its settings are in its window.
        away_row = QHBoxLayout(self.away)
        away_row.setContentsMargins(4, 0, 4, 0)
        away_row.addWidget(QLabel("Settings are in this plot's window"))
        self.away_button = QPushButton("Show plot window")
        self.away_button.setToolTip("Bring this plot's window to the front, with its settings open")
        self.away_button.clicked.connect(self.raise_current)
        away_row.addWidget(self.away_button)
        away_row.addStretch(1)
        away_row.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.stack.addWidget(self.away)
        layout.addWidget(self.stack, 1)
        self._pages: Dict[QDockWidget, QWidget] = {}
        self._order: List[QDockWidget] = []  # the chooser's order: as opened
        self._recent: List[QDockWidget] = []  # most recently shown last
        self._followed: List[QMainWindow] = []
        self._check_shown = QTimer(self)
        self._check_shown.setSingleShot(True)
        self._check_shown.setInterval(0)
        self._check_shown.timeout.connect(self._shown_still_visible)
        # Floated or docked: the page moves a pass of the event loop later, or after a drag.
        self._unplaced: List[QDockWidget] = []
        self._place_soon = QTimer(self)
        self._place_soon.setSingleShot(True)
        self._place_soon.setInterval(0)
        self._place_soon.timeout.connect(self._place_moved)
        self._drag_end = DragEnd(self)
        self._drag_end.ended.connect(self._drag_ended)
        self._update_chooser()
        app = QApplication.instance()
        self._app = app if isinstance(app, QApplication) else None
        if self._app is not None:
            self._app.focusChanged.connect(self._focus_changed)
            self._app.focusWindowChanged.connect(self._window_activated)

    def detach(self) -> None:
        """Stop following the app's focus and tab activations (the window is closing)."""
        if self._app is not None:
            self._app.focusChanged.disconnect(self._focus_changed)
            self._app.focusWindowChanged.disconnect(self._window_activated)
            self._app = None
        for area in self._followed:
            if not sip.isdeleted(area):
                area.tabifiedDockWidgetActivated.disconnect(self._tab_activated)
        self._followed.clear()

    def add_plot(self, dock: QDockWidget, page: QWidget, title: str) -> None:
        """A new plot's page; it shows at once, as its dock comes to the front. The dock takes
        click focus, so a click anywhere in it (title, plot, label) focuses it and shows its page."""
        self._pages[dock] = page
        self._order.append(dock)
        self.stack.addWidget(page)
        self.chooser.addItem(title)
        dock.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        dock.destroyed.connect(self._forget_deleted)
        dock.visibilityChanged.connect(self._visibility_changed)
        if isinstance(dock, AnalysisDock):
            dock.settings.toggle.set_text(name=title)
            dock.topLevelChanged.connect(self._dock_moved)
            dock.dockLocationChanged.connect(self._dock_moved)
            self._place(dock)
        self.show_plot(dock)

    def remove_plot(self, dock: QDockWidget) -> None:
        """A closed plot's page goes; the most recently shown plot still open shows."""
        page = self._pages.pop(dock, None)
        if page is None:
            return
        index = self._order.index(dock)
        self._order.pop(index)
        self.chooser.removeItem(index)
        if dock in self._recent:
            self._recent.remove(dock)
        self._drag_end.stop(dock)
        if dock in self._unplaced:
            self._unplaced.remove(dock)
        if isinstance(dock, AnalysisDock) and not sip.isdeleted(dock):
            dock.settings.release()
        if not sip.isdeleted(page) and self.stack.indexOf(page) >= 0:
            self.stack.removeWidget(page)
        fallback = self._fallback()
        if fallback is not None:
            self.show_plot(fallback)
        else:
            self.stack.setCurrentWidget(self.hint)
        self._update_chooser()

    def show_plot(self, dock: QDockWidget, raise_dock: bool = False) -> None:
        page = self._pages.get(dock)
        if page is None:
            return
        before = self.current_plot()
        if dock in self._recent:
            self._recent.remove(dock)
        self._recent.append(dock)
        self.stack.setCurrentWidget(page if self.stack.indexOf(page) >= 0 else self.away)
        self.chooser.setCurrentIndex(self._order.index(dock))
        self._update_chooser()
        if raise_dock:
            dock.show()
            dock.raise_()
            if dock.isFloating():
                dock.activateWindow()
        # Focus left in another plot (this one came by its tab, its window or the chooser)
        # moves here, so a click back in that plot changes focus and shows it again.
        if self._plot_of(QApplication.focusWidget()) not in (None, dock) and dock.isVisible():
            dock.setFocus(Qt.FocusReason.OtherFocusReason)
        if before is not dock:
            self.plotShown.emit(dock)

    def current_plot(self) -> Optional[QDockWidget]:
        return self._recent[-1] if self._recent else None

    def recent(self) -> List[QDockWidget]:
        """The open plots by when they last showed, least recently first."""
        return list(self._recent)

    def plots(self) -> List[QDockWidget]:
        """The open plots, in the chooser's order."""
        return list(self._order)

    def page(self, dock: QDockWidget) -> Optional[QWidget]:
        return self._pages.get(dock)

    def set_title(self, dock: QDockWidget, title: str) -> None:
        """A plot's name in the chooser and its window's settings header (it changes as the
        plot follows Live to newer data)."""
        if dock in self._pages:
            self.chooser.setItemText(self._order.index(dock), title)
            if isinstance(dock, AnalysisDock):
                dock.settings.toggle.set_text(name=title)

    def follow(self, area: QMainWindow) -> None:
        """Show a plot's page when its tab is clicked among tabbed docks in ``area``."""
        if area not in self._followed:
            self._followed.append(area)
            area.tabifiedDockWidgetActivated.connect(self._tab_activated)

    def close_current(self) -> None:
        dock = self.current_plot()
        if dock is not None:
            dock.close()

    def raise_current(self) -> None:
        """Show plot window: the shown plot's window comes up with its settings open."""
        dock = self.current_plot()
        if dock is not None:
            self.show_plot(dock, raise_dock=True)
            if isinstance(dock, AnalysisDock) and self.settings_away(dock) and not dock.settings.is_open:
                dock.set_settings_open(True)

    def settings_away(self, dock: QDockWidget) -> bool:
        """Whether ``dock``'s page is in its floating window."""
        page = self._pages.get(dock)
        return page is not None and isinstance(dock, AnalysisDock) and dock.settings.page is page

    def _place(self, dock: AnalysisDock) -> None:
        """The page goes where the plot is: into its window while it floats, else here."""
        page = self._pages.get(dock)
        if page is None or sip.isdeleted(page) or sip.isdeleted(dock):
            return
        if dock.isFloating() and dock.settings.page is not page:
            self.stack.removeWidget(page)
            dock.hold_settings(page)
        elif not dock.isFloating() and dock.settings.page is page:
            dock.settings.release()
            self.stack.addWidget(page)
        if dock is self.current_plot():
            self.stack.setCurrentWidget(page if self.stack.indexOf(page) >= 0 else self.away)

    @pyqtSlot()
    def _dock_moved(self) -> None:
        """A plot floated, docked or moved: its page follows once the user lets go of it (a
        drag floats it as it starts), else a pass of the event loop later."""
        dock = self.sender()
        if not isinstance(dock, AnalysisDock):
            return
        if mouse_held():
            self._drag_end.wait(dock)
        else:
            self._drag_ended(dock)

    @pyqtSlot(QDockWidget)
    def _drag_ended(self, dock: QDockWidget) -> None:
        if isinstance(dock, AnalysisDock) and dock not in self._unplaced:
            self._unplaced.append(dock)
        self._place_soon.start()

    def _place_moved(self) -> None:
        moved, self._unplaced = self._unplaced, []
        for dock in moved:
            if isinstance(dock, AnalysisDock) and not sip.isdeleted(dock) and not self._drag_end.waiting(dock):
                self._place(dock)

    def _update_chooser(self) -> None:
        self.chooser_row.setVisible(bool(self._order))

    def _plot_of(self, widget: Optional[QWidget]) -> Optional[QDockWidget]:
        while widget is not None:
            if isinstance(widget, QDockWidget) and widget in self._pages:
                return widget
            widget = widget.parentWidget()
        return None

    def _fallback(self, leaving: Optional[QDockWidget] = None) -> Optional[QDockWidget]:
        """The plot to show when the shown one goes: the most recently shown one still
        visible, else the most recently shown one."""
        others = [dock for dock in reversed(self._recent) if dock is not leaving and not sip.isdeleted(dock)]
        return next((dock for dock in others if dock.isVisible()), others[0] if others else None)

    def _activate(self, dock: Optional[QDockWidget]) -> None:
        if dock is not None and dock is not self.current_plot():
            self.show_plot(dock)

    @pyqtSlot(QDockWidget)
    def _tab_activated(self, dock: QDockWidget) -> None:
        self._activate(dock)

    @pyqtSlot(QWidget, QWidget)
    def _focus_changed(self, old: Optional[QWidget], now: Optional[QWidget]) -> None:
        """Focus moved into a plot: the user clicked or tabbed into it. Focus that moves only
        because the focused widget was hidden (its dock went behind another tab, or closed)
        is Qt's choice, not the user's, and shows nothing."""
        if old is not None and not old.isVisible():
            return
        self._activate(self._plot_of(now))

    @pyqtSlot(QWindow)
    def _window_activated(self, window: Optional[QWindow]) -> None:
        """A floating plot's window became active (clicked, even where nothing takes focus)."""
        if window is None:
            return
        for dock in self._order:
            if dock.isFloating() and dock.windowHandle() is window:
                self._activate(dock)
                return

    @pyqtSlot(bool)
    def _visibility_changed(self, visible: bool) -> None:
        if not visible and self.sender() is self.current_plot():
            self._check_shown.start()

    def _shown_still_visible(self) -> None:
        """The shown plot was hidden (unticked in the plot area's menu, its window minimised,
        behind another tab on screen): a visible plot shows instead, as when it closes; if
        none is visible, it stays. Checked a pass of the event loop later: floating or docking
        a plot hides it for a moment, and a tab click shows the plot it brings forward."""
        shown = self.current_plot()
        if shown is None or sip.isdeleted(shown) or shown.isVisible():
            return
        fallback = self._fallback(shown)
        if fallback is not None and fallback.isVisible():
            self.show_plot(fallback)

    @pyqtSlot()
    def _forget_deleted(self) -> None:
        """A plot's dock was deleted without being closed (its window went): drop its page."""
        for dock in [dock for dock in self._order if sip.isdeleted(dock)]:
            self.remove_plot(dock)
