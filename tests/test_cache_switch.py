"""Roadmap S5: the helpers use the store-v2 disk cache (``cache_store``) instead of diskcache."""
from __future__ import annotations

from pathlib import Path
import json
import os
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any

import pytest

from helab.io_helper import cache_admin, list_folder, load, read_cached, scan
from helab.utils import cache_location, file_kinds
from helab.utils.cache_location import cache_location_problem
from helab.utils.cache_store import LAYOUT_VERSION, OLD_CACHE_DIRS, CacheStore, DatasetRow
from helab.utils.constants import refuse_unsafe_cache_dir


def data_folder(tmp_path: Path, shots: int = 2) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    for shot in range(1, shots + 1):
        (source / f"d{shot}.txt").write_text("raw\n")
        (source / f"d_txy_forc{shot}.txt").write_text(f"{shot},2,3\n{shot},5,6\n")
    return source


def options_for(tmp_path: Path) -> dict[str, Any]:
    return {"directory": str(tmp_path / "caches" / "store-v2")}


def run_load(source: Path, tmp_path: Path, options: dict[str, Any] | None, **kwargs: Any) -> list[dict[str, Any]]:
    output = tmp_path / f"artifacts-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    load(str(source), str(output), events.append, options, **kwargs)
    return events


def dataset_row(options: dict[str, Any], path: str) -> DatasetRow:
    with CacheStore(options["directory"]) as store:
        found = store.read_dataset_row(path)
    assert found.value is not None
    return found.value


def test_file_kinds_match_count_and_size_from_one_table() -> None:
    assert [kind.name for kind in file_kinds.FILE_KINDS] == ["raw", "txy"]
    raw, txy = file_kinds.RAW, file_kinds.TXY
    assert file_kinds.match("d12.txt") == (raw, 12)
    assert file_kinds.match("d_txy_forc7.txt") == (txy, 7)
    assert file_kinds.match("d_txy_forc7.txt.bak") is None and file_kinds.match("notes.txt") is None
    assert txy.loaded and txy.sized and not raw.loaded and not raw.sized
    # A kind that isn't measured has no "bytes", never 0.
    assert file_kinds.files_summary({"raw": {1, 2}, "txy": {1}}, {"txy": 70, "raw": 99}) == {
        "raw": {"count": 2}, "txy": {"count": 1, "bytes": 70}}
    assert file_kinds.valid_files({"txy": {"count": 1, "bytes": 0}})
    assert not file_kinds.valid_files({"txy": {"count": -1}})
    assert not file_kinds.valid_files({"txy": {"count": 1, "bytes": 1.5}})


def test_scan_saves_per_kind_counts_and_txy_size(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    (source / "d3.txt").write_text("raw only\n")
    options = options_for(tmp_path)
    events: list[dict[str, Any]] = []
    scan(str(source), events.append, options)
    txy_bytes = sum((source / f"d_txy_forc{shot}.txt").stat().st_size for shot in (1, 2))
    status = next(event for event in events if event["kind"] == "status")
    assert status["files"] == {"raw": {"count": 3}, "txy": {"count": 2, "bytes": txy_bytes}}
    assert status["status"] == "fixable"  # Classification still works from the counts.
    with CacheStore(options["directory"]) as store:
        saved = store.read_record("summaries", str(source)).value
    assert saved is not None and saved["files"] == status["files"]
    assert (saved["raw_count"], saved["txy_count"]) == (3, 2)
    # A listing (names only) counts but never sizes.
    events.clear()
    list_folder(str(source), events.append, options)
    listed = next(event for event in events if event["kind"] == "status")
    assert listed["files"] == {"raw": {"count": 3}, "txy": {"count": 2}}


def test_load_saves_dataset_sizes_and_records_use(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    path, options = str(source), options_for(tmp_path)
    events = run_load(source, tmp_path, options)
    summary = next(event for event in events if event["kind"] == "scan_summary")["status"]
    assert summary["files"]["txy"]["bytes"] == sum(
        (source / f"d_txy_forc{shot}.txt").stat().st_size for shot in (1, 2))
    row = dataset_row(options, path)
    assert (row["rows"], row["shots"], row["ram_bytes"]) == (4, 2, 4 * 3 * 8)
    assert row["info"]["kind"] == "txy" and row["info"]["format"] == "blosc-pickle-1"
    assert row["bytes"] == os.path.getsize(Path(options["directory"]) / "datasets" / row["file"])
    # Reused by a load, shown from the cache and confirmed by the one-stat check: each is a use.
    for use in ("reuse", "cached", "confirmed"):
        before = row["last_used"]
        time.sleep(0.01)
        if use == "reuse":
            loaded = next(event for event in run_load(source, tmp_path, options) if event["kind"] == "loaded")
            assert loaded["source"] == "disk"
        elif use == "cached":
            output = tmp_path / "cached"
            output.mkdir()
            read_cached(path, str(output), lambda event: None, options)
        else:
            memory = [list(entry) for entry in row["fingerprint"]]
            loaded = next(event for event in run_load(source, tmp_path, options, memory=memory,
                          base_signature=row["info"]["signature"]) if event["kind"] == "loaded")
            assert loaded.get("unchanged") is True
        row = dataset_row(options, path)
        assert row["last_used"] > before, use
    # A use doesn't rewrite the dataset.
    assert row["info"]["action"] == "created"


def test_replaced_dataset_file_is_retired_not_deleted(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    path, options = str(source), options_for(tmp_path)
    run_load(source, tmp_path, options)
    first = dataset_row(options, path)["file"]
    (source / "d_txy_forc3.txt").write_text("3,2,3\n")
    events = run_load(source, tmp_path, options)
    assert next(event for event in events if event["kind"] == "cache_saved")["cache_info"]["action"] == "updated"
    second = dataset_row(options, path)
    assert second["file"] != first and second["shots"] == 3
    # A reader that looked up the old row can still open its file until the sweep's grace period ends.
    assert (Path(options["directory"]) / "datasets" / first).exists()
    with sqlite3.connect(Path(options["directory"]) / "records.sqlite") as connection:
        assert connection.execute("SELECT file FROM retired_files").fetchall() == [(first,)]


def test_invalidate_removes_the_dataset_through_the_helper(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    path, options = str(source), options_for(tmp_path)
    run_load(source, tmp_path, options)
    request = {"operation": "invalidate", "path": path, "cache": options}
    completed = subprocess.run([sys.executable, "-m", "helab.io_helper"], input=json.dumps(request) + "\n",
                               capture_output=True, text=True, timeout=60, check=True)
    assert json.loads(completed.stdout.strip().splitlines()[-1]) == {"kind": "done"}
    with CacheStore(options["directory"]) as store:
        assert store.read_dataset_row(path).missing
    events: list[dict[str, Any]] = []
    scan(str(source.parent), events.append, options)
    entry = next(e for event in events if event["kind"] == "entries" for e in event["entries"] if e["path"] == path)
    assert entry["disk_cached"] is False and entry["cache_info"] == {}


def test_startup_cleanup_deletes_old_diskcache_folders_and_sweeps(tmp_path: Path) -> None:
    caches = tmp_path / "caches"
    for name in OLD_CACHE_DIRS:
        (caches / name / "00").mkdir(parents=True)
        (caches / name / "00" / "cache.db").write_bytes(b"old")
    (caches / "keep-me").mkdir()
    options = options_for(tmp_path)
    with CacheStore(options["directory"]) as store:
        # A retired file past its grace period.
        store.remove(("datasets",), ["nothing"])
        stale = store.write_dataset_file(b"replaced")
        with store.transaction():
            store._retire(stale, time.time() - 3600)
    events: list[dict[str, Any]] = []
    cache_admin(options, "sweep", events.append)
    swept = events[-1]
    assert swept["kind"] == "swept" and sorted(swept["old_caches"]) == sorted(OLD_CACHE_DIRS)
    assert swept["deleted_files"] == 1 and swept["next_deadline"] is None
    assert sorted(os.listdir(caches)) == ["keep-me", "store-v2"]
    assert not (Path(options["directory"]) / "datasets" / stale).exists()
    with pytest.raises(ValueError, match="Unknown cache action"):
        cache_admin(options, "compact", events.append)


def test_folder_cache_submits_the_cleanup_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.utils.folder_cache import FolderCache, store_options
    from helab.utils.io_service import IOService
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    cache = FolderCache(service)
    try:
        cache.clean_up_cache()
        cache.clean_up_cache()
        requests = [r for r in service.pending if r.operation == "cache_admin"]
        # The sweep, and the inventory that restores saves still waiting for an answer.
        assert [r.payload for r in requests] == [{"cache": store_options(), "action": action, "params": {}}
                                                 for action in ("sweep", "inventory")]
        assert store_options()["directory"].endswith("store-v2")
        assert "cache_admin" in service.LOCAL_OPERATIONS
    finally:
        service.shutdown()


def test_newer_store_is_read_but_never_written(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    path, options = str(source), options_for(tmp_path)
    run_load(source, tmp_path, options)
    with sqlite3.connect(Path(options["directory"]) / "records.sqlite") as connection:
        connection.execute("UPDATE meta SET value = ? WHERE key = 'layout_version'", (str(LAYOUT_VERSION + 1),))
    row = dataset_row(options, path)
    (source / "d_txy_forc3.txt").write_text("3,2,3\n")
    events = run_load(source, tmp_path, options)
    # The cached shots are still reused; nothing is saved.
    loaded = next(event for event in events if event["kind"] == "loaded")
    assert loaded["source"] == "merged" and loaded["files"] == 3
    assert any(e["kind"] == "cache_warning" and "newer HeLab" in e["message"] for e in events)
    assert not any(e["kind"] in ("cache_saved", "cache_save_failed") for e in events)
    assert dataset_row(options, path) == row
    events.clear()
    cache_admin(options, "sweep", events.append)
    assert events[-1]["read_only"] is True


def test_synced_and_network_cache_folders_are_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = Path.home()
    assert cache_location_problem(str(home / "Library/Mobile Documents/com~apple~CloudDocs/c")) == \
        "in a synced folder (Mobile Documents)"
    assert cache_location_problem(str(home / "Library/CloudStorage/Box-Box/c")) == \
        "in a synced folder (CloudStorage)"
    assert cache_location_problem(str(home / "OneDrive - ANU" / "c")) == "in a synced folder (OneDrive - ANU)"
    assert cache_location_problem(str(home / "Dropbox" / "c")) == "in a synced folder (Dropbox)"
    assert cache_location_problem(str(tmp_path)) == ""
    mounts = [SimpleNamespace(mountpoint="/", fstype="apfs", opts="rw,local"),
              SimpleNamespace(mountpoint=str(tmp_path / "share"), fstype="smbfs", opts="rw,nosuid"),
              SimpleNamespace(mountpoint=str(tmp_path / "drive"), fstype="NTFS", opts="rw,remote")]
    monkeypatch.setattr("psutil.disk_partitions", lambda all=False: mounts)
    assert cache_location_problem(str(tmp_path / "share" / "caches")) == "on a network drive (smbfs)"
    assert cache_location_problem(str(tmp_path / "share-2" / "caches")) == ""
    assert cache_location_problem(str(tmp_path / "drive" / "caches")) == "on a network drive (ntfs)"
    if sys.platform == "win32":
        assert cache_location_problem(r"\\server\share\caches") == "on a network drive"

    def broken(all: bool = False) -> Any:
        raise OSError("no mount table")
    monkeypatch.setattr("psutil.disk_partitions", broken)
    assert cache_location_problem(str(tmp_path)) == ""  # Unknown is allowed.
    assert cache_location.NETWORK_FILESYSTEMS >= {"smbfs", "afpfs", "nfs", "webdav", "cifs"}


def test_unsafe_saved_cache_folder_is_replaced_for_this_session(monkeypatch: pytest.MonkeyPatch,
                                                                tmp_path: Path) -> None:
    synced = str(Path.home() / "Dropbox" / "HeLab" / "caches")
    fallback = str(tmp_path / "default")
    path, reason, enabled = refuse_unsafe_cache_dir(synced, [fallback])
    assert path == fallback and os.path.isdir(fallback) and enabled
    assert synced in reason and "synced folder" in reason and fallback in reason
    assert refuse_unsafe_cache_dir(fallback, [str(tmp_path / "other")]) == (fallback, "", True)
    # With no safe default the refused folder is never used: the disk cache is off.
    path, reason, enabled = refuse_unsafe_cache_dir(synced, [str(Path.home() / "Dropbox" / "x")])
    assert not enabled and "no safe default" in reason and "off for this session" in reason


def test_disk_cache_off_means_no_helper_opens_a_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from helab.utils import folder_cache
    from helab.utils.folder_cache import FolderCache, store_options
    from helab.utils.io_service import IOService
    monkeypatch.setattr(folder_cache, "DISK_CACHE_ENABLED", False)
    assert store_options() == {}
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    cache = FolderCache(service)
    try:
        cache.clean_up_cache()
        cache.save_subtree(str(tmp_path), {"status": "something", "derived_at": time.time()}, store_options())
        assert not service.pending and not cache._subtree_pending
    finally:
        service.shutdown()
    # Source helpers run without a cache; cache-only jobs refuse.
    source = data_folder(tmp_path)
    events = run_load(source, tmp_path, store_options())
    assert next(event for event in events if event["kind"] == "loaded")["cache_reason"] == "Disk cache unavailable"
    assert not (tmp_path / "caches").exists()
    for operation in ("cached", "invalidate", "subtree_save", "scan_history", "cache_admin"):
        request: dict[str, Any] = {"operation": operation, "path": str(source), "cache": {}}
        completed = subprocess.run([sys.executable, "-m", "helab.io_helper"], input=json.dumps(request) + "\n",
                                   capture_output=True, text=True, timeout=60, check=True)
        assert json.loads(completed.stdout.strip().splitlines()[-1]) == {
            "kind": "error", "message": "The disk cache is off for this session"}, operation


@pytest.mark.parametrize("failure", ["read error", "malformed record"])
def test_unreadable_saved_records_are_unknown_not_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str,
) -> None:
    from helab.utils.cache_store import Read
    source = data_folder(tmp_path)
    path, options = str(source), options_for(tmp_path)
    run_load(source, tmp_path, options)
    scan(path, lambda event: None, options)
    if failure == "malformed record":
        with sqlite3.connect(Path(options["directory"]) / "records.sqlite") as connection:
            connection.execute("UPDATE folder_summaries SET record = '{broken'")
            connection.execute("UPDATE datasets SET info = '{broken'")
    else:
        def failing(self: CacheStore, paths: Any) -> dict[str, Read[Any]]:
            return {p: Read("error", error="Disk cache could not be read: disk I/O error") for p in paths}
        monkeypatch.setattr(CacheStore, "read_dataset_infos", failing)
        original = CacheStore.read_records

        def failing_summaries(self: CacheStore, kind: Any, paths: Any) -> Any:
            if kind == "summaries":
                return {p: Read("error", error="Disk cache could not be read: disk I/O error") for p in paths}
            return original(self, kind, paths)
        monkeypatch.setattr(CacheStore, "read_records", failing_summaries)
    for helper in (list_folder, scan):
        events: list[dict[str, Any]] = []
        helper(str(source.parent), events.append, options)
        entry = next(e for event in events if event["kind"] == "entries" for e in event["entries"] if e["path"] == path)
        # Left out, so the GUI keeps what it knew; never "not cached" or "no summary".
        assert not {"disk_cached", "cache_info", "scan_status"} & set(entry), helper
        assert entry["scan_history"] is not None
        assert any(event["kind"] == "cache_warning" for event in events), helper


def test_load_that_cannot_read_the_cache_leaves_its_flag_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from helab.utils.cache_store import Read
    source = data_folder(tmp_path)
    options = options_for(tmp_path)
    run_load(source, tmp_path, options)
    monkeypatch.setattr(CacheStore, "read_dataset_row",
                        lambda self, path: Read("error", error="Disk cache could not be read: disk I/O error"))
    events = run_load(source, tmp_path, options)
    loaded = next(event for event in events if event["kind"] == "loaded")
    assert loaded["source"] == "files" and "disk_cached" not in loaded
    assert any(e["kind"] == "cache_warning" and "disk I/O error" in e["message"] for e in events)


def test_app_no_longer_imports_diskcache() -> None:
    code = ("import sys\n"
            "import helab.main, helab.views.HelabMainWindow, helab.views.SettingsDialog\n"
            "print('diskcache' in sys.modules, 'helab.utils.caching_setup' in sys.modules)\n")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, check=True)
    assert result.stdout.strip().splitlines()[-1] == "False False"


def test_folder_cache_keeps_known_flags_and_records_the_read_warning(
    qtbot: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from helab.utils.folder_cache import FolderCache
    from helab.utils.io_service import IOService
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    cache = FolderCache(service)
    path, child = str(tmp_path), str(tmp_path / "run")
    cache._set_disk_cached(child, True)
    status = {"kind": "status", "details": False, "status": "unknown", "count": -1, "empty": False,
              "has_dirs": True, "scanned_at": time.time(), "raw": [], "txy": []}

    def listing(*events: dict[str, Any]) -> None:
        assert cache.submit(f"tab-{time.monotonic_ns()}", 0, path, "list", {"cache": options_for(tmp_path)},
                            force=True)
        request = next(r for r in service.pending if r.operation == "list")
        for event in (*events, status, {"kind": "done"}):
            service.resultReady.emit(request, event)
        service.pending.remove(request)

    try:
        listing({"kind": "cache_warning", "message": "Disk cache could not be read: disk I/O error"},
                {"kind": "entries", "entries": [{"path": child, "name": "run", "scan_history": None}]})
        assert cache.disk_cached(child)  # Unknown is not "not cached".
        assert cache.cache_read_errors[path] == "Disk cache could not be read: disk I/O error"
        # A later listing that reads the cache clears the warning.
        listing({"kind": "entries", "entries": [{"path": child, "name": "run", "scan_history": None,
                                                 "disk_cached": False, "cache_info": {}}]})
        assert not cache.disk_cached(child) and path not in cache.cache_read_errors
    finally:
        service.shutdown()


def test_cache_that_cannot_open_is_unknown_not_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from helab.utils.cache_store import StoreError
    source = data_folder(tmp_path)
    options = options_for(tmp_path)
    run_load(source, tmp_path, options)

    def cannot_open(*args: Any, **kwargs: Any) -> None:
        raise StoreError("Disk cache could not be opened: database is locked")
    monkeypatch.setattr(CacheStore, "__init__", cannot_open)
    for helper in (list_folder, scan):
        events: list[dict[str, Any]] = []
        helper(str(source.parent), events.append, options)
        status = next(event for event in events if event["kind"] == "status")
        entry = next(e for event in events if event["kind"] == "entries" for e in event["entries"])
        assert "disk_cached" not in status and "disk_cached" not in entry, helper
        assert any(e["kind"] == "cache_warning" and "database is locked" in e["message"] for e in events), helper
    events = run_load(source, tmp_path, options)
    loaded = next(event for event in events if event["kind"] == "loaded")
    assert loaded["source"] == "files" and "disk_cached" not in loaded
    assert any(e["kind"] == "cache_warning" and "database is locked" in e["message"] for e in events)
    # With no cache configured, nothing is cached: that is known.
    events.clear()
    scan(str(source), events.append, None)
    assert next(event for event in events if event["kind"] == "status")["disk_cached"] is False


def test_clear_while_a_load_starts_up_is_not_undone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import builtins
    source = data_folder(tmp_path)
    path, options = str(source), options_for(tmp_path)
    run_load(source, tmp_path, options)
    (source / "d_txy_forc3.txt").write_text("3,2,3\n")
    original_import = builtins.__import__
    cleared: list[bool] = []

    def clear_while_importing(name: str, *args: Any, **kwargs: Any) -> Any:
        # The load is already running, initialising pandas, when the folder's cache is cleared.
        if name == "pandas" and not cleared:
            cleared.append(True)
            with CacheStore(options["directory"]) as store:
                store.remove(("datasets",), [path])
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", clear_while_importing)
    events = run_load(source, tmp_path, options)
    monkeypatch.undo()
    assert cleared
    assert next(event for event in events if event["kind"] == "loaded")["files"] == 3
    assert not any(event["kind"] == "cache_saved" for event in events)
    failed = next(event for event in events if event["kind"] == "cache_save_failed")
    assert failed["message"] == "Cache was cleared before saving completed"
    with CacheStore(options["directory"]) as store:
        assert store.read_dataset_row(path).missing


def test_clear_while_a_scan_reads_saved_results_is_not_undone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from helab import io_helper
    source = data_folder(tmp_path)
    path, options = str(source), options_for(tmp_path)
    scan(path, lambda event: None, options)
    original = io_helper._send_saved

    def clear_while_restoring(*args: Any) -> Any:
        # The scan is already running, restoring saved results, when they are cleared.
        with CacheStore(options["directory"]) as store:
            store.remove(("summaries", "histories"))
        return original(*args)
    monkeypatch.setattr(io_helper, "_send_saved", clear_while_restoring)
    events: list[dict[str, Any]] = []
    scan(path, events.append, options, manual=True)
    assert any(event["kind"] == "status" for event in events)
    assert any(e["kind"] == "scan_history_warning" and "cleared" in e["message"] for e in events)
    with CacheStore(options["directory"]) as store:
        assert store.read_record("summaries", path).missing
        assert store.read_record("histories", path).missing


def test_a_load_saves_within_the_budget_the_app_set_last(tmp_path: Path) -> None:
    """A load requested before the user lowered the budget doesn't save over the new one."""
    source = data_folder(tmp_path)
    options = options_for(tmp_path)
    requested = time.time() - 60
    with CacheStore(options["directory"]) as store:
        assert store.record_budget(1000, requested + 30) == 1000  # Lowered while it ran.
    events = run_load(source, tmp_path, {**options, "budget": 1 << 30, "budget_set_at": requested})
    held = next(event for event in events if event["kind"] in ("cache_full", "cache_saved"))
    assert held["kind"] == "cache_full" and held["budget"] == 1000
