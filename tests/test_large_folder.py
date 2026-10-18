"""Roadmap S8: the large-folder warning. Automatic loads of large folders never start; deliberate
ones ask first; above 30% of RAM nothing loads, from the source or the disk cache."""
from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from helab import io_helper
from helab.io_helper import list_folder, load, read_cached
from helab.utils import large_folder
from helab.utils.cache_store import CacheStore, DatasetRow
from helab.utils.folder_cache import Dataset, FolderCache, get_folder_cache
from helab.utils.io_service import IORequest, IOService
from helab.views.FolderDetailsPanel import FolderDetailsPanel
from helab.views.FolderExplorer import AMBER, FolderExplorer
from helab.views.LargeFolderDialog import LargeFolderDialog

def data_folder(tmp_path: Path, shots: int = 2) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    for shot in range(1, shots + 1):
        (source / f"d{shot}.txt").write_text("raw\n")
        (source / f"d_txy_forc{shot}.txt").write_text(f"{shot},2,3\n{shot},5,6\n")
    return source


def options_for(tmp_path: Path) -> dict[str, Any]:
    return {"directory": str(tmp_path / "caches" / "store-v2")}


def run_load(source: Path, tmp_path: Path, options: dict[str, Any] | None, **kwargs: Any) -> list[dict[str, Any]]:
    output = tmp_path / f"artifacts-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    load(str(source), str(output), events.append, options, **kwargs)
    return events


def dataset_row(options: dict[str, Any], path: str) -> DatasetRow:
    with io_helper._cache_store(options["directory"], [path]) as store:
        found = store.read_dataset_row(path)
    assert found.value is not None
    return found.value


# Thresholds used throughout: warn above 10 kB, refuse above 30 kB.
LIMITS = {"warn": 10_000, "refuse": 30_000}


def test_thresholds_warn_above_the_ram_budget_or_10_percent_and_refuse_above_30() -> None:
    assert large_folder.limits(ram_budget=16 << 30, total=128 << 30) == {
        "warn": int(12.8 * (1 << 30)), "refuse": int(0.3 * (128 << 30))}
    assert large_folder.limits(ram_budget=1 << 30, total=128 << 30)["warn"] == 1 << 30
    assert large_folder.verdict(None, LIMITS) == ""
    assert large_folder.verdict(10_000, LIMITS) == ""
    assert large_folder.verdict(10_001, LIMITS) == "large"
    assert large_folder.verdict(10_001, LIMITS, allow_large=True) == ""
    assert large_folder.verdict(30_001, LIMITS, allow_large=True) == "refused"
    # The estimate is the size on disk, unscaled, of the shots not already in RAM.
    assert large_folder.estimate([[1, 100, 0], [2, 50, 0]], held=[2]) == 100


# The helper: it stops before reading, after its scan phase has been saved.

def test_a_large_load_stops_after_its_scan_phase_unless_allowed(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    options = options_for(tmp_path)
    size = sum(f.stat().st_size for f in source.glob("d_txy_forc*.txt"))
    tight = {"warn": size - 1, "refuse": 10 * size}
    events = run_load(source, tmp_path, options, limits=tight)
    kinds = [event["kind"] for event in events]
    assert "scan_summary" in kinds and "loaded" not in kinds and "file_started" not in kinds
    stopped = next(event for event in events if event["kind"] == "too_large")
    assert stopped == {"kind": "too_large", "estimate": size, "refused": False}
    # Its scan phase was saved first: the size is known next time without listing.
    with io_helper._cache_store(options["directory"], [str(source)]) as store:
        summary = store.read_records("summaries", [str(source)])[str(source)].value
    assert summary is not None and summary["files"]["txy"]["bytes"] == size
    # Allowed (the user said yes): it loads, and saves the sizes with the dataset.
    loaded = next(e for e in run_load(source, tmp_path, options, limits=tight, allow_large=True)
                  if e["kind"] == "loaded")
    assert loaded["files"] == 2
    info = dataset_row(options, str(source))["info"]
    assert info["txy_bytes"] == size and info["ram_bytes"] == 4 * 3 * 8
    # Above the refusal nothing overrides it.
    refused = run_load(source, tmp_path, options, limits={"warn": 0, "refuse": size - 1}, allow_large=True)
    assert [e for e in refused if e["kind"] == "too_large"] == [{"kind": "too_large", "estimate": size,
                                                                "refused": True}]
    # Without limits (an older caller) only the 30% refusal applies: the old 1 GiB limit is gone.
    assert any(e["kind"] == "loaded" for e in run_load(source, tmp_path, options))


@pytest.mark.parametrize("newline", [None, "\n", "\r\n"], ids=["native", "lf", "crlf"])
def test_the_check_of_data_already_in_ram_counts_only_what_it_adds(tmp_path: Path, newline: str | None) -> None:
    source = data_folder(tmp_path)
    options = options_for(tmp_path)
    run_load(source, tmp_path, options)
    row = dataset_row(options, str(source))
    memory = [list(entry) for entry in row["fingerprint"]]
    tiny = {"warn": 0, "refuse": 1 << 40}
    # The one-stat fast path still answers: nothing new is read.
    fast = next(e for e in run_load(source, tmp_path, options, memory=memory, limits=tiny,
                                    base_signature=row["info"]["signature"]) if e["kind"] in ("loaded", "too_large"))
    assert fast["kind"] == "loaded" and fast.get("unchanged") is True
    # A full check holding every shot adds nothing either.
    full = [e["kind"] for e in run_load(source, tmp_path, options, memory=memory, limits=tiny)]
    assert "loaded" in full and "too_large" not in full
    # A new shot is what it would add.
    new_file = source / "d_txy_forc3.txt"
    new_file.write_text("3,2,3\n", newline=newline)
    added = next(e for e in run_load(source, tmp_path, options, memory=memory, limits=tiny)
                 if e["kind"] in ("loaded", "too_large"))
    assert added == {"kind": "too_large", "estimate": new_file.stat().st_size, "refused": False}


def test_a_load_doesnt_unpack_a_cached_dataset_larger_than_the_folder_now_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = data_folder(tmp_path, shots=3)
    options = options_for(tmp_path)
    run_load(source, tmp_path, options)
    cached = sum(f.stat().st_size for f in source.glob("d_txy_forc*.txt"))
    for shot in (2, 3):
        (source / f"d_txy_forc{shot}.txt").unlink()
    left = (source / "d_txy_forc1.txt").stat().st_size
    assert left < cached

    def unpack(packed: bytes) -> Any:
        raise AssertionError("the whole cached dataset was unpacked")
    monkeypatch.setattr("helab.utils.cache_store.unpack_dataset", unpack)
    # (Shots 2 and 3 were deleted: loaded as the folder is now, as the user chose.)
    events = run_load(source, tmp_path, options, limits={"warn": left, "refuse": 1 << 40}, allow_missing=True)
    loaded = next(e for e in events if e["kind"] == "loaded")
    assert loaded["files"] == 1 and loaded["cache_reason"] == "Cached dataset too large to reuse"


def test_a_large_cached_dataset_isnt_read_unless_allowed_and_listings_carry_its_size(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    options = options_for(tmp_path)
    run_load(source, tmp_path, options)
    size = sum(f.stat().st_size for f in source.glob("d_txy_forc*.txt"))
    output = tmp_path / "out"
    output.mkdir()
    events: list[dict[str, Any]] = []
    read_cached(str(source), str(output), events.append, options, limits={"warn": size - 1, "refuse": 1 << 40})
    assert events == [{"kind": "too_large", "estimate": size, "refused": False}] and not any(output.iterdir())
    events.clear()
    read_cached(str(source), str(output), events.append, options, limits={"warn": size - 1, "refuse": 1 << 40},
                allow_large=True)
    loaded = next(e for e in events if e["kind"] == "loaded")
    assert loaded["cache_info"]["txy_bytes"] == size
    # The dataset read is checked too: it may have been replaced since its record was checked.
    real = CacheStore.read_dataset_row
    calls: list[str] = []

    def smaller(self: CacheStore, folder: str) -> Any:
        found = real(self, folder)
        calls.append(folder)
        if len(calls) == 1:  # The record checked first, before the dataset was replaced.
            assert found.value is not None
            found.value["fingerprint"] = [[1, 1, 0]]
        return found
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(CacheStore, "read_dataset_row", smaller)
        events.clear()
        read_cached(str(source), str(output), events.append, options, limits={"warn": size - 1, "refuse": 1 << 40})
    assert events == [{"kind": "too_large", "estimate": size, "refused": False}]
    # A listing sends each subfolder's cached size, so the app decides before submitting;
    # for a dataset saved before S8 it is summed from the fingerprint.
    older = tmp_path / "older"
    older.mkdir()
    with io_helper._cache_store(options["directory"], [str(older)]) as store:
        store.save_dataset(str(older), store.write_dataset_file(b"x"), {
            "ram_bytes": 7, "rows": 1, "shots": 2, "fingerprint": [[1, 300, 0], [2, 200, 0]], "problematic": [],
            "info": {"saved_at": time.time(), "signature": "s"}}, store.start_dataset_job(str(older)))
    listed: list[dict[str, Any]] = []
    list_folder(str(tmp_path), listed.append, options)
    entry = next(e for event in listed if event["kind"] == "entries" for e in event["entries"]
                 if e["path"] == str(source))
    assert entry["cache_info"]["txy_bytes"] == size and entry["cache_info"]["ram_bytes"] == 4 * 3 * 8
    old = next(e for event in listed if event["kind"] == "entries" for e in event["entries"] if e["path"] == str(older))
    assert old["cache_info"]["txy_bytes"] == 500 and old["cache_info"]["ram_bytes"] == 7


# The tab.

def frozen(monkeypatch: pytest.MonkeyPatch) -> tuple[IOService, FolderCache]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    cache = get_folder_cache(service)
    # 100 kB of RAM and a 50 kB budget: warn above 10 kB, refuse above 30 kB.
    cache.total_ram, cache.max_data_bytes = 100_000, 50_000
    assert cache.large_limits() == LIMITS
    return service, cache


def scan(cache: FolderCache, path: str, children: list[str] | None = None, txy_bytes: int | None = None,
         data: bool = True) -> None:
    job = cache.jobs[("list" if ("list", path) in cache.jobs else "scan", path)]
    request = next(r for r in cache.service.pending if r.owner == job.owner)
    cache.service.resultReady.emit(request, {"kind": "entries", "entries": [
        {"path": p, "modified": None} for p in (children or [])]})
    files = {"txy": {"count": 1, **({} if txy_bytes is None else {"bytes": txy_bytes})}}
    cache.service.resultReady.emit(request, {"kind": "status", "status": "ok", "count": 1, "raw": [1], "details": True,
                                             "txy": [1] if data else [], "files": files if data else {},
                                             "modified": 0, "signature": "v1", "scanned_at": time.time()})
    cache.service.resultReady.emit(request, {"kind": "done"})
    cache.service.pending.remove(request)


def request_for(service: IOService, operation: str, path: str) -> IORequest:
    return next(r for r in reversed(service.pending) if r.operation == operation and r.path == path)


def stop(service: IOService, request: IORequest, estimate: int, refused: bool = False) -> None:
    for event in ({"kind": "too_large", "estimate": estimate, "refused": refused}, {"kind": "done"}):
        service.resultReady.emit(request, event)
    service.pending.remove(request)


def make_explorer(qtbot: QtBot, service: IOService, cache: FolderCache, root: str,
                  folders: dict[str, int | None]) -> tuple[FolderExplorer, list[tuple[str, int]], list[bool]]:
    explorer = FolderExplorer(root, root, root, [0, 4, 5])
    qtbot.addWidget(explorer)
    explorer.selectionPathChanged.connect(lambda p: explorer.load_to_ram_cache(p))
    asked: list[tuple[str, int]] = []
    answers: list[bool] = []

    def confirm(path: str, estimate: int) -> bool:
        asked.append((path, estimate))
        return answers.pop(0) if answers else False
    explorer.confirm_large = confirm
    qtbot.waitUntil(lambda: ("list", root) in cache.jobs)
    paths = [os.path.join(root, name) for name in folders]
    scan(cache, root, paths, data=False)
    qtbot.waitUntil(lambda: all(path in explorer.model.nodes for path in paths))
    for name, size in folders.items():
        path = os.path.join(root, name)
        explorer.model.request_scan(path)
        scan(cache, path, txy_bytes=size)
    qtbot.waitUntil(lambda: all(explorer.model.nodes[path].report is not None for path in paths))
    return explorer, asked, answers


def select(qtbot: QtBot, explorer: FolderExplorer, path: str) -> None:
    explorer.tree.setCurrentIndex(explorer.model.path_index(path))
    qtbot.waitUntil(lambda: explorer.selected_path_globally == path)


def test_automatic_loads_of_large_folders_never_start_and_offer_load_anyway(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer, asked, answers = make_explorer(qtbot, service, cache, root, {"big": 20_000, "small": 5_000})
    big, small = os.path.join(root, "big"), os.path.join(root, "small")
    try:
        assert cache.large_estimate(big) == 20_000
        select(qtbot, explorer, big)
        # Known from its saved summary: no helper starts, no dialog.
        assert ("load", big) not in cache.jobs and not explorer.loading and not asked
        assert explorer.large_state(big) == (20_000, False)
        assert "Not loaded · Large folder · ~19.5 kB in RAM" in explorer.folder_summary_label.text()
        assert AMBER in explorer.folder_summary_label.styleSheet()
        assert explorer.retry_button.isVisibleTo(explorer) and explorer.retry_button.text() == "Load anyway…"
        assert "Large folder · ~19.5 kB in RAM · right-click › Load data" in str(
            explorer.model.data(explorer.model.path_index(big), 3))
        assert explorer.activity_brief == "Large folder · ~19.5 kB in RAM"
        panel = FolderDetailsPanel(explorer)
        panel.show_explorer(explorer, service)
        assert panel.text("state") == "Large folder · ~19.5 kB in RAM · Load anyway…"
        assert AMBER in panel.values["state"].styleSheet()
        # Load anyway… asks; declined, nothing starts.
        explorer.retry_button.click()
        assert asked == [(big, 20_000)] and ("load", big) not in cache.jobs
        # Accepted: it loads, saying so to the helper.
        answers.append(True)
        explorer.retry_button.click()
        request = request_for(service, "load", big)
        assert request.payload["allow_large"] is True and request.payload["limits"] == LIMITS
        assert request.payload["deliberate"] is True
        assert explorer.large_state(big) is None
        # The yes was for that load: if it fails, Retry asks again.
        service.resultReady.emit(request, {"kind": "error", "message": "Read failed — Retry"})
        explorer.retry_button.click()
        assert len(asked) == 3 and ("load", big) not in cache.jobs
        asked.pop()
        service.pending.remove(request)
        # A small folder loads as usual, without the yes.
        select(qtbot, explorer, small)
        assert request_for(service, "load", small).payload["allow_large"] is False
        # Saying yes once doesn't let later automatic loads through.
        cache.cancel(explorer.model.owner)
        select(qtbot, explorer, big)
        assert ("load", big) not in cache.jobs and explorer.large_state(big) == (20_000, False)
        assert len(asked) == 2
        # The yes lasts until that load ends; its data, now in RAM, then shows without asking.
        answers.append(True)
        explorer.retry_button.click()
        request = request_for(service, "load", big)
        for event in ({"kind": "loaded", "signature": "v1", "files": 1, "rows": 2, "bytes": 48,
                       "fingerprint": [[1, 20_000, 0]], "problematic": []}, {"kind": "done"}):
            service.resultReady.emit(request, event)
        service.pending.remove(request)
        qtbot.waitUntil(lambda: explorer.folder_opened_path == big)
        assert explorer.large_state(big) is None
        select(qtbot, explorer, small)
        cache.cancel(explorer.model.owner)
        select(qtbot, explorer, big)
        assert explorer.folder_opened_path == big and explorer.large_state(big) is None and len(asked) == 3
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_above_30_percent_of_ram_nothing_loads_even_deliberately(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer, asked, _ = make_explorer(qtbot, service, cache, root, {"huge": 40_000})
    huge = os.path.join(root, "huge")
    try:
        select(qtbot, explorer, huge)
        assert explorer.large_state(huge) == (40_000, True)
        assert "Too large to load · ~39.1 kB in RAM, over 30% of RAM" in explorer.folder_summary_label.text()
        assert not explorer.retry_button.isVisibleTo(explorer)
        assert not explorer.load_to_ram_cache(huge, dwell=False, explicit=True)
        assert not explorer.queue_load(huge)
        assert ("load", huge) not in cache.jobs and not asked
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_a_size_found_by_the_load_itself_stops_it_and_a_deliberate_load_then_asks(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer, asked, answers = make_explorer(qtbot, service, cache, root, {"a": None, "b": None})
    a, b = os.path.join(root, "a"), os.path.join(root, "b")
    try:
        # Only listed: the size is unknown, so the load starts and its helper stops it.
        select(qtbot, explorer, a)
        stop(service, request_for(service, "load", a), 20_000)
        assert not explorer.loading and explorer.large_state(a) == (20_000, False)
        qtbot.wait(10)
        assert not asked  # Automatic: no dialog.
        # Deliberate: stopped the same way, then asked, then loaded with the yes.
        answers.append(True)
        explorer.queue_load(b)
        stop(service, request_for(service, "load", b), 25_000)
        qtbot.waitUntil(lambda: asked == [(b, 25_000)])
        assert request_for(service, "load", b).payload["allow_large"] is True
        # The yes went with that request only: selecting b doesn't load it automatically.
        cache.cancel(explorer.bg_owner)
        qtbot.waitUntil(lambda: b not in explorer._bg_paths)
        select(qtbot, explorer, b)
        assert ("load", b) not in cache.jobs and explorer.large_state(b) == (25_000, False)
        select(qtbot, explorer, a)
        # A deliberate load of the selected folder, stopped and then declined...
        explorer.model.request_scan(a, force=True)
        scan(cache, a)  # Measured again, without a size: the earlier stop no longer counts.
        explorer.load_to_ram_cache(a, dwell=False, explicit=True)
        stop(service, request_for(service, "load", a), 22_000)
        qtbot.waitUntil(lambda: len(asked) == 2)
        # ...doesn't make a later automatic load of it ask.
        explorer.model.request_scan(a, force=True)
        scan(cache, a)
        explorer.load_to_ram_cache(a)
        stop(service, request_for(service, "load", a), 22_000)
        qtbot.wait(10)
        assert len(asked) == 2
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_a_large_cached_folder_doesnt_open_automatically(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer, asked, answers = make_explorer(qtbot, service, cache, root,
                                             {"cached": None, "other": 1000, "shrank": 1000, "third": None})
    cached, other, shrank, third = (os.path.join(root, name) for name in ("cached", "other", "shrank", "third"))
    try:
        # Their cached datasets' sizes came with the listing.
        for path, size in ((cached, 20_000), (shrank, 40_000)):
            cache._observe_cache(path, {"disk_cached": True, "cache_info": {
                "saved_at": time.time() - 60, "signature": "s", "txy_bytes": size, "ram_bytes": size // 2}})
        # Too large to read whole: not read; the load decides by the folder's own size.
        select(qtbot, explorer, cached)
        assert ("cached", cached) not in cache.jobs
        stop(service, request_for(service, "load", cached), 20_000)
        assert explorer.large_state(cached) == (20_000, False) and not asked
        # Opened deliberately once...
        answers.append(True)
        explorer.retry_button.click()
        assert asked == [(cached, 20_000)]
        read = request_for(service, "cached", cached)
        assert read.payload["allow_large"] is True and read.payload["deliberate"] is True
        # Its check runs beside it, under the same yes: it counts the cached shots as held, so
        # it adds only what changed (the earlier stop counted the whole folder).
        check = request_for(service, "load", cached)
        assert check.payload["deliberate"] is True and check.payload["allow_large"] is True
        assert check.payload["cache_base"] is True
        for event in ({"kind": "loaded", "signature": "s", "files": 1, "rows": 2, "bytes": 48, "verified": False,
                       "fingerprint": [[1, 20_000, 0]], "problematic": []}, {"kind": "done"}):
            service.resultReady.emit(read, event)
        service.pending.remove(read)
        assert request_for(service, "load", cached) is check
        assert explorer.large_state(cached) is None
        cache.cancel(explorer.model.owner)
        # ...then another folder; its data leaves RAM (a large folder is over the RAM budget).
        select(qtbot, explorer, other)
        cache.cancel(explorer.model.owner)
        for key in [key for key in cache.datasets if key[0] == cached]:
            del cache.datasets[key]
        # Back to it: never opened automatically from the disk cache.
        select(qtbot, explorer, cached)
        assert ("cached", cached) not in cache.jobs and ("load", cached) not in cache.jobs and len(asked) == 1
        # An old, larger cache doesn't block a folder that is small now: its load reads the files.
        select(qtbot, explorer, shrank)
        assert ("cached", shrank) not in cache.jobs and request_for(service, "load", shrank).payload["allow_large"] is False
        assert explorer.large_state(shrank) is None
        cache.cancel(explorer.model.owner)
        # The helper stops a cached read the app didn't know was large; no load follows it.
        cache._observe_cache(third, {"disk_cached": True, "cache_info": {"saved_at": time.time(), "signature": "s"}})
        select(qtbot, explorer, third)
        stop(service, request_for(service, "cached", third), 20_000)
        qtbot.wait(10)
        assert explorer.large_state(third) == (20_000, False) and ("load", third) not in cache.jobs and len(asked) == 1
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_queue_mode_skips_a_large_folder_without_asking(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer, asked, _ = make_explorer(qtbot, service, cache, root, {"a": None, "b": None})
    a, b = os.path.join(root, "a"), os.path.join(root, "b")
    explorer.load_mode = "queue"
    try:
        select(qtbot, explorer, a)
        assert ("load", a) in cache.jobs
        select(qtbot, explorer, b)  # a goes on in the background.
        qtbot.waitUntil(lambda: a in explorer._bg_paths)
        stop(service, request_for(service, "load", a), 20_000)
        assert a not in explorer._bg_paths and explorer.model.large_paths[a] == (20_000, False)
        qtbot.wait(10)
        assert not asked
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_cancel_drops_a_large_folder_question_scheduled_before_it(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer, asked, answers = make_explorer(qtbot, service, cache, root, {"a": None, "b": None, "c": 1000})
    a, b, c = (os.path.join(root, name) for name in ("a", "b", "c"))
    try:
        select(qtbot, explorer, c)
        explorer.queue_load(a)
        explorer.queue_load(b)
        answers.append(True)
        # a stops as large and its question is scheduled; Cancel comes first.
        stop(service, request_for(service, "load", a), 20_000)
        explorer.cancel_loading()
        qtbot.wait(20)
        assert not asked and ("load", a) not in cache.jobs and not explorer._bg_paths
        assert explorer.large_state(a) == (20_000, False)  # Still says why, for Load anyway… later.
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_what_a_load_would_add_to_data_in_ram_asks_too(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer, asked, answers = make_explorer(qtbot, service, cache, root, {"a": 20_000, "b": None})
    b = os.path.join(root, "b")
    try:
        # b's earlier data is in RAM: only what a load would add counts, which its helper finds.
        cache.datasets[(b, "v0", 0)] = Dataset(b, "v0", {1: np.zeros((1, 3))}, {"bytes": 24, "files": 1}, 0)
        explorer.queue_load(b)
        first = request_for(service, "load", b)
        assert first.payload["allow_large"] is False and not asked
        answers.append(True)
        stop(service, first, 15_000)
        # Asked, then loaded with the yes; not tried again and again without asking.
        qtbot.waitUntil(lambda: asked == [(b, 15_000)])
        assert request_for(service, "load", b).payload["allow_large"] is True
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_an_automatic_update_too_large_to_load_says_so_beside_the_shown_data(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer, asked, _ = make_explorer(qtbot, service, cache, root, {"a": None, "b": None})
    a, b = os.path.join(root, "a"), os.path.join(root, "b")
    try:
        # b's earlier data is still in RAM.
        cache.datasets[(b, "v0", 0)] = Dataset(b, "v0", {1: np.zeros((1, 3))}, {"bytes": 24, "files": 1}, 0)
        select(qtbot, explorer, b)
        qtbot.waitUntil(lambda: explorer.folder_opened_path == b)
        # "Load data" while its check already runs starts nothing new...
        explorer.queue_load(b)
        check = request_for(service, "load", b)
        assert check.payload["deliberate"] is False
        # ...so when the check finds a large update, it stops without asking.
        stop(service, check, 15_000)
        qtbot.wait(10)
        # (The folder changed since: the data stays shown as previous data.)
        shown = explorer.displayed_dataset
        assert not asked and shown is not None and shown.path == b and not explorer.loading
        explorer._update_activity()
        assert "Large folder · ~14.6 kB in RAM" in explorer.folder_summary_label.text()
        assert explorer.retry_button.isVisibleTo(explorer) and explorer.retry_button.text() == "Load anyway…"
        panel = FolderDetailsPanel(explorer)
        panel.show_explorer(explorer, service)
        assert panel.text("state").endswith(" · Update not loaded: Large folder · ~14.6 kB in RAM · Load anyway…")
        assert AMBER in panel.values["state"].styleSheet()
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_a_fresh_size_replaces_an_earlier_stop(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen(monkeypatch)
    root = str(tmp_path)
    explorer, asked, _ = make_explorer(qtbot, service, cache, root, {"a": None, "other": 1000})
    a, other = os.path.join(root, "a"), os.path.join(root, "other")
    try:
        select(qtbot, explorer, a)
        stop(service, request_for(service, "load", a), 40_000, refused=True)
        assert explorer.large_state(a) == (40_000, True)
        select(qtbot, explorer, other)
        cache.cancel(explorer.model.owner)
        select(qtbot, explorer, a)
        assert ("load", a) not in cache.jobs  # Still the newest word.
        # Measured again, smaller: it loads.
        explorer.model.request_scan(a, force=True)
        scan(cache, a, txy_bytes=1000)
        select(qtbot, explorer, other)
        cache.cancel(explorer.model.owner)
        select(qtbot, explorer, a)
        assert ("load", a) in cache.jobs and explorer.large_state(a) is None
    finally:
        explorer.close_cleanup()
        service.shutdown()


def test_the_dialog_enables_load_anyway_only_once_understood(qtbot: QtBot) -> None:
    dialog = LargeFolderDialog("/data/run", 2 << 30, 16 << 30, 128 << 30)
    qtbot.addWidget(dialog)
    assert "run would take about 2.0 GB in RAM" in dialog.text.text()
    assert "RAM budget 16.0 GB · this computer has 128 GB of RAM" in dialog.text.text()
    assert "2–3×" in dialog.text.text()
    assert not dialog.load_button.isEnabled()
    dialog.understood.setChecked(True)
    assert dialog.load_button.isEnabled()
