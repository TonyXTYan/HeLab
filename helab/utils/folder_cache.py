"""Session memory reuse above isolated I/O; no filesystem or disk-cache reads."""
from __future__ import annotations

from collections import OrderedDict
import base64
from dataclasses import dataclass, field
import logging
import math
import os
import time
from typing import Any
from uuid import uuid4

import numpy as np
import numpy.typing as npt
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap

from helab.utils.io_service import IORequest, IOService
from helab.utils.scan_history import ScanHistory, empty_history, parse_history, apply_outcome, for_identity, folder_identity


# Folder checks that list a folder: browse step 1 (names only), browse step 2
# (``details``, the full scan in the background) and a basic scan.
SCANS = ("list", "details", "scan")
# The current tab's work that runs in the foreground I/O lane.
FOREGROUND_OPERATIONS = ("list", "resolve", "load")


@dataclass
class FolderSnapshot:
    entries: tuple[dict[str, Any], ...]
    status: dict[str, Any]
    checked_at: float
    listed_at: float = 0.0


@dataclass(eq=False)
class Dataset:
    path: str
    signature: str
    data: dict[int, npt.NDArray[np.float64]]
    metadata: dict[str, Any]
    epoch: int


@dataclass
class CacheStatus:
    info: dict[str, Any] = field(default_factory=dict)
    error: str = ""


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
    load_status: dict[str, Any] | None = None
    attempt: int = 1
    fingerprints: dict[int, tuple[int, int, int]] = field(default_factory=dict)
    problematic: set[int] = field(default_factory=set)
    base: Dataset | None = None
    scan_mode: str = "scan"
    history_saved: bool = False
    completed_scan: FolderSnapshot | None = None
    created: float = field(default_factory=time.monotonic)
    paused: bool = False


class FolderCache(QObject):
    resultReady = pyqtSignal(object, object)
    snapshotChanged = pyqtSignal(str)
    datasetChanged = pyqtSignal(str)
    diskCacheChanged = pyqtSignal(str)
    scanHistoryChanged = pyqtSignal(str)
    folderIconChanged = pyqtSignal(str)
    subtreeChanged = pyqtSignal(str)
    MAX_FOLDER_ICONS = 4096
    MAX_SUBTREES = 4096
    SUBTREE_SAVE_DELAY_MS = 500
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
        self._disk_cache_writers: set[str] = set()
        self._finishing_epochs: dict[str, int] = {}
        self._cache_states: OrderedDict[str, CacheStatus] = OrderedDict()
        # When each folder's disk cache was last cleared; older scans saw stale entries.
        self._cleared_at: OrderedDict[str, float] = OrderedDict()
        self.scan_summaries: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.metadata_notifications: set[str] = set()
        self.listing_notifications: set[str] = set()
        self.scan_histories: OrderedDict[str, ScanHistory] = OrderedDict()
        self.scan_history_errors: dict[str, str] = {}
        # Native icons (including unsuccessful lookups) are session-only and bounded.
        self.folder_icons: OrderedDict[str, QIcon] = OrderedDict()
        self._history_identity_dates: dict[str, float] = {}
        self._history_writes: dict[str, str] = {}
        # Statuses derived from subfolders, newest per folder; status "" marks a removal.
        # Saved by one batched helper write at a time, after a short delay.
        self.subtrees: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._subtree_pending: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._subtree_writer = ""
        self._subtree_options: dict[str, Any] = {}
        self._subtree_timer = QTimer(self)
        self._subtree_timer.setSingleShot(True)
        self._subtree_timer.timeout.connect(self._save_subtrees)
        # Subscriber owners of the current tab (its model, and in queue mode its
        # background loads); their listings and loads use the foreground lane.
        self.foreground_owners: set[str] = set()
        service.is_foreground = self._is_foreground
        service.resultReady.connect(self._on_event)

    def _is_foreground(self, request: IORequest) -> bool:
        job = self._producers.get(request.owner)
        return (job is not None and job.operation in FOREGROUND_OPERATIONS
                and any(r.owner in self.foreground_owners for r in job.subscribers.values()))

    def set_foreground(self, owners: set[str]) -> None:
        """Make these subscribers' work the foreground; the previous tab's becomes background."""
        if owners != self.foreground_owners:
            self.foreground_owners = set(owners)
            self.service.reschedule()

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

    def remember_scan(self, path: str, status: dict[str, Any]) -> None:
        previous = self.scan_summaries.get(path)
        if previous and previous.get("scanned_at", 0) > status.get("scanned_at", 0):
            return
        self.scan_summaries[path] = dict(status)
        self.scan_summaries.move_to_end(path)
        while len(self.scan_summaries) > self.MAX_SNAPSHOTS:
            self.scan_summaries.popitem(last=False)

    def subtree(self, path: str, saved: object = None) -> dict[str, Any] | None:
        """The newest derived status for the folder: this session's or ``saved`` (from a listing)."""
        current = self.subtrees.get(path)
        if isinstance(saved, dict) and saved and (current is None or saved["derived_at"] > current["derived_at"]):
            current = saved
        return current if current and current["status"] else None

    def remember_subtree(self, path: str, record: dict[str, Any], *, notify: bool = True) -> None:
        previous = self.subtrees.get(path)
        if previous and previous["derived_at"] > record["derived_at"]:
            return
        self.subtrees[path] = dict(record)
        self.subtrees.move_to_end(path)
        while len(self.subtrees) > self.MAX_SUBTREES:
            self.subtrees.popitem(last=False)
        if notify:
            self.subtreeChanged.emit(path)

    def save_subtree(self, path: str, record: dict[str, Any], cache_options: dict[str, Any]) -> None:
        """Share a newly derived status with other tabs and save it for later sessions."""
        self.remember_subtree(path, record, notify=False)
        # Notified later: the deriving tab must not re-enter its own derivation.
        QTimer.singleShot(0, lambda: None if self.service.closed else self.subtreeChanged.emit(path))
        self._subtree_pending[path] = {"path": path, **record}
        self._subtree_pending.move_to_end(path)
        self._subtree_options = cache_options
        if not self._subtree_writer and not self._subtree_timer.isActive():
            self._subtree_timer.start(self.SUBTREE_SAVE_DELAY_MS)

    def _save_subtrees(self) -> None:
        if self._subtree_writer or not self._subtree_pending or self.service.closed:
            return
        records = [self._subtree_pending.popitem(last=False)[1]
                   for _ in range(min(256, len(self._subtree_pending)))]
        owner = uuid4().hex
        if self.service.submit(owner, 0, records[0]["path"], "subtree_save",
                               {"cache": self._subtree_options, "records": records}):
            self._subtree_writer = owner
            return
        for record in records:  # Queue full: try again later, newer derivations first.
            self._subtree_pending.setdefault(record["path"], record)
        self._subtree_timer.start(5000)

    def scan_history(self, path: str) -> ScanHistory:
        return self.scan_histories.get(self.key(path), empty_history())

    def remember_history(self, path: str, value: object, *, identity: object = None,
                         observed_at: float = 0) -> None:
        path = self.key(path)
        current = self.scan_histories.get(path)
        observed = folder_identity(identity)
        if observed is not None:
            if observed_at < self._history_identity_dates.get(path, 0):
                return
            self._history_identity_dates[path] = observed_at
            if current is not None:
                current = for_identity(current, observed)
                self.scan_histories[path] = current
        if value is None and current is None:
            return
        history = parse_history(value) if value is not None else current
        if history is None:
            return
        if observed is not None:
            history = for_identity(history, observed)
        if current is not None and (current["revision"] > history["revision"] or
                current["identity"] is not None and history["identity"] is not None
                and current["identity"] != history["identity"]):
            return
        self.scan_histories[path] = history
        self.scan_histories.move_to_end(path)
        while len(self.scan_histories) > 4096:
            removed, _ = self.scan_histories.popitem(last=False)
            self.scan_history_errors.pop(removed, None)
            self._history_identity_dates.pop(removed, None)
        self.scanHistoryChanged.emit(path)

    def _record_scan_outcome(self, job: SharedJob, event: dict[str, Any], *, success: bool = False) -> None:
        history = self.scan_history(job.path)
        outcome = {"operation_id": job.owner, "revision": job.payload["scan_revision"],
            "kind": "success" if success else "timeout" if event.get("timeout") else "io_error",
            "at": job.status.get("scanned_at", time.time()) if success and job.status else time.time(),
            "attempts": event.get("attempt", job.attempt),
            "reason": event.get("message", "Folder status check failed").removesuffix(" — Retry"),
            "identity": job.status.get("identity") if success and job.status else job.payload.get("identity")}
        if (not success and history["identity"] is not None and outcome["identity"] is not None
                and history["identity"] != outcome["identity"]):
            return  # The failed job belonged to a directory replaced at this path.
        self.remember_history(job.path, apply_outcome(history, outcome))
        # Successful helpers persist their result before done. Compatibility
        # producers only need a write when recovering an existing failure.
        if job.history_saved or success and not history["failures"]:
            return
        options = job.payload.get("cache")
        if not options:
            self.scan_history_errors[job.path] = "Scan history could not be saved; suppression is session-only."
            return
        owner = uuid4().hex
        self._history_writes[owner] = job.path
        if not self.service.submit(owner, 0, job.path, "scan_history", {"cache": options, "outcome": outcome},
                                   priority=True):
            self._history_writes.pop(owner, None)
            self.scan_history_errors[job.path] = "Scan history save queue full; suppression is session-only."
            logging.warning("Scan history %s: %s", job.path, self.scan_history_errors[job.path])
            self.scanHistoryChanged.emit(job.path)

    def dataset(self, path: str, signature: str) -> Dataset | None:
        key = (self.key(path), signature, self._epochs.get(self.key(path), 0))
        entry = self.datasets.get(key)
        if entry:
            self.datasets.move_to_end(key)
        return entry

    def current_dataset(self, path: str) -> Dataset | None:
        path = self.key(path)
        snapshot = self.snapshots.get(path)
        # A names-only listing has no signature yet; show the latest dataset meanwhile.
        if snapshot and snapshot.status.get("signature"):
            return self.dataset(path, snapshot.status["signature"])
        return next((entry for key, entry in reversed(self.datasets.items())
                     if key[0] == path and entry.epoch == self._epochs.get(path, 0)), None)

    def latest_dataset(self, path: str) -> Dataset | None:
        """This folder's most recent dataset in memory, whether or not it matches the folder now."""
        path = self.key(path)
        return next((entry for key, entry in reversed(self.datasets.items())
                     if key[0] == path and entry.epoch == self._epochs.get(path, 0)), None)

    def _base(self, path: str) -> Dataset | None:
        # A dataset an open tab still shows survives signature changes, so a
        # refresh only needs the shots that are new or changed since then.
        floor = self._base_floor.get(path, 0)
        candidates = [entry for entry in (*self.pins.values(), *self.datasets.values())
                      if entry.path == path and entry.epoch >= floor and "fingerprint" in entry.metadata]
        return max(candidates, key=lambda entry: entry.epoch, default=None)

    @staticmethod
    def verified(dataset: Dataset) -> bool:
        """False for data read from the disk cache that has not been checked against its folder."""
        return bool(dataset.metadata.get("verified", True))

    def holds(self, dataset: Dataset) -> bool:
        """Whether this dataset is still kept (not cleared, replaced or evicted)."""
        return any(entry is dataset for entry in self.datasets.values())

    def confirmed(self, dataset: Dataset) -> bool:
        """Checked data whose signature matches this session's scan of the folder."""
        snapshot = self.snapshots.get(dataset.path)
        return (self.verified(dataset) and snapshot is not None
                and snapshot.status.get("signature") == dataset.signature)

    def disk_cached(self, path: str) -> bool:
        return path in self._disk_cached_paths

    def disk_cache_saving(self, path: str) -> bool:
        return any(self._finishing.get(owner) == path and self._finishing_epochs.get(owner) ==
                   self._epochs.get(path, 0) for owner in self._disk_cache_writers)

    def writing_disk_cache(self, owner: str) -> bool:
        """Whether a finished load's helper (by producer owner) is still writing the disk cache."""
        return owner in self._disk_cache_writers

    def disk_cache_known(self, path: str) -> bool:
        snapshot = self.snapshots.get(path)
        dataset = self.current_dataset(path)
        return (path in self._cache_states or self.disk_cached(path) or bool(snapshot and "disk_cached" in snapshot.status)
                or bool(dataset and "disk_cached" in dataset.metadata))

    def cache_status(self, path: str) -> CacheStatus:
        """Last helper observation, with no disk reads during GUI rendering."""
        return self._cache_states.get(path, CacheStatus())

    def _observe_cache(self, path: str, event: dict[str, Any]) -> None:
        state = self._cache_states.setdefault(path, CacheStatus())
        info = event.get("cache_info", {})
        # A scan that started before a save can report the previous date.
        if info and info.get("saved_at", 0) >= state.info.get("saved_at", 0):
            state.info = dict(info)
        if not event.get("disk_cached") and not self.disk_cache_saving(path):
            state.info = {}
        self._cache_states.move_to_end(path)
        while len(self._cache_states) > self.MAX_ENTRIES:
            self._cache_states.popitem(last=False)
        self._set_disk_cached(path, bool(event.get("disk_cached")))

    def _set_disk_cached(self, path: str, cached: bool, *, notify: bool = False) -> None:
        previous = self.disk_cached(path)
        if cached:
            self._disk_cached_paths[path] = None
            self._disk_cached_paths.move_to_end(path)
            while len(self._disk_cached_paths) > self.MAX_ENTRIES:
                evicted, _ = self._disk_cached_paths.popitem(last=False)
                self.diskCacheChanged.emit(evicted)
        else:
            self._disk_cached_paths.pop(path, None)
        if previous != self.disk_cached(path) or notify:
            self.diskCacheChanged.emit(path)

    def has_request(self, owner: str, operation: str, path: str) -> bool:
        return any(r.owner == owner and r.operation == operation and r.path == path
                   for r in self.requests(owner))

    def requests(self, owner: str) -> list[IORequest]:
        return [r for job in self.jobs.values() for r in job.subscribers.values() if r.owner == owner] + [
            r for r in self._deliveries if r.owner == owner and not r.cancelled.is_set()]

    def remember_folder_icon(self, path: str, png: str = "") -> None:
        pixmap = QPixmap()
        try:
            pixmap.loadFromData(base64.b64decode(png, validate=True), "PNG")
        except ValueError:
            pass
        # Transport 32 physical pixels for the view's 16-pixel icon at 2x scale.
        pixmap.setDevicePixelRatio(2)
        self.folder_icons[path] = QIcon(pixmap)
        self.folder_icons.move_to_end(path)
        while len(self.folder_icons) > self.MAX_FOLDER_ICONS:
            self.folder_icons.popitem(last=False)
        self.folderIconChanged.emit(path)

    def refresh_folder_icons(self, paths: list[str]) -> None:
        targets = set(paths)
        for job in list(self.jobs.values()):
            if job.operation == "icons" and targets.intersection(job.payload["paths"]):
                self._cancel_job(job)
        for path in paths:
            if self.folder_icons.pop(path, None) is not None:
                self.folderIconChanged.emit(path)

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
               timeout: float | None = None, force: bool = False) -> bool:
        """``timeout`` is seconds without progress (default: IOService's); ``math.inf`` for none."""
        if self.service.closed:
            return False
        path = self.key(path)
        payload = payload or {}
        if self.has_request(owner, operation, path):
            return True
        request = IORequest(owner, generation, path, operation, payload,
                            self.service.NO_PROGRESS_TIMEOUT if timeout is None else timeout)
        snapshot = self.snapshot(path) if operation in SCANS else None
        if snapshot and operation != "list" and not snapshot.status.get("details"):
            snapshot = None  # A names-only listing cannot answer a full scan.
        manual = bool(payload.get("scan_manual", force))
        blocked = self.scan_history(path)["blocked"]
        if operation in ("scan", "details") and blocked and not manual:
            # Browsing still lists a blocked folder; only full scans are skipped.
            self._deliver(request, {"kind": "scan_mode", "mode": "skipped"})
            return True
        if snapshot and not force:
            self._replay(request, snapshot, priority=priority)
            if blocked or time.monotonic() - snapshot.checked_at < self.FRESH_SECONDS:
                return True
            # Complete cached content first, then validate it once in a helper.
            request.payload = {**payload, "revalidate": True}
            return True
        if operation == "cached" and ("invalidate", path) in self.jobs:
            return False
        if operation == "load":
            if ("invalidate", path) in self.jobs:
                return False
            entry = self.dataset(path, payload.get("signature", ""))
            if entry and not self.verified(entry):
                # Cached data not checked against the folder yet: only this
                # session's own scan of the folder can confirm it.
                snapshot = self.snapshots.get(path)
                if snapshot and snapshot.status.get("signature") == entry.signature:
                    entry.metadata["verified"] = True
                else:
                    entry = None
            if entry:
                self._deliver(request, {"kind": "loaded", "dataset": entry, **entry.metadata,
                                        "cached": True, "source": "memory", "cache_reason": "",
                                        "disk_cache_pending": False,
                                        "load_counts": {"reused_memory": len(entry.data), "reused_disk": 0,
                                                        "read": 0, "new": 0, "modified": 0, "removed": 0,
                                                        "new_loaded": 0, "modified_loaded": 0}})
                return True
        if operation in SCANS and ("invalidate", path) in self.jobs:
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
                self.submit(owner, generation, path, operation, payload, priority=priority, force=True)
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
            if priority and operation != "load":
                self.service.promote(job.owner)
            if timeout is not None and math.isinf(timeout):
                self.service.set_timeout(job.owner, timeout)
            job.subscribers[(owner, generation)] = request
            self._catch_up(job, request)
            self.service.reschedule()
            return True
        if operation == "invalidate":
            self._cleared_at[path] = time.monotonic()
            self._cleared_at.move_to_end(path)
            while len(self._cleared_at) > self.MAX_SNAPSHOTS:
                self._cleared_at.popitem(last=False)
            self._cache_states[path] = CacheStatus()
            self._set_disk_cached(path, False)
            self._invalidate_data(path)
            self._base_floor[path] = self._epochs[path]
            snapshot = self.snapshot(path)
            if snapshot:
                snapshot.checked_at = 0
        base = self._base(path) if operation == "load" else None
        if base:
            payload = {**payload, "memory": [list(entry) for entry in base.metadata["fingerprint"]
                                             if entry[0] in base.data],
                       "base_signature": base.signature}
        job = SharedJob(uuid4().hex, path, operation, self._epochs.get(path, 0), payload, base=base)
        if operation in SCANS:
            job.payload = payload = {**payload, "scan_operation_id": job.owner,
                                     "scan_revision": time.time_ns(), "scan_manual": manual}
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
                                           "metadata_only": bool(request.payload.get("metadata_only")),
                                           "checked_at": snapshot.checked_at})
            self.resultReady.emit(request, {"kind": "done", "cached": True})
            if request in self._deliveries:
                self._deliveries.remove(request)
            if request.payload.get("revalidate") and not request.cancelled.is_set():
                # The check itself must not request another check when it completes.
                payload = {k: v for k, v in request.payload.items() if k != "revalidate"}
                payload.update(scan_manual=False, automatic=True)
                if self.scan_history(request.path)["blocked"]:
                    return
                self.submit(request.owner, request.generation, request.path, request.operation, payload,
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

    def _cleared_since(self, job: SharedJob, path: str) -> bool:
        """A scan that started before a cache clear may report the cleared entry."""
        return job.created < self._cleared_at.get(path, float("-inf"))

    def _adopt_load_summary(self, path: str, status: dict[str, Any]) -> None:
        """A load's listing and fingerprint complete a names-only listing of the same files."""
        self.remember_scan(path, status)
        snapshot = self.snapshots.get(path)
        if (snapshot and not snapshot.status.get("signature")
                and snapshot.status.get("txy") == status["txy"] and snapshot.status.get("raw") == status["raw"]):
            # Subfolder dates and identities still need the details scan.
            snapshot.status = {**snapshot.status, **{key: status[key] for key in (
                "signature", "identity", "modified")}, "details": not status["has_dirs"]}

    def _cancel_replays(self, path: str) -> None:
        for request in list(self._deliveries):
            if request.path == path and request.operation in SCANS:
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
        for operation in ("load", "cached"):
            job = self.jobs.get((operation, path))
            if job:
                self._cancel_job(job)
        for key in [key for key in self.datasets if key[0] == path]:
            del self.datasets[key]
        for request in self._deliveries:
            if request.operation in ("load", "cached") and request.path == path:
                request.cancelled.set()
        self.datasetChanged.emit(path)

    def cancel_automatic_scans(self, owner: str) -> list[IORequest]:
        """Drop only this tab's automatic status work; shared/manual work survives."""
        cancelled = []
        for request in tuple(self.requests(owner)):
            if (request.operation in SCANS and not request.payload.get("listing_only")
                    and not request.payload.get("scan_manual") and (
                    request.payload.get("automatic") or request.payload.get("revalidate")
                    or request.operation in ("scan", "details"))):
                request.payload["refresh_cancelled"] = True
                self.cancel(owner, request.operation, request.path)
                cancelled.append(request)
        return cancelled

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
        self._catch_up(job, request)
        # Leaving or joining the current tab moves the load between I/O lanes.
        self.service.reschedule()
        return True

    def _catch_up(self, job: SharedJob, request: IORequest) -> None:
        self.resultReady.emit(request, {"kind": job.state, "attempt": job.attempt})
        if job.progress is not None:
            self.resultReady.emit(request, job.progress)
        if job.load_status is not None:
            self.resultReady.emit(request, job.load_status)
        if job.paused:
            self.resultReady.emit(request, {"kind": "paused"})

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
        self._disk_cache_writers.clear()
        self._finishing_epochs.clear()
        self._cache_states.clear()
        self._cleared_at.clear()
        self.scan_summaries.clear()
        self.metadata_notifications.clear()
        self.listing_notifications.clear()
        self.scan_histories.clear()
        self.scan_history_errors.clear()
        self.folder_icons.clear()
        self._history_identity_dates.clear()
        self._subtree_timer.stop()
        self.subtrees.clear()
        self._subtree_pending.clear()

    def _on_event(self, producer: IORequest, event: dict[str, Any]) -> None:
        if producer.owner == self._subtree_writer:
            if event["kind"] in ("error", "cancelled"):
                logging.warning("Subfolder status save: %s", event.get("message", "Save cancelled"))
            if event["kind"] in ("done", "error", "cancelled"):
                self._subtree_writer = ""
                if self._subtree_pending:
                    self._subtree_timer.start(self.SUBTREE_SAVE_DELAY_MS)
            return
        if producer.owner in self._history_writes:
            path = self._history_writes[producer.owner]
            if event["kind"] == "scan_history_saved":
                self.scan_history_errors.pop(path, None)
                self.remember_history(path, event["history"])
            elif event["kind"] in ("error", "cancelled"):
                self.scan_history_errors[path] = "Scan history save failed; suppression is session-only."
                logging.warning("Scan history %s: %s", path, event.get("message", "Save cancelled"))
                self.scanHistoryChanged.emit(path)
            if event["kind"] in ("done", "error", "cancelled"):
                self._history_writes.pop(producer.owner, None)
            return
        job = self._producers.get(producer.owner)
        if job is None and producer.owner in self._finishing:
            path = self._finishing[producer.owner]
            kind = event["kind"]
            valid = self._finishing_epochs.get(producer.owner) == self._epochs.get(path, 0)
            was_saving = producer.owner in self._disk_cache_writers
            if kind in ("cache_saved", "cache_save_failed", "disk_cached", "cache_warning", "done", "error", "cancelled"):
                self._disk_cache_writers.discard(producer.owner)
            if valid and kind == "cache_saved":
                state = self._cache_states.setdefault(path, CacheStatus())
                state.info, state.error = dict(event["cache_info"]), ""
                for entry in self.datasets.values():
                    if entry.path == path and entry.signature == state.info.get("signature"):
                        entry.metadata.update(cache_info=state.info, disk_cached=True, disk_cache_pending=False)
                self._set_disk_cached(path, True, notify=True)
            elif valid and kind == "disk_cached":
                self._set_disk_cached(path, bool(event["disk_cached"]), notify=was_saving)
            elif valid and (kind == "cache_save_failed" or was_saving and kind in (
                    "cache_warning", "done", "error", "cancelled")):
                state = self._cache_states.setdefault(path, CacheStatus())
                state.error = event.get("message", "Cache save did not complete")
                self.diskCacheChanged.emit(path)
            if kind == "cache_warning":
                logging.warning("Folder cache %s: %s", path, event["message"])
            if kind in ("done", "error", "cancelled"):
                del self._finishing[producer.owner]
                self._finishing_epochs.pop(producer.owner, None)
            return
        if job is None:
            # Non-shared IOService consumers retain their existing protocol.
            self.resultReady.emit(producer, event)
            return
        kind = event["kind"]
        if kind in ("paused", "resumed"):
            job.paused = kind == "paused"
        if kind in ("queued", "started"):
            job.paused = False
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
                job.load_status = None
        if job.operation in SCANS:
            if kind == "scan_history":
                self.remember_history(job.path, event.get("history"))
                if event.get("revision"):
                    job.payload["scan_revision"] = producer.payload["scan_revision"] = event["revision"]
                job.history_saved |= bool(event.get("saved"))
                return
            if kind == "scan_history_warning":
                self.scan_history_errors[job.path] = event["message"]
                logging.warning("Scan history %s: %s", job.path, event["message"])
                self.scanHistoryChanged.emit(job.path)
                return
            if kind == "scan_mode":
                job.scan_mode = event["mode"]
            if kind == "subtree_cached":
                self.remember_subtree(job.path, event["subtree"], notify=False)
                for request in tuple(job.subscribers.values()):
                    self.resultReady.emit(request, event)
                return
            if kind == "scan_cached":
                self.remember_scan(job.path, event["status"])
                for request in tuple(job.subscribers.values()):
                    self.resultReady.emit(request, event)
                return
            if kind == "entries":
                for entry in event["entries"]:
                    self.remember_history(entry["path"], entry.get("scan_history"), identity=entry.get("identity"),
                                          observed_at=entry.get("modified_observed_at", time.time()))
                    if entry.get("scan_status"):
                        self.remember_scan(entry["path"], entry["scan_status"])
                    if entry.get("subtree"):
                        self.remember_subtree(entry["path"], entry["subtree"], notify=False)
                    if "disk_cached" in entry and not self._cleared_since(job, entry["path"]):
                        self._observe_cache(entry["path"], entry)
                job.entries.extend(event["entries"])
                if len(job.entries) > self.MAX_ENTRIES:
                    logging.warning("%s failed: %s — Folder exceeds snapshot entry limit (%s entries)",
                                    self.service.LABELS.get(job.operation, job.operation), job.path,
                                    f"{self.MAX_ENTRIES:,}")
                    if job.scan_mode == "scan":
                        self._record_scan_outcome(job, {"message": "Folder exceeds snapshot entry limit"})
                    self._forget_job(job)
                    self.service.cancel(job.owner)
                    for request in tuple(job.subscribers.values()):
                        self.resultReady.emit(request, {"kind": "error", "message": "Folder exceeds snapshot entry limit"})
                return
            if kind == "status":
                self.remember_history(job.path, None, identity=event.get("identity"),
                                      observed_at=event.get("scanned_at", time.time()))
                if "disk_cached" in event and not self._cleared_since(job, job.path):
                    self._observe_cache(job.path, event)
                job.status = event
                job.completed_scan = FolderSnapshot(tuple(job.entries), event, time.monotonic())
                return
            if kind == "error" and job.completed_scan is not None:
                self.scan_history_errors[job.path] = "Folder status check completed, but saving its metadata failed."
                job.status = job.completed_scan.status
                job.entries = list(job.completed_scan.entries)
                kind = "done"
            if kind == "done" and job.status:
                # Only a full scan clears a failure; a listing does not check files.
                if job.operation != "list":
                    self._record_scan_outcome(job, event, success=True)
                old = self.snapshot(job.path)
                signature = job.status.get("signature")
                if old and signature and old.status.get("signature") not in (None, "", signature):
                    self._invalidate_data(job.path)
                checked_at = time.monotonic() - max(0, time.time() - job.status.get("scanned_at", time.time()))
                # A late status check must not replace a newer refresh's names,
                # including snapshots used by tabs opened after both jobs finish.
                newer_listing = old is not None and old.listed_at > job.created
                entries = old.entries if old is not None and newer_listing else tuple(job.entries)
                listed_at = old.listed_at if old is not None and newer_listing else job.created
                snapshot = FolderSnapshot(entries, job.status, checked_at, listed_at)
                if not job.payload.get("listing_only"):
                    self.remember_scan(job.path, job.status)
                if not newer_listing:
                    self._cancel_replays(job.path)
                self.snapshots[job.path] = snapshot
                self.snapshots.move_to_end(job.path)
                self._evict()
                if job.payload.get("metadata_only"):
                    self.metadata_notifications.add(job.path)
                if job.payload.get("listing_only"):
                    self.listing_notifications.add(job.path)
                try:
                    self.snapshotChanged.emit(job.path)
                finally:
                    self.metadata_notifications.discard(job.path)
                    self.listing_notifications.discard(job.path)
                self._forget_job(job)
                for request in tuple(job.subscribers.values()):
                    self._replay(request, snapshot)
                return
            if kind == "done" and job.scan_mode != "scan":
                event = {**event, "scan_skipped": job.scan_mode == "skipped"}
            if kind == "error" and job.scan_mode == "scan":
                self._record_scan_outcome(job, event)
        elif job.operation in ("load", "cached"):
            if kind == "file_started":
                attempt = event.get("attempt", job.attempt)
                job.load_status = event if attempt > 1 else None
                if attempt == job.attempt and attempt == 1:
                    return
                job.attempt = attempt
            if kind == "file_finished":
                job.load_status = None
                if job.attempt == 1:
                    return
                job.attempt = 1
            if kind == "heartbeat":
                job.load_status = event
            if kind == "progress":
                job.progress = event
                if job.load_status is not None and job.load_status["kind"] == "heartbeat":
                    job.load_status = None
            if kind == "scan_summary":
                self._adopt_load_summary(job.path, event["status"])
                return
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
                event = {"loaded_at": time.time(), **event}
                source_snapshot = self.snapshot(job.path)
                expected = source_snapshot.status.get("signature") if source_snapshot else None
                # Cached data is shown unchecked, even if the folder has changed since.
                if job.epoch != self._epochs.get(job.path, 0) or (
                        job.operation == "load" and expected and event.get("signature") != expected):
                    self._cancel_job(job)
                    if source_snapshot:
                        source_snapshot.checked_at = 0
                    self.snapshotChanged.emit(job.path)
                    return
                if "disk_cached" in event:
                    self._observe_cache(job.path, event)
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
                self._finishing_epochs[job.owner] = job.epoch
                if event.get("disk_cache_pending"):
                    self._disk_cache_writers.add(job.owner)
                    self._cache_states.setdefault(job.path, CacheStatus()).error = ""
                entry = Dataset(job.path, event["signature"], job.data, event, job.epoch)
                self.datasets[(job.path, entry.signature, entry.epoch)] = entry
                event = {**event, "dataset": entry}
                # Subscribers pin the dataset during delivery before eviction.
                for request in tuple(job.subscribers.values()):
                    self.resultReady.emit(request, event)
                self.datasetChanged.emit(job.path)
                self._evict()
                return
        elif job.operation == "icons":
            if kind == "folder_icon" and event["path"] in job.payload["paths"]:
                self.remember_folder_icon(event["path"], event.get("png", ""))
            elif kind in ("done", "error"):
                for path in job.payload["paths"]:
                    if path not in self.folder_icons:
                        self.remember_folder_icon(path)
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
