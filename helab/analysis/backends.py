"""The plotting libraries a plot can be drawn with, chosen in its settings (Drawing › Library).

The choice is the plot's, not the analysis's: it is not a parameter (not in the result's record
or its reuse key), and changing it draws the result already shown again, without a rerun.

- **PyQtGraph**: native Qt drawing, fast to redraw while Live adds shots, and painted on lab PCs
  that can't paint QtWebEngine. Its 3D view needs OpenGL (``opengl_available``).
- **Plotly**: an interactive page served by the Dash server (``PlotlyPane``), with Open in
  browser for PCs whose GPU can't paint QtWebEngine; a rerun updates the page in place.
- **Matplotlib**: publication-style figures with Matplotlib's own toolbar (zoom, pan, save).
  Drawn with ``matplotlib.figure.Figure`` only, never ``pyplot`` (no global state on the GUI
  thread)."""
from __future__ import annotations

import functools
from typing import Any, Optional, Sequence

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from helab.analysis.parameters import ParameterSpec

PYQTGRAPH = "PyQtGraph"
PLOTLY = "Plotly"
MATPLOTLIB = "Matplotlib"
BACKENDS = (PYQTGRAPH, PLOTLY, MATPLOTLIB)

BACKEND = "plot_backend"
DRAWING_GROUP = "Drawing"


def backend_specs(backends: Sequence[str], page: str = "") -> tuple[ParameterSpec, ...]:
    """The Drawing group of a plot's settings: its library, the script's default first. None for
    a script drawing with one library only."""
    if len(backends) < 2:
        return ()
    return (ParameterSpec(
        BACKEND, "Library", "choice", backends[0], choices=tuple(backends), group=DRAWING_GROUP, page=page,
        tip="The plotting library this plot is drawn with. Changing it draws the plot shown again, without "
            "a rerun. PyQtGraph: fastest, native; Plotly: interactive page, also in a browser; Matplotlib: "
            f"publication-style, with its own toolbar. The script's default: {backends[0]}."),)


def rgb(colour: tuple[int, int, int], alpha: float = 1.0) -> str:
    """A CSS colour for Plotly."""
    return f"rgba({colour[0]}, {colour[1]}, {colour[2]}, {alpha:g})"


def mpl_colour(colour: tuple[int, int, int], alpha: float = 1.0) -> tuple[float, float, float, float]:
    """An RGBA colour for Matplotlib."""
    return colour[0] / 255, colour[1] / 255, colour[2] / 255, alpha


class MatplotlibPane(QWidget):
    """A Matplotlib figure in the plot area, with Matplotlib's navigation toolbar."""

    def __init__(self, figure: Any, parent: Optional[QWidget] = None) -> None:
        from matplotlib.backends.backend_qt import NavigationToolbar2QT
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

        super().__init__(parent)
        self.setObjectName("plot_matplotlib")
        self.figure = figure
        self.canvas = FigureCanvasQTAgg(figure)  # type: ignore[no-untyped-call]
        self.canvas.setParent(self)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)  # type: ignore[no-untyped-call]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)


def mpl_figure() -> Any:
    """A new Matplotlib figure laid out to fit its plot area (no ``pyplot``)."""
    from matplotlib.figure import Figure

    return Figure(layout="constrained")


@functools.cache
def opengl_available() -> bool:
    """Whether this machine can make an OpenGL context (PyQtGraph's 3D view needs one). Not on
    Qt's offscreen platform, and not on PCs without a working OpenGL driver."""
    from PyQt6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext

    if QGuiApplication.platformName() in ("offscreen", "minimal"):
        return False
    context = QOpenGLContext()
    if not context.create():
        return False
    surface = QOffscreenSurface()
    surface.create()
    try:
        return surface.isValid() and context.makeCurrent(surface)
    finally:
        context.doneCurrent()
