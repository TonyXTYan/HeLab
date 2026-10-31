"""store-v3 read only, once caching v2's store-v4 is the live store (stage 1 design addendum §8).

``LegacyStore`` is the only code that opens ``store-v3`` while store-v4 is in use: for the one-time
import of the user's own state into v4 (Q22.4), Keep's read-through of records and saved results
(Q22.3), and v3's size for the budget. It never creates a folder or a file of its own, never runs
``_migrate``, has no write method, and reads a table it lacks as empty.

It opens ``records.sqlite`` with ``mode=ro``, or, where that fails (a WAL database without its
``-shm`` where the folder isn't writable, an older SQLite), with a normal connection under
``PRAGMA query_only``. Either way ``SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE`` is set, so closing never
checkpoints the WAL into ``records.sqlite``; SQLite may still make its own ``-wal``/``-shm`` beside
it, which the v3-unchanged check allows. An older HeLab may still be writing v3 (WAL readers don't
block it).

Only helpers open it (as every store). Qt-free; standard library only.
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
from typing import Any, Sequence

DIRNAME = "store-v3"
LAYOUT = 3
BUSY_SECONDS = 5.0


class LegacyUnavailable(Exception):
    """store-v3 is there but can't be read now."""


def legacy_root(store_root: str) -> str:
    """The store-v3 folder beside a store's folder (both in the cache folder)."""
    return os.path.join(os.path.dirname(os.path.abspath(store_root)), DIRNAME)


def present(root: str) -> bool:
    return os.path.isfile(os.path.join(root, "records.sqlite"))


class LegacyStore:
    """A read-only view of the store-v3 at ``root`` (``LegacyUnavailable`` when it can't be opened)."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.database = os.path.join(root, "records.sqlite")
        if not os.path.isfile(self.database):
            raise LegacyUnavailable("There is no store-v3 here")
        self._conn = self._open()
        try:
            self._tables = {str(row[0]) for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            meta = self._meta()
        except sqlite3.Error as exc:
            self._conn.close()
            raise LegacyUnavailable(f"store-v3 can't be read ({exc})") from exc
        layout = meta.get("layout_version")
        if layout != LAYOUT or not isinstance(meta.get("store_id"), str):
            self._conn.close()
            raise LegacyUnavailable(f"store-v3 has layout {layout!r}, not {LAYOUT}")
        self.store_id = str(meta["store_id"])
        self.meta = meta

    def _open(self) -> sqlite3.Connection:
        uri = pathlib.Path(os.path.abspath(self.database)).as_uri()
        failure: sqlite3.Error | None = None
        for read_only in (True, False):
            conn: sqlite3.Connection | None = None
            try:
                if read_only:
                    conn = sqlite3.connect(f"{uri}?mode=ro", uri=True, timeout=BUSY_SECONDS, isolation_level=None)
                else:
                    # (``mode=rw``: never ``rwc``, so a file gone meanwhile isn't made again.)
                    conn = sqlite3.connect(f"{uri}?mode=rw", uri=True, timeout=BUSY_SECONDS, isolation_level=None)
                conn.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
                conn.execute("PRAGMA query_only = 1")
                conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
                return conn
            except sqlite3.Error as exc:
                if conn is not None:
                    conn.close()
                failure = exc
        raise LegacyUnavailable(f"store-v3 can't be opened ({failure})")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> LegacyStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def has(self, table: str) -> bool:
        return table in self._tables

    def _meta(self) -> dict[str, Any]:
        found: dict[str, Any] = {}
        for key, value in self._conn.execute("SELECT key, value FROM meta"):
            try:
                found[str(key)] = json.loads(value)
            except ValueError:
                continue
        return found

    def columns(self, table: str) -> list[str]:
        if not self.has(table):
            return []
        return [str(row[1]) for row in self._conn.execute(f"PRAGMA table_info({table})")]

    def rows(self, table: str, columns: Sequence[str]) -> list[tuple[Any, ...]]:
        """Every row of ``table`` with these columns; none when the table or a column is missing."""
        have = set(self.columns(table))
        if not columns or not set(columns) <= have:
            return []
        try:
            return [tuple(row) for row in self._conn.execute(f"SELECT {', '.join(columns)} FROM {table}")]
        except sqlite3.Error as exc:
            raise LegacyUnavailable(f"store-v3's {table} can't be read ({exc})") from exc

    def records(self, table: str, keys: Sequence[str], *, before: float | None = None,
                failures_before: float | None = None) -> dict[str, str]:
        """``table``'s ``record`` text by key, for the keys it has; with ``before``, not those saved before
        it (a purge by age in the store reading through), except a scan history with failures saved since
        ``failures_before`` (the latest purge that took those; None: none did, so every one stays)."""
        if not self.has(table):
            return {}
        found: dict[str, str] = {}
        since = ""
        args: tuple[float, ...] = ()
        if before is not None:
            failed = "json_array_length(record, '$.failures') > 0"
            if table != "scan_histories":
                since, args = " AND saved_at >= ?", (before,)
            elif failures_before is None:
                since, args = f" AND (saved_at >= ? OR {failed})", (before,)
            else:
                since, args = f" AND (saved_at >= ? OR ({failed} AND saved_at >= ?))", (before, failures_before)
        try:
            for start in range(0, len(keys), 500):
                chunk = list(keys[start:start + 500])
                found.update((str(key), str(record)) for key, record in self._conn.execute(
                    f"SELECT path, record FROM {table} WHERE path IN ({','.join('?' * len(chunk))}){since}",
                    [*chunk, *args]))
        except sqlite3.Error as exc:
            raise LegacyUnavailable(f"store-v3's {table} can't be read ({exc})") from exc
        return found

    def result_row(self, key: str, where: str, args: tuple[Any, ...], *,
                   since: float | None = None) -> tuple[Any, ...] | None:
        """The newest ``results`` row of ``key`` matching ``where`` (as ``CacheStore._result_row``); with
        ``since``, only one shown since then (a purge by age in the store reading through)."""
        if not self.has("results"):
            return None
        used = "" if since is None else " AND last_used >= ?"
        try:
            row = self._conn.execute(
                "SELECT result_id, path, lookup, family, analysis_id, action, record, file, bytes, computed_at, "
                f"saved_at, last_used FROM results WHERE path = ? AND {where}{used} ORDER BY computed_at DESC LIMIT 1",
                (key, *args, *(() if since is None else (since,)))).fetchone()
        except sqlite3.Error as exc:
            raise LegacyUnavailable(f"store-v3's results can't be read ({exc})") from exc
        return None if row is None else tuple(row)

    def result_counts(self, keys: Sequence[str]) -> dict[str, tuple[int, int]]:
        """Each key's saved results in v3: (count, bytes), for the keys it has any of."""
        if not self.has("results"):
            return {}
        found: dict[str, tuple[int, int]] = {}
        try:
            for start in range(0, len(keys), 500):
                chunk = list(keys[start:start + 500])
                for key, count, size in self._conn.execute(
                        f"SELECT path, COUNT(*), COALESCE(SUM(bytes), 0) FROM results "
                        f"WHERE path IN ({','.join('?' * len(chunk))}) GROUP BY path", chunk):
                    found[str(key)] = (int(count), int(size))
        except sqlite3.Error as exc:
            raise LegacyUnavailable(f"store-v3's results can't be read ({exc})") from exc
        return found

    def result_lookups(self, keys: Sequence[str], *, since: float | None = None) -> dict[str, list[tuple[str, int]]]:
        """Each key's saved results in v3: (lookup, bytes) each; with ``since``, those shown since then."""
        if not self.has("results"):
            return {}
        found: dict[str, list[tuple[str, int]]] = {}
        used = "" if since is None else " AND last_used >= ?"
        try:
            for start in range(0, len(keys), 500):
                chunk = list(keys[start:start + 500])
                for key, lookup, size in self._conn.execute(
                        f"SELECT path, lookup, bytes FROM results WHERE path IN ({','.join('?' * len(chunk))}){used}",
                        [*chunk, *(() if since is None else (since,))]):
                    found.setdefault(str(key), []).append((str(lookup), int(size)))
        except sqlite3.Error as exc:
            raise LegacyUnavailable(f"store-v3's results can't be read ({exc})") from exc
        return found

    def read_file(self, file: str) -> bytes:
        """A data file a v3 row names (``results/<name>`` or a dataset file), read only."""
        parts = file.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise LegacyUnavailable(f"store-v3 names a file outside it ({file!r})")
        path = os.path.join(self.root, *parts) if len(parts) > 1 else os.path.join(self.root, "datasets", file)
        with open(path, "rb") as handle:
            return handle.read()

    def live_bytes(self) -> int:
        """v3's live bytes as its own ``_live`` counts them: dataset and result files rows name, plus
        the records database's pages in use, less pending saves' and results' records."""
        try:
            total = 0
            for table in ("datasets", "results"):
                if self.has(table):
                    total += int(self._conn.execute(f"SELECT COALESCE(SUM(bytes), 0) FROM {table}").fetchone()[0])
            pending = 0
            if self.has("pending_saves"):
                pending += int(self._conn.execute(
                    "SELECT COALESCE(SUM(LENGTH(record)), 0) FROM pending_saves").fetchone()[0])
            if self.has("pending_results"):
                pending += int(self._conn.execute(
                    "SELECT COALESCE(SUM(LENGTH(record) + LENGTH(guard)), 0) FROM pending_results").fetchone()[0])
            pages = int(self._conn.execute("PRAGMA page_count").fetchone()[0])
            free = int(self._conn.execute("PRAGMA freelist_count").fetchone()[0])
            size = int(self._conn.execute("PRAGMA page_size").fetchone()[0])
        except sqlite3.Error as exc:
            raise LegacyUnavailable(f"store-v3 can't be measured ({exc})") from exc
        return total + max(0, (pages - free) * size - pending)

    def integrity_ok(self) -> bool:
        """SQLite's ``integrity_check`` (a cache move's verification of a copy)."""
        try:
            return bool(self._conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
        except sqlite3.Error as exc:
            raise LegacyUnavailable(f"store-v3 can't be checked ({exc})") from exc

    def named_files(self) -> list[tuple[str, int]]:
        """Every data file a row names, with its recorded size (datasets, pending saves, results)."""
        found: list[tuple[str, int]] = []
        for table in ("datasets", "pending_saves", "results", "pending_results"):
            found += [(str(file), int(size)) for file, size in self.rows(table, ("file", "bytes"))]
        return found

    def writes(self) -> int:
        """v3's write counter (``meta.writes``), to tell whether it changed since it was measured."""
        value = self._meta().get("writes", 0)
        return int(value) if isinstance(value, int) else 0
