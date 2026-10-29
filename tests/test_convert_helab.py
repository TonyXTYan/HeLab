"""HeLab's own conversions (TXY converter stage 4): the settle checks, provenance, outputs and the
``convert`` helper operation (``helab/io_ops/convert.py``), the converter flags in the store, and
``helab convert --watch``. Synthetic raw files under ``tmp_path`` only (tests never touch real data)."""
from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any, Callable, Iterator

import pytest
from pytestqt.qtbot import QtBot

from helab.convert import provenance, raw, txy
from helab.convert.pipeline import APP_BACKEND, convert_raw, convert_shot
from helab.convert.profile import MATLAB_2019, MATLAB_2023_LAB_EDIT
from helab.io_ops import convert, fingerprints, stores
from helab.io_ops.admin import cache_admin
from helab.io_ops.convert import ConvertRequest, convert_folder, folder_for
from helab.utils import file_kinds
from helab.utils.cache_store import store_root

ROOT = Path(__file__).resolve().parent.parent
OLD = 1_700_000_000  # an mtime long settled (2023-11)


def raw_bytes(*starts: int, trigger: int = 5, ending: bytes = b"\r\n") -> bytes:
    """A trigger, then one clean hit (x1, x2, y1, y2) per start, in bins, as the TDC writes them."""
    lines = [f"{trigger},1000"]
    for start in starts:
        for channel, delay in ((0, 1500), (1, 1700), (2, 1550), (3, 1650)):
            lines.append(f"{channel},{start + delay}")
    return b"".join(line.encode() + ending for line in lines)


def write_raw(folder: Path, shot: int, data: bytes, mtime: float = OLD) -> Path:
    path = folder / f"d{shot}.txt"
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return path


def older_beside(folder: Path, shot: int, data: bytes) -> Path:
    """A TXY of matlab-2019's tag beside the raw file that is older than it (``write_raw``'s): one HeLab
    doesn't stand behind (Q18.4: beside, a TXY is current while newer than its raw file)."""
    path = folder / f"d_txy_helab_m19v1_{shot}.txt"
    path.write_bytes(data)
    os.utime(path, (OLD - 60, OLD - 60))
    return path


@pytest.fixture
def source(tmp_path: Path) -> Path:
    folder = tmp_path / "source"
    folder.mkdir()
    return folder


def options(private_store: str) -> dict[str, Any]:
    return {"directory": store_root(private_store)}


def request_for(path: Path, tmp_path: Path, private_store: str | None = None, **fields: Any) -> ConvertRequest:
    # (seen None: one check, which with no settle age in tests converts at once; the two-check
    # rule has its own tests.)
    request: ConvertRequest = {"path": str(path), "profile": MATLAB_2019.to_dict(), "temps": str(tmp_path / "temps"),
                               "seen": None, "destination": "temp", "workers": 1}
    if private_store is not None:
        request["cache"] = options(private_store)
    request.update(fields)  # type: ignore[typeddict-item]
    return request


def run(path: Path, request: ConvertRequest) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    convert_folder(str(path), request, events.append)  # type: ignore[arg-type]
    return events


def of(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [event for event in events if event["kind"] == kind]


def summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    [found] = of(events, "convert_summary")
    return found


# The done-writing checks (A10.1, Q10.2).


def test_settled_by_age_wants_the_settle_age_and_no_future_date() -> None:
    now = 1_000_000.0
    assert raw.settled_by_age(int((now - 6) * 1e9), now, 5.0)
    assert not raw.settled_by_age(int((now - 4) * 1e9), now, 5.0)
    assert not raw.settled_by_age(int((now + 60) * 1e9), now, 5.0)  # A clock ahead: still being written.
    assert raw.settled_by_age(int((now + 60) * 1e9), now, 0.0)  # (Tests: no settle age.)


def test_not_done_finds_a_half_written_file() -> None:
    whole = raw_bytes(10_000, 20_000)
    assert raw.not_done(whole, 5) is None
    assert raw.not_done(raw_bytes(10_000, ending=b"\n"), 5) is None
    # Cut mid-line, as a reader catching the writer at work sees it (d3667's MATLAB read).
    half = whole[: len(whole) // 2 + 3]
    assert not half.endswith(b"\n")
    problem = raw.not_done(half, 5)
    assert problem is not None and problem[0] == raw.NO_FINAL_NEWLINE
    # Started on a corner rather than the trigger, or on the other era's trigger channel.
    assert (raw.not_done(raw_bytes(10_000, trigger=0), 5) or ("",))[0] == raw.NOT_TRIGGER_FIRST
    assert raw.not_done(raw_bytes(10_000, trigger=4), 4) is None
    assert (raw.not_done(b"garbage\r\n", 5) or ("",))[0] == raw.NOT_TRIGGER_FIRST
    for empty in (b"", b"\r\n\r\n", b"  \n"):
        assert (raw.not_done(empty, 5) or ("",))[0] == raw.NO_ROWS


# HeLab's conversion and its provenance.


def test_convert_shot_matches_the_reference_and_writes_empty_for_no_hits() -> None:
    data = raw_bytes(10_000, 20_000, 30_000)
    shot = convert_shot(data, MATLAB_2019)
    assert shot.txy == convert_raw(data, MATLAB_2019, "reference") and shot.hits == 3
    # Only a trigger: no hits. matlab-2019 writes no TXY for comparisons; HeLab's own is 0 bytes.
    trigger_only = b"5,1000\r\n"
    assert convert_raw(trigger_only, MATLAB_2019, "reference") is None
    empty = convert_shot(trigger_only, MATLAB_2019)
    assert empty.txy == b"" and empty.hits == 0
    assert APP_BACKEND == "numpy"


def provenance_record(**changes: Any) -> provenance.Provenance:
    values: dict[str, Any] = dict(
        shot=3, raw_name="d3.txt", raw_size=100,
        raw_mtime_ns=5, raw_sha256="ab", profile_name="matlab-2019", profile_version=1,
        profile_hash=MATLAB_2019.content_hash(), profile_tag="m19v1", profile_calibrated=False, backend="numpy", output="cache",
        txy_name="d_txy_helab_m19v1_3.txt", txy_size=40, txy_mtime_ns=7, txy_sha256="cd", hits=2, converted_at=1.5, helab_version="0",
        read_seconds=0.1, parse_seconds=0.0, reconstruct_seconds=0, format_seconds=0.0, write_seconds=0.0)
    values.update(changes)
    return provenance.Provenance(**values)


def index_rows(folder: str | Path, tag: str = "") -> dict[tuple[str, int], provenance.Provenance]:
    """The rows HeLab's index holds for its folder ``folder``."""
    return provenance.read_shots(os.path.dirname(folder), os.path.basename(folder), tag=tag)


def test_provenance_rows_round_trip_and_say_what_is_stale(tmp_path: Path) -> None:
    record = provenance_record()
    root = str(tmp_path / "converted-txy")
    assert provenance.read_shots(root, "f") == {}  # (No index yet: nothing, and none made by a read.)
    assert not os.path.exists(root)
    with provenance.open_index(root, write=True) as index:
        index.record("f", "root://u/run", "/data/run", record, 10.0)
        index.record("f", "root://u/run", "/data/run", provenance_record(shot=4, output="beside", txy_size=3), 11.0)
        assert index.folders() == [("f", "root://u/run", "/data/run", 40, 11.0)]  # (Beside TXY aren't here.)
        index.record("f", "root://u/moved", "/data/moved", provenance_record(txy_size=50), 12.0)
        assert index.folders() == [("f", "root://u/moved", "/data/moved", 50, 12.0)]
        index.record("f", "", "/data/moved", record, 13.0)
    assert index_rows(Path(root) / "f") == {("m19v1", 3): record, ("m19v1", 4): provenance_record(
        shot=4, output="beside", txy_size=3)}
    assert provenance.read_shots(root, "f", tag="m23v1") == {} and provenance.read_shots(root, "g") == {}
    assert list(provenance.read_shots(root, "f", shots=[4])) == [("m19v1", 4)]
    # (``closing``: a connection's own ``with`` commits but doesn't close, and Windows renames no open file.)
    with contextlib.closing(sqlite3.connect(os.path.join(root, provenance.INDEX_NAME))) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == provenance.SCHEMA == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        conn.execute("UPDATE shots SET hits = 'two' WHERE shot = 4")  # A row of the wrong shape: none.
        conn.commit()
    assert list(index_rows(Path(root) / "f")) == [("m19v1", 3)]

    def stale(record: provenance.Provenance | None, raw_mtime_ns: int = 5, txy: tuple[int, int] | None = (40, 7),
              profile_hash: str = MATLAB_2019.content_hash()) -> str:
        return provenance.stale(record, raw_size=100, raw_mtime_ns=raw_mtime_ns, profile_hash=profile_hash,
                                txy=txy) or ""
    assert stale(record) == ""
    assert stale(record, txy=None) == "no TXY"
    assert stale(None) == "no provenance record"
    assert "raw file changed" in stale(record, raw_mtime_ns=6)
    assert "TXY changed" in stale(record, txy=(41, 7))
    # The row names the very TXY written (its mtime too): an older one of that size isn't it.
    assert "TXY changed" in stale(record, txy=(40, 6))
    assert "another profile" in stale(record, profile_hash=MATLAB_2023_LAB_EDIT.content_hash())
    # Another backend or profile name with the same hash converts alike: still current.
    assert stale(provenance_record(backend="rust", profile_name="copy")) == ""


def test_write_atomic_calls_before_rename_with_the_files_stat(tmp_path: Path) -> None:
    folder = tmp_path / "out"
    folder.mkdir()
    target = folder / "d_txy_helab_m19v1_1.txt"
    seen: list[os.stat_result] = []

    def before(info: os.stat_result) -> None:
        assert not target.exists()  # (Before the rename.)
        seen.append(info)
    txy.write_atomic(target, b"new\n", before_rename=before)
    after = target.stat()
    assert target.read_bytes() == b"new\n"
    # The rename keeps the size and mtime: what the index pins is the file now at the target.
    assert (seen[0].st_size, seen[0].st_mtime_ns) == (after.st_size, after.st_mtime_ns) == (4, after.st_mtime_ns)

    def refuse(info: os.stat_result) -> None:
        raise OSError("index busy")
    with pytest.raises(OSError, match="index busy"):
        txy.write_atomic(target, b"other\n", before_rename=refuse)
    assert target.read_bytes() == b"new\n" and [path.name for path in folder.iterdir()] == [target.name]


def test_write_atomic_without_replace_never_touches_an_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "d_txy_helab_m19v1_1.txt"
    txy.write_atomic(target, b"new\n", replace=False)
    assert target.read_bytes() == b"new\n"
    with pytest.raises(FileExistsError):
        txy.write_atomic(target, b"other\n", replace=False)
    assert target.read_bytes() == b"new\n"
    folder = tmp_path / "out"
    folder.mkdir()
    target = folder / "d_txy_helab_m19v1_1.txt"
    txy.write_atomic(target, b"new\n", replace=False)
    with pytest.raises(FileExistsError):
        txy.write_atomic(target, b"other\n", replace=False)
    assert [path.name for path in folder.iterdir()] == [target.name]  # No temporary file left.


# The helper operation.


def test_a_folder_converts_to_the_temp_folder_with_provenance(source: Path, tmp_path: Path) -> None:
    datas = {1: raw_bytes(10_000), 2: raw_bytes(10_000, 50_000), 3: b"5,1000\r\n", 4: b""}
    for shot, data in datas.items():
        write_raw(source, shot, data)
    events = run(source, request_for(source, tmp_path))
    [plan] = of(events, "convert_plan")
    folder = folder_for(str(tmp_path / "temps"), "path:" + str(source))
    assert plan["output"] == "temp" and plan["folder"] == plan["txy_folder"] == folder and plan["todo"] == 4
    assert plan["fallback"] == ""  # (Temp was asked for.)
    converted = {event["shot"]: event for event in of(events, "shot_converted")}
    assert sorted(converted) == [1, 2, 3]
    for shot in (1, 2):
        assert Path(converted[shot]["txy"]).read_bytes() == convert_raw(datas[shot], MATLAB_2019, "reference")
    # No hits: a 0-byte TXY, "converted, empty" (Q10.3).
    assert converted[3]["hits"] == 0 and Path(converted[3]["txy"]).read_bytes() == b""
    # No rows, unchanged for 20 s: damaged, no TXY, never silently skipped (Q10.2, Q18.5).
    [refused] = of(events, "shot_unconvertible")
    assert (refused["shot"], refused["reason"], refused["problem"]) == (4, convert.DAMAGED, raw.NO_ROWS)
    assert not (Path(folder) / "d_txy_helab_m19v1_4.txt").exists()
    record = index_rows(folder)[("m19v1", 2)]
    assert (record.raw_name, record.raw_size, record.raw_mtime_ns) == ("d2.txt", len(datas[2]), OLD * 10**9)
    assert (record.profile_name, record.profile_hash, record.backend, record.hits) == (
        "matlab-2019", MATLAB_2019.content_hash(), "numpy", 2)
    written = Path(converted[2]["txy"]).stat()
    assert (record.txy_size, record.txy_mtime_ns) == (written.st_size, written.st_mtime_ns)
    # No JSON beside the TXY: the index (one per base) holds the rows and which source the folder is.
    assert sorted(os.listdir(folder)) == [f"d_txy_helab_m19v1_{shot}.txt" for shot in (1, 2, 3)]
    assert converted[2]["provenance"] == os.path.join(os.path.dirname(folder), provenance.INDEX_NAME)
    with provenance.open_index(os.path.dirname(folder), write=False) as index:  # type: ignore[union-attr]
        assert index.folders()[0][:3] == (os.path.basename(folder), "", str(source))
    done = summary(events)
    assert done["converted"] == 3 and sorted(entry[0] for entry in done["current"]) == ["d1.txt", "d2.txt", "d3.txt"]
    assert [entry[0] for entry in done["unconvertible"]] == ["d4.txt"]
    # Again: every TXY is current; only the empty raw file is looked at (and refused) again.
    again = run(source, request_for(source, tmp_path))
    assert of(again, "shot_converted") == [] and of(again, "convert_plan")[0]["todo"] == 1
    # With the previous summary sent back, done shots aren't checked and the refused one is skipped.
    quiet = run(source, request_for(source, tmp_path, done=done["current"], skip=done["unconvertible"], seen=[]))
    assert [event["kind"] for event in quiet if event["kind"].startswith("shot_")] == []
    assert len(summary(quiet)["unconvertible"]) == 1


def test_files_that_may_still_be_written_wait(source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fingerprints, "SETTLE_SECONDS", 5.0)
    whole = raw_bytes(10_000, 20_000)
    write_raw(source, 1, whole, mtime=time.time() - 1)  # Modified a second ago.
    monkeypatch.setattr(convert, "DAMAGED_SECONDS", 1e9)  # (Not damaged yet: their own test is below.)
    write_raw(source, 2, whole[:-5])  # Ends mid-line (settled by age, but half-written).
    write_raw(source, 3, raw_bytes(10_000, trigger=0))  # Doesn't start on the trigger.
    write_raw(source, 4, whole, mtime=time.time() + 120)  # Dated ahead of this clock: the clocks differ.
    write_raw(source, 5, whole)
    events = run(source, request_for(source, tmp_path))
    waiting = {event["shot"]: event["reason"] for event in of(events, "shot_waiting")}
    assert waiting == {1: raw.SETTLING, 2: raw.NO_FINAL_NEWLINE, 3: raw.NOT_TRIGGER_FIRST, 4: raw.FUTURE}
    [skew] = of(events, "clock_skew")
    assert skew["path"] == str(source) and 100 < skew["seconds"] < 130
    assert [event["shot"] for event in of(events, "shot_converted")] == [5]
    folder = Path(of(events, "convert_plan")[0]["folder"])
    assert sorted(path.name for path in folder.glob("d_txy_helab_*.txt")) == ["d_txy_helab_m19v1_5.txt"]
    # Looked at again with the summary sent back: shot 2, unchanged, isn't read again.
    reads: list[int] = []
    original = convert._read_raw

    def counted(shot: Any, beat: Any) -> bytes | str:
        reads.append(shot.shot)
        return original(shot, beat)
    monkeypatch.setattr(convert, "_read_raw", counted)
    again = run(source, request_for(source, tmp_path, seen=summary(events)["waiting"],
                                    done=summary(events)["current"]))
    assert {event["shot"]: event["reason"] for event in of(again, "shot_waiting")}[2] == raw.NO_FINAL_NEWLINE
    assert 2 not in reads
    # The writer finishes shot 2 and it settles: then it converts.
    write_raw(source, 2, whole)
    later = run(source, request_for(source, tmp_path))
    assert [event["shot"] for event in of(later, "shot_converted")] == [2]


def aged(waiting: list[list[Any]], seconds: float) -> list[list[Any]]:
    """A summary's waiting entries as if first seen ``seconds`` earlier (their sixth field)."""
    return [[*entry[:5], entry[5] - seconds] for entry in waiting]


def test_a_source_clock_behind_ours_never_makes_a_paused_file_damaged(source: Path, tmp_path: Path) -> None:
    """Avocet's review: the 20 s also count from when this computer first saw the file with that size and
    mtime, so a file paused mid-write on a share whose clock is far behind ours (its mtime looks old) waits."""
    write_raw(source, 1, raw_bytes(10_000, 20_000)[:-5], mtime=time.time() - 100)  # Written just now.
    request = request_for(source, tmp_path, seen=[])
    first = run(source, request)
    [entry] = summary(first)["waiting"]
    assert len(entry) == 6 and abs(entry[5] - time.time()) < 5  # First seen now, by this clock.
    request["seen"] = summary(first)["waiting"]
    second = run(source, request)
    assert [(event["shot"], event["reason"]) for event in of(second, "shot_waiting")] == [(1, raw.NO_FINAL_NEWLINE)]
    assert of(second, "shot_unconvertible") == [] and summary(second)["waiting"][0][5] == entry[5]  # (Carried.)
    # 20 s after it was first seen so, unchanged: damaged.
    request["seen"] = aged(summary(second)["waiting"], 25)
    third = run(source, request)
    assert [(event["shot"], event["reason"]) for event in of(third, "shot_unconvertible")] == [(1, convert.DAMAGED)]
    # Seen long ago but its mtime recent (a file touched since, our clock): it waits.
    write_raw(source, 2, raw_bytes(10_000, trigger=0), mtime=time.time() - 8)
    request["seen"] = [[*entry[:5], time.time() - 300] for entry in summary(run(source, request_for(
        source, tmp_path, shots=[2], seen=[])))["waiting"]]
    fourth = run(source, {**request, "shots": [2]})
    assert of(fourth, "shot_unconvertible") == [] and [e["reason"] for e in of(fourth, "shot_waiting")] == [
        raw.NOT_TRIGGER_FIRST]


def test_a_raw_file_failing_the_checks_for_20_s_is_damaged_and_holds_nothing_up(
        source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Q18.5: unmodified for ``DAMAGED_SECONDS`` and still failing the format checks (no final newline,
    off the trigger channel, no rows): damaged, no TXY, skipped from then on while unchanged."""
    assert convert.DAMAGED_SECONDS == 20.0
    whole = raw_bytes(10_000, 20_000)
    young = time.time() - 10
    write_raw(source, 1, whole[:-5], mtime=young)
    write_raw(source, 2, raw_bytes(10_000, trigger=0), mtime=young)
    write_raw(source, 3, b"\r\n", mtime=young)
    write_raw(source, 4, whole)
    request = request_for(source, tmp_path, seen=[])
    first = run(source, request)  # (Seen for the first time: every file waits for a second look.)
    assert of(first, "shot_unconvertible") == [] and of(first, "shot_converted") == []
    # Seen unchanged a check apart: read, and waiting while younger than 20 s.
    request["seen"] = summary(first)["waiting"]
    second = run(source, request)
    assert [event["shot"] for event in of(second, "shot_converted")] == [4]
    assert {event["shot"]: event["reason"] for event in of(second, "shot_waiting")} == {
        1: raw.NO_FINAL_NEWLINE, 2: raw.NOT_TRIGGER_FIRST, 3: raw.NO_ROWS}
    # Unchanged, and now past the damaged age by their mtime and since first seen: damaged, without being
    # read again.
    monkeypatch.setattr(convert, "DAMAGED_SECONDS", 5.0)
    request["seen"], request["done"] = aged(summary(second)["waiting"], 30), summary(second)["current"]
    reads: list[int] = []
    original = convert._read_raw

    def counted(shot: Any, beat: Any) -> bytes | str:
        reads.append(shot.shot)
        return original(shot, beat)
    monkeypatch.setattr(convert, "_read_raw", counted)
    fourth = run(source, request)
    assert reads == []
    damaged = {event["shot"]: (event["reason"], event["problem"]) for event in of(fourth, "shot_unconvertible")}
    assert damaged == {1: (convert.DAMAGED, raw.NO_FINAL_NEWLINE), 2: (convert.DAMAGED, raw.NOT_TRIGGER_FIRST),
                       3: (convert.DAMAGED, raw.NO_ROWS)}
    assert all(event["message"].startswith("Damaged: ") for event in of(fourth, "shot_unconvertible"))
    assert sorted(entry[0] for entry in summary(fourth)["unconvertible"]) == ["d1.txt", "d2.txt", "d3.txt"]
    folder = Path(of(second, "convert_plan")[0]["folder"])
    assert [path.name for path in folder.glob("d_txy_helab_*.txt")] == ["d_txy_helab_m19v1_4.txt"]
    # Read for the first time past the damaged age: damaged at once.
    write_raw(source, 6, whole[:-5], mtime=young)
    once = run(source, request_for(source, tmp_path, shots=[6]))
    assert [(event["shot"], event["problem"]) for event in of(once, "shot_unconvertible")] == [(6, raw.NO_FINAL_NEWLINE)]
    (source / "d6.txt").unlink()
    # Skipped from then on (sent back as skip), never read again, never holding up a later shot.
    write_raw(source, 5, whole)
    request["seen"], request["skip"] = summary(fourth)["waiting"], summary(fourth)["unconvertible"]
    request["done"] = summary(fourth)["current"]
    reads.clear()
    fifth = run(source, request)
    request["seen"] = summary(fifth)["waiting"]
    sixth = run(source, request)
    assert [event["shot"] for event in of(sixth, "shot_converted")] == [5] and of(sixth, "shot_unconvertible") == []
    assert set(reads) <= {5}


def test_a_file_changed_since_the_previous_check_waits_for_the_next(source: Path, tmp_path: Path) -> None:
    whole = raw_bytes(10_000, 20_000)
    write_raw(source, 1, whole[: len(whole) // 2])  # Half the lines, each whole (as d3667's cut).
    first = run(source, request_for(source, tmp_path, seen=[]))
    # Seen for the first time: never converted on that one look.
    assert [(event["shot"], event["reason"]) for event in of(first, "shot_waiting")] == [(1, raw.CHANGED)]
    write_raw(source, 1, whole, mtime=OLD + 1)  # The writer went on: another size.
    second = run(source, request_for(source, tmp_path, seen=summary(first)["waiting"]))
    assert [(event["shot"], event["reason"]) for event in of(second, "shot_waiting")] == [(1, raw.CHANGED)]
    # Unchanged between two checks: converted, and whole.
    third = run(source, request_for(source, tmp_path, seen=summary(second)["waiting"]))
    [done] = of(third, "shot_converted")
    assert Path(done["txy"]).read_bytes() == convert_raw(whole, MATLAB_2019, "reference")


def test_a_file_changing_while_read_is_not_taken_as_done(source: Path, tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    write_raw(source, 1, raw_bytes(10_000))
    original = convert._read_raw

    def grows(shot: Any, beat: Any) -> bytes | str:
        with open(shot.path, "ab") as stream:  # The writer appends as HeLab reads.
            stream.write(b"0,99999\r\n")
        return original(shot, beat)
    monkeypatch.setattr(convert, "_read_raw", grows)
    events = run(source, request_for(source, tmp_path))
    assert [(event["shot"], event["reason"]) for event in of(events, "shot_waiting")] == [(1, raw.CHANGED)]
    assert of(events, "shot_converted") == []


def test_a_better_profile_converts_again_under_its_own_tag(source: Path, tmp_path: Path) -> None:
    write_raw(source, 1, raw_bytes(10_000, 20_000))
    [first] = of(run(source, request_for(source, tmp_path)), "shot_converted")
    events = run(source, request_for(source, tmp_path, profile=MATLAB_2023_LAB_EDIT.to_dict()))
    [again] = of(events, "shot_converted")
    # Its own names (Q18.4): the other profile's TXY stays as it was, nothing replaced.
    assert again["replaced"] == "" and again["profile"]["name"] == "matlab-2023-lab-edit"
    assert again["profile"]["tag"] == "m23v1" and Path(again["txy"]).name == "d_txy_helab_m23v1_1.txt"
    assert Path(first["txy"]).name == "d_txy_helab_m19v1_1.txt" and Path(first["txy"]).is_file()
    folder = os.path.dirname(again["txy"])
    assert sorted(index_rows(folder)) == [("m19v1", 1), ("m23v1", 1)]  # (One row per tag and shot.)
    assert of(run(source, request_for(source, tmp_path, profile=MATLAB_2023_LAB_EDIT.to_dict())),
              "shot_converted") == []
    forced = run(source, request_for(source, tmp_path, profile=MATLAB_2023_LAB_EDIT.to_dict(), redo="always"))
    assert len(of(forced, "shot_converted")) == 1


def test_only_the_shots_asked_for(source: Path, tmp_path: Path) -> None:
    for shot in (1, 2, 3):
        write_raw(source, shot, raw_bytes(10_000 * shot))
    events = run(source, request_for(source, tmp_path, shots=[2]))
    assert [event["shot"] for event in of(events, "shot_converted")] == [2]


def test_workers_give_the_same_bytes(source: Path, tmp_path: Path) -> None:
    datas = {shot: raw_bytes(*range(10_000, 10_000 + 40_000 * shot, 40_000)) for shot in range(1, 7)}
    for shot, data in datas.items():
        write_raw(source, shot, data)
    events = run(source, request_for(source, tmp_path, workers=3))
    assert of(events, "convert_plan")[0]["workers"] == 3
    converted = {event["shot"]: Path(event["txy"]).read_bytes() for event in of(events, "shot_converted")}
    assert converted == {shot: convert_raw(data, MATLAB_2019, "reference") for shot, data in datas.items()}


def test_one_large_shot_is_cut_into_pieces_and_stays_byte_identical(source: Path, tmp_path: Path,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.convert import split
    monkeypatch.setattr(convert, "SPLIT_BYTES", 1)
    monkeypatch.setattr(split, "MIN_ROWS", 4)  # (Pieces this small only here; the default is 50,000 rows.)
    data = raw_bytes(*range(10_000, 2_000_000, 40_000))
    write_raw(source, 1, data)
    events = run(source, request_for(source, tmp_path, workers=2))
    [done] = of(events, "shot_converted")
    assert Path(done["txy"]).read_bytes() == convert_raw(data, MATLAB_2019, "reference")


# Where the TXY go (Q9.3, Q9.7).


def test_cache_output_is_keyed_by_the_data_root(source: Path, tmp_path: Path, private_store: str) -> None:
    write_raw(source, 1, raw_bytes(10_000))
    events = run(source, request_for(source, tmp_path, private_store, destination="cache"))
    [plan] = of(events, "convert_plan")
    assert plan["output"] == "cache" and plan["fallback"] == ""
    assert plan["key"].startswith("root://") and plan["key"].endswith("/source")
    assert plan["folder"] == folder_for(private_store, plan["key"])
    assert Path(plan["folder"], "d_txy_helab_m19v1_1.txt").is_file()


@pytest.mark.no_auto_data_root
def test_a_folder_without_a_data_root_goes_to_the_temp_folder(source: Path, tmp_path: Path,
                                                              private_store: str) -> None:
    write_raw(source, 1, raw_bytes(10_000))
    events = run(source, request_for(source, tmp_path, private_store, destination="cache"))
    [plan] = of(events, "convert_plan")
    assert plan["output"] == "temp" and plan["fallback"] == "no .helab-root found here or above"
    assert plan["folder"].startswith(str(tmp_path / "temps")) and plan["key"] == ""
    assert len(of(events, "shot_converted")) == 1


class Writes:
    """Every write, rename, link, removal or folder made, by path, while it is entered (the
    source-folder audit)."""

    def __enter__(self) -> Writes:
        self.patches = pytest.MonkeyPatch()
        self._patch(self.patches)
        return self

    def __exit__(self, *_: object) -> None:
        self.patches.undo()

    def _patch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.paths: list[str] = []
        flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
        real_open, real_os_open = builtins.open, os.open

        def opened(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            if any(letter in mode for letter in "wax+"):
                self.paths.append(str(file))
            return real_open(file, mode, *args, **kwargs)

        def os_opened(path: Any, flag: int, *args: Any, **kwargs: Any) -> int:
            if flag & flags:
                self.paths.append(str(path))
            return real_os_open(path, flag, *args, **kwargs)
        monkeypatch.setattr(builtins, "open", opened)
        monkeypatch.setattr(io, "open", opened)  # (pathlib's open, write_bytes and write_text use it.)
        monkeypatch.setattr(os, "open", os_opened)
        for name in ("replace", "rename", "renames", "link", "symlink", "unlink", "remove", "mkdir", "makedirs",
                     "rmdir", "utime", "truncate", "chmod"):
            real = getattr(os, name)

            def wrapped(*args: Any, _real: Any = real, **kwargs: Any) -> Any:
                self.paths.extend(str(arg) for arg in args[:2] if isinstance(arg, (str, os.PathLike)))
                return _real(*args, **kwargs)
            monkeypatch.setattr(os, name, wrapped)

    def inside(self, folder: Path) -> list[str]:
        return [path for path in self.paths if Path(path).parent == folder or Path(path) == folder]


def flag_beside(private_store: str, source: Path, on: bool = True) -> None:
    events: list[Any] = []
    cache_admin(options(private_store), "convert_prefs", events.append, path=str(source), write_beside=on,
                set_at=time.time())
    assert of(events, "convert_prefs")[0]["prefs"]["write_beside"] is on


def test_beside_needs_the_folders_flag(source: Path, tmp_path: Path, private_store: str) -> None:
    write_raw(source, 1, raw_bytes(10_000))
    events = run(source, request_for(source, tmp_path, private_store, destination="cache", beside=True))
    [plan] = of(events, "convert_plan")
    assert plan["output"] == "cache" and plan["fallback"] == "writing beside the raw files is off for this folder"
    assert sorted(path.name for path in source.iterdir()) == ["d1.txt"]


def test_beside_writes_only_its_txy_into_the_source_folder(source: Path, tmp_path: Path, private_store: str) -> None:
    """AGENTS.md's write rule: in a source folder HeLab writes only ``d_txy_helab_<tag>_<N>.txt`` (a
    temporary name, then renamed) and never touches raw files or an existing TXY."""
    for shot in (1, 2, 3):
        write_raw(source, shot, raw_bytes(10_000 * shot))
    (source / "d_txy_forc1.txt").write_bytes(b"MATLAB's\n")
    older_beside(source, 3, b"someone else's\n")
    before = {path.name: path.read_bytes() for path in source.iterdir()}
    flag_beside(private_store, source)
    with Writes() as writes:
        events = run(source, request_for(source, tmp_path, private_store, destination="cache", beside=True))
    [plan] = of(events, "convert_plan")
    assert plan["output"] == "beside" and plan["txy_folder"] == str(source) and plan["folder"] != str(source)
    assert sorted(event["shot"] for event in of(events, "shot_converted")) == [1, 2]
    # The one already there stays as it was.
    [kept] = of(events, "shot_kept")
    assert kept["shot"] == 3 and "never replaced" in kept["reason"]
    after = {path.name: path.read_bytes() for path in source.iterdir()}
    assert {name: data for name, data in after.items() if name in before} == before
    assert sorted(set(after) - set(before)) == ["d_txy_helab_m19v1_1.txt", "d_txy_helab_m19v1_2.txt"]
    touched = {Path(path).name for path in writes.inside(source)}
    assert touched, "the audit saw the writes"
    for name in touched:
        assert name in ("d_txy_helab_m19v1_1.txt", "d_txy_helab_m19v1_2.txt") or (
            name.startswith((".d_txy_helab_m19v1_1.txt.", ".d_txy_helab_m19v1_2.txt."))
            and name.endswith(".partial")), name
    # Provenance is in HeLab's own index (the base's), and HeLab's folder for it isn't even made.
    assert index_rows(plan["folder"])[("m19v1", 1)].output == "beside" and not os.path.exists(plan["folder"])
    # The second time: current, nothing written there at all.
    with Writes() as writes:
        again = run(source, request_for(source, tmp_path, private_store, destination="cache", beside=True))
    assert of(again, "shot_converted") == [] and writes.inside(source) == []


def test_the_command_lines_beside_needs_no_flag(source: Path, tmp_path: Path) -> None:
    write_raw(source, 1, raw_bytes(10_000))
    events = run(source, request_for(source, tmp_path, beside=True, beside_confirmed=True))
    assert of(events, "convert_plan")[0]["output"] == "beside"
    assert (source / "d_txy_helab_m19v1_1.txt").is_file()


# The converter flags in the store.


def test_convert_prefs_newest_wins_cleared_by_clear_prefs_and_rekeyed(tmp_path: Path, private_store: str) -> None:
    folder = tmp_path / "run"
    folder.mkdir()
    with stores._cache_store(store_root(private_store), [str(folder)]) as store:
        assert store.read_convert_prefs([str(folder)])[str(folder)].status == "missing"
        assert store.set_convert_prefs(str(folder), True, 10.0) == {"write_beside": True, "set_at": 10.0}
        assert store.set_convert_prefs(str(folder), False, 5.0)["write_beside"] is True  # Older: refused.
        assert store.read_convert_prefs([str(folder)])[str(folder)].value == {"write_beside": True, "set_at": 10.0}
        assert store.inventory(None)["prefs"]["write_beside"] == 1
        key = store._path_key(str(folder))
        assert str(folder) in store.clear_prefs(20.0)
        assert store.read_convert_prefs([str(folder)])[str(folder)].value == {"write_beside": False, "set_at": 20.0}
        assert store.set_convert_prefs(str(folder), True, 15.0)["write_beside"] is False  # Chosen before the Clear.
        store.set_convert_prefs(str(folder), True, 30.0)
        moved = store.rekey_subtree(key.rsplit("/", 1)[0], "root://other")
        assert key in moved
        row = store._conn.execute("SELECT path, write_beside FROM convert_prefs").fetchall()
        assert row == [("root://other/run", 1)]


def test_an_older_store_gains_the_convert_prefs_table(tmp_path: Path, private_store: str) -> None:
    import sqlite3
    from helab.utils.cache_store import CacheStore
    root = store_root(private_store)
    with CacheStore(root, root_mode=True):
        pass
    database = sqlite3.connect(os.path.join(root, "records.sqlite"))
    database.execute("DROP TABLE convert_prefs")
    database.commit()
    database.close()
    with CacheStore(root, root_mode=True) as store:
        assert store._conn.execute("SELECT COUNT(*) FROM convert_prefs").fetchone() == (0,)


# The helper process and the app's side.


def helper(request: dict[str, Any], *, timeout: float = 60) -> list[dict[str, Any]]:
    done = subprocess.run([sys.executable, "-m", "helab.io_helper"], input=json.dumps(request) + "\n",
                          capture_output=True, text=True, timeout=timeout, cwd=ROOT, env=dict(os.environ))
    assert done.returncode == 0, done.stderr
    return [json.loads(line) for line in done.stdout.splitlines() if line.strip()]


def test_the_helper_dispatches_convert_and_refuses_it_offline(source: Path, tmp_path: Path,
                                                              private_store: str) -> None:
    write_raw(source, 1, raw_bytes(10_000))
    request = {"operation": "convert", **request_for(source, tmp_path, private_store, destination="cache")}
    events = helper(request)
    assert [event["kind"] for event in events][-2:] == ["convert_summary", "done"]
    assert len(of(events, "shot_converted")) == 1
    offline = helper({**request, "cache": {**options(private_store), "offline": True}})
    assert offline[-1]["kind"] == "error" and "offline" in offline[-1]["message"].lower()
    from helab.utils.io_service import IOService
    assert "convert" not in IOService.OFFLINE_OPERATIONS and "convert" in IOService.PAUSABLE
    assert "convert" not in IOService.LOCAL_OPERATIONS and "convert" in IOService.LABELS


# A path the source guard refuses on each platform (it doesn't exist); its note names it as sent.
MOUNTED = "\\\\no-such-server\\share\\run_1" if sys.platform == "win32" else "/Volumes/helab-no-such-share/run_1"


def test_the_helper_refuses_a_source_path_that_could_be_real_data(tmp_path: Path) -> None:
    notes = Path(os.environ["HELAB_TEST_SOURCE_GUARD"])
    try:
        events = helper({"operation": "convert", **request_for(Path(MOUNTED), tmp_path)})
        assert events[-1]["kind"] == "error"
        # (The note holds the path as the request had it: str(Path(...)), backslashes on Windows.)
        assert any(str(Path(MOUNTED)) in note.read_text() for note in notes.glob("*.txt"))
    finally:
        for note in notes.glob("*.txt"):
            note.unlink()


def test_a_killed_helpers_workers_exit(source: Path, tmp_path: Path) -> None:
    """Cancelling (killing) a converting helper ends its workers too, and nothing is written
    after: workers only compute."""
    import psutil
    for shot in range(1, 31):  # ~1 MB each, ~0.1 s each with the plain-Python reference
        write_raw(source, shot, raw_bytes(*range(10_000, 10_000 + 40_000 * 20_000, 40_000)))
    request = {"operation": "convert", **request_for(source, tmp_path, workers=2, backend="reference")}
    process = subprocess.Popen([sys.executable, "-m", "helab.io_helper"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True, cwd=ROOT, env=dict(os.environ))
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.flush()
    for line in process.stdout:
        if json.loads(line)["kind"] == "shot_converted":
            break
    children = psutil.Process(process.pid).children(recursive=True)
    assert children, "the pool started"
    process.kill()
    process.wait(10)
    gone, alive = psutil.wait_procs(children, timeout=15)
    assert alive == []
    folder = Path(folder_for(str(tmp_path / "temps"), "path:" + str(source)))
    names = sorted(path.name for path in folder.iterdir())
    time.sleep(0.5)
    assert sorted(path.name for path in folder.iterdir()) == names  # Nothing written after the kill.
    # The kill may land in a write: its temporary file stays (on Windows, where the flush to disk
    # takes most of each write, it usually does; a later conversion removes it once old), but no
    # TXY under its own name is ever half written.
    expected = convert_raw(raw_bytes(*range(10_000, 10_000 + 40_000 * 20_000, 40_000)), MATLAB_2019, "reference")
    assert all(path.read_bytes() == expected for path in folder.glob("d_txy_helab_*.txt"))
    assert all(convert.own_partial().match(name) for name in names if name.endswith(".partial"))


def test_the_numba_backends_cache_folder_is_in_the_temp_folder(source: Path, tmp_path: Path, private_store: str,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """Q18.1: in HeLab's temp folder, not the cache's, also when the request has a disk cache."""
    from helab.convert.backends import numba_backend
    folders: list[str] = []
    monkeypatch.setattr(numba_backend, "set_cache_folder", lambda folder: folders.append(str(folder)))
    write_raw(source, 1, raw_bytes(10_000))
    try:
        run(source, request_for(source, tmp_path, private_store, backend="numba"))
    except RuntimeError:
        pass  # (numba not installed here: the backend can't run, after the folder was set.)
    assert folders == [os.path.join(str(tmp_path / "temps"), "numba")]


def test_an_unavailable_backend_fails_the_conversion_before_any_read(source: Path, tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.convert import reconstruct
    from helab.convert.backends import numpy_backend  # noqa: F401  (registered)
    backend = reconstruct.get_backend("numpy")
    monkeypatch.setitem(reconstruct._BACKENDS, "numpy", reconstruct.Backend(
        name="numpy", run=backend.run, unavailable=lambda profile: "not here"))
    write_raw(source, 1, raw_bytes(10_000))
    with pytest.raises(reconstruct.BackendError, match="not here"):
        run(source, request_for(source, tmp_path))


def test_the_file_kind_is_counted_but_not_loaded() -> None:
    assert file_kinds.match("d_txy_helab_m19v1_12.txt") == (file_kinds.HELAB_TXY, 12)
    assert file_kinds.match("d_txy_helab_u0123abcd_3.txt") == (file_kinds.HELAB_TXY, 3)
    assert provenance.parse_txy_name("d_txy_helab_p25t1_40.txt") == ("p25t1", 40)
    kind = file_kinds.HELAB_TXY
    assert not kind.loaded and not kind.counted_empty
    # The untagged names of before Q18.4 are no HeLab TXY any more: never matched, so never loaded or removed.
    for name in ("d_txy_helab_12.txy", "d_txy_helab_12.txt", "d_txy_helab_m19v1_12.txy", ".d_txy_helab_m19v1_1.txt.ab.partial",
                 "d_txy_helab_m19v1_07.txt", "d_txy_helab_m19v1_\u0661.txt", "d_txy_helab_m19v1_.txt",
                 "d_txy_helab_m_1.txt", "d_txy_helab_M19v1_1.txt", "d_txy_helab_1x_1.txt", "d_txy_helab_m19v1_1_2.txt",
                 "d_txy_helab_abcdefghijklmnopq_1.txt", "d_txy_helab_m19-v1_1.txt"):
        assert file_kinds.match(name) is None and not provenance.TXY_PATTERN.match(name), name
    # The file kind and the provenance module agree (the tag a group only in the latter).
    for name in ("d_txy_helab_m19v1_0.txt", "d_txy_helab_abcdefghijklmnop_9.txt"):
        found = provenance.TXY_PATTERN.fullmatch(name)
        assert found and file_kinds.match(name) == (file_kinds.HELAB_TXY, int(found["shot"])), name
    assert file_kinds.files_summary({"helab_txy": {1, 2}}, {})["helab_txy"] == {"count": 2}
    assert "helab_txy" not in file_kinds.files_summary({"raw": {1}}, {})  # (Summaries keep their shape.)


def test_the_output_setting_defaults_to_the_cache() -> None:
    from helab.utils.constants import read_convert_output
    from helab.utils.settings_defaults import CONVERT_OUTPUT_SETTING
    from helab.utils.settings_store import app_settings
    settings = app_settings()
    assert read_convert_output(settings) == "cache"
    settings.setValue(CONVERT_OUTPUT_SETTING, "temp")
    assert read_convert_output(settings) == "temp"
    settings.setValue(CONVERT_OUTPUT_SETTING, "beside")  # Not a setting value: a folder's flag.
    assert read_convert_output(settings) == "cache"


# The registry's first load (the lock in reconstruct._load).

FIRST_LOAD = """
import sys, threading
from helab.convert import reconstruct
start = threading.Barrier(24)
failures = []
def load(k):
    start.wait()
    try:
        names = sorted(reconstruct._MODULES)
        name = names[k % len(names)]
        backend = reconstruct.get_backend(name)
        assert backend.name == name
        assert "numpy" in reconstruct.backends()
    except Exception as error:
        failures.append(f"thread {k}: {error!r}")
threads = [threading.Thread(target=load, args=(k,)) for k in range(24)]
for thread in threads: thread.start()
for thread in threads: thread.join()
print("ok" if not failures else "; ".join(failures))
"""


@pytest.mark.parametrize("attempt", range(3))
def test_many_threads_loading_backends_at_once(attempt: int) -> None:
    done = subprocess.run([sys.executable, "-c", FIRST_LOAD], capture_output=True, text=True, timeout=120,
                          env=dict(os.environ), cwd=ROOT)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines()[-1] == "ok"


# helab convert --watch.


def cli(*args: str, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "helab", "convert", *args], capture_output=True, text=True,
                          timeout=timeout, cwd=ROOT, env=dict(os.environ))


def test_convert_once_from_the_command_line(source: Path, tmp_path: Path) -> None:
    data = raw_bytes(10_000, 20_000)
    write_raw(source, 1, data)
    write_raw(source, 2, b"")
    done = cli("--watch", str(source), "--once", "--output", "beside")
    assert done.returncode == 0, done.stderr
    assert (source / "d_txy_helab_m19v1_1.txt").read_bytes() == convert_raw(data, MATLAB_2019, "reference")
    assert "d1.txt -> d_txy_helab_m19v1_1.txt: 2 hits" in done.stderr
    assert "d2.txt can't be converted" in done.stderr
    assert cli("--watch", str(tmp_path / "missing"), "--once").returncode == 2
    assert cli("--watch", str(source), "--once", "--profile", "no-such-profile").returncode == 2


@pytest.fixture
def watching(source: Path) -> Iterator[subprocess.Popen[str]]:
    # A shell starts a background job (`pytest … &`) with SIGINT ignored, which children inherit and
    # Python then leaves alone, so the watcher would never see Ctrl-C. Start it as from a terminal:
    # a handled SIGINT is reset to the default by exec, and Python installs its handler.
    previous = signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        process = subprocess.Popen([sys.executable, "-m", "helab", "convert", "--watch", str(source), "--output",
                                    "beside", "--interval", "0.2"], stderr=subprocess.PIPE, text=True, cwd=ROOT,
                                   env=dict(os.environ))
    finally:
        if previous is not None:
            signal.signal(signal.SIGINT, previous)
    yield process
    if process.poll() is None:
        process.kill()
        process.wait(10)


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT to a child process is a console event on Windows")
def test_watch_converts_new_shots_and_stops_on_ctrl_c(source: Path, watching: subprocess.Popen[str]) -> None:
    data = raw_bytes(10_000)
    write_raw(source, 7, data)
    deadline = time.monotonic() + 30
    while not (source / "d_txy_helab_m19v1_7.txt").exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert (source / "d_txy_helab_m19v1_7.txt").read_bytes() == convert_raw(data, MATLAB_2019, "reference")
    watching.send_signal(signal.SIGINT)
    assert watching.wait(20) == 0
    assert watching.stderr is not None and "Stopped" in watching.stderr.read()


# Gannet's review: the two-check rule, the clock, kept shots, the record first, leftovers, budgets.


def test_a_request_without_seen_is_refused(source: Path, tmp_path: Path) -> None:
    write_raw(source, 1, raw_bytes(10_000))
    request = request_for(source, tmp_path)
    del request["seen"]  # type: ignore[misc]
    with pytest.raises(ValueError, match="needs `seen`"):
        run(source, request)


def test_a_first_conversion_only_records_then_converts_and_finds_converted_shots_current(
        source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fingerprints, "SETTLE_SECONDS", 5.0)
    for shot in (1, 2):
        write_raw(source, shot, raw_bytes(10_000 * shot))
    first = run(source, request_for(source, tmp_path, seen=[]))
    assert of(first, "shot_converted") == [] and {e["reason"] for e in of(first, "shot_waiting")} == {raw.CHANGED}
    second = run(source, request_for(source, tmp_path, seen=summary(first)["waiting"]))
    assert sorted(event["shot"] for event in of(second, "shot_converted")) == [1, 2]
    # Another session's first look (seen=[]): converted shots are current at once, only new ones wait.
    write_raw(source, 3, raw_bytes(30_000))
    third = run(source, request_for(source, tmp_path, seen=[]))
    assert sorted(entry[0] for entry in summary(third)["current"]) == ["d1.txt", "d2.txt"]
    assert [event["shot"] for event in of(third, "shot_waiting")] == [3]


def test_a_single_check_wants_a_minute_of_age(source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """seen None (helab convert --once): no second check, so the age stands for it."""
    monkeypatch.setattr(fingerprints, "SETTLE_SECONDS", 5.0)
    write_raw(source, 1, raw_bytes(10_000), mtime=time.time() - 30)
    write_raw(source, 2, raw_bytes(20_000), mtime=time.time() - 70)
    events = run(source, request_for(source, tmp_path, seen=None))
    assert [(event["shot"], event["reason"]) for event in of(events, "shot_waiting")] == [(1, raw.SETTLING)]
    assert [event["shot"] for event in of(events, "shot_converted")] == [2]
    # With two checks, 5 s of age is enough.
    again = run(source, request_for(source, tmp_path, seen=summary(events)["waiting"]))
    assert [event["shot"] for event in of(again, "shot_converted")] == [1]


def test_kept_shots_stay_kept_when_the_summary_is_sent_back(source: Path, tmp_path: Path) -> None:
    write_raw(source, 1, raw_bytes(10_000))
    write_raw(source, 2, raw_bytes(20_000))
    older_beside(source, 1, b"another computer's\n")
    request = request_for(source, tmp_path, beside=True, beside_confirmed=True, seen=[])
    events = run(source, request)
    assert [event["shot"] for event in of(events, "shot_kept")] == [1]
    for _ in range(3):
        done = summary(events)
        request["seen"], request["done"] = done["waiting"], done["current"]
        request["kept"], request["skip"] = done["kept"], done["unconvertible"]
        events = run(source, request)
        assert of(events, "shot_kept") == [] and all(event["shot"] != 1 for event in of(events, "shot_waiting"))
        assert [entry[0] for entry in summary(events)["kept"]] == ["d1.txt"]
    assert (source / "d_txy_helab_m19v1_1.txt").read_bytes() == b"another computer's\n"
    assert (source / "d_txy_helab_m19v1_2.txt").is_file()


@pytest.mark.parametrize("beside", [True, False])
def test_a_write_killed_after_its_row_is_converted_again(source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                         beside: bool) -> None:
    """The row goes in before the rename, naming the very file (size and mtime): killed between them, the
    row stays (nothing cleans up after a kill) but matches no TXY there, so the shot is converted again:
    beside, where no TXY is there yet; in HeLab's folder, even over an older TXY of the same size."""
    write_raw(source, 1, raw_bytes(10_000))
    request = request_for(source, tmp_path, beside=beside, beside_confirmed=beside)
    folder = Path(folder_for(str(tmp_path / "temps"), "path:" + str(source)))
    if not beside:
        [first] = of(run(source, request_for(source, tmp_path)), "shot_converted")
        age(Path(first["txy"]), 600)  # (An older TXY of the same size: a stopped redo leaves it.)
        request = request_for(source, tmp_path, redo="always")
    original = txy.write_atomic

    def killed(path: Any, data: bytes, *, replace: bool = True, before_rename: Any = None) -> None:
        def then_killed(info: os.stat_result) -> None:
            before_rename(info)
            raise KeyboardInterrupt  # (Killed between the row and the rename.)
        original(path, data, replace=replace, before_rename=then_killed)
    monkeypatch.setattr(txy, "write_atomic", killed)
    monkeypatch.setattr(provenance.TxyIndex, "forget", lambda *args: False)  # (A kill runs no clean-up.)
    with pytest.raises(KeyboardInterrupt):
        run(source, request)
    monkeypatch.undo()
    [row] = index_rows(folder).values()
    there = (source if beside else folder) / "d_txy_helab_m19v1_1.txt"
    assert there.exists() is not beside
    if not beside:
        assert there.stat().st_size == row.txy_size and there.stat().st_mtime_ns != row.txy_mtime_ns
    events = run(source, request_for(source, tmp_path, beside=beside, beside_confirmed=beside))
    assert [event["shot"] for event in of(events, "shot_converted")] == [1] and of(events, "shot_kept") == []
    assert of(run(source, request_for(source, tmp_path, beside=beside, beside_confirmed=beside)), "shot_converted") == []


def test_a_failed_write_removes_its_row_only_if_still_its_own(source: Path, tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    write_raw(source, 1, raw_bytes(10_000))
    folder = Path(folder_for(str(tmp_path / "temps"), "path:" + str(source)))
    original = txy.write_atomic
    theirs = provenance_record(shot=1, txy_name="d_txy_helab_m19v1_1.txt", txy_sha256="theirs")

    def failing(path: Any, data: bytes, *, replace: bool = True, before_rename: Any = None) -> None:
        def then_fail(info: os.stat_result) -> None:
            before_rename(info)
            if overtaken:  # Another conversion writes its own row meanwhile: it stands.
                with provenance.open_index(str(folder.parent), write=True) as index:
                    index.record(folder.name, "", str(source), theirs, 1.0)
            raise OSError(28, "No space left on device")
        original(path, data, replace=replace, before_rename=then_fail)
    monkeypatch.setattr(txy, "write_atomic", failing)
    for overtaken in (False, True):
        with pytest.raises(OSError, match="No space"):
            run(source, request_for(source, tmp_path))
        assert index_rows(folder) == ({("m19v1", 1): theirs} if overtaken else {})
        assert not (folder / "d_txy_helab_m19v1_1.txt").exists()


PARTIAL_NAME = ".d_txy_helab_m19v1_1.txt.0123456789abcdef.partial"


def age(path: Path, seconds: float) -> None:
    then = time.time() - seconds
    if path.is_symlink():
        os.utime(path, (then, then), follow_symlinks=False)
    else:
        os.utime(path, (then, then))


def test_the_partial_pattern_is_exactly_write_atomics_names(tmp_path: Path) -> None:
    pattern = convert.partial()
    made: list[str] = []
    real_open = os.open

    def spy(path: Any, *args: Any, **kwargs: Any) -> int:
        made.append(Path(path).name)
        return real_open(path, *args, **kwargs)
    with pytest.MonkeyPatch.context() as patches:
        patches.setattr(os, "open", spy)
        txy.write_atomic(tmp_path / "d_txy_helab_m19v1_12.txt", b"")
    assert any(pattern.match(name) for name in made)
    assert pattern.match(PARTIAL_NAME)
    for name in (".d_txy_helab_m19v1_1.txt.0123456789abcdeg.partial", ".d_txy_helab_m19v1_1.txt.0123456789abcde.partial",
                 PARTIAL_NAME + ".bak", "x" + PARTIAL_NAME, PARTIAL_NAME[1:], ".d_txy_forc1.txt.0123456789abcdef.partial",
                 ".d_txy_helab_m19v1_1.txt.0123456789ABCDEF.partial", ".d1.txt.0123456789abcdef.partial",
                 ".d_txy_helab_m19v1_07.txt.0123456789abcdef.partial", ".d_txy_helab_\u0661.txy.0123456789abcdef.partial",
                 # Before Q18.4's names: left alone (never removed).
                 ".d_txy_helab_1.txy.0123456789abcdef.partial", ".d_txy_helab_m19v1_1.txy.0123456789abcdef.partial"):
        assert not pattern.match(name), name


RECORD_PARTIAL = ".d_txy_helab_m19v1_1.json.0123456789abcdef.partial"
FOLDER_PARTIAL = ".folder.json.0123456789abcdef.partial"


def test_the_own_folder_pattern_adds_exactly_old_builds_records_temporary_names(tmp_path: Path) -> None:
    """HeLab's folder holds TXY alone since the index (Q26.2); housekeeping there also removes the
    temporaries old builds gave their JSON (each shot's record, ``folder.json``), and nothing else: the
    index's journal is SQLite's, a set-aside index the user's to clear."""
    pattern = convert.own_partial()
    made: list[str] = []
    real_open = os.open

    def spy(path: Any, *args: Any, **kwargs: Any) -> int:
        made.append(Path(path).name)
        return real_open(path, *args, **kwargs)
    with pytest.MonkeyPatch.context() as patches:
        patches.setattr(os, "open", spy)
        for name in ("d_txy_helab_m19v1_12.txt", "d_txy_helab_m19v1_12.json", "folder.json"):
            txy.write_atomic(tmp_path / name, b"")
    assert sum(bool(pattern.match(name)) for name in made) == 3
    for name in (PARTIAL_NAME, RECORD_PARTIAL, FOLDER_PARTIAL, ".d_txy_helab_m19v1_0.json.fedcba9876543210.partial"):
        assert pattern.match(name), name
    # Source folders keep the TXY's names only: no JSON was ever written there.
    assert not convert.partial().match(RECORD_PARTIAL) and not convert.partial().match(FOLDER_PARTIAL)
    for name in (".d_txy_helab_m19v1_1.json.0123456789abcdeg.partial", ".d_txy_helab_m19v1_1.json.0123456789abcde.partial",
                 ".d_txy_helab_m19v1_1.json.0123456789ABCDEF.partial", ".d_txy_helab_m19v1_07.json.0123456789abcdef.partial",
                 ".d_txy_helab_\u0661.json.0123456789abcdef.partial", RECORD_PARTIAL + ".bak", RECORD_PARTIAL[1:],
                 "x" + RECORD_PARTIAL, ".d_txy_forc1.json.0123456789abcdef.partial", ".d1.json.0123456789abcdef.partial",
                 FOLDER_PARTIAL + ".bak", FOLDER_PARTIAL[1:], ".xfolder.json.0123456789abcdef.partial",
                 ".Folder.json.0123456789abcdef.partial", ".folder.jsonl.0123456789abcdef.partial",
                 ".folderxjson.0123456789abcdef.partial", ".notes.json.0123456789abcdef.partial",
                 ".d_txy_helab_1.json.0123456789abcdef.partial", provenance.INDEX_NAME, provenance.INDEX_NAME + "-journal",
                 ".index.sqlite.0123456789abcdef.partial", "index-damaged-20261029T120000Z-0123abcd.sqlite"):
        assert not pattern.match(name), name


def test_a_beside_conversion_removes_only_its_own_old_leftovers(source: Path, tmp_path: Path) -> None:
    write_raw(source, 1, raw_bytes(10_000))
    old = source / PARTIAL_NAME
    old.write_bytes(b"half")
    age(old, 2 * 3600)
    young = source / ".d_txy_helab_m19v1_2.txt.fedcba9876543210.partial"
    young.write_bytes(b"half")
    age(young, 600)
    lookalikes = [source / name for name in (".d_txy_helab_m19v1_3.txt.0123456789abcdeg.partial", PARTIAL_NAME + ".bak",
                                             ".d_txy_forc1.txt.0123456789abcdef.partial", "notes.partial")]
    for path in lookalikes:
        path.write_bytes(b"keep")
        age(path, 2 * 3600)
    elsewhere = tmp_path / "elsewhere.txt"
    elsewhere.write_bytes(b"not HeLab's")
    age(elsewhere, 2 * 3600)
    link = source / ".d_txy_helab_m19v1_4.txt.aaaaaaaaaaaaaaaa.partial"
    try:
        link.symlink_to(elsewhere)
        age(link, 2 * 3600)
    except (OSError, NotImplementedError):  # (Windows without the privilege to make links.)
        pass
    # Not writing beside: nothing removed.
    run(source, request_for(source, tmp_path))
    assert old.exists()
    events = run(source, request_for(source, tmp_path, beside=True, beside_confirmed=True))
    assert [(event["file"], event["size"]) for event in of(events, "partial_removed")] == [(PARTIAL_NAME, 4)]
    assert not old.exists() and young.exists() and elsewhere.read_bytes() == b"not HeLab's"
    assert link.is_symlink() or sys.platform == "win32"
    assert all(path.exists() for path in lookalikes)


KILLED_WRITE = """
import json, os, sys
from helab.convert import txy
from helab.io_ops import convert
request = json.loads(sys.argv[1])
# Killed mid-write: the temporary file beside the raw files has its bytes, not yet renamed.
txy._rename_new = lambda temporary, target: os._exit(9)
convert.convert_folder(request["path"], request, lambda event: None)
"""


def test_a_killed_beside_writes_leftover_goes_on_a_later_pass_once_old(source: Path, tmp_path: Path) -> None:
    write_raw(source, 1, raw_bytes(10_000))
    request = request_for(source, tmp_path, beside=True, beside_confirmed=True)
    done = subprocess.run([sys.executable, "-c", KILLED_WRITE, json.dumps(request)], cwd=ROOT, env=dict(os.environ),
                          timeout=60, capture_output=True, text=True)
    leftovers = [path for path in source.iterdir() if convert.partial().match(path.name)]
    assert done.returncode == 9 and len(leftovers) == 1 and not (source / "d_txy_helab_m19v1_1.txt").exists(), done.stderr
    events = run(source, request)  # Too young: left, and the shot converted beside it.
    assert of(events, "partial_removed") == [] and leftovers[0].exists()
    assert (source / "d_txy_helab_m19v1_1.txt").is_file()
    age(leftovers[0], 2 * 3600)
    events = run(source, request)
    assert [event["file"] for event in of(events, "partial_removed")] == [leftovers[0].name]
    assert sorted(path.name for path in source.iterdir()) == ["d1.txt", "d_txy_helab_m19v1_1.txt"]


def convert_clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """``io_ops.convert``'s monotonic clock, moved only by the test (the ticker's waits keep real
    time): a compute budget can't run out while a loaded runner holds the ticker's thread back."""
    now = [time.monotonic()]
    monkeypatch.setattr(convert, "time", SimpleNamespace(monotonic=lambda: now[0], perf_counter=time.perf_counter,
                                                         time=time.time))
    return now


def wait_for(condition: Callable[[], bool], timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_heartbeats_while_computing_stop_after_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.io_ops.infra import Heartbeat
    monkeypatch.setattr(Heartbeat, "INTERVAL", 0.02)
    now = convert_clock(monkeypatch)
    beats: list[dict[str, Any]] = []
    ticker = convert._Ticker(lambda event: beats.append(dict(event)), "converting", 0.15)
    with ticker:
        wait_for(lambda: len(beats) >= 2)
        now[0] += 0.15
        # The budget spent, the ticker stops by itself while the shot still computes.
        ticker.thread.join(30)
        assert not ticker.thread.is_alive() and not ticker.stop.is_set()
    assert {(beat["kind"], beat["phase"]) for beat in beats} == {("heartbeat", "converting")}
    assert convert.still_computing([10.0, 20.0], 15.0) and not convert.still_computing([10.0, 12.0], 15.0)
    assert not convert.still_computing([], 0.0)
    assert convert.compute_budget(0) == convert.COMPUTE_SECONDS
    assert convert.compute_budget(50 * 10**6) == convert.COMPUTE_SECONDS + 50


def test_a_hung_backend_stops_sending_heartbeats(source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.convert import pipeline
    from helab.io_ops.infra import Heartbeat
    monkeypatch.setattr(Heartbeat, "INTERVAL", 0.02)
    now = convert_clock(monkeypatch)
    tickers: list[convert._Ticker] = []

    class Ticker(convert._Ticker):
        def __enter__(self) -> convert._Ticker:
            tickers.append(self)
            return super().__enter__()
    monkeypatch.setattr(convert, "_Ticker", Ticker)
    events: list[dict[str, Any]] = []

    def beats() -> int:
        return sum(event["kind"] == "heartbeat" and event["phase"] == "converting" for event in list(events))
    original = pipeline.convert_shot
    stopped: list[bool] = []

    def hung(*args: Any, **kwargs: Any) -> Any:
        wait_for(lambda: beats() > 0)  # Heartbeats while it computes,
        now[0] += 3600  # until it has computed past its budget: then they stop, though it goes on.
        tickers[0].thread.join(30)
        stopped.append(not tickers[0].thread.is_alive() and not tickers[0].stop.is_set())
        return original(*args, **kwargs)
    monkeypatch.setattr(pipeline, "convert_shot", hung)
    write_raw(source, 1, raw_bytes(10_000))
    convert_folder(str(source), request_for(source, tmp_path), lambda event: events.append(dict(event)))
    assert stopped == [True] and len(tickers) == 1 and len(of(events, "shot_converted")) == 1


@pytest.mark.no_auto_data_root
def test_beside_without_a_data_root_says_where_the_records_go(source: Path, tmp_path: Path,
                                                              private_store: str) -> None:
    write_raw(source, 1, raw_bytes(10_000))
    events = run(source, request_for(source, tmp_path, private_store, destination="cache", beside=True,
                                     beside_confirmed=True))
    [plan] = of(events, "convert_plan")
    assert plan["output"] == "beside"
    assert plan["fallback"] == "the provenance rows go to the temp folder's index: no .helab-root found here or above"


def test_a_flag_that_cant_be_read_is_said_so(source: Path, tmp_path: Path, private_store: str,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.utils.cache_store import CacheStore, Read
    monkeypatch.setattr(CacheStore, "read_convert_prefs",
                        lambda self, paths: {path: Read("error", None, "database is locked") for path in paths})
    write_raw(source, 1, raw_bytes(10_000))
    events = run(source, request_for(source, tmp_path, private_store, destination="cache", beside=True))
    [plan] = of(events, "convert_plan")
    assert plan["output"] == "cache" and plan["fallback"] == "the folder's flag couldn't be read (database is locked)"


# Gannet round 2.


def test_a_kept_or_done_shot_whose_beside_txy_is_deleted_is_converted_again(source: Path, tmp_path: Path) -> None:
    write_raw(source, 1, raw_bytes(10_000))
    write_raw(source, 2, raw_bytes(20_000))
    older_beside(source, 1, b"another computer's\n")
    request = request_for(source, tmp_path, beside=True, beside_confirmed=True)
    events = run(source, request)
    assert [event["shot"] for event in of(events, "shot_kept")] == [1]
    assert [event["shot"] for event in of(events, "shot_converted")] == [2]
    # The user deletes both TXY; with the summary sent back, both are converted again.
    (source / "d_txy_helab_m19v1_1.txt").unlink()
    (source / "d_txy_helab_m19v1_2.txt").unlink()
    done = summary(events)
    request["seen"], request["done"], request["kept"] = done["waiting"], done["current"], done["kept"]
    again = run(source, request)
    assert sorted(event["shot"] for event in of(again, "shot_converted")) == [1, 2]
    assert (source / "d_txy_helab_m19v1_1.txt").read_bytes() == convert_raw(raw_bytes(10_000), MATLAB_2019, "reference")


def test_a_lost_beside_race_leaves_the_other_conversions_record(source: Path, tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """Two conversions of one folder at once: the one that finds the TXY written meanwhile removes
    its own row only if it is still its own."""
    write_raw(source, 1, raw_bytes(10_000))
    request = request_for(source, tmp_path, beside=True, beside_confirmed=True)
    folder = Path(folder_for(str(tmp_path / "temps"), "path:" + str(source)))
    theirs = provenance_record(shot=1, output="beside", txy_sha256="theirs")
    original = txy.write_atomic
    rival_row = True

    def raced(path: Any, data: bytes, *, replace: bool = True, before_rename: Any = None) -> None:
        def then_theirs(info: os.stat_result) -> None:
            before_rename(info)
            # The other conversion: its row and then its TXY land between ours.
            if rival_row:
                with provenance.open_index(str(folder.parent), write=True) as index:
                    index.record(folder.name, "", str(source), theirs, 1.0)
            Path(path).write_bytes(b"the other conversion's\n")
        original(path, data, replace=replace, before_rename=then_theirs)
    monkeypatch.setattr(txy, "write_atomic", raced)
    events = run(source, request)
    assert [event["shot"] for event in of(events, "shot_kept")] == [1]
    assert index_rows(folder) == {("m19v1", 1): theirs}
    # Without a rival row, ours (unmatched by any TXY) goes.
    (source / "d_txy_helab_m19v1_1.txt").unlink()
    with provenance.open_index(str(folder.parent), write=True) as index:
        index.forget(folder.name, theirs)
    rival_row = False
    run(source, request)
    assert index_rows(folder) == {}



def test_a_conversion_through_the_apps_io_service(qtbot: QtBot, source: Path, tmp_path: Path,
                                                   private_store: str) -> None:
    """The app's path end to end: ``IOService.submit`` starts a real helper, which gets the payload
    plus the service's own fields (its private folder is the request's ``output``, so the converter's
    is ``destination``)."""
    from helab.utils.io_service import IOService
    data = raw_bytes(10_000, 20_000)
    write_raw(source, 1, data)
    payload = dict(request_for(source, tmp_path, private_store, destination="cache"))
    payload.pop("path")
    service = IOService()
    events: list[dict[str, Any]] = []
    service.resultReady.connect(lambda request, event: events.append(event) if request.owner == "convert" else None)
    try:
        assert service.submit("convert", 0, str(source), "convert", payload)
        qtbot.waitUntil(lambda: any(event["kind"] in ("done", "error") for event in events), timeout=60_000)
        assert [event for event in events if event["kind"] == "error"] == []
        [plan] = of(events, "convert_plan")
        assert plan["output"] == "cache" and plan["key"].startswith("root://")
        [converted] = of(events, "shot_converted")
        assert Path(converted["txy"]).read_bytes() == convert_raw(data, MATLAB_2019, "reference")
        qtbot.waitUntil(lambda: not service.active, timeout=30_000)
    finally:
        service.shutdown()


def test_a_conversion_removes_old_leftovers_in_helabs_own_folder(source: Path, tmp_path: Path) -> None:
    """A helper killed mid-write in HeLab's own folder (likely on Windows) leaves a temporary file
    there too: removed by a later conversion once old, a young one kept."""
    write_raw(source, 1, raw_bytes(10_000))
    folder = Path(folder_for(str(tmp_path / "temps"), "path:" + str(source)))
    folder.mkdir(parents=True)
    # (Old builds' JSON temporaries too: the index's builds write none, but theirs are HeLab's leftovers.)
    old = [folder / name for name in (PARTIAL_NAME, RECORD_PARTIAL, FOLDER_PARTIAL)]
    young = [folder / name for name in (".d_txy_helab_m19v1_2.txt.fedcba9876543210.partial",
                                        ".d_txy_helab_m19v1_2.json.fedcba9876543210.partial",
                                        ".folder.json.fedcba9876543210.partial")]
    lookalikes = [folder / name for name in (".d_txy_helab_m19v1_3.json.0123456789abcdeg.partial", RECORD_PARTIAL + ".bak",
                                             ".xfolder.json.0123456789abcdef.partial", "notes.partial")]
    for path, seconds in [(path, 2 * 3600) for path in old + lookalikes] + [(path, 60) for path in young]:
        path.write_bytes(b"half")
        age(path, seconds)
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_bytes(b"not HeLab's")
    age(elsewhere, 2 * 3600)
    link = folder / ".d_txy_helab_m19v1_4.json.aaaaaaaaaaaaaaaa.partial"
    try:
        link.symlink_to(elsewhere)
        age(link, 2 * 3600)
    except (OSError, NotImplementedError):  # (Windows without the privilege to make links.)
        pass
    events = run(source, request_for(source, tmp_path))
    assert sorted((event["folder"], event["file"]) for event in of(events, "partial_removed")) == sorted(
        (str(folder), path.name) for path in old)
    assert not any(path.exists() for path in old) and all(path.exists() for path in young + lookalikes)
    assert link.is_symlink() or sys.platform == "win32"
    assert elsewhere.read_bytes() == b"not HeLab's"


# HeLab's index (Q26.2): one SQLite file per base, rebuildable.


def index_file(tmp_path: Path) -> Path:
    return tmp_path / "temps" / convert.FOLDER_NAME / provenance.INDEX_NAME


def set_aside(tmp_path: Path) -> list[str]:
    return sorted(name for name in os.listdir(index_file(tmp_path).parent)
                  if provenance.SET_ASIDE_PATTERN.fullmatch(name))


@pytest.mark.parametrize("problem", ["missing", "not a database", "malformed", "newer"])
def test_a_missing_or_damaged_index_only_means_shots_convert_again(source: Path, tmp_path: Path, problem: str) -> None:
    """Never an error the user must fix, never a crash: shots convert again. A damaged or newer index is
    set aside under an exact name (never deleted: Settings → Cache's Clear removes it) and a new one made."""
    write_raw(source, 1, raw_bytes(10_000))
    write_raw(source, 2, raw_bytes(10_000, 20_000))
    folder = Path(folder_for(str(tmp_path / "temps"), "path:" + str(source)))
    assert len(of(run(source, request_for(source, tmp_path)), "shot_converted")) == 2
    index = index_file(tmp_path)
    if problem == "missing":
        index.unlink()
    elif problem == "not a database":
        index.write_bytes(b"not a database, " * 300)
    elif problem == "malformed":
        data = bytearray(index.read_bytes())
        page = int.from_bytes(data[16:18], "big")
        data[page:] = b"\xff" * (len(data) - page)  # (Every page but the schema's.)
        index.write_bytes(bytes(data))
    else:
        with contextlib.closing(sqlite3.connect(index)) as conn:
            conn.execute(f"PRAGMA user_version = {provenance.SCHEMA + 1}")
            conn.commit()
    damaged = index.read_bytes() if index.exists() else b""
    # A load finds no rows (and changes nothing); a conversion converts both shots again.
    assert index_rows(folder) == {} and (index.read_bytes() if index.exists() else b"") == damaged
    events = run(source, request_for(source, tmp_path))
    assert sorted(event["shot"] for event in of(events, "shot_converted")) == [1, 2]
    assert sorted(index_rows(folder)) == [("m19v1", 1), ("m19v1", 2)]
    aside = set_aside(tmp_path)
    if problem == "missing":
        assert aside == []
    else:
        [name] = aside
        assert name.startswith("index-newer-" if problem == "newer" else "index-damaged-")
        assert (index.parent / name).read_bytes() == damaged
    assert of(run(source, request_for(source, tmp_path)), "shot_converted") == []


def test_an_index_that_cant_be_written_fails_the_conversion_to_be_tried_again(
        source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Busy past the timeout (another process's transaction): no TXY without its row; the next one converts."""
    write_raw(source, 1, raw_bytes(10_000))
    run(source, request_for(source, tmp_path, shots=[]))
    with provenance.open_index(str(index_file(tmp_path).parent), write=True):
        pass
    monkeypatch.setattr(provenance, "BUSY_SECONDS", 0.1)
    holder = sqlite3.connect(index_file(tmp_path), isolation_level=None)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(provenance.IndexUnavailable, match="index couldn't be opened .database is locked"):
            run(source, request_for(source, tmp_path))
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    folder = Path(folder_for(str(tmp_path / "temps"), "path:" + str(source)))
    assert not (folder / "d_txy_helab_m19v1_1.txt").exists() and set_aside(tmp_path) == []
    assert len(of(run(source, request_for(source, tmp_path)), "shot_converted")) == 1


def test_an_index_that_cant_be_set_aside_fails_the_conversion_to_be_tried_again(
        source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows renames no file another process holds open (a running ``helab convert``, a load): a damaged
    or newer index then can't be set aside, so the conversion fails before any TXY, leaving it as it was;
    the next one (Live's Retry, ``helab convert``'s next pass) sets it aside and converts."""
    write_raw(source, 1, raw_bytes(10_000))
    index = index_file(tmp_path)
    index.parent.mkdir(parents=True)
    index.write_bytes(b"not a database, " * 300)

    def held_open(path: str, reason: str) -> str:
        raise PermissionError(13, "The process cannot access the file because it is being used by another process")
    monkeypatch.setattr(provenance, "set_aside", held_open)
    with pytest.raises(provenance.IndexUnavailable, match="damaged and couldn't be set aside"):
        run(source, request_for(source, tmp_path))
    folder = Path(folder_for(str(tmp_path / "temps"), "path:" + str(source)))
    assert not (folder / "d_txy_helab_m19v1_1.txt").exists()
    assert index.read_bytes() == b"not a database, " * 300 and set_aside(tmp_path) == []
    monkeypatch.undo()
    assert len(of(run(source, request_for(source, tmp_path)), "shot_converted")) == 1
    assert [name.startswith("index-damaged-") for name in set_aside(tmp_path)] == [True]


WRITER = """
import sys, time
from helab.convert import provenance
root, name, count, start = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
while time.time() < start:
    time.sleep(0.001)
for shot in range(count):
    record = provenance.Provenance(
        shot=shot, raw_name=f"d{shot}.txt", raw_size=1, raw_mtime_ns=1, raw_sha256="", profile_name="p",
        profile_version=1, profile_hash="h", profile_tag="m19v1", profile_calibrated=False, backend="numpy",
        output="temp", txy_name=provenance.txy_name("m19v1", shot), txy_size=shot, txy_mtime_ns=shot,
        txy_sha256="", hits=1, converted_at=time.time(), helab_version="0", read_seconds=0.0, parse_seconds=0.0,
        reconstruct_seconds=0.0, format_seconds=0.0, write_seconds=0.0)
    with provenance.open_index(root, write=True) as index:
        index.record(name, "", "/data/" + name, record, time.time())
"""


def test_two_writers_side_by_side_lose_nothing(tmp_path: Path) -> None:
    """The app's helper and ``helab convert`` (two processes) writing one index at once, each opening it per
    shot as a conversion does: every row lands, and the file stays sound."""
    root = str(tmp_path / "converted-txy")
    start = time.time() + 1.0
    writers = [subprocess.Popen([sys.executable, "-c", WRITER, root, name, "150", str(start)],
                                stderr=subprocess.PIPE, text=True) for name in ("helper", "command line")]
    for writer in writers:
        _, errors = writer.communicate(timeout=120)
        assert writer.returncode == 0, errors
    with provenance.open_index(root, write=False) as index:  # type: ignore[union-attr]
        assert len(index.shots("helper")) == len(index.shots("command line")) == 150
        assert [(row[0], row[3]) for row in index.folders()] == [("command line", sum(range(150))),
                                                                 ("helper", sum(range(150)))]
        assert index.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert sorted(os.listdir(root)) == [provenance.INDEX_NAME]  # (No journal left between transactions.)


def flag_no_cache(private_store: str, source: Path, on: bool = True) -> None:
    events: list[Any] = []
    cache_admin(options(private_store), "prefs", events.append, path=str(source), no_cache=on, no_auto_load=False,
                set_at=time.time())


def test_a_dont_cache_folder_converts_to_the_temp_folder(source: Path, tmp_path: Path, private_store: str) -> None:
    """Q19.5, Q27.4: the store's Don't cache flag, read by the conversion itself (the app and the command
    line alike), sends its TXY to the temp folder, still keyed by its data root."""
    write_raw(source, 1, raw_bytes(10_000))
    flag_no_cache(private_store, source)
    events = run(source, request_for(source, tmp_path, private_store, destination="cache"))
    [plan] = of(events, "convert_plan")
    assert plan["output"] == "temp" and plan["fallback"] == "you chose Don't cache for this folder"
    assert plan["key"].startswith("root://") and plan["folder"] == folder_for(str(tmp_path / "temps"), plan["key"])
    assert Path(plan["folder"], "d_txy_helab_m19v1_1.txt").is_file()
    assert not os.path.exists(os.path.join(private_store, convert.FOLDER_NAME))
    # The flag off: the cache folder again (the temp folder's TXY stays until Settings → Cache clears it).
    flag_no_cache(private_store, source, on=False)
    [plan] = of(run(source, request_for(source, tmp_path, private_store, destination="cache")), "convert_plan")
    assert plan["output"] == "cache" and plan["folder"] == folder_for(private_store, plan["key"])


def test_a_dont_cache_flag_that_cant_be_read_converts_to_the_temp_folder(
        source: Path, tmp_path: Path, private_store: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.utils.cache_store import CacheStore, _error
    write_raw(source, 1, raw_bytes(10_000))
    monkeypatch.setattr(CacheStore, "read_prefs", lambda self, paths: {path: _error("locked") for path in paths})
    [plan] = of(run(source, request_for(source, tmp_path, private_store, destination="cache")), "convert_plan")
    assert plan["output"] == "temp" and plan["fallback"] == "the folder's Don't cache flag couldn't be read (locked)"


@pytest.mark.parametrize("method", ["rename", "copy"])
def test_the_index_moves_with_the_cache_folder_and_its_shots_stay_current(
        source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    """Brief item 7: converted-txy (TXY and index) is inside the cache folder, so a move carries it, and both
    ways keep the TXY's mtimes (a rename, or ``shutil.copy2``): nothing converts again after it."""
    from helab.utils import cache_move
    from helab.utils.cache_store import CacheStore
    app, cache, target = tmp_path / "app", tmp_path / "caches", tmp_path / "moved" / "caches"
    with CacheStore(store_root(str(cache))):
        pass
    for shot in (1, 2):
        write_raw(source, shot, raw_bytes(10_000 * shot))

    def convert_into(folder: Path) -> list[dict[str, Any]]:
        return run(source, request_for(source, tmp_path, destination="cache", cache={"directory": store_root(str(folder))}))
    events = convert_into(cache)
    assert len(of(events, "shot_converted")) == 2 and of(events, "convert_plan")[0]["output"] == "cache"
    monkeypatch.setattr(cache_move, "same_disk", lambda source, target: method == "rename")
    checked = cache_move.check_target(str(cache), str(target))
    assert not checked["problem"] and checked["method"] == method
    record = cache_move.move(cache_move.start(str(cache), str(target), str(app), method), str(app),
                             lambda done, total: None, lambda: False)
    updated = cache_move.cutover(str(app), record, lambda value: True)
    assert updated is not None and cache_move.cleanup(str(app), updated) == []
    assert (target / convert.FOLDER_NAME / provenance.INDEX_NAME).is_file() and not cache.exists()
    moved = convert_into(target)
    assert of(moved, "shot_converted") == [] and len(summary(moved)["current"]) == 2
