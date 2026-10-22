"""HeLab's log file, and its catch for unhandled exceptions (``main`` starts both).

Without an excepthook, PyQt6 ends the app on an exception in a slot or a model's ``data()``; with
``catch_unhandled`` it is logged with its traceback and HeLab carries on. The packaged app has no
console, so the log file in the app folder is where such an error leaves its trace.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import math
import os
import sys
import threading
import time
from types import TracebackType
from typing import Callable


LOG_NAME = "helab.log"
# The log file grows to LOG_BYTES, then is renamed helab.log.1 (and so on, LOG_BACKUPS of them).
LOG_BYTES = 2 * 1024 * 1024
LOG_BACKUPS = 4
LOG_FORMAT = "%(asctime)s %(levelname)s [%(process)d %(threadName)s] %(name)s: %(message)s"
# The same unhandled exception (its type and where it was raised) is logged once in this time, and
# the repeats are counted in the next one logged: a model's ``data()`` may raise on every repaint.
REPEAT_SECONDS = 60.0

_notice: Callable[[str], None] | None = None
_seen: dict[tuple[str, str, int], tuple[float, int]] = {}  # (When last logged, repeats since.)
_lock = threading.Lock()


def start_log_file(folder: str, level: int = logging.INFO) -> RotatingFileHandler | None:
    """Log to ``<folder>/logs/helab.log`` as well (``app_folder()``; tests' own folder), from
    ``level`` up. Its handler, or None if it can't be written there (logged)."""
    path = os.path.join(folder, "logs", LOG_NAME)
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
