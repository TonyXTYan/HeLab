"""Quit that confirms (roadmaps/smoke-automation.md, item 6): once HeLab's event loop has ended (File ›
Quit, the window's close button, Cmd+Q, after the quit window if anything was still being saved),
the process ends within ``GRACE`` seconds. Python's own teardown can outlive the windows (a thread
that isn't a daemon, a library's exit handler, a stuck helper pipe), and a HeLab with no windows left
still holds its instance lock and its bundle ID, so a second HeLab started meanwhile would share
them (known-issues: "File › Quit sometimes left the process running"). ``exit_soon`` waits ``GRACE``
on a daemon thread; if the process is still there, it logs what is still running and ends it with
the same exit code. Saves never reach this point: quitting waits for them in the quit window first
(``QuitSaveDialog``, the last uses' flush included, ~5 s without progress at most), and Quit now skips
them. Standard library only: no Qt, no helab.utils.constants."""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback
from typing import Callable

GRACE = 1.0  # Seconds after the event loop ends.


def still_running() -> str:
    """The threads still alive, each with its stack (the main thread's too): why teardown lingers."""
    frames = sys._current_frames()
    lines = []
    for thread in threading.enumerate():
        frame = frames.get(thread.ident or -1)
        stack = "".join(traceback.format_stack(frame)) if frame is not None else ""
        lines.append(f"{thread.name} (daemon={thread.daemon}):\n{stack}")
    return "\n".join(lines)


def exit_soon(code: int, grace: float = GRACE, exit: Callable[[int], object] = os._exit) -> threading.Thread:
    """End the process with ``code`` ``grace`` seconds from now unless it has ended by then (a daemon
    thread, so it never itself keeps the process alive). The thread, for tests."""
    def watch() -> None:
        time.sleep(grace)
        logging.warning("HeLab was still running %.1f s after its windows closed; ending it (exit code %d). "
                        "Still running:\n%s", grace, code, still_running())
        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception:  # A handler that can't flush doesn't stop the exit.
                pass
        exit(code)

    thread = threading.Thread(target=watch, name="HeLab-quit-watch", daemon=True)
    thread.start()
    return thread
