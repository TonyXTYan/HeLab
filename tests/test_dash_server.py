import socket
import urllib.request
from typing import Iterator

import plotly.graph_objs as go
import pytest

from helab.utils.dash_server import DashServer


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
