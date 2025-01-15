# helab/scripts/pg_simple_densities.py
import logging
from typing import Optional, Dict, Tuple, Callable

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from pyqtgraph import QtCore, GraphicsLayoutWidget, ViewBox


from scipy.optimize import curve_fit
from scipy.stats import norm


from PyQt6.QtCore import QObject, QEvent, QRectF
from PyQt6.QtGui import QMouseEvent, QPainter, QColor


def compute_range(
    data: npt.NDArray[np.float64],
    specified_range: Optional[Tuple[float, float]] = None,
    nsigs: float = 3,
) -> Tuple[float, float]:
    if specified_range is not None:
        return specified_range

    # Fit a Gaussian to the data
    mean, std = norm.fit(data)
    three_sigma_range = (mean - nsigs * std, mean + nsigs * std)

    # Compute data min and max
    data_min, data_max = data.min(), data.max()

    # Determine the tighter range
    return (
        max(three_sigma_range[0], data_min),
        min(three_sigma_range[1], data_max)
    )


def make_three_density_plots(
    data: Dict[int, npt.NDArray[np.float64]],
    nbins: int = 50,
    i_range: Optional[tuple[int, int]] = None,
    t_range: Optional[tuple[float, float]] = None,
    x_range: Optional[tuple[float, float]] = None,
    y_range: Optional[tuple[float, float]] = None
) -> GraphicsLayoutWidget:
    # Filter keys based on i_range if provided
    all_keys = sorted(data.keys())
    if i_range is not None:
        min_i, max_i = i_range
        i_keys = [k for k in all_keys if min_i <= k <= max_i]
    else:
        i_keys = all_keys

    if not i_keys:
        raise ValueError("No data keys fall within the specified i_range.")

    ni = len(i_keys)

    # Collect all t, x, y values for keys in i_keys
    all_t = np.concatenate([data[i][:, 0] for i in i_keys])
    all_x = np.concatenate([data[i][:, 1] for i in i_keys])
    all_y = np.concatenate([data[i][:, 2] for i in i_keys])

    # Determine bin ranges using provided ranges or data limits
    t_min, t_max = compute_range(all_t, t_range)
    x_min, x_max = compute_range(all_x, x_range)
    y_min, y_max = compute_range(all_y, y_range)

    # Define bin edges for histograms
    t_bins = np.linspace(t_min, t_max, nbins + 1)
    x_bins = np.linspace(x_min, x_max, nbins + 1)
    y_bins = np.linspace(y_min, y_max, nbins + 1)

    # Prepare 2D arrays for histograms: shape (ni, nbins)
    Tdensity = np.zeros((ni, nbins), dtype=float)
    Xdensity = np.zeros((ni, nbins), dtype=float)
    Ydensity = np.zeros((ni, nbins), dtype=float)

    for row, i in enumerate(i_keys):
        arr = data[i]
        t_vals = arr[:, 0]
        x_vals = arr[:, 1]
        y_vals = arr[:, 2]

        Tdensity[row, :], _ = np.histogram(t_vals, bins=t_bins)
        Xdensity[row, :], _ = np.histogram(x_vals, bins=x_bins)
        Ydensity[row, :], _ = np.histogram(y_vals, bins=y_bins)

    # Create the GraphicsLayoutWidget container
    win = GraphicsLayoutWidget()
    cmap = pg.colormap.getFromMatplotlib("Blues")

    # Plot 1: t vs i
    p1 = win.addPlot(title="t vs. i (Density)")
    img1 = pg.ImageItem(Tdensity.T)
    p1.addItem(img1)
    img1.setRect(QtCore.QRectF(t_min, 0, t_max - t_min, ni))
    p1.setLabel('bottom', 't')
    p1.setLabel('left', 'i')
    img1.setLookupTable(cmap.getLookupTable(alpha=True))
    p1.setYRange(0, ni)

    # Create y-axis ticks with at most 20 labels, uniformly distributed
    max_ticks = 20
    if ni <= max_ticks:
        selected_rows = list(range(ni))
    else:
        # Uniformly sample up to 20 indices from available rows
        selected_rows = np.linspace(0, ni - 1, num=max_ticks, dtype=int)

    ticks = [(row + 0.5, str(i_keys[row])) for row in selected_rows]
    p1.getAxis('left').setTicks([ticks])
    # p1.scene().sigMouseClicked.connect(lambda event: on_mouse_click(event, p1, "t", i_keys))

    # Plot 2: x vs i
    win.nextColumn()
    p2 = win.addPlot(title="x vs. i (Density)")
    img2 = pg.ImageItem(Xdensity.T)
    p2.addItem(img2)
    img2.setRect(QtCore.QRectF(x_min, 0, x_max - x_min, ni))
    p2.setLabel('bottom', 'x')
    # Hide the left (y) axis labels and ticks
    p2.getAxis('left').setVisible(False)
    img2.setLookupTable(cmap.getLookupTable(alpha=True))
    p2.setYLink(p1)  # Link y-axis to p1 to share the custom ticks
    # p2.scene().sigMouseClicked.connect(lambda event: on_mouse_click(event, p2, "x", i_keys))

    # Plot 3: y vs i
    win.nextColumn()
    p3 = win.addPlot(title="y vs. i (Density)")
    img3 = pg.ImageItem(Ydensity.T)
    p3.addItem(img3)
    img3.setRect(QtCore.QRectF(y_min, 0, y_max - y_min, ni))
    p3.setLabel('bottom', 'y')
    # Hide the left (y) axis labels and ticks
    p3.getAxis('left').setVisible(False)
    img3.setLookupTable(cmap.getLookupTable(alpha=True))
    p3.setYLink(p1)  # Link y-axis to p1 to share the custom ticks
    # p3.scene().sigMouseClicked.connect(lambda event: on_mouse_click(event, p3, "y", i_keys))

    p1.setMouseEnabled(x=False, y=False)
    p2.setMouseEnabled(x=False, y=False)
    p3.setMouseEnabled(x=False, y=False)

    # p1.hideButtons()
    # p2.hideButtons()
    # p3.hideButtons()

    return win


# def on_mouse_click(event: QMouseEvent, plot: pg.PlotItem, plot_type: str, i_keys: list[int]):
#     """Handle mouse clicks on the plot."""
#     pos = event.pos()  # Get the position of the click in scene coordinates
#     if plot.sceneBoundingRect().contains(pos):
#         mouse_point = plot.vb.mapSceneToView(pos)  # Map to plot coordinates
#         i = int(mouse_point.y())  # Get i from y-coordinate
#         value = mouse_point.x()  # Get t, x, or y from x-coordinate
#
#         if 0 <= i < len(i_keys):  # Ensure i is valid
#             print(f"Clicked on {plot_type}: i={i_keys[i]}, {plot_type}={value}")
#         else:
#             print(f"Clicked outside valid i range: i={i}, {plot_type}={value}")

