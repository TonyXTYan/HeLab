import uuid
from typing import Dict, Optional, Tuple

import numpy as np
import numpy.typing as npt
import plotly.graph_objs as go
from PyQt6.QtCore import QUrl, QTimer
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QDockWidget
from scipy.optimize import curve_fit

# from helab.scripts.dev.pg_simple_densities import compute_range
from helab.utils.dash_server import DashServer, dash_server


class Plotly3DScatter(QWidget):
    def __init__(self,
                 data: Dict[int, npt.NDArray[np.float64]],
                 # dash_server: DashServer
                 ):
        super().__init__()
        self.data = data
        # self.dash_server = dash_server
        self.unique_id = str(uuid.uuid4())
        self.url = dash_server.plot_url(self.unique_id)
        # self.url = f"http://127.0.0.1:8050/plot/{self.unique_id}"
        # self.url = f"http://192.168.1.23:8050/plot/{self.unique_id}"
        self.browser = QWebEngineView()
        print(f"{self.url = }")
        layout = QVBoxLayout(self)
        layout.addWidget(self.browser)
        self.setLayout(layout)
        self.plot()

    def plot(self) -> None:

        points_list = []
        for arr in self.data.values():
            if arr.ndim == 2 and arr.shape[1] >= 3:
                points_list.append(arr[:, :3])
        all_points = np.vstack(points_list)
        all_points = all_points[:10000, :]

        # z_min, z_max = 3.8, 3.9
        # x_min, x_max = -0.03, 0.03
        # y_min, y_max = -0.03, 0.03
        z_range = self.compute_range(all_points[:, 0])
        y_range = self.compute_range(all_points[:, 1])
        x_range = self.compute_range(all_points[:, 2])

        scatter = go.Scatter3d(
            x=all_points[:, 1],
            y=all_points[:, 2],
            z=all_points[:, 0],
            mode='markers',
            marker=dict(size=1, opacity=0.5)
        )
        layout = go.Layout(
            scene=dict(
                xaxis=dict(title='X-axis', range=(x_range[0], x_range[1])),
                yaxis=dict(title='Y-axis', range=(y_range[0], y_range[1])),
                zaxis=dict(title='Z-axis', range=(z_range[0], z_range[1])),
            ),
            margin=dict(l=0, r=0, b=0, t=0)
        )
        fig = go.Figure(data=[scatter], layout=layout)

        dash_server.add_plot(self.unique_id, fig)
        QTimer.singleShot(100, lambda: self.browser.setUrl(QUrl(self.url)))

    @staticmethod
    def gaussian_with_offset(x: npt.NDArray[np.float64], amp: float, mu: float, sigma: float, offset: float) -> npt.NDArray[np.float64]:
        return amp * np.exp(-(x - mu) ** 2 / (2 * sigma ** 2)) + offset

    @staticmethod
    def compute_range(
            data: npt.NDArray[np.float64],
            specified_range: Optional[Tuple[float, float]] = None,
            nsigs: float = 3,
    ) -> Tuple[float, float]:
        if specified_range is not None:
            return specified_range

        # Create histogram data for fitting
        hist, bin_edges = np.histogram(data, bins='auto')
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

        # Initial parameter guesses
        p0 = [
            np.max(hist) - np.min(hist),  # amplitude
            np.mean(data),  # mean
            np.std(data),  # standard deviation
            np.min(hist)  # offset
        ]

        try:
            # Fit Gaussian with offset
            popt, _ = curve_fit(Plotly3DScatter.gaussian_with_offset, bin_centers, hist, p0=p0)
            _, mu, sigma, _ = popt  # Ignore amplitude and offset

            return (mu - nsigs * sigma, mu + nsigs * sigma)
        except:
            # Fallback to simple statistics if fit fails
            mean, std = np.mean(data), np.std(data)
            return (mean - nsigs * std, mean + nsigs * std)