"""Q33.1: a folder memory knows has no subfolders is selected where it is (double-click) or in its
parent (a typed path), not made the tree's top; one with subfolders, or never listed, opens as before."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Iterator

import pytest
from pytestqt.qtbot import QtBot

from helab.utils.folder_cache import get_folder_cache
from helab.utils.io_service import IOService
from helab.views.FolderExplorer import FolderExplorer

pytestmark = pytest.mark.no_auto_data_root


def summary(has_dirs: bool) -> dict[str, Any]:
    return {"status": "ok", "count": 2, "raw": [1, 2], "txy": [1, 2], "scanned_at": time.time() - 60,
            "has_dirs": has_dirs}


@pytest.fixture
def explorer(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FolderExplorer]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    root = str(tmp_path)
    explorer = FolderExplorer(root, root, root, [0, 4, 5])
    qtbot.addWidget(explorer)
    try:
        list_root(qtbot, explorer, service, root)
        yield explorer
    finally:
        explorer.close_cleanup()
        service.shutdown()


def list_root(qtbot: QtBot, explorer: FolderExplorer, service: IOService, root: str) -> None:
    """The root's listing, from memory events: a leaf, a parent and a folder never scanned."""
    cache = get_folder_cache(service)
    qtbot.waitUntil(lambda: ("list", root) in cache.jobs)
    listing = next(r for r in service.pending if r.operation == "list" and r.path == root)
    entries = [{"path": os.path.join(root, "leaf"), "modified": None, "scan_status": summary(False)},
               {"path": os.path.join(root, "parent"), "modified": None, "scan_status": summary(True)},
               {"path": os.path.join(root, "unknown"), "modified": None}]
    for event in ({"kind": "entries", "entries": entries},
                  {"kind": "status", "status": "nothing", "count": 0, "raw": [], "txy": [], "details": True,
                   "modified": 0, "signature": "v1", "scanned_at": time.time()}, {"kind": "done"}):
        service.resultReady.emit(listing, event)
    service.pending.remove(listing)
    qtbot.waitUntil(lambda: all(os.path.join(root, name) in explorer.model.nodes
                                for name in ("leaf", "parent", "unknown")))


def test_double_click_selects_a_folder_without_subfolders(explorer: FolderExplorer, tmp_path: Path) -> None:
    root, leaf = str(tmp_path), str(tmp_path / "leaf")
    assert explorer.without_subfolders(leaf)
    explorer.on_double_click(explorer.model.path_index(leaf))
    assert explorer.view_path == root and explorer.selected_path_globally == leaf
    assert explorer.tree.currentIndex() == explorer.model.path_index(leaf)


@pytest.mark.parametrize("name", ["parent", "unknown"])
def test_double_click_opens_a_folder_with_or_maybe_with_subfolders(explorer: FolderExplorer, tmp_path: Path,
                                                                   name: str) -> None:
    folder = str(tmp_path / name)
    assert not explorer.without_subfolders(folder)
    explorer.on_double_click(explorer.model.path_index(folder))
    assert explorer.view_path == folder


@pytest.mark.parametrize("listed", ["from memory", "listed again"])
def test_a_typed_folder_without_subfolders_opens_its_parent_with_its_row_selected(
    qtbot: QtBot, explorer: FolderExplorer, tmp_path: Path, listed: str,
) -> None:
    root, leaf = str(tmp_path), str(tmp_path / "leaf")
    explorer.on_double_click(explorer.model.path_index(str(tmp_path / "parent")))  # Somewhere else first.
    assert explorer.view_path == str(tmp_path / "parent") and leaf not in explorer.model.nodes
    cache = explorer.model.cache
    if listed == "listed again":
        cache.snapshots.clear()  # The root's listing is gone: its rows come with the next one.
    explorer.path_edit.setText(leaf)
    explorer._navigate_input()  # Memory knows it from the root's listing (the session's scan summary).
    assert explorer.view_path == root
    if listed == "listed again":
        assert explorer._select_when_listed == leaf
        list_root(qtbot, explorer, cache.service, root)
    qtbot.waitUntil(lambda: explorer.selected_path_globally == leaf)
    assert explorer.view_path == root and explorer._select_when_listed is None
    assert explorer.tree.currentIndex() == explorer.model.path_index(leaf)


@pytest.mark.parametrize("name", ["parent", "unknown"])
def test_a_typed_folder_with_or_maybe_with_subfolders_opens_as_the_top(explorer: FolderExplorer, tmp_path: Path,
                                                                       name: str) -> None:
    folder = str(tmp_path / name)
    explorer.path_edit.setText(folder)
    explorer._navigate_input()
    assert explorer.view_path == folder and explorer._select_when_listed is None


def test_choosing_another_row_first_drops_the_typed_selection(qtbot: QtBot, explorer: FolderExplorer,
                                                              tmp_path: Path) -> None:
    root, leaf = str(tmp_path), str(tmp_path / "leaf")
    explorer.model.cache.snapshots.clear()
    explorer.path_edit.setText(leaf)
    explorer._navigate_input()
    assert explorer._select_when_listed == leaf
    list_root(qtbot, explorer, explorer.model.cache.service, root)
    explorer._select_when_listed = leaf  # (As if the posted selection hadn't run yet.)
    explorer.tree.setCurrentIndex(explorer.model.path_index(str(tmp_path / "parent")))
    assert explorer._select_when_listed is None
    qtbot.wait(20)
    assert explorer.selected_path_globally == str(tmp_path / "parent")
