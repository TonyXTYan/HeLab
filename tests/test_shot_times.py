"""Shot times (D7): a shot's time is its raw ``d<N>.txt`` file's mtime, found by the helper's own
listing and kept with the dataset (RAM, disk cache, Live); without a raw file it is the TXY file's
mtime, flagged as a fallback."""
from __future__ import annotations

import math
import os
from pathlib import Path
import sqlite3
import time
from typing import Any

import numpy as np
import pytest
from PyQt6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from helab import io_helper
from helab.analysis.dataset_view import DatasetView, build_view, revise
from helab.analysis.parameters import effective
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.io_helper import live_check, load, read_cached, save_held
from helab.scripts.dld import shot_times
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
    events = run_load(run, tmp_path, memory=first["fingerprint"], base_signature=first["signature"], no_cache=True,
                      memory_raw_times=base.metadata["raw_times"])
    event = loaded(events)
    assert event["source"] == "updated" and event["memory_shots"] == [1, 2, 3]
    assert shot_time_stats == ["d4.txt"] and times(event) == {1: raw_at(1), 2: raw_at(2), 4: raw_at(4)}
    view = build_view(dataset(run, event, events, base))
    assert view.shot_times() == {1: raw_at(1), 2: raw_at(2), 3: CONVERTED_AT, 4: raw_at(4)}
    assert view.fallback_times() == (3,)


def test_a_held_shots_raw_file_is_never_stat_again_while_its_txy_file_is_unchanged(
        run: Path, tmp_path: Path, shot_time_stats: list[str]) -> None:
    """Raw d<N>.txt files are never rewritten (Tony): with the caller's times sent along, an update
    from RAM that also writes the disk cache (reading the held shots' TXY files again for it) stats
    only the new shot's raw file, and the cache gets every time."""
    first_events = run_load(run, tmp_path, no_cache=True)
    first = loaded(first_events)
    base = dataset(run, first, first_events)
    write_shot(run, 4)
    age_folder(run)
    shot_time_stats.clear()
    events = run_load(run, tmp_path, memory=first["fingerprint"], base_signature=first["signature"],
                      memory_raw_times=base.metadata["raw_times"])
    event = loaded(events)
    assert event["source"] == "updated" and event["memory_shots"] == [1, 2, 3]
    assert any(item["kind"] == "disk_cached" for item in events)  # the held shots were read for the cache
    assert shot_time_stats == ["d4.txt"]
    shot_time_stats.clear()
    cached = loaded(run_cached(run, tmp_path))
    assert times(cached) == {1: raw_at(1), 2: raw_at(2), 4: raw_at(4)} and not shot_time_stats
    # A changed TXY file (another run's shot of that number) is stat'ed again, held or not.
    write_shot(run, 2, converted_at=CONVERTED_AT + 10)
    set_mtime(run / "d2.txt", raw_at(2) + 5)
    age_folder(run)
    again = loaded(run_load(run, tmp_path, memory=cached["fingerprint"], base_signature=cached["signature"],
                            memory_raw_times=cached["raw_times"]))
    assert shot_time_stats == ["d2.txt"] and times(again)[2] == raw_at(2) + 5


def test_another_run_copied_over_the_folder_gets_its_own_times(
        run: Path, tmp_path: Path, shot_time_stats: list[str]) -> None:
    """A later run copied to the same path, with more shots of the same numbers: its changed shots
    are read again with their own raw files' times, never the cached run's."""
    run_load(run, tmp_path)
    later = RAW_AT + 86400
    for file in list(run.iterdir()):
        file.unlink()
    for shot in (1, 2, 3, 4):
        txy = run / f"d_txy_forc{shot}.txt"
        txy.write_text(f"{shot},7,7\n")
        set_mtime(txy, later + 3600)
        (run / f"d{shot}.txt").write_text("raw\n")
        set_mtime(run / f"d{shot}.txt", later + shot)
    age_folder(run)
    shot_time_stats.clear()
    event = loaded(run_load(run, tmp_path))
    assert event["load_counts"]["modified"] == 3 and event["load_counts"]["new"] == 1
    assert times(event) == {shot: later + shot for shot in (1, 2, 3, 4)}
    assert sorted(shot_time_stats) == ["d1.txt", "d2.txt", "d3.txt", "d4.txt"]
    assert times(loaded(run_cached(run, tmp_path))) == {shot: later + shot for shot in (1, 2, 3, 4)}


def test_a_raw_file_still_being_written_gets_its_time_later(
        monkeypatch: pytest.MonkeyPatch, run: Path, tmp_path: Path) -> None:
    set_mtime(run / "d2.txt", time.time())
    monkeypatch.setattr(io_helper, "SETTLE_SECONDS", 30.0)
    first = loaded(run_load(run, tmp_path, no_cache=True))
    assert times(first) == {1: raw_at(1)}
    set_mtime(run / "d2.txt", raw_at(2))
    assert times(loaded(run_load(run, tmp_path, no_cache=True))) == {1: raw_at(1), 2: raw_at(2)}


def test_a_held_shot_without_a_time_gets_it_from_a_later_update_from_ram(
        monkeypatch: pytest.MonkeyPatch, run: Path, tmp_path: Path, shot_time_stats: list[str]) -> None:
    """A RAM-only load that saw a raw file still being written holds that shot without a time; a
    later update from RAM (the shot unchanged, held, no disk cache) stats that raw file again,
    and only it: a held shot with a time is never stat'ed again."""
    set_mtime(run / "d2.txt", time.time())
    monkeypatch.setattr(io_helper, "SETTLE_SECONDS", 30.0)
    first_events = run_load(run, tmp_path, no_cache=True)
    first = loaded(first_events)
    base = dataset(run, first, first_events)
    assert times(first) == {1: raw_at(1)} and base.metadata["raw_times"] == [[1, raw_at(1) * NS]]
    set_mtime(run / "d2.txt", raw_at(2))  # Settled now.
    write_shot(run, 4)
    age_folder(run)
    shot_time_stats.clear()
    events = run_load(run, tmp_path, memory=first["fingerprint"], base_signature=first["signature"], no_cache=True,
                      memory_raw_times=base.metadata["raw_times"])
    event = loaded(events)
    assert event["source"] == "updated" and event["memory_shots"] == [1, 2, 3]
    assert sorted(shot_time_stats) == ["d2.txt", "d4.txt"]  # Not d1.txt: its time is known.
    view = build_view(dataset(run, event, events, base))
    assert view.shot_times() == {1: raw_at(1), 2: raw_at(2), 3: CONVERTED_AT, 4: raw_at(4)}
    assert view.fallback_times() == (3,)
    # Now that every held shot with a raw file has its time, the next update stats none of them.
    shot_time_stats.clear()
    again = loaded(run_load(run, tmp_path, memory=event["fingerprint"], base_signature=event["signature"],
                            no_cache=True, memory_raw_times=event["raw_times"]))
    assert again["memory_shots"] == [1, 2, 3, 4] and not shot_time_stats


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


def test_a_dataset_keeps_its_bases_times_for_unchanged_shots() -> None:
    base = Dataset("/run", "a", {}, {"fingerprint": [[1, 1, 5], [2, 1, 5]], "raw_times": [[1, 10], [2, 20]]}, 0)
    update = {"fingerprint": [[1, 1, 5], [2, 1, 6], [3, 1, 7]], "raw_times": [[3, 30]]}
    # An unchanged shot (1) keeps its time; a changed one (2) has only what the helper found now
    # (it may be another run's shot 2); shots not in the fingerprint drop out.
    assert dataset_raw_times(base, update, {}) == [[1, 10], [3, 30]]
    assert dataset_raw_times(base, update, {2: 22}) == [[1, 10], [2, 22], [3, 30]]
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
    payloads: list[dict[str, Any]] = []

    def replay() -> Dataset:
        """Run the queued load in-process and deliver its events, as the service's reader would."""
        job = cache.jobs[("load", path)]
        request = next(item for item in service.pending if item.owner == job.owner)
        service.pending.remove(request)
        payload = request.payload
        payloads.append(dict(payload))
        events = run_load(run, tmp_path, memory=payload.get("memory"),
                          base_signature=payload.get("base_signature", ""), no_cache=True,
                          memory_raw_times=payload.get("memory_raw_times"))
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
        # The held shots' times go with their fingerprints: the helper never stats them again.
        assert payloads[-1]["memory_raw_times"] == [[1, raw_at(1) * NS], [2, raw_at(2) * NS]]
        assert build_view(update).shot_times() == {1: raw_at(1), 2: raw_at(2), 3: CONVERTED_AT, 4: raw_at(4)}
    finally:
        service.shutdown()


# The Shot times plot

def synthetic(raw: dict[int, float], txy: dict[int, float], events: dict[int, int] | None = None) -> Dataset:
    """A dataset of shots with these raw times (s) and TXY times (s, every shot's mtime)."""
    shots = sorted(txy)
    data = {shot: np.ones(((events or {}).get(shot, shot), 3)) for shot in shots}
    return Dataset("/data/run", "sig", data, {
        "fingerprint": [[shot, 10, int(txy[shot] * NS)] for shot in shots],
        "raw_times": [[shot, int(raw[shot] * NS)] for shot in sorted(raw)], "unsettled_files": 1}, 0)


def context(view: DatasetView, values: dict[str, Any] | None = None) -> AnalysisContext:
    script = shot_times.ShotTimesPlot()
    return AnalysisContext("a1", "Plot", view, effective(script.parameters("Plot"), values or {}),
                           script.get_metadata().identity())


def run_plot(view: DatasetView, values: dict[str, Any] | None = None) -> AnalysisResult:
    run = context(view, values)
    return AnalysisResult.of(run, "completed", shot_times.ShotTimesPlot().compute("Plot", run))


def test_the_plot_takes_raw_times_gaps_and_flags_txy_times() -> None:
    # Shot 3 has no raw file: its time is its TXY file's, converted with the others an hour later.
    view = build_view(synthetic({1: 100.0, 2: 160.0, 4: 400.0}, {1: 3700.0, 2: 3700.0, 3: 3700.0, 4: 3700.0}))
    data: shot_times.ShotTimes = run_plot(view).data
    assert data.shots.tolist() == [1, 2, 3, 4] and data.counts.tolist() == [1, 2, 3, 4]
    assert data.times.tolist() == [100.0, 160.0, 3700.0, 400.0]
    assert data.fallback.tolist() == [False, False, True, False] and data.fallbacks == 1
    assert math.isnan(data.gaps[0]) and data.gaps[1:].tolist() == [60.0, 3540.0, -3300.0]
    # Gaps from or to a TXY time are flagged too.
    assert data.gap_fallback.tolist() == [False, False, True, True]
    # The longest gap between raw times: one from or to a TXY time would make up a stall.
    assert data.longest_gap() == (2, 60.0)
    assert shot_times.title_text(data) == (
        "4 shots · 10 events · longest gap 60 s before shot 2 · ⚠ 1 TXY time (no raw file) · "
        "1 file still being written left out")
    script = shot_times.ShotTimesPlot()
    values = effective(script.parameters("Plot"), {})
    assert script.describe_run("Plot", values, view) == ("4 shots · ⚠ 1 TXY time (no raw file)", "")
    values = effective(script.parameters("Plot"), {"shots": "last N", "last_shots": 2, "panels": "gaps",
                                                   "log_gaps": True})
    assert script.describe_run("Plot", values, view) == (
        "shots 3–4 (2 of 4) · ⚠ 1 TXY time (no raw file)", "last 2 shots · gaps · log gaps")
    chosen = run_plot(view, {"shots": "range", "first_shot": 1, "last_shot": 2}).data
    assert chosen.shots.tolist() == [1, 2] and not chosen.fallbacks and chosen.total_shots == 4
    assert script.covered_shots("Plot", values, view) == (3, 4)


@pytest.mark.parametrize(("seconds", "text"), [
    (0.84, "0.84 s"), (4.25, "4.2 s"), (42, "42 s"), (750, "12.5 min"), (3 * 3600 + 720, "3.2 h"),
    (2 * 86400, "2.0 d"), (-90, "−90 s")])
def test_gap_text(seconds: float, text: str) -> None:
    assert shot_times.gap_text(seconds) == text


def test_the_plot_says_why_it_is_empty_and_draws_shots_without_events(qtbot: QtBot) -> None:
    script = shot_times.ShotTimesPlot()
    nothing = run_plot(build_view(Dataset("/data/run", "", {}, {"fingerprint": []}, 0)))
    widget = script.render(nothing)
    qtbot.addWidget(widget)
    assert isinstance(widget, QLabel) and widget.objectName() == "plot_empty" and widget.text() == "No shots yet"
    view = build_view(synthetic({1: 100.0}, {1: 200.0, 2: 300.0}, {1: 0, 2: 0}))
    none_chosen = script.render(run_plot(view, {"first_shot": 10}))
    qtbot.addWidget(none_chosen)
    assert isinstance(none_chosen, QLabel)
    assert none_chosen.text() == "None of the 2 shots is chosen (Shots settings)"
    # Shots without events still have times: drawn at 0 events, not "no events".
    drawn = script.render(run_plot(view))
    qtbot.addWidget(drawn)
    assert isinstance(drawn, shot_times.ShotTimesWidget) and len(drawn.plots) == 2
    # One shot: no gap yet.
    single = run_plot(build_view(synthetic({1: 100.0}, {1: 200.0}))).data
    assert single.longest_gap() is None and "gap" not in shot_times.title_text(single)
    # No raw files at all (an old cache): the TXY times' gaps, flagged.
    old = run_plot(build_view(synthetic({}, {1: 200.0, 2: 200.0, 3: 230.0}))).data
    assert old.fallbacks == 3 and old.longest_gap() == (3, 30.0)
    assert shot_times.title_text(old).endswith(
        "· ⚠ 3 TXY times (no raw file) · 1 file still being written left out")
    # Times found later for the shots shown (a listing check of an old cache): a new revision.
    filled = synthetic({1: 100.0, 2: 150.0, 3: 210.0}, {1: 200.0, 2: 200.0, 3: 230.0})
    first = build_view(synthetic({}, {1: 200.0, 2: 200.0, 3: 230.0}))
    later = revise(first, filled)
    assert later.revision == 2 and later.added_shots == () and later.fallback_times() == ()
    assert revise(later, synthetic({1: 100.0, 2: 150.0, 3: 210.0}, {1: 200.0, 2: 200.0, 3: 230.0})) is later
    # A replaced shot (its TXY file changed) keeps no earlier time.
    replaced = later.with_shots({2: np.ones((1, 3))}, {2: (2, 11, 300 * NS)})
    assert replaced.fallback_times() == (2,) and replaced.shot_time(2) == 300.0


def points(item: Any, drawn: bool = False) -> tuple[list[float], list[float]]:
    """A point item's data as given, or as drawn (``drawn``: after the plot's log mode)."""
    x, y = item.getData() if drawn else item.getOriginalDataset()
    return ([] if x is None else x.tolist()), ([] if y is None else y.tolist())


def test_the_plot_draws_raw_and_txy_times_apart_and_updates_in_place(qtbot: QtBot) -> None:
    script = shot_times.ShotTimesPlot()
    view = build_view(synthetic({1: 100.0, 2: 160.0}, {1: 900.0, 2: 900.0, 3: 900.0}))
    widget = script.render(run_plot(view))
    qtbot.addWidget(widget)
    assert isinstance(widget, shot_times.ShotTimesWidget)
    assert "TXY file's" in widget.toolTip() and "copied or rewritten" in widget.toolTip()
    (counts_raw, counts_txy), (gaps_raw, gaps_txy) = widget.points
    assert points(counts_raw) == ([100.0, 160.0], [1.0, 2.0])
    assert points(counts_txy) == ([900.0], [3.0])
    assert points(gaps_raw)[1] == [60.0] and points(gaps_txy)[1] == [740.0]
    # The key sits under the title, outside the plots (a legend inside covered the latest points).
    assert widget.plots[0].legend is None
    assert "raw file time" in widget.key_label.text and "TXY file time (no raw file)" in widget.key_label.text
    # Live's next shot (with its raw time): the same widget, its points replaced.
    later = view.with_shots({4: np.ones((4, 3))}, {4: (4, 10, 950 * NS)}, raw_times={4: 800 * NS})
    assert script.update(widget, run_plot(later))
    assert points(counts_raw)[0] == [100.0, 160.0, 800.0]
    assert "4 shots" in widget.title.text
    # Other settings, or nothing to draw: drawn anew.
    assert not script.update(widget, run_plot(later, {"panels": "counts"}))
    assert not script.update(widget, run_plot(later, {"first_shot": 10}))


def test_log_gaps_draws_the_gaps_logarithm(qtbot: QtBot) -> None:
    """Log gaps: points drawn at log10 of the gap (the axis reads seconds), the view around them;
    a negative gap (a shot timed before the one before it) has no logarithm and is left out."""
    script = shot_times.ShotTimesPlot()
    view = build_view(synthetic({1: 0.0, 2: 100.0, 3: 1100.0, 4: 1000.0}, {shot: 5.0 for shot in range(1, 5)}))
    widget = script.render(run_plot(view, {"panels": "gaps", "log_gaps": True}))
    qtbot.addWidget(widget)
    assert isinstance(widget, shot_times.ShotTimesWidget) and len(widget.plots) == 1
    widget.resize(600, 400)
    widget.show()
    qtbot.waitExposed(widget)
    ((raw_points, txy_points),) = widget.points
    assert points(raw_points)[1] == [100.0, 1000.0] and points(txy_points) == ([], [])
    assert points(raw_points, drawn=True)[1] == pytest.approx([2.0, 3.0])
    plot = widget.plots[0]
    plot.vb.autoRange()
    low, high = plot.vb.viewRange()[1]
    assert 1.0 < low < 2.0 < 3.0 < high < 4.0
