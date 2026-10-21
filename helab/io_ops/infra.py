"""Shared helper infrastructure: test seams, the I/O trace, traced source-folder calls, events,
cooperative pausing and heartbeats.

The helper's mutable process state (the trace file and request, the volume-ID cache, ``Pause``)
lives here only: ``helab.io_helper`` may run as ``__main__``, and nothing in ``helab.io_ops``
imports it.
"""
from __future__ import annotations

import contextlib
import errno
import functools
import json
import os
import sys
import time
from typing import Any, Callable, Iterator, TYPE_CHECKING

from helab.io_ops.events import HelperEvent

if TYPE_CHECKING:
    from helab.utils.cache_paths import Mount
    from helab.utils.data_roots import Marker


Emit = Callable[[HelperEvent], None]


# Test seam: with HELAB_TEST_READ_GATE=<dir>, reading a TXY file <name> first waits until
# <dir>/<name>.go exists (``_read_gate``). Unset in production: nothing is checked.
READ_GATE = os.environ.get("HELAB_TEST_READ_GATE") or None
READ_GATE_POLL = 0.02


def _read_gate(filename: str) -> None:
    """Tests only (``READ_GATE``): hold this TXY read until its ``<name>.go`` file appears. It
    sends nothing meanwhile, like a read still in progress, so a gate never opened stands in
    for a stuck read (the parent's per-file timeout stops it)."""
    if READ_GATE is None:
        return
    go = os.path.join(READ_GATE, os.path.basename(filename) + ".go")
    while not os.path.exists(go):
        time.sleep(READ_GATE_POLL)


# Test seam: with HELAB_TEST_SOURCE_GUARD=<dir> (tests/conftest.py), tests never touch real data. A
# source path on a mounted volume or share, in cloud storage or in one of the developers' data folders
# (``constants.DEV_POTENTIAL_DATA_PATHS``) is refused before it is touched (``SourceRefused``) unless
# it is inside the temp folder or this checkout, and noted in <dir>/<pid>.txt, which fails the test.
# Decided by the path's text alone: resolving it would touch it. Unset in production: nothing is checked.
SOURCE_GUARD = os.environ.get("HELAB_TEST_SOURCE_GUARD") or None
MOUNT_TOPS = ("/Volumes", "/Network", "/net", "/media", "/mnt", "/run/media")  # Anything below is a mount


class SourceRefused(PermissionError):
    """A test's source path that could be real data (``SOURCE_GUARD``): refused, never touched."""


def _normal(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _within(path: str, folder: str) -> bool:
    """Whether ``path`` is ``folder`` or inside it (normalised paths; different drives: not)."""
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:
        return False


@functools.cache
def _guard_rules() -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """(allowed, denied, mount tops): inside an allowed folder is always fine; a denied folder and
    anything inside it is refused, as is anything below a mount top (the top itself is fine)."""
    import tempfile
    from helab.utils.constants import DEV_POTENTIAL_DATA_PATHS
    temp = tempfile.gettempdir()
    checkout = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    allowed = tuple(dict.fromkeys(_normal(path) for path in (temp, os.path.realpath(temp), checkout)))
    data = [_normal(path) for path in DEV_POTENTIAL_DATA_PATHS if path]
    denied = tuple(path for path in data if not any(_within(path, folder) for folder in allowed))
    tops = [*MOUNT_TOPS, os.path.expanduser("~/Library/CloudStorage")] if sys.platform != "win32" else []
    return allowed, denied, tuple(_normal(top) for top in tops)


def _guard(path: str) -> None:
    """Under tests (``SOURCE_GUARD``), refuse ``path`` if it could be real data; else nothing."""
    if SOURCE_GUARD is None or not path:
        return
    target = _normal(path)
    allowed, denied, tops = _guard_rules()
    if any(_within(target, folder) for folder in allowed):
        return
    if sys.platform == "win32":
        drives = {os.path.splitdrive(folder)[0] for folder in allowed}
        refused = target.startswith("\\\\") or os.path.splitdrive(target)[0] not in drives
    else:
        refused = any(_within(target, top) and target != top for top in tops)
    if not (refused or any(_within(target, folder) for folder in denied)):
        return
    try:
        with open(os.path.join(SOURCE_GUARD, f"{os.getpid()}.txt"), "a", encoding="utf-8") as note:
            note.write(path + "\n")
    except OSError:
        pass
    raise SourceRefused(errno.EACCES, "Tests never touch real data", path)


# The I/O trace (Help › Record I/O trace, this session): every operation a helper makes on a source
# folder is appended to its own file in the recording's folder as one JSON line (``_trace``), with the
# request it serves. The app sends the folder with each request while the trace is on
# (``IOService.trace_dir``); test seam: HELAB_TEST_IO_TRACE=<folder> traces every helper. Off: nothing
# is written, and the wrappers below make the same calls as untraced code.


def _trace_path(folder: str | None) -> str | None:
    """This helper's file in a recording's ``folder``: one writer per file (Windows' C runtime emulates
    O_APPEND with a seek and a write, so helpers sharing a file could overwrite each other's lines). A
    PID reused later appends after the earlier helper's lines; it has exited by then."""
    return os.path.join(folder, f"{os.getpid()}.jsonl") if folder else None


TRACE = _trace_path(os.environ.get("HELAB_TEST_IO_TRACE"))
# This helper's request, on every line (``main``): its operation, owner and tabs, lane, flags.
_trace_request: dict[str, Any] = {}
_trace_fd: int | None = None


def _trace(op: str, path: str, reason: str, **fields: Any) -> None:
    """Append one line to this helper's trace file (``TRACE``), in one write; a line that can't be
    written is skipped."""
    global _trace_fd
    if TRACE is None:
        return
    line = json.dumps({"t": time.time(), "pid": os.getpid(), "op": op, "path": path, "reason": reason,
                       **_trace_request, **fields}, ensure_ascii=True, default=str) + "\n"
    try:
        if _trace_fd is None:
            _trace_fd = os.open(TRACE, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
        os.write(_trace_fd, line.encode("ascii"))
    except OSError:
        pass


def _start_trace(request: dict[str, Any]) -> None:
    """Trace into the recording folder the app sent, if any; note the request every trace line serves,
    and that this helper started."""
    global TRACE
    note = request.get("trace")
    if isinstance(note, dict) and note.get("dir"):
        TRACE = _trace_path(str(note["dir"]))
    if TRACE is None:
        return
    operation = str(request.get("operation", ""))
    flags = [key for key in TRACE_FLAGS if request.get(key)]
    _trace_request.update(request="live" if operation == "load" and request.get("live") else operation,
                          target=request.get("path", ""), flags=flags)
    if isinstance(note, dict):
        _trace_request.update({key: value for key, value in note.items() if key != "dir"})
    if request.get("memory"):
        _trace_request["held"] = len(request["memory"])
    _trace("request", str(request.get("path", "")), operation)


def _end_trace(started: float, error: str = "") -> None:
    """Note that this helper's request ended (``error``: why it failed)."""
    if TRACE is not None:
        _trace("request_end", str(_trace_request.get("target", "")), str(_trace_request.get("request", "")),
               seconds=round(time.monotonic() - started, 6), **({"error": error} if error else {}))


# Request fields that say why it was asked for (the app's payload), copied to every trace line.
TRACE_FLAGS = ("automatic", "scan_manual", "metadata_only", "listing_only", "revalidate", "refresh_sequence",
               "save", "cache_base", "full_check", "allow_missing", "deliberate", "no_cache", "live_since")


def _traced_error(op: str, path: str, reason: str, exc: BaseException) -> None:
    _trace(op, path, reason, error=type(exc).__name__)


def _stat(path: str, reason: str, *, follow_symlinks: bool = True) -> os.stat_result:
    """``os.stat`` of a source path, traced."""
    _guard(path)
    if TRACE is None:
        return os.stat(path) if follow_symlinks else os.stat(path, follow_symlinks=False)
    op = "stat" if follow_symlinks else "lstat"
    try:
        info = os.stat(path) if follow_symlinks else os.stat(path, follow_symlinks=False)
    except OSError as exc:
        _traced_error(op, path, reason, exc)
        raise
    _trace(op, path, reason, size=info.st_size, mtime_ns=info.st_mtime_ns)
    return info


def _lstat(path: str, reason: str) -> os.stat_result:
    """``os.lstat`` of a source path, traced."""
    _guard(path)
    if TRACE is None:
        return os.lstat(path)
    try:
        info = os.lstat(path)
    except OSError as exc:
        _traced_error("lstat", path, reason, exc)
        raise
    _trace("lstat", path, reason, size=info.st_size, mtime_ns=info.st_mtime_ns)
    return info


def _isdir(path: str, reason: str) -> bool:
    """``os.path.isdir`` of a source path (one stat), traced."""
    _guard(path)
    found = os.path.isdir(path)
    if TRACE is not None:
        _trace("stat", path, reason, isdir=found)
    return found


def _entry_stat(entry: os.DirEntry[str], reason: str) -> os.stat_result:
    """A listed entry's ``stat()``, traced. One more call on macOS and Linux; on Windows the
    listing already has it (``syscall`` False), unless the entry is a link (not probed: asking
    would be a call the untraced helper doesn't make)."""
    _guard(entry.path)
    if TRACE is None:
        return entry.stat()
    syscall = sys.platform != "win32"
    try:
        info = entry.stat()
    except OSError as exc:
        _trace("entry_stat", entry.path, reason, error=type(exc).__name__, syscall=syscall)
        raise
    _trace("entry_stat", entry.path, reason, size=info.st_size, mtime_ns=info.st_mtime_ns, syscall=syscall)
    return info


class _TracedListing:
    """``os.scandir`` of a source folder, traced: one line when it ends, with its entry count and
    how many entries were asked ``is_dir`` (``_is_dir``)."""
    current: _TracedListing | None = None

    def __init__(self, path: str, reason: str) -> None:
        self.path, self.reason, self.count, self.dir_checks = path, reason, 0, 0
        self.started = time.monotonic()
        try:
            self.directory = os.scandir(path)
        except OSError as exc:
            _traced_error("scandir", path, reason, exc)
            raise

    def __enter__(self) -> Iterator[os.DirEntry[str]]:
        _TracedListing.current = self
        return self._entries()

    def _entries(self) -> Iterator[os.DirEntry[str]]:
        for entry in self.directory:
            self.count += 1
            yield entry

    def __exit__(self, kind: type[BaseException] | None, *_: object) -> None:
        self.directory.close()
        _TracedListing.current = None
        _trace("scandir", self.path, self.reason, entries=self.count, is_dir=self.dir_checks,
               seconds=round(time.monotonic() - self.started, 6),
               **({"error": kind.__name__} if kind is not None and issubclass(kind, OSError) else {}))


def _scandir(path: str, reason: str) -> contextlib.AbstractContextManager[Iterator[os.DirEntry[str]]]:
    """``os.scandir`` of a source folder, traced."""
    _guard(path)
    return os.scandir(path) if TRACE is None else _TracedListing(path, reason)


def _is_dir(entry: os.DirEntry[str]) -> bool:
    """A listed entry's ``is_dir(follow_symlinks=False)``, counted on its listing's trace line. The
    listing's file type answers it (macOS, Linux, Windows); a call only where the file system
    doesn't report types."""
    if TRACE is not None and _TracedListing.current is not None:
        _TracedListing.current.dir_checks += 1
    return entry.is_dir(follow_symlinks=False)


def _read_marker(folder: str, reason: str) -> Marker:
    """``data_roots.read_marker`` of the folder's ``.helab-root``, traced step by step:
    ``marker_open``, ``marker_fstat``, ``marker_read`` (bytes); a failure after a step is
    ``marker_error`` (``after`` it), and a failed open is ``marker_open`` with its error."""
    from helab.utils import data_roots
    _guard(folder)
    if TRACE is None:
        return data_roots.read_marker(folder)
    path = os.path.join(folder, data_roots.MARKER_NAME)
    steps: list[str] = []

    def step(name: str, fields: dict[str, object]) -> None:
        steps.append(name)
        _trace(f"marker_{name}", path, reason, **fields)
    try:
        return data_roots.read_marker(folder, trace=step)
    except (OSError, ValueError) as exc:
        if steps:
            _trace("marker_error", path, reason, error=type(exc).__name__, after=steps[-1])
        else:
            _traced_error("marker_open", path, reason, exc)
        raise


def _read_txy_file(filename: str, reason: str) -> Any:
    """A whole TXY file, parsed: read in one go, then ``pandas.read_csv`` of its bytes. Traced with the
    bytes actually read (``read``). (Its content isn't checked for a writer still at work: settled by
    age, it's read as it is, by Tony's decision; see ``SETTLE_SECONDS``.)"""
    import io
    import numpy as np
    import pandas as pd
    _guard(filename)
    try:
        with open(filename, "rb") as stream:
            raw = stream.read()
    except OSError as exc:
        _traced_error("read", filename, reason, exc)
        raise
    _trace("read", filename, reason, bytes=len(raw))
    # pandas would take a row's extra leading numbers as its index, silently shifting t, x and y,
    # so a file whose rows have more than three numbers fails as unreadable (a later row with more
    # than the first already does). Shorter rows read as NaN, which the callers drop and flag.
    first = next((part for line in io.BytesIO(raw) for part in line.split(b"\r") if part.strip()), b"")
    if (fields := first.count(b",") + 1) > 3:
        raise ValueError(f"TXY rows have 3 numbers (t, x, y); this file's first row has {fields}")
    return pd.read_csv(io.BytesIO(raw), sep=",", names=["t", "x", "y"], dtype=np.float64)


def _mounts(reason: str) -> list[Mount]:
    """The mount table (``cache_paths.current_mounts``): the OS's list of mounts, which asks no
    source folder or server (psutil's getfsstat without waiting; Windows' drive types and mapped
    drives). Traced for completeness."""
    from helab.utils import cache_paths
    mounts = cache_paths.current_mounts()
    if TRACE is not None:
        _trace("mounts", "", reason, count=len(mounts))
    return mounts


# One helper handles one request. Reusing a volume ID within that request avoids
# repeated diskutil calls during discovery and listing without persisting stale IDs.
_volume_id_cache: dict[tuple[str, str], str | None] = {}


def _cached_volume_id(mount: Any) -> str | None:
    from helab.utils.data_roots import _volume_id
    key = (str(mount.path), str(mount.source))
    if key not in _volume_id_cache:
        _volume_id_cache[key] = _volume_id(mount)
        # (Local volumes only: shares are keyed by server and share, never by a volume ID.)
        _trace("volume_id", str(mount.path), "location key")
    return _volume_id_cache[key]


def emit(event: HelperEvent) -> None:
    print(json.dumps(event, ensure_ascii=True), flush=True)


class Pause:
    """Cooperative pause: the parent creates ``pause`` in the request's private
    folder while the current tab browses or loads, and removes it to resume.

    Checked between files and entries, so a call already in progress finishes.
    """
    CHECK_INTERVAL = 0.02
    POLL = 0.05
    flag: str | None = None
    last_check = 0.0

    @classmethod
    def configure(cls, control: str | None) -> None:
        cls.flag = os.path.join(control, "pause") if control else None
        cls.last_check = 0.0

    @classmethod
    def checkpoint(cls, send: Emit) -> None:
        now = time.monotonic()
        if cls.flag is None or now - cls.last_check < cls.CHECK_INTERVAL:
            return
        cls.last_check = now
        if not os.path.exists(cls.flag):
            return
        send({"kind": "paused"})
        while os.path.exists(cls.flag):
            time.sleep(cls.POLL)
        send({"kind": "resumed"})


class Heartbeat:
    """Tell the parent a slow listing is still progressing (resets its no-progress timer)."""
    INTERVAL = 1.0

    def __init__(self, send: Emit, phase: str) -> None:
        self.send, self.phase, self.count = send, phase, 0
        self.last = time.monotonic()

    def __call__(self, count: int = 1) -> None:
        Pause.checkpoint(self.send)
        self.count += count
        now = time.monotonic()
        if now - self.last >= self.INTERVAL:
            self.send({"kind": "heartbeat", "phase": self.phase, "entries": self.count})
            self.last = now
