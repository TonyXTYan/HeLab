"""The disk cache under contention and failures: nothing looks like "nothing saved",
a blocked folder is never scanned automatically, and failed saves are reported."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Mapping, Sequence

import pytest

from helab import io_helper
from helab.io_helper import save_subtrees, scan
from helab.utils import cache_store
from helab.utils.cache_store import CacheStore, Kind, Read, StoreError
from helab.utils.scan_history import ScanSkipped, begin_scan, empty_history, write_outcome


def history_guard(store: CacheStore, path: str) -> cache_store.SaveGuard:
    return store.guard([path], ("histories",))


def blocked_folder(tmp_path: Path) -> tuple[str, dict[str, Any]]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "d_txy_forc1.txt").write_text("1,2,3\n")
    options: dict[str, Any] = {"directory": str(tmp_path / "cache")}
    with CacheStore(options["directory"]) as store:
        write_outcome(store, str(source), {"operation_id": "failed", "revision": 11, "kind": "timeout",
            "at": time.time() - 60, "attempts": 1, "reason": "I/O timeout"}, history_guard(store, str(source)))
    return str(source), options


def saved_history(options: dict[str, Any], path: str) -> dict[str, Any]:
    with CacheStore(options["directory"]) as store:
        found = store.read_record("histories", path)
    assert found.value is not None
    return found.value


def hold_write_lock(options: dict[str, Any], seconds: float) -> threading.Thread:
    """Another connection holds the write lock, as a load saving its dataset does."""
    held = threading.Event()

    def hold() -> None:
        connection = sqlite3.connect(str(Path(options["directory"]) / "records.sqlite"), isolation_level=None)
        connection.execute("BEGIN IMMEDIATE")
        held.set()
        time.sleep(seconds)
        connection.execute("COMMIT")
        connection.close()
    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    assert held.wait(5)
    return thread


def no_saved_histories(monkeypatch: pytest.MonkeyPatch) -> None:
    """The read before the scan failed and looked like no saved history."""
    monkeypatch.setattr("helab.utils.scan_history.read_histories",
                        lambda store, paths: {path: empty_history() for path in paths})


def fail_history_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    original = CacheStore.read_records

    def failing(self: CacheStore, kind: Kind, paths: Sequence[str]) -> Mapping[str, Read[dict[str, Any]]]:
        if kind == "histories":
            return {path: Read("error", error="disk I/O error") for path in paths}
        return original(self, kind, paths)
    monkeypatch.setattr(CacheStore, "read_records", failing)


@pytest.mark.parametrize("automatic", [True, False], ids=["automatic", "details"])
def test_held_write_lock_does_not_unblock_a_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, automatic: bool,
) -> None:
    path, options = blocked_folder(tmp_path)
    monkeypatch.setattr(cache_store, "BUSY_TIMEOUT", 0.05)
    no_saved_histories(monkeypatch)
    holder = hold_write_lock(options, 0.5)
    events: list[dict[str, Any]] = []
    scan(path, events.append, options, manual=False, automatic=automatic)
    holder.join(5)
    assert events[-1] == {"kind": "scan_mode", "mode": "skipped"}
    assert not any(e["kind"] == "status" for e in events)


def test_held_write_lock_still_lets_a_manual_scan_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path, options = blocked_folder(tmp_path)
    monkeypatch.setattr(cache_store, "BUSY_TIMEOUT", 0.05)
    events: list[dict[str, Any]] = []
    # Keep the lock through the outcome save, even when coverage or a slow
    # runner makes the scan take longer than the timed holder's half second.
    with closing(sqlite3.connect(str(Path(options["directory"]) / "records.sqlite"),
                                 isolation_level=None)) as holder:
        holder.execute("BEGIN IMMEDIATE")
        scan(path, events.append, options, manual=True)
    assert any(e["kind"] == "scan_history_warning" for e in events)
    assert any(e["kind"] == "status" for e in events)
    # The saved failures stay: the outcome couldn't be written over them.
    assert saved_history(options, path)["blocked"]


@pytest.mark.parametrize("automatic", [True, False], ids=["automatic", "details"])
def test_begin_scan_decides_blocked_under_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, automatic: bool,
) -> None:
    path, options = blocked_folder(tmp_path)
    no_saved_histories(monkeypatch)
    events: list[dict[str, Any]] = []
    scan(path, events.append, options, manual=False, automatic=automatic)
    assert [e["mode"] for e in events if e["kind"] == "scan_mode"] == ["metadata", "skipped"]
    assert any(e["kind"] == "scan_history" and e["history"] and e["history"]["blocked"] for e in events)
    assert not any(e["kind"] == "status" for e in events)
    # A skipped scan writes nothing, not even its start.
    assert not saved_history(options, path)["starts"]
    with CacheStore(options["directory"]) as store:
        with pytest.raises(ScanSkipped):
            begin_scan(store, path, "auto", 20, history_guard(store, path), manual=False, automatic=automatic)
        # A manual scan still runs.
        history, revision = begin_scan(store, path, "manual", 20, history_guard(store, path))
        assert history["blocked"] and revision == 20


def test_unreadable_history_skips_automatic_scan_but_not_details(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "cache")) as store:
        store.save_record("histories", "folder", {"version": 1, "malformed": True}, history_guard(store, "folder"))
        with pytest.raises(ScanSkipped):
            begin_scan(store, "folder", "auto", 5, history_guard(store, "folder"), manual=False, automatic=True)
        history, _ = begin_scan(store, "folder", "details", 5, history_guard(store, "folder"), manual=False)
        assert not history["blocked"]


def test_scan_history_error_skips_a_scan_that_is_not_manual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, options = blocked_folder(tmp_path)
    no_saved_histories(monkeypatch)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise StoreError("disk I/O error")
    monkeypatch.setattr("helab.utils.scan_history.begin_scan", broken)
    events: list[dict[str, Any]] = []
    scan(path, events.append, options, manual=False)
    assert [e["kind"] for e in events if e["kind"] == "scan_history_warning"] == ["scan_history_warning"]
    assert events[-1] == {"kind": "scan_mode", "mode": "skipped"}
    events.clear()
    scan(path, events.append, options, manual=True)
    assert any(e["kind"] == "status" for e in events)


@pytest.mark.parametrize("automatic", [True, False], ids=["automatic", "details"])
def test_history_read_error_skips_a_scan_that_is_not_manual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, automatic: bool,
) -> None:
    path, options = blocked_folder(tmp_path)
    fail_history_reads(monkeypatch)
    events: list[dict[str, Any]] = []
    scan(path, events.append, options, manual=False, automatic=automatic)
    # Unreadable is unknown, never empty: an automatic scan stops at once, and
    # details stop when begin_scan's own read fails.
    assert events[-1] == {"kind": "scan_mode", "mode": "skipped"}
    assert not any(e["kind"] == "status" for e in events)
    if not automatic:
        assert any(e["kind"] == "scan_history_warning" and "disk I/O error" in e["message"] for e in events)
    monkeypatch.undo()
    saved = saved_history(options, path)
    assert saved["blocked"] and not saved["starts"]


def test_history_read_error_keeps_saved_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path, options = blocked_folder(tmp_path)
    fail_history_reads(monkeypatch)
    with CacheStore(options["directory"]) as store:
        with pytest.raises(StoreError, match="disk I/O error"):
            write_outcome(store, path, {"operation_id": "ok", "revision": 12, "kind": "success",
                                        "at": time.time(), "attempts": 1, "reason": ""}, history_guard(store, path))
    monkeypatch.undo()
    saved = saved_history(options, path)
    assert saved["blocked"] and len(saved["failures"]) == 1


def test_cache_that_cannot_open_skips_a_scan_that_is_not_manual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, options = blocked_folder(tmp_path)

    def cannot_open(*args: Any, **kwargs: Any) -> Any:
        raise StoreError("Disk cache could not be opened: unable to open database file")
    monkeypatch.setattr(CacheStore, "__init__", cannot_open)
    events: list[dict[str, Any]] = []
    scan(path, events.append, options, manual=False)
    assert any(e["kind"] == "scan_history_warning" for e in events)
    assert events[-1] == {"kind": "scan_mode", "mode": "skipped"}
    assert not any(e["kind"] == "status" for e in events)
    events.clear()
    # A manual scan still runs, with the warning; so does a scan with no cache configured.
    scan(path, events.append, options, manual=True)
    assert any(e["kind"] == "scan_history_warning" for e in events)
    assert any(e["kind"] == "status" for e in events)
    events.clear()
    scan(path, events.append, None, manual=False)
    assert any(e["kind"] == "status" for e in events)


def test_clear_during_a_scan_brings_back_neither_history_nor_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "d_txy_forc1.txt").write_text("1,2,3\n")
    path, options = str(source), {"directory": str(tmp_path / "cache")}
    original = io_helper._scan

    def clear_then_scan(*args: Any) -> dict[str, Any]:
        with CacheStore(options["directory"]) as store:
            store.remove(("summaries", "histories"))
        return original(*args)
    monkeypatch.setattr(io_helper, "_scan", clear_then_scan)
    events: list[dict[str, Any]] = []
    scan(path, events.append, options, manual=True)
    # The check itself succeeds; both saves are discarded and reported.
    assert any(e["kind"] == "status" for e in events)
    assert any(e["kind"] == "summary_save_failed" and "cleared" in e["message"] for e in events)
    assert any(e["kind"] == "scan_history_warning" and "cleared" in e["message"] for e in events)
    with CacheStore(options["directory"]) as store:
        assert store.read_record("summaries", path).missing
        assert store.read_record("histories", path).missing


def subtree_record(path: str) -> dict[str, Any]:
    return {"path": path, "status": "something", "derived_at": time.time(), "older": False,
            "data": 1, "checked": 1, "total": 1, "identity": None}


def test_failed_subtree_save_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    options: dict[str, Any] = {"directory": str(tmp_path / "cache")}

    def fail(*args: Any, **kwargs: Any) -> None:
        raise StoreError("Disk cache could not be written: disk I/O error")
    monkeypatch.setattr(CacheStore, "save_records", fail)
    events: list[dict[str, Any]] = []
    with pytest.raises(StoreError, match="disk I/O error"):
        save_subtrees(options, [subtree_record("a")], events.append)
    assert not events


def test_subtree_save_waits_for_a_held_write_lock(tmp_path: Path) -> None:
    options: dict[str, Any] = {"directory": str(tmp_path / "cache")}
    save_subtrees(options, [subtree_record("b")], lambda event: None)
    holder = hold_write_lock(options, 0.5)
    events: list[dict[str, Any]] = []
    save_subtrees(options, [subtree_record("a"), {"path": "b", "status": ""}], events.append)
    holder.join(5)
    assert events == [{"kind": "subtree_saved", "paths": ["a", "b"]}]
    with CacheStore(options["directory"]) as store:
        saved = store.read_record("subtrees", "a")
        assert saved.value is not None and saved.value["status"] == "something"
        assert store.read_record("subtrees", "b").missing


def test_failed_summary_save_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "d_txy_forc1.txt").write_text("1,2,3\n")
    options: dict[str, Any] = {"directory": str(tmp_path / "cache")}
    original = CacheStore.save_records

    def reject_summary(self: CacheStore, kind: Kind, *args: Any, **kwargs: Any) -> None:
        if kind == "summaries":
            raise StoreError("Disk cache could not be written: disk I/O error")
        original(self, kind, *args, **kwargs)
    monkeypatch.setattr(CacheStore, "save_records", reject_summary)
    events: list[dict[str, Any]] = []
    scan(str(source), events.append, options, manual=True)
    # The check itself still succeeds.
    assert any(e["kind"] == "status" for e in events)
    assert any(e["kind"] == "summary_save_failed" and "could not be saved" in e["message"] for e in events)
