"""Caching v2's store-v4 core behind its switch (stage 1, step 4): with the switch off nothing changes
and no store-v4 is made; with it on, store-v4 is the live store with every store-v3 table, ``makers``
and ``raw_layers``; store-v3 is opened only by ``LegacyStore`` (read only), for the one-time import
of the user's state and Keep's read-through; per-kind epochs (cache-2); a newer format is read only;
cache moves verify both stores. Temp stores only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import traceback
from typing import Any, Callable, Iterator

import pytest

from helab.io_ops.admin import cache_admin
from helab.utils import cache_move, cache_store, legacy_store, store_v4
from helab.utils.cache_move import COPY, RENAME
from helab.utils.cache_store import CacheStore, DatasetRecord, SaveRejected, StoreReadOnly
from helab.utils.legacy_store import LegacyStore, LegacyUnavailable

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
RUN = f"root://{A}/run"
OTHER = f"root://{A}/other"
FLAGGED = f"root://{A}/flagged"  # (The user's flags and constants are set on it.)
RECORD: DatasetRecord = {"ram_bytes": 1, "rows": 1, "shots": 1, "fingerprint": [], "problematic": [], "info": {}}


@pytest.fixture
def switch_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The ``store_v4`` row on in this test's own settings, read again by ``store_root``."""
    from helab.utils.settings_store import app_settings
    settings = app_settings()
    settings.setValue("store_v4", True)
    settings.sync()
    before = os.environ.pop(store_v4.MAKER_ENV, None)
    cache_store._reset_live_layout()
    yield
    cache_store._reset_live_layout()
    os.environ.pop(store_v4.MAKER_ENV, None)
    if before is not None:
        os.environ[store_v4.MAKER_ENV] = before


def save(store: CacheStore, path: str = RUN, data: bytes = b"data") -> None:
    store.save_dataset(path, store.write_dataset_file(data), RECORD, store.start_dataset_job(path))


def save_result(store: CacheStore, path: str = RUN, lookup: str = "k1", family: str = "f1",
                computed_at: float = 1.0) -> None:
    file = store.write_result_file(b"result " + lookup.encode())
    store.save_result(path, lookup, family, {"r": lookup}, file, store.start_result_job(path), analysis_id="a",
                      action="Plot", computed_at=computed_at)


def v3_with_state(caches: Path) -> str:
    """A store-v3 as an older HeLab left it: the user's own state, records, a dataset, a result."""
    with CacheStore(str(caches / "store-v3")) as store:
        store.set_prefs(FLAGGED, True, False, 10.0)
        store.set_convert_prefs(FLAGGED, True, 11.0)
        store.set_constants(FLAGGED, {"fall_distance": 0.85}, 12.0)
        store.write_presets([{"kind": "script", "scope": "s", "name": "kept", "record": "{}", "set_at": 13.0},
                             {"kind": "script", "scope": "s", "name": "deleted", "record": None, "set_at": 14.0}])
        store.record_root(f"vol://v/{A}", A, "volume", "data", decision="confirmed")
        store.record_volume("/Volumes/data", "/dev/disk9", "v")
        store.record_mount_hint("/Volumes/data", "vol://v")
        save(store, OTHER)
        store.save_dataset(RUN, store.write_dataset_file(b"v3 data"), RECORD, store.start_dataset_job(RUN),
                           budget=5 << 30, budget_set_at=15.0)
        store.save_record("summaries", RUN, {"version": 1, "from": "v3"}, store.guard([RUN], ("summaries",)))
        save_result(store, RUN, "k1", computed_at=1.0)
        save_result(store, RUN, "old", computed_at=0.5)
        return store.store_id


def files(folder: Path) -> dict[str, str]:
    """Every file under ``folder`` with its SHA-256, SQLite's own ``-wal``/``-shm`` left out."""
    return {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob("*")) if path.is_file() and not path.name.endswith(("-wal", "-shm"))}


def rows(store: CacheStore, sql: str, args: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    return [tuple(row) for row in store._conn.execute(sql, args)]


# The switch (Q28.3)

def test_with_the_switch_off_store_v3_is_live_and_no_store_v4_is_ever_made(private_store: str) -> None:
    from helab.utils.folder_cache import store_options
    cache_store._reset_live_layout()
    try:
        assert store_options()["directory"] == os.path.join(private_store, "store-v3")
        assert cache_store.store_root(private_store).endswith("store-v3")
        for action in ("inventory", "sweep", "presets"):
            cache_admin(store_options(), action, lambda event: None, **({"rows": []} if action == "presets" else {}))
        with CacheStore(cache_store.store_root(private_store)) as store:
            save(store)
            save_result(store)
            store.remove(("summaries",), [RUN])
        assert not os.path.exists(os.path.join(private_store, "store-v4"))
        assert store_v4.MAKER_ENV not in os.environ or json.loads(os.environ[store_v4.MAKER_ENV])  # (Not made here.)
    finally:
        cache_store._reset_live_layout()


def test_the_switch_on_makes_store_v4_the_live_store(switch_on: None, private_store: str) -> None:
    from helab.utils.folder_cache import store_options
    options = store_options()
    assert options["directory"] == os.path.join(private_store, "store-v4")
    maker = json.loads(os.environ[store_v4.MAKER_ENV])  # (For the helpers this process starts.)
    assert len(maker["maker"]) == 32 and maker["record"]["hostname"]
    events: list[Any] = []
    cache_admin(options, "inventory", events.append)
    with CacheStore(options["directory"]) as store:
        assert store.layout == 4 and store.layout_version == 4
    assert os.path.isdir(os.path.join(private_store, "store-v4", "raw"))


@pytest.mark.no_auto_data_root
def test_a_new_store_v4_has_every_store_v3_table_and_its_own(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store-v3")) as v3, CacheStore(str(tmp_path / "store-v4")) as v4:
        tables = {name for (name,) in rows(v3, "SELECT name FROM sqlite_master WHERE type = 'table'")}
        tables4 = {name for (name,) in rows(v4, "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert tables4 == tables | {"makers", "raw_layers"} and "datasets" in tables4  # (T~3: datasets carried.)
        meta = v4._meta()
        assert meta["layout_version"] == 4 and meta["format"] == store_v4.FORMAT == 1 and meta["gen_raw"] == 0
        assert v3._meta()["layout_version"] == 3 and "format" not in v3._meta()
        assert v3.store_id != v4.store_id and v4.layout == 4 and v3.layout == 3
        for table in ("datasets", "results"):
            assert "maker" in {row[1] for row in rows(v4, f"PRAGMA table_info({table})")}
            assert "maker" not in {row[1] for row in rows(v3, f"PRAGMA table_info({table})")}


@pytest.mark.no_auto_data_root
def test_store_v4s_rows_keep_their_makers_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(store_v4.MAKER_ENV, raising=False)
    monkeypatch.setenv("HELAB_APP_DIR_OVERRIDE", str(tmp_path / "app"))
    with CacheStore(str(tmp_path / "store-v4")) as store:
        save(store)
        save_result(store)
        [(maker, started, record)] = rows(store, "SELECT maker, started_at, record FROM makers")
        assert rows(store, "SELECT maker FROM datasets") == [(maker,)] == rows(store, "SELECT maker FROM results")
        made = json.loads(record)
        assert made["machine"] == store_v4.machine_id() and len(made["machine"]) == 32
        assert {"helab_version", "commit", "modified", "hostname", "python", "numpy", "scipy", "blosc"} <= set(made)
        assert json.loads(os.environ[store_v4.MAKER_ENV])["maker"] == maker and started <= time.time()
    # Another process of the same session (a helper) inherits it: one row, the same id.
    with CacheStore(str(tmp_path / "store-v4"), maker=json.loads(os.environ[store_v4.MAKER_ENV])) as store:
        save(store, OTHER)
        assert len(rows(store, "SELECT maker FROM makers")) == 1
        assert rows(store, "SELECT maker FROM datasets WHERE path = ?", (OTHER,)) == [(maker,)]
    assert (tmp_path / "app" / store_v4.MACHINE_FILE).read_text().strip() == made["machine"]


# store-v3: LegacyStore, the import (Q22.4) and Keep (Q22.3)

@pytest.mark.no_auto_data_root
def test_the_users_state_is_imported_once_and_store_v3_is_left_as_it_was(tmp_path: Path) -> None:
    caches = tmp_path / "caches"
    v3_id = v3_with_state(caches)
    before = files(caches / "store-v3")
    with CacheStore(str(caches / "store-v4")) as v4:
        assert v4.read_prefs([FLAGGED])[FLAGGED].value == {"no_cache": True, "no_auto_load": False, "set_at": 10.0}
        assert v4.read_convert_prefs([FLAGGED])[FLAGGED].value == {"write_beside": True, "set_at": 11.0}
        assert v4.read_constants([FLAGGED])[FLAGGED].value == {"values": {"fall_distance": 0.85}, "set_at": 12.0}
        presets = v4.read_presets().value or []
        assert {(row["name"], row["record"]) for row in presets} == {("kept", "{}"), ("deleted", None)}
        assert [row[:2] for row in v4.root_locations()] == [(f"vol://v/{A}", A)]
        assert v4.volume_locations() == [("/Volumes/data", "/dev/disk9", "v")]
        assert v4.mount_hints() == {"/Volumes/data": "vol://v"}
        assert v4._meta()["budget"] == {"bytes": 5 << 30, "set_at": 15.0}
        imported = v4._meta()["imported_v3"]
        assert imported["v3_store_id"] == v3_id and imported["rows"]["presets"] == 2
        assert rows(v4, "SELECT COUNT(*) FROM datasets") == [(0,)]  # (Cache isn't imported: only the user's state.)
    # Once: a later change in v3 (an older HeLab) isn't imported again.
    with CacheStore(str(caches / "store-v3")) as v3:
        v3.set_prefs(OTHER, True, True, 20.0)
    before = files(caches / "store-v3")
    with CacheStore(str(caches / "store-v4")) as v4:
        assert v4.read_prefs([OTHER])[OTHER].missing
    assert files(caches / "store-v3") == before


@pytest.mark.no_auto_data_root
def test_a_store_v3_that_cant_be_read_is_imported_at_a_later_open(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    caches = tmp_path / "caches"
    v3_with_state(caches)

    def unreadable(self: LegacyStore, root: str) -> None:
        raise LegacyUnavailable("busy")
    monkeypatch.setattr(LegacyStore, "__init__", unreadable)
    with CacheStore(str(caches / "store-v4")) as v4:
        assert "imported_v3" not in v4._meta() and v4.read_prefs([FLAGGED])[FLAGGED].missing
    monkeypatch.undo()
    with CacheStore(str(caches / "store-v4")) as v4:
        assert v4.read_prefs([FLAGGED])[FLAGGED].found and "imported_v3" in v4._meta()


@pytest.mark.no_auto_data_root
def test_without_a_store_v3_nothing_is_imported_and_a_later_one_isnt(tmp_path: Path) -> None:
    caches = tmp_path / "caches"
    with CacheStore(str(caches / "store-v4")) as v4:
        assert v4._meta()["imported_v3"]["v3_store_id"] is None
    v3_with_state(caches)
    with CacheStore(str(caches / "store-v4")) as v4:
        assert v4.read_prefs([FLAGGED])[FLAGGED].missing


@pytest.mark.no_auto_data_root
def test_keep_reads_records_and_results_through_from_store_v3(tmp_path: Path) -> None:
    caches = tmp_path / "caches"
    v3_with_state(caches)
    before = files(caches / "store-v3")
    with CacheStore(str(caches / "store-v4")) as v4:
        assert store_v4.legacy_choice(v4._meta()) is None  # (Not answered: Keep.)
        assert v4.read_record("summaries", RUN).value == {"version": 1, "from": "v3"}
        assert v4.read_record("summaries", OTHER).missing
        exact = v4.find_result(RUN, "k1", "f1").value
        assert exact is not None and exact.legacy and exact.exact and exact.data == b"result k1"
        outdated = v4.find_result(RUN, "k2", "f1").value
        assert outdated is not None and outdated.legacy and not outdated.exact and outdated.row["lookup"] == "k1"
        assert v4.result_counts([RUN])[RUN].count == 2
        # store-v4's own come first: an exact match here, and an outdated one here before v3's exact one.
        v4.save_record("summaries", RUN, {"version": 1, "from": "v4"}, v4.guard([RUN], ("summaries",)))
        save_result(v4, RUN, "k1", computed_at=2.0)
        save_result(v4, RUN, "k3", computed_at=3.0)
        assert v4.read_record("summaries", RUN).value == {"version": 1, "from": "v4"}
        mine = v4.find_result(RUN, "k1", "f1").value
        assert mine is not None and not mine.legacy and mine.exact and mine.row["computed_at"] == 2.0
        old = v4.find_result(RUN, "old", "f1").value
        assert old is not None and old.legacy and old.exact  # (Exact in v3 beats outdated in v4.)
        assert v4.result_counts([RUN])[RUN].count == 3  # (v4's k1 and k3, and v3's old: C2-4.)
    assert files(caches / "store-v3") == before


@pytest.mark.no_auto_data_root
@pytest.mark.parametrize("choice", ["ignore", "clear"])
def test_after_ignore_or_clear_store_v3_is_never_opened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                         choice: str) -> None:
    caches = tmp_path / "caches"
    v3_with_state(caches)
    with CacheStore(str(caches / "store-v4")) as v4:
        with v4.transaction():
            v4._conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('legacy_v3', ?)",
                             (json.dumps({"choice": choice, "v3_store_id": "x", "set_at": 1.0}),))
    opened: list[str] = []
    real = LegacyStore.__init__

    def counted(self: LegacyStore, root: str) -> None:
        opened.append(root)
        real(self, root)
    monkeypatch.setattr(LegacyStore, "__init__", counted)
    with CacheStore(str(caches / "store-v4")) as v4:
        assert v4.read_record("summaries", RUN).missing and v4.find_result(RUN, "k1", "f1").missing
        assert v4.result_counts([RUN])[RUN].count == 0
    assert opened == []


@pytest.mark.no_auto_data_root
def test_only_legacy_store_ever_opens_store_v3_once_store_v4_is_live(tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """Readiness §4: a session with store-v4 live (opens, saves, results, records, Make room, removals,
    the sweep, inventory, a cache move) opens store-v3's database only through ``LegacyStore``, and
    leaves its files as they were."""
    caches = tmp_path / "caches"
    v3_with_state(caches)
    v3 = caches / "store-v3"
    before = files(v3)
    opens: list[str] = []
    connect = sqlite3.connect

    def watched(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        name = str(database)
        if "store-v3" in name and not any(frame.filename.endswith("legacy_store.py")
                                          for frame in traceback.extract_stack()):
            opens.append(name)
        opened: sqlite3.Connection = connect(database, *args, **kwargs)
        return opened
    monkeypatch.setattr(sqlite3, "connect", watched)
    stores_opened: list[str] = []
    init = CacheStore.__init__

    def recorded(self: CacheStore, root: str, **kwargs: Any) -> None:
        stores_opened.append(root)
        init(self, root, **kwargs)
    monkeypatch.setattr(CacheStore, "__init__", recorded)
    directory = str(caches / "store-v4")
    options: dict[str, Any] = {"directory": directory, "budget": 8 << 30, "budget_set_at": 1.0}
    for action in ("inventory", "sweep"):
        cache_admin(options, action, lambda event: None)
    with CacheStore(directory) as v4:
        save(v4)
        save_result(v4)
        v4.read_records("summaries", [RUN, OTHER])
        v4.find_result(RUN, "old", "f1")
        v4.result_counts([RUN, OTHER])
        v4.purge_records(time.time() + 10)
        v4.remove(cache_store.KINDS, [RUN])
        v4.sweep(time.time() + 10 ** 6)
    app, target = tmp_path / "app", tmp_path / "moved" / "caches"
    record = cache_move.start(str(caches), str(target), str(app), COPY)
    record = cache_move.move(record, str(app), lambda done, total: None, lambda: False)
    assert opens == [] and all(not root.endswith("store-v3") for root in stores_opened)
    assert files(v3) == before == files(target / "store-v3")


@pytest.mark.no_auto_data_root
def test_legacy_store_reads_a_store_v3_closed_cleanly_and_never_writes_it(tmp_path: Path) -> None:
    caches = tmp_path / "caches"
    v3_id = v3_with_state(caches)
    root = caches / "store-v3"
    assert not (root / "records.sqlite-wal").exists()  # (Closed cleanly: no -wal, no -shm.)
    database = (root / "records.sqlite").read_bytes()
    with LegacyStore(str(root)) as legacy:
        assert legacy.store_id == v3_id and legacy.integrity_ok() and legacy.live_bytes() > 0
        assert legacy.records("folder_summaries", [RUN])
        assert legacy.result_counts([RUN]) == {RUN: (2, len(b"result k1") + len(b"result old"))}
        with pytest.raises(sqlite3.OperationalError):
            legacy._conn.execute("DELETE FROM folder_prefs")
        assert legacy.columns("no_such_table") == [] and legacy.rows("no_such_table", ("a",)) == []
    assert (root / "records.sqlite").read_bytes() == database
    with pytest.raises(LegacyUnavailable):
        LegacyStore(str(tmp_path / "none"))
    with CacheStore(str(caches / "store-v4")) as v4:  # (Not a v3: refused.)
        pass
    with pytest.raises(LegacyUnavailable, match="layout 4"):
        LegacyStore(str(caches / "store-v4"))
    assert legacy_store.legacy_root(str(caches / "store-v4")) == str(root)


# Formats and migrations

@pytest.mark.no_auto_data_root
def test_a_store_v4_of_a_newer_format_is_read_never_rewritten(tmp_path: Path) -> None:
    root = tmp_path / "store-v4"
    with CacheStore(str(root)) as store:
        save(store)
        with store.transaction():
            store._conn.execute("UPDATE meta SET value = '2' WHERE key = 'format'")
    with CacheStore(str(root)) as store:
        assert store.read_only and store.read_dataset_row(RUN).found
        with pytest.raises(StoreReadOnly):
            save(store, OTHER)


@pytest.mark.no_auto_data_root
def test_tables_added_within_layout_4_are_migrated_on_every_writable_open(tmp_path: Path,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[sqlite3.Connection] = []
    monkeypatch.setattr(store_v4, "migrate", calls.append)
    with CacheStore(str(tmp_path / "store-v4")):
        pass
    with CacheStore(str(tmp_path / "store-v4")):
        pass
    with CacheStore(str(tmp_path / "store-v3")):
        pass
    assert len(calls) == 2  # (Each writable open of v4; never v3.)
    monkeypatch.undo()
    with CacheStore(str(tmp_path / "store-v4")) as store:  # (None to add yet: nothing changes.)
        assert store.layout == 4


# Per-kind epochs (cache-2)

@pytest.mark.no_auto_data_root
@pytest.mark.parametrize("layout", [3, 4])
def test_a_records_purge_fences_a_waiting_dataset_save_only_in_store_v3(tmp_path: Path, layout: int) -> None:
    """cache-2's scenario: a folder's old records are purged while its dataset save waits for Make room."""
    with CacheStore(str(tmp_path / f"store-v{layout}")) as store:
        store.save_record("summaries", RUN, {"version": 1}, store.guard([RUN], ("summaries",)),
                          saved_at=time.time() - 40 * 86400)
        guard = store.start_dataset_job(RUN)
        pending = store.add_pending(RUN, store.write_dataset_file(b"data"), RECORD, guard, "over_budget")
        store.purge_records(time.time() - 30 * 86400)
        if layout == 3:
            with pytest.raises(SaveRejected, match="cleared"):
                store.adopt_pending(pending, budget=10 ** 12, budget_set_at=1.0)
        else:
            assert store.adopt_pending(pending, budget=10 ** 12, budget_set_at=1.0).adopted
            assert store.read_dataset_row(RUN).found


@pytest.mark.no_auto_data_root
def test_in_store_v4_a_kinds_removal_still_fences_that_kinds_saves_and_datasets_their_own(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store-v4")) as store:
        records = store.guard([RUN], ("summaries", "listings"))
        dataset = store.start_dataset_job(RUN)
        store.remove(("summaries",), [RUN])
        with pytest.raises(SaveRejected, match="cleared"):
            store.save_record("summaries", RUN, {"version": 1}, records)
        store.save_record("listings", RUN, {"version": 1, "listed_at": 1.0}, records)  # (Another kind: saved.)
        save_dataset = store.write_dataset_file(b"data")
        store.save_dataset(RUN, save_dataset, RECORD, dataset)  # (A records removal: the dataset still saves.)
        later = store.start_dataset_job(RUN)
        store.remove(("datasets",), [RUN])
        with pytest.raises(SaveRejected, match="cleared"):
            store.save_dataset(RUN, store.write_dataset_file(b"again"), RECORD, later)
        store.save_record("listings", RUN, {"version": 1, "listed_at": 2.0}, records)  # (Datasets: not records.)
        assert {key for (key,) in rows(store, "SELECT path FROM folder_epochs")} >= {RUN, f"summaries:{RUN}"}


# Cache moves with both stores (gap 6)

@pytest.mark.no_auto_data_root
@pytest.mark.parametrize("method", [RENAME, COPY])
def test_a_cache_folder_with_both_stores_moves_and_each_is_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                    method: str) -> None:
    caches, app, target = tmp_path / "caches", tmp_path / "app", tmp_path / "moved" / "caches"
    v3_id = v3_with_state(caches)
    with CacheStore(str(caches / "store-v4")) as v4:
        save(v4)
        v4_id = v4.store_id
    before = files(caches / "store-v3")
    assert cache_move.store_ids_at(str(caches)) == {"store-v4": v4_id, "store-v3": v3_id}
    assert cache_move.store_id_at(str(caches)) == v4_id  # (The primary store: the newest layout.)
    monkeypatch.setattr(cache_move, "same_disk", lambda source, target: method == RENAME)
    record = cache_move.start(str(caches), str(target), str(app), method)
    assert record["store_ids"] == {"store-v4": v4_id, "store-v3": v3_id}
    record = cache_move.move(record, str(app), lambda done, total: None, lambda: False)
    assert cache_move.verify(str(target), v4_id, record["store_ids"]) == ""
    assert files(target / "store-v3") == before
    with CacheStore(str(target / "store-v4")) as v4:
        assert v4.read_dataset_row(RUN).found


@pytest.mark.no_auto_data_root
@pytest.mark.parametrize("damage", ["v3 file", "v3 missing", "v4 file"])
def test_a_copy_with_either_store_damaged_fails_verification(tmp_path: Path, damage: str) -> None:
    caches = tmp_path / "caches"
    v3_with_state(caches)
    with CacheStore(str(caches / "store-v4")) as v4:
        save(v4, data=b"v4 data")
        v4_id = v4.store_id
    ids = cache_move.store_ids_at(str(caches))
    spoil: dict[str, Callable[[], object]] = {
        "v3 file": lambda: next((caches / "store-v3" / "datasets").iterdir()).write_bytes(b"x"),
        "v3 missing": lambda: os.rename(caches / "store-v3", tmp_path / "gone"),
        "v4 file": lambda: next((caches / "store-v4" / "datasets").iterdir()).write_bytes(b"x")}
    spoil[damage]()
    assert cache_move.verify(str(caches), v4_id, ids) != ""


@pytest.mark.no_auto_data_root
def test_the_inventory_measures_store_v3_kept_and_only_its_files_after_ignore(tmp_path: Path,
                                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """Gap 8: under Keep, v3's live bytes (through LegacyStore) go into ``meta.legacy_bytes`` with its
    write count; after Ignore, v3 isn't opened and its folder's size on disk is shown."""
    caches = tmp_path / "caches"
    v3_id = v3_with_state(caches)
    with LegacyStore(str(caches / "store-v3")) as legacy:
        live, writes = legacy.live_bytes(), legacy.writes()
    with CacheStore(str(caches / "store-v4")) as v4:
        kept = v4.inventory()["legacy"]
        assert kept == {"present": True, "choice": None, "bytes": live, "store_id": v3_id, "counted": True}
        recorded = v4._meta()["legacy_bytes"]
        assert (recorded["bytes"], recorded["writes"], recorded["v3_store_id"]) == (live, writes, v3_id)
        with v4.transaction():
            v4._conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('legacy_v3', ?)",
                             (json.dumps({"choice": "ignore", "v3_store_id": v3_id, "set_at": 1.0}),))
    monkeypatch.setattr(LegacyStore, "__init__", lambda self, root: pytest.fail("store-v3 opened after Ignore"))
    with CacheStore(str(caches / "store-v4")) as v4:
        ignored = v4.inventory()["legacy"]
    on_disk = sum(path.stat().st_size for path in (caches / "store-v3").rglob("*") if path.is_file())
    assert ignored == {"present": True, "choice": "ignore", "bytes": on_disk, "counted": False}
    with CacheStore(str(tmp_path / "alone" / "store-v4")) as v4:
        assert v4.inventory()["legacy"] == {"present": False, "choice": None, "bytes": 0}
    with CacheStore(str(tmp_path / "alone" / "store-v3")) as v3:
        assert "legacy" not in v3.inventory()


@pytest.mark.parametrize("contents", [b"abc123\n", b"A" * 32 + b"\n", b"", b"\x00\xff"])
def test_an_invalid_machine_id_file_is_replaced_never_recursed_on(tmp_path: Path, contents: bytes) -> None:
    """C2-3 (Assay): anything but 32 lowercase hex digits (a cut write, another format) is replaced by a
    new id, once; the same id comes back afterwards."""
    app = tmp_path / "app"
    app.mkdir()
    (app / store_v4.MACHINE_FILE).write_bytes(contents)
    made = store_v4.machine_id(str(app))
    assert len(made) == 32 and all(c in "0123456789abcdef" for c in made)
    assert (app / store_v4.MACHINE_FILE).read_text().strip() == made == store_v4.machine_id(str(app))


@pytest.mark.no_auto_data_root
@pytest.mark.parametrize("removal", ["folder's records", "every summary", "the root's cached data", "a None save",
                                     "a purge by age", "the folder's results", "every result", "the root's analysis",
                                     "a results purge by age"])
def test_keep_never_brings_back_what_store_v4_removed(tmp_path: Path, removal: str) -> None:
    """C2-1 (Assay): once store-v4 has removed a kind for a key (its generation, the key's epoch, its root's,
    a None save, a purge by age), store-v3's row for it isn't read through any more."""
    caches = tmp_path / "caches"
    v3_with_state(caches)
    with CacheStore(str(caches / "store-v4")) as v4:
        assert v4.read_record("summaries", RUN).found and v4.find_result(RUN, "k1", "f1").found
        records = removal in ("folder's records", "every summary", "the root's cached data", "a None save",
                              "a purge by age")
        if removal == "folder's records":
            v4.remove(("summaries",), [RUN])
        elif removal == "every summary":
            v4.remove(("summaries",))
        elif removal == "the root's cached data":
            v4.clear_root(A)
        elif removal == "a None save":
            v4.save_record("summaries", RUN, None, v4.guard([RUN], ("summaries",)))
        elif removal == "a purge by age":
            v4.purge_records(time.time() + 60)
        elif removal == "the folder's results":
            v4.remove_results([RUN])
        elif removal == "every result":
            v4.remove_results()
        elif removal == "the root's analysis":
            v4.remove_results(root=A)
        else:
            v4.remove_results(cutoff=time.time() + 60)
        if records:
            assert v4.read_record("summaries", RUN).missing
            assert v4.find_result(RUN, "k1", "f1").found  # (Results are another kind.)
        else:
            assert v4.find_result(RUN, "k1", "f1").missing and v4.find_result(RUN, "x", "f1").missing
            assert v4.result_counts([RUN])[RUN].count == 0
            assert v4.read_record("summaries", RUN).found


@pytest.mark.no_auto_data_root
def test_keep_counts_a_v3_result_once_and_not_when_store_v4_has_its_lookup(tmp_path: Path) -> None:
    """C2-4 (Assay): the folder's count is what can be found: v4's rows, and v3's of lookups v4 lacks."""
    caches = tmp_path / "caches"
    v3_with_state(caches)
    with CacheStore(str(caches / "store-v4")) as v4:
        assert v4.result_counts([RUN])[RUN].count == 2
        save_result(v4, RUN, "k1", computed_at=2.0)  # (Shadows v3's k1.)
        count = v4.result_counts([RUN])[RUN]
        assert count.count == 2 and count.bytes == len(b"result k1") + len(b"result old")


@pytest.mark.no_auto_data_root
def test_a_root_forgotten_before_a_retried_import_isnt_brought_back(tmp_path: Path,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """C2-5 (Assay): store-v3 couldn't be read when store-v4 was made; meanwhile the user forgot a data root
    in v4 (Settings › Data roots › Forget); the later import doesn't bring v3's record of it back."""
    caches = tmp_path / "caches"
    v3_with_state(caches)
    location = f"vol://v/{A}"

    def unreadable(self: LegacyStore, root: str) -> None:
        raise LegacyUnavailable("busy")
    monkeypatch.setattr(LegacyStore, "__init__", unreadable)
    with CacheStore(str(caches / "store-v4")) as v4:
        v4.record_root(location, A, "volume", "data", decision="confirmed")  # (Found again by discovery.)
        v4.forget_root(location)
    monkeypatch.undo()
    with CacheStore(str(caches / "store-v4")) as v4:
        assert "imported_v3" in v4._meta() and v4.read_prefs([FLAGGED])[FLAGGED].found  # (The rest came.)
        assert v4.root_at(location) is None


@pytest.mark.no_auto_data_root
@pytest.mark.parametrize("method", [RENAME, COPY])
def test_with_the_switch_off_a_leftover_store_v4_is_only_a_passenger_in_a_move(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    """C2-6 (Assay): told the live layout (3), a move keys on store-v3, checkpoints it as today, and carries
    a developer's leftover store-v4 along, verified; recovery follows store-v3's id."""
    caches, app, target = tmp_path / "caches", tmp_path / "app", tmp_path / "moved" / "caches"
    v3_id = v3_with_state(caches)
    with CacheStore(str(caches / "store-v4")) as v4:
        save(v4)
        v4_id = v4.store_id
    monkeypatch.setattr(cache_move, "same_disk", lambda source, target: method == RENAME)
    record = cache_move.start(str(caches), str(target), str(app), method, layout=3)
    assert record["store_id"] == v3_id and record["primary"] == "store-v3"
    assert record["store_ids"] == {"store-v4": v4_id, "store-v3": v3_id}
    record = cache_move.move(record, str(app), lambda done, total: None, lambda: False)
    assert cache_move.valid_at(str(target), v3_id, record["primary"])
    assert not cache_move.valid_at(str(target), v3_id)  # (Without it, the newest store is the primary.)
    # (A copy keeps its source until the cleanup after the cutover; a rename moved it.)
    assert cache_move.store_at(record) == (str(target) if method == RENAME else str(caches))


@pytest.mark.no_auto_data_root
def test_a_later_purge_keeping_failures_doesnt_bring_back_a_v3_history_an_earlier_one_hid(tmp_path: Path) -> None:
    """C2-7 (Assay): purges by age keep two cutoffs per kind, the latest and the latest that took failures."""
    caches = tmp_path / "caches"
    v3_with_state(caches)
    history = {"version": 1, "failures": [{"x": 1}], "starts": {}, "sequence": 1, "blocked": True}
    with CacheStore(str(caches / "store-v3")) as v3:
        v3.save_record("histories", OTHER, history, v3.guard([OTHER], ("histories",)), saved_at=50.0)
        v3.save_record("histories", FLAGGED, history, v3.guard([FLAGGED], ("histories",)), saved_at=150.0)
    with CacheStore(str(caches / "store-v4")) as v4:
        assert v4.read_record("histories", OTHER).found
        v4.purge_records(100.0, include_failures=True)
        assert v4.read_record("histories", OTHER).missing and v4.read_record("histories", FLAGGED).found
        v4.purge_records(200.0)  # (Keeps failures.)
        assert v4.read_record("histories", OTHER).missing  # (Hidden by the first: stays hidden.)
        assert v4.read_record("histories", FLAGGED).found  # (Failures, after the first purge: kept.)
