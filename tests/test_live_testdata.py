"""Live and the converter on real shots (HeLab's test data, ``test_convert_testdata``): runs replayed into
a watched folder shot by shot, each written as the TDC writes it (a part ending mid-row first), converted
once and only when whole, byte for byte as MATLAB did, and read into Live's data as MATLAB's TXY reads.

Skipped without the test data (``HELAB_TESTDATA``). Each test works on copies in its own temp folder and
waits through the harness's seams (in-process helpers, file times long past), never real settle times,
so each takes seconds and the file runs under xdist like any other.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
import pytest
from pytestqt.qtbot import QtBot

from helab.convert.pipeline import convert_raw
from helab.convert.profile import MATLAB_2019
from helab.io_ops import convert
from helab.utils.io_service import IOService
from helab.views.FolderExplorer import FolderExplorer
from test_convert_helab import request_for, run, summary
from test_convert_testdata import DATA, FAULTS, needs_data
from test_live import producer, replay, service  # noqa: F401  (the service fixture)
from test_live_convert import back_online, cycle, of, one_worker, watching_raw_folder, write_raw  # noqa: F401

pytestmark = [needs_data, pytest.mark.timeout(120)]

ROOT = Path(__file__).resolve().parent.parent
OLD = 1_700_000_000  # A raw file's mtime long settled (as test_live_convert's).


def era(folder: str) -> Path:
    assert DATA is not None
    return DATA / "data" / folder


def raws(folder: Path) -> dict[int, bytes]:
    """The folder's raw files' bytes, by shot."""
    return {int(path.stem[1:]): path.read_bytes()
            for path in sorted(folder.glob("d[0-9]*.txt"), key=lambda path: int(path.stem[1:]))}


def matlab_txy(folder: Path, shot: int) -> bytes:
    return (folder / f"d_txy_forc{shot}.txt").read_bytes()


def as_loaded(txy: bytes) -> npt.NDArray[np.float64]:
    """A TXY's hits as HeLab reads a TXY file (``io_ops.infra._read_txy_file``)."""
    if not txy:
        return np.empty((0, 3))
    hits: npt.NDArray[np.float64] = pd.read_csv(io.BytesIO(txy), sep=",", names=["t", "x", "y"],
                                                dtype=np.float64).to_numpy()
    return hits


def cut(data: bytes) -> bytes:
    """The part of a raw file a reader sees while the TDC is still writing it: ending mid-row."""
    part = data[: len(data) // 2]
    return part if not part.endswith(b"\n") else part[:-1]


def converted_by(sent: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(event["shot"]): event for event in of(sent, "shot_converted")}


def replay_into_live(qtbot: QtBot, explorer: FolderExplorer, path: str, tmp_path: Path,
                     shots: dict[int, bytes]) -> dict[int, list[dict[str, Any]]]:
    """Write ``shots`` into the watched folder two at a time, as a run: the first whole, the second
    caught mid-row and finished a check later. Every Live tick's conversions, by shot."""
    folder = Path(path)
    done: dict[int, list[dict[str, Any]]] = {shot: [] for shot in shots}
    order = sorted(shots)
    for first, second in zip(order[0::2], order[1::2] + [None] * (len(order) % 2)):
        write_raw(folder, first, shots[first])
        if second is not None:
            write_raw(folder, second, cut(shots[second]))
        for _ in range(3):
            for shot, event in converted_by(cycle(qtbot, explorer, path, tmp_path)[1]).items():
                done[shot].append(event)
        assert done[first], f"shot {first} not converted in 3 ticks"
        if second is None:
            continue
        assert not done[second], f"shot {second} converted while cut mid-row"
        write_raw(folder, second, shots[second], OLD + 1)  # The writer finishes: changed, so it waits a tick.
        for _ in range(3):
            for shot, event in converted_by(cycle(qtbot, explorer, path, tmp_path)[1]).items():
                done[shot].append(event)
        assert done[second], f"shot {second} not converted in 3 ticks after it was finished"
    return done


def test_a_run_replayed_into_live_is_converted_once_per_shot_as_matlab_did(
        qtbot: QtBot, service: IOService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The ghost-counts run's ten consecutive shots (shot 5 has no hits) arrive while Live watches with
    auto-convert: each converts once, only when whole, to MATLAB's TXY byte for byte, and Live's data for
    each shot is MATLAB's TXY as HeLab reads it."""
    monkeypatch.setattr(convert, "DAMAGED_SECONDS", 1e9)  # (Dated long ago: never damaged here.)
    source = era("eras/2022-11-ghost-counts")
    shots = raws(source)
    assert sorted(shots) == list(range(1, 11))
    explorer, path = watching_raw_folder(qtbot, tmp_path)
    try:
        cycle(qtbot, explorer, path, tmp_path)  # (The folder's first conversion only records.)
        done = replay_into_live(qtbot, explorer, path, tmp_path, shots)
        for shot, events in done.items():
            assert len(events) == 1, f"shot {shot} converted {len(events)} times"
            [event] = events
            assert Path(event["txy"]).read_bytes() == matlab_txy(source, shot), f"shot {shot}"
            assert event["hits"] == len(as_loaded(matlab_txy(source, shot)))
        assert done[5][0]["hits"] == 0
        for _ in range(4):  # Live's checks read what was converted.
            if set(explorer.folder_opened_data or {}) >= set(shots) - {5}:
                break
            cycle(qtbot, explorer, path, tmp_path)
        data = explorer.folder_opened_data or {}
        for shot in shots:
            expected = as_loaded(matlab_txy(source, shot))
            if not len(expected):
                assert shot not in data or not len(data[shot]), f"shot {shot} has no hits"
                continue
            assert shot in data, f"shot {shot} not in Live's data: {sorted(data)}"
            assert np.array_equal(data[shot], expected), f"shot {shot}"
        session = explorer.live
        assert session is not None and session.convert is not None
        assert session.convert.converted == len(shots) and not session.convert.unconvertible
    finally:
        explorer.stop_live(save=False)
        explorer.close_cleanup()


def test_damaged_files_during_live_are_said_once_and_the_run_goes_on(
        qtbot: QtBot, service: IOService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The test data's damaged raw files arrive among good shots. One cut mid-line and one empty are
    damaged once they have stayed so (here at once), each said once, and the good shots convert. One with
    a garbage line converts as MATLAB's reading does: its textscan stops at the first token it can't read,
    so the TXY holds only the hits before that line (the reference converter's output)."""
    monkeypatch.setattr(convert, "DAMAGED_SECONDS", 0.0)
    damaged = raws(era("damaged"))
    good_source = era("eras/2024-11-low-occupancy")
    renamed = {10 + index: shot for index, shot in enumerate(sorted(raws(good_source)))}  # (Beside d1-d5.)
    good = {shot: raws(good_source)[source_shot] for shot, source_shot in renamed.items()}
    explorer, path = watching_raw_folder(qtbot, tmp_path)
    try:
        cycle(qtbot, explorer, path, tmp_path)
        for shot, data in {**damaged, **good}.items():
            write_raw(Path(path), shot, data)
        said: list[dict[str, Any]] = []
        converted: dict[int, dict[str, Any]] = {}
        for _ in range(4):
            sent = cycle(qtbot, explorer, path, tmp_path)[1]
            said += of(sent, "shot_unconvertible")
            converted.update(converted_by(sent))
        assert sorted(converted) == [3, *sorted(good)]
        for shot, source_shot in renamed.items():
            assert Path(converted[shot]["txy"]).read_bytes() == matlab_txy(good_source, source_shot)
        stopped = convert_raw(damaged[3], MATLAB_2019, "reference")
        assert stopped is not None and Path(converted[3]["txy"]).read_bytes() == stopped
        assert converted[3]["hits"] < len(as_loaded(matlab_txy(good_source, 1111)))  # (Made from shot 1111.)
        assert sorted(event["raw_name"] for event in said) == ["d1.txt", "d2.txt"]
        assert {event["reason"] for event in said} == {"damaged"}
        session = explorer.live
        assert session is not None and session.convert is not None
        assert session.convert.damaged == {"d1.txt", "d2.txt"}
        assert explorer.live is not None  # Live goes on.
    finally:
        explorer.stop_live(save=False)
        explorer.close_cleanup()


ERAS = ["2019-old-plates", "2020-weak-trap", "2022-07-old-plates-he3he4", "2022-11-ghost-counts", "2023-02-new-plates",
        "2023-03-momentum-bells", "2024-11-low-occupancy", "2026-06-before-rotation", "2026-07-after-rotation"]


@pytest.mark.parametrize("name", ERAS)
def test_each_eras_raw_files_convert_in_a_folder_as_matlab_did(name: str, tmp_path: Path) -> None:
    """A folder of each era's raw files, converted as Live's helper converts it (the default profile, to
    HeLab's folder, named by its tag): every TXY MATLAB's, but the archive's listed faults."""
    source = era(f"eras/{name}")
    folder = tmp_path / name
    folder.mkdir()
    shots = raws(source)
    for shot, data in shots.items():
        write_raw(folder, shot, data)
    sent = run(folder, request_for(folder, tmp_path))
    converted = converted_by(sent)
    assert sorted(converted) == sorted(shots) and summary(sent)["converted"] == len(shots)
    for shot, event in converted.items():
        assert Path(event["txy"]).name == f"d_txy_helab_m19v1_{shot}.txt"
        same = Path(event["txy"]).read_bytes() == matlab_txy(source, shot)
        assert same != ((f"eras/{name}", shot) in FAULTS), f"shot {shot}"


@pytest.fixture
def watched(tmp_path: Path) -> Path:
    folder = tmp_path / "raw-20"
    folder.mkdir()
    return folder


def test_convert_watch_converts_a_run_as_it_arrives(watched: Path) -> None:
    """``helab convert --watch`` beside the twenty Live raw files arriving five at a time, the last of
    each five caught mid-row first: each converted once whole, as the converter gives it, and nothing
    left behind when it stops."""
    shots = raws(era("live/raw-20"))
    assert len(shots) == 20
    previous = signal.signal(signal.SIGINT, signal.default_int_handler)  # (As test_convert_helab's `watching`.)
    try:
        process = subprocess.Popen([sys.executable, "-m", "helab", "convert", "--watch", str(watched), "--output",
                                    "beside", "--interval", "0.2"], stderr=subprocess.PIPE, text=True, cwd=ROOT,
                                   env=dict(os.environ))
    finally:
        if previous is not None:
            signal.signal(signal.SIGINT, previous)

    def converted(shot: int) -> Path:
        return watched / f"d_txy_helab_m19v1_{shot}.txt"

    def wait_for(shot: int) -> None:
        deadline = time.monotonic() + 30
        while not converted(shot).exists() and time.monotonic() < deadline:
            assert process.poll() is None, process.stderr.read() if process.stderr else ""
            time.sleep(0.05)
        assert converted(shot).exists(), f"shot {shot} not converted in 30 s"

    try:
        order = sorted(shots)
        for start in range(0, len(order), 5):
            batch = order[start:start + 5]
            for shot in batch[:-1]:
                write_raw(watched, shot, shots[shot])
            write_raw(watched, batch[-1], cut(shots[batch[-1]]))
            for shot in batch[:-1]:
                wait_for(shot)
            time.sleep(0.5)  # A couple of the watcher's checks with the last shot cut.
            assert not converted(batch[-1]).exists(), f"shot {batch[-1]} converted while cut mid-row"
            write_raw(watched, batch[-1], shots[batch[-1]], OLD + 1)
            wait_for(batch[-1])
        for shot, data in shots.items():
            assert converted(shot).read_bytes() == convert_raw(data, MATLAB_2019, "numpy"), f"shot {shot}"
    finally:
        if sys.platform == "win32":
            process.terminate()
        else:
            process.send_signal(signal.SIGINT)
        code = process.wait(20)
        log = process.stderr.read() if process.stderr else ""
    if sys.platform != "win32":
        assert code == 0, log
        assert "Stopped" in log
    for shot in shots:
        assert log.count(f"d{shot}.txt -> ") == 1, f"shot {shot} converted {log.count(f'd{shot}.txt -> ')} times"
    left = sorted(path.name for path in watched.iterdir()
                  if not path.name.startswith(("d_txy_helab_m19v1_", "d")) or path.name.endswith(".partial"))
    assert left == [], left


def test_a_txy_only_folder_loads_matlabs_shots_and_live_finds_nothing_to_convert(
        qtbot: QtBot, service: IOService, tmp_path: Path) -> None:
    """MATLAB's TXY without raw files (a folder its converter already did): loaded as they read, and Live
    with auto-convert has nothing to convert or wait for."""
    source = era("txy-only")
    folder = tmp_path / "txy-only"
    shutil.copytree(source, folder)
    for file in folder.iterdir():
        os.utime(file, (OLD, OLD))
    when = time.time() - 120
    os.utime(folder, (when, when))
    path = str(folder)
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    cache = explorer.model.cache
    cache.live_interval = 0.02
    try:
        qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
        replay(cache, path, tmp_path, "list")
        explorer.load_to_ram_cache(path, dwell=False, explicit=True)
        qtbot.waitUntil(lambda: ("load", path) in cache.jobs)
        replay(cache, path, tmp_path)
        qtbot.waitUntil(lambda: explorer.folder_opened_path == path)
        data = explorer.folder_opened_data or {}
        shots = sorted(int(name.stem[len("d_txy_forc"):]) for name in source.glob("d_txy_forc*.txt"))
        assert sorted(data) == shots
        for shot in shots:
            assert np.array_equal(data[shot], as_loaded(matlab_txy(source, shot))), f"shot {shot}"
        for request in [r for r in service.pending if r.operation == "details"]:
            service.pending.remove(request)
        assert explorer.start_live()
        explorer.live_control.set_auto_convert(True)
        for _ in range(2):
            sent = cycle(qtbot, explorer, path, tmp_path)[1]
            assert not of(sent, "shot_converted") and not of(sent, "shot_waiting")
            assert not of(sent, "shot_unconvertible")
        assert not [name for name in os.listdir(folder) if name.startswith("d_txy_helab")]
    finally:
        if explorer.live is not None:
            explorer.stop_live(save=False)
        explorer.close_cleanup()
