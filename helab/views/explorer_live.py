"""Live for a folder tab (roadmaps/live-monitoring.md): ``LiveController`` checks the tab's
selected folder for new shots and saves them, and ``LiveSession`` is one folder's Live state.
``FolderExplorer`` owns one controller (``FolderExplorer.live_control``) and routes Live's I/O
results to it."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
import math
import os
import time
from typing import TYPE_CHECKING, Any
import weakref

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QInputDialog, QMenu, QMessageBox

from helab.utils import events
from helab.utils import folder_cache
from helab.utils.folder_cache import Dataset, FolderCache
from helab.utils.io_service import IORequest
from helab.utils.settings_defaults import CONVERT_LOW_HITS_SETTING, read_setting, setting_default
from helab.utils.settings_store import app_settings
from helab.utils.time_format import relative_age
from helab.views import live_launch
from helab.views.explorer_text import large_text, plural

if TYPE_CHECKING:
    from helab.views.FolderExplorer import FolderExplorer

# Why Live's new shots aren't saved to the disk cache: the summary line's words, and the tooltip's.
LIVE_BLOCKED = {
    "disk cache off": "the disk cache is off for this session",
    "Don't cache": "you chose Don't cache for this folder (right-click to change)",
    "RAM only": "RAM only: no .helab-root found here or above",
    "RAM only until confirmed": "RAM only until you answer whether its .helab-root is the same folder or a copy",
    "cached data mismatched": "its cached data doesn't match the folder (Review…)",
    "cache unavailable": "the disk cache couldn't be written for this folder this time",
}


# Why a raw file isn't converted yet that is no news while Live watches: it was just written, or
# changed between two checks (``io_ops.convert``'s ``shot_waiting`` reasons). Others wait for good,
# re-checked only when the file changes (no final newline, off the trigger channel: Q12.5), or
# until the clock or the share lets it be read (``future``, ``read_failed``).
CONVERT_SETTLING = ("settling", "changed")
# A raw file unmodified for 20 s that still fails the format checks (``io_ops.convert.DAMAGED``, Q18.5):
# its ``shot_unconvertible`` reason, and how its message starts (as FolderCache keeps it after auto-convert
# is turned off and on).
DAMAGED_REASON = "damaged"
DAMAGED_TEXT = "Damaged: "
# What the Live line calls each place HeLab's TXY go (``convert_plan.output``).
CONVERT_OUTPUTS = {"beside": "beside the raw files", "cache": "HeLab's disk cache folder",
                   "temp": "HeLab's temp folder"}


@dataclass(eq=False)
class AutoConvert:
    """Live's auto-convert for one folder (TXY converter stage 4, Q6.8): while it is on, each Live
    check also asks for a conversion of the folder's settled raw files (``FolderCache.convert``),
    one at a time, at least a check interval apart (the settle rule's two checks). Converted shots
    then reach the data through Live's next check."""
    started_at: float  # Wall time.
    request: bool = False  # A conversion in flight.
    passes: int = 0
    ended_at: float = -math.inf  # Monotonic: when the last conversion ended.
    todo: int = 0  # The running conversion's shots to convert, and those done.
    done: int = 0
    converted: int = 0  # Shots converted since auto-convert was turned on.
    last_shot: int | None = None
    last_hits: int = 0
    last_at: float | None = None  # Wall time.
    low: int = 0  # Low-count shots notified.
    # The last plan: where the TXY go and why not where asked, the profile and backend.
    output: str = ""
    fallback: str = ""
    txy_folder: str = ""
    profile: dict[str, Any] = field(default_factory=dict)
    backend: str = ""
    # Raw files not converted (by name): waiting (reason, message), from the last conversion;
    # unconvertible (message), kept while they stay unconvertible, the damaged ones among them (Q18.5)
    # named in ``damaged``; kept beside (shot: reason).
    waiting: dict[str, tuple[str, str]] = field(default_factory=dict)
    unconvertible: dict[str, str] = field(default_factory=dict)
    damaged: set[str] = field(default_factory=set)
    kept: dict[int, str] = field(default_factory=dict)
    error: str = ""  # Why conversions stopped (Retry, or auto-convert off and on, starts them again).

    def stuck(self) -> dict[str, tuple[str, str]]:
        """Files waiting for more than being written: no final newline, off the trigger channel,
        dated ahead or unreadable now."""
        return {name: why for name, why in self.waiting.items() if why[0] not in CONVERT_SETTLING}


def low_hits_threshold() -> int:
    """Settings: a converted shot with fewer hits notifies (0: never)."""
    try:
        return max(0, int(read_setting(app_settings(), CONVERT_LOW_HITS_SETTING)))
    except (TypeError, ValueError, OverflowError):
        return int(setting_default(CONVERT_LOW_HITS_SETTING))


@dataclass(eq=False)
class LiveSession:
    """Live for one folder of a tab (roadmaps/live-monitoring.md): its checks, and its new shots
    until they are saved to the disk cache. Kept after Live stops while a save of them runs."""
    path: str
    started_at: float  # Wall time.
    # The newest data's shots, and the data (its fingerprint names unreadable shots: ``known``).
    shots: set[int]
    dataset: Dataset
    # On (checking, or stopped by an error until Retry or Live off) or off (a save may still run).
    on: bool = True
    error: str = ""
    # The folder's mtime the next check may compare (None: the check lists the folder).
    since: int | None = None
    # "check" or "save" in flight (a save until its data arrives; its write runs after that).
    request: str = ""
    reading: bool = False
    checks: int = 0
    checked_at: float | None = None  # Wall time.
    seconds: float | None = None  # How long the last check took (the helper's measure).
    listed: bool = False  # Whether the last check listed the folder (else one stat).
    listed_at: float = -math.inf  # Monotonic: when a check last listed it.
    # The folder's identity (data root, else location) as Live's first listing found it: a later
    # listing finding another folder at this path stops Live. The folder whose .helab-root names it
    # ("" for a location; None until found): later listings read only that marker.
    identity: str = ""
    identity_root: str | None = None
    # New files the last check saw but didn't read ([shot, size, mtime_ns]) and their names: read
    # once they show the same size and mtime again, a check later.
    seen: list[list[int]] = field(default_factory=list)
    seen_names: list[str] = field(default_factory=list)
    # The folder's mtime as of the last listing: while it stays, a check stats only the files in
    # ``seen`` instead of listing the folder.
    listed_mtime: int | None = None
    next_at: float = 0.0  # Monotonic.
    new: int = 0  # New shots since Live started.
    unsettled: int = 0  # Files still being written at the last check.
    # New shots not yet in a save, and those in the save that runs (until it ends).
    unsaved: set[int] = field(default_factory=set)
    saving: set[int] = field(default_factory=set)
    # Unsaved shots that start a save (0: the setting); raised after a failed save.
    threshold: int = 0
    # Why this folder can't be saved (e.g. RAM only), found by a save; the last save's problem.
    blocked: str = ""
    note: str = ""
    saved_at: float | None = None  # Wall time.
    # When Live itself read each shot (wall time; read again: when that was). A shot it read
    # recently that changes is read again, not a mismatch (``LiveController.LIVE_REREAD_SECONDS``).
    read_at: dict[int, float] = field(default_factory=dict)
    # Auto-convert, while it is on (None: off).
    convert: AutoConvert | None = None
    # A conversion wrote a shot while a check ran: the next check starts at once.
    check_soon: bool = False

# Work Offline: Live reads the folder, so it is off (cache-only browsing).
OFFLINE_LIVE = "Live is off while working offline"


class LiveController:
    """Live (roadmaps/live-monitoring.md) for one ``FolderExplorer``: the selected folder's data,
    checked for new shots a cooldown after each check. New shots stay in RAM until N of them wait
    (or Live stops): then an ordinary load saves the folder in the background.

    The tab keeps its load and display state; the controller reads and sets it through
    ``explorer``, and the tab routes Live's I/O results (owners ``live_owner`` and
    ``live_save_owner``) and ``FolderCache.saveEnded`` here."""
    # A Live check lists the folder at least this often, even if its mtime is unchanged: a network
    # drive may report a folder's mtime late (SMB clients cache it for seconds).
    LIVE_LIST_SECONDS = 60.0
    # A held shot Live itself read less than this long ago that changes (its writer paused longer
    # than the settle age, so it was read unfinished) is read again and replaces the held one, by
    # Tony's decision; an older one that changes still stops Live as mismatched (a remount or a copy).
    # Five minutes covers the next listing (the next new shot, or once a minute) and the next save.
    LIVE_REREAD_SECONDS = 300.0
    # How long the tab's Live line and Folder details say that shots were read again.
    LIVE_REREAD_NOTE_SECONDS = 60.0

    def __init__(self, explorer: FolderExplorer) -> None:
        # The tab, which owns this controller. Held weakly: a reference cycle would keep the tab's
        # wrapper alive after Qt deletes the tab (until the garbage collector runs), where it now
        # goes with its C++ object. The timer below is the tab's child, so it goes with the tab.
        self._explorer = weakref.ref(explorer)
        # The folder watched while Live is on, and every folder whose Live work isn't finished.
        self.live: LiveSession | None = None
        self._live_sessions: dict[str, LiveSession] = {}
        # Shots Live read again, by folder: the note and when (monotonic), shown for a minute
        # (``live_reread_note``), also after Live stops and its session ends.
        self._reread_notes: dict[str, tuple[str, float]] = {}
        self._live_timer = QTimer(explorer)
        self._live_timer.setSingleShot(True)
        self._live_timer.timeout.connect(self._live_tick)

    @property
    def explorer(self) -> FolderExplorer:
        explorer = self._explorer()
        assert explorer is not None, "the tab owns its Live controller"
        return explorer

    def session(self, path: str) -> LiveSession | None:
        """The Live session of ``path``: watched, or with a save still to run or finish."""
        return self._live_sessions.get(path)

    def watching(self, path: str | None) -> bool:
        """Live is on for ``path`` (checking, or stopped by an error until Retry)."""
        return self.live is not None and self.live.path == path

    def live_unavailable(self, path: str) -> str:
        """Why Live can't watch ``path`` now ("" if it can)."""
        explorer = self.explorer
        name = os.path.basename(path.rstrip(os.sep)) or path
        dataset = explorer.displayed_dataset
        if explorer.closed:
            return "This tab is closing"
        if explorer.model.cache.offline:
            return OFFLINE_LIVE
        if path in explorer.model.cache.mismatched:
            return f"{name}'s cached data doesn't match the folder: Review… it first"
        if ((explorer.loading and explorer._load_path == path)
                or (explorer.load_waiting and explorer._dwell_path == path)):
            return f"Wait for {name} to finish loading"
        if ((explorer.folder_opened_path != path or explorer.folder_opened_data is None or dataset is None
                or dataset.path != path or "fingerprint" not in dataset.metadata) and not self._no_shots_yet(path)):
            return "Select a folder with loaded data, or with no shots yet, to watch it for new shots"
        return ""

    def _no_shots_yet(self, path: str) -> bool:
        """Whether Live can watch ``path`` from no data, before its first shot: this session's
        listing found no TXY files in it (subfolders or not: Live reads only the folder's own
        files, never its subfolders'), and none of its data is shown, held or cached. Live is
        a deliberate click, so any folder may be watched."""
        node = self.explorer.model.nodes.get(path)
        cache = self.explorer.model.cache
        return (node is not None and node.report is not None and not node.cached_report and not node.error
                and node.txy_count == 0 and cache.latest_dataset(path) is None and not cache.disk_cached(path))

    def live_state(self) -> tuple[bool, str]:
        """Whether the toolbar's Live can be used now (to turn Live on or off), and its tooltip."""
        explorer = self.explorer
        if self.live is not None:
            name = os.path.basename(self.live.path.rstrip(os.sep)) or self.live.path
            return True, (f"Live: watching {name} for new shots\nClick to stop. New shots not yet in the "
                          "disk cache are saved in the background.")
        reason = self.live_unavailable(explorer.selected_path_globally)
        if reason:
            return False, f"Live\n{reason}."
        name = os.path.basename(explorer.selected_path_globally.rstrip(os.sep)) or explorer.selected_path_globally
        return True, (f"Live: watch {name} for new shots\nChecks the folder {explorer.model.cache.live_interval:g} s "
                      "after each check and adds new TXY files once written. The folder tree is locked "
                      "while Live is on; switching tabs turns it off.")

    def start_live(self) -> bool:
        """Turn Live on for the selected folder, whose data is shown, or which has no shots yet
        (shown as data with none). Whether it started."""
        explorer = self.explorer
        path = explorer.selected_path_globally
        if self.live is not None or self.live_unavailable(path):
            return False
        dataset = explorer.displayed_dataset
        if dataset is None or dataset.path != path or explorer.folder_opened_path != path:
            # Before the first shot: Live starts from no data; its first check lists the folder.
            dataset = explorer.model.cache.empty_dataset(path)
            explorer.load_source, explorer.load_cache_reason, explorer._load_cache_pending = "", "", False
            explorer.load_counts = {}
            explorer._display(path, dataset, {"verified": True})
        session = self._live_sessions.get(path)
        if session is None:
            session = self._live_sessions[path] = LiveSession(path, time.time(), set(dataset.data), dataset)
        elif session.dataset is not dataset and dataset.metadata.get("loaded_at", 0) >= session.dataset.metadata.get(
                "loaded_at", 0):
            session.dataset, session.shots = dataset, set(dataset.data)
        session.on, session.error = True, ""
        self.live = session
        if path in explorer.model.cache.auto_convert and session.convert is None:
            self._convert_on(session)
        # Live's first check is the folder's check now: an earlier failure's Retry is replaced by Live's.
        explorer.load_error = ""
        self._set_browsing_enabled(False)
        if not session.request:
            self._live_next(0.0)
        logging.info("Live on: %s", path)
        self._live_changed()
        return True

    def stop_live(self, save: bool = True) -> None:
        """Turn Live off: no more checks. Its new shots not yet in the disk cache are saved in the
        background (unless not ``save``), after a save that is still running."""
        explorer = self.explorer
        session = self.live
        if session is None:
            return
        self.live = None
        session.on = False
        self._live_timer.stop()
        if session.request == "check":
            session.request = ""  # Its cancellation below isn't an error.
            explorer.model.cache.cancel(explorer.live_owner, "load", session.path)
        self._convert_off(session)
        if not explorer.closed:
            self._set_browsing_enabled(True)
        if save:
            self._live_save(session)
        self._live_forget(session)
        logging.info("Live off: %s", session.path)
        self._live_changed()

    def resume_live(self) -> None:
        """Retry after an error: check the folder again (listing it) and go on; and convert again
        after auto-convert stopped on an error."""
        session = self.live
        if session is None:
            return
        if session.convert is not None and session.convert.error:
            session.convert.error = ""
            if not session.error:
                if not session.request:
                    self._live_next(0.0)
                self._live_changed()
                return
        if not session.error:
            return
        session.error, session.since, session.listed_mtime = "", None, None
        if not session.request:
            self._live_next(0.0)
        self._live_changed()

    def _live_changed(self) -> None:
        explorer = self.explorer
        if explorer.closed:
            return
        explorer._update_activity()
        explorer.liveChanged.emit()
        explorer.loadStateChanged.emit()

    def _set_browsing_enabled(self, enabled: bool) -> None:
        """Live locks the tree, path bar and Deselect: the window is about the plots then."""
        explorer = self.explorer
        for widget in (explorer.tree, explorer.path_edit, explorer.deselect_button):
            widget.setEnabled(enabled)

    def _live_next(self, delay: float | None = None) -> None:
        """The next check, ``delay`` seconds from now (the setting: from the end of this one)."""
        session = self.live
        if session is None or self.explorer.closed:
            return
        if delay is None and session.check_soon:
            delay = 0.0  # A conversion wrote a shot during the check that just ended.
        session.check_soon = False
        delay = self.explorer.model.cache.live_interval if delay is None else delay
        session.next_at = time.monotonic() + delay
        self._live_timer.start(round(delay * 1000))

    def _live_tick(self) -> None:
        """Check the folder, or save it first when N new shots wait (Settings → Cache)."""
        explorer = self.explorer
        session = self.live
        if explorer.closed or session is None or session.error or session.request:
            return
        cache = explorer.model.cache
        self._convert_tick(session)
        threshold = session.threshold or cache.live_autosave_shots
        if (len(session.unsaved) >= threshold and not session.saving and not self._live_save_blocked(session)
                and session.path not in cache.pending_saves and not cache.disk_cache_saving(session.path)
                and self._live_save(session)):
            explorer._update_activity()
            return
        dataset = session.dataset
        # Shots it couldn't read: read again only if they change.
        known = [list(entry) for entry in dataset.metadata.get("fingerprint", ()) if int(entry[0]) not in dataset.data]
        recent = time.monotonic() - session.listed_at < self.LIVE_LIST_SECONDS
        payload = {"live": True, "live_since": session.since if recent else None, "known": known,
                   "prefer_base": dataset.signature, "identity": session.identity,
                   "identity_root": session.identity_root, "seen": session.seen, "seen_names": session.seen_names,
                   "listed_mtime": session.listed_mtime if recent else None, "check_level": cache.check_level,
                   "recent": self._live_recent(session)}
        if not cache.submit(explorer.live_owner, 0, session.path, "load", payload, priority=True):
            self._live_halt(session, "Live check couldn't be queued — Retry")
            return
        session.request, session.reading = "check", False
        explorer._update_activity()

    def _live_save_blocked(self, session: LiveSession) -> str:
        """Why the folder's new shots can't be saved to the disk cache, in a few words for the
        summary line ("" if they can); ``LIVE_BLOCKED`` explains each in the tooltip."""
        cache = self.explorer.model.cache
        path = session.path
        if not folder_cache.store_options():
            return "disk cache off"
        if cache.folder_prefs(path)["no_cache"]:
            return "Don't cache"
        if cache.no_root(path) is not None:
            return "RAM only"
        if cache.pending_root(path) is not None:
            return "RAM only until confirmed"
        if path in cache.mismatched:
            return "cached data mismatched"
        return session.blocked

    def _live_save(self, session: LiveSession) -> bool:
        """Save the folder's new shots in the background (an ordinary load that re-reads them):
        now, or after its running save. Whether a save was started."""
        if not session.unsaved or session.request or self._live_save_blocked(session):
            return False
        cache = self.explorer.model.cache
        # Saved from RAM: the folder is listed and its files checked, none read (``io_ops.save_held.save_held``).
        payload = {"cache": folder_cache.store_options(), "signature": "", "no_cache": False, "check_level": cache.check_level,
                   "limits": cache.large_limits(), "deliberate": False, "allow_large": False,
                   "prefer_base": session.dataset.signature, "save_memory": True,
                   "identity": session.identity, "identity_root": session.identity_root,
                   "recent": self._live_recent(session)}
        if not cache.save(self.explorer.live_save_owner, session.path, payload):
            session.note = "Save queue full"
            return False
        session.saving |= session.unsaved
        session.unsaved = set()
        session.request, session.reading = "save", False
        return True

    def _live_recent(self, session: LiveSession) -> list[int]:
        """The shots Live itself read within ``LIVE_REREAD_SECONDS``: read again if they change."""
        oldest = time.time() - self.LIVE_REREAD_SECONDS
        for shot in [shot for shot, at in session.read_at.items() if at < oldest]:
            del session.read_at[shot]
        return sorted(session.read_at)

    def _live_reread(self, session: LiveSession, entries: list[dict[str, Any]]) -> None:
        """Shots Live read recently that changed since and were read again: one WARNING each (for
        Tony to report: the converter writing to a temporary name and renaming it avoids this), and
        a note on the Live line and in Folder details for ``LIVE_REREAD_NOTE_SECONDS``."""
        now = time.time()

        def when(nanoseconds: int) -> str:
            try:
                return datetime.fromtimestamp(nanoseconds / 1e9).astimezone().isoformat(timespec="milliseconds")
            except (ValueError, OverflowError, OSError):  # A corrupt far-future mtime (Windows' localtime).
                return f"{nanoseconds} ns"
        for entry in entries:
            shot = int(entry["shot"])
            (old_size, old_mtime), (new_size, new_mtime) = entry["old"], entry["new"]
            read_at = session.read_at.get(shot)
            logging.warning(
                "Live: shot %s changed %s after Live read it, read again%s: %s (size %s → %s bytes, mtime %s → %s). "
                "The converter writing to a temporary name and renaming it avoids this.", shot,
                f"{now - read_at:.0f} s" if read_at is not None else "some time", "" if entry.get("read") else
                " (now unreadable)", entry.get("path", ""), f"{old_size:,}", f"{new_size:,}", when(old_mtime),
                when(new_mtime))
            session.read_at[shot] = now
        shots = sorted(int(entry["shot"]) for entry in entries)
        note = (f"Shot {shots[0]} changed after it was read (writer paused > 5 s?): read again" if len(shots) == 1
                else f"Shots {', '.join(map(str, shots[:5]))}{' …' if len(shots) > 5 else ''} changed after they "
                     "were read (writer paused > 5 s?): read again")
        self._reread_notes[session.path] = (note, time.monotonic())

    def live_reread_note(self, path: str) -> str:
        """Shots of ``path`` that Live read again in the last ``LIVE_REREAD_NOTE_SECONDS`` ("" if none)."""
        note, at = self._reread_notes.get(path, ("", -math.inf))
        if time.monotonic() - at >= self.LIVE_REREAD_NOTE_SECONDS:
            self._reread_notes.pop(path, None)
            return ""
        return note

    def _live_forget(self, session: LiveSession) -> None:
        """A session that is off with no save left to run or finish is done."""
        if not session.on and not session.request and not session.saving:
            self._live_sessions.pop(session.path, None)

    def _live_halt(self, session: LiveSession, message: str) -> None:
        """Stop checking (Live stays on, data kept): Retry checks again, Live off saves."""
        logging.warning("Live stopped for %s: %s", session.path, message)
        session.error = message
        events.notify(events.LIVE_ERROR, f"Live stopped for {session.path}: {message}", path=session.path,
                      error=message)  # For hooks (helab/utils/events.py); no desktop notification.
        self._live_timer.stop()
        self._live_changed()

    def _live_event(self, request: IORequest, event: dict[str, Any]) -> None:
        explorer = self.explorer
        session = self._live_sessions.get(request.path)
        kind = event["kind"]
        if request.operation == "convert":
            if session is not None:
                self._convert_event(session, event)
            return
        if session is None:
            # A save of a folder this tab no longer watches: its data shows if this tab shows the folder.
            if (kind == "loaded" and request.path == explorer.selected_path_globally
                    and explorer.folder_opened_path == request.path):
                self._live_display(request.path, event)
            return
        if kind == "file_started":
            session.reading = True
        elif kind == "loaded":
            self._live_loaded(session, event)
        elif kind == "live_unchanged":
            self._live_unchanged(session, event)
        elif kind in ("error", "cancelled", "shots_missing", "too_large"):
            if not session.request:
                return  # Cancelled by this tab (Live off).
            what, session.request = session.request, ""
            if kind == "shots_missing":
                count = int(event.get("missing_count", 0))
                reason = event.get("reason")
                message = ("another folder is at this path now (drive or data root changed)" if reason == "root"
                           else f"{plural(count, 'shot')} changed in the folder" if reason == "changed"
                           else f"{plural(count, 'shot')} missing from the folder")
            elif kind == "too_large":
                message = large_text(int(event.get("estimate", 0)), bool(event.get("refused")))
            else:
                message = str(event.get("message") or "Cancelled — Retry").removesuffix(" — Retry")
            if what == "save":
                session.unsaved |= session.saving
                session.saving = set()
                session.note = f"Save failed: {message}"
            if session.on:
                self._live_halt(session, message)
            else:
                self._live_forget(session)
        else:
            return
        explorer._update_activity()

    def _live_display(self, path: str, event: dict[str, Any]) -> None:
        """Show a Live result as a load's: the shown dataset is replaced (plots keep theirs)."""
        explorer = self.explorer
        explorer.load_source = event.get("source", "")
        explorer.load_counts = dict(event.get("load_counts", {}))
        explorer.load_cache_reason = event.get("cache_reason", "")
        explorer._load_cache_pending = bool(event.get("disk_cache_pending"))
        if "modified" in event:
            explorer.model.observe_modified(path, event["modified"], event.get("modified_observed_at", time.time()))
        dataset = event["dataset"]
        assert isinstance(dataset, Dataset)
        explorer._display(path, dataset, event)

    def _live_loaded(self, session: LiveSession, event: dict[str, Any]) -> None:
        """A check (or save) brought new shots: shown at once, and saved later."""
        explorer = self.explorer
        dataset = event["dataset"]
        assert isinstance(dataset, Dataset)
        what, session.request = session.request, ""
        new = set(dataset.data) - session.shots
        if what == "check":
            now = time.time()
            session.read_at.update(dict.fromkeys(new, now))
        reread = [entry for entry in event.get("live_reread") or () if isinstance(entry, dict)]
        if reread:
            self._live_reread(session, reread)
        # Read again: their new data is saved too (a save's own result saves it with this one).
        changed = {int(entry["shot"]) for entry in reread}
        session.dataset, session.shots = dataset, set(dataset.data)
        session.new += len(new)
        session.checks += 1
        session.checked_at, session.reading = time.time(), False
        session.seconds = event.get("live_seconds")
        session.since = event.get("live_since")  # (A save's listing doesn't say: the next check lists.)
        session.unsettled = int(event.get("unsettled_files", 0))
        session.listed, session.listed_at = True, time.monotonic()
        self._live_observed(session, event)
        if event.get("disk_cache_pending"):
            # Saved with this result (a save, or another tab's load the check joined).
            session.saving |= new
        elif what == "save":
            if not event.get("cached"):
                # Nothing could be saved (e.g. the cache couldn't be opened): not tried again.
                session.blocked = "cache unavailable"
                session.unsaved |= session.saving | new
            session.saving = set()
        else:
            session.unsaved |= new | changed
        if (explorer.selected_path_globally == session.path
                and (session.on or explorer.folder_opened_path == session.path)):
            self._live_display(session.path, event)
        if session.on and not session.error:
            self._live_next()
        else:
            self._live_forget(session)

    def _live_unchanged(self, session: LiveSession, event: dict[str, Any]) -> None:
        explorer = self.explorer
        session.request, session.reading = "", False
        session.checks += 1
        session.checked_at = time.time()
        session.seconds = event.get("live_seconds")
        session.since = event.get("live_since")
        session.unsettled = int(event.get("unsettled_files", 0))
        session.listed = bool(event.get("live_listed"))
        if session.listed:
            session.listed_at = time.monotonic()
        self._live_observed(session, event)
        if session.listed and explorer._unchecked_path == session.path:
            # Listed: no shot is missing and none is new, so the shown data is the folder's.
            explorer._unchecked_path = None
        if session.on and not session.error:
            self._live_next()

    @staticmethod
    def _live_observed(session: LiveSession, event: dict[str, Any]) -> None:
        """What a check found besides shots: the folder's identity and its marker's folder (the first
        listing's are the session's), the new files it saw but didn't read, and the folder's mtime
        as of its listing. (A save's load reports none of these.)"""
        if "live_seen" in event:
            session.seen = [list(entry) for entry in event["live_seen"]]
            session.seen_names = [str(name) for name in event.get("live_seen_names") or ()]
        if "live_listed_mtime" in event:
            session.listed_mtime = event["live_listed_mtime"]
        if not session.identity and event.get("live_identity"):
            session.identity = str(event["live_identity"])
            root = event.get("live_identity_root")
            session.identity_root = str(root) if isinstance(root, str) else None

    def _live_save_ended(self, path: str, outcome: str) -> None:
        """A save of the folder ended (``FolderCache.saveEnded``, through the tab)."""
        explorer = self.explorer
        session = self._live_sessions.get(path)
        if (explorer.closed or session is None or not session.saving or session.request == "save"
                or explorer.model.cache.disk_cache_saving(path)):
            return
        if outcome == "failed":
            session.unsaved |= session.saving
            session.note = explorer.model.cache.cache_status(path).error or "Cache save failed"
            # Tried again once N more new shots have come.
            session.threshold = len(session.unsaved) + explorer.model.cache.live_autosave_shots
        else:
            session.note = "Cache update waiting for your answer" if outcome == "pending" else ""
            session.threshold = 0
            if outcome in ("saved", "superseded"):
                session.saved_at = time.time()
        session.saving = set()
        self._live_forget(session)
        explorer._update_activity()

    # Auto-convert (TXY converter stage 4, Q6.8): shown once Live is on; reset each session (Q9.6).

    def auto_converting(self, path: str | None = None) -> bool:
        """Whether Live converts new raw shots of ``path`` (the watched folder by default)."""
        session = self.live
        return session is not None and session.convert is not None and path in (None, session.path)

    def set_auto_convert(self, on: bool) -> None:
        """Turn auto-convert on or off for the folder Live watches (remembered for this session,
        so turning Live on there again converts again). Off stops new conversions and cancels a
        running one (its shots written so far stay: each is written whole)."""
        session = self.live
        if session is None or on == (session.convert is not None):
            return
        cache = self.explorer.model.cache
        if on:
            cache.auto_convert.add(session.path)
            self._convert_on(session)
            if not session.request and not session.error:
                self._live_next(0.0)  # The first conversion only records: start it now.
        else:
            cache.auto_convert.discard(session.path)
            self._convert_off(session)
        logging.info("Live auto-convert %s: %s", "on" if on else "off", session.path)
        self._live_changed()

    def fill_convert_menu(self, menu: QMenu) -> None:
        """The Auto-convert button's menu: auto-convert, and the folder's converter choices."""
        menu.clear()
        menu.setToolTipsVisible(True)
        session = self.live
        if session is None:
            return
        cache, path = self.explorer.model.cache, session.path
        name = os.path.basename(path.rstrip(os.sep)) or path
        action = menu.addAction("Auto-convert new raw shots")
        assert action is not None
        action.setCheckable(True)
        action.setChecked(session.convert is not None)
        action.setToolTip("Convert each raw file (d<N>.txt) to HeLab's TXY once it is written; the new shots "
                          "then join the data. Off at each start, except in folders set to start at launch.")
        action.toggled.connect(self.set_auto_convert)
        action = menu.addAction("Write TXY beside the raw files in this folder…")
        assert action is not None
        action.setCheckable(True)
        action.setChecked(cache.write_beside(path))
        why = ("the disk cache is off for this session" if not folder_cache.store_options() else
               "no .helab-root found here or above (the choice is saved with the folder's data root)"
               if cache.no_root(path) is not None else
               "its .helab-root isn't confirmed yet (Review…)" if cache.pending_root(path) is not None else "")
        action.setEnabled(not why)
        action.setToolTip(f"Not available: {why}" if why else (
            f"HeLab's TXY (d_txy_helab_<tag>_<N>.txt) go into {name} itself, beside the raw files, instead of HeLab's "
            "own folder; HeLab writes nothing else there and never replaces a file. Saved for this folder."))
        action.toggled.connect(lambda on: self._set_write_beside(path, on))
        action = menu.addAction("Start Live and auto-convert here when HeLab launches")
        assert action is not None
        action.setCheckable(True)
        action.setChecked(live_launch.starts_at_launch(path))
        other = live_launch.launch_folder()
        action.setToolTip("At launch HeLab opens this folder alone, in one tab, and starts Live with auto-convert. "
                          "One folder only: Live runs in one folder."
                          + (f" Replaces the folder set now: {other}" if other and other != FolderCache.key(path)
                             else ""))
        action.toggled.connect(lambda on: self._set_starts_at_launch(path, on))
        threshold = low_hits_threshold()
        action = menu.addAction(f"Notify when a converted shot has fewer than {threshold:,} hits…" if threshold
                                else "Notify about low-count shots: off…")
        assert action is not None
        action.setToolTip("A system notification, once per shot (0: never)")
        action.triggered.connect(self._ask_low_hits)

    def _set_write_beside(self, path: str, on: bool) -> None:
        explorer = self.explorer
        name = os.path.basename(path.rstrip(os.sep)) or path
        if on and QMessageBox.question(
                explorer, "Write TXY beside the raw files?",
                f"HeLab will write its converted TXY files (d_txy_helab_<tag>_<N>.txt) into {name} itself, beside the raw "
                "files, for every shot it converts from now on. It writes nothing else there and never replaces "
                f"or removes a file there (apart from its own unfinished temporary TXY).\n\n{path}") \
                != QMessageBox.StandardButton.Yes:
            self._live_changed()
            return
        explorer.model.cache.set_write_beside(path, on)

    def _set_starts_at_launch(self, path: str, on: bool) -> None:
        live_launch.set_starts_at_launch(path, on)
        if on:
            self.explorer.model.cache.auto_convert.add(path)
            if self.live is not None and self.live.path == path and self.live.convert is None:
                self.set_auto_convert(True)
        self._live_changed()

    def _ask_low_hits(self) -> None:
        value, accepted = QInputDialog.getInt(
            self.explorer, "Low-count notifications",
            "Notify when a converted shot has fewer hits than (0: never):", low_hits_threshold(), 0, 10**9, 100)
        if accepted:
            app_settings().setValue(CONVERT_LOW_HITS_SETTING, value)
            self._live_changed()

    def _convert_on(self, session: LiveSession) -> None:
        session.convert = AutoConvert(time.time())

    def _convert_off(self, session: LiveSession) -> None:
        convert, session.convert = session.convert, None
        if convert is not None and convert.request:
            self.explorer.model.cache.cancel(self.explorer.live_owner, "convert", session.path)

    def _convert_tick(self, session: LiveSession) -> None:
        """Ask for the folder's next conversion with Live's check: one at a time, at least a check
        interval after the last one ended (a raw file is taken as finished only when two
        conversions found it unchanged, so they must be that far apart)."""
        convert = session.convert
        cache = self.explorer.model.cache
        if (convert is None or convert.request or convert.error
                or time.monotonic() - convert.ended_at < cache.live_interval):
            return
        if not cache.convert(self.explorer.live_owner, session.path):
            convert.error = "the conversion couldn't be queued"
            logging.warning("Live auto-convert stopped for %s: %s", session.path, convert.error)
            return
        convert.request, convert.todo, convert.done = True, 0, 0

    def _convert_event(self, session: LiveSession, event: dict[str, Any]) -> None:
        """A conversion's events (``io_ops.events``: the converter's kinds)."""
        convert = session.convert
        kind = event["kind"]
        if convert is None or not convert.request:
            return  # Auto-convert was turned off (or Live): its cancellation, or a late event.
        if kind == "convert_plan":
            convert.todo, convert.done = int(event["todo"]), 0
            convert.output, convert.fallback = str(event["output"]), str(event.get("fallback") or "")
            convert.txy_folder = str(event["txy_folder"])
            convert.profile, convert.backend = dict(event["profile"]), str(event["backend"])
            cache = self.explorer.model.cache
            if event.get("key") and session.path not in cache.convert_prefs:
                # Whether its TXY go beside the raw files (Q9.7; saved with its data root): asked once
                # a conversion found the root (the first only records; the helper checks the store too).
                cache.read_convert_prefs(session.path)
        elif kind == "convert_progress":
            convert.done, convert.todo = int(event["done"]), int(event["todo"])
        elif kind == "shot_converted":
            self._converted(session, convert, event)
        elif kind == "shot_waiting":
            convert.waiting[str(event["raw_name"])] = (str(event["reason"]), str(event.get("message") or ""))
        elif kind == "shot_unconvertible":
            name = str(event["raw_name"])
            convert.unconvertible[name] = str(event.get("message") or event["reason"])
            logging.warning("Live auto-convert: %s in %s can't be converted: %s", name, session.path,
                            convert.unconvertible[name])
            if event["reason"] == DAMAGED_REASON:
                convert.damaged.add(name)
                self._notify_damaged(session, event)
        elif kind == "shot_kept":
            convert.kept[int(event["shot"])] = str(event["reason"])
        elif kind == "partial_removed":
            logging.info("Live auto-convert removed a leftover temporary TXY: %s", event["file"])
        elif kind == "convert_summary":
            convert.waiting = {str(entry[0]): (str(entry[3]), str(entry[4])) if len(entry) >= 5 else ("", "")
                               for entry in event["waiting"]}
            # (A file skipped as unconvertible isn't sent again: its reason is the folder's, kept by FolderCache.)
            reasons = self.explorer.model.cache.convert_reasons.get(session.path, {})
            convert.unconvertible = {str(entry[0]): convert.unconvertible.get(str(entry[0])) or reasons.get(
                str(entry[0]), "can't be converted") for entry in event["unconvertible"]}
            convert.damaged = {name for name, why in convert.unconvertible.items()
                               if name in convert.damaged or why.startswith(DAMAGED_TEXT)}
        elif kind in ("done", "error", "cancelled", "offline"):
            if kind == "offline":
                convert.error = "not while working offline"
            elif kind == "error":
                convert.error = str(event.get("message") or "the conversion failed").removesuffix(" — Retry")
            if kind != "offline":
                convert.request = False
                convert.ended_at = time.monotonic()
                convert.passes += kind == "done"
                convert.todo = convert.done = 0
            if convert.error and kind != "cancelled":
                logging.warning("Live auto-convert stopped for %s: %s", session.path, convert.error)
        else:
            return
        self.explorer._update_activity()
        self.explorer.loadStateChanged.emit()

    @staticmethod
    def _notify_damaged(session: LiveSession, event: dict[str, Any]) -> None:
        """A damaged raw file (Q18.5): a system notification, once per file (its name, size and mtime)."""
        name = os.path.basename(session.path.rstrip(os.sep)) or session.path
        raw_name = str(event["raw_name"])
        message = str(event.get("message") or "").removeprefix(DAMAGED_TEXT)
        events.notify(events.DAMAGED_RAW, f"{raw_name} in {name} is damaged: {message}. No TXY is made for it; "
                      "later shots go on.", title="HeLab: damaged raw file",
                      key=(events.DAMAGED_RAW, session.path, raw_name, int(event["raw_size"]),
                           int(event["raw_mtime_ns"])),
                      desktop=True, path=session.path, shot=int(event["shot"]), source="convert")

    def _converted(self, session: LiveSession, convert: AutoConvert, event: dict[str, Any]) -> None:
        """A shot converted: its TXY reaches the data through Live's next check (now, or as soon
        as the running one ends); a low-count one notifies (Q9.4), once per shot."""
        shot, hits = int(event["shot"]), int(event["hits"])
        convert.converted += 1
        convert.last_shot, convert.last_hits, convert.last_at = shot, hits, time.time()
        convert.waiting.pop(str(event["raw_name"]), None)
        threshold = low_hits_threshold()
        if threshold and hits < threshold:
            name = os.path.basename(session.path.rstrip(os.sep)) or session.path
            notified = events.notify(
                events.LOW_COUNTS, f"Shot {shot} of {name}: {hits:,} hits (fewer than {threshold:,}), converted by HeLab",
                title="HeLab: low counts", key=("convert_low_hits", session.path, shot, str(event["raw_sha256"])),
                desktop=True, path=session.path, shot=shot, count=hits, threshold=threshold, source="convert")
            convert.low += notified is not None
        if session.on and not session.error:
            if session.request:
                session.check_soon = True
            else:
                self._live_next(0.0)

    def convert_line(self, session: LiveSession) -> tuple[str, list[str], bool]:
        """Auto-convert's part of the Live line, its tooltip lines, and whether it stopped on an
        error ("" and no lines while off)."""
        convert = session.convert
        if convert is None:
            return "", [], False
        if convert.error:
            text = f"auto-convert stopped: {convert.error}"
        else:
            parts = []
            if convert.request and convert.todo > convert.done:
                parts.append(f"converting {convert.todo - convert.done:,}")
            if convert.converted:
                parts.append(f"{convert.converted:,} converted (last: shot {convert.last_shot})")
            if stuck := convert.stuck():
                parts.append(f"{len(stuck):,} waiting")
            if convert.damaged:
                parts.append(f"{len(convert.damaged):,} damaged")
            if others := len(convert.unconvertible) - len(convert.damaged):
                parts.append(f"{others:,} unconvertible")
            text = "auto-convert " + (", ".join(parts) if parts else "on")
        started = datetime.fromtimestamp(convert.started_at).astimezone()
        lines = [f"Auto-convert on since {started:%H:%M:%S} (this session): each check also converts the folder's "
                 "raw files once written (settled, unchanged at two checks, ending in a newline)"]
        if convert.output:
            where = CONVERT_OUTPUTS.get(convert.output, convert.output)
            lines.append(f"TXY go to {where}" + (f" ({convert.fallback})" if convert.fallback else "")
                         + (f": {convert.txy_folder}" if convert.output != "beside" else ""))
        if convert.profile:
            profile = convert.profile
            lines.append(f"Profile {profile.get('name')} v{profile.get('version')}"
                         + ("" if profile.get("calibrated") else " (uncalibrated)") + f", backend {convert.backend}")
        threshold = low_hits_threshold()
        lines.append(f"Converted: {convert.converted:,}" + (
            f"; last: shot {convert.last_shot}, {convert.last_hits:,} hits at "
            f"{datetime.fromtimestamp(convert.last_at).astimezone():%H:%M:%S}" if convert.last_at is not None else "")
            + (f"; notified below {threshold:,} hits: {convert.low:,}" if threshold else "; low-count notifications off"))
        settling = len(convert.waiting) - len(convert.stuck())
        if settling:
            lines.append(f"Being written: {plural(settling, 'raw file')} (converted once written)")
        for title, entries in (("Waiting", [f"{name}: {message or reason}" for name, (reason, message)
                                            in sorted(convert.stuck().items())]),
                               ("Damaged (unchanged for 20 s and still failing the format checks; no TXY, "
                                "skipped while unchanged)",
                                [f"{name}: {why.removeprefix(DAMAGED_TEXT)}" for name, why
                                 in sorted(convert.unconvertible.items()) if name in convert.damaged]),
                               ("Can't be converted", [f"{name}: {why}" for name, why
                                                       in sorted(convert.unconvertible.items())
                                                       if name not in convert.damaged]),
                               ("Kept beside (not HeLab's to replace)", [f"shot {shot}: {why}" for shot, why
                                                                         in sorted(convert.kept.items())])):
            if entries:
                lines.append(f"{title} ({len(entries):,}): " + "; ".join(entries[:8])
                             + (" …" if len(entries) > 8 else ""))
        if convert.stuck():
            lines.append("A waiting file is checked again only when it changes.")
        if convert.error:
            lines.append(f"Auto-convert stopped: {convert.error}. Retry converts again.")
        return text, lines, bool(convert.error)

    def live_line(self, session: LiveSession) -> tuple[str, str, bool]:
        """The summary's third line for a folder Live watches or saves: text, tooltip, amber."""
        now = time.time()
        if session.on and session.error:
            parts = [f"Live stopped: {session.error}"]
        elif session.on:
            parts = ["Live · " + ("reading new shots…" if session.request == "check" and session.reading else
                                  "checking…" if session.request == "check" else
                                  "saving…" if session.request == "save" else
                                  f"checked {relative_age(now - session.checked_at)}" if session.checked_at
                                  else "starting…"),
                     plural(session.new, "new shot") if session.shots else "waiting for the first shot"]
            if session.unsettled:
                parts.append(f"{session.unsettled:,} still being written")
            if not session.request:
                parts.append(f"next check in {max(0, math.ceil(session.next_at - time.monotonic()))} s")
        else:
            parts = ["Live updates off"]
        convert_text, convert_lines, convert_stopped = self.convert_line(session)
        if convert_text and session.on and not session.error:
            parts.append(convert_text)
        if reread := self.live_reread_note(session.path):
            parts.append(reread)
        blocked = self._live_save_blocked(session)
        if session.saving:
            parts.append(f"saving {plural(len(session.saving), 'shot')}")
        elif session.unsaved:
            parts.append(f"{len(session.unsaved):,} not cached" + (f" ({blocked})" if blocked else " yet"))
        started = datetime.fromtimestamp(session.started_at).astimezone()
        cache = self.explorer.model.cache
        lines = [f"Live {'on' if session.on else 'off'}: {session.path}",
                 f"Watching since {started:%Y-%m-%d %H:%M:%S}",
                 f"Checks: {session.checks:,}, {cache.live_interval:g} s after each one ends (Settings → General)"]
        if session.seconds is not None:
            lines.append(f"The last check took {session.seconds * 1000:,.0f} ms"
                         + (" (listed the folder)" if session.listed else " (one folder stat: nothing changed)"))
        lines.append(f"New shots: {session.new:,}" + (f"; {session.unsettled:,} still being written, read once "
                                                       "written" if session.unsettled else ""))
        lines.append(f"Not yet in the disk cache: {len(session.unsaved) + len(session.saving):,}; saved every "
                     f"{cache.live_autosave_shots:,} new shots (Settings → Cache) and when Live stops")
        if blocked:
            lines.append(f"Not saved: {LIVE_BLOCKED.get(blocked, blocked)}")
        if session.saved_at is not None:
            lines.append(f"Last saved: {datetime.fromtimestamp(session.saved_at).astimezone():%H:%M:%S}")
        if reread:
            ago = relative_age(time.monotonic() - self._reread_notes[session.path][1])
            lines.append(f"{reread} {ago} (the log names its old and new size and mtime). A shot Live read in the last "
                         f"{self.LIVE_REREAD_SECONDS / 60:g} minutes that changes is read again; an older one "
                         "that changes stops Live. The converter writing to a temporary name and renaming it "
                         "would avoid this.")
        if session.note:
            lines.append(session.note)
        if session.error:
            lines.append(f"Stopped: {session.error}. Retry checks again; turning Live off saves the new shots.")
        lines.extend(convert_lines)
        return " · ".join(parts), "\n".join(lines), bool(session.on and (session.error or convert_stopped))
