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
from typing import Any, Callable, Optional, Sequence

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


FOLLOWER = "_helab_follower"  # An axes whose limits follow another's (a twin axis): never restored


def axes_state(figure: Any) -> list[tuple[Any, ...]]:
    """Each axes' scales and limits (3D: with z), in order; a follower's as None."""
    states: list[tuple[Any, ...]] = []
    for axes in figure.axes:
        if getattr(axes, FOLLOWER, False):
            states.append(())
            continue
        three_d = hasattr(axes, "get_zlim")
        scales = (axes.get_xscale(), axes.get_yscale(), axes.get_zscale() if three_d else "")
        limits = (axes.get_xlim(), axes.get_ylim(), axes.get_zlim() if three_d else ())
        states.append((scales, limits))
    return states


def set_limits(axes: Any, limits: tuple[Any, ...]) -> None:
    axes.set_xlim(*limits[0])
    axes.set_ylim(*limits[1])
    if limits[2]:
        axes.set_zlim(*limits[2])


class MatplotlibPane(QWidget):
    """A Matplotlib figure in the plot area, with Matplotlib's navigation toolbar.

    ``redraw`` draws a newer result onto the same figure (a Live rerun), keeping what the user did
    to the view: an axes zoomed or panned away from its automatic limits keeps its limits (when the
    newer drawing has the same axes and scales), and 3D axes keep their rotation. Home goes back to
    the newer drawing's automatic limits."""

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
        self.auto_state = axes_state(figure)  # The limits as drawn, before the user changed any

    def zoomed(self) -> list[bool]:
        """Per axes: whether the user moved it away from its automatic limits."""
        now = axes_state(self.figure)
        if len(now) != len(self.auto_state):
            return [False] * len(now)
        return [bool(state) and state != auto for state, auto in zip(now, self.auto_state)]

    def redraw(self, build: Callable[[Any], Any]) -> None:
        """``build`` draws the newer result into the cleared figure; the user's view is kept."""
        figure = self.figure
        before, zoomed = axes_state(figure), self.zoomed()
        views = [(axes.elev, axes.azim, axes.roll) if hasattr(axes, "elev") else None for axes in figure.axes]
        figure.clear()
        build(figure)
        self.auto_state = axes_state(figure)
        after = figure.axes
        same = len(after) == len(before) and all(
            not state or (new and new[0] == state[0]) for state, new in zip(before, self.auto_state))
        self.toolbar.update()  # The old axes' views are gone.
        if same:
            for axes, view in zip(after, views):
                if view is not None and hasattr(axes, "view_init"):
                    axes.view_init(elev=view[0], azim=view[1], roll=view[2])
            if any(zoomed):
                self.toolbar.push_current()  # Home: the automatic view.
                for axes, state, moved in zip(after, before, zoomed):
                    if moved:
                        set_limits(axes, state[1])
                self.toolbar.push_current()
        self.canvas.draw_idle()  # type: ignore[no-untyped-call]


def mpl_figure(figure: Any = None) -> Any:
    """``figure`` (one being drawn again), else a new Matplotlib figure laid out to fit its plot
    area (no ``pyplot``)."""
    if figure is not None:
        return figure
    from matplotlib.figure import Figure

    return Figure(layout="constrained")


def matplotlib_pane(widget: QWidget) -> Optional[MatplotlibPane]:
    """The Matplotlib pane ``widget`` is or holds, if any."""
    return widget if isinstance(widget, MatplotlibPane) else widget.findChild(MatplotlibPane)


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
