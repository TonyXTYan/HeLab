"""Bounded process I/O with nonblocking delivery to the GUI thread."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Iterator, TYPE_CHECKING

from PyQt6.QtCore import QCoreApplication, QObject, QTimer, pyqtSignal

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


class IOService(QObject):
    resultReady = pyqtSignal(object, object)
    activityChanged = pyqtSignal()
    MAX_ACTIVE = 2
    MAX_ACTIVE_LOADS = 1
    MAX_PENDING = 128
    MAX_RETIRED = 2
    TIMEOUTS: tuple[float, ...] = (15.0, 20.0, 30.0)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pending: deque[IORequest] = deque()
        self.active: list[IORequest] = []
        self.retired: list[IORequest] = []
        self.messages: queue.Queue[tuple[IORequest, dict[str, Any]]] = queue.Queue(maxsize=256)
        self.closed = False
        self.folder_cache: FolderCache | None = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(20)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    def submit(self, owner: str, generation: int, path: str, operation: str,
               payload: dict[str, Any] | None = None, *, priority: bool = False,
               timeout: float = 15.0) -> bool:
        if self.closed:
            return False
        if any((r.owner, r.generation, r.path, r.operation) == (owner, generation, path, operation)
               for r in (*self.active, *self.pending)):
            return True
        # Reserve pending capacity for active requests that may need a retry.
        if len(self.pending) + len(self.active) >= self.MAX_PENDING:
            return False
        request = IORequest(owner, generation, path, operation, payload or {}, timeout)
        # Folder loads wait in submission order, including across tabs.
        if priority and operation != "load":
            self.pending.appendleft(request)
        else:
            self.pending.append(request)
        self.resultReady.emit(request, {"kind": "queued", "attempt": request.attempt})
        self._dispatch()
        self.activityChanged.emit()
        return True

    def _dispatch(self) -> None:
        while (self.pending and len(self.active) < self.MAX_ACTIVE
               and len(self.retired) < self.MAX_RETIRED and not self.closed):
            loads = sum(r.operation == "load" for r in (*self.active, *self.retired))
            # Skip blocked loads so directory navigation can still use a slot.
            request = next((r for r in self.pending
                            if (r.operation != "load" or loads < self.MAX_ACTIVE_LOADS)
                            and not any((old.owner, old.generation, old.path, old.operation)
                                        == (r.owner, r.generation, r.path, r.operation)
                                        for old in self.retired)), None)
            if request is None:
                break
            self.pending.remove(request)
            request.started = time.monotonic()
            request.last_activity = request.started
            self.active.append(request)
            self.resultReady.emit(request, {"kind": "started", "attempt": request.attempt})
            threading.Thread(target=self._run, args=(request,), daemon=True,
                             name=f"HeLab-{request.operation}").start()

    def queued_load_paths(self) -> list[str]:
        """Queued folders in dispatch order, without filesystem access."""
        return list(dict.fromkeys(r.path for r in self.pending if r.operation == "load"))

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
            if request.operation == "load":
                request.output = tempfile.mkdtemp(prefix="helab_data_")
                payload["output"] = request.output
            response_file: str | None = None
            if getattr(sys, "frozen", False):
                if request.output is None:
                    request.output = tempfile.mkdtemp(prefix="helab_io_")
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
            if request.process is not None:
                try:
                    if request.process.poll() is None:
                        request.process.kill()
                except OSError:
                    pass
                # Reaping may wait for the OS. This daemon thread is independent
                # of application exit and the GUI; retired requests stay bounded.
                request.process.wait()
                if request.process.stdout is not None:
                    request.process.stdout.close()
            self._put(request, {"kind": "exit"})
            self.release(request)

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
        output, request.output = request.output, None
        if output:
            threading.Thread(target=shutil.rmtree, args=(output,), kwargs={"ignore_errors": True},
                             daemon=True, name="HeLab-artifact-cleanup").start()

    def _retire(self, request: IORequest) -> None:
        request.cancelled.set()
        if request in self.active:
            self.active.remove(request)
            self.retired.append(request)
        def kill() -> None:
            process = request.process
            if process is not None:
                try:
                    process.kill()
                except OSError:
                    pass
        threading.Thread(target=kill, daemon=True, name="HeLab-cancel").start()

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
                if request in self.active:
                    self.active.remove(request)
                if request in self.retired:
                    self.retired.remove(request)
                self.activityChanged.emit()
            elif not request.cancelled.is_set() and not self.closed:
                kind = event["kind"]
                if request.operation == "load" and kind in ("file_started", "file_finished", "shot", "load_source"):
                    request.last_activity = time.monotonic()
                    if kind == "file_started":
                        request.current_file = event["filename"]
                        request.attempt = request.file_attempts.get(event["filename"], 1)
                        request.timeout = self.TIMEOUTS[request.attempt - 1]
                        event = {**event, "attempt": request.attempt}
                    elif kind == "file_finished":
                        request.file_attempts.pop(event["filename"], None)
                        request.current_file = None
                        request.attempt = 1
                        request.timeout = self.TIMEOUTS[0]
                if event["kind"] in ("loaded", "resolved", "done", "error"):
                    request.completed = True
                self.resultReady.emit(request, event)
        now = time.monotonic()
        for request in list(self.active):
            deadline_start = request.last_activity if request.operation == "load" else request.started
            if now - deadline_start <= request.timeout:
                continue
            self._retire(request)
            if request.completed:
                # Data may already be delivered while the helper writes its
                # disk cache. Never restart or fail a successful request.
                self.resultReady.emit(request, {"kind": "done"})
                continue
            logging.warning("I/O timeout (attempt %s/%s): %s %s", request.attempt,
                            len(self.TIMEOUTS), request.operation, request.path)
            if request.attempt < len(self.TIMEOUTS):
                file_attempts = dict(request.file_attempts)
                if request.current_file is not None:
                    file_attempts[request.current_file] = request.attempt + 1
                retry = IORequest(request.owner, request.generation, request.path,
                                  request.operation, dict(request.payload), self.TIMEOUTS[request.attempt],
                                  attempt=request.attempt + 1, current_file=request.current_file,
                                  file_attempts=file_attempts)
                self.pending.appendleft(retry)
                self.resultReady.emit(retry, {"kind": "queued", "retry": True,
                                             "attempt": retry.attempt})
            else:
                message = (f"File timed out after 3 attempts: {os.path.basename(request.current_file)} — Retry"
                           if request.current_file else "Request timed out after 3 attempts — Retry")
                self.resultReady.emit(request, {"kind": "error", "timeout": True,
                                               "attempt": request.attempt,
                                               "message": message})
            self.activityChanged.emit()
        self._dispatch()

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
