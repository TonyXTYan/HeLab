"""PyQtGraph axes for the plots' T, X and Y: tick labels grouped by thousands (``20,450.5``),
whatever the locale and however large (``display_units.tick_strings``; pyqtgraph's own switch to
``2.045e+04`` from 10,000)."""
from __future__ import annotations

from typing import Any

import pyqtgraph as pg

from helab.analysis.display_units import tick_strings


class GroupedAxis(pg.AxisItem):  # type: ignore[misc]
    """An axis whose tick labels group thousands with "," and use "." for decimals, the decimals
    from the tick spacing. In log mode it keeps pyqtgraph's own labels. Never rescaled by an SI
    prefix of its own: the plots give their values in ms or mm already."""

    def __init__(self, orientation: str, **kwargs: Any) -> None:
        super().__init__(orientation, **kwargs)
        self.enableAutoSIPrefix(False)

    def tickStrings(self, values: list[float], scale: float, spacing: float) -> list[str]:
        if self.logMode:
            return [str(text) for text in super().tickStrings(values, scale, spacing)]
        return tick_strings(values, scale, spacing)


def grouped_axes(*orientations: str) -> dict[str, Any]:
    """``axisItems`` for ``addPlot`` / ``PlotWidget``: a ``GroupedAxis`` on each side named."""
    return {orientation: GroupedAxis(orientation) for orientation in orientations}
