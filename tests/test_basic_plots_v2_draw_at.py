"""Q~1 (Tony, 2026-11-10; GT-4 of the GUI-thread audit): XY, XT, YT histograms draw at screen resolution by default
(Image › Draw at), beside every bin. An image of more than ``DISPLAY_SIDE`` bins a side is drawn from the mean of
blocks of bins made on the worker, at most that a side (Plotly ``PLOTLY_SIDE``); PyQtGraph also averages what the
screen can't show (``autoDownsample``) and Matplotlib draws one raster (``imshow``); PyQtGraph and Matplotlib draw at
most ``DRAWN_DOTS`` dots. The bins, the counts and the image stay as set; the plane's title says how it is drawn; the
memory estimate follows the setting. Every bin draws as before.

The drawn cells are all the same size (review R3, 2026-11-17): where the bins don't divide into whole blocks, a bin
on a cell's border counts by its part on either side, so the image, stretched evenly over its range by every
library, has each cell where its bins are."""
from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from helab.analysis import histogram2d as histogram2d_module
from helab.analysis.backends import MATPLOTLIB, PLOTLY, PYQTGRAPH
from helab.analysis.histogram2d import DISPLAY_SIDE, PLOTLY_SIDE, cell_edges, cell_mean, display_factors, display_shape
from helab.analysis.parameters import effective
from helab.scripts.standard_v2 import histograms_2d
from helab.scripts.standard_v2.histograms_2d import DOTS, EVERY_BIN, SCREEN, PlaneHistograms
from test_basic_plots_v2_hist2d import only, result_of, view

# XY alone at 5,000 × 10 bins: drawn 1,667 × 10 (means of 3 × 1 bins), and by Plotly 834 × 10 (6 × 1).
WIDE = {**only("XY"), "bins_x": 5_000, "bins_y": 10}


def test_bins_that_divide_are_drawn_as_whole_blocks_their_means_and_edges() -> None:
    assert (DISPLAY_SIDE, PLOTLY_SIDE) == (2048, 1000)
    assert display_factors((5_000, 10)) == (3, 1) and display_shape((5_000, 10)) == (1_667, 10)
    assert display_factors((2_048, 2_048)) == (1, 1) and display_factors((20_000, 20_000)) == (10, 10)
    image = np.arange(48, dtype=np.float64).reshape(6, 8)
    means = cell_mean(image, (3, 2))
    assert means.dtype == np.float32 and means.shape == (3, 2)
    assert np.array_equal(means, [[image[r:r + 2, c:c + 4].mean() for c in (0, 4)] for r in (0, 2, 4)])
    assert np.array_equal(cell_mean(image, (6, 8)), image)
    edges = np.linspace(0.0, 1.0, 9)
    assert np.array_equal(cell_edges(edges, 4), edges[::2]) and cell_edges(edges, 8) is edges


def weighted_cells(counts: Any, cells: int) -> Any:
    """``counts`` along an axis as ``cells`` equal cells, a bin shared by its part in each (worked out bin by bin)."""
    bins = len(counts)
    borders = np.linspace(0.0, bins, cells + 1)
    return np.array([sum(counts[j] * max(0.0, min(borders[k + 1], j + 1) - max(borders[k], j)) for j in range(bins))
                     for k in range(cells)])


@pytest.mark.parametrize("shape, drawn", [((2_049, 4), (1_025, 4)), ((3_001, 5), (1_501, 5)), ((2_050, 4), (1_025, 4))])
def test_bins_that_dont_divide_are_drawn_as_equal_cells_each_in_its_place(shape: tuple[int, int],
                                                                         drawn: tuple[int, int]) -> None:
    """One count in the last bin, one in the bin before it and one in the middle: every drawn cell is where the bins
    it averages are. (2,050 bins divide: the control, whole blocks.)"""
    assert display_shape(shape) == drawn
    edges = np.linspace(-3.0, 7.0, shape[0] + 1)
    image = np.zeros(shape)
    lit = (shape[0] - 1, shape[0] - 2, shape[0] // 2)
    for bin_ in lit:
        image[bin_, 1] = 1.0
    display = histograms_2d.display_of(image, edges, np.linspace(0.0, 1.0, shape[1] + 1), DISPLAY_SIDE)
    assert display is not None and display.image.shape == drawn
    cell = np.diff(display.h_edges)
    assert np.allclose(cell, 10.0 / drawn[0], rtol=1e-12)  # equal cells: an even stretch over the range is exact
    assert display.h_edges[0] == edges[0] and display.h_edges[-1] == edges[-1]
    assert display.factors == (shape[0] / drawn[0], 1.0)
    # each cell holds the counts of the bins inside its own edges, a border bin by its part
    assert np.allclose(display.image[:, 1].astype(np.float64) * display.factors[0],
                       weighted_cells(image[:, 1], drawn[0]), atol=1e-6)
    assert float(display.image.sum()) * display.factors[0] == pytest.approx(3.0, rel=1e-5)
    for bin_ in lit:
        cells = np.flatnonzero(display.image[:, 1] > 0)
        holding = [k for k in cells if display.h_edges[k] < edges[bin_ + 1] and display.h_edges[k + 1] > edges[bin_]]
        # the bin lies within the lit cells drawn over it, and they reach no further than a cell beyond it
        assert holding and display.h_edges[holding[0]] <= edges[bin_] + 1e-12
        assert display.h_edges[holding[-1] + 1] >= edges[bin_ + 1] - 1e-12
        assert display.h_edges[holding[-1] + 1] - display.h_edges[holding[0]] <= 2 * cell[0] + 1e-12
    assert display.image[-1, 1] > 0 and display.h_edges[-2] <= edges[-2]  # the last bin is in the last cell, whole
    if shape[0] % drawn[0] == 0:
        assert np.array_equal(display.h_edges, edges[::2]) and display.image[-1, 1] == 1.0  # (both of its two bins)


@pytest.mark.parametrize("bins", [(2_049, 4), (3_001, 5), (4_096, 4)])
def test_every_library_draws_each_cell_over_the_bins_it_averages(bins: tuple[int, int], qtbot: QtBot) -> None:
    """The cells as each library places them (PyQtGraph's image rectangle, Matplotlib's extent, Plotly's centres),
    against the bins' own edges: also where the bins don't divide (2,049 and 3,001; 4,096 is the control)."""
    from PyQt6.QtCore import QRectF
    script = PlaneHistograms()
    result = result_of(script, view(), {**only("XY"), "bins_x": bins[0], "bins_y": bins[1]})
    item = result.data.items[0]
    histogram, display = item.histogram, item.display
    assert display is not None and histogram.counts.shape == bins
    cells = display.image.shape[0]
    assert cells == display_shape(bins)[0] and np.allclose(np.diff(display.h_edges), np.diff(display.h_edges)[0])
    # what each cell shows is what its place holds: the image's bins inside the cell's edges
    counted = item.image.sum(axis=1)
    assert np.allclose(display.image.astype(np.float64).sum(axis=1) * display.factors[0] * display.factors[1],
                       weighted_cells(counted, cells), rtol=1e-4, atol=1e-6)
    widget: Any = script.draw(result, PYQTGRAPH)
    qtbot.addWidget(widget)
    image = widget.plane_panels[0].image
    placed = [image.mapRectToParent(QRectF(k, 0, 1, 1)) for k in (0, cells // 2, cells - 2, cells - 1)]
    for k, rect in zip((0, cells // 2, cells - 2, cells - 1), placed):
        assert (rect.left(), rect.right()) == pytest.approx((display.h_edges[k], display.h_edges[k + 1]), abs=1e-12)
    drawn = histograms_2d.planes_matplotlib(result).axes[0].images[0]
    left, right, bottom, top = drawn.get_extent()
    assert drawn.get_array().shape == (bins[1], cells)
    assert np.allclose(np.linspace(left, right, cells + 1), display.h_edges, atol=1e-12)
    assert (bottom, top) == (histogram.v_edges[0], histogram.v_edges[-1])
    figure: Any = histograms_2d.planes_plotly(result)
    across = np.asarray(figure.data[0].x)
    assert np.allclose(np.diff(across), np.diff(across)[0])  # Plotly's cells: equal, borders midway between centres
    assert across[0] - np.diff(across)[0] / 2 == pytest.approx(histogram.h_edges[0])
    assert across[-1] + np.diff(across)[0] / 2 == pytest.approx(histogram.h_edges[-1])
    whole = bins[0] % cells == 0
    assert ("each the mean of 2 × 1 bins" in histograms_2d.plane_title(item)) is whole
    if not whole:
        assert f"each the mean of {bins[0] / cells:.4g} × 1 bins" in histograms_2d.plane_title(item)


def test_the_worker_makes_the_drawn_image_and_keeps_every_bin() -> None:
    script = PlaneHistograms()
    screen, every = (result_of(script, view(), {**WIDE, "draw_at": at}).data.items[0] for at in (SCREEN, EVERY_BIN))
    assert screen.histogram.counts.shape == every.histogram.counts.shape == (5_000, 10)
    assert np.array_equal(screen.image, every.image) and every.display is None
    display = screen.display
    assert display is not None and display.image.shape == (1_667, 10) and display.factors == (5_000 / 1_667, 1.0)
    assert np.allclose(np.diff(display.h_edges), np.diff(display.h_edges)[0])  # (5,000 bins in 1,667 equal cells.)
    assert display.h_edges[0] == screen.histogram.h_edges[0] and display.h_edges[-1] == screen.histogram.h_edges[-1]
    assert float(display.image.astype(np.float64).sum()) * 5_000 / 1_667 == pytest.approx(float(screen.image.sum()))
    assert screen.peak == pytest.approx(float(display.image.max()))  # (The colour bar reads what is drawn.)
    assert "drawn at 1,667 × 10, each the mean of 2.999 × 1 bins" in histograms_2d.plane_title(screen)
    assert "drawn at" not in histograms_2d.plane_title(every)
    small = result_of(script, view(), only("XY")).data.items[0]  # (Automatic bins: no smaller drawing.)
    assert small.display is None
    assert script.describe_run("Plot", effective(script.parameters("Plot"), {"draw_at": EVERY_BIN}),
                               view())[1].count("every bin drawn") == 1
    assert "every bin" not in script.describe_run("Plot", effective(script.parameters("Plot"), {}), view())[1]


@pytest.mark.parametrize("at", [SCREEN, EVERY_BIN])
def test_each_library_draws_the_drawn_image(at: str, qtbot: QtBot) -> None:
    script = PlaneHistograms()
    result = result_of(script, view(), {**WIDE, "draw_at": at})
    item = result.data.items[0]
    screen = at == SCREEN
    widget: Any = script.draw(result, PYQTGRAPH)
    qtbot.addWidget(widget)
    image = widget.plane_panels[0].image
    assert image.image.shape == ((1_667, 10) if screen else (5_000, 10)) and image.autoDownsample is screen
    assert ("drawn at" in widget.plane_panels[0].label.text) is screen
    figure: Any = histograms_2d.planes_plotly(result)
    trace = figure.data[0]
    assert np.asarray(trace.z).shape == ((10, 834) if screen else (10, 5_000))
    assert (trace.customdata is None) is screen  # (A block's mean has no one bin's events.)
    assert ("each the mean of 5.995 × 1 bins" in figure.layout.annotations[0].text) is screen
    drawn = histograms_2d.planes_matplotlib(result)
    axes = drawn.axes[0]
    if screen:
        assert len(axes.images) == 1 and not axes.collections
        assert axes.images[0].get_array().shape == (10, 1_667)
        assert "drawn at 1,667 × 10" in axes.get_title()
    else:
        assert not axes.images and len(axes.collections) == 1  # (pcolormesh, a quad a bin, as before.)
    assert item.histogram.counts.shape == (5_000, 10)


def test_switching_draw_at_draws_anew_in_pyqtgraph(qtbot: QtBot) -> None:
    script = PlaneHistograms()
    widget: Any = script.draw(result_of(script, view(), WIDE), PYQTGRAPH)
    qtbot.addWidget(widget)
    assert script.update(widget, result_of(script, view(range(1, 4)), WIDE))
    assert not script.update(widget, result_of(script, view(range(1, 4)), {**WIDE, "draw_at": EVERY_BIN}))


@pytest.mark.parametrize("backend", [PYQTGRAPH, MATPLOTLIB, PLOTLY])
@pytest.mark.parametrize("at", [SCREEN, EVERY_BIN])
def test_pyqtgraph_and_matplotlib_draw_at_most_their_dots(backend: str, at: str, qtbot: QtBot,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(histograms_2d, "DRAWN_DOTS", 100)
    script = PlaneHistograms()
    result = result_of(script, view(), {**only("XY"), "draw": DOTS, "draw_at": at})
    item = result.data.items[0]
    assert item.dots is not None and item.dots.drawn > 100 and item.display is None
    capped = at == SCREEN and backend != PLOTLY
    expected = 100 if capped else item.dots.drawn
    if backend == PYQTGRAPH:
        widget: Any = script.draw(result, backend)
        qtbot.addWidget(widget)
        assert len(widget.plane_panels[0].dots.data) == expected
        assert ("100 of them drawn" in widget.plane_panels[0].label.text) is capped
    elif backend == MATPLOTLIB:
        axes = histograms_2d.planes_matplotlib(result).axes[0]
        assert len(axes.collections[0].get_offsets()) == expected
        assert ("100 of them drawn" in axes.get_title()) is capped
    else:
        figure: Any = histograms_2d.planes_plotly(result)
        assert len(figure.data[0].x) == expected  # (WebGL: every dot.)


def test_the_estimate_follows_draw_at() -> None:
    script = PlaneHistograms()

    def estimate(values: dict[str, Any]) -> int:
        return script.estimated_bytes("Plot", effective(script.parameters("Plot"), values))
    big = {"bins_x": 20_000, "bins_y": 20_000, "bins_t": 20_000}
    bins, drawn = 400_000_000, 2_000 * 2_000
    # Held: counts and image (16 B a bin) and the drawn image (4 B a cell); colouring at the drawn size.
    assert estimate(big) == 16 * 3 * bins + 4 * 3 * drawn + 32 * drawn
    assert estimate({**big, "draw_at": EVERY_BIN}) == 16 * 3 * bins + 32 * bins
    # A filter still runs on every bin.
    assert estimate({**big, "blur_gaussian": True}) == 16 * 3 * bins + 4 * 3 * drawn + 32 * bins
    assert estimate({}) == estimate({"draw_at": EVERY_BIN}) == 16 * 3 * 1_000_000 + 32 * 1_000_000
    assert estimate({**big, "draw": DOTS}) == 16 * 3 * bins + 32 * bins  # (Dots: as before.)
    assert histogram2d_module.estimated_bytes([10, 10], drawn=[10, 4]) == 16 * 20 + 4 * 4 + 32 * 10


def test_draw_at_sits_beside_the_bins() -> None:
    names = [spec.name for spec in PlaneHistograms().parameters("Plot")]
    assert names.index("draw_at") == names.index("bins_y") + 1
    spec = histograms_2d.DRAW_AT
    assert spec.default == SCREEN and spec.choices == (SCREEN, EVERY_BIN) and spec.group == "Image"
