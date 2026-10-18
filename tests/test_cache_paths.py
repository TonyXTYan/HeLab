"""Mounted SMB shares keep their cache identity when macOS renumbers volumes."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import time

import pytest

from helab.utils import cache_paths
from helab.utils.cache_paths import CachePaths, Mount, UnresolvedRemotePath, _smb_source
from helab.utils.cache_store import CacheStore, DatasetRecord, Kind

RECORD_KINDS: tuple[Kind, ...] = ("summaries", "histories", "subtrees")


def mounts(c_suffix: str, r_suffix: str) -> CachePaths:
    return CachePaths([
        Mount("//operator@198.51.100.23/share-c", f"/Volumes/example-server{c_suffix}", "smbfs"),
        Mount("//operator@198.51.100.23/share-r", f"/Volumes/example-server{r_suffix}", "smbfs"),
        # macOS may report nested automounts within the same SMB share.
        Mount("//operator@198.51.100.23/share-c/Documents%20and%20Settings",
              f"/Volumes/example-server{c_suffix}/Documents and Settings", "smbfs"),
    ])


def opened(root: Path, paths: CachePaths) -> CacheStore:
    return CacheStore(str(root), path_key=paths.key, source_path=paths.source)


def test_share_keys_survive_suffix_swap_and_isolate_all_cache_kinds(tmp_path: Path) -> None:
    first = mounts("-1", "-2")
    later = mounts("-2", "-1")
    c_before = "/Volumes/example-server-1/Documents and Settings/run"
    c_after = "/Volumes/example-server-2/Documents and Settings/run"
    r_after = "/Volumes/example-server-1/Documents and Settings/run"
    assert first.key(c_before) == later.key(c_after)
    assert first.key(c_before) == "smb://198.51.100.23/share-c/Documents%20and%20Settings/run"
    assert first.key(c_before) != later.key(r_after)
    assert later.source(first.key(c_before)) == c_after

    root = tmp_path / "store-v2"
    with opened(root, first) as store:
        guard = store.start_dataset_job(c_before, RECORD_KINDS)
        for kind in RECORD_KINDS:
            store.save_record(kind, c_before, {"owner": "C"}, guard)
        store.set_prefs(c_before, True, True, time.time())
        file = store.write_dataset_file(b"cached bytes")
        record: DatasetRecord = {"ram_bytes": 1, "rows": 1, "shots": 1, "fingerprint": [],
                                 "problematic": [], "info": {"saved_at": time.time(), "signature": "C"}}
        # A no-cache preference blocks the dataset save, so clear that flag first.
        store.set_prefs(c_before, False, True, time.time() + 1)
        store.save_dataset(c_before, file, record, guard)
        pending_guard = store.start_dataset_job(c_before)
        pending_file = store.write_dataset_file(b"new cached bytes")
        pending_id = store.add_pending(c_before, pending_file, record, pending_guard, "over_budget")
        with sqlite3.connect(store.database) as conn:
            assert conn.execute("SELECT path FROM datasets").fetchone()[0] == first.key(c_before)

    with opened(root, later) as store:
        for kind in RECORD_KINDS:
            assert store.read_record(kind, c_after).value == {"owner": "C"}
            assert store.read_record(kind, r_after).missing
        prefs = store.read_prefs([c_after])[c_after].value
        assert prefs is not None and prefs["no_auto_load"]
        assert store.read_prefs([r_after])[r_after].missing
        dataset = store.read_dataset_row(c_after).value
        assert dataset is not None and dataset["path"] == c_after
        assert store.read_dataset_row(r_after).missing
        assert store.read_dataset_infos([c_after, r_after])[c_after].found
        assert store.read_dataset_infos([c_after, r_after])[r_after].missing
        assert store.inventory()["pending"][0]["path"] == c_after
        assert store.adopt_pending(pending_id).path == c_after
        assert store.remove(("datasets",), [c_after]).paths == (c_after,)
        assert store.read_dataset_row(c_after).missing


def test_smb_account_and_nested_mount_source_share_one_key() -> None:
    expected = "smb://host.local/share/Documents%20and%20Settings/run"
    sources = [
        "//GUEST:@Host.local/Share",
        "//DOMAIN;user@Host.local/Share",
        "//user:pw@Host.local/Share",
        "//Host.local/Share",
    ]
    for source in sources:
        paths = CachePaths([Mount(source, "/Volumes/share", "smbfs")])
        assert paths.key("/Volumes/share/Documents and Settings/run") == expected
    nested = CachePaths([Mount("//host.local/share/Documents%20and%20Settings",
                               "/Volumes/nested", "smbfs")])
    assert nested.key("/Volumes/nested/run") == expected
    assert _smb_source("//[2001:db8::1]:445/Share", "smbfs") == "smb://[2001:db8::1]:445/share"


def test_unmounted_account_free_share_keeps_pending_save_visible(tmp_path: Path) -> None:
    root = tmp_path / "store-v2"
    key = "smb://example-server/share/run"
    record: DatasetRecord = {"ram_bytes": 1, "rows": 1, "shots": 1, "fingerprint": [],
                             "problematic": [], "info": {"saved_at": time.time(), "signature": "new"}}
    with CacheStore(str(root)) as store:
        guard = store.start_dataset_job(key)
        file = store.write_dataset_file(b"pending data")
        store.add_pending(key, file, record, guard, "over_budget")
    with opened(root, CachePaths([])) as store:
        inventory = store.inventory()
        assert inventory["pending"][0]["path"] == key
    assert CachePaths([]).source("smb://[bad-bracket/share/run") == "smb://[bad-bracket/share/run"


def test_guard_from_old_share_cannot_save_history_to_reused_mount_path(tmp_path: Path) -> None:
    root = tmp_path / "store-v2"
    path = "/Volumes/example-server-1/run"
    with opened(root, mounts("-1", "-2")) as store:
        guard = store.guard([path], ("histories",))
    with opened(root, mounts("-2", "-1")) as store:
        with pytest.raises(ValueError, match="save guard doesn't cover"):
            store.save_record("histories", path, {"blocked": True}, guard)
        assert store.read_record("histories", path).missing


def test_purge_uses_stored_key_after_share_mounts_at_literal_path(tmp_path: Path) -> None:
    root = tmp_path / "store-v2"
    path = "/Volumes/example-server-1/run"
    old_saved_at = time.time() - 3600
    with opened(root, CachePaths([])) as store:
        guard = store.guard([path], ("summaries",))
        store.save_record("summaries", path, {"owner": "unmounted"}, guard,
                          saved_at=old_saved_at)
    with opened(root, mounts("-1", "-2")) as store:
        guard = store.guard([path], ("summaries",))
        store.save_record("summaries", path, {"owner": "mounted"}, guard)
        store.purge_records(time.time() - 1800)
        assert store.read_record("summaries", path).value == {"owner": "mounted"}
        with sqlite3.connect(store.database) as conn:
            keys = {key for (key,) in conn.execute("SELECT path FROM folder_summaries")}
        assert keys == {mounts("-1", "-2").key(path)}


def test_windows_mapped_and_unc_paths_preserve_source_spelling(monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "win32")
        paths = CachePaths([Mount(r"\\Server\Share", "Z:\\", "smb", True)])
        original = r"Z:\Data\Run1"
        key = paths.key(original)
        assert key == "smb://server/share/Data/Run1"
        assert paths.source(key) == original
        assert paths.key(r"\\SERVER\SHARE\Data\Run1") == key
        assert paths.source(key) == original  # A UNC lookup must not replace a mounted drive's display path.
        assert paths.key(r"\\Server\Share\a%20b") == "smb://server/share/a%2520b"
        assert paths.key(r"Z:\a%20b") == "smb://server/share/a%2520b"
        assert paths.key(r"\\Server\Share\a b") == "smb://server/share/a%20b"
        assert paths.key("\\\\Server\\Share\\") == paths.key("Z:\\")
        assert paths.key("\\\\Server\\Share\\a\\\\b\\") == paths.key(r"Z:\a\b")


def test_windows_webdav_drive_and_unc_are_not_given_smb_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "win32")
        paths = CachePaths([Mount(r"\\host@SSL\DavWWWRoot\folder", "W:\\", "smb", True)])
        for path in (r"W:\run", r"\\host@SSL\DavWWWRoot\folder\run"):
            with pytest.raises(UnresolvedRemotePath) as raised:
                paths.key(path)
            assert raised.value.mount_type == "webdav"


def test_unresolved_remote_mount_refuses_literal_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "win32")
        paths = CachePaths([Mount("Z:\\", "Z:\\", "remote", True)])
        with pytest.raises(UnresolvedRemotePath):
            paths.key("Z:\\Data")


def test_unresolved_smb_mount_refuses_literal_key(tmp_path: Path) -> None:
    paths = CachePaths([Mount("unparseable source", str(tmp_path), "smbfs", True)])
    with pytest.raises(UnresolvedRemotePath):
        paths.key(str(tmp_path / "run"))


@pytest.mark.parametrize("fstype", ["nfs", "afpfs", "webdav"])
def test_unsupported_remote_root_browses_with_typed_cache_notice(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fstype: str) -> None:
    from helab import io_helper

    mount = tmp_path / "remote"
    mount.mkdir()
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("server:/export", str(mount), fstype, True)])
    events: list[dict[str, object]] = []
    io_helper.list_folder(str(mount), events.append, {"directory": str(tmp_path / "store-v2")})
    notices = [event for event in events if event.get("kind") == "cache_skipped"]
    assert len(notices) == 1
    mounts_seen = notices[0]["mounts"]
    assert isinstance(mounts_seen, list) and mounts_seen[0]["type"] == fstype
    assert any(event.get("kind") == "status" for event in events)
    assert not any(event.get("kind") in ("error", "cache_warning") for event in events)


def test_mount_lookup_failure_keeps_listing_successful(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab import io_helper

    folder = tmp_path / "run"
    folder.mkdir()
    (folder / "child").mkdir()

    def unavailable() -> CachePaths:
        raise RuntimeError("mount table unavailable")

    monkeypatch.setattr(cache_paths, "current_cache_paths", unavailable)
    events: list[dict[str, object]] = []
    io_helper.list_folder(str(folder), events.append,
                          {"directory": str(tmp_path / "store-v2")})
    assert any(event.get("kind") == "cache_warning" for event in events)
    assert any(event.get("kind") == "entries" for event in events)
    assert not any(event.get("kind") == "error" for event in events)


def test_helper_listing_uses_share_key_and_returns_source_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab import io_helper

    mount = tmp_path / "volume-1"
    child = mount / "Run1"
    child.mkdir(parents=True)
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("//operator@example-server/Share", str(mount), "smbfs")])
    root = str(tmp_path / "store-v2")
    with io_helper._cache_store(root, [str(child)]) as store:
        store.set_prefs(str(child), True, True, time.time())
        with sqlite3.connect(store.database) as conn:
            assert conn.execute("SELECT path FROM folder_prefs").fetchone()[0] == (
                "smb://example-server/share/Run1")
    events: list[dict[str, object]] = []
    io_helper.list_folder(str(mount), events.append, {"directory": root})
    batches = [event["entries"] for event in events if event.get("kind") == "entries"]
    entries = [entry for batch in batches if isinstance(batch, list) for entry in batch]
    assert len(entries) == 1
    assert entries[0]["path"] == str(child)
    assert entries[0]["prefs"]["no_cache"] is True


def test_refused_child_does_not_fail_parent_scan_or_lose_sibling_cache(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab import io_helper

    parent = tmp_path / "parent"
    normal = parent / "normal"
    remote = parent / "remote"
    normal.mkdir(parents=True)
    remote.mkdir()
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("server:/export", str(remote), "nfs", True)])
    root = str(tmp_path / "store-v2")
    with io_helper._cache_store(root, [str(normal)]) as store:
        store.set_prefs(str(normal), True, True, time.time())
    events: list[dict[str, object]] = []
    io_helper.scan(str(parent), events.append, {"directory": root})
    assert any(event.get("kind") == "status" for event in events)
    assert not any(event.get("kind") == "error" for event in events)
    assert not any(event.get("kind") == "cache_warning" for event in events)
    assert any(event.get("kind") == "cache_skipped" and event.get("paths") == [str(remote)]
               for event in events)
    assert any(event.get("kind") == "cache_skipped" and event.get("mounts") == [
        {"path": str(remote), "type": "nfs",
         "detail": f"Remote mount source could not be identified: {remote} (nfs)"}]
               for event in events)
    batches = [event["entries"] for event in events if event.get("kind") == "entries"]
    entries = {entry["path"]: entry for batch in batches if isinstance(batch, list) for entry in batch}
    assert entries[str(normal)]["prefs"]["no_cache"] is True
    assert "prefs" not in entries[str(remote)]


def test_refused_subtree_does_not_lose_other_batch_saves(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab import io_helper

    remote = tmp_path / "remote"
    remote.mkdir()
    local = str(tmp_path / "local")
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("server:/export", str(remote), "nfs", True)])
    root = str(tmp_path / "store-v2")
    events: list[dict[str, object]] = []
    io_helper.save_subtrees({"directory": root},
                            [{"path": local, "status": "nothing", "derived_at": 1.0},
                             {"path": str(remote), "status": "something", "derived_at": 1.0}],
                            events.append)
    assert any(event.get("kind") == "subtree_saved" and event.get("paths") == [local]
               and event.get("skipped") == [str(remote)] for event in events)
    with io_helper._cache_store(root, [local]) as store:
        assert store.read_record("subtrees", local).found
