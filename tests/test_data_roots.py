"""D1: marker identities and an isolated root-keyed store, without runtime wiring."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid

import pytest

from helab.utils.cache_paths import CachePaths, Mount, UnresolvedRemotePath
from helab.utils.cache_store import CacheStore, ROOT_LAYOUT_VERSION, ROOT_STORE_DIRNAME, StoreError
from helab.utils.data_roots import (
    DataRoots, LocalVolumes, Marker, NoDataRoot, RootLocation, current_local_volumes,
    _mac_volume_id_from_plist, parse_marker, read_marker,
)


def marker(folder: Path, identifier: str, label: str = "data", **extra: object) -> Marker:
    folder.mkdir(parents=True, exist_ok=True)
    contents = {"helab": "root", "version": 1, "uuid": identifier,
                "label": label, "created_at": "2026-10-18T00:00:00Z", **extra}
    (folder / ".helab-root").write_text(json.dumps(contents), encoding="utf-8")
    return read_marker(str(folder))


def resolver(mounts: list[Mount], rows: list[RootLocation],
             volumes: LocalVolumes | None = None) -> DataRoots:
    local = volumes or LocalVolumes([])
    return DataRoots(CachePaths(mounts), rows, local_location=local.location,
                     local_source=local.source)


def test_location_matching_ignores_case_on_smb_and_windows_volumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identifier = str(uuid.uuid4())
    share = resolver([Mount("//host/share", "/Volumes/Share", "smbfs", True)],
                     [RootLocation("smb://host/share/Data", identifier)])
    assert share.key("/Volumes/Share/data/Run") == f"root://{identifier}/Run"
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "win32")
        volume = LocalVolumes([(Mount("C:\\", "C:\\", "local"), "1234abcd")])
        local = DataRoots(CachePaths([]), [RootLocation("vol://1234abcd/Data", identifier)],
                          local_location=volume.location, local_source=volume.source,
                          case_insensitive_volumes=True)
        assert local.key("C:\\data\\Run") == f"root://{identifier}/Run"


def test_nested_markers_nearest_wins_and_store_uses_root_keys(tmp_path: Path) -> None:
    outer = tmp_path / "share"
    inner = outer / "data"
    first = marker(outer, str(uuid.uuid4()), "outer")
    second = marker(inner, str(uuid.uuid4()), "inner", future_field="ignored")
    mounts = [Mount("//host/Share", str(outer), "smbfs", True)]
    root = tmp_path / ROOT_STORE_DIRNAME
    with CacheStore(str(root), root_mode=True) as store:
        store.record_root("smb://host/share", first.uuid, "smb", first.label, decision="confirmed")
        store.record_root("smb://host/share/data", second.uuid, "smb", second.label, decision="confirmed")
        rows = [RootLocation(*row) for row in store.root_locations()]
    paths = resolver(mounts, rows)
    outer_run = str(outer / "other" / "run")
    inner_run = str(inner / "run")
    assert paths.key(outer_run) == f"root://{first.uuid}/other/run"
    assert paths.key(inner_run) == f"root://{second.uuid}/run"
    with CacheStore(str(root), path_key=paths.key, source_path=paths.source,
                    root_mode=True) as store:
        assert store.layout_version == ROOT_LAYOUT_VERSION
        guard = store.guard([outer_run, inner_run], ["summaries"])
        store.save_record("summaries", outer_run, {"root": "outer"}, guard)
        store.save_record("summaries", inner_run, {"root": "inner"}, guard)
        assert store.read_record("summaries", inner_run).value == {"root": "inner"}
        with sqlite3.connect(store.database) as conn:
            assert {row[0] for row in conn.execute("SELECT path FROM folder_summaries")} == {
                f"root://{first.uuid}/other/run", f"root://{second.uuid}/run"}


def test_equivalent_locations_share_data_and_source_uses_mounted_alias(tmp_path: Path) -> None:
    identifier = str(uuid.uuid4())
    first = tmp_path / "mount-a"
    second = tmp_path / "mount-b"
    marker(first, identifier)
    marker(second, identifier)
    rows = [RootLocation("smb://host/share/data", identifier),
            RootLocation("smb://host/data", identifier)]
    before = resolver([Mount("//host/share/data", str(first), "smbfs", True)], rows)
    after = resolver([Mount("//host/data", str(second), "smbfs", True)], rows)
    assert before.key(str(first / "run")) == after.key(str(second / "run"))
    key = before.key(str(first / "run"))
    assert after.source(key) == str(second / "run")
    root = tmp_path / ROOT_STORE_DIRNAME
    with CacheStore(str(root), path_key=before.key, source_path=before.source,
                    root_mode=True) as store:
        store.save_record("summaries", str(first / "run"), {"shared": True},
                          store.guard([str(first / "run")], ["summaries"]))
    with CacheStore(str(root), path_key=after.key, source_path=after.source,
                    root_mode=True) as store:
        assert store.read_record("summaries", str(second / "run")).value == {"shared": True}


def test_no_marker_refuses_reads_and_writes(tmp_path: Path) -> None:
    mount = tmp_path / "share"
    mount.mkdir()
    paths = resolver([Mount("//host/share", str(mount), "smbfs", True)], [])
    source = str(mount / "run")
    root = tmp_path / ROOT_STORE_DIRNAME
    with CacheStore(str(root), path_key=paths.key, source_path=paths.source,
                    root_mode=True) as store:
        with pytest.raises((NoDataRoot, UnresolvedRemotePath)):
            store.read_record("summaries", source)
        with pytest.raises((NoDataRoot, UnresolvedRemotePath)):
            store.guard([source], ["summaries"])
        with sqlite3.connect(store.database) as conn:
            assert conn.execute("SELECT COUNT(*) FROM folder_summaries").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM folder_epochs").fetchone()[0] == 0


def test_local_volume_ids_are_locations_only_and_separate_same_named_disks(tmp_path: Path) -> None:
    path = str(tmp_path / "USB" / "run")
    first_uuid, second_uuid = str(uuid.uuid4()), str(uuid.uuid4())
    mount = Mount("/dev/disk5", str(tmp_path / "USB"), "apfs")
    first_volume = current_local_volumes([mount], paths=[path], id_reader=lambda _: "volume-a")
    second_volume = current_local_volumes([mount], paths=[path], id_reader=lambda _: "volume-b")
    first = resolver([mount], [RootLocation("vol://volume-a", first_uuid)], first_volume)
    second = resolver([mount], [RootLocation("vol://volume-b", second_uuid)], second_volume)
    assert first_volume.location(path) == "vol://volume-a/run"
    assert first.key(path) == f"root://{first_uuid}/run"
    assert second.key(path) == f"root://{second_uuid}/run"
    assert first.source(f"root://{first_uuid}/run") == path
    assert second.source(f"root://{second_uuid}/run") == path


def test_startup_disk_firmlink_uses_volume_group_id_without_data_identity() -> None:
    mount = Mount("/dev/disk3s1", "/", "apfs")
    volumes = current_local_volumes([mount], paths=["/Users/tony/data/run"],
                                    id_reader=lambda _: "APFS-GROUP-ID")
    source = "/Users/tony/data/run"
    assert volumes.location(source) == "vol://apfs-group-id/Users/tony/data/run"
    identifier = str(uuid.uuid4())
    paths = resolver([mount], [RootLocation("vol://apfs-group-id/Users/tony/data", identifier)], volumes)
    assert paths.key(source) == f"root://{identifier}/run"


def test_windows_drive_letter_uses_injected_serial(monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "win32")
        mount = Mount("C:\\", "C:\\", "ntfs")
        volumes = current_local_volumes([mount], paths=["C:\\data\\run"],
                                        id_reader=lambda _: "1234abcd")
        source = "C:\\data\\run"
        identifier = str(uuid.uuid4())
        paths = resolver([mount], [RootLocation("vol://1234abcd/data", identifier)], volumes)
        assert volumes.location(source) == "vol://1234abcd/data/run"
        assert paths.key(source) == f"root://{identifier}/run"
        assert paths.source(f"root://{identifier}/run") == source


@pytest.mark.parametrize("change", [
    {"version": 2}, {"version": True}, {"uuid": "not-a-uuid"},
    {"label": "../data"}, {"label": "a/b"}, {"label": "a\\b"},
    {"created_at": "not-a-date"},
])
def test_bad_marker_is_not_a_root(tmp_path: Path, change: dict[str, object]) -> None:
    folder = tmp_path / "data"
    folder.mkdir()
    contents = {"helab": "root", "version": 1, "uuid": str(uuid.uuid4()),
                "label": "data", "created_at": "2026-10-18T00:00:00Z", **change}
    (folder / ".helab-root").write_text(json.dumps(contents), encoding="utf-8")
    with pytest.raises(ValueError):
        read_marker(str(folder))
    paths = resolver([Mount("//host/share", str(folder), "smbfs", True)], [])
    with pytest.raises(NoDataRoot):
        paths.key(str(folder / "run"))


def test_marker_size_is_bounded() -> None:
    with pytest.raises(ValueError, match="too large"):
        parse_marker(b"x" * (64 * 1024 + 1))


def test_mac_plist_prefers_group_id_over_snapshot_uuid() -> None:
    # Reduced from `diskutil info -plist /`: the actual key ends in ID, not UUID.
    raw = b'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>APFSVolumeGroupID</key><string>GROUP-UUID</string>
<key>VolumeUUID</key><string>SYSTEM-SNAPSHOT-UUID</string>
</dict></plist>'''
    assert _mac_volume_id_from_plist(raw) == "GROUP-UUID"


def test_volume_capture_probes_only_requested_mount() -> None:
    mounts = [Mount("/dev/a", "/", "apfs"),
              Mount("/dev/b", "/Volumes/USB", "apfs"),
              Mount("/dev/c", "/Volumes/Other", "apfs")]
    checked: list[str] = []

    def read_id(mount: Mount) -> str:
        checked.append(mount.path)
        return "id-b"

    volumes = current_local_volumes(mounts, paths=["/Volumes/USB/run"], id_reader=read_id)
    assert checked == ["/Volumes/USB"]
    assert volumes.location("/Volumes/USB/run") == "vol://id-b/run"


@pytest.mark.skipif(os.environ.get("HELAB_TEST_REAL_VOLUME") != "1",
                    reason="opt in to a native volume-ID check")
def test_native_volume_reader_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.utils.data_roots import _volume_id
    from helab.utils.cache_paths import current_mounts
    monkeypatch.delenv("HELAB_TEST_VOLUME_ID", raising=False)
    monkeypatch.delenv("HELAB_TEST_LOCAL_MOUNT", raising=False)
    mounts = current_mounts()
    local = next((mount for mount in mounts if not mount.remote), None)
    if local is None:
        pytest.skip("no local volume available")
    assert _volume_id(local)


def test_utf8_bom_and_harmless_label_dots_are_accepted(tmp_path: Path) -> None:
    folder = tmp_path / "data"
    marker(folder, str(uuid.uuid4()), "v1..2")
    raw = (folder / ".helab-root").read_bytes()
    (folder / ".helab-root").write_bytes(b"\xef\xbb\xbf" + raw)
    assert read_marker(str(folder)).label == "v1..2"


def test_fifo_marker_is_rejected_without_blocking(tmp_path: Path) -> None:
    if sys.platform == "win32":  # (A check type checkers follow: no os.mkfifo there.)
        pytest.skip("FIFO marker is POSIX-only")
    folder = tmp_path / "data"
    folder.mkdir()
    os.mkfifo(folder / ".helab-root")
    with pytest.raises(ValueError, match="regular file"):
        read_marker(str(folder))


def test_old_store_is_preserved_and_not_opened_as_root_store(tmp_path: Path) -> None:
    old = tmp_path / "store-v2"
    with CacheStore(str(old)) as store:
        store.save_record("summaries", "old", {"old": True},
                          store.guard(["old"], ["summaries"]))
        database = store.database
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE meta SET value='2' WHERE key='layout_version'")
    with pytest.raises(StoreError, match="unsupported layout version"):
        CacheStore(str(old), root_mode=True)
    assert (old / "records.sqlite").exists()


def test_marker_replacement_resets_first_seen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    with CacheStore(str(tmp_path / ROOT_STORE_DIRNAME), root_mode=True) as store:
        with monkeypatch.context() as patch:
            clock = iter((10.0, 20.0, 30.0))
            patch.setattr("helab.utils.cache_store.time.time", lambda: next(clock))
            store.record_root("smb://host/share", first, "smb", "data", decision="confirmed")
            store.record_root("smb://host/share", first, "smb", "data", decision="confirmed")
            store.record_root("smb://host/share", second, "smb", "replacement", decision="pending")
        row = store._conn.execute(
            "SELECT uuid, first_seen, last_seen, decision FROM roots WHERE location=?",
            ("smb://host/share",)).fetchone()
        assert row == (second, 30.0, 30.0, "pending")
