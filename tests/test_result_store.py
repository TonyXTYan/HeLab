"""The result cache's tables in ``store-v3`` (result caching R2): a new store has them, and an
older ``store-v3`` gains them on its next writable open (``cache_store._migrate``), once even
when several helpers open it at once; a read-only store without them is left as it is. Result
files and rows count toward the one disk budget."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid

import pytest

from helab.utils import cache_store
from helab.utils.cache_store import CacheStore

pytestmark = pytest.mark.no_auto_data_root

# The store's schema at c3d4b50, the base of result caching R2: everything but ``results``.
BASE_SCHEMA = cache_store.SCHEMA.split("CREATE TABLE IF NOT EXISTS results")[0] + cache_store.ROOT_SCHEMA
A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def base_store(directory: Path, *, layout: int = cache_store.LAYOUT_VERSION) -> Path:
    """A store as c3d4b50 made it (``layout``: as a newer HeLab's would read, for read-only opens)."""
    (directory / "datasets").mkdir(parents=True)
    conn = sqlite3.connect(directory / "records.sqlite", isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("BEGIN IMMEDIATE")
        for statement in BASE_SCHEMA.split(";"):
            if statement.strip():
                conn.execute(statement)
        meta: dict[str, object] = {"layout_version": layout, "store_id": uuid.uuid4().hex, "created_at": time.time(),
                                   **{f"gen_{kind}": 0 for kind in cache_store.KINDS}}
        conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)",
                         [(key, json.dumps(value)) for key, value in meta.items()])
        conn.execute("COMMIT")
    finally:
        conn.close()
    return directory


def tables(directory: Path) -> set[str]:
    with sqlite3.connect(directory / "records.sqlite") as conn:
        return {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")}


def meta(directory: Path) -> dict[str, str]:
    with sqlite3.connect(directory / "records.sqlite") as conn:
        return {str(key): str(value) for key, value in conn.execute("SELECT key, value FROM meta")}


RESULT_TABLES = {"results", "results_family", "results_last_used"}


def insert_result(store: CacheStore, path: str, record: str = "{}", size: int = 0) -> None:
    with store.transaction():
        store._conn.execute(
            "INSERT INTO results (result_id, path, lookup, family, analysis_id, action, record, file, bytes, "
            "computed_at, saved_at, last_used) VALUES (?, ?, ?, 'f', 'a', 'Plot', ?, 'x.npz', ?, 1, 1, 1)",
            (uuid.uuid4().hex, path, uuid.uuid4().hex, record, size))


def test_a_new_store_has_the_result_tables(tmp_path: Path) -> None:
    directory = tmp_path / "store"
    with CacheStore(str(directory)) as store:
        assert store._results_table
        assert os.path.isdir(store.results_dir)
    assert RESULT_TABLES <= tables(directory)
    assert meta(directory)["gen_results"] == "0"


def test_an_older_store_v3_gains_the_result_tables_when_opened(tmp_path: Path) -> None:
    directory = base_store(tmp_path / "store")
    assert not RESULT_TABLES & tables(directory)
    with CacheStore(str(directory)) as store:
        assert store._results_table and os.path.isdir(store.results_dir)
        insert_result(store, f"root://{A}/run")
    assert RESULT_TABLES <= tables(directory)
    assert meta(directory)["gen_results"] == "0"
    with CacheStore(str(directory)) as store:  # Opened again: nothing left to do, the row stays.
        assert store._conn.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 1


def test_a_store_with_the_table_but_no_generation_gains_it(tmp_path: Path) -> None:
    directory = base_store(tmp_path / "store")
    with sqlite3.connect(directory / "records.sqlite") as conn:
        conn.execute(cache_store.RESULT_SCHEMA[0])
    with CacheStore(str(directory)):
        pass
    assert meta(directory)["gen_results"] == "0" and RESULT_TABLES <= tables(directory)


def test_concurrent_helpers_add_the_result_tables_once(tmp_path: Path) -> None:
    directory = base_store(tmp_path / "store")
    code = ("import sys\nfrom helab.utils.cache_store import CacheStore\n"
            "with CacheStore(sys.argv[1]) as store:\n"
            "    assert store._results_table\n")
    helpers = [subprocess.Popen([sys.executable, "-c", code, str(directory)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(6)]
    results = [helper.communicate(timeout=60) + (helper.returncode,) for helper in helpers]
    assert all(returncode == 0 for _, _, returncode in results), [err for _, err, _ in results]
    assert RESULT_TABLES <= tables(directory) and meta(directory)["gen_results"] == "0"


def test_a_read_only_store_without_them_is_left_as_it_is(tmp_path: Path) -> None:
    directory = base_store(tmp_path / "store", layout=cache_store.LAYOUT_VERSION + 1)
    with CacheStore(str(directory)) as store:
        assert store.read_only and not store._results_table
        assert store.usage() >= 0  # (Usage leaves the missing table out.)
    assert not RESULT_TABLES & tables(directory)
    assert not (directory / cache_store.RESULTS_DIRNAME).exists()


def test_results_count_toward_the_disk_budget(tmp_path: Path) -> None:
    """One budget for datasets and results (Tony, 2026-10-22): a result's file and row add to the
    live usage the budget and its 80 % rules see."""
    with CacheStore(str(tmp_path / "store")) as store:
        before = store.usage()
        for index in range(200):
            insert_result(store, f"root://{A}/run{index}", json.dumps({"lines": ["x" * 400] * 4}), size=1000)
        with store.transaction(write=False):
            results = store._results_live()
        assert results >= 200 * (1000 + 1600)
        assert store.usage() - before >= 200 * (1000 + 1600)
        # The rows' estimate is about what they take in the database.
        assert abs(store.usage() - before - results) < 0.25 * results
