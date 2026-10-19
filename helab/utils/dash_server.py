import os
import socket
import threading
from typing import Optional, Dict, Any

import dash
from dash import html, Output, Input, dcc
from plotly.graph_objs import Figure
from werkzeug.serving import BaseWSGIServer, make_server

from helab.utils.synchronised_dict import SynchronisedDict


class DashServer:

    HOST_NAME = "127.0.0.1"
    HOST_PORT = 8050  # preferred; another free port is used when it is taken


    def __init__(self) -> None:
        self.app = dash.Dash(__name__, suppress_callback_exceptions=True)
        self.plots: SynchronisedDict[str, Figure] = SynchronisedDict()
        self.setup_layout()
        # The server starts on first use, not at import: importing the GUI (as
        # tests and every parallel test worker do) must not take a port.
        self._lock = threading.Lock()
        self._server: Optional[BaseWSGIServer] = None

    def setup_layout(self) -> None:
        self.app.layout = html.Div([
            dcc.Location(id='url', refresh=False),
            html.Div(id='page-content')
        ])

        @self.app.callback(Output('page-content', 'children'),
                           Input('url', 'pathname'))
        def display_page(pathname: Optional[str]) -> Any:
            if pathname and pathname.startswith('/plot/'):
                plot_id = pathname.split('/plot/')[1]
                fig = self.plots.get(plot_id)
                if fig:
                    return dcc.Graph(figure=fig, style={"height": "96vh"})
            return html.Div("Plot not found. It is removed when its plot is closed in HeLab.")

    def add_plot(self, plot_id: str, fig: Figure) -> None:
        self.start()
        self.plots[plot_id] = fig

    def remove_plot(self, plot_id: str) -> None:
        """Forget a figure (its plot dock closed), freeing its data."""
        self.plots.pop(plot_id, None)

    def _bind(self) -> socket.socket:
        """Listen on HOST_PORT, or on any free port if it is in use (e.g. by another HeLab)."""
        for port in (self.HOST_PORT, 0):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if os.name != "nt":
                # On Windows SO_REUSEADDR would let us share a port another program is using.
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((self.HOST_NAME, port))
                sock.listen(socket.SOMAXCONN)
            except OSError:
                sock.close()
                if port == 0:
                    raise
                continue
            return sock
        raise AssertionError("unreachable")

    def start(self) -> int:
        """Start the server if it isn't running, and return its port."""
        with self._lock:
            if self._server is None:
                sock = self._bind()
                try:
                    server = make_server(self.HOST_NAME, sock.getsockname()[1], self.app.server,
                                         threaded=True, fd=sock.fileno())
                finally:
                    sock.close()  # the server holds its own duplicate of the socket
                threading.Thread(target=server.serve_forever, name="DashServer", daemon=True).start()
                self._server = server
            return int(self._server.server_address[1])

    def stop(self) -> None:
        with self._lock:
            server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()

    @property
    def url(self) -> str:
        return f"http://{self.HOST_NAME}:{self.start()}"

    def plot_url(self, plot_id: str) -> str:
        return f"{self.url}/plot/{plot_id}"

dash_server = DashServer()
