"""The Settings panel follows the active plot through Qt's own signals (focus, the active
window, tab activation): no Python runs per event, the connections end with the panel, and
plots deleted without closing leave nothing behind."""
from __future__ import annotations

import sys
from typing import Iterator, List, Optional, cast

import pytest
from pytestqt.qtbot import QtBot
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QDockWidget, QLabel, QLineEdit, QMainWindow, QTabBar, QVBoxLayout, QWidget
import pyqtgraph as pg

from helab.models.ScriptTreeSelector import AnalysisDock, DockTabCloser, PlotSettingsPanel, TreePanelWidget


def app() -> QApplication:
    instance = QApplication.instance()
    assert isinstance(instance, QApplication)
    return instance


def receivers(panel_app: QApplication) -> tuple[int, int]:
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)  # Earlier tests' panels go.
    return panel_app.receivers(panel_app.focusChanged), panel_app.receivers(panel_app.focusWindowChanged)


def delete_now(widget: QWidget) -> None:
    widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


class Plots:
    """A plot area with plot docks and their Settings pages."""

    def __init__(self, qtbot: QtBot) -> None:
        self.area = QMainWindow()
        self.area.setCentralWidget(QLabel("centre"))
        self.area.resize(800, 600)
        self.panel = PlotSettingsPanel()
        qtbot.addWidget(self.panel)
        self.panel.follow(self.area)
        self.docks: List[QDockWidget] = []

    def add(self, content: Optional[QWidget] = None) -> QDockWidget:
        dock = AnalysisDock(f"Plot ({len(self.docks) + 1})", self.area)
        dock.setWidget(content or QLabel(f"plot {len(self.docks) + 1}"))
        self.area.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.panel.add_plot(dock, QLabel(f"settings {len(self.docks) + 1}"), dock.windowTitle())
        self.docks.append(dock)
        return dock

    def show(self, qtbot: QtBot) -> None:
        self.area.show()
        self.area.activateWindow()
        qtbot.waitUntil(lambda: QApplication.activeWindow() is self.area)


@pytest.fixture
def plots(qtbot: QtBot) -> Iterator[Plots]:
    made = Plots(qtbot)
    yield made
    made.panel.detach()
    if not sip.isdeleted(made.area):  # Some tests delete it.
        made.area.close()
        delete_now(made.area)


def test_no_python_runs_per_event() -> None:
    """Neither the panel nor anything it installs filters events: Qt calls into Python only
    when focus, the active window or a tab changes, never per mouse move."""
    assert "eventFilter" not in vars(PlotSettingsPanel)
    assert "event" not in vars(PlotSettingsPanel)


def test_connections_end_with_detach_and_deletion(qtbot: QtBot) -> None:
    before = receivers(app())
    panel = PlotSettingsPanel()
    assert receivers(app()) == (before[0] + 1, before[1] + 1)
    area = QMainWindow()
    qtbot.addWidget(area)
    panel.follow(area)
    panel.follow(area)  # Followed once.
    assert area.receivers(area.tabifiedDockWidgetActivated) == 1
    panel.detach()
    panel.detach()
    assert receivers(app()) == before and area.receivers(area.tabifiedDockWidgetActivated) == 0
    # A panel deleted without detaching (its window went) takes its connections with it.
    other = PlotSettingsPanel()
    other.follow(area)
    assert receivers(app()) == (before[0] + 1, before[1] + 1)
    delete_now(other)
    assert receivers(app()) == before and area.receivers(area.tabifiedDockWidgetActivated) == 0
    delete_now(panel)


def test_many_panels_and_windows_leave_no_connections(qtbot: QtBot) -> None:
    """Main windows made and deleted one after another (tests, a second window) don't pile up."""
    before = receivers(app())
    for _ in range(10):
        window = QMainWindow()
        panel = PlotSettingsPanel(window)
        panel.follow(window)
        delete_now(window)
    assert receivers(app()) == before


def test_a_dock_deleted_unclosed_drops_its_page(plots: Plots, qtbot: QtBot) -> None:
    one, two, three = plots.add(), plots.add(), plots.add()
    plots.show(qtbot)
    plots.panel.show_plot(two)
    delete_now(two)
    assert plots.panel.plots() == [one, three] and plots.panel.chooser.count() == 2
    assert plots.panel.current_plot() is three  # The most recently shown before it.
    delete_now(plots.area)  # The rest go with the plot area.
    assert plots.panel.plots() == [] and plots.panel.current_plot() is None
    assert plots.panel.stack.currentWidget() is plots.panel.hint and plots.panel.chooser_row.isHidden()
    # Focus and window changes afterwards find nothing stale.
    edit = QLineEdit()
    qtbot.addWidget(edit)
    edit.show()
    edit.activateWindow()
    edit.setFocus()
    qtbot.waitUntil(edit.hasFocus)


def test_hiding_the_shown_plot_then_clicking_another(plots: Plots, qtbot: QtBot) -> None:
    """Hiding the shown plot shows the most recently shown plot still visible, as closing
    does; focus Qt moved into another plot meanwhile goes there too, so a click in any other
    plot (even where Qt had put focus) changes focus and shows that plot."""
    edits = [QLineEdit() for _ in range(3)]
    a, b, c = (plots.add(line_edit) for line_edit in edits)
    plots.show(qtbot)
    panel = plots.panel
    edits[2].setFocus(Qt.FocusReason.MouseFocusReason)
    edits[0].setFocus(Qt.FocusReason.MouseFocusReason)
    assert panel.current_plot() is a
    a.hide()
    qtbot.waitUntil(lambda: panel.current_plot() is c)  # Shown before a; b only had focus moved to it.
    focused = QApplication.focusWidget()
    assert focused is not None and panel._plot_of(focused) is c
    qtbot.mouseClick(edits[1], Qt.MouseButton.LeftButton)  # type: ignore[no-untyped-call]
    assert panel.current_plot() is b
    # With two plots: the focus Qt moves and the fallback agree; a click there keeps it.
    c.hide()
    a.show()
    edits[0].setFocus(Qt.FocusReason.MouseFocusReason)
    assert panel.current_plot() is a
    a.hide()
    qtbot.waitUntil(lambda: panel.current_plot() is b)
    qtbot.mouseClick(edits[1], Qt.MouseButton.LeftButton)  # type: ignore[no-untyped-call]
    assert panel.current_plot() is b and edits[1].hasFocus()


def test_floating_the_shown_plot_keeps_it(plots: Plots, qtbot: QtBot) -> None:
    """Floating or docking a plot hides it for a moment: its settings stay."""
    first, second = plots.add(), plots.add()
    plots.show(qtbot)
    plots.panel.show_plot(first)
    first.setFloating(True)
    first.show()
    qtbot.wait(50)
    assert plots.panel.current_plot() is first and first.isVisible()
    first.setFloating(False)
    qtbot.wait(50)
    assert plots.panel.current_plot() is first


def test_nothing_visible_keeps_the_shown_plot(plots: Plots, qtbot: QtBot) -> None:
    first, second = plots.add(), plots.add()
    plots.show(qtbot)
    second.hide()
    plots.panel.show_plot(first)
    first.hide()
    qtbot.wait(50)
    assert plots.panel.current_plot() is first
    # Closing falls back the same way: a hidden plot only when none is visible.
    third = plots.add()
    second.show()
    for dock in (second, first, third):  # first, hidden, is more recent than second.
        plots.panel.show_plot(dock)
    plots.panel.remove_plot(third)
    assert plots.panel.current_plot() is second


def test_closing_the_main_window_detaches_the_panel(qtbot: QtBot) -> None:
    from helab.views.HelabMainWindow import HelabMainWindow
    before = receivers(app())
    window = HelabMainWindow()
    qtbot.addWidget(window)
    assert receivers(app()) == (before[0] + 1, before[1] + 1)
    window.close()
    assert receivers(app()) == before


def test_tab_target_rule(plots: Plots, qtbot: QtBot) -> None:
    """Which open plot a new plot is tabbed with (``TreePanelWidget.tab_target``)."""
    target = TreePanelWidget.tab_target
    area, panel = plots.area, plots.panel
    assert target(area, [], None) is None  # Nothing open: it docks on its own.
    one, two, three = plots.add(), plots.add(), plots.add()
    # Docks just added, in an area not shown yet: none is visible, all count.
    assert not any(dock.isVisible() for dock in plots.docks)
    assert target(area, plots.docks, None) is three
    plots.show(qtbot)
    area.tabifyDockWidget(one, two)
    area.tabifyDockWidget(one, three)
    # The plot whose settings show, if docked, else the newest docked.
    assert target(area, plots.docks, one) is one
    two.setFloating(True)
    assert target(area, plots.docks, two) is three
    # A plot behind another tab is docked, not hidden.
    area.tabifiedDockWidgetActivated.emit(one)
    one.raise_()
    assert target(area, plots.docks, one) is one
    # A hidden plot (unticked in the area's menu) on its own is never a target; in a tab
    # group it stands for the group.
    four = plots.add()
    four.hide()
    assert not area.tabifiedDockWidgets(four)
    assert target(area, plots.docks, four) is three
    three.hide()
    assert target(area, plots.docks, three) is three and area.tabifiedDockWidgets(three) == [one]
    plots.docks.remove(four)
    # Nor a closed one (not open, no longer in the area) or a deleted one.
    one.close()
    area.removeDockWidget(one)
    assert target(area, [two, three], None) is None
    assert target(area, plots.docks, None) is None
    delete_now(one)
    assert target(area, plots.docks, None) is None
    # All floating: the new plot docks on its own.
    three.show()
    three.setFloating(True)
    assert target(area, [two, three], three) is None


def closable_bars(area: QMainWindow, tabs: int) -> List[QTabBar]:
    return [bar for bar in area.findChildren(QTabBar) if bar.count() == tabs and bar.tabsClosable()]


def test_tab_close_buttons_match_docks_by_identity(plots: Plots, qtbot: QtBot) -> None:
    """A tab's × closes that tab's own dock, even when titles collide or change."""
    assert "eventFilter" not in vars(DockTabCloser)
    closer = DockTabCloser(plots.area)
    one, two, three = plots.add(), plots.add(), plots.add()
    closed: List[QDockWidget] = []
    for dock in (one, two, three):
        dock.setWindowTitle("Counts per shot (1)")  # The same title on every tab.
        cast(AnalysisDock, dock).closed.connect(lambda dock=dock: closed.append(dock))
        closer.watch(dock)
    plots.show(qtbot)
    plots.area.tabifyDockWidget(one, two)
    plots.area.tabifyDockWidget(one, three)
    qtbot.waitUntil(lambda: bool(closable_bars(plots.area, 3)))
    bar = closable_bars(plots.area, 3)[0]
    # Qt keeps each tab's dock as its tab data: the identity the closer relies on.
    assert [closer.dock_at(bar, i) for i in range(3)] == [one, two, three]
    bar.tabCloseRequested.emit(1)
    assert closed == [two]
    qtbot.waitUntil(lambda: bool(closable_bars(plots.area, 2)))
    bar = closable_bars(plots.area, 2)[0]
    three.setWindowTitle("Renamed")
    bar.tabCloseRequested.emit(next(i for i in range(2) if bar.tabText(i) == "Counts per shot (1)"))
    assert closed == [two, one]


def test_tab_bars_made_later_get_close_buttons(plots: Plots, qtbot: QtBot) -> None:
    """Tab bars Qt makes after the docks were added (a plot floated and docked again, a
    hidden one shown) are fitted too."""
    closer = DockTabCloser(plots.area)
    docks = [plots.add() for _ in range(4)]
    for dock in docks:
        closer.watch(dock)
    plots.show(qtbot)
    one, two, three, four = docks
    plots.area.tabifyDockWidget(one, two)
    qtbot.waitUntil(lambda: bool(closable_bars(plots.area, 2)))
    three.setFloating(True)
    three.setFloating(False)
    plots.area.tabifyDockWidget(three, four)
    qtbot.waitUntil(lambda: len(closable_bars(plots.area, 2)) == 2)
    four.hide()
    plots.area.tabifyDockWidget(one, four)
    four.show()
    qtbot.waitUntil(lambda: bool(closable_bars(plots.area, 3)))
    assert all(bar.tabsClosable() for bar in plots.area.findChildren(QTabBar) if bar.count() > 1)


@pytest.mark.parametrize(("system", "qpa", "made"), [
    ("darwin", "cocoa", True), ("darwin", "offscreen", False), ("darwin", "minimal", False),
    ("win32", "windows", False), ("win32", "offscreen", False), ("linux", "xcb", False),
    ("linux", "wayland", False), ("linux", "offscreen", False)])
def test_rhi_surface_only_on_macos_own_windows(system: str, qpa: str, made: bool) -> None:
    from helab.views.HelabMainWindow import HelabMainWindow
    assert HelabMainWindow.needs_rhi_surface(system, qpa) is made


def test_no_rhi_surface_offscreen(qtbot: QtBot) -> None:
    """Tests run offscreen on every OS: the main window makes no QQuickWidget there."""
    from PyQt6.QtQuickWidgets import QQuickWidget
    from helab.views.HelabMainWindow import HelabMainWindow
    if QApplication.platformName() != "offscreen":
        pytest.skip("HELAB_SHOW_GUI=1: on screen")
    assert not HelabMainWindow.needs_rhi_surface()
    window = HelabMainWindow()
    qtbot.addWidget(window)
    assert window.findChildren(QQuickWidget) == [] and not hasattr(window, "_rhi_surface")
    window.close()


@pytest.mark.skipif(sys.platform != "darwin", reason="the surface is made on macOS only")
def test_rhi_surface_is_a_hidden_child(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    from PyQt6.QtQuickWidgets import QQuickWidget
    from helab.views.HelabMainWindow import HelabMainWindow
    monkeypatch.setattr(HelabMainWindow, "needs_rhi_surface", staticmethod(lambda: True))
    window = QMainWindow()
    qtbot.addWidget(window)
    HelabMainWindow._start_with_rhi_surface(window)  # type: ignore[arg-type]
    surfaces = window.findChildren(QQuickWidget)
    assert len(surfaces) == 1 and surfaces[0].isHidden() and surfaces[0].parent() is window
    window.show()
    assert surfaces[0].isHidden()


def line_edit_plot() -> tuple[QWidget, QLineEdit]:
    content = QWidget()
    edit = QLineEdit(content)
    QVBoxLayout(content).addWidget(edit)
    return content, edit


def test_activation_sources(plots: Plots, qtbot: QtBot) -> None:
    """Each way a plot becomes active shows its settings, as far as offscreen Qt shows it:
    clicks (pyqtgraph, a web view, content that takes no focus, the dock's title), keyboard
    focus, a tab, a floating window, and the main window activated again."""
    graph, web, label = pg.PlotWidget(), QWebEngineView(), QLabel("takes no focus")
    web.setHtml("<p>web view</p>")
    content, edit = line_edit_plot()
    g, w, n, k, f = (plots.add(widget) for widget in (graph, web, label, content, QLabel("floats")))
    plots.show(qtbot)
    panel, click = plots.panel, Qt.MouseButton.LeftButton
    qtbot.mouseClick(label, click)  # type: ignore[no-untyped-call]
    assert panel.current_plot() is n and n.hasFocus()  # The dock takes the click.
    qtbot.mouseClick(graph.viewport(), click)  # type: ignore[no-untyped-call]
    assert panel.current_plot() is g and graph.hasFocus()
    qtbot.mouseClick(n, click, pos=QPoint(n.width() // 2, 4))  # type: ignore[no-untyped-call]  # Its title.
    assert panel.current_plot() is n
    qtbot.waitUntil(lambda: web.focusProxy() is not None, timeout=10_000)
    proxy = web.focusProxy()
    assert proxy is not None
    qtbot.mouseClick(proxy, click)  # type: ignore[no-untyped-call]
    assert panel.current_plot() is w
    edit.setFocus(Qt.FocusReason.TabFocusReason)
    assert panel.current_plot() is k
    plots.area.tabifyDockWidget(g, n)
    qtbot.waitUntil(lambda: any(bar.count() == 2 and bar.isVisible() for bar in plots.area.findChildren(QTabBar)))
    bar = next(bar for bar in plots.area.findChildren(QTabBar) if bar.count() == 2)
    bar.setCurrentIndex(next(i for i in range(2) if bar.tabText(i) == g.windowTitle()))
    qtbot.waitUntil(lambda: panel.current_plot() is g)
    assert g.hasFocus()  # Taken from plot k, so a click back there shows k.
    f.setFloating(True)
    f.show()
    f.activateWindow()
    qtbot.waitUntil(lambda: panel.current_plot() is f)
    # Back to the main window: Qt gives focus back to its focus widget, in plot g.
    plots.area.activateWindow()
    qtbot.waitUntil(lambda: panel.current_plot() is g)


def test_a_click_back_in_the_focused_plot(plots: Plots, qtbot: QtBot) -> None:
    """Another plot shown by its tab, window or the chooser takes the focus left in a plot, so
    a click back in that plot (which had focus) changes focus and shows it again."""
    first_content, first_edit = line_edit_plot()
    first, second = plots.add(first_content), plots.add()
    plots.show(qtbot)
    first_edit.setFocus(Qt.FocusReason.MouseFocusReason)
    assert plots.panel.current_plot() is first
    plots.area.tabifiedDockWidgetActivated.emit(second)  # Side by side: its tab in another group.
    assert plots.panel.current_plot() is second and second.hasFocus()
    qtbot.mouseClick(first_edit, Qt.MouseButton.LeftButton)  # type: ignore[no-untyped-call]
    assert plots.panel.current_plot() is first
    # The chooser keeps its own focus.
    plots.panel.show()
    plots.panel.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is plots.panel)
    plots.panel.chooser.setFocus()
    plots.panel.chooser.activated.emit(1)
    assert plots.panel.current_plot() is second and plots.panel.chooser.hasFocus()
