"""Every variant of the folder-tree row tooltip, built from in-memory row states.

The tooltip has one fact per line in a fixed order (see ``SnapshotFileSystemModel._tooltip``);
each case asserts the whole text, so wording, order and omissions are all covered.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Iterator
import time

import pytest
from pytestqt.qtbot import QtBot

from helab.models.SnapshotFileSystemModel import FolderNode, SnapshotFileSystemModel, _stamp
from helab.models.StatusReport import StatusReport
from helab.utils.folder_cache import CacheStatus
from helab.utils.io_service import IORequest, IOService

PATH = "/data/F"
NOW = time.time()
SCANNED = NOW - 7200
BEFORE, AFTER = SCANNED - 600, SCANNED + 600


@pytest.fixture
def model(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> Iterator[SnapshotFileSystemModel]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    built = SnapshotFileSystemModel(service=service)
    yield built
    built.close_cleanup()
    service.shutdown()


def stamp(timestamp: float) -> str:
    return _stamp(timestamp)


def checked(status: str, raw: list[int], txy: list[int], **fields: object) -> FolderNode:
    """A row with a status check (scanned 2h ago, folder modified before it), then ``fields``."""
    path = str(fields.pop("path", PATH))
    node = FolderNode(path, report=StatusReport(path, status, len(set(raw) & set(txy)), [], raw, txy,
                                                datetime.fromtimestamp(SCANNED)),
                      scanned_at=SCANNED, modified=BEFORE, raw_count=len(raw), txy_count=len(txy))
    for name, value in fields.items():
        assert hasattr(node, name), name
        setattr(node, name, value)
    return node


def leaf(status: str = "ok", raw: list[int] | None = None, txy: list[int] | None = None, **fields: object) -> FolderNode:
    fields.setdefault("loaded", True)
    return checked(status, [1, 2] if raw is None else raw, [1, 2] if txy is None else txy, **fields)


def derived(model: SnapshotFileSystemModel, node: FolderNode) -> FolderNode:
    """Apply what the model derives on a listing (e.g. a saved subfolder result)."""
    model._derive(node)
    return node


def saved_on(model: SnapshotFileSystemModel, node: FolderNode) -> FolderNode:
    """A saved subfolder result arrives for the folder (as a listing sends it)."""
    node.subtree_saved = {"status": "something", "derived_at": SCANNED, "older": False, "identity": None,
                          "data": 2, "checked": 3, "total": 4}
    return derived(model, node)


def with_children(model: SnapshotFileSystemModel, statuses: list[str | None], *,
                  child_modified: float = BEFORE) -> FolderNode:
    node = checked("unknown", [], [], loaded=True)
    for row, status in enumerate(statuses):
        path = f"{PATH}/c{row}"
        child = (FolderNode(path, node, row) if status is None else checked(
            status, [1] if status == "ok" else [], [1] if status == "ok" else [], path=path,
            modified=child_modified, loaded=True))
        child.parent, child.row = node, row
        node.children.append(child)
    model._derive(node)
    return node


HEAD = [PATH]
CHECKED_LINES = [f"Folder modified: {stamp(BEFORE)}", f"Status checked: {stamp(SCANNED)}"]
Case = Callable[[SnapshotFileSystemModel], tuple[FolderNode, str]]
CASES: dict[str, tuple[Case, list[str]]] = {
    # Here: the folder's own files.
    "not checked": (lambda m: (FolderNode(PATH), ""),
                    HEAD + ["Here: not checked yet", "Subfolders: not listed yet", "Select the folder to check it."]),
    "ok": (lambda m: (leaf(), ""), HEAD + ["Here: 2 shots, all converted", "Subfolders: none"] + CHECKED_LINES),
    "one shot": (lambda m: (leaf(raw=[1], txy=[1]), ""),
                 HEAD + ["Here: 1 shot, all converted", "Subfolders: none"] + CHECKED_LINES),
    "fixable": (lambda m: (leaf("fixable", raw=[1, 2, 3]), ""),
                HEAD + ["Here: 2 of 3 shots converted", "Subfolders: none"] + CHECKED_LINES),
    "raw only": (lambda m: (leaf("warning", txy=[]), ""),
                 HEAD + ["Here: 2 shots, none converted", "Subfolders: none"] + CHECKED_LINES),
    "converted only": (lambda m: (leaf("warning", raw=[]), ""),
                       HEAD + ["Here: 2 shots converted, no raw files", "Subfolders: none"] + CHECKED_LINES),
    "mismatch": (lambda m: (leaf("warning", raw=[1, 2], txy=[2, 3]), ""),
                 HEAD + ["Here: 2 raw, 2 converted · raw and converted shots do not match", "Subfolders: none"]
                 + CHECKED_LINES),
    "critical": (lambda m: (leaf("critical", raw=[1], txy=[1, 2]), ""),
                 HEAD + ["Here: 1 raw, 2 converted · converted shots without matching raw files", "Subfolders: none"]
                 + CHECKED_LINES),
    "empty": (lambda m: (leaf("nothing", raw=[], txy=[], empty=True), ""),
              HEAD + ["Here: empty folder", "Subfolders: none"] + CHECKED_LINES),
    # Status cache (loaded, not rechecked) vs checked: freshness notes.
    "cache unchanged, no subfolders saved": (
        lambda m: (leaf(cached_report=True, loaded=False, has_dirs=False), ""),
        HEAD + ["Here: 2 shots, all converted", "Subfolders: none", f"Folder modified: {stamp(BEFORE)}",
                f"Status cache: {stamp(SCANNED)} · folder not modified since", "Select the folder to check it again."]),
    "cache outdated": (
        lambda m: (leaf(cached_report=True, modified=AFTER), ""),
        HEAD + ["Here: 2 shots, all converted", "Subfolders: none", f"Folder modified: {stamp(AFTER)}",
                f"Status cache: {stamp(SCANNED)} · may be outdated", "Select the folder to check it again."]),
    "cache freshness unknown": (
        lambda m: (leaf(cached_report=True, modified=None), ""),
        HEAD + ["Here: 2 shots, all converted", "Subfolders: none", "Folder modified: not known yet",
                f"Status cache: {stamp(SCANNED)} · freshness unknown", "Select the folder to check it again."]),
    "checked, freshness unknown": (
        lambda m: (leaf(modified=None), ""),
        HEAD + ["Here: 2 shots, all converted", "Subfolders: none", "Folder modified: not known yet",
                f"Status checked: {stamp(SCANNED)}"]),
    "checked, outdated": (
        lambda m: (leaf(modified=AFTER), ""),
        HEAD + ["Here: 2 shots, all converted", "Subfolders: none", f"Folder modified: {stamp(AFTER)}",
                f"Status checked: {stamp(SCANNED)} · may be outdated", "Select the folder to check it again."]),
    "scan date not recorded": (
        lambda m: (leaf(scanned_at=None), ""),
        HEAD + ["Here: 2 shots, all converted", "Subfolders: none", f"Folder modified: {stamp(BEFORE)}",
                "Status checked: date not recorded"]),
    # Subfolders: listed in this tab, or saved.
    "unlisted with subfolders": (
        lambda m: (leaf("unknown", raw=[], txy=[], loaded=False, has_dirs=True), ""),
        HEAD + ["Here: no TXY files", "Subfolders: not listed yet"] + CHECKED_LINES),
    "none checked": (lambda m: (with_children(m, [None, None, None]), ""),
                     HEAD + ["Here: no TXY files", "Subfolders: 3 · none checked yet"] + CHECKED_LINES),
    "some checked": (lambda m: (with_children(m, ["nothing", None, None]), ""),
                     HEAD + ["Here: no TXY files", "Subfolders: 3 · 1 checked, no TXY data so far"] + CHECKED_LINES),
    "all checked, nothing": (lambda m: (with_children(m, ["nothing", "nothing"]), ""),
                             HEAD + ["Here: no TXY files", "Subfolders: 2 · all checked, no TXY data"] + CHECKED_LINES),
    "data in a subfolder": (lambda m: (with_children(m, ["ok", "nothing", None]), ""),
                            HEAD + ["Here: no TXY files", "Subfolders: 3 · TXY data in 1"] + CHECKED_LINES),
    "data in an outdated subfolder": (
        lambda m: (with_children(m, ["ok"], child_modified=AFTER), ""),
        HEAD + ["Here: no TXY files", "Subfolders: 1 · TXY data in 1 · may be outdated"] + CHECKED_LINES
        + ["Select the outdated subfolder to check it again."]),
    "listed, none checked, saved derivation shows": (
        lambda m: (saved_on(m, with_children(m, [None, None, None])), ""),
        HEAD + ["Here: no TXY files", f"Subfolders: 4 · TXY data in 2 · saved {stamp(SCANNED)}"] + CHECKED_LINES
        + ["Select the folder to check it again."]),
    "saved derivation": (
        lambda m: (derived(m, leaf("unknown", raw=[], txy=[], cached_report=True, loaded=False, subtree_saved={
            "status": "something", "derived_at": SCANNED, "older": False, "identity": None,
            "data": 2, "checked": 3, "total": 4})), ""),
        HEAD + ["Here: no TXY files", f"Subfolders: 4 · TXY data in 2 · saved {stamp(SCANNED)}",
                f"Folder modified: {stamp(BEFORE)}", f"Status cache: {stamp(SCANNED)} · folder not modified since",
                "Select the folder to check it again."]),
    "saved derivation, outdated": (
        lambda m: (derived(m, leaf("unknown", raw=[], txy=[], cached_report=True, loaded=False, subtree_saved={
            "status": "nothing", "derived_at": SCANNED, "older": True, "identity": None,
            "data": 0, "checked": 2, "total": 2})), ""),
        HEAD + ["Here: no TXY files", f"Subfolders: 2 · all checked, no TXY data · saved {stamp(SCANNED)} · may be outdated",
                f"Folder modified: {stamp(BEFORE)}", f"Status cache: {stamp(SCANNED)} · folder not modified since",
                "Select the folder to check it again."]),
    # Activity: start times, no hint while busy.
    "listing": (lambda m: (leaf(state="running", state_since=SCANNED), ""),
                HEAD + [f"Listing folder… since {datetime.fromtimestamp(SCANNED):%H:%M:%S} · showing last results",
                        "Here: 2 shots, all converted", "Subfolders: none"] + CHECKED_LINES),
    "queued check, no time limit": (
        lambda m: (leaf(state="queued", state_since=SCANNED, retry_since=time.monotonic()), "scan"),
        HEAD + [f"Queued to check folder status since {datetime.fromtimestamp(SCANNED):%H:%M:%S} · no time limit"
                " · showing last results", "Here: 2 shots, all converted", "Subfolders: none"] + CHECKED_LINES),
    "checking, never checked before": (
        lambda m: (FolderNode(PATH, state="running"), "scan"),
        HEAD + ["Checking folder status…", "Here: not checked yet", "Subfolders: not listed yet"]),
    "failed": (lambda m: (leaf(state="error", error="Folder listing timed out — Retry"), ""),
               HEAD + ["Last check failed: Folder listing timed out · showing earlier results",
                       "Here: 2 shots, all converted", "Subfolders: none"] + CHECKED_LINES
               + ["Use Retry / Refresh to try again."]),
    "cancelled": (lambda m: (leaf(state="cancelled", error="Cancelled — Retry"), ""),
                  HEAD + ["Last check cancelled · showing earlier results", "Here: 2 shots, all converted",
                          "Subfolders: none"] + CHECKED_LINES + ["Use Retry / Refresh to try again."]),
}


@pytest.mark.parametrize("case", CASES)
def test_row_tooltip(model: SnapshotFileSystemModel, case: str) -> None:
    build, expected = CASES[case]
    node, operation = build(model)
    if operation:
        model._tree_requests[PATH] = IORequest("owner", 0, PATH, operation, {}, 60)
    assert model._tooltip(node, "").splitlines() == expected


@pytest.mark.parametrize("load_state, line", [("loading", "Loading dataset…"), ("queued", "Queued to load dataset"),
                                              ("paused", "Loading paused while the current tab browses or loads")])
def test_load_states_replace_the_hint(model: SnapshotFileSystemModel, load_state: str, line: str) -> None:
    node = leaf(cached_report=True, modified=AFTER)  # Would otherwise ask to check again.
    assert model._tooltip(node, load_state).splitlines() == HEAD + [
        line, "Here: 2 shots, all converted", "Subfolders: none", f"Folder modified: {stamp(AFTER)}",
        f"Status cache: {stamp(SCANNED)} · may be outdated"]


@pytest.mark.parametrize("modified, note", [(BEFORE, " · folder not modified since"), (AFTER, " · may be outdated"),
                                            (None, " · freshness unknown")],
                         ids=["unchanged", "outdated", "unknown"])  # Stable across xdist workers.
def test_data_cache_line_has_its_own_date_and_freshness(
    model: SnapshotFileSystemModel, modified: float | None, note: str,
) -> None:
    saved = SCANNED + 60
    model.cache._set_disk_cached(PATH, True)
    model.cache._cache_states[PATH] = CacheStatus({"saved_at": saved})
    lines = model._tooltip(leaf(modified=modified), "").splitlines()
    assert lines[3:] == [f"Folder modified: {stamp(modified) if modified is not None else 'not known yet'}",
                         f"Status checked: {stamp(SCANNED)}" + ("" if modified != AFTER else " · may be outdated"),
                         f"Data cache: {stamp(saved)}{note}"] + (
        ["Select the folder to check it again."] if modified == AFTER else [])


def test_history_save_warning_line(model: SnapshotFileSystemModel) -> None:
    model.cache.scan_history_errors[PATH] = "Scan history save failed; suppression is session-only."
    assert model._tooltip(leaf(), "").splitlines()[-1] == "Scan history save failed; suppression is session-only."


def test_stamp_formats_exact_time_and_age() -> None:
    assert _stamp(NOW - 7200) == f"{datetime.fromtimestamp(NOW - 7200):%Y-%m-%d %H:%M:%S} (2h ago)"
    assert _stamp(None) == _stamp(1e20) == "date not recorded"
