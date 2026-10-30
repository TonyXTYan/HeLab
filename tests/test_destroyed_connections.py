"""No Python callable on a Qt object's ``destroyed`` (Tony, 2026-10-30): a lambda on ``PlotlyPane.destroyed``
crashed the process (SIGSEGV in a PyQt slot proxy as a plot dock's children were deleted; Smoke ready's
follow-up notes). Cleanup that needs Python runs with ``weakref.finalize`` instead, once the object's Python side
goes, and is also called where the object leaves its use: a closed Plotly plot's figure leaves the Dash server as
it closes (``release_figure``), not when garbage collection gets to the closed plot's reference cycles."""
from __future__ import annotations

import ast
import gc
from pathlib import Path

import plotly.graph_objs as go
import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before any QApplication: the main window)
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget
from pytestqt.qtbot import QtBot

from helab.analysis.panes import PlotlyPane
from helab.utils.dash_server import DashServer, dash_server
from helab.views.HelabMainWindow import HelabMainWindow
from test_debug_runner_menu import items, load, plot, run_folder, submenu, window  # noqa: F401  (a fixture)

HELAB = Path(__file__).resolve().parent.parent / "helab"


def _is_destroyed(node: ast.expr, stored: set[str]) -> bool:
    """``<x>.destroyed``, ``<x>.destroyed[QObject]`` or a name a ``destroyed`` signal was stored in."""
    if isinstance(node, ast.Subscript):
        node = node.value
    return (isinstance(node, ast.Attribute) and node.attr == "destroyed"
            or isinstance(node, ast.Name) and node.id in stored)


def destroyed_connections_to_callables() -> list[str]:
    """A ``destroyed`` signal's ``connect(<y>)`` (or ``connect(slot=<y>)``) anywhere in ``helab/`` where ``<y>``
    isn't a bound method (an attribute, e.g. ``self._forget_deleted``): a lambda, a function's name,
    ``functools.partial(...)``. The signal written out, subscripted (``destroyed[QObject]``) or stored in a name
    in the same file first (``signal = w.destroyed``)."""
    found: list[str] = []
    for path in sorted(HELAB.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        stored = {target.id for node in ast.walk(tree) if isinstance(node, ast.Assign)
                  and _is_destroyed(node.value, set()) for target in node.targets if isinstance(target, ast.Name)}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "connect" and _is_destroyed(node.func.value, stored)):
                continue
            slots = [*node.args[:1], *(keyword.value for keyword in node.keywords if keyword.arg == "slot")]
            if any(not isinstance(slot, ast.Attribute) for slot in slots):
                found.append(f"{path.relative_to(HELAB.parent).as_posix()}:{node.lineno}: {ast.unparse(node)}")
    return found


def test_no_python_callable_is_connected_to_destroyed() -> None:
    assert destroyed_connections_to_callables() == []


def test_the_scan_finds_each_kind_it_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "helab"
    package.mkdir()
    (package / "bad.py").write_text(
        "w.destroyed.connect(lambda *_: gone())\nw.destroyed.connect(gone)\n"
        "w.destroyed.connect(functools.partial(gone, 1))\nw.destroyed.connect(self.forget)\n"
        "w.destroyed.connect(slot=lambda: gone())\nw.destroyed[QObject].connect(gone)\n"
        "signal = w.destroyed\nsignal.connect(gone)\nw.clicked.connect(gone)\n", encoding="utf-8")
    monkeypatch.setitem(globals(), "HELAB", package)
    assert [line.split(": ", 1)[0] for line in destroyed_connections_to_callables()] == [
        "helab/bad.py:1", "helab/bad.py:2", "helab/bad.py:3", "helab/bad.py:5", "helab/bad.py:6", "helab/bad.py:8"]


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


def test_release_figure_frees_it_at_once_and_the_pane_going_does_nothing_more(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    server = DashServer()
    monkeypatch.setattr(server, "start", lambda: 0)
    removed: list[str] = []
    monkeypatch.setattr(server, "remove_plot", lambda plot_id: removed.append(plot_id))  # (Before: the finalizer holds it.)
    pane = PlotlyPane(go.Figure(), server=server)
    qtbot.addWidget(pane)
    pane.release_figure()
    pane.release_figure()
    assert removed == [pane.plot_id]  # Once, though the pane is still here.


def test_a_plot_drawn_anew_in_its_dock_frees_the_old_figure(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.views.plots.dock import AnalysisDock
    server = DashServer()
    monkeypatch.setattr(server, "start", lambda: 0)
    dock = AnalysisDock("Plot")
    qtbot.addWidget(dock)
    first = PlotlyPane(go.Figure(), server=server)
    dock.setWidget(first)
    plot_id = first.plot_id
    wrapper = QWidget()  # A wrapper around the same pane: still shown, kept.
    QVBoxLayout(wrapper).addWidget(first)
    dock.setWidget(wrapper)
    assert server.snapshot(plot_id) is not None
    dock.setWidget(QWidget())  # Drawn anew (another library, released): gone now, the pane still held here.
    assert server.snapshot(plot_id) is None


@pytest.mark.no_auto_data_root  # RAM only: nothing left saving at quit (test_debug_runner_menu.py).
def test_closing_a_plotly_plot_frees_its_figure_as_it_closes(
        window: HelabMainWindow, qtbot: QtBot, tmp_path: Path) -> None:  # noqa: F811
    """No collection here: a closed plot's instance sits in reference cycles until one runs (review R2-1)."""
    load(window, qtbot, run_folder(tmp_path))
    plot(window, qtbot, "3D scatter")  # Plotly by default.
    [instance] = window.panel_right_bottom_script_selector.instances()
    dock = instance.dock_widget
    assert dock is not None
    found = dock.findChild(PlotlyPane)
    assert found is not None
    plot_id = found.plot_id
    title = dock.windowTitle()
    assert dash_server.snapshot(plot_id) is not None
    items(submenu(window, "Close Plot Tab"))[title].trigger()
    assert dash_server.snapshot(plot_id) is None  # At once, while this test still holds the pane.
