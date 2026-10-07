"""Session memory reuse above isolated I/O; no filesystem or disk-cache reads."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import logging
import os
import time
from typing import Any
from uuid import uuid4

import numpy as np
import numpy.typing as npt
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from helab.utils.io_service import IORequest, IOService


@dataclass
class FolderSnapshot:
    entries: tuple[dict[str, Any], ...]
    status: dict[str, Any]
    checked_at: float


@dataclass(eq=False)
class Dataset:
    path: str
    signature: str
    data: dict[int, npt.NDArray[np.float64]]
    metadata: dict[str, Any]
    epoch: int


@dataclass
class SharedJob:
    owner: str
    path: str
    operation: str
    epoch: int
    payload: dict[str, Any]
    subscribers: dict[tuple[str, int], IORequest] = field(default_factory=dict)
    entries: list[dict[str, Any]] = field(default_factory=list)
    status: dict[str, Any] | None = None
    data: dict[int, npt.NDArray[np.float64]] = field(default_factory=dict)
    state: str = "queued"
    progress: dict[str, Any] | None = None
    attempt: int = 1
    fingerprints: dict[int, tuple[int, int, int]] = field(default_factory=dict)
    problematic: set[int] = field(default_factory=set)
    base: Dataset | None = None


class FolderCache(QObject):
    resultReady = pyqtSignal(object, object)
    snapshotChanged = pyqtSignal(str)
    datasetChanged = pyqtSignal(str)
    diskCacheChanged = pyqtSignal(str)
    FRESH_SECONDS: float = 10.0
    MAX_SNAPSHOTS: int = 256
    MAX_ENTRIES: int = 100_000
    MAX_DATA_BYTES: int = 512 << 20

    def __init__(self, service: IOService) -> None:
        super().__init__(service)
        self.service = service
        self.snapshots: OrderedDict[str, FolderSnapshot] = OrderedDict()
        self.datasets: OrderedDict[tuple[str, str, int], Dataset] = OrderedDict()
        self.pins: dict[str, Dataset] = {}
        self.jobs: dict[tuple[str, str], SharedJob] = {}
        self._producers: dict[str, SharedJob] = {}
        self._deliveries: list[IORequest] = []
        self._epochs: dict[str, int] = {}
        self._defaults: OrderedDict[tuple[str, ...], str] = OrderedDict()
        self._disk_cached_paths: OrderedDict[str, None] = OrderedDict()
        # Datasets from before an explicit disk-cache clear are never reused.
        self._base_floor: dict[str, int] = {}
        # Load helpers still updating the disk cache after delivering data.
        self._finishing: dict[str, str] = {}
        service.resultReady.connect(self._on_event)

    @staticmethod
    def key(path: str) -> str:
        # Lexical normalization only: realpath/stat can block on remote mounts.
        return os.path.abspath(os.path.expanduser(path))

    def snapshot(self, path: str) -> FolderSnapshot | None:
        key = self.key(path)
        snapshot = self.snapshots.get(key)
        if snapshot:
            self.snapshots.move_to_end(key)
        return snapshot

    def dataset(self, path: str, signature: str) -> Dataset | None:
        key = (self.key(path), signature, self._epochs.get(self.key(path), 0))
        entry = self.datasets.get(key)
        if entry:
            self.datasets.move_to_end(key)
        return entry

    def current_dataset(self, path: str) -> Dataset | None:
        path = self.key(path)
        snapshot = self.snapshots.get(path)
        if snapshot:
            return self.dataset(path, snapshot.status.get("signature", ""))
        return next((entry for key, entry in reversed(self.datasets.items())
                     if key[0] == path and entry.epoch == self._epochs.get(path, 0)), None)

    def _base(self, path: str) -> Dataset | None:
        # A dataset an open tab still shows survives signature changes, so a
        # refresh only needs the shots that are new or changed since then.
        floor = self._base_floor.get(path, 0)
        candidates = [entry for entry in (*self.pins.values(), *self.datasets.values())
                      if entry.path == path and entry.epoch >= floor and "fingerprint" in entry.metadata]
        return max(candidates, key=lambda entry: entry.epoch, default=None)

    def disk_cached(self, path: str) -> bool:
        return path in self._disk_cached_paths

    def _set_disk_cached(self, path: str, cached: bool) -> None:
        previous = self.disk_cached(path)
        if cached:
            self._disk_cached_paths[path] = None
            self._disk_cached_paths.move_to_end(path)
            while len(self._disk_cached_paths) > self.MAX_ENTRIES:
                evicted, _ = self._disk_cached_paths.popitem(last=False)
                self.diskCacheChanged.emit(evicted)
        else:
            self._disk_cached_paths.pop(path, None)
        if previous != self.disk_cached(path):
            self.diskCacheChanged.emit(path)

    def has_request(self, owner: str, operation: str, path: str) -> bool:
        return any(r.owner == owner and r.operation == operation and r.path == path
                   for r in self.requests(owner))

    def requests(self, owner: str) -> list[IORequest]:
        return [r for job in self.jobs.values() for r in job.subscribers.values() if r.owner == owner] + [
            r for r in self._deliveries if r.owner == owner and not r.cancelled.is_set()]

    def retain(self, owner: str, dataset: Dataset) -> None:
        self.pins[owner] = dataset
        self._evict()

    def release(self, owner: str) -> None:
        self.pins.pop(owner, None)
        self._evict()

    def _evict(self) -> None:
        total = sum(int(d.metadata["bytes"]) for d in self.datasets.values())
        for key, entry in list(self.datasets.items()):
            if total <= self.MAX_DATA_BYTES:
                break
            if entry not in self.pins.values():
                total -= int(entry.metadata["bytes"])
                del self.datasets[key]
                self.datasetChanged.emit(entry.path)
        count = sum(len(s.entries) for s in self.snapshots.values())
        while self.snapshots and (len(self.snapshots) > self.MAX_SNAPSHOTS or count > self.MAX_ENTRIES):
            _, snapshot = self.snapshots.popitem(last=False)
            count -= len(snapshot.entries)

    def submit(self, owner: str, generation: int, path: str, operation: str,
               payload: dict[str, Any] | None = None, *, priority: bool = False,
               timeout: float = 15.0, force: bool = False) -> bool:
        if self.service.closed:
            return False
        path = self.key(path)
        payload = payload or {}
        if self.has_request(owner, operation, path):
            return True
        request = IORequest(owner, generation, path, operation, payload, timeout)
        snapshot = self.snapshot(path) if operation == "scan" else None
        if snapshot and not force:
            self._replay(request, snapshot, priority=priority)
            if time.monotonic() - snapshot.checked_at < self.FRESH_SECONDS:
                return True
            # Complete cached content first, then validate it once in a helper.
            request.payload = {**payload, "revalidate": True}
            return True
        if operation == "load":
            if ("invalidate", path) in self.jobs:
                return False
            entry = self.dataset(path, payload.get("signature", ""))
            if entry:
                self._deliver(request, {"kind": "loaded", "dataset": entry, **entry.metadata,
                                        "cached": True, "source": "memory", "cache_reason": ""})
                return True
        if operation == "scan" and ("invalidate", path) in self.jobs:
            # Invalidation completion will broadcast a fresh check to models.
            self._deliveries.append(request)
            self.resultReady.emit(request, {"kind": "queued"})

            def wait_for_clear() -> None:
                if request.cancelled.is_set() or self.service.closed:
                    return
                if ("invalidate", path) in self.jobs:
                    QTimer.singleShot(50, wait_for_clear)
                    return
                if request in self._deliveries:
                    self._deliveries.remove(request)
                self.submit(owner, generation, path, "scan", payload, priority=priority, force=True)
            QTimer.singleShot(0, wait_for_clear)
            return True
        if operation == "resolve":
            candidates = tuple(payload["candidates"])
            if candidates in self._defaults:
                self._deliver(request, {"kind": "resolved", "path": self._defaults[candidates]})
                return True
        job_key = (operation, path)
        job = self.jobs.get(job_key)
        if job:
            job.subscribers[(owner, generation)] = request
            self.resultReady.emit(request, {"kind": job.state, "attempt": job.attempt})
            if job.progress is not None:
                self.resultReady.emit(request, job.progress)
            return True
        if operation == "invalidate":
            self._set_disk_cached(path, False)
            self._invalidate_data(path)
            self._base_floor[path] = self._epochs[path]
            snapshot = self.snapshot(path)
            if snapshot:
                snapshot.checked_at = 0
        base = self._base(path) if operation == "load" else None
        if base:
            payload = {**payload, "memory": [list(entry) for entry in base.metadata["fingerprint"]
                                             if entry[0] in base.data]}
        job = SharedJob(uuid4().hex, path, operation, self._epochs.get(path, 0), payload, base=base)
        job.subscribers[(owner, generation)] = request
        self.jobs[job_key] = job
        self._producers[job.owner] = job
        if not self.service.submit(job.owner, 0, path, operation, payload, priority=priority, timeout=timeout):
            self.jobs.pop(job_key)
            self._producers.pop(job.owner)
            return False
        return True

    def _deliver(self, request: IORequest, event: dict[str, Any]) -> None:
        self._deliveries.append(request)

        def send() -> None:
            if not request.cancelled.is_set() and not self.service.closed:
                self.resultReady.emit(request, event)
                self.resultReady.emit(request, {"kind": "done", "cached": True})
            if request in self._deliveries:
                self._deliveries.remove(request)
        QTimer.singleShot(0, send)

    def _replay(self, request: IORequest, snapshot: FolderSnapshot, *, priority: bool = False) -> None:
        self._deliveries.append(request)
        position = 0
        self.resultReady.emit(request, {"kind": "queued", "cached": True})

        def batch() -> None:
            nonlocal position
            if request.cancelled.is_set() or self.service.closed:
                return
            entries = snapshot.entries[position:position + 128]
            if entries:
                self.resultReady.emit(request, {"kind": "entries", "entries": entries, "cached": True})
                position += len(entries)
                QTimer.singleShot(0, batch)
                return
            self.resultReady.emit(request, {**snapshot.status, "cached": True,
                                           "checked_at": snapshot.checked_at})
            self.resultReady.emit(request, {"kind": "done", "cached": True})
            if request in self._deliveries:
                self._deliveries.remove(request)
            if request.payload.get("revalidate") and not request.cancelled.is_set():
                # The check itself must not request another check when it completes.
                payload = {k: v for k, v in request.payload.items() if k != "revalidate"}
                self.submit(request.owner, request.generation, request.path, "scan", payload,
                            priority=priority, force=True)
        QTimer.singleShot(0, batch)

    def _forget_job(self, job: SharedJob) -> None:
        self.jobs.pop((job.operation, job.path), None)
        self._producers.pop(job.owner, None)

    def _resume_load(self, job: SharedJob, producer: IORequest) -> None:
        """Keep completed shots as the retry's RAM base, validated by the helper."""
        if not job.fingerprints:
            return
        data = dict(job.base.data) if job.base else {}
        fingerprints = {int(entry[0]): tuple(entry) for entry in job.base.metadata["fingerprint"]} if job.base else {}
        problematic = set(job.base.metadata.get("problematic", ())) if job.base else set()
        for shot, fingerprint in job.fingerprints.items():
            data[shot] = job.data[shot]
            fingerprints[shot] = fingerprint
            problematic.discard(shot)
        problematic.update(job.problematic)
        metadata = {"fingerprint": list(fingerprints.values()), "problematic": sorted(problematic)}
        job.base = Dataset(job.path, "", data, metadata, job.epoch)
        memory = [list(entry) for shot, entry in fingerprints.items() if shot in data]
        producer.payload["memory"] = memory
        job.payload = dict(producer.payload)

    def _cancel_replays(self, path: str) -> None:
        for request in list(self._deliveries):
            if request.path == path and request.operation == "scan":
                self._deliveries.remove(request)
                request.cancelled.set()
                self.resultReady.emit(request, {"kind": "cancelled"})

    def _cancel_job(self, job: SharedJob) -> None:
        self._forget_job(job)
        self.service.cancel(job.owner)
        for request in tuple(job.subscribers.values()):
            request.cancelled.set()
            self.resultReady.emit(request, {"kind": "cancelled"})

    def _invalidate_data(self, path: str) -> None:
        self._epochs[path] = self._epochs.get(path, 0) + 1
        job = self.jobs.get(("load", path))
        if job:
            self._cancel_job(job)
        for key in [key for key in self.datasets if key[0] == path]:
            del self.datasets[key]
        for request in self._deliveries:
            if request.operation == "load" and request.path == path:
                request.cancelled.set()
        self.datasetChanged.emit(path)

    def cancel(self, owner: str, operation: str | None = None, path: str | None = None) -> None:
        for request in list(self._deliveries):
            if request.owner == owner and (operation is None or request.operation == operation) and (path is None or request.path == path):
                self._deliveries.remove(request)
                request.cancelled.set()
                self.resultReady.emit(request, {"kind": "cancelled"})
        for job in list(self.jobs.values()):
            for key, request in list(job.subscribers.items()):
                if request.owner == owner and (operation is None or request.operation == operation) and (path is None or request.path == path):
                    del job.subscribers[key]
                    request.cancelled.set()
                    self.resultReady.emit(request, {"kind": "cancelled"})
            if not job.subscribers:
                self._forget_job(job)
                self.service.cancel(job.owner)

    def transfer(self, owner: str, generation: int, path: str,
                 new_owner: str, new_generation: int) -> bool:
        """Move a load subscription to another owner without interrupting the shared job."""
        job = self.jobs.get(("load", self.key(path)))
        old = job.subscribers.get((owner, generation)) if job else None
        if job is None or old is None:
            return False
        del job.subscribers[(owner, generation)]
        old.cancelled.set()
        replaced = job.subscribers.get((new_owner, new_generation))
        if replaced:
            replaced.cancelled.set()
        request = IORequest(new_owner, new_generation, old.path, "load", old.payload, old.timeout)
        job.subscribers[(new_owner, new_generation)] = request
        self.resultReady.emit(request, {"kind": job.state, "attempt": job.attempt})
        if job.progress is not None:
            self.resultReady.emit(request, job.progress)
        return True

    def promote(self, path: str) -> None:
        """Run this folder's queued load before other queued loads."""
        job = self.jobs.get(("load", self.key(path)))
        if job:
            self.service.promote(job.owner)

    def shutdown(self) -> None:
        for owner in {r.owner for job in self.jobs.values() for r in job.subscribers.values()} | {
            r.owner for r in self._deliveries}:
            self.cancel(owner)
        self.pins.clear()
        self.datasets.clear()
        self.snapshots.clear()
        self._defaults.clear()
        self._disk_cached_paths.clear()

    def _on_event(self, producer: IORequest, event: dict[str, Any]) -> None:
        job = self._producers.get(producer.owner)
        if job is None and producer.owner in self._finishing:
            path = self._finishing[producer.owner]
            if event["kind"] == "disk_cached":
                self._set_disk_cached(path, bool(event["disk_cached"]))
            elif event["kind"] == "cache_warning":
                logging.warning("Folder cache %s: %s", path, event["message"])
            elif event["kind"] in ("done", "error", "cancelled"):
                del self._finishing[producer.owner]
            return
        if job is None:
            # Non-shared IOService consumers retain their existing protocol.
            self.resultReady.emit(producer, event)
            return
        kind = event["kind"]
        if kind in ("queued", "started"):
            job.state = kind
            job.attempt = event.get("attempt", job.attempt)
            if event.get("retry"):
                if job.operation == "load":
                    self._resume_load(job, producer)
                job.entries.clear()
                job.status = None
                job.data.clear()
                job.fingerprints.clear()
                job.problematic.clear()
                job.progress = None
        if job.operation == "scan":
            if kind == "entries":
                for entry in event["entries"]:
                    if "disk_cached" in entry:
                        self._set_disk_cached(entry["path"], bool(entry["disk_cached"]))
                job.entries.extend(event["entries"])
                if len(job.entries) > self.MAX_ENTRIES:
                    self._forget_job(job)
                    self.service.cancel(job.owner)
                    for request in tuple(job.subscribers.values()):
                        self.resultReady.emit(request, {"kind": "error", "message": "Folder exceeds snapshot entry limit"})
                return
            if kind == "status":
                if "disk_cached" in event:
                    self._set_disk_cached(job.path, bool(event["disk_cached"]))
                job.status = event
                return
            if kind == "done" and job.status:
                old = self.snapshot(job.path)
                if old and old.status.get("signature") != job.status.get("signature"):
                    self._invalidate_data(job.path)
                snapshot = FolderSnapshot(tuple(job.entries), job.status, time.monotonic())
                self._cancel_replays(job.path)
                self.snapshots[job.path] = snapshot
                self.snapshots.move_to_end(job.path)
                self._evict()
                self.snapshotChanged.emit(job.path)
                self._forget_job(job)
                for request in tuple(job.subscribers.values()):
                    self._replay(request, snapshot)
                return
        elif job.operation == "load":
            if kind == "file_started":
                attempt = event.get("attempt", job.attempt)
                if attempt == job.attempt:
                    return
                job.attempt = attempt
            if kind == "file_finished":
                return
            if kind == "progress":
                job.progress = event
            if kind == "shot":
                array = event["array"]
                array.setflags(write=False)
                job.data[event["shot"]] = array
                if "fingerprint" in event:
                    job.fingerprints[event["shot"]] = tuple(event["fingerprint"])
                if event.get("problematic"):
                    job.problematic.add(event["shot"])
                return
            if kind == "loaded":
                source_snapshot = self.snapshot(job.path)
                if job.epoch != self._epochs.get(job.path, 0) or (
                    source_snapshot and event.get("signature") != source_snapshot.status.get("signature")):
                    self._cancel_job(job)
                    if source_snapshot:
                        source_snapshot.checked_at = 0
                    self.snapshotChanged.emit(job.path)
                    return
                if "disk_cached" in event:
                    self._set_disk_cached(job.path, bool(event["disk_cached"]))
                memory_shots = event.get("memory_shots", [])
                if memory_shots:
                    assert job.base is not None
                    for shot in memory_shots:
                        job.data[shot] = job.base.data[shot]
                    job.data = dict(sorted(job.data.items()))
                    problematic = set(event["problematic"]) | (
                        set(job.base.metadata.get("problematic", ())) & set(memory_shots))
                    event = {**event, "problematic": sorted(problematic), "files": len(job.data),
                             "rows": sum(len(array) for array in job.data.values()),
                             "bytes": sum(array.nbytes for array in job.data.values())}
                # The helper may still be updating the disk cache; the data is
                # complete, so later shared loads must not wait for that.
                self._forget_job(job)
                self._finishing[job.owner] = job.path
                entry = Dataset(job.path, event["signature"], job.data, event, job.epoch)
                self.datasets[(job.path, entry.signature, entry.epoch)] = entry
                event = {**event, "dataset": entry}
                # Subscribers pin the dataset during delivery before eviction.
                for request in tuple(job.subscribers.values()):
                    self.resultReady.emit(request, event)
                self.datasetChanged.emit(job.path)
                self._evict()
                return
        elif job.operation == "resolve" and kind == "resolved":
            candidates = tuple(job.payload["candidates"])
            self._defaults[candidates] = event["path"]
            if len(self._defaults) > 16:
                self._defaults.popitem(last=False)
        if kind in ("done", "error", "cancelled"):
            self._forget_job(job)
        for request in tuple(job.subscribers.values()):
            self.resultReady.emit(request, event)
        if job.operation == "invalidate" and kind == "done":
            self.snapshotChanged.emit(job.path)


def get_folder_cache(service: IOService) -> FolderCache:
    if service.folder_cache is None:
        service.folder_cache = FolderCache(service)
    return service.folder_cache
