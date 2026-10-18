"""Roadmap S10: folder flags, "Don't cache this folder" and "Don't auto-load this folder".

They apply to one folder only, survive restarts and purges, and are never removed to make room."""
from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any

import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtCore import QSettings

from helab.io_helper import cache_admin, list_folder, load
from helab import io_helper
from helab.resources.icons import IconsInitUtil, StatusIcons
from helab.utils.cache_store import KINDS, CacheStore, DatasetRecord, SaveRejected
from helab.utils.folder_cache import FolderCache, get_folder_cache, store_options
from helab.utils.io_service import IORequest, IOService
from helab.views.CacheTab import CacheTab
from helab.views.FolderDetailsPanel import FolderDetailsPanel
from helab.views.FolderExplorer import AUTO_LOAD_OFF, FolderExplorer

RECORD: DatasetRecord = {"ram_bytes": 1, "rows": 1, "shots": 1, "fingerprint": [], "problematic": [], "info": {}}


def data_folder(parent: Path, name: str = "source") -> Path:
    source = parent / name
    source.mkdir(parents=True)
    for shot in (1, 2):
        (source / f"d{shot}.txt").write_text("raw\n")
        (source / f"d_txy_forc{shot}.txt").write_text(f"{shot},2,3\n{shot},5,6\n")
    return source


def run_load(source: Path, tmp_path: Path, options: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
    output = tmp_path / f"artifacts-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    load(str(source), str(output), events.append, options, **kwargs)
    return events


# The store and helpers

def test_flags_are_saved_per_folder_newest_choice_wins_and_survive_clears_and_purges(tmp_path: Path) -> None:
    root = str(tmp_path / "store-v2")
    with CacheStore(root) as store:
        assert store.set_prefs("/a", True, False, 10.0) == {"no_cache": True, "no_auto_load": False, "set_at": 10.0}
        # An older choice (e.g. from another HeLab) doesn't overwrite a newer one.
        assert store.set_prefs("/a", False, True, 5.0)["no_cache"] is True
        store.set_prefs("/b", False, True, 11.0)
        store.remove(KINDS)  # Clear all.
        store.purge_records(time.time() + 1, include_failures=True)
        store.purge_datasets(time.time() + 1)
    with CacheStore(root) as store:  # A restart.
        prefs = store.read_prefs(["/a", "/b", "/a/sub", "/"])
        assert prefs["/a"].value == {"no_cache": True, "no_auto_load": False, "set_at": 10.0}
        assert prefs["/b"].value is not None and prefs["/b"].value["no_auto_load"]
        assert prefs["/a/sub"].status == "missing" and prefs["/"].status == "missing"  # Never inherited.
        assert store.inventory()["prefs"] == {"no_cache": 1, "no_auto_load": 1}
        # Turned off, a flag keeps its time, so an older choice arriving late can't bring it back.
        store.set_prefs("/b", False, False, 12.0)
        assert store.read_prefs(["/b"])["/b"].value == {"no_cache": False, "no_auto_load": False, "set_at": 12.0}
        assert store.set_prefs("/b", False, True, 11.5)["no_auto_load"] is False
        # The Cache tab's Clear turns them all off, as a choice made now.
        assert store.clear_prefs(20.0) == ["/a"] and store.inventory()["prefs"] == {"no_cache": 0, "no_auto_load": 0}
        assert store.set_prefs("/a", True, False, 15.0)["no_cache"] is False
        # Also for a folder with no flags saved before the Clear.
        assert store.set_prefs("/new", True, False, 15.0)["no_cache"] is False
        assert store.set_prefs("/new", True, False, 25.0)["no_cache"] is True
        # A Clear from before a saved choice (it waited for the lock) leaves that choice alone,
        # and an older Clear finishing last doesn't move the barrier back.
        assert store.clear_prefs(22.0) == []
        assert store.read_prefs(["/new"])["/new"].value == {"no_cache": True, "no_auto_load": False, "set_at": 25.0}
        assert store.set_prefs("/other", True, False, 21.0)["no_cache"] is False
        store.clear_prefs(21.5)  # An older Clear finishing last...
        assert store.set_prefs("/late", True, False, 21.8)["no_cache"] is False  # ...doesn't lower the barrier.


def test_a_superseded_choice_removes_nothing(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    options: dict[str, Any] = {"directory": str(tmp_path / "caches" / "store-v2")}
    run_load(source, tmp_path, options)
    with io_helper._cache_store(options["directory"], [str(source)]) as store:
        store.set_prefs(str(source), True, False, 20.0)  # Don't cache, keep the cached data (the newer choice).
    events: list[dict[str, Any]] = []
    cache_admin(options, "prefs", events.append, path=str(source), no_cache=True, no_auto_load=False,
                set_at=10.0, remove_cached=True)  # An older request, arriving late.
    assert events[0]["prefs"]["set_at"] == 20.0 and not any(e["kind"] == "removed" for e in events)
    with io_helper._cache_store(options["directory"], [str(source)]) as store:
        assert store.read_dataset_row(str(source)).value is not None


def test_a_cached_read_asked_for_before_dont_cache_reads_nothing(tmp_path: Path) -> None:
    from helab.io_helper import read_cached
    source = data_folder(tmp_path)
    options: dict[str, Any] = {"directory": str(tmp_path / "caches" / "store-v2")}
    run_load(source, tmp_path, options)
    with io_helper._cache_store(options["directory"], [str(source)]) as store:
        store.set_prefs(str(source), True, False, time.time())
    output = tmp_path / "out"
    output.mkdir()
    with pytest.raises(ValueError, match="Not cached: your choice"):
        read_cached(str(source), str(output), lambda event: None, options)
    assert not any(output.iterdir())


def test_a_folder_not_cached_is_never_saved_even_by_a_load_already_running(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    options: dict[str, Any] = {"directory": str(tmp_path / "caches" / "store-v2")}
    run_load(source, tmp_path, options)  # Cached before the choice.
    with io_helper._cache_store(options["directory"], [str(source)]) as store:
        guard = store.start_dataset_job(str(source))  # A load already running...
        store.set_prefs(str(source), True, False, time.time())  # ...when the user ticks Don't cache.
        with pytest.raises(SaveRejected, match="Not cached: your choice"):
            store.save_dataset(str(source), store.write_dataset_file(b"x"), RECORD, guard)
        before = store.read_dataset_row(str(source)).value
    assert before is not None
    # A load now reads the files, neither using nor writing the cached data.
    events = run_load(source, tmp_path, options)
    loaded = next(e for e in events if e["kind"] == "loaded")
    assert loaded["source"] == "files" and loaded["cache_reason"] == "Not cached: your choice"
    assert loaded["disk_cache_pending"] is False  # No save to wait for (so no "Cache update failed").
    assert not any(e["kind"] in ("cache_saved", "cache_full", "cache_approval", "cache_save_failed", "cache_warning")
                   for e in events)  # Not even tried.
    with io_helper._cache_store(options["directory"], [str(source)]) as store:
        assert store.read_dataset_row(str(source)).value == before


def test_a_flag_that_cant_be_read_keeps_the_cache_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.io_helper import read_cached
    from helab.utils import cache_store
    source = data_folder(tmp_path)
    options: dict[str, Any] = {"directory": str(tmp_path / "caches" / "store-v2")}
    run_load(source, tmp_path, options)

    def unreadable(self: CacheStore, paths: Any) -> Any:
        return {path: cache_store._error("Disk cache could not be read: locked") for path in paths}
    monkeypatch.setattr(CacheStore, "read_prefs", unreadable)
    output = tmp_path / "out"
    output.mkdir()
    with pytest.raises(ValueError, match="settings couldn't be read"):
        read_cached(str(source), str(output), lambda event: None, options)
    events = run_load(source, tmp_path, options)
    loaded = next(e for e in events if e["kind"] == "loaded")
    assert loaded["source"] == "files" and loaded["disk_cache_pending"] is False
    assert loaded["cache_reason"] == "Disk cache not used: the folder's settings couldn't be read"  # Not "your choice".
    assert any(e["kind"] == "cache_warning" and "settings couldn't be read" in e["message"] for e in events)


def test_listings_send_each_subfolders_own_flags_and_admin_sets_and_clears_them(tmp_path: Path) -> None:
    parent = tmp_path / "data"
    child = data_folder(parent, "run1")
    options: dict[str, Any] = {"directory": str(tmp_path / "caches" / "store-v2")}
    run_load(child, tmp_path, options)
    events: list[dict[str, Any]] = []
    cache_admin(options, "prefs", events.append, path=str(child), no_cache=True, no_auto_load=False,
                set_at=time.time(), remove_cached=True)
    assert events[0]["kind"] == "folder_prefs" and events[0]["prefs"]["no_cache"] is True
    removed = next(e for e in events if e["kind"] == "removed")
    assert removed["kinds"] == ["datasets"] and removed["paths"] == [str(child)]
    listed: list[dict[str, Any]] = []
    list_folder(str(parent), listed.append, options)
    entry = next(e for event in listed if event["kind"] == "entries" for e in event["entries"]
                 if e["path"] == str(child))
    assert entry["prefs"]["no_cache"] is True and entry["disk_cached"] is False
    listed.clear()
    list_folder(str(tmp_path), listed.append, options)
    parent_entry = next(e for event in listed if event["kind"] == "entries" for e in event["entries"]
                        if e["path"] == str(parent))
    assert parent_entry["prefs"] == {}  # A subfolder's flag says nothing about its parent.
    events.clear()
    cache_admin(options, "clear_prefs", events.append)
    assert events[0]["kind"] == "prefs_cleared" and events[0]["paths"] == [str(child)] and events[0]["set_at"] > 0


# The tab

def frozen(monkeypatch: pytest.MonkeyPatch) -> tuple[IOService, FolderCache]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    return service, get_folder_cache(service)


def scan(cache: FolderCache, path: str, children: list[str] | None = None, data: bool = True) -> None:
    job = cache.jobs[("list" if ("list", path) in cache.jobs else "scan", path)]
    request = next(r for r in cache.service.pending if r.owner == job.owner)
    cache.service.resultReady.emit(request, {"kind": "entries", "entries": [
        {"path": p, "modified": None} for p in (children or [])]})
    cache.service.resultReady.emit(request, {"kind": "status", "status": "ok", "count": 1, "raw": [1], "details": True,
                                             "txy": [1] if data else [], "modified": 0, "signature": "v1",
                                             "scanned_at": time.time()})
    cache.service.resultReady.emit(request, {"kind": "done"})
    cache.service.pending.remove(request)


def admin(service: IOService, action: str) -> IORequest:
    return next(r for r in reversed(service.pending) if r.operation == "cache_admin" and r.payload["action"] == action)


def make_explorer(qtbot: QtBot, service: IOService, cache: FolderCache, root: str,
                  names: list[str]) -> FolderExplorer:
    explorer = FolderExplorer(root, root, root, [0, 4, 5])
    qtbot.addWidget(explorer)
    explorer.selectionPathChanged.connect(lambda p: explorer.load_to_ram_cache(p))
    qtbot.waitUntil(lambda: ("list", root) in cache.jobs)
    paths = [os.path.join(root, name) for name in names]
    scan(cache, root, paths, data=False)
    qtbot.waitUntil(lambda: all(path in explorer.model.nodes for path in paths))
    for path in paths:
        explorer.model.request_scan(path)
        scan(cache, path)
    qtbot.waitUntil(lambda: all(explorer.model.nodes[path].report is not None for path in paths))
    return explorer


def select(qtbot: QtBot, explorer: FolderExplorer, path: str) -> None:
    explorer.tree.setCurrentIndex(explorer.model.path_index(path))
    qtbot.waitUntil(lambda: explorer.selected_path_globally == path)


def test_a_folder_not_auto_loaded_starts_nothing_when_selected(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer = make_explorer(qtbot, service, cache, root, ["quiet", "other"])
    quiet, other = os.path.join(root, "quiet"), os.path.join(root, "other")
    try:
        # Its flag came with the listing; its data is cached, yet nothing is read.
        cache.remember_prefs(quiet, {"no_cache": False, "no_auto_load": True, "set_at": 1.0}, known=False)
        cache._observe_cache(quiet, {"disk_cached": True, "cache_info": {"saved_at": time.time(), "signature": "s"}})
        select(qtbot, explorer, quiet)
        assert ("cached", quiet) not in cache.jobs and ("load", quiet) not in cache.jobs
        explorer._update_activity()
        assert explorer.folder_summary_label.text().endswith(AUTO_LOAD_OFF)
        assert explorer.retry_button.isVisibleTo(explorer) and explorer.retry_button.text() == "Load"
        tooltip = str(explorer.model.data(explorer.model.path_index(quiet), 3))
        assert "Not auto-loaded: your choice" in tooltip and "Not cached" not in tooltip
        IconsInitUtil.initialise_icons()
        icons = explorer.model.data(explorer.model.path_index(quiet), explorer.model.STATUS_EXTRA_ICONS_ROLE)
        assert isinstance(icons, list) and StatusIcons.ICON_NO_AUTO_LOAD in icons
        panel = FolderDetailsPanel(explorer)
        panel.show_explorer(explorer, service)
        assert panel.text("state") == AUTO_LOAD_OFF + " · Load data"
        # The other folder (its sibling) is not affected.
        assert cache.folder_prefs(other) == {"no_cache": False, "no_auto_load": False}
        # Deliberate loads work as usual, including the check that follows reading the cache.
        explorer.retry_button.click()
        read = next(r for r in service.pending if r.operation == "cached" and r.path == quiet)
        assert read.payload["deliberate"] is True
        for event in ({"kind": "loaded", "signature": "s", "files": 1, "rows": 2, "bytes": 48, "verified": False,
                       "fingerprint": [[1, 10, 0]], "problematic": []}, {"kind": "done"}):
            service.resultReady.emit(read, event)
        service.pending.remove(read)
        qtbot.waitUntil(lambda: ("load", quiet) in cache.jobs)
        check = next(r for r in service.pending if r.operation == "load" and r.path == quiet)
        assert check.payload["deliberate"] is True
        cache.cancel(explorer.model.owner)
        explorer.folder_opened_path = None
        for key in [key for key in cache.datasets if key[0] == quiet]:
            del cache.datasets[key]
        # Turned back on for the selected folder: it loads by itself.
        explorer._cache_read_path = None
        cache.remember_prefs(quiet, {"no_cache": False, "no_auto_load": False, "set_at": 2.0})
        assert ("cached", quiet) in cache.jobs
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_a_folder_not_cached_loads_from_its_files_and_ticking_it_offers_removal(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer = make_explorer(qtbot, service, cache, root, ["run", "other"])
    run, other = os.path.join(root, "run"), os.path.join(root, "other")
    asked: list[tuple[str, int | None]] = []

    def ask(path: str, size: int | None) -> bool:
        asked.append((path, size))
        return True
    explorer.ask_remove_cached = ask
    try:
        cache._observe_cache(run, {"disk_cached": True, "cache_info": {
            "saved_at": time.time(), "signature": "s", "disk_bytes": 420 << 20}})
        explorer.set_folder_flag(run, "no_cache", True)
        assert asked == [(run, 420 << 20)]
        request = admin(service, "prefs")
        assert request.payload["params"]["path"] == run and request.payload["params"]["no_cache"] is True
        assert request.payload["params"]["remove_cached"] is True
        assert cache.folder_prefs(run)["no_cache"]  # Shown at once.
        assert "Not cached: your choice" in str(explorer.model.data(explorer.model.path_index(run), 3))
        # Selecting it doesn't read the cache; its load says not to cache.
        select(qtbot, explorer, run)
        assert ("cached", run) not in cache.jobs
        assert next(r for r in service.pending if r.operation == "load" and r.path == run).payload["no_cache"] is True
        # The helper's answer is kept; no question for a folder with no cached data.
        service.resultReady.emit(request, {"kind": "folder_prefs", "path": run, "prefs": {
            "no_cache": True, "no_auto_load": False, "set_at": request.payload["params"]["set_at"]}})
        explorer.set_folder_flag(other, "no_cache", True)
        assert len(asked) == 1
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_cancel_drops_a_deliberate_reads_follow_up_check(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer = make_explorer(qtbot, service, cache, root, ["run", "other"])
    run, other = os.path.join(root, "run"), os.path.join(root, "other")
    try:
        cache.remember_prefs(run, {"no_cache": False, "no_auto_load": True, "set_at": 1.0}, known=False)
        cache._observe_cache(run, {"disk_cached": True, "cache_info": {"saved_at": time.time(), "signature": "s"}})
        select(qtbot, explorer, run)
        explorer.queue_load(other)
        explorer.retry_button.click()
        read = next(r for r in service.pending if r.operation == "cached" and r.path == run)
        for event in ({"kind": "loaded", "signature": "s", "files": 1, "rows": 2, "bytes": 48, "verified": False,
                       "fingerprint": [[1, 10, 0]], "problematic": []}, {"kind": "done"}):
            service.resultReady.emit(read, event)
        service.pending.remove(read)
        explorer.cancel_loading()  # Before the follow-up check runs.
        qtbot.wait(20)
        assert ("load", run) not in cache.jobs
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_dont_cache_during_a_queued_cached_read_loads_from_the_folder_instead(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer = make_explorer(qtbot, service, cache, root, ["run"])
    run = os.path.join(root, "run")
    explorer.ask_remove_cached = lambda path, size: False  # Keep it.
    try:
        cache._observe_cache(run, {"disk_cached": True, "cache_info": {"saved_at": time.time(), "signature": "s"}})
        select(qtbot, explorer, run)
        # The check runs beside the cached read, counting its shots as held.
        assert ("cached", run) in cache.jobs and ("load", run) in cache.jobs
        explorer.set_folder_flag(run, "no_cache", True)
        assert ("cached", run) not in cache.jobs
        qtbot.waitUntil(lambda: any(r.operation == "load" and r.path == run and r.payload["no_cache"]
                                    for r in service.pending))
        load_request = next(r for r in service.pending if r.operation == "load" and r.path == run
                            and r.payload["no_cache"])
        assert load_request.payload["cache_base"] is False
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_setting_a_flag_stops_automatic_work_it_rules_out(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer = make_explorer(qtbot, service, cache, root, ["a", "b"])
    a, b = os.path.join(root, "a"), os.path.join(root, "b")
    try:
        select(qtbot, explorer, a)
        assert ("load", a) in cache.jobs  # An automatic load...
        explorer.set_folder_flag(a, "no_auto_load", True)
        assert ("load", a) not in cache.jobs  # ...stops when the user turns auto-load off.
        explorer._update_activity()
        assert explorer.load_error == "" and AUTO_LOAD_OFF in explorer.folder_summary_label.text()
        explorer.queue_load(b)  # Asked for: it stays.
        explorer.set_folder_flag(b, "no_auto_load", True)
        assert ("load", b) in cache.jobs
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_a_flag_that_cant_be_saved_is_put_back_and_reported(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer = make_explorer(qtbot, service, cache, root, ["a"])
    a = os.path.join(root, "a")
    reports: list[str] = []
    explorer.report_flag_failure = lambda path, text: reports.append(text)
    try:
        explorer.set_folder_flag(a, "no_auto_load", True)
        assert cache.folder_prefs(a)["no_auto_load"]
        request = admin(service, "prefs")
        service.resultReady.emit(request, {"kind": "error", "message": "disk full"})
        service.pending.remove(request)
        assert not cache.folder_prefs(a)["no_auto_load"]
        assert reports == ["HeLab couldn't save your choice for a: disk full. Try again."]
        # The queue is full: the same.
        monkeypatch.setattr(cache, "cache_admin", lambda action, **params: "")
        explorer.set_folder_flag(a, "no_cache", True)
        assert not cache.folder_prefs(a)["no_cache"] and "work queue is full" in reports[-1]
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_the_large_folder_warning_offers_dont_auto_load(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    cache.total_ram, cache.max_data_bytes = 100_000, 50_000
    root = str(tmp_path)
    explorer = make_explorer(qtbot, service, cache, root, ["big"])
    big = os.path.join(root, "big")
    try:
        select(qtbot, explorer, big)
        request = next(r for r in service.pending if r.operation == "load" and r.path == big)
        for event in ({"kind": "too_large", "estimate": 20_000, "refused": False}, {"kind": "done"}):
            service.resultReady.emit(request, event)
        service.pending.remove(request)
        explorer._update_activity()
        assert explorer.no_auto_load_button.isVisibleTo(explorer)
        explorer.no_auto_load_button.click()
        assert cache.folder_prefs(big)["no_auto_load"] and admin(service, "prefs").payload["params"]["no_auto_load"]
        explorer._update_activity()
        assert not explorer.no_auto_load_button.isVisibleTo(explorer)
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_the_cache_tab_lists_and_clears_folder_preferences_apart_from_clear_all(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    try:
        tab = CacheTab(cache, QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
        qtbot.addWidget(tab)
        asked: list[str] = []

        def confirm(title: str, text: str, verb: str) -> bool:
            asked.append(text)
            return True
        tab.confirm = confirm
        events: list[dict[str, Any]] = []
        with CacheStore(store_options()["directory"]) as store:
            store.set_prefs("/x", True, False, time.time())
            store.set_prefs("/y", True, True, time.time())
        cache_admin(store_options(), "inventory", events.append)
        request = admin(service, "inventory")
        for event in (events[0], {"kind": "done"}):
            service.resultReady.emit(request, event)
        service.pending.remove(request)
        assert tab.prefs_label.text() == "2 folders not cached · 1 folder not auto-loaded"
        tab.clear(list(KINDS))
        assert admin(service, "clear").payload["params"]["kinds"] == list(KINDS)  # Not the flags.
        service.pending.clear()
        tab._job = ""
        tab.clear_prefs()
        assert "2 folders not cached and 1 folder not auto-loaded" in asked[-1]
        assert admin(service, "clear_prefs").payload["params"] == {}
        tab.detach()
        with CacheStore(store_options()["directory"]) as store:
            store.clear_prefs()
    finally:
        service.shutdown()


def test_a_cleared_flag_is_forgotten_in_memory(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service, cache = frozen(monkeypatch)
    changed: list[str] = []
    cache.folderPrefsChanged.connect(changed.append)
    try:
        cache.set_folder_prefs("/x", no_cache=True, no_auto_load=False)
        assert changed == ["/x"]
        # A listing read before the choice doesn't undo it.
        cache.remember_prefs("/x", {}, known=False)
        assert cache.folder_prefs("/x")["no_cache"]
        request = admin(service, "prefs")
        service.resultReady.emit(request, {"kind": "prefs_cleared", "paths": ["/x"], "set_at": time.time()})
        assert cache.folder_prefs("/x") == {"no_cache": False, "no_auto_load": False} and changed == ["/x", "/x"]
        # A Clear's result arriving after a newer saved choice doesn't undo it.
        service.resultReady.emit(request, {"kind": "folder_prefs", "path": "/x", "prefs": {
            "no_cache": True, "no_auto_load": False, "set_at": time.time() + 10}})
        service.resultReady.emit(request, {"kind": "prefs_cleared", "paths": ["/x"], "set_at": time.time()})
        assert cache.folder_prefs("/x")["no_cache"]
    finally:
        service.shutdown()


def test_two_failed_choices_show_what_the_store_has(monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    try:
        cache.set_folder_prefs("/y", no_cache=True, no_auto_load=False)
        first = admin(service, "prefs")
        cache.set_folder_prefs("/y", no_cache=True, no_auto_load=True)
        second = admin(service, "prefs")
        for request in (second, first):  # Both fail, the newer first.
            service.resultReady.emit(request, {"kind": "error", "message": "disk full"})
            service.pending.remove(request)
            assert cache.folder_prefs("/y") == {"no_cache": False, "no_auto_load": False}  # Never saved.
        # A folder whose flag the store has: a failed change shows that flag again.
        cache.remember_prefs("/z", {"no_cache": True, "no_auto_load": False, "set_at": 1.0}, known=False)
        cache.set_folder_prefs("/z", no_cache=False, no_auto_load=False)
        failed = admin(service, "prefs")
        service.resultReady.emit(failed, {"kind": "error", "message": "disk full"})
        assert cache.folder_prefs("/z") == {"no_cache": True, "no_auto_load": False}
    finally:
        service.shutdown()


def test_returning_to_a_folder_in_ram_checks_it_again(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Data in RAM counts as checked only for a few seconds: back at the folder later, its check
    runs again (one folder stat when nothing changed), so a TXY added meanwhile is found."""
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer = make_explorer(qtbot, service, cache, root, ["run", "other"])
    run, other = os.path.join(root, "run"), os.path.join(root, "other")
    try:
        select(qtbot, explorer, run)
        load = next(r for r in service.pending if r.operation == "load" and r.path == run)
        for event in ({"kind": "shot", "shot": 1, "array": np.ones((1, 3)), "fingerprint": [1, 6, 123]},
                      {"kind": "loaded", "signature": "v1", "files": 1, "rows": 1, "bytes": 24, "problematic": [],
                       "fingerprint": [[1, 6, 123]]}, {"kind": "done"}):
            service.resultReady.emit(load, event)
        service.pending.remove(load)
        assert explorer.folder_opened_path == run and not explorer.shows_unchecked(run)
        select(qtbot, explorer, other)
        cache.cancel(explorer.model.owner)
        # Back within the freshness window: shown as checked, nothing runs.
        select(qtbot, explorer, run)
        assert ("load", run) not in cache.jobs and not explorer.shows_unchecked(run)
        select(qtbot, explorer, other)
        cache.cancel(explorer.model.owner)
        dataset = cache.current_dataset(run)
        assert dataset is not None
        dataset.metadata["checked_at"] -= cache.FRESH_SECONDS + 1
        snapshot = cache.snapshot(run)
        assert snapshot is not None
        snapshot.checked_at -= cache.FRESH_SECONDS + 1  # Its scan was a check too.
        # Later: shown at once, unchecked, and checked against the folder with the RAM shots held.
        select(qtbot, explorer, run)
        assert explorer.folder_opened_path == run and explorer.shows_unchecked(run)
        check = next(r for r in service.pending if r.operation == "load" and r.path == run)
        assert check.payload["memory"] == [[1, 6, 123]] and check.payload["base_signature"] == "v1"
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_missing_shots_in_a_background_load_list_the_folder(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer = make_explorer(qtbot, service, cache, root, ["run", "other"])
    run, other = os.path.join(root, "run"), os.path.join(root, "other")
    try:
        select(qtbot, explorer, run)
        assert explorer.queue_load(other)
        background = next(r for r in service.pending if r.operation == "load" and r.path == other)
        service.resultReady.emit(background, {"kind": "shots_missing", "missing": [1], "missing_count": 1,
                                              "known_count": 1, "listed_count": 0})
        service.resultReady.emit(background, {"kind": "done"})
        service.pending.remove(background)
        assert other in cache.mismatched and cache.mismatched[other]["listed_count"] == 0
        assert not explorer.load_error  # The shown folder is left alone.
        # Load as it is now (from the list window): queued like any explicit load.
        explorer.load_as_it_is_now(other)
        qtbot.waitUntil(lambda: any(r.operation == "load" and r.path == other and r.payload["allow_missing"]
                                    for r in service.pending))
        assert explorer.selected_path_globally == run
    finally:
        explorer.close_cleanup()
        service.shutdown()


@pytest.mark.parametrize("cached", [False, True], ids=["files", "cached"])
def test_a_load_starting_soon_spins_without_flashing_the_queued_indicator(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cached: bool,
) -> None:
    """Selecting a folder: its row spins until the data is in (no queued ring, no gap, in between)."""
    from helab.models.SnapshotFileSystemModel import SnapshotFileSystemModel as Model
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer = make_explorer(qtbot, service, cache, root, ["run"])
    run = os.path.join(root, "run")

    def shown() -> str:
        activity = explorer.model.path_index(run, Model.COLUMN_STATUS_ICON).data(Model.ACTIVITY_ROLE)
        return "spin" if activity in ("load", "check") else str(activity)
    try:
        if cached:
            cache._observe_cache(run, {"disk_cached": True, "cache_info": {"saved_at": time.time(), "signature": "v1"}})
        select(qtbot, explorer, run)
        states = [shown()]
        read = next((r for r in service.pending if r.operation == "cached" and r.path == run), None)
        if read is not None:
            for event in ({"kind": "shot", "shot": 1, "array": np.ones((1, 3)), "fingerprint": [1, 6, 1]},
                          {"kind": "loaded", "signature": "v1", "files": 1, "rows": 1, "bytes": 24, "problematic": [],
                           "fingerprint": [[1, 6, 1]], "verified": False, "source": "disk", "cached": True,
                           "disk_cached": True}, {"kind": "done"}):
                service.resultReady.emit(read, event)
            service.pending.remove(read)
            states.append(shown())
        load = next(r for r in service.pending if r.operation == "load" and r.path == run)
        service.resultReady.emit(load, {"kind": "started"})
        states.append(shown())
        assert set(states) == {"spin"}
        for event in ({"kind": "shot", "shot": 1, "array": np.ones((1, 3)), "fingerprint": [1, 6, 1]},
                      {"kind": "loaded", "signature": "v1", "files": 1, "rows": 1, "bytes": 24, "problematic": [],
                       "fingerprint": [[1, 6, 1]]}, {"kind": "done"}):
            service.resultReady.emit(load, event)
        service.pending.remove(load)
        assert run not in explorer.model.load_states and explorer.folder_opened_path == run
        # A load that keeps waiting does show the queued indicator (with no scan of it running).
        explorer.model.nodes[run].state = "idle"
        explorer.model.set_load_state(run, "queued")
        explorer.model.load_state_since[run] -= Model.QUEUED_INDICATOR_DELAY
        assert shown() == "queued"
    finally:
        explorer.close_cleanup()
        service.shutdown()


@pytest.mark.parametrize("reading", [False, True], ids=["checking", "reading"])
def test_a_check_beside_its_cached_read_leaves_with_it(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, reading: bool,
) -> None:
    """Leaving a cached folder while its check runs (Finish mode): a check that found nothing to
    read is cancelled with the cached read, with no error; one reading new files finishes in the
    background with its read, and both stop together."""
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer = make_explorer(qtbot, service, cache, root, ["run", "other"])
    run, other = os.path.join(root, "run"), os.path.join(root, "other")
    errors: list[str] = []
    try:
        assert explorer.load_mode == "finish"
        cache._observe_cache(run, {"disk_cached": True, "cache_info": {"saved_at": time.time(), "signature": "v1"}})
        select(qtbot, explorer, run)
        check = next(r for r in service.pending if r.operation == "load" and r.path == run)
        assert check.payload["cache_base"] is True and ("cached", run) in cache.jobs
        service.resultReady.emit(check, {"kind": "started"})
        if reading:
            service.resultReady.emit(check, {"kind": "progress", "progress": 0.0, "read_bytes": 0, "read_files": 0,
                                             "total_read_bytes": 100})

        def record(request: IORequest, event: dict[str, Any]) -> None:
            if request.path == run and event["kind"] == "error":
                errors.append(event["message"])
        cache.resultReady.connect(record)
        select(qtbot, explorer, other)
        if not reading:
            assert ("load", run) not in cache.jobs and ("cached", run) not in cache.jobs
            assert run not in explorer._bg_paths and run not in explorer.model.load_states
        else:
            assert run in explorer._bg_paths
            for operation in ("load", "cached"):
                assert [owner for owner, _ in cache.jobs[(operation, run)].subscribers] == [explorer.bg_owner]
            # Stopped in the background (trimmed, cancelled): its read stops too.
            cache.cancel(explorer.bg_owner, "load", run)
            assert ("load", run) not in cache.jobs and ("cached", run) not in cache.jobs
        assert not errors
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_returning_to_a_background_check_brings_its_cached_read_back(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer = make_explorer(qtbot, service, cache, root, ["run", "other"])
    run, other = os.path.join(root, "run"), os.path.join(root, "other")
    try:
        cache._observe_cache(run, {"disk_cached": True, "cache_info": {"saved_at": time.time(), "signature": "v1"}})
        select(qtbot, explorer, run)
        check = next(r for r in service.pending if r.operation == "load" and r.path == run)
        for event in ({"kind": "started"}, {"kind": "progress", "progress": 0.0, "read_bytes": 0, "read_files": 0,
                                             "total_read_bytes": 100}):
            service.resultReady.emit(check, event)
        read_job = cache.jobs[("cached", run)]
        select(qtbot, explorer, other)
        assert run in explorer._bg_paths
        select(qtbot, explorer, run)
        assert run not in explorer._bg_paths and explorer.loading
        assert cache.jobs[("cached", run)] is read_job  # The same read, not a new one.
        for operation in ("load", "cached"):
            assert [owner for owner, _ in cache.jobs[(operation, run)].subscribers] == [explorer.model.owner]
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_missing_shots_offer_retry_and_review(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Retry stays (mounting the right drive is a fix); Review… shows the folder in the list window."""
    from helab.views.FolderExplorer import MISMATCH_RETRY_TOOLTIP
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer = make_explorer(qtbot, service, cache, root, ["run"])
    run = os.path.join(root, "run")
    reviewed: list[str] = []
    explorer.reviewMismatchRequested.connect(reviewed.append)
    try:
        select(qtbot, explorer, run)
        load = next(r for r in service.pending if r.operation == "load" and r.path == run)
        service.resultReady.emit(load, {"kind": "shots_missing", "missing": [1, 2], "missing_count": 2,
                                        "known_count": 3, "listed_count": 1})
        service.resultReady.emit(load, {"kind": "done"})
        service.pending.remove(load)
        explorer._update_folder_summary()
        assert explorer.load_error == "2 cached shots missing — Retry after checking the drive, or Review…"
        assert not explorer.retry_button.isHidden() and explorer.retry_button.isEnabled()
        assert explorer.retry_button.toolTip() == MISMATCH_RETRY_TOOLTIP
        assert not explorer.review_button.isHidden()
        explorer.review_button.click()
        assert reviewed == [run]
    finally:
        explorer.close_cleanup()
        service.shutdown()
