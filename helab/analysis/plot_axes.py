"""PyQtGraph axes for the plots' T, X and Y: tick labels grouped by thousands (``20,450.5``),
whatever the locale and however large (``display_units.tick_strings``; pyqtgraph's own switch to
``2.045e+04`` from 10,000)."""
from __future__ import annotations

import math
from typing import Any, cast

import pyqtgraph as pg

from helab.analysis.display_units import tick_strings


class GroupedAxis(pg.AxisItem):  # type: ignore[misc]
    """An axis whose tick labels group thousands with "," and use "." for decimals, the decimals
    from the tick spacing. Never rescaled by an SI prefix of its own (no "(x0.001)"): the plots give
    their values in ms or mm already. In log mode it labels whole decades only, with unlabelled
    2…9 ticks between them (pyqtgraph labels the 2…9 ticks too when the axis spans under about two
    decades, and those labels overlap); with no whole decade in view it keeps pyqtgraph's ticks."""

    def __init__(self, orientation: str, **kwargs: Any) -> None:
        super().__init__(orientation, **kwargs)
        self.enableAutoSIPrefix(False)

    def logTickValues(self, minVal: float, maxVal: float, size: float,
                      stdTicks: list[tuple[float, list[float]]]) -> list[tuple[float | None, list[float]]]:
        decades = [float(v) for v in range(math.ceil(minVal), math.floor(maxVal) + 1)]
        if not decades:
            return cast(list[tuple[float | None, list[float]]],
                        super().logTickValues(minVal, maxVal, size, stdTicks))
        minor = [v + math.log10(k) for v in range(math.floor(minVal), math.ceil(maxVal)) for k in range(2, 10)]
        self.setStyle(maxTextLevel=0)
        return [(1.0, decades), (None, [v for v in minor if minVal < v < maxVal])]

    def tickStrings(self, values: list[float], scale: float, spacing: float) -> list[str]:
        if self.logMode:
            return [str(text) for text in super().tickStrings(values, scale, spacing)]
        return tick_strings(values, scale, spacing)


def grouped_axes(*orientations: str) -> dict[str, Any]:
    """``axisItems`` for ``addPlot`` / ``PlotWidget``: a ``GroupedAxis`` on each side named."""
    return {orientation: GroupedAxis(orientation) for orientation in orientations}
