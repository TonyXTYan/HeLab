import os
import sys
import threading
import uuid

import numpy as np
from PyQt6.QtCore import QUrl, QTimer
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QTabWidget
from PyQt6.QtWebEngineWidgets import QWebEngineView
import plotly.graph_objs as go

import dash
from dash import dcc, html
from dash.dependencies import Input, Output

from helab.scripts.pg_simple_densities import compute_range
from helab.utils.cachingSetup import data_ram_cache
from helab.utils.constants import DIR_TEMPS
from helab.workers.loadFolderToRamWorker import LoadFolderToRamWorker

class DashServer:
    def __init__(self):
        self.app = dash.Dash(__name__, suppress_callback_exceptions=True)
        self.plots = {}
        self.setup_layout()
        threading.Thread(target=self.run_server, daemon=True).start()

    def setup_layout(self):
        self.app.layout = html.Div([
            dcc.Location(id='url', refresh=False),
            html.Div(id='page-content')
        ])

        @self.app.callback(Output('page-content', 'children'),
                           Input('url', 'pathname'))
        def display_page(pathname):
            print(f"{pathname = }")
            if pathname and pathname.startswith('/plot/'):
                plot_id = pathname.split('/plot/')[1]
                fig = self.plots.get(plot_id)
                if fig:
                    return dcc.Graph(figure=fig)
            return html.Div("Plot not found.")

    def add_plot(self, plot_id, fig):
        self.plots[plot_id] = fig

    def run_server(self):
        # self.app.run_server(host="192.168.1.23", port=8050, debug=False, use_reloader=False)
        self.app.run_server(host="127.0.0.1", port=8050, debug=False, use_reloader=False)

class Plotly3DScatter(QWidget):
    def __init__(self, parent=None, dash_server=None):
        super().__init__(parent)
        self.dash_server = dash_server
        self.unique_id = str(uuid.uuid4())
        self.url = f"http://127.0.0.1:8050/plot/{self.unique_id}"
        # self.url = f"http://192.168.1.23:8050/plot/{self.unique_id}"
        print(f"{self.url = }")
        self.layout = QVBoxLayout(self)
        self.browser = QWebEngineView()
        self.layout.addWidget(self.browser)
        self.setLayout(self.layout)
        self.plot()

    def plot(self):
        data = LoadFolderToRamWorker.default_algorithm_decompress(
            data_ram_cache['/Users/tonyyan/OneDrive - Australian National University/SharePoint - Testing only/_He_BEC_data_root_copy/20230130_new_plates_halo_3_halos_manual_exclude']
        )

        points_list = []
        for arr in data.values():
            if arr.ndim == 2 and arr.shape[1] >= 3:
                points_list.append(arr[:, :3])
        all_points = np.vstack(points_list)

        z_min, z_max = 3.8, 3.9
        x_min, x_max = -0.03, 0.03
        y_min, y_max = -0.03, 0.03

        scatter = go.Scatter3d(
            x=all_points[:, 1],
            y=all_points[:, 2],
            z=all_points[:, 0],
            mode='markers',
            marker=dict(size=1, opacity=0.5)
        )
        layout = go.Layout(
            scene=dict(
                xaxis=dict(title='X-axis', range=(x_min, x_max)),
                yaxis=dict(title='Y-axis', range=(y_min, y_max)),
                zaxis=dict(title='Z-axis', range=(z_min, z_max))
            ),
            margin=dict(l=0, r=0, b=0, t=0)
        )
        fig = go.Figure(data=[scatter], layout=layout)

        self.dash_server.add_plot(self.unique_id, fig)
        QTimer.singleShot(1000, lambda: self.browser.setUrl(QUrl(self.url)))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('3D Scatter Plot with Plotly and PyQt6')
        self.setGeometry(100, 100, 800, 600)
        self.tab_widget = QTabWidget()
        
        self.dash_server = DashServer()

        self.plot_widget1 = Plotly3DScatter(self, dash_server=self.dash_server)
        self.plot_widget2 = Plotly3DScatter(self, dash_server=self.dash_server)
        
        self.tab_widget.addTab(self.plot_widget1, "Plot 1")
        self.tab_widget.addTab(self.plot_widget2, "Plot 2")
        self.setCentralWidget(self.tab_widget)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())