"""Enable disk cache here…: creating or adopting a folder's data-root marker (D3)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
from typing import Any
import uuid

import pytest
from pytestqt.qtbot import QtBot

from helab import io_helper
from helab.utils import cache_paths, data_roots
from helab.utils.cache_paths import Mount
from helab.utils.cache_store import CacheStore
from helab.utils.folder_cache import get_folder_cache
from helab.utils.io_service import IORequest, IOService

pytestmark = pytest.mark.no_auto_data_root


def options(tmp_path: Path) -> dict[str, Any]:
    return {"directory": str(tmp_path / "cache")}


@pytest.fixture
def share(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "share"
    (folder / "run").mkdir(parents=True)
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("//host/share", str(folder), "smbfs", True)])
    return folder


def test_new_marker_is_the_exact_text_a_reader_accepts(tmp_path: Path) -> None:
    marker, contents = data_roots.new_marker(str(tmp_path / "dld_output"))
    assert data_roots.parse_marker(contents) == marker
    assert marker.label == "dld_output"
    assert json.loads(contents)["uuid"] == marker.uuid == str(uuid.UUID(marker.uuid))
    assert data_roots.marker_label(os.sep) == "data"  # A drive's root without a name.


def test_enabling_writes_the_marker_and_records_the_root(share: Path, tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    io_helper.create_root(str(share), options(tmp_path), events.append)
    created = next(event for event in events if event["kind"] == "root_created")
    assert data_roots.read_marker(str(share)).uuid == created["uuid"]
    assert any(event["kind"] == "root_found" for event in events)
    with CacheStore(options(tmp_path)["directory"], root_mode=True) as store:
        assert store.root_at("smb://host/share") == (created["uuid"], "share", "confirmed")
    with io_helper._cache_store(options(tmp_path)["directory"], [str(share / "run")]) as store:
        assert store._path_key(str(share / "run")) == f"root://{created['uuid']}/run"


def test_enabling_again_adopts_the_marker_already_there(share: Path, tmp_path: Path) -> None:
    first: list[dict[str, Any]] = []
    io_helper.create_root(str(share), options(tmp_path), first.append)
    again: list[dict[str, Any]] = []
    io_helper.create_root(str(share), options(tmp_path), again.append)
    created = next(event for event in first if event["kind"] == "root_created")
    adopted = next(event for event in again if event["kind"] == "root_adopted")
    assert adopted["uuid"] == created["uuid"]


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX permissions")
def test_without_write_permission_the_exact_contents_are_handed_out(share: Path, tmp_path: Path) -> None:
    share.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        events: list[dict[str, Any]] = []
        io_helper.create_root(str(share), options(tmp_path), events.append)
    finally:
        share.chmod(stat.S_IRWXU)
    manual = next(event for event in events if event["kind"] == "root_manual")
    assert manual["name"] == ".helab-root" and manual["path"] == str(share)
    assert data_roots.parse_marker(manual["contents"].encode("utf-8")).label == "share"
    assert not (share / ".helab-root").exists()
    assert not any(event["kind"] in ("root_found", "root_created") for event in events)
    # Placed by hand, the next listing finds it.
    (share / ".helab-root").write_bytes(manual["contents"].encode("utf-8"))
    listed: list[dict[str, Any]] = []
    io_helper.list_folder(str(share), listed.append, options(tmp_path))
    assert any(event["kind"] == "root_found" for event in listed)


def test_inventory_lists_root_locations_and_forgetting_one_keeps_its_data(share: Path, tmp_path: Path) -> None:
    cache = options(tmp_path)
    io_helper.create_root(str(share), cache, lambda _: None)
    run = str(share / "run")
    with io_helper._cache_store(cache["directory"], [run]) as store:
        store.save_record("summaries", run, {"version": 1}, store.guard([run], ["summaries"]))
    events: list[dict[str, Any]] = []
    io_helper.cache_admin(cache, "inventory", events.append)
    roots = next(event for event in events if event["kind"] == "inventory")["inventory"]["roots"]
    assert [(row["location"], row["label"], row["decision"], row["path"]) for row in roots] == [
        ("smb://host/share", "share", "confirmed", str(share))]
    events = []
    io_helper.cache_admin(cache, "forget_root", events.append, location="smb://host/share")
    assert {"kind": "root_changed", "path": str(share), "location": "smb://host/share",
            "reason": "forgotten"} in events
    with CacheStore(cache["directory"], root_mode=True) as store:
        assert store.root_rows() == []
        assert store._conn.execute("SELECT COUNT(*) FROM folder_summaries").fetchone()[0] == 1
    # The marker is still there: the next listing finds it, and the data with it.
    io_helper.list_folder(str(share), lambda _: None, cache)
    with io_helper._cache_store(cache["directory"], [run]) as store:
        assert store.read_record("summaries", run).value == {"version": 1}


def test_folder_cache_tracks_roots_and_ram_only_folders(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
                                                         tmp_path: Path) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    cache = get_folder_cache(service)
    share, run = str(tmp_path / "share"), str(tmp_path / "share" / "run")
    request = IORequest("tab", 0, share, "list", {}, 60.0)
    changed: list[str] = []
    cache.dataRootsChanged.connect(changed.append)
    detail = f"Disk cache off: no data root for {run}"
    service.resultReady.emit(request, {"kind": "cache_skipped", "paths": [run], "mounts": [
        {"path": run, "type": "no data root", "detail": detail}]})
    assert cache.no_root(run) == detail and cache.mount_warning(run) is None
    identifier = str(uuid.uuid4())
    service.resultReady.emit(request, {"kind": "root_created", "path": share, "uuid": identifier,
                                       "label": "share"})
    assert cache.no_root(run) is None
    assert cache.root_of(run) == (share, identifier, "share")
    service.resultReady.emit(request, {"kind": "root_changed", "path": share, "location": "smb://host/share",
                                       "reason": "marker removed"})
    assert cache.root_of(run) is None
    assert changed == [run, share, share]
    service.shutdown()


def test_a_folder_deep_in_a_root_reports_that_root(share: Path, tmp_path: Path) -> None:
    """A restored tab inside a root whose folder this session never listed still learns it."""
    cache = options(tmp_path)
    io_helper.create_root(str(share), cache, lambda _: None)
    deep = share / "run" / "a"
    deep.mkdir()
    (deep / "d_txy_forc1.txt").write_text("1,2,3\n")
    identifier = data_roots.read_marker(str(share)).uuid
    expected = {"path": str(share), "uuid": identifier, "label": "share"}
    events: list[dict[str, Any]] = []
    io_helper.list_folder(str(deep), events.append, cache)
    assert next(event for event in events if event["kind"] == "status")["data_root"] == expected
    output = tmp_path / "output"
    output.mkdir()
    loaded: list[dict[str, Any]] = []
    io_helper.load(str(deep), str(output), loaded.append, cache)
    assert next(event for event in loaded if event["kind"] == "loaded")["data_root"] == expected
    cached: list[dict[str, Any]] = []
    io_helper.read_cached(str(deep), str(output), cached.append, cache)
    # The local lane too, from the roots table alone.
    assert next(event for event in cached if event["kind"] == "loaded")["data_root"] == expected


def test_an_invalid_marker_is_never_overwritten(share: Path, tmp_path: Path) -> None:
    (share / ".helab-root").write_text("not json")
    with pytest.raises(ValueError, match="already exists here but can't be used.*Fix or remove it"):
        io_helper.create_root(str(share), options(tmp_path), lambda _: None)
    assert (share / ".helab-root").read_text() == "not json"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS file flags")
def test_a_marker_created_on_macos_is_flagged_hidden(share: Path, tmp_path: Path) -> None:
    io_helper.create_root(str(share), options(tmp_path), lambda _: None)
    assert os.stat(share / ".helab-root").st_flags & stat.UF_HIDDEN


def test_folder_cache_learns_a_root_from_a_deep_folder(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: Path) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    cache = get_folder_cache(service)
    share, deep = str(tmp_path / "share"), str(tmp_path / "share" / "run" / "a")
    request = IORequest("tab", 0, deep, "cached", {}, 60.0)
    identifier = str(uuid.uuid4())
    for label in ("share", ""):  # A later result without the label keeps the known one.
        service.resultReady.emit(request, {"kind": "progress", "progress": 0.5,
                                           "data_root": {"path": share, "uuid": identifier, "label": label}})
    assert cache.root_of(deep) == (share, identifier, "share")
    service.shutdown()
