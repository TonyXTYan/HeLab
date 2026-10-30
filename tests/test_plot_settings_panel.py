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

from helab.views.plots.dock import AnalysisDock, DockTabCloser, FloatingSettings
from helab.views.plots.script_tree import TreePanelWidget
from helab.views.plots.settings_panel import PlotSettingsPanel


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

    def add(self, content: Optional[QWidget] = None, page: Optional[QWidget] = None) -> QDockWidget:
        dock = AnalysisDock(f"Plot ({len(self.docks) + 1})", self.area)
        dock.setWidget(content or QLabel(f"plot {len(self.docks) + 1}"))
        self.area.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.panel.add_plot(dock, page or QLabel(f"settings {len(self.docks) + 1}"), dock.windowTitle())
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


# A floating plot's settings (its page moves into its window)

def floated(dock: QDockWidget, qtbot: QtBot, width: int = 0) -> AnalysisDock:
    """``dock`` floating on its own, its settings section showing; ``width``: its window's."""
    assert isinstance(dock, AnalysisDock)
    dock.setFloating(True)
    if width:
        dock.setGeometry(40, 40, width, 300)
    dock.show()
    qtbot.waitUntil(dock.settings.isVisible)
    return dock


def docked(dock: AnalysisDock, qtbot: QtBot) -> None:
    dock.setFloating(False)
    qtbot.waitUntil(dock.settings.isHidden)


def test_a_floating_plot_takes_its_page_and_gives_it_back(plots: Plots, qtbot: QtBot) -> None:
    """Floating a plot moves its page into its window: the same widgets, with their edits,
    starting closed. The panel keeps naming the plot and says where its settings are, with a
    button that raises the window; other plots' pages show here as before. Docked again, the
    page comes back."""
    page = QLineEdit("unapplied")
    one, two = plots.add(), plots.add(page=page)
    plots.show(qtbot)
    panel = plots.panel
    assert panel.stack.currentWidget() is page and cast(AnalysisDock, two).settings.isHidden()
    dock = floated(two, qtbot, width=400)  # (Room to widen on the offscreen screen.)
    side = dock.settings
    assert side.page is page and page.parentWidget() is side and panel.page(two) is page
    assert panel.settings_away(two) and panel.stack.currentWidget() is panel.away
    assert panel.stack.indexOf(page) == -1 and panel.chooser.currentText() == two.windowTitle()
    assert not side.is_open and page.isHidden() and side.width() == side.toggle.strip_width()
    panel.show_plot(one)
    assert panel.stack.currentWidget() is panel.page(one) and not panel.settings_away(one)
    plots.area.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is plots.area)
    panel.chooser.activated.emit(1)  # Chosen: its window comes up.
    qtbot.waitUntil(lambda: QApplication.activeWindow() is two)
    assert panel.current_plot() is two and panel.stack.currentWidget() is panel.away
    assert not side.is_open  # The chooser only raises it.
    plots.area.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is plots.area)
    panel.show_plot(two)  # The main window active, its focus back in plot one: two again.
    width = two.width()
    panel.away_button.click()  # Show plot window: raised, with its settings open.
    qtbot.waitUntil(lambda: QApplication.activeWindow() is two)
    assert side.is_open and page.isVisible() and side.toggle.isChecked()
    assert two.width() == width + FloatingSettings.DEFAULT_WIDTH - side.toggle.strip_width()
    panel.away_button.click()  # Open already: stays as it is.
    assert side.is_open and two.width() == width + FloatingSettings.DEFAULT_WIDTH - side.toggle.strip_width()
    page.setText("edited in the plot's window")
    docked(dock, qtbot)
    assert side.page is None and page.parentWidget() is panel.stack and panel.stack.currentWidget() is page
    assert page.text() == "edited in the plot's window" and not panel.settings_away(two)


def test_the_section_opens_wider_and_remembers_for_the_session(plots: Plots, qtbot: QtBot) -> None:
    """Opening the section widens the window by its width (the plot keeps its size); the
    splitter sets the width open, and closing narrows the window by as much. Whether it is
    open and its width stay with the plot, docked and floated again."""
    page = QLineEdit()
    plots.add(page=page)
    plots.show(qtbot)
    dock = floated(plots.docks[0], qtbot, width=400)
    side, frame = dock.settings, dock.frame
    strip = side.toggle.strip_width()
    plot_width = frame.sizes()[0]
    handle = frame.handle(1)
    assert handle is not None and not handle.isEnabled()  # Closed: the strip can't be dragged wider.
    side.toggle.click()
    assert side.is_open and page.isVisible() and handle.isEnabled()
    assert side.width() == FloatingSettings.DEFAULT_WIDTH == side.open_width
    assert frame.sizes()[0] == plot_width and dock.width() == 400 + FloatingSettings.DEFAULT_WIDTH - strip
    frame.moveSplitter(frame.sizes()[0] - 60, 1)  # As a drag of the handle does.
    wider = FloatingSettings.DEFAULT_WIDTH + 60
    assert side.width() == side.open_width == wider and frame.sizes()[0] == plot_width - 60
    side.toggle.click()
    assert not side.is_open and page.isHidden() and side.width() == strip
    assert frame.sizes()[0] == plot_width - 60 and dock.width() == 400 - 60
    docked(dock, qtbot)
    floated(dock, qtbot)
    assert not side.is_open and side.width() == strip
    side.toggle.click()
    assert side.is_open and side.width() == wider
    docked(dock, qtbot)
    floated(dock, qtbot)
    assert side.is_open and page.isVisible() and side.width() == wider


def test_opening_keeps_the_window_on_its_screen(plots: Plots, qtbot: QtBot) -> None:
    plots.add()
    plots.show(qtbot)
    dock = floated(plots.docks[0], qtbot)
    screen = dock.screen()
    assert screen is not None
    available = screen.availableGeometry()
    dock.setGeometry(available.right() - 300, 40, available.width() - 100, 300)
    dock.settings.toggle.click()
    assert dock.width() == available.width() and dock.geometry().left() == available.left()
    assert dock.settings.width() == FloatingSettings.DEFAULT_WIDTH  # The plot gives up the rest.


def test_the_header_names_the_plot_and_its_settings(plots: Plots, qtbot: QtBot) -> None:
    one = plots.add()
    toggle = cast(AnalysisDock, one).settings.toggle
    assert toggle.name == "Plot (1)" and "Show this plot's settings" in toggle.toolTip()
    plots.panel.set_title(one, "Plot (1) · run_L · rev 2")
    toggle.set_text(summary="last 10 shots · bins auto")
    assert toggle.text_shown() == "Plot (1) · run_L · rev 2 · last 10 shots · bins auto"
    assert toggle.toolTip() == "Show this plot's settings\nPlot (1) · run_L · rev 2\nlast 10 shots · bins auto"
    toggle.setChecked(True)
    assert toggle.toolTip().startswith("Hide this plot's settings")
    # Space opens and closes it too (it is a button).
    plots.show(qtbot)
    dock = floated(one, qtbot)
    toggle.setChecked(False)
    dock.activateWindow()
    toggle.setFocus()
    qtbot.waitUntil(toggle.hasFocus)
    qtbot.keyClick(toggle, Qt.Key.Key_Space)  # type: ignore[no-untyped-call]
    assert dock.settings.is_open


def test_redocking_into_its_tab_group(plots: Plots, qtbot: QtBot) -> None:
    """A plot floated from a tab group docks back into it, its page comes back, and the
    group's tabs keep their close buttons."""
    closer = DockTabCloser(plots.area)
    one, two, three = plots.add(), plots.add(), plots.add()
    for dock in (one, two, three):
        closer.watch(dock)
    plots.show(qtbot)
    plots.area.tabifyDockWidget(one, two)
    plots.area.tabifyDockWidget(one, three)
    qtbot.waitUntil(lambda: bool(closable_bars(plots.area, 3)))
    plots.panel.show_plot(two)
    dock = floated(two, qtbot)
    qtbot.waitUntil(lambda: bool(closable_bars(plots.area, 2)))
    assert plots.panel.stack.currentWidget() is plots.panel.away
    docked(dock, qtbot)
    qtbot.waitUntil(lambda: bool(closable_bars(plots.area, 3)))
    assert set(plots.area.tabifiedDockWidgets(two)) == {one, three}
    assert plots.panel.current_plot() is two and plots.panel.stack.currentWidget() is plots.panel.page(two)


def test_a_hidden_floating_plot_falls_back_to_a_visible_one(plots: Plots, qtbot: QtBot) -> None:
    """A floating plot counts as shown; hidden (its window minimised), a visible plot shows,
    with its page in the panel."""
    one, two = plots.add(), plots.add()
    plots.show(qtbot)
    plots.panel.show_plot(one)
    dock = floated(two, qtbot)
    dock.activateWindow()
    qtbot.waitUntil(lambda: plots.panel.current_plot() is two)
    plots.area.activateWindow()  # Focus back in the main window, not in a plot: two stays.
    qtbot.wait(50)
    assert plots.panel.current_plot() is two and plots.panel.stack.currentWidget() is plots.panel.away
    two.hide()
    qtbot.waitUntil(lambda: plots.panel.current_plot() is one)
    assert plots.panel.stack.currentWidget() is plots.panel.page(one)


def test_many_floating_plots_each_hold_their_own_page(plots: Plots, qtbot: QtBot) -> None:
    pages = [QLineEdit(f"page {n}") for n in range(8)]
    docks = [plots.add(page=page) for page in pages]
    plots.show(qtbot)
    for dock in docks:
        floated(dock, qtbot)
    for n, dock in enumerate(docks):
        assert cast(AnalysisDock, dock).settings.page is pages[n]
        plots.panel.chooser.activated.emit(n)
        assert plots.panel.current_plot() is dock and plots.panel.stack.currentWidget() is plots.panel.away
    # A floating plot closed (its page goes with it) or deleted unclosed leaves nothing behind.
    plots.panel.remove_plot(docks[3])
    assert cast(AnalysisDock, docks[3]).settings.page is None
    delete_now(docks[5])
    assert sip.isdeleted(pages[5]) and docks[5] not in plots.panel.plots()
    assert plots.panel.stack.count() == 2 and plots.panel.chooser.count() == 6
    for dock in docks[:3]:
        docked(cast(AnalysisDock, dock), qtbot)
    assert plots.panel.stack.count() == 5


def counted_moves(dock: AnalysisDock, monkeypatch: pytest.MonkeyPatch) -> List[str]:
    """Each time the page moves into ``dock``'s window ("in") or out of it ("out")."""
    moves: List[str] = []
    hold, release = dock.hold_settings, dock.settings.release

    def holding(page: QWidget) -> None:
        moves.append("in")
        hold(page)

    def releasing() -> Optional[QWidget]:
        if dock.settings.page is not None:
            moves.append("out")
        return release()

    monkeypatch.setattr(dock, "hold_settings", holding)
    monkeypatch.setattr(dock.settings, "release", releasing)
    return moves


@pytest.fixture
def let_go(plots: Plots, qtbot: QtBot) -> Iterator[None]:
    """A drag test that fails mid-drag leaves no button down for the tests after it."""
    yield
    if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
        qtbot.mouseRelease(plots.area, Qt.MouseButton.LeftButton)  # type: ignore[no-untyped-call]


def press_title(dock: QDockWidget, qtbot: QtBot) -> None:
    qtbot.mousePress(dock, Qt.MouseButton.LeftButton, pos=QPoint(20, 5))  # type: ignore[no-untyped-call]
    assert QApplication.mouseButtons() == Qt.MouseButton.LeftButton


def test_a_dragged_plot_takes_its_page_once_let_go(
        plots: Plots, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, let_go: None) -> None:
    """Qt floats a plot as a drag of it starts: its page stays in the panel until the user
    lets go, then moves once. Between drags nothing watches the dock."""
    page = QLineEdit()
    dock = cast(AnalysisDock, plots.add(page=page))
    plots.show(qtbot)
    moves = counted_moves(dock, monkeypatch)
    panel = plots.panel
    press_title(dock, qtbot)
    for x in range(20, 300, 20):  # Dragged out of the plot area.
        qtbot.mouseMove(dock, QPoint(x, 5 + x))  # type: ignore[no-untyped-call]
    assert dock.isFloating() and panel._drag_end.waiting(dock)
    qtbot.wait(100)
    assert moves == [] and panel.stack.currentWidget() is page
    qtbot.mouseRelease(dock, Qt.MouseButton.LeftButton, pos=QPoint(300, 305))  # type: ignore[no-untyped-call]
    qtbot.waitUntil(lambda: moves == ["in"])
    assert dock.settings.page is page and panel.stack.currentWidget() is panel.away
    assert not panel._drag_end.waiting(dock)
    qtbot.wait(50)
    assert moves == ["in"]


def test_a_plot_dragged_out_and_back_keeps_its_page(
        plots: Plots, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, let_go: None) -> None:
    """Out and back in one drag (Qt floats it, then docks it at the drop): nothing moves."""
    page = QLineEdit()
    dock = cast(AnalysisDock, plots.add(page=page))
    plots.show(qtbot)
    moves = counted_moves(dock, monkeypatch)
    press_title(dock, qtbot)
    dock.setFloating(True)  # As the drag starts.
    qtbot.wait(50)
    dock.setFloating(False)  # Dropped back in the plot area.
    qtbot.wait(50)
    qtbot.mouseRelease(dock, Qt.MouseButton.LeftButton, pos=QPoint(20, 5))  # type: ignore[no-untyped-call]
    qtbot.wait(50)
    assert moves == [] and not dock.isFloating() and plots.panel.stack.currentWidget() is page
    assert not plots.panel._drag_end.waiting(dock)
    # A floating plot dragged back in moves its page out once, at the drop.
    dock.setFloating(True)
    qtbot.waitUntil(lambda: moves == ["in"])
    press_title(dock, qtbot)
    dock.setFloating(False)
    qtbot.wait(50)
    assert moves == ["in"] and dock.settings.page is page
    qtbot.mouseRelease(dock, Qt.MouseButton.LeftButton, pos=QPoint(20, 5))  # type: ignore[no-untyped-call]
    qtbot.waitUntil(lambda: moves == ["in", "out"])
    assert plots.panel.stack.currentWidget() is page


def test_a_release_the_dock_never_saw_ends_the_drag_at_its_next_mouse_event(
        plots: Plots, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, let_go: None) -> None:
    """A drag whose release went elsewhere (a system move of the window): the next mouse event
    the dock gets, with no button down, ends it."""
    dock = cast(AnalysisDock, plots.add(page=QLineEdit()))
    plots.show(qtbot)
    moves = counted_moves(dock, monkeypatch)
    press_title(dock, qtbot)
    dock.setFloating(True)
    qtbot.wait(50)  # Events of its window coming up, the button still down: still waiting.
    assert moves == [] and plots.panel._drag_end.waiting(dock)
    # Let go where the dock gets no event: Qt knows no button is down.
    monkeypatch.setattr("helab.views.plots.settings_panel.mouse_held", lambda: False)
    qtbot.mouseMove(dock, QPoint(30, 30))  # type: ignore[no-untyped-call]
    qtbot.waitUntil(lambda: moves == ["in"])
    assert not plots.panel._drag_end.waiting(dock)
    qtbot.mouseRelease(dock, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))  # type: ignore[no-untyped-call]


def test_a_plot_wrapped_in_place_stays_shown(qtbot: QtBot) -> None:
    """``setWidget`` with a wrapper around the plot shown (as ``_set_plot_source`` does) keeps
    the plot shown inside it; a plot replaced outright is hidden, a child of the dock still."""
    dock = AnalysisDock("Plot")
    qtbot.addWidget(dock)
    plot = QLabel("plot")
    dock.setWidget(plot)
    dock.show()
    wrapper = QWidget(dock)
    QVBoxLayout(wrapper).addWidget(plot)
    dock.setWidget(wrapper)
    assert dock.widget() is wrapper and plot.parentWidget() is wrapper and plot.isVisible()
    other = QLabel("another plot")
    dock.setWidget(other)
    assert dock.widget() is other and other.isVisible() and wrapper.isHidden()
    assert wrapper.parentWidget() is not None and dock.isAncestorOf(wrapper)
