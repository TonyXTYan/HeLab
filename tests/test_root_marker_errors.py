"""Placing, replacing and deleting ``.helab-root`` markers when the file system says no
(``helab.io_ops.markers``): nothing is overwritten, nothing half-written is left behind, and the user is
told what to do. The failures are injected for the marker file alone, so these run on every OS and as
root, where the permission tests in test_root_enable.py, test_root_duplicates.py and
test_root_remove.py are skipped."""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Callable
import uuid

import pytest

from helab.io_ops import infra, markers, stores
from helab.io_ops.browse import list_folder
from helab.io_ops.markers import create_root, reassign_root, remove_root, verify_known_roots
from helab.utils import cache_paths, data_roots
from helab.utils.cache_paths import Mount
from helab.utils.cache_store import CacheStore, StoreError

pytestmark = pytest.mark.no_auto_data_root

Events = list[Any]
LOCATION = "smb://host/share"


def options(tmp_path: Path) -> dict[str, Any]:
    return {"directory": str(tmp_path / "cache")}


@pytest.fixture
def share(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "share"
    (folder / "run").mkdir(parents=True)
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("//host/share", str(folder), "smbfs", True)])
    return folder


def root_rows(tmp_path: Path) -> dict[str, tuple[str, str, str]]:
    with CacheStore(options(tmp_path)["directory"], root_mode=True) as store:
        return {location: row for location in (LOCATION,) if (row := store.root_at(location)) is not None}


def placed(share: Path, tmp_path: Path) -> str:
    events: Events = []
    create_root(str(share), options(tmp_path), events.append)
    return str(next(event for event in events if event["kind"] == "root_created")["uuid"])


def refuse(target: Path, error: int = errno.EACCES) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Wrap an ``os`` call so that it fails, as the OS would, for ``target`` alone."""
    def wrap(call: Callable[..., Any]) -> Callable[..., Any]:
        def refused(path: Any, *args: Any, **kwargs: Any) -> Any:
            if os.fspath(path) == str(target):
                raise OSError(error, os.strerror(error), os.fspath(path))
            return call(path, *args, **kwargs)
        return refused
    return wrap


def rewrite(path: Path, text: str) -> None:
    """Replace an existing marker's text in place. ``root_create`` hides the marker, and Windows
    refuses to open a hidden file for a truncating write ("w")."""
    with open(path, "r+", encoding="utf-8") as stream:
        stream.write(text)
        stream.truncate()


def marker_text(identifier: str, *, version: int = 1, label: str = "share") -> str:
    return json.dumps({"helab": "root", "version": version, "uuid": identifier, "label": label,
                       "created_at": "2026-10-18T00:00:00Z"})


# root_create


def test_a_refused_create_hands_out_the_contents_and_records_nothing(
    share: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = share / ".helab-root"
    events: Events = []
    with monkeypatch.context() as patch:
        patch.setattr(os, "open", refuse(marker)(os.open))
        create_root(str(share), options(tmp_path), events.append)
    assert [event["kind"] for event in events] == ["root_manual"]
    manual = events[0]
    assert manual["path"] == str(share) and manual["name"] == ".helab-root"
    assert "Permission denied" in manual["reason"] and "replace" not in manual
    assert data_roots.parse_marker(manual["contents"].encode("utf-8")).label == "share"
    assert not marker.exists() and not root_rows(tmp_path)


def test_a_create_that_fails_while_writing_leaves_no_partial_marker(
    share: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def full(_: int) -> None:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    events: Events = []
    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", full)
        create_root(str(share), options(tmp_path), events.append)
    assert [event["kind"] for event in events] == ["root_manual"]
    assert os.strerror(errno.ENOSPC) in events[0]["reason"]
    assert not (share / ".helab-root").exists() and not root_rows(tmp_path)
    # The contents handed out are a marker the next listing accepts.
    (share / ".helab-root").write_text(events[0]["contents"], encoding="utf-8")
    listed: Events = []
    list_folder(str(share), listed.append, options(tmp_path))
    assert any(event["kind"] == "root_found" for event in listed)


@pytest.mark.parametrize("kind", ["newer version", "uuid without hyphens", "empty", "directory"])
def test_a_marker_create_cant_use_is_never_overwritten(share: Path, tmp_path: Path, kind: str) -> None:
    if kind == "directory" and sys.platform == "win32":
        pytest.skip("Windows can't open a folder as a file: an OSError, not a marker HeLab can't use")
    marker = share / ".helab-root"
    if kind == "directory":
        marker.mkdir()
        (marker / "kept").write_text("x")
    else:
        marker.write_text({"newer version": marker_text(str(uuid.uuid4()), version=2),
                           "uuid without hyphens": marker_text(uuid.uuid4().hex),
                           "empty": ""}[kind], encoding="utf-8")
    before = None if kind == "directory" else marker.read_bytes()
    with pytest.raises(ValueError, match="already exists here but can't be used"):
        create_root(str(share), options(tmp_path), lambda _: None)
    if before is None:
        assert (marker / "kept").read_text() == "x"
    else:
        assert marker.read_bytes() == before
    assert not root_rows(tmp_path)


def test_a_created_marker_the_store_cant_record_is_found_by_the_next_listing(
    share: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def busy(*_: Any, **__: Any) -> CacheStore:
        raise StoreError("database is locked")

    events: Events = []
    with monkeypatch.context() as patch:
        patch.setattr(stores, "_cache_store", busy)
        create_root(str(share), options(tmp_path), events.append)
    assert [event["kind"] for event in events] == ["cache_warning", "root_created"]
    assert events[0]["message"] == "Data root could not be recorded: database is locked"
    assert data_roots.read_marker(str(share)).uuid == events[1]["uuid"] and not root_rows(tmp_path)
    listed: Events = []
    list_folder(str(share), listed.append, options(tmp_path))
    assert any(event["kind"] == "root_found" and event["uuid"] == events[1]["uuid"] for event in listed)


# Discovery of a marker that went bad


def test_a_known_marker_made_invalid_is_forgotten_with_a_warning(share: Path, tmp_path: Path) -> None:
    identifier = placed(share, tmp_path)
    assert root_rows(tmp_path) == {LOCATION: (identifier, "share", "confirmed")}
    rewrite(share / ".helab-root", "{broken")
    events: Events = []
    list_folder(str(share), events.append, options(tmp_path))
    warnings = [event["message"] for event in events if event["kind"] == "cache_warning"]
    assert any(message.startswith(f"Invalid {share}/.helab-root") for message in warnings)
    assert not root_rows(tmp_path) and (share / ".helab-root").read_text() == "{broken"


def test_a_known_marker_made_invalid_is_reported_gone_like_a_removed_one(share: Path, tmp_path: Path) -> None:
    """``FolderCache`` drops a root, its badge and the RAM state under it only on ``root_changed``
    (``folder_cache.py``, ``_root_gone``): an invalid marker must say so as a removed one does."""
    placed(share, tmp_path)
    rewrite(share / ".helab-root", "{broken")
    events: Events = []
    list_folder(str(share), events.append, options(tmp_path))
    assert [(event["path"], event["location"], event["reason"]) for event in events
            if event["kind"] == "root_changed"] == [(str(share), LOCATION, "marker invalid")]
    events.clear()
    list_folder(str(share), events.append, options(tmp_path))  # Already forgotten: said once.
    assert not [event for event in events if event["kind"] == "root_changed"]


def test_an_invalid_marker_never_known_changes_no_root(share: Path, tmp_path: Path) -> None:
    (share / ".helab-root").write_text("{broken", encoding="utf-8")
    events: Events = []
    list_folder(str(share), events.append, options(tmp_path))
    assert not [event for event in events if event["kind"] == "root_changed"] and not root_rows(tmp_path)


@pytest.mark.parametrize("marker", [True, False], ids=["marker", "marker removed"])
def test_a_roots_table_that_cant_be_read_warns_and_the_listing_completes(
        share: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, marker: bool) -> None:
    """A busy store or a disk I/O error reading the roots table is a cache warning: the listing still
    ends with its status, not an error (which would block the folder's automatic status checks)."""
    placed(share, tmp_path)
    if not marker:
        (share / ".helab-root").unlink()

    def unreadable(*args: Any) -> Any:
        raise StoreError("Data roots could not be read: disk I/O error")

    monkeypatch.setattr(CacheStore, "root_at", unreadable)
    monkeypatch.setattr(CacheStore, "other_root_locations", unreadable)
    events: Events = []
    list_folder(str(share), events.append, options(tmp_path))
    assert [event["kind"] for event in events if event["kind"] in ("status", "error")] == ["status"]
    assert any(event["kind"] == "cache_warning" and "disk I/O error" in event["message"] for event in events)


def test_a_root_record_sqlite_cant_write_warns_and_the_listing_completes(
        share: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    placed(share, tmp_path)

    def unwritable(*args: Any, **kwargs: Any) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(CacheStore, "record_root", unwritable)
    events: Events = []
    list_folder(str(share), events.append, options(tmp_path))
    assert [event["kind"] for event in events if event["kind"] in ("status", "error")] == ["status"]
    assert any(event["kind"] == "cache_warning" and "disk I/O error" in event["message"] for event in events)


def test_roots_table_reads_report_a_database_error_as_a_store_error(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Failing:
        def execute(self, *args: Any) -> Any:
            raise sqlite3.OperationalError("disk I/O error")

    with CacheStore(options(tmp_path)["directory"], root_mode=True) as store:
        with monkeypatch.context() as patch:
            patch.setattr(store, "_conn", Failing())
            with pytest.raises(StoreError, match="disk I/O error"):
                store.root_at(LOCATION)
            with pytest.raises(StoreError, match="disk I/O error"):
                store.other_root_locations("uuid", LOCATION)


# root_reassign


@pytest.fixture
def pending(share: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    """``share`` holds a copy of a marker already known at another share: pending until answered."""
    first = tmp_path / "first"
    first.mkdir()
    identifier = str(uuid.uuid4())
    (first / ".helab-root").write_text(marker_text(identifier, label="first"), encoding="utf-8")
    (share / ".helab-root").write_bytes((first / ".helab-root").read_bytes())
    mounts = [Mount("//host/first", str(first), "smbfs", True), Mount("//host/share", str(share), "smbfs", True)]
    monkeypatch.setattr(cache_paths, "current_mounts", lambda: mounts)
    list_folder(str(first), lambda _: None, options(tmp_path))
    events: Events = []
    list_folder(str(share), events.append, options(tmp_path))
    assert any(event["kind"] == "root_duplicate" for event in events)
    return share, identifier


@pytest.mark.parametrize("call", ["open", "fsync", "replace"])
def test_a_refused_reassign_keeps_the_marker_and_leaves_no_temporary(
    pending: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, call: str,
) -> None:
    share, identifier = pending
    marker = share / ".helab-root"
    before = marker.read_bytes()
    original_open, original_replace = os.open, os.replace

    def no_temporary(path: Any, *args: Any, **kwargs: Any) -> int:
        if Path(os.fspath(path)).parent == share and Path(os.fspath(path)).name.endswith(".tmp"):
            raise OSError(errno.EROFS, os.strerror(errno.EROFS), os.fspath(path))
        return original_open(path, *args, **kwargs)

    def full(_: int) -> None:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    def not_replaced(source: Any, target: Any) -> None:
        if os.fspath(target) == str(marker):
            raise OSError(errno.EACCES, os.strerror(errno.EACCES), os.fspath(target))
        original_replace(source, target)

    events: Events = []
    with monkeypatch.context() as patch:
        patch.setattr(os, call, {"open": no_temporary, "fsync": full, "replace": not_replaced}[call])
        reassign_root(str(share), options(tmp_path), identifier, "smb://host/first", events.append)
    assert [event["kind"] for event in events] == ["root_manual"]
    manual = events[0]
    assert manual["replace"] is True and manual["path"] == str(share) and manual["reason"]
    assert data_roots.parse_marker(manual["contents"].encode("utf-8")).uuid != identifier
    assert marker.read_bytes() == before
    assert not [name for name in os.listdir(share) if markers._marker_temporary(name)]
    with CacheStore(options(tmp_path)["directory"], root_mode=True) as store:
        assert store.root_at(LOCATION) == (identifier, "first", "pending")


@pytest.mark.parametrize("kind", ["invalid", "missing"])
def test_reassign_refuses_a_marker_it_cant_read(pending: tuple[Path, str], tmp_path: Path, kind: str) -> None:
    share, identifier = pending
    marker = share / ".helab-root"
    if kind == "invalid":
        marker.write_text("not a marker", encoding="utf-8")
    else:
        marker.unlink()
    with pytest.raises(ValueError if kind == "invalid" else FileNotFoundError):
        reassign_root(str(share), options(tmp_path), identifier, "smb://host/first", lambda _: None)
    assert (marker.read_text(encoding="utf-8") == "not a marker") if kind == "invalid" else not marker.exists()
    assert not [name for name in os.listdir(share) if markers._marker_temporary(name)]


# root_remove


def test_a_refused_delete_names_the_file_and_forgets_nothing(
    share: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    identifier = placed(share, tmp_path)
    marker = share / ".helab-root"
    events: Events = []
    with monkeypatch.context() as patch:
        patch.setattr(os, "remove", refuse(marker)(os.remove))
        remove_root(str(share), options(tmp_path), identifier, LOCATION, events.append)
    assert events == [{"kind": "root_remove_refused", "path": str(share), "file": str(marker),
                       "reason": os.strerror(errno.EACCES)}]
    assert data_roots.read_marker(str(share)).uuid == identifier
    assert root_rows(tmp_path) == {LOCATION: (identifier, "share", "confirmed")}


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need a privilege on Windows")
def test_delete_never_follows_a_link_to_the_marker(share: Path, tmp_path: Path) -> None:
    """A link to a marker holding the row's UUID reads as that marker, but it isn't the file HeLab
    placed: deleting it is refused, and neither the link nor its target goes."""
    identifier = placed(share, tmp_path)
    marker = share / ".helab-root"
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_bytes(marker.read_bytes())
    marker.unlink()
    marker.symlink_to(elsewhere)
    assert data_roots.read_marker(str(share)).uuid == identifier
    with pytest.raises(ValueError, match="isn't a file"):
        remove_root(str(share), options(tmp_path), identifier, LOCATION, lambda _: None)
    assert marker.is_symlink() and elsewhere.exists()
    assert root_rows(tmp_path) == {LOCATION: (identifier, "share", "confirmed")}


def test_delete_goes_by_the_uuid_not_the_label(share: Path, tmp_path: Path) -> None:
    """Only the UUID decides: a marker rewritten with the same UUID (a new label) is still the row's,
    and one with another UUID is not, whatever its label."""
    identifier = placed(share, tmp_path)
    marker = share / ".helab-root"
    rewrite(marker, marker_text(str(uuid.uuid4()), label="share"))
    with pytest.raises(ValueError, match="changed since HeLab found it"):
        remove_root(str(share), options(tmp_path), identifier, LOCATION, lambda _: None)
    assert marker.exists()
    rewrite(marker, marker_text(identifier, label="renamed"))
    events: Events = []
    remove_root(str(share), options(tmp_path), identifier, LOCATION, events.append)
    assert not marker.exists() and events[-1]["kind"] == "root_removed"
    assert events[-1]["forgotten"] == [LOCATION] and not root_rows(tmp_path)


# roots_verify after volumes_verify


def test_marker_check_uses_the_volume_ids_just_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``roots_verify`` given the volume check's IDs asks for none again, visits only roots on those
    volumes, and reconciles a marker replaced since (a root_changed to the new UUID)."""
    disk = tmp_path / "USB"
    disk.mkdir()
    old = str(uuid.uuid4())
    (disk / ".helab-root").write_text(marker_text(old, label="USB"), encoding="utf-8")
    mount = Mount("/dev/disk4s1", str(disk), "apfs")
    monkeypatch.setattr(cache_paths, "current_mounts", lambda: [mount])
    monkeypatch.setattr(data_roots, "_volume_id", lambda _: "disk-a")
    list_folder(str(disk), lambda _: None, options(tmp_path))
    new = str(uuid.uuid4())
    (disk / ".helab-root").write_text(marker_text(new, label="USB"), encoding="utf-8")
    monkeypatch.setattr(infra, "_volume_id_cache", {})
    monkeypatch.setattr(data_roots, "_volume_id", lambda _: pytest.fail("asked for a volume ID again"))
    events: Events = []
    verify_known_roots(options(tmp_path), events.append, volume_ids=[])  # Its volume wasn't verified.
    assert [event["kind"] for event in events if event["kind"] != "heartbeat"] == ["roots_verified"]
    with CacheStore(options(tmp_path)["directory"], root_mode=True) as store:
        assert [row[1] for row in store.root_locations()] == [old]
    events = []
    verify_known_roots(options(tmp_path), events.append, volume_ids=[[mount.path, mount.source, "disk-a"]])
    assert [event["kind"] for event in events if event["kind"] != "heartbeat"] == ["root_changed", "roots_verified"]
    assert events[0]["uuid"] == new and events[0]["path"] == str(disk)
    with CacheStore(options(tmp_path)["directory"], root_mode=True) as store:
        assert [row[1] for row in store.root_locations()] == [new]
