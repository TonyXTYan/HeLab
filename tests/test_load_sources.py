"""What a ``merged`` and an ``updated`` load do, which their labels must say (status-message audit,
.ai/sessions/2026-10-26-claude-quick-fixes-2/notes.md, job 4): which TXY files each reads (new and
modified ones, or none), where the rest come from, and that the disk cache is written only after
``loaded``; and the origin each one shows (``load_origin``, Tony 2026-10-26)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from helab.views.FolderExplorer import load_origin
from test_cache_switch import data_folder, options_for, run_load


def kinds(events: list[Any]) -> list[str]:
    return [event["kind"] for event in events]


def loaded(events: list[Any]) -> dict[str, Any]:
    return next(event for event in events if event["kind"] == "loaded")


def announced(events: list[Any]) -> list[str]:
    """Files announced (``file_started``) before ``loaded``: only those read, never reused ones."""
    return [Path(event["filename"]).name for event in events[:kinds(events).index("loaded")]
            if event["kind"] == "file_started"]


def test_a_merged_load_reads_new_and_modified_files_then_saves_after_loaded(tmp_path: Path) -> None:
    source = data_folder(tmp_path, shots=3)
    options = options_for(tmp_path)
    assert loaded(run_load(source, tmp_path, options))["source"] == "files"
    (source / "d_txy_forc2.txt").write_text("2,2,3\n2,5,6\n2,8,9\n")  # Modified.
    (source / "d4.txt").write_text("raw\n")
    (source / "d_txy_forc4.txt").write_text("4,2,3\n")  # New.
    events = run_load(source, tmp_path, options)
    result = loaded(events)
    assert result["source"] == "merged"
    counts = result["load_counts"]
    assert (counts["reused_disk"], counts["read"], counts["new_loaded"], counts["modified_loaded"]) == (2, 2, 1, 1)
    assert announced(events) == ["d_txy_forc2.txt", "d_txy_forc4.txt"]
    assert load_origin("merged", counts) == "disk cache + 2 TXY files read"
    assert result["cache_reason"] == "Reused 2 shots from disk cache; 2 new or changed TXY files to read"
    # The disk cache is written after the data is delivered.
    order = kinds(events)
    assert order.index("load_source") < order.index("loaded") < order.index("cache_saved") < order.index("disk_cached")
    assert result["disk_cache_pending"]


def test_a_merged_load_may_read_nothing(tmp_path: Path) -> None:
    """Load as it is now after a shot went (``allow_missing``): every shot left is the cache's."""
    source = data_folder(tmp_path, shots=3)
    options = options_for(tmp_path)
    run_load(source, tmp_path, options)
    (source / "d_txy_forc3.txt").unlink()
    result = loaded(run_load(source, tmp_path, options, allow_missing=True))
    assert result["source"] == "merged"
    assert (result["load_counts"]["read"], result["load_counts"]["removed"]) == (0, 1)
    assert load_origin("merged", result["load_counts"]) == "disk cache"
    assert result["cache_reason"] == "Reused 2 shots from disk cache"


def test_an_updated_load_reuses_memory_and_the_cache(tmp_path: Path) -> None:
    source = data_folder(tmp_path, shots=3)
    options = options_for(tmp_path)
    fingerprint = loaded(run_load(source, tmp_path, options))["fingerprint"]
    (source / "d4.txt").write_text("raw\n")
    (source / "d_txy_forc4.txt").write_text("4,2,3\n")
    events = run_load(source, tmp_path, options, memory=[fingerprint[0]])  # The tab holds shot 1.
    result = loaded(events)
    assert result["source"] == "updated" and result["memory_shots"] == [1]
    counts = result["load_counts"]
    # Shots from memory and from the disk cache, one new file read.
    assert (counts["reused_memory"], counts["reused_disk"], counts["read"], counts["new_loaded"]) == (1, 2, 1, 1)
    assert load_origin("updated", counts) == "memory + disk cache + 1 TXY file read"
    assert announced(events) == ["d_txy_forc4.txt"]
    order = kinds(events)
    assert order.index("loaded") < order.index("cache_saved") < order.index("disk_cached")


def test_an_updated_load_rereads_the_shots_only_memory_held_after_loaded(tmp_path: Path) -> None:
    """Data held in RAM without a disk cache: the save after ``loaded`` reads those shots again."""
    source = data_folder(tmp_path, shots=2)
    fingerprint = loaded(run_load(source, tmp_path, None))["fingerprint"]
    (source / "d3.txt").write_text("raw\n")
    (source / "d_txy_forc3.txt").write_text("3,2,3\n")
    events = run_load(source, tmp_path, options_for(tmp_path), memory=fingerprint)
    result = loaded(events)
    assert result["source"] == "updated" and result["disk_cache_pending"]
    assert announced(events) == ["d_txy_forc3.txt"]
    assert result["load_counts"]["read"] == 1 and load_origin("updated", result["load_counts"]) == "memory + 1 TXY file read"
    after = events[kinds(events).index("loaded") + 1:]
    assert [Path(event["filename"]).name for event in after if event["kind"] == "file_started"] == [
        "d_txy_forc1.txt", "d_txy_forc2.txt"]
    assert kinds(after).index("cache_saved") < kinds(after).index("disk_cached")


def test_an_updated_load_may_read_nothing(tmp_path: Path) -> None:
    """A full check of data the tab holds, with nothing changed: still ``updated``."""
    source = data_folder(tmp_path, shots=2)
    options = options_for(tmp_path)
    fingerprint = loaded(run_load(source, tmp_path, options))["fingerprint"]
    result = loaded(run_load(source, tmp_path, options, memory=fingerprint))
    assert result["source"] == "updated" and result["cached"]
    assert (result["load_counts"]["read"], result["load_counts"]["new"], result["load_counts"]["modified"]) == (0, 0, 0)
    assert load_origin("updated", result["load_counts"]) == "memory"
    assert result["cache_reason"] == "Reused 2 shots from memory"
    assert not result["disk_cache_pending"]
