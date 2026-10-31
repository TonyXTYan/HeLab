import os
import socket
import threading
from dataclasses import dataclass
from typing import Optional, Dict, Any

import dash
from dash import html, no_update, Output, Input, State, dcc
from dash.exceptions import PreventUpdate
from plotly.graph_objs import Figure
from werkzeug.serving import BaseWSGIServer, make_server

NOT_FOUND = "Plot not found. It is removed when its plot is closed in HeLab."


@dataclass(frozen=True)
class PlotSnapshot:
    """A plot's figure and its revision, stored and read as one value: a page is never sent one
    figure tagged with another's revision (it would then wait for ever for the figure it lacks)."""
    revision: int
    figure: Figure


class DashServer:
    """Serves each plot's Plotly figure at ``/plot/<id>`` (the plot dock's web view and Open in
    browser show the same page). A plot's newer figure (``update_plot``, e.g. a rerun as Live
    adds shots) replaces the shown one in place: each page asks every ``POLL_MS`` whether its
    plot has a newer revision, and Dash swaps the figure in without reloading the page, so the
    view's rotation, zoom and pan stay (figures keep a constant ``layout.uirevision``). Once the
    plot is closed (``remove_plot``), a page still open says so, drops the figure and stops
    polling."""

    HOST_NAME = "127.0.0.1"
    HOST_PORT = 8050  # preferred; another free port is used when it is taken
    POLL_MS = 1000


    def __init__(self) -> None:
        self.app = dash.Dash(__name__, suppress_callback_exceptions=True)
        # Each plot's latest snapshot, replaced whole by each update (pages read it on threads).
        self._plots: dict[str, PlotSnapshot] = {}
        self._plots_lock = threading.Lock()
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
            return self.page(pathname)

        @self.app.callback(Output('plot-graph', 'figure'), Output('plot-revision', 'data'),
                           Output('plot-graph', 'style'), Output('plot-closed', 'children'),
                           Output('plot-poll', 'disabled'),
                           Input('plot-poll', 'n_intervals'), State('url', 'pathname'),
                           State('plot-revision', 'data'), prevent_initial_call=True)
        def refresh(_: Any, pathname: Optional[str], shown: Any) -> Any:
            outputs = self.poll(pathname, shown)
            if outputs is None:
                raise PreventUpdate  # Nothing newer: the page stays as it is.
            return outputs

    def poll(self, pathname: Optional[str], shown: Any) -> Optional[tuple[Any, ...]]:
        """What a page's poll changes (figure, revision, graph style, closed text, poll disabled):
        a newer snapshot's figure and revision; for a closed plot, an empty hidden graph, the
        not-found text and no more polls; None when nothing changed."""
        plot_id = self.plot_id_of(pathname)
        if plot_id is None:
            return None
        snapshot = self.snapshot(plot_id)
        if snapshot is None:
            return {"data": [], "layout": {}}, no_update, {"display": "none"}, NOT_FOUND, True
        if isinstance(shown, int) and snapshot.revision <= shown:
            return None
        return snapshot.figure, snapshot.revision, no_update, no_update, no_update

    def page(self, pathname: Optional[str]) -> Any:
        """A plot's page: its figure, the revision it is (from one snapshot) and the poll."""
        plot_id = self.plot_id_of(pathname)
        snapshot = self.snapshot(plot_id) if plot_id else None
        if snapshot is None:
            return html.Div(NOT_FOUND)
        return html.Div([
            html.Div(id='plot-closed'),
            dcc.Graph(id='plot-graph', figure=snapshot.figure, style={"height": "96vh"}),
            dcc.Store(id='plot-revision', data=snapshot.revision),
            dcc.Interval(id='plot-poll', interval=self.POLL_MS)])

    @staticmethod
    def plot_id_of(pathname: Optional[str]) -> Optional[str]:
        if not pathname or not pathname.startswith('/plot/'):
            return None
        return pathname.split('/plot/')[1]

    def snapshot(self, plot_id: str) -> Optional[PlotSnapshot]:
        """The plot's figure and revision, read together (None: no such plot, or closed)."""
        with self._plots_lock:
            return self._plots.get(plot_id)

    def newer_snapshot(self, pathname: Optional[str], shown: Any) -> Optional[PlotSnapshot]:
        """The snapshot of the plot at ``pathname``, if newer than the revision ``shown``."""
        plot_id = self.plot_id_of(pathname)
        snapshot = self.snapshot(plot_id) if plot_id else None
        if snapshot is None or (isinstance(shown, int) and snapshot.revision <= shown):
            return None
        return snapshot

    def add_plot(self, plot_id: str, fig: Figure) -> None:
        self.start()
        with self._plots_lock:
            previous = self._plots.get(plot_id)
            self._plots[plot_id] = PlotSnapshot((previous.revision if previous else 0) + 1, fig)

    def update_plot(self, plot_id: str, fig: Figure) -> None:
        """A newer figure of a shown plot: its pages swap it in place within ``POLL_MS``."""
        self.add_plot(plot_id, fig)

    def remove_plot(self, plot_id: str) -> None:
        """Forget a figure (its plot dock closed), freeing its data."""
        with self._plots_lock:
            self._plots.pop(plot_id, None)

    def _bind(self) -> socket.socket:
        """Listen on HOST_PORT, or on any free port if it is in use (e.g. by another HeLab)."""
        for port in (self.HOST_PORT, 0):
            if port and self._listened_on_all(port):
                continue
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

    @staticmethod
    def _listened_on_all(port: int) -> bool:
        """Whether another socket holds ``port`` on all addresses (IPv4's, or IPv6's taking IPv4 too).
        macOS (with SO_REUSEADDR) and Windows (without) bind HOST_NAME beside it, which then takes its
        connections to 127.0.0.1 (plots-4). Found by binding the wildcard address as HeLab binds its own
        (SO_REUSEADDR off Windows, where it would share the port): connections in TIME_WAIT don't refuse
        that (on Linux a listener on HOST_NAME does, whose port can't be shared anyway). Nothing is sent."""
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name != "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("0.0.0.0", port))
        except OSError:
            return True
        finally:
            probe.close()
        return False

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
