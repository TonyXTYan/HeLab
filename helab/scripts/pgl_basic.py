import logging

import coloredlogs

coloredlogs.install(
        level=logging.DEBUG,
        # format='%(asctime)s - %(levelname)s - %(message)s'
        fmt='%(asctime)s - %(levelname)s:\t%(message)s',
    )
import sys
import numpy as np
from PyQt6 import QtWidgets, QtCore, QtGui
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
        self.openGLWidget = gl.GLViewWidget()
        self.openGLWidget.opts['distance'] = 20  # Set a comfortable viewing distance
        self.openGLWidget.setWindowTitle('3D Scatter Plot')
        self.openGLWidget.setCameraPosition(distance=20)
        self.openGLWidget.pan(0, 0, 0)  # Enable panning

        # self.openGLWidget.setMouseEnabled(pan=True, zoom=True)  # Enable pan and zoom
        # self.openGLWidget.setMouseMode(self.openGLWidget.MouseMode.Pan)  # Set the default mouse mode to pan
        # self.openGLWidget.mouseMoveEvent()

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
        self.openGLWidget.opts['center'] = pg.Vector(center)

        # Adjust the viewing distance to fit the ranges
        max_range = max(
            t_range[1] - t_range[0],
            x_range[1] - x_range[0],
            y_range[1] - y_range[0],
        )
        self.openGLWidget.opts['distance'] = max_range * 1.5  # Scale to include some padding

        # Create a scatter plot item with the filtered points.
        scatter = gl.GLScatterPlotItem(pos=filtered_points, size=5, color=(1, 1, 1, 0.5))

        # Add the scatter plot item to the
        self.openGLWidget.addItem(scatter)

        # Add a grid to the
        self.openGLWidget.addItem(gl.GLGridItem(antialias=True))

        # # Draw a box representing the data range
        # box_color = (1, 0, 0, 0.3)  # Semi-transparent red
        # box_lines = []
        # for start, end in [
        #     # Bottom square
        #     ([t_min, x_min, y_min], [t_max, x_min, y_min]),
        #     ([t_min, x_min, y_min], [t_min, x_max, y_min]),
        #     ([t_min, x_max, y_min], [t_max, x_max, y_min]),
        #     ([t_max, x_min, y_min], [t_max, x_max, y_min]),
        #     # Top square
        #     ([t_min, x_min, y_max], [t_max, x_min, y_max]),
        #     ([t_min, x_min, y_max], [t_min, x_max, y_max]),
        #     ([t_min, x_max, y_max], [t_max, x_max, y_max]),
        #     ([t_max, x_min, y_max], [t_max, x_max, y_max]),
        #     # Vertical lines
        #     ([t_min, x_min, y_min], [t_min, x_min, y_max]),
        #     ([t_min, x_max, y_min], [t_min, x_max, y_max]),
        #     ([t_max, x_min, y_min], [t_max, x_min, y_max]),
        #     ([t_max, x_max, y_min], [t_max, x_max, y_max])
        # ]:
        #     line = gl.GLLinePlotItem(pos=np.array([start, end]), color=box_color, width=2, antialias=True)
        #     box_lines.append(line)
        #     self.openGLWidget.addItem(line)

        # layout.installEventFilter(self)
        # self.openGLWidget.installEventFilter(self)
        # Add the GLViewWidget to the layout
        layout.addWidget(self.openGLWidget)

    # Just use default
    # https://pyqtgraph.readthedocs.io/en/latest/user_guide/mouse_interaction.html

    # https://stackoverflow.com/questions/63578370/how-to-change-pan-event-from-wheel-presdrag-to-mouse-right-click-drag-at-pyqtg
    # DOES NOT WORK: pan direction is messed up.
    #
    # def eventFilter(self, source, event):
    #     logging.debug(f"{event = }")
    #     if event.type() == QtCore.QEvent.Type.MouseMove:
    #         if event.buttons() == QtCore.Qt.MouseButton.NoButton:
    #             print("Simple mouse motion")
    #             pass
    #         elif event.buttons() == QtCore.Qt.MouseButton.LeftButton:
    #             # print("Left click drag")
    #             pass
    #         elif event.buttons() == QtCore.Qt.MouseButton.RightButton:
    #             coef = 20  # Responsiveness of the pan
    #
    #             xx = ((self.openGLWidget.size().width()) / 2) / coef
    #             yy = ((self.openGLWidget.size().height()) / 2) / coef
    #             self.pan((event.position().x() / coef) - xx, (event.position().y() / coef) - yy, 0)
    #             # self.openGLWidget.updateGL()
    #             self.openGLWidget.update()
    #             # print("Right click drag")
    #
    #
    #     elif event.type() == QtCore.QEvent.Type.MouseButtonPress:
    #         if event.button() == QtCore.Qt.MouseButton.RightButton:
    #             pass
    #             # print("Press!")
    #     # return super(MainWindow, self).eventFilter(source, event)
    #     # return False
    #
    # def pan(self, dx, dy, dz, relative='view'):
    #     """
    #     Moves the center (look-at) position while holding the camera in place.
    #
    #     ==============  =======================================================
    #     *relative*      String that determines the direction of dx,dy,dz.
    #
    #                     If "global", then the global coordinate system is used.
    #                     If "view", then the z axis is aligned with the view
    #                     If "view-upright", then x is in the global xy plane and
    #
    #                     points to the right side of the view, y is in the
    #                     global xy plane and orthogonal to x, and z points in
    #                     the global z direction.
    #     """
    #     # for backward compatibility:
    #     # relative = {True: "view-upright", False: "global"}.get(relative, relative)
    #
    #     if relative == 'global':
    #         self.openGLWidget.opts['center'] += QtGui.QVector3D(dx, dy, dz)
    #     elif relative == 'view-upright':
    #         cPos = self.openGLWidget.cameraPosition()
    #         cVec = self.openGLWidget.opts['center'] - cPos
    #         dist = cVec.length()  ## distance from camera to center
    #         xDist = dist * 2. * np.tan(0.5 * self.openGLWidget.opts[
    #             'fov'] * np.pi / 180.)  ## approx. width of view at distance of center point
    #         xScale = xDist / self.width()
    #         zVec = QtGui.QVector3D(0, 0, 1)
    #         xVec = QtGui.QVector3D.crossProduct(zVec, cVec).normalized()
    #         yVec = QtGui.QVector3D.crossProduct(xVec, zVec).normalized()
    #         self.openGLWidget.opts['center'] = self.openGLWidget.opts[
    #                                                'center'] + xVec * xScale * dx + yVec * xScale * dy + zVec * xScale * dz
    #     elif relative == 'view':
    #         # pan in plane of camera
    #         elev = np.radians(self.openGLWidget.opts['elevation'])
    #         azim = np.radians(self.openGLWidget.opts['azimuth'])
    #         fov = np.radians(self.openGLWidget.opts['fov'])
    #         dist = (self.openGLWidget.opts['center'] - self.openGLWidget.cameraPosition()).length()
    #         fov_factor = np.tan(fov / 2) * 2
    #         scale_factor = dist * fov_factor / self.width()
    #         z = scale_factor * np.cos(elev) * dy
    #         x = scale_factor * (np.sin(azim) * dx - np.sin(elev) * np.cos(azim) * dy)
    #         y = scale_factor * (np.cos(azim) * dx + np.sin(elev) * np.sin(azim) * dy)
    #         self.openGLWidget.opts['center'] += QtGui.QVector3D(x, -y, z)
    #     else:
    #         raise ValueError("relative argument must be global, view, or view-upright")
    #
    #     self.update()


# Sample usage
if __name__ == "__main__":
    # Replace with your actual data loading logic
    # data = LoadFolderToRamWorker.default_algorithm_decompress(data_ram_cache[list(data_ram_cache)[1]])
    data = LoadFolderToRamWorker.default_algorithm_decompress(
        # data_ram_cache['/Volumes/tonyNVME Gold/dld output/20240827_20240828_raman_transfer_check_det_1GHz'])
        data_ram_cache['/Users/tonyyan/OneDrive - Australian National University/SharePoint - Testing only/_He_BEC_data_root_copy/20230130_new_plates_halo_3_halos_manual_exclude'])


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
