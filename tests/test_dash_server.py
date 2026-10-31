import json
import socket
import urllib.request
from typing import Any, Iterator

import plotly.graph_objs as go
import pytest

from helab.utils.dash_server import NOT_FOUND, DashServer, PlotSnapshot


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


@pytest.mark.parametrize("family", [socket.AF_INET, socket.AF_INET6], ids=["ipv4", "ipv6"])
def test_a_port_another_program_holds_on_all_addresses_is_left_to_it(
        servers: list[DashServer], family: socket.AddressFamily) -> None:
    """plots-4: on macOS, SO_REUSEADDR let 127.0.0.1:8050 bind beside another program listening on
    all addresses, which then lost its localhost connections to HeLab. HeLab moves to another port."""
    if family == socket.AF_INET6 and not socket.has_ipv6:
        pytest.skip("no IPv6")
    server = DashServer()
    servers.append(server)
    with socket.socket(family) as other:
        if family == socket.AF_INET6:
            try:
                other.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)  # IPv4 too, as a dual-stack server
                other.bind(("::", 0))
            except OSError:
                pytest.skip("no dual-stack IPv6")
        else:
            other.bind(("0.0.0.0", 0))
        other.listen()
        port = other.getsockname()[1]
        server.HOST_PORT = port
        assert server.start() != port


def test_serves_added_plot(servers: list[DashServer]) -> None:
    server = DashServer()
    servers.append(server)
    server.add_plot("abc", go.Figure())
    with urllib.request.urlopen(server.plot_url("abc"), timeout=10) as response:
        assert response.status == 200
    with urllib.request.urlopen(f"{server.url}/_dash-layout", timeout=10) as response:
        assert response.status == 200


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind((DashServer.HOST_NAME, 0))
        return int(sock.getsockname()[1])


def test_stop_frees_the_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """After stop, the next server (this HeLab's again, or another's) gets the port at once. On a
    port of the test's own: suites running at once share 8050. Pages the server closed leave its
    side of their connections in TIME_WAIT for a minute, which a plain bind refuses (reruns on
    Ubuntu CI); a server binds as DashServer does, with SO_REUSEADDR off Windows."""
    server = DashServer()
    monkeypatch.setattr(server, "HOST_PORT", free_port())
    port = server.start()
    assert port == server.HOST_PORT
    with socket.create_connection((DashServer.HOST_NAME, port), timeout=10) as page:
        page.sendall(b"GET /_dash-layout HTTP/1.0\r\n\r\n")
        while page.recv(65536):
            pass  # Until the server closes it.
    server.stop()
    assert server._server is None
    again = DashServer()
    monkeypatch.setattr(again, "HOST_PORT", port)
    try:
        assert again.start() == port
    finally:
        again.stop()


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
    page = {child.id: child for child in server.page("/plot/p").children}
    graph, revision = page["plot-graph"], page["plot-revision"]
    assert graph.figure is new and revision.data == 2
    newer = server.newer_snapshot("/plot/p", revision.data)
    assert newer is not None and newer.revision == 3


POLL_OUTPUTS = [("plot-graph", "figure"), ("plot-revision", "data"), ("plot-graph", "style"),
                ("plot-closed", "children"), ("plot-poll", "disabled")]


def poll_page(server: DashServer, plot_id: str, shown: int) -> tuple[int, dict[str, Any]]:
    """A plot page's poll, posted as its browser sends it: (HTTP status, the outputs it sets)."""
    body = {"output": ".." + "...".join(f"{name}.{prop}" for name, prop in POLL_OUTPUTS) + "..",
            "outputs": [{"id": name, "property": prop} for name, prop in POLL_OUTPUTS],
            "inputs": [{"id": "plot-poll", "property": "n_intervals", "value": 1}],
            "changedPropIds": ["plot-poll.n_intervals"],
            "state": [{"id": "url", "property": "pathname", "value": f"/plot/{plot_id}"},
                      {"id": "plot-revision", "property": "data", "value": shown}]}
    request = urllib.request.Request(f"{server.url}/_dash-update-component", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = response.read()
        return response.status, json.loads(payload)["response"] if payload else {}


def test_plot_pages_poll_and_updates_bump_the_revision(servers: list[DashServer]) -> None:
    """The page's poll: a page showing revision 1 gets revision 2's figure (and nothing else
    changes); one showing revision 2 gets nothing (204: the page and its camera stay)."""
    server = DashServer()
    servers.append(server)
    server.add_plot("abc", go.Figure())
    server.update_plot("abc", go.Figure(layout=dict(title="newer", uirevision="keep")))
    snapshot = server.snapshot("abc")
    assert snapshot is not None and snapshot.revision == 2
    with urllib.request.urlopen(server.plot_url("abc"), timeout=10) as response:
        assert response.status == 200
    status, reply = poll_page(server, "abc", 1)
    assert status == 200 and reply["plot-revision"]["data"] == 2
    assert reply["plot-graph"]["figure"]["layout"]["title"]["text"] == "newer"
    assert reply["plot-graph"]["figure"]["layout"]["uirevision"] == "keep"
    assert "style" not in reply["plot-graph"] and "plot-closed" not in reply and "plot-poll" not in reply
    assert poll_page(server, "abc", 2)[0] == 204


def test_a_page_still_open_after_its_plot_closes_says_so_and_stops_polling(servers: list[DashServer]) -> None:
    """The plot's dock closed (remove_plot): a browser page still open drops the figure, shows
    the plot-not-found text and turns its poll off; the server keeps no figure for it."""
    server = DashServer()
    servers.append(server)
    server.add_plot("gone", go.Figure(layout=dict(title="last")))
    page = server.page("/plot/gone")
    assert [child.id for child in page.children] == ["plot-closed", "plot-graph", "plot-revision", "plot-poll"]
    server.remove_plot("gone")
    assert server.snapshot("gone") is None
    status, reply = poll_page(server, "gone", 1)
    assert status == 200 and reply["plot-poll"]["disabled"] is True
    assert reply["plot-closed"]["children"] == NOT_FOUND
    assert reply["plot-graph"]["style"] == {"display": "none"} and reply["plot-graph"]["figure"]["data"] == []
    assert "plot-revision" not in reply
    with urllib.request.urlopen(server.plot_url("gone"), timeout=10) as response:  # A new page: not found.
        assert NOT_FOUND in json.dumps(server.page("/plot/gone").to_plotly_json()) and response.status == 200
