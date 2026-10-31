"""Caching v2's integration check (stage 1, step 7), the ``store_v4`` switch on, in temp stores: one session
as the helpers run it. Load, ``raw_fill``, each raw layer equal to its file (the TXY made from the layer is
the file's byte for byte), Clear, Make room's order (other folders' datasets, then raw layers whose files
are there, then only copies, and exactly what it named), and a cache move with both stores. Through all of
it store-v3 is opened only by ``LegacyStore`` and its files stay as they were (SQLite's ``-wal``/``-shm``
aside). Synthetic data under ``tmp_path`` and the test's own cache folder only."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
import time
import traceback
from typing import Any

import numpy as np
import pytest

from helab import cache_cli
from helab.convert import raw_layer
from helab.convert.pipeline import convert_raw
from helab.convert.profile import MATLAB_2019
from helab.convert.reconstruct import reconstruct
from helab.convert.txy import format_txy
from helab.io_ops import stores
from helab.io_ops.admin import cache_admin
from helab.io_ops.loading import load
from helab.io_ops.raw_fill import raw_fill
from helab.utils import cache_move
from helab.utils.cache_move import COPY
from helab.utils.cache_store import CacheStore
from helab.utils.folder_cache import store_options

from test_store_v4 import files, switch_on, v3_with_state  # noqa: F401  (switch_on: a fixture)

ROOT = Path(__file__).resolve().parents[1]
CASE = (ROOT / "tests" / "data" / "convert" / "cases" / "basic" / "d1.txt").read_bytes()
OLD = 1_700_000_000


def synthetic(shot: int, rows: int) -> bytes:
    """A raw file of ``rows`` pulses at random times (so its layer doesn't compress to nothing)."""
    rng = np.random.default_rng(shot * rows)
    times = 100_000 * shot + np.cumsum(rng.integers(1, 1 << 20, rows))
    channels = rng.integers(1, 9, rows)
    channels[0] = 5
    return "".join(f"{channel},{time}\r\n" for channel, time in zip(channels.tolist(), times.tolist())).encode()


def folder(data: Path, name: str, raw: dict[int, bytes], txy: bool = False) -> Path:
    path = data / name
    path.mkdir(parents=True)
    for shot, text in raw.items():
        (path / f"d{shot}.txt").write_bytes(text)
        if txy:
            converted = convert_raw(text, MATLAB_2019)
            assert converted
            (path / f"d_txy_forc{shot}.txt").write_bytes(converted)
    for file in path.iterdir():
        os.utime(file, (OLD, OLD))
    return path


def loaded(source: Path, tmp_path: Path, options: dict[str, Any], **changes: Any) -> dict[str, Any]:
    output = tmp_path / f"artifacts-{time.monotonic_ns()}"
    output.mkdir()
    sent: list[dict[str, Any]] = []
    load(str(source), str(output), sent.append, {**options, **changes})  # type: ignore[arg-type]
    [answer] = [event for event in sent if event["kind"] in ("cache_saved", "cache_full", "cache_approval")]
    return answer


def filled(source: Path, options: dict[str, Any]) -> dict[str, Any]:
    sent: list[dict[str, Any]] = []
    raw_fill(str(source), options, sent.append)  # type: ignore[arg-type]
    [done] = [event for event in sent if event["kind"] == "raw_fill_done"]
    return done


def opened(options: dict[str, Any], *sources: Path) -> CacheStore:
    return stores._cache_store(options["directory"], [str(source) for source in sources])


def test_a_session_with_store_v4_live_leaves_store_v3_as_it_was(switch_on: None, private_store: str,  # noqa: F811
                                                                tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    options = store_options()
    assert options["directory"] == os.path.join(private_store, "store-v4")  # (The switch, as the app reads it.)
    caches = Path(private_store)
    v3_with_state(caches)  # (An older HeLab's store beside it.)
    v3 = caches / "store-v3"
    before = files(v3)
    v3_opens: list[str] = []
    connect = sqlite3.connect

    def watched(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        if "store-v3" in str(database) and not any(frame.filename.endswith("legacy_store.py")
                                                   for frame in traceback.extract_stack()):
            v3_opens.append(str(database))
        connection: sqlite3.Connection = connect(database, *args, **kwargs)
        return connection
    monkeypatch.setattr(sqlite3, "connect", watched)
    roots: list[str] = []
    init = CacheStore.__init__

    def recorded(self: CacheStore, root: str, **kwargs: Any) -> None:
        roots.append(root)
        init(self, root, **kwargs)
    monkeypatch.setattr(CacheStore, "__init__", recorded)

    data = tmp_path / "data"
    run = folder(data, "run", {1: CASE, 2: CASE, 3: CASE}, txy=True)

    # Load, then raw_fill (as FolderCache queues it after the save).
    assert loaded(run, tmp_path, options)["kind"] == "cache_saved"
    assert filled(run, options)["saved"] == 3 and filled(run, options)["saved"] == 0  # (Once.)

    # Each layer equals its file: the same bytes read, and the TXY made from the layer is the file's.
    with opened(options, run) as store:
        saved = store.raw_rows(str(run)).value or {}
        assert sorted(saved) == [1, 2, 3]
        for shot in saved:
            read = store.read_raw(str(run), shot).value
            assert read is not None
            row, hlb_bytes = read
            text = (run / f"d{shot}.txt").read_bytes()
            assert row.sha256 == hashlib.sha256(text).hexdigest() and row.size == len(text)
            layer, header = raw_layer.from_hlb(hlb_bytes)
            assert header["meta"]["facts"] == raw_layer.encode(text).facts.to_json()
            assert format_txy(reconstruct(raw_layer.decode(layer), MATLAB_2019)) == convert_raw(
                text, MATLAB_2019) == (run / f"d_txy_forc{shot}.txt").read_bytes()

    # Clear (Settings › Cache's Clear all): every kind, raw pulses too.
    sent: list[Any] = []
    cache_admin(options, "clear", sent.append)
    removed = [event for event in sent if event["kind"] == "removed"]
    assert [kind for event in removed for kind in event["kinds"]][-1] == "raw"
    assert next(event for event in removed if "raw" in event["kinds"])["raw"] == 3
    with opened(options, run) as store:
        assert store.raw_rows(str(run)).value == {} and store.read_dataset_row(str(run)).missing

    # Make room's order: X's dataset, Y's raw layers (files there), Z's (the only copy, gone from its folder).
    x = folder(data, "x", {1: CASE}, txy=True)
    assert loaded(x, tmp_path, options)["kind"] == "cache_saved"
    y = folder(data, "y", {1: synthetic(1, 3000), 2: synthetic(2, 3000)})
    z_text = {1: synthetic(1, 20000), 2: synthetic(2, 20000)}  # (Larger than X and Y together.)
    z = folder(data, "z", z_text)
    assert filled(y, options)["saved"] == 2 and filled(z, options)["saved"] == 2
    for shot in z_text:
        (z / f"d{shot}.txt").unlink()
    filled(z, options)  # (Seen gone: the only copy.)
    held = loaded(run, tmp_path, options, budget=1, budget_set_at=time.time())
    assert held["kind"] == "cache_full"
    pending = held["pending_id"]
    with opened(options, run, x, y, z) as store:
        x_row = store.read_dataset_row(str(x)).value
        assert x_row is not None
        x_bytes = x_row["bytes"]
        y_bytes = sum(row.bytes for row in (store.raw_rows(str(y)).value or {}).values())
        z_bytes = sum(row.bytes for row in (store.raw_rows(str(z)).value or {}).values())
        assert z_bytes > x_bytes + y_bytes
        assert store.inventory()["raw"]["only_copy"] == 2
        everything = store.room_plan(pending, 1 << 40)
        assert everything.possible and everything.items == ()  # (Fits: nothing to remove.)
        # Find the budget that needs X's dataset and Y's raw layers, then one that needs part of Z's too.
        enough = next(budget for budget in range(store.usage() + held["bytes"], 0, -512)
                      if store.room_plan(pending, budget).items)
        enough -= x_bytes + y_bytes - 512
        plan = store.room_plan(pending, enough)
        assert plan.items == (str(x), f"raw:{y}")  # (Z's only copy stays, though it alone would do.)
        deeper = store.room_plan(pending, enough - z_bytes // 2)
        assert deeper.items == (str(x), f"raw:{y}", f"raw-only:{z}")
    sent.clear()
    cache_admin({**options, "budget": enough, "budget_set_at": time.time()}, "adopt", sent.append,
                pending_id=pending, make_room=True, room_paths=list(plan.items))
    [result] = [event for event in sent if event["kind"] == "admin_result"]
    assert result["adopted"] is True
    with opened(options, run, x, y, z) as store:
        assert store.read_dataset_row(str(run)).found and store.read_dataset_row(str(x)).missing
        assert store.raw_rows(str(y)).value == {} and sorted(store.raw_rows(str(z)).value or {}) == [1, 2]

    # store-v3 as it was, and opened by nothing but LegacyStore.
    assert files(v3) == before
    assert v3_opens == [] and not any(root.endswith("store-v3") for root in roots)

    # A cache move with both stores: each verified, store-v3's files carried as they were.
    app, target = tmp_path / "app", tmp_path / "moved" / "caches"
    record = cache_move.start(str(caches), str(target), str(app), COPY)
    assert set(record["store_ids"]) == {"store-v4", "store-v3"}
    record = cache_move.move(record, str(app), lambda done, total: None, lambda: False)
    assert cache_move.verify(str(target), record["store_id"], record["store_ids"]) == ""
    assert files(target / "store-v3") == before == files(v3)
    assert v3_opens == [] and not any(root.endswith("store-v3") for root in roots)

    # The moved store's only copy still exports (read only) to what Z's raw files held.
    out = tmp_path / "exported"
    assert cache_cli.main(["export", "--folder", str(z), "--cache", str(target), "--out", str(out)]) == 0
    for shot, text in z_text.items():
        with np.load(out / f"d{shot}.npz") as exported:
            assert np.array_equal(exported["time_bins"], raw_layer.columns(raw_layer.encode(text))["time_bins"])
