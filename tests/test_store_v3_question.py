"""Caching v2, step 6: the store-v3 question (Keep using / Ignore / Clear…, Q19.4, Q22.3), Settings ›
Cache's rows for raw pulses and the older store (Clear all taking raw pulses too), Make room naming raw
pulses and only copies with "Clear old stores…" (D8, Q28.5), and ``removed`` kinds ``raw`` and
``legacy``. Temp stores only; no other HeLab may run for a Clear (the check is patched)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtWidgets import QWidget

from helab.io_ops.admin import cache_admin
from helab.utils import cache_locks
from helab.utils.cache_store import CacheStore, StoreError
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IOService
from helab.utils.number_format import byte_size
from helab.views.CacheDialogs import CacheDialogs, legacy_text, room_items, room_text

from test_cache_tab import admin_request, finish, frozen_cache, inventory, make_tab, pending, hold

MB = 10**6
pytestmark = pytest.mark.no_auto_data_root


def two_stores(tmp_path: Path) -> Path:
    caches = tmp_path / "caches"
    with CacheStore(str(caches / "store-v3")) as v3:
        v3.save_dataset("/data/x", v3.write_dataset_file(os.urandom(5000)),
                        {"ram_bytes": 1, "rows": 1, "shots": 1, "fingerprint": [], "problematic": [], "info": {}},
                        v3.start_dataset_job("/data/x"))
    with CacheStore(str(caches / "store-v4")):
        pass
    return caches


# The store and the admin

def test_the_choice_is_recorded_and_clear_removes_store_v3_only(tmp_path: Path) -> None:
    caches = two_stores(tmp_path)
    with CacheStore(str(caches / "store-v4")) as v4:
        assert v4.measure_legacy()["choice"] is None
        ignored = v4.set_legacy_choice("ignore")
        assert ignored["choice"] == "ignore" and ignored["counted"] is False
        assert v4._meta()["legacy_v3"]["v3_store_id"]
        assert v4.set_legacy_choice("keep")["counted"] is True
        with pytest.raises(ValueError):
            v4.set_legacy_choice("clear")
        gone = v4.clear_legacy()
        assert gone > 5000 and not (caches / "store-v3").exists() and (caches / "store-v4").exists()
        assert v4.measure_legacy() == {"present": False, "choice": "clear", "bytes": 0}
        assert sorted(os.listdir(caches)) == ["store-v4"]  # (Nothing set aside left behind.)
    with CacheStore(str(caches / "store-v3")) as v3:  # (An older HeLab may make it again.)
        with pytest.raises(StoreError, match="store-v4"):
            v3.clear_legacy()


def test_a_store_v3_that_is_a_link_is_never_cleared_through_it(tmp_path: Path) -> None:
    caches = tmp_path / "caches"
    real = tmp_path / "elsewhere" / "store-v3"
    with CacheStore(str(real)):
        pass
    caches.mkdir()
    os.symlink(real, caches / "store-v3")
    with CacheStore(str(caches / "store-v4")) as v4:
        with pytest.raises(StoreError, match="isn't a folder here"):
            v4.clear_legacy()
    assert (real / "records.sqlite").exists()


def test_the_admin_answers_with_the_new_state_and_says_what_it_removed(tmp_path: Path) -> None:
    caches = two_stores(tmp_path)
    options: dict[str, Any] = {"directory": str(caches / "store-v4")}
    events: list[Any] = []
    cache_admin(options, "legacy_choice", events.append, choice="ignore")
    assert events[-1]["kind"] == "admin_result" and events[-1]["legacy"]["choice"] == "ignore"
    events.clear()
    cache_admin(options, "clear_legacy", events.append)
    [removed] = [event for event in events if event["kind"] == "removed"]
    assert removed["kinds"] == ["legacy"] and removed["paths"] is None and removed["bytes"] > 5000
    assert events[-1]["legacy"]["present"] is False


# FolderCache and the question

LEGACY = {"present": True, "choice": None, "bytes": 6 * MB, "store_id": "v3", "counted": True}


def send_inventory(service: IOService, cache: FolderCache, **changes: Any) -> None:
    owner = cache.cache_admin("inventory")
    request = next(r for r in service.pending if r.owner == owner)
    finish(service, request, {"kind": "inventory", "inventory": inventory(**changes)})


def test_an_unanswered_store_v3_is_asked_about_once_a_session(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen_cache(monkeypatch)
    parent = QWidget()
    qtbot.addWidget(parent)
    dialogs = CacheDialogs(cache, parent, lambda: None)
    try:
        changed: list[bool] = []
        cache.legacyChanged.connect(lambda: changed.append(True))
        send_inventory(service, cache, legacy=LEGACY)
        assert cache.legacy == LEGACY and changed == [True]
        qtbot.waitUntil(lambda: dialogs.dialog is not None)
        box = dialogs.dialog
        assert box is not None and "store-v3, 6.0 MB" in box.text()
        assert [b.text() for b in box.buttons()] == ["Keep using it", "Ignore it", "Clear it…"]
        next(b for b in box.buttons() if b.text() == "Keep using it").click()
        choice = admin_request(service, "legacy_choice")
        assert choice.payload["params"] == {"choice": "keep"}
        finish(service, choice, {"kind": "admin_result", "action": "legacy_choice",
                                 "legacy": {**LEGACY, "choice": "keep"}})
        assert (cache.legacy or {}).get("choice") == "keep"
        send_inventory(service, cache, legacy=LEGACY)  # (Unanswered again, say: not asked twice a session.)
        qtbot.wait(20)
        assert dialogs.dialog is None
    finally:
        dialogs.detach()
        service.shutdown()


def test_clear_old_stores_asks_first_and_never_while_another_helab_runs(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from helab.views import CacheDialogs as module
    service, cache = frozen_cache(monkeypatch)
    cache.legacy = dict(LEGACY)
    parent = QWidget()
    qtbot.addWidget(parent)
    asked: list[str] = []
    told: list[str] = []
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *args: told.append(str(args[2])))
    try:
        assert module.ask_clear_old_stores(parent, cache, confirm=lambda *args: True, others=lambda: [123]) == ""
        assert told and "Another HeLab is running" in told[0]
        def decline(title: str, text: str, verb: str) -> bool:
            asked.append(text)
            return False
        assert module.ask_clear_old_stores(parent, cache, confirm=decline, others=lambda: []) == ""
        assert "store-v3, 6.0 MB" in asked[0] and not any(r.operation == "cache_admin" for r in service.pending)
        owner = module.ask_clear_old_stores(parent, cache, confirm=lambda *args: True, others=lambda: [])
        assert owner and admin_request(service, "clear_legacy").owner == owner
    finally:
        service.shutdown()


def test_make_room_names_raw_pulses_and_only_copies_and_removes_exactly_them() -> None:
    room = {"paths": ["/data/a"], "bytes": 100 * MB, "newest_last_used": None, "possible": True,
            "raw_paths": ["/data/b"], "only_copy_paths": ["/data/c"], "raw_bytes": 30 * MB}
    text = room_text(room)
    assert "cached data for 1 folder (100 MB)" in text and "raw pulses of 1 folder" in text
    assert "only copy: their raw files are gone from c" in text
    assert f"({byte_size(30 * MB, 'disk')} of raw pulses in all.)" in text
    assert room_items(room) == ["/data/a", "raw:/data/b", "raw-only:/data/c"]
    assert legacy_text(LEGACY) == "6.0 MB · not answered yet: kept"
    assert legacy_text({**LEGACY, "choice": "ignore"}) == "6.0 MB · ignored" and legacy_text(None) == ""


def test_make_room_offers_clear_old_stores_while_store_v3_counts(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
                                                                 tmp_path: Path) -> None:
    service, cache = frozen_cache(monkeypatch)
    cache.legacy = {**LEGACY, "choice": "keep"}
    parent = QWidget()
    qtbot.addWidget(parent)
    dialogs = CacheDialogs(cache, parent, lambda: None)
    try:
        room = {"paths": ["/a"], "bytes": 1, "oldest_last_used": 1.0, "newest_last_used": 1.0, "possible": True,
                "raw_paths": ["/b"], "only_copy_paths": [], "raw_bytes": 5}
        hold(service, cache, pending("p1", str(tmp_path / "first"), room=room))
        qtbot.waitUntil(lambda: dialogs.dialog is not None)
        box = dialogs.dialog
        assert box is not None and "Clear old stores…" in [b.text() for b in box.buttons()]
        next(b for b in box.buttons() if b.text() == "Make room").click()
        adopt = admin_request(service, "adopt")
        assert adopt.payload["params"]["room_paths"] == ["/a", "raw:/b"]  # (Exactly what it named.)
    finally:
        dialogs.detach()
        service.shutdown()


# Settings › Cache

def v4_inventory(**changes: Any) -> dict[str, Any]:
    return inventory(raw={"count": 40, "bytes": 30 * MB, "folders": 2, "only_copy": 3, "only_copy_bytes": 2 * MB,
                          "last_used": None}, legacy={**LEGACY, "choice": "keep"}, older_stores=[], **changes)


def test_the_tab_shows_raw_pulses_and_the_older_store_only_with_store_v4(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service, cache = frozen_cache(monkeypatch)
    monkeypatch.setattr(cache_locks, "other_instances", lambda app_dir: [])
    try:
        tab, asked = make_tab(qtbot, cache, tmp_path)
        tab.inventory = inventory()
        tab._update()
        assert not tab.raw_button.isVisibleTo(tab) and not tab.legacy_clear_button.isVisibleTo(tab)
        tab.inventory = v4_inventory()
        tab._update()
        assert tab.raw_button.isVisibleTo(tab) and tab.legacy_clear_button.isVisibleTo(tab)
        assert tab.raw_label.text() == f"40 shots in 2 folders · {byte_size(30 * MB, 'disk')} · 3 only copies"
        assert tab.legacy_label.text() == "6.0 MB · kept, counted in the budget"
        assert tab.legacy_choice_button.text() == "Ignore it"
        tab.clear_raw()
        assert "3 shots are the only copy" in asked[-1][1]
        assert admin_request(service, "clear_raw").payload["params"] == {}
        tab._job = ""
        tab.clear(["datasets", "summaries", "histories", "subtrees", "listings"])  # (Clear all.)
        assert f"raw pulses for 2 folders ({byte_size(30 * MB, 'disk')})" in asked[-1][1]
        assert admin_request(service, "clear").payload["params"]["kinds"][-1] == "raw"
        tab._job = ""
        tab.toggle_legacy()
        assert admin_request(service, "legacy_choice").payload["params"] == {"choice": "ignore"}
        tab._job = ""
        tab.clear_legacy()
        assert "store-v3, 6.0 MB" in asked[-1][1] and admin_request(service, "clear_legacy")
    finally:
        service.shutdown()


def test_the_tab_wont_clear_the_older_store_while_another_helab_runs(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service, cache = frozen_cache(monkeypatch)
    monkeypatch.setattr(cache_locks, "other_instances", lambda app_dir: [4321])
    try:
        tab, asked = make_tab(qtbot, cache, tmp_path)
        tab.inventory = v4_inventory()
        tab._update()
        tab.clear_legacy()
        assert asked == [] and "Another HeLab is running" in tab.message
        assert not any(r.payload.get("action") == "clear_legacy" for r in service.pending)
    finally:
        service.shutdown()
