"""The I/O trace (Help › Record I/O trace, this session): every operation a helper makes on a source
folder, one JSON line each, with the request it serves, in HeLab's temp folder. Off by default: nothing
is written then, and helpers make the same calls and send the same events. Tests turn it on for helpers
with the test seam ``HELAB_TEST_IO_TRACE=<file>`` (or ``IOService.trace_file``, as the menu does)."""
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
import uuid

import numpy as np
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


# Bookkeeping lines, not operations on a source folder.
BOOKKEEPING = ("request", "request_end", "mounts", "volume_id")


def counts(records: list[dict[str, Any]]) -> Counter[tuple[str, str]]:
    return Counter((record["op"], record["reason"]) for record in records if record["op"] not in BOOKKEEPING)


@pytest.fixture
def trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Tracing on in this process (in-process helper calls) and in helpers it starts."""
    file = tmp_path / "trace" / "io.jsonl"
    file.parent.mkdir()
    monkeypatch.setattr(io_helper, "TRACE", str(file))
    monkeypatch.setattr(io_helper, "_trace_request", {})
    monkeypatch.setattr(io_helper, "_trace_fd", None)
    monkeypatch.setenv("HELAB_TEST_IO_TRACE", str(file))
    yield file
    if io_helper._trace_fd is not None:
        os.close(io_helper._trace_fd)


# Event fields that differ between two runs of the same call: times, and each run's output folder.
VOLATILE = {"scanned_at", "loaded_at", "listed_at", "modified_observed_at", "saved_at", "snapshot_at", "live_seconds",
            "artifact", "scan_operation_id", "revision"}


def stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: stable(item) for key, item in value.items() if key not in VOLATILE}
    if isinstance(value, list):
        return [stable(item) for item in value]
    return value


def events_of(call: Callable[[Callable[[dict[str, Any]], None]], None]) -> list[Any]:
    """The events a helper call sends, without the fields that differ between runs."""
    events: list[dict[str, Any]] = []
    call(events.append)
    return [stable(event) for event in events]


def test_off_unless_the_test_seam_names_a_file(tmp_path: Path) -> None:
    """No user-facing variable: only the test seam turns a helper's trace on by itself (the old
    HELAB_IO_TRACE does nothing)."""
    script = "import helab.io_helper as h; print(h.TRACE)"
    environment = {key: value for key, value in os.environ.items()
                   if key not in ("HELAB_TEST_IO_TRACE", "HELAB_IO_TRACE")}
    for name, value, expected in (("", None, "None"), ("HELAB_TEST_IO_TRACE", "", "None"),
                                  ("HELAB_IO_TRACE", str(tmp_path / "t.jsonl"), "None"),
                                  ("HELAB_TEST_IO_TRACE", str(tmp_path / "t.jsonl"), str(tmp_path / "t.jsonl"))):
        run_environment = dict(environment, **({name: value} if name and value is not None else {}))
        result = subprocess.run([sys.executable, "-c", script], env=run_environment, capture_output=True,
                                text=True, timeout=60, check=True)
        assert result.stdout.strip() == expected


def test_a_helper_traces_to_the_file_its_request_names(tmp_path: Path) -> None:
    """As the app sends it while the trace is on (``IOService.trace_file``); nothing on stdout but events."""
    run = tmp_path / "run"
    write_shots(run, range(1, 3))
    environment = {key: value for key, value in os.environ.items() if key != "HELAB_TEST_IO_TRACE"}
    for traced in (False, True):
        file = tmp_path / f"trace-{traced}.jsonl"
        request: dict[str, Any] = {"operation": "list", "path": str(run)}
        if traced:
            request["trace"] = {"file": str(file), "owner": "o", "tabs": ["tab"], "lane": "foreground", "attempt": 1}
        result = subprocess.run([sys.executable, "-m", "helab.io_helper"], input=json.dumps(request) + "\n",
                                env=environment, capture_output=True, text=True, timeout=60, check=True)
        assert all(json.loads(line)["kind"] for line in result.stdout.splitlines())
        assert file.exists() is traced
    records = lines(tmp_path / "trace-True.jsonl")
    assert {record["op"] for record in records} >= {"request", "scandir", "request_end"}
    assert all(record["tabs"] == ["tab"] and "file" not in record for record in records)


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
    (run / "sub").mkdir()
    list_folder(str(run), lambda _: None)
    assert counts(lines(trace)) == {("scandir", "listing"): 1}
    # Names only; the entry that isn't a data file is asked is_dir (the listing's file type answers).
    assert lines(trace)[0]["entries"] == 7 and lines(trace)[0]["is_dir"] == 1
    before = len(lines(trace))
    scan(str(run), lambda _: None)
    assert counts(lines(trace)[before:]) == {("scandir", "listing"): 1, ("entry_stat", "fingerprint"): 3,
                                             ("lstat", "subfolder date"): 1, ("stat", "folder mtime"): 1}
    listing = next(record for record in lines(trace)[before:] if record["op"] == "scandir")
    assert listing["is_dir"] == 7  # (Every entry, in a scan.)
    before = len(lines(trace))
    load(str(run), str(output), lambda _: None)
    records = lines(trace)[before:]
    assert counts(records) == {
        ("scandir", "load: listing"): 1, ("entry_stat", "load: checking"): 3, ("stat", "folder mtime"): 1,
        ("stat", "load: before read"): 3, ("read", "load: read"): 3, ("stat", "load: after read"): 3,
        ("stat", "load: verifying"): 3}
    listing = next(record for record in records if record["op"] == "scandir")
    assert listing["path"] == str(run) and listing["entries"] == 7
    reads = [record for record in records if record["op"] == "read"]
    assert [record["bytes"] for record in reads] == [(run / f"d_txy_forc{shot}.txt").stat().st_size
                                                     for shot in range(1, 4)]
    first = next(record for record in records if record["reason"] == "load: checking")
    info = (run / "d_txy_forc1.txt").stat()
    assert (first["size"], first["mtime_ns"]) == (info.st_size, info.st_mtime_ns)
    assert all(record["pid"] == os.getpid() and record["t"] > 0 for record in records)


def test_tracing_changes_no_event_and_no_source_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A listing, a scan, a load and a Live check, untraced and traced: the same events (times aside)
    and the same calls on the folder, in the same order."""
    run = tmp_path / "run"
    write_shots(run, range(1, 4))
    (run / "sub").mkdir()
    memory = [[shot, (info := (run / f"d_txy_forc{shot}.txt").stat()).st_size, info.st_mtime_ns] for shot in (1, 2)]
    info = (run / "d_txy_forc3.txt").stat()
    seen = [[3, info.st_size, info.st_mtime_ns]]
    source = SourceCalls(run, monkeypatch)

    def calls() -> tuple[list[list[Any]], list[tuple[str, str]]]:
        source.calls.clear()
        output = tmp_path / f"out-{time.monotonic_ns()}"
        output.mkdir()
        events = [events_of(lambda send: list_folder(str(run), send)), events_of(lambda send: scan(str(run), send)),
                  events_of(lambda send: load(str(run), str(output), send)),
                  events_of(lambda send: live_check(str(run), str(output), send, memory, seen=seen))]
        return events, list(source.calls)
    monkeypatch.setattr(io_helper, "TRACE", None)
    plain = calls()
    monkeypatch.setattr(io_helper, "TRACE", str(tmp_path / "io.jsonl"))
    monkeypatch.setattr(io_helper, "_trace_fd", None)
    try:
        traced = calls()
    finally:
        if io_helper._trace_fd is not None:
            os.close(io_helper._trace_fd)
    assert traced[0] == plain[0]
    assert traced[1] == plain[1] and plain[1]
    assert lines(tmp_path / "io.jsonl")


def test_a_live_check_traces_its_folder_stat_samples_and_reads(tmp_path: Path, trace: Path) -> None:
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
    # The new file is opened once: read, then its last row checked on the bytes read.
    assert found[("read", "live: read")] == 1 and not any(op == "read_tail" for op, _ in found)
    # The data root's marker (the test folder's) names the folder: the folder's own is missing, the
    # root's is opened, fstat'ed and read.
    assert found[("marker_open", "live: identity")] == 2 and found[("marker_fstat", "live: identity")] == 1
    assert found[("marker_read", "live: identity")] == 1
    marker = next(record for record in lines(trace) if record["op"] == "marker_read")
    assert marker["bytes"] == (tmp_path / ".helab-root").stat().st_size
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
    service.trace_file = str(trace)  # (As Help › Record I/O trace does: the app names the tabs.)
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


def test_read_marker_behaves_the_same_with_a_trace_callback(tmp_path: Path) -> None:
    from helab.utils import data_roots
    good, bad, folder_named, missing = (tmp_path / name for name in ("good", "bad", "dir", "missing"))
    for path in (good, bad, folder_named, missing):
        path.mkdir()
    (good / data_roots.MARKER_NAME).write_text(json.dumps({"helab": "root", "version": 1, "uuid": str(uuid.uuid4()),
                                                           "label": "good", "created_at": "2026-10-19T00:00:00Z"}))
    (bad / data_roots.MARKER_NAME).write_text("not json")
    (folder_named / data_roots.MARKER_NAME).mkdir()

    def outcome(folder: Path, **kwargs: Any) -> object:
        try:
            return data_roots.read_marker(str(folder), **kwargs)
        except (OSError, ValueError) as exc:
            return (type(exc), str(exc))
    # A .helab-root that is a folder: POSIX opens it and fstat finds no regular file; Windows can't
    # open a folder as a file at all (PermissionError), so no step succeeds there.
    folder_steps = [] if sys.platform == "win32" else ["open", "fstat"]
    for folder, expected in ((good, ["open", "fstat", "read"]), (bad, ["open", "fstat", "read"]),
                             (folder_named, folder_steps), (missing, [])):
        steps: list[tuple[str, dict[str, object]]] = []
        assert outcome(folder, trace=lambda name, fields: steps.append((name, fields))) == outcome(folder)
        assert [name for name, _ in steps] == expected
    steps = []
    data_roots.read_marker(str(good), trace=lambda name, fields: steps.append((name, fields)))
    size = (good / data_roots.MARKER_NAME).stat().st_size
    assert steps[1][1]["size"] == size and steps[2][1] == {"bytes": size}


def test_hiding_a_marker_is_traced(tmp_path: Path, trace: Path) -> None:
    marker = tmp_path / ".helab-root"
    marker.write_text("{}")
    io_helper._hide(str(marker))
    expected = {"darwin": ["stat", "chflags"], "win32": ["get_attributes", "set_attributes"]}.get(sys.platform, [])
    assert [record["op"] for record in lines(trace)] == expected


def test_a_changed_mount_table_makes_at_most_one_verification_until_a_listing_reports_another(
    qtbot: QtBot, tmp_path: Path, trace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With real helpers: a listing that reports a mount table the next check doesn't see (a disk
    that came and went) makes one volume check and one marker check, not a loop of them."""
    from helab.utils.cache_paths import current_mounts
    from helab.utils.folder_cache import FolderCache
    from helab.utils.io_service import IORequest
    service = IOService()
    cache = FolderCache(service)
    monkeypatch.setattr(cache, "VERIFY_MIN_SECONDS", 0.0)
    real = sorted([[mount.path, mount.source] for mount in current_mounts()])
    listing = IORequest("tab", 0, str(tmp_path), "list", {}, 60.0)

    def seen(mounts: list[list[str]]) -> None:
        service.resultReady.emit(listing, {"kind": "mounts_seen", "mounts": mounts})

    def started(operation: str) -> int:
        return sum(record["op"] == "request" and record["request"] == operation for record in lines(trace))
    try:
        seen(sorted([*real, ["/Volumes/HeLabTestGone", "//nobody@nowhere/gone"]]))
        qtbot.waitUntil(lambda: started("roots_verify") == 1 and not service.active and not service.pending,
                        timeout=20000)
        qtbot.wait(1500)  # (A loop would have started more by now.)
        assert (started("volumes_verify"), started("roots_verify")) == (1, 1)
        # The marker check used the volume check's IDs: it asked for none itself.
        verify = [record for record in lines(trace) if record.get("request") == "roots_verify"]
        assert not any(record["op"] == "volume_id" for record in verify)
        assert any(record["op"] == "marker_read" for record in verify)
        seen(real)  # The table the check saw: nothing to verify.
        qtbot.wait(500)
        assert (started("volumes_verify"), started("roots_verify")) == (1, 1)
        seen(sorted([*real, ["/Volumes/HeLabTestOther", "//nobody@nowhere/other"]]))
        qtbot.waitUntil(lambda: started("roots_verify") == 2 and not service.active and not service.pending,
                        timeout=20000)
        qtbot.wait(1000)
        assert (started("volumes_verify"), started("roots_verify")) == (2, 2)
    finally:
        service.shutdown()


def test_a_saved_load_stats_each_file_read_four_times_and_once_more_only_after_rereads(
    tmp_path: Path, trace: Path,
) -> None:
    """The fingerprint comes with the listing; each file read is statted before and after the read,
    and all once more at the end. The cache save checks them again only after reading files for it."""
    run = tmp_path / "run"
    write_shots(run, range(1, 4))
    cache = store_options()
    output = tmp_path / "out"
    output.mkdir()
    load(str(run), str(output), lambda _: None, cache)
    assert counts(lines(trace)) == {
        ("scandir", "load: listing"): 1, ("entry_stat", "load: checking"): 3, ("stat", "folder mtime"): 1,
        ("stat", "load: before read"): 3, ("read", "load: read"): 3, ("stat", "load: after read"): 3,
        ("stat", "load: verifying"): 3}
    # Shot 4 is new and shots 1-3 are held in RAM but aren't in this new cache: they're read for
    # the cache after ``loaded``, and the files are checked again before saving.
    write_shots(run, range(4, 5))
    (tmp_path / "cache-b").mkdir()
    memory = [[shot, (info := (run / f"d_txy_forc{shot}.txt").stat()).st_size, info.st_mtime_ns] for shot in (1, 2, 3)]
    before = len(lines(trace))
    load(str(run), str(output), lambda _: None, {**cache, "directory": str(tmp_path / "cache-b")}, memory)
    found = counts(lines(trace)[before:])
    assert found[("read", "load: read")] == 1 and found[("read", "cache save: read")] == 3
    assert found[("stat", "load: verifying")] == 4 and found[("stat", "cache save: verifying")] == 4


def test_a_changed_cached_folder_is_listed_once_by_its_load(
    qtbot: QtBot, tmp_path: Path, trace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting a cached folder whose files changed: its load lists and fingerprints it, and the row
    takes that status. It used to be listed again for the tree, and then scanned for details."""
    share = tmp_path / "share"
    run = share / "run"
    write_shots(run, range(1, 4))
    cache = store_options()
    output = tmp_path / "out"
    output.mkdir()
    list_folder(str(share), lambda _: None, cache)
    scan(str(run), lambda _: None, cache)
    load(str(run), str(output), lambda _: None, cache)
    write_shots(run, range(4, 5))
    os.utime(run)  # A new file changes the folder's mtime (``write_shots`` ages it).
    service = IOService()
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    explorer = FolderExplorer(str(share), str(share), str(share), [0, 4, 5])
    qtbot.addWidget(explorer)
    model = explorer.model
    qtbot.waitUntil(lambda: str(run) in model.nodes and model.nodes[str(run)].cached_report, timeout=20000)
    wait_idle(qtbot, service)
    before = len(lines(trace))
    explorer.tree.setCurrentIndex(model.path_index(str(run)))
    explorer.load_to_ram_cache(str(run))
    qtbot.waitUntil(lambda: explorer.folder_opened_path == str(run) and len(explorer.folder_opened_data or {}) == 4,
                    timeout=20000)
    wait_idle(qtbot, service)
    qtbot.wait(300)
    wait_idle(qtbot, service)
    listings = [record for record in lines(trace)[before:] if record["op"] == "scandir" and record["path"] == str(run)]
    assert [record["request"] for record in listings] == ["load"]
    node = model.nodes[str(run)]
    assert not node.cached_report and node.txy_count == 4 and node.signature and node.loaded
    explorer.close_cleanup()
    service.shutdown()


def test_a_writer_stalled_longer_than_the_settle_age_is_read_as_it_is(tmp_path: Path, trace: Path) -> None:
    """Settle age only, by Tony's decision: a TXY write never takes longer, so a file unmodified for
    the settle age is read as it is, without looking at its content. If a writer ever stalls longer
    mid-row, the load shows (and caches) what is there, its partial row dropped as unreadable
    (problematic); the finished file's new size makes the next check read it again."""
    run = tmp_path / "run"
    write_shots(run, range(1, 3))
    stalled = run / "d_txy_forc3.txt"
    stalled.write_text("3,2,3\n3,4")
    when = time.time() - 8
    os.utime(stalled, (when, when))
    cache = store_options()
    output = tmp_path / "out"
    output.mkdir()
    events: list[dict[str, Any]] = []
    load(str(run), str(output), events.append, cache)
    loaded = next(event for event in events if event["kind"] == "loaded")
    assert [event["shot"] for event in events if event["kind"] == "shot"] == [1, 2, 3]
    assert loaded["files"] == 3 and loaded["unsettled_files"] == 0 and loaded["problematic"] == [3]
    assert any(record["op"] == "read" and record["path"] == str(stalled) for record in lines(trace))
    stalled.write_text("3,2,3\n3,4,5\n")  # The writer finished.
    os.utime(stalled, (when, when))
    events = []
    load(str(run), str(output), events.append, cache)
    loaded = next(event for event in events if event["kind"] == "loaded")
    # Shots 1 and 2 come from the disk cache; the changed file is read again, whole now.
    assert loaded["files"] == 3 and loaded["load_counts"]["modified_loaded"] == 1 and not loaded["problematic"]


def memory_check_of(loaded: dict[str, Any]) -> dict[str, Any]:
    """What ``FolderCache.submit`` sends with a load of data held in RAM."""
    return {key: loaded.get(key) for key in ("listed_at", "names", "identity", "fingerprint", "problematic",
                                             "data_root")} | {"signature": loaded["signature"],
                                                              "unsettled": loaded["unsettled_files"]}


def test_data_held_in_ram_without_a_disk_cache_gets_the_quick_check(tmp_path: Path, trace: Path) -> None:
    """Re-checking unchanged RAM-only data: one folder stat and the check level's sample, no listing
    (it used to list the folder and stat every file twice). A new file, unsettled files, another
    location, a changed data root or Retry/Refresh (``full_check``) check every file."""
    run = tmp_path / "run"
    write_shots(run, range(1, 21))
    output = tmp_path / "out"
    output.mkdir()
    events: list[dict[str, Any]] = []
    load(str(run), str(output), events.append)  # No disk cache.
    loaded = next(event for event in events if event["kind"] == "loaded")
    assert loaded["names"] == [f"d_txy_forc{shot}.txt" for shot in range(1, 21)] and loaded["identity"]
    memory = [list(entry) for entry in loaded["fingerprint"]]
    check = memory_check_of(loaded)

    def again(**kwargs: Any) -> tuple[dict[str, Any], Counter[tuple[str, str]]]:
        before = len(lines(trace))
        found: list[dict[str, Any]] = []
        load(str(run), str(output), found.append, None, memory, loaded["signature"],
             **{"memory_check": check, **kwargs})
        return next(event for event in found if event["kind"] == "loaded"), counts(lines(trace)[before:])
    result, found = again()
    assert result["unchanged"] and result["memory_shots"] == list(range(1, 21))
    assert found == {("stat", "memory check: folder"): 1, ("stat", "memory check: sample"): 5}
    assert result["listed_at"] == loaded["listed_at"] and result["names"] == loaded["names"]
    for changed in ({**check, "unsettled": 1}, {**check, "identity": "location:elsewhere|/run"},
                    {**check, "data_root": {"path": str(tmp_path), "uuid": str(uuid.uuid4())}}):
        before = len(lines(trace))
        load(str(run), str(output), lambda _: None, None, memory, loaded["signature"], memory_check=changed)
        assert counts(lines(trace)[before:])[("scandir", "load: listing")] == 1
    result, found = again(full_check=True)
    assert not result.get("unchanged") and found[("scandir", "load: listing")] == 1
    write_shots(run, range(21, 22))
    os.utime(run)  # (A new file changes the folder's mtime.)
    result, found = again()
    assert not result.get("unchanged") and result["load_counts"]["read"] == 1


def test_folder_cache_sends_the_ram_quick_check_only_for_checked_data(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from helab.utils.folder_cache import Dataset, FolderCache
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    cache = FolderCache(service)
    path = str(tmp_path / "run")
    metadata = {"fingerprint": [[1, 6, 7]], "listed_at": 10.0, "names": ["d_txy_forc1.txt"],
                "identity": "location:x|/run", "unsettled_files": 0, "problematic": []}
    try:
        cache.datasets[(path, "sig", 0)] = Dataset(path, "sig", {1: np.zeros((1, 3))}, metadata, 0)
        assert cache.submit("tab", 0, path, "load", {"signature": "sig"})
        (request,) = service.pending
        assert request.payload["memory_check"]["names"] == ["d_txy_forc1.txt"]
        assert request.payload["memory_check"]["signature"] == "sig"
        cache.cancel("tab")
        # Read from the disk cache and not checked yet: no quick check from it.
        cache.datasets[(path, "sig", 0)].metadata["verified"] = False
        assert cache.submit("tab", 1, path, "load", {"signature": "sig"})
        assert "memory_check" not in service.pending[-1].payload
    finally:
        service.shutdown()


class LiveState:
    """What FolderExplorer keeps between Live checks (``LiveSession``) and sends with the next."""

    def __init__(self, memory: list[list[int]]) -> None:
        self.memory = memory
        self.since: int | None = None
        self.listed_mtime: int | None = None
        self.identity = ""
        self.identity_root: str | None = None
        self.seen: list[list[int]] = []
        self.seen_names: list[str] = []

    def check(self, run: Path, output: Path) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        live_check(str(run), str(output), events.append, self.memory, since=self.since, identity=self.identity,
                   seen=self.seen, listed_mtime=self.listed_mtime, seen_names=self.seen_names,
                   identity_root=self.identity_root)
        result: dict[str, Any] = next(event for event in reversed(events)
                                      if event["kind"] in ("live_unchanged", "loaded", "shots_missing"))
        if result["kind"] == "shots_missing":
            return result
        self.since, self.listed_mtime = result["live_since"], result["live_listed_mtime"]
        self.seen, self.seen_names = result["live_seen"], result["live_seen_names"]
        if not self.identity and result["live_identity"]:
            self.identity, self.identity_root = result["live_identity"], result["live_identity_root"]
        if result["kind"] == "loaded":
            self.memory = [list(entry) for entry in result["fingerprint"]]
        return result


def test_live_watches_a_file_being_written_without_listing_the_folder(tmp_path: Path, trace: Path) -> None:
    """While a new file grows and the folder's mtime stays, a check stats only that file: no listing,
    no marker read, no sample. Once it stops changing, the check lists the folder and reads it."""
    run = tmp_path / "run"
    write_shots(run, range(1, 4))
    memory = [[shot, (info := (run / f"d_txy_forc{shot}.txt").stat()).st_size, info.st_mtime_ns] for shot in (1, 2, 3)]
    growing = run / "d_txy_forc4.txt"
    growing.write_text("4,1,1\n")
    old = time.time() - 30
    os.utime(run, (old, old))  # (Not racy: the folder's mtime is safe to compare.)
    live = LiveState(memory)
    output = tmp_path / "out"
    output.mkdir()
    first = live.check(run, output)
    assert first["kind"] == "live_unchanged" and live.seen_names == ["d_txy_forc4.txt"]
    for row in range(2, 5):  # The writer appends: the file's mtime changes, the folder's doesn't.
        with open(growing, "a") as stream:
            stream.write(f"4,{row},{row}\n")
        os.utime(run, (old, old))
        before = len(lines(trace))
        result = live.check(run, output)
        assert result["kind"] == "live_unchanged" and not result["live_listed"]
        assert counts(lines(trace)[before:]) == {("stat", "live: folder"): 1, ("stat", "live: pending file"): 1}
    before = len(lines(trace))
    result = live.check(run, output)  # Unchanged since the last look: read.
    assert result["kind"] == "loaded" and result["memory_shots"] == [1, 2, 3] and result["files"] == 4
    found = counts(lines(trace)[before:])
    assert found[("scandir", "live: listing")] == 1 and found[("read", "live: read")] == 1


def test_live_reads_only_the_known_root_marker_and_still_sees_another_root(tmp_path: Path, trace: Path) -> None:
    from helab.utils import data_roots
    run = tmp_path / "share" / "2026" / "run"
    write_shots(run, range(1, 3))
    memory = [[shot, (info := (run / f"d_txy_forc{shot}.txt").stat()).st_size, info.st_mtime_ns] for shot in (1, 2)]
    live = LiveState(memory)
    output = tmp_path / "out"
    output.mkdir()

    def marker_lines() -> list[tuple[str, str]]:
        return [(record["op"], record["path"]) for record in lines(trace)
                if record["op"].startswith("marker_") and record["pid"] == os.getpid()]
    live.check(run, output)
    # The first listing walks up to the nearest marker (the test folder's): one open per level.
    assert live.identity_root == str(tmp_path)
    opened = [path for op, path in marker_lines() if op == "marker_open"]
    assert len(opened) == 4 and opened[-1] == str(tmp_path / data_roots.MARKER_NAME)
    for shot in (3, 4):  # New files: the folder's mtime changes, so each check lists it.
        write_shots(run, range(shot, shot + 1))
        os.utime(run)
        before = len(marker_lines())
        live.check(run, output)
        assert [op for op, _ in marker_lines()[before:]] == ["marker_open", "marker_fstat", "marker_read"]
    # Another data root at that folder now (another drive at the path): Live stops.
    marker = tmp_path / data_roots.MARKER_NAME
    marker.write_text(json.dumps({"helab": "root", "version": 1, "uuid": str(uuid.uuid4()), "label": "other",
                                  "created_at": "2026-10-19T00:00:00Z"}))
    write_shots(run, range(5, 6))
    os.utime(run)
    stopped = live.check(run, output)
    assert stopped["kind"] == "shots_missing" and stopped["reason"] == "root"


def held_arrays(run: Path, folder: Path, shots: range) -> list[list[int]]:
    """Live's data for ``shots``: their arrays as the app hands them over, and their fingerprint."""
    folder.mkdir(exist_ok=True)
    for shot in shots:
        np.save(folder / f"{shot}.npy", np.array([[shot, 2.0, 3.0], [shot, 4.0, 5.0]]), allow_pickle=False)
    return [[shot, (info := (run / f"d_txy_forc{shot}.txt").stat()).st_size, info.st_mtime_ns] for shot in shots]


def test_a_live_save_checks_every_held_file_once_and_reads_none(tmp_path: Path, trace: Path) -> None:
    """The save lists the folder once (its listing's stats check every held file), reads no TXY
    file, and saves the data it was handed, guarded and budgeted like a load's save."""
    from helab.utils.cache_store import unpack_dataset
    run = tmp_path / "run"
    write_shots(run, range(1, 11))
    held = held_arrays(run, tmp_path / "held", range(1, 10))  # Shot 10: not read by Live yet.
    cache = store_options()
    events: list[dict[str, Any]] = []
    identity, root = io_helper._folder_identity(str(run))
    before = len(lines(trace))
    io_helper.save_held(str(run), events.append, cache, held, [3], str(tmp_path / "held"),
                        identity=identity, identity_root=root)
    kinds = [event["kind"] for event in events]
    assert "cache_saved" in kinds and "disk_cached" in kinds and "shots_missing" not in kinds
    loaded = next(event for event in events if event["kind"] == "loaded")
    assert loaded["memory_shots"] == list(range(1, 10)) and loaded["disk_cache_pending"]
    assert loaded["unsettled_files"] == 1 and loaded["problematic"] == [3]
    found = counts(lines(trace)[before:])
    assert found[("scandir", "save: listing")] == 1 and found[("entry_stat", "save: checking")] == 10
    assert not any(op in ("read", "stat") for op, _ in found)
    assert found[("marker_read", "save: identity")] == 1
    with io_helper._cache_store(cache["directory"], [str(run)]) as store:
        value = store.read_dataset(str(run)).value
        assert value is not None
        row, packed = value
        data = unpack_dataset(packed)
        assert data is not None and sorted(data) == list(range(1, 10))
        np.testing.assert_array_equal(data[4], [[4, 2, 3], [4, 4, 5]])
        assert row["info"]["unsettled"] == 1 and row["problematic"] == [3]


def test_a_live_save_saves_nothing_for_a_missing_changed_or_other_folder(tmp_path: Path) -> None:
    from helab.utils import data_roots
    run = tmp_path / "run"
    write_shots(run, range(1, 4))
    held = held_arrays(run, tmp_path / "held", range(1, 4))
    cache = store_options()

    def save(**kwargs: Any) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        io_helper.save_held(str(run), events.append, cache, held, [], str(tmp_path / "held"), **kwargs)
        return events

    def stopped(events: list[dict[str, Any]], reason: str) -> bool:
        return (any(event["kind"] == "shots_missing" and event["reason"] == reason for event in events)
                and not any(event["kind"] in ("loaded", "cache_saved") for event in events))
    identity, root = io_helper._folder_identity(str(run))
    other = {"helab": "root", "version": 1, "uuid": str(uuid.uuid4()), "label": "x", "created_at": "2026-10-19T00:00:00Z"}
    marker = tmp_path / data_roots.MARKER_NAME
    original = marker.read_text()
    marker.write_text(json.dumps(other))
    assert stopped(save(identity=identity, identity_root=root), "root")
    marker.write_text(original)
    (run / "d_txy_forc2.txt").write_text("2,9,9\n")  # Rewritten in place (TXY files are written once).
    assert stopped(save(identity=identity, identity_root=root), "changed")
    (run / "d_txy_forc2.txt").unlink()
    assert stopped(save(), "missing")
    with io_helper._cache_store(cache["directory"], [str(run)]) as store:
        assert store.read_dataset_row(str(run)).value is None


def test_a_live_save_keeps_dont_cache_and_the_budget(tmp_path: Path) -> None:
    run = tmp_path / "run"
    write_shots(run, range(1, 4))
    held = held_arrays(run, tmp_path / "held", range(1, 4))
    events: list[dict[str, Any]] = []
    io_helper.save_held(str(run), events.append, store_options(), held, [], str(tmp_path / "held"), no_cache=True)
    loaded = next(event for event in events if event["kind"] == "loaded")
    assert not loaded["disk_cache_pending"] and not any(event["kind"] == "cache_saved" for event in events)
    events = []
    io_helper.save_held(str(run), events.append, {**store_options(), "budget": 1, "budget_set_at": time.time()},
                        held, [], str(tmp_path / "held"))
    assert any(event["kind"] == "cache_full" for event in events)
    assert not any(event["kind"] == "cache_saved" for event in events)


def test_folder_cache_hands_live_s_data_to_its_save(qtbot: QtBot, tmp_path: Path, trace: Path) -> None:
    """``FolderCache.save`` with ``save_memory``: the data in RAM goes to the helper, which reads no
    TXY file; without data in RAM it is an ordinary load's save."""
    from helab.utils.folder_cache import FolderCache
    run = tmp_path / "run"
    write_shots(run, range(1, 6))
    service = IOService()
    cache = FolderCache(service)
    payload = {"cache": store_options(), "signature": "", "no_cache": False, "save_memory": True}
    try:
        assert cache.submit("tab", 0, str(run), "load", {"cache": {}})  # Into RAM only.
        qtbot.waitUntil(lambda: cache.current_dataset(str(run)) is not None and not cache.jobs, timeout=20000)
        saved: list[tuple[str, str]] = []
        cache.saveEnded.connect(lambda path, outcome: saved.append((path, outcome)))
        before = len(lines(trace))
        assert cache.save("tab:live-save", str(run), payload)
        qtbot.waitUntil(lambda: bool(saved), timeout=20000)
        assert saved == [(str(run), "saved")]
        records = [record for record in lines(trace)[before:] if record["pid"] != os.getpid()]
        assert any(record["op"] == "request" and "save" in record["flags"] for record in records)
        assert not any(record["op"] == "read" for record in records)
    finally:
        service.shutdown()


@pytest.mark.no_auto_data_root
def test_reselecting_a_ram_only_folder_checks_it_without_listing_it(
    qtbot: QtBot, tmp_path: Path, trace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A folder without subfolders whose checked data is in RAM: selecting it again doesn't list it
    (nor scan its details); its load's quick check is the check. A change found by that load updates
    the row from the load's own listing."""
    from helab.utils.folder_cache import FolderCache
    share = tmp_path / "share"
    run = share / "run"
    write_shots(run, range(1, 21))
    service = IOService()
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    monkeypatch.setattr(FolderCache, "FRESH_SECONDS", 0.2)
    explorer = FolderExplorer(str(share), str(share), str(share), [0, 4, 5])
    qtbot.addWidget(explorer)
    # As the main window does: each selection (and status update of it) asks for its data.
    explorer.selectionPathChanged.connect(lambda path: explorer.load_to_ram_cache(path))
    model = explorer.model

    def select(path: Path) -> None:
        qtbot.waitUntil(lambda: str(path) in model.nodes, timeout=20000)
        explorer.tree.setCurrentIndex(model.path_index(str(path)))

    def shown(count: int) -> bool:
        return explorer.folder_opened_path == str(run) and len(explorer.folder_opened_data or {}) == count
    select(run)
    qtbot.waitUntil(lambda: shown(20), timeout=20000)
    wait_idle(qtbot, service)
    assert model.cache.no_root(str(run)) is not None  # RAM only.
    qtbot.wait(300)  # Older than FRESH_SECONDS: the next selection checks it.
    explorer.clear_selection()
    wait_idle(qtbot, service)
    before = len(lines(trace))
    select(run)
    qtbot.waitUntil(lambda: shown(20) and not explorer.shows_unchecked(str(run)), timeout=20000)
    wait_idle(qtbot, service)
    on_run = [record for record in lines(trace)[before:]
              if record["path"].startswith(str(run)) and record["op"] not in BOOKKEEPING]
    assert not any(record["op"] == "scandir" for record in on_run)
    assert {record["reason"] for record in on_run} == {"memory check: folder", "memory check: sample"}
    write_shots(run, range(21, 22))
    os.utime(run)
    qtbot.wait(300)
    explorer.clear_selection()
    wait_idle(qtbot, service)
    before = len(lines(trace))
    select(run)
    qtbot.waitUntil(lambda: shown(21), timeout=20000)
    wait_idle(qtbot, service)
    listings = [record["request"] for record in lines(trace)[before:]
                if record["op"] == "scandir" and record["path"] == str(run)]
    assert listings == ["load"] and model.nodes[str(run)].txy_count == 21
    explorer.close_cleanup()
    service.shutdown()


def test_the_trace_goes_to_the_temp_folder_and_says_so_once_each_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Help › Record I/O trace: a new file in the temp folder's io-traces folder, one INFO line when it
    starts and one when it stops; refused (no file, no line) when the temp folder is on a share."""
    import logging
    from helab.utils import cache_location
    from helab.utils.io_service import IO_TRACE_FOLDER
    service = IOService()
    try:
        assert service.trace_file is None  # Off at every start.
        with caplog.at_level(logging.INFO):
            path = service.start_io_trace(str(tmp_path))
            service.stop_io_trace()
        said = [record.getMessage() for record in caplog.records if "I/O trace" in record.getMessage()]
        assert said == [f"I/O trace on: {path}", f"I/O trace off: {path}"]
        assert all(record.levelname == "INFO" for record in caplog.records if "I/O trace" in record.getMessage())
        assert os.path.dirname(path) == str(tmp_path / IO_TRACE_FOLDER) and os.path.isdir(os.path.dirname(path))
        assert os.path.basename(path).startswith("io-trace-") and path.endswith(".jsonl")
        assert service.trace_file is None
        caplog.clear()
        with caplog.at_level(logging.INFO):
            service.stop_io_trace()  # (Already off: nothing more said.)
        assert not caplog.records
        open(path, "w").close()  # (A helper's first line creates it.)
        again = service.start_io_trace(str(tmp_path))  # Within the same second: still a new file.
        assert again != path and not os.path.exists(again)
        service.stop_io_trace()
        caplog.clear()
        monkeypatch.setattr(cache_location, "cache_location_problem", lambda folder: "on a network drive (smbfs)")
        with caplog.at_level(logging.INFO), pytest.raises(ValueError, match="network drive"):
            service.start_io_trace(str(tmp_path / "share"))
        assert service.trace_file is None and not caplog.records
    finally:
        service.shutdown()
