"""Opening the store retries SQLite's "disk I/O error" briefly, and nothing else.

On Windows, a helper opening the store while another process's last connection closes (and
removes the WAL files) can get SQLITE_IOERR, which the busy timeout doesn't cover. That made
tests/test_live.py's quitting test fail on Windows CI ("Disk cache could not be opened: disk I/O
error") and can fail a cached read in the app the same way.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

import pytest

from helab.io_ops import stores
from helab.utils import cache_store
from helab.utils.cache_store import CacheStore, StoreError


def io_error(code: int | None = sqlite3.SQLITE_IOERR) -> sqlite3.OperationalError:
    exc = sqlite3.OperationalError("disk I/O error")
    if code is not None:
        exc.sqlite_errorcode = code  # Python sets it for errors that come from SQLite.
    return exc


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(cache_store, "_sleep", slept.append)
    return slept


def failing_opens(monkeypatch: pytest.MonkeyPatch, *errors: sqlite3.Error) -> list[Any]:
    """``CacheStore._open`` raises ``errors`` in turn, then opens for real; returns its calls."""
    original, calls, pending = CacheStore._open, [], list(errors)

    def open_(self: CacheStore, busy_timeout: float) -> sqlite3.Connection:
        calls.append(busy_timeout)
        if pending:
            raise pending.pop(0)
        return original(self, busy_timeout)
    monkeypatch.setattr(CacheStore, "_open", open_)
    return calls


def test_a_disk_io_error_while_opening_is_tried_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float],
) -> None:
    calls = failing_opens(monkeypatch, io_error(), io_error(sqlite3.SQLITE_IOERR | (13 << 8)))  # Any IOERR.
    with CacheStore(str(tmp_path / "store")) as store:
        assert store.store_id and not store.read_only
    assert len(calls) == 3 and sleeps == [0.1, 0.2]


def test_one_that_lasts_fails_after_the_last_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float],
) -> None:
    calls = failing_opens(monkeypatch, *(io_error() for _ in range(cache_store.OPEN_ATTEMPTS)))
    with pytest.raises(StoreError, match="Disk cache could not be opened: disk I/O error"):
        CacheStore(str(tmp_path / "store"))
    assert len(calls) == cache_store.OPEN_ATTEMPTS and len(sleeps) == cache_store.OPEN_ATTEMPTS - 1


def test_the_text_decides_when_python_gives_no_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float],
) -> None:
    calls = failing_opens(monkeypatch, io_error(None))
    CacheStore(str(tmp_path / "store")).close()
    assert len(calls) == 2


@pytest.mark.parametrize("error", [
    sqlite3.OperationalError("database is locked"),  # The busy timeout's job, not this retry's.
    sqlite3.DatabaseError("unsupported layout version 1"),
], ids=["locked", "layout"])
def test_other_errors_are_not_tried_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float], error: sqlite3.Error,
) -> None:
    calls = failing_opens(monkeypatch, error)
    with pytest.raises(StoreError, match=str(error)):
        CacheStore(str(tmp_path / "store"))
    assert len(calls) == 1 and sleeps == []


def test_a_file_that_isnt_a_database_fails_at_once(tmp_path: Path, sleeps: list[float]) -> None:
    root = tmp_path / "store"
    root.mkdir()
    (root / "records.sqlite").write_bytes(b"not a database" * 100)
    with pytest.raises(StoreError, match="Disk cache could not be opened"):
        CacheStore(str(root))
    assert sleeps == []


def test_an_attempt_that_failed_after_opening_closes_its_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float],
) -> None:
    CacheStore(str(tmp_path / "store")).close()  # Exists, so _open probes it first.
    opened: list[Any] = []
    original = CacheStore._open

    def open_(self: CacheStore, busy_timeout: float) -> sqlite3.Connection:
        conn = original(self, busy_timeout)
        opened.append(conn)
        return conn
    failures = [io_error()]

    def meta(self: CacheStore) -> dict[str, Any]:
        if failures:
            raise failures.pop()
        return original_meta(self)
    original_meta = CacheStore._meta
    monkeypatch.setattr(CacheStore, "_open", open_)
    monkeypatch.setattr(CacheStore, "_meta", meta)
    with CacheStore(str(tmp_path / "store")) as store:
        assert store.store_id
    with pytest.raises(sqlite3.ProgrammingError):  # The first attempt's connection is closed.
        opened[0].execute("SELECT 1")


@pytest.mark.parametrize(("error", "message"), [
    (StoreError("Disk cache could not be opened: disk I/O error"), "Disk cache could not be opened: disk I/O error"),
    (StoreError("Mount information is unavailable: no mounts"),
     "Disk cache could not be opened: Mount information is unavailable: no mounts"),
    (PermissionError("denied"), "Disk cache could not be opened: denied"),
], ids=["the store's own", "another store error", "an OS error"])
def test_the_warning_says_could_not_be_opened_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception, message: str,
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> CacheStore:
        raise error
    monkeypatch.setattr(stores, "_cache_store", refuse)
    events: list[Any] = []
    assert stores._store_or_off({"directory": str(tmp_path)}, events.append, str(tmp_path)) == (None, False)
    assert events == [{"kind": "cache_warning", "message": message}]


@pytest.mark.parametrize(("error", "message"), [
    (sqlite3.OperationalError("unable to open database file"),
     "Disk cache could not be opened: unable to open database file"),
    (PermissionError("denied"), "Disk cache could not be opened: denied"),
], ids=["sqlite", "an OS error"])
@pytest.mark.no_auto_data_root  # (Its seeding would open the store first.)
def test_a_store_that_cant_be_opened_is_not_reported_as_mount_information(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception, message: str,
) -> None:
    """The store's own open error passes through ``_cache_store`` as it is: "Mount information is
    unavailable" is only for the mount table and volume steps."""
    def refuse(self: CacheStore, busy_timeout: float) -> sqlite3.Connection:
        raise error
    monkeypatch.setattr(CacheStore, "_open", refuse)
    events: list[Any] = []
    assert stores._store_or_off({"directory": str(tmp_path / "store")}, events.append, str(tmp_path)) == (
        None, False)
    assert events == [{"kind": "cache_warning", "message": message}]
