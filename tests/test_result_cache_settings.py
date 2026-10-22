"""Clearing saved analysis results (result caching R2, Tony 2026-10-22): Settings → Cache shows
them apart (Cached analysis: count, size, last shown) with its own Clear… and purge by age, each
asking first; Clear all leaves them. Settings → Data roots has Clear cached analysis… per root
(button and row menu), beside Clear cached data…, which leaves them. A ``removed`` of kind
``results`` reaches FolderCache's subscribers."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterator

import pytest
from PyQt6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from helab.utils.folder_cache import FolderCache, get_folder_cache
from helab.utils.io_service import IORequest, IOService
from helab.views import DataRootsTab as tab_module
from helab.views.CacheTab import CacheTab
from helab.views.DataRootsTab import CLEAR, CLEAR_RESULTS, DataRootsTab

GB = 1 << 30
MB = 1 << 20
DAY = 86400.0
A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def frozen_cache(monkeypatch: pytest.MonkeyPatch) -> tuple[IOService, FolderCache]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    return service, get_folder_cache(service)


def admin_request(service: IOService, action: str) -> IORequest:
    return next(r for r in reversed(service.pending) if r.operation == "cache_admin" and r.payload["action"] == action)


def finish(service: IOService, request: IORequest, *events: dict[str, Any]) -> None:
    for event in (*events, {"kind": "done"}):
        service.resultReady.emit(request, event)
    service.pending.remove(request)


def inventory(**changes: Any) -> dict[str, Any]:
    now = time.time()
    value: dict[str, Any] = {
        "layout_version": 3, "store_id": "s", "read_only": False, "root": "/cache", "usage": 3 * GB,
        "budget": 8 * GB, "records_bytes": 1 << 20,
        "datasets": {"count": 3, "bytes": 2 * GB, "ram_bytes": 4 * GB, "last_used": now - 7200},
        "results": {"count": 4, "bytes": 40 * MB, "last_used": now - 3600},
        "summaries": {"count": 1}, "subtrees": {"count": 1}, "histories": {"count": 0, "blocked": 0},
        "pending": [], "retired": {"count": 0, "bytes": 0}, "orphans": {"count": 0, "bytes": 0},
        "ages": {"datasets": [[now - 7200, GB]], "summaries": [now], "subtrees": [now], "histories": [],
                 "results": [[now - 100 * DAY, 10 * MB], [now - 100 * DAY, 10 * MB], [now, 10 * MB],
                             [now, 10 * MB]]},
        "next_deadline": None, "checked_at": now, "usage_seq": ["s", 1]}
    value.update(changes)
    return value


@pytest.fixture
def cache_tab(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
              tmp_path: Path) -> Iterator[tuple[CacheTab, IOService, list[tuple[str, str, str]], list[bool]]]:
    service, cache = frozen_cache(monkeypatch)
    tab = CacheTab(cache, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(tab)
    asked: list[tuple[str, str, str]] = []
    answers = [True]

    def confirm(title: str, text: str, verb: str) -> bool:
        asked.append((title, text, verb))
        return answers[0]
    tab.confirm = confirm
    finish(service, admin_request(service, "inventory"), {"kind": "inventory", "inventory": inventory()})
    yield tab, service, asked, answers
    tab.detach()
    service.shutdown()


def test_the_cache_tab_shows_cached_analysis_apart(
        cache_tab: tuple[CacheTab, IOService, list[tuple[str, str, str]], list[bool]]) -> None:
    tab, *_ = cache_tab
    assert tab.results_label.text().startswith("4 results · 40.0 MB · last shown")
    assert tab.results_button.isEnabled() and "2 results" in tab.result_estimate.text()


def test_clear_cached_analysis_asks_first_and_clears_only_results(
        cache_tab: tuple[CacheTab, IOService, list[tuple[str, str, str]], list[bool]]) -> None:
    tab, service, asked, answers = cache_tab
    answers[0] = False
    tab.results_button.click()
    assert asked[-1][0] == "Clear cached analysis?" and "4 saved results (40.0 MB)" in asked[-1][1]
    assert "Cached data, folder records and exported files are kept" in asked[-1][1]
    assert not any(r.payload.get("action") == "clear_results" for r in service.pending) and not tab.busy
    answers[0] = True
    tab.results_button.click()
    request = admin_request(service, "clear_results")
    assert request.payload["params"] == {} and tab.busy
    finish(service, request, {"kind": "removed", "kinds": ["results"], "paths": None, "results": 4,
                              "bytes": 40 * MB, "root": None},
           {"kind": "admin_result", "action": "clear_results", "next_deadline": None})
    assert not tab.busy and admin_request(service, "inventory")


def test_clear_all_names_cached_analysis_as_kept(
        cache_tab: tuple[CacheTab, IOService, list[tuple[str, str, str]], list[bool]]) -> None:
    tab, service, asked, _ = cache_tab
    tab.clear_all_button.click()
    assert "Cached analysis stays" in asked[-1][1]
    assert admin_request(service, "clear").payload["params"]["kinds"] == ["datasets", "summaries", "histories",
                                                                         "subtrees"]


def test_purging_cached_analysis_by_age_asks_with_its_estimate(
        cache_tab: tuple[CacheTab, IOService, list[tuple[str, str, str]], list[bool]]) -> None:
    tab, service, asked, _ = cache_tab
    tab.result_days.setValue(30)
    tab.purge_results_button.click()
    assert asked[-1][0] == "Remove old cached analysis?"
    assert "2 saved results (20.0 MB) not shown in the last 30 days" in asked[-1][1]
    params = admin_request(service, "purge").payload["params"]
    assert params["what"] == "results" and abs(params["cutoff"] - (time.time() - 30 * DAY)) < 5


def test_a_results_removal_reaches_folder_cache_subscribers(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service, cache = frozen_cache(monkeypatch)
    monkeypatch.setattr("helab.utils.folder_cache.store_options", lambda: {"directory": str(tmp_path)})
    seen: list[tuple[Any, Any]] = []
    cache.cacheRemoved.connect(lambda paths, kinds: seen.append((paths, kinds)))
    owner = cache.cache_admin("clear_root_results", uuid=A)
    request = next(r for r in service.pending if r.owner == owner)
    service.resultReady.emit(request, {"kind": "removed", "kinds": ["results"], "paths": [str(tmp_path / "run")],
                                       "results": 1, "bytes": 10, "root": A})
    assert seen == [([FolderCache.key(str(tmp_path / "run"))], ["results"])]
    service.shutdown()


@pytest.fixture
def jobs() -> list[tuple[str, dict[str, Any]]]:
    return []


@pytest.fixture
def page(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
         jobs: list[tuple[str, dict[str, Any]]]) -> Iterator[DataRootsTab]:
    service, _ = frozen_cache(monkeypatch)
    cache = FolderCache(service)

    def admin(action: str, **params: Any) -> str:
        jobs.append((action, params))
        return f"job-{len(jobs)}"
    monkeypatch.setattr(cache, "cache_admin", admin)
    monkeypatch.setattr(tab_module, "store_options", lambda: {"directory": str(tmp_path)})
    settings = DataRootsTab(cache)
    qtbot.addWidget(settings)
    rows = [{"location": "smb://server/dld_output", "uuid": A, "kind": "smb", "label": "dld_output",
             "first_seen": 1.0e9, "last_seen": 1.7e9, "decision": "confirmed", "path": "",
             "cached": {"folders": 12, "bytes": 3 * GB, "results": 5, "result_bytes": 30 * MB}}]
    cache.cacheAdminResult.emit("inventory", {"kind": "inventory", "inventory": {"roots": rows}})
    cache.cacheAdminDone.emit("job-1", "inventory", "")
    yield settings
    settings.detach()
    service.shutdown()


def test_a_roots_clear_cached_analysis_asks_and_sends_only_that(
        page: DataRootsTab, jobs: list[tuple[str, dict[str, Any]]]) -> None:
    item = page.list.topLevelItem(0)
    assert item is not None
    page.list.setCurrentItem(item)
    assert "Cached analysis: 5 saved results (30.0 MB)" in item.toolTip(DataRootsTab.CACHED)
    actions = {action.text(): action for action in page.context_menu().actions()}
    assert actions[CLEAR].isEnabled() and actions[CLEAR_RESULTS].isEnabled() and page.clear_results_button.isEnabled()
    asked: list[str] = []
    answers = iter((False, True))

    def answer(title: str, text: str, verb: str) -> bool:
        asked.append(text)
        return next(answers)
    page.confirm = answer
    page.clear_results_selected()
    assert asked[-1] == ("Clears 5 saved results (30.0 MB) for data root “dld_output” on this computer: plots "
                         "compute them again. Its cached data, the .helab-root and folder flags stay.")
    assert len(jobs) == 1  # Declined: nothing sent.
    page.clear_results_selected()
    assert jobs[-1] == ("clear_root_results", {"uuid": A}) and not page.clear_results_button.isEnabled()
