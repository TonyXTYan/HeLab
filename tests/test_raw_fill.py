"""Caching v2's ``raw_fill`` (stage 1, step 5): a folder's raw files into store-v4's raw layers, in
batches, skipping what is cached, marking shots gone, yielding, never asking over the budget (T~1);
FolderCache's scheduling (store-v4 only, after a save, one per folder, again when asked or when it
yielded) and Q28.6's notice; a conversion's own raw rows. Synthetic files under ``tmp_path`` only."""
from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any, Iterator

import pytest
from pytestqt.qtbot import QtBot

from helab.convert import raw_layer
from helab.convert.profile import MATLAB_2019
from helab.convert.raw import parse_raw
from helab.io_ops import fingerprints, stores
from helab.io_ops.convert import convert_folder
from helab.io_ops.raw_fill import raw_fill
from helab.utils import cache_store, events
from helab.utils.cache_store import CacheStore
from helab.utils.folder_cache import RAW_FILL_OWNER, FolderCache, store_options
from helab.utils.io_service import IORequest, IOService

OLD = 1_700_000_000


def raw_text(shot: int, rows: int = 300) -> bytes:
    return "".join(f"{5 if i == 0 else 1 + i % 8},{100_000 * shot + 41 * i}\r\n" for i in range(rows)).encode()


def write_raw(folder: Path, shot: int, data: bytes | None = None, mtime: float = OLD) -> Path:
    path = folder / f"d{shot}.txt"
    path.write_bytes(raw_text(shot) if data is None else data)
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def source(tmp_path: Path) -> Path:
    folder = tmp_path / "data" / "run"
    folder.mkdir(parents=True)
    for shot in (1, 2, 3):
        write_raw(folder, shot)
    return folder


@pytest.fixture
def v4_options(tmp_path: Path) -> dict[str, Any]:
    return {"directory": str(tmp_path / "caches" / "store-v4"), "budget": 8 << 30, "budget_set_at": 1.0}


def fill(source: Path, options: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    raw_fill(str(source), options, sent.append, **kwargs)  # type: ignore[arg-type]
    return sent


def done(sent: list[dict[str, Any]]) -> dict[str, Any]:
    [found] = [event for event in sent if event["kind"] == "raw_fill_done"]
    return found


def opened(options: dict[str, Any], source: Path) -> CacheStore:
    """The store as the helpers open it: folders keyed by their data root."""
    return stores._cache_store(options["directory"], [str(source)])


def rows(options: dict[str, Any], source: Path) -> dict[int, Any]:
    with opened(options, source) as store:
        found = store.raw_rows(str(source))
        assert found.found or found.missing
        return found.value or {}


# The helper operation

def test_a_fill_saves_every_settled_raw_file_once(source: Path, v4_options: dict[str, Any]) -> None:
    first = done(fill(source, v4_options))
    assert (first["saved"], first["kept"], first["reason"], first["more"]) == (3, 0, "", False)
    assert first["usage"] > 0 and isinstance(first["usage_seq"], list)
    saved = rows(v4_options, source)
    assert set(saved) == {1, 2, 3}
    with opened(v4_options, source) as store:
        found = store.read_raw(str(source), 2).value
        assert found is not None
        row, data = found
        assert row.seen_at > 0 and row.gone_at is None
        layer, header = raw_layer.from_hlb(data)
        pulses, file = raw_layer.decode(layer), parse_raw(raw_text(2))
        assert pulses.times[0] == file.times[0] and len(pulses) == len(file)
        assert header["meta"]["name"] == "d2.txt" and header["maker"]["maker"]
    again = done(fill(source, v4_options))  # (Nothing new: one listing, no read.)
    assert (again["saved"], again["kept"], again["waiting"]) == (0, 0, 0)


def test_an_overwritten_raw_file_is_replaced_and_said_and_a_gone_one_is_the_only_copy(
        source: Path, v4_options: dict[str, Any]) -> None:
    fill(source, v4_options)
    write_raw(source, 2, raw_text(2, rows=500), mtime=OLD + 100)  # (Rewritten in place: the TDC misconfigured.)
    (source / "d3.txt").unlink()
    sent = fill(source, v4_options)
    [overwritten] = [event for event in sent if event["kind"] == "raw_overwritten"]
    assert overwritten["shot"] == 2 and overwritten["raw_name"] == "d2.txt"
    assert overwritten["old"][1] == OLD * 10**9 and overwritten["new"][1] == (OLD + 100) * 10**9
    finished = done(sent)
    assert (finished["saved"], finished["gone"]) == (1, 1)
    saved = rows(v4_options, source)
    assert saved[3].gone_at is not None and saved[2].size == len(raw_text(2, rows=500))


def test_files_not_settled_wait_and_a_fill_yields(source: Path, v4_options: dict[str, Any],
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fingerprints, "SETTLE_SECONDS", 5.0)
    write_raw(source, 4, mtime=time.time())  # (Still being written.)
    first = done(fill(source, v4_options))
    assert (first["saved"], first["waiting"]) == (3, 1)
    write_raw(source, 5)
    yielded = done(fill(source, v4_options, work_seconds=-1.0))  # (Its time is up at once.)
    assert yielded["more"] and yielded["saved"] == 0


@pytest.mark.parametrize("case", ["store-v3", "no_cache", "over_budget"])
def test_a_fill_that_may_not_save(source: Path, tmp_path: Path, v4_options: dict[str, Any], case: str) -> None:
    if case == "store-v3":
        options = {**v4_options, "directory": str(tmp_path / "caches" / "store-v3")}
        assert done(fill(source, options))["reason"] == "store_v3"
        assert not (tmp_path / "caches" / "store-v4").exists()
        return
    if case == "no_cache":
        with opened(v4_options, source) as store:
            store.set_prefs(str(source), True, False, time.time())
        assert done(fill(source, v4_options))["reason"] == "no_cache"
    else:
        with opened(v4_options, source) as store:
            usage = store.usage()
        finished = done(fill(source, {**v4_options, "budget": usage + 10, "budget_set_at": 2.0}))
        assert (finished["reason"], finished["saved"], finished["more"]) == ("over_budget", 0, False)
    assert rows(v4_options, source) == {}


# A conversion's raw rows

def test_a_conversion_into_the_cache_saves_its_raw_rows(source: Path, tmp_path: Path,
                                                         v4_options: dict[str, Any]) -> None:
    request: dict[str, Any] = {"path": str(source), "profile": MATLAB_2019.to_dict(), "temps": str(tmp_path / "temps"),
                               "seen": None, "destination": "cache", "workers": 1, "cache": v4_options}
    sent: list[dict[str, Any]] = []
    convert_folder(str(source), request, sent.append)  # type: ignore[arg-type]
    assert sorted(event["shot"] for event in sent if event["kind"] == "shot_converted") == [1, 2, 3]
    assert set(rows(v4_options, source)) == {1, 2, 3}
    temp: dict[str, Any] = {**request, "destination": "temp"}  # (Not the cache folder: no raw rows.)
    other = tmp_path / "data" / "other"
    other.mkdir()
    write_raw(other, 1)
    temp["path"] = str(other)
    convert_folder(str(other), temp, sent.append)  # type: ignore[arg-type]
    assert rows(v4_options, other) == {}


def test_a_conversions_raw_rows_are_saved_by_bytes_too(source: Path, tmp_path: Path, v4_options: dict[str, Any],
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """C3-1 (Assay): a folder of large shots isn't held until 50 have gathered (about 1 GB at 20 MB a shot):
    a conversion's raw rows are saved once ``BATCH_BYTES`` of raw text has gathered, as ``raw_fill``'s are."""
    from helab.io_ops import raw_fill as module
    monkeypatch.setattr(module, "BATCH_BYTES", len(raw_text(1)) + 1)  # (Two shots' worth reach it.)
    batches: list[list[int]] = []
    save_batch = module.save_batch

    def counted(store: Any, path: str, items: Any, *args: Any, **kwargs: Any) -> Any:
        batches.append([item.shot for item in items])
        return save_batch(store, path, items, *args, **kwargs)
    monkeypatch.setattr(module, "save_batch", counted)
    request: dict[str, Any] = {"path": str(source), "profile": MATLAB_2019.to_dict(), "temps": str(tmp_path / "temps"),
                               "seen": None, "destination": "cache", "workers": 1, "cache": v4_options}
    convert_folder(str(source), request, lambda event: None)  # type: ignore[arg-type]
    assert batches == [[1, 2], [3]] and set(rows(v4_options, source)) == {1, 2, 3}


def test_encoding_a_large_raw_file_keeps_heartbeats_going(source: Path, v4_options: dict[str, Any],
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """C3-1 (Assay): zstd 9 on a few hundred MB takes longer than the no-progress timeout on a slow PC; the
    encode runs under the converter's ticker (``compute_budget``), for ``raw_fill`` and conversions alike."""
    import threading
    from helab.io_ops import raw_fill as module
    from helab.io_ops.infra import Heartbeat
    monkeypatch.setattr(Heartbeat, "INTERVAL", 0.02)
    encode = raw_layer.encode
    sent: list[dict[str, Any]] = []
    beating = threading.Event()

    def send(event: dict[str, Any]) -> None:
        sent.append(event)
        if sum(item["kind"] == "heartbeat" for item in sent) >= 3:
            beating.set()

    def slow(data: bytes) -> Any:
        # (A long encode, with no read and no shot finished meanwhile: it lasts until three heartbeats came,
        # however slowly a loaded runner schedules the ticker; without one it gives up after 10 s.)
        beating.wait(10)
        return encode(data)
    monkeypatch.setattr(raw_layer, "encode", slow)
    with opened(v4_options, source) as store:
        guard = store.start_raw_job(str(source))
        data = raw_text(1)
        item = module.RawRead(1, "d1.txt", len(data), OLD * 10**9, data, time.time())
        module.save_batch(store, str(source), [item], guard, v4_options, send)  # type: ignore[arg-type]
    assert beating.is_set()


def test_a_fill_leaves_a_raw_file_that_isnt_finished_waiting(source: Path, v4_options: dict[str, Any]) -> None:
    """C3-2 (Assay): the TDC paused mid-file longer than the settle time. Its layer isn't cached (as the
    converter, ``raw.not_done``: blank or no final newline), so finishing it later isn't reported as
    overwritten (Q28.6's warning means a finished file changed)."""
    whole = raw_text(4)
    write_raw(source, 4, whole[:-7])  # (Cut mid-line.)
    write_raw(source, 5, b"\r\n\r\n")  # (Blank.)
    first = done(fill(source, v4_options))
    assert (first["saved"], first["waiting"]) == (3, 2) and set(rows(v4_options, source)) == {1, 2, 3}
    write_raw(source, 4, whole, mtime=OLD + 100)
    sent = fill(source, v4_options)
    assert done(sent)["saved"] == 1 and not any(event["kind"] == "raw_overwritten" for event in sent)
    assert set(rows(v4_options, source)) == {1, 2, 3, 4}


# FolderCache

@pytest.fixture
def v4_live() -> Iterator[None]:
    cache_store._reset_live_layout(4)
    yield
    cache_store._reset_live_layout()


def frozen(monkeypatch: pytest.MonkeyPatch) -> tuple[IOService, FolderCache]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    return service, FolderCache(service)


def fills(service: IOService) -> list[IORequest]:
    return [request for request in service.pending if request.operation == "raw_fill"]


def test_folder_cache_fills_once_per_folder_in_store_v4_only(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
                                                            v4_live: None) -> None:
    service, cache = frozen(monkeypatch)
    try:
        cache.schedule_raw_fill("/data/run")
        cache.schedule_raw_fill("/data/run")  # (Queued already: one.)
        [request] = fills(service)
        assert request.owner == RAW_FILL_OWNER + "/data/run" and request.payload["cache"] == store_options()
        assert request.payload["cache"]["directory"].endswith("store-v4")
        cache.remember_prefs("/data/flagged", {"no_cache": True, "no_auto_load": False, "set_at": 1.0})
        cache.schedule_raw_fill("/data/flagged")
        assert len(fills(service)) == 1  # (Don't cache: none.)
        service.pending.remove(request)
        service.resultReady.emit(request, {"kind": "raw_fill_done", "path": "/data/run", "reason": "", "saved": 50,
                                           "kept": 0, "refused": 0, "waiting": 0, "gone": 0, "more": True})
        service.resultReady.emit(request, {"kind": "done"})
        qtbot.waitUntil(lambda: bool(fills(service)), timeout=5000)
        assert [r.path for r in fills(service)] == ["/data/run"]  # (It yielded: the rest, queued again.)
    finally:
        service.shutdown()


def test_folder_cache_never_fills_in_store_v3_or_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    cache_store._reset_live_layout(3)
    try:
        cache.schedule_raw_fill("/data/run")
        assert fills(service) == []
        cache_store._reset_live_layout(4)
        cache.set_offline(True)
        cache.schedule_raw_fill("/data/run")
        assert fills(service) == []
    finally:
        cache.set_offline(False)  # (A module-wide choice: the next test's too.)
        cache_store._reset_live_layout()
        service.shutdown()


def test_an_overwritten_raw_file_is_said_once_per_shot(monkeypatch: pytest.MonkeyPatch, v4_live: None,
                                                        caplog: pytest.LogCaptureFixture) -> None:
    service, cache = frozen(monkeypatch)
    shown: list[str] = []
    cache.rawOverwritten.connect(shown.append)
    noticed: list[events.Event] = []
    remove = events.hub().add_hook(noticed.append)
    try:
        cache.schedule_raw_fill("/data/run")
        [request] = fills(service)
        event = {"kind": "raw_overwritten", "path": "/data/run", "shot": 12, "raw_name": "d12.txt",
                 "old": [10, 1, "a"], "new": [20, 2, "b"]}
        for _ in range(2):
            service.resultReady.emit(request, event)
        assert shown == ["/data/run"] and list(cache.raw_overwrites["/data/run"]) == [12]
        # (FolderCache's own warning names the folder; the hub logs the notice too.)
        assert sum("Raw file d12.txt in run was overwritten" in record.getMessage()
                   and record.getMessage().endswith("(/data/run)") for record in caplog.records) == 1
        assert cache.raw_overwrites["/data/run"][12]["raw_name"] == "d12.txt"
        [notice] = [event for event in noticed if event.kind == events.RAW_OVERWRITTEN]
        assert notice.desktop and "d12.txt" in notice.message
    finally:
        remove()
        service.shutdown()


def test_folder_details_names_overwritten_raw_files_in_amber() -> None:
    from types import SimpleNamespace
    from helab.views.FolderDetailsPanel import RAW_OVERWRITTEN_TEXT, FolderDetailsPanel
    cache = SimpleNamespace(raw_overwrites={"/data/run": {12: {"raw_name": "d12.txt"}, 3: {"raw_name": "d3.txt"}}})
    explorer: Any = SimpleNamespace(model=SimpleNamespace(cache=cache), selected_path_globally="/data/run")
    text, tooltip = FolderDetailsPanel._raw_overwritten_row(explorer, ("1 shot unreadable", "why")) or ("", "")
    assert text == f"1 shot unreadable · 2 {RAW_OVERWRITTEN_TEXT}"
    assert tooltip.startswith("why\n\n") and "d3.txt, d12.txt" in tooltip
    explorer.selected_path_globally = "/data/other"
    assert FolderDetailsPanel._raw_overwritten_row(explorer, ("", "")) is None


@pytest.mark.parametrize("valid", [True, False])
def test_a_folders_saved_data_queues_its_raw_fill(monkeypatch: pytest.MonkeyPatch, v4_live: None,
                                                  valid: bool) -> None:
    """Q19.10: wherever HeLab saves a folder's data to the disk cache (a load, Live's saves: ``cache_saved``),
    its raw fill follows in the background; a save a Clear voided queues none."""
    service, cache = frozen(monkeypatch)
    try:
        producer = IORequest("loader", 0, "/data/run", "load", {}, 60)
        cache._finishing[producer.owner] = "/data/run"
        cache._finishing_epochs[producer.owner] = cache._epochs.get("/data/run", 0) + (0 if valid else 1)
        cache._on_finishing_event(producer, {"kind": "cache_saved", "cache_info": {"signature": "s"}})
        assert [r.path for r in fills(service)] == (["/data/run"] if valid else [])
    finally:
        service.shutdown()
