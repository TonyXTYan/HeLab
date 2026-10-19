"""Live (L1, L2): a tab watches its selected folder for new shots, saves them every N, and on stop.

Helpers run in-process: each queued request gets the real helper's events (``replay``).
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import time
from types import SimpleNamespace
from typing import Any, Iterator

import numpy as np
import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from helab import io_helper
from helab.io_helper import list_folder, live_check, load, read_cached
from helab.utils.constants import (
    DEFAULT_LIVE_AUTOSAVE, DEFAULT_LIVE_INTERVAL, LIVE_AUTOSAVE_SETTING, LIVE_INTERVAL_SETTING, read_live_autosave,
    read_live_interval,
)
from helab.utils.folder_cache import FolderCache, store_options
from helab.utils.io_service import FOREGROUND, IORequest, IOService
from helab.views.FolderExplorer import FolderExplorer, LiveSession
from helab.views.HelabMainWindow import HelabMainWindow
from helab.views.QuitSaveDialog import QuitSaveDialog


def write_shot(folder: Path, shot: int, *, age: float = 60.0) -> None:
    file = folder / f"d_txy_forc{shot}.txt"
    file.write_text(f"{shot},2,3\n{shot},4,5\n")
    when = time.time() - age
    os.utime(file, (when, when))


def age_folder(folder: Path, seconds: float) -> None:
    """A folder mtime this old is safe for the next check to compare (not within RACY_SECONDS)."""
    when = time.time() - seconds
    os.utime(folder, (when, when))


def producer(cache: FolderCache, path: str, operation: str = "load") -> IORequest:
    job = cache.jobs[(operation, path)]
    return next(request for request in cache.service.pending if request.owner == job.owner)


def replay(cache: FolderCache, path: str, tmp_path: Path, operation: str = "load") -> list[dict[str, Any]]:
    """Run the real helper for the queued request in-process and deliver its events, as the
    service's reader thread would (shots' artifacts become arrays)."""
    request = producer(cache, path, operation)
    payload = request.payload
    output = tmp_path / f"artifacts-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    try:
        if operation == "list":
            list_folder(path, events.append, payload.get("cache"))
        elif payload.get("live"):
            live_check(path, str(output), events.append, payload.get("memory"), payload.get("known"),
                       payload.get("live_since"))
        else:
            load(path, str(output), events.append, payload.get("cache"), payload.get("memory"),
                 payload.get("base_signature", ""), payload.get("signature", ""), limits=payload.get("limits"),
                 no_cache=bool(payload.get("no_cache")), check_level=str(payload.get("check_level") or "medium"))
        events.append({"kind": "done"})
    except Exception as exc:
        events.append({"kind": "error", "message": str(exc)})
    cache.service.pending.remove(request)
    for event in events:
        if event["kind"] == "shot":
            event = {**event, "array": np.load(event.pop("artifact"))}
        cache.service.resultReady.emit(request, event)
    return events


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> Iterator[IOService]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    yield service
    service.shutdown()


@pytest.fixture
def run(tmp_path: Path) -> Path:
    folder = tmp_path / "run"
    folder.mkdir()
    for shot in (1, 2):
        write_shot(folder, shot)
    age_folder(folder, 120)
    return folder


def open_loaded(qtbot: QtBot, service: IOService, run: Path, tmp_path: Path) -> FolderExplorer:
    """A tab showing ``run``'s data (loaded from its files, then saved to the disk cache)."""
    path = str(run)
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    cache = explorer.model.cache
    cache.live_interval, cache.live_autosave_shots = 0.02, 2
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    replay(cache, path, tmp_path, "list")
    explorer.load_to_ram_cache(path, dwell=False, explicit=True)
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs)
    replay(cache, path, tmp_path)
    qtbot.waitUntil(lambda: explorer.folder_opened_path == path and not cache.disk_cache_saving(path))
    assert sorted(explorer.folder_opened_data or {}) == [1, 2] and cache.disk_cached(path)
    for request in [r for r in service.pending if r.operation == "details"]:
        service.pending.remove(request)
    return explorer


def next_request(qtbot: QtBot, explorer: FolderExplorer, path: str) -> IORequest:
    cache = explorer.model.cache
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs)
    return producer(cache, path)


def cached_shots(path: str, tmp_path: Path) -> list[int]:
    output = tmp_path / f"cached-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    read_cached(path, str(output), events.append, store_options())
    return sorted(event["shot"] for event in events if event["kind"] == "shot")


def test_live_adds_new_shots_saves_every_n_and_when_it_stops(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path,
) -> None:
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    assert explorer.live_state()[0] and not explorer.watching(path)
    assert explorer.folder_freshness_label.text().endswith("Live updates off")
    assert explorer.start_live()
    assert not explorer.tree.isEnabled() and not explorer.path_edit.isEnabled()
    assert explorer.live_state() == (True, explorer.live_state()[1]) and "Click to stop" in explorer.live_state()[1]

    # First check: lists the folder, nothing new; it is a foreground load with the shots held.
    check = next_request(qtbot, explorer, path)
    assert check.owner == cache.jobs[("load", path)].owner and check.payload["live"]
    assert sorted(entry[0] for entry in check.payload["memory"]) == [1, 2] and check.payload["live_since"] is None
    assert service.is_foreground(check)
    events = replay(cache, path, tmp_path)
    assert events[0]["kind"] == "live_unchanged" and events[0]["live_listed"]
    session = explorer.live
    assert session is not None and session.since == run.stat().st_mtime_ns and session.checks == 1
    explorer._update_activity()
    assert explorer.folder_freshness_label.text().startswith("Live · ")
    assert "0 new shots" in explorer.folder_freshness_label.text()

    # Nothing changed: the next check is one stat (it compares the folder's mtime).
    check = next_request(qtbot, explorer, path)
    assert check.payload["live_since"] == session.since
    events = replay(cache, path, tmp_path)
    assert events[0]["kind"] == "live_unchanged" and not events[0]["live_listed"]
    # At least once a minute it lists the folder anyway (a network drive may report its mtime late).
    session.listed_at -= explorer.LIVE_LIST_SECONDS
    check = next_request(qtbot, explorer, path)
    assert check.payload["live_since"] is None
    assert replay(cache, path, tmp_path)[0]["live_listed"]

    # A new shot arrives: read and shown at once, kept in RAM (not yet saved).
    write_shot(run, 3)
    age_folder(run, 60)
    next_request(qtbot, explorer, path)
    replay(cache, path, tmp_path)
    assert sorted(explorer.folder_opened_data or {}) == [1, 2, 3]
    assert session.new == 1 and session.unsaved == {3}
    assert explorer.displayed_dataset is not None and explorer.displayed_dataset.metadata["source"] == "updated"
    assert cached_shots(path, tmp_path) == [1, 2]
    # The superseded dataset isn't kept beside the new one (its arrays would count twice).
    assert [key for key in cache.datasets if key[0] == path] == [(path, explorer.displayed_dataset.signature, 0)]
    explorer._update_activity()
    assert "1 new shot" in explorer.folder_freshness_label.text()
    assert "1 not cached yet" in explorer.folder_freshness_label.text()

    # The second unsaved shot: the next step saves the folder (N = 2) with an ordinary load, in the background.
    write_shot(run, 4)
    age_folder(run, 50)
    next_request(qtbot, explorer, path)
    replay(cache, path, tmp_path)
    assert session.unsaved == {3, 4}
    save = next_request(qtbot, explorer, path)
    assert save.payload.get("save") and not save.payload.get("live") and not service.is_foreground(save)
    assert session.request == "save" and session.saving == {3, 4} and not session.unsaved
    assert path in cache.quit_saves()
    replay(cache, path, tmp_path)
    qtbot.waitUntil(lambda: not session.saving)
    assert session.saved_at is not None and cached_shots(path, tmp_path) == [1, 2, 3, 4]
    assert not cache.quit_saves()

    # Live off with one unsaved shot: saved in the background, then the session is done.
    write_shot(run, 5)
    age_folder(run, 40)
    next_request(qtbot, explorer, path)
    replay(cache, path, tmp_path)
    assert session.unsaved == {5}
    explorer.stop_live()
    assert explorer.live is None and explorer.tree.isEnabled() and explorer.path_edit.isEnabled()
    save = next_request(qtbot, explorer, path)
    assert save.payload.get("save") and save.owner == cache.jobs[("load", path)].owner
    explorer._update_activity()
    assert explorer.folder_freshness_label.text() == "Live updates off · saving 1 shot"
    replay(cache, path, tmp_path)
    qtbot.waitUntil(lambda: not explorer._live_sessions)
    assert cached_shots(path, tmp_path) == [1, 2, 3, 4, 5]
    assert sorted(explorer.folder_opened_data or {}) == [1, 2, 3, 4, 5]
    explorer._update_activity()
    assert explorer.folder_freshness_label.text().endswith("Live updates off")
    explorer.close_cleanup()


def test_files_still_being_written_wait_and_are_counted(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    assert explorer.start_live()
    monkeypatch.setattr(io_helper, "SETTLE_SECONDS", 5.0)
    write_shot(run, 3, age=0)
    age_folder(run, 60)
    next_request(qtbot, explorer, path)
    replay(cache, path, tmp_path)
    session = explorer.live
    assert session is not None and session.unsettled == 1 and session.new == 0 and session.since is None
    explorer._update_activity()
    assert "1 still being written" in explorer.folder_freshness_label.text()
    write_shot(run, 3, age=60)  # Written now; the folder itself didn't change.
    next_request(qtbot, explorer, path)
    replay(cache, path, tmp_path)
    assert session.unsettled == 0 and session.new == 1 and sorted(explorer.folder_opened_data or {}) == [1, 2, 3]
    explorer.stop_live(save=False)
    explorer.close_cleanup()


def test_an_error_stops_checking_keeps_the_data_and_retry_resumes(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path,
) -> None:
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    data = explorer.folder_opened_data
    explorer.load_error = "Timed out after 60 s without progress"  # An earlier check's.
    assert explorer.start_live()
    explorer._update_activity()
    assert explorer.retry_button.isHidden()  # Live's own Retry shows when Live needs it.
    hidden = tmp_path / "unmounted"
    run.rename(hidden)
    next_request(qtbot, explorer, path)
    events = replay(cache, path, tmp_path)
    assert events[-1]["kind"] == "error"
    session = explorer.live
    assert session is not None and session.error.startswith("Folder not found")
    explorer._update_activity()
    assert explorer.folder_freshness_label.text().startswith("Live stopped: Folder not found")
    assert "color" in explorer.folder_freshness_label.styleSheet()
    assert explorer.folder_opened_data is data and not explorer.retry_button.isHidden()
    assert explorer.activity_brief == "Live stopped: run"
    # No retries by itself: nothing more is queued.
    qtbot.wait(100)
    assert ("load", path) not in cache.jobs
    hidden.rename(run)
    explorer.retry_button.click()
    next_request(qtbot, explorer, path)
    assert replay(cache, path, tmp_path)[0]["kind"] == "live_unchanged"
    assert not session.error and explorer.retry_button.isHidden()
    explorer.stop_live(save=False)
    explorer.close_cleanup()


def test_shots_gone_from_the_folder_stop_live(qtbot: QtBot, service: IOService, run: Path, tmp_path: Path) -> None:
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    assert explorer.start_live()
    (run / "d_txy_forc2.txt").unlink()
    next_request(qtbot, explorer, path)
    replay(cache, path, tmp_path)
    assert explorer.live is not None and explorer.live.error == "1 shot missing from the folder"
    assert path in cache.mismatched
    explorer.stop_live()  # Nothing to save, and its cached data may not be this folder's.
    assert ("load", path) not in cache.jobs and not explorer._live_sessions
    explorer.close_cleanup()


def test_live_needs_shown_data_and_locks_navigation(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path,
) -> None:
    path = str(run)
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    enabled, tooltip = explorer.live_state()
    assert not enabled and "Select a folder with loaded data" in tooltip and not explorer.start_live()
    explorer.close_cleanup()
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    assert explorer.start_live() and not explorer.start_live()
    # Selecting another folder, opening one, or Deselect turn Live off (the tree is locked: by code only).
    explorer.load_to_ram_cache(path, dwell=False, explicit=True)
    assert ("load", path) not in cache.jobs or cache.jobs[("load", path)].payload.get("live")
    explorer.open_to_path(str(tmp_path))
    assert explorer.live is None and explorer.tree.isEnabled()
    explorer.close_cleanup()


def test_rules_that_stop_saving_show_on_the_line(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path,
) -> None:
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    cache.remember_prefs(path, {"no_cache": True, "no_auto_load": False, "set_at": time.time()}, confirmed=False)
    assert explorer.start_live()
    for shot in (3, 4, 5):
        write_shot(run, shot)
        age_folder(run, 100 - shot)
        next_request(qtbot, explorer, path)
        replay(cache, path, tmp_path)
    session = explorer.live
    assert session is not None and session.unsaved == {3, 4, 5} and not session.saving
    explorer._update_activity()
    assert "3 not cached (Don't cache)" in explorer.folder_freshness_label.text()
    assert "Not saved: you chose Don't cache for this folder" in explorer.folder_freshness_label.toolTip()
    explorer.stop_live()
    assert not explorer._live_sessions and ("load", path) not in cache.jobs
    explorer.close_cleanup()


def test_closing_the_tab_saves_its_new_shots(qtbot: QtBot, service: IOService, run: Path, tmp_path: Path) -> None:
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    assert explorer.start_live()
    write_shot(run, 3)
    age_folder(run, 60)
    next_request(qtbot, explorer, path)
    replay(cache, path, tmp_path)
    explorer.on_stop_button_clicked()  # As closing a tab does first.
    explorer.close_cleanup()
    assert explorer.closed and cache.quit_saves() == [path]
    replay(cache, path, tmp_path)
    assert not cache.quit_saves() and cached_shots(path, tmp_path) == [1, 2, 3]


def test_switching_tabs_turns_live_off(qtbot: QtBot, service: IOService, run: Path, tmp_path: Path) -> None:
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    other = FolderExplorer(str(tmp_path), str(tmp_path), str(tmp_path), [0])
    qtbot.addWidget(other)
    assert explorer.start_live()
    current = [explorer]
    window = SimpleNamespace(
        update_tool_enabled_state=lambda: None, _update_live_action=lambda: None,
        _explorers=lambda: [(0, explorer), (1, other)],
        tab_widget=SimpleNamespace(currentWidget=lambda: current[0]))
    HelabMainWindow.on_current_tab_changed(window, 0)  # type: ignore[arg-type]
    assert explorer.live is not None
    current[0] = other
    other.claim_foreground()
    HelabMainWindow.on_current_tab_changed(window, 1)  # type: ignore[arg-type]
    assert explorer.live is None and explorer.tree.isEnabled()
    other.close_cleanup()
    explorer.close_cleanup()


def test_a_save_waits_for_the_folders_running_save(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path,
) -> None:
    """Saves of one folder never overlap: Live off while its auto-save writes waits for it."""
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    assert explorer.start_live()
    for shot in (3, 4):
        write_shot(run, shot)
        age_folder(run, 100 - shot)
        next_request(qtbot, explorer, path)
        replay(cache, path, tmp_path)
    save = next_request(qtbot, explorer, path)
    assert save.payload.get("save")
    # Deliver its data, but not its write yet.
    events = run_helper_events(cache, path, tmp_path)
    loaded_at = next(i for i, event in enumerate(events) if event["kind"] == "loaded")
    for event in events[:loaded_at + 1]:
        cache.service.resultReady.emit(save, event)
    assert cache.disk_cache_saving(path)
    write_shot(run, 5)
    age_folder(run, 60)
    next_request(qtbot, explorer, path)
    replay(cache, path, tmp_path)
    explorer.stop_live()
    assert ("load", path) not in cache.jobs and cache.quit_saves() == [path]  # Waiting.
    for event in events[loaded_at + 1:]:
        cache.service.resultReady.emit(save, event)
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs)
    replay(cache, path, tmp_path)
    qtbot.waitUntil(lambda: not explorer._live_sessions)
    assert cached_shots(path, tmp_path) == [1, 2, 3, 4, 5]
    explorer.close_cleanup()


def run_helper_events(cache: FolderCache, path: str, tmp_path: Path) -> list[dict[str, Any]]:
    """The real helper's events for the queued load, not yet delivered."""
    request = producer(cache, path)
    payload = request.payload
    output = tmp_path / f"artifacts-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    load(path, str(output), events.append, payload.get("cache"), payload.get("memory"),
         payload.get("base_signature", ""), payload.get("signature", ""), limits=payload.get("limits"))
    events.append({"kind": "done"})
    cache.service.pending.remove(request)
    return [{**event, "array": np.load(event.pop("artifact"))} if event["kind"] == "shot" else event
            for event in events]


def test_quit_window_waits_for_saves_and_quit_now_skips_them(
    qtbot: QtBot, service: IOService, tmp_path: Path,
) -> None:
    cache = FolderCache(service)
    path = str(tmp_path / "run")
    cache._deferred_saves[path] = ("owner", {})
    dialog = QuitSaveDialog(cache)
    qtbot.addWidget(dialog)
    results: list[int] = []
    dialog.finished.connect(results.append)
    dialog.open()
    item = dialog.folders.item(0)
    assert dialog.folders.count() == 1 and item is not None and item.text() == "run — waiting for its previous save"
    dialog.reject()  # Esc keeps waiting.
    assert dialog.isVisible() and not results
    del cache._deferred_saves[path]
    qtbot.waitUntil(lambda: bool(results))
    assert results == [QDialog.DialogCode.Accepted] and not dialog.skipped
    cache._deferred_saves[path] = ("owner", {})
    dialog = QuitSaveDialog(cache)
    qtbot.addWidget(dialog)
    dialog.finished.connect(results.append)
    dialog.open()
    dialog.quit_now_button.click()
    assert results[-1] == QDialog.DialogCode.Rejected and dialog.skipped


def test_a_finished_loads_background_save_is_a_quit_save(service: IOService, tmp_path: Path) -> None:
    cache = FolderCache(service)
    path = str(tmp_path)
    assert cache.submit("tab", 0, path, "load", {})
    request = producer(cache, path)
    service.resultReady.emit(request, {"kind": "shot", "shot": 1, "array": np.ones((1, 3))})
    service.resultReady.emit(request, {"kind": "loaded", "signature": "s", "files": 1, "rows": 1, "bytes": 24,
                                       "problematic": [], "disk_cache_pending": True})
    assert cache.quit_saves() == [path]
    ended: list[tuple[str, str]] = []
    cache.saveEnded.connect(lambda folder, outcome: ended.append((folder, outcome)))
    service.resultReady.emit(request, {"kind": "cache_saved", "cache_info": {"signature": "s"}})
    assert not cache.quit_saves() and ended == [(path, "saved")]


def test_closing_the_window_waits_in_the_quit_window(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    window = HelabMainWindow()
    qtbot.addWidget(window)
    from helab.utils.folder_cache import get_folder_cache
    from helab.utils.io_service import get_io_service
    cache = get_folder_cache(get_io_service())
    path = str(tmp_path / "run")
    cache._deferred_saves[path] = ("owner", {})
    window.close()
    assert not window._closing and window._quit_dialog is not None and window._quit_dialog.isVisible()
    window.close()  # Again (e.g. Ctrl+C): the window still decides.
    assert not window._closing
    del cache._deferred_saves[path]
    qtbot.waitUntil(lambda: window._closing, timeout=3000)
    assert get_io_service() is not cache.service  # The old service was shut down.


def test_the_live_action_follows_the_current_tab_and_locks_navigation(qtbot: QtBot, tmp_path: Path) -> None:
    window = HelabMainWindow()
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: isinstance(window.tab_widget.currentWidget(), FolderExplorer))
    explorer = window.tab_widget.currentWidget()
    assert isinstance(explorer, FolderExplorer)
    window._update_live_action()
    assert not window.action_tab_live.isEnabled() and "Select a folder with loaded data" in window.action_tab_live.toolTip()
    window.on_live_button_clicked()  # Says why instead.
    assert window._status_notice is not None and "Select a folder" in window._status_notice[0]
    from helab.utils.folder_cache import Dataset
    explorer.live = LiveSession(explorer.selected_path_globally, time.time(), set(),
                                Dataset(explorer.selected_path_globally, "s", {}, {}, 0))
    window._update_live_action()
    assert window.action_tab_live.isEnabled() and window.action_tab_live.isChecked()
    assert not window.action_tab_refresh.isEnabled() and not window.action_tab_rescan.isEnabled()
    assert not window.action_tab_folder_up.isEnabled() and window.action_tab_new.isEnabled()
    explorer.live = None
    window._update_live_action()
    assert not window.action_tab_live.isChecked() and window.action_tab_refresh.isEnabled()
    window._quit_now = True


def test_quit_now_closes_at_once(qtbot: QtBot, tmp_path: Path) -> None:
    window = HelabMainWindow()
    qtbot.addWidget(window)
    from helab.utils.folder_cache import get_folder_cache
    from helab.utils.io_service import get_io_service
    cache = get_folder_cache(get_io_service())
    cache._deferred_saves[str(tmp_path)] = ("owner", {})
    window.close()
    dialog = window._quit_dialog
    assert dialog is not None
    dialog.quit_now_button.click()
    qtbot.waitUntil(lambda: window._closing, timeout=3000)


def test_a_live_check_holds_background_work_only_while_reading(service: IOService) -> None:
    check = IORequest("tab:live", 0, "/data/run", "load", {"live": True}, 60.0)
    check.lane, check.last_activity = FOREGROUND, time.monotonic()
    service.active.append(check)
    assert not service.hold_background()
    check.current_file = "/data/run/d_txy_forc3.txt"
    assert service.hold_background()
    assert service.label(check) == "Live check" and service.running_loads() == []
    check.current_file = None
    assert "Checking for new shots" in service.activity_summary()
    service.active.remove(check)


def test_live_settings_are_read_within_bounds(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    assert read_live_interval(settings) == DEFAULT_LIVE_INTERVAL == 3.0
    assert read_live_autosave(settings) == DEFAULT_LIVE_AUTOSAVE == 10
    for value, expected in ((0.01, 0.5), (1e9, 600.0), ("nan", 3.0), ("x", 3.0), (7.5, 7.5)):
        settings.setValue(LIVE_INTERVAL_SETTING, value)
        assert read_live_interval(settings) == expected
    for count, saved in ((0, 1), ("x", 10), (25, 25)):
        settings.setValue(LIVE_AUTOSAVE_SETTING, count)
        assert read_live_autosave(settings) == saved


def test_settings_dialog_edits_both_live_settings(qtbot: QtBot, tmp_path: Path) -> None:
    from helab.views.SettingsDialog import SettingsDialog
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)
    assert dialog.live_interval_spin.value() == 3.0 and dialog.cache_tab.live_autosave.value() == 10
    dialog.live_interval_spin.setValue(5.5)
    dialog.cache_tab.live_autosave.setValue(4)
    dialog._write_settings()
    assert read_live_interval(settings) == 5.5 and read_live_autosave(settings) == 4
