"""D2 helper discovery and root-keyed cache behavior on fake shares."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import uuid
from typing import Any

import pytest

from helab import io_helper
from helab.utils import cache_paths, data_roots
from helab.utils.cache_paths import Mount
from helab.utils.cache_store import CacheStore

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
    io_helper.list_folder(str(share), events.append, options(tmp_path))
    assert any(event["kind"] == "root_found" for event in events)
    assert not any(event["kind"] == "cache_skipped" for event in events)
    assert any(event["kind"] == "entries" and event["entries"][0]["path"] == str(run)
               for event in events)
    with io_helper._cache_store(options(tmp_path)["directory"], [str(run)]) as store:
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
    io_helper.list_folder(str(share), lambda _: None, cache)
    with io_helper._cache_store(cache["directory"], [str(run)]) as store:
        store.save_record("summaries", str(run), {"owner": "outer"},
                          store.guard([str(run)], ["summaries"]))
    write_marker(inner, inner_id)
    events: list[dict[str, Any]] = []
    io_helper.list_folder(str(inner), events.append, cache)
    assert any(event["kind"] == "root_rekeyed" for event in events)
    with io_helper._cache_store(cache["directory"], [str(run)]) as store:
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
    io_helper.list_folder(str(share), lambda _: None, cache)
    (share / ".helab-root").unlink()
    events: list[dict[str, Any]] = []
    io_helper.list_folder(str(share), events.append, cache)
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
    io_helper.list_folder(str(first), lambda _: None, cache)
    events: list[dict[str, Any]] = []
    io_helper.list_folder(str(second), events.append, cache)
    assert any(event["kind"] == "root_duplicate" for event in events)
    assert any(event["kind"] == "cache_skipped" for event in events)
    with CacheStore(cache["directory"], root_mode=True) as store:
        assert store.root_at("smb://host/second") == (identifier, "b", "pending")


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
    io_helper.list_folder(str(folder), lambda _: None, cache)

    def forbidden(_: Mount) -> str:
        raise AssertionError("local lane probed a source volume")

    monkeypatch.setattr(data_roots, "_volume_id", forbidden)
    with io_helper._cache_store(cache["directory"], [str(folder)], local_lane=True) as store:
        assert store._path_key(str(folder)) == f"root://{identifier}"


def test_background_verifies_only_known_marker_folders(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    write_marker(root, str(uuid.uuid4()))
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("//host/share", str(root), "smbfs", True)])
    cache = options(tmp_path)
    io_helper.list_folder(str(root), lambda _: None, cache)
    (root / ".helab-root").unlink()
    events: list[dict[str, Any]] = []
    io_helper.verify_known_roots(cache, events.append)
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
        io_helper.scan(str(folder), events.append, None)
        return next(event for event in events if event["kind"] == "status")

    before = status()
    write_marker(folder, str(uuid.uuid4()))
    after = status()
    assert (before["count"], before["files"], before["signature"]) == (
        after["count"], after["files"], after["signature"])


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
    io_helper.list_folder(str(folder), events.append, cache)
    assert any(event["kind"] == "status" for event in events)
    assert any(event["kind"] == "cache_skipped" for event in events)
    assert_no_cached_rows(cache)


def test_unrooted_details_is_ram_only(unrooted: tuple[Path, dict[str, Any]]) -> None:
    folder, cache = unrooted
    events: list[dict[str, Any]] = []
    io_helper.scan(str(folder), events.append, cache, manual=True)
    assert any(event["kind"] == "status" for event in events)
    assert any(event["kind"] == "cache_skipped" for event in events)
    assert_no_cached_rows(cache)


def test_unrooted_cached_read_reads_nothing(unrooted: tuple[Path, dict[str, Any]],
                                            tmp_path: Path) -> None:
    folder, cache = unrooted
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(ValueError, match="Disk cache unavailable"):
        io_helper.read_cached(str(folder), str(output), lambda _: None, cache)
    assert not list(output.iterdir())
    assert_no_cached_rows(cache)


def test_unrooted_load_reads_source_without_saving(unrooted: tuple[Path, dict[str, Any]],
                                                   tmp_path: Path) -> None:
    folder, cache = unrooted
    output = tmp_path / "output"
    output.mkdir()
    events: list[dict[str, Any]] = []
    io_helper.load(str(folder), str(output), events.append, cache)
    assert any(event["kind"] == "loaded" for event in events)
    assert any(event["kind"] == "cache_skipped" for event in events)
    assert_no_cached_rows(cache)


def test_unrooted_subtree_save_skips_row(unrooted: tuple[Path, dict[str, Any]]) -> None:
    folder, cache = unrooted
    events: list[dict[str, Any]] = []
    io_helper.save_subtrees(cache, [{"path": str(folder), "status": "something"}], events.append)
    assert events[-1] == {"kind": "subtree_saved", "paths": [], "skipped": [str(folder)]}
    assert_no_cached_rows(cache)
