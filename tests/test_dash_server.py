import json
import socket
import urllib.request
from typing import Any, Iterator

import plotly.graph_objs as go
import pytest

from helab.utils.dash_server import DashServer, PlotSnapshot


@pytest.fixture
def servers() -> Iterator[list[DashServer]]:
    made: list[DashServer] = []
    yield made
    for server in made:
        server.stop()


def test_server_does_not_start_until_used(servers: list[DashServer]) -> None:
    server = DashServer()
    servers.append(server)
    assert server._server is None
    server.plot_url("x")
    assert server._server is not None


def test_taken_port_falls_back_to_a_free_one(servers: list[DashServer]) -> None:
    # Two servers can't share a port: the second must move, not fail in its thread.
    first, second = DashServer(), DashServer()
    servers.extend([first, second])
    with socket.socket() as blocker:
        blocker.bind((DashServer.HOST_NAME, 0))
        blocker.listen()
        port = blocker.getsockname()[1]
        first.HOST_PORT = second.HOST_PORT = port
        assert first.start() != port
        assert second.start() not in (port, first.start())


def test_serves_added_plot(servers: list[DashServer]) -> None:
    server = DashServer()
    servers.append(server)
    server.add_plot("abc", go.Figure())
    with urllib.request.urlopen(server.plot_url("abc"), timeout=10) as response:
        assert response.status == 200
    with urllib.request.urlopen(f"{server.url}/_dash-layout", timeout=10) as response:
        assert response.status == 200


def test_stop_frees_the_port() -> None:
    server = DashServer()
    port = server.start()
    server.stop()
    assert server._server is None
    with socket.socket() as probe:
        probe.bind((DashServer.HOST_NAME, port))


def test_a_newer_figure_replaces_the_shown_one_in_place() -> None:
    """Each plot page polls for its plot's revision; a newer one is swapped in by Dash (no page
    reload, so the camera stays), and nothing is sent while it hasn't changed."""
    server = DashServer()
    first, second = go.Figure(layout=dict(title="one")), go.Figure(layout=dict(title="two"))
    server._plots["p"] = PlotSnapshot(1, first)  # As add_plot does, without starting the server.
    assert server.newer_snapshot("/plot/p", 1) is None and server.newer_snapshot("/plot/q", 0) is None
    assert server.newer_snapshot("/elsewhere", 0) is None
    server._plots["p"] = PlotSnapshot(2, second)
    assert server.newer_snapshot("/plot/p", 1) == PlotSnapshot(2, second)
    server.remove_plot("p")
    assert server.newer_snapshot("/plot/p", 1) is None and server.snapshot("p") is None


class UpdatedAfterRead(dict[str, PlotSnapshot]):
    """The plot store, with an update (from the GUI thread) landing right after a page's read:
    where a poll that read the figure and the revision apart used to pair the old figure with
    the new revision."""

    def __init__(self, entries: dict[str, PlotSnapshot]) -> None:
        super().__init__(entries)
        self.landing: PlotSnapshot | None = None

    def get(self, key: str, default: Any = None) -> Any:
        value = super().get(key, default)
        if self.landing is not None:
            self[key], self.landing = self.landing, None
        return value


def test_an_update_landing_mid_poll_is_never_paired_with_the_old_figure() -> None:
    server = DashServer()
    old, new = go.Figure(layout=dict(title="old")), go.Figure(layout=dict(title="new"))
    store = server._plots = UpdatedAfterRead({"p": PlotSnapshot(1, old)})
    # A page showing nothing yet polls; revision 2 lands just after the poll's read.
    store.landing = PlotSnapshot(2, new)
    sent = server.newer_snapshot("/plot/p", 0)
    assert sent is not None and sent == PlotSnapshot(1, old)  # The old figure with its own revision.
    assert server.newer_snapshot("/plot/p", sent.revision) == PlotSnapshot(2, new)  # So the next poll brings it.
    # The page load: the same, its figure and stored revision from one snapshot.
    store.landing = PlotSnapshot(3, go.Figure(layout=dict(title="newer")))
    page = server.page("/plot/p")
    graph, revision = page.children[0], page.children[1]
    assert graph.figure is new and revision.data == 2
    newer = server.newer_snapshot("/plot/p", revision.data)
    assert newer is not None and newer.revision == 3


def test_plot_pages_poll_and_updates_bump_the_revision(servers: list[DashServer]) -> None:
    """The page's poll, as its browser sends it: a page showing revision 1 gets revision 2's
    figure; one showing revision 2 gets nothing (204: the page and its camera stay)."""
    server = DashServer()
    servers.append(server)
    server.add_plot("abc", go.Figure())
    server.update_plot("abc", go.Figure(layout=dict(title="newer", uirevision="keep")))
    snapshot = server.snapshot("abc")
    assert snapshot is not None and snapshot.revision == 2
    with urllib.request.urlopen(server.plot_url("abc"), timeout=10) as response:
        assert response.status == 200

    def poll(shown: int) -> tuple[int, bytes]:
        body = {"output": "..plot-graph.figure...plot-revision.data..",
                "outputs": [{"id": "plot-graph", "property": "figure"}, {"id": "plot-revision", "property": "data"}],
                "inputs": [{"id": "plot-poll", "property": "n_intervals", "value": 1}],
                "changedPropIds": ["plot-poll.n_intervals"],
                "state": [{"id": "url", "property": "pathname", "value": "/plot/abc"},
                          {"id": "plot-revision", "property": "data", "value": shown}]}
        request = urllib.request.Request(f"{server.url}/_dash-update-component", json.dumps(body).encode(),
                                         {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()

    status, payload = poll(1)
    reply = json.loads(payload)["response"]
    assert status == 200 and reply["plot-revision"]["data"] == 2
    assert reply["plot-graph"]["figure"]["layout"]["title"]["text"] == "newer"
    assert reply["plot-graph"]["figure"]["layout"]["uirevision"] == "keep"
    assert poll(2)[0] == 204
