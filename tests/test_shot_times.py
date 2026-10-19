"""Shot times (D7): a shot's time is its raw ``d<N>.txt`` file's mtime, found by the helper's own
listing and kept with the dataset (RAM, disk cache, Live); without a raw file it is the TXY file's
mtime, flagged as a fallback."""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import time
from typing import Any

import numpy as np
import pytest

from helab import io_helper
from helab.analysis.dataset_view import build_view
from helab.io_helper import live_check, load, read_cached, save_held
from helab.utils.folder_cache import Dataset, FolderCache, dataset_raw_times
from helab.utils.io_service import IOService

NS = 1_000_000_000
# The raw files are written long before their TXY files, which a converter wrote all at once.
RAW_AT = 1_700_000_000
CONVERTED_AT = RAW_AT + 3600


def set_mtime(file: Path, seconds: float) -> None:
    os.utime(file, ns=(int(seconds * NS), int(seconds * NS)))


def write_shot(folder: Path, shot: int, *, raw: bool = True, converted_at: float = CONVERTED_AT) -> None:
    txy = folder / f"d_txy_forc{shot}.txt"
    txy.write_text(f"{shot},2,3\n{shot},4,5\n")
    set_mtime(txy, converted_at)
    if raw:
        file = folder / f"d{shot}.txt"
        file.write_text("raw\n")
        set_mtime(file, raw_at(shot))


def raw_at(shot: int) -> float:
    return RAW_AT + 10 * shot


def age_folder(folder: Path) -> None:
    when = time.time() - 60
    os.utime(folder, (when, when))


@pytest.fixture
def run(tmp_path: Path) -> Path:
    folder = tmp_path / "run"
    folder.mkdir()
    write_shot(folder, 1)
    write_shot(folder, 2)
    write_shot(folder, 3, raw=False)
    age_folder(folder)
    return folder


def cache_options(tmp_path: Path) -> dict[str, Any]:
    return {"directory": str(tmp_path / "disk-cache")}


def run_load(run: Path, tmp_path: Path, **kwargs: Any) -> list[dict[str, Any]]:
    output = tmp_path / f"load-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    load(str(run), str(output), events.append, cache_options(tmp_path), **kwargs)
    return events


def run_cached(run: Path, tmp_path: Path) -> list[dict[str, Any]]:
    output = tmp_path / f"cached-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    read_cached(str(run), str(output), events.append, cache_options(tmp_path))
    return events


def loaded(events: list[dict[str, Any]]) -> dict[str, Any]:
    found = [event for event in events if event["kind"] == "loaded"]
    assert found, events
    return found[0]


def times(event: dict[str, Any]) -> dict[int, float]:
    return {shot: modified / NS for shot, modified in event["raw_times"]}


def dataset(path: Path, event: dict[str, Any], events: list[dict[str, Any]],
            base: Dataset | None = None) -> Dataset:
    """The dataset the app builds from a load's events (``FolderCache``), with its shot times."""
    data = {shot: base.data[shot] for shot in event.get("memory_shots", ())} if base else {}
    sent: dict[int, int] = {}
    for item in events:
        if item["kind"] == "shot":
            data[item["shot"]] = np.load(item["artifact"])
            if "raw_mtime" in item:
                sent[item["shot"]] = item["raw_mtime"]
    metadata = {**event, "raw_times": dataset_raw_times(base, event, sent)}
    return Dataset(str(path), str(event["signature"]), dict(sorted(data.items())), metadata, 0)


@pytest.fixture
def shot_time_stats(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The raw files stat'ed for shot times."""
    names: list[str] = []
    real = io_helper._raw_mtime

    def counted(entry: os.DirEntry[str] | None, reason: str) -> int | None:
        if entry is not None:
            names.append(entry.name)
        return real(entry, reason)

    monkeypatch.setattr(io_helper, "_raw_mtime", counted)
    return names


def test_a_shots_time_is_its_raw_files_mtime_else_its_txy_files(run: Path, tmp_path: Path) -> None:
    events = run_load(run, tmp_path)
    event = loaded(events)
    assert times(event) == {1: raw_at(1), 2: raw_at(2)}
    assert {item["shot"]: item.get("raw_mtime") for item in events if item["kind"] == "shot"} == {
        1: raw_at(1) * NS, 2: raw_at(2) * NS, 3: None}
    view = build_view(dataset(run, event, events))
    assert view.shot_times() == {1: raw_at(1), 2: raw_at(2), 3: CONVERTED_AT}
    assert view.fallback_times() == (3,) and view.fallback_times([1, 2]) == ()
    assert view.shot_time(99) is None
    # Raw files never enter the fingerprint.
    assert [entry[2] for entry in event["fingerprint"]] == [CONVERTED_AT * NS] * 3


def test_times_survive_the_disk_cache_without_another_stat(
        run: Path, tmp_path: Path, shot_time_stats: list[str]) -> None:
    run_load(run, tmp_path)
    assert sorted(shot_time_stats) == ["d1.txt", "d2.txt"]
    shot_time_stats.clear()
    again = loaded(run_load(run, tmp_path))
    assert again["source"] == "disk" and times(again) == {1: raw_at(1), 2: raw_at(2)}
    cached = loaded(run_cached(run, tmp_path))
    assert times(cached) == {1: raw_at(1), 2: raw_at(2)}
    assert not shot_time_stats


def test_an_update_from_ram_stats_only_the_new_shots_raw_files(
        run: Path, tmp_path: Path, shot_time_stats: list[str]) -> None:
    first_events = run_load(run, tmp_path, no_cache=True)
    first = loaded(first_events)
    base = dataset(run, first, first_events)
    write_shot(run, 4)
    age_folder(run)
    shot_time_stats.clear()
    events = run_load(run, tmp_path, memory=first["fingerprint"], base_signature=first["signature"], no_cache=True)
    event = loaded(events)
    assert event["source"] == "updated" and event["memory_shots"] == [1, 2, 3]
    assert shot_time_stats == ["d4.txt"] and times(event) == {4: raw_at(4)}
    view = build_view(dataset(run, event, events, base))
    assert view.shot_times() == {1: raw_at(1), 2: raw_at(2), 3: CONVERTED_AT, 4: raw_at(4)}
    assert view.fallback_times() == (3,)


def test_a_deleted_raw_file_keeps_the_cached_shot_and_its_time(run: Path, tmp_path: Path) -> None:
    first = loaded(run_load(run, tmp_path))
    (run / "d1.txt").unlink()
    age_folder(run)
    again = loaded(run_load(run, tmp_path, full_check=True))
    # The same dataset, from the cache: nothing was read again, and shot 1 keeps its time.
    assert again["source"] == "disk" and again["cached"] and again["signature"] == first["signature"]
    assert again["load_counts"]["read"] == 0
    assert times(again) == {1: raw_at(1), 2: raw_at(2)}


def drop_raw_times(tmp_path: Path) -> None:
    """Make the store one saved before shot times: no ``raw_times`` column."""
    database = tmp_path / "disk-cache" / "records.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.execute("ALTER TABLE datasets DROP COLUMN raw_times")
        connection.commit()
    finally:
        connection.close()


def test_an_old_cache_without_times_still_loads_and_its_first_full_check_fills_them(
        run: Path, tmp_path: Path) -> None:
    run_load(run, tmp_path)
    drop_raw_times(tmp_path)
    cached_events = run_cached(run, tmp_path)
    cached = loaded(cached_events)
    assert sorted(item["shot"] for item in cached_events if item["kind"] == "shot") == [1, 2, 3]
    assert cached["raw_times"] == []
    view = build_view(dataset(run, cached, cached_events))
    # Unknown times fall back to the TXY files' mtimes, flagged.
    assert view.shot_times() == {1: CONVERTED_AT, 2: CONVERTED_AT, 3: CONVERTED_AT}
    assert view.fallback_times() == (1, 2, 3)
    # The check beside a cached read lists the folder: the raw files it lists give the times,
    # which the cache keeps.
    check = loaded(run_load(run, tmp_path, cache_base=True, full_check=True))
    assert check["cached"] and times(check) == {1: raw_at(1), 2: raw_at(2)}
    assert times(loaded(run_cached(run, tmp_path))) == {1: raw_at(1), 2: raw_at(2)}


def test_live_reads_new_shots_times_and_its_save_keeps_them(
        run: Path, tmp_path: Path, shot_time_stats: list[str]) -> None:
    first_events = run_load(run, tmp_path)
    first = loaded(first_events)
    base = dataset(run, first, first_events)
    write_shot(run, 4, converted_at=time.time() - 60)
    age_folder(run)
    shot_time_stats.clear()
    memory = [list(entry) for entry in first["fingerprint"]]

    def check(**kwargs: Any) -> list[dict[str, Any]]:
        output = tmp_path / f"live-{time.monotonic_ns()}"
        output.mkdir()
        events: list[dict[str, Any]] = []
        live_check(str(run), str(output), events.append, memory, **kwargs)
        return events

    seen = check()[-1]["live_seen"]
    events = check(seen=seen)
    event = loaded(events)
    assert shot_time_stats == ["d4.txt"] and times(event) == {4: raw_at(4)}
    live = dataset(run, event, events, base)
    view = build_view(live)
    assert view.shot_times()[4] == raw_at(4) and view.fallback_times() == (3,)

    # Live's save writes the data held in RAM, with its times, and stats no raw file.
    held = tmp_path / "held"
    held.mkdir()
    for shot, array in live.data.items():
        np.save(held / f"{shot}.npy", array, allow_pickle=False)
    shot_time_stats.clear()
    saved: list[dict[str, Any]] = []
    save_held(str(run), saved.append, cache_options(tmp_path), live.metadata["fingerprint"], [], str(held),
              raw_times=live.metadata["raw_times"])
    assert any(item["kind"] == "cache_saved" for item in saved), saved
    assert not shot_time_stats
    assert times(loaded(run_cached(run, tmp_path))) == {1: raw_at(1), 2: raw_at(2), 4: raw_at(4)}


def test_a_dataset_keeps_its_bases_times_for_the_shots_it_held() -> None:
    base = Dataset("/run", "a", {}, {"fingerprint": [[1, 1, 5], [2, 1, 5]], "raw_times": [[1, 10], [2, 20]]}, 0)
    update = {"fingerprint": [[1, 1, 5], [2, 1, 6], [3, 1, 7]], "raw_times": [[3, 30]]}
    # A shot read again (2) keeps its time; shots not in the fingerprint drop out.
    assert dataset_raw_times(base, update, {}) == [[1, 10], [2, 20], [3, 30]]
    assert dataset_raw_times(base, {"fingerprint": [[1, 1, 5]]}, {}) == [[1, 10]]
    assert dataset_raw_times(None, update, {2: 25}) == [[2, 25], [3, 30]]
    # Malformed entries are ignored.
    assert dataset_raw_times(None, {"fingerprint": [[1, 1, 5]], "raw_times": [[1, "x"], [1]]}, {}) == []


def test_the_apps_datasets_carry_the_times_through_an_update(
        monkeypatch: pytest.MonkeyPatch, run: Path, tmp_path: Path) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    cache = FolderCache(service)
    path = str(run)

    def replay() -> Dataset:
        """Run the queued load in-process and deliver its events, as the service's reader would."""
        job = cache.jobs[("load", path)]
        request = next(item for item in service.pending if item.owner == job.owner)
        service.pending.remove(request)
        payload = request.payload
        events = run_load(run, tmp_path, memory=payload.get("memory"),
                          base_signature=payload.get("base_signature", ""), no_cache=True)
        for event in events + [{"kind": "done"}]:
            if event["kind"] == "shot":
                event = {**event, "array": np.load(event.pop("artifact"))}
            service.resultReady.emit(request, event)
        found = cache.dataset(path, loaded(events)["signature"])
        assert found is not None
        return found

    try:
        assert cache.submit("tab", 0, path, "load")
        first = replay()
        assert first.metadata["raw_times"] == [[1, raw_at(1) * NS], [2, raw_at(2) * NS]]
        cache.retain("tab", first)
        write_shot(run, 4)
        age_folder(run)
        assert cache.submit("tab", 1, path, "load", force=True)
        update = replay()
        assert update.metadata["source"] == "updated" and update.metadata["memory_shots"] == [1, 2, 3]
        assert build_view(update).shot_times() == {1: raw_at(1), 2: raw_at(2), 3: CONVERTED_AT, 4: raw_at(4)}
    finally:
        service.shutdown()
