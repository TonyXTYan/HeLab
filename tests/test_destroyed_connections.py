"""No Python callable on a Qt object's ``destroyed`` (Tony, 2026-10-30): a lambda on ``PlotlyPane.destroyed``
crashed the process (SIGSEGV in a PyQt slot proxy as a plot dock's children were deleted; Smoke ready's
follow-up notes). Cleanup that needs Python runs with ``weakref.finalize`` instead, once the object's Python side
goes: a closed Plotly plot's figure leaves the Dash server once the plot is dropped."""
from __future__ import annotations

import ast
import gc
from pathlib import Path

import plotly.graph_objs as go
import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before any QApplication: the main window)
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from helab.analysis.panes import PlotlyPane
from helab.utils.dash_server import DashServer, dash_server
from helab.views.HelabMainWindow import HelabMainWindow
from test_debug_runner_menu import items, load, plot, run_folder, submenu, window  # noqa: F401  (a fixture)

HELAB = Path(__file__).resolve().parent.parent / "helab"


def destroyed_connections_to_callables() -> list[str]:
    """``<x>.destroyed.connect(<y>)`` anywhere in ``helab/`` where ``<y>`` isn't a bound method (an
    attribute, e.g. ``self._forget_deleted``): a lambda, a function's name, ``functools.partial(...)``."""
    found: list[str] = []
    for path in sorted(HELAB.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "connect"
                    and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "destroyed"
                    and node.args and not isinstance(node.args[0], ast.Attribute)):
                found.append(f"{path.relative_to(HELAB.parent)}:{node.lineno}: {ast.unparse(node)}")
    return found


def test_no_python_callable_is_connected_to_destroyed() -> None:
    assert destroyed_connections_to_callables() == []


def test_the_scan_finds_each_kind_it_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "helab"
    package.mkdir()
    (package / "bad.py").write_text(
        "w.destroyed.connect(lambda *_: gone())\nw.destroyed.connect(gone)\n"
        "w.destroyed.connect(functools.partial(gone, 1))\nw.destroyed.connect(self.forget)\n", encoding="utf-8")
    monkeypatch.setitem(globals(), "HELAB", package)
    assert [line.split(": ", 1)[0] for line in destroyed_connections_to_callables()] == [
        "helab/bad.py:1", "helab/bad.py:2", "helab/bad.py:3"]


def test_a_plotly_panes_figure_leaves_the_server_once_the_pane_goes(qtbot: QtBot,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    server = DashServer()
    monkeypatch.setattr(server, "start", lambda: 0)  # (Its plots only: no port.)
    holder = QWidget()
    pane = PlotlyPane(go.Figure(), parent=holder, server=server)
    plot_id = pane.plot_id
    assert server.snapshot(plot_id) is not None
    holder.deleteLater()  # Its dock deleted: the pane's C++ side goes with it.
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    assert server.snapshot(plot_id) is not None  # Still held here (the plot's instance, in the app).
    del pane, holder
    gc.collect()
    assert server.snapshot(plot_id) is None


@pytest.mark.no_auto_data_root  # RAM only: nothing left saving at quit (test_debug_runner_menu.py).
def test_closing_a_plotly_plot_frees_its_figure_once_the_plot_is_dropped(
        window: HelabMainWindow, qtbot: QtBot, tmp_path: Path) -> None:  # noqa: F811
    load(window, qtbot, run_folder(tmp_path))
    plot(window, qtbot, "3D scatter")  # Plotly by default.
    [instance] = window.panel_right_bottom_script_selector.instances()
    dock = instance.dock_widget
    assert dock is not None
    found = dock.findChild(PlotlyPane)
    assert found is not None
    plot_id = found.plot_id
    title = dock.windowTitle()
    del found, dock, instance
    assert dash_server.snapshot(plot_id) is not None
    items(submenu(window, "Close Plot Tab"))[title].trigger()

    def freed() -> bool:
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        gc.collect()
        return dash_server.snapshot(plot_id) is None
    qtbot.waitUntil(freed, timeout=10_000)
