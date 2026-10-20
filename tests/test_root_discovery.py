"""D2 helper discovery and root-keyed cache behavior on fake shares."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import threading
import uuid
from typing import Any

import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before any QApplication: FolderCache tests load the views)
from pytestqt.qtbot import QtBot

from helab.io_ops import browse, infra, markers, stores
from helab.io_ops.admin import cache_admin
from helab.io_ops.browse import list_folder
from helab.io_ops.loading import load, read_cached
from helab.io_ops.markers import verify_known_roots, verify_volumes
from helab.io_ops.scanning import save_subtrees, scan
from helab.utils import cache_paths, data_roots
from helab.utils.cache_paths import Mount
from helab.utils.cache_store import CacheStore, DatasetRecord
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IORequest, IOService

pytestmark = pytest.mark.no_auto_data_root


def write_marker(folder: Path, identifier: str) -> None:
    (folder / ".helab-root").write_text(json.dumps({
        "helab": "root", "version": 1, "uuid": identifier, "label": folder.name,
        "created_at": "2026-10-18T00:00:00Z"}), encoding="utf-8")


def options(tmp_path: Path) -> dict[str, Any]:
    return {"directory": str(tmp_path / "cache" / "store-v3")}


def test_listing_discovers_marker_and_uses_root_key(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    share = tmp_path / "share"
    run = share / "run"
    run.mkdir(parents=True)
    identifier = str(uuid.uuid4())
    write_marker(share, identifier)
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("//host/share", str(share), "smbfs", True)])
    events: list[dict[str, Any]] = []
    list_folder(str(share), events.append, options(tmp_path))
    assert any(event["kind"] == "root_found" for event in events)
    assert not any(event["kind"] == "cache_skipped" for event in events)
    assert any(event["kind"] == "entries" and event["entries"][0]["path"] == str(run)
               for event in events)
    with stores._cache_store(options(tmp_path)["directory"], [str(run)]) as store:
        assert store._path_key(str(run)) == f"root://{identifier}/run"
        store.save_record("summaries", str(run), {"saved": True},
                          store.guard([str(run)], ["summaries"]))
    with sqlite3.connect(Path(options(tmp_path)["directory"]) / "records.sqlite") as conn:
        assert conn.execute("SELECT path FROM folder_summaries").fetchone()[0] == (
            f"root://{identifier}/run")


def test_late_nested_marker_rekeys_rows(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    share = tmp_path / "share"
    inner = share / "data"
    run = inner / "run"
    run.mkdir(parents=True)
    outer_id, inner_id = str(uuid.uuid4()), str(uuid.uuid4())
    write_marker(share, outer_id)
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("//host/share", str(share), "smbfs", True)])
    cache = options(tmp_path)
    list_folder(str(share), lambda _: None, cache)
    with stores._cache_store(cache["directory"], [str(run)]) as store:
        store.save_record("summaries", str(run), {"owner": "outer"},
                          store.guard([str(run)], ["summaries"]))
    write_marker(inner, inner_id)
    events: list[dict[str, Any]] = []
    list_folder(str(inner), events.append, cache)
    assert any(event["kind"] == "root_rekeyed" for event in events)
    with stores._cache_store(cache["directory"], [str(run)]) as store:
        assert store._path_key(str(run)) == f"root://{inner_id}/run"
        assert store.read_record("summaries", str(run)).value == {"owner": "outer"}


def test_removed_marker_disables_disk_cache(tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    share = tmp_path / "share"
    share.mkdir()
    write_marker(share, str(uuid.uuid4()))
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("//host/share", str(share), "smbfs", True)])
    cache = options(tmp_path)
    list_folder(str(share), lambda _: None, cache)
    (share / ".helab-root").unlink()
    events: list[dict[str, Any]] = []
    list_folder(str(share), events.append, cache)
    assert any(event["kind"] == "root_changed" and event.get("reason") == "marker removed"
               for event in events)
    assert any(event["kind"] == "cache_skipped" for event in events)


def test_new_equivalent_location_waits_for_confirmation(tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    identifier = str(uuid.uuid4())
    write_marker(first, identifier)
    write_marker(second, identifier)
    monkeypatch.setattr(cache_paths, "current_mounts", lambda: [
        Mount("//host/first", str(first), "smbfs", True),
        Mount("//host/second", str(second), "smbfs", True)])
    cache = options(tmp_path)
    list_folder(str(first), lambda _: None, cache)
    events: list[dict[str, Any]] = []
    list_folder(str(second), events.append, cache)
    assert any(event["kind"] == "root_duplicate" for event in events)
    assert any(event["kind"] == "cache_skipped" for event in events)
    with CacheStore(cache["directory"], root_mode=True) as store:
        assert store.root_at("smb://host/second") == (identifier, "b", "pending")


def test_pending_nested_root_blocks_outer_root_cache(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    share = tmp_path / "share"
    nested = share / "copy"
    nested.mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    duplicate_id = str(uuid.uuid4())
    write_marker(share, str(uuid.uuid4()))
    write_marker(other, duplicate_id)
    write_marker(nested, duplicate_id)
    monkeypatch.setattr(cache_paths, "current_mounts", lambda: [
        Mount("//host/share", str(share), "smbfs", True),
        Mount("//host/other", str(other), "smbfs", True)])
    cache = options(tmp_path)
    list_folder(str(share), lambda _: None, cache)
    list_folder(str(other), lambda _: None, cache)
    events: list[dict[str, Any]] = []
    list_folder(str(nested), events.append, cache)
    assert any(event["kind"] == "root_duplicate" for event in events)
    assert any(event["kind"] == "cache_skipped" for event in events)


def test_replacing_one_alias_marker_leaves_shared_cache_with_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    old_id, new_id = str(uuid.uuid4()), str(uuid.uuid4())
    write_marker(first, old_id)
    write_marker(second, old_id)
    monkeypatch.setattr(cache_paths, "current_mounts", lambda: [
        Mount("//host/first", str(first), "smbfs", True),
        Mount("//host/second", str(second), "smbfs", True)])
    cache = options(tmp_path)
    list_folder(str(first), lambda _: None, cache)
    with stores._cache_store(cache["directory"], [str(first)]) as store:
        store.record_root("smb://host/second", old_id, "smb", "second", decision="confirmed")
        store.save_record("summaries", str(first), {"owner": "original"},
                          store.guard([str(first)], ["summaries"]))
    write_marker(second, new_id)
    events: list[dict[str, Any]] = []
    list_folder(str(second), events.append, cache)
    assert not any(event["kind"] == "root_rekeyed" for event in events)
    with stores._cache_store(cache["directory"], [str(first)]) as store:
        assert store.read_record("summaries", str(first)).value == {"owner": "original"}
        assert store._path_key(str(first)) == f"root://{old_id}"
        assert store._path_key(str(second)) == f"root://{new_id}"


def test_mixed_case_source_path_survives_cache_admin_event(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "share"
    run = root / "Run_042A"
    run.mkdir(parents=True)
    (run / "d_txy_forc1.txt").write_text("1,2,3\n")
    write_marker(root, str(uuid.uuid4()))
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("//host/share", str(root), "smbfs", True)])
    cache = options(tmp_path)
    list_folder(str(root), lambda _: None, cache)
    with stores._cache_store(cache["directory"], [str(run)]) as store:
        guard = store.start_dataset_job(str(run))
        record: DatasetRecord = {"ram_bytes": 1, "rows": 1, "shots": 1,
                                 "fingerprint": [], "problematic": [], "info": {}}
        store.save_dataset(str(run), store.write_dataset_file(b"data"), record, guard)
    events: list[dict[str, Any]] = []
    cache_admin(cache, "trim", events.append, budget=0)
    assert next(event for event in events if event["kind"] == "removed")["paths"] == [str(run)]
    with stores._cache_store(cache["directory"], [str(run)]) as store:
        guard = store.start_dataset_job(str(run))
        store.add_pending(str(run), store.write_dataset_file(b"data"), record, guard, "needs_approval")
        root_record = store.root_at("smb://host/share")
        assert root_record is not None
        assert conn_keys(store) == [f"root://{root_record[0]}/Run_042A"]  # The source's spelling.
    events = []
    cache_admin(cache, "inventory", events.append)
    inventory = next(event for event in events if event["kind"] == "inventory")["inventory"]
    assert [entry["path"] for entry in inventory["pending"]] == [str(run)]


def conn_keys(store: CacheStore) -> list[str]:
    return [row[0] for row in store._conn.execute("SELECT path FROM pending_saves")]


def test_transient_marker_read_error_keeps_confirmed_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "share"
    root.mkdir()
    identifier = str(uuid.uuid4())
    write_marker(root, identifier)
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("//host/share", str(root), "smbfs", True)])
    cache = options(tmp_path)
    list_folder(str(root), lambda _: None, cache)

    def unavailable(_: str) -> data_roots.Marker:
        raise PermissionError("temporary share failure")

    monkeypatch.setattr(data_roots, "read_marker", unavailable)
    events: list[dict[str, Any]] = []
    list_folder(str(root), events.append, cache)
    assert any(event["kind"] == "cache_warning" for event in events)
    with CacheStore(cache["directory"], root_mode=True) as store:
        assert store.root_at("smb://host/share") == (identifier, "share", "confirmed")


def test_local_lane_uses_saved_volume_id_without_source_probe(tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "data"
    folder.mkdir()
    identifier = str(uuid.uuid4())
    write_marker(folder, identifier)
    mount = Mount("/dev/fake", str(tmp_path), "apfs")
    monkeypatch.setattr(cache_paths, "current_mounts", lambda: [mount])
    monkeypatch.setattr(data_roots, "_volume_id", lambda _: "test-volume")
    cache = options(tmp_path)
    list_folder(str(folder), lambda _: None, cache)

    def forbidden(_: Mount) -> str:
        raise AssertionError("local lane probed a source volume")

    monkeypatch.setattr(data_roots, "_volume_id", forbidden)
    with stores._cache_store(cache["directory"], [str(folder)], local_lane=True) as store:
        assert store._path_key(str(folder)) == f"root://{identifier}"


def test_verification_replaces_reused_usb_mount_hint_before_cached_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "USB"
    folder.mkdir()
    write_marker(folder, str(uuid.uuid4()))
    mount = Mount("/dev/disk4s1", str(folder), "apfs")
    monkeypatch.setattr(cache_paths, "current_mounts", lambda: [mount])
    monkeypatch.setattr(data_roots, "_volume_id", lambda _: "disk-a")
    cache = options(tmp_path)
    list_folder(str(folder), lambda _: None, cache)
    monkeypatch.setattr(infra, "_volume_id_cache", {})  # A new source-helper process.
    monkeypatch.setattr(data_roots, "_volume_id", lambda _: "disk-b")
    verify_known_roots(cache, lambda _: None)
    with stores._cache_store(cache["directory"], [str(folder)], local_lane=True,
                             allow_unrooted=True) as store:
        with pytest.raises(data_roots.NoDataRoot):
            store._path_key(str(folder))


def usb_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Mount, dict[str, Any]]:
    """A cached folder on a removable disk, its volume hint saved by a listing."""
    disk = tmp_path / "USB"
    run = disk / "run"
    run.mkdir(parents=True)
    write_marker(disk, str(uuid.uuid4()))
    mount = Mount("/dev/disk4s1", str(disk), "apfs")
    monkeypatch.setattr(cache_paths, "current_mounts", lambda: [mount])
    monkeypatch.setattr(data_roots, "_volume_id", lambda _: "disk-a")
    cache = options(tmp_path)
    list_folder(str(disk), lambda _: None, cache)
    with stores._cache_store(cache["directory"], [str(run)]) as store:
        guard = store.start_dataset_job(str(run))
        record: DatasetRecord = {"ram_bytes": 1, "rows": 1, "shots": 1,
                                 "fingerprint": [], "problematic": [], "info": {}}
        store.save_dataset(str(run), store.write_dataset_file(b"data"), record, guard)
    return run, mount, cache


def test_cached_read_waits_for_its_volume_to_be_verified(tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    run, mount, cache = usb_root(tmp_path, monkeypatch)
    output = tmp_path / "output"
    output.mkdir()
    events: list[dict[str, Any]] = []
    with pytest.raises(data_roots.VolumeUnverified):
        read_cached(str(run), str(output), events.append, cache, verified_volumes=[])
    # Not "Disk cache off": the read waits, it isn't refused.
    assert not any(event["kind"] in ("cache_skipped", "cache_warning") for event in events)
    with stores._cache_store(cache["directory"], [str(run)], local_lane=True,
                             verified_volumes=[[mount.path, mount.source]]) as store:
        assert store.read_dataset_row(str(run)).value is not None


def test_system_volume_hint_needs_no_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run, mount, cache = usb_root(tmp_path, monkeypatch)
    fixed_mount = data_roots.fixed_mount
    with monkeypatch.context() as patch:
        patch.setattr(data_roots, "fixed_mount", lambda candidate: candidate == mount)
        with stores._cache_store(cache["directory"], [str(run)], local_lane=True,
                                 verified_volumes=[]) as store:
            assert store.read_dataset_row(str(run)).value is not None
    assert fixed_mount(Mount("/dev/disk3s5", "/System/Volumes/Data", "apfs")) or os.name == "nt"
    assert not fixed_mount(Mount("/dev/disk4s1", "/Volumes/USB", "apfs"))


def test_verification_reports_checked_volumes_before_visiting_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, mount, cache = usb_root(tmp_path, monkeypatch)
    monkeypatch.setattr(infra, "_volume_id_cache", {})
    monkeypatch.setattr(data_roots, "_volume_id", lambda _: "disk-b")  # Another disk, same mount.
    events: list[dict[str, Any]] = []
    verify_known_roots(cache, events.append)
    kinds = [event["kind"] for event in events if event["kind"] != "heartbeat"]
    assert kinds.index("volumes_verified") < kinds.index("roots_verified")
    verified = next(event for event in events if event["kind"] == "volumes_verified")["volumes"]
    assert verified == [[mount.path, mount.source]]
    # Disk B's marker isn't known yet at this location's new volume ID: no cached data shows.
    with stores._cache_store(cache["directory"], [], local_lane=True, verified_volumes=verified) as store:
        with pytest.raises(data_roots.NoDataRoot):
            store._path_key(str(run))


def test_volume_check_alone_refreshes_hints_without_visiting_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``volumes_verify`` runs on the local lane: volume IDs only, never a source folder."""
    run, mount, cache = usb_root(tmp_path, monkeypatch)
    monkeypatch.setattr(infra, "_volume_id_cache", {})
    monkeypatch.setattr(data_roots, "_volume_id", lambda _: "disk-b")
    monkeypatch.setattr(os, "lstat", lambda *_: pytest.fail("visited a source folder"))
    monkeypatch.setattr(data_roots, "read_marker", lambda _: pytest.fail("read a marker"))
    events: list[dict[str, Any]] = []
    verify_volumes(cache, events.append)
    assert events == [{"kind": "volumes_verified", "volumes": [[mount.path, mount.source]],
                       "ids": [[mount.path, mount.source, "disk-b"]]}]
    with CacheStore(cache["directory"], root_mode=True) as store:
        assert ("disk-b" in {identifier for _, _, identifier in store.volume_locations()})


def test_writes_on_an_unverified_volume_are_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run, mount, cache = usb_root(tmp_path, monkeypatch)
    record = {"path": str(run), "status": "something", "count": 1}
    events: list[dict[str, Any]] = []
    save_subtrees(cache, [record], events.append, verified_volumes=[])
    assert events[-1] == {"kind": "subtree_saved", "paths": [], "skipped": [str(run)]}
    events = []
    save_subtrees(cache, [record], events.append, verified_volumes=[[mount.path, mount.source]])
    assert events[-1] == {"kind": "subtree_saved", "paths": [str(run)]}


def test_verification_keeps_a_root_whose_marker_cannot_be_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "share"
    root.mkdir()
    identifier = str(uuid.uuid4())
    write_marker(root, identifier)
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("//host/share", str(root), "smbfs", True)])
    cache = options(tmp_path)
    list_folder(str(root), lambda _: None, cache)
    real_lstat = os.lstat

    def lstat(target: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        if str(target).endswith(data_roots.MARKER_NAME):
            raise PermissionError("temporary share failure")
        return real_lstat(target, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", lstat)
    verify_known_roots(cache, lambda _: None)
    with CacheStore(cache["directory"], root_mode=True) as store:
        assert store.root_at("smb://host/share") == (identifier, "share", "confirmed")


def test_background_verifies_only_known_marker_folders(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    write_marker(root, str(uuid.uuid4()))
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("//host/share", str(root), "smbfs", True)])
    cache = options(tmp_path)
    list_folder(str(root), lambda _: None, cache)
    (root / ".helab-root").unlink()
    events: list[dict[str, Any]] = []
    verify_known_roots(cache, events.append)
    assert any(event["kind"] == "root_changed" and event.get("reason") == "marker removed"
               for event in events)
    assert events[-1] == {"kind": "roots_verified", "mounts": [[str(root), "//host/share"]]}
    with CacheStore(cache["directory"], root_mode=True) as store:
        assert store.root_locations() == []
    assert child.exists()


def test_marker_does_not_change_folder_counts_or_signature(tmp_path: Path) -> None:
    folder = tmp_path / "source"
    folder.mkdir()
    (folder / "d_txy_forc1.txt").write_text("1,2,3\n")

    def status() -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        scan(str(folder), events.append, None)
        return next(event for event in events if event["kind"] == "status")

    before = status()
    write_marker(folder, str(uuid.uuid4()))
    after = status()
    assert (before["count"], before["files"], before["signature"]) == (
        after["count"], after["files"], after["signature"])


def test_listing_sends_first_batch_before_scandir_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "source"
    folder.mkdir()
    batch_sent = threading.Event()
    finish_listing = threading.Event()
    events: list[dict[str, Any]] = []

    class Entry:
        def __init__(self, index: int) -> None:
            self.name = f"run_{index}"
            self.path = str(folder / self.name)

        def is_dir(self, *, follow_symlinks: bool = False) -> bool:
            return True

    class Directory:
        def __enter__(self) -> Directory:
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def __iter__(self) -> Any:
            for index in range(128):
                yield Entry(index)
            assert finish_listing.wait(5)
            yield Entry(128)

    real_scandir = os.scandir
    monkeypatch.setattr(os, "scandir", lambda target: Directory() if str(target) == str(folder)
                        else real_scandir(target))
    monkeypatch.setattr(browse, "_mount_fingerprint", lambda: [])

    def collect(event: dict[str, Any]) -> None:
        events.append(event)
        if event["kind"] == "entries":
            batch_sent.set()

    worker = threading.Thread(target=browse.list_folder, args=(str(folder), collect))
    worker.start()
    try:
        assert batch_sent.wait(5)
        assert worker.is_alive()
        assert len(next(event for event in events if event["kind"] == "entries")["entries"]) == 128
    finally:
        finish_listing.set()
        worker.join(5)
    assert not worker.is_alive()


def test_marker_found_only_by_the_scandir_resends_entries_with_its_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A nested marker written between the lstat and the scandir: the names streamed under the
    outer root are sent again (``replace``) with the records re-keyed to the new root."""
    outer = tmp_path / "share"
    inner = outer / "copy"
    run = inner / "run"
    run.mkdir(parents=True)
    write_marker(outer, str(uuid.uuid4()))
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("//host/share", str(outer), "smbfs", True)])
    cache = options(tmp_path)
    list_folder(str(outer), lambda _: None, cache)
    (run / "d_txy_forc1.txt").write_text("1,2,3\n")
    scan(str(run), lambda _: None, cache)  # Its summary, saved under the outer root.
    real_scandir = os.scandir
    inner_id = str(uuid.uuid4())

    def scandir(target: Any) -> Any:
        if str(target) == str(inner):
            write_marker(inner, inner_id)  # Appears once the lstat has looked.
        return real_scandir(target)

    monkeypatch.setattr(os, "scandir", scandir)
    events: list[dict[str, Any]] = []
    list_folder(str(inner), events.append, cache)
    batches = [event for event in events if event["kind"] == "entries"]
    assert [event.get("replace", False) for event in batches] == [False, True]
    assert [entry["path"] for entry in batches[1]["entries"]] == [str(run)]
    saved = batches[1]["entries"][0]["scan_status"]
    assert saved and saved == batches[0]["entries"][0]["scan_status"]
    assert any(event["kind"] == "root_rekeyed" for event in events)
    with stores._cache_store(cache["directory"], [str(run)]) as store:
        assert store._path_key(str(run)) == f"root://{inner_id}/run"


def test_listing_an_unmarked_subfolder_skips_discovery(tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "share"
    run = root / "run"
    (run / "shot").mkdir(parents=True)
    write_marker(root, str(uuid.uuid4()))
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("//host/share", str(root), "smbfs", True)])
    cache = options(tmp_path)
    list_folder(str(root), lambda _: None, cache)
    discovered: list[str] = []
    original = markers._discover_root

    def discover(path: str, present: bool, *args: Any) -> bool:
        discovered.append(path)
        return original(path, present, *args)

    monkeypatch.setattr(markers, "_discover_root", discover)
    events: list[dict[str, Any]] = []
    list_folder(str(run), events.append, cache)
    assert discovered == []  # No marker, and the open store has no row here to forget.
    assert [entry["path"] for event in events if event["kind"] == "entries"
            for entry in event["entries"]] == [str(run / "shot")]


def test_listing_with_a_known_marker_streams_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "share"
    (root / "run").mkdir(parents=True)
    write_marker(root, str(uuid.uuid4()))
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("//host/share", str(root), "smbfs", True)])
    cache = options(tmp_path)
    for _ in range(2):  # Found, then known.
        events: list[dict[str, Any]] = []
        list_folder(str(root), events.append, cache)
        assert [event.get("replace", False) for event in events if event["kind"] == "entries"] == [False]
        assert not any(event["kind"] == "cache_skipped" for event in events)


@pytest.fixture
def unrooted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, Any]]:
    folder = tmp_path / "unrooted"
    folder.mkdir()
    (folder / "d_txy_forc1.txt").write_text("1,2,3\n")
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("/dev/fake", str(tmp_path), "apfs")])
    monkeypatch.setattr(data_roots, "_volume_id", lambda _: "test-volume")
    return folder, options(tmp_path)


def assert_no_cached_rows(cache: dict[str, Any]) -> None:
    with CacheStore(cache["directory"], root_mode=True) as store:
        for table in ("datasets", "folder_summaries", "scan_histories", "subtrees"):
            assert store._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_unrooted_listing_is_ram_only(unrooted: tuple[Path, dict[str, Any]]) -> None:
    folder, cache = unrooted
    events: list[dict[str, Any]] = []
    list_folder(str(folder), events.append, cache)
    assert any(event["kind"] == "status" for event in events)
    assert sum(event["kind"] == "cache_skipped" for event in events) == 1
    assert_no_cached_rows(cache)


def test_unrooted_details_is_ram_only(unrooted: tuple[Path, dict[str, Any]]) -> None:
    folder, cache = unrooted
    events: list[dict[str, Any]] = []
    scan(str(folder), events.append, cache, manual=True)
    assert any(event["kind"] == "status" for event in events)
    assert any(event["kind"] == "cache_skipped" for event in events)
    assert_no_cached_rows(cache)


def test_unrooted_cached_read_reads_nothing(unrooted: tuple[Path, dict[str, Any]],
                                            tmp_path: Path) -> None:
    folder, cache = unrooted
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(ValueError, match="Disk cache unavailable"):
        read_cached(str(folder), str(output), lambda _: None, cache)
    assert not list(output.iterdir())
    assert_no_cached_rows(cache)


def test_unrooted_load_reads_source_without_saving(unrooted: tuple[Path, dict[str, Any]],
                                                   tmp_path: Path) -> None:
    folder, cache = unrooted
    output = tmp_path / "output"
    output.mkdir()
    events: list[dict[str, Any]] = []
    load(str(folder), str(output), events.append, cache)
    assert any(event["kind"] == "loaded" for event in events)
    assert any(event["kind"] == "cache_skipped" for event in events)
    assert_no_cached_rows(cache)


def test_unrooted_subtree_save_skips_row(unrooted: tuple[Path, dict[str, Any]]) -> None:
    folder, cache = unrooted
    events: list[dict[str, Any]] = []
    save_subtrees(cache, [{"path": str(folder), "status": "something"}], events.append)
    assert events[-1] == {"kind": "subtree_saved", "paths": [], "skipped": [str(folder)]}
    assert_no_cached_rows(cache)


def test_verification_is_asked_once_per_mount_table_and_waits_behind_other_background_work(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    cache = FolderCache(service)
    monkeypatch.setattr("helab.utils.folder_cache.store_options", lambda: options(tmp_path))
    listing = IORequest("tab", 0, str(tmp_path), "list", {}, 60.0)

    def seen(*mounts: list[str]) -> None:
        service.resultReady.emit(listing, {"kind": "mounts_seen", "mounts": list(mounts)})
        qtbot.waitUntil(lambda: not cache._deliveries)

    def queued(operation: str) -> list[IORequest]:
        return [request for request in service.pending if request.operation == operation]

    try:
        seen(["/", "disk1"])
        volumes = queued("volumes_verify")
        # The marker check follows the volume check, and reuses its IDs.
        assert len(volumes) == 1 and not queued("roots_verify")
        service.resultReady.emit(volumes[0], {"kind": "done"})
        service.pending.remove(volumes[0])
        assert len(queued("roots_verify")) == 1
        seen(["/", "disk1"])  # Listed again while the roots check waits: nothing new to verify.
        assert not queued("volumes_verify") and len(queued("roots_verify")) == 1
        seen(["/", "disk1"], ["/Volumes/USB", "disk2"])  # A disk appeared: its volume ID is checked.
        assert len(queued("volumes_verify")) == 1 and len(queued("roots_verify")) == 1
        # Maintenance nothing waits for goes after background work queued later.
        assert service.submit("tab", 0, str(tmp_path), "details")
        background = [request.operation for request in service.pending if request.operation != "volumes_verify"]
        assert background == ["details", "roots_verify"]
    finally:
        service.shutdown()


def test_a_verification_never_asks_again_for_the_table_it_saw_itself(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Only listings ask: a check that saw another table than they reported ends there (it used to
    start again at once, back to back, until the next listing). A table reported while a check runs
    gets one more check after it, unless that check saw the same table."""
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    cache = FolderCache(service)
    monkeypatch.setattr(cache, "VERIFY_MIN_SECONDS", 0.0)
    monkeypatch.setattr("helab.utils.folder_cache.store_options", lambda: options(tmp_path))
    listing = IORequest("tab", 0, str(tmp_path), "list", {}, 60.0)

    def seen(*mounts: list[str]) -> None:
        service.resultReady.emit(listing, {"kind": "mounts_seen", "mounts": list(mounts)})

    def queued(operation: str) -> list[IORequest]:
        return [request for request in service.pending if request.operation == operation]

    def start(operation: str) -> IORequest:
        """As ``IOService._start``, without the helper."""
        (request,) = queued(operation)
        assert service.before_start is not None
        service.before_start(request)
        service.pending.remove(request)
        service.active.append(request)
        return request

    def finish(request: IORequest, *events: dict[str, Any]) -> None:
        for event in (*events, {"kind": "done"}):
            service.resultReady.emit(request, event)
        service.active.remove(request)

    try:
        first, second, third = ["/", "disk1"], ["/Volumes/USB", "disk2"], ["/Volumes/Other", "disk3"]
        seen(first)
        volumes = start("volumes_verify")
        seen(first, second)  # While the volume check runs: one more after it.
        finish(volumes, {"kind": "volumes_verified", "volumes": [], "ids": []})
        volumes = start("volumes_verify")
        assert not queued("roots_verify")
        finish(volumes, {"kind": "volumes_verified", "volumes": [first], "ids": [[*first, "id1"]]})
        markers = start("roots_verify")
        # The marker check reuses the volume check's IDs.
        assert markers.payload["volume_ids"] == [[*first, "id1"]]
        # It saw a table the listings didn't report (a disk came and went): no new check.
        finish(markers, {"kind": "roots_verified", "mounts": [first, third]})
        assert not queued("roots_verify") and not queued("volumes_verify")
        # A listing reports the table that check saw: nothing to do.
        seen(first, third)
        assert not queued("roots_verify") and not queued("volumes_verify")
        # A new table while a check runs: one more check after it, then none.
        seen(first, second)
        finish(start("volumes_verify"), {"kind": "volumes_verified", "volumes": [], "ids": []})
        markers = start("roots_verify")
        seen(second)
        seen(second)
        finish(markers, {"kind": "roots_verified", "mounts": [first, second]})
        finish(start("volumes_verify"))
        markers = start("roots_verify")
        finish(markers, {"kind": "roots_verified", "mounts": [first]})
        assert not queued("roots_verify") and not queued("volumes_verify")
        # A failed check isn't retried until a listing reports a table again.
        seen(third)
        finish(start("volumes_verify"))
        markers = start("roots_verify")
        service.resultReady.emit(markers, {"kind": "error", "message": "store locked"})
        service.active.remove(markers)
        assert not queued("roots_verify") and not queued("volumes_verify")
    finally:
        service.shutdown()
