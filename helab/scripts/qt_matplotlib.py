import sys
import numpy as np
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QDockWidget, QVBoxLayout, QWidget
)
from PyQt6.QtCore import Qt
import matplotlib
from mpl_toolkits.mplot3d.art3d import Line3DCollection

matplotlib.use('QtAgg')
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

from helab.utils.cachingSetup import data_ram_cache
from helab.workers.loadFolderToRamWorker import LoadFolderToRamWorker
from helab.scripts.pg_simple_densities import compute_range

from vispy import app, scene

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("PyQt6 Matplotlib Scatter Plot")
        self.setGeometry(100, 100, 800, 600)

        # Main widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()
        central_widget.setLayout(layout)

        # Initialize a dock area
        self.dock_widgets = []

        # Create and add the scatter plot dock
        self.add_scatter_plot_dock()

    def add_scatter_plot_dock(self):

        data = LoadFolderToRamWorker.default_algorithm_decompress(
            data_ram_cache['/Users/tonyyan/OneDrive - Australian National University/SharePoint - Testing only/_He_BEC_data_root_copy/20230130_new_plates_halo_3_halos_manual_exclude']
        )
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


        t_range = compute_range(all_points[:, 0])
        x_range = compute_range(all_points[:, 1])
        y_range = compute_range(all_points[:, 2])



        # def optimized_3d_plot(ax, points):
        #     segments = [[(x, y, z), (x, y, z)] for x, y, z in points]  # Dummy segments
        #     lc = Line3DCollection(segments, colors='r', linewidths=0.5, alpha=0.1)
        #     ax.add_collection3d(lc)


        # Filter visible points
        x_min, x_max = 3.8, 3.9
        y_min, y_max = -0.03, 0.03
        z_min, z_max = -0.03, 0.03

        visible_points = all_points[
            (all_points[:, 0] >= x_min) & (all_points[:, 0] <= x_max) &
            (all_points[:, 1] >= y_min) & (all_points[:, 1] <= y_max) &
            (all_points[:, 2] >= z_min) & (all_points[:, 2] <= z_max)
        ]

        # Create a figure and scatter plot
        fig = Figure()
        ax = fig.add_subplot(projection='3d')
        ax.scatter(visible_points[:, 0], visible_points[:, 1], visible_points[:, 2], c='r', alpha=0.1, s=1)
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
        ax.set_zlim(z_min, z_max)

        # optimized_3d_plot(ax, all_points)

        # plt.xlim(2.0, 2.2)
        ax.axes.set_xlim3d(3.8, 3.9)
        ax.axes.set_ylim3d(-0.03, 0.03)
        ax.axes.set_zlim3d(-0.03, 0.03)
        # plt.show()

        # Create a canvas to embed the figure
        canvas = FigureCanvas(fig)

        # Create a dock widget and set the canvas as its content
        dock_widget = QDockWidget("Matplotlib Scatter", self)
        dock_widget.setWidget(canvas)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock_widget)
        self.dock_widgets.append(dock_widget)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
