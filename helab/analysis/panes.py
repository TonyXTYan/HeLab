"""Plot-dock content shared by analyses: a Plotly figure served by the Dash server."""
from __future__ import annotations

import uuid
from typing import Optional

from plotly.graph_objs import Figure
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from helab.utils.dash_server import DashServer, dash_server


class PlotlyPane(QWidget):
    """A Plotly figure in the plot area, and an **Open in browser** button for the same
    page: lab PCs whose GPU can't paint QtWebEngine show the plot in a browser instead."""

    def __init__(self, figure: Figure, note: str = "", parent: Optional[QWidget] = None,
                 server: DashServer = dash_server) -> None:
        super().__init__(parent)
        self.plot_id = uuid.uuid4().hex
        server.add_plot(self.plot_id, figure)
        self.url = server.plot_url(self.plot_id)
        # Free the figure's data on the server when the dock goes (not bound to self).
        plot_id = self.plot_id
        self.destroyed.connect(lambda *_: server.remove_plot(plot_id))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.note = QLabel(note, self)
        row.addWidget(self.note, 1)
        self.open_button = QPushButton("Open in browser", self)
        self.open_button.setToolTip(f"Show this plot in your web browser\n{self.url}")
        self.open_button.clicked.connect(self.open_in_browser)
        row.addWidget(self.open_button)
        layout.addLayout(row)
        self.browser = QWebEngineView(self)
        self.browser.setUrl(QUrl(self.url))
        layout.addWidget(self.browser, 1)

    def open_in_browser(self) -> bool:
        return QDesktopServices.openUrl(QUrl(self.url))
