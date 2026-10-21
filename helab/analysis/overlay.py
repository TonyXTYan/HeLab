"""The newest shot's counts drawn over a PyQtGraph histogram in a view of their own, its real
counts read on the right axis (Basic plots v1's T/X/Y histograms and transfer fractions)."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PyQt6.QtCore import QRectF, pyqtSlot


class OverlayView(pg.ViewBox):  # type: ignore[misc]
    """A view drawn over a plot (``source``, its ViewBox) that leaves the mouse to the plot below
    (its zoom, pan and menu): it only follows the plot's geometry and ranges, its y range the
    plot's divided by ``ratio`` (log Y: shifted by log10 of it). ``follow`` is a Qt slot, so
    the plot's signals hold no Python reference to it and Qt ends the connections when either
    is destroyed: nothing outlives the widget."""

    def __init__(self, source: Any, ratio: float, log_y: bool) -> None:
        super().__init__(enableMenu=False)
        self.setMouseEnabled(x=False, y=False)  # Wheel events then pass to the plot below.
        # (Not ``scale``: that is QGraphicsItem.scale(), which Qt and pyqtgraph call.)
        self._source, self._ratio, self._log_y = source, ratio, log_y
        self._shift = math.log10(ratio) if log_y and ratio > 0 else 0.0
        source.sigResized.connect(self.follow)
        source.sigYRangeChanged.connect(self.follow)
        self.curve: Any = None  # The newest shot's counts (``overlay_newest``)

    def set_ratio(self, ratio: float) -> None:
        """A newer shot's scale (a Live rerun): its counts stay where they'd sit at the plot's."""
        self._ratio = ratio
        self._shift = math.log10(ratio) if self._log_y and ratio > 0 else 0.0
        self.follow()

    @pyqtSlot()
    def follow(self) -> None:
        source = self._source
        # The plot's exact geometry (its scene bounding rect is half a pixel larger, which shifts
        # the x link, mapped by pixel, by a pixel where rounding differs).
        self.setGeometry(QRectF(source.scenePos(), source.size()))
        self.linkedViewChanged(source, self.XAxis)  # The x link maps by pixel: again at the new size.
        low, high = source.viewRange()[1]
        if self._log_y:
            self.setYRange(low - self._shift, high - self._shift, padding=0)
        else:
            self.setYRange(low / self._ratio, high / self._ratio, padding=0)

    def mouseDragEvent(self, ev: Any, axis: Any = None) -> None:
        ev.ignore()

    def mouseClickEvent(self, ev: Any) -> None:
        ev.ignore()


def overlay_newest(plot: Any, edges: npt.NDArray[np.float64], counts: npt.NDArray[np.int64], scale: float,
                   colour: tuple[int, int, int], log_y: bool, name: str) -> OverlayView:
    """The newest shot's real counts over ``plot`` in a view of their own, linked on x, with the
    right axis (in ``colour``) reading them. Its y range follows the plot's divided by ``scale``
    (the histogram's total over the shot's; with log Y, shifted by log10 of it), so the line sits
    where the shot's histogram scaled to the same total would."""
    view = OverlayView(plot.vb, scale, log_y)
    plot.scene().addItem(view)
    axis = plot.getAxis("right")
    plot.showAxis("right")
    axis.linkToView(view)
    view.setXLink(plot.vb)
    hex_colour = pg.mkColor(colour).name()
    axis.setPen(pg.mkPen(colour))
    axis.setTextPen(pg.mkPen(colour))
    plot.setLabel("right", f"{name} events", color=hex_colour)
    values = counts.astype(np.float64)
    if log_y:
        values[values <= 0] = np.nan
    curve = pg.PlotDataItem(edges, values, stepMode="center", connect="finite", pen=pg.mkPen(colour, width=2),
                            name=name)
    if log_y:
        curve.setLogMode(False, True)
    view.addItem(curve)
    view.curve = curve
    view.follow()
    return view
