"""Stores made before the DLD port (F0b's ``folder_constants``, D7's ``datasets.raw_times``) are
brought up to date on every writable open (``cache_store._migrate``): every real store was made
before them, and ``SCHEMA`` only runs for a new store. A read-only store (written by a newer HeLab)
without them reads as "none set", never as an error. A nested root's re-key is in one transaction
with its root record, so a failed one is retried by the next listing."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid
from typing import Any

import pytest

from helab import io_helper
from helab.utils import cache_paths, cache_store, data_roots, folder_cache
from helab.utils.cache_paths import Mount
from helab.utils.cache_store import CacheStore, DatasetRecord, StoreError, StoreReadOnly
from helab.utils.folder_cache import FolderCache, store_options
from helab.utils.io_service import IORequest, IOService

pytestmark = pytest.mark.no_auto_data_root

# The store's schema at 1231025, the last commit before the DLD port merged F0b and D7.
OLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS folder_epochs (
    path TEXT PRIMARY KEY, epoch INTEGER NOT NULL DEFAULT 0, job_seq INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS folder_summaries (
    path TEXT PRIMARY KEY, record TEXT NOT NULL, identity TEXT, saved_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS folder_summaries_saved_at ON folder_summaries (saved_at);
CREATE TABLE IF NOT EXISTS scan_histories (path TEXT PRIMARY KEY, record TEXT NOT NULL, saved_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS scan_histories_saved_at ON scan_histories (saved_at);
CREATE TABLE IF NOT EXISTS subtrees (path TEXT PRIMARY KEY, record TEXT NOT NULL, saved_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS subtrees_saved_at ON subtrees (saved_at);
CREATE TABLE IF NOT EXISTS folder_prefs (
    path TEXT PRIMARY KEY, no_cache INTEGER NOT NULL DEFAULT 0, no_auto_load INTEGER NOT NULL DEFAULT 0,
    set_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS pending_saves (
    pending_id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE,
    reason TEXT NOT NULL CHECK (reason IN ('over_budget', 'needs_approval')),
    file TEXT NOT NULL, bytes INTEGER NOT NULL, record TEXT NOT NULL,
    gen_datasets INTEGER NOT NULL, epoch INTEGER NOT NULL, job_seq INTEGER NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS retired_files (file TEXT PRIMARY KEY, retired_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS datasets (
    path TEXT PRIMARY KEY, file TEXT NOT NULL, bytes INTEGER NOT NULL, ram_bytes INTEGER NOT NULL,
    rows INTEGER NOT NULL, shots INTEGER NOT NULL, fingerprint TEXT NOT NULL, problematic TEXT NOT NULL,
    info TEXT NOT NULL, last_used REAL NOT NULL, job_seq INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS datasets_last_used ON datasets (last_used);
CREATE TABLE IF NOT EXISTS roots (
    location TEXT PRIMARY KEY, uuid TEXT NOT NULL, kind TEXT NOT NULL,
    label TEXT NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL,
    verified_at REAL NOT NULL, decision TEXT NOT NULL
        CHECK (decision IN ('confirmed', 'pending')));
CREATE INDEX IF NOT EXISTS roots_uuid ON roots (uuid);
CREATE TABLE IF NOT EXISTS root_volumes (
    mount_path TEXT NOT NULL, mount_source TEXT NOT NULL, volume_id TEXT NOT NULL,
    seen_at REAL NOT NULL, PRIMARY KEY (mount_path, mount_source));
"""
A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def old_store(directory: Path, *, layout: int = cache_store.LAYOUT_VERSION) -> Path:
    """A store as 1231025 made it (``layout``: as a newer HeLab's would read, for read-only opens),
    holding one dataset row saved then, without ``raw_times``."""
    (directory / "datasets").mkdir(parents=True)
    conn = sqlite3.connect(directory / "records.sqlite", isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("BEGIN IMMEDIATE")
        for statement in OLD_SCHEMA.split(";"):
            if statement.strip():
                conn.execute(statement)
        meta: dict[str, object] = {"layout_version": layout, "store_id": uuid.uuid4().hex, "created_at": time.time(),
                                   **{f"gen_{kind}": 0 for kind in cache_store.KINDS}}
        conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)",
                         [(key, json.dumps(value)) for key, value in meta.items()])
        conn.execute("INSERT INTO datasets VALUES (?, 'f.blosc', 4, 1, 1, 1, '[]', '[]', '{}', 1.0, 1)",
                     (f"root://{A}/old",))
        conn.execute("COMMIT")
    finally:
        conn.close()
    return directory


def schema(directory: Path) -> tuple[set[str], set[str]]:
    with sqlite3.connect(directory / "records.sqlite") as conn:
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(datasets)")}
    return tables, columns


def test_an_old_store_gains_constants_and_shot_times_when_opened(tmp_path: Path) -> None:
    directory = old_store(tmp_path / "store")
    with CacheStore(str(directory)) as store:
        tables, columns = schema(directory)
        assert "folder_constants" in tables and "raw_times" in columns
        assert store.read_constants([f"root://{A}/run"])[f"root://{A}/run"].missing
        assert store.set_constants(f"root://{A}/run", {"fall_distance": 0.85}, 10.0)["values"] == {"fall_distance": 0.85}
        # The dataset saved before keeps working: no raw times known.
        row = store.read_dataset_row(f"root://{A}/old").value
        assert row is not None and row.get("raw_times") == []
    with CacheStore(str(directory)) as store:  # Opened again: nothing left to do.
        assert store.read_constants([f"root://{A}/run"])[f"root://{A}/run"].value == {
            "values": {"fall_distance": 0.85}, "set_at": 10.0}


def test_concurrent_helpers_migrate_an_old_store_once(tmp_path: Path) -> None:
    directory = old_store(tmp_path / "store")
    code = ("import sys\nfrom helab.utils.cache_store import CacheStore\n"
            "with CacheStore(sys.argv[1]) as store:\n"
            "    store.set_constants(f'root://a/p{sys.argv[2]}', {'g': 1.0}, 1.0)\n")
    helpers = [subprocess.Popen([sys.executable, "-c", code, str(directory), str(index)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for index in range(6)]
    results = [helper.communicate(timeout=60) + (helper.returncode,) for helper in helpers]
    assert all(returncode == 0 for _, _, returncode in results), [err for _, err, _ in results]
    tables, columns = schema(directory)
    assert "folder_constants" in tables and "raw_times" in columns
    with CacheStore(str(directory)) as store:
        read = store.read_constants([f"root://a/p{index}" for index in range(6)])
        assert all(value.value is not None for value in read.values())


def test_a_read_only_old_store_reads_as_none_set(tmp_path: Path) -> None:
    directory = old_store(tmp_path / "store", layout=cache_store.LAYOUT_VERSION + 1)
    with CacheStore(str(directory)) as store:
        assert store.read_only
        assert store.read_constants([f"root://{A}/run"])[f"root://{A}/run"].missing
        row = store.read_dataset_row(f"root://{A}/old").value
        assert row is not None and row.get("raw_times") == []
        with pytest.raises(StoreReadOnly):
            store.set_constants(f"root://{A}/run", {"g": 1.0}, 1.0)
    # Left as it was: a read-only store is never changed.
    tables, columns = schema(directory)
    assert "folder_constants" not in tables and "raw_times" not in columns


def test_a_rekey_skips_tables_the_store_lacks(tmp_path: Path) -> None:
    directory = old_store(tmp_path / "store")
    with CacheStore(str(directory)) as store:
        store._conn.execute("DROP TABLE folder_constants")  # (As a store this HeLab couldn't migrate.)
        store._constants_table = False
        assert store.rekey_subtree(f"root://{A}", f"root://{A}x") == [f"root://{A}/old"]


# Listings and nested roots on an old store

def write_marker(folder: Path, identifier: str) -> None:
    (folder / ".helab-root").write_text(json.dumps({
        "helab": "root", "version": 1, "uuid": identifier, "label": folder.name,
        "created_at": "2026-10-20T00:00:00Z"}), encoding="utf-8")


def share(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, Any]]:
    """An SMB share with a data root at its top, and an old store."""
    top = tmp_path / "share"
    (top / "data" / "run").mkdir(parents=True)
    write_marker(top, str(uuid.uuid4()))
    monkeypatch.setattr(cache_paths, "current_mounts", lambda: [Mount("//host/share", str(top), "smbfs", True)])
    directory = old_store(tmp_path / "cache" / "store-v3")
    return top, {"directory": str(directory)}


def test_a_listing_with_an_old_store_reads_every_saved_record(tmp_path: Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    top, cache = share(tmp_path, monkeypatch)
    for _ in range(2):  # Discovery, then the listing the app does next.
        events: list[dict[str, Any]] = []
        io_helper.list_folder(str(top), events.append, cache)
        assert not any(event["kind"] == "cache_warning" for event in events), events
        entries = [entry for event in events if event["kind"] == "entries" for entry in event["entries"]]
        assert entries and all(entry["saved_read"] and "constants" not in entry for entry in entries)


def test_a_nested_root_rekeys_flags_datasets_summaries_and_constants(tmp_path: Path,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    top, cache = share(tmp_path, monkeypatch)
    inner, run = top / "data", top / "data" / "run"
    io_helper.list_folder(str(top), lambda _: None, cache)
    with io_helper._cache_store(cache["directory"], [str(run)]) as store:
        store.set_prefs(str(run), True, False, 5.0)  # Don't cache this folder.
        store.set_constants(str(run), {"fall_distance": 0.85}, 6.0)
        store.save_record("summaries", str(run), {"owner": "outer"}, store.guard([str(run)], ["summaries"]))
        guard = store.start_dataset_job(str(inner))
        record: DatasetRecord = {"ram_bytes": 1, "rows": 1, "shots": 1, "fingerprint": [], "problematic": [],
                                 "info": {}}
        store.save_dataset(str(inner), store.write_dataset_file(b"data"), record, guard)
    inner_id = str(uuid.uuid4())
    write_marker(inner, inner_id)
    real = CacheStore.rekey_subtree
    calls: list[int] = []

    def busy_once(self: CacheStore, old: str, new: str) -> list[str]:
        calls.append(1)
        if len(calls) == 1:
            raise StoreError("Data-root subtree could not be re-keyed: database is locked")
        return real(self, old, new)

    monkeypatch.setattr(CacheStore, "rekey_subtree", busy_once)
    events: list[dict[str, Any]] = []
    io_helper.list_folder(str(inner), events.append, cache)
    # The re-key failed: the root isn't recorded either, so the next listing tries again.
    assert any(event["kind"] == "cache_warning" for event in events)
    assert not any(event["kind"] in ("root_found", "root_rekeyed") for event in events)
    with io_helper._cache_store(cache["directory"], allow_unrooted=True) as store:
        assert all(location != store._location_key(str(inner)) for location, _, _ in store.root_locations())
    events = []
    io_helper.list_folder(str(inner), events.append, cache)
    assert any(event["kind"] == "root_rekeyed" for event in events)
    with io_helper._cache_store(cache["directory"], [str(run)]) as store:
        assert store._path_key(str(run)) == f"root://{inner_id}/run"
        assert store.read_prefs([str(run)])[str(run)].value == {"no_cache": True, "no_auto_load": False,
                                                                 "set_at": 5.0}
        assert store.read_constants([str(run)])[str(run)].value == {"values": {"fall_distance": 0.85},
                                                                     "set_at": 6.0}
        assert store.read_record("summaries", str(run)).value == {"owner": "outer"}
        assert store.read_dataset_row(str(inner)).value is not None
    entry = next(entry for event in events if event["kind"] == "entries" for entry in event["entries"]
                 if entry["path"] == str(run))
    assert entry["prefs"]["no_cache"] and entry["constants"]["values"] == {"fall_distance": 0.85}


# Constants on a volume not verified this session

def test_constants_on_an_unverified_volume_wait_for_its_verification(tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    disk = tmp_path / "USB"
    run = disk / "run"
    run.mkdir(parents=True)
    write_marker(disk, str(uuid.uuid4()))
    mount = Mount("/dev/disk4s1", str(disk), "apfs")
    monkeypatch.setattr(cache_paths, "current_mounts", lambda: [mount])
    monkeypatch.setattr(data_roots, "_volume_id", lambda _: "disk-a")
    cache = {"directory": str(tmp_path / "cache" / "store-v3")}
    io_helper.list_folder(str(disk), lambda _: None, cache)
    events: list[dict[str, Any]] = []
    io_helper.cache_admin(cache, "constants", events.append, path=str(run), values={"g": 9.8}, set_at=1.0,
                          verified_volumes=[])
    assert events[0] == {"kind": "folder_constants", "folders": {},
                         "session_only": {str(run): io_helper.UNVERIFIED_CONSTANTS}}
    events = []
    io_helper.cache_admin(cache, "constants", events.append, path=str(run), values={"g": 9.8}, set_at=1.0,
                          verified_volumes=[[mount.path, mount.source]])
    assert events[0] == {"kind": "folder_constants", "folders": {str(run): {"values": {"g": 9.8}, "set_at": 1.0}}}


def frozen(monkeypatch: pytest.MonkeyPatch) -> tuple[IOService, FolderCache]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    return service, FolderCache(service)


def admin(service: IOService) -> IORequest:
    return next(r for r in reversed(service.pending) if r.operation == "cache_admin")


RUN = os.path.join(os.sep, "data", "root", "run")


def test_the_app_saves_them_again_once_volumes_are_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    assert folder_cache.UNVERIFIED_CONSTANTS == io_helper.UNVERIFIED_CONSTANTS
    assert folder_cache.NO_ROOT_CONSTANTS == io_helper.NO_ROOT_CONSTANTS
    service, cache = frozen(monkeypatch)
    try:
        assert store_options()
        cache.set_folder_constants(RUN, {"fall_distance": 0.9})
        request = admin(service)
        assert request.payload["params"]["verified_volumes"] == []
        service.resultReady.emit(request, {"kind": "folder_constants", "folders": {},
                                           "session_only": {RUN: io_helper.UNVERIFIED_CONSTANTS}})
        service.resultReady.emit(request, {"kind": "done"})
        service.pending.remove(request)
        assert cache.constants_session_only(RUN) == folder_cache.UNVERIFIED_CONSTANTS
        assert cache.folder_constants(RUN) == {"fall_distance": 0.9}
        cache._verified_volumes = (("/Volumes/USB", "/dev/disk4s1"),)
        cache.volumesVerified.emit()
        again = admin(service)
        assert again.payload["params"]["path"] == RUN and again.payload["params"]["values"] == {"fall_distance": 0.9}
        assert again.payload["params"]["verified_volumes"] == [["/Volumes/USB", "/dev/disk4s1"]]
        assert cache.constants_session_only(RUN) == ""
    finally:
        service.shutdown()


# Quitting

def test_quitting_waits_for_flags_and_constants_being_written_and_refuses_new_ones(
        monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    try:
        cache.data_roots[os.path.dirname(RUN)] = (A, "root")
        cache.set_folder_constants(RUN, {"fall_distance": 0.9})
        constants = admin(service)
        other = os.path.join(os.path.dirname(RUN), "other")
        cache.set_folder_prefs(other, no_cache=True, no_auto_load=False)
        prefs = admin(service)
        assert set(cache.quit_saves()) == {RUN, other}
        assert cache.folder_settings_saving(RUN) and cache.folder_settings_saving(other)
        changes: list[int] = []
        cache.quitSavesChanged.connect(lambda: changes.append(1))
        cache.cancel_for_quit()
        failures: list[tuple[str, str, str]] = []
        cache.folderConstantsFailed.connect(lambda *args: failures.append(args))
        cache.folderPrefsFailed.connect(lambda *args: failures.append(args))
        assert not cache.set_folder_constants(other, {"g": 1.0}, owner="tab")
        assert not cache.set_folder_prefs(RUN, no_cache=False, no_auto_load=True, owner="tab")
        assert failures == [(other, folder_cache.QUITTING, "tab"), (RUN, folder_cache.QUITTING, "tab")]
        assert cache.folder_constants(other) == {} and not cache.folder_prefs(RUN)["no_auto_load"]
        service.resultReady.emit(constants, {"kind": "done"})
        assert cache.quit_saves() == [other] and changes
        service.resultReady.emit(prefs, {"kind": "done"})
        assert cache.quit_saves() == []
    finally:
        service.shutdown()
