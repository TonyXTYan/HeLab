"""A plot's saved results (result caching R2): ``CachedRuns`` looks a run up in the disk cache
before it computes, hands back a match, and saves the run's result once it completes.

Only one-off runs the user asked for (Rerun, a plot's first run, a reload; never Live's reruns:
Rule 7) of a script that supports it (``DatasetAnalysis.cache_supported``) on a folder with a
disk cache. The lookup is a local-lane helper (``FolderCache.find_result``): never the folder,
never waiting on its I/O. Its answer:

- an exact match: the plot shows it (from disk cache, computed <date>) and the run is skipped;
- an outdated one (same plot and settings, another script version, environment, data or
  constants): it shows at once, marked, while the run goes on and replaces it;
- none, or an error (never taken as "nothing saved": the run goes on, and the plot says the
  disk cache couldn't be read);
- refused because the folder's local volume isn't verified yet this session (``unverified``): not
  a miss. The lookup is asked again once verification has run (``volumesVerified``, once, as a
  cached read is), the run waiting meanwhile; a save refused so is asked again the same way, with
  its guard. Tony (2026-10-26), two waits: after ``VERIFY_WAIT`` the plot computes, and the status
  bar and the plot's status line say ``VERIFY_NOTE``; its save waits on, up to
  ``SAVE_VERIFY_WAIT`` from the refusal (verification then asks the lookup again for the guard
  alone, and the result is saved; the note clears). A Clear cached analysis of the folder after
  the run started and before that guard voids the save, as the guard taken at the start would
  have. Without verification by then, or refused again after it, the plot's amber line says
  ``UNCHECKED_NOTE`` and one line is logged; no window.

Either way the answer carries the save guard taken now, as the run starts; the save of its
completed result (packed on the worker thread, ``AnalysisResult.packed``) checks it, so a
Clear cached analysis meanwhile can't be undone. A script that keeps something for the plot
between runs (``cache_holds_state``) isn't looked up (the run starts at once; the answer only
gives the guard), and saves only a result ``cache_result`` says a fresh plot would give.

A plot reopened at start (the Presets Reopen floor) finds its saved result the same way: its
first run goes through ``AnalysisInstance._submit``, which asks here."""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional
from uuid import uuid4

from PyQt6.QtCore import QObject, QTimer, pyqtSlot

from helab.analysis import result_cache
from helab.analysis.dataset_view import DatasetView
from helab.analysis.results import DISK_CACHED, AnalysisContext, AnalysisResult
from helab.utils.io_service import IORequest
from helab.utils.number_format import byte_size
from helab.utils.settings_defaults import RESULT_REUSE_SETTING, read_setting
from helab.utils.settings_store import app_settings

if TYPE_CHECKING:
    from PyQt6.QtCore import QSettings

    from helab.scripts.base import DatasetAnalysis
    from helab.utils.folder_cache import FolderCache


# The plot's status while its result waits for the user's answer (replaced once answered).
PENDING_NOTE = "not saved yet: the disk cache is full (Make room or Discard)"
# How long a lookup its folder's unverified volume refused waits for this session's volume
# verification before the plot computes (Tony, 2026-10-26), and how long, from the refusal, its
# save (or a refused save) waits on for it before the result is left unsaved.
VERIFY_WAIT = 15.0
SAVE_VERIFY_WAIT = 120.0
# The status bar's and the plot's status line's note while a computed result waits for the
# drive's check, and the plot's amber line once it stops waiting (Tony's wording).
VERIFY_NOTE = "Disk cache: still checking this drive; this result isn't saved yet."
UNCHECKED_NOTE = "not saved: the drive couldn't be checked"


def reuse_on(settings: Optional[QSettings] = None) -> bool:
    """Settings → Cache › Reuse saved analysis results (on by default): off, no plot looks its runs
    up or saves them."""
    return bool(read_setting(settings if settings is not None else app_settings(), RESULT_REUSE_SETTING, typed=True))


@dataclass
class Lookup:
    """One run's lookup and, once it completes, its save."""
    context: AnalysisContext
    view: DatasetView
    key: Dict[str, Any]
    lookup: str
    family: str
    wait: bool  # The run waits for the answer (False: the script holds state, only the guard is wanted).
    owner: str = field(default_factory=lambda: f"result-find:{uuid4().hex}")
    guard: Any = None
    answered: bool = False
    # A completed result waiting for the guard to arrive, to be saved then.
    waiting: Optional[AnalysisResult] = None
    # The ``unverified`` error it waits to be asked again after (volume verification), whether it
    # was asked again already (only once), the verifications seen when it was last asked, when it
    # was first refused (monotonic; 0: never), whether ``VERIFY_WAIT`` passed (the run started
    # then) and whether a Clear cached analysis came after that (its late guard saves nothing).
    unverified: Optional[Dict[str, Any]] = None
    retried: bool = False
    verified: int = 0
    refused_at: float = 0.0
    late: bool = False
    fenced: bool = False


@dataclass
class Save:
    """A save asked for: the run's result (without its packed data) and what it was asked with."""
    result: AnalysisResult
    path: str
    packed: bytes
    params: Dict[str, Any]
    unverified: Optional[Dict[str, Any]] = None  # As ``Lookup``'s.
    retried: bool = False
    verified: int = 0
    refused_at: float = 0.0
    late: bool = False


class CachedRuns(QObject):
    """The saved results of one plot. ``found(context, result)`` shows a match (exact: the run is
    skipped; else it runs meanwhile), ``run(context)`` queues the run, ``saved(result)`` and
    ``note(text)`` report a save or a problem (``notice(text)`` in the status bar, ``warn(text)``
    in the plot's amber line, "" clears it); all on the GUI thread."""

    def __init__(self, cache: FolderCache, script: DatasetAnalysis, action: str, name: str, *,
                 found: Callable[[AnalysisContext, AnalysisResult], None],
                 run: Callable[[AnalysisContext], None],
                 saved: Callable[[AnalysisResult, int], None],
                 note: Callable[[str], None], closed: Callable[[], bool],
                 removed: Callable[[Optional[List[str]]], None] = lambda paths: None,
                 evicted: Callable[[str], None] = lambda job_id: None,
                 notice: Callable[[str], None] = lambda text: None,
                 warn: Callable[[str], None] = lambda text: None) -> None:
        super().__init__()
        self.cache, self.script, self.action, self.name = cache, script, action, name
        self._found, self._run, self._saved, self._note, self._closed = found, run, saved, note, closed
        self._removed, self._evicted, self._notice, self._warn = removed, evicted, notice, warn
        # The saved result of each of the plot's runs it found or saved: job id → its row's result_id.
        self._keys: Dict[str, str] = {}
        self._lookups: Dict[str, Lookup] = {}  # By the run's job id.
        self._saves: Dict[str, Save] = {}  # By the save's owner.
        # Saves refused for their folder's unverified volume, to ask again after verification.
        self._unverified_saves: List[Save] = []
        self._verified = 0  # Volume verifications seen (``volumesVerified``) since connecting.
        self._verify_timer = QTimer(self)
        self._verify_timer.setSingleShot(True)
        self._verify_timer.timeout.connect(self._verification_due)
        # Results that didn't fit the disk budget, waiting for Make room or Discard, by pending_id.
        self._waiting: Dict[str, tuple[AnalysisResult, int]] = {}
        self._connected = False

    def supported(self) -> bool:
        """Whether the plot's runs are looked up and saved: its script supports it and reuse is on."""
        if not reuse_on():
            return False
        try:
            return bool(self.script.cache_supported(self.action))
        except Exception:
            logging.exception("cache_supported of %s failed: not cached", self.name)
            return False

    def off_reason(self, view: DatasetView) -> str:
        """Why runs on ``view`` keep their results in RAM only, as far as known now ("" if not)."""
        return self.cache.result_cache_off(view.identity.source_path)

    def start(self, context: AnalysisContext) -> bool:
        """Look ``context``'s run up; True if the run waits for the answer (``run`` queues it then),
        False if the caller queues it now (nothing to look up, or only the guard is wanted)."""
        try:
            holds = bool(self.script.cache_holds_state(self.action, context.owner))
            key = result_cache.lookup_key(context)
            family = result_cache.digest(result_cache.family_key(context))
        except Exception:
            logging.exception("Disk cache key of %s: not looked up", self.name)
            return False
        entry = Lookup(context, context.view, key, result_cache.digest(key), family, wait=not holds)
        self._connect()
        entry.verified = self._verified
        if not self.cache.find_result(entry.owner, context.view.identity.source_path, entry.lookup,
                                      "" if holds else family):
            return False
        self._lookups[context.job_id] = entry
        return entry.wait

    def forget(self, job_id: str) -> None:
        """The run's plot moved on (another run, closed): its lookup's answer is dropped."""
        entry = self._lookups.pop(job_id, None)
        if entry is not None and not entry.answered:
            self.cache.service.cancel(entry.owner)

    def finished(self, result: AnalysisResult) -> None:
        """A run ended: save its completed, packed result once its lookup's guard is here."""
        entry = self._lookups.get(result.job_id)
        if entry is None:
            return
        if result.state != "completed" or result.packed is None:
            if result.packing_error:
                self._note(f"not saved in the disk cache: {result.packing_error}")
            self.forget(result.job_id)  # (Its lookup's answer, if still to come, is for nobody.)
            return
        if not entry.answered:
            entry.waiting = result  # Saved when the guard arrives.
            return
        self._save(entry, result)

    def _save(self, entry: Lookup, result: AnalysisResult) -> None:
        self._lookups.pop(result.job_id, None)
        packed = result.packed
        if entry.guard is None or packed is None:
            return  # (No guard: the lookup failed or the store is a newer HeLab's; never saved blind.)
        if entry.fenced:
            logging.info("%s: result not saved: its cached analysis was cleared after the run started", self.name)
            return
        try:
            record = {"key": entry.key, "result": result_cache.record_of(result)}
        except Exception as error:
            logging.exception("%s: its result's record can't be saved", self.name)
            self._note(f"not saved in the disk cache: {error}")
            return
        self._submit_save(Save(replace(result, packed=None), entry.view.identity.source_path, packed,
                               {"lookup": entry.lookup, "family": entry.family, "record": record,
                                "analysis_id": result.analysis.analysis_id, "action": result.action,
                                "computed_at": result.finished_at, "guard": entry.guard, "label": self.name}))

    def _submit_save(self, save: Save) -> bool:
        owner = f"result-save:{uuid4().hex}"
        self._connect()
        save.verified = self._verified
        if not self.cache.save_result(owner, save.path, save.packed, **save.params):
            return False
        self._saves[owner] = save
        return True

    def _saving(self) -> bool:
        return bool(self._saves or self._unverified_saves)

    def _connect(self) -> None:
        if not self._connected:
            self.cache.resultReady.connect(self._event)
            self.cache.cacheRemoved.connect(self._cache_removed)
            self.cache.resultPendingAnswered.connect(self._pending_answered)
            self.cache.resultsEvicted.connect(self._results_evicted)
            self.cache.volumesVerified.connect(self._volumes_verified)
            self._connected = True

    def _wait_for_verification(self, item: Lookup | Save) -> None:
        """``item`` was refused for its volume: asked again now if a verification ran since it was
        asked, else once the next one has (``_verification_due`` keeps the time limits)."""
        if not item.refused_at:
            item.refused_at = time.monotonic()
        if item.verified < self._verified:
            self._ask_again()
        self._schedule()

    def _unverified(self) -> List[Lookup | Save]:
        return [*(item for item in self._lookups.values() if item.unverified is not None), *self._unverified_saves]

    def _schedule(self) -> None:
        """One timer for the earliest time limit of what waits for verification."""
        due = [item.refused_at + (SAVE_VERIFY_WAIT if item.late else VERIFY_WAIT) for item in self._unverified()]
        if not due:
            self._verify_timer.stop()
            return
        self._verify_timer.start(max(0, math.ceil((min(due) - time.monotonic()) * 1000)))

    @pyqtSlot()
    def _volumes_verified(self) -> None:
        """This session's volume verification ran: the lookups and saves it refused are asked again."""
        self._verified += 1
        self._ask_again()
        self._schedule()

    def _ask_again(self) -> None:
        """Ask again what its volume refused before the latest verification (once each): a lookup
        whose run has started (``late``, or a script holding state) for the guard alone."""
        for entry in [item for item in self._lookups.values()
                      if item.unverified is not None and item.verified < self._verified]:
            refused, entry.unverified = entry.unverified, None
            entry.owner, entry.verified = f"result-find:{uuid4().hex}", self._verified
            if not self.cache.find_result(entry.owner, entry.view.identity.source_path, entry.lookup,
                                          entry.family if entry.wait else ""):
                self._answer(entry, "error", refused or {})
        saves = [save for save in self._unverified_saves if save.verified < self._verified]
        self._unverified_saves = [save for save in self._unverified_saves if save not in saves]
        for save in saves:
            refused, save.unverified = save.unverified, None
            if not self._submit_save(save):
                self._save_ended(save, "error", refused or {})
        if self._closed() and not self._saving():
            self.disconnect_all()

    @pyqtSlot()
    def _verification_due(self) -> None:
        """A time limit passed: at ``VERIFY_WAIT`` a waiting run computes (its save waits on, said
        in the status bar and on the plot); at ``SAVE_VERIFY_WAIT`` the result is left unsaved."""
        now = time.monotonic()
        said = False
        for item in self._unverified():
            if item.late and now >= item.refused_at + SAVE_VERIFY_WAIT:
                self._unchecked(item)
            elif not item.late and now >= item.refused_at + VERIFY_WAIT:
                item.late = True
                if isinstance(item, Lookup) and item.wait:
                    item.wait = False  # It computes now; asked again later for the guard alone.
                    self._run(item.context)
                said = True
        if said and not self._closed():
            self._notice(VERIFY_NOTE)
            self._note(VERIFY_NOTE)
        if self._closed() and not self._saving():
            self.disconnect_all()
        self._schedule()

    def _unchecked(self, item: Lookup | Save) -> None:
        """The drive couldn't be checked in time (or verification refused it again): its result
        isn't saved. The plot's amber line says so; one line is logged."""
        if isinstance(item, Lookup):
            item.unverified, item.answered, item.guard, item.waiting = None, True, None, None
            self._lookups.pop(item.context.job_id, None)
            path = item.view.identity.source_path
        else:
            if item in self._unverified_saves:
                self._unverified_saves.remove(item)
            path = item.path
        logging.warning("%s: result not saved in the disk cache: %s's drive couldn't be checked (its volume "
                        "wasn't verified within %g s)", self.name, path, SAVE_VERIFY_WAIT)
        if not self._closed():
            self._note("")
            self._warn(UNCHECKED_NOTE)

    @pyqtSlot(object)
    def _results_evicted(self, ids: Any) -> None:
        """Make room removed old saved results: a run of this plot whose saved row was one of them is
        in RAM only (one whose newer copy was saved since has that copy's id: still saved)."""
        gone = {str(result_id) for result_id in ids or ()}
        for job_id, result_id in list(self._keys.items()):
            if result_id in gone:
                del self._keys[job_id]
                if not self._closed():
                    self._evicted(job_id)

    @pyqtSlot(str, bool, str)
    def _pending_answered(self, pending_id: str, saved: bool, result_id: str) -> None:
        """The user answered a result that didn't fit (Make room: saved, as row ``result_id``;
        Discard), or it expired."""
        waiting = self._waiting.pop(pending_id, None)
        if waiting is None or self._closed():
            return
        result, size = waiting
        if saved and result_id:
            self._keys[result.job_id] = result_id
        if saved:
            self._saved(replace(result, policy=DISK_CACHED), size)
        else:
            self._note("not saved in the disk cache (discarded)")

    @pyqtSlot(object, object)
    def _cache_removed(self, paths: Any, kinds: Any) -> None:
        """Saved results were removed (Clear cached analysis): the plot's record no longer says its
        result is in the disk cache, for those folders (None: every folder)."""
        if not isinstance(kinds, list) or "results" not in kinds:
            return
        for entry in self._lookups.values():
            # A run started before its guard (``late``): this removal came after the run began.
            if entry.late and not entry.answered and (
                    paths is None or self.cache.key(entry.view.identity.source_path) in paths):
                entry.fenced = True
        if not self._closed():
            self._removed(None if paths is None else [str(path) for path in paths])

    def disconnect_all(self) -> None:
        """The plot closed: its lookups' answers are dropped (saves already asked for go on)."""
        for job_id in list(self._lookups):
            self.forget(job_id)
        if self._connected and not self._saving():
            self._waiting.clear()
            self._verify_timer.stop()
            for signal, slot in ((self.cache.resultReady, self._event), (self.cache.cacheRemoved, self._cache_removed),
                                 (self.cache.resultPendingAnswered, self._pending_answered),
                                 (self.cache.resultsEvicted, self._results_evicted),
                                 (self.cache.volumesVerified, self._volumes_verified)):
                try:
                    signal.disconnect(slot)
                except TypeError:
                    pass
            self._connected = False

    @pyqtSlot(object, object)
    def _event(self, request: IORequest, event: Dict[str, Any]) -> None:
        if self._closed() and not self._saving() and not any(not item.answered for item in self._lookups.values()):
            self.disconnect_all()
            return
        if request.owner in self._saves:
            self._save_event(request.owner, event)
            return
        entry = next((item for item in self._lookups.values() if item.owner == request.owner), None)
        if entry is None or entry.answered:
            return
        kind = event.get("kind")
        if kind not in ("result_found", "result_missing", "error", "cancelled"):
            return
        if kind == "error" and event.get("unverified") and not self._closed():
            if not entry.retried:
                # The folder's volume isn't verified yet this session: not a miss, nor a failed read.
                entry.retried, entry.unverified = True, dict(event)
                self._wait_for_verification(entry)
                return
            # Refused again after verification ran: the drive couldn't be checked.
            if entry.wait:
                entry.wait = False
                self._run(entry.context)
            self._unchecked(entry)
            return
        self._answer(entry, str(kind), event)

    def _answer(self, entry: Lookup, kind: str, event: Dict[str, Any]) -> None:
        """The lookup's answer: show a match, else the run computes; a result waiting for the guard
        is saved (or not, without one)."""
        entry.answered = True
        entry.guard = event.get("guard")
        if self._closed():
            self._lookups.pop(entry.context.job_id, None)
            return
        shown = False
        if kind == "result_found" and entry.wait:
            shown = self._show(entry, event)
        elif kind == "error":
            message = str(event.get("message") or "unknown error")
            logging.warning("%s: the disk cache's saved results couldn't be read: %s", self.name, message)
            self._note(f"the disk cache couldn't be read ({message}): computing")
        if entry.wait and not shown:
            self._run(entry.context)
        if entry.waiting is not None:
            waiting, entry.waiting = entry.waiting, None
            self._save(entry, waiting)

    def _show(self, entry: Lookup, event: Dict[str, Any]) -> bool:
        """Show a saved result; True if it was an exact match (the run is skipped)."""
        unreadable = event.get("unreadable")
        record = event.get("record")
        try:
            if unreadable:
                raise ValueError(unreadable)
            if not isinstance(record, dict):
                raise ValueError("no record")
            data = self.script.cache_unpack(self.action, event.get("tree"), event.get("arrays") or {})
            exact = bool(event.get("exact"))
            outdated = () if exact else result_cache.outdated_reasons(record.get("key") or {}, entry.key)
            saved = result_cache.result_from(record.get("result"), data, outdated=outdated)
        except Exception as error:
            logging.warning("%s: a saved result couldn't be read back (%s): computing", self.name, error)
            self._note(f"a saved result couldn't be read back ({error}): computing")
            return False
        context = entry.context
        if exact:
            # The same data, script and settings: shown as this run's result, its record kept.
            saved = replace(saved, job_id=context.job_id, input=context.view.key, owner=context.owner,
                            policy=DISK_CACHED)
            self._lookups.pop(context.job_id, None)
            if event.get("result_id"):
                self._keys[context.job_id] = str(event["result_id"])
        self._found(context, saved)
        return exact

    def _save_event(self, owner: str, event: Dict[str, Any]) -> None:
        kind = event.get("kind")
        save = self._saves.get(owner)
        if save is None or kind not in ("result_saved", "result_not_saved", "result_pending", "error", "cancelled"):
            return
        del self._saves[owner]
        if kind == "error" and event.get("unverified"):
            # As a lookup's (a closed plot's too: its save goes on): asked again after verification.
            if save.retried:
                self._unchecked(save)
                return
            save.retried, save.unverified = True, dict(event)
            self._unverified_saves.append(save)
            self._wait_for_verification(save)
            return
        self._save_ended(save, str(kind), event)

    def _save_ended(self, save: Save, kind: str, event: Dict[str, Any]) -> None:
        result = save.result
        if kind == "result_pending":
            # Doesn't fit the disk budget: the disk cache asks the user (Make room or Discard).
            self._waiting[str(event.get("pending_id"))] = (result, int(event.get("bytes") or 0))
            self._note(PENDING_NOTE)
            return
        if kind == "result_saved":
            size = int(event.get("bytes") or 0)
            if event.get("result_id"):
                self._keys[result.job_id] = str(event["result_id"])
            if size > result_cache.LARGE_RESULT_BYTES:
                logging.warning("Saved %s's result (%s) in the disk cache: %s", self.name,
                                result.input.identity.source_path, byte_size(size))
            if not self._closed():
                self._saved(replace(result, policy=DISK_CACHED), size)
        elif kind == "result_not_saved" and event.get("reason") == "dropped":
            self._note("not saved in the disk cache (discarded)")
        elif kind == "result_not_saved":
            logging.info("%s: result not saved in the disk cache (%s)", self.name, event.get("message"))
        else:
            logging.warning("%s: result not saved in the disk cache: %s", self.name, event.get("message"))
            self._note(f"not saved in the disk cache: {event.get('message') or 'the save failed'}")
        if self._closed() and not self._saving():
            self.disconnect_all()
