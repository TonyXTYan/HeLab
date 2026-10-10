"""The disk cache: SQLite records and compressed dataset files (``store-v2``).

Only isolated helpers open a store; the GUI process never does. Design, rules
and the reasons behind them: ``roadmaps/cache-storage-and-settings.md``.

- Records are JSON text in ``records.sqlite`` (WAL), readable with ``sqlite3``.
- Datasets are files in ``datasets/``, never inside SQLite. A replaced or removed
  file is retired, and only the sweep deletes it, after a grace period, so a
  reader that looked up the old row can still open it.
- Reads answer found, missing or error. An error is never "nothing saved".
- Every write checks a :class:`SaveGuard` taken when its job started, so a save
  that was already running can't bring back removed data or overwrite newer data.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
import json
import os
import pathlib
import sqlite3
import time
from typing import Any, Generator, Generic, Iterable, Literal, Mapping, Sequence, TypeVar, TypedDict, cast
import uuid

LAYOUT_VERSION = 2
STORE_DIRNAME = "store-v2"
DATASET_FORMAT = "blosc-pickle-1"
BUSY_TIMEOUT = 30.0
# Retired dataset files outlive any reader that looked up their row.
RETIRE_GRACE = 600.0
# A file still open (Windows) is retried this much later.
RETRY_OPEN = 60.0
# Pending saves the user hasn't answered, and files no row names (a killed writer).
PENDING_MAX_AGE = 3600.0
ORPHAN_MIN_AGE = 3600.0

Kind = Literal["datasets", "summaries", "histories", "subtrees"]
KINDS: tuple[Kind, ...] = ("datasets", "summaries", "histories", "subtrees")
RECORD_TABLES: dict[Kind, str] = {
    "summaries": "folder_summaries", "histories": "scan_histories", "subtrees": "subtrees"}
TABLES: dict[Kind, str] = {"datasets": "datasets", **RECORD_TABLES}

T = TypeVar("T")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS folder_epochs (
    path TEXT PRIMARY KEY, epoch INTEGER NOT NULL DEFAULT 0, job_seq INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS folder_summaries (
    path TEXT PRIMARY KEY, record TEXT NOT NULL, identity TEXT, saved_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS folder_summaries_saved_at ON folder_summaries (saved_at);
CREATE TABLE IF NOT EXISTS scan_histories (path TEXT PRIMARY KEY, record TEXT NOT NULL, saved_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS scan_histories_saved_at ON scan_histories (saved_at);
CREATE TABLE IF NOT EXISTS subtrees (path TEXT PRIMARY KEY, record TEXT NOT NULL, saved_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS subtrees_saved_at ON subtrees (saved_at);
CREATE TABLE IF NOT EXISTS folder_prefs (
    path TEXT PRIMARY KEY, no_cache INTEGER NOT NULL DEFAULT 0, no_auto_load INTEGER NOT NULL DEFAULT 0,
    set_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS pending_saves (
    pending_id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE,
    reason TEXT NOT NULL CHECK (reason IN ('over_budget', 'needs_approval')),
    file TEXT NOT NULL, bytes INTEGER NOT NULL, record TEXT NOT NULL,
    gen_datasets INTEGER NOT NULL, epoch INTEGER NOT NULL, job_seq INTEGER NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS retired_files (file TEXT PRIMARY KEY, retired_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS datasets (
    path TEXT PRIMARY KEY, file TEXT NOT NULL, bytes INTEGER NOT NULL, ram_bytes INTEGER NOT NULL,
    rows INTEGER NOT NULL, shots INTEGER NOT NULL, fingerprint TEXT NOT NULL, problematic TEXT NOT NULL,
    info TEXT NOT NULL, last_used REAL NOT NULL, job_seq INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS datasets_last_used ON datasets (last_used);
"""


class StoreError(Exception):
    """The store can't be opened, read or written. Never means "nothing saved"."""


class StoreReadOnly(StoreError):
    """A newer HeLab wrote this store's layout; this one only reads it."""


class SaveRejected(Exception):
    """The save guard discarded a write; nothing was written."""

    def __init__(self, reason: Literal["cleared", "newer", "gone"], message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Read(Generic[T]):
    """One read's answer: found (with a value), missing, or error (with a message)."""
    status: Literal["found", "missing", "error"]
    value: T | None = None
    error: str = ""

    @property
    def found(self) -> bool:
        return self.status == "found"

    @property
    def missing(self) -> bool:
        return self.status == "missing"

    @property
    def failed(self) -> bool:
        return self.status == "error"


def _found(value: T) -> Read[T]:
    return Read("found", value)


def _missing() -> Read[Any]:
    return Read("missing")


def _error(message: str) -> Read[Any]:
    return Read("error", error=message)


@dataclass(frozen=True)
class SaveGuard:
    """Values read when a job started; its writes succeed only while they hold."""
    generations: Mapping[str, int]
    epochs: Mapping[str, int]
    job_seq: int = 0


class DatasetRecord(TypedDict):
    """What a load saves with its dataset file. ``info`` holds ``saved_at``,
    ``snapshot_at``, ``signature``, ``counts``, ``unsettled``, ``kind`` and ``format``."""
    ram_bytes: int
    rows: int
    shots: int
    fingerprint: list[list[int]]
    problematic: list[int]
    info: dict[str, Any]


class DatasetRow(DatasetRecord):
    path: str
    file: str
    bytes: int
    last_used: float
    job_seq: int


@dataclass(frozen=True)
class Removal:
    """What one removal did. ``paths`` is None for a removal by kind (every path)."""
    kinds: tuple[Kind, ...]
    paths: tuple[str, ...] | None
    datasets: int = 0
    dataset_bytes: int = 0


@dataclass(frozen=True)
class Sweep:
    deleted_files: int = 0
    expired_pending: int = 0
    still_open: list[str] = field(default_factory=list)
    next_deadline: float | None = None


def store_root(caches_dir: str) -> str:
    return os.path.join(caches_dir, STORE_DIRNAME)


def pack_dataset(data: Mapping[int, Any]) -> bytes:
    """Blosc zstd-9 pickle of ``{shot: float64 array (n, 3)}`` (``DATASET_FORMAT``)."""
    import blosc
    import pickle
    packed: bytes = blosc.compress(pickle.dumps(dict(sorted(data.items())), protocol=pickle.HIGHEST_PROTOCOL),
                                   typesize=8, cname="zstd", clevel=9, shuffle=blosc.NOSHUFFLE)
    return packed


def unpack_dataset(packed: bytes) -> dict[int, Any] | None:
    """The shots in a dataset file, or None if it isn't a valid dataset."""
    import blosc
    import numpy as np
    import pickle
    unpacked = pickle.loads(blosc.decompress(packed))
    valid = isinstance(unpacked, dict) and all(
        isinstance(shot, int) and isinstance(array, np.ndarray) and array.ndim == 2 and array.shape[1] == 3
        for shot, array in unpacked.items())
    return cast(dict[int, Any], unpacked) if valid else None


def _dumps(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


class CacheStore:
    """One connection to a store. Not thread-safe: one per helper process."""

    def __init__(self, root: str, *, busy_timeout: float = BUSY_TIMEOUT) -> None:
        self.root = root
        self.datasets_dir = os.path.join(root, "datasets")
        self.database = os.path.join(root, "records.sqlite")
        self.read_only = False
        self._depth = 0
        self._writing = False
        try:
            self._conn = self._open(busy_timeout)
            meta = self._meta()
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be opened: {exc}") from exc
        self.layout_version = int(meta["layout_version"])
        self.store_id = str(meta["store_id"])

    # Opening and transactions

    def _connect(self, busy_timeout: float, read_only: bool) -> sqlite3.Connection:
        if read_only:
            # Percent-encoded, so "%", "?" or "#" in the folder name aren't read as URI syntax.
            uri = pathlib.Path(os.path.abspath(self.database)).as_uri()
            conn = sqlite3.connect(f"{uri}?mode=ro", uri=True,
                                   timeout=busy_timeout, isolation_level=None)
        else:
            conn = sqlite3.connect(self.database, timeout=busy_timeout, isolation_level=None)
        # A lock held longer than this is an error, never a miss.
        conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout * 1000)}")
        return conn

    def _open(self, busy_timeout: float) -> sqlite3.Connection:
        if os.path.exists(self.database):
            # Read the layout before writing anything: a newer layout is left untouched.
            probe = self._connect(busy_timeout, read_only=True)
            try:
                version = _layout_version(probe)
            finally:
                probe.close()
            if version is not None and version > LAYOUT_VERSION:
                self.read_only = True
                return self._connect(busy_timeout, read_only=True)
            if version is not None and version < LAYOUT_VERSION:
                raise sqlite3.DatabaseError(f"unsupported layout version {version}")
        os.makedirs(self.datasets_dir, exist_ok=True)
        conn = self._connect(busy_timeout, read_only=False)
        try:
            if _layout_version(conn) is None:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for statement in SCHEMA.split(";"):
                        if statement.strip():
                            conn.execute(statement)
                    defaults: dict[str, object] = {
                        "layout_version": LAYOUT_VERSION, "store_id": uuid.uuid4().hex, "created_at": time.time(),
                        **{f"gen_{kind}": 0 for kind in KINDS}}
                    # Another helper may have created it meanwhile: keep its values.
                    conn.executemany("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                                     [(key, _dumps(value)) for key, value in defaults.items()])
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
            version = _layout_version(conn)
            if version != LAYOUT_VERSION:
                raise sqlite3.DatabaseError(f"unsupported layout version {version}")
        except BaseException:
            conn.close()
            raise
        return conn

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> CacheStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextlib.contextmanager
    def transaction(self, write: bool = True) -> Generator[None, None, None]:
        """One SQLite transaction; nested calls join the outer one.

        A write transaction takes the write lock at once (``BEGIN IMMEDIATE``),
        so what it reads stays true until it commits.
        """
        if self._depth:
            if write and not self._writing:
                raise StoreError("A write inside a read transaction")
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        if write and self.read_only:
            raise StoreReadOnly("This disk cache was written by a newer HeLab and is read-only")
        try:
            self._conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache is busy or unavailable: {exc}") from exc
        self._depth, self._writing = 1, write
        try:
            yield
            self._conn.execute("COMMIT")
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                self._conn.execute("ROLLBACK")
            raise
        finally:
            self._depth, self._writing = 0, False

    def _meta(self) -> dict[str, Any]:
        return {key: json.loads(value) for key, value in self._conn.execute("SELECT key, value FROM meta")}

    # Save guard

    def guard(self, paths: Sequence[str], kinds: Iterable[Kind]) -> SaveGuard:
        """The generations and folder epochs a job's later writes must still see."""
        kinds = tuple(kinds)
        try:
            with self.transaction(write=False):
                meta = self._meta()
                epochs = {path: self._epoch(path) for path in paths}
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be read: {exc}") from exc
        return SaveGuard({kind: int(meta[f"gen_{kind}"]) for kind in kinds}, epochs)

    def start_dataset_job(self, path: str, kinds: Iterable[Kind] = ("datasets",)) -> SaveGuard:
        """A guard for a job that may save ``path``'s dataset, with its job sequence.

        Every such job takes the next ``job_seq`` when it starts; only a save from a
        later-started job can replace a dataset or supersede a pending save.
        """
        kinds = tuple(dict.fromkeys(("datasets", *kinds)))
        try:
            with self.transaction():
                self._conn.execute("INSERT INTO folder_epochs (path, job_seq) VALUES (?, 1) "
                                   "ON CONFLICT (path) DO UPDATE SET job_seq = job_seq + 1", (path,))
                epoch, job_seq = self._conn.execute(
                    "SELECT epoch, job_seq FROM folder_epochs WHERE path = ?", (path,)).fetchone()
                meta = self._meta()
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return SaveGuard({kind: int(meta[f"gen_{kind}"]) for kind in kinds}, {path: int(epoch)}, int(job_seq))

    def _epoch(self, path: str) -> int:
        row = self._conn.execute("SELECT epoch FROM folder_epochs WHERE path = ?", (path,)).fetchone()
        return int(row[0]) if row else 0

    def _guard_holds(self, guard: SaveGuard, kind: Kind, path: str) -> bool:
        if kind not in guard.generations or path not in guard.epochs:
            raise ValueError(f"The save guard doesn't cover {kind} for {path}")
        meta = self._meta()
        return (int(meta[f"gen_{kind}"]) == guard.generations[kind]
                and self._epoch(path) == guard.epochs[path])

    def _check(self, guard: SaveGuard, kind: Kind, path: str) -> None:
        if not self._guard_holds(guard, kind, path):
            raise SaveRejected("cleared", "Cache was cleared before saving completed")

    # Records

    def read_record(self, kind: Kind, path: str) -> Read[dict[str, Any]]:
        return self.read_records(kind, [path])[path]

    def read_records(self, kind: Kind, paths: Sequence[str]) -> dict[str, Read[dict[str, Any]]]:
        """Each path's record: found, missing, or (for that path, or all on a database error) error."""
        table = RECORD_TABLES[kind]
        unique = list(dict.fromkeys(paths))
        rows: dict[str, str] = {}
        try:
            with self.transaction(write=False):
                for start in range(0, len(unique), 500):
                    chunk = unique[start:start + 500]
                    rows.update(self._conn.execute(
                        f"SELECT path, record FROM {table} WHERE path IN ({','.join('?' * len(chunk))})",
                        chunk).fetchall())
        except (sqlite3.Error, StoreError) as exc:
            failure = _error(f"Disk cache could not be read: {exc}")
            return {path: failure for path in unique}
        result: dict[str, Read[dict[str, Any]]] = {}
        for path in unique:
            if path not in rows:
                result[path] = _missing()
                continue
            try:
                value = json.loads(rows[path])
            except ValueError as exc:
                result[path] = _error(f"Saved {kind} record is unreadable: {exc}")
                continue
            result[path] = _found(value) if isinstance(value, dict) else _error(f"Saved {kind} record is not an object")
        return result

    def save_record(self, kind: Kind, path: str, record: Mapping[str, Any] | None, guard: SaveGuard, *,
                    saved_at: float | None = None) -> None:
        """Save (or with None, delete) one record, if ``guard`` still holds."""
        self.save_records(kind, {path: record}, guard, saved_at=saved_at)

    def save_records(self, kind: Kind, records: Mapping[str, Mapping[str, Any] | None], guard: SaveGuard, *,
                     saved_at: float | None = None) -> None:
        """Save a batch in one transaction: all of it, or (on a rejection or error) none."""
        table = RECORD_TABLES[kind]
        saved_at = time.time() if saved_at is None else saved_at
        try:
            with self.transaction():
                for path, record in records.items():
                    self._check(guard, kind, path)
                    if record is None:
                        self._conn.execute(f"DELETE FROM {table} WHERE path = ?", (path,))
                    elif kind == "summaries":
                        identity = record.get("identity")
                        self._conn.execute(
                            "INSERT OR REPLACE INTO folder_summaries (path, record, identity, saved_at) "
                            "VALUES (?, ?, ?, ?)",
                            (path, _dumps(record), None if identity is None else _dumps(identity), saved_at))
                    else:
                        self._conn.execute(f"INSERT OR REPLACE INTO {table} (path, record, saved_at) VALUES (?, ?, ?)",
                                           (path, _dumps(record), saved_at))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    # Datasets

    def write_dataset_file(self, packed: bytes) -> str:
        """Publish a compressed dataset under its final name; no row names it yet.

        A killed writer leaves at most a ``tmp-`` or an unreferenced file, which the
        sweep deletes once it is over an hour old.
        """
        if self.read_only:
            raise StoreReadOnly("This disk cache was written by a newer HeLab and is read-only")
        name = uuid.uuid4().hex
        temporary = os.path.join(self.datasets_dir, f"tmp-{name}")
        final = f"{name}.blosc"
        try:
            with open(temporary, "wb") as handle:
                handle.write(packed)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, os.path.join(self.datasets_dir, final))
        except OSError as exc:
            with contextlib.suppress(OSError):
                os.remove(temporary)
            raise StoreError(f"Cached data file could not be written: {exc}") from exc
        _fsync_dir(self.datasets_dir)
        return final

    def _file_bytes(self, file: str) -> int:
        try:
            return os.path.getsize(os.path.join(self.datasets_dir, file))
        except OSError as exc:
            raise StoreError(f"Cached data file is unavailable: {exc}") from exc

    def _retire(self, file: str, now: float) -> None:
        self._conn.execute("INSERT OR IGNORE INTO retired_files (file, retired_at) VALUES (?, ?)", (file, now))

    def _stored_job_seq(self, path: str) -> int | None:
        row = self._conn.execute("SELECT job_seq FROM datasets WHERE path = ?", (path,)).fetchone()
        return int(row[0]) if row else None

    def _reject_file(self, file: str, rejection: SaveRejected) -> SaveRejected:
        """Retire a published file whose save was rejected, in its own transaction.

        Never one a row still names: a repeated save of the same file is rejected too.
        """
        with contextlib.suppress(sqlite3.Error, StoreError):
            with self.transaction():
                if self._conn.execute("SELECT 1 FROM datasets WHERE file = ? UNION ALL "
                                      "SELECT 1 FROM pending_saves WHERE file = ?", (file, file)).fetchone() is None:
                    self._retire(file, time.time())
        return rejection

    def save_dataset(self, path: str, file: str, record: DatasetRecord, guard: SaveGuard) -> None:
        """Point ``path``'s dataset row at a file from :meth:`write_dataset_file`.

        The previous file, and those of older jobs' pending saves, are retired, never
        deleted here. A rejected save retires ``file`` and raises :class:`SaveRejected`.
        """
        now = time.time()
        size = self._file_bytes(file)
        try:
            with self.transaction():
                self._check(guard, "datasets", path)
                stored = self._stored_job_seq(path)
                if stored is not None and stored >= guard.job_seq:
                    raise SaveRejected("newer", "Newer data is already cached")
                self._upsert_dataset(path, file, size, record, guard.job_seq, now)
                for (old,) in self._conn.execute("SELECT file FROM pending_saves WHERE path = ? AND job_seq < ?",
                                                 (path, guard.job_seq)).fetchall():
                    self._retire(old, now)
                self._conn.execute("DELETE FROM pending_saves WHERE path = ? AND job_seq < ?", (path, guard.job_seq))
        except SaveRejected as rejection:
            raise self._reject_file(file, rejection) from None
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    def _upsert_dataset(self, path: str, file: str, size: int, record: DatasetRecord, job_seq: int,
                        now: float) -> None:
        previous = self._conn.execute("SELECT file FROM datasets WHERE path = ?", (path,)).fetchone()
        info = {"format": DATASET_FORMAT, **record["info"]}
        self._conn.execute(
            "INSERT OR REPLACE INTO datasets (path, file, bytes, ram_bytes, rows, shots, fingerprint, problematic, "
            "info, last_used, job_seq) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (path, file, size, int(record["ram_bytes"]), int(record["rows"]), int(record["shots"]),
             _dumps(record["fingerprint"]), _dumps(record["problematic"]), _dumps(info), now, job_seq))
        if previous and previous[0] != file:
            self._retire(previous[0], now)

    def add_pending(self, path: str, file: str, record: DatasetRecord, guard: SaveGuard,
                    reason: Literal["over_budget", "needs_approval"]) -> str:
        """Keep a dataset waiting for the user's answer; returns its ``pending_id``.

        One per folder: a later job's pending save replaces an earlier one, and an
        earlier job's arriving later is discarded, like a save that is already
        older than the stored dataset.
        """
        now = time.time()
        size = self._file_bytes(file)
        pending_id = uuid.uuid4().hex
        try:
            with self.transaction():
                self._check(guard, "datasets", path)
                stored = self._stored_job_seq(path)
                if stored is not None and stored >= guard.job_seq:
                    raise SaveRejected("newer", "Newer data is already cached")
                existing = self._conn.execute("SELECT file, job_seq FROM pending_saves WHERE path = ?",
                                              (path,)).fetchone()
                if existing and int(existing[1]) >= guard.job_seq:
                    raise SaveRejected("newer", "Newer data is already waiting to be cached")
                if existing:
                    self._retire(existing[0], now)
                    self._conn.execute("DELETE FROM pending_saves WHERE path = ?", (path,))
                self._conn.execute(
                    "INSERT INTO pending_saves (pending_id, path, reason, file, bytes, record, gen_datasets, epoch, "
                    "job_seq, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (pending_id, path, reason, file, size, _dumps(record), guard.generations["datasets"],
                     guard.epochs[path], guard.job_seq, now))
        except SaveRejected as rejection:
            raise self._reject_file(file, rejection) from None
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return pending_id

    def adopt_pending(self, pending_id: str) -> str:
        """Make a pending save the folder's dataset; returns its path.

        Raises :class:`SaveRejected` if it is gone, or (discarding it) if the folder
        was cleared or newer data was cached since its job started.
        """
        now = time.time()
        rejection: SaveRejected | None = None
        try:
            with self.transaction():
                row = self._conn.execute(
                    "SELECT path, file, bytes, record, gen_datasets, epoch, job_seq FROM pending_saves "
                    "WHERE pending_id = ?", (pending_id,)).fetchone()
                if row is None:
                    raise SaveRejected("gone", "This save is no longer waiting")
                path, file, size, record, generation, epoch, job_seq = row
                stored = self._stored_job_seq(path)
                if (int(self._meta()["gen_datasets"]) != generation or self._epoch(path) != epoch):
                    rejection = SaveRejected("cleared", "Cache was cleared before saving completed")
                elif stored is not None and stored >= job_seq:
                    rejection = SaveRejected("newer", "Newer data is already cached")
                else:
                    self._upsert_dataset(path, file, int(size), json.loads(record), int(job_seq), now)
                if rejection is not None:
                    self._retire(file, now)
                self._conn.execute("DELETE FROM pending_saves WHERE pending_id = ?", (pending_id,))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        if rejection is not None:
            raise rejection
        return str(path)

    def discard_pending(self, pending_id: str) -> bool:
        """Drop a pending save and retire its file; False if it was already gone."""
        try:
            with self.transaction():
                row = self._conn.execute("SELECT file FROM pending_saves WHERE pending_id = ?",
                                         (pending_id,)).fetchone()
                if row is None:
                    return False
                self._retire(row[0], time.time())
                self._conn.execute("DELETE FROM pending_saves WHERE pending_id = ?", (pending_id,))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return True

    def read_dataset_row(self, path: str) -> Read[DatasetRow]:
        """The dataset's record without its data, e.g. for the one-stat check."""
        try:
            with self.transaction(write=False):
                row = self._conn.execute(
                    "SELECT path, file, bytes, ram_bytes, rows, shots, fingerprint, problematic, info, last_used, "
                    "job_seq FROM datasets WHERE path = ?", (path,)).fetchone()
        except (sqlite3.Error, StoreError) as exc:
            return _error(f"Disk cache could not be read: {exc}")
        if row is None:
            return _missing()
        try:
            return _found(cast(DatasetRow, {
                "path": row[0], "file": row[1], "bytes": row[2], "ram_bytes": row[3], "rows": row[4],
                "shots": row[5], "fingerprint": json.loads(row[6]), "problematic": json.loads(row[7]),
                "info": json.loads(row[8]), "last_used": row[9], "job_seq": row[10]}))
        except ValueError as exc:
            return _error(f"Saved dataset record is unreadable: {exc}")

    def _read_file(self, file: str) -> bytes:
        with open(os.path.join(self.datasets_dir, file), "rb") as handle:
            return handle.read()

    def read_dataset(self, path: str) -> Read[tuple[DatasetRow, bytes]]:
        """The dataset's record and its compressed file.

        A writer may replace the file just after the row was read. A missing file
        is answered by re-reading the row once: another file is opened, no row is
        "missing", and the same row is an error. The re-read needs a fresh snapshot,
        so this never runs inside a transaction.
        """
        if self._depth:
            raise RuntimeError("read_dataset can't run inside a transaction")
        found = self.read_dataset_row(path)
        if not found.found or found.value is None:
            return cast(Read[tuple[DatasetRow, bytes]], found)
        row = found.value
        try:
            return _found((row, self._read_file(row["file"])))
        except FileNotFoundError:
            pass
        except OSError as exc:
            return _error(f"Cached data file could not be read: {exc}")
        again = self.read_dataset_row(path)
        if not again.found or again.value is None:
            return cast(Read[tuple[DatasetRow, bytes]], again)
        if again.value["file"] == row["file"]:
            return _error("Cached data file is missing")
        try:
            return _found((again.value, self._read_file(again.value["file"])))
        except OSError as exc:
            return _error(f"Cached data file could not be read: {exc}")

    def touch_dataset(self, path: str, now: float | None = None) -> None:
        """Record that the dataset was used: shown from the cache, reused or confirmed."""
        try:
            with self.transaction():
                self._conn.execute("UPDATE datasets SET last_used = ? WHERE path = ?",
                                   (time.time() if now is None else now, path))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    # Removals and cleanup

    def remove(self, kinds: Iterable[Kind], paths: Iterable[str] | None = None) -> Removal:
        """The one removal function: Clear, purges, trim, Make room, don't-cache, per-folder clear.

        In one transaction it deletes the rows, bumps each path's folder epoch (by
        path) or each kind's generation (by kind, which also stops a folder's first
        save still in flight), and retires dataset files, including those of
        pending saves, whose adoption would fail anyway.
        """
        kinds = tuple(dict.fromkeys(kinds))
        selected = None if paths is None else tuple(dict.fromkeys(paths))
        now = time.time()
        datasets = dataset_bytes = 0
        where, args = "", cast(tuple[str, ...], ())
        try:
            with self.transaction():
                if selected is not None:
                    where = f" WHERE path IN ({','.join('?' * len(selected))})"
                    args = selected
                if "datasets" in kinds and (selected is None or selected):
                    for file, size in self._conn.execute(f"SELECT file, bytes FROM datasets{where}", args).fetchall():
                        self._retire(file, now)
                        datasets += 1
                        dataset_bytes += int(size)
                    for (file,) in self._conn.execute(f"SELECT file FROM pending_saves{where}", args).fetchall():
                        self._retire(file, now)
                    self._conn.execute(f"DELETE FROM pending_saves{where}", args)
                for kind in kinds:
                    if selected is None or selected:
                        self._conn.execute(f"DELETE FROM {TABLES[kind]}{where}", args)
                    if selected is None:
                        self._conn.execute("UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
                                           "WHERE key = ?", (f"gen_{kind}",))
                for path in selected or ():
                    self._conn.execute("INSERT INTO folder_epochs (path, epoch) VALUES (?, 1) "
                                       "ON CONFLICT (path) DO UPDATE SET epoch = epoch + 1", (path,))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return Removal(kinds, selected, datasets, dataset_bytes)

    def next_deadline(self) -> float | None:
        """When the next sweep has something to do: a retired file's or pending save's expiry."""
        try:
            with self.transaction(write=False):
                retired = self._conn.execute("SELECT MIN(retired_at) FROM retired_files").fetchone()[0]
                pending = self._conn.execute("SELECT MIN(created_at) FROM pending_saves").fetchone()[0]
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be read: {exc}") from exc
        deadlines = [value for value in (None if retired is None else retired + RETIRE_GRACE,
                                         None if pending is None else pending + PENDING_MAX_AGE)
                     if value is not None]
        return min(deadlines) if deadlines else None

    def sweep(self, now: float | None = None) -> Sweep:
        """Delete retired files past their grace period, expire pending saves over an
        hour old, and delete files no row names that are over an hour old."""
        now = time.time() if now is None else now
        try:
            with self.transaction():
                expired = self._conn.execute("SELECT pending_id, file FROM pending_saves WHERE created_at <= ?",
                                             (now - PENDING_MAX_AGE,)).fetchall()
                for _, file in expired:
                    self._retire(file, now)
                self._conn.executemany("DELETE FROM pending_saves WHERE pending_id = ?",
                                       [(pending_id,) for pending_id, _ in expired])
                due = [file for (file,) in self._conn.execute(
                    "SELECT file FROM retired_files WHERE retired_at <= ?", (now - RETIRE_GRACE,)).fetchall()]
            deleted, still_open = 0, []
            for file in due:
                try:
                    os.remove(os.path.join(self.datasets_dir, file))
                    deleted += 1
                except FileNotFoundError:
                    pass
                except OSError:
                    # Windows can't delete an open file: try again on a later sweep.
                    still_open.append(file)
                    continue
                with self.transaction():
                    self._conn.execute("DELETE FROM retired_files WHERE file = ?", (file,))
            deleted += self._sweep_orphans(now)
            deadline = self.next_deadline()
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be cleaned up: {exc}") from exc
        if deadline is not None and deadline <= now:
            # Only files still open are past due: retry them shortly, not at once.
            deadline = now + RETRY_OPEN
        return Sweep(deleted, len(expired), still_open, deadline)

    def _sweep_orphans(self, now: float) -> int:
        try:
            names = os.listdir(self.datasets_dir)
        except OSError:
            # Leftovers are only tidied up; the next sweep tries again.
            return 0
        with self.transaction(write=False):
            known = {file for (file,) in self._conn.execute(
                "SELECT file FROM datasets UNION SELECT file FROM pending_saves UNION SELECT file FROM retired_files")}
        deleted = 0
        for name in names:
            if name in known:
                continue
            full = os.path.join(self.datasets_dir, name)
            try:
                # Younger files may belong to a writer that hasn't committed yet.
                if os.path.getmtime(full) > now - ORPHAN_MIN_AGE:
                    continue
                os.remove(full)
                deleted += 1
            except OSError:
                continue
        return deleted


def _layout_version(conn: sqlite3.Connection) -> int | None:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'").fetchone() is None:
        return None
    row = conn.execute("SELECT value FROM meta WHERE key = 'layout_version'").fetchone()
    return None if row is None else int(json.loads(row[0]))


def _fsync_dir(directory: str) -> None:
    """Make a rename durable where the OS allows it (not on Windows)."""
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
