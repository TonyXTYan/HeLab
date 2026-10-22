"""Presets in the disk cache store (helab/utils/cache_store.py's ``presets`` table, the
``cache_admin`` "presets" action, FolderCache's RAM copy): written only by helpers, the newest
choice winning each preset, a delete kept so an older write can't bring it back, added to older
stores, read as none from a read-only one without it; RAM only while the cache folder is refused
(saved once it's there); a store that can't be read named, never "no presets"; untouched by Clear
all and Reset all settings; ``quit_saves`` waits for their writes."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterator

import pytest
from PyQt6.QtCore import QSettings
from pytestqt.qtbot import QtBot

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
        cache_admin({"directory": str(directory)}, "presets", events.append, rows=[row("run", "{}", 1.0)])


def test_the_helpers_action_writes_then_reads_every_preset(tmp_path: Path) -> None:
    options = {"directory": str(tmp_path / "store")}
    events: list[Any] = []
    cache_admin(options, "presets", events.append, rows=[row("a", "{}", 5.0), row("b", None, 6.0)])
    [answer] = [event for event in events if event["kind"] == "presets"]
    assert answer["saved"] == [row("a", "{}", 5.0), row("b", None, 6.0)]
    assert sorted(answer["rows"], key=lambda entry: entry["name"]) == answer["saved"]
    assert events[-1]["kind"] == "admin_result" and events[-1]["action"] == "presets"


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
    assert dialog.folders.count() == 1 and item is not None and item.text() == "Presets — saving"
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
