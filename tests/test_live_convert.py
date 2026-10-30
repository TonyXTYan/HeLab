"""Live auto-convert (TXY converter stage 4, Q6.8): a Live tab converts new raw shots once they are
written, says what it converts and what waits, notifies a low-count shot once (Q9.4), and folders
set to start at launch open and start Live with auto-convert (Q9.6).

Helpers run in-process, as in ``test_live``: each queued request gets the real helper's events.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Iterator

import pytest
from pytestqt.qtbot import QtBot

from helab.convert.profile import MATLAB_2019, MATLAB_2023_LAB_EDIT
from helab.io_ops import convert
from helab.io_ops.convert import convert_folder
from helab.io_ops.fingerprints import DEFAULT_CHECK_LEVEL
from helab.io_ops.live import live_check
from helab.utils import events, folder_cache, io_service
from helab.utils.folder_cache import FolderCache, SharedJob
from helab.utils.io_service import IORequest, IOService
from helab.utils.settings_defaults import (
    CONVERT_BACKEND_SETTING, CONVERT_LOW_HITS_SETTING, LIVE_LAUNCH_FOLDER_SETTING, LIVE_LAUNCH_FOLDERS_SETTING,
)
from helab.utils.settings_store import app_settings
from helab.views import live_launch
from helab.views.FolderDetailsPanel import FolderDetailsPanel
from helab.views.FolderExplorer import FolderExplorer
from helab.views.explorer_live import no_hits_text as live_no_hits
from test_convert_helab import raw_bytes
from test_live import age_folder, deliver, job_of, next_request, producer, replay, service, write_shot  # noqa: F401

OLD = 1_700_000_000  # A raw file's mtime long settled.


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def deliver(self, title: str, message: str) -> str:
        self.sent.append((title, message))
        return "fake"


@pytest.fixture
def notifier() -> Iterator[FakeNotifier]:
    fake = FakeNotifier()
    events.reset(fake)
    yield fake
    events.reset()


@pytest.fixture(autouse=True)
def one_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Conversions run in this process, one shot after another (no process pool)."""
    monkeypatch.setattr(convert, "DEFAULT_WORKERS", 1)


@pytest.fixture(autouse=True)
def back_online() -> Iterator[None]:
    yield
    held = io_service._service
    if held is not None and held.folder_cache is not None and held.folder_cache.offline:
        held.folder_cache.set_offline(False)
    folder_cache._offline = False


def write_raw(folder: Path, shot: int, data: bytes, mtime: float = OLD) -> Path:
    path = folder / f"d{shot}.txt"
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return path


def run_convert(cache: FolderCache, path: str) -> list[dict[str, Any]]:
    """The queued conversion, run in-process, its events delivered as the service's would be."""
    request = producer(cache, path, "convert")
    sent: list[Any] = []
    try:
        convert_folder(path, request.payload, sent.append)  # type: ignore[arg-type]
        sent.append({"kind": "done"})
    except Exception as exc:
        sent.append({"kind": "error", "message": str(exc)})
    cache.service.pending.remove(request)
    return deliver(cache, request, sent)


def check(cache: FolderCache, path: str, tmp_path: Path) -> list[dict[str, Any]]:
    """``test_live.replay`` for the queued Live check, with every field ``io_helper`` passes (HeLab's
    TXY among them: ``txy``, ``memory_origins``, ``helab_since``); other requests as ``replay``."""
    request = producer(cache, path, "load")
    payload = request.payload
    if not payload.get("live"):
        return replay(cache, path, tmp_path)
    output = tmp_path / f"artifacts-{time.monotonic_ns()}"
    output.mkdir()
    sent: list[Any] = []
    try:
        live_check(path, str(output), sent.append, memory=payload.get("memory"), known=payload.get("known"),
                   since=payload.get("live_since"), identity=str(payload.get("identity") or ""),
                   seen=payload.get("seen"), check_level=str(payload.get("check_level") or DEFAULT_CHECK_LEVEL),
                   listed_mtime=payload.get("listed_mtime"), seen_names=payload.get("seen_names"),
                   identity_root=payload.get("identity_root"), recent=payload.get("recent"),
                   txy=payload.get("txy"), memory_origins=payload.get("memory_origins"),
                   helab_since=payload.get("helab_since"))
        sent.append({"kind": "done"})
    except Exception as exc:
        sent.append({"kind": "error", "message": str(exc)})
    cache.service.pending.remove(request)
    return deliver(cache, request, sent)


def of(sent: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [event for event in sent if event["kind"] == kind]


def watching_raw_folder(qtbot: QtBot, tmp_path: Path, *, auto_convert: bool = True) -> tuple[FolderExplorer, str]:
    """A tab watching an empty folder (raw files only arrive later), its first check done."""
    folder = tmp_path / "run"
    folder.mkdir()
    age_folder(folder, 120)
    path = str(folder)
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    cache = explorer.model.cache
    cache.live_interval = 0.02
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    replay(cache, path, tmp_path, "list")
    qtbot.waitUntil(lambda: explorer.model.nodes[path].report is not None)
    assert explorer.start_live()
    assert not explorer.auto_convert_button.isHidden() or explorer.isHidden()
    if auto_convert:
        explorer.live_control.set_auto_convert(True)
    next_request(qtbot, explorer, path)
    check(cache, path, tmp_path)
    return explorer, path


def cycle(qtbot: QtBot, explorer: FolderExplorer, path: str, tmp_path: Path) -> tuple[IORequest, list[dict[str, Any]]]:
    """One Live tick with auto-convert on: its conversion (run first), then its check. A check that
    a converted shot asked for comes alone (conversions keep their interval): answered first."""
    cache = explorer.model.cache
    for _ in range(3):
        qtbot.waitUntil(lambda: ("convert", path) in cache.jobs or job_of(cache, path) is not None)
        if ("convert", path) in cache.jobs:
            break
        check(cache, path, tmp_path)
    request = producer(cache, path, "convert")
    sent = run_convert(cache, path)
    next_request(qtbot, explorer, path)
    check(cache, path, tmp_path)
    return request, sent


def line(explorer: FolderExplorer) -> tuple[str, str]:
    explorer._update_activity()
    return explorer.folder_freshness_label.text(), explorer.folder_freshness_label.toolTip()


def test_a_raw_file_arriving_during_live_is_converted_once_written_not_before(
        qtbot: QtBot, service: IOService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(convert, "DAMAGED_SECONDS", 1e9)  # (Its files are dated long ago: never damaged here.)
    explorer, path = watching_raw_folder(qtbot, tmp_path)
    cache = explorer.model.cache
    session = explorer.live
    assert session is not None and session.convert is not None and explorer.auto_convert_button.isChecked()
    assert path in cache.auto_convert

    # The folder's first conversion this session only records (``seen`` is []).
    request, sent = cycle(qtbot, explorer, path, tmp_path)
    assert request.payload["seen"] == [] and request.payload["path"] == path and not of(sent, "shot_converted")
    assert request.payload["profile"] == MATLAB_2019.to_dict() and request.payload["destination"] == "cache"

    # Shot 1 arrives whole; shot 2 is still being written (no final newline yet).
    whole = raw_bytes(10_000, 20_000)
    write_raw(Path(path), 1, whole)
    write_raw(Path(path), 2, whole[:-2])
    request, sent = cycle(qtbot, explorer, path, tmp_path)
    assert not of(sent, "shot_converted")  # Seen once: not taken as finished yet.
    assert {event["raw_name"] for event in of(sent, "shot_waiting")} == {"d1.txt", "d2.txt"}

    # A check later: shot 1 is converted; shot 2 waits for its final newline, said with why.
    request, sent = cycle(qtbot, explorer, path, tmp_path)
    assert sorted(entry[0] for entry in request.payload["seen"]) == ["d1.txt", "d2.txt"]
    converted = of(sent, "shot_converted")
    assert [event["shot"] for event in converted] == [1] and converted[0]["hits"] == 2
    assert os.path.getsize(converted[0]["txy"]) == converted[0]["txy_size"] > 0
    waiting = of(sent, "shot_waiting")
    assert [(event["raw_name"], event["reason"]) for event in waiting] == [("d2.txt", "no_final_newline")]
    assert session.convert.converted == 1 and session.convert.last_shot == 1
    text, tooltip = line(explorer)
    assert "auto-convert 1 converted (last: shot 1), 1 waiting" in text, text
    assert "d2.txt" in tooltip and "Waiting (1)" in tooltip

    # Folder details say the same, its waiting file's reason in the tooltip.
    panel = FolderDetailsPanel()
    qtbot.addWidget(panel)
    panel.show_explorer(explorer, None)
    assert panel.text("convert").startswith("1 converted (last: shot 1), 1 waiting")
    assert "d2.txt" in panel.values["convert"].toolTip()

    # Shot 2's writer finishes: changed since it was seen, so it waits one more check, then converts.
    write_raw(Path(path), 2, whole, OLD + 1)
    request, sent = cycle(qtbot, explorer, path, tmp_path)
    assert [entry[0] for entry in request.payload["done"]] == ["d1.txt"]  # Not checked again.
    assert not of(sent, "shot_converted") and [event["reason"] for event in of(sent, "shot_waiting")] == ["changed"]
    request, sent = cycle(qtbot, explorer, path, tmp_path)
    assert [event["shot"] for event in of(sent, "shot_converted")] == [2]
    text, tooltip = line(explorer)
    assert "auto-convert 2 converted (last: shot 2)" in text and "waiting" not in text, text
    explorer.stop_live(save=False)
    explorer.close_cleanup()


def test_a_converted_shot_asks_for_lives_next_check(qtbot: QtBot, service: IOService, tmp_path: Path) -> None:
    """After a conversion writes a shot, Live's next check starts at once (it reads HeLab's TXY): the
    check queued with the conversion runs, then the next one without the wait."""
    explorer, path = watching_raw_folder(qtbot, tmp_path)
    cache = explorer.model.cache
    session = explorer.live
    assert session is not None
    cycle(qtbot, explorer, path, tmp_path)  # (Records.)
    write_raw(Path(path), 1, raw_bytes(10_000))
    cycle(qtbot, explorer, path, tmp_path)  # (Seen once.)
    qtbot.waitUntil(lambda: ("convert", path) in cache.jobs)
    assert session.request == "check" and not session.check_soon  # Queued with the conversion.
    assert [event["shot"] for event in of(run_convert(cache, path), "shot_converted")] == [1]
    assert session.check_soon
    cache.live_interval = 30.0  # Long: only a requested check comes soon.
    check(cache, path, tmp_path)
    qtbot.waitUntil(lambda: session.request == "check", timeout=2_000)
    assert not session.check_soon and ("convert", path) not in cache.jobs  # (Conversions keep their interval.)
    explorer.stop_live(save=False)
    explorer.close_cleanup()


def test_turning_auto_convert_off_stops_new_conversions(qtbot: QtBot, service: IOService, tmp_path: Path) -> None:
    explorer, path = watching_raw_folder(qtbot, tmp_path)
    cache = explorer.model.cache
    cycle(qtbot, explorer, path, tmp_path)
    qtbot.waitUntil(lambda: ("convert", path) in cache.jobs)
    explorer.auto_convert_button.click()  # Off: the running conversion is cancelled.
    assert ("convert", path) not in cache.jobs and not any(r.operation == "convert" for r in service.pending)
    assert explorer.live is not None and explorer.live.convert is None and path not in cache.auto_convert
    assert not explorer.auto_convert_button.isChecked()
    write_raw(Path(path), 1, raw_bytes(10_000))
    for _ in range(3):
        next_request(qtbot, explorer, path)
        check(cache, path, tmp_path)
        assert ("convert", path) not in cache.jobs
    text, _ = line(explorer)
    assert "auto-convert" not in text
    # On again: the folder's lists from earlier this session are sent back.
    explorer.auto_convert_button.click()
    qtbot.waitUntil(lambda: ("convert", path) in cache.jobs)
    assert producer(cache, path, "convert").payload["seen"] == []  # (Its last conversion found no raw file.)
    explorer.stop_live(save=False)
    assert ("convert", path) not in cache.jobs
    explorer.close_cleanup()


def test_auto_convert_is_remembered_for_the_session_and_shown_only_while_live(
        qtbot: QtBot, service: IOService, tmp_path: Path) -> None:
    explorer, path = watching_raw_folder(qtbot, tmp_path)
    explorer.stop_live(save=False)
    explorer._update_activity()
    assert explorer.auto_convert_button.isHidden()
    assert explorer.start_live()
    explorer._update_activity()
    assert explorer.live is not None and explorer.live.convert is not None
    assert explorer.auto_convert_button.isChecked()
    explorer.stop_live(save=False)
    explorer.close_cleanup()


def test_shots_converted_with_no_hits_are_named_in_amber(qtbot: QtBot, service: IOService, tmp_path: Path) -> None:
    """A17.1: a raw file that converts to no hits (a 0-byte TXY) is named on the Live line and in Folder
    details' Auto-convert row, amber, its shot number in the tooltip; a folder loaded later shows the same
    from its data's empty HeLab shots (memory only)."""
    explorer, path = watching_raw_folder(qtbot, tmp_path)
    session = explorer.live
    assert session is not None and session.convert is not None
    cycle(qtbot, explorer, path, tmp_path)
    write_raw(Path(path), 3, b"5,1000\r\n")  # The trigger alone: no hits.
    write_raw(Path(path), 4, raw_bytes(10_000, 20_000))
    cycle(qtbot, explorer, path, tmp_path)
    _, sent = cycle(qtbot, explorer, path, tmp_path)
    assert {event["shot"]: event["hits"] for event in of(sent, "shot_converted")} == {3: 0, 4: 2}
    assert session.convert.no_hits == {3}
    text, tooltip = line(explorer)
    assert "1 shot with no hits" in text and "No hits (1): shot 3." in tooltip
    assert "color" in explorer.folder_freshness_label.styleSheet()
    panel = FolderDetailsPanel()
    qtbot.addWidget(panel)
    panel.show_explorer(explorer, None)
    assert "1 shot with no hits" in panel.text("convert") and "shot 3" in panel.values["convert"].toolTip()
    assert "color" in panel.values["convert"].styleSheet()
    # Live off: the data shown still names it, from its empty HeLab shot.
    cycle(qtbot, explorer, path, tmp_path)
    shown = explorer.displayed_dataset
    assert shown is not None and 3 in shown.data and len(shown.data[3]) == 0
    explorer.stop_live(save=False)
    panel.show_explorer(explorer, None)
    assert panel.text("convert") == "1 shot with no hits" and "color" in panel.values["convert"].styleSheet()
    explorer.close_cleanup()


def test_a_loaded_folders_empty_helab_shots_are_its_no_hit_shots() -> None:
    import numpy as np
    from helab.utils import txy_sources
    metadata = {"txy": {"source": "helab-priority", "origins": {"2": "helab:h", "3": "helab:h"}}}
    data = {1: np.zeros((0, 3)), 2: np.zeros((0, 3)), 3: np.ones((4, 3))}
    # (Shot 1 is MATLAB's: an empty MATLAB TXY isn't HeLab's conversion.)
    assert txy_sources.empty_helab_shots(metadata, data) == [2]
    assert txy_sources.empty_helab_shots({}, data) == []
    text, tip = live_no_hits([2, 5])
    assert text == "2 shots with no hits" and "shots 2, 5." in tip and live_no_hits([]) == ("", "")


def test_a_damaged_file_is_said_once_and_survives_auto_convert_off_and_on(
        qtbot: QtBot, service: IOService, tmp_path: Path, notifier: FakeNotifier,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A raw file unchanged for 20 s that fails the format checks (here: no rows) is damaged (Q18.5), said
    once by the helper (later conversions skip it) and notified once; the Live line and Folder details
    name it, also after auto-convert goes off and on (Heron2's review)."""
    # (Its checks are milliseconds apart: no wait for 20 s since the file was first seen.)
    monkeypatch.setattr(convert, "DAMAGED_SECONDS", 0.0)
    explorer, path = watching_raw_folder(qtbot, tmp_path)
    session = explorer.live
    assert session is not None
    cycle(qtbot, explorer, path, tmp_path)
    write_raw(Path(path), 4, b"\r\n\r\n")
    cycle(qtbot, explorer, path, tmp_path)
    _, sent = cycle(qtbot, explorer, path, tmp_path)
    [refused] = of(sent, "shot_unconvertible")
    reason = str(refused["message"])
    assert refused["reason"] == "damaged" and refused["problem"] == "no_rows" and reason.startswith("Damaged: ")
    assert session.convert is not None and session.convert.unconvertible == {"d4.txt": reason}
    assert session.convert.damaged == {"d4.txt"}
    assert len(notifier.sent) == 1 and notifier.sent[0][0] == "HeLab: damaged raw file"
    assert "d4.txt in run is damaged" in notifier.sent[0][1] and "later shots go on" in notifier.sent[0][1]
    explorer.live_control.set_auto_convert(False)
    explorer.live_control.set_auto_convert(True)
    _, sent = cycle(qtbot, explorer, path, tmp_path)
    assert not of(sent, "shot_unconvertible")  # Skipped, not said again ...
    assert session.convert.unconvertible == {"d4.txt": reason}  # ... and its reason kept.
    assert session.convert.damaged == {"d4.txt"} and len(notifier.sent) == 1
    text, tooltip = line(explorer)
    assert "1 damaged" in text and "unconvertible" not in text
    assert f"d4.txt: {reason.removeprefix('Damaged: ')}" in tooltip and "Damaged (unchanged for 20 s" in tooltip
    panel = FolderDetailsPanel()
    qtbot.addWidget(panel)
    panel.show_explorer(explorer, None)
    assert "1 damaged" in panel.text("convert") and "d4.txt" in panel.values["convert"].toolTip()
    explorer.stop_live(save=False)
    explorer.close_cleanup()


def test_a_file_unconvertible_under_one_profile_is_tried_under_another(
        qtbot: QtBot, service: IOService, tmp_path: Path, notifier: FakeNotifier,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex 4425255663: the unconvertible list is the profile's, as the done one is. Under another profile
    a damaged file is read again (still damaged here: said again on the Live line, notified only once,
    as the notification is per file, size and date)."""
    monkeypatch.setattr(convert, "DAMAGED_SECONDS", 0.0)
    explorer, path = watching_raw_folder(qtbot, tmp_path)
    cycle(qtbot, explorer, path, tmp_path)
    write_raw(Path(path), 4, b"\r\n\r\n")
    cycle(qtbot, explorer, path, tmp_path)
    _, sent = cycle(qtbot, explorer, path, tmp_path)
    assert [event["shot"] for event in of(sent, "shot_unconvertible")] == [4] and len(notifier.sent) == 1
    _, sent = cycle(qtbot, explorer, path, tmp_path)
    assert not of(sent, "shot_unconvertible")  # (Skipped under the same profile.)
    explorer.model.cache.set_convert_profile(MATLAB_2023_LAB_EDIT)
    # (Its first conversion under that profile has no lists of its own: the file waits one tick, unseen.)
    retried = [event for _ in range(2) for event in of(cycle(qtbot, explorer, path, tmp_path)[1], "shot_unconvertible")]
    assert [event["shot"] for event in retried] == [4] and retried[0]["reason"] == "damaged"
    session = explorer.live
    assert session is not None and session.convert is not None and session.convert.damaged == {"d4.txt"}
    assert len(notifier.sent) == 1
    explorer.stop_live(save=False)
    explorer.close_cleanup()


def test_the_lists_of_the_last_conversion_are_sent_back(service: IOService) -> None:
    cache = folder_cache.get_folder_cache(service)
    path = FolderCache.key("/data/run")
    cache._remember_convert(
        SharedJob("job", path, "convert", 0, {"profile": MATLAB_2019.to_dict()}),
        {"current": [["d1.txt", 10, 1]], "waiting": [["d2.txt", 5, 2, "no_final_newline", "…"]],
         "unconvertible": [["d3.txt", 0, 3]], "kept": [["d4.txt", 9, 4]]})
    assert cache.convert("t", path)
    payload = next(r for r in service.pending if r.operation == "convert").payload
    assert payload["seen"] == [["d2.txt", 5, 2, "no_final_newline", "…"]] and payload["skip"] == [["d3.txt", 0, 3]]
    assert payload["done"] == [["d1.txt", 10, 1]] and payload["kept"] == [["d4.txt", 9, 4]]
    assert payload["profile"] == MATLAB_2019.to_dict() and payload["backend"] == "numpy"
    cache.cancel("t")
    # Another profile and backend (Settings → TXY converter's Save): the profile's current shots
    # aren't this one's, so they are checked again.
    cache.set_convert_profile(MATLAB_2023_LAB_EDIT)
    app_settings().setValue(CONVERT_BACKEND_SETTING, "reference")
    assert cache.convert("t", path)
    payload = next(r for r in service.pending if r.operation == "convert").payload
    # Nor its unconvertible ones (Codex 4425255663): a file damaged for one profile's trigger channel is tried
    # again under the corrected one.
    assert payload["profile"] == MATLAB_2023_LAB_EDIT.to_dict() and "done" not in payload and "kept" not in payload
    assert payload["backend"] == "reference" and "skip" not in payload
    assert payload["seen"]
    cache.cancel("t")


def test_work_offline_refuses_a_conversion(qtbot: QtBot, service: IOService, tmp_path: Path) -> None:
    cache = folder_cache.get_folder_cache(service)
    got: list[dict[str, Any]] = []
    cache.resultReady.connect(lambda request, event: got.append(event) if request.owner == "t" else None)
    cache.set_offline(True)
    try:
        assert cache.convert("t", str(tmp_path))
        qtbot.waitUntil(lambda: any(event["kind"] == "cancelled" for event in got))
        assert [event["kind"] for event in got] == ["offline", "cancelled"]
        assert not any(r.operation == "convert" for r in service.pending)
    finally:
        cache.set_offline(False)


def test_a_conversion_refused_offline_stops_auto_convert_and_says_so(
        qtbot: QtBot, service: IOService, tmp_path: Path) -> None:
    explorer, path = watching_raw_folder(qtbot, tmp_path)
    cache = explorer.model.cache
    cycle(qtbot, explorer, path, tmp_path)
    qtbot.waitUntil(lambda: ("convert", path) in cache.jobs)
    session = explorer.live
    assert session is not None and session.convert is not None
    cache.cancel(explorer.live_owner, "convert", path)  # (Cancelled by someone else: tried again next tick.)
    assert not session.convert.request and not session.convert.error
    service.offline = True  # (As if offline came first; the window turns Live off then.)
    try:
        session.convert.ended_at = -1e9
        explorer.live_control._convert_tick(session)
        qtbot.waitUntil(lambda: bool(session.convert and session.convert.error))
    finally:
        service.offline = False
    assert str(session.convert.error) == "not while working offline"  # (str: mypy narrowed it to "" above.)
    text, tooltip = line(explorer)
    assert "auto-convert stopped: not while working offline" in text
    assert "Retry converts again" in tooltip and explorer.folder_freshness_label.styleSheet()
    assert not explorer.retry_button.isHidden() or explorer.isHidden()
    # Retry converts again.
    explorer.resume_live()
    assert not session.convert.error
    if session.request == "check":
        check(cache, path, tmp_path)  # (Its next tick asks for both.)
    qtbot.waitUntil(lambda: ("convert", path) in cache.jobs)
    explorer.stop_live(save=False)
    explorer.close_cleanup()


def test_a_conversion_error_stops_auto_convert_until_retry(qtbot: QtBot, service: IOService, tmp_path: Path) -> None:
    explorer, path = watching_raw_folder(qtbot, tmp_path)
    cache = explorer.model.cache
    session = explorer.live
    assert session is not None and session.convert is not None
    qtbot.waitUntil(lambda: ("convert", path) in cache.jobs)
    request = producer(cache, path, "convert")
    cache.service.pending.remove(request)
    deliver(cache, request, [{"kind": "error", "message": "Backend numpy unavailable — Retry"}])
    assert session.convert.error == "Backend numpy unavailable" and not session.error
    for _ in range(2):  # Live goes on checking; no conversion meanwhile.
        next_request(qtbot, explorer, path)
        check(cache, path, tmp_path)
        assert ("convert", path) not in cache.jobs
    explorer._retry()
    qtbot.waitUntil(lambda: ("convert", path) in cache.jobs)
    explorer.stop_live(save=False)
    explorer.close_cleanup()


def test_a_low_count_shot_notifies_once(qtbot: QtBot, service: IOService, tmp_path: Path,
                                        notifier: FakeNotifier) -> None:
    app_settings().setValue(CONVERT_LOW_HITS_SETTING, 2)
    explorer, path = watching_raw_folder(qtbot, tmp_path)
    cycle(qtbot, explorer, path, tmp_path)
    write_raw(Path(path), 1, raw_bytes(10_000))  # 1 hit: low.
    write_raw(Path(path), 2, raw_bytes(10_000, 20_000))  # 2 hits: not.
    cycle(qtbot, explorer, path, tmp_path)
    _, sent = cycle(qtbot, explorer, path, tmp_path)
    converted = of(sent, "shot_converted")
    assert [(event["shot"], event["hits"]) for event in converted] == [(1, 1), (2, 2)]
    assert notifier.sent == [("HeLab: low counts", "Shot 1 of run: 1 hits (fewer than 2), converted by HeLab")]
    low = [event for event in events.hub().history if event.kind == events.LOW_COUNTS]
    assert len(low) == 1 and low[0].data["shot"] == 1 and low[0].data["source"] == "convert"
    # The same shot converted again (another profile, say): no second notification.
    session = explorer.live
    assert session is not None and session.convert is not None
    session.convert.request = True
    explorer.live_control._convert_event(session, converted[0])
    assert len(notifier.sent) == 1 and session.convert.low == 1
    # 0: never.
    app_settings().setValue(CONVERT_LOW_HITS_SETTING, 0)
    explorer.live_control._convert_event(session, {**converted[0], "shot": 9, "raw_sha256": "x"})
    assert len(notifier.sent) == 1
    text, tooltip = line(explorer)
    assert "low-count notifications off" in tooltip
    explorer.stop_live(save=False)
    explorer.close_cleanup()


def test_a_converted_shot_reaches_the_live_data(qtbot: QtBot, service: IOService, tmp_path: Path) -> None:
    """The seam between the floors: a raw file converted while Live runs joins the tab's data."""
    explorer, path = watching_raw_folder(qtbot, tmp_path)
    cycle(qtbot, explorer, path, tmp_path)
    write_raw(Path(path), 1, raw_bytes(10_000, 20_000))
    for _ in range(4):  # Recorded, converted, then seen and read by Live's checks.
        cycle(qtbot, explorer, path, tmp_path)
    try:
        assert sorted(explorer.folder_opened_data or {}) == [1]
    finally:
        explorer.stop_live(save=False)
        explorer.close_cleanup()


def test_a_conversion_the_app_asks_for_runs_in_a_helper_process(qtbot: QtBot, tmp_path: Path) -> None:
    """Through the app's own IOService and a real helper process, as Live asks for it: the payload
    survives what the service adds to it (each helper's private folder is its ``output``)."""
    folder = tmp_path / "run"
    folder.mkdir()
    write_raw(folder, 1, raw_bytes(10_000, 20_000))
    real = IOService()
    cache = folder_cache.get_folder_cache(real)
    got: list[tuple[str, dict[str, Any]]] = []
    cache.resultReady.connect(lambda request, event: got.append((request.owner, event)))
    try:
        for owner in ("first", "second"):  # The first only records; the second converts.
            assert cache.convert(owner, str(folder))
            qtbot.waitUntil(lambda: any(who == owner and event["kind"] in ("done", "error", "cancelled")
                                        for who, event in got), timeout=30_000)
        second = [event for who, event in got if who == "second"]
        assert not [event for event in second if event["kind"] == "error"], second
        plan = next(event for event in second if event["kind"] == "convert_plan")
        assert plan["output"] in ("cache", "temp")
        converted = [event for event in second if event["kind"] == "shot_converted"]
        assert [event["shot"] for event in converted] == [1] and converted[0]["hits"] == 2
        assert os.path.getsize(converted[0]["txy"]) == converted[0]["txy_size"]
    finally:
        cache.shutdown()
        real.shutdown()


# Start at launch (Q9.6; one folder, Q18.3)


def test_the_launch_folder_is_a_setting_of_one_folder(qtbot: QtBot, tmp_path: Path) -> None:
    first, second = str(tmp_path / "a"), str(tmp_path / "b")
    settings = app_settings()
    assert live_launch.launch_folder() == "" and not live_launch.starts_at_launch(first)
    live_launch.set_starts_at_launch(first, True)
    live_launch.set_starts_at_launch(second + os.sep, True)  # (Another: it replaces the first.)
    assert live_launch.launch_folder() == second and not live_launch.starts_at_launch(first)
    live_launch.set_starts_at_launch(first, False)  # (Not the launch folder: nothing changes.)
    assert live_launch.starts_at_launch(second)
    live_launch.set_starts_at_launch(second, False)
    assert live_launch.launch_folder() == "" and not settings.contains(LIVE_LAUNCH_FOLDER_SETTING)
    # A list saved before Q18.3: its first folder kept, the list removed.
    settings.setValue(LIVE_LAUNCH_FOLDERS_SETTING, json.dumps([second, first]))
    assert live_launch.launch_folder() == second and not settings.contains(LIVE_LAUNCH_FOLDERS_SETTING)
    assert settings.value(LIVE_LAUNCH_FOLDER_SETTING) == second
    settings.remove(LIVE_LAUNCH_FOLDER_SETTING)
    settings.setValue(LIVE_LAUNCH_FOLDERS_SETTING, "not json")
    assert live_launch.launch_folder() == "" and not settings.contains(LIVE_LAUNCH_FOLDERS_SETTING)
    # The new folder wins over an old list (an older HeLab may have saved one since).
    settings.setValue(LIVE_LAUNCH_FOLDER_SETTING, first)
    settings.setValue(LIVE_LAUNCH_FOLDERS_SETTING, json.dumps([second]))
    assert live_launch.launch_folder() == first
    settings.remove(LIVE_LAUNCH_FOLDER_SETTING)
    settings.remove(LIVE_LAUNCH_FOLDERS_SETTING)


def window(qtbot: QtBot) -> Any:
    from helab.views.HelabMainWindow import HelabMainWindow
    created = HelabMainWindow()
    qtbot.addWidget(created)
    qtbot.waitUntil(lambda: isinstance(created.tab_widget.currentWidget(), FolderExplorer), timeout=10_000)
    return created


@pytest.fixture
def at_launch(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The main window opens the launch folder as it would outside pytest."""
    monkeypatch.setattr(live_launch, "opens_at_launch", lambda in_tests=False: live_launch.launch_folder())
    yield
    app_settings().remove(LIVE_LAUNCH_FOLDER_SETTING)
    folder_cache.get_folder_cache(io_service.get_io_service()).auto_convert.clear()


def test_the_launch_folder_opens_alone_and_starts_live_with_auto_convert(
        qtbot: QtBot, tmp_path: Path, notifier: FakeNotifier, caplog: pytest.LogCaptureFixture, at_launch: None) -> None:
    caplog.set_level(logging.INFO)
    from test_presets_window import quit_window
    folder = tmp_path / "run"
    folder.mkdir()
    write_shot(folder, 1)
    assert live_launch.start(window(qtbot)) is None  # Never under pytest unless the test asks (or patched).
    app_settings().setValue(LIVE_LAUNCH_FOLDER_SETTING, str(folder))
    main = window(qtbot)
    # The launch folder's tab is the only one (Q18.3): no usual first tab beside it.
    assert main.tab_widget.count() == 1
    explorer = main.tab_widget.currentWidget()
    assert isinstance(explorer, FolderExplorer) and explorer.selected_path_globally == str(folder)
    qtbot.waitUntil(lambda: explorer.live is not None, timeout=30_000)
    assert explorer.live is not None and explorer.live.path == str(folder) and explorer.live.convert is not None
    qtbot.wait(100)
    assert [record.getMessage() for record in caplog.records if record.getMessage().startswith("Live on:")] == [
        f"Live on: {folder}"]  # Once: starting shows its data, which signals the watcher again.
    assert explorer.live_control.auto_converting() and main.action_tab_live.isChecked()
    assert str(folder) in explorer.model.cache.auto_convert and notifier.sent == []
    # Live on collapses the file explorer panel; an error stopping its checks (Retry is there) and Live
    # off restore it.
    assert main.splitter.sizes()[0] == 0
    explorer.live.error = "test"
    explorer.liveChanged.emit()
    assert main.splitter.sizes()[0] > 0
    explorer.live.error = ""
    explorer.liveChanged.emit()
    assert main.splitter.sizes()[0] == 0
    explorer.stop_live(save=False)
    assert main.splitter.sizes()[0] > 0 and not main._live_collapsed_panel
    # A panel the user collapsed stays so after Live.
    main.toggle_left_panel(False)
    assert explorer.start_live()
    explorer.stop_live(save=False)
    assert main.splitter.sizes()[0] == 0
    main.toggle_left_panel(True)
    quit_window(qtbot, main)


def test_a_launch_folder_that_cant_be_opened_notifies_once_and_isnt_retried(
        qtbot: QtBot, tmp_path: Path, notifier: FakeNotifier, at_launch: None) -> None:
    from test_presets_window import quit_window
    missing = tmp_path / "gone"
    app_settings().setValue(LIVE_LAUNCH_FOLDER_SETTING, str(missing))
    main = window(qtbot)
    explorer = main.tab_widget.currentWidget()
    assert isinstance(explorer, FolderExplorer) and main.tab_widget.count() == 1
    qtbot.waitUntil(lambda: len(notifier.sent) == 1, timeout=60_000)
    assert explorer.live is None and notifier.sent[0][0] == "HeLab: Live at launch"
    assert "not started for gone: it can't be opened now" in notifier.sent[0][1], notifier.sent
    time.sleep(0.2)
    qtbot.wait(100)
    assert len(notifier.sent) == 1 and explorer.live is None
    quit_window(qtbot, main)


def test_working_offline_the_launch_folder_opens_without_live_and_it_says_so(
        qtbot: QtBot, tmp_path: Path, notifier: FakeNotifier) -> None:
    from test_presets_window import quit_window
    folder = tmp_path / "run"
    folder.mkdir()
    app_settings().setValue(LIVE_LAUNCH_FOLDER_SETTING, str(folder))
    try:
        main = window(qtbot)
        tabs = main.tab_widget.count()
        main.set_work_offline(True)
        try:
            assert live_launch.start(main, in_tests=True) is None
            assert main.tab_widget.count() == tabs + 1
            explorer = main.tab_widget.currentWidget()
            assert isinstance(explorer, FolderExplorer) and explorer.live is None
            assert len(notifier.sent) == 1 and "Working offline: Live and auto-convert not started for run" in \
                notifier.sent[0][1]
        finally:
            main.set_work_offline(False)
        quit_window(qtbot, main)
    finally:
        app_settings().remove(LIVE_LAUNCH_FOLDER_SETTING)
