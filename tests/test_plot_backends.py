"""Each standard plot drawn with every plotting library it offers (PyQtGraph, Plotly, Matplotlib):
the same result, no rerun, and a Plotly page updated in place on a rerun."""
from __future__ import annotations

from typing import Any, Callable, cast

import numpy as np
import pyqtgraph as pg
import pytest
from PyQt6.QtWidgets import QLabel, QWidget
from pytestqt.qtbot import QtBot

from helab.analysis import backends
from helab.analysis.backends import (BACKEND, MATPLOTLIB, PLOTLY, PYQTGRAPH, MatplotlibPane, backend_specs,
                                     opengl_available)
from helab.analysis.dataset_view import DatasetView, build_view
from helab.analysis.panes import PlotlyPane
from helab.analysis.parameters import effective
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.scripts.base import DatasetAnalysis
from helab.scripts.standard import basic_plots, scatter_3d, transfer_fractions
from helab.utils.dash_server import dash_server
from helab.utils.folder_cache import Dataset

CENTRE, SPACING = 2.1375, 0.0125


def shot_events(rng: np.random.Generator, shot: int) -> Any:
    """Orders −2…+2 in T around ``CENTRE``, a small cloud in X and Y."""
    parts = []
    for order, count in {-2: 20, -1: 100, 0: 600, 1: 250 + shot, 2: 30}.items():
        times = rng.normal(CENTRE + order * SPACING, 0.001, count)
        parts.append(np.column_stack((times, rng.normal(0, 0.005, (count, 2)))))
    events = np.concatenate(parts)
    events.setflags(write=False)
    return events


def view(shots: range = range(1, 7)) -> DatasetView:
    rng = np.random.default_rng(7)
    data = {shot: shot_events(rng, shot) for shot in shots}
    fingerprint = [[shot, 100 + shot, 1_000 + shot] for shot in shots]
    return build_view(Dataset("/data/root/run_1", "sig-1", data, {"fingerprint": fingerprint, "source": "files",
                                                                  "loaded_at": 1_700_000_000.0}, 0))


def result_of(script: DatasetAnalysis, data: DatasetView, values: dict[str, Any] | None = None) -> AnalysisResult:
    context = AnalysisContext("a1", "Plot", data, effective(script.parameters("Plot"), values),
                              script.get_metadata().identity())
    return AnalysisResult.of(context, "completed", script.compute("Plot", context))


SCRIPTS: list[Callable[[], DatasetAnalysis]] = [basic_plots.CountsPerShot, basic_plots.TxyHistograms, scatter_3d.Scatter3D,
           transfer_fractions.TransferFractions]


def test_the_drawing_choice_offers_every_library_the_script_names() -> None:
    assert backend_specs(()) == () and backend_specs((PYQTGRAPH,)) == ()
    spec, = backend_specs((PLOTLY, PYQTGRAPH, MATPLOTLIB), page="Plot")
    assert spec.name == BACKEND and spec.kind == "choice" and spec.default == PLOTLY and spec.page == "Plot"
    assert spec.choices == (PLOTLY, PYQTGRAPH, MATPLOTLIB) and spec.group == backends.DRAWING_GROUP
    for script_class in SCRIPTS:
        named = script_class().backends("Plot")
        assert sorted(named) == sorted(backends.BACKENDS)
    # Defaults keep what each plot drew before: PyQtGraph for 2D, Plotly for the 3D scatter.
    assert scatter_3d.Scatter3D().backends("Plot")[0] == PLOTLY
    assert basic_plots.TxyHistograms().backends("Plot")[0] == PYQTGRAPH


def expected(script: DatasetAnalysis, backend: str) -> type[QWidget]:
    if backend == PLOTLY:
        return PlotlyPane
    if backend == MATPLOTLIB:
        return MatplotlibPane
    return cast(type[QWidget], pg.PlotWidget if isinstance(script, basic_plots.CountsPerShot)
                else pg.GraphicsLayoutWidget)


@pytest.mark.parametrize("script_class", SCRIPTS[:2] + SCRIPTS[3:])
@pytest.mark.parametrize("backend", backends.BACKENDS)
@pytest.mark.parametrize("values", [{}, {"highlight_newest": True, "log_y": True}, {"highlight_newest": True}])
def test_2d_plots_draw_with_every_library(script_class: Callable[[], DatasetAnalysis], backend: str, values: dict[str, Any],
                                          qtbot: QtBot) -> None:
    script = script_class()
    result = result_of(script, view(), {key: value for key, value in values.items()
                                        if key in {spec.name for spec in script.parameters("Plot")}})
    widget = script.draw(result, backend)
    qtbot.addWidget(widget)
    assert isinstance(widget, expected(script, backend))
    if isinstance(widget, MatplotlibPane):
        widget.canvas.draw()  # type: ignore[no-untyped-call]  # Draws without error, and has its toolbar.
        assert widget.toolbar is not None and widget.figure.axes
    # A rerun with the same settings (Live's next shots) shows in place in every library.
    assert script.update(widget, result_of(script, view(range(1, 8)), dict(result.parameters)))


def test_render_is_the_default_library(qtbot: QtBot) -> None:
    for script_class in SCRIPTS:
        script = script_class()
        widget = script.render(result_of(script, view()))
        qtbot.addWidget(widget)
        default = script.backends("Plot")[0]
        assert isinstance(widget, expected(script, default) if not isinstance(script, scatter_3d.Scatter3D)
                          else PlotlyPane)


def test_histograms_matplotlib_newest_axis_follows_the_zoom(qtbot: QtBot) -> None:
    """The newest shot's right axis reads its real counts at the histogram's scale, and keeps that
    scale when the left one is zoomed."""
    script = basic_plots.TxyHistograms()
    result = result_of(script, view(), {"highlight_newest": True})
    figure = basic_plots.histograms_matplotlib(result)
    left = figure.axes[0]
    right = next(axes for axes in figure.axes if axes is not left and axes.bbox.bounds == left.bbox.bounds)
    item, fresh = result.data.items[0], result.data.newest[0]
    scale = float(item.counts.sum()) / float(fresh.sum())
    assert right.get_ylim()[1] == pytest.approx(left.get_ylim()[1] / scale)
    left.set_ylim(0, 100)
    assert right.get_ylim()[1] == pytest.approx(100 / scale)


def test_histograms_plotly_newest_shot_is_scaled_with_real_counts_in_hover() -> None:
    script = basic_plots.TxyHistograms()
    result = result_of(script, view(), {"highlight_newest": True, "log_y": True})
    figure: Any = basic_plots.histograms_plotly(result)
    assert len(figure.data) == 6  # each axis: all shots, and the newest
    newest = figure.data[1]
    fresh = result.data.newest[0]
    assert list(newest.customdata[:-1]) == fresh.tolist()
    assert figure.layout.yaxis.type == "log" and figure.layout.uirevision == basic_plots.UI_REVISION


@pytest.mark.parametrize("backend", backends.BACKENDS)
def test_the_scatter_draws_with_every_library(backend: str, qtbot: QtBot) -> None:
    script = scatter_3d.Scatter3D()
    result = result_of(script, view(), {"highlight_newest": True})
    widget = script.draw(result, backend)
    qtbot.addWidget(widget)
    if backend == PLOTLY:
        assert isinstance(widget, PlotlyPane)
    elif backend == MATPLOTLIB:
        pane = widget.findChild(MatplotlibPane)
        assert pane is not None and len(pane.figure.axes[0].collections) == 2  # earlier shots, and the newest
        note = widget.findChild(QLabel, "plot_note")
        assert note is not None and note.text() == scatter_3d.note_text(result.data)
    elif opengl_available():
        import pyqtgraph.opengl as gl
        assert widget.findChild(gl.GLViewWidget) is not None
    else:  # Qt's offscreen platform, or a PC without OpenGL: it says so instead of a black view.
        assert isinstance(widget, QLabel) and "needs OpenGL" in widget.text()
    # In place, except offscreen PyQtGraph: its message is drawn anew (OpenGL may have come back).
    assert script.update(widget, result) == (backend != PYQTGRAPH or opengl_available())


def test_the_scatter_unit_box_spans_the_crop() -> None:
    script = scatter_3d.Scatter3D()
    data = result_of(script, view(), {}).data
    box = scatter_3d.unit_box(data.points, data.crop)
    assert box.shape == data.points.shape and box.dtype == np.float32
    assert box.min() >= -0.5 - 1e-6 and box.max() <= 0.5 + 1e-6


@pytest.mark.parametrize("backend", backends.BACKENDS)
def test_empty_plots_say_why_with_every_library(backend: str, qtbot: QtBot) -> None:
    empty = view(range(0))
    for script_class in SCRIPTS:
        script = script_class()
        widget: QWidget = script.draw(result_of(script, empty), backend)
        qtbot.addWidget(widget)
        assert isinstance(widget, QLabel) and widget.text() == "No shots yet"


def test_pyqtgraph_updates_in_place_keeping_a_zoom(qtbot: QtBot) -> None:
    """Unzoomed, the axes follow the new data; zoomed or panned (pyqtgraph's auto range off), the
    view stays where the user put it."""
    script = basic_plots.CountsPerShot()
    widget: Any = script.draw(result_of(script, view(range(1, 7))), PYQTGRAPH)
    qtbot.addWidget(widget)
    widget.resize(400, 300)
    widget.show()
    box = widget.getPlotItem().vb
    curve = widget.counts_curve
    assert script.update(widget, result_of(script, view(range(1, 11))))
    assert widget.counts_curve is curve and list(curve.xData) == list(range(1, 11))
    box.updateAutoRange()
    assert box.viewRange()[0][1] >= 10  # Followed the new shots.
    box.setXRange(2, 4, padding=0)  # The user zooms: auto range off.
    assert script.update(widget, result_of(script, view(range(1, 13))))
    assert box.viewRange()[0] == pytest.approx([2, 4]) and len(curve.xData) == 12


def test_pyqtgraph_histograms_update_in_place_unless_their_layout_changed(qtbot: QtBot) -> None:
    script = basic_plots.TxyHistograms()
    highlighted = result_of(script, view(), {"highlight_newest": True})
    widget: Any = script.draw(highlighted, PYQTGRAPH)
    qtbot.addWidget(widget)
    overlay = widget.newest_views[0]
    newer = result_of(script, view(range(1, 9)), {"highlight_newest": True})
    assert script.update(widget, newer)
    assert widget.newest_views[0] is overlay and newer.data.newest_shot == 8
    item, fresh = newer.data.items[0], newer.data.newest[0]
    assert list(overlay.curve.yData) == fresh.astype(float).tolist()
    assert overlay._ratio == pytest.approx(basic_plots.newest_scale(item, fresh))
    assert "shot 8" in widget.title_label.text
    # Log Y, or the highlight off, is another layout: drawn anew.
    assert not script.update(widget, result_of(script, view(), {"highlight_newest": True, "log_y": True}))
    assert not script.update(widget, result_of(script, view(), {}))


def test_transfer_fractions_pyqtgraph_update_in_place(qtbot: QtBot) -> None:
    script = transfer_fractions.TransferFractions()
    widget: Any = script.draw(result_of(script, view()), PYQTGRAPH)
    qtbot.addWidget(widget)
    curves = list(widget.fraction_curves)
    newer = result_of(script, view(range(1, 10)))
    assert script.update(widget, newer)
    assert widget.fraction_curves == curves and len(curves[0].xData) == 9
    region, _ = widget.order_windows[2]
    assert region.getRegion() == pytest.approx(newer.data.orders.window(0))
    # Another number of orders: drawn anew.
    assert not script.update(widget, result_of(script, view(), {"orders_each_side": 3}))


def test_matplotlib_redraw_keeps_a_zoom_and_home_goes_to_the_new_data(qtbot: QtBot) -> None:
    script = basic_plots.CountsPerShot()
    pane = script.draw(result_of(script, view(range(1, 7))), MATPLOTLIB)
    qtbot.addWidget(pane)
    assert isinstance(pane, MatplotlibPane)
    figure = pane.figure
    assert script.update(pane, result_of(script, view(range(1, 11))))
    axes = figure.axes[0]
    assert pane.figure is figure and axes.get_xlim()[1] >= 10  # Unzoomed: follows the new shots.
    axes.set_xlim(2, 4)  # The user zooms.
    assert pane.zoomed() == [True]
    assert script.update(pane, result_of(script, view(range(1, 13))))
    axes = figure.axes[0]
    assert axes.get_xlim() == pytest.approx((2, 4)) and len(axes.lines[0].get_xdata()) == 12
    pane.toolbar.home()
    assert figure.axes[0].get_xlim()[1] >= 12


def test_matplotlib_scatter_keeps_its_rotation(qtbot: QtBot) -> None:
    script = scatter_3d.Scatter3D()
    widget = script.draw(result_of(script, view()), MATPLOTLIB)
    qtbot.addWidget(widget)
    pane = widget.findChild(MatplotlibPane)
    assert pane is not None
    pane.figure.axes[0].view_init(elev=55, azim=-30)
    newer = result_of(script, view(range(1, 9)))
    assert script.update(widget, newer)
    axes = pane.figure.axes[0]
    assert (axes.elev, axes.azim) == (55, -30)
    note = widget.findChild(QLabel, "plot_note")
    assert note is not None and note.text() == scatter_3d.note_text(newer.data)


def test_opengl_scatter_updates_its_points_in_place(qtbot: QtBot) -> None:
    """Built directly (Qt's offscreen platform has no OpenGL to draw it): the same view and items,
    newer points and axis labels; the camera is left alone."""
    script = scatter_3d.Scatter3D()
    first = result_of(script, view())
    built: Any = scatter_3d.opengl_view(first, first.data)
    widget = scatter_3d.noted(built, first.data, None)
    qtbot.addWidget(widget)
    points, camera = built.earlier_points, dict(built.opts)
    newer = result_of(script, view(range(1, 9)), {"highlight_newest": True})
    assert script.update(widget, newer)
    assert built.earlier_points is points and len(points.pos) == len(newer.data.points)
    assert len(built.newest_points.pos) == len(newer.data.newest)
    assert built.opts["distance"] == camera["distance"] and built.opts["azimuth"] == camera["azimuth"]


def test_transfer_fractions_highlight_the_newest_shot_in_the_t_histogram() -> None:
    """Off by default; on, the newest chosen shot's T (in the XY box) in the histogram's bins."""
    script = transfer_fractions.TransferFractions()
    data = view()
    plain = result_of(script, data).data
    assert plain.newest_shot is None and len(plain.newest) == 0
    lit = result_of(script, data, {"highlight_newest": True, "newest_colour": "magenta"}).data
    assert lit.newest_shot == 6 and not lit.newest_left_out and lit.colour != plain.colour
    edges = lit.histogram[0]
    expected = np.histogram(transfer_fractions.in_box(np.asarray(data.shots[6]), 0.03)[:, 0], bins=edges)[0]
    assert lit.newest.tolist() == expected.astype(float).tolist()
    assert "newest shot in magenta" in script.describe_run("Plot", {**result_of(script, data).parameters,
                                                                    "highlight_newest": True,
                                                                    "newest_colour": "magenta"}, data)[1]
    # A newest shot Minimum counts left out (a bad shot) is still shown, and says so.
    shots = {shot: np.asarray(data.shots[shot]) for shot in data.shot_numbers}
    shots[7] = shots[6][:30]
    fingerprint = [[shot, 100 + shot, 1_000 + shot] for shot in shots]
    weak = build_view(Dataset("/data/root/run_1", "sig-2", shots, {"fingerprint": fingerprint, "source": "files",
                                                                   "loaded_at": 1_700_000_000.0}, 0))
    left_out = result_of(script, weak, {"highlight_newest": True}).data
    assert left_out.newest_shot == 7 and left_out.newest_left_out and 7 not in left_out.shots.tolist()
    assert 0 < left_out.newest.sum() <= 30
    assert "left out: ≤ 50 counts" in transfer_fractions.times_title(left_out)


@pytest.mark.parametrize("backend", backends.BACKENDS)
def test_transfer_fractions_draw_the_newest_shot_in_every_library(backend: str, qtbot: QtBot) -> None:
    script = transfer_fractions.TransferFractions()
    result = result_of(script, view(), {"highlight_newest": True})
    widget: Any = script.draw(result, backend)
    qtbot.addWidget(widget)
    if backend == PYQTGRAPH:
        assert widget.newest_view is not None
        assert list(widget.newest_view.curve.yData) == result.data.newest.tolist()
        assert widget.times_plot.getAxis("right").isVisible()
    elif backend == PLOTLY:
        snapshot = dash_server.snapshot(widget.plot_id)
        assert snapshot is not None
        newest = [trace for trace in cast(Any, snapshot.figure).data if str(trace.name).startswith("shot 6")]
        assert len(newest) == 1 and list(newest[0].customdata[:-1]) == result.data.newest.tolist()
    else:
        times = widget.figure.axes[1]
        right = next(axes for axes in widget.figure.axes if getattr(axes, backends.FOLLOWER, False))
        scale = transfer_fractions.newest_scale(result.data.histogram[1], result.data.newest)
        assert right.get_ylim()[1] == pytest.approx(times.get_ylim()[1] / scale)
    # Live's next shot: in place, the highlight moving to it.
    newer = result_of(script, view(range(1, 8)), {"highlight_newest": True})
    assert script.update(widget, newer) and newer.data.newest_shot == 7
    if backend == PYQTGRAPH:
        assert list(widget.newest_view.curve.yData) == newer.data.newest.tolist()
        assert widget.newest_view._ratio == pytest.approx(
            transfer_fractions.newest_scale(newer.data.histogram[1], newer.data.newest))
        # The highlight off, or another colour: another layout, drawn anew.
        assert not script.update(widget, result_of(script, view(), {}))
        assert not script.update(widget, result_of(script, view(), {"highlight_newest": True,
                                                                    "newest_colour": "magenta"}))
