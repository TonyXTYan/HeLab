"""The folder row's badge for saved analysis results (result caching R2, Follow-up 2: Tony chose
Debug › Show all Icons' ``report``): a listing sends each subfolder's saved results from the store's
records, a save and Make room send their folders' counts after them, FolderCache keeps the newest
measurement (by the store's write count) and drops them with a Clear cached analysis; the row
shows REPORT after the data cache's badge, and its tooltip and Folder details' cache line say
"Cached analysis: N results, X MB", only while reuse is on. Memory only during rendering."""
from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any, cast

import pytest
from pytestqt.qtbot import QtBot

from helab.io_ops.browse import list_folder
from helab.resources.icons import IconsInitUtil, StatusIcons
from helab.utils.folder_cache import FolderCache, analysis_cached_text
from helab.utils.io_service import IOService
from helab.views.FolderDetailsPanel import FolderDetailsPanel
from test_folder_flags import frozen, make_explorer, select
from test_result_cache_plots import (WAIT, Costly, cache, close, folder_view, make_window,  # noqa: F401
                                     open_plot, saved, stop_runners)
from test_result_cache_store import find, options, packed, save_through_helper


def saved_results(tmp_path: Path, folder: Path, cache_options: dict[str, Any], lookups: list[str]) -> int:
    """Save one result per lookup of ``folder`` through the helper; their files' bytes."""
    size = 0
    for lookup in lookups:
        guard = find(tmp_path, folder, cache_options, lookup)[-1]["guard"]
        assert save_through_helper(tmp_path, folder, cache_options, guard, lookup=lookup)[-1]["kind"] == "result_saved"
        size += len(packed())
    return size


def test_a_listing_sends_each_subfolders_saved_results(tmp_path: Path) -> None:
    parent = tmp_path / "data"
    (parent / "plain").mkdir(parents=True)
    (parent / "run").mkdir()
    cache_options = options(tmp_path)
    size = saved_results(tmp_path, parent / "run", cache_options, ["k1", "k2"])
    saved_results(tmp_path, parent, cache_options, ["own"])
    events: list[Any] = []
    list_folder(str(parent), events.append, cache_options)
    entries = {entry["path"]: entry for event in events if event["kind"] == "entries" for entry in event["entries"]}
    run, plain = entries[str(parent / "run")]["results"], entries[str(parent / "plain")]["results"]
    assert (run["count"], run["bytes"]) == (2, size) and (plain["count"], plain["bytes"]) == (0, 0)
    assert run["seq"] == plain["seq"] and isinstance(run["seq"][1], int)
    status = next(event for event in events if event["kind"] == "status")
    assert status["results"]["count"] == 1  # The listed folder's own, too.


@pytest.mark.no_auto_data_root
def test_a_folder_without_a_data_root_sends_no_count(tmp_path: Path) -> None:
    parent = tmp_path / "plain"
    (parent / "child").mkdir(parents=True)
    events: list[Any] = []
    list_folder(str(parent), events.append, options(tmp_path))
    entries = [entry for event in events if event["kind"] == "entries" for entry in event["entries"]]
    assert entries and all("results" not in entry for entry in entries)


def counts(count: int, size: int, writes: int, store: str = "s") -> dict[str, Any]:
    return {"count": count, "bytes": size, "seq": [store, writes]}


def folder_holds(cache: FolderCache, store: str) -> None:
    """The cache folder answers the identity probe a count from another store started."""
    probe = next(r for r in cache.service.pending if r.operation == "cache_admin" and r.payload["action"] == "identity")
    for event in ({"kind": "admin_result", "action": "identity", "store": store}, {"kind": "done"}):
        cache.service.resultReady.emit(probe, event)
    cache.service.pending.remove(probe)


def test_folder_cache_keeps_the_newest_measurement_and_drops_counts_with_a_clear(
        monkeypatch: pytest.MonkeyPatch) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    cache = FolderCache(service)
    monkeypatch.setattr(cache, "result_cache_off", lambda path: "")
    changed: list[Any] = []
    cache.resultCountsChanged.connect(changed.append)
    cache._note_result_counts({"/r/a": counts(2, 2_000_000, 10), "/r/b": counts(0, 0, 10)})
    assert cache.analysis_cached("/r/a") == (2, 2_000_000) and cache.analysis_cached("/r/b") is None
    assert changed == [[FolderCache.key("/r/a"), FolderCache.key("/r/b")]]
    cache._note_result_counts({"/r/a": counts(1, 1_000_000, 9)})  # Measured before: ignored.
    assert cache.analysis_cached("/r/a") == (2, 2_000_000)
    cache._note_result_counts({"/r/a": counts(3, 3 << 20, 11)})
    assert analysis_cached_text(cache, "/r/a") == "Cached analysis: 3 results, 3.0 MB"
    cache._note_result_counts({"/r/a": counts(1, 500, 1, store="other")})  # Another store: the folder is asked…
    assert analysis_cached_text(cache, "/r/a") == "Cached analysis: 3 results, 3.0 MB"
    folder_holds(cache, "other")  # …and holds it (recreated): the old store's counts go.
    assert cache.analysis_cached("/r/a") is None
    cache._note_result_counts({"/r/a": counts(1, 500, 1, store="other")})
    assert analysis_cached_text(cache, "/r/a") == "Cached analysis: 1 result, 500 B"
    started = time.monotonic()
    cache.removed(["/r/a"], ["results"])  # Clear cached analysis of the folder.
    assert cache.analysis_cached("/r/a") is None
    cache._note_result_counts({"/r/a": counts(1, 500, 2, store="other")}, started)  # Asked before the clear.
    assert cache.analysis_cached("/r/a") is None
    cache._note_result_counts({"/r/a": counts(1, 700, 3, store="other")})  # A save after it.
    assert cache.analysis_cached("/r/a") == (1, 700)
    cache.removed(None, ["results"])  # Clear cached analysis (all).
    assert cache.analysis_cached("/r/a") is None and changed[-1] is None
    cache._note_result_counts({"/r/a": counts(1, 700, 4, store="other")})
    cache.set_result_reuse(False)  # Reuse off: no badge.
    assert cache.analysis_cached("/r/a") is None and changed[-1] is None
    cache.set_result_reuse(True)
    assert cache.analysis_cached("/r/a") == (1, 700)
    # Don't cache this folder: its saved results aren't reused (the helper refuses), so no badge.
    cache.remember_prefs("/r/a", {"no_cache": True, "no_auto_load": False, "set_at": 1.0})
    assert cache.analysis_cached("/r/a") is None and analysis_cached_text(cache, "/r/a") == ""
    cache.remember_prefs("/r/a", {"no_cache": False, "no_auto_load": False, "set_at": 2.0})
    assert cache.analysis_cached("/r/a") == (1, 700)


def test_the_row_shows_report_with_a_tooltip_line_and_folder_details_says_it(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer = make_explorer(qtbot, service, cache, root, ["run", "other"])
    run, other = os.path.join(root, "run"), os.path.join(root, "other")
    IconsInitUtil.initialise_icons()
    model = explorer.model

    def icons(path: str) -> list[Any]:
        return cast(list[Any], model.data(model.path_index(path), model.STATUS_EXTRA_ICONS_ROLE) or [])
    try:
        monkeypatch.setattr(cache, "root_of", lambda path: (root, "u", "Lab"))
        assert StatusIcons.ICONS_EXTRA["report"] not in icons(run)
        repainted: list[Any] = []
        model.dataChanged.connect(lambda first, last, roles=None: repainted.append(model.filePath(first)))
        cache._note_result_counts({run: counts(2, 3 * 1024 * 1024, 5)})
        assert run in repainted  # The row repaints at once.
        assert icons(run)[-1] is StatusIcons.ICONS_EXTRA["report"]
        assert StatusIcons.ICONS_EXTRA["report"] not in icons(other)
        tooltip = str(model.data(model.path_index(run), 3))
        assert "Cached analysis: 2 results, 3.0 MB" in tooltip
        select(qtbot, explorer, run)
        details = FolderDetailsPanel()
        qtbot.addWidget(details)
        details.show_explorer(explorer, service)
        line = details.values["cache"]
        assert line.text().endswith("· Cached analysis: 2 results, 3.0 MB")
        cache.set_result_reuse(False)
        assert StatusIcons.ICONS_EXTRA["report"] not in icons(run)
        assert "Cached analysis" not in str(model.data(model.path_index(run), 3))
        details.show_explorer(explorer, service)
        assert "Cached analysis" not in details.values["cache"].text()
    finally:
        explorer.close()


def test_a_plots_save_shows_the_badge_without_listing_and_a_clear_hides_it(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    try:
        view = folder_view(tmp_path)
        path = view.identity.source_path
        assert cache.analysis_cached(path) is None
        instance = open_plot(window, qtbot, view, Costly())
        qtbot.waitUntil(lambda: saved(instance), timeout=WAIT)
        qtbot.waitUntil(lambda: cache.analysis_cached(path) is not None, timeout=WAIT)
        count, size = cache.analysis_cached(path) or (0, 0)
        assert count == 1 and size > 0
        owner = cache.cache_admin("clear_results")
        assert owner
        qtbot.waitUntil(lambda: cache.analysis_cached(path) is None, timeout=WAIT)
    finally:
        close(window)
