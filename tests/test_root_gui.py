"""Data roots in the GUI (D3): Place .helab-root here…, the ANCHOR badge, Folder details' Disk
cache row, the manual-placement dialog and Settings → Data roots."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Iterator
import uuid

import numpy as np
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox
from pytestqt.qtbot import QtBot

from helab import io_helper
from helab.io_helper import list_folder
from helab.resources.icons import IconsInitUtil, StatusIcons
from helab.utils import data_roots
from helab.utils.folder_cache import (NEEDS_ROOT_TOOLTIP, PLACE_ROOT_TOOLTIP, RAM_ONLY, FolderCache,
                                      data_root_row)
from helab.utils.io_service import IORequest, IOService
from helab.views import DataRootDialogs
from helab.views.DataRootDialogs import NESTED, NOT_TOP, SYSTEM, ManualMarkerDialog, placement_checks
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
    # The system volume's top is never suggested; a system or home folder is warned about.
    assert placement_checks(cache, os.path.join(os.path.expanduser("~"), "data")) == (None, [])
    assert placement_checks(cache, os.path.expanduser("~")) == (None, [SYSTEM])
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
    assert NEEDS_ROOT_TOOLTIP.startswith("No .helab-root above this folder")


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
    io_helper.create_root(str(target), request.payload["cache"], events.append)
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
    dialog.write(str(saved))
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
    assert second is not None and second.text(1) == "Not mounted · vol://abc/data"
    assert second.text(2) == "Waiting: same folder or a copy?"
    first = page.list.topLevelItem(0)
    assert first is not None
    page.list.setCurrentItem(first)
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


def test_saving_by_hand_uses_a_visible_name_and_says_to_rename_it(qtbot: QtBot, tmp_path: Path) -> None:
    folder = str(tmp_path / "share")
    _, contents = data_roots.new_marker(folder)
    dialog = ManualMarkerDialog(None, folder, ".helab-root", contents.decode("utf-8"), "Read-only file system")
    qtbot.addWidget(dialog)
    target = tmp_path / DataRootDialogs.SAVE_NAME
    dialog.write(str(target))
    assert target.read_bytes() == contents
    assert dialog.intro.text() == DataRootDialogs.SAVED_TEXT.format(target=target, name=".helab-root",
                                                                    folder=folder)


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
