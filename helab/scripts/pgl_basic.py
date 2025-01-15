import logging
import sys
import numpy as np
from PyQt6 import QtWidgets
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from PyQt6.QtCore import QRectF

from helab.scripts.pg_simple_densities import compute_range
from helab.utils.cachingSetup import data_ram_cache
from helab.workers.loadFolderToRamWorker import LoadFolderToRamWorker



class ScatterPlot3DWidget(QtWidgets.QWidget):
    def __init__(self, data: dict[int, np.ndarray], data_range: dict[str, tuple[float, float]], parent=None):
        super().__init__(parent)

        # Create a layout for the widget
        layout = QtWidgets.QVBoxLayout(self)

        # Create a GLViewWidget for 3D visualization
        self.view = gl.GLViewWidget()
        self.view.opts['distance'] = 20  # Set a comfortable viewing distance
        self.view.setWindowTitle('3D Scatter Plot')

        # Combine all (t,x,y) points from each array in the dictionary
        points_list = []
        for arr in data.values():
            # Ensure the array has shape (n,3); adjust slicing if necessary.
            if arr.ndim == 2 and arr.shape[1] >= 3:
                # Use the first three columns as t, x, y
                points_list.append(arr[:, :3])
            else:
                # Handle different shapes as needed
                pass

        # Concatenate all points into a single array of shape (total_points, 3)
        all_points = np.vstack(points_list)

        # Filter points within the specified range
        t_min, t_max = data_range.get('t', (-np.inf, np.inf))
        x_min, x_max = data_range.get('x', (-np.inf, np.inf))
        y_min, y_max = data_range.get('y', (-np.inf, np.inf))

        filtered_points = all_points[
            (all_points[:, 0] >= t_min) & (all_points[:, 0] <= t_max) &
            (all_points[:, 1] >= x_min) & (all_points[:, 1] <= x_max) &
            (all_points[:, 2] >= y_min) & (all_points[:, 2] <= y_max)
            ]

        # Compute range for each axis
        t_range = compute_range(filtered_points[:, 0])
        x_range = compute_range(filtered_points[:, 1])
        y_range = compute_range(filtered_points[:, 2])

        # Set the camera position based on the computed ranges
        center = np.array([np.mean(t_range), np.mean(x_range), np.mean(y_range)])
        self.view.opts['center'] = pg.Vector(center)

        # Adjust the viewing distance to fit the ranges
        max_range = max(
            t_range[1] - t_range[0],
            x_range[1] - x_range[0],
            y_range[1] - y_range[0],
        )
        self.view.opts['distance'] = max_range * 1.5  # Scale to include some padding

        # Create a scatter plot item with the filtered points.
        scatter = gl.GLScatterPlotItem(pos=filtered_points, size=5, color=(1, 1, 1, 0.003))

        # Add the scatter plot item to the view
        self.view.addItem(scatter)

        # Add a grid to the view
        self.view.addItem(gl.GLGridItem(antialias=True))

        # Draw a box representing the data range
        box_color = (1, 0, 0, 0.3)  # Semi-transparent red
        box_lines = []
        for start, end in [
            # Bottom square
            ([t_min, x_min, y_min], [t_max, x_min, y_min]),
            ([t_min, x_min, y_min], [t_min, x_max, y_min]),
            ([t_min, x_max, y_min], [t_max, x_max, y_min]),
            ([t_max, x_min, y_min], [t_max, x_max, y_min]),
            # Top square
            ([t_min, x_min, y_max], [t_max, x_min, y_max]),
            ([t_min, x_min, y_max], [t_min, x_max, y_max]),
            ([t_min, x_max, y_max], [t_max, x_max, y_max]),
            ([t_max, x_min, y_max], [t_max, x_max, y_max]),
            # Vertical lines
            ([t_min, x_min, y_min], [t_min, x_min, y_max]),
            ([t_min, x_max, y_min], [t_min, x_max, y_max]),
            ([t_max, x_min, y_min], [t_max, x_min, y_max]),
            ([t_max, x_max, y_min], [t_max, x_max, y_max])
        ]:
            line = gl.GLLinePlotItem(pos=np.array([start, end]), color=box_color, width=2, antialias=True)
            box_lines.append(line)
            self.view.addItem(line)

        # Add the GLViewWidget to the layout
        layout.addWidget(self.view)


# Sample usage
if __name__ == "__main__":
    # Replace with your actual data loading logic
    # data = LoadFolderToRamWorker.default_algorithm_decompress(data_ram_cache[list(data_ram_cache)[1]])
    data = LoadFolderToRamWorker.default_algorithm_decompress(
        data_ram_cache['/Volumes/tonyNVME Gold/dld output/20240827_20240828_raman_transfer_check_det_1GHz'])

    # Specify the range for the data
    data_range = {
        't': (0, 10),  # t-axis range
        'x': (0, 10),  # x-axis range
        'y': (0, 10),  # y-axis range
    }

    app = QtWidgets.QApplication(sys.argv)

    # Create the main window and add the 3D scatter plot widget
    main_window = QtWidgets.QMainWindow()
    scatter_plot_widget = ScatterPlot3DWidget(data, data_range)
    main_window.setCentralWidget(scatter_plot_widget)
    main_window.setWindowTitle("3D Scatter Plot Viewer")
    main_window.resize(800, 600)
    main_window.show()

    sys.exit(app.exec())
