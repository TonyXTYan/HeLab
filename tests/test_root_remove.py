"""Settings → Data roots: Show in Finder / File Explorer, Copy path and Delete .helab-root…
(``root_remove``: only a marker still holding the row's UUID is deleted, then its locations forgotten)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import types
from typing import Any, Iterator
import uuid

import pytest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from helab import io_helper
from helab.utils import cache_paths, data_roots
from helab.utils.cache_paths import Mount
from helab.utils.cache_store import CacheStore
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IOService
from helab.views import DataRootsTab as tab_module
from helab.views.DataRootsTab import DELETE, NOT_MOUNTED_TOOLTIP, DataRootsTab

pytestmark = pytest.mark.no_auto_data_root

Events = list[dict[str, Any]]


def options(tmp_path: Path) -> dict[str, Any]:
    return {"directory": str(tmp_path / "cache")}


@pytest.fixture
def share(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "share"
    (folder / "run").mkdir(parents=True)
    monkeypatch.setattr(cache_paths, "current_mounts",
                        lambda: [Mount("//host/share", str(folder), "smbfs", True)])
    return folder


def placed(share: Path, tmp_path: Path) -> str:
    events: Events = []
    io_helper.create_root(str(share), options(tmp_path), events.append)
    return str(next(event for event in events if event["kind"] == "root_created")["uuid"])


def locations(tmp_path: Path) -> dict[str, str]:
    with CacheStore(options(tmp_path)["directory"], root_mode=True) as store:
        return {location: identifier for location, identifier, _ in store.root_locations()}


def test_deleting_removes_the_marker_and_forgets_its_locations_but_not_other_shares(
    share: Path, tmp_path: Path,
) -> None:
    identifier = placed(share, tmp_path)
    with CacheStore(options(tmp_path)["directory"], root_mode=True) as store:
        # The same marker seen through a mount of its subfolder, and through another share.
        store.record_root("smb://host/share/run", identifier, "smb", "share", decision="confirmed")
        store.record_root("smb://other/data", identifier, "smb", "share", decision="confirmed")
        store.record_root("smb://host/share-2", str(uuid.uuid4()), "smb", "share-2", decision="confirmed")
    events: Events = []
    io_helper.remove_root(str(share), options(tmp_path), identifier, "smb://host/share", events.append)
    assert not (share / ".helab-root").exists()
    removed = next(event for event in events if event["kind"] == "root_removed")
    assert sorted(removed["forgotten"]) == ["smb://host/share", "smb://host/share/run"]
    assert set(locations(tmp_path)) == {"smb://other/data", "smb://host/share-2"}
    changed = [event for event in events if event["kind"] == "root_changed"]
    assert {event["path"] for event in changed} == {str(share), str(share / "run")}
    assert all("uuid" not in event for event in changed)  # The folders now have no root.


@pytest.mark.parametrize("change", ["replaced", "invalid", "directory", "missing"])
def test_deleting_refuses_a_marker_that_is_not_the_rows(share: Path, tmp_path: Path, change: str) -> None:
    identifier = placed(share, tmp_path)
    marker = share / ".helab-root"
    if change == "replaced":
        marker.unlink()
        marker.write_text(json.dumps({"helab": "root", "version": 1, "uuid": str(uuid.uuid4()),
                                      "label": "share", "created_at": "2026-10-18T00:00:00Z"}))
    elif change == "invalid":
        marker.unlink()
        marker.write_text("not a marker")
    elif change == "directory":
        marker.unlink()
        marker.mkdir()
    else:
        marker.unlink()
    with pytest.raises(ValueError, match={"replaced": "changed since", "invalid": "never deletes it",
                                          "directory": "isn't a file", "missing": "no .helab-root"}[change]):
        io_helper.remove_root(str(share), options(tmp_path), identifier, "smb://host/share", lambda _: None)
    assert marker.exists() == (change != "missing")
    assert locations(tmp_path) == {"smb://host/share": identifier}


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX permissions")
def test_without_permission_the_file_stays_and_is_named(share: Path, tmp_path: Path) -> None:
    identifier = placed(share, tmp_path)
    share.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        events: Events = []
        io_helper.remove_root(str(share), options(tmp_path), identifier, "smb://host/share", events.append)
    finally:
        share.chmod(stat.S_IRWXU)
    refused = next(event for event in events if event["kind"] == "root_remove_refused")
    assert refused["file"] == str(share / ".helab-root") and refused["reason"]
    assert (share / ".helab-root").exists() and data_roots.read_marker(str(share)).uuid == identifier
    assert not any(event["kind"] == "root_removed" for event in events)
    assert locations(tmp_path) == {"smb://host/share": identifier}


def frozen_service(monkeypatch: pytest.MonkeyPatch) -> IOService:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    return service


ROWS: list[dict[str, Any]] = [
    {"location": "smb://server/dld_output", "uuid": "11111111-1111-4111-8111-111111111111", "kind": "smb",
     "label": "dld_output", "first_seen": 1.0e9, "last_seen": 1.7e9, "decision": "confirmed",
     "path": os.path.join(os.sep, "Volumes", "dld_output")},
    {"location": "vol://abc/data", "uuid": "22222222-2222-4222-8222-222222222222", "kind": "vol",
     "label": "data", "first_seen": 1.0e9, "last_seen": 1.6e9, "decision": "confirmed", "path": ""}]


@pytest.fixture
def admin() -> list[tuple[str, dict[str, Any]]]:
    """The page's cache_admin jobs (inventory, forget_root)."""
    return []


@pytest.fixture
def page(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
         admin: list[tuple[str, dict[str, Any]]]) -> Iterator[DataRootsTab]:
    service = frozen_service(monkeypatch)
    cache = FolderCache(service)

    def cache_admin(action: str, **params: Any) -> str:
        admin.append((action, params))
        return f"job-{len(admin)}"
    monkeypatch.setattr(cache, "cache_admin", cache_admin)
    monkeypatch.setattr(tab_module, "store_options", lambda: options(tmp_path))
    monkeypatch.setattr("helab.utils.folder_cache.store_options", lambda: options(tmp_path))
    settings = DataRootsTab(cache)
    qtbot.addWidget(settings)
    cache.cacheAdminResult.emit("inventory", {"kind": "inventory", "inventory": {"roots": ROWS}})
    cache.cacheAdminDone.emit("job-1", "inventory", "")
    yield settings
    settings.detach()
    service.shutdown()


def select(page: DataRootsTab, row: int) -> None:
    item = page.list.topLevelItem(row)
    assert item is not None
    page.list.setCurrentItem(item)


def menu_items(page: DataRootsTab) -> dict[str, tuple[bool, str]]:
    return {action.text(): (action.isEnabled(), action.toolTip())
            for action in page.context_menu().actions() if action.text()}


def test_row_menu_and_delete_button_follow_whether_the_row_is_mounted(page: DataRootsTab) -> None:
    select(page, 0)
    items = menu_items(page)
    show = tab_module.show_label()
    assert list(items) == [show, "Copy path", "Clear cached data…", "Forget location…", DELETE]
    assert all(enabled for enabled, _ in items.values()) and "hidden" in items[show][1]
    assert page.delete_button.isEnabled() and page.forget_button.isEnabled()
    page.copy_selected()
    clipboard = QApplication.clipboard()
    assert clipboard is not None and clipboard.text() == os.path.join(ROWS[0]["path"], ".helab-root")
    select(page, 1)  # Not mounted: nothing to show or delete; it can still be forgotten.
    items = menu_items(page)
    assert items[show] == (False, NOT_MOUNTED_TOOLTIP) and items[DELETE] == (False, NOT_MOUNTED_TOOLTIP)
    assert items["Copy path"][0] and items["Forget location…"][0]
    assert not page.delete_button.isEnabled() and page.forget_button.isEnabled()
    assert not page.show_selected()


@pytest.mark.parametrize("platform", ["darwin", "win32", "linux"])
def test_show_reveals_the_marker_without_waiting(page: DataRootsTab, monkeypatch: pytest.MonkeyPatch,
                                                 platform: str) -> None:
    monkeypatch.setattr(tab_module, "sys", types.SimpleNamespace(platform=platform))
    launched: list[tuple[str, list[str]]] = []
    opened: list[str] = []

    def launch(program: str, arguments: list[str]) -> bool:
        launched.append((program, arguments))
        return True

    def open_folder(folder: str) -> bool:
        opened.append(folder)
        return True
    page.launch, page.open_folder = launch, open_folder
    select(page, 0)
    assert page.show_selected()
    marker = os.path.join(ROWS[0]["path"], ".helab-root")
    expected = {"darwin": [("open", ["-R", marker])], "win32": [("explorer", ["/select,", marker])],
                "linux": []}[platform]
    assert launched == expected and opened == ([] if expected else [ROWS[0]["path"]])
    assert tab_module.show_label() == {"darwin": "Show in Finder", "win32": "Show in File Explorer",
                                       "linux": "Show in File Manager"}[platform]
    assert {"darwin": "Cmd+Shift+.", "win32": "Hidden items", "linux": "hidden files"}[platform] in (
        tab_module.show_tooltip())


def test_delete_asks_then_runs_root_remove_in_the_foreground(
    page: DataRootsTab, admin: list[tuple[str, dict[str, Any]]],
) -> None:
    select(page, 0)
    asked: list[str] = []

    def cancel(title: str, text: str, verb: str) -> bool:
        asked.append(text)
        return False
    page.confirm = cancel
    page.delete_selected()
    assert page.cache is not None
    service = page.cache.service
    assert not service.pending
    marker = os.path.join(ROWS[0]["path"], ".helab-root")
    assert asked[0].startswith(f"Deletes {marker}.") and "lose their disk cache" in asked[0]
    page.confirm = lambda title, text, verb: True
    page.delete_selected()
    request = next(r for r in service.pending if r.operation == "root_remove")
    assert request.path == page.cache.key(ROWS[0]["path"])
    assert {key: request.payload[key] for key in ("uuid", "location")} == {
        "uuid": ROWS[0]["uuid"], "location": ROWS[0]["location"]}
    # Not the current tab's work, yet in the foreground like the user's other marker writes.
    assert service.is_foreground(request)
    assert not page.delete_button.isEnabled() and not page.forget_button.isEnabled()
    service.resultReady.emit(request, {"kind": "root_removed", "path": ROWS[0]["path"],
                                       "uuid": ROWS[0]["uuid"], "forgotten": [ROWS[0]["location"]]})
    service.resultReady.emit(request, {"kind": "done"})
    QApplication.processEvents()
    assert page.message == f"Deleted {marker}"
    assert admin[-1] == ("inventory", {})  # The list is read again.


def test_a_refused_delete_names_the_file(page: DataRootsTab) -> None:
    select(page, 0)
    alerts: list[str] = []
    page.alert = alerts.append
    page.confirm = lambda title, text, verb: True
    page.delete_selected()
    assert page.cache is not None
    service = page.cache.service
    request = next(r for r in service.pending if r.operation == "root_remove")
    marker = os.path.join(ROWS[0]["path"], ".helab-root")
    service.resultReady.emit(request, {"kind": "root_remove_refused", "path": ROWS[0]["path"],
                                       "file": marker, "reason": "Permission denied"})
    service.resultReady.emit(request, {"kind": "done"})
    QApplication.processEvents()
    assert alerts == [f"HeLab can't delete {marker} (Permission denied). Delete it by hand "
                      f"({tab_module.show_label()} finds it), then Refresh this list."]
    assert page.message == f"Could not delete {marker}" and not page._job
