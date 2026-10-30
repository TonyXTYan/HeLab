"""Q33.7: the settle time is a setting (Settings › General, ``settle_seconds``, 2 to 60 s, default 5 s). The app
sends it with every request (``IOService.settle_seconds`` → ``settle_seconds``), and the helper applies it before
any operation (``fingerprints.configure_settle``); without one (``helab convert``, an older HeLab's request) the
helper keeps its default, and HELAB_SETTLE_SECONDS, when set, wins (tests)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable

import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before any QApplication: the main window)
from PyQt6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from helab import io_helper
from helab.io_ops import fingerprints, infra
from helab.utils.io_service import FOREGROUND, IORequest, IOService
from helab.utils.settings_defaults import SETTLE_SECONDS_SETTING, setting_default
from helab.views.HelabMainWindow import HelabMainWindow
from helab.views.SettingsDialog import SettingsDialog, read_settle_seconds
from tests.test_helper_dispatch import HANDLERS, ROUTES, helper_state, send  # noqa: F401  (a fixture)


@pytest.fixture
def from_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """As in the app: HELAB_SETTLE_SECONDS unset, so a request's settle time applies (restored after)."""
    monkeypatch.setattr(fingerprints, "_SETTLE_OVERRIDE", None)
    monkeypatch.setattr(fingerprints, "SETTLE_SECONDS", fingerprints.DEFAULT_SETTLE_SECONDS)
    monkeypatch.setattr(fingerprints, "RACY_SECONDS", 2.0)


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, float, float]]:
    """Every handler replaced by a stub noting the settle time (and margin) as it runs: what its
    operation's reads use, since they read ``fingerprints``' module values when they run."""
    made: list[tuple[str, float, float]] = []

    def stub(name: str) -> Callable[..., None]:
        def record(*args: Any, **kwargs: Any) -> None:
            made.append((name, fingerprints.SETTLE_SECONDS, fingerprints.RACY_SECONDS))
        return record

    for name in HANDLERS:
        monkeypatch.setattr(io_helper, name, stub(name))
    return made


@pytest.mark.usefixtures("from_requests")
@pytest.mark.parametrize("request_, handler", [(route[0], route[1]) for route in ROUTES],
                         ids=[f"{route[0]['operation']}-{route[1]}-{n}" for n, route in enumerate(ROUTES)])
def test_every_operation_runs_with_the_requests_settle_time(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], seen: list[tuple[str, float, float]],
        request_: dict[str, Any], handler: str) -> None:
    """Browsing, scans, loads, Live checks and saves, cached reads, conversions and every other operation."""
    send(monkeypatch, capsys, {**request_, "settle_seconds": 12.5})
    assert seen == [(handler, 12.5, 2.0)]


@pytest.mark.usefixtures("from_requests")
@pytest.mark.parametrize("given, used", [
    (None, 5.0), ("12", 12.0), ("x", 5.0), (float("nan"), 5.0), (True, 5.0), (0.5, 2.0), (600, 60.0), (2, 2.0),
], ids=["absent", "text number", "not a number", "nan", "bool", "below 2 s", "above 60 s", "the least"])
def test_a_missing_or_odd_settle_time_falls_back_or_takes_the_nearest_limit(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], seen: list[tuple[str, float, float]],
        given: object, used: float) -> None:
    request: dict[str, Any] = {"operation": "details", "path": str(ROUTES[0][0]["path"])}
    if given is not None:
        request["settle_seconds"] = given
    send(monkeypatch, capsys, request)
    assert seen == [("scan", used, 2.0)]


def test_helab_settle_seconds_wins_over_the_request(monkeypatch: pytest.MonkeyPatch,
                                                    capsys: pytest.CaptureFixture[str],
                                                    seen: list[tuple[str, float, float]]) -> None:
    assert os.environ["HELAB_SETTLE_SECONDS"] == "0" and fingerprints._SETTLE_OVERRIDE == "0"  # (conftest)
    send(monkeypatch, capsys, {"operation": "details", "path": str(ROUTES[0][0]["path"]), "settle_seconds": 30})
    assert seen == [("scan", 0.0, 0.0)]


@pytest.mark.usefixtures("from_requests")
def test_the_io_trace_notes_the_settle_time_on_every_line(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path,
        seen: list[tuple[str, float, float]]) -> None:
    send(monkeypatch, capsys, {"operation": "details", "path": str(ROUTES[0][0]["path"]), "settle_seconds": 7,
                               "trace": {"dir": str(tmp_path), "owner": "tab"}})
    [trace] = tmp_path.glob("*.jsonl")
    lines = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert [line["op"] for line in lines] == ["request", "request_end"]
    assert all(line["settle"] == 7.0 for line in lines)


def test_the_service_sends_its_settle_time_with_every_request(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    """``settle_seconds`` as the request's attempt started; not sent while the service has none."""
    service = IOService()
    service.timer.stop()
    started = subprocess.Popen
    echo = ("import json, sys; request = json.loads(sys.stdin.readline()); "
            "print(json.dumps({'kind': 'echo', 'settle': request.get('settle_seconds', 'absent')})); "
            "print(json.dumps({'kind': 'done'}))")

    def echoing(command: list[str], **kwargs: Any) -> subprocess.Popen[str]:
        return started([sys.executable, "-c", echo], **kwargs)

    monkeypatch.setattr("helab.utils.io_service.subprocess.Popen", echoing)
    sent: list[object] = []
    try:
        for value in (None, 9.5):
            service.settle_seconds = value
            for operation in ("list", "load", "convert", "cached"):
                request = IORequest("tab", 0, "/data", operation, {}, 60.0)
                service.pending.append(request)
                service._start(request, FOREGROUND)  # (Its helper runs on a daemon thread.)
                while True:
                    _, event = service.messages.get(timeout=30)
                    if event["kind"] == "echo":
                        sent.append(event["settle"])
                    if event["kind"] == "exit":
                        break
    finally:
        service.shutdown()
    assert sent == ["absent"] * 4 + [9.5] * 4


@pytest.mark.no_auto_data_root
@pytest.mark.parametrize("settle, unsettled", [(None, 0), (5.0, 0), (60.0, 1)],
                         ids=["absent: default 5 s", "5 s", "60 s"])
def test_a_real_helper_leaves_a_file_newer_than_the_settle_time(tmp_path: Path, settle: float | None,
                                                               unsettled: int) -> None:
    """A real helper process, as the app starts it, without HELAB_SETTLE_SECONDS: a TXY file modified 10 s
    ago is settled at 5 s and still being written at 60 s."""
    folder = tmp_path / "run"
    folder.mkdir()
    for shot, age in ((1, 120), (2, 10)):
        path = folder / f"d_txy_forc{shot}.txt"
        path.write_text("1,2,3\n", encoding="utf-8")
        then = time.time() - age
        os.utime(path, (then, then))
    request: dict[str, Any] = {"operation": "details", "path": str(folder), "output": str(tmp_path)}
    if settle is not None:
        request["settle_seconds"] = settle
    env = {key: value for key, value in os.environ.items() if key != "HELAB_SETTLE_SECONDS"}
    done = subprocess.run([sys.executable, "-m", "helab.io_helper"], input=json.dumps(request) + "\n",
                          capture_output=True, text=True, env=env, timeout=60, check=True)
    events = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
    [status] = [event for event in events if event["kind"] == "status"]
    assert status["unsettled"] == unsettled and events[-1]["kind"] == "done"


def test_the_setting_reads_within_its_limits_and_its_default_is_the_helpers(tmp_path: Path) -> None:
    assert setting_default(SETTLE_SECONDS_SETTING) == fingerprints.DEFAULT_SETTLE_SECONDS == 5.0
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    assert read_settle_seconds(settings) == 5.0
    for saved, read in (("8.5", 8.5), ("1", 2.0), ("90", 60.0), ("soon", 5.0)):
        settings.setValue(SETTLE_SECONDS_SETTING, saved)
        assert read_settle_seconds(settings) == read


def test_settings_general_edits_it_beside_lives_interval(qtbot: QtBot, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)
    spin = dialog.settle_spin
    assert (spin.minimum(), spin.maximum(), spin.value()) == (2.0, 60.0, 5.0)
    assert spin.objectName() == "settle_seconds" and spin.accessibleName() == "Settle time"
    assert "every read" in spin.toolTip() and "conversions" in spin.toolTip()
    form = spin.parentWidget()
    assert form is dialog.live_interval_spin.parentWidget()
    spin.setValue(12.5)
    dialog._write_settings()
    assert read_settle_seconds(settings) == 12.5
    again = SettingsDialog(settings=settings)
    qtbot.addWidget(again)
    assert again.settle_spin.value() == 12.5


def test_the_main_window_gives_the_service_the_setting(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from helab.utils.io_service import get_io_service
    service = get_io_service()
    monkeypatch.setattr(service, "settle_seconds", None)  # (The app-wide service: restored after.)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue(SETTLE_SECONDS_SETTING, 20)
    HelabMainWindow._apply_live_settings(settings)  # At start and after Settings.
    assert service.settle_seconds == 20.0
