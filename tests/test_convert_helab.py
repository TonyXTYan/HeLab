"""HeLab's own conversions (TXY converter stage 4): the settle checks, provenance, outputs and the
``convert`` helper operation (``helab/io_ops/convert.py``), the converter flags in the store, and
``helab convert --watch``. Synthetic raw files under ``tmp_path`` only (tests never touch real data)."""
from __future__ import annotations

import builtins
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any, Iterator

import pytest

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


@pytest.fixture
def source(tmp_path: Path) -> Path:
    folder = tmp_path / "source"
    folder.mkdir()
    return folder


def options(private_store: str) -> dict[str, Any]:
    return {"directory": store_root(private_store)}


def request_for(path: Path, tmp_path: Path, private_store: str | None = None, **fields: Any) -> ConvertRequest:
    request: ConvertRequest = {"path": str(path), "profile": MATLAB_2019.to_dict(), "temps": str(tmp_path / "temps"),
                               "output": "temp", "workers": 1}
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
        shot=3, source_folder="/data/run", source_key="root://u/run", raw_name="d3.txt", raw_size=100,
        raw_mtime_ns=5, raw_sha256="ab", profile_name="matlab-2019", profile_version=1,
        profile_hash=MATLAB_2019.content_hash(), profile_calibrated=False, backend="numpy", output="cache",
        txy_name="d_txy_helab_3.txy", txy_size=40, txy_sha256="cd", hits=2, converted_at=1.5, helab_version="0",
        read_seconds=0.1, parse_seconds=0.0, reconstruct_seconds=0, format_seconds=0.0, write_seconds=0.0)
    values.update(changes)
    return provenance.Provenance(**values)


def test_provenance_round_trips_and_says_what_is_stale() -> None:
    record = provenance_record()
    assert provenance.Provenance.from_json(record.to_json()) == record
    def stale(record: provenance.Provenance | None, raw_mtime_ns: int = 5, txy_size: int | None = 40,
              profile_hash: str = MATLAB_2019.content_hash()) -> str:
        return provenance.stale(record, raw_size=100, raw_mtime_ns=raw_mtime_ns, profile_hash=profile_hash,
                                txy_size=txy_size) or ""
    assert stale(record) == ""
    assert stale(record, txy_size=None) == "no TXY"
    assert stale(None) == "no provenance record"
    assert "raw file changed" in stale(record, raw_mtime_ns=6)
    assert "TXY changed" in stale(record, txy_size=41)
    assert "another profile" in stale(record, profile_hash=MATLAB_2023_LAB_EDIT.content_hash())
    # Another backend or profile name with the same hash converts alike: still current.
    assert stale(provenance_record(backend="rust", profile_name="copy")) == ""
    for broken in ("{", "[]", json.dumps({"helab": "x"}), record.to_json().replace('"hits": 2', '"hits": true'),
                   record.to_json().replace('"version": 1', '"version": 2')):
        with pytest.raises(provenance.ProvenanceError):
            provenance.Provenance.from_json(broken)


def test_write_atomic_without_replace_never_touches_an_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "d_txy_helab_1.txy"
    txy.write_atomic(target, b"new\n", replace=False)
    assert target.read_bytes() == b"new\n"
    with pytest.raises(FileExistsError):
        txy.write_atomic(target, b"other\n", replace=False)
    assert target.read_bytes() == b"new\n"
    folder = tmp_path / "out"
    folder.mkdir()
    target = folder / "d_txy_helab_1.txy"
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
    # No rows: unconvertible, no TXY, never silently skipped (Q10.2).
    [refused] = of(events, "shot_unconvertible")
    assert (refused["shot"], refused["reason"]) == (4, raw.NO_ROWS)
    assert not (Path(folder) / "d_txy_helab_4.txy").exists()
    record = provenance.Provenance.from_json((Path(folder) / "d_txy_helab_2.json").read_text())
    assert (record.raw_name, record.raw_size, record.raw_mtime_ns) == ("d2.txt", len(datas[2]), OLD * 10**9)
    assert (record.profile_name, record.profile_hash, record.backend, record.hits) == (
        "matlab-2019", MATLAB_2019.content_hash(), "numpy", 2)
    assert record.txy_size == len(Path(converted[2]["txy"]).read_bytes())
    assert json.loads((Path(folder) / "folder.json").read_text())["source"] == str(source)
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
    write_raw(source, 2, whole[:-5])  # Ends mid-line (settled by age, but half-written).
    write_raw(source, 3, raw_bytes(10_000, trigger=0))  # Doesn't start on the trigger.
    write_raw(source, 4, whole, mtime=time.time() + 120)  # Dated ahead of this clock.
    write_raw(source, 5, whole)
    events = run(source, request_for(source, tmp_path))
    waiting = {event["shot"]: event["reason"] for event in of(events, "shot_waiting")}
    assert waiting == {1: raw.SETTLING, 2: raw.NO_FINAL_NEWLINE, 3: raw.NOT_TRIGGER_FIRST, 4: raw.SETTLING}
    assert [event["shot"] for event in of(events, "shot_converted")] == [5]
    folder = Path(of(events, "convert_plan")[0]["folder"])
    assert sorted(path.name for path in folder.glob("*.txy")) == ["d_txy_helab_5.txy"]
    # The writer finishes shot 2 and it settles: then it converts.
    write_raw(source, 2, whole)
    later = run(source, request_for(source, tmp_path))
    assert [event["shot"] for event in of(later, "shot_converted")] == [2]


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


def test_a_better_profile_converts_again_and_says_why(source: Path, tmp_path: Path) -> None:
    write_raw(source, 1, raw_bytes(10_000, 20_000))
    run(source, request_for(source, tmp_path))
    events = run(source, request_for(source, tmp_path, profile=MATLAB_2023_LAB_EDIT.to_dict()))
    [again] = of(events, "shot_converted")
    assert "another profile" in again["replaced"] and again["profile"]["name"] == "matlab-2023-lab-edit"
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
    events = run(source, request_for(source, tmp_path, private_store, output="cache"))
    [plan] = of(events, "convert_plan")
    assert plan["output"] == "cache" and plan["fallback"] == ""
    assert plan["key"].startswith("root://") and plan["key"].endswith("/source")
    assert plan["folder"] == folder_for(private_store, plan["key"])
    assert Path(plan["folder"], "d_txy_helab_1.txy").is_file()


@pytest.mark.no_auto_data_root
def test_a_folder_without_a_data_root_goes_to_the_temp_folder(source: Path, tmp_path: Path,
                                                              private_store: str) -> None:
    write_raw(source, 1, raw_bytes(10_000))
    events = run(source, request_for(source, tmp_path, private_store, output="cache"))
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
        monkeypatch.setattr(os, "open", os_opened)
        for name in ("replace", "rename", "link", "unlink", "remove", "mkdir", "makedirs", "rmdir", "utime"):
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
    events = run(source, request_for(source, tmp_path, private_store, output="cache", beside=True))
    [plan] = of(events, "convert_plan")
    assert plan["output"] == "cache" and plan["fallback"] == "writing beside the raw files is off for this folder"
    assert sorted(path.name for path in source.iterdir()) == ["d1.txt"]


def test_beside_writes_only_its_txy_into_the_source_folder(source: Path, tmp_path: Path, private_store: str) -> None:
    """AGENTS.md's write rule: in a source folder HeLab writes only ``d_txy_helab_<N>.txy`` (a
    temporary name, then renamed) and never touches raw files or an existing TXY."""
    for shot in (1, 2, 3):
        write_raw(source, shot, raw_bytes(10_000 * shot))
    (source / "d_txy_forc1.txt").write_bytes(b"MATLAB's\n")
    (source / "d_txy_helab_3.txy").write_bytes(b"someone else's\n")
    before = {path.name: path.read_bytes() for path in source.iterdir()}
    flag_beside(private_store, source)
    with Writes() as writes:
        events = run(source, request_for(source, tmp_path, private_store, output="cache", beside=True))
    [plan] = of(events, "convert_plan")
    assert plan["output"] == "beside" and plan["txy_folder"] == str(source) and plan["folder"] != str(source)
    assert sorted(event["shot"] for event in of(events, "shot_converted")) == [1, 2]
    # The one already there stays as it was.
    [kept] = of(events, "shot_kept")
    assert kept["shot"] == 3 and "never replaced" in kept["reason"]
    after = {path.name: path.read_bytes() for path in source.iterdir()}
    assert {name: data for name, data in after.items() if name in before} == before
    assert sorted(set(after) - set(before)) == ["d_txy_helab_1.txy", "d_txy_helab_2.txy"]
    touched = {Path(path).name for path in writes.inside(source)}
    assert touched, "the audit saw the writes"
    for name in touched:
        assert name in ("d_txy_helab_1.txy", "d_txy_helab_2.txy") or (
            name.startswith((".d_txy_helab_1.txy.", ".d_txy_helab_2.txy.")) and name.endswith(".partial")), name
    # Provenance is in HeLab's own folder.
    assert Path(plan["folder"], "d_txy_helab_1.json").is_file()
    # The second time: current, nothing written there at all.
    with Writes() as writes:
        again = run(source, request_for(source, tmp_path, private_store, output="cache", beside=True))
    assert of(again, "shot_converted") == [] and writes.inside(source) == []


def test_the_command_lines_beside_needs_no_flag(source: Path, tmp_path: Path) -> None:
    write_raw(source, 1, raw_bytes(10_000))
    events = run(source, request_for(source, tmp_path, beside=True, beside_confirmed=True))
    assert of(events, "convert_plan")[0]["output"] == "beside"
    assert (source / "d_txy_helab_1.txy").is_file()


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
    request = {"operation": "convert", **request_for(source, tmp_path, private_store, output="cache")}
    events = helper(request)
    assert [event["kind"] for event in events][-2:] == ["convert_summary", "done"]
    assert len(of(events, "shot_converted")) == 1
    offline = helper({**request, "cache": {**options(private_store), "offline": True}})
    assert offline[-1]["kind"] == "error" and "offline" in offline[-1]["message"].lower()
    from helab.utils.io_service import IOService
    assert "convert" not in IOService.OFFLINE_OPERATIONS and "convert" in IOService.PAUSABLE
    assert "convert" not in IOService.LOCAL_OPERATIONS and "convert" in IOService.LABELS


def test_the_helper_refuses_a_source_path_that_could_be_real_data(tmp_path: Path) -> None:
    events = helper({"operation": "convert", **request_for(Path("/Volumes/dld_output/run"), tmp_path)})
    assert events[-1]["kind"] == "error"
    notes = Path(os.environ["HELAB_TEST_SOURCE_GUARD"])
    assert any("/Volumes/dld_output/run" in note.read_text() for note in notes.glob("*.txt"))
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
    assert sorted(path.name for path in folder.iterdir()) == names
    assert not any(name.endswith(".partial") for name in names)


def test_the_numba_backends_cache_folder_is_under_the_cache(source: Path, tmp_path: Path, private_store: str,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.convert.backends import numba_backend
    folders: list[str] = []
    monkeypatch.setattr(numba_backend, "set_cache_folder", lambda folder: folders.append(str(folder)))
    write_raw(source, 1, raw_bytes(10_000))
    try:
        run(source, request_for(source, tmp_path, private_store, backend="numba"))
    except RuntimeError:
        pass  # (numba not installed here: the backend can't run, after the folder was set.)
    assert folders == [os.path.join(private_store, "numba")]


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
    assert file_kinds.match("d_txy_helab_12.txy") == (file_kinds.HELAB_TXY, 12)
    kind = file_kinds.HELAB_TXY
    assert not kind.loaded and not kind.counted_empty
    assert file_kinds.match("d_txy_helab_12.txt") is None and file_kinds.match(".d_txy_helab_1.txy.ab.partial") is None
    assert kind.pattern.pattern == provenance.TXY_PATTERN.pattern
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
    assert (source / "d_txy_helab_1.txy").read_bytes() == convert_raw(data, MATLAB_2019, "reference")
    assert "d1.txt → d_txy_helab_1.txy: 2 hits" in done.stderr
    assert "d2.txt can't be converted" in done.stderr
    assert cli("--watch", str(tmp_path / "missing"), "--once").returncode == 2
    assert cli("--watch", str(source), "--once", "--profile", "no-such-profile").returncode == 2


@pytest.fixture
def watching(source: Path) -> Iterator[subprocess.Popen[str]]:
    process = subprocess.Popen([sys.executable, "-m", "helab", "convert", "--watch", str(source), "--output",
                                "beside", "--interval", "0.2"], stderr=subprocess.PIPE, text=True, cwd=ROOT,
                               env=dict(os.environ))
    yield process
    if process.poll() is None:
        process.kill()
        process.wait(10)


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT to a child process is a console event on Windows")
def test_watch_converts_new_shots_and_stops_on_ctrl_c(source: Path, watching: subprocess.Popen[str]) -> None:
    data = raw_bytes(10_000)
    write_raw(source, 7, data)
    deadline = time.monotonic() + 30
    while not (source / "d_txy_helab_7.txy").exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert (source / "d_txy_helab_7.txy").read_bytes() == convert_raw(data, MATLAB_2019, "reference")
    watching.send_signal(signal.SIGINT)
    assert watching.wait(20) == 0
    assert watching.stderr is not None and "Stopped" in watching.stderr.read()
