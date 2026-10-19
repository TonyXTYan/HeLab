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
import uuid

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
    monkeypatch.setenv("HELAB_IO_TRACE", str(file))
    yield file
    if io_helper._trace_fd is not None:
        os.close(io_helper._trace_fd)


# Event fields that differ between two runs of the same call: times, and each run's output folder.
VOLATILE = {"scanned_at", "loaded_at", "modified_observed_at", "saved_at", "snapshot_at", "live_seconds",
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
    for folder, expected in ((good, ["open", "fstat", "read"]), (bad, ["open", "fstat", "read"]),
                             (folder_named, ["open", "fstat"]), (missing, [])):
        steps: list[tuple[str, dict[str, object]]] = []
        assert outcome(folder, trace=lambda name, fields: steps.append((name, fields))) == outcome(folder)
        assert [name for name, _ in steps] == expected
    steps = []
    data_roots.read_marker(str(good), trace=lambda name, fields: steps.append((name, fields)))
    size = (good / data_roots.MARKER_NAME).stat().st_size
    assert steps[1][1]["size"] == size and steps[2][1] == {"bytes": size}


def test_a_trace_file_on_a_network_drive_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                    caplog: pytest.LogCaptureFixture) -> None:
    from helab.utils import cache_location
    assert io_helper._trace_file(None) is None and io_helper._trace_file("") is None
    assert io_helper._trace_file(str(tmp_path / "t.jsonl")) == str(tmp_path / "t.jsonl")
    assert io_helper._trace_file("//server/share/t.jsonl") is None
    monkeypatch.setattr(cache_location, "_filesystem", lambda path: ("smbfs", True))
    assert io_helper._trace_file(str(tmp_path / "t.jsonl")) is None
    assert "HELAB_IO_TRACE ignored" in caplog.text


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


def test_a_load_never_shows_or_caches_a_file_whose_writer_stalled_mid_row(tmp_path: Path, trace: Path) -> None:
    """A file settled by age (its writer paused longer than the settle age) but ending mid-row is
    still being written: read, then dropped, neither shown nor cached, and read once it's whole."""
    from helab.utils.cache_store import unpack_dataset
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
    assert [event["shot"] for event in events if event["kind"] == "shot"] == [1, 2]
    assert loaded["files"] == 2 and loaded["unsettled_files"] == 1 and 3 not in loaded["problematic"]
    assert any(record["op"] == "read" and record["path"] == str(stalled) for record in lines(trace))
    with io_helper._cache_store(cache["directory"], [str(run)]) as store:
        found = store.read_dataset(str(run))
        assert found.value is not None
        row, packed = found.value
        data = unpack_dataset(packed)
        assert data is not None and sorted(data) == [1, 2] and row["info"]["unsettled"] == 1
    stalled.write_text("3,2,3\n3,4,5\n")  # The writer finished.
    os.utime(stalled, (when, when))
    events = []
    load(str(run), str(output), events.append, cache)
    loaded = next(event for event in events if event["kind"] == "loaded")
    # Shots 1 and 2 come from the disk cache; only the finished file is read.
    assert loaded["files"] == 3 and loaded["load_counts"]["read"] == 1 and loaded["unsettled_files"] == 0


def test_an_old_file_ending_mid_row_is_read_as_far_as_it_goes(tmp_path: Path) -> None:
    """Untouched for longer than ``RECENT_SECONDS``, a file ending mid-row is damaged, not being
    written: it loads as problematic, without its partial row."""
    run = tmp_path / "run"
    run.mkdir()
    damaged = run / "d_txy_forc1.txt"
    damaged.write_text("1,2,3\n4,5")
    when = time.time() - io_helper.RECENT_SECONDS - 60
    os.utime(damaged, (when, when))
    output = tmp_path / "out"
    output.mkdir()
    events: list[dict[str, Any]] = []
    load(str(run), str(output), events.append)
    loaded = next(event for event in events if event["kind"] == "loaded")
    assert loaded["files"] == 1 and loaded["problematic"] == [1] and loaded["rows"] == 1
