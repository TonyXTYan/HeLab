"""HeLab's log file, and its catch for unhandled exceptions (``main`` starts both).

Without an excepthook, PyQt6 ends the app on an exception in a slot or a model's ``data()``; with
``catch_unhandled`` it is logged with its traceback and HeLab carries on. The packaged app has no
console, so the log file in the app folder is where such an error leaves its trace.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
import re
import sys
import threading
import time
from types import TracebackType
from typing import Callable

from helab.utils.cache_locks import other_instances


# Each HeLab writes its own file, helab-<process ID>.log (Tony, 2026-10-22): two at once never share
# one, whose rollover on Windows would fail in the other. It grows to LOG_BYTES, then is renamed
# helab-<pid>.log.1 (and so on, LOG_BACKUPS of them). Old sessions' files go at startup: the oldest
# beyond Settings → General → Log files to keep, and past ASK_BYTES the user is asked
# (``helab.views.OldLogs``; Tony, 2026-10-22).
MB = 1000 * 1000  # SI, as every size HeLab shows (Tony, 2026-10-26)
LOG_NAME = "helab-{pid}.log"
LOG_FILE = re.compile(r"helab-(\d+)\.log(\.\d+)?")  # Rotated copies too; the group is the pid.
LOG_BYTES = 1 * MB
LOG_BACKUPS = 10
# Past ASK_BYTES of logs (after the count rule) the user is asked, and Delete goes below TRIM_BYTES.
ASK_BYTES = 50 * MB
TRIM_BYTES = 20 * MB
# A file modified this recently is never deleted: a HeLab starting up writes its log before it holds
# its instance lock (``cache_locks.instance_lock``).
STARTING_SECONDS = 60.0
LOG_FORMAT = "%(asctime)s %(levelname)s [%(process)d %(threadName)s] %(name)s: %(message)s"
# The same unhandled exception (its type and where it was raised) is logged once in this time, and
# the repeats are counted in the next one logged: a model's ``data()`` may raise on every repaint.
REPEAT_SECONDS = 60.0
# Milestones: one INFO line when a long step ends (a folder loaded, a plot computed, a conversion
# finished), for a runner (a smoke pass, computer use) to wait on in the log file:
#     ... INFO [4242 MainThread] helab.milestone: MILESTONE load_done folder="/a b/c" shots=3 seconds=1.250
# ``milestone`` writes every one and ``parse_milestone`` reads them back, so the form can't drift.
MILESTONE = "MILESTONE"
MILESTONE_LOGGER = "helab.milestone"
_BARE = re.compile(r"[A-Za-z0-9_.:/+-]+")
_INT = re.compile(r"-?\d+")
_FLOAT = re.compile(r"-?\d+\.\d+")
_LITERALS: dict[str, bool | None] = {"true": True, "false": False, "null": None}
_VALUE = r'"(?:[^"\\]|\\.)*"|[^\s"]+'
_FIELD = re.compile(rf"([a-z][a-z0-9_]*)=({_VALUE})")
# The message alone, or a log line whose logger is ``helab.milestone``: never another line that
# happens to hold the word (a folder named ".../MILESTONE load_done"). Every field, nothing between.
_MILESTONE_LINE = re.compile(rf"(?:^|\s{re.escape(MILESTONE_LOGGER)}: ){MILESTONE} ([a-z][a-z0-9_]*)"
                             rf"((?: [a-z][a-z0-9_]*=(?:{_VALUE}))*)$")
# What ``str.splitlines`` breaks a line at beyond what JSON escapes: escaped too, so a value never
# splits the log line.
_LINE_BREAKS = {0x85: "\\u0085", 0x2028: "\\u2028", 0x2029: "\\u2029"}

MilestoneValue = str | int | float | bool | None

_notice: Callable[[str], None] | None = None
_seen: dict[tuple[str, str, int], tuple[float, int]] = {}  # (When last logged, repeats since.)
_lock = threading.Lock()


def log_folder(folder: str) -> str:
    """Where the log files are, in the app folder ``folder``."""
    return os.path.join(folder, "logs")


def start_log_file(folder: str, level: int = logging.INFO) -> RotatingFileHandler | None:
    """Log to ``<folder>/logs/helab-<pid>.log`` as well (``app_folder()``; tests' own folder), from
    ``level`` up. Its handler, or None if it can't be written there (logged)."""
    path = os.path.join(log_folder(folder), LOG_NAME.format(pid=os.getpid()))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=LOG_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8")
    except OSError as exc:
        logging.warning(f"No log file: {path} could not be written: {exc}")
        return None
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(handler)
    logging.info(f"Logging to {path}")
    return handler


def milestone(event: str, **fields: MilestoneValue) -> str:
    """Log the milestone ``event`` (``load_done``…) with ``fields`` in the order given, one INFO line
    on ``helab.milestone``: ``MILESTONE <event> key=value…``. Integers as they are, floats to 3
    decimals, ``true``/``false``/``null``; a string bare when it is plain (``_BARE``) and can't be
    read as another type, JSON-quoted otherwise. Memory only, from any thread. The line's message."""
    message = " ".join([MILESTONE, event, *(f"{key}={_milestone_value(value)}" for key, value in fields.items())])
    logging.getLogger(MILESTONE_LOGGER).info("%s", message)
    return message


def _milestone_value(value: MilestoneValue) -> str:
    if value is None or isinstance(value, bool):
        return {None: "null", True: "true", False: "false"}[value]
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.3f}" if math.isfinite(value) else "null"
    if _BARE.fullmatch(value) and value not in _LITERALS and not _FLOAT.fullmatch(value) and not _INT.fullmatch(value):
        return value
    return json.dumps(value, ensure_ascii=False).translate(_LINE_BREAKS)


def parse_milestone(line: str) -> tuple[str, dict[str, MilestoneValue]] | None:
    """A milestone (``milestone``'s message, or its line in the log file) as its event and fields,
    typed back; None for any other line, or one not wholly in that form."""
    match = _MILESTONE_LINE.search(line.rstrip("\r\n"))
    if match is None:
        return None
    fields: dict[str, MilestoneValue] = {}
    for key, text in _FIELD.findall(match.group(2)):
        value: MilestoneValue
        if text.startswith('"'):
            value = str(json.loads(text))
        elif text in _LITERALS:
            value = _LITERALS[text]
        elif _INT.fullmatch(text):
            value = int(text)
        elif _FLOAT.fullmatch(text):
            value = float(text)
        else:
            value = text
        fields[key] = value
    return match.group(1), fields


@dataclass(frozen=True)
class LogFile:
    path: str
    pid: int
    size: int
    mtime: float


def scan_logs(folder: str) -> list[LogFile]:
    """Every log file, rotated copies included, of every session, in the app folder ``folder``.
    Never on the GUI thread (``OldLogs``)."""
    files: list[LogFile] = []
    try:
        entries = list(os.scandir(log_folder(folder)))
    except OSError:  # (None yet, or unreadable: nothing to tidy.)
        return []
    for entry in entries:
        match = LOG_FILE.fullmatch(entry.name)
        if match is None:
            continue
        try:
            stat = entry.stat(follow_symlinks=False)
        except OSError:  # (Gone meanwhile.)
            continue
        files.append(LogFile(entry.path, int(match.group(1)), stat.st_size, stat.st_mtime))
    return files


def deletable(folder: str, files: list[LogFile]) -> list[LogFile]:
    """``files`` that may go, oldest first by mtime (process IDs come round again, so never by name):
    not a running HeLab's (``cache_locks.other_instances``, this one's) and not one just written."""
    running = set(other_instances(folder)) | {os.getpid()}
    recent = time.time() - STARTING_SECONDS
    return sorted((file for file in files if file.pid not in running and file.mtime < recent),
                  key=lambda file: (file.mtime, file.path))


def delete_logs(files: list[LogFile]) -> list[LogFile]:
    """Delete ``files``; those deleted. One that can't be (on Windows, open in another process) is
    skipped and logged."""
    deleted: list[LogFile] = []
    for file in files:
        try:
            os.remove(file.path)
        except FileNotFoundError:
            deleted.append(file)  # (Another HeLab got there first.)
        except OSError as exc:
            logging.info(f"Old log file {file.path} not deleted: {exc}")
        else:
            deleted.append(file)
    if deleted:
        logging.info(f"Deleted {len(deleted)} old log file(s), {sum(file.size for file in deleted) / MB:.1f} MB")
    return deleted


def tidy_logs(folder: str, keep: int) -> int:
    """At startup: delete the oldest log files beyond ``keep`` of them (Settings → General → Log
    files to keep, which counts every session's files), not a running HeLab's. The bytes of logs
    left."""
    files = scan_logs(folder)
    gone = delete_logs(deletable(folder, files)[:max(0, len(files) - keep)])
    return sum(file.size for file in files) - sum(file.size for file in gone)


def trim_logs(folder: str, below: int = TRIM_BYTES) -> int:
    """Delete the oldest log files, not a running HeLab's, until they total under ``below`` bytes
    (the user said Delete). The bytes left."""
    files = scan_logs(folder)
    total = sum(file.size for file in files)
    chosen: list[LogFile] = []
    left = total
    for file in deletable(folder, files):
        if left < below:
            break
        chosen.append(file)
        left -= file.size
    return total - sum(file.size for file in delete_logs(chosen))


def catch_unhandled(notice: Callable[[str], None] | None = None) -> None:
    """Log every unhandled exception, on any thread, with its traceback, and carry on. One on the
    GUI thread is also shown with ``notice`` (the window's status bar). Called again, the new
    ``notice`` replaces the old one."""
    global _notice
    _notice = notice
    sys.excepthook = _unhandled
    threading.excepthook = _unhandled_in_thread


def _unhandled(kind: type[BaseException], value: BaseException, traceback: TracebackType | None) -> None:
    if issubclass(kind, KeyboardInterrupt):
        sys.__excepthook__(kind, value, traceback)
        return
    if not _log(kind, value, traceback, "Unhandled exception") or _notice is None:
        return
    if threading.current_thread() is threading.main_thread():
        try:
            _notice(f"Unexpected error, logged: {kind.__name__}: {value}")
        except Exception:  # (The window may be gone.)
            logging.exception("An unhandled exception couldn't be shown in the status bar")


def _unhandled_in_thread(args: threading.ExceptHookArgs) -> None:
    if args.exc_type is SystemExit:
        return  # (Ends the thread quietly, as by default.)
    name = args.thread.name if args.thread is not None else "?"
    _log(args.exc_type, args.exc_value, args.exc_traceback, f"Unhandled exception in thread {name}")


def _log(kind: type[BaseException], value: BaseException | None, traceback: TracebackType | None,
         what: str) -> bool:
    """Log it, unless the same one was logged within REPEAT_SECONDS; whether it was logged."""
    last = traceback
    while last is not None and last.tb_next is not None:
        last = last.tb_next
    key = (kind.__name__, last.tb_frame.f_code.co_filename if last else "", last.tb_lineno if last else 0)
    now = time.monotonic()
    with _lock:
        logged_at, repeats = _seen.get(key, (-math.inf, 0))
        if now - logged_at < REPEAT_SECONDS:
            _seen[key] = (logged_at, repeats + 1)
            return False
        _seen[key] = (now, 0)
    more = f" ({repeats} more like it not logged)" if repeats else ""
    logging.error(f"{what}{more}: {kind.__name__}: {value}",
                  exc_info=(kind, value, traceback) if value is not None else None)
    return True
