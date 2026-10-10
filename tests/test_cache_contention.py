"""The diskcache store under write contention: no read or write failure looks like "nothing saved"."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import threading
import time
from typing import Any

from diskcache import Cache, FanoutCache
import pytest
from PyQt6.QtCore import QSettings

from helab import io_helper
from helab.io_helper import SUBTREE_KEY, save_subtrees, scan
from helab.utils.caching_setup import load_cache_param
from helab.utils.scan_history import HISTORY_KEY, ScanSkipped, begin_scan, empty_history, write_outcome


def blocked_folder(tmp_path: Path, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "d_txy_forc1.txt").write_text("1,2,3\n")
    options: dict[str, Any] = {"directory": str(tmp_path / "cache"), "params": params}
    with FanoutCache(options["directory"], **params) as cache:
        write_outcome(cache, str(source), {"operation_id": "failed", "revision": 11, "kind": "timeout",
            "at": time.time() - 60, "attempts": 1, "reason": "I/O timeout"})
    return str(source), options


def hold_write_lock(options: dict[str, Any], seconds: float) -> threading.Thread:
    """Another connection holds every shard's write lock, as a load saving its dataset does."""
    held = threading.Event()

    def hold() -> None:
        with FanoutCache(options["directory"], **options["params"]) as other:
            with other.transact():
                held.set()
                time.sleep(seconds)
    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    assert held.wait(5)
    return thread


def test_helper_cache_options_never_turn_statistics_on(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("cache_params/data_ram_cache/statistics", True)
    assert load_cache_param("data_ram_cache", settings)["statistics"] is False


@pytest.mark.parametrize("automatic", [True, False], ids=["automatic", "details"])
def test_held_write_lock_does_not_unblock_a_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, automatic: bool,
) -> None:
    # Statistics on and a short timeout: the old setup, where a read under a held
    # write lock timed out and answered "nothing saved".
    path, options = blocked_folder(tmp_path, {"shards": 2, "statistics": True, "timeout": 0.05})
    holders: list[threading.Thread] = []
    open_cache = io_helper._open_cache

    def open_then_lock(cache_options: dict[str, Any] | None) -> Any:
        # Opening writes settings and waits for the lock, so take it afterwards.
        cache = open_cache(cache_options)
        holders.append(hold_write_lock(options, 0.5))
        return cache
    monkeypatch.setattr(io_helper, "_open_cache", open_then_lock)
    events: list[dict[str, Any]] = []
    scan(path, events.append, options, manual=False, automatic=automatic)
    holders[0].join(5)
    assert [e["mode"] for e in events if e["kind"] == "scan_mode"][-1] == "skipped"
    assert not any(e["kind"] == "status" for e in events)


@pytest.mark.parametrize("automatic", [True, False], ids=["automatic", "details"])
def test_begin_scan_decides_blocked_under_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, automatic: bool,
) -> None:
    path, options = blocked_folder(tmp_path, {"shards": 2})
    # The read before the scan failed and looked like no saved history.
    monkeypatch.setattr("helab.utils.scan_history.read_history", lambda cache, path: empty_history())
    events: list[dict[str, Any]] = []
    scan(path, events.append, options, manual=False, automatic=automatic)
    assert [e["mode"] for e in events if e["kind"] == "scan_mode"] == ["metadata", "skipped"]
    assert any(e["kind"] == "scan_history" and e["history"]["blocked"] for e in events)
    assert not any(e["kind"] == "status" for e in events)
    with FanoutCache(options["directory"], **options["params"]) as cache:
        # A skipped scan writes nothing, not even its start.
        saved: Any = cache.get((HISTORY_KEY, path))
        assert not saved["starts"]
        with pytest.raises(ScanSkipped):
            begin_scan(cache, path, "auto", 20, manual=False, automatic=automatic)
        # A manual scan still runs.
        history, revision = begin_scan(cache, path, "manual", 20)
        assert history["blocked"] and revision == 20


def test_unreadable_history_skips_automatic_scan_but_not_details(tmp_path: Path) -> None:
    options: dict[str, Any] = {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}
    with FanoutCache(options["directory"], **options["params"]) as cache:
        cache.set((HISTORY_KEY, "folder"), {"version": 1, "malformed": True})
        with pytest.raises(ScanSkipped):
            begin_scan(cache, "folder", "auto", 5, manual=False, automatic=True)
        history, _ = begin_scan(cache, "folder", "details", 5, manual=False)
        assert not history["blocked"]


def test_scan_history_error_skips_a_scan_that_is_not_manual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, options = blocked_folder(tmp_path, {"shards": 2})
    monkeypatch.setattr("helab.utils.scan_history.read_history", lambda cache, path: empty_history())

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise OSError("disk I/O error")
    monkeypatch.setattr("helab.utils.scan_history.begin_scan", broken)
    events: list[dict[str, Any]] = []
    scan(path, events.append, options, manual=False)
    assert [e["kind"] for e in events if e["kind"] == "scan_history_warning"] == ["scan_history_warning"]
    assert events[-1] == {"kind": "scan_mode", "mode": "skipped"}
    events.clear()
    scan(path, events.append, options, manual=True)
    assert any(e["kind"] == "status" for e in events)


def fail_history_reads(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    """The shard's read fails; FanoutCache.get alone would swallow it and answer None."""
    original = Cache.get

    def failing(self: Cache, key: Any, *args: Any, **kwargs: Any) -> Any:
        if key == (HISTORY_KEY, path):
            raise sqlite3.OperationalError("disk I/O error")
        return original(self, key, *args, **kwargs)
    monkeypatch.setattr(Cache, "get", failing)


@pytest.mark.parametrize("automatic", [True, False], ids=["automatic", "details"])
def test_history_read_error_skips_a_scan_that_is_not_manual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, automatic: bool,
) -> None:
    path, options = blocked_folder(tmp_path, {"shards": 2})
    fail_history_reads(monkeypatch, path)
    events: list[dict[str, Any]] = []
    scan(path, events.append, options, manual=False, automatic=automatic)
    assert any(e["kind"] == "scan_history_warning" and "disk I/O error" in e["message"] for e in events)
    assert events[-1] == {"kind": "scan_mode", "mode": "skipped"}
    assert not any(e["kind"] == "status" for e in events)
    monkeypatch.undo()
    with FanoutCache(options["directory"], **options["params"]) as cache:
        saved: Any = cache.get((HISTORY_KEY, path))
        assert saved["blocked"] and not saved["starts"]


def test_history_read_error_keeps_saved_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path, options = blocked_folder(tmp_path, {"shards": 2})
    fail_history_reads(monkeypatch, path)
    with FanoutCache(options["directory"], **options["params"]) as cache:
        with pytest.raises(sqlite3.OperationalError):
            write_outcome(cache, path, {"operation_id": "ok", "revision": 12, "kind": "success",
                                        "at": time.time(), "attempts": 1, "reason": ""})
    monkeypatch.undo()
    with FanoutCache(options["directory"], **options["params"]) as cache:
        saved: Any = cache.get((HISTORY_KEY, path))
        assert saved["blocked"] and len(saved["failures"]) == 1


def test_cache_that_cannot_open_skips_a_scan_that_is_not_manual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, options = blocked_folder(tmp_path, {"shards": 2})

    def cannot_open(*args: Any, **kwargs: Any) -> Any:
        raise sqlite3.OperationalError("unable to open database file")
    monkeypatch.setattr(FanoutCache, "__init__", cannot_open)
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


def subtree_record(path: str) -> dict[str, Any]:
    return {"path": path, "status": "something", "derived_at": time.time(), "older": False,
            "data": 1, "checked": 1, "total": 1, "identity": None}


def test_failed_subtree_save_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    options: dict[str, Any] = {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}
    monkeypatch.setattr(FanoutCache, "set", lambda self, *args, **kwargs: False)
    events: list[dict[str, Any]] = []
    with pytest.raises(OSError, match="rejected"):
        save_subtrees(options, [subtree_record("a")], events.append)
    assert not events


def test_subtree_save_waits_for_a_held_write_lock(tmp_path: Path) -> None:
    options: dict[str, Any] = {"directory": str(tmp_path / "cache"), "params": {"shards": 2, "timeout": 0.05}}
    holder = hold_write_lock(options, 0.5)
    events: list[dict[str, Any]] = []
    save_subtrees(options, [subtree_record("a"), {"path": "b", "status": ""}], events.append)
    holder.join(5)
    assert events == [{"kind": "subtree_saved", "paths": ["a", "b"]}]
    with FanoutCache(options["directory"], **options["params"]) as cache:
        subtree: Any = cache.get((SUBTREE_KEY, "a"))
        assert subtree["status"] == "something"


def test_failed_summary_save_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "d_txy_forc1.txt").write_text("1,2,3\n")
    options: dict[str, Any] = {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}
    original = FanoutCache.set

    def reject_summary(self: FanoutCache, key: Any, *args: Any, **kwargs: Any) -> bool:
        return False if isinstance(key, tuple) and key[0] == "folder-scan-v1" else original(self, key, *args, **kwargs)
    monkeypatch.setattr(FanoutCache, "set", reject_summary)
    events: list[dict[str, Any]] = []
    scan(str(source), events.append, options, manual=True)
    # The check itself still succeeds.
    assert any(e["kind"] == "status" for e in events)
    assert any(e["kind"] == "summary_save_failed" and "could not be saved" in e["message"] for e in events)
