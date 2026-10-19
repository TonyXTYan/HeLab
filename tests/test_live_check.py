"""Live checks in the helper: one stat while the folder is unchanged, only new settled files read."""
from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any

import numpy as np
import pytest

from helab import io_helper
from helab.io_helper import live_check, load


def write_shot(folder: Path, shot: int, *, age: float = 60.0) -> Path:
    file = folder / f"d_txy_forc{shot}.txt"
    file.write_text(f"{shot},2,3\n{shot},4,5\n")
    when = time.time() - age
    os.utime(file, (when, when))
    return file


def age_folder(folder: Path, seconds: float = 60.0) -> None:
    """Folder mtimes this old are safe to compare (not within ``RACY_SECONDS`` of now)."""
    when = time.time() - seconds
    os.utime(folder, (when, when))


def held(folder: Path, tmp_path: Path) -> list[list[int]]:
    """Load the folder as the app would before turning Live on: the shots it holds."""
    output = tmp_path / f"load-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    load(str(folder), str(output), events.append)
    loaded = next(event for event in events if event["kind"] == "loaded")
    return [list(entry) for entry in loaded["fingerprint"]]


def check(folder: Path, tmp_path: Path, memory: list[list[int]], **kwargs: Any) -> list[dict[str, Any]]:
    output = tmp_path / f"live-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    live_check(str(folder), str(output), events.append, memory, **kwargs)
    return events


def last(events: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(event for event in reversed(events) if event["kind"] == kind)


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    source = tmp_path / "run"
    source.mkdir()
    for shot in (1, 2):
        write_shot(source, shot)
    age_folder(source)
    return source


def test_an_unchanged_folder_is_one_stat(monkeypatch: pytest.MonkeyPatch, folder: Path, tmp_path: Path) -> None:
    memory = held(folder, tmp_path)
    first = last(check(folder, tmp_path, memory), "live_unchanged")
    assert first["live_listed"] and first["live_since"] == folder.stat().st_mtime_ns
    assert first["total_files"] == 2 and first["unsettled_files"] == 0

    def no_listing(path: Any = ".") -> Any:
        raise AssertionError("listed the folder")
    monkeypatch.setattr(os, "scandir", no_listing)
    again = last(check(folder, tmp_path, memory, since=first["live_since"]), "live_unchanged")
    assert not again["live_listed"] and again["live_since"] == first["live_since"]


def test_new_settled_shots_are_read_and_held_ones_trusted(
    monkeypatch: pytest.MonkeyPatch, folder: Path, tmp_path: Path,
) -> None:
    memory = held(folder, tmp_path)
    since = folder.stat().st_mtime_ns
    write_shot(folder, 3)
    age_folder(folder, 30)
    stats: list[str] = []
    real_stat = os.stat

    def stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        stats.append(os.path.basename(str(path)))
        return real_stat(path, *args, **kwargs)
    monkeypatch.setattr(os, "stat", stat)
    events = check(folder, tmp_path, memory, since=since)
    monkeypatch.undo()
    assert "d_txy_forc1.txt" not in stats and "d_txy_forc2.txt" not in stats  # Written once: trusted.
    shots = [event for event in events if event["kind"] == "shot"]
    assert [event["shot"] for event in shots] == [3]
    np.testing.assert_array_equal(np.load(shots[0]["artifact"]), [[3, 2, 3], [3, 4, 5]])
    loaded = last(events, "loaded")
    assert loaded["memory_shots"] == [1, 2] and loaded["source"] == "updated"
    assert loaded["load_counts"]["new_loaded"] == 1 and loaded["load_counts"]["reused_memory"] == 2
    assert [entry[0] for entry in loaded["fingerprint"]] == [1, 2, 3]
    assert loaded["files"] == loaded["total_files"] == 3
    assert not loaded["disk_cache_pending"] and "disk_cached" not in loaded
    # The same signature an ordinary load gives the folder now, and its summary agrees.
    assert loaded["signature"] == last(check_load(folder, tmp_path), "loaded")["signature"]
    assert last(events, "scan_summary")["status"]["signature"] == loaded["signature"]
    assert loaded["live_since"] == folder.stat().st_mtime_ns


def check_load(folder: Path, tmp_path: Path) -> list[dict[str, Any]]:
    output = tmp_path / f"load-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    load(str(folder), str(output), events.append)
    return events


def test_files_still_being_written_are_counted_and_left_for_later(
    monkeypatch: pytest.MonkeyPatch, folder: Path, tmp_path: Path,
) -> None:
    memory = held(folder, tmp_path)
    monkeypatch.setattr(io_helper, "SETTLE_SECONDS", 5.0)
    write_shot(folder, 3, age=0)
    age_folder(folder, 30)
    result = last(check(folder, tmp_path, memory), "live_unchanged")
    assert result["unsettled_files"] == 1 and result["live_listed"]
    # Not safe to compare next time: the file settles without changing the folder.
    assert result["live_since"] is None
    write_shot(folder, 3, age=60)  # Settled now.
    events = check(folder, tmp_path, memory)
    assert [event["shot"] for event in events if event["kind"] == "shot"] == [3]


def test_a_recently_modified_folder_is_listed_again(folder: Path, tmp_path: Path) -> None:
    memory = held(folder, tmp_path)
    now = time.time()
    os.utime(folder, (now, now))
    result = last(check(folder, tmp_path, memory), "live_unchanged")
    assert result["live_listed"] and result["live_since"] is None  # Within RACY_SECONDS.


def test_unreadable_new_files_are_kept_known_and_not_read_again(
    monkeypatch: pytest.MonkeyPatch, folder: Path, tmp_path: Path,
) -> None:
    memory = held(folder, tmp_path)
    bad = folder / "d_txy_forc3.txt"
    bad.write_text("not,numeric,data\n")
    when = time.time() - 60
    os.utime(bad, (when, when))
    age_folder(folder, 30)
    loaded = last(check(folder, tmp_path, memory), "loaded")
    assert loaded["failed_files"] == 1 and 3 in loaded["problematic"] and loaded["memory_shots"] == [1, 2]
    known = [entry for entry in loaded["fingerprint"] if entry[0] == 3]
    import pandas as pd
    reads: list[str] = []
    real = pd.read_csv

    def read_csv(*args: Any, **kwargs: Any) -> Any:
        reads.append(str(args[0]))
        return real(*args, **kwargs)
    monkeypatch.setattr(pd, "read_csv", read_csv)
    again = check(folder, tmp_path, memory, known=known)
    assert last(again, "live_unchanged")["total_files"] == 3 and not reads


def test_held_shots_gone_from_the_folder_stop_the_check(folder: Path, tmp_path: Path) -> None:
    memory = held(folder, tmp_path)
    (folder / "d_txy_forc2.txt").unlink()
    events = check(folder, tmp_path, memory)
    missing = last(events, "shots_missing")
    assert missing["missing"] == [2] and not any(event["kind"] == "loaded" for event in events)


def test_a_missing_folder_says_so(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="Folder not found"):
        check(tmp_path / "gone", tmp_path, [[1, 2, 3]])
