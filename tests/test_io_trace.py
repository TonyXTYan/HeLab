"""The opt-in I/O trace (``HELAB_IO_TRACE=<file>``): every operation a helper makes on a source folder,
one JSON line each, with the request it serves. Off by default: nothing is written then, and helpers
make the same calls and send the same events."""
from __future__ import annotations

import builtins
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable, Iterator

import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before any QApplication: conftest loads the views)
from pytestqt.qtbot import QtBot

from helab import io_helper
from helab.io_helper import list_folder, live_check, load, scan
from helab.utils.folder_cache import store_options
from helab.utils.io_service import IOService
from helab.views.FolderExplorer import FolderExplorer


def write_shots(folder: Path, shots: range, *, age: float = 60.0) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    when = time.time() - age
    for shot in shots:
        (folder / f"d{shot}.txt").write_text("raw\n")
        file = folder / f"d_txy_forc{shot}.txt"
        file.write_text(f"{shot},2,3\n{shot},4,5\n")
        os.utime(file, (when, when))
    os.utime(folder, (when, when))


def lines(trace: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []


def counts(records: list[dict[str, Any]]) -> Counter[tuple[str, str]]:
    return Counter((record["op"], record["reason"]) for record in records)


@pytest.fixture
def trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Tracing on in this process (in-process helper calls) and in helpers it starts."""
    file = tmp_path / "trace" / "io.jsonl"
    file.parent.mkdir()
    monkeypatch.setattr(io_helper, "TRACE", str(file))
    monkeypatch.setattr(io_helper, "_trace_request", {})
    monkeypatch.setattr(io_helper, "_trace_fd", None)
    monkeypatch.setenv("HELAB_IO_TRACE", str(file))
    yield file
    if io_helper._trace_fd is not None:
        os.close(io_helper._trace_fd)


def events_of(call: Callable[[Callable[[dict[str, Any]], None]], None]) -> list[str]:
    """The kinds of event a helper call sends (times and paths differ between runs)."""
    events: list[dict[str, Any]] = []
    call(events.append)
    return [event["kind"] for event in events]


def test_off_unless_the_variable_names_a_file(tmp_path: Path) -> None:
    script = "import helab.io_helper as h; print(h.TRACE)"
    environment = {key: value for key, value in os.environ.items() if key != "HELAB_IO_TRACE"}
    for value, expected in ((None, "None"), ("", "None"), (str(tmp_path / "t.jsonl"), str(tmp_path / "t.jsonl"))):
        if value is not None:
            environment["HELAB_IO_TRACE"] = value
        result = subprocess.run([sys.executable, "-c", script], env=environment, capture_output=True, text=True,
                                timeout=60, check=True)
        assert result.stdout.strip() == expected


def test_off_it_writes_nothing_and_lists_with_the_plain_scandir(tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(io_helper, "TRACE", None)
    monkeypatch.setattr(io_helper, "_trace_fd", None)
    run = tmp_path / "run"
    write_shots(run, range(1, 4))
    with io_helper._scandir(str(run), "listing") as listing:
        assert type(listing) is type(os.scandir(str(run)))
    output = tmp_path / "out"
    output.mkdir()
    cache = store_options()
    list_folder(str(run), lambda _: None, cache)
    scan(str(run), lambda _: None, cache)
    load(str(run), str(output), lambda _: None, cache)
    assert io_helper._trace_fd is None
    assert not list(tmp_path.glob("**/*.jsonl"))


def test_a_listing_scan_and_load_trace_each_source_operation(tmp_path: Path, trace: Path) -> None:
    run = tmp_path / "run"
    write_shots(run, range(1, 4))
    output = tmp_path / "out"
    output.mkdir()
    list_folder(str(run), lambda _: None)
    assert counts(lines(trace)) == {("scandir", "listing"): 1}
    before = len(lines(trace))
    scan(str(run), lambda _: None)
    assert counts(lines(trace)[before:]) == {("scandir", "listing"): 1, ("entry_stat", "fingerprint"): 3,
                                             ("stat", "folder mtime"): 1}
    before = len(lines(trace))
    load(str(run), str(output), lambda _: None)
    records = lines(trace)[before:]
    assert counts(records) == {
        ("scandir", "load: listing"): 1, ("stat", "load: checking"): 3, ("stat", "folder mtime"): 1,
        ("stat", "load: before read"): 3, ("read", "load: read"): 3, ("stat", "load: after read"): 3,
        ("stat", "load: verifying"): 3}
    listing = next(record for record in records if record["op"] == "scandir")
    assert listing["path"] == str(run) and listing["entries"] == 6
    reads = [record for record in records if record["op"] == "read"]
    assert [record["bytes"] for record in reads] == [(run / f"d_txy_forc{shot}.txt").stat().st_size
                                                     for shot in range(1, 4)]
    first = next(record for record in records if record["reason"] == "load: checking")
    info = (run / "d_txy_forc1.txt").stat()
    assert (first["size"], first["mtime_ns"]) == (info.st_size, info.st_mtime_ns)
    assert all(record["pid"] == os.getpid() and record["t"] > 0 for record in records)


def test_tracing_changes_no_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = tmp_path / "run"
    write_shots(run, range(1, 4))
    (run / "sub").mkdir()

    def calls() -> list[list[str]]:
        output = tmp_path / f"out-{time.monotonic_ns()}"
        output.mkdir()
        return [events_of(lambda send: list_folder(str(run), send)), events_of(lambda send: scan(str(run), send)),
                events_of(lambda send: load(str(run), str(output), send))]
    monkeypatch.setattr(io_helper, "TRACE", None)
    plain = calls()
    monkeypatch.setattr(io_helper, "TRACE", str(tmp_path / "io.jsonl"))
    monkeypatch.setattr(io_helper, "_trace_fd", None)
    try:
        assert calls() == plain
    finally:
        if io_helper._trace_fd is not None:
            os.close(io_helper._trace_fd)
    assert lines(tmp_path / "io.jsonl")


def test_a_live_check_traces_its_folder_stat_samples_and_tail_reads(tmp_path: Path, trace: Path) -> None:
    run = tmp_path / "run"
    write_shots(run, range(1, 4))
    memory = [[shot, (info := (run / f"d_txy_forc{shot}.txt").stat()).st_size, info.st_mtime_ns]
              for shot in (1, 2)]
    info = (run / "d_txy_forc3.txt").stat()
    seen = [[3, info.st_size, info.st_mtime_ns]]
    output = tmp_path / "out"
    output.mkdir()
    live_check(str(run), str(output), lambda _: None, memory, seen=seen)
    found = counts(lines(trace))
    assert found[("stat", "live: folder")] == 1 and found[("scandir", "live: listing")] == 1
    assert found[("stat", "live: sample")] == 2 and found[("stat", "live: new file")] == 1
    # The new file's last row is checked before it is read: its tail is opened and read.
    assert found[("stat", "live: last row")] == 1 and found[("read_tail", "live: last row")] == 1
    assert found[("read", "live: read")] == 1
    # The data root's marker (the test folder's) names the folder.
    assert found[("marker_read", "live: identity")] >= 1
    # Held shots are never read.
    assert not any(record["op"] == "read" and record["path"].endswith(("forc1.txt", "forc2.txt"))
                   for record in lines(trace))


def wait_idle(qtbot: QtBot, service: IOService, timeout: int = 20000) -> None:
    cache = service.folder_cache
    qtbot.waitUntil(lambda: not service.pending and not service.active and not service.retired
                    and (cache is None or not cache._deliveries), timeout=timeout)


def test_helpers_trace_their_request_and_the_tabs_they_work_for(
    qtbot: QtBot, tmp_path: Path, trace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    share = tmp_path / "share"
    write_shots(share / "run", range(1, 3))
    service = IOService()
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    explorer = FolderExplorer(str(share), str(share), str(share), [0, 4, 5])
    qtbot.addWidget(explorer)
    qtbot.waitUntil(lambda: explorer.model.root is not None and explorer.model.root.loaded, timeout=20000)
    wait_idle(qtbot, service)
    records = [record for record in lines(trace) if record["pid"] != os.getpid()]
    started = next(record for record in records if record["op"] == "request" and record["request"] == "list")
    assert started["path"] == str(share) and started["tabs"] == [explorer.model.owner]
    assert started["lane"] == "foreground" and started["attempt"] == 1
    listing = next(record for record in records if record["op"] == "scandir" and record["pid"] == started["pid"])
    assert listing["request"] == "list" and listing["tabs"] == [explorer.model.owner]
    assert any(record["op"] == "request_end" and record["pid"] == started["pid"] for record in records)
    explorer.close_cleanup()
    service.shutdown()


class SourceCalls:
    """Calls the GUI process makes on paths inside ``root`` (what Python can see: os, open)."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root, self.calls = os.path.normcase(str(root)), list[tuple[str, str]]()
        for module, names in ((os, ("stat", "lstat", "scandir", "listdir", "open")),
                              (os.path, ("exists", "isdir", "isfile", "getmtime", "getsize")),
                              (builtins, ("open",))):
            for name in names:
                monkeypatch.setattr(module, name, self.recording(name, getattr(module, name)))

    def recording(self, name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def call(target: Any = ".", *args: Any, **kwargs: Any) -> Any:
            if isinstance(target, (str, os.PathLike)) and os.path.normcase(os.fspath(target)).startswith(self.root):
                self.calls.append((name, os.fspath(target)))
            return real(target, *args, **kwargs)
        return call


def test_the_gui_process_never_touches_source_folders(
    qtbot: QtBot, tmp_path: Path, trace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Browsing, expanding, selecting, loading and Refresh: every source operation is a helper's.
    (Native calls inside Qt are out of Python's sight; the GUI process makes none on purpose.)"""
    share = tmp_path / "share"
    write_shots(share / "run a", range(1, 4))
    write_shots(share / "more" / "run b", range(1, 3))
    service = IOService()
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    gui = SourceCalls(share, monkeypatch)
    explorer = FolderExplorer(str(share), str(share), str(share), [0, 4, 5])
    qtbot.addWidget(explorer)
    explorer.resize(600, 400)
    explorer.show()
    model = explorer.model
    qtbot.waitUntil(lambda: str(share / "more") in model.nodes, timeout=20000)
    explorer.tree.expand(model.path_index(str(share / "more")))
    qtbot.waitUntil(lambda: str(share / "more" / "run b") in model.nodes, timeout=20000)
    run = str(share / "run a")
    explorer.tree.setCurrentIndex(model.path_index(run))
    explorer.load_to_ram_cache(run, dwell=False, explicit=True)
    qtbot.waitUntil(lambda: explorer.folder_opened_path == run and explorer.folder_opened_data is not None,
                    timeout=20000)
    wait_idle(qtbot, service)
    explorer.refresh()
    wait_idle(qtbot, service)
    assert gui.calls == []
    helpers = [record for record in lines(trace) if record["pid"] != os.getpid()]
    assert {(record["request"], record["op"]) for record in helpers} >= {
        ("list", "scandir"), ("details", "scandir"), ("load", "read"), ("icons", "icon")}
    assert all(record["path"].startswith(str(share)) for record in helpers if record["op"] in ("scandir", "read"))
    explorer.close_cleanup()
    service.shutdown()
