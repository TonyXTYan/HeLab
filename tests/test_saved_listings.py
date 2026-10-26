"""Saved folder listings (cache-only browsing C2): a ``list`` helper saves each folder it lists
below a data root (its subfolder names and own counts) after sending its status, under the save
guard it took before its scandir, best effort; the local lane reads them back without touching
the source folder. Stores from before listings gain the table when opened, and listings go with
Clear, purges by age, a root's Clear cached data… and a nested root's re-key."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import types
from typing import Any, cast

import pytest
from pytestqt.qtbot import QtBot

from helab.io_ops import listings, stores
from helab.io_ops.browse import list_folder
from helab.io_ops.listings import REFRESH_SECONDS, listing_guard, read_listing, save_listing, saved_listing
from helab.utils import cache_store
from helab.utils.cache_store import CacheStore

from test_cache_tab import admin_request, finish, frozen_cache, inventory, make_tab
from test_store_migration import A, old_store, schema


def data_folder(path: Path) -> None:
    path.mkdir(exist_ok=True)
    for name in ("run_b", "run_a"):
        (path / name).mkdir()
    for shot in (1, 2, 3):
        (path / f"d{shot}.txt").write_text("")
    for shot in (1, 2):
        (path / f"d_txy_forc{shot}.txt").write_text(f"{shot},2,3\n")


def options(tmp_path: Path) -> dict[str, Any]:
    return {"directory": str(tmp_path / "cache")}


def saved(cache: dict[str, Any], path: str) -> tuple[dict[str, Any] | None, float | None]:
    """The folder's saved listing and its row's ``saved_at`` (None, None if there is none)."""
    with stores._cache_store(cache["directory"], [path]) as store:
        record = read_listing(store, path).value
        row = store._conn.execute("SELECT saved_at FROM listings WHERE path = ?",
                                  (store._path_key(path),)).fetchone()
    return record, None if row is None else float(row[0])


def listed(path: str, cache: dict[str, Any]) -> list[Any]:
    events: list[Any] = []
    list_folder(path, events.append, cache)
    return events


def test_a_listing_saves_its_names_and_counts_and_the_local_lane_reads_them(tmp_path: Path) -> None:
    source = tmp_path / "source"
    data_folder(source)
    cache = options(tmp_path)
    events = listed(str(source), cache)
    status = next(event for event in events if event["kind"] == "status")
    record, _ = saved(cache, str(source))
    assert record is not None
    assert record["names"] == ["run_a", "run_b"]
    assert (record["status"], record["count"], record["raw_count"], record["txy_count"]) == (
        status["status"], status["count"], 3, 2)
    assert record["has_dirs"] and not record["empty"] and record["listed_at"] == status["scanned_at"]
    assert "raw" not in record and "txy" not in record  # Counts only, as a folder summary keeps.
    # The local lane reads it from the disk cache alone: the source folder may be gone.
    for child in source.iterdir():
        if child.is_dir():
            child.rmdir()
        else:
            child.unlink()
    source.rmdir()
    assert saved_listing(str(source), cache).value == record
    # A folder never listed has none; a subfolder isn't listed by its parent's listing.
    assert saved_listing(str(source / "run_a"), cache).missing


def test_an_empty_folders_listing_is_saved_too(tmp_path: Path) -> None:
    source = tmp_path / "empty"
    source.mkdir()
    cache = options(tmp_path)
    listed(str(source), cache)
    record, _ = saved(cache, str(source))
    assert record is not None and record["names"] == [] and record["empty"] and not record["has_dirs"]


@pytest.mark.no_auto_data_root
def test_a_folder_without_a_data_root_saves_no_listing(tmp_path: Path) -> None:
    source = tmp_path / "source"
    data_folder(source)
    cache = options(tmp_path)
    listed(str(source), cache)
    with CacheStore(cache["directory"], root_mode=True) as store:
        assert store._conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0


def test_an_unchanged_listing_is_written_again_only_once_an_hour_old(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    data_folder(source)
    cache, path = options(tmp_path), str(source)
    listed(path, cache)
    first, saved_at = saved(cache, path)
    assert first is not None and saved_at == first["listed_at"]
    listed(path, cache)
    assert saved(cache, path) == (first, saved_at)  # Unchanged: not written.
    (source / "run_c").mkdir()
    listed(path, cache)
    changed, changed_at = saved(cache, path)
    assert changed is not None and changed["names"] == ["run_a", "run_b", "run_c"]
    assert changed_at is not None and saved_at is not None and changed_at > saved_at
    # The same names an hour later: written again, so its date stays recent.
    later = time.time() + REFRESH_SECONDS + 1
    monkeypatch.setattr("helab.io_ops.browse.time.time", lambda: later)
    listed(path, cache)
    again, again_at = saved(cache, path)
    assert again is not None and again["names"] == changed["names"] and again_at == later


def test_an_older_listing_never_replaces_a_newer_one(tmp_path: Path) -> None:
    source = tmp_path / "source"
    data_folder(source)
    cache, path = options(tmp_path), str(source)
    events = listed(path, cache)
    newer, _ = saved(cache, path)
    status = {**next(event for event in events if event["kind"] == "status"), "scanned_at": 1000.0}
    with stores._cache_store(cache["directory"], [path]) as store:
        assert save_listing(store, listing_guard(store, path), path, ["late"], status) == "unchanged"
    assert saved(cache, path)[0] == newer


def test_two_helpers_listing_at_once_never_let_the_older_listing_win(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Vernier, review round 1: "newer wins" is decided under the write lock. Here the older helper
    looked before the newer one saved (its first look, without the lock, saw nothing), then saves."""
    source = tmp_path / "source"
    data_folder(source)
    cache, path = options(tmp_path), str(source)
    events = listed(path, cache)
    status = next(event for event in events if event["kind"] == "status")
    with stores._cache_store(cache["directory"], [path]) as store:
        store.remove(("listings",), [path])
        older_guard = listing_guard(store, path)
        newer = {**status, "scanned_at": 2000.0}
        assert save_listing(store, listing_guard(store, path), path, ["run_a", "run_b", "run_new"], newer) == "saved"
        real_read = CacheStore.read_record

        def stale(self: CacheStore, kind: Any, folder: str) -> Any:
            return cache_store._missing() if kind == "listings" else real_read(self, kind, folder)
        monkeypatch.setattr(CacheStore, "read_record", stale)
        older = {**status, "scanned_at": 1000.0}
        assert save_listing(store, older_guard, path, ["run_a"], older) == "unchanged"
        monkeypatch.setattr(CacheStore, "read_record", real_read)
        record = read_listing(store, path).value
    assert record is not None and record["listed_at"] == 2000.0 and record["names"] == ["run_a", "run_b", "run_new"]


@pytest.mark.parametrize("cleared", ["listings", "folder", "root"])
def test_a_clear_after_the_listing_started_makes_its_save_a_no_op(tmp_path: Path, cleared: str) -> None:
    source = tmp_path / "source"
    data_folder(source)
    cache, path = options(tmp_path), str(source)
    events = listed(path, cache)
    status = next(event for event in events if event["kind"] == "status")
    with stores._cache_store(cache["directory"], [path]) as store:
        guard = listing_guard(store, path)
        assert guard is not None
        if cleared == "listings":
            store.remove(("listings",))
        elif cleared == "folder":
            store.remove(("listings",), [path])
        else:
            store.clear_root(store._path_key(path)[len("root://"):].partition("/")[0])
        assert save_listing(store, guard, path, ["run_a"], status) == "skipped"
        assert read_listing(store, path).missing


def test_a_busy_store_skips_the_save_without_holding_up_the_listing(tmp_path: Path) -> None:
    source = tmp_path / "source"
    data_folder(source)
    cache, path = options(tmp_path), str(source)
    events = listed(path, cache)
    status = {**next(event for event in events if event["kind"] == "status"), "scanned_at": time.time() + 1}
    with stores._cache_store(cache["directory"], [path]) as store:
        guard = listing_guard(store, path)
        before = read_listing(store, path).value
        # Another helper holds the write lock while this listing saves.
        holder = sqlite3.connect(os.path.join(cache["directory"], "records.sqlite"), isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")
        try:
            started = time.monotonic()
            assert save_listing(store, guard, path, ["new"], status) == "skipped"
            elapsed = time.monotonic() - started
        finally:
            holder.execute("ROLLBACK")
            holder.close()
        assert elapsed < listings.WRITE_WAIT + 2  # Not the store's own (much longer) busy wait.
        assert read_listing(store, path).value == before
        # The store waits as long as before for its other work.
        assert store._conn.execute("PRAGMA busy_timeout").fetchone()[0] == int(cache_store.BUSY_TIMEOUT * 1000)


def test_a_failing_save_never_fails_the_listing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    data_folder(source)

    def fail(*args: object, **kwargs: object) -> None:
        raise cache_store.StoreError("disk full")
    monkeypatch.setattr(CacheStore, "save_listing", fail)
    events = listed(str(source), options(tmp_path))
    assert next(event for event in events if event["kind"] == "status")["count"] == 2


def test_listings_are_purged_by_age_cleared_by_kind_and_counted(tmp_path: Path) -> None:
    root = tmp_path / "data"
    data_folder(root)
    cache = options(tmp_path)
    for folder in (root, root / "run_a", root / "run_b"):
        listed(str(folder), cache)
    with stores._cache_store(cache["directory"], [str(root)]) as store:
        key = store._path_key(str(root / "run_a"))
        store._conn.execute("UPDATE listings SET saved_at = 1000 WHERE path = ?", (key,))
        inventory = store.inventory()
        assert inventory["listings"]["count"] == 3
        estimate = cache_store.purge_estimate(inventory, 2000.0, datasets=False)
        assert estimate["listings"] == 1
        removals = store.purge_records(2000.0)
        assert [(removal.kinds, removal.paths) for removal in removals] == [(("listings",), (str(root / "run_a"),))]
        assert read_listing(store, str(root / "run_a")).missing and read_listing(store, str(root)).value
        removal = store.remove(cache_store.KINDS)  # Clear all.
        assert "listings" in removal.kinds and store.inventory()["listings"]["count"] == 0


def test_a_nested_roots_rekey_moves_its_listings(tmp_path: Path) -> None:
    root = tmp_path / "data"
    data_folder(root)
    cache = options(tmp_path)
    listed(str(root / "run_a"), cache)
    with stores._cache_store(cache["directory"], [str(root / "run_a")]) as store:
        old = store._path_key(str(root / "run_a"))
        record = read_listing(store, str(root / "run_a")).value
        moved = store.rekey_subtree(old, f"root://{A}")
        assert moved == [old]
        row = store._conn.execute("SELECT record FROM listings WHERE path = ?", (f"root://{A}",)).fetchone()
        assert row is not None and json.loads(row[0]) == record


@pytest.mark.no_auto_data_root
def test_an_older_store_gains_the_listings_table_when_opened(tmp_path: Path) -> None:
    directory = old_store(tmp_path / "store")
    with sqlite3.connect(directory / "records.sqlite") as conn:  # (As before C2: no gen_listings.)
        conn.execute("DELETE FROM meta WHERE key = 'gen_listings'")
    assert "listings" not in schema(directory)[0]
    with CacheStore(str(directory)) as store:
        assert "listings" in schema(directory)[0]
        guard = store.guard([f"root://{A}/run"], ("listings",))
        store.save_record("listings", f"root://{A}/run", {"version": 1, "names": []}, guard)
        assert store.inventory()["listings"]["count"] == 1


@pytest.mark.no_auto_data_root
def test_a_read_only_store_from_before_listings_reads_them_as_missing(tmp_path: Path) -> None:
    directory = old_store(tmp_path / "store", layout=cache_store.LAYOUT_VERSION + 1)
    with CacheStore(str(directory)) as store:
        assert store.read_only
        assert store.read_record("listings", f"root://{A}/run").missing
        assert store.inventory()["listings"]["count"] == 0
        assert A in store.root_usage()
    assert "listings" not in schema(directory)[0]


def test_the_cache_tab_shows_and_clears_folder_listings(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    try:
        tab, asked = make_tab(qtbot, cache, tmp_path)
        finish(service, admin_request(service, "inventory"), {"kind": "inventory", "inventory": inventory(
            listings={"count": 7})})
        assert tab.kind_labels["listings"].text() == "7 folders"
        tab.clear(["listings"])
        assert "folder listings for 7 folders" in asked[0][1] and "offline" in asked[0][1]
        assert admin_request(service, "clear").payload["params"] == {"kinds": ["listings"]}
    finally:
        service.shutdown()


# Mount hints (cache-only browsing D1): a folder on a share that is no longer mounted keeps its key
# offline, through the share last seen at its mount path.

@pytest.mark.no_auto_data_root
def test_an_unmounted_shares_listing_is_found_offline_through_its_mount_hint(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.utils.cache_paths import Mount, current_mounts
    from helab.utils.data_roots import new_marker
    share = tmp_path / "Volumes" / "lab-data"
    share.parent.mkdir()
    data_folder(share)
    _, marker = new_marker(str(share))
    (share / ".helab-root").write_bytes(marker)
    # The mount table's own spelling of a share: macOS's mount source with its account, Windows'
    # WNetGetConnection UNC (where "user@host" is a WebDAV path, which has no disk cache).
    source, fstype = (("\\\\server.example\\LabData", "smb") if sys.platform == "win32"
                      else ("//operator@server.example/LabData", "smbfs"))
    mounted = [*current_mounts(), Mount(source, str(share), fstype, True)]
    monkeypatch.setattr(stores, "_mounts", lambda reason: mounted)
    cache = options(tmp_path)
    listed(str(share), cache)
    with CacheStore(cache["directory"], root_mode=True) as store:
        assert store.mount_hints() == {str(share): "smb://server.example/labdata"}
    # Unmounted: only an offline request keys it, through the hint.
    monkeypatch.setattr(stores, "_mounts", lambda reason: current_mounts())
    assert saved_listing(str(share), cache).missing
    found = saved_listing(str(share), {**cache, "offline": True}).value
    assert found is not None and found["names"] == ["run_a", "run_b"]
    # Another share mounted at that path now wins: the hint is not used for it.
    other = [*current_mounts(), Mount(source.replace("LabData", "Other"), str(share), fstype, True)]
    monkeypatch.setattr(stores, "_mounts", lambda reason: other)
    assert saved_listing(str(share), {**cache, "offline": True}).missing


def test_a_windows_mapped_drive_gets_a_hint_and_keys_offline_once_unmapped(monkeypatch: pytest.MonkeyPatch) -> None:
    """D1 on Windows, whatever the OS running the test: a mapped drive (``Z:``, its share from
    WNetGetConnection) is hinted, and once the drive letter is gone an offline request keys its
    folders by that share again; a drive mapped to another share now wins. The system drive is
    never hinted."""
    from helab.utils import cache_paths, data_roots
    from helab.utils.cache_paths import CachePaths, Mount
    from helab.utils.data_roots import LocalVolumes
    windows = types.SimpleNamespace(platform="win32")
    monkeypatch.setattr(cache_paths, "sys", windows)
    monkeypatch.setattr(data_roots, "sys", windows)
    monkeypatch.setenv("SystemDrive", "C:")
    drive = Mount("\\\\lab-server\\LabData", "Z:\\", "smb", True)
    system = Mount("C:\\", "C:\\", "local")
    tops = stores._mount_tops([system, drive], CachePaths([system, drive]), LocalVolumes([]),
                              ["Z:\\2026\\run_1", "C:\\Users\\lab\\data"])
    assert tops == {"Z:\\": "smb://lab-server/labdata"}
    # A "user@host" UNC is WebDAV on Windows (no disk cache): no hint (CI 40272585640's failure was
    # the test giving a share macOS's mount source there).
    webdav = Mount("\\\\operator@lab-server\\LabData", "Y:\\", "smb", True)
    assert stores._mount_tops([system, webdav], CachePaths([system, webdav]), LocalVolumes([]), ["Y:\\run"]) == {}

    class Hints:
        def __init__(self, hints: dict[str, str]) -> None:
            self.hints = hints

        def mount_hints(self) -> dict[str, str]:
            return self.hints
    hinted = Hints(tops)
    paths, _ = stores._offline_mounts(cast(Any, hinted), [system], LocalVolumes([]))
    assert paths.key("Z:\\2026\\run_1") == "smb://lab-server/labdata/2026/run_1"
    assert paths.key("z:\\2026") == "smb://lab-server/labdata/2026"  # (Drive letters ignore case.)
    other = Mount("\\\\lab-server\\Other", "Z:\\", "smb", True)
    paths, _ = stores._offline_mounts(cast(Any, hinted), [system, other], LocalVolumes([]))
    assert paths.key("Z:\\2026") == "smb://lab-server/other/2026"
    # Review rounds 1–3 on Windows: a share once mounted at a folder of the system drive is still
    # hinted (C: is transparent); a drive attached now wins over hints below it, whatever it is.
    folders = Hints({"C:\\shares\\lab": "smb://lab-server/labdata", "D:\\lab\\old": "smb://old-server/old"})
    disk = Mount("D:\\", "D:\\", "local")
    paths, _ = stores._offline_mounts(cast(Any, folders), [system, disk], LocalVolumes([]))
    assert paths.key("C:\\shares\\lab\\run") == "smb://lab-server/labdata/run"
    assert not paths.key("D:\\lab\\old\\run").startswith("smb://old-server")
