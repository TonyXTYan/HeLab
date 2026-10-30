"""Plot-dock content shared by analyses: a Plotly figure served by the Dash server."""
from __future__ import annotations

import uuid
import weakref
from typing import Optional

from plotly.graph_objs import Figure
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from helab.utils.dash_server import DashServer, dash_server
from helab.utils.accessible import identify


class PlotlyPane(QWidget):
    """A Plotly figure in the plot area, and an **Open in browser** button for the same
    page: lab PCs whose GPU can't paint QtWebEngine show the plot in a browser instead.
    ``update_figure`` shows a newer figure on the same page, in place (here and in browser tabs
    showing it), keeping the view's rotation, zoom and pan."""

    def __init__(self, figure: Figure, note: str = "", parent: Optional[QWidget] = None,
                 server: DashServer = dash_server) -> None:
        super().__init__(parent)
        self.server = server
        self.plot_id = uuid.uuid4().hex
        server.add_plot(self.plot_id, figure)
        self.url = server.plot_url(self.plot_id)
        # Free the figure's data on the server: when the plot leaves its dock (``release_figure``, called
        # by the dock and the plot's close), else once the pane goes (holding neither the pane nor a Qt
        # connection). Not a Python callable on ``destroyed``: run as the dock's children are deleted,
        # one crashed the process (SIGSEGV in a PyQt slot proxy, Smoke ready's follow-up notes).
        self._free = weakref.finalize(self, server.remove_plot, self.plot_id)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.note = QLabel(note, self)
        row.addWidget(self.note, 1)
        self.open_button = identify(QPushButton("Open in browser", self), "plotly_open_in_browser")
        self.open_button.setToolTip(f"Show this plot in your web browser\n{self.url}")
        self.open_button.clicked.connect(self.open_in_browser)
        row.addWidget(self.open_button)
        layout.addLayout(row)
        self.browser = QWebEngineView(self)
        self.browser.setUrl(QUrl(self.url))
        layout.addWidget(self.browser, 1)

    def update_figure(self, figure: Figure, note: str = "") -> None:
        """A newer figure: the page swaps it in without reloading (``DashServer.update_plot``)."""
        self.server.update_plot(self.plot_id, figure)
        self.note.setText(note)

    def release_figure(self) -> None:
        """The plot left its dock (closed, released or drawn anew): its figure leaves the server now, so a
        browser page showing it says so, and its data is freed (once; the pane's going does nothing more)."""
        self._free()

    def open_in_browser(self) -> bool:
        return QDesktopServices.openUrl(QUrl(self.url))
