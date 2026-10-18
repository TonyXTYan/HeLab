"""Same folder or a copy? (data roots, D4): one .helab-root found at a second location."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
from typing import Any, Iterator
import uuid

import pytest
from pytestqt.qtbot import QtBot

from helab import io_helper
from helab.utils import cache_paths, data_roots
from helab.utils.cache_paths import Mount
from helab.utils.cache_store import CacheStore
from helab.utils.folder_cache import PENDING_ROOT, FolderCache, data_root_row
from helab.utils.io_service import IORequest, IOService
from helab.views.RootDuplicatesWindow import CopyRootDialog, RootDuplicatesWindow, duplicate_hints

pytestmark = pytest.mark.no_auto_data_root


def write_marker(folder: Path, identifier: str) -> None:
    (folder / ".helab-root").write_text(
        f'{{"helab": "root", "version": 1, "uuid": "{identifier}", "label": "{folder.name}", '
        '"created_at": "2026-10-18T00:00:00Z"}', encoding="utf-8")


@pytest.fixture
def two(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, str, dict[str, Any]]:
    """One root known at smb://host/first; the same marker now also seen at smb://host/second."""
    first, second = tmp_path / "first", tmp_path / "second"
    for folder in (first, second):
        (folder / "run").mkdir(parents=True)
    identifier = str(uuid.uuid4())
    write_marker(first, identifier)
    (second / ".helab-root").write_bytes((first / ".helab-root").read_bytes())  # A copy: the same bytes.
    monkeypatch.setattr(cache_paths, "current_mounts", lambda: [
        Mount("//host/first", str(first), "smbfs", True), Mount("//host/second", str(second), "smbfs", True)])
    cache = {"directory": str(tmp_path / "cache")}
    io_helper.list_folder(str(first), lambda _: None, cache)
    run = str(first / "run")
    with io_helper._cache_store(cache["directory"], [run]) as store:
        store.save_record("summaries", run, {"version": 1, "owner": "first"}, store.guard([run], ["summaries"]))
    return first, second, identifier, cache


def duplicate(second: Path, cache: dict[str, Any]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    io_helper.list_folder(str(second), events.append, cache)
    return next(event for event in events if event["kind"] == "root_duplicate")


def test_a_second_location_waits_with_hints(two: tuple[Path, Path, str, dict[str, Any]]) -> None:
    first, second, identifier, cache = two
    event = duplicate(second, cache)
    assert event["uuid"] == identifier and event["label"] == "first"
    assert [(other["location"], other["path"]) for other in event["others"]] == [("smb://host/first", str(first))]
    assert event["marker"]["size"] == event["others"][0]["marker"]["size"]
    assert event["marker"]["file_id"] != event["others"][0]["marker"]["file_id"]
    assert duplicate_hints(event).startswith("same server · ")
    assert duplicate_hints(event).endswith("different file ID")
    with pytest.raises(data_roots.NoDataRoot):  # RAM only until answered.
        with io_helper._cache_store(cache["directory"], [str(second / "run")]):
            pass


def test_same_folder_shares_the_cached_data(two: tuple[Path, Path, str, dict[str, Any]]) -> None:
    first, second, identifier, cache = two
    duplicate(second, cache)
    events: list[dict[str, Any]] = []
    io_helper.cache_admin(cache, "root_same", events.append, location="smb://host/second", uuid=identifier)
    confirmed = next(event for event in events if event["kind"] == "root_confirmed")
    assert confirmed["path"] == str(second)
    with io_helper._cache_store(cache["directory"], [str(second / "run")]) as store:
        assert store.read_record("summaries", str(second / "run")).value == {"version": 1, "owner": "first"}


def test_a_copy_keeping_the_known_location_gets_a_new_root_and_starts_empty(
    two: tuple[Path, Path, str, dict[str, Any]],
) -> None:
    first, second, identifier, cache = two
    duplicate(second, cache)
    events: list[dict[str, Any]] = []
    io_helper.reassign_root(str(second), cache, identifier, "smb://host/first", events.append)
    reassigned = next(event for event in events if event["kind"] == "root_reassigned")
    new = data_roots.read_marker(str(second)).uuid
    assert reassigned["uuid"] == new != identifier and reassigned["moved"] == ["smb://host/second"]
    assert not list(second.glob(".helab-root.*.tmp"))
    with CacheStore(cache["directory"], root_mode=True) as store:
        assert store.root_at("smb://host/second") == (new, "second", "confirmed")
        assert store.root_at("smb://host/first") == (identifier, "first", "confirmed")
    with io_helper._cache_store(cache["directory"], [str(second / "run"), str(first / "run")]) as store:
        assert store.read_record("summaries", str(second / "run")).value is None
        assert store.read_record("summaries", str(first / "run")).value == {"version": 1, "owner": "first"}


def test_a_copy_keeping_the_new_location_rewrites_the_known_folder(
    two: tuple[Path, Path, str, dict[str, Any]],
) -> None:
    first, second, identifier, cache = two
    duplicate(second, cache)
    events: list[dict[str, Any]] = []
    io_helper.reassign_root(str(first), cache, identifier, "smb://host/second", events.append)
    new = data_roots.read_marker(str(first)).uuid
    assert data_roots.read_marker(str(second)).uuid == identifier
    assert {"kind": "root_found", "path": str(second), "location": "smb://host/second", "uuid": identifier,
            "label": "first"} in events
    assert any(event["kind"] == "root_changed" and event["path"] == str(first) for event in events)
    with io_helper._cache_store(cache["directory"], [str(second / "run"), str(first / "run")]) as store:
        assert store._path_key(str(first)) == f"root://{new}"
        # The data stays with the original UUID, now reached through the second location.
        assert store.read_record("summaries", str(second / "run")).value == {"version": 1, "owner": "first"}


def test_a_marker_changed_since_is_not_rewritten(two: tuple[Path, Path, str, dict[str, Any]]) -> None:
    first, second, identifier, cache = two
    duplicate(second, cache)
    write_marker(second, str(uuid.uuid4()))
    before = (second / ".helab-root").read_bytes()
    with pytest.raises(ValueError, match="changed since HeLab found it"):
        io_helper.reassign_root(str(second), cache, identifier, "smb://host/first", lambda _: None)
    assert (second / ".helab-root").read_bytes() == before


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX permissions")
def test_a_read_only_copy_gets_the_new_contents_to_place(two: tuple[Path, Path, str, dict[str, Any]]) -> None:
    first, second, identifier, cache = two
    duplicate(second, cache)
    second.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        events: list[dict[str, Any]] = []
        io_helper.reassign_root(str(second), cache, identifier, "smb://host/first", events.append)
    finally:
        second.chmod(stat.S_IRWXU)
    manual = next(event for event in events if event["kind"] == "root_manual")
    assert data_roots.parse_marker(manual["contents"].encode("utf-8")).uuid != identifier
    assert data_roots.read_marker(str(second)).uuid == identifier
    with CacheStore(cache["directory"], root_mode=True) as store:
        assert store.root_at("smb://host/second") == (identifier, "first", "pending")


@pytest.fixture
def cache(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> Iterator[FolderCache]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    folder_cache = FolderCache(service)
    yield folder_cache
    service.shutdown()


def sighting(cache: FolderCache, path: str = "/Volumes/second", location: str = "smb://host/second") -> None:
    request = IORequest("tab", 0, path, "list", {}, 60.0)
    cache.service.resultReady.emit(request, {
        "kind": "root_duplicate", "path": path, "location": location, "uuid": "u", "label": "second",
        "other_locations": ["smb://host/first"], "marker": {"size": 10, "mtime": 1.0, "file_id": "1:2"},
        "others": [{"location": "smb://host/first", "path": "/Volumes/first",
                    "marker": {"size": 10, "mtime": 1.0, "file_id": "1:2"}}]})


def test_the_window_opens_once_per_session_again_after_later_never_after_snooze(cache: FolderCache) -> None:
    found: list[str] = []
    cache.rootDuplicateFound.connect(found.append)
    sighting(cache)
    sighting(cache)  # Listed again while waiting: no second popup.
    assert found == ["smb://host/second"]
    cache.answer_root_duplicate("smb://host/second", "later")
    sighting(cache)
    assert len(found) == 2
    cache.answer_root_duplicate("smb://host/second", "snoozed")
    sighting(cache)
    assert len(found) == 2 and cache.root_duplicates["smb://host/second"]["answer"] == "snoozed"
    assert cache.pending_root("/Volumes/second/run") is not None
    assert data_root_row(cache, "/Volumes/second/run")[0] == PENDING_ROOT
    request = IORequest("admin", 0, "", "cache_admin", {}, 60.0)
    cache.service.resultReady.emit(request, {"kind": "root_confirmed", "location": "smb://host/second",
                                             "uuid": "u", "path": "/Volumes/second", "label": "second"})
    assert not cache.root_duplicates and cache.root_of("/Volumes/second/run") is not None


def test_window_answers_go_to_the_cache(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, cache: FolderCache) -> None:
    window = RootDuplicatesWindow(cache)
    qtbot.addWidget(window)
    sighting(cache)
    assert window.isVisible() and window.tree.topLevelItemCount() == 1
    item = window.tree.topLevelItem(0)
    assert item is not None and item.text(3) == "same server · marker same size and modified time · same file ID"
    admin: list[tuple[str, dict[str, Any]]] = []
    def cache_admin(action: str, **params: Any) -> str:
        admin.append((action, params))
        return "job"
    monkeypatch.setattr(cache, "cache_admin", cache_admin)
    window.same()
    assert admin == [("root_same", {"location": "smb://host/second", "uuid": "u"})]
    monkeypatch.setattr("helab.utils.folder_cache.store_options", lambda: {"directory": "/tmp/cache"})
    window.choose_keep = lambda entry: "smb://host/first"
    window.copy()
    job = cache.jobs[("root_reassign", "/Volumes/second")]
    assert job.payload["keep"] == "smb://host/first" and job.payload["old_uuid"] == "u"
    window.later_button.click()
    assert cache.root_duplicates["smb://host/second"]["answer"] == "later"
    window.show_list()
    window.snooze_button.click()
    assert cache.root_duplicates["smb://host/second"]["answer"] == "snoozed"


def test_closing_unanswered_counts_as_later(qtbot: QtBot, cache: FolderCache) -> None:
    window = RootDuplicatesWindow(cache)
    qtbot.addWidget(window)
    sighting(cache)
    window.close()
    assert cache.root_duplicates["smb://host/second"]["answer"] == "later"


def test_keeping_the_new_location_needs_the_known_folder_mounted(qtbot: QtBot) -> None:
    entry = {"location": "smb://host/second", "path": "/Volumes/second",
             "others": [{"location": "smb://host/first", "path": ""}]}
    dialog = CopyRootDialog(None, entry)
    qtbot.addWidget(dialog)
    known, new = dialog.choices
    assert known.isChecked() and not new.isEnabled()
    assert dialog.keep() == "smb://host/first"
