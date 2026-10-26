"""Work Offline (cache-only browsing, Tony 2026-10-26: D1–D10 of
.ai/sessions/2026-10-26-claude-cache-only/design.md): HeLab reads only its disk cache. Folders are
listed from their saved listings (``saved_list``), selected folders show their data from RAM or one
cached read, plots run on it, and no source folder or server is read until Work Online.

Source access is denied throughout: ``answer`` fails if a pending request is a source operation
while offline, ``no_source_io`` fails if one reaches ``IOService._start``, and "restart" tests
delete the source folders first, so a read of one would fail too.
"""
from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any, Callable, Iterator, cast

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from helab.analysis.dataset_view import build_view
from helab.io_helper import OFFLINE_REFUSED
from helab.io_ops.browse import list_folder
from helab.io_ops.listings import newest_root_folder, saved_list_folder
from helab.io_ops.loading import load, read_cached
from helab.io_ops.results import result_find
from helab.utils import folder_cache
from helab.utils.folder_cache import Dataset, FolderCache, get_folder_cache, store_options
from helab.utils.io_service import IORequest, IOService
from helab.utils.folder_cache import OFFLINE_TOOLTIP
from helab.views.FolderExplorer import OFFLINE_NOT_KEPT, FolderExplorer
from helab.views.explorer_live import OFFLINE_LIVE

from test_result_cache_plots import Costly, close, folder_view, make_window, open_plot, results_saved, saved

SOURCE = frozenset(OFFLINE_REFUSED | {"details"})


@pytest.fixture(autouse=True)
def back_online() -> Iterator[None]:
    """Every test ends online (``store_options`` reads a module flag)."""
    yield
    folder_cache._offline = False


@pytest.fixture
def no_source_io(monkeypatch: pytest.MonkeyPatch) -> list[IORequest]:
    """What started; fails at once if a source operation starts while its service is offline."""
    started: list[IORequest] = []
    real_start = IOService._start

    def start(service: IOService, request: IORequest, lane: str) -> None:
        real_start(service, request, lane)
        if request in service.active:
            assert not (service.offline and request.operation in SOURCE and not IOService.finishes_offline(request)), (
                f"Source operation started offline: {request.operation} {request.path}")
            started.append(request)
    monkeypatch.setattr(IOService, "_start", start)
    return started


def deny_source(monkeypatch: pytest.MonkeyPatch, folder: Path) -> list[str]:
    """Deny the real source calls inside ``folder`` in this process (helpers run here in these tests):
    a listing, stat, open or read of it fails the test at once; the calls tried, for a final check."""
    import builtins
    import os
    tried: list[str] = []
    top = os.path.normcase(os.path.abspath(folder))

    def inside(path: Any) -> bool:
        try:
            target = str(os.path.normcase(os.path.abspath(os.fspath(path))))
        except TypeError:
            return False  # (A file descriptor.)
        return target == top or target.startswith(top + os.sep)

    def denied(name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def call(path: Any = ".", *args: Any, **kwargs: Any) -> Any:
            if inside(path):
                tried.append(f"{name} {path}")
                raise AssertionError(f"Source call offline: {name} {path}")
            return real(path, *args, **kwargs)
        return call
    for name in ("scandir", "stat", "lstat", "listdir"):
        monkeypatch.setattr(os, name, denied(name, getattr(os, name)))
    monkeypatch.setattr(builtins, "open", denied("open", builtins.open))
    return tried


def frozen_service(monkeypatch: pytest.MonkeyPatch) -> IOService:
    """A service whose requests wait in ``pending`` until a test answers them (``answer``)."""
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    return service


def answer(qtbot: QtBot, service: IOService, operation: str, path: str,
           helper: Callable[[Callable[[Any], None]], None]) -> None:
    """Answer the pending ``operation`` for ``path`` with a real helper's events; never a source
    operation while offline."""
    qtbot.waitUntil(lambda: any(r.operation == operation and r.path == path for r in service.pending))
    request = next(r for r in service.pending if r.operation == operation and r.path == path)
    assert not (service.offline and operation in SOURCE), f"{operation} {path} submitted offline"

    def send(event: Any) -> None:
        if event["kind"] == "shot":
            event = {**event, "array": np.load(event["artifact"])}
        service.resultReady.emit(request, event)
    helper(send)
    service.resultReady.emit(request, {"kind": "done"})
    service.pending.remove(request)
    cache = service.folder_cache
    if cache is not None:  # Results reach tabs from posted calls (``FolderCache._replay``).
        qtbot.waitUntil(lambda: not any(r.path == path for r in cache._deliveries))


def source_requests(service: IOService) -> list[str]:
    return [f"{r.operation} {r.path}" for r in service.pending if r.operation in SOURCE]


# A tree listed and loaded online, then the source deleted

def experiment(tmp_path: Path) -> Path:
    """``data/day/run_1`` (2 shots, loaded), ``run_2`` (no data), ``run_3`` (1 shot, never
    loaded), ``data/later`` (never listed)."""
    data = tmp_path / "data"
    for folder in ("day/run_1", "day/run_2", "day/run_3", "later/run_9"):
        (data / folder).mkdir(parents=True)
    for shot in (1, 2):
        (data / "day/run_1" / f"d{shot}.txt").write_text("")
        (data / "day/run_1" / f"d_txy_forc{shot}.txt").write_text(f"{shot},2,3\n")
    (data / "day/run_3" / "d_txy_forc1.txt").write_text("1,2,3\n")
    return data


def browse_online(tmp_path: Path, data: Path) -> None:
    """What an online session leaves in the disk cache: listings (from the data root, the tab's top
    folder) and run_1's dataset."""
    options = store_options()
    for folder in (tmp_path, data, data / "day", data / "day/run_1", data / "day/run_2", data / "day/run_3"):
        list_folder(str(folder), lambda event: None, options)
    output = tmp_path / "artifacts"
    output.mkdir()
    load(str(data / "day/run_1"), str(output), lambda event: None, options)


@pytest.fixture
def offline_restart(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[tuple[IOService, FolderCache, Path]]:
    """A restart with the source deleted: a fresh service and cache, offline from the start."""
    data = experiment(tmp_path)
    browse_online(tmp_path, data)
    shutil.rmtree(data)
    tried = deny_source(monkeypatch, data)
    service = frozen_service(monkeypatch)
    cache = get_folder_cache(service)
    cache.set_offline(True)
    yield service, cache, data
    service.shutdown()
    assert not tried, f"Source calls offline: {tried}"


def list_saved(qtbot: QtBot, service: IOService, folder: Path) -> None:
    answer(qtbot, service, "saved_list", str(folder),
           lambda send: saved_list_folder(str(folder), send, store_options()))


def open_tab(qtbot: QtBot, service: IOService, data: Path) -> FolderExplorer:
    explorer = FolderExplorer(str(data), str(data), str(data), [0, 4, 5])
    qtbot.addWidget(explorer)
    list_saved(qtbot, service, data)
    return explorer


def select(qtbot: QtBot, explorer: FolderExplorer, path: str) -> None:
    explorer.tree.setCurrentIndex(explorer.model.path_index(path))
    qtbot.waitUntil(lambda: explorer.selected_path_globally == path)


def cached_read(qtbot: QtBot, service: IOService, path: str, tmp_path: Path) -> None:
    output = tmp_path / f"cached-read-{len(list(tmp_path.iterdir()))}"
    output.mkdir()
    answer(qtbot, service, "cached", path, lambda send: read_cached(path, str(output), send, store_options()))


# The gate

@pytest.mark.parametrize("operation", sorted(SOURCE))
def test_the_gate_answers_every_source_operation_offline_and_refuses_it_at_the_service(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, operation: str) -> None:
    service = frozen_service(monkeypatch)
    cache = get_folder_cache(service)
    try:
        cache.set_offline(True)
        events: list[dict[str, Any]] = []
        cache.resultReady.connect(lambda request, event: events.append(event))
        assert cache.submit("tab", 0, str(tmp_path), operation, {"cache": store_options(), "paths": [str(tmp_path)],
                                                                   "candidates": [str(tmp_path)]})
        if operation in ("list", "resolve"):
            # A listing is the folder's saved listing, a default folder the newest data root: the local lane.
            assert [r.operation for r in service.pending] == ["saved_list"]
        else:
            assert not service.pending
            qtbot.waitUntil(lambda: any(event["kind"] == "offline" for event in events))
            assert not any(event["kind"] == "error" for event in events)
        # Anything bypassing FolderCache is refused at the service.
        assert not service.submit("raw", 0, str(tmp_path), operation, {})
    finally:
        service.shutdown()


@pytest.mark.parametrize("operation", sorted(IOService.OFFLINE_OPERATIONS))
def test_local_work_goes_on_offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, operation: str) -> None:
    service = frozen_service(monkeypatch)
    try:
        service.set_offline(True)
        assert service.submit("local", 0, str(tmp_path), operation, {"cache": store_options()})
        assert [r.operation for r in service.pending] == [operation]
    finally:
        service.shutdown()


def test_entering_offline_cancels_source_work_but_not_saves_or_local_work(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service = frozen_service(monkeypatch)
    cache = get_folder_cache(service)
    try:
        path = str(tmp_path)
        cancelled: list[str] = []
        cache.resultReady.connect(lambda request, event: cancelled.append(request.operation)
                                  if event["kind"] == "cancelled" and request.owner in ("tab", "raw") else None)
        for operation in ("list", "scan", "load"):
            assert cache.submit("tab", 0, path, operation, {"cache": store_options()})
        assert cache.submit("tab", 0, path, "icons", {"paths": [path]})
        assert cache.submit("tab", 0, path, "cached", {"cache": store_options()})
        assert cache.submit("live-save", 0, str(tmp_path / "other"), "load", {"cache": store_options(), "save": True})
        assert service.submit("raw", 0, path, "details", {})
        cache.set_offline(True)
        assert sorted(cancelled) == ["details", "icons", "list", "load", "scan"]
        assert sorted(r.operation for r in service.pending) == ["cached", "load"]
        assert next(r for r in service.pending if r.operation == "load").payload["save"]
        # New source work is refused, a save asked for now too.
        assert not service.submit("raw", 0, path, "load", {"save": True})
    finally:
        service.shutdown()


def test_a_source_request_left_queued_is_refused_as_it_starts(
        no_source_io: list[IORequest], tmp_path: Path) -> None:
    service = IOService()
    try:
        service.timer.stop()
        request = IORequest("raw", 0, str(tmp_path), "list", {}, 60.0)
        service.offline = True  # (As if queued in a gap: set_offline cancels queued ones itself.)
        service.pending.append(request)
        service._dispatch()
        assert request.cancelled.is_set() and request not in service.active and not no_source_io
    finally:
        service.shutdown()


# Navigation on saved listings, after a restart with the source deleted

def test_a_restart_offline_navigates_saved_listings_with_their_counts(
        qtbot: QtBot, offline_restart: tuple[IOService, FolderCache, Path]) -> None:
    service, cache, data = offline_restart
    explorer = open_tab(qtbot, service, data)
    model = explorer.model
    day = str(data / "day")
    assert sorted(child.path for child in model.nodes[str(data)].children) == [day, str(data / "later")]
    model.request_scan(day)
    list_saved(qtbot, service, data / "day")
    run_1, run_3 = model.nodes[str(data / "day/run_1")], model.nodes[str(data / "day/run_3")]
    assert run_1.report is not None and run_1.txy_count == 2 and run_1.cached_report
    assert run_3.report is not None and run_3.txy_count == 1
    assert cache.disk_cached(run_1.path) and not cache.disk_cached(run_3.path)
    assert "Offline: showing saved results from" in model._tooltip(model.nodes[day], "")
    # Rendering and scrolling ask for no icons, details or checks.
    explorer.show()
    explorer._load_visible_icons()
    explorer._check_visible_folders()
    for index, _ in model.get_visible_rows():
        for role in range(0, 40):
            model.data(index, role)
    assert not source_requests(service)
    explorer.close_cleanup()


def test_a_folder_never_listed_says_so_and_has_no_expand_arrow(
        qtbot: QtBot, offline_restart: tuple[IOService, FolderCache, Path]) -> None:
    service, cache, data = offline_restart
    explorer = open_tab(qtbot, service, data)
    later = str(data / "later")
    explorer.model.request_scan(later)
    list_saved(qtbot, service, data / "later")
    node = explorer.model.nodes[later]
    qtbot.waitUntil(lambda: node.loaded)
    assert node.offline_unlisted and not explorer.model.hasChildren(explorer.model.path_index(later))
    tooltip = explorer.model._tooltip(node, "")
    assert "Subfolders: not listed while online" in tooltip and "Offline: not listed while online" in tooltip
    assert node.state == "idle" and not node.error
    explorer.close_cleanup()


def test_a_folder_above_data_roots_leads_down_to_them(
        offline_restart: tuple[IOService, FolderCache, Path], tmp_path: Path) -> None:
    events: list[Any] = []
    saved_list_folder(str(tmp_path.parent), events.append, store_options())  # Above conftest's data root.
    names = [entry["name"] for event in events if event["kind"] == "entries" for entry in event["entries"]]
    status = next(event for event in events if event["kind"] == "status")
    assert names == [tmp_path.name] and not status["listed"] and status["offline"]


def test_a_restart_offline_opens_at_the_newest_data_root(
        offline_restart: tuple[IOService, FolderCache, Path], tmp_path: Path) -> None:
    events: list[Any] = []
    newest_root_folder(events.append, store_options())
    assert events == [{"kind": "resolved", "path": str(tmp_path)}]


# Selection and data

def test_selecting_a_cached_folder_reads_the_cache_only_and_says_not_checked(
        qtbot: QtBot, tmp_path: Path, offline_restart: tuple[IOService, FolderCache, Path]) -> None:
    service, cache, data = offline_restart
    explorer = open_tab(qtbot, service, data)
    run_1 = str(data / "day/run_1")
    explorer.model.request_scan(str(data / "day"))
    list_saved(qtbot, service, data / "day")
    explorer.selectionPathChanged.connect(lambda path: explorer.load_to_ram_cache(path))
    select(qtbot, explorer, run_1)
    cached_read(qtbot, service, run_1, tmp_path)
    qtbot.waitUntil(lambda: explorer.folder_opened_path == run_1)
    assert sorted(explorer.folder_opened_data or {}) == [1, 2]
    assert not source_requests(service) and not any(r.operation == "load" for r in service.pending)
    explorer._update_folder_summary()
    assert "not checked (offline)" in explorer.folder_cache_label.text()
    assert explorer.folder_freshness_label.text().startswith("Offline · cached data only")
    explorer.close_cleanup()


def test_a_folder_without_cached_data_says_so_and_loads_nothing(
        qtbot: QtBot, offline_restart: tuple[IOService, FolderCache, Path]) -> None:
    service, cache, data = offline_restart
    explorer = open_tab(qtbot, service, data)
    run_3 = str(data / "day/run_3")
    explorer.model.request_scan(str(data / "day"))
    list_saved(qtbot, service, data / "day")
    select(qtbot, explorer, run_3)
    list_saved(qtbot, service, data / "day/run_3")
    assert not explorer.load_to_ram_cache(run_3, dwell=False, explicit=True)  # Even a deliberate load.
    assert not explorer.queue_load(str(data / "day/run_1"))  # Nor another folder's.
    assert not any(r.operation in ("load", "cached") for r in service.pending)
    explorer._update_folder_summary()
    assert OFFLINE_NOT_KEPT in explorer.folder_summary_label.text()
    assert explorer.folder_cache_label.text() == "No cached data (offline)"
    explorer.close_cleanup()


def test_going_offline_keeps_the_shown_data_and_ends_its_work_quietly(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data = experiment(tmp_path)
    browse_online(tmp_path, data)
    service = frozen_service(monkeypatch)
    cache = get_folder_cache(service)
    explorer = FolderExplorer(str(data), str(data), str(data), [0, 4, 5])
    qtbot.addWidget(explorer)
    try:
        answer(qtbot, service, "list", str(data), lambda send: list_folder(str(data), send, store_options()))
        explorer.model.request_scan(str(data / "day"))
        answer(qtbot, service, "list", str(data / "day"),
               lambda send: list_folder(str(data / "day"), send, store_options()))
        run_1 = str(data / "day/run_1")
        explorer.selectionPathChanged.connect(lambda path: explorer.load_to_ram_cache(path))
        select(qtbot, explorer, run_1)
        cached_read(qtbot, service, run_1, tmp_path)
        qtbot.waitUntil(lambda: explorer.folder_opened_path == run_1)
        cache.set_offline(True)
        assert not source_requests(service) and not explorer.load_error and not explorer.loading
        assert explorer.folder_opened_path == run_1 and sorted(explorer.folder_opened_data or {}) == [1, 2]
        assert all(node.state != "cancelled" and not node.error for node in explorer.model.nodes.values())
    finally:
        explorer.close_cleanup()
        service.shutdown()


# Controls

def test_source_controls_are_off_offline_with_the_reason(
        qtbot: QtBot, offline_restart: tuple[IOService, FolderCache, Path]) -> None:
    service, cache, data = offline_restart
    explorer = open_tab(qtbot, service, data)
    assert explorer.place_root_state(str(data)) == (False, OFFLINE_TOOLTIP)
    assert not explorer.place_root(str(data))
    assert explorer.live_unavailable(str(data)) == OFFLINE_LIVE and not explorer.start_live()
    enabled, tooltip = explorer.live_state()
    assert not enabled and OFFLINE_LIVE in tooltip
    explorer.refresh_folder(str(data))
    explorer.start_basic_scan("view")
    explorer.context_menu_action_deep_calc_status(str(data), 2)
    assert not source_requests(service)
    explorer.close_cleanup()


# Plots

def test_a_saved_analysis_result_shows_offline_without_computing(
        qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_source_io: list[IORequest]) -> None:
    """Online a plot saves its result; after a restart offline, the saved result shows at once
    (``result_find`` on the local lane) and nothing reads a folder."""
    service = IOService()
    cache = get_folder_cache(service)
    script = Costly()
    view = folder_view(tmp_path)
    try:
        window = make_window(qtbot, cache, tmp_path, monkeypatch)
        first = open_plot(window, qtbot, view, script)
        qtbot.waitUntil(lambda: saved(first), timeout=30_000)
        close(window)
    finally:
        service.shutdown()
    service = IOService()
    cache = get_folder_cache(service)
    cache.set_offline(True)
    try:
        window = make_window(qtbot, cache, tmp_path, monkeypatch)
        again = open_plot(window, qtbot, view, script)
        qtbot.waitUntil(lambda: again.shown is not None and not again.job_id, timeout=30_000)
        assert script.computed == 1 and results_saved() == 1
        assert {r.operation for r in no_source_io if r.owner in cache._result_ops} <= {"result_find"}
        assert {r.operation for r in no_source_io} <= IOService.OFFLINE_OPERATIONS
        close(window)
    finally:
        service.shutdown()


def test_a_plot_runs_offline_on_data_from_a_cached_read(
        qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        offline_restart: tuple[IOService, FolderCache, Path]) -> None:
    service, cache, data = offline_restart
    run_1 = str(data / "day/run_1")
    shown: list[Dataset] = []
    cache.resultReady.connect(lambda request, event: shown.append(event["dataset"])
                              if event["kind"] == "loaded" else None)
    assert cache.submit("tab", 0, run_1, "cached", {"cache": store_options()})
    cached_read(qtbot, service, run_1, tmp_path)
    qtbot.waitUntil(lambda: bool(shown))
    script = Costly()
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    try:
        instance = open_plot(window, qtbot, build_view(shown[0]), script)
        # Its saved-result lookup is local-lane work: none saved, so it computes.
        lookup = next(r for r in service.pending if r.operation == "result_find").payload
        (tmp_path / "lookup").mkdir()
        answer(qtbot, service, "result_find", run_1, lambda send: result_find(
            run_1, str(tmp_path / "lookup"), store_options(), lookup["lookup"], lookup.get("family", ""), send))
        qtbot.waitUntil(lambda: instance.shown is not None and not instance.job_id, timeout=30_000)
        assert script.computed == 1 and not source_requests(service)
    finally:
        close(window)


# Settings

def test_cache_maintenance_runs_offline_and_marker_writes_do_not(
        qtbot: QtBot, offline_restart: tuple[IOService, FolderCache, Path]) -> None:
    service, cache, data = offline_restart
    service.pending.clear()
    for action in ("inventory", "clear_root", "forget_root"):
        assert cache.cache_admin(action, uuid="u", location="l")
    assert [r.operation for r in service.pending] == ["cache_admin"] * 3
    events: list[str] = []
    cache.resultReady.connect(lambda request, event: events.append(event["kind"]))
    cache.remove_root("tab", str(data), "u", "l")  # (Settings → Data roots › Delete .helab-root…)
    qtbot.waitUntil(lambda: "offline" in events)
    assert not source_requests(service)


# The window: File › Work Offline, remembered (D2); the way back (D8)

def test_the_window_starts_offline_when_asked_last_time_and_work_online_relists_every_tab(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_source_io: list[IORequest]) -> None:
    from helab.utils.io_service import get_io_service
    from helab.utils.settings_defaults import WORK_OFFLINE_SETTING, read_setting
    from helab.utils.settings_store import app_settings
    from helab.views.HelabMainWindow import HelabMainWindow
    data = experiment(tmp_path)
    browse_online(tmp_path, data)
    app_settings().setValue(WORK_OFFLINE_SETTING, True)
    window = HelabMainWindow()
    qtbot.addWidget(window)
    cache = get_folder_cache(get_io_service())
    assert cache.offline and window.action_work_offline.isChecked() and not window.offline_button.isHidden()
    # The first tab opens at the newest data root, from its saved listing; nothing reads a folder.
    qtbot.waitUntil(lambda: isinstance(window.tab_widget.currentWidget(), FolderExplorer))
    explorer = window.tab_widget.currentWidget()
    assert isinstance(explorer, FolderExplorer)
    qtbot.waitUntil(lambda: explorer.model.rootPath() == str(tmp_path), timeout=10_000)
    qtbot.waitUntil(lambda: str(data) in explorer.model.nodes, timeout=10_000)
    # A second tab, offline too, at a folder below.
    window.add_new_folder_explorer_tab(str(data), str(data), str(data))
    qtbot.waitUntil(lambda: window.tab_widget.count() == 2)
    second = window.tab_widget.widget(1)
    assert isinstance(second, FolderExplorer)
    qtbot.waitUntil(lambda: second.model.root is not None and second.model.root.loaded, timeout=10_000)
    assert {r.operation for r in no_source_io} <= IOService.OFFLINE_OPERATIONS
    window._update_live_action()
    assert not window.action_tab_refresh.isEnabled() and not window.action_tab_rescan.isEnabled()
    assert OFFLINE_TOOLTIP in window.action_tab_refresh.toolTip()
    window.set_work_offline(False)
    assert not cache.offline and not read_setting(app_settings(), WORK_OFFLINE_SETTING, typed=True)
    assert window.offline_button.isHidden() and window.action_tab_refresh.isEnabled()
    # Work Online lists every tab's folders again from the source (D8).
    qtbot.waitUntil(lambda: {str(tmp_path), str(data)} <= {r.path for r in no_source_io if r.operation == "list"},
                    timeout=10_000)
    window.set_work_offline(True)
    assert cache.offline and read_setting(app_settings(), WORK_OFFLINE_SETTING, typed=True)
    window._quit_now = True
    window.close()


# Review round 1 (Vernier, review-findings.md): each fails without its fix.

def test_going_offline_stops_a_finished_loads_cache_write_which_reads_the_folder(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """P1: a load that delivered its data may still read the folder's files for its cache write
    (the shots it reused from RAM): it stops, saying why; a save the user asked for goes on."""
    service = frozen_service(monkeypatch)
    cache = get_folder_cache(service)
    try:
        ordinary, saving = str(tmp_path / "run_1"), str(tmp_path / "run_2")
        assert cache.submit("tab", 0, ordinary, "load", {})
        assert cache.save("live", saving, {})
        ended: list[tuple[str, str]] = []
        cache.saveEnded.connect(lambda folder, outcome: ended.append((folder, outcome)))
        requests = {}
        for path in (ordinary, saving):
            request = next(r for r in service.pending if r.path == path)
            service.pending.remove(request)
            service.active.append(request)
            service.resultReady.emit(request, {"kind": "shot", "shot": 1, "array": np.ones((1, 3))})
            service.resultReady.emit(request, {"kind": "loaded", "signature": "s", "files": 1, "rows": 1,
                                               "bytes": 24, "problematic": [], "disk_cache_pending": True})
            request.completed = True  # (As the service marks a load that sent ``loaded``.)
            requests[path] = request
        assert sorted(cache.quit_saves()) == [ordinary, saving]
        cache.set_offline(True)
        assert requests[ordinary].cancelled.is_set() and requests[ordinary] not in service.active
        assert not requests[saving].cancelled.is_set() and requests[saving] in service.active
        assert ended == [(ordinary, "failed")] and cache.quit_saves() == [saving]
        assert cache.cache_status(ordinary).error == IOService.OFFLINE_SAVE_STOPPED
        assert cache.dataset(ordinary, "s") is not None  # Its data stays in RAM.
    finally:
        service.active.clear()
        service.shutdown()


def test_a_save_asked_for_before_going_offline_still_runs_after_the_load_it_waited_for(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """P2: Live's stop-save waiting for another load of the folder keeps its authorization; a save
    asked for once offline is refused."""
    service = frozen_service(monkeypatch)
    cache = get_folder_cache(service)
    try:
        path = str(tmp_path / "run")
        assert cache.submit("other-tab", 0, path, "load", {})
        assert cache.save("live-stop-save", path, {}) and path in cache._deferred_saves
        events: list[str] = []
        cache.resultReady.connect(lambda request, event: events.append(event["kind"])
                                  if request.owner == "live-stop-save" else None)
        cache.set_offline(True)  # Cancels the other tab's load: the save it waited for starts.
        qtbot.waitUntil(lambda: any(r.operation == "load" and r.payload.get("save") for r in service.pending))
        assert "offline" not in events and cache.quit_saves() == [path]
        assert cache.save("later", str(tmp_path / "other"), {})  # Asked for offline: answered offline.
        assert not any(r.path == str(tmp_path / "other") for r in service.pending)
    finally:
        service.shutdown()


def test_a_volume_or_share_mounted_above_a_hint_wins_over_it() -> None:
    """P2: a share mounted at /Volumes/lab now owns /Volumes/lab/subdir, even if a share was mounted
    at subdir last time; a system mount above (a tmpfs /tmp) doesn't take a hint's place."""
    from helab.io_ops import stores
    from helab.utils.cache_paths import Mount
    from helab.utils.data_roots import LocalVolumes

    class Hints:
        def mount_hints(self) -> dict[str, str]:
            return {"/Volumes/lab/subdir": "smb://old-server/old-share", "/tmp/shares/data": "smb://server/data"}
    system = Mount("/dev/disk3s1", "/", "apfs")
    lab = Mount("//new-server/lab", "/Volumes/lab", "smbfs", True)
    tmp = Mount("tmpfs", "/tmp", "tmpfs")
    paths, _ = stores._offline_mounts(cast(Any, Hints()), [system, lab, tmp], LocalVolumes([]))
    assert paths.key("/Volumes/lab/subdir/run") == "smb://new-server/lab/subdir/run"
    assert paths.key("/tmp/shares/data/run") == "smb://server/data/run"


@pytest.mark.parametrize("known", [True, False])
def test_a_disk_mounted_anywhere_wins_over_a_hint_below_it(known: bool) -> None:
    """Vernier, review round 2: a disk at a custom mount point (/srv/lab) is a volume too, known by
    its volume ID now or by its block device; the old share hinted at /srv/lab/subdir doesn't take
    its folders. A pseudo filesystem's hints below stay."""
    from helab.io_ops import stores
    from helab.utils.cache_paths import Mount
    from helab.utils.data_roots import DataRoots, LocalVolumes, RootLocation

    class Hints:
        def mount_hints(self) -> dict[str, str]:
            return {"/srv/lab/subdir": "smb://old-server/old-share", "/run/user/1000/share": "smb://server/data"}
    disk = Mount("/dev/sdb1" if not known else "LABDISK", "/srv/lab", "ext4")
    pseudo = Mount("tmpfs", "/run/user/1000", "tmpfs")
    volumes = LocalVolumes([(disk, "new-disk")] if known else [])
    paths, local = stores._offline_mounts(cast(Any, Hints()), [Mount("/dev/sda1", "/", "ext4"), disk, pseudo],
                                          volumes)
    assert paths.key("/srv/lab/subdir/run") == "/srv/lab/subdir/run"  # Not the old share's.
    assert paths.key("/run/user/1000/share/run") == "smb://server/data/run"
    if known:
        roots = [RootLocation("smb://old-server/old-share", "old-root"), RootLocation("vol://new-disk", "new-root")]
        resolver = DataRoots(paths, roots, local_location=local.location, local_source=local.source)
        assert resolver.key("/srv/lab/subdir/run") == "root://new-root/subdir/run"


def test_work_online_cancels_a_saved_listing_in_flight_and_lists_the_folder_anew(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """P2: an offline listing still running when Work Online starts never answers its tab's Refresh:
    it is cancelled quietly, and the folder is listed from the source."""
    from helab.models.SnapshotFileSystemModel import SnapshotFileSystemModel
    service = frozen_service(monkeypatch)
    cache = get_folder_cache(service)
    model = SnapshotFileSystemModel(service=service)
    try:
        cache.set_offline(True)
        path = str(tmp_path / "data")
        model.setRootPath(path)
        before = next(r for r in service.pending if r.operation == "saved_list")
        cache.set_offline(False)
        model.refresh()
        assert [r.operation for r in service.pending if r.path == path] == ["list"]
        assert before.cancelled.is_set()
        assert model.root is not None and model.root.state != "cancelled" and not model.root.error
        # Its answer, late, is dropped.
        service.resultReady.emit(before, {"kind": "entries", "entries": [{"path": path + "/stale", "name": "stale"}]})
        service.resultReady.emit(before, {"kind": "status", "offline": True, "listed": True, "listed_at": 1000.0,
                                          "details": False, "empty": False, "has_dirs": True})
        service.resultReady.emit(before, {"kind": "done"})
        qtbot.wait(50)
        assert model.root.offline_listed_at is None and not model.root.children
    finally:
        model.close_cleanup()
        service.shutdown()


@pytest.mark.parametrize("current", [
    ("new-server:/export", "nfs4"),  # psutil: no "remote" option, no volume ID, no /dev source (round 3).
    ("sshfs#lab@new-server:/data", "fuse.sshfs"),
    ("//new-server/lab", "cifs"),
    ("map auto_lab", "autofs"),
], ids=["nfs4", "fuse", "cifs", "autofs"])
def test_any_mount_at_a_custom_path_wins_over_a_hint_below_it_unless_transparent(current: tuple[str, str]) -> None:
    """Vernier, review round 3, and the rule it asked for: whatever is mounted at or above a hint's
    path now wins, whatever its filesystem; only the system volume and pseudo filesystems (tmpfs at
    /tmp or /run/user…) let the hints below them be used."""
    from helab.io_ops import stores
    from helab.utils.cache_paths import Mount, UnresolvedRemotePath
    from helab.utils.data_roots import LocalVolumes

    class Hints:
        def mount_hints(self) -> dict[str, str]:
            return {"/srv/lab/subdir": "smb://old-server/old-share", "/tmp/shares/a": "smb://server/a",
                    "/run/user/1000/b": "smb://server/b"}
    source, fstype = current
    mounts = [Mount("/dev/sda1", "/", "ext4"), Mount(source, "/srv/lab", fstype),
              Mount("tmpfs", "/tmp", "tmpfs"), Mount("tmpfs", "/run/user/1000", "tmpfs")]
    paths, _ = stores._offline_mounts(cast(Any, Hints()), mounts, LocalVolumes([]))
    try:
        key = paths.key("/srv/lab/subdir/run")
    except UnresolvedRemotePath:
        key = ""  # (A network mount without an SMB share: no disk cache, never the old share's.)
    assert not key.startswith("smb://old-server")
    assert paths.key("/tmp/shares/a/run") == "smb://server/a/run"
    assert paths.key("/run/user/1000/b/run") == "smb://server/b/run"
