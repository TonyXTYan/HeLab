# type: ignore
import sys
import numpy as np
import pyvista as pv
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from pyvistaqt import QtInteractor

from helab.utils.caching_setup import data_ram_cache
from helab.workers.LoadFolderToRamWorker import LoadFolderToRamWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("PyVista 3D Scatter Plot")

        # Set up the main widget and layout
        self.main_widget = QWidget()
        self.layout = QVBoxLayout(self.main_widget)

        # Create the PyVista interactor
        self.plotter = QtInteractor(self.main_widget)
        self.layout.addWidget(self.plotter.interactor)

        self.setCentralWidget(self.main_widget)

        # # Generate random 3D scatter data
        # points = np.random.rand(10000, 3)
        #
        # # Create a PyVista PolyData object
        # cloud = pv.PolyData(points)

        data = LoadFolderToRamWorker.default_algorithm_decompress(
            data_ram_cache[
                '/Users/tonyyan/OneDrive - Australian National University/SharePoint - Testing only/_He_BEC_data_root_copy/20230130_new_plates_halo_3_halos_manual_exclude']
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

        cloud = pv.PolyData(all_points)

        # Add the scatter plot to the plotter
        self.plotter.add_points(cloud, color='blue', point_size=1, opacity=0.5)

        # Show the plot
        self.plotter.show()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())