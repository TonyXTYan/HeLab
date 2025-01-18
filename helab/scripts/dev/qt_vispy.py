# type: ignore
import sys
import numpy as np
from PyQt6.QtWidgets import QApplication, QMainWindow
from vispy import scene
from vispy.scene import visuals

from helab.utils.caching_setup import data_ram_cache
from helab.workers.LoadFolderToRamWorker import LoadFolderToRamWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('3D Scatter Plot with Vispy and PyQt6')
        self.setGeometry(100, 100, 800, 600)

        # Create a canvas and add a view
        self.canvas = scene.SceneCanvas(keys='interactive', show=True)
        self.view = self.canvas.central_widget.add_view()

        # # Generate some data
        # pos = np.random.normal(size=(1000, 3), scale=0.2)
        # colors = np.random.uniform(size=(1000, 4), low=0.5, high=1)

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

        all_points = np.vstack(points_list)

        # Create scatter plot
        scatter = visuals.Markers()
        # scatter.set_data(pos, edge_color=None, face_color=colors, size=5)
        scatter.set_data(all_points, edge_color=None, face_color=(1, 1, 1, 0.7), size=2)

        # Add scatter plot to the view
        self.view.add(scatter)

        # Set the camera
        # self.view.camera = 'turntable'
        self.view.camera = 'arcball'
        self.view.camera.fov = 45
        self.view.camera.distance = 2

        self.view.camera._near = 1e-6
        self.view.camera._far = 1e6

        # Add the canvas to the main window
        self.setCentralWidget(self.canvas.native)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())