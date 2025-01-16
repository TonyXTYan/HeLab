# type: ignore
import os
import sys
import tempfile

import numpy as np
from PyQt6.QtCore import QUrl, QTimer
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PyQt6.QtWebEngineWidgets import QWebEngineView
import plotly.graph_objs as go
import plotly.io as pio

from helab.scripts.pg_simple_densities import compute_range
from helab.utils.cachingSetup import data_ram_cache
from helab.utils.constants import DIR_TEMPS
from helab.workers.loadFolderToRamWorker import LoadFolderToRamWorker


class Plotly3DScatter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.browser = QWebEngineView()
        self.layout.addWidget(self.browser)
        self.setLayout(self.layout)
        self.plot()

    def plot(self):
        # # Sample data
        # np.random.seed(0)
        # x = np.random.randn(100)
        # y = np.random.randn(100)
        # z = np.random.randn(100)

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

        z_min, z_max = 3.8, 3.9
        x_min, x_max = -0.03, 0.03
        y_min, y_max = -0.03, 0.03

        # Create a 3D scatter plot
        # scatter = go.Scatter3d(x=x, y=y, z=z, mode='markers')
        scatter = go.Scatter3d(x=all_points[:, 1], y=all_points[:, 2], z=all_points[:, 0],
                               mode='markers',
                               marker=dict(size=1, opacity=0.5)
                               )
        layout = go.Layout(scene=dict(
            xaxis=dict(title='X-axis', range=(x_min, x_max)),
            yaxis=dict(title='Y-axis', range=(y_min, y_max)),
            zaxis=dict(title='Z-axis', range=(z_min, z_max))
        ),
            margin=dict(l=0, r=0, b=0, t=0)
        )
        fig = go.Figure(data=[scatter], layout=layout)


        # # Render the plot as HTML
        # html = pio.to_html(fig, full_html=True)
        # self.browser.setHtml(html)

        plotly_fig_html = fig.to_html()
        plotly_view = QWebEngineView()
        plotly_view.setHtml(plotly_fig_html)
        plotly_temp = tempfile.NamedTemporaryFile(prefix="plotly_", suffix='.html', dir=DIR_TEMPS, delete=False)
        # plotly_temp = tempfile.SpooledTemporaryFile(prefix="plotly_", suffix='.html', dir=DIR_TEMPS, max_size=1<<20<<7, encoding='utf-8')
        plotly_temp.write(plotly_fig_html.encode('utf-8'))
        # plotly_temp.write(plotly_fig_html.encode())
        print(plotly_temp.name)
        plotly_temp_html_filename = plotly_temp.name
        plotly_view.load(QUrl.fromLocalFile(plotly_temp_html_filename))
        #
        plotly_temp.close()

        # delete the temp file
        QTimer.singleShot(5*1000, lambda: os.remove(plotly_temp.name))

        self.layout.addWidget(plotly_view)
        # print(plotly_view.)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('3D Scatter Plot with Plotly and PyQt6')
        self.setGeometry(100, 100, 800, 600)
        self.plot_widget = Plotly3DScatter(self)
        self.setCentralWidget(self.plot_widget)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())