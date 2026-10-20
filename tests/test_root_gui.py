"""Data roots in the GUI (D3): Place .helab-root here…, the ANCHOR badge, Folder details' Disk
cache row, the manual-placement dialog and Settings → Data roots."""
from __future__ import annotations

import os
from pathlib import Path
import types
from typing import Any, Callable, Iterator
import uuid

import numpy as np
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton
from pytestqt.qtbot import QtBot

from helab.io_ops.browse import list_folder
from helab.io_ops.markers import create_root
from helab.resources.icons import IconsInitUtil, StatusIcons
from helab.utils import data_roots
from helab.utils.folder_cache import (NEEDS_ROOT_TOOLTIP, PLACE_ROOT_TOOLTIP, RAM_ONLY, FolderCache,
                                      data_root_row)
from helab.utils.io_service import IORequest, IOService
from helab.views import DataRootDialogs
from helab.views.DataRootDialogs import (ADMIN, HOME, NESTED, NOT_TOP, STARTUP, VOLUMES, ManualMarkerDialog,
                                        placement_checks)
from helab.views.DataRootsTab import DataRootsTab
from helab.views.FolderDetailsPanel import FolderDetailsPanel
from helab.views.FolderExplorer import FolderExplorer


def frozen_service(monkeypatch: pytest.MonkeyPatch) -> IOService:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    return service


def producer(cache: FolderCache, path: str, operation: str) -> IORequest:
    owner = cache.jobs[(operation, path)].owner
    return next(r for r in cache.service.pending if r.owner == owner)


def replay(qtbot: QtBot, cache: FolderCache, path: str, operation: str,
           helper: Callable[[Callable[[dict[str, Any]], None]], None]) -> None:
    request = producer(cache, path, operation)

    def send(event: dict[str, Any]) -> None:
        if event["kind"] == "shot":
            event = {**event, "array": np.load(event["artifact"])}
        cache.service.resultReady.emit(request, event)
    helper(send)
    cache.service.resultReady.emit(request, {"kind": "done"})
    cache.service.pending.remove(request)
    qtbot.waitUntil(lambda: not any(r.path == path for r in cache._deliveries))


@pytest.fixture
def tab(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FolderExplorer]:
    """A tab on the test's folder, which holds the test's .helab-root (conftest)."""
    IconsInitUtil.initialise_icons()
    service = frozen_service(monkeypatch)
    (tmp_path / "run").mkdir()
    (tmp_path / "other").mkdir()
    root = str(tmp_path)
    explorer = FolderExplorer(root, root, root, [0, 4, 5])
    qtbot.addWidget(explorer)
    qtbot.waitUntil(lambda: ("list", root) in explorer.model.cache.jobs)
    yield explorer
    explorer.close_cleanup()
    service.shutdown()


def no_root(cache: FolderCache, path: str) -> None:
    """A helper reported the folder has no data root (RAM only)."""
    request = IORequest("helper", 0, path, "list", {}, 60.0)
    cache.service.resultReady.emit(request, {"kind": "cache_skipped", "paths": [path], "mounts": [
        {"path": path, "type": "no data root", "detail": f"Disk cache off: no data root for {path}"}]})


def mounts(cache: FolderCache, *paths: str) -> None:
    cache._mounts_observed = tuple((path, f"//server/{os.path.basename(path)}") for path in paths)


def test_checks_warn_below_the_top_of_a_share_inside_a_root_and_on_system_folders(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = frozen_service(monkeypatch)
    cache = FolderCache(service)
    share = os.path.join(os.sep, "Volumes", "dld_output")
    deep = os.path.join(share, "2026", "run_042")
    mounts(cache, os.sep, share)
    assert placement_checks(cache, share) == (None, [])
    assert placement_checks(cache, deep) == (share, [NOT_TOP.format(top=share)])
    cache._root_seen(share, str(uuid.uuid4()), "dld_output")
    top, warnings = placement_checks(cache, deep)
    assert top == share and warnings[1] == NESTED.format(label="dld_output",
                                                         marker=os.path.join(share, ".helab-root"))
    # The startup disk's top is never suggested; a home folder is warned about.
    assert placement_checks(cache, os.path.join(os.path.expanduser("~"), "data")) == (None, [])
    assert placement_checks(cache, os.path.expanduser("~")) == (None, [HOME])
    service.shutdown()


def test_posix_startup_disk_home_folders_and_volumes_warn_with_their_reasons(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = frozen_service(monkeypatch)
    cache = FolderCache(service)
    monkeypatch.setattr(DataRootDialogs, "sys", types.SimpleNamespace(platform="darwin"))
    monkeypatch.setenv("HOME", "/Users/tony")
    monkeypatch.setenv("USERPROFILE", "/Users/tony")  # (Where expanduser looks on Windows.)
    monkeypatch.setattr(cache, "mount_of", lambda path: "/")
    assert placement_checks(cache, "/") == (None, [STARTUP])
    assert placement_checks(cache, "/System/Volumes/Data") == (None, [STARTUP])
    assert placement_checks(cache, "/Volumes") == (None, [VOLUMES])
    assert placement_checks(cache, "/Users") == (None, [HOME])
    assert placement_checks(cache, "/Users/tony") == (None, [HOME])
    # Never "Place at /" from a folder on the startup disk.
    assert placement_checks(cache, "/Users/tony/data") == (None, [])
    assert "read-only" in STARTUP and "~/data" in STARTUP
    service.shutdown()


def test_windows_system_drive_top_is_a_drive_top_like_any_other(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A lab PC may share its whole C: drive: C:\.helab-root is the file the Mac sees at //pc/C.
    service = frozen_service(monkeypatch)
    cache = FolderCache(service)
    monkeypatch.setattr(DataRootDialogs, "sys", types.SimpleNamespace(platform="win32"))
    monkeypatch.setenv("SystemDrive", "C:")
    monkeypatch.setenv("HOME", "C:\\Users\\tony")
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\tony")
    monkeypatch.setattr(cache, "mount_of", lambda path: "C:\\")
    drive, data = "C:\\", "C:\\data\\run_042"
    assert placement_checks(cache, drive) == (None, [])
    assert placement_checks(cache, data) == (drive, [NOT_TOP.format(top=drive)])
    assert placement_checks(cache, "C:\\Users") == (drive, [HOME, NOT_TOP.format(top=drive)])
    assert placement_checks(cache, "c:\\users\\TONY") == (drive, [HOME, NOT_TOP.format(top=drive)])
    note = ADMIN.format(drive=drive)
    box = DataRootDialogs.PlaceRootBox(None, cache, drive)
    default = box.defaultButton()
    # A note, not a warning: Return still places it.
    assert box.informativeText() == note and default is not None and default.text() == "Place .helab-root"
    box = DataRootDialogs.PlaceRootBox(None, cache, data)
    assert box.at_top is not None and box.at_top.text() == "Place at C:\\"
    assert box.informativeText() == f"{NOT_TOP.format(top=drive)}\n\n{note}"
    default = box.defaultButton()
    assert default is not None and default.text() == "Cancel"
    service.shutdown()


def test_root_folders_show_the_anchor_beside_their_status(qtbot: QtBot, tab: FolderExplorer,
                                                          tmp_path: Path) -> None:
    model, cache = tab.model, tab.model.cache
    replay(qtbot, cache, str(tmp_path), "list", lambda send: list_folder(str(tmp_path), send, model._cache_options))
    # A nested root below the tab's folder (whose own row isn't shown).
    cache._root_seen(str(tmp_path / "run"), str(uuid.uuid4()), "run")

    def badges(path: Path) -> list[int]:
        icons = model.data(model.path_index(str(path), model.COLUMN_STATUS_ICON), model.STATUS_EXTRA_ICONS_ROLE)
        assert isinstance(icons, list)
        return [icon.cacheKey() for icon in icons if not isinstance(icon, str)]
    anchor = StatusIcons.ICONS_EXTRA["data_root"].cacheKey()
    assert badges(tmp_path / "run")[0] == anchor  # First, beside the status icon.
    assert anchor not in badges(tmp_path / "other")


def test_folder_details_name_the_root_in_use_or_say_ram_only(qtbot: QtBot, tab: FolderExplorer,
                                                             tmp_path: Path) -> None:
    cache = tab.model.cache
    replay(qtbot, cache, str(tmp_path), "list", lambda send: list_folder(str(tmp_path), send,
                                                                        tab.model._cache_options))
    panel = FolderDetailsPanel()
    # Nothing selected: the tab's own folder.
    panel.show_explorer(tab, cache.service)
    marker = str(tmp_path / ".helab-root")
    assert panel.text("cache") == f"⚓ {tmp_path.name} · {marker}"
    other = str(tmp_path.parent / f"elsewhere-{uuid.uuid4().hex}")
    no_root(cache, other)
    text, tooltip = data_root_row(cache, other)
    assert text == RAM_ONLY and "Place .helab-root here…" in tooltip


def test_menu_offers_the_action_and_greys_disk_cache_items_for_ram_only_folders(
    qtbot: QtBot, tab: FolderExplorer, tmp_path: Path,
) -> None:
    cache = tab.model.cache
    replay(qtbot, cache, str(tmp_path), "list", lambda send: list_folder(str(tmp_path), send,
                                                                        tab.model._cache_options))
    assert tab.place_root_state(str(tmp_path)) == (False, "This folder already has a .helab-root")
    enabled, tooltip = tab.place_root_state(str(tmp_path / "run"))
    assert enabled and "own identity" in tooltip
    elsewhere = str(Path(tmp_path).parent / f"elsewhere-{uuid.uuid4().hex}")
    assert tab.place_root_state(elsewhere) == (True, PLACE_ROOT_TOOLTIP)
    assert NEEDS_ROOT_TOOLTIP.startswith("No .helab-root found here or above")


def test_placing_a_root_writes_it_then_lists_the_folder_again(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tab: FolderExplorer, tmp_path: Path,
) -> None:
    cache = tab.model.cache
    replay(qtbot, cache, str(tmp_path), "list", lambda send: list_folder(str(tmp_path), send,
                                                                        tab.model._cache_options))
    target = tmp_path / "run"
    asked: list[str] = []

    def ask(parent: Any, folder_cache: FolderCache, path: str) -> str | None:
        asked.append(path)
        return path
    monkeypatch.setattr(DataRootDialogs, "ask_place_root", ask)
    assert tab.place_root(str(target))
    assert asked == [str(target)]
    request = producer(cache, str(target), "root_create")
    assert request.payload["cache"] == tab.model._cache_options
    cache.service.pending.remove(request)
    events: list[dict[str, Any]] = []
    create_root(str(target), request.payload["cache"], events.append)
    for event in events:
        cache.service.resultReady.emit(request, event)
    cache.service.resultReady.emit(request, {"kind": "done"})
    identifier = data_roots.read_marker(str(target)).uuid
    assert cache.root_of(str(target)) == (str(target), identifier, "run")
    # Listed again, with no time limit, so its rows show the new root.
    qtbot.waitUntil(lambda: ("list", str(target)) in cache.jobs)
    assert producer(cache, str(target), "list").timeout == float("inf")


def test_without_write_permission_the_dialog_hands_out_the_exact_file(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tab: FolderExplorer, tmp_path: Path,
) -> None:
    cache = tab.model.cache
    target = str(tmp_path / "run")
    monkeypatch.setattr(DataRootDialogs, "ask_place_root", lambda parent, folder_cache, path: path)
    assert tab.place_root(target)
    request = producer(cache, target, "root_create")
    _, contents = data_roots.new_marker(target)
    text = contents.decode("utf-8")
    cache.service.resultReady.emit(request, {"kind": "root_manual", "path": target, "name": ".helab-root",
                                             "contents": text, "reason": "Permission denied"})
    dialog = tab.findChild(ManualMarkerDialog)
    assert dialog is not None and dialog.isVisible()
    assert dialog.text.toPlainText() == text
    dialog.copy()
    clipboard = QApplication.clipboard()
    assert clipboard is not None and clipboard.text() == text
    saved = tmp_path / "saved" / ".helab-root"
    saved.parent.mkdir()
    dialog.write(str(saved.parent))
    assert saved.read_bytes() == contents
    dialog.close()


def test_settings_lists_roots_and_forgets_a_location_after_asking(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = frozen_service(monkeypatch)
    cache = FolderCache(service)
    jobs: list[tuple[str, dict[str, Any]]] = []

    def admin(action: str, **params: Any) -> str:
        jobs.append((action, params))
        return f"job-{len(jobs)}"
    monkeypatch.setattr(cache, "cache_admin", admin)
    monkeypatch.setattr("helab.views.DataRootsTab.store_options", lambda: {"directory": str(tmp_path)})
    page = DataRootsTab(cache)
    qtbot.addWidget(page)
    assert jobs == [("inventory", {})]
    rows = [{"location": "smb://server/dld_output", "uuid": str(uuid.uuid4()), "kind": "smb",
             "label": "dld_output", "first_seen": 1.0e9, "last_seen": 1.7e9, "decision": "confirmed",
             "path": "/Volumes/dld_output"},
            {"location": "vol://abc/data", "uuid": str(uuid.uuid4()), "kind": "vol", "label": "data",
             "first_seen": 1.0e9, "last_seen": 1.6e9, "decision": "pending", "path": ""}]
    cache.cacheAdminResult.emit("inventory", {"kind": "inventory", "inventory": {"roots": rows}})
    cache.cacheAdminDone.emit("job-1", "inventory", "")
    assert page.list.topLevelItemCount() == 2
    second = page.list.topLevelItem(1)
    assert second is not None and second.text(DataRootsTab.STATUS) == "Waiting: same folder or a copy?"
    assert "Folder" not in DataRootsTab.COLUMNS  # The path is in the lines below the list.
    assert (page.path_line.text(), page.uuid_line.text()) == ("", "")
    page.list.setCurrentItem(second)
    assert page.path_line.text() == "Not mounted · last seen at vol://abc/data"
    assert page.uuid_line.text() == f"UUID {rows[1]['uuid']}"
    first = page.list.topLevelItem(0)
    assert first is not None and first.text(DataRootsTab.STATUS) == "In use"
    page.list.setCurrentItem(first)
    assert page.path_line.text() == os.path.join("/Volumes/dld_output", ".helab-root")
    assert page.uuid_line.text() == f"UUID {rows[0]['uuid']}"
    assert page.forget_button.isEnabled()
    asked: list[str] = []

    def cancel(title: str, text: str, verb: str) -> bool:
        asked.append(text)
        return False
    page.confirm = cancel
    page.forget_selected()
    assert len(jobs) == 1 and "found again" in asked[0]  # Cancelled: nothing sent.
    page.confirm = lambda title, text, verb: True
    page.forget_selected()
    assert jobs[-1] == ("forget_root", {"location": "smb://server/dld_output"})
    page.detach()
    service.shutdown()


def test_confirmation_buttons_and_cancel_by_default_with_warnings(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = frozen_service(monkeypatch)
    cache = FolderCache(service)
    share = os.path.join(os.sep, "Volumes", "dld_output")
    deep = os.path.join(share, "run_042")
    mounts(cache, os.sep, share)

    def clicked(path: str, button: str) -> tuple[str | None, str]:
        box = DataRootDialogs.PlaceRootBox(None, cache, path)
        default = box.defaultButton()
        target = {"top": box.at_top, "here": box.here,
                  "cancel": box.button(QMessageBox.StandardButton.Cancel)}[button]
        assert target is not None
        target.click()
        return box.choice(), default.text() if default is not None else ""

    assert clicked(deep, "top") == (share, "Cancel")  # Return never writes where you didn't click.
    assert clicked(deep, "here") == (deep, "Cancel")
    assert clicked(deep, "cancel") == (None, "Cancel")
    assert clicked(share, "here") == (share, "Place .helab-root")  # No warnings: the action is the default.
    service.shutdown()


def test_saving_by_hand_writes_the_exact_name_and_says_it_is_hidden(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    folder = str(tmp_path / "share")
    _, contents = data_roots.new_marker(folder)
    monkeypatch.setattr(DataRootDialogs, "sys", types.SimpleNamespace(platform="darwin"))
    dialog = ManualMarkerDialog(None, folder, ".helab-root", contents.decode("utf-8"), "Read-only file system")
    qtbot.addWidget(dialog)
    save = next(button for button in dialog.findChildren(QPushButton) if button.text() == DataRootDialogs.SAVE_ACTION)
    assert "⌘⇧." in save.toolTip()
    target = tmp_path / "saved"
    target.mkdir()
    dialog.write(str(target))
    assert (target / ".helab-root").read_bytes() == contents
    assert dialog.intro.text() == DataRootDialogs.SAVED_TEXT.format(
        name=".helab-root", target=target, hidden=DataRootDialogs.hidden_hint(), folder=folder)
    assert "⌘⇧." in dialog.intro.text()
    # An existing file is replaced only on Yes.
    (target / ".helab-root").write_text("mine")
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    dialog.write(str(target))
    assert (target / ".helab-root").read_text() == "mine"
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    dialog.write(str(target))
    assert (target / ".helab-root").read_bytes() == contents


def test_placing_at_the_top_lists_the_clicked_folder_again_too(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tab: FolderExplorer, tmp_path: Path,
) -> None:
    cache = tab.model.cache
    replay(qtbot, cache, str(tmp_path), "list", lambda send: list_folder(str(tmp_path), send,
                                                                        tab.model._cache_options))
    clicked, top = str(tmp_path / "run"), str(tmp_path.parent)  # The top isn't in this tab's tree.
    monkeypatch.setattr(DataRootDialogs, "ask_place_root", lambda parent, folder_cache, path: top)
    assert tab.place_root(clicked)
    request = producer(cache, top, "root_create")
    assert request.payload["clicked"] == clicked
    cache.service.pending.remove(request)
    cache.service.resultReady.emit(request, {"kind": "root_created", "path": top, "uuid": str(uuid.uuid4()),
                                             "label": "top"})
    qtbot.waitUntil(lambda: ("list", clicked) in cache.jobs)
    assert ("list", top) not in cache.jobs


def test_deleting_a_root_lists_the_tabs_folders_inside_it_again(
    qtbot: QtBot, tab: FolderExplorer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tab.model.cache
    replay(qtbot, cache, str(tmp_path), "list", lambda send: list_folder(str(tmp_path), send,
                                                                        tab.model._cache_options))
    run = str(tmp_path / "run")
    tab.selected_path_globally = run
    refreshed: list[str] = []
    monkeypatch.setattr(tab, "refresh_folder", refreshed.append)
    request = IORequest("settings", 0, str(tmp_path), "root_remove", {}, 60.0)
    cache.service.resultReady.emit(request, {"kind": "root_changed", "path": str(tmp_path),
                                             "location": "vol://test/x", "reason": "removed"})
    cache.service.resultReady.emit(request, {"kind": "root_removed", "path": str(tmp_path),
                                             "uuid": str(uuid.uuid4()), "forgotten": ["vol://test/x"]})
    assert refreshed == [str(tmp_path), run]  # The tab's top folder, and its selection inside the root.
    assert cache.root_of(run) is None
    refreshed.clear()
    # A root above the tab's top folder (which is no row of its own here): its top and selection.
    cache.service.resultReady.emit(request, {"kind": "root_removed", "path": str(tmp_path.parent),
                                             "uuid": str(uuid.uuid4()), "forgotten": []})
    assert refreshed == ([str(tmp_path), run] if str(tmp_path) in tab.model.nodes else [run])


def pending(cache: FolderCache, path: str, other: str = "/Volumes/C/data") -> str:
    """A helper found this folder's .helab-root also at ``other``: Same folder or a copy?"""
    location = f"smb://server/share/{os.path.basename(path)}"
    request = IORequest("helper", 0, path, "list", {}, 60.0)
    cache.service.resultReady.emit(request, {
        "kind": "root_duplicate", "path": path, "location": location, "uuid": str(uuid.uuid4()),
        "label": "run", "other_locations": ["smb://pc/c/data"], "marker": None,
        "others": [{"location": "smb://pc/c/data", "path": other, "marker": None}]})
    return location


def test_a_pending_location_warns_on_its_rows_tooltip_and_summary_until_answered(
    qtbot: QtBot, tab: FolderExplorer, tmp_path: Path,
) -> None:
    from helab.utils.folder_cache import PENDING_SUMMARY
    model, cache = tab.model, tab.model.cache
    run, inner = tmp_path / "run", tmp_path / "run" / "a"
    inner.mkdir()
    replay(qtbot, cache, str(tmp_path), "list", lambda send: list_folder(str(tmp_path), send, model._cache_options))
    model.request_scan(str(run), priority=True)
    qtbot.waitUntil(lambda: ("list", str(run)) in cache.jobs)
    replay(qtbot, cache, str(run), "list", lambda send: list_folder(str(run), send, model._cache_options))
    warning = StatusIcons.ICONS_EXTRA["root_pending"].cacheKey()

    def badges(path: Path) -> list[int]:
        icons = model.data(model.path_index(str(path), model.COLUMN_STATUS_ICON), model.STATUS_EXTRA_ICONS_ROLE)
        assert isinstance(icons, list)
        return [icon.cacheKey() for icon in icons if not isinstance(icon, str)]

    def tooltip(path: Path) -> str:
        return str(model.data(model.path_index(str(path), model.COLUMN_NAME), Qt.ItemDataRole.ToolTipRole))
    changed: list[int] = []
    model.dataChanged.connect(lambda top, bottom, roles: changed.append(top.row()))
    location = pending(cache, str(run))
    assert changed  # The rows were told to repaint.
    line = "Data root “run” also seen at /Volumes/C/data: same folder or a copy? RAM only until answered."
    for path in (run, inner):
        assert badges(path)[0] == warning  # Beside the status icon, before the anchor.
        assert line in tooltip(path).splitlines()
    assert warning not in badges(tmp_path / "other")
    tab.selected_path_globally = str(inner)
    tab._update_activity()
    assert tab.folder_cache_label.text() == PENDING_SUMMARY
    assert line in tab.folder_cache_label.toolTip()
    assert not tab.root_review_button.isHidden()
    reviews: list[str] = []
    tab.reviewRootRequested.connect(reviews.append)
    tab.root_review_button.click()
    assert reviews == [location]
    # Same folder: the warnings go.
    cache.service.resultReady.emit(IORequest("helper", 0, str(run), "cache_admin", {}, 60.0), {
        "kind": "root_confirmed", "location": location, "path": str(run), "uuid": str(uuid.uuid4()),
        "label": "run"})
    for path in (run, inner):
        assert warning not in badges(path) and line not in tooltip(path).splitlines()
    tab._update_activity()
    assert tab.folder_cache_label.text() != PENDING_SUMMARY and tab.root_review_button.isHidden()
    # Pending again, then It's a copy… (reassigned), then forgotten: each clears it.
    location = pending(cache, str(run))
    assert badges(run)[0] == warning
    cache.service.resultReady.emit(IORequest("helper", 0, str(run), "root_reassign", {"duplicate": location},
                                             60.0), {"kind": "root_reassigned", "path": str(run), "moved": []})
    assert warning not in badges(run)
    location = pending(cache, str(run))
    cache.service.resultReady.emit(IORequest("helper", 0, str(run), "cache_admin", {}, 60.0), {
        "kind": "root_changed", "path": str(run), "location": location, "reason": "forgotten"})
    assert warning not in badges(inner)


def test_settings_review_opens_the_duplicates_window_at_a_pending_row(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from helab.views.DataRootsTab import REVIEW
    service = frozen_service(monkeypatch)
    cache = FolderCache(service)
    monkeypatch.setattr(cache, "cache_admin", lambda action, **params: "job")
    monkeypatch.setattr("helab.views.DataRootsTab.store_options", lambda: {"directory": str(tmp_path)})
    page = DataRootsTab(cache)
    qtbot.addWidget(page)
    rows = [{"location": loc, "uuid": str(uuid.uuid4()), "kind": "smb", "label": "run", "first_seen": 1.0e9,
             "last_seen": 1.7e9, "decision": decision, "path": "/Volumes/run"}
            for loc, decision in (("smb://a/run", "confirmed"), ("smb://b/run", "pending"))]
    cache.cacheAdminResult.emit("inventory", {"kind": "inventory", "inventory": {"roots": rows}})
    asked: list[str] = []
    page.reviewRequested.connect(asked.append)
    for index, expected in ((0, False), (1, True)):
        item = page.list.topLevelItem(index)
        assert item is not None
        page.list.setCurrentItem(item)
        assert page.review_button.isEnabled() is expected
        assert any(action.text() == REVIEW for action in page.context_menu().actions()) is expected
    page.review_button.click()
    assert asked == ["smb://b/run"]
    page.detach()
    service.shutdown()
