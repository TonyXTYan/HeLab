"""The helper's events: what an I/O helper sends the app, one JSON object per line.

One ``TypedDict`` per event shape, keyed by ``kind``. Most kinds have one shape; a few are sent
with different fields by different operations (``loaded``, ``status``, ``admin_result``,
``swept``, ``root_changed``) and have one shape per sender, so strict type checking sees each
sender's exact fields. ``HelperEvent`` is the union the helper's ``Emit`` accepts, and ``KINDS``
every kind (``tests/test_helper_events.py`` checks both against the code that sends and the
code that matches them).

Standard library only: the app may import this without importing helper code. Field values
are as JSON carries them; nested payloads (a dataset's ``cache_info``, a folder summary's
``files``, the store's ``inventory``) stay ``dict[str, Any]``.
"""
from __future__ import annotations

from typing import Any, Literal, NotRequired, Sequence, TypedDict, Union

# Fields several events carry, spread into them by the helper (``**``).


class StoreField(TypedDict, total=False):
    """The store an answer came from (``stores._store_fields``): its ``store_id``, which
    ``FolderCache.store_answer`` checks before anything else in the answer counts."""
    store: str


class UsageFields(TypedDict, total=False):
    """The store's live usage (``stores._usage``); absent if it couldn't be measured."""
    usage: int
    usage_seq: list[Any]  # [store id, write count]


class DataRoot(TypedDict):
    path: str
    uuid: str
    label: str


class DataRootField(TypedDict, total=False):
    """The data root a folder is keyed by (``stores._data_root``); absent without one."""
    data_root: DataRoot


class DatasetFlags(TypedDict, total=False):
    """Whether a folder has cached data and its record (``metadata._dataset_flags``); absent if unknown."""
    disk_cached: bool
    cache_info: dict[str, Any]


class SavedRootField(TypedDict, total=False):
    """A listing's own folder's saved records (``list``)."""
    saved_root: dict[str, Any]


class DiskCachedField(TypedDict, total=False):
    disk_cached: bool


class RawMtimeField(TypedDict, total=False):
    """A shot's raw file's mtime (ns), when known."""
    raw_mtime: int


class UnverifiedField(TypedDict, total=False):
    """An ``error`` raised because the folder's drive isn't verified yet this session."""
    unverified: bool


class LiveState(TypedDict):
    """What the next Live check compares with (``live.live_check``'s ``state``)."""
    live_helab: NotRequired[list[list[Any]]]  # HeLab's folders' state (``helab_txy.folder_state``)
    live_since: int | None
    live_listed: bool
    live_seconds: float
    unsettled_files: int
    live_identity: str
    live_seen: list[list[int]]
    live_seen_names: list[str]
    live_listed_mtime: int | None
    live_identity_root: str | None


class MoveCheckFields(TypedDict):
    """``cache_move.check_target``'s answer."""
    bytes: int
    free: int | None
    method: str
    problem: str


class AdminResultFields(TypedDict, total=False):
    """Results of one ``cache_admin`` action (each action sets some)."""
    removed: dict[str, int]
    bytes: int
    datasets: int
    adopted: bool
    rejected: str
    message: str
    path: str
    room: dict[str, Any] | None
    cache_info: dict[str, Any]
    discarded: bool
    forgotten: str
    confirmed: bool
    budget: int
    recorded: bool
    results: int  # saved results removed (R2)
    result_id: str  # an adopted result's saved row (R2)
    folder_results: dict[str, ResultCountField]  # an adoption's folders' saved results after it (R2)
    store: str  # the store an adoption answered from (its ``store_id``)
    converted_txy: dict[str, int]  # HeLab's TXY under the cache folder after a Clear (files, bytes, folders)


# Process and progress


class DoneEvent(TypedDict):
    kind: Literal["done"]


class ErrorEvent(TypedDict):
    kind: Literal["error"]
    message: str
    unverified: NotRequired[bool]


class PausedEvent(TypedDict):
    kind: Literal["paused"]


class ResumedEvent(TypedDict):
    kind: Literal["resumed"]


class HeartbeatEvent(TypedDict):
    kind: Literal["heartbeat"]
    phase: str
    entries: int


class DrivesEvent(TypedDict):
    kind: Literal["drives"]
    paths: list[str]


class ResolvedEvent(TypedDict):
    kind: Literal["resolved"]
    path: str


class CacheWarningEvent(TypedDict):
    kind: Literal["cache_warning"]
    message: str


class CacheSkippedEvent(TypedDict):
    kind: Literal["cache_skipped"]
    paths: list[str]
    mounts: list[dict[str, str]]


# Browsing and scans


class EntriesEvent(TypedDict):
    kind: Literal["entries"]
    entries: list[dict[str, Any]]
    replace: NotRequired[bool]


class _StatusBase(TypedDict):
    kind: Literal["status"]
    details: bool
    status: str
    count: int
    empty: bool
    has_dirs: bool
    scanned_at: float
    raw: list[int]
    txy: list[int]
    files: dict[str, Any]


class ListedStatusEvent(_StatusBase):
    """A listing's status of its folder (``details`` False)."""
    disk_cached: NotRequired[bool]
    cache_info: NotRequired[dict[str, Any]]
    data_root: NotRequired[DataRoot]
    saved_root: NotRequired[dict[str, Any]]
    results: NotRequired[ResultCountField]  # The folder's saved analysis results (R2)


class OfflineListingEvent(TypedDict):
    """A saved listing's status of its folder, working offline (``io_ops.listings.saved_list_folder``):
    counts only (in its ``scan_cached``), never shot lists. ``listed`` False: never listed while
    online, so its subfolders aren't known (those leading to known data roots are sent anyway)."""
    kind: Literal["status"]
    details: Literal[False]
    offline: Literal[True]
    listed: bool
    listed_at: float | None
    empty: bool | None
    has_dirs: bool | None
    disk_cached: NotRequired[bool]
    cache_info: NotRequired[dict[str, Any]]
    data_root: NotRequired[DataRoot]
    results: NotRequired[ResultCountField]


class FolderSummary(_StatusBase):
    """A folder's complete status as a scan or load computes it (``summary._summary``): a scan's
    ``status`` event starts from it, and a load sends it as ``scan_summary``."""
    modified: float
    signature: str
    unsettled: NotRequired[int]


class ScanStatusEvent(_StatusBase):
    """A scan's (``details``) status of its folder."""
    modified: float
    signature: str
    unsettled: int
    disk_cached: NotRequired[bool]
    cache_info: NotRequired[dict[str, Any]]
    data_root: NotRequired[DataRoot]


class MountsSeenEvent(TypedDict):
    kind: Literal["mounts_seen"]
    mounts: list[list[str]]


class SaveGuardEvent(TypedDict):
    kind: Literal["save_guard"]
    guard: dict[str, Any]


class ScanHistoryEvent(TypedDict):
    kind: Literal["scan_history"]
    history: Any
    revision: NotRequired[int]
    saved: NotRequired[bool]


class ScanHistorySavedEvent(TypedDict):
    kind: Literal["scan_history_saved"]
    history: Any


class ScanHistoryWarningEvent(TypedDict):
    kind: Literal["scan_history_warning"]
    message: str


class ScanModeEvent(TypedDict):
    kind: Literal["scan_mode"]
    mode: Literal["metadata", "scan", "skipped"]


class ScanCachedEvent(TypedDict):
    kind: Literal["scan_cached"]
    status: dict[str, Any]


class SubtreeCachedEvent(TypedDict):
    kind: Literal["subtree_cached"]
    subtree: dict[str, Any]


class SubtreeSavedEvent(TypedDict):
    kind: Literal["subtree_saved"]
    paths: list[str]
    skipped: NotRequired[list[str]]


class SummarySaveFailedEvent(TypedDict):
    kind: Literal["summary_save_failed"]
    message: str


class FolderPrefsEvent(TypedDict):
    kind: Literal["folder_prefs"]
    path: str
    prefs: dict[str, Any]


class FolderConstantsEvent(TypedDict):
    kind: Literal["folder_constants"]
    folders: dict[str, Any]
    session_only: NotRequired[dict[str, str]]


class PresetRowFields(TypedDict):
    """One preset as the store holds it (``CacheStore.read_presets``); ``record`` None: deleted."""
    kind: str
    scope: str
    name: str
    record: str | None
    set_at: float


class PresetsEvent(TypedDict):
    """``cache_admin`` "presets": the rows it wrote (as saved now: a later choice may have won),
    then every row, or why they couldn't be read (never "none saved")."""
    kind: Literal["presets"]
    saved: list[PresetRowFields]
    rows: NotRequired[list[PresetRowFields]]
    store: NotRequired[str]  # The store's ``store_id`` (a recreated store has another).
    error: NotRequired[str]


class CacheMismatchEvent(TypedDict):
    kind: Literal["cache_mismatch"]
    missing: list[int]
    missing_count: int
    known_count: int
    listed_count: int


class FolderIconEvent(TypedDict):
    kind: Literal["folder_icon"]
    path: str
    png: str


# Loads, cached reads, Live and saves from RAM


class LoadSourceEvent(TypedDict):
    kind: Literal["load_source"]
    source: str
    cache_reason: str


class ProgressEvent(TypedDict):
    kind: Literal["progress"]
    progress: float
    checked_files: int
    loaded_files: int
    total_files: int
    failed_files: int
    unsettled_files: int
    read_bytes: NotRequired[int]
    read_files: NotRequired[int]
    total_read_bytes: NotRequired[int]


class FileStartedEvent(TypedDict):
    kind: Literal["file_started"]
    filename: str


class FileFinishedEvent(TypedDict):
    kind: Literal["file_finished"]
    filename: str


class ShotEvent(TypedDict):
    kind: Literal["shot"]
    shot: int
    artifact: str
    fingerprint: Sequence[int]  # [shot, size, mtime_ns] of its TXY file
    problematic: bool
    raw_mtime: NotRequired[int]


class ScanSummaryEvent(TypedDict):
    kind: Literal["scan_summary"]
    status: FolderSummary


class ShotsMissingEvent(TypedDict):
    kind: Literal["shots_missing"]
    missing: list[int]
    missing_count: int
    known_count: int
    listed_count: int
    reason: NotRequired[str]


class TooLargeEvent(TypedDict):
    kind: Literal["too_large"]
    estimate: int
    refused: bool


class TxyRecord(TypedDict):
    """Which TXY a dataset is made of (Q6.6, ``helab_txy.record``): the source asked for
    (``txy_sources.SOURCES``), HeLab's shots' origins (``{shot: "helab:<profile hash>"}``), those
    profiles' name/version/calibrated by hash, the profile hash asked for ("" any) and HeLab's
    folders' ``[[folder, mtime_ns]]`` as the listing found them."""
    source: str
    origins: dict[str, str]
    profiles: dict[str, dict[str, Any]]
    profile_hash: str
    folders: list[list[Any]]


class _LoadedBase(TypedDict):
    kind: Literal["loaded"]
    rows: int
    bytes: int
    files: int
    loaded_at: float
    total_files: int
    failed_files: int
    unsettled_files: int
    problematic: list[int]
    source: str
    cached: bool
    disk_cache_pending: bool
    load_counts: dict[str, int]
    cache_reason: str
    fingerprint: list[Any]
    memory_shots: list[int]
    signature: str  # The folder's, as a scan computes it: its settled MATLAB TXY (``helab_txy.matlab_signature``).
    txy: NotRequired[TxyRecord | dict[str, Any]]


class CachedLoadedEvent(_LoadedBase):
    """A cached read's dataset (``cached``)."""
    disk_cached: bool
    cache_info: dict[str, Any]
    verified: bool
    raw_times: list[list[int]]
    data_root: NotRequired[DataRoot]


class UnchangedCachedLoadedEvent(_LoadedBase):
    """A load's quick check that found the folder unchanged since its cached data."""
    disk_cached: bool
    cache_info: dict[str, Any]
    unchanged: bool
    modified: float
    modified_observed_at: float
    raw_times: list[list[int]]
    base_signature: str
    data_root: NotRequired[DataRoot]


class UnchangedHeldLoadedEvent(_LoadedBase):
    """A load's quick check that found the folder unchanged since the data in RAM was loaded."""
    cache_info: dict[str, Any]
    unchanged: bool
    modified: float
    modified_observed_at: float
    base_signature: str
    listed_at: float
    names: list[str]
    identity: str
    folder_mtime_ns: int | None
    data_root: NotRequired[DataRoot]


class LoadedEvent(_LoadedBase):
    """A load's dataset after listing the folder (``load``)."""
    cache_info: dict[str, Any]
    raw_times: list[list[int]]
    base_signature: str
    listed_at: float
    names: list[str]
    identity: str
    folder_mtime_ns: int | None
    data_root: NotRequired[DataRoot]
    disk_cached: NotRequired[bool]


class HeldLoadedEvent(_LoadedBase):
    """A save from RAM's dataset (``save_held``)."""
    cache_info: dict[str, Any]
    live_reread: list[Any]
    raw_times: list[list[int]]
    base_signature: str
    listed_at: float
    names: list[str]
    identity: str
    folder_mtime_ns: int | None
    data_root: NotRequired[DataRoot]


class LiveLoadedEvent(_LoadedBase, LiveState):
    """A Live check's new shots (``live_check``), with what the next check compares with."""
    live_reread: list[Any]
    raw_times: list[list[int]]
    base_signature: str
    modified: float
    modified_observed_at: float


class LiveUnchangedEvent(LiveState):
    kind: Literal["live_unchanged"]
    total_files: int


# The disk cache


class CacheSavedEvent(TypedDict):
    kind: Literal["cache_saved"]
    cache_info: dict[str, Any]
    superseded: list[Any]
    job_seq: int
    next_deadline: float | None
    usage: int
    usage_seq: list[Any]


class DiskCachedEvent(TypedDict):
    kind: Literal["disk_cached"]
    disk_cached: bool


class CacheSaveFailedEvent(TypedDict):
    kind: Literal["cache_save_failed"]
    message: str
    next_deadline: float | None


class PendingSaveEvent(TypedDict):
    """A dataset save held until the user answers: ``cache_full`` (it doesn't fit) or
    ``cache_approval`` (it grows the cache over 80%)."""
    kind: Literal["cache_full", "cache_approval"]
    pending_id: str
    path: str
    reason: str
    bytes: int
    usage: int
    usage_seq: list[Any]
    created_at: float
    budget: int | None
    job_seq: int
    replaces: Any
    superseded: list[Any]
    next_deadline: float | None
    room: NotRequired[dict[str, Any]]


class RemovedEvent(TypedDict):
    """What a removal did (``FolderCache.removed``); ``paths`` None: every path of those kinds.
    Kind ``results`` (saved analysis results, R2): ``results`` removed, and for a data root's
    Clear cached analysis its ``root`` UUID."""
    kind: Literal["removed"]
    kinds: list[str]
    paths: list[str] | None
    datasets: NotRequired[int]
    bytes: NotRequired[int]
    results: NotRequired[int]
    root: NotRequired[str | None]
    # Saved results Make room removed for a waiting one, [folder, lookup, result_id] each: not a clear
    # (no epoch moved; a newer copy of one of those keys has another result_id).
    evicted: NotRequired[list[list[str]]]


class ResultCountField(TypedDict):
    """A folder's saved results (``CacheStore.ResultCount``): the row badge and Folder details. ``seq``
    is the store's [store_id, writes] when counted; the newest wins."""
    count: int
    bytes: int
    seq: list[Any]


class ResultsField(TypedDict, total=False):
    """A listing's own folder's saved results, when known (``ListedStatusEvent.results``)."""
    results: ResultCountField


class FolderResultsField(TypedDict, total=False):
    """A save's folder's saved results after it (``ResultSavedEvent.folder_results``)."""
    folder_results: ResultCountField


class ResultGuard(TypedDict):
    """A result save's guard (``CacheStore.start_result_job``), taken when its run started."""
    generations: dict[str, int]
    epochs: dict[str, int]
    # The store it was taken in (its ``store_id``): a save with it writes nothing in another, such
    # as one recreated at the cache folder since.
    store: NotRequired[str]


class ResultFoundEvent(TypedDict):
    """A saved result for a run (``io_ops.results.result_find``): exact, or an outdated one of the
    same plot and settings. Its data file is ``artifact`` in the helper's private folder."""
    kind: Literal["result_found"]
    artifact: str
    exact: bool
    lookup: NotRequired[str]  # The row's own key (an outdated one's differs from the one asked)
    result_id: NotRequired[str]  # The row's id (Make room's eviction names the rows it removed by it)
    store: NotRequired[str]  # The store's ``store_id`` (a recreated store has another)
    record: Any
    computed_at: float
    bytes: int
    guard: NotRequired[ResultGuard]


class ResultMissingEvent(TypedDict):
    """None saved for the run; ``ram_only``: the folder has no disk cache; ``no_cache``: the user
    chose not to cache it."""
    kind: Literal["result_missing"]
    guard: NotRequired[ResultGuard]
    store: NotRequired[str]  # The store's ``store_id`` (absent without a store: ``ram_only``)
    ram_only: NotRequired[bool]
    no_cache: NotRequired[bool]


class ResultSavedEvent(UsageFields):
    kind: Literal["result_saved"]
    bytes: int
    result_id: NotRequired[str]  # Its saved row's id (new for every save)
    store: NotRequired[str]  # The store's ``store_id``
    folder_results: NotRequired[ResultCountField]  # The folder's saved results after it
    # The store's next cleanup deadline: a save that replaced a result retired its file.
    next_deadline: NotRequired[float | None]


class ResultPendingEvent(UsageFields):
    """A result that doesn't fit the disk budget waits for the user's answer (Make room or Discard):
    ``room`` is what Make room would remove (``CacheStore.result_room_plan``), None if unknown."""
    kind: Literal["result_pending"]
    pending_id: str
    path: str
    label: str
    bytes: int
    budget: int | None
    room: dict[str, Any] | None
    store: NotRequired[str]  # The store's ``store_id``: it waits there
    next_deadline: NotRequired[float | None]  # (Its expiry, an hour unanswered.)


class ResultNotSavedEvent(UsageFields):
    """Why not: ``over_budget``, ``cleared`` (the guard), ``no_cache``, ``ram_only``."""
    kind: Literal["result_not_saved"]
    reason: str
    message: str
    bytes: int  # its file (0 when not known)
    budget: int | None
    store: NotRequired[str]  # The store's ``store_id`` (absent without a store: ``ram_only``)
    next_deadline: NotRequired[float | None]  # A refused save retired its file: the sweep deletes it.


class InventoryEvent(TypedDict):
    kind: Literal["inventory"]
    inventory: dict[str, Any]


class PrefsClearedEvent(TypedDict):
    kind: Literal["prefs_cleared"]
    paths: list[str]
    set_at: float


class AdminResultEvent(AdminResultFields, UsageFields):
    """The end of a ``cache_admin`` action."""
    kind: Literal["admin_result"]
    action: str
    next_deadline: float | None


class InvalidatedEvent(UsageFields):
    """The end of an ``invalidate`` request (``admin_result``, action ``invalidate``)."""
    kind: Literal["admin_result"]
    action: Literal["invalidate"]
    next_deadline: float | None


class SweptEvent(UsageFields):
    kind: Literal["swept"]
    old_caches: list[str]
    deleted_files: int
    expired_pending: int
    expired_ids: list[str]
    still_open: int
    next_deadline: float | None


class SweptReadOnlyEvent(TypedDict):
    """A sweep of a store opened read-only: only the old cache folders were removed."""
    kind: Literal["swept"]
    old_caches: list[str]
    deleted_files: int
    expired_pending: int
    next_deadline: None
    read_only: bool


class MoveCheckEvent(MoveCheckFields):
    kind: Literal["move_check"]


class MoveProgressEvent(TypedDict):
    kind: Literal["move_progress"]
    done: int
    total: int


class MoveDoneEvent(TypedDict):
    kind: Literal["move_done"]
    record: dict[str, Any]


class MoveFailedEvent(TypedDict):
    kind: Literal["move_failed"]
    message: str
    left: list[str]
    store_at: str


class MoveCleanedEvent(TypedDict):
    kind: Literal["move_cleaned"]
    left: list[str]


class MoveAbortedEvent(TypedDict):
    kind: Literal["move_aborted"]
    left: list[str]
    store_at: str


class MoveRecoveredEvent(TypedDict):
    kind: Literal["move_recovered"]
    message: str
    usable: bool


class TraceFolderEvent(TypedDict):
    kind: Literal["trace_folder"]
    problem: str
    earlier: list[dict[str, Any]]


# Data roots


class RootFoundEvent(TypedDict):
    """A marker reconciled (``root_found``), or found with another UUID than the location had
    (``root_changed``)."""
    kind: Literal["root_found", "root_changed"]
    path: str
    location: str
    uuid: str
    label: str


class RootChangedEvent(TypedDict):
    """A location's root forgotten: its marker removed, deleted or made invalid, or the user forgot it."""
    kind: Literal["root_changed"]
    path: str
    location: str
    reason: str


class RootDuplicateEvent(TypedDict):
    kind: Literal["root_duplicate"]
    path: str
    location: str
    uuid: str
    label: str
    other_locations: list[str]
    marker: dict[str, Any] | None
    others: list[dict[str, Any]]


class RootRekeyedEvent(TypedDict):
    kind: Literal["root_rekeyed"]
    path: str
    count: int


class RootConfirmedEvent(TypedDict):
    kind: Literal["root_confirmed"]
    location: str
    uuid: str
    path: str
    label: str


class RootCreatedEvent(TypedDict):
    """A marker written (``root_created``) or one already there taken on (``root_adopted``)."""
    kind: Literal["root_created", "root_adopted"]
    path: str
    uuid: str
    label: str


class RootManualEvent(TypedDict):
    """A marker HeLab couldn't write: its exact contents, for the user to place."""
    kind: Literal["root_manual"]
    path: str
    name: str
    contents: str
    reason: str
    replace: NotRequired[bool]


class RootReassignedEvent(TypedDict):
    kind: Literal["root_reassigned"]
    path: str
    uuid: str
    label: str
    old_uuid: str
    moved: list[str]
    kept: str


class RootRemovedEvent(TypedDict):
    kind: Literal["root_removed"]
    path: str
    uuid: str
    forgotten: list[str]


class RootRemoveRefusedEvent(TypedDict):
    kind: Literal["root_remove_refused"]
    path: str
    file: str
    reason: str


class ClockSkewEvent(TypedDict):
    """A source file dated more than ``fingerprints.FUTURE_SECONDS`` ahead of this computer's clock:
    the computers' clocks are out of sync (``clock_skew``; the app tells the user once per location)."""
    kind: Literal["clock_skew"]
    path: str  # the folder
    seconds: float  # how far its newest file is ahead
    location: str  # its share or volume (the mount's source), else the folder


class MarkerSaveEvent(TypedDict):
    """The manual marker dialog's copy (``marker_save``): written, or a file already there (not replaced)."""
    kind: Literal["marker_saved", "marker_save_exists"]
    path: str
    file: str


class MarkerSaveRefusedEvent(TypedDict):
    kind: Literal["marker_save_refused"]
    path: str
    file: str
    reason: str


class VolumesVerifiedEvent(TypedDict):
    kind: Literal["volumes_verified"]
    volumes: list[list[str]]
    ids: list[list[str]]


class RootsVerifiedEvent(TypedDict):
    kind: Literal["roots_verified"]
    mounts: list[list[str]]


class ConvertPrefsEvent(TypedDict):
    """A folder's converter flags as the store now has them (``cache_admin convert_prefs``):
    ``prefs`` is ``{"write_beside": bool, "set_at": float}``."""
    kind: Literal["convert_prefs"]
    path: str
    prefs: dict[str, Any]


# The converter (``io_ops.convert``, TXY converter stage 4). Every event names the source folder
# (``path``); a shot's events name its raw file and that file's (size, mtime) as this conversion saw
# them, so the app can tell a later change apart.


class ConvertProfile(TypedDict):
    """The detector profile a conversion used: provenance (``helab.convert.profile``)."""
    name: str
    version: int
    hash: str  # ``DetectorProfile.content_hash()``: equal hashes convert every file alike
    calibrated: bool


class ConvertSeconds(TypedDict):
    read: float  # the raw file's bytes, from the source folder
    parse: float
    reconstruct: float
    format: float
    write: float  # the TXY and its provenance record


class ConvertPlanEvent(TypedDict):
    """Sent once, after the folder is listed: where this conversion writes and what it found.
    ``output`` is where the TXY go (``beside``, ``cache`` or ``temp``): the one asked for, or
    ``temp`` with ``fallback`` saying why (no data root, the disk cache off or unreadable; Q9.3), or
    the setting's output when ``beside`` was asked for a folder whose flag is off.
    ``folder`` is HeLab's own folder for this source folder (the TXY unless beside, and every
    provenance record); ``txy_folder`` where the TXY go; ``key`` the data-root key ("" without)."""
    kind: Literal["convert_plan"]
    path: str
    output: str
    fallback: str
    folder: str
    txy_folder: str
    key: str
    profile: ConvertProfile
    backend: str
    workers: int
    raw: int  # raw files the folder lists (of the shots asked for)
    todo: int  # of those, to convert now


class ShotConvertedEvent(TypedDict):
    """A shot converted: its TXY (``txy``, 0 bytes when ``hits`` is 0: "converted, empty", Q10.3) and
    provenance record (``provenance``) written atomically. A low-count shot is the app's to judge
    from ``hits``."""
    kind: Literal["shot_converted"]
    path: str
    shot: int
    raw_name: str
    raw_size: int
    raw_mtime_ns: int
    raw_sha256: str
    output: str
    txy: str
    txy_size: int
    provenance: str
    hits: int
    replaced: str  # why an older HeLab TXY of the shot was replaced ("" if there was none)
    profile: ConvertProfile
    backend: str
    seconds: ConvertSeconds


class ShotWaitingEvent(TypedDict):
    """A raw file not converted yet: it may still be being written (``reason``: ``settling``,
    ``changed``, ``no_final_newline``, ``not_trigger_first``), is dated ahead of this computer's
    clock (``future``, with ``clock_skew`` for the folder) or couldn't be read now
    (``read_failed``). Nothing was written; it is looked at again by a later conversion."""
    kind: Literal["shot_waiting"]
    path: str
    shot: int
    raw_name: str
    raw_size: int
    raw_mtime_ns: int
    reason: str
    message: str


class ShotUnconvertibleEvent(TypedDict):
    """A settled raw file that can't be converted (``reason``: ``no_rows``, Q10.2, or ``failed``):
    no TXY. A later conversion skips it while its (size, mtime) stay the same and the app sends them
    back in ``skip``."""
    kind: Literal["shot_unconvertible"]
    path: str
    shot: int
    raw_name: str
    raw_size: int
    raw_mtime_ns: int
    reason: str
    message: str


class ShotKeptEvent(TypedDict):
    """A HeLab TXY already beside the raw file that this conversion doesn't stand behind (no local
    provenance record, or a stale one): kept as it is, since a TXY in a source folder is never
    replaced (``reason`` says which)."""
    kind: Literal["shot_kept"]
    path: str
    shot: int
    txy: str
    reason: str


class ConvertProgressEvent(TypedDict):
    """After each shot handled (at most a few per second): counts so far of the ``todo`` shots."""
    kind: Literal["convert_progress"]
    path: str
    done: int
    todo: int
    converted: int
    raw_bytes: int  # read so far


class ConvertSummaryEvent(TypedDict):
    """The conversion's end (before ``done``). Shot lists are the raw files' ``[name, size,
    mtime_ns]``: ``current`` (a current HeLab TXY: converted now or before), ``waiting`` (with its
    reason and message after them), ``unconvertible`` and ``kept`` (beside: a TXY there this
    conversion doesn't stand behind); the next conversion of the folder (Live, ``helab convert
    --watch``) sends them back as ``done``, ``seen``, ``skip`` and ``kept``, so it neither checks
    done or kept shots again, nor takes a file whose size or mtime changed between two checks as
    finished, nor reads an unfinished one again while it is unchanged."""
    kind: Literal["convert_summary"]
    path: str
    output: str
    folder: str
    txy_folder: str
    converted: int
    current: list[list[Any]]
    waiting: list[list[Any]]
    unconvertible: list[list[Any]]
    kept: list[list[Any]]
    seconds: float


class PartialRemovedEvent(TypedDict):
    """A beside conversion removed a leftover temporary TXY of its own (``.d_txy_helab_<N>.txy.<16
    hex>.partial``, a regular file over ``io_ops.convert.PARTIAL_MAX_AGE`` old: a write a killed
    helper left) from the source folder ``path``."""
    kind: Literal["partial_removed"]
    path: str
    file: str
    size: int
    age: float  # seconds since it was last modified


HelperEvent = Union[
    DoneEvent, ErrorEvent, PausedEvent, ResumedEvent, HeartbeatEvent, DrivesEvent, ResolvedEvent,
    CacheWarningEvent, CacheSkippedEvent,
    EntriesEvent, ListedStatusEvent, OfflineListingEvent, ScanStatusEvent, MountsSeenEvent, SaveGuardEvent, ScanHistoryEvent,
    ScanHistorySavedEvent, ScanHistoryWarningEvent, ScanModeEvent, ScanCachedEvent, SubtreeCachedEvent,
    SubtreeSavedEvent, SummarySaveFailedEvent, FolderPrefsEvent, FolderConstantsEvent, PresetsEvent, CacheMismatchEvent,
    FolderIconEvent,
    LoadSourceEvent, ProgressEvent, FileStartedEvent, FileFinishedEvent, ShotEvent, ScanSummaryEvent,
    ShotsMissingEvent, TooLargeEvent, CachedLoadedEvent, UnchangedCachedLoadedEvent, UnchangedHeldLoadedEvent,
    LoadedEvent, HeldLoadedEvent, LiveLoadedEvent, LiveUnchangedEvent,
    CacheSavedEvent, DiskCachedEvent, CacheSaveFailedEvent, PendingSaveEvent, RemovedEvent, InventoryEvent,
    PrefsClearedEvent, AdminResultEvent, InvalidatedEvent, SweptEvent, SweptReadOnlyEvent,
    MoveCheckEvent, MoveProgressEvent, MoveDoneEvent, MoveFailedEvent, MoveCleanedEvent, MoveAbortedEvent,
    MoveRecoveredEvent, TraceFolderEvent,
    RootFoundEvent, RootChangedEvent, RootDuplicateEvent, RootRekeyedEvent, RootConfirmedEvent, RootCreatedEvent,
    RootManualEvent, RootReassignedEvent, RootRemovedEvent, RootRemoveRefusedEvent, ClockSkewEvent, MarkerSaveEvent,
    MarkerSaveRefusedEvent, VolumesVerifiedEvent, RootsVerifiedEvent,
    ResultFoundEvent, ResultMissingEvent, ResultSavedEvent, ResultNotSavedEvent, ResultPendingEvent,
    ConvertPrefsEvent, ConvertPlanEvent, ShotConvertedEvent, ShotWaitingEvent, ShotUnconvertibleEvent, ShotKeptEvent,
    ConvertProgressEvent, ConvertSummaryEvent, PartialRemovedEvent,
]

# Every kind a helper sends.
KINDS = frozenset({
    "done", "error", "paused", "resumed", "heartbeat", "drives", "resolved", "cache_warning", "cache_skipped",
    "entries", "status", "mounts_seen", "save_guard", "scan_history", "scan_history_saved",
    "scan_history_warning", "scan_mode", "scan_cached", "subtree_cached", "subtree_saved", "summary_save_failed",
    "folder_prefs", "folder_constants", "presets", "cache_mismatch", "folder_icon",
    "load_source", "progress", "file_started", "file_finished", "shot", "scan_summary", "shots_missing",
    "too_large", "loaded", "live_unchanged",
    "cache_saved", "disk_cached", "cache_save_failed", "cache_full", "cache_approval", "removed", "inventory",
    "prefs_cleared", "admin_result", "swept",
    "move_check", "move_progress", "move_done", "move_failed", "move_cleaned", "move_aborted", "move_recovered",
    "trace_folder",
    "root_found", "root_changed", "root_duplicate", "root_rekeyed", "root_confirmed", "root_created",
    "root_adopted", "root_manual", "root_reassigned", "root_removed", "root_remove_refused",
    "clock_skew", "marker_saved", "marker_save_exists", "marker_save_refused", "volumes_verified",
    "roots_verified", "result_found", "result_missing", "result_saved", "result_not_saved",
    "result_pending",
    "convert_prefs", "convert_plan", "shot_converted", "shot_waiting", "shot_unconvertible", "shot_kept",
    "convert_progress", "convert_summary", "partial_removed",
})
