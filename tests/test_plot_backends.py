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
    # A rerun shows in place only on a Plotly page (zoom and pan stay); the others draw anew.
    assert script.update(widget, result_of(script, view(range(1, 8)), values=None)) == (backend == PLOTLY)


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
    assert script.update(widget, result) == (backend == PLOTLY)


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
