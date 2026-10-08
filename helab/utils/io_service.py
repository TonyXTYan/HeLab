"""Bounded process I/O with nonblocking delivery to the GUI thread."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
import logging
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Iterator, TYPE_CHECKING

from PyQt6.QtCore import QCoreApplication, QObject, QTimer, pyqtSignal

from helab.utils.constants import MAX_SIMULTANEOUS_IO
from helab.utils.time_format import duration

if TYPE_CHECKING:
    from helab.utils.folder_cache import FolderCache


@dataclass(eq=False)
class IORequest:
    owner: str
    generation: int
    path: str
    operation: str
    payload: dict[str, Any]
    timeout: float
    cancelled: threading.Event = field(default_factory=threading.Event)
    process: subprocess.Popen[str] | None = None
    started: float = 0.0
    output: str | None = None
    attempt: int = 1
    completed: bool = False
    last_activity: float = 0.0
    current_file: str | None = None
    file_attempts: dict[str, int] = field(default_factory=dict)
    priority: bool = False
    retirement_reason: str = ""
    retired_at: float | None = None
    exited: threading.Event = field(default_factory=threading.Event)
    # "foreground" (the current tab's browsing and selected load) or "background", set at dispatch.
    lane: str = ""
    # Cooperative pause: a ``pause`` file in ``output`` that the helper polls.
    pause_requested: bool = False
    paused: bool = False
    slow_stop_logged: bool = False
    control: threading.Lock = field(default_factory=threading.Lock)


FOREGROUND = "foreground"
BACKGROUND = "background"
# Reads of the local disk cache only; they never touch source folders.
LOCAL = "local"
REQUEUED = "moved to the background queue"


class IOService(QObject):
    resultReady = pyqtSignal(object, object)
    activityChanged = pyqtSignal()
    MAX_PENDING = 128
    MAX_RETIRED = 2
    # Per-file read attempts for loads; the next file gets a fresh budget.
    TIMEOUTS: tuple[float, ...] = (15.0, 20.0, 30.0)
    # Listings, scans and a load's listing phase: one attempt, no retry.
    # Helper heartbeats reset it, so a slow but progressing folder never times out.
    NO_PROGRESS_TIMEOUT = 60.0
    # Compressing a large dataset into the disk cache sends no progress.
    FINISH_TIMEOUT = 120.0
    # A killed helper normally exits at once; longer means it is stuck in a filesystem call.
    SLOW_STOP_SECONDS = 5.0
    # The foreground lane runs the current tab's listing and selected load beside
    # the background lanes, up to this many processes including stopping ones.
    FOREGROUND_CAP = 3
    # A listing silent this long no longer holds the listing slot or pauses others:
    # pausing cannot help a hung volume.
    STALLED_LISTING = 3.0
    # Paused work resumes this long after the foreground goes idle, so consecutive
    # expands do not stop and start it.
    RESUME_DELAY = 0.5
    LISTINGS = ("list", "resolve")
    # Operations in the local lane: they never wait for or pause with source-folder I/O.
    LOCAL_OPERATIONS = ("cached",)
    LOCAL_CAP = 2
    PAUSABLE = ("load", "list", "details", "scan", "icons")
    LABELS = {"load": "Load data", "cached": "Read cached data", "list": "Browse folder", "details": "Folder details",
              "scan": "Check folder status", "resolve": "Browse folder", "invalidate": "Clear data cache",
              "scan_history": "Save scan history", "icons": "Folder icons"}
    NOUNS = {"load": "load", "cached": "cached data read", "list": "folder listing", "details": "folder details scan",
             "scan": "folder status check", "resolve": "folder lookup", "invalidate": "cache clear",
             "scan_history": "scan-history save", "icons": "folder icon lookup"}

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pending: deque[IORequest] = deque()
        self.active: list[IORequest] = []
        self.retired: list[IORequest] = []
        self.messages: queue.Queue[tuple[IORequest, dict[str, Any]]] = queue.Queue(maxsize=256)
        self.closed = False
        self.folder_cache: FolderCache | None = None
        self.max_operations = 1
        # Set by FolderCache: whether a request is the current tab's browsing or selected load.
        self.is_foreground: Callable[[IORequest], bool] = lambda request: False
        self._foreground_busy_at = -math.inf
        self._listing_busy_at = -math.inf
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(20)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    def submit(self, owner: str, generation: int, path: str, operation: str,
               payload: dict[str, Any] | None = None, *, priority: bool = False,
               timeout: float | None = None) -> bool:
        """Queue a helper; ``timeout`` is seconds without progress (``math.inf``: none)."""
        if self.closed:
            return False
        if any((r.owner, r.generation, r.path, r.operation) == (owner, generation, path, operation)
               for r in (*self.active, *self.pending)):
            return True
        # Reserve pending capacity for active requests that may need a retry.
        if len(self.pending) + len(self.active) >= self.MAX_PENDING:
            logging.warning("I/O queue full (%s requests); not queued: %s %s",
                            self.MAX_PENDING, self.NOUNS.get(operation, operation), path)
            return False
        request = IORequest(owner, generation, path, operation, payload or {},
                            self.NO_PROGRESS_TIMEOUT if timeout is None else timeout,
                            priority=priority or operation == "load")
        # Navigation and loads precede bulk scans, with FIFO within each group.
        if request.priority:
            index = next((i for i, r in enumerate(self.pending) if not r.priority), len(self.pending))
            self.pending.insert(index, request)
        else:
            self.pending.append(request)
        self.resultReady.emit(request, {"kind": "queued", "attempt": request.attempt})
        self._dispatch()
        self.activityChanged.emit()
        return True

    @staticmethod
    def finishing(request: IORequest) -> bool:
        """A load that delivered its data and may still be writing the disk cache."""
        return request.operation == "load" and request.completed

    def set_timeout(self, owner: str, timeout: float) -> None:
        """Change the no-progress limit of an owner's queued and running requests."""
        for request in (*self.pending, *self.active):
            if request.owner == owner and not request.completed:
                request.timeout = timeout

    @staticmethod
    def retries(request: IORequest) -> bool:
        """Only a load's per-file reads are retried; a stalled listing is not."""
        return request.operation == "load" and request.current_file is not None

    def configure_concurrency(self, operations: int) -> None:
        """Apply shared limits without interrupting already running helpers."""
        self.max_operations = max(1, min(MAX_SIMULTANEOUS_IO, operations))
        self._dispatch()
        self.activityChanged.emit()

    def reschedule(self) -> None:
        """Apply a change of foreground (tab switch or load mode) at once."""
        self._dispatch()
        self._apply_pauses(time.monotonic())
        self.activityChanged.emit()

    def wants_foreground(self, request: IORequest) -> bool:
        # A load writing the disk cache after delivering its data is background work.
        return not request.completed and self.is_foreground(request)

    def _listing_progressing(self, request: IORequest, now: float) -> bool:
        return request.operation != "load" and now - request.last_activity < self.STALLED_LISTING

    def _foreground_room(self, request: IORequest, now: float) -> bool:
        """One listing and one load; stopping and stalled helpers count only toward the cap."""
        if sum(r.lane == FOREGROUND for r in (*self.active, *self.retired)) >= self.FOREGROUND_CAP:
            return False
        running = [r for r in self.active if r.lane == FOREGROUND]
        if request.operation == "load":
            return not any(r.operation == "load" for r in running)
        return not any(self._listing_progressing(r, now) for r in running)

    def _background_room(self) -> bool:
        # Cache writers, paused and cancelled helpers still occupy slots until exit.
        background = [r for r in (*self.active, *self.retired) if r.lane not in (FOREGROUND, LOCAL)]
        return (len(background) < self.max_operations
                and sum(r.lane not in (FOREGROUND, LOCAL) for r in self.retired) < self.MAX_RETIRED)

    def _local_room(self) -> bool:
        return sum(r.lane == LOCAL for r in (*self.active, *self.retired)) < self.LOCAL_CAP

    def _foreground_busy(self, now: float) -> bool:
        return any(r.lane == FOREGROUND and not r.completed
                   and (r.operation == "load" or self._listing_progressing(r, now)) for r in self.active)

    def hold_background(self, now: float | None = None) -> bool:
        """Background loads and scans pause, and none start, while the foreground works."""
        now = time.monotonic() if now is None else now
        if self._foreground_busy(now):
            self._foreground_busy_at = now
        return now - self._foreground_busy_at < self.RESUME_DELAY

    def _hold_foreground_load(self, now: float) -> bool:
        """The selected load pauses while the current tab lists a folder."""
        if any(r.lane == FOREGROUND and self._listing_progressing(r, now) for r in self.active):
            self._listing_busy_at = now
        return now - self._listing_busy_at < self.RESUME_DELAY

    def _update_lanes(self, now: float) -> None:
        for request in list(self.active):
            foreground = self.wants_foreground(request)
            if request.lane == FOREGROUND and not foreground:
                if request.operation == "load" and not request.completed and not self._background_room():
                    self._requeue(request)
                else:
                    # Listings and cache writes finish here even when over the limit.
                    request.lane = BACKGROUND
            elif request.lane == BACKGROUND and foreground and self._foreground_room(request, now):
                request.lane = FOREGROUND

    def _requeue(self, request: IORequest) -> None:
        """Stop a load that left the foreground with no background slot; it restarts from RAM shots."""
        logging.info("Load moved to the background queue; restarts from loaded shots: %s", request.path)
        self._retire(request, REQUEUED)
        again = IORequest(request.owner, request.generation, request.path, request.operation,
                          dict(request.payload),
                          request.timeout if math.isinf(request.timeout) else self.NO_PROGRESS_TIMEOUT,
                          attempt=request.attempt, file_attempts=dict(request.file_attempts),
                          priority=request.priority)
        self.pending.appendleft(again)
        self.resultReady.emit(again, {"kind": "queued", "retry": True, "requeued": True,
                                      "attempt": again.attempt})

    def _start(self, request: IORequest, lane: str) -> None:
        self.pending.remove(request)
        request.lane = lane
        request.started = time.monotonic()
        request.last_activity = request.started
        self.active.append(request)
        self.resultReady.emit(request, {"kind": "started", "attempt": request.attempt})
        threading.Thread(target=self._run, args=(request,), daemon=True,
                         name=f"HeLab-{request.operation}").start()

    def _dispatch(self) -> None:
        if self.closed:
            return
        now = time.monotonic()
        self._update_lanes(now)
        # A retry never runs beside its predecessor; it waits for confirmed exit.
        # The current tab's listing and selected load never wait for background work.
        for request in list(self.pending):
            if self.blocker(request) is not None:
                continue
            if request.operation in self.LOCAL_OPERATIONS:
                if self._local_room():
                    self._start(request, LOCAL)
            elif self.wants_foreground(request) and self._foreground_room(request, now):
                self._start(request, FOREGROUND)
        hold = self.hold_background(now)
        for request in list(self.pending):
            if (self.blocker(request) is not None or self.wants_foreground(request)
                    or request.operation in self.LOCAL_OPERATIONS):
                continue
            if not self._background_room():
                break
            if hold and request.operation in self.PAUSABLE:
                continue
            self._start(request, BACKGROUND)

    def _apply_pauses(self, now: float) -> None:
        hold_background = self.hold_background(now)
        hold_load = self._hold_foreground_load(now)
        for request in self.active:
            pause = (request.operation in self.PAUSABLE and not request.completed
                     and (hold_background if request.lane != FOREGROUND
                          else request.operation == "load" and hold_load))
            if pause != request.pause_requested:
                with request.control:
                    request.pause_requested = pause
                    if request.output:
                        self._write_pause(request.output, pause)

    @staticmethod
    def _write_pause(output: str, pause: bool) -> None:
        # A local temp file; the helper checks it between files and entries.
        flag = os.path.join(output, "pause")
        try:
            if pause:
                Path(flag).touch()
            else:
                os.remove(flag)
        except OSError:
            pass

    def load_busy(self) -> bool:
        """Whether a load is running or waiting, without filesystem access."""
        return any(r.operation == "load" and not r.completed for r in (*self.active, *self.pending))

    def promote(self, owner: str) -> None:
        """Move an owner's pending requests ahead of other pending requests."""
        promoted = [r for r in self.pending if r.owner == owner]
        for request in reversed(promoted):
            self.pending.remove(request)
            request.priority = True
            self.pending.appendleft(request)
        if promoted:
            self.activityChanged.emit()

    def queued_load_paths(self) -> list[str]:
        """Queued folders in dispatch order, without filesystem access."""
        return list(dict.fromkeys(r.path for r in self.pending if r.operation == "load"))

    def queued_operations(self, *, include_held: bool = True) -> list[tuple[str, str]]:
        """Operation/path pairs in dispatch order, shared across tabs and memory-only.

        Held requests wait for a stopping helper and are described with it instead.
        """
        return list(dict.fromkeys((r.operation, r.path) for r in self.pending
                                  if include_held or self.blocker(r) is None))

    @staticmethod
    def _key(request: IORequest) -> tuple[str, int, str, str]:
        return request.owner, request.generation, request.path, request.operation

    def blocker(self, request: IORequest) -> IORequest | None:
        """The stopping helper a pending request must wait for, if any."""
        return next((old for old in self.retired if self._key(old) == self._key(request)), None)

    def waiting_for(self, old: IORequest) -> IORequest | None:
        """The pending retry or repeated request held until ``old`` exits."""
        return next((r for r in self.pending if self._key(r) == self._key(old)), None)

    def held_requests(self) -> list[IORequest]:
        return [r for r in self.pending if self.blocker(r) is not None]

    @classmethod
    def label(cls, request: IORequest) -> str:
        return "Save data cache" if cls.finishing(request) else cls.LABELS.get(request.operation, request.operation)

    @classmethod
    def noun(cls, request: IORequest) -> str:
        return "cache save" if cls.finishing(request) else cls.NOUNS.get(request.operation, request.operation)

    @staticmethod
    def stopping_for(request: IORequest, now: float) -> float | None:
        return None if request.retired_at is None else max(0.0, now - request.retired_at)

    def _stopping_row(self, old: IORequest, now: float) -> str:
        attempts = len(self.TIMEOUTS)
        if old.retirement_reason != "timed out":
            details = [old.retirement_reason or "cancelled"]
        elif self.finishing(old):
            details = ["timed out while saving the data cache"]
        elif self.retries(old):
            assert old.current_file is not None
            details = [f"attempt {old.attempt} of {attempts} timed out after {old.timeout:.0f} s "
                       f"without progress on {os.path.basename(old.current_file)}"]
        else:
            details = [f"timed out after {old.timeout:.0f} s without progress"]
        age = self.stopping_for(old, now)
        details.append("stopping" if age is None else f"stopping for {duration(age)}")
        waiting = self.waiting_for(old)
        if waiting is not None and old.retirement_reason == REQUEUED:
            details.append("restarts from the shots already loaded when it exits")
        elif waiting is not None:
            details.append(f"attempt {waiting.attempt} of {attempts} starts when it exits"
                           if waiting.attempt > old.attempt else "requested again; starts when it exits")
        elif (old.retirement_reason == "timed out" and not self.finishing(old) and self.retries(old)
              and old.attempt >= attempts):
            details.append("no retries left")
        return f"{self.label(old)}: {old.path} — " + " · ".join(details)

    def stopping_summary(self) -> str:
        """One status-bar phrase for helpers that were stopped but have not exited."""
        if not self.retired:
            return ""
        now = time.monotonic()
        old = min(self.retired, key=lambda r: now if r.retired_at is None else r.retired_at)
        reason = {"timed out": "timed-out", REQUEUED: "background"}.get(old.retirement_reason, "cancelled")
        age = self.stopping_for(old, now)
        text = f"{reason} {self.noun(old)} to stop" + ("" if age is None else f" ({duration(age)})")
        waiting = self.waiting_for(old)
        if waiting is not None and waiting.attempt > old.attempt:
            text = f"Retry {waiting.attempt} of {len(self.TIMEOUTS)} waiting for {text}"
        else:
            text = f"Waiting for {text}"
        if len(self.retired) > 1:
            text += f" · {len(self.retired) - 1} more stopping"
        return text

    # Status-bar phrases for running operations other than scans and loads.
    ACTIVITIES = {"resolve": "Finding default folder", "cached": "Reading cached data", "invalidate": "Clearing data cache",
                  "scan_history": "Saving scan history", "icons": "Fetching folder icons",
                  "drives": "Listing drives"}

    def activity_summary(self) -> str:
        """App-wide status-bar phrase from memory; zero counts are left out."""
        def counted(count: int, noun: str) -> str:
            return f"{count:,} {noun}{'' if count == 1 else 's'}"
        running = [r for r in self.active if not r.paused and not r.completed]
        scans = sum(r.operation in ("list", "details", "scan") for r in running)
        loads = sum(r.operation == "load" for r in running)
        paused_loads = sum(r.operation == "load" and r.paused and not r.completed for r in self.active)
        paused_scans = sum(r.operation in ("list", "details", "scan") and r.paused for r in self.active)
        # A finished load keeps its slot until it exits, but only some are writing a cache.
        writing = self.folder_cache.writing_disk_cache if self.folder_cache else (lambda owner: False)
        saving = sum(self.finishing(r) and writing(r.owner) for r in self.active)
        others = dict.fromkeys(self.ACTIVITIES.get(r.operation, self.LABELS.get(r.operation, r.operation))
                               for r in running if r.operation not in ("list", "details", "scan", "load"))
        queued = len(self.pending) - len(self.held_requests())
        return " · ".join(filter(None, (
            f"Scanning {counted(scans, 'folder')}" if scans else "",
            f"Loading {counted(loads, 'dataset')}" if loads else "",
            *others,
            f"{counted(paused_loads, 'load')} paused" if paused_loads else "",
            f"{counted(paused_scans, 'scan')} paused" if paused_scans else "",
            f"Saving {counted(saving, 'data cache')}" if saving else "",
            self.stopping_summary(),
            f"{counted(queued, 'operation')} queued" if queued else ""))) or "Ready"

    def queue_tooltip(self) -> str:
        """Shared queue and termination details without querying the filesystem."""
        parts: list[str] = []
        now = time.monotonic()
        if self.retired:
            parts.append("Stopping operations:\n" + "\n".join(self._stopping_row(r, now) for r in self.retired))
            notes: list[str] = []
            if any((age := self.stopping_for(r, now)) is not None and age >= self.SLOW_STOP_SECONDS
                   for r in self.retired):
                notes.append("A stopped helper has not exited yet. This usually means the folder's volume "
                             "is not responding, and the system cannot end the helper until it does.")
            if not self._background_room() and any(self.blocker(r) is None for r in self.pending):
                notes.append("Other queued I/O also waits: stopping helpers keep their I/O slots until they exit.")
            if notes:
                parts.append("\n".join(notes))
        paused = [f"{self.label(r)}: {r.path}" for r in self.active if r.paused]
        if paused:
            parts.append("Paused while the current tab browses or loads:\n" + "\n".join(paused))
        rows: dict[tuple[str, str], str] = {}
        for request in self.pending:
            if self.blocker(request) is None:
                rows.setdefault((request.operation, request.path), f"{self.label(request)}: {request.path}")
        if rows:
            parts.append("Queued folders (next first):\n" + "\n".join(rows.values()))
        return "\n\n".join(parts)

    def _put(self, request: IORequest, event: dict[str, Any]) -> None:
        while not self.closed:
            if request.cancelled.is_set() and event["kind"] != "exit":
                return
            try:
                self.messages.put((request, event), timeout=0.1)
                return
            except queue.Full:
                continue

    def _run(self, request: IORequest) -> None:
        # Process creation, pipe reads, JSON parsing and local artifact reads
        # all happen in a daemon thread. No join/communicate on the GUI thread.
        try:
            if request.cancelled.is_set():
                return
            payload = {**request.payload, "operation": request.operation, "path": request.path}
            # Every helper gets a private folder: load artifacts, the frozen app's
            # request/response files, and the pause flag.
            with request.control:
                request.output = tempfile.mkdtemp(
                    prefix="helab_data_" if request.operation in ("load", "cached") else "helab_io_")
                if request.pause_requested:
                    self._write_pause(request.output, True)
            payload["output"] = payload["control"] = request.output
            response_file: str | None = None
            if getattr(sys, "frozen", False):
                input_file = os.path.join(request.output, "request.json")
                response_file = os.path.join(request.output, "response.jsonl")
                Path(input_file).write_text(json.dumps(payload) + "\n", encoding="utf-8")
                Path(response_file).touch()
                command = [sys.executable, "--helab-io-helper", input_file, response_file]
            else:
                command = [sys.executable, "-m", "helab.io_helper"]
            env = os.environ.copy()
            package_root = str(Path(__file__).resolve().parents[2])
            env["PYTHONPATH"] = os.pathsep.join(filter(None, (package_root, env.get("PYTHONPATH", ""))))
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, text=True, env=env,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0)
            request.process = process
            if request.cancelled.is_set():
                process.kill()
                return
            assert process.stdin is not None and process.stdout is not None
            if response_file is not None:
                process.stdin.close()
                lines = self._file_lines(request, response_file)
            else:
                process.stdin.write(json.dumps(payload) + "\n")
                process.stdin.close()
                lines = iter(process.stdout)
            complete = False
            for line in lines:
                event = json.loads(line)
                if event["kind"] == "shot":
                    import numpy as np
                    artifact = event.pop("artifact")
                    event["array"] = np.load(artifact, allow_pickle=False)
                    os.remove(artifact)
                if event["kind"] in ("done", "error"):
                    complete = True
                self._put(request, event)
                if request.cancelled.is_set():
                    break
            if not complete and not request.cancelled.is_set():
                self._put(request, {"kind": "error", "message": "I/O helper exited unexpectedly"})
        except Exception as exc:
            self._put(request, {"kind": "error", "message": str(exc)})
        finally:
            try:
                if request.process is None:
                    request.exited.set()
                    self._put(request, {"kind": "exit"})
                else:
                    self._reap(request)
                    if request.process.stdout is not None:
                        try:
                            request.process.stdout.close()
                        except OSError:
                            logging.exception("Could not close I/O helper output: %s %s",
                                              request.operation, request.path)
            finally:
                self.release(request)

    def _reap(self, request: IORequest) -> None:
        """Confirm process death independently of pipe/artifact reader completion."""
        process = request.process
        if process is None:
            # Startup may still be in progress. _run observes cancellation after
            # creating the process and confirms exit itself in its finally block.
            return
        try:
            if process.poll() is None:
                process.kill()
        except OSError:
            logging.exception("Could not stop I/O helper: %s %s", request.operation, request.path)
        try:
            # Only daemon threads wait on the OS; never release an alive helper's slot.
            process.wait()
        except OSError:
            logging.exception("Could not reap I/O helper: %s %s", request.operation, request.path)
            return
        # Duplicate exit notifications are harmless; the scheduler removes by
        # request identity, so an old reader cannot release a new retry's slot.
        request.exited.set()
        self._put(request, {"kind": "exit"})

    @staticmethod
    def _file_lines(request: IORequest, filename: str) -> Iterator[str]:
        with open(filename, encoding="utf-8") as response:
            partial = ""
            while not request.cancelled.is_set():
                line = response.readline()
                if line:
                    partial += line
                    if partial.endswith("\n"):
                        yield partial
                        partial = ""
                elif request.process is not None and request.process.poll() is not None:
                    break
                else:
                    time.sleep(0.01)

    @staticmethod
    def release(request: IORequest) -> None:
        with request.control:
            output, request.output = request.output, None
        if output:
            threading.Thread(target=shutil.rmtree, args=(output,), kwargs={"ignore_errors": True},
                             daemon=True, name="HeLab-artifact-cleanup").start()

    def _retire(self, request: IORequest, reason: str = "cancelled") -> None:
        request.retirement_reason = reason
        if request.retired_at is None:
            request.retired_at = time.monotonic()
        request.cancelled.set()
        if request in self.active:
            self.active.remove(request)
            self.retired.append(request)
        threading.Thread(target=self._reap, args=(request,), daemon=True, name="HeLab-cancel").start()

    def cancel(self, owner: str, operation: str | None = None) -> None:
        for request in list(self.pending):
            if request.owner == owner and (operation is None or request.operation == operation):
                self.pending.remove(request)
                request.cancelled.set()
                self.resultReady.emit(request, {"kind": "cancelled"})
        for request in list(self.active):
            if request.owner == owner and (operation is None or request.operation == operation):
                self._retire(request)
                self.resultReady.emit(request, {"kind": "cancelled"})
        self.activityChanged.emit()

    def _tick(self) -> None:
        start = time.monotonic()
        for _ in range(64):
            if time.monotonic() - start > 0.008:
                break
            try:
                request, event = self.messages.get_nowait()
            except queue.Empty:
                break
            if event["kind"] == "exit":
                self._forget(request)
            elif not request.cancelled.is_set() and not self.closed:
                kind = event["kind"]
                if kind == "error":
                    # One line per failure; timeouts are logged where they are detected.
                    logging.warning("%s failed: %s — %s", self.label(request), request.path,
                                    str(event.get("message", "")).removesuffix(" — Retry"))
                if kind in ("paused", "resumed"):
                    # The no-progress timer is frozen while the helper waits.
                    request.paused = kind == "paused"
                    request.last_activity = time.monotonic()
                # Any helper event, including heartbeats, is progress, except that
                # while a file is read only file events count: a repeated
                # percentage must not hide a stalled file.
                if not (request.operation == "load" and request.current_file is not None
                        and kind not in ("file_started", "file_finished", "shot")):
                    request.last_activity = time.monotonic()
                # Files re-read for the disk cache keep the finishing deadline;
                # a no-timeout request keeps none.
                if request.operation == "load" and not request.completed and not math.isinf(request.timeout):
                    if kind == "file_started":
                        request.current_file = event["filename"]
                        request.attempt = request.file_attempts.get(event["filename"], 1)
                        request.timeout = self.TIMEOUTS[request.attempt - 1]
                        event = {**event, "attempt": request.attempt}
                    elif kind == "file_finished":
                        request.file_attempts.pop(event["filename"], None)
                        request.current_file = None
                        request.attempt = 1
                        request.timeout = self.NO_PROGRESS_TIMEOUT
                if event["kind"] in ("loaded", "resolved", "done", "error"):
                    request.completed = True
                    request.last_activity = time.monotonic()
                    request.timeout = self.FINISH_TIMEOUT
                self.resultReady.emit(request, event)
        # Exit notifications may be delayed behind reader events. Confirmed
        # death is an independent memory-only signal; cleanup cannot hold a slot.
        for request in (*self.active, *self.retired):
            if request.exited.is_set():
                self._forget(request)
        now = time.monotonic()
        for request in self.retired:
            age = self.stopping_for(request, now)
            if not request.slow_stop_logged and age is not None and age >= self.SLOW_STOP_SECONDS:
                request.slow_stop_logged = True
                logging.warning("Stopped %s has not exited after %.0f s (%s); its volume may not be "
                                "responding: %s", self.noun(request), age,
                                request.retirement_reason or "cancelled", request.path)
        for request in list(self.active):
            if request.paused or now - request.last_activity <= request.timeout:
                continue
            self._retire(request, "timed out")
            if request.completed:
                # Data may already be delivered while the helper writes its
                # disk cache. Never restart or fail a successful request.
                self.resultReady.emit(request, {"kind": "done"})
                continue
            retries = self.retries(request)
            logging.warning("I/O timeout after %.0f s without progress (attempt %s/%s): %s %s",
                            request.timeout, request.attempt, len(self.TIMEOUTS) if retries else 1,
                            request.operation, request.path)
            if retries and request.attempt < len(self.TIMEOUTS):
                assert request.current_file is not None
                file_attempts = {**request.file_attempts, request.current_file: request.attempt + 1}
                # The retry lists the folder again under the no-progress limit;
                # the file gets its next budget when it starts.
                retry = IORequest(request.owner, request.generation, request.path,
                                  request.operation, dict(request.payload), self.NO_PROGRESS_TIMEOUT,
                                  attempt=request.attempt + 1, file_attempts=file_attempts,
                                  priority=request.priority)
                self.pending.appendleft(retry)
                self.resultReady.emit(retry, {"kind": "queued", "retry": True,
                                             "attempt": retry.attempt})
            else:
                message = (f"File timed out after 3 attempts: {os.path.basename(request.current_file)} — Retry"
                           if retries and request.current_file else
                           f"Timed out after {request.timeout:.0f} s without progress — Retry")
                self.resultReady.emit(request, {"kind": "error", "timeout": True,
                                               "attempt": request.attempt,
                                               "message": message})
            self.activityChanged.emit()
        self._dispatch()
        self._apply_pauses(time.monotonic())

    def _forget(self, request: IORequest) -> None:
        """Free a slot once the helper's exit is confirmed (duplicates are ignored)."""
        if request in self.active:
            self.active.remove(request)
        if request in self.retired:
            self.retired.remove(request)
            age = self.stopping_for(request, time.monotonic())
            if request.slow_stop_logged and age is not None:
                logging.warning("Stopped %s exited after %.0f s: %s", self.noun(request), age, request.path)
        self.activityChanged.emit()

    def shutdown(self) -> None:
        if self.closed:
            return
        if self.folder_cache is not None:
            self.folder_cache.shutdown()
        for owner in {r.owner for r in (*self.pending, *self.active)}:
            self.cancel(owner)
        self.closed = True
        self.timer.stop()
        while not self.messages.empty():
            try:
                request, _ = self.messages.get_nowait()
                if request.output:
                    self.release(request)
            except queue.Empty:
                break


_service: IOService | None = None


def get_io_service() -> IOService:
    global _service
    if _service is None or _service.closed:
        _service = IOService(QCoreApplication.instance())
    return _service
