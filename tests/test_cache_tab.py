"""Roadmap S7: the Settings → Cache tab, the disk and RAM budgets, the 80% pause and the cache dialogs."""
from __future__ import annotations

import itertools
import os
from pathlib import Path
import time
from typing import Any

import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QDialog, QMessageBox, QWidget

from helab.io_ops.admin import cache_admin
from helab.utils.cache_store import CacheStore, DatasetRecord, _record_bytes, trim_estimate
from helab.utils.constants import (
    DISK_BUDGET_SETTING, RAM_BUDGET_SETTING, read_disk_budget, read_io_concurrency, read_ram_budget,
    read_ram_budget_steps, ram_step_range,
)
from helab.utils.folder_cache import Dataset, FolderCache, get_folder_cache, store_options
from helab.utils.io_service import IORequest, IOService
from helab.views.CacheDialogs import CacheDialogs
from helab.utils.number_format import byte_size
from helab.views.CacheTab import CacheTab, RamBudgetSpinBox
from helab.views.SettingsDialog import SettingsDialog
from helab.views.FolderDetailsPanel import FolderDetailsPanel
from helab.views.FolderExplorer import AUTO_LOAD_PAUSED, FolderExplorer

GB = 1 << 30
DAY = 86400.0


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


def inventory(usage: int = 3 * GB, **changes: Any) -> dict[str, Any]:
    now = time.time()
    value: dict[str, Any] = {
        "layout_version": 2, "store_id": "s", "read_only": False, "root": "/cache", "usage": usage,
        "budget": 8 * GB, "records_bytes": 1 << 20,
        "datasets": {"count": 3, "bytes": 3 * GB, "ram_bytes": 4 * GB, "last_used": now - 7200},
        "summaries": {"count": 445}, "subtrees": {"count": 33}, "histories": {"count": 10, "blocked": 3},
        "pending": [], "retired": {"count": 0, "bytes": 0}, "orphans": {"count": 0, "bytes": 0},
        # Two datasets unused for 100 days, one used two hours ago.
        "ages": {"datasets": [[now - 100 * DAY, GB], [now - 100 * DAY, GB], [now - 7200, GB]],
                 "summaries": [now - 100 * DAY] * 5 + [now] * 440, "subtrees": [now] * 33,
                 "histories": [[now - 100 * DAY, True], [now - 100 * DAY, False]] + [[now, True]] * 8},
        "next_deadline": None, "checked_at": now, "usage_seq": ["s", 1]}
    value.update(changes)
    return value


def make_tab(qtbot: QtBot, cache: FolderCache, tmp_path: Path) -> tuple[CacheTab, list[tuple[str, str, str]]]:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    tab = CacheTab(cache, settings)
    qtbot.addWidget(tab)
    asked: list[tuple[str, str, str]] = []

    def confirm(title: str, text: str, verb: str) -> bool:
        asked.append((title, text, verb))
        return True
    tab.confirm = confirm
    return tab, asked


def test_cache_tab_shows_the_inventory_and_disables_actions_until_it_arrives(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    try:
        tab, _ = make_tab(qtbot, cache, tmp_path)
        request = admin_request(service, "inventory")
        assert tab.checked_label.text() == "Checking…" and tab.kind_labels["datasets"].text() == "Checking…"
        assert not tab.clear_all_button.isEnabled() and not tab.refresh_button.isEnabled()
        finish(service, request, {"kind": "inventory", "inventory": inventory(
            retired={"count": 1, "bytes": GB}, pending=[{"pending_id": "p", "path": "/x", "reason": "over_budget",
                                                          "bytes": 1, "created_at": 1.0, "job_seq": 1}])})
        assert tab.usage_label.text() == "3.0 GB of 8.0 GB budget · freeing 1.0 GB · 1 save waiting for your answer"
        assert tab.usage_bar.value() == 375
        assert tab.kind_labels["datasets"].text() == "3 folders · 3.0 GB · last used 2h ago"
        assert tab.kind_labels["summaries"].text() == "445 folders"
        assert tab.kind_labels["histories"].text() == "3 folders skip automatic checks"
        assert tab.kind_labels["subtrees"].text() == "33 folders"
        assert tab.checked_label.text().startswith("Checked ")
        # The purge estimates use the inventory's ages: 90 days by default.
        assert tab.dataset_estimate.text() == "— frees ~2.0 GB (2 folders)"
        assert tab.record_estimate.text() == "— 6 records"  # 5 summaries, 1 history without failures.
        tab.include_failures.setChecked(True)
        assert tab.record_estimate.text() == "— 7 records"
        tab.dataset_days.setValue(200)
        assert tab.dataset_estimate.text() == "— frees ~0 B (0 folders)" and not tab.purge_datasets_button.isEnabled()
        assert all(button.isEnabled() for button in (*tab.kind_buttons.values(), tab.clear_all_button,
                                                     tab.refresh_button, tab.purge_records_button))
        # A store written by a newer HeLab is read only: nothing can be removed.
        tab.refresh()
        finish(service, admin_request(service, "inventory"),
               {"kind": "inventory", "inventory": inventory(read_only=True)})
        assert "read only" in tab.usage_label.text()
        assert not any(button.isEnabled() for button in (*tab.kind_buttons.values(), tab.clear_all_button,
                                                         tab.purge_records_button))
        tab.detach()
    finally:
        service.shutdown()


@pytest.mark.parametrize("kind", ["datasets", "summaries", "histories", "subtrees", "all"])
def test_clear_asks_first_runs_once_and_refreshes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    try:
        tab, asked = make_tab(qtbot, cache, tmp_path)
        finish(service, admin_request(service, "inventory"), {"kind": "inventory", "inventory": inventory()})
        if kind == "all":
            tab.clear_all_button.click()
        else:
            tab.kind_buttons[kind].click()
        title, text, verb = asked[-1]
        expected = {"datasets": ("Clear cached data?", "3 folders (3.0 GB)", "Loaded data stays open"),
                    "summaries": ("Clear folder summaries?", "445 folders", "after their next check"),
                    "histories": ("Forget scan failures?", "3 folders", "Automatic checks will try these folders"),
                    "subtrees": ("Clear subfolder status?", "33 folders", "derived again"),
                    "all": ("Clear the disk cache?", "3 folders (3.0 GB)", "Loaded data stays open")}[kind]
        assert title == expected[0] and expected[1] in text and expected[2] in text
        request = admin_request(service, "clear")
        assert request.payload["params"] == {
            "kinds": ["datasets", "summaries", "histories", "subtrees", "listings"] if kind == "all" else [kind]}
        # While it runs, nothing else can start.
        assert tab.busy and not tab.clear_all_button.isEnabled() and not tab.refresh_button.isEnabled()
        tab.clear(["datasets"])
        tab.purge_datasets()
        assert len(asked) == 1
        finish(service, request, {"kind": "removed", "kinds": request.payload["params"]["kinds"], "paths": None,
                                  "datasets": 3, "bytes": 3 * GB},
               {"kind": "admin_result", "action": "clear", "next_deadline": None, "usage": 0,
                "usage_seq": ["s", 5]})
        assert not tab.busy and cache.disk_usage == 0
        # It shows what is left.
        refreshed = admin_request(service, "inventory")
        finish(service, refreshed, {"kind": "inventory", "inventory": inventory(usage=0)})
        assert tab.usage_label.text().startswith("0 B of 8.0 GB budget")
        tab.detach()
    finally:
        service.shutdown()


def test_declined_clear_runs_nothing_and_a_failed_one_says_why(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    try:
        tab, _ = make_tab(qtbot, cache, tmp_path)
        finish(service, admin_request(service, "inventory"), {"kind": "inventory", "inventory": inventory()})
        tab.confirm = lambda title, text, verb: False
        tab.clear_all_button.click()
        assert not any(r.payload.get("action") == "clear" for r in service.pending) and not tab.busy
        tab.confirm = lambda title, text, verb: True
        tab.kind_buttons["datasets"].click()
        request = admin_request(service, "clear")
        service.resultReady.emit(request, {"kind": "error", "message": "database is locked"})
        service.pending.remove(request)
        assert not tab.busy and "Clear cached data failed: database is locked" in tab.checked_label.text()
        tab.detach()
    finally:
        service.shutdown()


def test_purges_ask_with_the_estimate_and_send_the_cutoff(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    try:
        tab, asked = make_tab(qtbot, cache, tmp_path)
        finish(service, admin_request(service, "inventory"), {"kind": "inventory", "inventory": inventory()})
        tab.dataset_days.setValue(30)
        tab.purge_datasets_button.click()
        assert "2 folders (2.0 GB) not used in the last 30 days" in asked[-1][1]
        request = admin_request(service, "purge")
        params = request.payload["params"]
        assert params["what"] == "datasets" and abs(params["cutoff"] - (time.time() - 30 * DAY)) < 5
        finish(service, request, {"kind": "admin_result", "action": "purge", "next_deadline": None})
        finish(service, admin_request(service, "inventory"), {"kind": "inventory", "inventory": inventory()})
        tab.include_failures.setChecked(True)
        tab.purge_records_button.click()
        assert "7 folder records" in asked[-1][1] and "try folders whose scan failed again" in asked[-1][1]
        params = admin_request(service, "purge").payload["params"]
        assert params["what"] == "records" and params["include_failures"] is True
        tab.detach()
    finally:
        service.shutdown()


def test_lowering_the_disk_budget_below_use_asks_and_trims(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    try:
        tab, asked = make_tab(qtbot, cache, tmp_path)
        applied: list[bool] = []
        tab.budgetApplied.connect(applied.append)
        settings = tab.settings
        assert tab.disk_budget.value() == 8.0 and read_disk_budget(settings) == 8 * GB
        finish(service, admin_request(service, "inventory"), {"kind": "inventory", "inventory": inventory()})
        assert tab.apply_budget() is True  # Unchanged: nothing to tell the store.
        # Above current use: no question, nothing removed; the store records it first.
        tab.disk_budget.setValue(4.0)
        assert tab.apply_budget() is None and not asked and tab.applying
        request = admin_request(service, "budget")
        assert request.payload["params"]["budget"] == 4 * GB
        assert abs(request.payload["params"]["budget_set_at"] - time.time()) < 60
        assert tab.apply_budget() is False  # One at a time.
        assert tab.checked_label.text() == "Changing the disk budget…" and not tab.disk_budget.isEnabled()
        tab.disk_budget.setValue(1.0)  # Changed anyway: Save still writes only what the store has.
        finish(service, request, {"kind": "admin_result", "action": "budget", "budget": 4 * GB, "next_deadline": None})
        assert applied == [True] and not tab.applying and tab.disk_budget.isEnabled()
        tab.save(settings)
        assert read_disk_budget(settings) == 4 * GB
        finish(service, admin_request(service, "inventory"), {"kind": "inventory", "inventory": inventory()})
        # Below it: asked first, with what goes (least recently used first).
        tab.disk_budget.setValue(1.5)
        def decline(title: str, text: str, verb: str) -> bool:
            asked.append((title, text, verb))
            return False
        tab.confirm = decline
        assert tab.apply_budget() is False
        assert "up to 2 folders (2.0 GB), least recently used first" in asked[-1][1]
        assert trim_estimate(inventory(), int(1.5 * GB)) == {"datasets": 2, "bytes": 2 * GB}
        tab.confirm = lambda title, text, verb: True
        # The job can't be queued: nothing is saved, and the tab says why.
        queue = cache.cache_admin
        monkeypatch.setattr(cache, "cache_admin", lambda action, **params: "")
        assert tab.apply_budget() is False and "nothing saved" in tab.checked_label.text()
        monkeypatch.setattr(cache, "cache_admin", queue)
        # The trim records the budget and removes, in one job; if it fails, neither happened.
        assert tab.apply_budget() is None
        trim = admin_request(service, "trim")
        assert trim.payload["params"]["budget"] == int(1.5 * GB)
        service.resultReady.emit(trim, {"kind": "error", "message": "database is locked"})
        service.pending.remove(trim)
        assert applied == [True, False]
        assert "Changing the disk budget failed: database is locked — nothing saved" in tab.checked_label.text()
        # Typed values snap to steps of 0.5 GB.
        tab.disk_budget.setValue(2.3)
        assert tab.disk_budget_bytes() == int(2.5 * GB)
        tab.detach()
    finally:
        service.shutdown()


def test_settings_saves_a_new_disk_budget_once_the_store_has_it(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Until then a running load would still save within the old one."""
    service, cache = frozen_cache(monkeypatch)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("helab.utils.folder_cache._disk_budget", 8 * GB)
    monkeypatch.setattr("helab.utils.folder_cache._disk_budget_set_at", 0.0)
    try:
        for outcome in ("saved", "failed", "cancelled"):
            dialog = SettingsDialog(settings=settings, cache=cache)
            qtbot.addWidget(dialog)
            dialog.simultaneous_io_spin.setValue(7)
            dialog.cache_tab.disk_budget.setValue(12.0)  # Raised: no question.
            dialog.save_settings()
            request = admin_request(service, "budget")
            assert not dialog.save_button.isEnabled() and not dialog.reset_button.isEnabled()
            assert read_io_concurrency(settings) == 1 and read_disk_budget(settings) == 8 * GB
            if outcome == "saved":
                finish(service, request, {"kind": "admin_result", "action": "budget", "next_deadline": None})
                assert dialog.result() == QDialog.DialogCode.Accepted
                assert read_io_concurrency(settings) == 7 and read_disk_budget(settings) == 12 * GB
                settings.clear()
            elif outcome == "failed":
                service.resultReady.emit(request, {"kind": "error", "message": "disk full"})
                service.pending.remove(request)
                assert dialog.save_button.isEnabled() and dialog.reset_button.isEnabled()
                assert dialog.tabs.currentWidget() is dialog.cache_tab
                assert read_io_concurrency(settings) == 1 and not settings.contains(DISK_BUDGET_SETTING)
                dialog.reject()
            else:
                # Closed while the store records it: the saved budget is set again, so it is
                # newer, and sent until the store has it, however full the queue.
                queue = cache.cache_admin
                monkeypatch.setattr(cache, "cache_admin", lambda action, **params: "")
                dialog.reject()
                assert store_options()["budget"] == 8 * GB and cache._budget_timer.isActive()
                assert store_options()["budget_set_at"] >= request.payload["params"]["budget_set_at"]
                monkeypatch.setattr(cache, "cache_admin", queue)
                cache._budget_timer.timeout.emit()
                again = admin_request(service, "budget")
                assert again.payload["cache"] == store_options() and again.payload["params"] == {}
                service.resultReady.emit(again, {"kind": "error", "message": "database is locked"})
                service.pending.remove(again)
                assert cache._budget_timer.isActive()  # Failed: sent again.
                cache._budget_timer.timeout.emit()
                finish(service, admin_request(service, "budget"),
                       {"kind": "admin_result", "action": "budget", "next_deadline": None})
                assert not cache._budget_timer.isActive() and not cache._budget_owner
                assert read_io_concurrency(settings) == 1
    finally:
        service.shutdown()


def test_reset_then_save_tells_the_store_the_default_budget(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Reset saves the defaults at once; the budget in effect is still the store's until Save."""
    service, cache = frozen_cache(monkeypatch)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue(DISK_BUDGET_SETTING, 12 * GB)
    monkeypatch.setattr("helab.utils.folder_cache._disk_budget", 12 * GB)
    try:
        dialog = SettingsDialog(settings=settings, cache=cache)
        qtbot.addWidget(dialog)
        dialog.cache_tab.confirm = lambda title, text, verb: True
        # Use is below the default: lowering to it removes nothing.
        finish(service, admin_request(service, "inventory"), {"kind": "inventory", "inventory": inventory(GB)})
        dialog.reset_settings()
        assert dialog.cache_tab.disk_budget_bytes() == 8 * GB and not settings.contains(DISK_BUDGET_SETTING)
        dialog.save_settings()
        request = admin_request(service, "budget")
        assert request.payload["params"]["budget"] == 8 * GB and not dialog.save_button.isEnabled()
        finish(service, request, {"kind": "admin_result", "action": "budget", "next_deadline": None})
        assert read_disk_budget(settings) == 8 * GB
    finally:
        service.shutdown()


def test_a_lowered_budget_is_checked_against_what_is_cached_by_then(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The tab's inventory may be old: the helper only records a lower budget the data fits."""
    service, cache = frozen_cache(monkeypatch)
    try:
        tab, asked = make_tab(qtbot, cache, tmp_path)
        applied: list[bool] = []
        tab.budgetApplied.connect(applied.append)
        finish(service, admin_request(service, "inventory"), {"kind": "inventory", "inventory": inventory()})
        for answer in (False, True):
            def confirm(title: str, text: str, verb: str, answer: bool = answer) -> bool:
                asked.append((title, text, verb))
                return answer
            tab.confirm = confirm
            tab.disk_budget.setValue(4.0)  # Above the 3 GB the tab saw: no question yet.
            assert tab.apply_budget() is None and not asked
            request = admin_request(service, "budget")
            assert request.payload["params"]["fit"] is True
            # 5 GB is cached by now: not recorded, so the tab asks with that.
            finish(service, request, {"kind": "admin_result", "action": "budget", "budget": 4 * GB,
                                      "recorded": False, "usage": 5 * GB, "next_deadline": None})
            assert asked[-1][0] == "Lower the disk cache budget?" and "now uses 5.0 GB, more than 4.0 GB" in asked[-1][1]
            asked.clear()
            if not answer:
                assert applied == [False] and tab._acknowledged is None
                assert "Budget not lowered — nothing saved" in tab.checked_label.text()
                finish(service, admin_request(service, "inventory"), {"kind": "inventory", "inventory": inventory()})
                applied.clear()
                continue
            trim = admin_request(service, "trim")
            assert trim.payload["params"]["budget"] == 4 * GB and tab.applying and not applied
            finish(service, trim, {"kind": "admin_result", "action": "trim", "next_deadline": None})
            assert applied == [True] and tab._acknowledged == 4 * GB
        tab.detach()
    finally:
        service.shutdown()


def test_a_budget_job_that_fails_may_have_recorded_it_so_the_budget_in_effect_is_sent_again(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    monkeypatch.setattr("helab.utils.folder_cache._disk_budget", 8 * GB)
    monkeypatch.setattr("helab.utils.folder_cache._disk_budget_set_at", 0.0)
    try:
        tab, _ = make_tab(qtbot, cache, tmp_path)
        tab.disk_budget.setValue(12.0)
        assert tab.apply_budget() is None
        request = admin_request(service, "budget")
        # Committed, then the helper died before saying so.
        service.resultReady.emit(request, {"kind": "cancelled", "message": "Helper exited"})
        service.pending.remove(request)
        assert "Changing the disk budget failed" in tab.checked_label.text()
        assert store_options()["budget"] == 8 * GB
        assert store_options()["budget_set_at"] > request.payload["params"]["budget_set_at"]
        again = admin_request(service, "budget")
        assert again is not request and again.payload["params"] == {} and cache._budget_owner == again.owner
        tab.detach()
    finally:
        service.shutdown()


def test_the_helper_records_a_lower_budget_only_if_the_data_fits(tmp_path: Path) -> None:
    root = str(tmp_path / "store-v2")
    with CacheStore(root) as store:
        store.save_dataset("/a", store.write_dataset_file(os.urandom(200_000)), {
            "ram_bytes": 1, "rows": 1, "shots": 1, "fingerprint": [], "problematic": [], "info": {}},
            store.start_dataset_job("/a"))
        usage = store.usage()
    set_at = time.time()
    options: dict[str, Any] = {"directory": root, "budget": GB, "budget_set_at": set_at - 60}
    for budget, recorded in ((usage - 1000, False), (usage + 1000, True)):
        events: list[Any] = []
        cache_admin(options, "budget", events.append, budget=budget, budget_set_at=set_at, fit=True)
        assert events[-1]["recorded"] is recorded and events[-1]["usage"] == usage
        with CacheStore(root) as store:
            assert store.record_budget(GB, set_at - 30) == (budget if recorded else GB)
    # Without ``fit`` (e.g. sending the budget in effect again) it is always recorded.
    events = []
    cache_admin(options, "budget", events.append, budget=1000, budget_set_at=set_at + 1)
    assert events[-1]["recorded"] is True


def test_ram_budget_steps_of_1_128_of_ram(qtbot: QtBot, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    total = 128 * GB
    assert read_ram_budget_steps(settings, total) == 16 and read_ram_budget(settings, total) == 16 * GB
    assert ram_step_range(total) == (1, 64) and ram_step_range(8 * GB) == (16, 64)
    assert ram_step_range(16 * GB) == (8, 64)  # At least 1 GB.
    for saved, expected in ((200, 64), (0, 1), ("junk", 16)):
        settings.setValue(RAM_BUDGET_SETTING, saved)
        assert read_ram_budget_steps(settings, total) == expected
    box = RamBudgetSpinBox(total)
    qtbot.addWidget(box)
    box.setValue(16)
    assert box.text() == "16.0 GB (1/8 of 128 GB)"
    box.setValue(3)
    assert box.text() == "3.0 GB (3/128 of 128 GB)"
    # A typed size snaps to the nearest step, within range.
    assert box.valueFromText("10.4 GB") == 10 and box.valueFromText("900") == 64


def test_ram_budget_drops_unshown_datasets_least_recently_used_first(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    try:
        def add(path: str, size: int) -> Dataset:
            dataset = Dataset(path, "s", {1: np.zeros((1, 3))}, {"bytes": size}, 0)
            cache.datasets[(path, "s", 0)] = dataset
            return dataset
        shown, old, recent = add("/shown", 600), add("/old", 300), add("/recent", 300)
        cache.retain("tab", shown)  # Shown in a tab: never dropped, even over budget.
        assert cache.memory_usage() == (3, 1200, 600)
        dropped = cache.set_ram_budget(900)
        assert dropped == [old] and cache.holds(shown) and cache.holds(recent)
        assert cache.set_ram_budget(0) == [recent] and cache.holds(shown)
        assert cache.memory_usage() == (1, 600, 600)
        # A tab can still show a dataset no longer kept (invalidated): it counts too.
        del cache.datasets[("/shown", "s", 0)]
        other = add("/other", 300)
        assert cache.memory_usage() == (2, 900, 600)
        assert cache.set_ram_budget(800) == [other] and cache.memory_usage() == (1, 600, 600)
    finally:
        service.shutdown()


def asking(dialogs: CacheDialogs) -> tuple[str, str]:
    """The pending save the open question is about, and which question it is."""
    pending_id, question = dialogs._asking
    return pending_id, question if not pending_id else CacheDialogs.kind(question)


def question(dialogs: CacheDialogs) -> QMessageBox:
    assert dialogs.dialog is not None
    return dialogs.dialog


_writes = itertools.count(1)


def usage_event(cache: FolderCache, usage: int, writes: int | None = None, store_id: str = "s") -> None:
    """A helper's usage measurement, by default after every earlier one."""
    cache._note_usage(usage, [store_id, next(_writes) if writes is None else writes])


def test_80_percent_dialog_once_per_crossing_and_ignore_lasts_the_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("helab.utils.folder_cache._disk_budget", 1000)
    service, cache = frozen_cache(monkeypatch)
    parent = QWidget()
    qtbot.addWidget(parent)
    purge: list[bool] = []
    dialogs = CacheDialogs(cache, parent, lambda: purge.append(True))
    warnings: list[bool] = []
    cache.diskNearlyFull.connect(lambda: warnings.append(True))
    try:
        usage_event(cache, 700)
        assert not cache.auto_load_paused and not warnings
        usage_event(cache, 800)
        assert cache.auto_load_paused and warnings == [True]
        qtbot.waitUntil(lambda: dialogs.dialog is not None)
        box = dialogs.dialog
        assert box is not None and "80% full (800 B of 1000 B)" in box.text()
        # Still over 80%: no second dialog for this crossing.
        usage_event(cache, 850)
        assert warnings == [True]
        next(b for b in box.buttons() if b.text() == "Open purge settings").click()
        qtbot.waitUntil(lambda: purge == [True])
        assert dialogs.dialog is None and cache.auto_load_paused
        # Below 80% resumes; crossing again asks again.
        usage_event(cache, 500)
        assert not cache.auto_load_paused
        usage_event(cache, 820)
        assert warnings == [True, True]
        qtbot.waitUntil(lambda: dialogs.dialog is not None)
        assert dialogs.dialog is not None
        next(b for b in question(dialogs).buttons() if b.text() == "Ignore this time").click()
        assert not cache.auto_load_paused
        # Ignore lasts the session, even across another crossing...
        usage_event(cache, 500)
        usage_event(cache, 900)
        assert not cache.auto_load_paused and warnings == [True, True]
        # ...until usage rises another 10% of the budget.
        usage_event(cache, 920)
        assert cache.auto_load_paused and warnings == [True, True, True]
        # An older measurement arriving late changes nothing; another store's (recreated) counts
        # once the cache folder says it holds that store (FolderCache.store_answer).
        usage_event(cache, 100, writes=0)
        assert cache.disk_usage == 920 and cache.auto_load_paused
        usage_event(cache, 930, writes=0, store_id="new")
        assert cache.disk_usage == 920
        probe = next(r for r in service.pending if r.operation == "cache_admin" and r.payload["action"] == "identity")
        for event in ({"kind": "admin_result", "action": "identity", "store": "new"}, {"kind": "done"}):
            service.resultReady.emit(probe, event)
        service.pending.remove(probe)
        assert cache.disk_usage is None  # The old store's usage goes with it.
        usage_event(cache, 930, writes=0, store_id="new")
        assert cache.disk_usage == 930
        # A larger budget resumes at once.
        monkeypatch.setattr("helab.utils.folder_cache._disk_budget", 2000)
        cache.update_auto_load_pause()
        assert not cache.auto_load_paused and dialogs.dialog is None
    finally:
        dialogs.detach()
        service.shutdown()


def pending(pending_id: str, path: str, reason: str = "over_budget", **changes: Any) -> dict[str, Any]:
    entry = {"kind": "cache_full" if reason == "over_budget" else "cache_approval", "pending_id": pending_id,
             "path": path, "reason": reason, "bytes": 420 << 20, "usage": 7900 << 20, "budget": 8 * GB,
             "job_seq": 1, "replaces": 300 << 20, "usage_seq": ["s", 1], "created_at": time.time(),
             "room": {"paths": ["/a", "/b"], "bytes": 1200 << 20, "oldest_last_used": 1.0,
                      "newest_last_used": time.mktime((2026, 8, 3, 12, 0, 0, 0, 0, -1)), "possible": True}}
    entry.update(changes)
    return entry


def hold(service: IOService, cache: FolderCache, event: dict[str, Any]) -> None:
    """A finished load's helper reports a held save."""
    owner = f"writer-{event['pending_id']}"
    cache._finishing[owner] = cache.key(event["path"])
    cache._finishing_epochs[owner] = 0
    request = IORequest(owner, 0, event["path"], "load", {}, 60)
    service.resultReady.emit(request, event)
    service.resultReady.emit(request, {"kind": "done"})


def test_one_cache_dialog_at_a_time_each_answering_its_own_save(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    parent = QWidget()
    qtbot.addWidget(parent)
    dialogs = CacheDialogs(cache, parent, lambda: None)
    first, second = str(tmp_path / "first"), str(tmp_path / "second")
    try:
        hold(service, cache, pending("p1", first))
        hold(service, cache, pending("p2", second, job_seq=1))
        qtbot.wait(10)  # The 80% warning (usage is 7.7 of 8 GB) waits for the saves' questions.
        box = dialogs.dialog
        assert box is not None and asking(dialogs) == ("p1", "over_budget")
        assert box.text() == "Not enough room in the disk cache for first (420 MB, 7.7 GB of 8.0 GB used)."
        assert "cached data for 2 folders (1.2 GB) not used since 3 Aug" in box.informativeText()
        assert len(parent.findChildren(QMessageBox)) == 1
        next(b for b in box.buttons() if b.text() == "Make room").click()
        adopt = admin_request(service, "adopt")
        # Exactly the folders the question named.
        assert adopt.payload["params"] == {"pending_id": "p1", "make_room": True, "room_paths": ["/a", "/b"]}
        # The next question follows, for the other save.
        qtbot.waitUntil(lambda: dialogs.dialog is not None and dialogs._asking[0] == "p2")
        assert "second" in question(dialogs).text()
        # Its save is superseded meanwhile: the question closes unanswered.
        cache._forget_pending({"p2"})
        assert dialogs.dialog is None or dialogs._asking[0] != "p2"
        assert not any(r.payload.get("action") == "discard" for r in service.pending)
        finish(service, adopt, {"kind": "admin_result", "action": "adopt", "adopted": True, "path": first,
                                "bytes": 1, "room": None, "cache_info": {"saved_at": 1.0}, "next_deadline": None})
        # Usage is still over 80%: only the warning is left.
        assert not cache.pending_saves
        qtbot.waitUntil(lambda: dialogs._asking == ("", "full"))
    finally:
        dialogs.detach()
        service.shutdown()


def test_save_update_rechecks_and_turns_into_make_room(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    # The app's budget is large enough that the 80% warning stays out of this test.
    monkeypatch.setattr("helab.utils.folder_cache._disk_budget", 100 * GB)
    service, cache = frozen_cache(monkeypatch)
    parent = QWidget()
    qtbot.addWidget(parent)
    dialogs = CacheDialogs(cache, parent, lambda: None)
    path = str(tmp_path / "run")
    try:
        hold(service, cache, pending("p1", path, "needs_approval", room=None))
        box = dialogs.dialog
        assert box is not None
        assert box.text() == "run changed: save the update to the disk cache (+120 MB, 7.8 GB of 100 GB)?"
        assert cache.cache_status(path).error == "Cache update waiting for your answer"
        next(b for b in box.buttons() if b.text() == "Save update").click()
        adopt = admin_request(service, "adopt")
        assert adopt.payload["params"] == {"pending_id": "p1", "make_room": False}
        qtbot.wait(10)
        assert dialogs.dialog is None  # Answered: not asked again while the helper works.
        # It no longer fits: the same save now asks Make room.
        finish(service, adopt, {"kind": "admin_result", "action": "adopt", "adopted": False, "path": path,
                                "bytes": 1, "room": pending("p1", path)["room"], "next_deadline": None})
        qtbot.waitUntil(lambda: dialogs.dialog is not None)
        assert asking(dialogs) == ("p1", "over_budget")
        # Don't cache: discards exactly that save; the data stays in RAM.
        next(b for b in question(dialogs).buttons() if b.text() == "Don't cache this folder now").click()
        discard = admin_request(service, "discard")
        assert discard.payload["params"] == {"pending_id": "p1"}
        finish(service, discard, {"kind": "admin_result", "action": "discard", "discarded": True,
                                  "next_deadline": None})
        assert not cache.pending_saves and cache.cache_status(path).error == ""
    finally:
        dialogs.detach()
        service.shutdown()


def test_a_failed_answer_asks_again_saying_why(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr("helab.utils.folder_cache._disk_budget", 100 * GB)  # No 80% warning here.
    service, cache = frozen_cache(monkeypatch)
    parent = QWidget()
    qtbot.addWidget(parent)
    notices: list[str] = []
    dialogs = CacheDialogs(cache, parent, lambda: None, notices.append)

    def fail(request: IORequest) -> None:
        # A helper that fails sends only ``error`` before it exits.
        service.resultReady.emit(request, {"kind": "error", "message": "database is locked"})
        service.pending.remove(request)
    try:
        hold(service, cache, pending("p1", str(tmp_path / "run")))
        next(b for b in question(dialogs).buttons() if b.text() == "Make room").click()
        fail(admin_request(service, "adopt"))
        # Nothing was saved: the same save is asked again, with why.
        qtbot.waitUntil(lambda: dialogs.dialog is not None)
        assert asking(dialogs) == ("p1", "over_budget")
        assert question(dialogs).informativeText().startswith("Make room failed: database is locked")
        assert "p1" in cache.pending_saves[cache.key(str(tmp_path / "run"))]["pending_id"]
        # A failed Don't cache is still "not now": said once, not asked again.
        next(b for b in question(dialogs).buttons() if b.text() == "Don't cache this folder now").click()
        fail(admin_request(service, "discard"))
        qtbot.wait(10)
        assert dialogs.dialog is None and notices == [
            "Disk cache: couldn't drop a waiting save — database is locked"]
    finally:
        dialogs.detach()
        service.shutdown()


def test_saves_restored_from_the_store_ask_with_its_numbers(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """After a restart, the pending saves come from the inventory, without their events' details."""
    root = store_options()["directory"]
    # A fingerprint large enough that the records count in what the update adds.
    record: DatasetRecord = {"ram_bytes": 1, "rows": 1, "shots": 1, "problematic": [], "info": {},
                              "fingerprint": [[i, 1000, 1_700_000_000] for i in range(300)]}
    with CacheStore(root) as store:
        for path, size in (("/a", 100_000), ("/b", 50_000)):
            store.save_dataset(path, store.write_dataset_file(os.urandom(size)), record,
                               store.start_dataset_job(path))
        budget = store.usage() + 20_000  # Over 80%.
        update = store.save_dataset("/a", store.write_dataset_file(os.urandom(110_000)), record,
                                    store.start_dataset_job("/a"), budget=budget)
        new = store.save_dataset("/c", store.write_dataset_file(os.urandom(30_000)), record,
                                 store.start_dataset_job("/c"), budget=budget)
    assert (update.reason, new.reason) == ("needs_approval", "over_budget")
    monkeypatch.setattr("helab.utils.folder_cache._disk_budget", budget)
    # Set now: newer than any budget an earlier test recorded in this worker's store.
    monkeypatch.setattr("helab.utils.folder_cache._disk_budget_set_at", time.time())
    events: list[Any] = []
    cache_admin(store_options(), "inventory", events.append)
    service, cache = frozen_cache(monkeypatch)
    parent = QWidget()
    qtbot.addWidget(parent)
    dialogs = CacheDialogs(cache, parent, lambda: None)
    try:
        cache.cache_admin("inventory")
        finish(service, admin_request(service, "inventory"), events[0])
        qtbot.waitUntil(lambda: dialogs.dialog is not None)
        # Grows by 10 kB and its records, not by the whole dataset.
        growth = update.bytes - 100_000
        now = int(events[0]["inventory"]["usage"])  # The store's usage now, not when the save was held.
        assert growth == 10_000 + _record_bytes(record) and _record_bytes(record) > 5000
        assert question(dialogs).text() == (f"a changed: save the update to the disk cache (+{byte_size(growth)}, "
                                            f"{byte_size(now + growth)} of {byte_size(budget)})?")
        next(b for b in question(dialogs).buttons() if b.text() == "Don't cache this update now").click()
        qtbot.waitUntil(lambda: dialogs._asking[0] == new.pending_id)
        assert "Make room removes cached data for 1 folder" in question(dialogs).informativeText()
    finally:
        dialogs.detach()
        service.shutdown()


def test_make_room_asks_again_when_its_plan_or_the_budget_changes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr("helab.utils.folder_cache._disk_budget", 8 * GB)
    service, cache = frozen_cache(monkeypatch)
    parent = QWidget()
    qtbot.addWidget(parent)
    dialogs = CacheDialogs(cache, parent, lambda: None)
    path = str(tmp_path / "run")
    try:
        hold(service, cache, pending("p1", path))
        first = question(dialogs)
        assert "of 8.0 GB used" in first.text() and "2 folders (1.2 GB)" in first.informativeText()
        # The budget changed (Settings): the open question is replaced, saying the new one.
        monkeypatch.setattr("helab.utils.folder_cache._disk_budget", 6 * GB)
        dialogs.next()
        assert dialogs.dialog is not first and "of 6.0 GB used" in question(dialogs).text()
        next(b for b in question(dialogs).buttons() if b.text() == "Make room").click()
        adopt = admin_request(service, "adopt")
        assert adopt.payload["params"]["room_paths"] == ["/a", "/b"]
        # The store's plan differs from what was shown: nothing removed, asked again with it.
        new_room = {"paths": ["/a", "/b", "/c"], "bytes": 1800 << 20, "oldest_last_used": 1.0,
                    "newest_last_used": 2.0, "possible": True}
        finish(service, adopt, {"kind": "admin_result", "action": "adopt", "adopted": False, "path": path,
                                "bytes": 1, "room": new_room, "next_deadline": None})
        qtbot.waitUntil(lambda: dialogs.dialog is not None)
        assert asking(dialogs) == ("p1", "over_budget") and "3 folders (1.8 GB)" in question(dialogs).informativeText()
    finally:
        dialogs.detach()
        service.shutdown()


def test_folder_bigger_than_the_budget_is_only_offered_dont_cache(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    parent = QWidget()
    qtbot.addWidget(parent)
    dialogs = CacheDialogs(cache, parent, lambda: None)
    try:
        hold(service, cache, pending("p1", str(tmp_path / "huge"), room={
            "paths": [], "bytes": 0, "oldest_last_used": None, "newest_last_used": None, "possible": False}))
        box = dialogs.dialog
        assert box is not None and [b.text() for b in box.buttons()] == ["Don't cache this folder now"]
        assert "larger than the disk cache budget" in box.informativeText()
    finally:
        dialogs.detach()
        service.shutdown()


# The explorer: automatic loads of uncached folders pause over 80%; cached folders still open.

def scan_folder(cache: FolderCache, path: str, children: list[str] | None = None, data: bool = True) -> None:
    job = cache.jobs[("list" if ("list", path) in cache.jobs else "scan", path)]
    request = next(r for r in cache.service.pending if r.owner == job.owner)
    cache.service.resultReady.emit(request, {"kind": "entries", "entries": [
        {"path": p, "modified": None} for p in (children or [])]})
    cache.service.resultReady.emit(request, {"kind": "status", "status": "ok", "count": 1, "raw": [1], "details": True,
                                           "txy": [1] if data else [], "modified": 0, "signature": "v1"})
    cache.service.resultReady.emit(request, {"kind": "done"})
    cache.service.pending.remove(request)


def test_over_80_percent_uncached_folders_wait_cached_ones_open_and_loading_resumes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr("helab.utils.folder_cache._disk_budget", 1000)
    service, cache = frozen_cache(monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    root = str(tmp_path)
    explorer = FolderExplorer(root, root, root, [0, 4, 5])
    qtbot.addWidget(explorer)
    explorer.selectionPathChanged.connect(lambda p: explorer.load_to_ram_cache(p))
    try:
        qtbot.waitUntil(lambda: ("list", root) in cache.jobs)
        new, cached = os.path.join(root, "new"), os.path.join(root, "cached")
        scan_folder(cache, root, [new, cached], data=False)
        qtbot.waitUntil(lambda: new in explorer.model.nodes and cached in explorer.model.nodes)
        for path in (new, cached):
            explorer.model.request_scan(path)
            scan_folder(cache, path)
        cache._set_disk_cached(cached, True)
        usage_event(cache, 900)
        assert cache.auto_load_paused
        explorer.tree.setCurrentIndex(explorer.model.path_index(new))
        qtbot.waitUntil(lambda: explorer.auto_load_paused_path == new)
        assert ("load", new) not in cache.jobs and not explorer.loading
        assert explorer.folder_summary_label.text().endswith(AUTO_LOAD_PAUSED)
        assert explorer.retry_button.isVisibleTo(explorer) and explorer.retry_button.text() == "Load"
        assert "Auto-load paused" in str(explorer.model.data(explorer.model.path_index(new), 3))
        panel = FolderDetailsPanel(explorer)
        panel.show_explorer(explorer, service)
        assert panel.text("state") == AUTO_LOAD_PAUSED + " · Load data"
        # A folder with cached data still opens from the cache.
        explorer.tree.setCurrentIndex(explorer.model.path_index(cached))
        qtbot.waitUntil(lambda: ("cached", cached) in cache.jobs)
        assert explorer.auto_load_paused_path is None
        # Back to the new folder; then usage drops below 80%: its load starts by itself.
        explorer.tree.setCurrentIndex(explorer.model.path_index(new))
        qtbot.waitUntil(lambda: explorer.auto_load_paused_path == new)
        usage_event(cache, 100)
        assert ("load", new) in cache.jobs and explorer.auto_load_paused_path is None
        cache.cancel(explorer.model.owner)
        # Deliberate loads work while paused.
        usage_event(cache, 950)
        explorer._release_load()
        explorer.load_to_ram_cache(new)
        assert explorer.auto_load_paused_path == new and ("load", new) not in cache.jobs
        explorer.retry_button.click()
        assert ("load", new) in cache.jobs
        # Its save is held while another question is open: the cache line and Folder details say so.
        hold(service, cache, pending("p9", new))
        explorer._update_activity()
        panel.show_explorer(explorer, service)
        assert explorer.folder_cache_label.text() == "Not cached — disk cache full"
        assert panel.text("cache") == "Not cached — disk cache full"
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_helpers_report_usage_with_results(tmp_path: Path) -> None:
    options: dict[str, Any] = {"directory": str(tmp_path / "store-v2"), "budget": GB}
    with CacheStore(str(options["directory"])) as store:
        guard = store.start_dataset_job("/a")
        store.save_dataset("/a", store.write_dataset_file(b"x" * 5000), {
            "ram_bytes": 1, "rows": 1, "shots": 1, "fingerprint": [], "problematic": [], "info": {}}, guard)
        usage = store.usage()
    for action, params in (("sweep", {}), ("trim", {"budget": GB}), ("discard", {"pending_id": "none"})):
        events: list[Any] = []
        cache_admin(options, action, events.append, **params)
        result = events[-1]
        assert result["usage"] == usage and result["usage_seq"][0] == store.store_id, action
    assert store_options()  # Tests run with the disk cache on.


def test_a_slow_inventory_never_undoes_a_newer_clear(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Usage measurements are ordered by the store's write count, not by when they finish."""
    budget = 600_000
    options: dict[str, Any] = {"directory": str(tmp_path / "store-v2"), "budget": budget}
    with CacheStore(str(options["directory"])) as store:
        store.save_dataset("/a", store.write_dataset_file(os.urandom(450_000)), {
            "ram_bytes": 1, "rows": 1, "shots": 1, "fingerprint": [], "problematic": [], "info": {}},
            store.start_dataset_job("/a"))
        slow = store.inventory(budget)  # Measured now; its helper is still sizing files.
    cleared: list[Any] = []
    cache_admin(options, "clear", cleared.append)
    after = cleared[-1]["usage"]
    assert slow["usage"] >= 0.8 * budget > after
    monkeypatch.setattr("helab.utils.folder_cache._disk_budget", budget)
    service, cache = frozen_cache(monkeypatch)
    try:
        cache.cache_admin("clear")
        finish(service, admin_request(service, "clear"), *cleared)
        assert cache.disk_usage == after and not cache.auto_load_paused
        cache.cache_admin("inventory")
        finish(service, admin_request(service, "inventory"), {"kind": "inventory", "inventory": slow})
        assert cache.disk_usage == after and not cache.auto_load_paused
    finally:
        service.shutdown()


def test_a_running_load_saves_within_a_budget_lowered_after_it_started(tmp_path: Path) -> None:
    """Each request carries the budget and when the app set it; the store keeps the latest."""
    root = str(tmp_path / "store-v2")
    record: DatasetRecord = {"ram_bytes": 1, "rows": 1, "shots": 1, "fingerprint": [], "problematic": [],
                             "info": {}}
    with CacheStore(root) as store:
        store.save_dataset("/a", store.write_dataset_file(os.urandom(100_000)), record,
                           store.start_dataset_job("/a"))
        usage = store.usage()
    started = time.time() - 60  # The load's request, with the old, large budget.
    lowered = usage + 50_000
    events: list[Any] = []
    cache_admin({"directory": root, "budget": lowered, "budget_set_at": started + 30}, "budget", events.append)
    assert events[-1]["budget"] == lowered
    with CacheStore(root) as store:
        late = store.save_dataset("/b", store.write_dataset_file(os.urandom(80_000)), record,
                                  store.start_dataset_job("/b"), budget=GB, budget_set_at=started)
        assert late.reason == "over_budget" and late.budget == lowered
        # A budget set later still wins over the recorded one (raised again).
        raised = store.save_dataset("/c", store.write_dataset_file(os.urandom(80_000)), record,
                                    store.start_dataset_job("/c"), budget=GB, budget_set_at=started + 40)
        assert raised.saved and raised.budget == GB
        # Make room and Save update use it too.
        assert store.record_budget(lowered, started + 50) == lowered
        adopted = store.adopt_pending(late.pending_id, budget=GB, budget_set_at=started)
        assert not adopted.adopted and adopted.room is not None


def test_startup_restores_saves_waiting_from_an_earlier_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    try:
        queue = cache.cache_admin
        monkeypatch.setattr(cache, "cache_admin", lambda action, **params: "" if action == "inventory" else
                            queue(action, **params))
        cache.clean_up_cache()
        assert cache._restore_timer.isActive()  # The queue was full: tried again shortly.
        monkeypatch.setattr(cache, "cache_admin", queue)
        cache._restore_timer.timeout.emit()
        finish(service, admin_request(service, "inventory"), {"kind": "inventory", "inventory": inventory(
            pending=[{"pending_id": "p", "path": "/x", "reason": "needs_approval", "bytes": 1, "replaces": 0,
                      "created_at": 1.0, "job_seq": 1}])})
        assert [entry["pending_id"] for entry in cache.pending_saves.values()] == ["p"]
        assert cache.disk_usage == 3 * GB
    finally:
        service.shutdown()


def test_a_trim_records_its_budget_only_if_it_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lowering the budget below use is one job: the store gets the budget with the removal, or neither."""
    root = str(tmp_path / "store-v2")
    with CacheStore(root) as store:
        store.save_dataset("/a", store.write_dataset_file(os.urandom(100_000)), {
            "ram_bytes": 1, "rows": 1, "shots": 1, "fingerprint": [], "problematic": [], "info": {}},
            store.start_dataset_job("/a"))
    set_at = time.time()
    options: dict[str, Any] = {"directory": root, "budget": GB, "budget_set_at": set_at - 60}

    def fail(self: CacheStore, budget: int, set_at: float | None = None) -> Any:
        raise RuntimeError("database is locked")
    with monkeypatch.context() as patch:
        patch.setattr(CacheStore, "trim", fail)
        with pytest.raises(RuntimeError):
            cache_admin(options, "trim", lambda event: None, budget=5000, budget_set_at=set_at)
    with CacheStore(root) as store:
        assert store.record_budget(GB, set_at - 30) == GB  # Not recorded.
    events: list[Any] = []
    cache_admin(options, "trim", events.append, budget=5000, budget_set_at=set_at)
    with CacheStore(root) as store:
        assert store.record_budget(GB, set_at - 30) == 5000 and store.usage() > 5000 > 0
        assert not store.read_dataset_row("/a").value
