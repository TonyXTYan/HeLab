"""The Settings panel follows the active plot through Qt's own signals (focus, the active
window, tab activation): no Python runs per event, the connections end with the panel, and
plots deleted without closing leave nothing behind."""
from __future__ import annotations

from typing import Iterator, List, Optional

import pytest
from pytestqt.qtbot import QtBot
from PyQt6 import sip
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QApplication, QDockWidget, QLabel, QLineEdit, QMainWindow, QWidget

from helab.models.ScriptTreeSelector import AnalysisDock, PlotSettingsPanel


def app() -> QApplication:
    instance = QApplication.instance()
    assert isinstance(instance, QApplication)
    return instance


def receivers(panel_app: QApplication) -> tuple[int, int]:
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


def test_focus_moved_by_hiding_shows_nothing(plots: Plots, qtbot: QtBot) -> None:
    """When the focused widget's dock is hidden (behind another tab on screen, or closed), Qt
    moves focus on to the next widget, maybe in another plot: that isn't the user's choice."""
    first_edit, second_edit = QLineEdit(), QLineEdit()
    first, second = plots.add(first_edit), plots.add(second_edit)
    plots.show(qtbot)
    first_edit.setFocus(Qt.FocusReason.MouseFocusReason)
    qtbot.waitUntil(lambda: plots.panel.current_plot() is first)
    first.hide()
    qtbot.waitUntil(second_edit.hasFocus)
    assert plots.panel.current_plot() is first
    # The user's own focus change still counts.
    first.show()
    first_edit.setFocus(Qt.FocusReason.MouseFocusReason)
    second_edit.setFocus(Qt.FocusReason.TabFocusReason)
    assert plots.panel.current_plot() is second


def test_closing_the_main_window_detaches_the_panel(qtbot: QtBot) -> None:
    from helab.views.HelabMainWindow import HelabMainWindow
    before = receivers(app())
    window = HelabMainWindow()
    qtbot.addWidget(window)
    assert receivers(app()) == (before[0] + 1, before[1] + 1)
    window.close()
    assert receivers(app()) == before
