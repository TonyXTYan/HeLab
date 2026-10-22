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
  disk cache couldn't be read).

Either way the answer carries the save guard taken now, as the run starts; the save of its
completed result (packed on the worker thread, ``AnalysisResult.packed``) checks it, so a
Clear cached analysis meanwhile can't be undone. A script that keeps something for the plot
between runs (``cache_holds_state``) isn't looked up (the run starts at once; the answer only
gives the guard), and saves only a result ``cache_result`` says a fresh plot would give.

A plot reopened at start (the Presets Reopen floor) finds its saved result the same way: its
first run goes through ``AnalysisInstance._submit``, which asks here."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional
from uuid import uuid4

from PyQt6.QtCore import QObject, pyqtSlot

from helab.analysis import result_cache
from helab.analysis.dataset_view import DatasetView
from helab.analysis.results import DISK_CACHED, AnalysisContext, AnalysisResult
from helab.utils.io_service import IORequest
from helab.utils.number_format import byte_size

if TYPE_CHECKING:
    from helab.scripts.base import DatasetAnalysis
    from helab.utils.folder_cache import FolderCache


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


class CachedRuns(QObject):
    """The saved results of one plot. ``found(context, result)`` shows a match (exact: the run is
    skipped; else it runs meanwhile), ``run(context)`` queues the run, ``saved(result)`` and
    ``note(text)`` report a save or a problem; all on the GUI thread."""

    def __init__(self, cache: FolderCache, script: DatasetAnalysis, action: str, name: str, *,
                 found: Callable[[AnalysisContext, AnalysisResult], None],
                 run: Callable[[AnalysisContext], None],
                 saved: Callable[[AnalysisResult, int], None],
                 note: Callable[[str], None], closed: Callable[[], bool],
                 removed: Callable[[Optional[List[str]]], None] = lambda paths: None) -> None:
        super().__init__()
        self.cache, self.script, self.action, self.name = cache, script, action, name
        self._found, self._run, self._saved, self._note, self._closed = found, run, saved, note, closed
        self._removed = removed
        self._lookups: Dict[str, Lookup] = {}  # By the run's job id.
        self._saves: Dict[str, AnalysisResult] = {}  # By the save's owner.
        self._connected = False

    def supported(self) -> bool:
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
            self._lookups.pop(result.job_id, None)
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
        try:
            record = {"key": entry.key, "result": result_cache.record_of(result)}
        except Exception as error:
            logging.exception("%s: its result's record can't be saved", self.name)
            self._note(f"not saved in the disk cache: {error}")
            return
        owner = f"result-save:{uuid4().hex}"
        self._connect()
        if self.cache.save_result(owner, entry.view.identity.source_path, packed, lookup=entry.lookup,
                                  family=entry.family, record=record, analysis_id=result.analysis.analysis_id,
                                  action=result.action, computed_at=result.finished_at, guard=entry.guard):
            self._saves[owner] = replace(result, packed=None)

    def _connect(self) -> None:
        if not self._connected:
            self.cache.resultReady.connect(self._event)
            self.cache.cacheRemoved.connect(self._cache_removed)
            self._connected = True

    @pyqtSlot(object, object)
    def _cache_removed(self, paths: Any, kinds: Any) -> None:
        """Saved results were removed (Clear cached analysis): the plot's record no longer says its
        result is in the disk cache, for those folders (None: every folder)."""
        if isinstance(kinds, list) and "results" in kinds and not self._closed():
            self._removed(None if paths is None else [str(path) for path in paths])

    def disconnect_all(self) -> None:
        """The plot closed: its lookups' answers are dropped (saves already asked for go on)."""
        for job_id in list(self._lookups):
            self.forget(job_id)
        if self._connected and not self._saves:
            for signal, slot in ((self.cache.resultReady, self._event), (self.cache.cacheRemoved, self._cache_removed)):
                try:
                    signal.disconnect(slot)
                except TypeError:
                    pass
            self._connected = False

    @pyqtSlot(object, object)
    def _event(self, request: IORequest, event: Dict[str, Any]) -> None:
        if self._closed() and not self._saves and not any(not item.answered for item in self._lookups.values()):
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
        self._found(context, saved)
        return exact

    def _save_event(self, owner: str, event: Dict[str, Any]) -> None:
        kind = event.get("kind")
        result = self._saves.get(owner)
        if result is None or kind not in ("result_saved", "result_not_saved", "error", "cancelled"):
            return
        del self._saves[owner]
        if kind == "result_saved":
            size = int(event.get("bytes") or 0)
            if size > result_cache.LARGE_RESULT_BYTES:
                logging.warning("Saved %s's result (%s) in the disk cache: %s", self.name,
                                result.input.identity.source_path, byte_size(size))
            if not self._closed():
                self._saved(replace(result, policy=DISK_CACHED), size)
        elif kind == "result_not_saved" and event.get("reason") == "over_budget":
            self._note("not saved in the disk cache: it doesn't fit the disk budget (Settings → Cache)")
        elif kind == "result_not_saved":
            logging.info("%s: result not saved in the disk cache (%s)", self.name, event.get("message"))
        else:
            logging.warning("%s: result not saved in the disk cache: %s", self.name, event.get("message"))
            self._note(f"not saved in the disk cache: {event.get('message') or 'the save failed'}")
        if self._closed() and not self._saves:
            self.disconnect_all()
