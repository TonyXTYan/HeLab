"""The store-v2 disk cache (helab/utils/cache_store.py), before any helper uses it."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap
import time
from typing import Any, Iterator

import numpy as np
import pytest

pytestmark = pytest.mark.no_auto_data_root

from helab.utils.cache_store import (
    KINDS, LAYOUT_VERSION, ORPHAN_MIN_AGE, PENDING_MAX_AGE, RETIRE_GRACE, CacheStore, DatasetRecord,
    SaveGuard, SaveRejected, StoreError, StoreReadOnly, pack_dataset, unpack_dataset,
)


@pytest.fixture
def root(tmp_path: Path) -> str:
    return str(tmp_path / "store-v2")


@pytest.fixture
def store(root: str) -> Iterator[CacheStore]:
    with CacheStore(root) as opened:
        yield opened


def shots(value: float, count: int = 2) -> dict[int, Any]:
    return {shot: np.full((3, 3), value + shot) for shot in range(1, count + 1)}


def record(value: float) -> DatasetRecord:
    return {"ram_bytes": 144, "rows": 6, "shots": 2, "fingerprint": [[1, 10, int(value)], [2, 10, int(value)]],
            "problematic": [], "info": {"saved_at": time.time(), "signature": f"sig-{value}", "kind": "txy"}}


def save(store: CacheStore, path: str, guard: SaveGuard, value: float) -> str:
    file = store.write_dataset_file(pack_dataset(shots(value)))
    store.save_dataset(path, file, record(value), guard)
    return file


def pend(store: CacheStore, path: str, guard: SaveGuard, value: float) -> str:
    file = store.write_dataset_file(pack_dataset(shots(value)))
    return store.add_pending(path, file, record(value), guard, "over_budget")


def stored_value(store: CacheStore, path: str) -> float:
    found = store.read_dataset(path)
    assert found.found and found.value is not None
    data = unpack_dataset(found.value[1])
    assert data is not None
    return float(data[1][0, 0]) - 1


def files_in(store: CacheStore) -> set[str]:
    return set(os.listdir(store.datasets_dir))


def retired(store: CacheStore) -> set[str]:
    with sqlite3.connect(store.database) as conn:
        return {file for (file,) in conn.execute("SELECT file FROM retired_files")}


def test_new_store_is_versioned_and_readable_with_sqlite(store: CacheStore, root: str) -> None:
    assert store.layout_version == LAYOUT_VERSION and not store.read_only
    store.save_record("summaries", "/data/a", {"status": "ok", "identity": [1, 2]},
                      store.guard(["/data/a"], ["summaries"]))
    with sqlite3.connect(store.database) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        meta = dict(conn.execute("SELECT key, value FROM meta"))
        saved = conn.execute("SELECT record, identity FROM folder_summaries").fetchone()
    assert json.loads(meta["layout_version"]) == LAYOUT_VERSION and all(meta[f"gen_{kind}"] == "0" for kind in KINDS)
    assert json.loads(saved[0]) == {"status": "ok", "identity": [1, 2]} and saved[1] is None
    with CacheStore(root) as again:
        assert again.store_id == store.store_id


def test_records_are_found_missing_or_deleted(store: CacheStore) -> None:
    guard = store.guard(["a", "b"], ["histories"])
    assert store.read_record("histories", "a").missing
    store.save_records("histories", {"a": {"blocked": True}, "b": {"blocked": False}}, guard)
    found = store.read_records("histories", ["a", "b", "c"])
    assert found["a"].value == {"blocked": True} and found["b"].found and found["c"].missing
    store.save_record("histories", "a", None, guard)
    assert store.read_record("histories", "a").missing


def test_unreadable_record_is_an_error_not_missing(store: CacheStore) -> None:
    with sqlite3.connect(store.database) as conn:
        conn.execute("INSERT INTO subtrees (path, record, saved_at) VALUES ('a', '{broken', 0)")
        conn.execute("INSERT INTO subtrees (path, record, saved_at) VALUES ('b', '[1]', 0)")
    found = store.read_records("subtrees", ["a", "b"])
    assert found["a"].failed and "unreadable" in found["a"].error
    assert found["b"].failed


class BrokenConnection:
    def __init__(self, real: sqlite3.Connection) -> None:
        self.real = real

    def execute(self, sql: str, *args: Any) -> Any:
        if sql.startswith(("BEGIN", "SELECT")):
            raise sqlite3.OperationalError("disk I/O error")
        return self.real.execute(sql, *args)

    def close(self) -> None:
        self.real.close()


def test_database_error_is_an_error_not_missing(store: CacheStore, monkeypatch: pytest.MonkeyPatch) -> None:
    guard = store.start_dataset_job("a", ["summaries"])
    save(store, "a", guard, 1)
    monkeypatch.setattr(store, "_conn", BrokenConnection(store._conn))
    assert store.read_record("summaries", "a").failed
    assert store.read_dataset_row("a").failed
    assert store.read_dataset("a").failed
    with pytest.raises(StoreError):
        store.save_record("summaries", "a", {"status": "ok"}, guard)


def test_a_held_write_lock_is_an_error_for_writers_not_a_miss_for_readers(root: str) -> None:
    with CacheStore(root, busy_timeout=0.1) as store:
        guard = store.guard(["a"], ["summaries"])
        store.save_record("summaries", "a", {"status": "ok"}, guard)
        other = sqlite3.connect(store.database, isolation_level=None)
        other.execute("BEGIN IMMEDIATE")
        try:
            # WAL: readers still see the committed record while another writer holds the lock.
            assert store.read_record("summaries", "a").value == {"status": "ok"}
            with pytest.raises(StoreError):
                store.save_record("summaries", "a", {"status": "newer"}, guard)
        finally:
            other.execute("ROLLBACK")
            other.close()


def test_dataset_round_trip_and_replacement_retires_the_old_file(store: CacheStore) -> None:
    first = save(store, "a", store.start_dataset_job("a"), 1)
    row = store.read_dataset_row("a").value
    assert row is not None and row["file"] == first and row["info"]["format"] == "blosc-pickle-1"
    assert row["bytes"] == os.path.getsize(os.path.join(store.datasets_dir, first)) and row["job_seq"] == 1
    second = save(store, "a", store.start_dataset_job("a"), 2)
    assert stored_value(store, "a") == 2
    # The old file stays for readers that looked up the old row.
    assert retired(store) == {first} and first in files_in(store)
    assert store.sweep().deleted_files == 0 and first in files_in(store)
    assert store.sweep(time.time() + RETIRE_GRACE + 1).deleted_files == 1
    assert files_in(store) == {second} and not retired(store)


def test_reader_racing_a_replacement_opens_the_new_file(store: CacheStore, root: str,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    save(store, "a", store.start_dataset_job("a"), 1)
    read_file = store._read_file
    calls: list[str] = []

    def replaced_meanwhile(file: str) -> bytes:
        if not calls:
            # Another helper replaces the dataset and its sweep deletes the old file.
            with CacheStore(root) as writer:
                save(writer, "a", writer.start_dataset_job("a"), 2)
                writer.sweep(time.time() + RETIRE_GRACE + 1)
        calls.append(file)
        return read_file(file)
    monkeypatch.setattr(store, "_read_file", replaced_meanwhile)
    assert stored_value(store, "a") == 2
    assert len(calls) == 2 and calls[0] != calls[1]


def test_reader_racing_a_removal_answers_missing(store: CacheStore, root: str,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    save(store, "a", store.start_dataset_job("a"), 1)
    read_file = store._read_file

    def removed_meanwhile(file: str) -> bytes:
        with CacheStore(root) as other:
            other.remove(["datasets"], ["a"])
            other.sweep(time.time() + RETIRE_GRACE + 1)
        return read_file(file)
    monkeypatch.setattr(store, "_read_file", removed_meanwhile)
    assert store.read_dataset("a").missing


def test_missing_file_with_an_unchanged_row_is_an_error(store: CacheStore) -> None:
    file = save(store, "a", store.start_dataset_job("a"), 1)
    os.remove(os.path.join(store.datasets_dir, file))
    found = store.read_dataset("a")
    assert found.failed and "missing" in found.error


def test_removal_racing_a_save_discards_the_save(store: CacheStore, root: str) -> None:
    guard = store.start_dataset_job("a", ["summaries"])
    other_guard = store.start_dataset_job("b")
    with CacheStore(root) as other:
        removal = other.remove(KINDS, ["a"])
    assert removal.paths == ("a",)
    file = store.write_dataset_file(pack_dataset(shots(1)))
    with pytest.raises(SaveRejected) as rejected:
        store.save_dataset("a", file, record(1), guard)
    assert rejected.value.reason == "cleared"
    with pytest.raises(SaveRejected):
        store.save_record("summaries", "a", {"status": "ok"}, guard)
    assert store.read_dataset("a").missing and store.read_record("summaries", "a").missing
    # The rejected file is retired, and another folder's save is unaffected.
    assert file in retired(store)
    save(store, "b", other_guard, 3)
    assert stored_value(store, "b") == 3


def test_repeated_save_of_the_same_file_never_retires_it(store: CacheStore) -> None:
    guard = store.start_dataset_job("a")
    file = store.write_dataset_file(pack_dataset(shots(1)))
    store.save_dataset("a", file, record(1), guard)
    with pytest.raises(SaveRejected):
        store.save_dataset("a", file, record(1), guard)
    pending_file = store.write_dataset_file(pack_dataset(shots(2)))
    newer = store.start_dataset_job("a")
    store.add_pending("a", pending_file, record(2), newer, "over_budget")
    with pytest.raises(SaveRejected):
        store.add_pending("a", pending_file, record(2), newer, "over_budget")
    assert not retired(store)
    store.sweep(time.time() + ORPHAN_MIN_AGE + 1)
    assert stored_value(store, "a") == 1 and files_in(store) == {file, pending_file}


def test_read_dataset_refuses_to_run_inside_a_transaction(store: CacheStore) -> None:
    save(store, "a", store.start_dataset_job("a"), 1)
    # Its missing-file re-read would see the same stale snapshot.
    with store.transaction(write=False):
        with pytest.raises(RuntimeError):
            store.read_dataset("a")


def test_failed_dataset_file_write_is_a_store_error(store: CacheStore, monkeypatch: pytest.MonkeyPatch) -> None:
    def disk_full(descriptor: int) -> None:
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(os, "fsync", disk_full)
    with pytest.raises(StoreError, match="No space left"):
        store.write_dataset_file(pack_dataset(shots(1)))
    assert files_in(store) == set()


def test_clear_by_kind_stops_a_first_save_still_in_flight(store: CacheStore, root: str) -> None:
    summary_guard = store.guard(["new"], ["summaries"])
    dataset_guard = store.start_dataset_job("new")
    with CacheStore(root) as other:
        # No row and no epoch bump can reach "new": only the generation does.
        removal = other.remove(["summaries", "datasets"])
    assert removal.paths is None
    with pytest.raises(SaveRejected):
        store.save_record("summaries", "new", {"status": "ok"}, summary_guard)
    with pytest.raises(SaveRejected):
        save(store, "new", dataset_guard, 1)
    # A job started after the clear saves as usual.
    store.save_record("summaries", "new", {"status": "ok"}, store.guard(["new"], ["summaries"]))
    save(store, "new", store.start_dataset_job("new"), 2)
    assert stored_value(store, "new") == 2


def test_clear_by_kind_retires_every_file_and_leaves_other_kinds(store: CacheStore) -> None:
    files = {save(store, path, store.start_dataset_job(path), 1) for path in ("a", "b")}
    store.save_record("histories", "a", {"blocked": True}, store.guard(["a"], ["histories"]))
    removal = store.remove(["datasets"])
    assert removal.datasets == 2 and removal.dataset_bytes > 0
    assert retired(store) == files and store.read_dataset("a").missing
    assert store.read_record("histories", "a").found


def test_older_job_never_overwrites_a_newer_dataset(store: CacheStore) -> None:
    older, newer = store.start_dataset_job("a"), store.start_dataset_job("a")
    save(store, "a", newer, 2)
    with pytest.raises(SaveRejected) as rejected:
        save(store, "a", older, 1)
    assert rejected.value.reason == "newer" and stored_value(store, "a") == 2


def test_older_pending_save_never_supersedes_a_newer_one(store: CacheStore) -> None:
    older, newer = store.start_dataset_job("a"), store.start_dataset_job("a")
    kept = pend(store, "a", newer, 2)
    # The older job finishes last, and neither has been adopted.
    with pytest.raises(SaveRejected):
        pend(store, "a", older, 1)
    assert store.adopt_pending(kept).path == "a" and stored_value(store, "a") == 2


def test_newer_pending_save_replaces_an_older_one(store: CacheStore) -> None:
    older, newer = store.start_dataset_job("a"), store.start_dataset_job("a")
    replaced = pend(store, "a", older, 1)
    kept = pend(store, "a", newer, 2)
    with pytest.raises(SaveRejected) as gone:
        store.adopt_pending(replaced)
    assert gone.value.reason == "gone"
    store.adopt_pending(kept)
    assert stored_value(store, "a") == 2


def test_older_save_finishing_after_a_newer_pending_save(store: CacheStore) -> None:
    older, newer = store.start_dataset_job("a"), store.start_dataset_job("a")
    pending = pend(store, "a", newer, 2)
    # Nothing newer is stored yet, so the older job's save is kept for now ...
    save(store, "a", older, 1)
    assert stored_value(store, "a") == 1
    # ... and the newer pending save still replaces it when adopted.
    store.adopt_pending(pending)
    assert stored_value(store, "a") == 2


def test_adopting_an_older_pending_save_after_a_newer_save_is_refused(store: CacheStore) -> None:
    older, newer = store.start_dataset_job("a"), store.start_dataset_job("a")
    pending = pend(store, "a", older, 1)
    save(store, "a", newer, 2)
    with pytest.raises(SaveRejected):
        store.adopt_pending(pending)
    assert stored_value(store, "a") == 2


def test_adopting_after_the_folder_was_cleared_discards_it(store: CacheStore) -> None:
    guard = store.start_dataset_job("a")
    file = store.write_dataset_file(pack_dataset(shots(1)))
    pending = store.add_pending("a", file, record(1), guard, "needs_approval")
    store.remove(["summaries"], ["a"])
    with pytest.raises(SaveRejected) as rejected:
        store.adopt_pending(pending)
    assert rejected.value.reason == "cleared"
    assert store.read_dataset("a").missing and file in retired(store)
    assert not store.discard_pending(pending)


def test_newer_layout_opens_read_only(root: str) -> None:
    with CacheStore(root) as store:
        store.save_record("summaries", "a", {"status": "ok"}, store.guard(["a"], ["summaries"]))
        database = store.database
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE meta SET value = ? WHERE key = 'layout_version'", (str(LAYOUT_VERSION + 1),))
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = Path(database).read_bytes()
    with CacheStore(root) as newer:
        assert newer.read_only and newer.layout_version == LAYOUT_VERSION + 1
        assert newer.read_record("summaries", "a").value == {"status": "ok"}
        with pytest.raises(StoreReadOnly):
            newer.save_record("summaries", "a", {"status": "changed"}, newer.guard(["a"], ["summaries"]))
        with pytest.raises(StoreReadOnly):
            newer.remove(KINDS)
        files = files_in(newer)
        with pytest.raises(StoreReadOnly):
            newer.write_dataset_file(b"data")
        with pytest.raises(StoreReadOnly):
            newer.sweep()
        assert files_in(newer) == files
    assert Path(database).read_bytes() == before


@pytest.mark.parametrize("name", [
    "with%20space",
    pytest.param("query?mode=rw", marks=pytest.mark.skipif(sys.platform == "win32",
                                                        reason="Windows forbids '?' in folder names")),
    "hash#part",
])
def test_read_only_open_handles_uri_characters_in_the_path(tmp_path: Path, name: str) -> None:
    root = tmp_path / name / "store-v2"
    with CacheStore(str(root)) as store:
        store.save_record("summaries", "a", {"status": "ok"}, store.guard(["a"], ["summaries"]))
    with sqlite3.connect(root / "records.sqlite") as conn:
        conn.execute("UPDATE meta SET value = ? WHERE key = 'layout_version'", (str(LAYOUT_VERSION + 1),))
    with CacheStore(str(root)) as newer:
        assert newer.read_only and newer.read_record("summaries", "a").value == {"status": "ok"}
    # Nothing was opened or created anywhere else.
    assert sorted(p.name for p in tmp_path.iterdir()) == [name]


def test_older_or_corrupt_store_fails_to_open(root: str, tmp_path: Path) -> None:
    with CacheStore(root) as store:
        database = store.database
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE meta SET value = '1' WHERE key = 'layout_version'")
    with pytest.raises(StoreError):
        CacheStore(root)
    corrupt = tmp_path / "corrupt"
    corrupt.mkdir()
    (corrupt / "records.sqlite").write_bytes(b"not a database" * 100)
    with pytest.raises(StoreError):
        CacheStore(str(corrupt))


WRITER = textwrap.dedent("""
    import sys
    from helab.utils.cache_store import CacheStore, SaveRejected, pack_dataset
    import numpy as np
    root, name = sys.argv[1], sys.argv[2]
    rejected = 0
    with CacheStore(root) as store:
        for i in range(25):
            path = f"{name}/{i}"
            store.save_record("summaries", path, {"i": i}, store.guard([path], ["summaries"]))
            guard = store.start_dataset_job("shared")
            file = store.write_dataset_file(pack_dataset({1: np.full((2, 3), float(i))}))
            try:
                store.save_dataset("shared", file, {"ram_bytes": 48, "rows": 2, "shots": 1,
                    "fingerprint": [[1, 1, i]], "problematic": [], "info": {"writer": name}}, guard)
            except SaveRejected:
                rejected += 1
    print(rejected)
""")


def test_two_processes_writing_at_once(store: CacheStore, root: str) -> None:
    writers = [subprocess.Popen([sys.executable, "-c", WRITER, root, name], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True) for name in ("one", "two")]
    results = [writer.communicate(timeout=120) for writer in writers]
    assert [writer.returncode for writer in writers] == [0, 0], results
    for name in ("one", "two"):
        found = store.read_records("summaries", [f"{name}/{i}" for i in range(25)])
        assert all(read.found for read in found.values())
    row = store.read_dataset_row("shared").value
    # 50 jobs took distinct sequence numbers; the stored dataset is the newest saved.
    assert row is not None and store.read_dataset("shared").found
    with sqlite3.connect(store.database) as conn:
        assert conn.execute("SELECT job_seq FROM folder_epochs WHERE path = 'shared'").fetchone()[0] == 50
    referenced = {row["file"]} | retired(store)
    assert files_in(store) <= referenced


KILLED = textwrap.dedent("""
    import os, sys
    from helab.utils.cache_store import CacheStore, pack_dataset
    import numpy as np
    with CacheStore(sys.argv[1]) as store:
        # Published but never saved, a half-written temporary file, and an open transaction.
        store.write_dataset_file(pack_dataset({1: np.zeros((2, 3))}))
        with open(os.path.join(store.datasets_dir, "tmp-killed"), "wb") as handle:
            handle.write(b"partial")
        with store.transaction():
            store._conn.execute("INSERT INTO subtrees (path, record, saved_at) VALUES ('ghost', '{}', 0)")
            os._exit(1)
""")


def test_killed_writer_leaves_nothing_that_blocks_or_lingers(store: CacheStore, root: str) -> None:
    kept = save(store, "a", store.start_dataset_job("a"), 1)
    result = subprocess.run([sys.executable, "-c", KILLED, root], capture_output=True, text=True, timeout=120)
    assert result.returncode == 1, result.stderr
    leftovers = files_in(store) - {kept}
    assert len(leftovers) == 2 and "tmp-killed" in leftovers
    # Its transaction never committed, and its lock is gone.
    assert store.read_record("subtrees", "ghost").missing
    store.save_record("subtrees", "a", {"status": "ok"}, store.guard(["a"], ["subtrees"]))
    # Too young to tell from a writer still running.
    assert store.sweep().deleted_files == 0
    assert store.sweep(time.time() + ORPHAN_MIN_AGE + 1).deleted_files == 2
    assert files_in(store) == {kept} and stored_value(store, "a") == 1


def test_sweep_expires_pending_saves_by_deadline(store: CacheStore) -> None:
    pending = pend(store, "a", store.start_dataset_job("a"), 1)
    deadline = store.next_deadline()
    assert deadline is not None and deadline == pytest.approx(time.time() + PENDING_MAX_AGE, rel=0, abs=5)
    later = deadline + 1
    swept = store.sweep(later)
    assert swept.expired_pending == 1 and swept.next_deadline == pytest.approx(later + RETIRE_GRACE, rel=0, abs=1e-6)
    with pytest.raises(SaveRejected):
        store.adopt_pending(pending)
    assert store.sweep(later + RETIRE_GRACE).deleted_files == 1
    assert files_in(store) == set() and store.next_deadline() is None


def test_sweep_retries_a_file_still_open(store: CacheStore, monkeypatch: pytest.MonkeyPatch) -> None:
    old = save(store, "a", store.start_dataset_job("a"), 1)
    save(store, "a", store.start_dataset_job("a"), 2)
    remove = os.remove

    def still_open(path: str) -> None:
        if path.endswith(old):
            raise PermissionError("in use")
        remove(path)
    monkeypatch.setattr(os, "remove", still_open)
    now = time.time() + RETIRE_GRACE + 1
    swept = store.sweep(now)
    assert swept.still_open == [old] and swept.next_deadline == pytest.approx(now + 60, rel=0, abs=1e-6)
    assert old in retired(store)
    monkeypatch.undo()
    assert store.sweep(now + 60).deleted_files == 1 and not retired(store)


def test_touch_records_use(store: CacheStore) -> None:
    save(store, "a", store.start_dataset_job("a"), 1)
    store.touch_dataset("a", now=123.0)
    row = store.read_dataset_row("a").value
    assert row is not None and row["last_used"] == 123.0
