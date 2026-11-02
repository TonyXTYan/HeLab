"""A local HTTP test with a fake engine and private settings; never contacts a camera."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest


def test_a_foreign_origin_cannot_persist_labcam_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from http.server import ThreadingHTTPServer

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "side_projects/labcam"))
    from labcam import config
    from labcam.server import RingHandler, make_handler

    local = tmp_path / "config.local.json"
    monkeypatch.setattr(config, "LOCAL", local)
    settings = config.Config("", False, 5, 10, 80, 3, {})
    engine = SimpleNamespace(config=settings, power_mode="auto")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(engine, RingHandler()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        client.request("POST", "/api/settings", body='{"power_mode":"low"}', headers={
            "Origin": "https://untrusted.invalid", "Content-Type": "text/plain", "Connection": "close"})
        response = client.getresponse()
        print("status", response.status, "response", response.read(),
              "settings", json.loads(local.read_text()) if local.exists() else {})
        assert response.status in (401, 403), "anonymous foreign-origin request changed persistent settings"
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(2)
