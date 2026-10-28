"""Live checks in the helper: one stat while the folder is unchanged, only new settled files read,
held shots reused only from the same folder, new files read once seen unchanged a check apart."""
from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any

import json
import shutil
import uuid

import numpy as np
import pytest

from helab.io_ops import fingerprints, infra
from helab.io_ops.live import live_check
from helab.io_ops.loading import load


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
    events: list[Any] = []
    load(str(folder), str(output), events.append)
    loaded = next(event for event in events if event["kind"] == "loaded")
    return [list(entry) for entry in loaded["fingerprint"]]


def check(folder: Path, tmp_path: Path, memory: list[list[int]], **kwargs: Any) -> list[dict[str, Any]]:
    output = tmp_path / f"live-{time.monotonic_ns()}"
    output.mkdir()
    events: list[Any] = []
    live_check(str(folder), str(output), events.append, memory, **kwargs)
    return events


def last(events: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(event for event in reversed(events) if event["kind"] == kind)


def check_twice(folder: Path, tmp_path: Path, memory: list[list[int]], **kwargs: Any) -> list[dict[str, Any]]:
    """Two checks a cooldown apart: the first sees new files, the second reads those unchanged."""
    first = check(folder, tmp_path, memory, **kwargs)
    seen = first[-1]["live_seen"] if first[-1]["kind"] == "live_unchanged" else []
    return check(folder, tmp_path, memory, **{**kwargs, "since": None, "seen": seen})


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


def test_new_settled_shots_are_read_and_held_ones_trusted(folder: Path, tmp_path: Path) -> None:
    memory = held(folder, tmp_path)
    since = folder.stat().st_mtime_ns
    write_shot(folder, 3)
    age_folder(folder, 30)
    # The first check sees the new file; it is read once it shows the same size and mtime again.
    first = check(folder, tmp_path, memory, since=since)
    assert [event["kind"] for event in first if event["kind"] in ("shot", "loaded")] == []
    seen = last(first, "live_unchanged")
    assert seen["unsettled_files"] == 1 and seen["live_since"] is None
    assert [entry[0] for entry in seen["live_seen"]] == [3]
    assert seen["live_identity"].startswith("root:")  # This folder's data root (tests have one).
    events = check(folder, tmp_path, memory, seen=seen["live_seen"], identity=seen["live_identity"])
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
    assert loaded["live_since"] == folder.stat().st_mtime_ns and loaded["live_seen"] == []


def test_a_listing_samples_held_shots_and_trusts_the_rest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Written once: a listing stats the check level's sample of held shots (first, last and
    max(3, 1%) random for Medium), not each of them."""
    folder = tmp_path / "big"
    folder.mkdir()
    for shot in range(1, 401):
        write_shot(folder, shot)
    age_folder(folder, 60)
    memory = held(folder, tmp_path)
    stats: list[str] = []
    real_stat = os.stat

    def stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        stats.append(os.path.basename(str(path)))
        return real_stat(path, *args, **kwargs)
    monkeypatch.setattr(os, "stat", stat)
    result = last(check(folder, tmp_path, memory), "live_unchanged")
    monkeypatch.undo()
    held_stats = [name for name in stats if name.startswith("d_txy_forc")]
    assert result["live_listed"] and len(held_stats) == 2 + 4
    assert "d_txy_forc1.txt" in held_stats and "d_txy_forc400.txt" in held_stats


def test_another_folder_with_the_same_shot_numbers_is_never_merged(folder: Path, tmp_path: Path) -> None:
    memory = held(folder, tmp_path)
    identity = last(check(folder, tmp_path, memory), "live_unchanged")["live_identity"]
    folder.rename(tmp_path / "old run")
    folder.mkdir()
    for shot in (1, 2, 3):  # Its own shots 1 and 2, written later; and a new shot 3.
        (folder / f"d_txy_forc{shot}.txt").write_text(f"{shot},9,9\n")
    age_folder(folder, 30)
    events = check(folder, tmp_path, memory, identity=identity)
    missing = last(events, "shots_missing")
    assert missing["reason"] == "changed" and missing["missing"] == [1, 2]
    assert not any(event["kind"] in ("shot", "loaded") for event in events)


def test_a_remount_to_another_data_root_is_never_merged(folder: Path, tmp_path: Path) -> None:
    """Same names, sizes and mtimes (a copy elsewhere, mounted at the same path): the data root says."""
    memory = held(folder, tmp_path)
    identity = last(check(folder, tmp_path, memory), "live_unchanged")["live_identity"]
    copy = tmp_path / "copy"
    shutil.copytree(folder, copy, copy_function=shutil.copy2)
    (copy / ".helab-root").write_text(json.dumps({"helab": "root", "version": 1, "uuid": str(uuid.uuid4()),
                                                  "label": "other", "created_at": "2026-10-19T00:00:00Z"}))
    folder.rename(tmp_path / "unmounted")
    copy.rename(folder)
    age_folder(folder, 30)
    events = check(folder, tmp_path, memory, identity=identity)
    missing = last(events, "shots_missing")
    assert missing["reason"] == "root" and missing["missing_count"] == 2
    assert not any(event["kind"] in ("shot", "loaded") for event in events)


def test_a_file_still_growing_with_an_old_stable_mtime_is_not_read_half_written(
    folder: Path, tmp_path: Path,
) -> None:
    """Stale or coarse metadata (e.g. SMB): the mtime looks old, but the size still changes. A
    new file is read only once a check finds the same size and mtime as the one before it."""
    memory = held(folder, tmp_path)
    partial = folder / "d_txy_forc3.txt"
    old = time.time() - 60
    partial.write_text("3,2,3\n")
    os.utime(partial, (old, old))
    age_folder(folder, 30)
    first = last(check(folder, tmp_path, memory), "live_unchanged")
    assert first["unsettled_files"] == 1
    partial.write_text("3,2,3\n3,4,5\n")  # Still being written; the reported mtime doesn't move.
    os.utime(partial, (old, old))
    second = check(folder, tmp_path, memory, seen=first["live_seen"])
    assert not any(event["kind"] == "shot" for event in second)
    assert last(second, "live_unchanged")["unsettled_files"] == 1
    third = check(folder, tmp_path, memory, seen=second[-1]["live_seen"])
    shots = [event for event in third if event["kind"] == "shot"]
    assert [event["shot"] for event in shots] == [3]
    np.testing.assert_array_equal(np.load(shots[0]["artifact"]), [[3, 2, 3], [3, 4, 5]])


def test_a_file_ending_mid_row_is_read_once_unchanged_a_check_apart(folder: Path, tmp_path: Path) -> None:
    """Settle age and "unchanged since the previous check" only (metadata), by Tony's decision: a TXY
    write never takes longer than the settle age, so the file's content isn't checked. A file left
    mid-row longer is read as it is, its partial row dropped as unreadable (problematic)."""
    memory = held(folder, tmp_path)
    partial = folder / "d_txy_forc3.txt"
    old = time.time() - 60
    partial.write_text("3,2,3\n3,4")
    os.utime(partial, (old, old))
    age_folder(folder, 30)
    first = last(check(folder, tmp_path, memory), "live_unchanged")
    assert first["unsettled_files"] == 1  # Seen once: read only if unchanged a check later.
    second = check(folder, tmp_path, memory, seen=first["live_seen"])
    shots = [event for event in second if event["kind"] == "shot"]
    assert [event["shot"] for event in shots] == [3] and shots[0]["problematic"]
    np.testing.assert_array_equal(np.load(shots[0]["artifact"]), [[3, 2, 3]])


def test_a_shot_live_read_recently_that_changes_is_read_again(folder: Path, tmp_path: Path) -> None:
    """By Tony's decision: a held shot Live itself read recently (``recent``) that changes (its writer
    paused longer than the settle age, so Live read it unfinished) is read again as a new file is,
    once settled and unchanged a check apart, and replaces the held one; the check goes on."""
    partial = folder / "d_txy_forc3.txt"
    partial.write_text("3,2,3\n3,4")
    old = time.time() - 60
    os.utime(partial, (old, old))
    memory = held(folder, tmp_path)  # (Shot 3 held as Live read it: unfinished.)
    before = next(entry for entry in memory if entry[0] == 3)
    partial.write_text("3,2,3\n3,4,5\n")  # The writer finishes it.
    os.utime(partial, (old + 10, old + 10))
    age_folder(folder, 30)
    first = check(folder, tmp_path, memory, recent=[3])
    assert not [event for event in first if event["kind"] in ("shots_missing", "shot", "loaded")]
    waiting = last(first, "live_unchanged")
    assert waiting["unsettled_files"] == 1 and waiting["live_since"] is None
    after = [3, partial.stat().st_size, partial.stat().st_mtime_ns]
    assert waiting["live_seen"] == [after]
    events = check(folder, tmp_path, memory, recent=[3], seen=waiting["live_seen"])
    shots = [event for event in events if event["kind"] == "shot"]
    assert [event["shot"] for event in shots] == [3] and not shots[0]["problematic"]
    np.testing.assert_array_equal(np.load(shots[0]["artifact"]), [[3, 2, 3], [3, 4, 5]])
    loaded = last(events, "loaded")
    assert loaded["memory_shots"] == [1, 2] and after in loaded["fingerprint"] and before not in loaded["fingerprint"]
    assert loaded["live_reread"] == [{"shot": 3, "path": str(partial), "old": before[1:], "new": after[1:],
                                      "read": True}]
    assert loaded["load_counts"]["modified"] == loaded["load_counts"]["modified_loaded"] == 1
    assert loaded["load_counts"]["new_loaded"] == 0 and loaded["files"] == 3 and loaded["problematic"] == []
    assert loaded["unsettled_files"] == 0 and "read again" in loaded["cache_reason"]


def test_a_recent_shot_outside_the_sample_that_changes_is_read_again(folder: Path, tmp_path: Path) -> None:
    """Codex review on PR #9: Swift samples only the newest held shot, so a writer resuming shot 2
    after shot 3 arrived was never seen and Live kept the unfinished shot. Every listing stats the
    ``recent`` shots too."""
    write_shot(folder, 3)
    partial = folder / "d_txy_forc2.txt"
    partial.write_text("2,2,3\n2,4")
    old = time.time() - 60
    os.utime(partial, (old, old))
    age_folder(folder)
    memory = held(folder, tmp_path)  # (Shot 2 held as Live read it: unfinished.)
    partial.write_text("2,2,3\n2,4,5\n")  # The writer finishes it.
    os.utime(partial, (old + 10, old + 10))
    age_folder(folder, 30)
    first = check(folder, tmp_path, memory, recent=[2, 3], check_level="swift")
    waiting = last(first, "live_unchanged")
    after = [2, partial.stat().st_size, partial.stat().st_mtime_ns]
    assert waiting["live_seen"] == [after] and waiting["live_since"] is None
    events = check(folder, tmp_path, memory, recent=[2, 3], check_level="swift", seen=waiting["live_seen"])
    assert [event["shot"] for event in events if event["kind"] == "shot"] == [2]
    loaded = last(events, "loaded")
    assert loaded["memory_shots"] == [1, 3] and after in loaded["fingerprint"]
    assert [entry["shot"] for entry in loaded["live_reread"]] == [2]


def test_an_older_held_shot_that_changes_still_stops_the_check(folder: Path, tmp_path: Path) -> None:
    """Not read by Live recently (only shot 1 is ``recent``): a change long after reading suggests a
    remount or a copy, so the check stops as mismatched, as before."""
    memory = held(folder, tmp_path)
    file = folder / "d_txy_forc2.txt"
    file.write_text("2,9,9\n2,9,9\n2,9,9\n")
    old = time.time() - 30
    os.utime(file, (old, old))
    age_folder(folder, 30)
    for recent in (None, [1]):
        events = check(folder, tmp_path, memory, recent=recent)
        stopped = last(events, "shots_missing")
        assert stopped["reason"] == "changed" and stopped["missing"] == [2]
        assert not [event for event in events if event["kind"] in ("shot", "loaded")]


def check_load(folder: Path, tmp_path: Path) -> list[dict[str, Any]]:
    output = tmp_path / f"load-{time.monotonic_ns()}"
    output.mkdir()
    events: list[Any] = []
    load(str(folder), str(output), events.append)
    return events


def test_files_still_being_written_are_counted_and_left_for_later(
    monkeypatch: pytest.MonkeyPatch, folder: Path, tmp_path: Path,
) -> None:
    memory = held(folder, tmp_path)
    monkeypatch.setattr(fingerprints, "SETTLE_SECONDS", 5.0)
    write_shot(folder, 3, age=0)
    age_folder(folder, 30)
    result = last(check(folder, tmp_path, memory), "live_unchanged")
    assert result["unsettled_files"] == 1 and result["live_listed"]
    # Not safe to compare next time: the file settles without changing the folder.
    assert result["live_since"] is None
    write_shot(folder, 3, age=60)  # Settled now.
    events = check_twice(folder, tmp_path, memory)
    assert [event["shot"] for event in events if event["kind"] == "shot"] == [3]


def test_a_recently_modified_folder_is_listed_again(
        monkeypatch: pytest.MonkeyPatch, folder: Path, tmp_path: Path) -> None:
    """Within the margin the quick check uses too (``fingerprints.RACY_SECONDS``, one constant since
    codebase review 2's C-12; tests, with no settle age, have none unless set)."""
    monkeypatch.setattr(fingerprints, "RACY_SECONDS", 2.0)
    memory = held(folder, tmp_path)
    now = time.time()
    os.utime(folder, (now, now))
    result = last(check(folder, tmp_path, memory), "live_unchanged")
    assert result["live_listed"] and result["live_since"] is None  # Within RACY_SECONDS.
    monkeypatch.setattr(fingerprints, "RACY_SECONDS", 0.0)  # (The same margin, set to none: compared.)
    again = last(check(folder, tmp_path, memory), "live_unchanged")
    assert again["live_since"] is not None


def test_unreadable_new_files_are_kept_known_and_not_read_again(
    monkeypatch: pytest.MonkeyPatch, folder: Path, tmp_path: Path,
) -> None:
    memory = held(folder, tmp_path)
    bad = folder / "d_txy_forc3.txt"
    bad.write_text("not,numeric,data\n")
    when = time.time() - 60
    os.utime(bad, (when, when))
    age_folder(folder, 30)
    loaded = last(check_twice(folder, tmp_path, memory), "loaded")
    assert loaded["failed_files"] == 1 and 3 in loaded["problematic"] and loaded["memory_shots"] == [1, 2]
    known = [entry for entry in loaded["fingerprint"] if entry[0] == 3]
    reads: list[str] = []
    real = infra._read_txy_file

    def read_file(filename: str, reason: str) -> Any:
        reads.append(filename)
        return real(filename, reason)
    monkeypatch.setattr(infra, "_read_txy_file", read_file)
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


def test_live_can_start_before_the_first_shot(tmp_path: Path) -> None:
    """No shots held (``memory=[]``): the check lists the folder, and a new file is read once it
    shows the same size and mtime a check later, as any new file during Live."""
    source = tmp_path / "empty"
    source.mkdir()
    age_folder(source)
    nothing = last(check(source, tmp_path, []), "live_unchanged")
    assert nothing["live_listed"] and nothing["total_files"] == 0 and nothing["unsettled_files"] == 0
    assert nothing["live_since"] == source.stat().st_mtime_ns and nothing["live_seen"] == []

    write_shot(source, 1)
    age_folder(source)
    first = check(source, tmp_path, [])
    seen = last(first, "live_unchanged")
    assert seen["live_listed"] and seen["unsettled_files"] == 1 and [entry[0] for entry in seen["live_seen"]] == [1]
    assert not any(event["kind"] == "shot" for event in first)
    second = check(source, tmp_path, [], seen=seen["live_seen"])
    loaded = last(second, "loaded")
    assert [event["shot"] for event in second if event["kind"] == "shot"] == [1]
    assert loaded["memory_shots"] == [] and loaded["source"] == "updated" and loaded["unsettled_files"] == 0
    assert [entry[0] for entry in loaded["fingerprint"]] == [1] and loaded["files"] == 1


def test_a_check_without_held_shots_given_is_refused(folder: Path, tmp_path: Path) -> None:
    """``memory`` None (not sent) is never taken for "no shots yet": the caller's data is unknown."""
    output = tmp_path / "out"
    output.mkdir()
    with pytest.raises(ValueError, match="loaded data"):
        live_check(str(folder), str(output), lambda event: None, None)


def test_live_reads_only_the_folders_own_files_never_its_subfolders(folder: Path, tmp_path: Path) -> None:
    """Live watches the folder itself: TXY files in its subfolders are neither counted nor read."""
    parent = tmp_path
    age_folder(parent)
    first = check(parent, tmp_path, [])
    assert last(first, "live_unchanged")["total_files"] == 0  # ``run`` (shots 1, 2) is a subfolder.
    write_shot(folder, 3)
    write_shot(parent, 7)
    age_folder(parent)
    events = check_twice(parent, tmp_path, [])
    assert [event["shot"] for event in events if event["kind"] == "shot"] == [7]
    loaded = last(events, "loaded")
    assert [entry[0] for entry in loaded["fingerprint"]] == [7] and loaded["total_files"] == 1
