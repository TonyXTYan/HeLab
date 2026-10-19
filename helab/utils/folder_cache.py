"""Session memory reuse above isolated I/O; no filesystem or disk-cache reads."""
from __future__ import annotations

from collections import OrderedDict
import base64
from dataclasses import dataclass, field
import logging
import math
import os
import time
from typing import Any, Iterable
from uuid import uuid4

import numpy as np
import numpy.typing as npt
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap

from helab.utils import large_folder
from helab.utils.cache_store import APPROVAL_SHARE, KINDS, store_root
from helab.utils.constants import (
    DEFAULT_CHECK_LEVEL, DEFAULT_DISK_BUDGET, DEFAULT_LIVE_AUTOSAVE, DEFAULT_LIVE_INTERVAL, DEFAULT_RAM_STEPS,
    DISK_CACHE_ENABLED, cache_dir, cache_dir_enabled, ram_step_bytes,
)
from helab.utils.io_service import IORequest, IOService
from helab.utils.load_clock import LoadClock
from helab.utils.time_format import clock as clock_text
from helab.utils.scan_history import ScanHistory, empty_history, parse_history, apply_outcome


# Folder checks that list a folder: browse step 1 (names only), browse step 2
# (``details``, the full scan in the background) and a basic scan.
SCANS = ("list", "details", "scan")
# The saved fields a listing entry carries for each kind of disk cache record.
ENTRY_KEYS = {"datasets": ("disk_cached", "cache_info"), "summaries": ("scan_status",),
              "histories": ("scan_history",), "subtrees": ("subtree",)}
# The current tab's work that runs in the foreground I/O lane.
# (``root_create``: the user's Enable disk cache here…, one small write, runs like a listing.)
FOREGROUND_OPERATIONS = ("list", "resolve", "load", "root_create", "root_reassign", "root_remove")
# The user's marker writes: in the foreground whoever asked (a tab, Settings or a window).
MARKER_OPERATIONS = ("root_create", "root_reassign", "root_remove")


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
    cache_warning: str = ""
    # The helper found no disk cache for this folder by design (no data root, unsupported mount).
    cache_off: bool = False
    # The scan helper's save guard, handed to the follow-up history write.
    save_guard: dict[str, Any] | None = None
    completed_scan: FolderSnapshot | None = None
    created: float = field(default_factory=time.monotonic)
    paused: bool = False
    # Shared, so a tab joining a running load shows its real elapsed time.
    clock: LoadClock = field(default_factory=LoadClock)
    # The TXY file a load is reading now ("" between files), for the I/O tooltip.
    current_file: str = ""
    # A Live check (``io_helper.live_check``): keyed apart from ordinary loads of the folder, so
    # neither joins the other (their results differ).
    live: bool = False

    @property
    def key(self) -> tuple[str, str]:
        return ("live" if self.live else self.operation), self.path

    def saves(self) -> bool:
        """Whether a subscriber asked for a save (``FolderCache.save``), whatever the job's own payload."""
        return bool(self.payload.get("save")) or any(r.payload.get("save") for r in self.subscribers.values())


# Set from the saved setting at startup (``set_disk_budget``); sent with every request, with
# when it was set: the store keeps the latest, so a load that started before the user lowered
# the budget saves within the new one (``CacheStore._active_budget``).
_disk_budget = DEFAULT_DISK_BUDGET
_disk_budget_set_at = 0.0


def set_disk_budget(budget: int) -> None:
    global _disk_budget, _disk_budget_set_at
    _disk_budget, _disk_budget_set_at = int(budget), time.time()


def store_options() -> dict[str, Any]:
    """What a helper needs to open the disk cache, and its budget in bytes; {} when the
    cache is off for this session. The GUI process never opens the store."""
    if not (DISK_CACHE_ENABLED and cache_dir_enabled()):
        return {}
    return {"directory": store_root(cache_dir()), "budget": _disk_budget, "budget_set_at": _disk_budget_set_at}


class FolderCache(QObject):
    resultReady = pyqtSignal(object, object)
    snapshotChanged = pyqtSignal(str)
    datasetChanged = pyqtSignal(str)
    diskCacheChanged = pyqtSignal(str)
    scanHistoryChanged = pyqtSignal(str)
    folderIconChanged = pyqtSignal(str)
    # A folder's flags (S10: Don't cache, Don't auto-load) changed.
    folderPrefsChanged = pyqtSignal(str)
    # A flag couldn't be saved (path, why, the owner that set it); memory shows the saved state again.
    folderPrefsFailed = pyqtSignal(str, str, str)
    subtreeChanged = pyqtSignal(str)
    savedRefreshed = pyqtSignal(str)
    mountWarningChanged = pyqtSignal(str)
    # A removal from the disk cache: paths (None: every path) and the kinds removed.
    cacheRemoved = pyqtSignal(object, object)
    # Pending saves (waiting for Make room / Save update) were added or answered.
    pendingSavesChanged = pyqtSignal()
    # A cache_admin job's result: action, event (inventory, admin_result, swept, error).
    cacheAdminResult = pyqtSignal(str, object)
    # A cache_admin job ended: its owner, action, and "" or why it failed.
    cacheAdminDone = pyqtSignal(str, str, str)
    # The disk cache's live usage changed (``disk_usage``).
    diskUsageChanged = pyqtSignal()
    # Automatic loads of folders without cached data paused (True) or resumed (False).
    autoLoadPauseChanged = pyqtSignal(bool)
    # Usage crossed 80% of the budget (or rose another 10% after Ignore): ask the user once.
    diskNearlyFull = pyqtSignal()
    # The folders whose cached data doesn't match them (``mismatched``), their answers, or the
    # hold of loads and scans changed.
    mismatchesChanged = pyqtSignal()
    # A folder was found mismatched (again): the list window shows it.
    mismatchFound = pyqtSignal(str)
    # The session's count of mismatched folders reached 2, 4, 8…: loads and scans are held.
    mismatchWarning = pyqtSignal(int)
    # Data-root verification checked the local volume hints (``verified_volumes``): a cached
    # read that waited for its volume can run now.
    volumesVerified = pyqtSignal()
    # A folder became (or stopped being) a data root, or was found to have none (RAM only).
    dataRootsChanged = pyqtSignal(str)
    # The locations waiting for Same folder or Copy changed; one was found (the window opens).
    rootDuplicatesChanged = pyqtSignal()
    rootDuplicateFound = pyqtSignal(str)
    # A Same folder or Copy answer took effect: these folders are listed again by tabs showing them.
    rootDecided = pyqtSignal(list)
    # A finished load's disk cache save ended: the folder, and "saved", "pending" (waiting for the
    # user's answer), "superseded" (a later save covers it) or "failed".
    saveEnded = pyqtSignal(str, str)
    # The saves the quit window waits for changed (``quit_saves``).
    quitSavesChanged = pyqtSignal()
    MAX_FOLDER_ICONS = 4096
    # Seconds before a sweep the queue rejected is tried again.
    SWEEP_RETRY = 5.0
    # Data-root marker checks (``roots_verify``) start at most this often. A backstop only: they are
    # asked for by listings that report a mount table not yet asked about (``_verify_roots``).
    VERIFY_MIN_SECONDS = 5.0
    MAX_SUBTREES = 4096
    SUBTREE_SAVE_DELAY_MS = 500
    FRESH_SECONDS: float = 10.0
    MAX_SNAPSHOTS: int = 256
    MAX_ENTRIES: int = 100_000
    # Folders remembered as mismatched (``mismatched``): small entries, ~2-4 MB at most.
    MAX_MISMATCHED: int = 8192
    # From this many mismatched folders, the user may skip them for the session.
    SKIP_MISMATCHED_FROM = 8
    # After Ignore, the 80% dialog comes back when usage rises by this share of the budget.
    IGNORE_STEP = 0.1

    def __init__(self, service: IOService) -> None:
        super().__init__(service)
        # Helpers queued before a cache move open the cache where it is when they start.
        service.cache_options = store_options
        # The app's cache mover (S9, ``helab.views.CacheMover.cache_mover``): kept here so a move
        # outlives the Settings dialog that started it.
        self.cache_mover: QObject | None = None
        # Settings → General's check of cached data, sent with every load (``io_helper.load``).
        self.check_level = DEFAULT_CHECK_LEVEL
        # Live: seconds from the end of one check to the next (Settings → General), and how many
        # new shots wait in RAM before the folder is saved (Settings → Cache).
        self.live_interval = DEFAULT_LIVE_INTERVAL
        self.live_autosave_shots = DEFAULT_LIVE_AUTOSAVE
        # Saves (loads with ``save`` in their payload) waiting for the folder's running save to
        # end, so saves of one folder never overlap: folder → (owner, payload).
        self._deferred_saves: dict[str, tuple[str, dict[str, Any]]] = {}
        # Quitting waits for saves (``cancel_for_quit``): no other folder work starts meanwhile.
        self.quitting = False
        # Each folder's flags, as the store or this session last said: {"no_cache", "no_auto_load", "set_at"}.
        self.prefs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        # What the store last confirmed for each folder (listings, saves): shown again if a choice fails.
        self._confirmed_prefs: dict[str, dict[str, Any]] = {}
        # Flag saves in flight: job owner → (path, the choice's set_at, who set it).
        self._pref_writes: dict[str, tuple[str, float, str]] = {}
        self.service = service
        self.snapshots: OrderedDict[str, FolderSnapshot] = OrderedDict()
        self.datasets: OrderedDict[tuple[str, str, int], Dataset] = OrderedDict()
        self.pins: dict[str, Dataset] = {}
        # The RAM budget for datasets no tab shows (Settings → Cache; ``set_ram_budget``).
        self.max_data_bytes = DEFAULT_RAM_STEPS * ram_step_bytes()
        self.total_ram = large_folder.total_ram()
        # The disk cache's live bytes, as the newest helper measurement reported them.
        self.disk_usage: int | None = None
        # Which store and write count it was measured at (``CacheStore.Usage``).
        self._usage_seq: tuple[str, int] | None = None
        self.auto_load_paused = False
        # The 80% dialog was shown for this crossing; after Ignore, the usage it waits for.
        self._full_warned = False
        self._full_ignored_until: float | None = None
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
        # When each finishing load started: a removal since then voids its cache events.
        self._finishing_created: dict[str, float] = {}
        # A folder check run beside its cached read (``cache_base``) that finished first: its
        # events wait (by producer owner) until that read's dataset is in memory to complete it.
        self._awaiting_cached: dict[str, list[dict[str, Any]]] = {}
        # Folders that no longer have shots cached or loaded from them (a load's ``shots_missing``,
        # a scan's ``cache_mismatch``): their data in RAM was dropped and their cached data isn't
        # shown, until a load completes. Session-only; each entry is what was found
        # (``missing``, ``missing_count``, ``known_count``, ``listed_count``), when
        # (``found_at``), by what (``source``: load or scan), and the user's ``answer``
        # ("", "load" or "dont_load").
        self.mismatched: OrderedDict[str, dict[str, Any]] = OrderedDict()
        # Folders found mismatched this session (each counted when it joins ``mismatched``):
        # at 2, 4, 8… loads and scans are held (``IOService.mismatch_hold``) until the user answers.
        self.mismatch_count = 0
        # The user chose to skip mismatched folders for the session: no more holds or windows.
        self.skip_mismatched = False
        # Folders whose next load reads them as they are now, although shots are missing
        # (Load as it is now): sent as ``allow_missing`` and never with a RAM base.
        self.allow_missing: set[str] = set()
        self._awaiting_producers: dict[str, IORequest] = {}
        self._cache_states: OrderedDict[str, CacheStatus] = OrderedDict()
        # When each folder's disk cache was last cleared; older scans saw stale entries.
        self._cleared_at: OrderedDict[str, float] = OrderedDict()
        self.scan_summaries: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.metadata_notifications: set[str] = set()
        self.listing_notifications: set[str] = set()
        self.scan_histories: OrderedDict[str, ScanHistory] = OrderedDict()
        self.scan_history_errors: dict[str, str] = {}
        # A listing or scan that couldn't read the disk cache: its saved flags are unknown.
        self.cache_read_errors: OrderedDict[str, str] = OrderedDict()
        # One unsupported-network notice per mount for this session.
        self.mount_warnings: dict[str, tuple[str, str]] = {}
        # Data roots seen this session (folder → uuid, label): their folders and subfolders use
        # the disk cache. Folders a helper found without one (RAM only), with the reason.
        self.data_roots: dict[str, tuple[str, str]] = {}
        self.unrooted: OrderedDict[str, str] = OrderedDict()
        # Locations whose .helab-root is also at another location, awaiting Same folder or Copy
        # (D4), by location key; each with its "answer" this session ("", "later" or "snoozed").
        self.root_duplicates: OrderedDict[str, dict[str, Any]] = OrderedDict()
        # Native icons (including unsuccessful lookups) are session-only and bounded.
        self.folder_icons: OrderedDict[str, QIcon] = OrderedDict()
        self._history_writes: dict[str, str] = {}
        # Statuses derived from subfolders, newest per folder; status "" marks a removal.
        # Saved by one batched helper write at a time, after a short delay.
        self.subtrees: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._subtree_pending: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._subtree_writer = ""
        self._subtree_options: dict[str, Any] = {}
        self._cleanup = ""
        self._root_verify_owner = ""
        self._volume_verify_owner = ""
        # The local mounts (path, device) whose volume IDs this session's last verification
        # checked: the only hints a cached read trusts, besides the system volume's.
        self._verified_volumes: tuple[tuple[str, str], ...] = ()
        self._roots_mounts: tuple[tuple[str, str], ...] | None = None
        self._mounts_observed: tuple[tuple[str, str], ...] | None = None
        # The mounts listings had reported when verification was last asked for: listed again
        # while it waits, the same mounts don't ask again.
        self._verify_asked: tuple[tuple[str, str], ...] | None = None
        # The last volume check's IDs (path, device, ID), handed to the marker check when it starts
        # (``_before_start``) so it doesn't check the volumes again.
        self._volume_ids: tuple[tuple[str, str, str], ...] = ()
        # Asked for again while a check runs: one more after it (each at most once).
        self._volumes_again = False
        self._markers_again = False
        # The marker check waits for the volume check asked for with it.
        self._markers_wanted = False
        self._markers_started = -math.inf
        self._markers_timer = QTimer(self)
        self._markers_timer.setSingleShot(True)
        self._markers_timer.timeout.connect(self._verify_markers)
        # cache_admin jobs by owner: their action.
        self._admin: dict[str, str] = {}
        # When cache_admin jobs and history writes started: removals since then void their results.
        self._started: dict[str, float] = {}
        # When each kind was last removed from the disk cache, for every path or per path;
        # results read before then are stale.
        self._removed_all: dict[str, float] = {}
        self._removed_paths: OrderedDict[tuple[str, str], float] = OrderedDict()
        # Saves waiting for the user's answer, by folder: the cache_full / cache_approval event.
        self.pending_saves: dict[str, dict[str, Any]] = {}
        # What late events must not undo: pending ids answered, superseded or expired; each
        # folder's newest job_seq whose save outcome arrived; when events last changed a folder's
        # pending save (an inventory requested before then doesn't override it).
        self._pending_gone: OrderedDict[str, None] = OrderedDict()
        self._save_seq: dict[str, int] = {}
        self._pending_changed: dict[str, float] = {}
        # When the newest inventory applied was requested; an older one arriving later is stale.
        self._inventory_started = float("-inf")
        # One timer for the store's next cleanup deadline (wall clock).
        self._sweep_deadline: float | None = None
        # ``sync_budget``: the job telling the store the app's disk budget, retried until it has.
        self._budget_owner = ""
        self._budget_timer = QTimer(self)
        self._budget_timer.setSingleShot(True)
        self._budget_timer.timeout.connect(self.sync_budget)
        self._restore_timer = QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.timeout.connect(self.restore_pending)
        self._sweep_timer = QTimer(self)
        self._sweep_timer.setSingleShot(True)
        self._sweep_timer.timeout.connect(self._sweep_due)
        self._subtree_timer = QTimer(self)
        self._subtree_timer.setSingleShot(True)
        self._subtree_timer.timeout.connect(self._save_subtrees)
        # Subscriber owners of the current tab (its model, and in queue mode its
        # background loads); their listings and loads use the foreground lane.
        self.foreground_owners: set[str] = set()
        service.is_foreground = self._is_foreground
        service.owners_of = self._owners_of
        service.before_start = self._before_start
        service.resultReady.connect(self._on_event)

    def _is_foreground(self, request: IORequest) -> bool:
        job = self._producers.get(request.owner)
        return (job is not None and job.operation in FOREGROUND_OPERATIONS
                and (job.operation in MARKER_OPERATIONS
                     or any(r.owner in self.foreground_owners for r in job.subscribers.values())))

    def _owners_of(self, request: IORequest) -> list[str]:
        """Whom a helper works for: its shared job's subscribers (tabs), for the I/O trace."""
        job = self._producers.get(request.owner)
        return sorted({r.owner for r in job.subscribers.values()}) if job is not None else [request.owner]

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

    def refresh_saved(self, paths: Iterable[str]) -> None:
        """Let a toolbar relisting replace these paths' RAM status with its saved records."""
        keys = {self.key(path) for path in paths}
        for path in keys:
            self.scan_summaries.pop(path, None)
            self.scan_histories.pop(path, None)
            self.scan_history_errors.pop(path, None)
            self.subtrees.pop(path, None)
            self._subtree_pending.pop(path, None)
            self.snapshots.pop(path, None)
        for dataset in (*self.datasets.values(), *self.pins.values()):
            if dataset.path in keys:
                dataset.metadata["checked_at"] = float("-inf")
        for path in keys:
            self.savedRefreshed.emit(path)

    def mount_warning(self, path: str) -> tuple[str, str] | None:
        matches = [(mount, warning) for mount, warning in self.mount_warnings.items()
                   if path == mount or path.startswith(mount.rstrip("/\\") + os.sep)]
        return max(matches, key=lambda item: len(item[0]))[1] if matches else None

    def root_of(self, path: str) -> tuple[str, str, str] | None:
        """The nearest data root seen this session at or above ``path``: (folder, uuid, label)."""
        matches = [(root, info) for root, info in self.data_roots.items()
                   if path == root or path.startswith(root.rstrip("/\\") + os.sep)]
        if not matches:
            return None
        root, (identifier, label) = max(matches, key=lambda item: len(item[0]))
        return root, identifier, label

    def mount_of(self, path: str) -> str | None:
        """The mount point holding ``path``, from the mount table listings last reported (memory)."""
        mounts = [mount for mount, _ in self._mounts_observed or ()
                  if path == mount or path.startswith(mount.rstrip("/\\") + os.sep)]
        return max(mounts, key=len) if mounts else None

    def no_root(self, path: str) -> str | None:
        """Why this folder uses RAM only (no data root, or one not yet confirmed), if a helper said so."""
        return self.unrooted.get(path)

    def _root_seen(self, path: str, identifier: str, label: str) -> None:
        cleared = [folder for folder in self.unrooted
                   if folder == path or folder.startswith(path.rstrip("/\\") + os.sep)]
        for folder in cleared:
            del self.unrooted[folder]
        if self.data_roots.get(path) != (identifier, label) or cleared:
            self.data_roots[path] = (identifier, label)
            self.dataRootsChanged.emit(path)

    def _root_reported(self, root: dict[str, Any]) -> None:
        folder, identifier = str(root["path"]), str(root["uuid"])
        known = self.data_roots.get(folder)
        # (No label when the location's row couldn't be matched: keep the one known.)
        label = str(root["label"]) or (known[1] if known and known[0] == identifier else "")
        self._root_seen(folder, identifier, label)

    def _root_duplicate(self, event: dict[str, Any]) -> None:
        """Once per location per session the window opens; after Later, again at its next sighting;
        after Remind me next session, not again this session."""
        location = str(event["location"])
        entry = self.root_duplicates.get(location)
        answer = entry["answer"] if entry is not None else ""
        found = entry is None or answer == "later"
        self.root_duplicates[location] = {**event, "found_at": time.time(),
                                          "answer": "" if found else answer}
        self.rootDuplicatesChanged.emit()
        if found:
            self.rootDuplicateFound.emit(location)

    def _duplicate_settled(self, *locations: str) -> None:
        if any([self.root_duplicates.pop(location, None) is not None for location in locations]):
            self.rootDuplicatesChanged.emit()

    def pending_root(self, path: str) -> dict[str, Any] | None:
        """The nearest location awaiting Same folder or Copy at or above ``path`` (its folder uses RAM only)."""
        matches = [entry for entry in self.root_duplicates.values()
                   if path == entry["path"] or path.startswith(str(entry["path"]).rstrip("/\\") + os.sep)]
        return max(matches, key=lambda entry: len(entry["path"])) if matches else None

    def answer_root_duplicate(self, location: str, answer: str) -> None:
        """Later or Remind me next session (``snoozed``): the location stays RAM only meanwhile."""
        if (entry := self.root_duplicates.get(location)) is not None and entry["answer"] != answer:
            entry["answer"] = answer
            self.rootDuplicatesChanged.emit()

    def same_root(self, location: str) -> str:
        """Same folder: the pending location uses its root's cached data (a local-lane job's owner)."""
        entry = self.root_duplicates.get(location)
        return self.cache_admin("root_same", location=location, uuid=entry["uuid"]) if entry else ""

    def remove_root(self, owner: str, path: str, identifier: str, location: str) -> bool:
        """Delete .helab-root…: the marker in ``path`` goes if it still holds ``identifier``, and its
        location is forgotten; open tabs list the folder again (``rootDecided``)."""
        options = store_options()
        return bool(options) and self.submit(owner, 0, path, "root_remove",
                                             {"cache": options, "uuid": identifier, "location": location},
                                             priority=True)

    def reassign_root(self, owner: str, generation: int, location: str, keep: str) -> bool:
        """It's a copy…: the location not kept gets a new .helab-root. ``keep`` is the location
        keeping the cached data: the pending one, or one of the root's known locations."""
        entry = self.root_duplicates.get(location)
        options = store_options()
        if entry is None or not options:
            return False
        if keep == location:  # The pending copy keeps the data: the known folder is rewritten.
            target = next((str(other["path"]) for other in entry.get("others", []) if other.get("path")), "")
        else:
            target = str(entry["path"])
        if not target:
            return False
        return self.submit(owner, generation, target, "root_reassign",
                           {"cache": options, "old_uuid": entry["uuid"], "keep": keep, "duplicate": location},
                           priority=True)

    def _root_gone(self, path: str) -> None:
        if self.data_roots.pop(path, None) is not None:
            self.dataRootsChanged.emit(path)

    def _remember_unrooted(self, path: str, detail: str) -> None:
        if self.unrooted.get(path) != detail:
            self.unrooted[path] = detail
            self.unrooted.move_to_end(path)
            while len(self.unrooted) > self.MAX_FOLDER_ICONS:
                self.unrooted.popitem(last=False)
            self.dataRootsChanged.emit(path)

    def _remember_mount_warning(self, event: dict[str, Any]) -> None:
        for mount in event.get("mounts", []):
            path = str(mount["path"])
            if mount["type"] == "no data root":
                self._remember_unrooted(path, str(mount["detail"]))
                continue
            if path in self.mount_warnings:
                continue
            kind = str(mount["type"])
            label = {"nfs": "NFS", "nfs4": "NFS", "afpfs": "AFP", "webdav": "WebDAV",
                     "davfs": "WebDAV"}.get(kind.lower(), kind.upper())
            short = ("Disk cache off: this SMB drive's share couldn't be identified"
                     if kind == "unidentified SMB" else
                     f"Disk cache off: only SMB network drives are supported (this is {label})")
            detail = f"{short}\n{mount['detail']}\nMount: {path}. Browsing and source checks still work."
            self.mount_warnings[path] = (short, detail)
            self.mountWarningChanged.emit(path)

    def _clear_mount_warning(self, path: str) -> None:
        if self.unrooted.pop(path, None) is not None:
            self.dataRootsChanged.emit(path)
        for mount in list(self.mount_warnings):
            if path == mount or path.startswith(mount.rstrip("/\\") + os.sep):
                del self.mount_warnings[mount]
                self.mountWarningChanged.emit(mount)

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
        if not cache_options:
            return  # The disk cache is off: shared in memory only.
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
                               {"cache": self._subtree_options, "records": records,
                                "verified_volumes": self.verified_volumes()}):
            self._subtree_writer = owner
            return
        for record in records:  # Queue full: try again later, newer derivations first.
            self._subtree_pending.setdefault(record["path"], record)
        self._subtree_timer.start(5000)

    def scan_history(self, path: str) -> ScanHistory:
        return self.scan_histories.get(self.key(path), empty_history())

    def remember_history(self, path: str, value: object) -> None:
        path = self.key(path)
        current = self.scan_histories.get(path)
        if value is None and current is None:
            return
        history = parse_history(value) if value is not None else current
        if history is None:
            return
        if current is not None and current["revision"] > history["revision"]:
            return
        self.scan_histories[path] = history
        self.scan_histories.move_to_end(path)
        while len(self.scan_histories) > 4096:
            removed, _ = self.scan_histories.popitem(last=False)
            self.scan_history_errors.pop(removed, None)
        self.scanHistoryChanged.emit(path)

    def _record_scan_outcome(self, job: SharedJob, event: dict[str, Any], *, success: bool = False) -> None:
        if self._removed_since(job, "histories", job.path):
            return  # The history was cleared after this scan started; its outcome stays out.
        history = self.scan_history(job.path)
        outcome = {"operation_id": job.owner, "revision": job.payload["scan_revision"],
            "kind": "success" if success else "timeout" if event.get("timeout") else "io_error",
            "at": job.status.get("scanned_at", time.time()) if success and job.status else time.time(),
            "attempts": event.get("attempt", job.attempt),
            "reason": event.get("message", "Folder status check failed").removesuffix(" — Retry")}
        self.remember_history(job.path, apply_outcome(history, outcome))
        # Successful helpers persist their result before done. Compatibility
        # producers only need a write when recovering an existing failure.
        # Without a disk cache (off, or off by design for this folder) it stays in RAM: nothing failed.
        options = job.payload.get("cache")
        if job.history_saved or not options or job.cache_off or success and not history["failures"]:
            return
        owner = uuid4().hex
        self._history_writes[owner] = job.path
        self._started[owner] = time.monotonic()
        payload: dict[str, Any] = {"cache": options, "outcome": outcome,
                                   "verified_volumes": self.verified_volumes()}
        if job.save_guard is not None:
            payload["guard"] = job.save_guard
        if not self.service.submit(owner, 0, job.path, "scan_history", payload, priority=True):
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

    def _base(self, path: str, prefer: str = "") -> Dataset | None:
        # A dataset an open tab still shows survives signature changes, so a
        # refresh only needs the shots that are new or changed since then.
        # ``prefer``: the signature of the data the caller shows (Live), if still held.
        floor = self._base_floor.get(path, 0)
        candidates = [entry for entry in (*self.pins.values(), *self.datasets.values())
                      if entry.path == path and entry.epoch >= floor and "fingerprint" in entry.metadata]
        newest = max((entry.epoch for entry in candidates), default=None)
        preferred = next((entry for entry in candidates if prefer and entry.signature == prefer
                          and entry.epoch == newest), None)
        return preferred or max(candidates, key=lambda entry: entry.epoch, default=None)

    @staticmethod
    def verified(dataset: Dataset) -> bool:
        """False for data read from the disk cache that has not been checked against its folder."""
        return bool(dataset.metadata.get("verified", True))

    def holds(self, dataset: Dataset) -> bool:
        """Whether this dataset is still kept (not cleared, replaced or evicted)."""
        return any(entry is dataset for entry in self.datasets.values())

    def counts_as_checked(self, dataset: Dataset, signature: str = "") -> bool:
        """Whether this data needs no check of its folder now: the one rule for the tab's label
        and for answering a load from memory. Within ``FRESH_SECONDS`` (``checked_recently``),
        either this session's scan of the folder found the same files (as thorough as any check
        level: it fingerprinted every TXY file), or the data was checked (``verified``) and
        matches ``signature``, the folder's signature as the caller knows it. Data read from the
        disk cache counts only by such a scan."""
        snapshot = self.snapshots.get(dataset.path)
        scanned = snapshot is not None and snapshot.status.get("signature") == dataset.signature
        return self.checked_recently(dataset) and (
            scanned or (self.verified(dataset) and bool(signature) and signature == dataset.signature))

    def checked_recently(self, dataset: Dataset) -> bool:
        """Whether this data was checked against its folder in the last ``FRESH_SECONDS``: by
        the load that made it, or by a scan of the folder that found the same files."""
        checked = float(dataset.metadata.get("checked_at", -math.inf))
        snapshot = self.snapshots.get(dataset.path)
        if snapshot is not None and snapshot.status.get("signature") == dataset.signature:
            checked = max(checked, snapshot.checked_at)
        return time.monotonic() - checked < self.FRESH_SECONDS

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

    def empty_dataset(self, path: str) -> Dataset:
        """No shots yet: Live started before the folder's first shot. Not kept here; the tab that
        shows it pins it (``retain``), which makes it the base of the folder's Live checks, so
        the first check lists the folder and every TXY file it finds is new."""
        metadata = {"fingerprint": [], "problematic": [], "files": 0, "rows": 0, "bytes": 0,
                    "loaded_at": time.time(), "checked_at": time.monotonic(), "verified": True}
        return Dataset(path, "", {}, metadata, self._epochs.get(path, 0))

    def release(self, owner: str) -> None:
        self.pins.pop(owner, None)
        self._evict()

    def folder_prefs(self, path: str) -> dict[str, Any]:
        """A folder's flags (never its parent's or subfolders'): no_cache, no_auto_load."""
        saved = self.prefs.get(path) or {}
        return {"no_cache": bool(saved.get("no_cache")), "no_auto_load": bool(saved.get("no_auto_load"))}

    def remember_prefs(self, path: str, prefs: object, *, known: bool = True, confirmed: bool = True) -> None:
        """Keep a folder's flags; a later choice (``set_at``) wins. ``known=False`` (a listing that
        found none) only fills in a folder this session knows nothing about. ``confirmed``: what
        the store said (not this session's unsaved choice)."""
        if not isinstance(prefs, dict):
            return
        if confirmed and prefs:
            saved = self._confirmed_prefs.get(path)
            if saved is None or float(saved.get("set_at", 0)) <= float(prefs.get("set_at", 0)):
                self._confirmed_prefs[path] = dict(prefs)
        current = self.prefs.get(path)
        if not prefs:
            if current is not None and not known:
                return
            prefs = {"no_cache": False, "no_auto_load": False, "set_at": 0.0}
        elif current is not None and float(current.get("set_at", 0)) > float(prefs.get("set_at", 0)):
            return
        before = self.folder_prefs(path)
        self.prefs[path] = dict(prefs)
        self.prefs.move_to_end(path)
        while len(self.prefs) > self.MAX_ENTRIES:
            self.prefs.popitem(last=False)
        if self.folder_prefs(path) != before:
            self.folderPrefsChanged.emit(path)

    def set_folder_prefs(self, path: str, *, no_cache: bool, no_auto_load: bool, remove_cached: bool = False,
                         owner: str = "") -> bool:
        """The user's choice for one folder: shown at once, then saved by a helper (with the folder's
        cached data removed too, if asked). If saving fails, the saved state is shown again and
        ``folderPrefsFailed`` says why. Session-only when the disk cache is off."""
        set_at = time.time()
        self.remember_prefs(path, {"no_cache": no_cache, "no_auto_load": no_auto_load, "set_at": set_at},
                            confirmed=False)
        if not store_options():
            return True
        job = self.cache_admin("prefs", path=path, no_cache=no_cache, no_auto_load=no_auto_load,
                               set_at=set_at, remove_cached=remove_cached)
        if not job:
            self._prefs_not_saved(path, set_at, "HeLab's work queue is full", owner)
            return False
        self._pref_writes[job] = (path, set_at, owner)
        return True

    def _prefs_not_saved(self, path: str, set_at: float, message: str, owner: str) -> None:
        current = self.prefs.get(path)
        if current is not None and float(current.get("set_at", 0)) == set_at:
            # Still this choice (not a newer one): show what the store last confirmed again.
            saved = self._confirmed_prefs.get(path)
            if saved is None:
                del self.prefs[path]
            else:
                self.prefs[path] = dict(saved)
            self.folderPrefsChanged.emit(path)
        self.folderPrefsFailed.emit(path, message, owner)

    def load_file(self, path: str) -> str:
        """The TXY file a running load of ``path`` is reading now ("" if none), from memory."""
        job = self.jobs.get(("load", self.key(path)))
        return job.current_file if job is not None else ""

    def load_note(self, producer: IORequest) -> tuple[list[str], str]:
        """For the I/O tooltip, from memory: the owners (tabs) a running load is for, and its
        progress, current file and time, e.g. "123 of 579 files (21%) · d_txy_forc123.txt · 1:23"."""
        job = self._producers.get(producer.owner)
        if job is None or job.operation != "load":
            return [], ""
        parts: list[str] = []
        progress = job.progress or {}
        total, checked = progress.get("total_files"), progress.get("checked_files")
        if isinstance(total, int) and isinstance(checked, int):
            parts.append(f"{checked:,} of {total:,} files ({checked / total:.0%})" if total else "no files")
        if job.current_file:
            parts.append(job.current_file)
        elapsed, remaining = job.clock.elapsed(), job.clock.remaining()
        if elapsed:
            parts.append(clock_text(elapsed) + (f", ~{clock_text(remaining)} left" if remaining else ""))
        return [request.owner for request in job.subscribers.values()], " · ".join(parts)

    def large_limits(self) -> dict[str, int]:
        """The large-folder thresholds sent with every load and cached read."""
        return large_folder.limits(self.max_data_bytes, self.total_ram)

    def large_estimate(self, path: str) -> int | None:
        """What loading ``path`` from its files would take in RAM, from memory only (no I/O):
        its saved summary's TXY size (the newer of this session's and the saved one); None
        if unknown. (A load whose cached dataset is larger doesn't unpack it.)"""
        snapshot = self.snapshots.get(path)
        newest: tuple[float, int] | None = None
        for status in (self.scan_summaries.get(path), snapshot.status if snapshot else None):
            files = status.get("files") if isinstance(status, dict) else None
            txy = files.get("txy") if isinstance(files, dict) else None
            if isinstance(txy, dict) and isinstance(txy.get("bytes"), int):
                assert isinstance(status, dict)
                at = status.get("scanned_at")
                measured = (float(at) if isinstance(at, (int, float)) else 0.0, int(txy["bytes"]))
                if newest is None or measured[0] >= newest[0]:
                    newest = measured
        return None if newest is None else newest[1]

    def cached_estimate(self, path: str) -> int | None:
        """What reading ``path``'s cached dataset would take in RAM (its TXY size); None if unknown."""
        cached = self.cache_status(path).info.get("txy_bytes")
        return cached if self.disk_cached(path) and isinstance(cached, int) else None

    def set_ram_budget(self, budget: int) -> list[Dataset]:
        """Apply a new RAM budget at once; the datasets it dropped from memory."""
        self.max_data_bytes = max(0, int(budget))
        return self._evict()

    def memory_usage(self) -> tuple[int, int, int]:
        """Loaded datasets in memory: (count, bytes, bytes shown in tabs)."""
        held = {id(entry): entry for entry in (*self.datasets.values(), *self.pins.values())}
        shown = {id(entry) for entry in self.pins.values()}
        total = sum(int(entry.metadata.get("bytes", 0)) for entry in held.values())
        pinned = sum(int(entry.metadata.get("bytes", 0)) for key, entry in held.items() if key in shown)
        return len(held), total, pinned

    def _evict(self) -> list[Dataset]:
        """Drop datasets no tab shows, least recently used first, until the rest fit the RAM budget."""
        dropped: list[Dataset] = []
        # Everything held in RAM, once each: tabs may still show datasets no longer in
        # ``datasets`` (e.g. invalidated), and those count too.
        _, total, _ = self.memory_usage()
        pinned = {id(entry) for entry in self.pins.values()}
        for key, entry in list(self.datasets.items()):
            if total <= self.max_data_bytes:
                break
            if id(entry) not in pinned:
                total -= int(entry.metadata.get("bytes", 0))
                del self.datasets[key]
                dropped.append(entry)
                self.datasetChanged.emit(entry.path)
        count = sum(len(s.entries) for s in self.snapshots.values())
        while self.snapshots and (len(self.snapshots) > self.MAX_SNAPSHOTS or count > self.MAX_ENTRIES):
            _, snapshot = self.snapshots.popitem(last=False)
            count -= len(snapshot.entries)
        return dropped

    def submit(self, owner: str, generation: int, path: str, operation: str,
               payload: dict[str, Any] | None = None, *, priority: bool = False,
               timeout: float | None = None, force: bool = False) -> bool:
        """``timeout`` is seconds without progress (default: IOService's); ``math.inf`` for none."""
        if self.service.closed:
            return False
        path = self.key(path)
        payload = payload or {}
        if self.quitting and not (operation == "load" and payload.get("save")):
            return False
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
            if entry and not self.counts_as_checked(entry, payload.get("signature", "")):
                entry = None  # Not checked lately: the load checks the folder (one stat when unchanged).
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
        live = operation == "load" and bool(payload.get("live"))
        job_key = ("live" if live else operation, path)
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
        # The data of a folder that lost shots may be another folder's: never a load's base.
        base = (self._base(path, str(payload.get("prefer_base") or "")) if operation == "load"
                and path not in self.mismatched and path not in self.allow_missing
                and not payload.get("allow_missing") else None)
        if base:
            payload = {**payload, "memory": [list(entry) for entry in base.metadata["fingerprint"]
                                             if entry[0] in base.data],
                       "base_signature": base.signature}
            if self.verified(base) and base.metadata.get("listed_at") and base.metadata.get("identity"):
                # The quick check of the data in RAM when no cached dataset has one (``io_helper``).
                payload["memory_check"] = {key: base.metadata.get(key) for key in (
                    "listed_at", "names", "identity", "fingerprint", "problematic", "data_root")} | {
                    "signature": base.signature, "unsettled": base.metadata.get("unsettled_files", 0)}
        arrays: dict[int, npt.NDArray[np.float64]] | None = None
        if operation == "load" and payload.get("save_memory"):
            if base is not None and base.data:
                # Live's save: the data in RAM is saved as it is (``io_helper.save_held``), its arrays
                # handed to the helper; its files are checked, not read.
                arrays = dict(base.data)
                payload = {**payload, "held": [list(entry) for entry in base.metadata["fingerprint"]],
                           "held_problematic": list(base.metadata.get("problematic", ()))}
            else:
                payload = {key: value for key, value in payload.items() if key != "save_memory"}
        job = SharedJob(uuid4().hex, path, operation, self._epochs.get(path, 0), payload, base=base, live=live)
        if operation in SCANS:
            job.payload = payload = {**payload, "scan_operation_id": job.owner,
                                     "scan_revision": time.time_ns(), "scan_manual": manual}
        job.subscribers[(owner, generation)] = request
        self.jobs[job_key] = job
        self._producers[job.owner] = job
        if not self.service.submit(job.owner, 0, path, operation, payload, priority=priority, timeout=timeout,
                                   arrays=arrays):
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
        if self.jobs.get(job.key) is job:
            del self.jobs[job.key]
        if job.operation == "load" and not job.live and job.path in self._deferred_saves:
            # A save waiting for this load: it starts once the load (and any write it does) ends.
            QTimer.singleShot(0, lambda: self._start_deferred(job.path))
        self._producers.pop(job.owner, None)
        self._awaiting_cached.pop(job.owner, None)
        if job.operation == "cached" and job.path in self._awaiting_producers:
            # A check waits for this read: completed by its dataset, or failed without it.
            QTimer.singleShot(0, lambda: self._resume_awaiting(job.path))

    def _resume_awaiting(self, path: str) -> None:
        producer = self._awaiting_producers.pop(path, None)
        if producer is None:
            return
        for event in self._awaiting_cached.pop(producer.owner, None) or ():
            self._on_event(producer, event)

    def _mismatch(self, path: str, event: dict[str, Any] | None = None, source: str = "load") -> None:
        """``path`` no longer has shots cached or loaded from it: drop its data from RAM (tabs that
        show it keep their pins until they let go), so nothing shows it again until a load completes.
        A folder new to the list counts; at 2, 4, 8… loads and scans are held for the user."""
        event = event or {}
        earlier = self.mismatched.pop(path, None)
        self.mismatched[path] = {
            "missing": [int(shot) for shot in event.get("missing", [])],
            "missing_count": int(event.get("missing_count", len(event.get("missing", [])))),
            "known_count": int(event.get("known_count", 0)), "listed_count": int(event.get("listed_count", 0)),
            "found_at": time.time(), "source": source,
            # Found again (Retry, another check): the answer stands, unless it was to load it.
            "answer": earlier["answer"] if earlier and earlier["answer"] != "load" else ""}
        while len(self.mismatched) > self.MAX_MISMATCHED:
            self.mismatched.popitem(last=False)  # The oldest.
        for key in [key for key in self.datasets if key[0] == path]:
            del self.datasets[key]
        self.datasetChanged.emit(path)
        if earlier is None:
            self.mismatch_count += 1
            count = self.mismatch_count
            if not self.skip_mismatched and count >= 2 and count & (count - 1) == 0:
                self.service.set_mismatch_hold(True)
                logging.warning("Cached data doesn't match %d folders: loads and scans held", count)
                self.mismatchWarning.emit(count)
        self.mismatchFound.emit(path)
        self.mismatchesChanged.emit()

    def _matched(self, path: str) -> None:
        """A load of ``path`` completed: its data matches the folder again."""
        self.allow_missing.discard(path)
        if self.mismatched.pop(path, None) is not None:
            self.mismatchesChanged.emit()

    def answer_mismatches(self, paths: list[str], answer: str) -> None:
        """The user's answer for these folders: "load" (their next load reads them as they are
        now) or "dont_load" (nothing is read; they stay listed)."""
        for path in paths:
            entry = self.mismatched.get(path)
            if entry is None:
                continue
            entry["answer"] = answer
            if answer == "load":
                self.allow_missing.add(path)
            else:
                self.allow_missing.discard(path)
        self.mismatchesChanged.emit()

    def take_allow_missing(self, path: str) -> bool:
        """Whether this load of ``path`` reads it as it is now (the user's answer); used once."""
        if path in self.allow_missing:
            self.allow_missing.discard(path)
            return True
        return False

    def resume_after_mismatch(self) -> None:
        """Let held loads and scans go on."""
        self.service.set_mismatch_hold(False)
        self.mismatchesChanged.emit()

    def cancel_held_io(self) -> None:
        """Cancel every load and scan (queued, running or held), then stop holding them."""
        self.service.cancel_operations(self.service.MISMATCH_HELD)
        self.resume_after_mismatch()

    def skip_mismatches(self) -> None:
        """For the rest of the session: mismatched folders are listed but nothing else is
        shown, and loads and scans are no longer held for them."""
        self.skip_mismatched = True
        self.resume_after_mismatch()

    def _fail_job(self, job: SharedJob, message: str) -> None:
        self._forget_job(job)
        self.service.cancel(job.owner)
        for request in tuple(job.subscribers.values()):
            self.resultReady.emit(request, {"kind": "error", "message": message})

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
        return job.created < self._cleared_at.get(path, float("-inf")) or self._removed_since(job, "datasets", path)

    def _adopt_load_summary(self, path: str, status: dict[str, Any], *, live: bool = False) -> None:
        """A load's listing and fingerprint complete a names-only listing of the same files.

        A Live check's (``live``) found new shots just now: the snapshot takes its files and
        counts as freshly listed, so tabs show the new counts without listing the folder again."""
        self.remember_scan(path, status)
        snapshot = self.snapshots.get(path)
        if snapshot and live:
            snapshot.status = {**snapshot.status, **status,
                               "details": bool(snapshot.status.get("details")) or not status["has_dirs"]}
            snapshot.checked_at = time.monotonic()
            self.snapshotChanged.emit(path)
        elif (snapshot and not snapshot.status.get("signature")
                and snapshot.status.get("txy") == status["txy"] and snapshot.status.get("raw") == status["raw"]):
            # Subfolder dates still need the details scan.
            snapshot.status = {**snapshot.status, **{key: status[key] for key in (
                "signature", "modified")}, "details": not status["has_dirs"]}
        elif (snapshot and snapshot.status.get("signature") != status["signature"]
              and float(status.get("scanned_at") or 0) > float(snapshot.status.get("scanned_at") or 0)):
            # The folder changed after its details scan, and this load listed it later: its
            # files are the current ones (else the finished load is dropped as out of date).
            # Subfolder entries and their dates still come from the details scan. Without
            # subfolders, that listing was the whole folder: as fresh as a check of it, so tabs
            # showing it needn't list it again.
            snapshot.status = {**snapshot.status, **status,
                               "details": bool(snapshot.status.get("details")) or not status["has_dirs"]}
            if not status["has_dirs"]:
                snapshot.checked_at = time.monotonic()
            self.snapshotChanged.emit(path)

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

    def _drop_superseded(self, entry: Dataset) -> None:
        """A dataset that reuses an older one's arrays (``memory_shots``: an update or a Live check)
        replaces the folder's older datasets no tab shows: they describe files the folder has moved
        past, and each would count its shared arrays again against the RAM budget."""
        shown = {id(dataset) for dataset in self.pins.values()}
        for key in [key for key, dataset in self.datasets.items()
                    if key[0] == entry.path and key[1] != entry.signature and id(dataset) not in shown]:
            del self.datasets[key]

    def _invalidate_data(self, path: str) -> None:
        self._epochs[path] = self._epochs.get(path, 0) + 1
        for operation in ("load", "live", "cached"):
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

    def save(self, owner: str, path: str, payload: dict[str, Any]) -> bool:
        """Save a folder's data shown in RAM to the disk cache with an ordinary load (Live's saves:
        its new shots are re-read from the folder, the rest come from the cache). Saves of one
        folder never overlap: while its previous save runs, this one waits (one per folder, the
        newest). It never joins another load of the folder that isn't a save either (that one may
        not save, or save with other choices): it waits for it to end. False if it couldn't be
        queued."""
        path = self.key(path)
        payload = {**payload, "save": True}
        if self._save_waits(path):
            self._deferred_saves[path] = (owner, payload)
            self.quitSavesChanged.emit()
            return True
        submitted = self.submit(owner, 0, path, "load", payload, priority=True)
        self.quitSavesChanged.emit()
        return submitted

    def _save_waits(self, path: str) -> bool:
        """A save of ``path`` waits: the folder's data is being written, or another load of it
        that isn't a save is running or queued."""
        job = self.jobs.get(("load", path))
        return self.disk_cache_saving(path) or (job is not None and not job.saves())

    def _start_deferred(self, path: str) -> None:
        if path not in self._deferred_saves or self._save_waits(path) or self.service.closed:
            return
        owner, payload = self._deferred_saves.pop(path)
        if not self.submit(owner, 0, path, "load", payload, priority=True):
            logging.warning("Disk cache save of %s: queue full", path)
            # Its owner waits for a load's outcome: this is it.
            request = IORequest(owner, 0, path, "load", payload, self.service.NO_PROGRESS_TIMEOUT)
            self.resultReady.emit(request, {"kind": "error", "message": "Save queue full"})
        self.quitSavesChanged.emit()

    def quit_saves(self) -> list[str]:
        """Folders whose data is being saved to the disk cache, or will be: what quitting waits
        for. A finished load's background save, and a save not yet started or still reading."""
        writing = [self._finishing[owner] for owner in self._disk_cache_writers if owner in self._finishing]
        loading = [job.path for job in self.jobs.values() if job.operation == "load" and job.saves()]
        return list(dict.fromkeys((*writing, *loading, *self._deferred_saves)))

    def cancel_for_quit(self) -> None:
        """Quitting: stop the reads, listings and loads nothing will show, and data-root
        verification, so saves get the I/O (a save waiting for a load it doesn't join then
        starts); none of those start again (``quitting``)."""
        self.quitting = True
        if self._root_verify_owner:
            self.service.cancel(self._root_verify_owner)
        for job in list(self.jobs.values()):
            if job.operation in ("load", "cached", "list", "details", "scan", "icons", "resolve") and not (
                    job.operation == "load" and job.saves()):
                self._cancel_job(job)

    def cancel(self, owner: str, operation: str | None = None, path: str | None = None) -> None:
        for folder, (waiting, _) in list(self._deferred_saves.items()):
            if waiting == owner and operation in (None, "load") and path in (None, folder):
                del self._deferred_saves[folder]
                self.quitSavesChanged.emit()
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
                 new_owner: str, new_generation: int, operation: str = "load") -> bool:
        """Move a load (or cached read) subscription to another owner without interrupting the shared job."""
        job = self.jobs.get((operation, self.key(path)))
        old = job.subscribers.get((owner, generation)) if job else None
        if job is None or old is None:
            return False
        del job.subscribers[(owner, generation)]
        old.cancelled.set()
        replaced = job.subscribers.get((new_owner, new_generation))
        if replaced:
            replaced.cancelled.set()
        request = IORequest(new_owner, new_generation, old.path, operation, old.payload, old.timeout)
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

    def load_clock(self, path: str) -> LoadClock | None:
        """The running load's clock for this folder, if it is loading."""
        job = self.jobs.get(("load", self.key(path)))
        return job.clock if job else None

    def promote(self, path: str) -> None:
        """Run this folder's queued load before other queued loads."""
        job = self.jobs.get(("load", self.key(path)))
        if job:
            self.service.promote(job.owner)

    def shutdown(self) -> None:
        self._deferred_saves.clear()
        self._sweep_timer.stop()
        self._restore_timer.stop()
        self._budget_timer.stop()
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
        self._finishing_created.clear()
        self._awaiting_cached.clear()
        self._awaiting_producers.clear()
        self.mismatched.clear()
        self.allow_missing.clear()
        self._cache_states.clear()
        self._cleared_at.clear()
        self.scan_summaries.clear()
        self.metadata_notifications.clear()
        self.listing_notifications.clear()
        self.scan_histories.clear()
        self.scan_history_errors.clear()
        self.cache_read_errors.clear()
        self.folder_icons.clear()
        self._subtree_timer.stop()
        self.subtrees.clear()
        self._subtree_pending.clear()

    def clean_up_cache(self) -> None:
        """Once per session, on the local lane: delete the old diskcache folders, and cache
        files past their grace period. Later sweeps run by deadline."""
        if self._cleanup or not store_options():
            return
        self._cleanup = self.cache_admin("sweep") or "failed"
        if self._cleanup == "failed":
            self._schedule_sweep(time.time() + self.SWEEP_RETRY)
        self.restore_pending()
        self._verify_roots()

    def _verify_roots(self) -> None:
        """Check the saved volume IDs at once on the local lane (cached reads of external volumes
        wait for that), then remembered marker locations in one background source helper, which
        reuses those IDs. Asked for at startup and by listings reporting a mount table not yet
        asked about; a check already queued sees the newest table when it starts, and one asked for
        while a check runs follows it once. Never asked again because a check saw a newer table
        than the listings reported: only a new listing observation asks."""
        options = store_options()
        if not options or self.service.closed or self.quitting:
            return
        self._verify_asked = self._mounts_observed
        if self._volume_verify_owner:
            self._volumes_again = self._volumes_again or self._started_request(self._volume_verify_owner)
        else:
            self._verify_volumes(options)
        running = self._started_request(self._root_verify_owner)
        if running:
            self._markers_again = True
        elif not self._root_verify_owner:
            self._markers_wanted = True
            if not self._volume_verify_owner:
                self._verify_markers()

    def _started_request(self, owner: str) -> bool:
        return bool(owner) and any(request.owner == owner for request in self.service.active)

    def _verify_volumes(self, options: dict[str, Any]) -> None:
        self._volume_verify_owner = uuid4().hex
        if not self.service.submit(self._volume_verify_owner, 0, options["directory"], "volumes_verify",
                                   {"cache": options}):
            self._volume_verify_owner = ""

    def _verify_markers(self) -> None:
        """Queue the marker check asked for, at most every ``VERIFY_MIN_SECONDS``."""
        options = store_options()
        if (not self._markers_wanted or self._root_verify_owner or not options or self.service.closed
                or self.quitting):
            return
        wait = self._markers_started + self.VERIFY_MIN_SECONDS - time.monotonic()
        if wait > 0:
            if not self._markers_timer.isActive():
                self._markers_timer.start(int(wait * 1000) + 1)
            return
        # The owner is known before the job can start (``_before_start`` runs as it does).
        self._root_verify_owner = uuid4().hex
        if self.service.submit(self._root_verify_owner, 0, options["directory"], "roots_verify", {"cache": options}):
            self._markers_wanted = False
            self._markers_started = time.monotonic()
        else:
            self._root_verify_owner = ""

    def _before_start(self, request: IORequest) -> None:
        """The marker check uses the volume IDs checked last, unless a volume check still runs (it
        checks them itself then)."""
        if request.operation == "roots_verify" and request.owner == self._root_verify_owner:
            if self._volume_verify_owner or not self._volume_ids:
                request.payload.pop("volume_ids", None)
            else:
                request.payload["volume_ids"] = [list(item) for item in self._volume_ids]

    def verified_volumes(self) -> list[list[str]]:
        """For a cached read (``verified_volumes``): a disk swapped in at the same mount path and
        device would otherwise inherit the previous disk's volume hint, and show its cached data."""
        return [list(pair) for pair in self._verified_volumes]

    def sync_budget(self) -> None:
        """Make the store record the app's disk budget (``store_options``), retrying until a job
        has: a running load saves within the store's. (Settings cancelled while the store took
        an unsaved budget sends the saved one this way, set later, so it wins.)"""
        self._budget_timer.stop()
        if not store_options() or self.service.closed:
            return
        self._budget_owner = self.cache_admin("budget")
        if not self._budget_owner:
            self._budget_timer.start(int(self.SWEEP_RETRY * 1000))

    def restore_budget(self) -> None:
        """A change of the disk budget failed or was abandoned, and the store may have recorded
        it anyway: set the budget in effect again (so it is newer) and send it until it has."""
        set_disk_budget(_disk_budget)
        self.sync_budget()

    def restore_pending(self) -> None:
        """At startup: the inventory brings back saves still waiting for an answer from an
        earlier session (they would expire unasked), and the usage for the 80% pause."""
        if store_options() and not self.service.closed and not self.cache_admin("inventory"):
            self._restore_timer.start(int(self.SWEEP_RETRY * 1000))

    def cache_admin(self, action: str, **params: Any) -> str:
        """Submit a disk cache maintenance job on the local lane; its owner, or "" if it
        couldn't be queued (or the cache is off). Results arrive as ``cacheAdminResult``."""
        options = store_options()
        if not options or self.service.closed:
            return ""
        owner = uuid4().hex
        if not self.service.submit(owner, 0, options["directory"], "cache_admin",
                                   {"cache": options, "action": action, "params": params}, priority=True):
            logging.warning("Disk cache %s: queue full", action)
            return ""
        self._admin[owner] = action
        self._started[owner] = time.monotonic()
        return owner

    def _schedule_sweep(self, deadline: object) -> None:
        """Keep one timer for the earliest cleanup deadline any helper reported."""
        if not isinstance(deadline, (int, float)) or not math.isfinite(deadline) or self.service.closed:
            return
        if self._sweep_deadline is not None and self._sweep_timer.isActive() and self._sweep_deadline <= deadline:
            return
        self._sweep_deadline = float(deadline)
        self._sweep_timer.start(int(min(max(0.0, deadline - time.time()), 24 * 3600) * 1000) + 1000)

    def _sweep_due(self) -> None:
        self._sweep_deadline = None
        if store_options() and not self.cache_admin("sweep"):
            self._schedule_sweep(time.time() + self.SWEEP_RETRY)  # Queue full: try again shortly.

    def _note_usage(self, usage: object, seq: object) -> None:
        """A helper measured the disk cache's live usage; keep the newest measurement, by the
        store's write count when it was taken (a different store, e.g. recreated, starts over)."""
        if (not isinstance(usage, int) or isinstance(usage, bool) or not isinstance(seq, (list, tuple))
                or len(seq) != 2 or not isinstance(seq[0], str) or not isinstance(seq[1], int)):
            return
        store_id, writes = seq
        if self._usage_seq is not None and self._usage_seq[0] == store_id and writes < self._usage_seq[1]:
            return
        self._usage_seq = (store_id, writes)
        if usage != self.disk_usage:
            self.disk_usage = usage
            self.diskUsageChanged.emit()
        self.update_auto_load_pause()

    def disk_nearly_full(self) -> bool:
        """Usage is at least 80% of the budget (whether or not the user chose to ignore it)."""
        budget = store_options().get("budget")
        return bool(self.disk_usage is not None and budget and self.disk_usage >= APPROVAL_SHARE * budget)

    def update_auto_load_pause(self) -> None:
        """Re-decide the 80% pause after a new usage or budget. Ask once per crossing; after
        Ignore, only when usage rises another ``IGNORE_STEP`` of the budget."""
        full = self.disk_nearly_full()
        ignored = (full and self._full_ignored_until is not None and self.disk_usage is not None
                   and self.disk_usage < self._full_ignored_until)
        paused = full and not ignored
        if not full:
            self._full_warned = False
        warn = paused and not self._full_warned
        if warn:
            self._full_warned = True
        if paused != self.auto_load_paused:
            self.auto_load_paused = paused
            self.autoLoadPauseChanged.emit(paused)
        if warn:
            self.diskNearlyFull.emit()

    def ignore_disk_nearly_full(self) -> None:
        """Keep loading automatically this session, until usage rises another 10% of the budget."""
        budget = store_options().get("budget") or 0
        if self.disk_usage is not None:
            self._full_ignored_until = self.disk_usage + self.IGNORE_STEP * budget
        self._full_warned = False
        self.update_auto_load_pause()

    def removed(self, paths: list[str] | None, kinds: list[str]) -> None:
        """Forget what a disk cache removal took away: ``paths`` (None: every path) of ``kinds``.

        Cache flags and dates, saved summaries, histories and subfolder statuses go;
        datasets in RAM stay loaded but are no longer marked as cached. Results read
        before the removal are ignored when they arrive (see ``_removed_since``).
        """
        now = time.monotonic()
        keys = None if paths is None else [self.key(path) for path in paths]
        for kind in kinds:
            if keys is None:
                self._removed_all[kind] = now
            else:
                for path in keys:
                    self._removed_paths[(kind, path)] = now
                    self._removed_paths.move_to_end((kind, path))
        while len(self._removed_paths) > self.MAX_ENTRIES:
            self._removed_paths.popitem(last=False)

        def selected(known: Any) -> list[str]:
            return list(known) if keys is None else [path for path in keys if path in known]
        if "datasets" in kinds:
            # The store drops the folders' pending saves with their data.
            self._forget_pending({entry["pending_id"] for path, entry in self.pending_saves.items()
                                  if (keys is None or path in keys) and entry.get("pending_id")})
            for path in selected({*self._disk_cached_paths, *self._cache_states}):
                self._cache_states[path] = CacheStatus()
                self._set_disk_cached(path, False, notify=True)
            for entry in self.datasets.values():
                if keys is None or entry.path in keys:
                    entry.metadata.update(disk_cached=False, cache_info={})
            for path in selected(self.snapshots):
                if "disk_cached" in self.snapshots[path].status:
                    self.snapshots[path].status = {**self.snapshots[path].status, "disk_cached": False,
                                                   "cache_info": {}}
            self.pendingSavesChanged.emit()
            # Without its cached data, a mismatched folder simply loads as it is.
            resolved = selected(self.mismatched)
            for path in resolved:
                del self.mismatched[path]
            if resolved:
                self.mismatchesChanged.emit()
        if "summaries" in kinds:
            for path in selected(self.scan_summaries):
                del self.scan_summaries[path]
        if "histories" in kinds:
            for path in selected(self.scan_histories):
                del self.scan_histories[path]
                self.scan_history_errors.pop(path, None)
                self.scanHistoryChanged.emit(path)
        if "subtrees" in kinds:
            if self._subtree_writer:
                # Its batch was derived before the clear and its guard may be taken after it.
                self.service.cancel(self._subtree_writer)
            for path in selected({*self.subtrees, *self._subtree_pending}):
                self.subtrees.pop(path, None)
                self._subtree_pending.pop(path, None)
                self.subtreeChanged.emit(path)
        # Snapshots replayed to tabs later must not bring the removed fields back.
        stale = [key for kind in kinds for key in ENTRY_KEYS.get(kind, ())]
        for snapshot in self.snapshots.values():
            if any(key in entry for entry in snapshot.entries for key in stale):
                snapshot.entries = tuple(
                    {key: value for key, value in entry.items() if key not in stale}
                    if keys is None or entry["path"] in keys else entry for entry in snapshot.entries)
        self.cacheRemoved.emit(keys, list(kinds))

    def _fresh_entry(self, job: SharedJob, entry: dict[str, Any]) -> dict[str, Any]:
        """A listing entry without saved fields read before they were removed."""
        stale = [key for kind, keys in ENTRY_KEYS.items() if self._removed_since(job, kind, entry["path"])
                 for key in keys if key in entry]
        return {key: value for key, value in entry.items() if key not in stale} if stale else entry

    def _forget_pending(self, pending_ids: set[str]) -> None:
        """Drop pending saves the store no longer has (answered, superseded or expired); a late
        event naming one of them never brings it back."""
        for pending_id in pending_ids:
            self._pending_gone[pending_id] = None
            self._pending_gone.move_to_end(pending_id)
        while len(self._pending_gone) > self.MAX_ENTRIES:
            self._pending_gone.popitem(last=False)
        gone = [path for path, entry in self.pending_saves.items() if entry.get("pending_id") in pending_ids]
        for path in gone:
            del self.pending_saves[path]
            self._pending_changed[path] = time.monotonic()
        if gone:
            self.pendingSavesChanged.emit()

    def _hold_pending(self, path: str, event: dict[str, Any]) -> bool:
        """A load's save waits for the user's answer, unless the store already moved past it:
        the save was answered or superseded, or a later job's save outcome already arrived."""
        job_seq = int(event.get("job_seq", 0))
        current = self.pending_saves.get(path)
        if (event.get("pending_id") in self._pending_gone or job_seq <= self._save_seq.get(path, 0)
                or current is not None and current.get("job_seq", 0) >= job_seq):
            return False
        self._save_seq[path] = job_seq
        self.pending_saves[path] = dict(event)
        self._pending_changed[path] = time.monotonic()
        self.pendingSavesChanged.emit()
        return True

    def _removed_since(self, job: SharedJob, kind: str, path: str) -> bool:
        """A job that started before a removal of ``kind`` may report what was removed."""
        return self._removed_after(job.created, kind, path)

    def _removed_after(self, started: float, kind: str, path: str) -> bool:
        removed = max(self._removed_all.get(kind, float("-inf")),
                      self._removed_paths.get((kind, path), float("-inf")))
        return started < removed

    def _on_admin_event(self, producer: IORequest, event: dict[str, Any]) -> None:
        action = self._admin[producer.owner]
        kind = event["kind"]
        if "next_deadline" in event:
            self._schedule_sweep(event["next_deadline"])
        self._note_usage(event.get("usage"), event.get("usage_seq"))
        if kind == "folder_prefs":
            self.remember_prefs(event["path"], event["prefs"])
            return
        if kind == "prefs_cleared":
            # As of the Clear's own time: a choice saved after it (arriving first) stays.
            cleared = {"no_cache": False, "no_auto_load": False, "set_at": float(event.get("set_at", 0))}
            for path in {*event["paths"], *self.prefs}:
                self.remember_prefs(path, cleared)
            return
        if kind == "removed":
            self.removed(event["paths"], event["kinds"])
            return
        started = self._started.get(producer.owner, 0.0)
        # A newer inventory was already applied: this one is stale, for the cache and its viewers.
        stale = kind == "inventory" and started < self._inventory_started
        if stale:
            pass
        elif kind == "inventory":
            self._inventory_started = started
            # First: the questions about its pending saves show this usage.
            self._note_usage(event["inventory"].get("usage"), event["inventory"].get("usage_seq"))
            # The store's list is the truth; keep what events added (e.g. a room plan) for the same
            # save, and leave out saves a removal since then took away.
            # Folders whose pending save an event changed after this inventory was requested keep
            # that newer state.
            snapshot = {self.key(entry["path"]): entry for entry in event["inventory"]["pending"]
                        if entry["pending_id"] not in self._pending_gone
                        and not self._removed_after(started, "datasets", self.key(entry["path"]))}
            merged: dict[str, dict[str, Any]] = {}
            for path in {*self.pending_saves, *snapshot}:
                current = self.pending_saves.get(path)
                if self._pending_changed.get(path, float("-inf")) > started:
                    if current is not None:
                        merged[path] = current
                elif path in snapshot:
                    same = current is not None and current.get("pending_id") == snapshot[path]["pending_id"]
                    merged[path] = {**(current if same and current else {}), **snapshot[path]}
                    # Its job_seq orders it against late events, as for one an event added.
                    self._save_seq[path] = max(self._save_seq.get(path, 0), int(snapshot[path].get("job_seq", 0)))
            self.pending_saves = merged
            self.pendingSavesChanged.emit()
            self._schedule_sweep(event["inventory"].get("next_deadline"))
        elif kind == "admin_result" and action in ("adopt", "discard"):
            # Matched by pending_id: a late answer about an older save never touches a newer one.
            pending_id = producer.payload["params"].get("pending_id")
            held = next((path for path, entry in self.pending_saves.items()
                         if entry.get("pending_id") == pending_id), None)
            if event.get("adopted") is False and event.get("room") is not None:
                # Still waiting: it no longer fits, so the answer is Make room or Don't cache.
                if held:
                    self.pending_saves[held] = {**self.pending_saves[held], "reason": "over_budget",
                                                "room": event["room"]}
            elif pending_id:
                # Adopted, discarded, or rejected: either way the store no longer has it.
                self._forget_pending({pending_id})
                if held and not event.get("adopted"):
                    # Not cached this time, by the user's answer; the data stays in RAM.
                    self._cache_states.setdefault(held, CacheStatus()).error = ""
                    self.diskCacheChanged.emit(held)
            if event.get("adopted") and event.get("path") and not self._removed_after(
                    started, "datasets", self.key(event["path"])):
                adopted = self.key(event["path"])
                state = self._cache_states.setdefault(adopted, CacheStatus())
                state.info, state.error = dict(event.get("cache_info") or {}), ""
                self._set_disk_cached(adopted, True, notify=True)
            self.pendingSavesChanged.emit()
        elif kind == "swept":
            self._forget_pending(set(event.get("expired_ids") or ()))
            logging.info("Disk cache cleanup: %s", event)
        elif kind in ("error", "cancelled"):
            logging.warning("Disk cache %s: %s", action, event.get("message", "Cancelled"))
        if kind in ("inventory", "admin_result", "swept", "error", "cancelled") and not stale:
            self.cacheAdminResult.emit(action, event)
        if kind in ("done", "error", "cancelled"):
            self._admin.pop(producer.owner, None)
            self._started.pop(producer.owner, None)
            write = self._pref_writes.pop(producer.owner, None)
            if write is not None and kind != "done":
                self._prefs_not_saved(write[0], write[1], str(event.get("message") or "the save was cancelled"),
                                      write[2])
            if producer.owner == self._budget_owner:
                self._budget_owner = ""
                if kind != "done":
                    self._budget_timer.start(int(self.SWEEP_RETRY * 1000))  # Not recorded: again.
            self.cacheAdminDone.emit(producer.owner, action,
                                     "" if kind == "done" else str(event.get("message") or "Cancelled"))

    def _on_event(self, producer: IORequest, event: dict[str, Any]) -> None:
        if isinstance(event.get("data_root"), dict):
            # The root of the folder listed, checked or loaded, wherever its root folder is.
            self._root_reported(event["data_root"])
        if event["kind"] == "root_duplicate":
            self._root_duplicate(event)
        elif event["kind"] == "root_confirmed":
            self._duplicate_settled(str(event["location"]))
            if event.get("path"):
                self._root_seen(str(event["path"]), str(event["uuid"]), str(event.get("label", "")))
                self.rootDecided.emit([str(event["path"])])
        elif event["kind"] == "root_reassigned":
            duplicate = str(producer.payload.get("duplicate", ""))
            self._duplicate_settled(duplicate, *event.get("moved", []))
            self.rootDecided.emit([str(path) for path in dict.fromkeys((producer.path, event.get("kept") or ""))
                                   if path])
        elif event["kind"] == "root_removed":
            self.rootDecided.emit([str(event["path"])])
        elif event["kind"] in ("root_found", "root_created", "root_adopted") and event.get("location"):
            self._duplicate_settled(str(event["location"]))
        if event["kind"] in ("root_found", "root_created", "root_adopted"):
            self._root_seen(str(event["path"]), str(event["uuid"]), str(event["label"]))
        if event["kind"] == "root_changed":
            if event.get("location"):
                self._duplicate_settled(str(event["location"]))  # Forgotten, removed or replaced.
            if "uuid" in event:
                self._root_seen(str(event["path"]), str(event["uuid"]), str(event["label"]))
            else:
                self._root_gone(str(event["path"]))
            root_path = str(event["path"])
            known = ({root_path, *self._cache_states, *self.scan_summaries,
                      *self.scan_histories, *self.subtrees, *self._disk_cached_paths})
            affected = [path for path in known if path == root_path or path.startswith(root_path.rstrip("/\\") + os.sep)]
            self.removed(affected, list(KINDS))
        if event["kind"] == "mounts_seen":
            self._mounts_observed = tuple(tuple(pair) for pair in event["mounts"])
            # A mount gone since may come back as another disk: verified again first.
            self._verified_volumes = tuple(pair for pair in self._verified_volumes
                                           if pair in self._mounts_observed)
            if self._mounts_observed not in (self._roots_mounts, self._verify_asked):
                self._verify_roots()
            elif self._mounts_observed == self._roots_mounts:
                # The table the last check saw: covered, so a later change back is new again.
                self._verify_asked = self._mounts_observed
            return
        if producer.owner == self._volume_verify_owner:
            if event["kind"] == "volumes_verified":
                self._verified_volumes = tuple(tuple(pair) for pair in event["volumes"])
                self._volume_ids = tuple((str(path), str(source), str(identifier))
                                         for path, source, identifier in event.get("ids", ()))
                self.volumesVerified.emit()
            elif event["kind"] in ("error", "cancelled"):
                logging.warning("Volume verification: %s", event.get("message", "Cancelled"))
                self._verify_asked = None  # The next listing asks again.
                self._volume_ids = ()
            if event["kind"] in ("done", "error", "cancelled"):
                self._volume_verify_owner = ""
                options = store_options()
                if self._volumes_again and options and not self.quitting:
                    self._volumes_again = False
                    self._verify_volumes(options)
                else:
                    self._verify_markers()
            return
        if producer.owner == self._root_verify_owner:
            if event["kind"] == "volumes_verified":
                self._verified_volumes = tuple(tuple(pair) for pair in event["volumes"])
                self.volumesVerified.emit()
            elif event["kind"] == "roots_verified":
                self._roots_mounts = tuple(tuple(pair) for pair in event["mounts"])
            elif event["kind"] == "removed":
                self.removed(event.get("paths"), event["kinds"])
            elif event["kind"] in ("error", "cancelled"):
                logging.warning("Data-root verification: %s", event.get("message", "Cancelled"))
                self._verify_asked = None  # The next listing asks again (no retry before it).
            if event["kind"] in ("done", "error", "cancelled"):
                self._root_verify_owner = ""
                # Once, for a listing that reported a table while it ran, unless it checked that table.
                again, self._markers_again = self._markers_again, False
                if again and self._mounts_observed != self._roots_mounts and not self.quitting:
                    self._markers_wanted = True
                    if not self._volume_verify_owner:
                        self._verify_markers()
            return
        if event["kind"] == "cache_skipped":
            self._remember_mount_warning(event)
            if (job := self._producers.get(producer.owner)) is not None and job.path in event.get("paths", ()):
                job.cache_off = True
            return
        if producer.owner in self._admin:
            self._on_admin_event(producer, event)
            return
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
            if event["kind"] == "scan_history_saved" and not self._removed_after(
                    self._started.get(producer.owner, 0.0), "histories", path):
                # (A history cleared after this write started stays cleared.)
                self.scan_history_errors.pop(path, None)
                self.remember_history(path, event["history"])
            elif event["kind"] in ("error", "cancelled"):
                self.scan_history_errors[path] = "Scan history save failed; suppression is session-only."
                logging.warning("Scan history %s: %s", path, event.get("message", "Save cancelled"))
                self.scanHistoryChanged.emit(path)
            if event["kind"] in ("done", "error", "cancelled"):
                self._history_writes.pop(producer.owner, None)
                self._started.pop(producer.owner, None)
            return
        if producer.owner in self._awaiting_cached:
            self._awaiting_cached[producer.owner].append(event)  # Replayed in order with its result.
            return
        job = self._producers.get(producer.owner)
        if job is None and producer.owner in self._finishing:
            path = self._finishing[producer.owner]
            kind = event["kind"]
            # A removal since the load started voids its cache events: a save that committed
            # before a Clear must not bring the badge back after it.
            valid = (self._finishing_epochs.get(producer.owner) == self._epochs.get(path, 0)
                     and not self._removed_after(self._finishing_created.get(producer.owner, 0.0), "datasets", path))
            was_saving = producer.owner in self._disk_cache_writers
            if kind in ("cache_saved", "cache_save_failed", "disk_cached", "cache_warning", "cache_full",
                        "cache_approval", "done", "error", "cancelled"):
                self._disk_cache_writers.discard(producer.owner)
            if "next_deadline" in event:
                self._schedule_sweep(event["next_deadline"])
            self._note_usage(event.get("usage"), event.get("usage_seq"))
            if kind in ("cache_full", "cache_approval", "cache_saved"):
                self._forget_pending(set(event.get("superseded") or ()))
            if kind == "cache_saved" and event.get("job_seq"):
                self._save_seq[path] = max(self._save_seq.get(path, 0), int(event["job_seq"]))
            held = False
            if valid and kind in ("cache_full", "cache_approval") and (held := self._hold_pending(path, event)):
                # Not saved yet: it waits for the user's answer (Make room / Save update).
                state = self._cache_states.setdefault(path, CacheStatus())
                state.error = ("Not cached — disk cache full" if kind == "cache_full"
                               else "Cache update waiting for your answer")
                self.diskCacheChanged.emit(path)
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
                self._finishing_created.pop(producer.owner, None)
            if was_saving and producer.owner not in self._disk_cache_writers:
                outcome = ("saved" if valid and kind == "cache_saved" else
                           "pending" if held else
                           "superseded" if valid and kind in ("cache_full", "cache_approval") else "failed")
                self.saveEnded.emit(path, outcome)
                self.quitSavesChanged.emit()
                if path in self._deferred_saves and not self.disk_cache_saving(path):
                    QTimer.singleShot(0, lambda: self._start_deferred(path))
            return
        if job is None:
            # Non-shared IOService consumers retain their existing protocol.
            self.resultReady.emit(producer, event)
            return
        kind = event["kind"]
        if kind == "summary_save_failed":
            # The check itself succeeded; only its saved copy for later sessions is missing.
            logging.warning("%s: %s", job.path, event["message"])
            return
        if kind in ("paused", "resumed"):
            job.paused = kind == "paused"
            if job.paused:
                job.clock.stop()
            elif job.state == "started":
                job.clock.run()
        if kind in ("queued", "started"):
            job.paused = False
            job.state = kind
            job.attempt = event.get("attempt", job.attempt)
            if kind == "started":
                job.clock.run()
            else:
                job.clock.stop()
            if event.get("retry"):
                job.clock.restart_rate()
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
            if kind == "save_guard":
                job.save_guard = event["guard"]
                return
            if kind in ("scan_history", "subtree_cached", "scan_cached") and self._removed_since(
                    job, {"scan_history": "histories", "subtree_cached": "subtrees",
                          "scan_cached": "summaries"}[kind], job.path):
                return  # Read before that record was removed.
            if kind == "scan_history":
                self.remember_history(job.path, event.get("history"))
                if event.get("revision"):
                    job.payload["scan_revision"] = producer.payload["scan_revision"] = event["revision"]
                job.history_saved |= bool(event.get("saved"))
                return
            if kind == "cache_warning":
                job.cache_warning = event["message"]
                self.cache_read_errors[job.path] = event["message"]
                self.cache_read_errors.move_to_end(job.path)
                while len(self.cache_read_errors) > 4096:
                    self.cache_read_errors.popitem(last=False)
                logging.warning("Disk cache %s: %s", job.path, event["message"])
                self.scanHistoryChanged.emit(job.path)
                return
            if kind == "scan_history_warning":
                self.scan_history_errors[job.path] = event["message"]
                logging.warning("Scan history %s: %s", job.path, event["message"])
                self.scanHistoryChanged.emit(job.path)
                return
            if kind == "folder_prefs":
                self.remember_prefs(event["path"], event["prefs"], known=False)
                return
            if kind == "cache_mismatch":
                # Its cached shots aren't all in the folder now. A folder not cached by choice
                # never shows its cached data, so it needs no answer.
                if not self.folder_prefs(job.path)["no_cache"] and not self._removed_since(job, "datasets", job.path):
                    self._mismatch(job.path, event, "scan")
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
                event = {**event, "entries": [self._fresh_entry(job, entry) for entry in event["entries"]]}
                for entry in event["entries"]:
                    if entry.get("saved_read"):
                        self._clear_mount_warning(entry["path"])
                if job.operation == "list" and any(
                        request.payload.get("refresh_sequence") for request in job.subscribers.values()):
                    self.refresh_saved(entry["path"] for entry in event["entries"] if entry.get("saved_read"))
                for entry in event["entries"]:
                    self.remember_history(entry["path"], entry.get("scan_history"))
                    if entry.get("scan_status"):
                        self.remember_scan(entry["path"], entry["scan_status"])
                    if entry.get("subtree"):
                        self.remember_subtree(entry["path"], entry["subtree"], notify=False)
                    if "prefs" in entry:
                        self.remember_prefs(entry["path"], entry["prefs"], known=False)
                    if "disk_cached" in entry and not self._cleared_since(job, entry["path"]):
                        self._observe_cache(entry["path"], entry)
                if event.get("replace"):
                    changed = {entry["path"]: entry for entry in event["entries"]}
                    job.entries = [changed.get(entry["path"], entry) for entry in job.entries]
                else:
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
                saved_root = event.get("saved_root")
                if isinstance(saved_root, dict) and saved_root.get("saved_read"):
                    self._clear_mount_warning(job.path)
                if job.operation == "list" and any(
                        request.payload.get("refresh_sequence") for request in job.subscribers.values()):
                    if isinstance(saved_root, dict) and saved_root.get("saved_read"):
                        self.refresh_saved([job.path])
                        self.remember_history(job.path, saved_root["scan_history"])
                        if saved_root.get("scan_status"):
                            self.remember_scan(job.path, saved_root["scan_status"])
                        if saved_root.get("subtree"):
                            self.remember_subtree(job.path, saved_root["subtree"], notify=False)
                if not job.cache_warning and job.path in self.cache_read_errors:
                    del self.cache_read_errors[job.path]
                    self.scanHistoryChanged.emit(job.path)
                self.remember_history(job.path, None)
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
                entries = old.entries if old is not None and newer_listing else tuple(
                    self._fresh_entry(job, entry) for entry in job.entries)
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
                job.current_file = os.path.basename(str(event.get("filename", "")))
                attempt = event.get("attempt", job.attempt)
                job.load_status = event if attempt > 1 else None
                if attempt == job.attempt and attempt == 1:
                    return
                job.attempt = attempt
            if kind == "file_finished":
                job.current_file = ""
                job.load_status = None
                if job.attempt == 1:
                    return
                job.attempt = 1
            if kind == "heartbeat":
                job.load_status = event
            if kind == "progress":
                job.progress = event
                if "total_read_bytes" in event:
                    job.clock.sample(int(event["read_bytes"]), int(event["total_read_bytes"]),
                                     int(event.get("read_files", 0)))
                if job.load_status is not None and job.load_status["kind"] == "heartbeat":
                    job.load_status = None
            if kind == "scan_summary":
                # A Live check's, or a Live save's that read shots again (``io_helper.save_held``).
                self._adopt_load_summary(job.path, event["status"],
                                         live=bool(job.payload.get("live") or job.payload.get("save_memory")))
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
                job.clock.stop()
                event = {"loaded_at": time.time(), **event}
                if job.operation == "load":
                    # When this data was last checked against its folder (a cached read isn't a check).
                    event["checked_at"] = time.monotonic()
                    self._matched(job.path)
                if job.operation == "load" and job.clock.total_bytes:
                    # Only a load that read TXY files has a load time; a check
                    # answered from memory or the cache would show "took 0:00".
                    event.setdefault("load_seconds", job.clock.elapsed())
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
                if self._cleared_since(job, job.path):
                    # Read before the folder's cached data was removed: the data is still right,
                    # but no longer cached (as for datasets already in RAM, see ``removed``).
                    event = {**event, "disk_cached": False, "cache_info": {}}
                elif "disk_cached" in event:
                    self._observe_cache(job.path, event)
                memory_shots = event.get("memory_shots", [])
                if memory_shots and job.base is None:
                    # A check run beside the cached read: its unchanged shots are that read's.
                    job.base = self.dataset(job.path, str(event.get("base_signature") or ""))
                    if job.base is None:
                        if ("cached", job.path) in self.jobs:
                            self._awaiting_cached[producer.owner] = [event]
                            self._awaiting_producers[job.path] = producer
                        else:
                            self._fail_job(job, "Cached data couldn't be read — Retry")
                        return
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
                self._finishing_created[job.owner] = job.created
                if event.get("disk_cache_pending"):
                    self._disk_cache_writers.add(job.owner)
                    self._cache_states.setdefault(job.path, CacheStatus()).error = ""
                entry = Dataset(job.path, event["signature"], job.data, event, job.epoch)
                self.datasets[(job.path, entry.signature, entry.epoch)] = entry
                event = {**event, "dataset": entry}
                # Subscribers pin the dataset during delivery before eviction.
                for request in tuple(job.subscribers.values()):
                    self.resultReady.emit(request, event)
                if memory_shots:
                    self._drop_superseded(entry)
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
        elif job.operation == "invalidate" and kind in ("removed", "admin_result"):
            # Its state was reset when it was submitted; only the cleanup deadline and usage are new.
            self._schedule_sweep(event.get("next_deadline"))
            self._note_usage(event.get("usage"), event.get("usage_seq"))
            return
        elif job.operation == "resolve" and kind == "resolved":
            candidates = tuple(job.payload["candidates"])
            self._defaults[candidates] = event["path"]
            if len(self._defaults) > 16:
                self._defaults.popitem(last=False)
        if job.operation == "load" and kind == "shots_missing":
            self._mismatch(job.path, event, "load")
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


# Data roots (Tony, 2026-10-18): the right-click action, and how a folder's disk cache is described.
PLACE_ROOT_ACTION = "Place .helab-root here…"
PLACE_ROOT_TOOLTIP = ("No .helab-root found here or above, so this folder uses RAM only.\n"
                      "Place it as high up as possible (the top folder of the drive or share), unless this "
                      "folder is also shared on its own, so other computers see it as a top folder.")
RAM_ONLY = "RAM only · no .helab-root found here or above"
RAM_ONLY_TOOLTIP = ("No .helab-root at or above this folder, so its statuses, settings and loaded data stay in "
                    "RAM for this session.\nTo use the disk cache: right-click the top folder of this drive "
                    "or share › " + PLACE_ROOT_ACTION)
NEEDS_ROOT_TOOLTIP = "No .helab-root found here or above: " + PLACE_ROOT_ACTION + " first"
# A location whose .helab-root is also elsewhere, until Same folder or Copy (D4).
PENDING_ROOT = "RAM only · this .helab-root is also at another location · Review…"
PENDING_ROOT_TOOLTIP = ("HeLab found the same .helab-root at two locations. Say whether they're the same "
                        "folder or a copy before its disk cache is used here.")


PENDING_SUMMARY = "RAM only · this .helab-root is also at another location"
REVIEW_ROOT_TOOLTIP = "Same folder or a copy? Answer in the data-root window"


def pending_root_text(pending: dict[str, Any]) -> str:
    """The row tooltip's line (and the summary's tooltip) for a folder below a pending location."""
    label = str(pending.get("label") or os.path.basename(str(pending["path"]).rstrip("/\\")))
    other = next(iter(pending.get("others") or ()), None)
    where = (str(other.get("path") or other["location"]) if other is not None else "another location")
    return f"Data root “{label}” also seen at {where}: same folder or a copy? RAM only until answered."


def marker_path(root: str) -> str:
    return os.path.join(root, ".helab-root")


def data_root_text(cache: FolderCache, path: str) -> str:
    """The row tooltip's line: which .helab-root the folder uses, or RAM only ("" if not known yet)."""
    if (pending := cache.pending_root(path)) is not None:
        return pending_root_text(pending)
    if (root := cache.root_of(path)) is not None:
        folder, _, label = root
        return f"Data root: {label or os.path.basename(folder)} · " + (
            ".helab-root in this folder" if folder == path else marker_path(folder))
    return "RAM only: no .helab-root found here or above" if cache.no_root(path) is not None else ""


def data_root_row(cache: FolderCache, path: str) -> tuple[str, str]:
    """Folder details' Disk cache row and its tooltip, ("", "") if not known yet."""
    if (pending := cache.pending_root(path)) is not None:
        return PENDING_ROOT, f"{PENDING_ROOT_TOOLTIP}\n\n{marker_path(str(pending['path']))}"
    if (root := cache.root_of(path)) is not None:
        folder, identifier, label = root
        name = label or os.path.basename(folder)
        return (f"⚓ {name} · {marker_path(folder)}",
                f"Disk cache on, using {marker_path(folder)} (data root “{name}”, {identifier}).\n"
                "Folders inside it share this identity, whichever drive or share reaches them.")
    if (detail := cache.no_root(path)) is not None:
        return RAM_ONLY, f"{RAM_ONLY_TOOLTIP}\n\n{detail}"
    return "", ""
