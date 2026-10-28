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

from helab.io_ops import stores
from helab.io_ops.admin import cache_admin
from helab.io_ops.browse import list_folder
from helab.io_ops.markers import reassign_root
from helab.io_ops.scanning import scan
from helab.utils import cache_paths, data_roots
from helab.utils.cache_paths import Mount
from helab.utils.cache_store import CacheStore
from helab.utils.folder_cache import PENDING_ROOT, FolderCache, data_root_row
from helab.utils.io_service import IORequest, IOService
from helab.views.RootDuplicatesWindow import CopyRootDialog, RootDuplicatesWindow, duplicate_hints

pytestmark = pytest.mark.no_auto_data_root

# Paths as helpers report them on this OS (FolderCache matches folders by os.sep).
FIRST = os.path.abspath(os.path.join(os.sep, "Volumes", "first"))
SECOND = os.path.abspath(os.path.join(os.sep, "Volumes", "second"))
SECOND_RUN = os.path.join(SECOND, "run")


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
    list_folder(str(first), lambda _: None, cache)
    run = str(first / "run")
    with stores._cache_store(cache["directory"], [run]) as store:
        store.save_record("summaries", run, {"version": 1, "owner": "first"}, store.guard([run], ["summaries"]))
    return first, second, identifier, cache


def duplicate(second: Path, cache: dict[str, Any]) -> dict[str, Any]:
    events: list[Any] = []
    list_folder(str(second), events.append, cache)
    return next(event for event in events if event["kind"] == "root_duplicate")


def test_a_second_location_waits_with_hints(two: tuple[Path, Path, str, dict[str, Any]]) -> None:
    first, second, identifier, cache = two
    event = duplicate(second, cache)
    assert event["uuid"] == identifier and event["label"] == "first"
    assert [(other["location"], other["path"]) for other in event["others"]] == [("smb://host/first", str(first))]
    assert event["marker"]["size"] == event["others"][0]["marker"]["size"]
    assert event["marker"]["ino"] != event["others"][0]["marker"]["ino"]  # Two files (a copy).
    assert duplicate_hints(event).startswith("same server · ")
    assert duplicate_hints(event) == ("same server · different file number on the server · "
                                      "marker identical (a copy would be too)")
    with pytest.raises(data_roots.NoDataRoot):  # RAM only until answered.
        with stores._cache_store(cache["directory"], [str(second / "run")]):
            pass


def test_same_folder_shares_the_cached_data(two: tuple[Path, Path, str, dict[str, Any]]) -> None:
    first, second, identifier, cache = two
    duplicate(second, cache)
    events: list[Any] = []
    cache_admin(cache, "root_same", events.append, location="smb://host/second", uuid=identifier)
    confirmed = next(event for event in events if event["kind"] == "root_confirmed")
    assert confirmed["path"] == str(second)
    with stores._cache_store(cache["directory"], [str(second / "run")]) as store:
        assert store.read_record("summaries", str(second / "run")).value == {"version": 1, "owner": "first"}


def test_a_pending_location_whose_duplicate_is_forgotten_is_confirmed_by_its_next_listing(
    two: tuple[Path, Path, str, dict[str, Any]],
) -> None:
    """Pending exists only because another confirmed location has the UUID: with none left, there is
    nothing to compare it with, so the next listing confirms it instead of asking again."""
    first, second, identifier, cache = two
    duplicate(second, cache)
    cache_admin(cache, "forget_root", lambda _: None, location="smb://host/first")
    events: list[Any] = []
    list_folder(str(second), events.append, cache)
    assert not [event for event in events if event["kind"] == "root_duplicate"]
    assert [(event["location"], event["uuid"]) for event in events if event["kind"] == "root_found"] == [
        ("smb://host/second", identifier)]
    with CacheStore(cache["directory"], root_mode=True) as store:
        assert store.root_at("smb://host/second") == (identifier, "first", "confirmed")
    with stores._cache_store(cache["directory"], [str(second / "run")]) as store:  # Not RAM only now.
        assert store.read_record("summaries", str(second / "run")).value == {"version": 1, "owner": "first"}


def test_a_copy_keeping_the_known_location_gets_a_new_root_and_starts_empty(
    two: tuple[Path, Path, str, dict[str, Any]],
) -> None:
    first, second, identifier, cache = two
    duplicate(second, cache)
    events: list[Any] = []
    reassign_root(str(second), cache, identifier, "smb://host/first", events.append)
    reassigned = next(event for event in events if event["kind"] == "root_reassigned")
    new = data_roots.read_marker(str(second)).uuid
    assert reassigned["uuid"] == new != identifier and reassigned["moved"] == ["smb://host/second"]
    assert not list(second.glob(".helab-root.*.tmp"))
    with CacheStore(cache["directory"], root_mode=True) as store:
        assert store.root_at("smb://host/second") == (new, "second", "confirmed")
        assert store.root_at("smb://host/first") == (identifier, "first", "confirmed")
    with stores._cache_store(cache["directory"], [str(second / "run"), str(first / "run")]) as store:
        assert store.read_record("summaries", str(second / "run")).value is None
        assert store.read_record("summaries", str(first / "run")).value == {"version": 1, "owner": "first"}


def test_a_copy_keeping_the_new_location_rewrites_the_known_folder(
    two: tuple[Path, Path, str, dict[str, Any]],
) -> None:
    first, second, identifier, cache = two
    duplicate(second, cache)
    events: list[Any] = []
    reassign_root(str(first), cache, identifier, "smb://host/second", events.append)
    new = data_roots.read_marker(str(first)).uuid
    assert data_roots.read_marker(str(second)).uuid == identifier
    assert {"kind": "root_found", "path": str(second), "location": "smb://host/second", "uuid": identifier,
            "label": "first"} in events
    assert any(event["kind"] == "root_changed" and event["path"] == str(first) for event in events)
    with stores._cache_store(cache["directory"], [str(second / "run"), str(first / "run")]) as store:
        assert store._path_key(str(first)) == f"root://{new}"
        # The data stays with the original UUID, now reached through the second location.
        assert store.read_record("summaries", str(second / "run")).value == {"version": 1, "owner": "first"}


def test_a_marker_changed_since_is_not_rewritten(two: tuple[Path, Path, str, dict[str, Any]]) -> None:
    first, second, identifier, cache = two
    duplicate(second, cache)
    write_marker(second, str(uuid.uuid4()))
    before = (second / ".helab-root").read_bytes()
    with pytest.raises(ValueError, match="changed since HeLab found it"):
        reassign_root(str(second), cache, identifier, "smb://host/first", lambda _: None)
    assert (second / ".helab-root").read_bytes() == before


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX permissions")
def test_a_read_only_copy_gets_the_new_contents_to_place(two: tuple[Path, Path, str, dict[str, Any]]) -> None:
    first, second, identifier, cache = two
    duplicate(second, cache)
    second.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        events: list[Any] = []
        reassign_root(str(second), cache, identifier, "smb://host/first", events.append)
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


def sighting(cache: FolderCache, path: str = SECOND, location: str = "smb://host/second") -> None:
    request = IORequest("tab", 0, path, "list", {}, 60.0)
    cache.service.resultReady.emit(request, {
        "kind": "root_duplicate", "path": path, "location": location, "uuid": "u", "label": "second",
        "other_locations": ["smb://host/first"], "marker": {"size": 10, "mtime": 1.0, "ino": 7},
        "others": [{"location": "smb://host/first", "path": FIRST,
                    "marker": {"size": 10, "mtime": 1.0, "ino": 7}}]})


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
    assert cache.pending_root(SECOND_RUN) is not None
    assert data_root_row(cache, SECOND_RUN)[0] == PENDING_ROOT
    request = IORequest("admin", 0, "", "cache_admin", {}, 60.0)
    cache.service.resultReady.emit(request, {"kind": "root_confirmed", "location": "smb://host/second",
                                             "uuid": "u", "path": SECOND, "label": "second"})
    assert not cache.root_duplicates and cache.root_of(SECOND_RUN) is not None


def test_window_answers_go_to_the_cache(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, cache: FolderCache) -> None:
    window = RootDuplicatesWindow(cache)
    qtbot.addWidget(window)
    sighting(cache)
    assert window.isVisible() and window.tree.topLevelItemCount() == 1
    item = window.tree.topLevelItem(0)
    assert item is not None and item.text(3) == ("same server · same file number on the server · "
                                                 "marker identical (a copy would be too)")
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
    job = cache.jobs[("root_reassign", SECOND)]
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


def test_file_numbers_are_compared_only_on_one_server() -> None:
    """One share mounted twice has a different device number per mount: only the file number counts,
    and only on the same server."""
    marker = {"size": 10, "mtime": 1.0, "ino": 7}
    entry: dict[str, Any] = {"location": "smb://host/dld_output", "path": "/Volumes/dld_output",
                             "marker": marker,
                             "others": [{"location": "smb://host/C/data/dld_output", "path": "/Volumes/C/data/dld_output",
                                         "marker": {**marker}}]}
    assert duplicate_hints(entry) == "same server · same file number on the server · marker identical (a copy would be too)"
    entry["others"][0]["location"] = "smb://other-host/dld_output"
    assert duplicate_hints(entry) == "different server · marker identical (a copy would be too)"
    entry["others"][0]["marker"] = {"size": 10, "mtime": 99.0, "ino": 7}
    assert duplicate_hints(entry) == "different server · markers differ"


def test_a_marker_left_half_replaced_is_not_listed_as_data(tmp_path: Path) -> None:
    folder = tmp_path / "share"
    (folder / "run").mkdir(parents=True)
    (folder / ".helab-root.0123abcd.tmp").write_text("{")  # A crash before os.replace.
    events: list[Any] = []
    list_folder(str(folder), events.append)
    names = [entry["name"] for event in events if event["kind"] == "entries" for entry in event["entries"]]
    assert names == ["run"]
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / ".helab-root.0123abcd.tmp").write_text("{")
    scanned: list[Any] = []
    scan(str(empty), scanned.append)
    assert next(event for event in scanned if event["kind"] == "status")["empty"] is True


def test_working_offline_its_a_copy_is_off(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, cache: FolderCache) -> None:
    """Work Offline (cache-only browsing, D6): It's a copy… writes a new marker in the folder."""
    from helab.utils import folder_cache
    from helab.utils.folder_cache import OFFLINE_TOOLTIP
    window = RootDuplicatesWindow(cache)
    qtbot.addWidget(window)
    sighting(cache)
    item = window.tree.topLevelItem(0)
    assert item is not None
    window.tree.setCurrentItem(item)
    try:
        cache.set_offline(True)
        assert not window.copy_button.isEnabled() and window.copy_button.toolTip() == OFFLINE_TOOLTIP
        assert window.same_button.isEnabled()  # (Same folder is a disk cache write.)
        window.choose_keep = lambda entry: pytest.fail("asked which side keeps the data")
        window.copy()
        assert ("root_reassign", SECOND) not in cache.jobs
        cache.set_offline(False)
        assert window.copy_button.isEnabled()
    finally:
        folder_cache._offline = False
