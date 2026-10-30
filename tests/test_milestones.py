"""Milestone log lines (``app_log.milestone``): one INFO line in a fixed form when a folder's load,
a plot's compute or a conversion ends, for a runner to wait on in HeLab's log file. Each site is
driven as in its own tests (helpers in-process), and its line read back with ``parse_milestone``."""
from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from helab.analysis.dataset_view import build_view
from helab.utils import app_log
from helab.utils.app_log import MILESTONE_LOGGER, MilestoneValue, milestone, parse_milestone
from helab.utils.io_service import IOService
from helab.views.FolderExplorer import FolderExplorer
from test_analysis import Blocking, Harness, dataset, harness  # noqa: F401
from test_cache_first import browser, show_cached  # noqa: F401
from test_convert_helab import raw_bytes
from test_live import (  # noqa: F401
    age_folder, checks, next_request, open_loaded, replay, run, service, write_shot,
)
from test_live_convert import cycle, of, one_worker, watching_raw_folder, write_raw  # noqa: F401


def logged(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, MilestoneValue]]:
    """The fields of each ``event`` milestone logged so far, in order."""
    found = []
    for record in caplog.records:
        if record.name == MILESTONE_LOGGER:
            parsed = parse_milestone(record.getMessage())
            assert parsed is not None, record.getMessage()
            if parsed[0] == event:
                found.append(parsed[1])
    return found


@pytest.fixture
def milestones(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO, logger=MILESTONE_LOGGER)
    return caplog


# The form

def test_a_milestone_is_one_line_its_fields_in_order_and_typed_back() -> None:
    message = milestone("load_done", folder="/data/2026 run \"A\"=1", shots=3, events=12, seconds=1.23456,
                        source="cache", live=False, note=None, odd=math.nan, unicode="Résumé")
    assert message == ('MILESTONE load_done folder="/data/2026 run \\"A\\"=1" shots=3 events=12 seconds=1.235 '
                       'source=cache live=false note=null odd=null unicode="Résumé"')
    parsed = parse_milestone(message)
    assert parsed is not None
    event, fields = parsed
    assert event == "load_done"
    assert list(fields) == ["folder", "shots", "events", "seconds", "source", "live", "note", "odd", "unicode"]
    assert fields == {"folder": '/data/2026 run "A"=1', "shots": 3, "events": 12, "seconds": 1.235,
                      "source": "cache", "live": False, "note": None, "odd": None, "unicode": "Résumé"}


@pytest.mark.parametrize("text", ["true", "null", "12", "-3", "1.500", "", "a b", "x=y", "C:\\data", "tab\there"])
def test_a_string_that_would_read_as_something_else_is_quoted(text: str) -> None:
    message = milestone("plot_done", script=text)
    assert '"' in message
    assert parse_milestone(message) == ("plot_done", {"script": text})


@pytest.mark.parametrize("text", ["tests.blocking", "/plain/path_1", "ok", "a:b+c-d"])
def test_a_plain_string_is_bare(text: str) -> None:
    assert milestone("plot_done", script=text) == f"MILESTONE plot_done script={text}"


def test_a_line_without_a_milestone_has_none() -> None:
    assert parse_milestone("2026-10-30 10:00:00,000 INFO [1 MainThread] root: Logging to /x") is None
    assert parse_milestone("MILESTONES load_done") is None
    assert parse_milestone("MILESTONE") is None
    # Another logger's line that holds the word (a folder named so) isn't one, nor is a line with junk.
    assert parse_milestone("2026-10-30 10:00:00,000 INFO [1 MainThread] root: Live on /data/MILESTONE load_done") is None
    assert parse_milestone("... INFO [1 MainThread] root: MILESTONE load_done folder=a") is None
    assert parse_milestone("MILESTONE load_done folder=a junk tail") is None
    assert parse_milestone('MILESTONE load_done folder="a') is None
    assert parse_milestone("... INFO [1 MainThread] helab.milestone: MILESTONE load_done folder=a") == (
        "load_done", {"folder": "a"})


@pytest.mark.parametrize("separator", ["\n", "\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028",
                                       "\u2029"])
def test_a_value_never_splits_the_line(separator: str) -> None:
    """Every character ``str.splitlines`` breaks at is escaped in a value (a folder named with one)."""
    text = f"/data/a{separator}b"
    message = milestone("load_done", folder=text, shots=1)
    assert message.splitlines() == [message]
    assert parse_milestone(message) == ("load_done", {"folder": text, "shots": 1})


def test_the_log_file_line_reads_back(tmp_path: Path) -> None:
    """In HeLab's log file (``start_log_file``), the INFO line on ``helab.milestone`` parses as written."""
    root = logging.getLogger()
    level = root.level
    root.setLevel(logging.INFO)
    handler = app_log.start_log_file(str(tmp_path))
    assert handler is not None
    try:
        milestone("convert_done", folder=str(tmp_path / "a run"), by="live", converted=2, seconds=0.5)
    finally:
        root.removeHandler(handler)
        handler.close()
        root.setLevel(level)
    path = os.path.join(app_log.log_folder(str(tmp_path)), app_log.LOG_NAME.format(pid=os.getpid()))
    lines = [line for line in Path(path).read_text(encoding="utf-8").splitlines() if "MILESTONE" in line]
    assert len(lines) == 1 and f" INFO [{os.getpid()} " in lines[0] and f" {MILESTONE_LOGGER}: MILESTONE " in lines[0]
    assert parse_milestone(lines[0]) == ("convert_done", {"folder": str(tmp_path / "a run"), "by": "live",
                                                          "converted": 2, "seconds": 0.5})


# plot_done

def test_a_plots_compute_says_its_script_plot_time_and_state(
        qtbot: QtBot, harness: Harness, milestones: pytest.LogCaptureFixture) -> None:
    view = build_view(dataset())
    script = Blocking()
    script.release.set()
    done = harness.finished(qtbot, harness.runner.submit(script, script.get_metadata(), "Plot", view,
                                                         owner="plot-7").job_id)
    script.fail = True
    failed = harness.finished(qtbot, harness.runner.submit(script, script.get_metadata(), "Plot", view,
                                                           owner="plot-8").job_id)
    lines = logged(milestones, "plot_done")
    assert [line["job"] for line in lines] == [done.job_id, failed.job_id]
    assert lines[0] == {"script": done.analysis.analysis_id, "version": done.analysis.version, "action": "Plot",
                        "plot": "plot-7", "job": done.job_id,
                        "seconds": round(done.finished_at - done.started_at, 3), "state": "ok"}
    assert lines[1]["plot"] == "plot-8" and lines[1]["state"] == "failed"


# load_done

def test_a_folder_loaded_from_its_files_says_shots_events_and_source(
        qtbot: QtBot, service: IOService, run: Path, tmp_path: Path, milestones: pytest.LogCaptureFixture) -> None:
    explorer = open_loaded(qtbot, service, run, tmp_path)
    lines = logged(milestones, "load_done")
    assert len(lines) == 1
    line = lines[0]
    seconds = line.pop("seconds")
    assert isinstance(seconds, float) and 0 <= seconds < 60
    assert line == {"folder": str(run), "shots": 2, "events": 4, "source": "folder", "live": False}
    explorer.close_cleanup()


def test_a_live_shot_and_lives_save_say_so(
        qtbot: QtBot, service: IOService, run: Path, tmp_path: Path, milestones: pytest.LogCaptureFixture) -> None:
    """A Live check that reads a new shot is ``live=true``; Live's save (at Live off) is ``source=save``,
    never taken for a check of the folder."""
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    assert explorer.start_live()
    next_request(qtbot, explorer, path)
    replay(cache, path, tmp_path)  # (Nothing new: no line.)
    write_shot(run, 3)
    age_folder(run, 60)
    checks(qtbot, explorer, path, tmp_path)
    explorer.stop_live()
    save = next_request(qtbot, explorer, path)
    assert save.payload.get("save_memory")
    replay(cache, path, tmp_path)
    qtbot.waitUntil(lambda: not explorer.live_control._live_sessions)
    lines = logged(milestones, "load_done")
    assert [(line["folder"], line["shots"], line["source"], line["live"]) for line in lines] == [
        (path, 2, "folder", False), (path, 3, "folder", True), (path, 3, "save", True)]
    explorer.close_cleanup()


def test_cached_data_then_its_check_each_say_so(
        browser: FolderExplorer, qtbot: QtBot, tmp_path: Path, milestones: pytest.LogCaptureFixture) -> None:
    path = str(tmp_path)
    signature, check = show_cached(browser, qtbot, path)
    service = browser.model.cache.service
    service.resultReady.emit(check, {
        "kind": "loaded", "unchanged": True, "signature": signature, "memory_shots": [1],
        "base_signature": signature, "fingerprint": [[1, 6, 123]], "files": 1, "total_files": 1,
        "failed_files": 0, "rows": 0, "bytes": 0, "problematic": [], "source": "memory", "cached": True,
        "disk_cached": True, "disk_cache_pending": False, "cache_info": browser.model.cache.cache_status(path).info,
        "load_counts": {"reused_memory": 1, "read": 0}})
    service.pending.remove(check)
    lines = logged(milestones, "load_done")
    assert [(line["folder"], line["shots"], line["events"], line["source"]) for line in lines] == [
        (path, 1, 1, "cache"), (path, 1, 1, "check")]


# convert_done

def test_each_live_conversion_says_what_that_run_did(
        qtbot: QtBot, service: IOService, tmp_path: Path, milestones: pytest.LogCaptureFixture) -> None:
    """Every count is the run's: converted and no-hit shots this run (no_hit: the growth of the
    session's no-hit shots since the last line), and the folder's unconvertible, waiting and kept
    files as that run left them. A run that changed nothing (Live converts every interval) logs none."""
    explorer, path = watching_raw_folder(qtbot, tmp_path)
    cycle(qtbot, explorer, path, tmp_path)
    write_raw(Path(path), 3, b"5,1000\r\n")  # The trigger alone: no hits.
    write_raw(Path(path), 4, raw_bytes(10_000, 20_000))
    cycle(qtbot, explorer, path, tmp_path)
    _, sent = cycle(qtbot, explorer, path, tmp_path)
    assert {event["shot"]: event["hits"] for event in of(sent, "shot_converted")} == {3: 0, 4: 2}
    cycle(qtbot, explorer, path, tmp_path)
    lines: list[dict[str, Any]] = logged(milestones, "convert_done")
    assert all(line["folder"] == path and line["by"] == "live" and isinstance(line["seconds"], float)
               and line["output"] == of(sent, "convert_summary")[0]["output"] for line in lines)
    counts = [(line["converted"], line["no_hit"], line["unconvertible"], line["waiting"], line["kept"])
              for line in lines]
    assert counts[0] == (0, 0, 0, 0, 0)  # The first run, though it found nothing.
    assert counts[-1] == (2, 1, 0, 0, 0)  # The run after it changed nothing: no line.
    assert all(before != after for before, after in zip(counts, counts[1:]))
    assert sum(line["converted"] for line in lines) == 2 and sum(line["no_hit"] for line in lines) == 1
    explorer.close_cleanup()
