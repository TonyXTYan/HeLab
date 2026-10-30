from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator
import time
import os
import re
import threading

import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDockWidget, QLabel

from helab.io_ops.browse import list_folder
from helab.io_ops.loading import load
from helab.io_ops.scanning import scan
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IORequest, IOService
from helab.views.CentralHint import CentralHint
from helab.views.FolderDetailsPanel import FolderDetailsPanel
from helab.views.FolderExplorer import FolderExplorer
from helab.views.HelabMainWindow import HelabMainWindow
from helab.views.plots.workspace import PlotWorkspace
from helab.resources.icons import IconsInitUtil, StatusIcons
from helab.utils.cache_freshness import CacheFreshness


@pytest.fixture
def browser(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FolderExplorer]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    explorer = FolderExplorer(str(tmp_path), str(tmp_path), str(tmp_path), [0, 4, 5])
    qtbot.addWidget(explorer)
    qtbot.waitUntil(lambda: ("list", str(tmp_path)) in explorer.model.cache.jobs)
    yield explorer
    explorer.close_cleanup()
    service.shutdown()


def request_for(cache: FolderCache, path: str, operation: str) -> IORequest:
    job = cache.jobs[(operation, path)]
    return next(request for request in cache.service.pending if request.owner == job.owner)


def run_helper(explorer: FolderExplorer, qtbot: QtBot, path: str, operation: str,
               options: dict[str, Any] | None = None) -> None:
    """Replay a real helper's events into the queued request, then wait for delivery."""
    cache = explorer.model.cache
    request = request_for(cache, path, operation)
    events: list[Any] = []
    if operation == "list":
        list_folder(path, events.append, options)
    else:
        scan(path, events.append, options)
    for event in events:
        cache.service.resultReady.emit(request, event)
    cache.service.resultReady.emit(request, {"kind": "done"})
    cache.service.pending.remove(request)
    qtbot.waitUntil(lambda: not cache.has_request(explorer.model.owner, operation, path))


def complete_scan(explorer: FolderExplorer, qtbot: QtBot, path: str,
                  options: dict[str, Any] | None = None, *, details: bool = True) -> None:
    """Browse (list, then the background details scan) or finish a folder status check."""
    cache = explorer.model.cache
    if ("list", path) in cache.jobs:
        run_helper(explorer, qtbot, path, "list", options)
        qtbot.waitUntil(lambda: explorer.model.nodes[path].loaded and explorer.model.nodes[path].state == "idle")
        if details and ("details", path) in cache.jobs:
            run_helper(explorer, qtbot, path, "details", options)
    else:
        run_helper(explorer, qtbot, path, "scan", options)
        qtbot.waitUntil(lambda: explorer.model.nodes[path].loaded and explorer.model.nodes[path].state == "idle")
    explorer._update_activity()


@pytest.mark.parametrize("contents, expected", [
    ("empty", "Folder is empty"),
    ("unrelated", "No TXY files in this folder"),
    ("subfolder", "No TXY files here · Select a subfolder to load data"),
    ("raw", "1 raw shot found · No converted TXY files"),
])
def test_non_data_folder_summary(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path, contents: str, expected: str,
) -> None:
    if contents == "unrelated":
        (tmp_path / "notes.txt").write_text("experiment notes")
    elif contents == "subfolder":
        child = tmp_path / "run"
        child.mkdir()
        (child / "d_txy_forc1.txt").write_text("1,2,3\n")
    elif contents == "raw":
        (tmp_path / "d1.txt").write_text("")
    assert browser.folder_summary_label.text() == "Scan queued"
    assert browser.folder_freshness_label.text() == "Live updates off"
    assert browser.folder_cache_label.text() == "Cache not checked"
    complete_scan(browser, qtbot, str(tmp_path))
    assert browser.folder_summary_label.text() == expected
    assert "Live updates off" in browser.folder_freshness_label.text()
    assert browser.selected_folder_label.isHidden()
    assert browser.deselect_button.isHidden()
    assert browser.folder_cache_label.text() == "No data to cache"


def test_folder_details_and_hint_describe_each_folder_state(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    browser.auto_load_ram = False
    child = tmp_path / "run"
    child.mkdir()
    (child / "d_txy_forc1.txt").write_text("1,2,3\n")
    root, path = str(tmp_path), str(child)
    window: Any = SimpleNamespace(
        _closing=False, tab_widget=SimpleNamespace(currentWidget=lambda: browser),
        plots=SimpleNamespace(central_placeholder=CentralHint(parent=browser), dock_widgets=[]),
        folder_details=FolderDetailsPanel(browser))
    panel = window.folder_details

    def show() -> tuple[str, str]:
        browser._update_activity()
        HelabMainWindow._update_folder_details(window)
        return panel.text("state"), window.plots.central_placeholder.text()

    complete_scan(browser, qtbot, root)
    assert show() == ("No TXY files here", f"No TXY files in {tmp_path.name} — select a data folder")
    browser.tree.setCurrentIndex(browser.model.path_index(path))
    complete_scan(browser, qtbot, path)
    assert show() == ("Not loaded", "run is not loaded — right-click it › Load data")
    assert panel.text("files") == "1 TXY found"
    # Browsing past folders while another load runs: the countdown to queueing.
    cache = browser.model.cache
    cache.submit("other-tab", 0, str(tmp_path / "other"), "load")
    browser.load_mode = "queue"
    assert browser.load_to_ram_cache(path) and browser.load_waiting
    assert show() == ("Waiting · queues in 3 s if still selected", "Waiting to load run…")
    browser.cancel_load_button.click()
    cache.cancel("other-tab")
    assert browser.load_to_ram_cache(path, dwell=False)
    assert show() == ("Queued", "Queued run…")
    request = request_for(cache, path, "load")
    cache.service.resultReady.emit(request, {"kind": "started"})
    assert show() == ("Loading", "Loading run…")
    cache.service.resultReady.emit(request, {"kind": "shot", "shot": 1, "array": np.ones((1, 3))})
    cache.service.resultReady.emit(request, {
        "kind": "loaded", "signature": browser.model.nodes[path].signature, "files": 1, "rows": 1,
        "bytes": 24, "problematic": [1], "failed_files": 0, "total_files": 1, "source": "files"})
    cache.service.pending.remove(request)
    assert show() == ("Loaded", "Loaded run — run a script to plot it")
    assert panel.text("files") == "1 TXY found · 1 loaded"
    assert panel.text("data") == "1 data row · 24B in RAM"
    assert panel.text("source") == "TXY files"
    assert panel.text("errors") == "1 shot unreadable or with invalid rows"
    # No TXY bytes were reported read, so there is no load time to show.
    assert panel.text("loaded").endswith("just now") and "took" not in panel.text("loaded")
    # Data shown before its check, a failed check, and data the folder has moved on from.
    browser._unchecked_path = path
    assert show() == ("Loaded from cache · not checked yet", "Loaded run — run a script to plot it")
    cache.service.offline = True  # Offline, as the summary says it (A33.2).
    try:
        assert show()[0] == "Loaded from cache · not checked (offline)"
        assert browser.folder_cache_label.text().endswith("not checked (offline)")
    finally:
        cache.service.offline = False
    browser.load_error = "Timed out — Retry"
    assert show() == ("Check failed · Timed out — Retry", "Could not check run — see Folder details")
    browser.load_error = ""
    browser.model.nodes[path].signature = "changed"  # Not answerable from memory: a real check runs.
    assert browser.load_to_ram_cache(path, dwell=False) and browser.load_is_check
    request = request_for(cache, path, "load")
    cache.service.resultReady.emit(request, {"kind": "started"})
    assert show() == ("Checking for changes", "Checking run for changes…")
    assert browser.activity_brief == "Checking run · 0:00"
    cache.service.resultReady.emit(request, {"kind": "paused"})
    assert show() == ("Paused", "Check paused: run…")
    browser.cancel_load_button.click()
    browser.folder_opened_path = None
    browser.load_error = ""
    assert show() == ("Folder changed · showing previous data", "Showing previous data for run — see Folder details")
    assert browser.displayed_dataset is not None
    browser.model.nodes[path].signature = browser.displayed_dataset.signature  # E.g. the cache was cleared.
    assert show()[0] == "Showing previous data"
    # Metadata the panel cannot make sense of is shown as zero or left out, never raised.
    rows: dict[str, tuple[str, str]] = {}
    FolderDetailsPanel._data_rows(browser, {"rows": None, "bytes": "x", "loaded_at": 1e30, "files": float("nan"),
                                            "load_seconds": "slow", "problematic": "1, 2"}, rows, False, False)
    assert rows["data"][0] == "0 data rows · 0B in RAM"
    assert rows["files"][0] == "0 TXY found · 0 loaded"
    assert "loaded" not in rows and "errors" not in rows
    # A check answered without reading files has no load time; it says it found no change.
    FolderDetailsPanel._data_rows(browser, {"loaded_at": time.time(), "unchanged": True}, rows, False, False)
    assert rows["loaded"][0].endswith("just now · checked, unchanged")


def test_offline_folder_details_agree_with_the_summary(browser: FolderExplorer, monkeypatch: pytest.MonkeyPatch) -> None:
    """A33.2: offline, data shown unchecked is "not checked (offline)" in Folder details' rows as in the
    summary, never "checked, unchanged" from an earlier check."""
    monkeypatch.setattr(browser.model.cache.service, "offline", True)  # (Only what the panel reads.)
    rows: dict[str, tuple[str, str]] = {}
    FolderDetailsPanel._data_rows(browser, {"loaded_at": time.time(), "unchanged": True}, rows, False, True,
                                  unchecked=True)
    assert rows["loaded"][0].endswith("just now · not checked (offline)") and "checked, unchanged" not in rows["loaded"][0]
    assert "Working offline" in rows["loaded"][1] and "nothing was read" not in rows["loaded"][1]
    monkeypatch.setattr(browser.model.cache.service, "offline", False)
    rows.clear()
    FolderDetailsPanel._data_rows(browser, {"loaded_at": time.time(), "unchanged": True}, rows, False, True,
                                  unchecked=True)  # Online, unchecked: being checked, not yet "unchanged".
    assert rows["loaded"][0].endswith("just now")


@pytest.mark.parametrize("known_counts", [False, True])
def test_scan_states_agree_in_summary_and_folder_details(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path, known_counts: bool,
) -> None:
    path = str(tmp_path)
    browser.auto_load_ram = False
    if known_counts:
        (tmp_path / "d_txy_forc1.txt").write_text("1,2,3\n")
        complete_scan(browser, qtbot, path)
        assert browser.model.request_scan(path, force=True, metadata_only=True)
    operation = "scan" if known_counts else "list"
    request = request_for(browser.model.cache, path, operation)
    window: Any = SimpleNamespace(
        _closing=False, tab_widget=SimpleNamespace(currentWidget=lambda: browser),
        plots=SimpleNamespace(central_placeholder=CentralHint(parent=browser), dock_widgets=[]),
        folder_details=FolderDetailsPanel(browser))

    def assert_message(message: str) -> None:
        browser._update_activity()
        HelabMainWindow._update_folder_details(window)
        assert browser.folder_summary_label.text().endswith(message)
        assert window.folder_details.text("state") == message
        assert window.plots.central_placeholder.text() == "Select a data folder to begin"

    assert_message("Scan queued")
    browser.model.service.resultReady.emit(request, {"kind": "started"})
    assert_message("Scanning: checking file counts and status…" if known_counts else "Listing folder…")
    browser.model.service.resultReady.emit(request, {"kind": "heartbeat", "phase": "listing", "entries": 3210})
    if not known_counts:
        assert_message("Listing folder… 3,210 entries")
    browser.model.service.resultReady.emit(request, {"kind": "paused"})
    assert_message("Scan paused")
    browser.model.service.resultReady.emit(request, {"kind": "resumed"})
    assert_message("Scanning: checking file counts and status…" if known_counts else "Listing folder… 3,210 entries")


def test_successful_and_partial_load_counts_survive_memory_reuse(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    (tmp_path / "d_txy_forc1.txt").write_text("1,2,3\n")
    (tmp_path / "d_txy_forc2.txt").write_text("bad,data,row\n")
    path = str(tmp_path)
    complete_scan(browser, qtbot, path)
    assert browser.folder_summary_label.text() == "2 TXY found · Not loaded"
    assert browser.folder_cache_label.text() == "No cached data"
    browser.load_to_ram_cache(path, dwell=False)
    browser._update_activity()
    assert browser.folder_summary_label.text() == "2 TXY found · Queued"
    assert not browser.cancel_load_button.isHidden()
    assert browser.deselect_button.isHidden()  # The displayed path itself is loading.
    request = request_for(browser.model.cache, path, "load")
    browser.model.service.resultReady.emit(request, {"kind": "started"})
    output = tmp_path / "artifacts"
    output.mkdir()
    events: list[Any] = []
    load(path, str(output), events.append)
    for event in events:
        if event["kind"] == "shot":
            event = {**event, "array": np.load(event["artifact"])}
        browser.model.service.resultReady.emit(request, event)
    browser.model.service.pending.remove(request)
    assert browser.folder_summary_label.text() == "2 TXY found · 1 loaded · 1 unreadable"
    assert browser.folder_cache_label.text() == "No cached data"
    assert browser.cancel_load_button.isHidden()
    # A second tab reuses the dataset metadata, without receiving progress events.
    second = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(second)
    second.selectionPathChanged.connect(lambda p: second.load_to_ram_cache(p, dwell=False))
    qtbot.waitUntil(lambda: second.displayed_dataset is not None)
    assert second.folder_summary_label.text() == "2 TXY found · 1 loaded · 1 unreadable"
    second.close_cleanup()


def test_cached_scan_age_and_failed_refresh_retain_counts(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = str(tmp_path)
    (tmp_path / "d_txy_forc1.txt").write_text("1,2,3\n")
    complete_scan(browser, qtbot, path)
    cache = browser.model.cache
    snapshot = cache.snapshot(path)
    assert snapshot is not None
    snapshot.checked_at = time.monotonic() - 35
    expected_time = time.time() - 35
    # Retain a fresh snapshot long enough to exercise cache replay without a new check.
    monkeypatch.setattr(cache, "FRESH_SECONDS", 100.0)
    browser.open_to_path(path)
    qtbot.waitUntil(lambda: browser.model.nodes[path].loaded)
    browser._update_activity()
    assert browser.folder_freshness_label.text() == "Status scan: 35s ago · Live updates off"
    report = browser.model.fetch_status(path)
    assert abs(report.time_last_updated.timestamp() - expected_time) < 2
    assert datetime.fromtimestamp(expected_time).strftime("%Y-%m-%d") in browser.folder_freshness_label.toolTip()
    checked_at = browser.model.nodes[path].checked_at
    browser.model.request_scan(path, force=True)
    request = request_for(cache, path, "list")
    cache.service.resultReady.emit(request, {"kind": "error", "message": "Volume disconnected"})
    cache.service.pending.remove(request)
    assert browser.model.nodes[path].checked_at == checked_at
    assert browser.folder_summary_label.text() == "1 TXY found · Not loaded · Refresh failed · Retry"
    assert browser.folder_freshness_label.text() == "Folder status check failed just now · Retry manually"
    assert "Volume disconnected" in browser.folder_summary_label.toolTip()


def test_unchecked_folder_failure_does_not_claim_empty(browser: FolderExplorer, tmp_path: Path) -> None:
    request = request_for(browser.model.cache, str(tmp_path), "list")
    browser.model.service.resultReady.emit(request, {"kind": "error", "message": "Permission denied"})
    browser.model.service.pending.remove(request)
    assert browser.folder_summary_label.text() == "TXY count not checked · Retry manually"
    assert browser.folder_freshness_label.text() == "Folder status check failed just now · Retry manually"


def test_subfolder_scope_and_retained_plot_source(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = tmp_path / "run_042"
    child.mkdir()
    (child / "details").mkdir()
    (child / "d_txy_forc1.txt").write_text("1,2,3\n")
    complete_scan(browser, qtbot, str(tmp_path))
    browser.tree.setCurrentIndex(browser.model.path_index(str(child)))
    complete_scan(browser, qtbot, str(child))
    browser.load_to_ram_cache(str(child), dwell=False)
    cache = browser.model.cache
    request = request_for(cache, str(child), "load")
    cache.service.resultReady.emit(request, {"kind": "shot", "shot": 1, "array": np.ones((1, 3))})
    cache.service.resultReady.emit(request, {"kind": "loaded", "signature": browser.model.nodes[str(child)].signature,
                                           "files": 1, "rows": 1, "bytes": 24, "problematic": [], "failed_files": 0})
    cache.service.pending.remove(request)
    assert browser.path_edit.text() == str(tmp_path)
    assert browser.selected_folder_label.text() == "run_042 ›"
    assert not browser.selected_folder_label.isHidden()
    assert browser.folder_summary_label.text() == "1 TXY found · 1 loaded"
    assert not browser.deselect_button.isHidden()
    child_index = browser.model.path_index(str(child))
    browser.tree.expand(child_index)
    qtbot.waitUntil(lambda: browser.model.nodes[str(child)].state == "idle")
    assert browser.tree.isExpanded(child_index)
    root_node = browser.model.root
    dock = QDockWidget()
    qtbot.addWidget(dock)
    dock.setWidget(QLabel("plot"))
    PlotWorkspace._set_plot_source(SimpleNamespace(), dock, browser)  # type: ignore[arg-type]
    label = dock.findChild(QLabel, "plot_data_source")
    assert label is not None and label.text() == "Data source: run_042"
    browser.deselect_button.click()
    assert browser.selected_path_globally == str(tmp_path)
    assert browser.path_edit.text() == str(tmp_path)
    assert browser.model.root is root_node
    assert browser.tree.isExpanded(child_index)
    assert not browser.get_selection_model().selectedIndexes()
    assert not browser.get_selection_model().currentIndex().isValid()
    assert browser.selected_folder_label.isHidden()
    assert browser.deselect_button.isHidden()
    qtbot.waitUntil(lambda: browser.model.root is not None and browser.model.root.state == "idle")
    PlotWorkspace._update_plot_source_label(dock, browser)
    assert label.text() == "Showing previously loaded data: run_042"
    assert label.toolTip() == str(child)
    assert browser.folder_summary_label.text() == "No TXY files here · Select a subfolder to load data"
    assert browser.displayed_dataset is not None and browser.displayed_dataset.path == str(child)
    # Rendering stays entirely in memory, including age and provenance updates.
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Rendering must not query source folders")
    with monkeypatch.context() as blocked:
        blocked.setattr("os.scandir", forbidden)
        blocked.setattr("os.stat", forbidden)
        browser._update_activity()
        PlotWorkspace._update_plot_source_label(dock, browser)


def fail_cached_read(browser: FolderExplorer, qtbot: QtBot, path: str) -> None:
    """A known disk cache is read first; failing that read makes the load read the files."""
    cache = browser.model.cache
    request = request_for(cache, path, "cached")
    cache.service.resultReady.emit(request, {"kind": "error", "message": "No cached data for this folder"})
    cache.service.pending.remove(request)
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs)


def deliver_load(browser: FolderExplorer, path: str, shot: int, *, saving: bool = False) -> IORequest:
    cache = browser.model.cache
    request = request_for(cache, path, "load")
    cache.service.resultReady.emit(request, {"kind": "shot", "shot": shot, "array": np.ones((1, 3))})
    cache.service.resultReady.emit(request, {
        "kind": "loaded", "signature": browser.model.nodes[path].signature,
        "files": 1, "rows": 1, "bytes": 24, "problematic": [], "failed_files": 0,
        "source": "files", "disk_cached": cache.disk_cached(path), "disk_cache_pending": saving,
        "cache_info": cache.cache_status(path).info,
    })
    cache.service.pending.remove(request)
    return request


@pytest.mark.parametrize("finish", ["cache_saved", "cache_save_failed", "done"])
def test_disk_cache_summary_tracks_shared_save_completion(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path, finish: str,
) -> None:
    path = str(tmp_path)
    (tmp_path / "d_txy_forc1.txt").write_text("1,2,3\n")
    complete_scan(browser, qtbot, path)
    browser.load_to_ram_cache(path, dwell=False)
    request = deliver_load(browser, path, 1, saving=True)
    assert not browser.loading
    assert browser.folder_cache_label.text() == "Creating cache…"
    assert "Loaded from TXY files" in browser.folder_cache_label.toolTip()
    second = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(second)
    second.selectionPathChanged.connect(lambda p: second.load_to_ram_cache(p, dwell=False))
    # The data in RAM shows first; the shared listing's replay brings the row's folder date (its
    # freshness) a timer later, so a slow event-loop pass can return between the two.
    qtbot.waitUntil(lambda: second.displayed_dataset is not None
                    and path in second.model.nodes and second.model.nodes[path].modified is not None)
    assert second.folder_cache_label.text() == "Creating cache…"
    event: dict[str, Any] = {"kind": finish}
    if finish == "cache_saved":
        assert browser.displayed_dataset is not None
        event["cache_info"] = {"saved_at": time.time(), "signature": browser.displayed_dataset.signature,
                               "action": "created"}
    elif finish == "cache_save_failed":
        event["message"] = "Disk full"
    browser.model.service.resultReady.emit(request, event)
    if finish == "cache_saved":
        assert browser.folder_cache_label.text() == "Cache created just now"
        assert second.folder_cache_label.text() == "Cached data loaded · Cached just now"
    else:
        assert browser.folder_cache_label.text() == second.folder_cache_label.text() == "Cache creation failed"
    assert not browser.model.cache.disk_cache_saving(path)
    if finish != "done":
        browser.model.service.resultReady.emit(request, {"kind": "done"})
    assert browser.displayed_dataset is not None  # A failed disk save retains usable data.
    second.close_cleanup()


def test_deselect_activates_data_in_displayed_path(browser: FolderExplorer, qtbot: QtBot, tmp_path: Path) -> None:
    path = str(tmp_path)
    child = tmp_path / "run"
    child.mkdir()
    (tmp_path / "d_txy_forc3.txt").write_text("1,2,3\n")
    (child / "d_txy_forc1.txt").write_text("1,2,3\n")
    browser.selectionPathChanged.connect(lambda p: browser.load_to_ram_cache(p, dwell=False))
    complete_scan(browser, qtbot, path)
    deliver_load(browser, path, 3)
    browser.tree.setCurrentIndex(browser.model.path_index(str(child)))
    complete_scan(browser, qtbot, str(child))
    deliver_load(browser, str(child), 1)
    assert browser.displayed_dataset is not None and browser.displayed_dataset.path == str(child)
    browser.deselect_button.click()
    # Data in memory shows at once, while the displayed path is listed again.
    qtbot.waitUntil(lambda: browser.folder_opened_path == path)
    assert browser.displayed_dataset is not None and browser.displayed_dataset.path == path
    qtbot.waitUntil(lambda: browser.model.nodes[path].state == "idle")
    browser._update_activity()
    assert browser.folder_summary_label.text() == "1 TXY found · 1 loaded"
    assert browser.selected_folder_label.isHidden()


def test_summary_height_is_fixed_so_tree_rows_never_move(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    child = tmp_path / ("run_" + "x" * 80)
    child.mkdir()
    (child / "d_txy_forc1.txt").write_text("1,2,3\n")
    browser.resize(260, 400)
    browser.show()
    qtbot.waitExposed(browser)

    def tree_top() -> int:
        QApplication.processEvents()  # Apply pending layout changes.
        return browser.tree.geometry().top()

    top, height = tree_top(), browser.summary_widget.height()
    line = browser.folder_counts_row.height()
    assert height == 3 * line
    complete_scan(browser, qtbot, str(tmp_path))  # No TXY files: the cache line still holds its place.
    assert browser.folder_cache_label.text() in ("Cache not checked", "No data to cache")
    assert tree_top() == top
    browser.tree.setCurrentIndex(browser.model.path_index(str(child)))
    complete_scan(browser, qtbot, str(child))
    assert not browser.selected_folder_label.isHidden() and not browser.deselect_button.isHidden()
    assert tree_top() == top
    browser.load_to_ram_cache(str(child), dwell=False)
    browser.load_error = "A long message that used to wrap the counts line onto several lines " * 3
    browser._update_activity()
    assert not browser.cancel_load_button.isHidden()
    assert tree_top() == top
    # Long text is elided, never wrapped; the full text stays in text() and tooltips.
    assert browser.folder_summary_label.height() == line
    assert QLabel.text(browser.folder_summary_label) != browser.folder_summary_label.text()
    assert browser.selected_folder_label.width() < browser.folder_counts_row.width() // 2
    browser.deselect_button.click()
    assert browser.selected_folder_label.isHidden()
    assert tree_top() == top and browser.summary_widget.height() == height


def test_detected_disk_cache_is_available_before_loading(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    assert browser.folder_cache_label.text() == "Cache not checked"
    path = str(tmp_path)
    (tmp_path / "d_txy_forc1.txt").write_text("1,2,3\n")
    options = {"directory": str(tmp_path / "disk-cache")}
    output = tmp_path / "artifacts"
    output.mkdir()
    # Created before loading: a new entry in the source folder after the file listing is a change.
    (tmp_path / "disk-cache").mkdir()
    load(path, str(output), lambda event: None, options)
    cache = browser.model.cache
    complete_scan(browser, qtbot, path, options)
    qtbot.waitUntil(lambda: browser.model.nodes[path].loaded)
    assert browser.folder_summary_label.text() == "1 TXY found · Not loaded"
    # ("just now" under 1 s: a slow runner can take longer to load and list.)
    assert re.fullmatch(r"Cached data found · Cached (just now|\d+s ago)", browser.folder_cache_label.text())
    assert "freshness is checked when loading" in browser.folder_cache_label.toolTip()


def test_cache_age_advances_without_filesystem_reads_or_new_save(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = str(tmp_path)
    (tmp_path / "d_txy_forc1.txt").write_text("1,2,3\n")
    complete_scan(browser, qtbot, path)
    browser.load_to_ram_cache(path, dwell=False)
    request = deliver_load(browser, path, 1, saving=True)
    assert browser.displayed_dataset is not None
    saved_at = time.time() - 30
    info = {"saved_at": saved_at, "signature": browser.displayed_dataset.signature, "action": "created"}
    browser.model.service.resultReady.emit(request, {"kind": "cache_saved", "cache_info": info})
    assert browser.folder_cache_label.text() == "Cache created 30s ago · May be outdated"
    original_tooltip = browser.folder_cache_label.toolTip()
    original_checked = browser.model.nodes[path].checked_at

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Updating displayed ages must not read disk")

    with monkeypatch.context() as blocked:
        blocked.setattr("time.time", lambda: saved_at + 61)
        blocked.setattr("os.scandir", forbidden)
        blocked.setattr("os.stat", forbidden)
        browser._animate()  # The existing GUI timer performs this update.
    assert browser.folder_cache_label.text() == "Cache created 1m ago · May be outdated"
    assert browser.folder_cache_label.toolTip() == original_tooltip
    assert browser.model.cache.cache_status(path).info["saved_at"] == saved_at
    assert browser.model.nodes[path].checked_at == original_checked


def test_failed_update_keeps_previous_date_and_clear_ignores_late_save(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    path = str(tmp_path)
    (tmp_path / "d_txy_forc1.txt").write_text("1,2,3\n")
    complete_scan(browser, qtbot, path)
    cache = browser.model.cache
    saved_at = time.time() - 7200
    old_info = {"saved_at": saved_at, "signature": "previous", "action": "created"}
    cache._observe_cache(path, {"disk_cached": True, "cache_info": old_info})
    browser.load_to_ram_cache(path, dwell=False)
    fail_cached_read(browser, qtbot, path)
    request = deliver_load(browser, path, 1, saving=True)
    browser._update_activity()
    assert browser.folder_cache_label.text() == "Updating cache… · Changes detected"
    cache.service.resultReady.emit(request, {"kind": "cache_save_failed", "message": "Disk full"})
    assert browser.folder_cache_label.text() == "Cache update failed · Changes detected"
    assert "Disk full" in browser.folder_cache_label.toolTip()
    assert "Last successful cache save:" in browser.folder_cache_label.toolTip()
    assert cache.cache_status(path).info == old_info
    assert browser.displayed_dataset is not None
    cache.submit(browser.model.owner, browser.model.generation, path, "invalidate", {})
    cache.service.resultReady.emit(request, {"kind": "cache_saved", "cache_info": {
        "saved_at": time.time(), "signature": browser.displayed_dataset.signature, "action": "updated"}})
    cache.service.resultReady.emit(request, {"kind": "disk_cached", "disk_cached": True})
    assert not cache.disk_cached(path)
    assert not cache.cache_status(path).info
    assert not cache.disk_cache_saving(path)


@pytest.mark.parametrize("mode, running, effect, continues", [
    ("cancel", False, "will be cancelled", False),
    ("cancel", True, "will be cancelled", False),
    ("finish", False, "removed from this tab's load queue", False),
    ("finish", True, "finish loading in the background", True),
    ("queue", False, "remain queued in the background", True),
    ("queue", True, "continue loading in the background", True),
])
def test_deselect_tooltip_matches_actual_load_mode_effect(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
    mode: str, running: bool, effect: str, continues: bool,
) -> None:
    child = tmp_path / "run"
    child.mkdir()
    (child / "d_txy_forc1.txt").write_text("1,2,3\n")
    complete_scan(browser, qtbot, str(tmp_path))
    browser.tree.setCurrentIndex(browser.model.path_index(str(child)))
    complete_scan(browser, qtbot, str(child))
    assert browser.deselect_button.toolTip() == "Clear selection and view the displayed path."
    browser.load_mode = mode
    browser.load_to_ram_cache(str(child), dwell=False)
    request = request_for(browser.model.cache, str(child), "load")
    if running:
        browser.model.service.resultReady.emit(request, {"kind": "started"})
    browser._update_activity()
    assert effect in browser.deselect_button.toolTip()
    assert not browser.cancel_load_button.isHidden()
    browser.deselect_button.click()
    assert browser.selected_path_globally == str(tmp_path)
    assert (("load", str(child)) in browser.model.cache.jobs) is continues
    assert (str(child) in browser._bg_paths) is continues
    assert browser.cancel_load_button.isHidden() is not continues
    if continues:
        # Explicit Cancel also stops work left in the background after Deselect.
        browser.cancel_load_button.click()
        assert not browser._bg_paths
        assert ("load", str(child)) not in browser.model.cache.jobs
        assert browser.cancel_load_button.isHidden()


@pytest.mark.parametrize("mode", ["cancel", "finish", "queue"])
@pytest.mark.parametrize("state", ["queued", "running", "retrying"])
def test_cancel_button_stops_loading_regardless_of_mode_and_retains_data(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path, mode: str, state: str,
) -> None:
    path = str(tmp_path)
    (tmp_path / "d_txy_forc1.txt").write_text("1,2,3\n")
    complete_scan(browser, qtbot, path)
    browser.load_to_ram_cache(path, dwell=False)
    deliver_load(browser, path, 1)
    previous = browser.displayed_dataset
    browser.folder_opened_path = None  # Start a replacement load with previous data retained.
    browser.load_mode = mode
    browser.load_to_ram_cache(path, dwell=False)
    qtbot.waitUntil(lambda: not browser.loading)  # This replacement is reused from memory.
    browser.model.cache._invalidate_data(path)
    browser.folder_opened_path = None
    browser.load_to_ram_cache(path, dwell=False)
    request = request_for(browser.model.cache, path, "load")
    if state != "queued":
        browser.model.service.resultReady.emit(request, {"kind": "started"})
    if state == "retrying":
        browser.model.service.resultReady.emit(request, {"kind": "queued", "retry": True, "attempt": 2})
        browser.model.service.resultReady.emit(request, {"kind": "started", "attempt": 2})
    browser._update_activity()
    assert not browser.cancel_load_button.isHidden()
    assert browser.cancel_load_button.toolTip() == "Cancel loading in this tab (Esc)"
    browser.cancel_load_button.click()
    assert not browser.loading
    assert ("load", path) not in browser.model.cache.jobs
    assert browser.load_error == "Cancelled — Retry"
    assert browser.displayed_dataset is previous
    assert browser.cancel_load_button.isHidden()
    assert browser.selected_path_globally == path


def test_wait_before_queueing_has_cancel_control_and_deselect_explanation(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    child = tmp_path / "run"
    child.mkdir()
    (child / "d_txy_forc1.txt").write_text("1,2,3\n")
    complete_scan(browser, qtbot, str(tmp_path))
    browser.tree.setCurrentIndex(browser.model.path_index(str(child)))
    complete_scan(browser, qtbot, str(child))
    browser.model.cache.submit("other-tab", 0, str(tmp_path / "other"), "load")
    browser.load_mode = "queue"
    assert browser.load_to_ram_cache(str(child))
    assert browser.load_waiting and not browser.loading
    assert not browser.cancel_load_button.isHidden()
    assert "will not be queued" in browser.deselect_button.toolTip()
    browser.cancel_load_button.click()
    assert not browser.load_waiting
    assert ("load", str(child)) not in browser.model.cache.jobs
    assert browser.cancel_load_button.isHidden()


def test_cancel_button_preserves_another_tabs_shared_load(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    path = str(tmp_path)
    (tmp_path / "d_txy_forc1.txt").write_text("1,2,3\n")
    complete_scan(browser, qtbot, path)
    browser.selectionPathChanged.connect(lambda p: browser.load_to_ram_cache(p))
    browser.load_to_ram_cache(path, dwell=False)
    second = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(second)
    second.selectionPathChanged.connect(lambda p: second.load_to_ram_cache(p))
    qtbot.waitUntil(lambda: second.loading)
    browser.cancel_load_button.click()
    assert not browser.loading and second.loading
    assert ("load", path) in browser.model.cache.jobs
    deliver_load(browser, path, 1)
    assert second.folder_opened_path == path
    assert not second.loading
    # Shared completion must not automatically restart the cancelled tab.
    assert browser.displayed_dataset is None
    assert browser.cancel_load_button.isHidden()
    second.close_cleanup()


def test_scan_metadata_survives_restart_without_reading_txy_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from helab.io_ops import stores
    import pandas as pd
    import blosc
    root, child = tmp_path / "source", tmp_path / "source" / "run"
    child.mkdir(parents=True)
    (child / "d1.txt").write_text("")
    (child / "d_txy_forc1.txt").write_text("bad,data,row\n")
    options: dict[str, Any] = {"directory": str(tmp_path / "cache")}

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Metadata scans must not parse or decompress TXY data")

    monkeypatch.setattr(pd, "read_csv", forbidden)
    monkeypatch.setattr(blosc, "decompress", forbidden)
    events: list[Any] = []
    scan(str(child), events.append, options)
    initial = next(e for e in events if e["kind"] == "status")
    assert initial["count"] == 1 and initial["status"] == "ok"
    with stores._cache_store(options["directory"], [str(child)]) as store:
        # Scan persistence exists without any loaded data.
        assert store.read_dataset_row(str(child)).missing
        saved = store.read_record("summaries", str(child)).value
    assert isinstance(saved, dict)
    assert saved["scanned_at"] == initial["scanned_at"]
    scanned: list[str] = []
    original_scandir = os.scandir
    # The patch is process-wide: other threads' calls (a previous test's IOService.release runs
    # shutil.rmtree, which lists by file descriptor, on a daemon thread) go through untouched.
    test_thread = threading.get_ident()

    def record_scandir(path: Any) -> Any:
        if threading.get_ident() == test_thread:
            scanned.append(path)
        return original_scandir(path)

    monkeypatch.setattr("os.scandir", record_scandir)
    events.clear()
    scan(str(root), events.append, options)
    child_entry = next(e for event in events if event["kind"] == "entries" for e in event["entries"])
    assert child_entry["scan_status"] == saved
    assert scanned == [str(root)]
    events.clear()
    scan(str(child), events.append, options)
    assert {"kind": "scan_cached", "status": saved} in events
    assert next(e for e in events if e["kind"] == "status")["scanned_at"] >= saved["scanned_at"]
    # A failed refresh retains the previous date and count in persistent storage.
    with stores._cache_store(options["directory"], [str(child)]) as store:
        previous = store.read_record("summaries", str(child)).value

    def unavailable(path: Any) -> Any:
        if threading.get_ident() == test_thread:
            raise OSError("Volume unavailable")
        return original_scandir(path)

    monkeypatch.setattr("os.scandir", unavailable)
    events.clear()
    with pytest.raises(OSError, match="Volume unavailable"):
        scan(str(child), events.append, options)
    assert next(e for e in events if e["kind"] == "scan_cached")["status"] == previous
    with stores._cache_store(options["directory"], [str(child)]) as store:
        assert store.read_record("summaries", str(child)).value == previous


def test_visible_child_restores_persisted_counts_before_selection(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    child = tmp_path / "run"
    child.mkdir()
    (child / "d1.txt").write_text("")
    (child / "d_txy_forc1.txt").write_text("1,2,3\n")
    options: dict[str, Any] = {"directory": str(tmp_path / "cache")}
    scan(str(child), lambda e: None, options)
    complete_scan(browser, qtbot, str(tmp_path), options)
    qtbot.waitUntil(lambda: browser.model.root is not None and browser.model.root.loaded)
    node = browser.model.nodes[str(child)]
    assert node.report is not None and node.report.count == 1 and node.report.status == "ok"
    assert node.cached_report and not node.loaded
    assert browser.model.data(browser.model.path_index(str(child), 4)) == "1"
    tooltip = browser.model.data(browser.model.path_index(str(child)), int(Qt.ItemDataRole.ToolTipRole))
    assert isinstance(tooltip, str) and "\nStatus cache: " in tooltip
    assert browser.selected_path_globally == str(tmp_path)
    assert not any(r.operation == "load" for r in browser.model.service.pending)


@pytest.mark.parametrize("depth", [0, 1, 2, 5])
def test_basic_recursive_scan_checks_exact_depth_without_loading_data(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path, depth: int,
) -> None:
    folders = [tmp_path]
    for i in range(6):
        folders.append(folders[-1] / f"level_{i}")
        folders[-1].mkdir()
    for folder in folders:
        (folder / "d1.txt").write_text("")
        (folder / "d_txy_forc1.txt").write_text("1,2,3\n")
    complete_scan(browser, qtbot, str(tmp_path))
    # Use the same auto-load handler as the main window.
    browser.selectionPathChanged.connect(lambda p: browser.load_to_ram_cache(p, dwell=False))
    browser.deep_timer.stop()
    browser.start_basic_scan("recursive", depth)
    visited: list[str] = []
    for _ in range(30):
        browser._dispatch_deep()
        for path in tuple(browser._deep_depth):
            visited.append(path)
            complete_scan(browser, qtbot, path)
        if not browser._basic_active:
            break
    assert visited == [str(folder) for folder in folders[:depth + 1]]
    assert not browser._basic_active
    assert browser._basic_completed == depth + 1
    assert "Folder status check complete" in browser.activity_text
    assert browser.folder_opened_data is None
    assert not any(r.operation == "load" for r in browser.model.service.pending)


def test_cancel_basic_scan_keeps_other_tabs_scan_subscription(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    complete_scan(browser, qtbot, str(tmp_path))
    browser.deep_timer.stop()
    browser.start_basic_scan("current")
    browser._dispatch_deep()
    path = str(tmp_path)
    cache = browser.model.cache
    request = request_for(cache, path, "scan")
    cache.submit("other-tab", 0, path, "scan", {}, force=True)
    browser.cancel_basic_scan()
    assert not browser._basic_active and not browser._deep_depth
    assert not request.cancelled.is_set()
    assert cache.has_request("other-tab", "scan", path)
    assert not cache.has_request(browser.model.owner, "scan", path)
    assert "cancelled" in browser.activity_text


def test_visible_scans_follow_scrolling_without_prefetching_offscreen_folders(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    for i in range(40):
        child = tmp_path / f"run_{i:02}"
        child.mkdir()
        (child / "d1.txt").write_text("")
        (child / "d_txy_forc1.txt").write_text("1,2,3\n")
    complete_scan(browser, qtbot, str(tmp_path))
    browser.set_auto_scan_visible(True)
    browser.selectionPathChanged.connect(lambda p: browser.load_to_ram_cache(p, dwell=False))
    browser.resize(420, 260)
    browser.show()
    qtbot.wait(20)
    visible = browser._viewport_paths()
    assert visible and len(visible) < 40
    browser._check_visible_folders()
    requests = browser.model.cache.requests(browser.model.owner)
    assert requests and all(r.path in visible and r.payload.get("metadata_only") for r in requests)
    assert len(requests) <= 8
    for r in tuple(requests):
        complete_scan(browser, qtbot, r.path)
    scroll_bar = browser.tree.verticalScrollBar()
    assert scroll_bar is not None
    scroll_bar.setValue(scroll_bar.maximum())
    qtbot.wait(20)
    now_visible = browser._viewport_paths()
    assert set(now_visible).isdisjoint(visible)
    browser._check_visible_folders()
    requests = browser.model.cache.requests(browser.model.owner)
    assert requests and all(r.path in now_visible for r in requests)
    assert browser.folder_opened_data is None
    assert not any(r.operation == "load" for r in browser.model.service.pending)


def test_load_summary_uses_load_inventory_and_retains_data_after_metadata_changes(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    path = str(tmp_path)
    file = tmp_path / "d_txy_forc1.txt"
    file.write_text("1,2,3\n")
    complete_scan(browser, qtbot, path)
    browser.load_to_ram_cache(path, dwell=False)
    deliver_load(browser, path, 1)
    dataset = browser.displayed_dataset
    assert dataset is not None
    # The load inventory wins over an inconsistent scan count.
    browser.model.nodes[path].txy_count = 7
    browser._update_activity()
    assert browser.folder_summary_label.text() == "1 TXY found · 1 loaded"
    assert "1 data rows loaded" in browser.folder_summary_label.toolTip()
    assert "Data loaded:" in browser.folder_summary_label.toolTip()
    browser.selectionPathChanged.connect(lambda p: browser.load_to_ram_cache(p, dwell=False))
    file.unlink()
    browser.deep_timer.stop()
    browser.start_basic_scan("current")
    browser._dispatch_deep()
    complete_scan(browser, qtbot, path)
    browser._dispatch_deep()
    assert browser.folder_summary_label.text() == "0 TXY found · 1 previously loaded · Changes detected"
    assert browser.displayed_dataset is dataset
    assert browser.folder_opened_data is not None
    assert not browser.loading
    assert not any(r.operation == "load" for r in browser.model.service.pending)


def test_basic_scan_updates_other_tabs_without_triggering_their_auto_load(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    path = str(tmp_path)
    (tmp_path / "d1.txt").write_text("")
    (tmp_path / "d_txy_forc1.txt").write_text("1,2,3\n")
    complete_scan(browser, qtbot, path)
    second = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(second)
    qtbot.waitUntil(lambda: second.model.root is not None and second.model.root.loaded)
    # Wire auto-load after initial setup: this checks only the basic-scan update.
    browser.selectionPathChanged.connect(lambda p: browser.load_to_ram_cache(p, dwell=False))
    second.selectionPathChanged.connect(lambda p: second.load_to_ram_cache(p, dwell=False))
    (tmp_path / "d_txy_forc2.txt").write_text("4,5,6\n")
    browser.deep_timer.stop()
    browser.start_basic_scan("current")
    browser._dispatch_deep()
    complete_scan(browser, qtbot, path)
    qtbot.waitUntil(lambda: second.model.nodes[path].txy_count == 2)
    assert second.folder_summary_label.text() == "2 TXY found · Not loaded"
    assert browser.folder_opened_data is second.folder_opened_data is None
    assert not any(r.operation == "load" for r in browser.model.service.pending)
    second.close_cleanup()


def test_basic_view_scan_includes_root_and_collapsed_visible_folders(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    for i in range(4):
        child = tmp_path / f"run_{i}"
        child.mkdir()
        (child / "d_txy_forc1.txt").write_text("1,2,3\n")
    complete_scan(browser, qtbot, str(tmp_path))
    browser.resize(420, 350)
    browser.show()
    qtbot.wait(20)
    browser.visible_timer.stop()
    browser.deep_timer.stop()
    visible = browser._viewport_paths()
    assert len(visible) == 4
    browser.start_basic_scan("view")
    visited: set[str] = set()
    for _ in range(15):
        browser._dispatch_deep()
        for path in tuple(browser._deep_depth):
            visited.add(path)
            complete_scan(browser, qtbot, path)
        if not browser._basic_active:
            break
    assert visited == {str(tmp_path), *visible}
    assert all(not browser.tree.isExpanded(browser.model.path_index(path)) for path in visible)
    assert not any(r.operation == "load" for r in browser.model.service.pending)


def test_visible_folder_scans_default_off_and_can_be_disabled(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    (tmp_path / "run").mkdir()
    complete_scan(browser, qtbot, str(tmp_path))
    browser.resize(420, 350)
    browser.show()
    qtbot.wait(200)
    assert not browser.auto_scan_visible
    browser._check_visible_folders()
    assert all(request.operation == "icons" for request in browser.model.cache.requests(browser.model.owner))
    browser.set_auto_scan_visible(True)
    assert browser.visible_timer.isActive()
    browser.set_auto_scan_visible(False)
    assert not browser.visible_timer.isActive()
    browser._check_visible_folders()
    assert all(request.operation == "icons" for request in browser.model.cache.requests(browser.model.owner))


@pytest.mark.parametrize("limit", [1, 3])
def test_basic_scan_submission_uses_configured_concurrency(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path, limit: int,
) -> None:
    for i in range(5):
        (tmp_path / f"run_{i}").mkdir()
    complete_scan(browser, qtbot, str(tmp_path))
    browser.resize(420, 350)
    browser.show()
    qtbot.wait(20)
    browser.deep_timer.stop()
    browser.model.service.configure_concurrency(limit)
    browser.start_basic_scan("view")
    for _ in range(4):
        browser._dispatch_deep()
    assert len(browser._deep_depth) == limit
    assert len(browser.model.cache.requests(browser.model.owner)) == limit


def test_auto_scan_keeps_persisted_results_until_manual_basic_scan(
    browser: FolderExplorer, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    cached_child = tmp_path / "cached_run"
    unknown_child = tmp_path / "new_run"
    for child in (cached_child, unknown_child):
        child.mkdir()
        (child / "d_txy_forc1.txt").write_text("1,2,3\n")
    options: dict[str, Any] = {"directory": str(tmp_path_factory.mktemp("scan-cache"))}
    saved_at = time.time() - 7200
    with monkeypatch.context() as old_clock:
        old_clock.setattr("helab.io_ops.scanning.time.time", lambda: saved_at)
        scan(str(cached_child), lambda e: None, options)
    # Source changes are deliberately left for a manual scan to discover.
    (cached_child / "d_txy_forc2.txt").write_text("4,5,6\n")
    complete_scan(browser, qtbot, str(tmp_path), options)
    qtbot.waitUntil(lambda: browser.model.root is not None and browser.model.root.loaded)
    node = browser.model.nodes[str(cached_child)]
    assert node.cached_report and node.txy_count == 1
    browser.resize(420, 350)
    browser.show()
    browser.set_auto_scan_visible(True)
    browser._check_visible_folders()
    assert [r.path for r in browser.model.cache.requests(browser.model.owner)] == [str(unknown_child)]
    complete_scan(browser, qtbot, str(unknown_child))
    browser._check_visible_folders()
    browser.set_auto_scan_visible(False)
    browser.set_auto_scan_visible(True)
    browser._check_visible_folders()
    assert not browser.model.cache.requests(browser.model.owner)
    tooltip = browser.model.data(browser.model.path_index(str(cached_child)), int(Qt.ItemDataRole.ToolTipRole))
    assert isinstance(tooltip, str) and "\nStatus cache: " in tooltip and "(2h ago)" in tooltip
    assert "Here: 1 shot converted, no raw files" in tooltip and "Select the folder to check it again." in tooltip
    assert node.txy_count == 1
    browser.deep_timer.stop()
    browser.context_menu_action_deep_calc_status(str(cached_child))
    browser._dispatch_deep()
    complete_scan(browser, qtbot, str(cached_child))
    assert node.txy_count == 2 and not node.cached_report


def test_auto_scan_keeps_old_session_results_after_toggle_and_visibility_changes(
    browser: FolderExplorer, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    child = tmp_path / "run"
    child.mkdir()
    complete_scan(browser, qtbot, str(tmp_path))
    browser.model.request_scan(str(child), metadata_only=True)
    complete_scan(browser, qtbot, str(child))
    node = browser.model.nodes[str(child)]
    node.checked_at -= 7200
    assert node.scanned_at is not None
    node.scanned_at -= 7200
    browser.model.cache.snapshots[str(child)].checked_at -= 7200
    browser.resize(420, 350)
    browser.show()
    browser.set_auto_scan_visible(True)
    browser._check_visible_folders()
    assert not browser.model.cache.requests(browser.model.owner)

    index = browser.model.path_index(str(child))
    tooltip = browser.model.data(index, int(Qt.ItemDataRole.ToolTipRole))
    assert isinstance(tooltip, str) and "\nStatus checked: " in tooltip and "(2h ago)" in tooltip
    with monkeypatch.context() as clock:
        current = time.time()
        clock.setattr("helab.models.SnapshotFileSystemModel.time.time", lambda: current + 3600)
        tooltip = browser.model.data(index, int(Qt.ItemDataRole.ToolTipRole))
        assert isinstance(tooltip, str) and "(3h ago)" in tooltip
    # Moving out of view and back, and re-enabling the option, both retain results.
    monkeypatch.setattr(browser, "_viewport_paths", lambda: [])
    browser._check_visible_folders()
    monkeypatch.setattr(browser, "_viewport_paths", lambda: [str(child)])
    browser.set_auto_scan_visible(False)
    browser.set_auto_scan_visible(True)
    browser._check_visible_folders()
    assert not browser.model.cache.requests(browser.model.owner)


@pytest.mark.parametrize("data_age, scan_age, folder_age, data_old, status_old", [
    (120, 120, 60, True, True),
    (30, 120, 60, False, True),
    (120, 30, 60, True, False),
    (30, 30, 60, False, False),
    (60, 60, 60, False, False),
    (None, None, 60, False, False),
    (120, 120, None, False, False),
])
def test_data_and_status_cache_freshness_indicators_are_independent(
    browser: FolderExplorer, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    data_age: int | None, scan_age: int | None, folder_age: int | None,
    data_old: bool, status_old: bool,
) -> None:
    IconsInitUtil.initialise_icons()
    path = str(tmp_path)
    (tmp_path / "d1.txt").write_text("")
    (tmp_path / "d_txy_forc1.txt").write_text("1,2,3\n")
    complete_scan(browser, qtbot, path)
    node = browser.model.nodes[path]
    now = time.time()
    node.modified = now - folder_age if folder_age is not None else None
    node.scanned_at = now - scan_age if scan_age is not None else None
    browser.model.cache._observe_cache(path, {"disk_cached": True, "cache_info": {
        "saved_at": now - data_age, "signature": node.signature} if data_age is not None else {}})
    browser._update_activity()

    def no_io(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Freshness rendering touched the filesystem or scheduled work")

    # Reading labels, badges and tooltips must consume memory only.
    with monkeypatch.context() as blocked:
        blocked.setattr("os.stat", no_io)
        blocked.setattr("os.scandir", no_io)
        blocked.setattr(browser.model.service, "submit", no_io)
        browser._update_activity()
        index = browser.model.path_index(path, browser.model.COLUMN_STATUS_ICON)
        assert browser.model.data(index, browser.model.STATUS_EXTRA_ICONS_ROLE) == [
            StatusIcons.ICON_CACHED_OLDER if data_old else StatusIcons.ICON_CACHED]
        expected_status = (StatusIcons.ICONS_STATUS_OLDER if status_old else StatusIcons.ICONS_STATUS)["ok"]
        assert browser.model.data(index, int(Qt.ItemDataRole.DecorationRole)) == expected_status
        assert ("May be outdated" in browser.folder_cache_label.text()) == data_old
        assert ("May be outdated" in browser.folder_freshness_label.text()) == status_old
        tooltip = str(browser.model.data(index, int(Qt.ItemDataRole.ToolTipRole)))
        # The row tooltip mirrors the icons: a reason only with the clock on each.
        # Each cache has its date and freshness; the folder modified time is stated once.
        lines = tooltip.splitlines()
        status_line = next(line for line in lines if line.startswith(("Status cache: ", "Status checked: ")))
        data_line = next(line for line in lines if line.startswith("Data cache: "))
        assert sum(line.startswith("Folder modified: ") for line in lines) == 1
        assert status_line.endswith("· may be outdated") == status_old
        assert data_line.endswith("· may be outdated") == data_old
        if folder_age is None:
            # A status checked in this session notes only a later sign of change.
            assert status_line.endswith("· freshness unknown") == status_line.startswith("Status cache: ")
            assert data_line.endswith("· freshness unknown")
        if data_age is None or folder_age is None:
            assert "Freshness unknown" in browser.folder_cache_label.text()
        if scan_age is None or folder_age is None:
            assert "Freshness unknown" in browser.folder_freshness_label.text()
    assert not browser.model.cache.requests(browser.model.owner)


def test_manual_scan_confirms_data_changes_and_load_clears_cache_warning(
    browser: FolderExplorer, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    IconsInitUtil.initialise_icons()
    child = tmp_path / "run"
    child.mkdir()
    (child / "d1.txt").write_text("")
    (child / "d_txy_forc1.txt").write_text("1,2,3\n")
    options: dict[str, Any] = {"directory": str(tmp_path_factory.mktemp("freshness-cache"))}
    output = tmp_path_factory.mktemp("freshness-artifacts")
    saved_at = time.time() - 3600
    with monkeypatch.context() as old_clock:
        old_clock.setattr("helab.io_ops.scanning.time.time", lambda: saved_at)
        scan(str(child), lambda e: None, options)
        load(str(child), str(output), lambda e: None, options)
    (child / "d2.txt").write_text("")
    (child / "d_txy_forc2.txt").write_text("4,5,6\n")
    complete_scan(browser, qtbot, str(tmp_path), options)
    qtbot.waitUntil(lambda: browser.model.nodes[str(tmp_path)].loaded)
    node = browser.model.nodes[str(child)]
    index = browser.model.path_index(str(child), browser.model.COLUMN_STATUS_ICON)
    assert node.cached_report and node.txy_count == 1
    assert browser.model.status_freshness(node) == CacheFreshness.POSSIBLY_OLD
    assert browser.model.data_freshness(node) == CacheFreshness.POSSIBLY_OLD
    assert browser.model.data(index, browser.model.STATUS_EXTRA_ICONS_ROLE) == [StatusIcons.ICON_CACHED_OLDER]
    # Auto basic scan must keep both old caches despite their badges.
    browser.resize(420, 350)
    browser.show()
    browser.set_auto_scan_visible(True)
    browser._check_visible_folders()
    assert not browser.model.cache.requests(browser.model.owner)
    browser.deep_timer.stop()
    browser.context_menu_action_deep_calc_status(str(child))
    browser._dispatch_deep()
    complete_scan(browser, qtbot, str(child), options)
    assert node.txy_count == 2
    assert browser.model.status_freshness(node) == CacheFreshness.UNCHANGED
    assert browser.model.data_freshness(node) == CacheFreshness.CHANGED
    assert browser.model.data(index, int(Qt.ItemDataRole.DecorationRole)) == StatusIcons.ICON_OK
    assert "different TXY fingerprints" in str(browser.model.data(index, int(Qt.ItemDataRole.ToolTipRole)))
    # A successful helper cache write replaces the old signature and save date.
    events: list[Any] = []
    load(str(child), str(output), events.append, options)
    saved = next(e for e in events if e["kind"] == "cache_saved")
    browser.model.cache._observe_cache(str(child), {"disk_cached": True, "cache_info": saved["cache_info"]})
    assert browser.model.data_freshness(node) == CacheFreshness.UNCHANGED
    assert browser.model.data(index, browser.model.STATUS_EXTRA_ICONS_ROLE) == [StatusIcons.ICON_CACHED]


def test_cached_snapshot_replay_preserves_newer_folder_metadata(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    child = tmp_path / "run"
    child.mkdir()
    (child / "d_txy_forc1.txt").write_text("1,2,3\n")
    complete_scan(browser, qtbot, str(tmp_path))
    browser.model.request_scan(str(child), metadata_only=True)
    complete_scan(browser, qtbot, str(child))
    node = browser.model.nodes[str(child)]
    assert node.scanned_at is not None
    newer_modified = node.scanned_at + 5
    os.utime(child, (newer_modified, newer_modified))
    browser.model.request_scan(str(tmp_path), force=True, metadata_only=True)
    complete_scan(browser, qtbot, str(tmp_path))
    assert node.modified == pytest.approx(newer_modified)
    assert browser.model.status_freshness(node) == CacheFreshness.POSSIBLY_OLD
    browser.model.request_scan(str(child), metadata_only=True)
    qtbot.waitUntil(lambda: not browser.model.cache.requests(browser.model.owner))
    assert node.modified == pytest.approx(newer_modified)
    assert browser.model.status_freshness(node) == CacheFreshness.POSSIBLY_OLD


def test_ram_badge_does_not_hide_outdated_disk_cache(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    IconsInitUtil.initialise_icons()
    path = str(tmp_path)
    (tmp_path / "d_txy_forc1.txt").write_text("1,2,3\n")
    complete_scan(browser, qtbot, path)
    node = browser.model.nodes[path]
    browser.model.cache._observe_cache(path, {"disk_cached": True, "cache_info": {
        "saved_at": time.time() - 3600, "signature": node.signature}})
    browser.load_to_ram_cache(path, dwell=False)
    fail_cached_read(browser, qtbot, path)
    request = deliver_load(browser, path, 1, saving=True)
    index = browser.model.path_index(path)
    assert browser.model.data(index, browser.model.STATUS_EXTRA_ICONS_ROLE) == [
        StatusIcons.ICON_RAM_OPENED, StatusIcons.ICON_CACHED_OLDER]
    browser.model.service.resultReady.emit(request, {"kind": "cache_saved", "cache_info": {
        "saved_at": time.time(), "signature": node.signature, "action": "updated"}})
    assert browser.model.data(index, browser.model.STATUS_EXTRA_ICONS_ROLE) == [StatusIcons.ICON_RAM_OPENED]
