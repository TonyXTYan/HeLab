"""Presets in the disk cache store (helab/utils/cache_store.py's ``presets`` table, the
``cache_admin`` "presets" action, FolderCache's RAM copy): written only by helpers, the newest
choice winning each preset, a delete kept so an older write can't bring it back, added to older
stores, read as none from a read-only one without it; RAM only while the cache folder is refused
(saved once it's there); a store that can't be read named, never "no presets"; untouched by Clear
all and Reset all settings; ``quit_saves`` waits for their writes."""
from __future__ import annotations

import re

import json
import sqlite3
import time
import weakref
from pathlib import Path
from typing import Any, Iterator

import pytest
from PyQt6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from conftest import store_free
from helab.io_ops.admin import cache_admin
from helab.utils import cache_store
from helab.utils.cache_store import KINDS, CacheStore, StoreError, StoreReadOnly
from helab.utils.folder_cache import (PRESET_FOUND, PRESETS_SAVING, PRESETS_WAIT_READ, FolderCache, get_folder_cache,
                                      store_options)
from helab.utils.io_service import IOService

ARR, SCR = "arrangement", "script"
A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def row(name: str, record: str | None, set_at: float, kind: str = ARR, scope: str = "") -> dict[str, Any]:
    return {"kind": kind, "scope": scope, "name": name, "record": record, "set_at": set_at}


def rows_of(store: CacheStore) -> dict[str, tuple[str | None, float]]:
    found = store.read_presets()
    assert found.found and found.value is not None
    return {entry["name"]: (entry["record"], entry["set_at"]) for entry in found.value}


# The store


def test_the_newest_choice_wins_and_a_delete_beats_an_older_write(tmp_path: Path) -> None:
    root = str(tmp_path / "store")
    with CacheStore(root) as store:
        assert store.write_presets([row("run", "{}", 10.0)]) == [row("run", "{}", 10.0)]
        # An older choice (another HeLab, a write arriving late) doesn't overwrite a newer one.
        assert store.write_presets([row("run", '{"old": 1}', 5.0)]) == [row("run", "{}", 10.0)]
        # A delete keeps its row: an older write can't bring the preset back, a later one can.
        store.write_presets([row("run", None, 20.0)])
        assert store.write_presets([row("run", '{"late": 1}', 15.0)]) == [row("run", None, 20.0)]
        assert rows_of(store) == {"run": (None, 20.0)}
        store.write_presets([row("run", '{"again": 1}', 30.0)])
        assert rows_of(store)["run"] == ('{"again": 1}', 30.0)
        # Several in one transaction (a rename): all or none.
        with pytest.raises(StoreError):
            store.write_presets([row("other", "{}", 31.0), row("", "{}", 31.0)])
        assert set(rows_of(store)) == {"run"}


def test_a_scripts_presets_are_apart_from_another_scripts_and_the_arrangements(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        store.write_presets([row("p", "1", 1.0, SCR, "a/Plot"), row("p", "2", 1.0, SCR, "b/Plot"), row("p", "3", 1.0)])
        found = store.read_presets().value or []
        assert sorted((entry["kind"], entry["scope"], entry["record"]) for entry in found) == [
            (ARR, "", "3"), (SCR, "a/Plot", "1"), (SCR, "b/Plot", "2")]


def test_presets_survive_clear_all_purges_making_room_and_a_roots_clear(tmp_path: Path) -> None:
    root = str(tmp_path / "store")
    with CacheStore(root) as store:
        store.write_presets([row("run", "{}", 10.0), row("p", "{}", 10.0, SCR, "a/Plot")])
        store.remove(KINDS)  # Clear all.
        store.purge_records(time.time() + 1, include_failures=True)
        store.purge_datasets(time.time() + 1)
        store.trim(0)  # Make room, as far as it goes.
        store.clear_root(A)  # Settings › Data roots › Clear cached data…
        store.clear_prefs(13.0)
        store.rekey_subtree(f"root://{A}", f"root://{A}x")
    with CacheStore(root) as store:  # A restart.
        assert set(rows_of(store)) == {"run", "p"}


def without_presets(directory: Path, *, layout: int | None = None) -> None:
    """A store as an earlier HeLab made it (no ``presets`` table); ``layout``: as a newer HeLab's."""
    with CacheStore(str(directory)):
        pass
    conn = sqlite3.connect(directory / "records.sqlite", isolation_level=None)
    try:
        conn.execute("DROP TABLE presets")
        if layout is not None:
            conn.execute("UPDATE meta SET value = ? WHERE key = 'layout_version'", (json.dumps(layout),))
    finally:
        conn.close()


def tables(directory: Path) -> set[str]:
    with sqlite3.connect(directory / "records.sqlite") as conn:
        return {str(found[0]) for found in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_an_older_store_gains_the_presets_table_when_opened(tmp_path: Path) -> None:
    directory = tmp_path / "store"
    without_presets(directory)
    assert "presets" not in tables(directory)
    with CacheStore(str(directory)) as store:
        assert "presets" in tables(directory) and rows_of(store) == {}
        store.write_presets([row("run", "{}", 1.0)])
    with CacheStore(str(directory)) as store:
        assert rows_of(store) == {"run": ("{}", 1.0)}


def test_a_read_only_store_without_the_table_reads_as_none_and_is_left_as_it_was(tmp_path: Path) -> None:
    directory = tmp_path / "store"
    without_presets(directory, layout=cache_store.LAYOUT_VERSION + 1)
    with CacheStore(str(directory)) as store:
        assert store.read_only and rows_of(store) == {}
        with pytest.raises(StoreReadOnly):
            store.write_presets([row("run", "{}", 1.0)])
    assert "presets" not in tables(directory)
    # Through the helper's action: a read answers (none), a write fails (named by the error event).
    events: list[Any] = []
    cache_admin({"directory": str(directory)}, "presets", events.append)
    [answered] = [event for event in events if event["kind"] == "presets"]
    assert answered["saved"] == [] and answered["rows"] == []
    with pytest.raises(StoreReadOnly):
        cache_admin({"directory": str(directory)}, "presets", events.append, rows=[row("run", "{}", 1.0)],
                    store=answered["store"])


def test_the_helpers_action_writes_then_reads_every_preset(tmp_path: Path) -> None:
    options = {"directory": str(tmp_path / "store")}
    events: list[Any] = []
    cache_admin(options, "presets", events.append)
    store_id = events[0]["store"]
    events.clear()
    cache_admin(options, "presets", events.append, rows=[row("a", "{}", 5.0), row("b", None, 6.0)], store=store_id)
    [answer] = [event for event in events if event["kind"] == "presets"]
    assert answer["saved"] == [row("a", "{}", 5.0), row("b", None, 6.0)] and answer["store"] == store_id
    assert sorted(answer["rows"], key=lambda entry: entry["name"]) == answer["saved"]
    assert events[-1]["kind"] == "admin_result" and events[-1]["action"] == "presets"


def test_rows_meant_for_another_store_are_never_written(tmp_path: Path) -> None:
    """A write names the store whose names the app read: in another (recreated since), it could
    replace a preset unasked, so the helper only reads that one, and says which it is."""
    options = {"directory": str(tmp_path / "store")}
    with CacheStore(options["directory"]) as store:
        store.write_presets([row("p", '"theirs"', 1.0)])
        store_id = store.store_id
    for named in ("another-store", None):
        events: list[Any] = []
        cache_admin(options, "presets", events.append, rows=[row("p", '"mine"', 5.0)],
                    **({"store": named} if named else {}))
        [answer] = [event for event in events if event["kind"] == "presets"]
        assert answer["saved"] == [] and answer["rows"] == [row("p", '"theirs"', 1.0)] and answer["store"] == store_id


# FolderCache, through real helpers


_sessions: list[IOService] = []


@pytest.fixture
def service() -> Iterator[IOService]:
    """A session's IOService; it and those ``restarted`` makes end with the test."""
    made = IOService()
    _sessions.append(made)
    yield made
    while _sessions:
        _sessions.pop().shutdown()


def settled(qtbot: QtBot, cache: FolderCache) -> None:
    qtbot.waitUntil(lambda: not cache._preset_jobs, timeout=30_000)


def restarted(qtbot: QtBot, service: IOService) -> FolderCache:
    """The same store, read by another HeLab session (a new IOService and FolderCache)."""
    service.shutdown()
    _sessions.append(IOService())
    again = get_folder_cache(_sessions[-1])
    again.read_presets()
    qtbot.waitUntil(lambda: again.presets_read or bool(again.presets_error), timeout=30_000)
    settled(qtbot, again)
    return again


def test_a_saved_preset_is_read_back_after_a_restart(qtbot: QtBot, service: IOService) -> None:
    cache = get_folder_cache(service)
    assert store_options() and cache.presets_note() == "Reading saved presets…"
    # (Before the first read: written once the store's names are known.)
    assert cache.set_presets([(ARR, "", "run", '{"format": 1}'), (SCR, "x/Plot", "p", "{}")]) == PRESETS_WAIT_READ
    assert cache.preset_records(ARR) == {("", "run"): '{"format": 1}'}  # Shown at once.
    assert cache.quit_saves() == [PRESETS_SAVING]  # Quitting waits for the write.
    settled(qtbot, cache)
    assert cache.quit_saves() == [] and cache.presets_read and cache.presets_note() == ""
    again = restarted(qtbot, service)
    assert again.preset_records(ARR) == {("", "run"): '{"format": 1}'}
    assert again.preset_records(SCR, "x/Plot") == {("x/Plot", "p"): "{}"}
    # Deleted here, then read again by a third session: gone.
    again.set_presets([(ARR, "", "run", None)])
    assert again.preset_records(ARR) == {}
    settled(qtbot, again)
    third = restarted(qtbot, again.service)
    assert third.preset_records(ARR) == {} and third.presets[(ARR, "", "run")]["record"] is None


def test_another_helabs_later_choice_wins_and_shows(qtbot: QtBot, service: IOService) -> None:
    cache = get_folder_cache(service)
    with CacheStore(store_options()["directory"]) as store:  # Another HeLab, whose clock is ahead.
        store.write_presets([row("run", '"theirs"', time.time() + 1000)])
    cache.set_presets([(ARR, "", "run", '"mine"')])
    settled(qtbot, cache)
    assert cache.preset_records(ARR) == {("", "run"): '"theirs"'} and not cache.presets_unsaved


def test_an_older_write_from_another_helab_cant_bring_a_deleted_preset_back(qtbot: QtBot,
                                                                            service: IOService) -> None:
    cache = get_folder_cache(service)
    cache.set_presets([(ARR, "", "run", "{}")])
    settled(qtbot, cache)
    cache.set_presets([(ARR, "", "run", None)])
    settled(qtbot, cache)
    deleted_at = float(cache.presets[(ARR, "", "run")]["set_at"])
    with CacheStore(store_options()["directory"]) as store:  # Another HeLab's write, made before the delete.
        store.write_presets([row("run", '"late"', deleted_at - 1)])
    cache.read_presets()
    settled(qtbot, cache)
    assert cache.preset_records(ARR) == {}


def test_a_refused_cache_folder_keeps_presets_in_ram_until_the_store_is_there(
        qtbot: QtBot, service: IOService, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = get_folder_cache(service)
    refused = "The saved cache folder /net/share is a network folder…"
    monkeypatch.setattr("helab.utils.folder_cache.cache_dir_refused", lambda: refused)
    why = cache.set_presets([(ARR, "", "run", "{}")])
    assert why == "the saved cache folder isn't used this session"
    assert cache.presets_note() == "RAM only: the saved cache folder isn't used this session"
    assert not cache._preset_jobs and cache.quit_saves() == []  # Nothing to wait for.
    assert cache.preset_unsaved(ARR, "", "run") == why
    cache.read_presets()  # Neither read nor written meanwhile.
    assert not cache._preset_jobs
    # The cache folder is usable again (moved with Change…): the next read saves it.
    monkeypatch.setattr("helab.utils.folder_cache.cache_dir_refused", lambda: "")
    cache.read_presets()
    settled(qtbot, cache)
    assert cache.preset_unsaved(ARR, "", "run") == "" and not cache.presets_unsaved
    assert restarted(qtbot, service).preset_records(ARR) == {("", "run"): "{}"}


def test_with_the_disk_cache_off_presets_last_the_session(service: IOService,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    cache = get_folder_cache(service)
    monkeypatch.setattr("helab.utils.folder_cache.store_options", lambda: {})
    assert cache.set_presets([(ARR, "", "run", "{}")]) == "the disk cache is off for this session"
    assert cache.preset_records(ARR) == {("", "run"): "{}"} and not cache._preset_jobs


def test_a_store_that_cant_be_read_is_named_never_none(qtbot: QtBot, service: IOService,
                                                       monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache = get_folder_cache(service)
    cache.set_presets([(ARR, "", "kept", "{}")])
    settled(qtbot, cache)
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "records.sqlite").write_bytes(b"not a database" * 100)
    monkeypatch.setattr("helab.utils.folder_cache.store_options", lambda: {"directory": str(broken)})
    monkeypatch.setattr(cache.service, "cache_options", lambda: {"directory": str(broken)})  # (As a job starts.)
    cache.set_presets([(ARR, "", "new", "{}")])
    settled(qtbot, cache)
    assert cache.presets_note().startswith("⚠ Saved presets can't be read: ")
    # What was known stays listed; the change is kept in RAM and said not saved.
    assert set(cache.preset_records(ARR)) == {("", "kept"), ("", "new")}
    assert cache.preset_unsaved(ARR, "", "new").startswith("couldn't be saved (")
    assert cache.quit_saves() == []
    # The store readable again: the next read saves it.
    monkeypatch.undo()
    cache.read_presets()
    settled(qtbot, cache)
    assert cache.presets_note() == "" and not cache.presets_unsaved


def test_clear_all_and_reset_all_settings_leave_presets(qtbot: QtBot, service: IOService,
                                                        tmp_path: Path) -> None:
    from helab.views.SettingsDialog import SettingsDialog
    cache = get_folder_cache(service)
    cache.set_presets([(ARR, "", "run", "{}")])
    settled(qtbot, cache)
    owner = cache.cache_admin("clear", kinds=list(KINDS))
    assert owner
    qtbot.waitUntil(lambda: owner not in cache._admin, timeout=30_000)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("open_plots", "{}")
    dialog = SettingsDialog(settings=settings, cache=cache)
    qtbot.addWidget(dialog)
    dialog.cache_tab.confirm = lambda title, text, verb: "presets are kept" in text
    dialog.reset_settings()
    assert not settings.contains("open_plots")  # The plots to reopen go; presets stay.
    dialog.close()
    assert restarted(qtbot, service).preset_records(ARR) == {("", "run"): "{}"}


def test_the_quit_window_names_presets_being_saved(qtbot: QtBot, service: IOService) -> None:
    from helab.views.QuitSaveDialog import QuitSaveDialog
    cache = get_folder_cache(service)
    cache.set_presets([(ARR, "", "run", "{}")])
    dialog = QuitSaveDialog(cache)
    qtbot.addWidget(dialog)
    results: list[int] = []
    dialog.finished.connect(results.append)
    dialog.open()
    item = dialog.folders.item(0)
    assert dialog.label.text() == "Saving presets to the disk cache before HeLab quits:"
    assert dialog.folders.count() == 1 and item is not None and re.sub(r" · \d+:\d\d$", "", item.text()) == "Presets — writing"
    qtbot.waitUntil(lambda: bool(results), timeout=30_000)  # Saved: it closes by itself.
    assert not dialog.skipped and cache.quit_saves() == []


# Review round 7 (Flint, 5923fe7..9a338fd)


def stored_in(name: str) -> tuple[str | None, float] | None:
    with CacheStore(store_options()["directory"]) as store:
        return rows_of(store).get(name)


def test_a_save_before_the_first_read_never_replaces_a_stored_preset_unasked(qtbot: QtBot,
                                                                            service: IOService) -> None:
    """(1, P1) The store holds "p" (another session's); this session saves "p" and "q" before its
    first read answers: nothing is written until the names are known, then "p" stays the stored
    one (said once), and "q" is written."""
    with CacheStore(store_options()["directory"]) as store:
        store.write_presets([row("p", '"theirs"', 1.0)])
    cache = get_folder_cache(service)
    why = cache.set_presets([(ARR, "", "p", '"mine"'), (ARR, "", "q", '"new"')])
    assert why == PRESETS_WAIT_READ and cache.preset_records(ARR)[("", "p")] == '"mine"'  # Shown at once.
    assert all(not keys for keys in cache._preset_jobs.values())  # Only a read: no write yet.
    assert cache.quit_saves() == [PRESETS_SAVING]  # Quitting waits for it all the same.
    settled(qtbot, cache)
    assert cache.preset_records(ARR) == {("", "p"): '"theirs"', ("", "q"): '"new"'}
    assert cache.presets_conflicts == {(ARR, "", "p"): PRESET_FOUND} and not cache.presets_unsaved
    assert stored_in("p") == ('"theirs"', 1.0) and stored_in("q") is not None and cache.quit_saves() == []
    # Saved again, now that the names are known: the user's word (the UI asks first), written.
    cache.set_presets([(ARR, "", "p", '"mine"')])
    settled(qtbot, cache)
    assert stored_in("p") == ('"mine"', cache.presets[(ARR, "", "p")]["set_at"])


def test_with_the_names_unreadable_a_change_waits_and_is_checked_once_they_are_read(
        qtbot: QtBot, service: IOService, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with CacheStore(store_options()["directory"]) as store:
        store.write_presets([row("p", '"theirs"', 1.0)])
    cache = get_folder_cache(service)
    good = store_options()
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "records.sqlite").write_bytes(b"not a database" * 100)
    monkeypatch.setattr(cache.service, "cache_options", lambda: {"directory": str(broken)})
    cache.set_presets([(ARR, "", "p", '"mine"')])
    settled(qtbot, cache)
    assert not cache.presets_read and cache.presets_note().startswith("⚠ Saved presets can't be read")
    assert cache.preset_unsaved(ARR, "", "p").startswith("not saved: the saved presets can't be read (")
    assert cache.quit_saves() == []  # Nothing will write it now: quitting doesn't wait.
    monkeypatch.setattr(cache.service, "cache_options", lambda: good)
    cache.read_presets()
    settled(qtbot, cache)
    assert cache.preset_records(ARR) == {("", "p"): '"theirs"'} and (ARR, "", "p") in cache.presets_conflicts
    assert stored_in("p") == ('"theirs"', 1.0)


def frozen() -> tuple[IOService, FolderCache]:
    """A cache whose helpers never run: the test sends their events, in the order it chooses."""
    made = IOService()
    made.timer.stop()
    made._dispatch = lambda: None  # type: ignore[method-assign]
    _sessions.append(made)
    return made, FolderCache(made)


def admin_job(service: IOService, rows: int) -> Any:
    """The newest presets job writing ``rows`` rows (0: a read)."""
    return next(request for request in reversed(service.pending) if request.operation == "cache_admin"
                and request.payload["action"] == "presets" and len(request.payload["params"]["rows"]) == rows)


def answer(service: IOService, request: Any, *events: dict[str, Any]) -> None:
    for event in events:
        service.resultReady.emit(request, event)
    service.pending.remove(request)
    folder_answers(service, *(str(event["store"]) for event in events if event.get("store")))


def emit(service: IOService, request: Any, event: dict[str, Any]) -> None:
    """One event of ``request``'s helper (its job goes on), then the cache folder answers a probe."""
    service.resultReady.emit(request, event)
    folder_answers(service, *([str(event["store"])] if event.get("store") else []))


# The stores each session named, by its IOService (weakly: an id can be reused after it is gone).
_made: "weakref.WeakKeyDictionary[IOService, set[str]]" = weakref.WeakKeyDictionary()


def folder_answers(service: IOService, *stores: str) -> None:
    """The cache folder answers an identity probe (``FolderCache.store_answer``): it holds the
    store made last of those this session has named ("B" after "A", "T" after "S": these tests'
    stores are made in letter order)."""
    named = _made.setdefault(service, set())
    named.update(stores)
    for _ in range(10):
        probe = next((request for request in service.pending if request.operation == "cache_admin"
                      and request.payload["action"] == "identity"), None)
        if probe is None or not named:
            return
        for event in ({"kind": "admin_result", "action": "identity", "store": max(named)}, {"kind": "done"}):
            service.resultReady.emit(probe, event)
        service.pending.remove(probe)


def test_an_older_snapshot_landing_after_a_write_removes_nothing(service: IOService) -> None:
    """(2, P2) A read asked after a write, whose snapshot was taken before the write committed
    (two local-lane helpers), lands after it: the preset stays. Rows never leave a store."""
    jobs, cache = frozen()
    cache.read_presets()
    answer(jobs, admin_job(jobs, 0), {"kind": "presets", "saved": [], "rows": [], "store": "S"}, {"kind": "done"})
    assert cache.presets_read
    cache.set_presets([(ARR, "", "p", "{}")])
    write = admin_job(jobs, 1)
    cache.read_presets()
    late = admin_job(jobs, 0)
    saved = row("p", "{}", cache.presets[(ARR, "", "p")]["set_at"])
    answer(jobs, write, {"kind": "presets", "saved": [saved], "rows": [saved], "store": "S"}, {"kind": "done"})
    answer(jobs, late, {"kind": "presets", "saved": [], "rows": [], "store": "S"}, {"kind": "done"})
    assert cache.preset_records(ARR) == {("", "p"): "{}"}
    # Another store (recreated by hand): what the last one said goes, this session's unsaved stays.
    cache.set_presets([(ARR, "", "mine", "{}")])
    cache.read_presets()
    answer(jobs, admin_job(jobs, 0), {"kind": "presets", "saved": [], "rows": [], "store": "T"}, {"kind": "done"})
    assert set(cache.preset_records(ARR)) == {("", "mine")}


def empty_lines(inspector: Any) -> list[str]:
    """What the inspector's two groups say when they list nothing."""
    lines = []
    for index in range(inspector.tree.topLevelItemCount()):
        child = inspector.tree.topLevelItem(index).child(0)
        lines.append(child.text(0) if child is not None else "")
    return lines


def test_names_are_claimed_empty_only_after_a_successful_read(qtbot: QtBot) -> None:
    """(3, P2) Before the store answers, or when it can't be read, no list says "none saved"."""
    from helab.views.PresetsInspector import PresetsInspector, presets_summary
    jobs, cache = frozen()
    inspector = PresetsInspector(cache)
    qtbot.addWidget(inspector)
    assert empty_lines(inspector) == ["(none known yet)"] * 2
    assert presets_summary(cache) == "0 script presets, 0 arrangements known · Reading saved presets…"
    answer(jobs, admin_job(jobs, 0), {"kind": "error", "message": "disk I/O error"})
    assert empty_lines(inspector) == ["(none known yet)"] * 2
    assert presets_summary(cache).endswith(" known · ⚠ Saved presets can't be read: disk I/O error")
    cache.read_presets()
    answer(jobs, admin_job(jobs, 0), {"kind": "presets", "saved": [], "rows": [], "store": "S"}, {"kind": "done"})
    assert empty_lines(inspector) == ["(none saved)"] * 2
    assert presets_summary(cache) == "0 script presets, 0 arrangements"


# Review round 8 (Flint, 9a338fd..393d2af): a store recreated while HeLab runs


def test_a_late_answer_from_the_retired_store_acknowledges_nothing(service: IOService) -> None:
    """(1) A write to store A is held; A is recreated as B, whose read answers first; A's answer
    then lands: it neither marks the change saved nor makes A current again. The change is
    written again, to B."""
    jobs, cache = frozen()
    cache.read_presets()
    answer(jobs, admin_job(jobs, 0), {"kind": "presets", "saved": [], "rows": [], "store": "A"}, {"kind": "done"})
    cache.set_presets([(ARR, "", "p", "{}")])
    to_a = admin_job(jobs, 1)
    cache.read_presets()
    answer(jobs, admin_job(jobs, 0), {"kind": "presets", "saved": [], "rows": [], "store": "B"}, {"kind": "done"})
    saved = row("p", "{}", cache.presets[(ARR, "", "p")]["set_at"])
    answer(jobs, to_a, {"kind": "presets", "saved": [saved], "rows": [saved], "store": "A"}, {"kind": "done"})
    assert cache._store == "B" and cache.preset_unsaved(ARR, "", "p") == ""  # Being written…
    assert cache.quit_saves() == [PRESETS_SAVING]
    to_b = admin_job(jobs, 1)  # …again, to B.
    assert to_b is not to_a and to_b.payload["params"]["rows"] == [saved]
    answer(jobs, to_b, {"kind": "presets", "saved": [saved], "rows": [saved], "store": "B"}, {"kind": "done"})
    assert not cache.presets_unsaved and cache.quit_saves() == [] and cache.preset_records(ARR) == {("", "p"): "{}"}


def test_a_recreated_stores_rows_replace_the_old_stores_whatever_their_times(service: IOService) -> None:
    """(2) A said p="old" (set_at 100); the recreated B says p="replacement" (set_at 10): B's shows.
    This session's unsaved change stays, and is written to B."""
    jobs, cache = frozen()
    cache.read_presets()
    answer(jobs, admin_job(jobs, 0), {"kind": "presets", "saved": [], "store": "A",
                                      "rows": [row("p", '"old"', 100.0), row("gone", '"a"', 100.0)]},
           {"kind": "done"})
    cache.set_presets([(ARR, "", "mine", "{}")])
    mine = admin_job(jobs, 1)
    cache.read_presets()
    answer(jobs, admin_job(jobs, 0), {"kind": "presets", "saved": [], "store": "B",
                                      "rows": [row("p", '"replacement"', 10.0)]}, {"kind": "done"})
    assert cache.preset_records(ARR) == {("", "p"): '"replacement"', ("", "mine"): "{}"}
    answer(jobs, mine, {"kind": "presets", "saved": [], "rows": [], "store": "A"}, {"kind": "done"})
    rewrite = admin_job(jobs, 1)
    assert rewrite is not mine and [entry["name"] for entry in rewrite.payload["params"]["rows"]] == ["mine"]


def test_a_store_recreated_at_the_same_folder_is_read_as_itself(qtbot: QtBot, service: IOService) -> None:
    """Through real helpers: the store deleted by hand and made again at the same path, holding an
    older "p" than the one this session saved: the new store's shows."""
    import shutil
    cache = get_folder_cache(service)
    cache.read_presets()
    settled(qtbot, cache)
    cache.set_presets([(ARR, "", "p", '"old"')])
    settled(qtbot, cache)
    qtbot.waitUntil(lambda: store_free(service), timeout=30_000)  # (Windows deletes no open file.)
    directory = store_options()["directory"]
    shutil.rmtree(directory)
    with CacheStore(directory) as store:
        store.write_presets([row("p", '"replacement"', 10.0)])
    cache.read_presets()
    settled(qtbot, cache)
    assert cache.preset_records(ARR) == {("", "p"): '"replacement"'} and not cache.presets_unsaved


# Review round 9 (Flint, 393d2af..3ba07eb): one rule, whatever order helpers answer in. A store
# change is a fresh start (its names unknown until it sends its rows; unsaved changes kept), a
# change is settled only by the current store holding it (or a later choice), and a change left
# unsaved and unwritten when a job ends is written again to the current store.


class Stores:
    """What frozen helpers' stores, by id, would answer: a job's rows are written only to the
    store it names (as the helper's action does), the newest choice winning each."""

    def __init__(self) -> None:
        self.held: dict[str, dict[str, dict[str, Any]]] = {}

    def answer(self, store: str, request: Any) -> dict[str, Any]:
        held = self.held.setdefault(store, {})
        params = request.payload["params"]
        saved = []
        for entry in params["rows"] if params.get("store") == store else ():
            found = held.get(entry["name"])
            if found is None or found["set_at"] <= entry["set_at"]:
                held[entry["name"]] = dict(entry)
            saved.append(dict(held[entry["name"]]))
        return {"kind": "presets", "saved": saved, "rows": [dict(entry) for entry in held.values()], "store": store}


def preset_jobs(service: IOService) -> list[Any]:
    return [request for request in service.pending if request.operation == "cache_admin"
            and request.payload["action"] == "presets"]


def drain(service: IOService, stores: Stores, store: str) -> None:
    """Answer every presets job still waiting, and those they start, from ``store``."""
    for _ in range(20):
        waiting = preset_jobs(service)
        if not waiting:
            return
        answer(service, waiting[0], stores.answer(store, waiting[0]), {"kind": "done"})
    raise AssertionError("preset jobs keep starting")


def recreated_with_two_writes(stores: Stores) -> tuple[IOService, FolderCache, list[Any]]:
    """A is read; p="first" is written to A, held; the store is recreated as B, which a read
    finds (p goes to B too); then p="second" is saved to B. The three writes, not yet answered."""
    jobs, cache = frozen()
    cache.read_presets()
    first = admin_job(jobs, 0)
    answer(jobs, first, stores.answer("A", first), {"kind": "done"})
    cache.set_presets([(ARR, "", "p", '"first"')])
    to_a = admin_job(jobs, 1)
    assert to_a.payload["params"]["store"] == "A"
    cache.read_presets()
    read_b = admin_job(jobs, 0)
    answer(jobs, read_b, stores.answer("B", read_b), {"kind": "done"})
    first_to_b = admin_job(jobs, 1)
    assert first_to_b is not to_a and first_to_b.payload["params"]["store"] == "B"
    cache.set_presets([(ARR, "", "p", '"second"')])
    second_to_b = admin_job(jobs, 1)
    assert second_to_b.payload["params"]["rows"][0]["record"] == '"second"'
    return jobs, cache, [to_a, first_to_b, second_to_b]


def assert_settled(service: IOService, cache: FolderCache, stores: Stores) -> None:
    assert not cache._preset_jobs and not preset_jobs(service)
    assert not cache.presets_unsaved and cache.quit_saves() == [] and cache._store == "B"
    assert cache.preset_records(ARR) == {("", "p"): '"second"'} and stores.held["B"]["p"]["record"] == '"second"'


def test_interleaved_answers_from_the_retired_and_the_current_store_leave_nothing_waiting(
        service: IOService) -> None:
    """(1) Flint's order: A's presets event, then B's, then each job's end. Neither defers to the
    other: B's answer settles p, A's changes nothing, and quitting waits for nothing."""
    stores = Stores()
    jobs, cache, (to_a, first_to_b, second_to_b) = recreated_with_two_writes(stores)
    emit(jobs, to_a, stores.answer("A", to_a))
    for request in (first_to_b, second_to_b):
        emit(jobs, request, stores.answer("B", request))
    assert not cache.presets_unsaved  # Settled by B's answers alone.
    for request in (to_a, first_to_b, second_to_b):
        answer(jobs, request, {"kind": "admin_result", "action": "presets"}, {"kind": "done"})
    assert_settled(jobs, cache, stores)


def interleavings(*sequences: tuple[Any, ...]) -> Iterator[list[Any]]:
    """Every order of these sequences' items that keeps each sequence's own order."""
    if not any(sequences):
        yield []
        return
    for index, sequence in enumerate(sequences):
        if sequence:
            rest = (*sequences[:index], sequence[1:], *sequences[index + 1:])
            for tail in interleavings(*rest):
                yield [sequence[0], *tail]


def test_every_order_of_the_three_writes_answers_settles_every_change(service: IOService) -> None:
    """Each job's presets event comes before its end; across jobs, any order (90 of them). The
    retired store's answer may come first, last or between B's; B may commit "second" before
    "first" (then "first" saves nothing: the later choice stays)."""
    count = 0
    for order in interleavings(*(((job, "presets"), (job, "done")) for job in range(3))):
        stores = Stores()
        jobs, cache, writes = recreated_with_two_writes(stores)
        for job, step in order:
            request = writes[job]
            if step == "presets":
                emit(jobs, request, stores.answer("A" if job == 0 else "B", request))
            else:
                answer(jobs, request, {"kind": "done"})
            # Never shown as being saved without a job in flight to settle it.
            assert not cache.presets_saving() or cache._preset_jobs, order
        drain(jobs, stores, "B")
        assert_settled(jobs, cache, stores)
        count += 1
    assert count == 90


def test_a_retired_stores_answer_after_its_change_was_superseded_writes_nothing_again(service: IOService) -> None:
    """A write to A held while B is found, and p changed again meanwhile: when A's job ends, p's
    change in RAM is B's job's, not A's, so nothing is written again."""
    stores = Stores()
    jobs, cache, (to_a, first_to_b, second_to_b) = recreated_with_two_writes(stores)
    for request in (first_to_b, second_to_b):
        answer(jobs, request, stores.answer("B", request), {"kind": "done"})
    answer(jobs, to_a, stores.answer("A", to_a), {"kind": "done"})
    assert not preset_jobs(jobs)
    assert_settled(jobs, cache, stores)


def test_a_write_meant_for_the_old_store_that_finds_a_new_one_writes_nothing_there(service: IOService) -> None:
    """The write's helper opens B (recreated since), which holds p: it writes nothing there, and
    B's names are a fresh start: p, changed before they were known, keeps B's (said once); q is
    written to B."""
    stores = Stores()
    stores.held["B"] = {"p": row("p", '"theirs"', 1.0)}
    jobs, cache = frozen()
    cache.read_presets()
    first = admin_job(jobs, 0)
    answer(jobs, first, stores.answer("A", first), {"kind": "done"})
    cache.set_presets([(ARR, "", "p", '"mine"'), (ARR, "", "q", '"new"')])
    to_a = admin_job(jobs, 2)
    answer(jobs, to_a, stores.answer("B", to_a), {"kind": "done"})
    assert stores.held["B"]["p"]["record"] == '"theirs"'
    assert cache.presets_conflicts == {(ARR, "", "p"): PRESET_FOUND}
    drain(jobs, stores, "B")
    assert cache.preset_records(ARR) == {("", "p"): '"theirs"', ("", "q"): '"new"'} and not cache.presets_unsaved
    assert stores.held["B"]["q"]["record"] == '"new"' and stores.held["B"]["p"]["record"] == '"theirs"'


def test_a_replacement_stores_failed_read_leaves_its_names_unknown(qtbot: QtBot, service: IOService) -> None:
    """(2) A was read; the store recreated as B answers with an error: nothing is known about B, so
    no list says "none saved", and a change waits for B's names instead of being written."""
    from helab.views.PresetsInspector import PresetsInspector
    stores = Stores()
    stores.held["A"] = {"old": row("old", "{}", 100.0)}
    jobs, cache = frozen()
    cache.read_presets()
    first = admin_job(jobs, 0)
    answer(jobs, first, stores.answer("A", first), {"kind": "done"})
    assert cache.presets_known() and set(cache.preset_records(ARR)) == {("", "old")}
    cache.set_presets([(ARR, "", "q", '"mine"')])
    to_a = admin_job(jobs, 1)
    cache.read_presets()
    read_b = admin_job(jobs, 0)
    answer(jobs, read_b, {"kind": "presets", "saved": [], "error": "no such column: kind", "store": "B"},
           {"kind": "done"})
    assert not cache.presets_read and not cache.presets_known()
    assert cache.presets_note() == "⚠ Saved presets can't be read: no such column: kind"
    assert cache.preset_records(ARR) == {("", "q"): '"mine"'}  # A's "old" isn't B's.
    # q is still A's job's, being saved: decided only once no preset job is left.
    assert cache.preset_unsaved(ARR, "", "q") == "" and cache.quit_saves() == [PRESETS_SAVING]
    inspector = PresetsInspector(cache)
    qtbot.addWidget(inspector)
    assert empty_lines(inspector)[0] == "(none known yet)"
    unreadable = {"kind": "presets", "saved": [], "error": "no such column: kind", "store": "B"}
    answer(jobs, admin_job(jobs, 0), unreadable, {"kind": "done"})  # The read the inspector asked for…
    assert empty_lines(inspector)[0] == "(none known yet)"
    # …which q waited for (B's names): still undecided while A's job runs.
    assert cache.preset_unsaved(ARR, "", "q") == PRESETS_WAIT_READ and cache.quit_saves() == [PRESETS_SAVING]
    answer(jobs, to_a, stores.answer("A", to_a), {"kind": "done"})  # Retired: changes nothing. The last job:
    assert cache.preset_unsaved(ARR, "", "q") == "not saved: the saved presets can't be read (no such column: kind)"
    assert cache.quit_saves() == [] and not preset_jobs(jobs)  # Nothing will write it now.
    # A change now waits for B's names: only a read is asked.
    assert cache.set_presets([(ARR, "", "r", '"mine"')]) == PRESETS_WAIT_READ
    assert [len(request.payload["params"]["rows"]) for request in preset_jobs(jobs)] == [0]
    assert cache.quit_saves() == [PRESETS_SAVING]
    stores.held["B"] = {"r": row("r", '"theirs"', 1.0)}  # B readable now, holding r.
    drain(jobs, stores, "B")
    assert cache.preset_records(ARR) == {("", "q"): '"mine"', ("", "r"): '"theirs"'}
    assert cache.presets_conflicts == {(ARR, "", "r"): PRESET_FOUND}
    assert stores.held["B"]["q"]["record"] == '"mine"' and stores.held["B"]["r"]["record"] == '"theirs"'
    assert not cache.presets_unsaved and cache.quit_saves() == [] and cache.presets_known()


# Review round 10 (Flint, 3ba07eb..4fc315b): a job's continuation is queued before its end is told


@pytest.mark.parametrize("failure", ["error answer", "job error"])
def test_quitting_waits_for_a_read_asked_again_after_the_first_one_fails(qtbot: QtBot, service: IOService,
                                                                         failure: str) -> None:
    """p is saved before the store's names are known, and a read is asked again while the first
    runs; HeLab starts quitting; the first read fails (its answer an error, or the job itself).
    The real quit window never sees nothing to wait for: the read asked again is queued before
    anyone hears of the failure, p waits for it, and is saved before the window closes."""
    from helab.views.QuitSaveDialog import QuitSaveDialog
    stores = Stores()
    jobs, cache = frozen()
    assert cache.set_presets([(ARR, "", "p", '"mine"')]) == PRESETS_WAIT_READ
    first = admin_job(jobs, 0)
    cache.read_presets()  # (The Presets menu opened, say.)
    assert cache._presets_again and preset_jobs(jobs) == [first]
    cache.cancel_for_quit()
    dialog = QuitSaveDialog(cache)
    qtbot.addWidget(dialog)
    results: list[int] = []
    dialog.finished.connect(results.append)
    dialog.open()
    told: list[list[str]] = []
    cache.quitSavesChanged.connect(lambda: told.append(cache.quit_saves()))
    if failure == "error answer":
        answer(jobs, first, {"kind": "presets", "saved": [], "error": "disk I/O error", "store": "A"},
               {"kind": "done"})
    else:
        answer(jobs, first, {"kind": "error", "message": "disk I/O error"})
    assert told and all(saves == [PRESETS_SAVING] for saves in told)
    assert results == [] and cache.preset_unsaved(ARR, "", "p") == PRESETS_WAIT_READ
    retry = admin_job(jobs, 0)
    assert retry is not first
    drain(jobs, stores, "A")  # The retry reads A; p is written to it.
    qtbot.waitUntil(lambda: bool(results), timeout=5_000)
    assert not dialog.skipped and stores.held["A"]["p"]["record"] == '"mine"' and not cache.presets_unsaved


# Review round 11 (Flint, 4fc315b..3bb153a): a change still owed is decided in one place, once no
# preset job is in flight and no read is asked for; until then quitting waits for it.

UNREADABLE_B = {"kind": "presets", "saved": [], "error": "no such column: kind", "store": "B"}


def owed_to_b(stores: Stores) -> tuple[IOService, FolderCache, Any, Any]:
    """A was read; p's write to A (w1) is in flight when the store, recreated as B, fails a read;
    B's read is asked again (r2) and is running. p is owed to B. (w1, r2), not yet answered."""
    jobs, cache = frozen()
    cache.read_presets()
    first = admin_job(jobs, 0)
    answer(jobs, first, stores.answer("A", first), {"kind": "done"})
    cache.set_presets([(ARR, "", "p", '"mine"')])
    w1 = admin_job(jobs, 1)
    cache.read_presets()
    answer(jobs, admin_job(jobs, 0), UNREADABLE_B, {"kind": "done"})
    assert cache.preset_unsaved(ARR, "", "p") == ""  # Still w1's: undecided.
    cache.read_presets()
    r2 = admin_job(jobs, 0)
    assert cache.preset_unsaved(ARR, "", "p") == PRESETS_WAIT_READ and cache.quit_saves() == [PRESETS_SAVING]
    return jobs, cache, w1, r2


def owed(cache: FolderCache) -> bool:
    return any(why in ("", PRESETS_WAIT_READ) for why in cache.presets_unsaved.values())


def check_quit(cache: FolderCache, step: Any = None) -> None:
    """At every step: quitting waits for presets exactly while a change is owed and a preset job
    or a requested read remains; and no change is owed without one (nothing would settle it)."""
    work = bool(cache._preset_jobs) or cache._presets_again
    assert (cache.quit_saves() == [PRESETS_SAVING]) == (owed(cache) and work), step
    assert cache.quit_saves() in ([], [PRESETS_SAVING]), step
    assert work or not owed(cache), step


@pytest.mark.parametrize("w1_ends", ["helper error", "B read error"])
def test_another_jobs_failure_never_tells_quit_nothing_is_left_while_bs_read_runs(
        qtbot: QtBot, service: IOService, w1_ends: str) -> None:
    """Flint's two orders, through the real quit window: w1 ends with a helper error, or answers
    with B's read error, while r2 (which would save p) runs. p stays owed, the window waits, and
    r2's answer saves it."""
    from helab.views.QuitSaveDialog import QuitSaveDialog
    stores = Stores()
    jobs, cache, w1, r2 = owed_to_b(stores)
    cache.cancel_for_quit()
    dialog = QuitSaveDialog(cache)
    qtbot.addWidget(dialog)
    results: list[int] = []
    dialog.finished.connect(results.append)
    dialog.open()
    told: list[list[str]] = []
    cache.quitSavesChanged.connect(lambda: told.append(cache.quit_saves()))
    if w1_ends == "helper error":
        answer(jobs, w1, {"kind": "error", "message": "helper exited"})
    else:
        answer(jobs, w1, UNREADABLE_B, {"kind": "done"})
    assert told and all(saves == [PRESETS_SAVING] for saves in told) and results == []
    assert cache.preset_unsaved(ARR, "", "p") == PRESETS_WAIT_READ
    answer(jobs, r2, stores.answer("B", r2), {"kind": "done"})  # B readable now: p is written to it.
    drain(jobs, stores, "B")
    qtbot.waitUntil(lambda: bool(results), timeout=5_000)
    assert not dialog.skipped and stores.held["B"]["p"]["record"] == '"mine"' and not cache.presets_unsaved


W1_ENDS: dict[str, list[str | dict[str, Any]]] = {"helper error": [{"kind": "error", "message": "helper exited"}],
           "B read error": [UNREADABLE_B, {"kind": "done"}],
           "A's answer (retired)": ["A", {"kind": "done"}],
           "B's rows": ["B", {"kind": "done"}]}
R2_ENDS: dict[str, list[str | dict[str, Any]]] = {"B's rows": ["B", {"kind": "done"}],
           "B read error": [UNREADABLE_B, {"kind": "done"}],
           "helper error": [{"kind": "error", "message": "helper exited"}]}


def test_quit_waits_exactly_while_work_that_would_save_a_change_remains(service: IOService) -> None:
    """Every way w1 and r2 can end, in every order of their events: at each step quitting waits for
    presets exactly while p is owed and a preset job or requested read remains, and p is never
    owed with neither left. In the end p is saved to B if any answer read B, else said not saved."""
    count = 0
    for w1_name, w1_events in W1_ENDS.items():
        for r2_name, r2_events in R2_ENDS.items():
            steps = (tuple(("w1", event) for event in w1_events), tuple(("r2", event) for event in r2_events))
            for order in interleavings(*steps):
                stores = Stores()
                jobs, cache, w1, r2 = owed_to_b(stores)
                case = (w1_name, r2_name, [(job, event if isinstance(event, str) else event["kind"])
                                           for job, event in order])
                for job, event in order:
                    request = w1 if job == "w1" else r2
                    if isinstance(event, str):
                        event = stores.answer(event, request)
                    emit(jobs, request, event)
                    if event["kind"] in ("done", "error"):
                        jobs.pending.remove(request)
                    check_quit(cache, case)
                for _ in range(10):  # Writes those answers started, answered by B (readable).
                    waiting = preset_jobs(jobs)
                    if not waiting:
                        break
                    answer(jobs, waiting[0], stores.answer("B", waiting[0]), {"kind": "done"})
                    check_quit(cache, case)
                assert not cache._preset_jobs and not cache._presets_again and cache.quit_saves() == [], case
                if "B's rows" in (w1_name, r2_name):
                    assert stores.held["B"]["p"]["record"] == '"mine"' and not cache.presets_unsaved, case
                else:
                    why = cache.preset_unsaved(ARR, "", "p")
                    assert why.startswith(("not saved: ", "couldn't be saved (")), case
                count += 1
    assert count == 53
