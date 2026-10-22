"""Arrangements of plots (helab/analysis/presets.py): recording the open plots and where they sit
(``capture``), opening a recorded arrangement again in place (``open_arrangement``), a reopened
plot's wait for its folder's data (``FolderWait``), and the plots that reopen at start
(``PlotReopen``).

A reopened plot never reads its folder: it runs on the folder's data in RAM, or read back from the
local disk cache (a ``cached`` read, as a released plot's reload), and otherwise waits until a
tab's normal load brings the data ("Waiting for <folder>'s data: select it to load").
"""
from __future__ import annotations

import base64
import dataclasses
import logging
import os
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from PyQt6 import sip
from PyQt6.QtCore import QByteArray, QObject, QSettings, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QDockWidget, QMessageBox

from helab.analysis.dataset_view import DatasetView, view_of
from helab.analysis.presets import Arrangement, RecordError, SavedPlot, parse
from helab.utils.folder_cache import Dataset, FolderCache, store_options
from helab.utils.io_service import IORequest
from helab.utils.settings_defaults import OPEN_PLOTS_SETTING, REOPEN_PLOTS_SETTING, read_setting
from helab.utils.settings_store import app_settings
from helab.views.plots.dock import AnalysisDock
from helab.views.plots.instance import AnalysisInstance

if TYPE_CHECKING:
    from helab.views.plots.script_tree import TreePanelWidget
    from helab.views.plots.workspace import PlotWorkspace

DOCK_NAME = "helab-plot-{}"  # A plot dock's object name in a recorded ``saveState``, by its place in the record


def folder_name(path: str) -> str:
    return os.path.basename(path.rstrip("/\\")) or path


class FolderWait(QObject):
    """A reopened plot's wait for its folder's data: ``found`` gives a view of it from RAM (a
    dataset held, shown in a tab or not), else from one ``cached`` read of the local disk cache
    (never the folder), else when a tab's load brings it (``FolderCache.datasetChanged``).
    ``noted`` says what it is doing, for the plot's one line.

    A folder recorded with a data root (``root_key``) whose data now has another is not the same
    folder: it isn't used unless asked deliberately (the plot's Rerun). A folder whose cached
    data is known not to match it (``FolderCache.mismatched``) has none to use, in RAM (a tab may
    still pin it) or the disk cache, until a load of the folder resolves it (Review…, Load as it
    is now). A cached read that waited for its volume's verification (``unverified``) is asked
    again once volumes are verified, as a tab's is."""

    found = pyqtSignal(object)  # DatasetView
    noted = pyqtSignal(str)

    def __init__(self, cache: FolderCache, path: str, root_key: str = "", parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.cache = cache
        self.path = FolderCache.key(path)
        self.root_key = root_key
        self.waiting: Callable[[], bool] = lambda: True  # The plot's (``AnalysisInstance.waiting``)
        self._owner = ""  # The cached read in flight (its request's owner)
        self._unverified = False  # The last read waited for its volume's verification: read again after it
        self._read_tried = False  # One automatic read: a tab's load brings newer data anyway
        self._stopped = False
        cache.datasetChanged.connect(self._dataset_changed)
        cache.mismatchesChanged.connect(self._mismatches_changed)
        cache.volumesVerified.connect(self._volumes_verified)

    def waiting_text(self) -> str:
        return f"Waiting for {folder_name(self.path)}'s data: select it to load"

    def look(self, deliberate: bool = False) -> None:
        """Find the folder's data now: in RAM, else (once, or each time ``deliberate``) the disk cache."""
        if self._stopped:
            return
        if not self.waiting():
            self.stop()
            return
        view, why = self._in_ram(deliberate)
        if view is not None:
            self._found(view)
            return
        if self._owner:
            return  # Reading the disk cache already.
        if (deliberate or not self._read_tried) and self._read_cached(deliberate):
            self.noted.emit(f"Reading {folder_name(self.path)}'s data from the disk cache…")
            return
        self.noted.emit(why or self.waiting_text())

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        for signal, slot in ((self.cache.datasetChanged, self._dataset_changed),
                             (self.cache.mismatchesChanged, self._mismatches_changed),
                             (self.cache.volumesVerified, self._volumes_verified)):
            try:
                signal.disconnect(slot)
            except TypeError:
                pass
        self._end_read()

    def _found(self, view: DatasetView) -> None:
        self.stop()
        self.found.emit(view)

    def _view(self, dataset: Dataset, deliberate: bool) -> Tuple[Optional[DatasetView], str]:
        view = view_of(dataset, self.cache.root_of(dataset.path))
        root = view.identity.root_key
        if self.root_key and root and root != self.root_key and not deliberate:
            return None, (f"{folder_name(self.path)} is now another data root's folder: select it, then "
                          "Rerun to use its data")
        return view, ""

    def _mismatched_text(self) -> str:
        return (f"{folder_name(self.path)}'s cached data doesn't match the folder: Review… it, or select it "
                "to load it as it is now")

    def _in_ram(self, deliberate: bool) -> Tuple[Optional[DatasetView], str]:
        """The folder's newest dataset held in RAM (a tab's, or kept), as a view; none while the
        folder is listed as mismatched (a tab's pin of its old data stays until it lets go)."""
        cache = self.cache
        if self.path in cache.mismatched:
            return None, self._mismatched_text()
        held = [entry for entry in (*cache.pins.values(), *cache.datasets.values()) if entry.path == self.path]
        if not held:
            return None, ""
        newest = max(held, key=lambda entry: (entry.epoch, float(entry.metadata.get("loaded_at") or 0)))
        return self._view(newest, deliberate)

    def _read_cached(self, deliberate: bool) -> bool:
        """Ask a helper for the folder's dataset from the local disk cache (the local lane: it never
        reads the folder). False if the disk cache is off or can't be asked now."""
        self._read_tried = True
        options = store_options()
        cache = self.cache
        if not options or self.path in cache.mismatched:
            return False
        self._unverified = False
        owner = f"plot-reopen:{uuid4().hex}"
        cache.resultReady.connect(self._read_event)
        self._owner = owner
        # Not a priority: the startup tab's own cached read goes first. Automatic: a large folder
        # is refused here as an automatic load would be (the tab asks when it is selected).
        if cache.submit(owner, 0, self.path, "cached",
                        {"cache": options, "verified_volumes": cache.verified_volumes(),
                         "limits": cache.large_limits(), "deliberate": deliberate, "allow_large": False}):
            return True
        self._end_read()
        return False

    def _end_read(self) -> None:
        owner, self._owner = self._owner, ""
        if owner:
            try:
                self.cache.resultReady.disconnect(self._read_event)
            except TypeError:
                pass
            self.cache.cancel(owner)

    @pyqtSlot(object, object)
    def _read_event(self, request: IORequest, event: Dict[str, Any]) -> None:
        if request.owner != self._owner:
            return
        kind = event.get("kind")
        if kind not in ("loaded", "error", "too_large", "cancelled"):
            return  # Progress.
        self._end_read()
        if self._stopped:
            return
        dataset = event.get("dataset")
        if kind == "loaded" and isinstance(dataset, Dataset):
            view, why = self._view(dataset, bool(request.payload.get("deliberate")))
            if view is not None:
                self._found(view)
                return
            self.noted.emit(why)
            return
        if kind == "error" and event.get("unverified"):
            self._unverified = True  # Not a miss: read again once volumes are verified.
        if not self.waiting():
            self.stop()
            return
        view, why = self._in_ram(False)  # A tab's load may have brought it meanwhile.
        if view is not None:
            self._found(view)
        elif kind == "too_large":
            self.noted.emit(f"{folder_name(self.path)} is too large to read back automatically: select it to load")
        else:
            self.noted.emit(why or self.waiting_text())

    @pyqtSlot()
    def _volumes_verified(self) -> None:
        """A cached read that waited for its volume's verification is asked again (once)."""
        if self._stopped or not self._unverified or self._owner:
            return
        self._unverified = False
        self._read_tried = False
        self.look()

    @pyqtSlot()
    def _mismatches_changed(self) -> None:
        """The mismatched list changed (an answer, or a load matched the folder again): look in RAM again."""
        if not self._stopped and self.path not in self.cache.mismatched:
            self._dataset_changed(self.path)

    @pyqtSlot(str)
    def _dataset_changed(self, path: str) -> None:
        if path != self.path or self._stopped:
            return
        if not self.waiting():
            self.stop()
            return
        view, why = self._in_ram(False)
        if view is not None:
            self._found(view)
        elif why:
            self.noted.emit(why)


# Recording and opening arrangements


def capture(plots: PlotWorkspace, instances: Sequence[AnalysisInstance], *, folder: str = "", root_key: str = "",
            live: bool = False) -> Arrangement:
    """The arrangement of ``instances`` (open plots) in the plot area: each plot's settings, in the
    Settings panel's order, its tab group (plots tabbed together share one, numbered in order),
    whether it floats and is the tab shown, and the area's ``saveState`` (each dock named by its
    place, ``DOCK_NAME``)."""
    area = plots.middle_mainwindow
    order = plots.panel_right_top_plot_settings.plots()
    by_dock = {id(instance.dock_widget): instance for instance in instances if instance.dock_widget is not None}
    docks = [dock for dock in order if id(dock) in by_dock and not sip.isdeleted(dock)]
    docks += [instance.dock_widget for instance in instances
              if instance.dock_widget is not None and instance.dock_widget not in docks
              and not sip.isdeleted(instance.dock_widget)]
    groups: Dict[int, int] = {}  # id(first dock of a group) → its number
    saved: List[SavedPlot] = []
    for index, dock in enumerate(docks):
        dock.setObjectName(DOCK_NAME.format(index))
        floating = dock.isFloating()
        together = [] if floating else [other for other in area.tabifiedDockWidgets(dock) if other in docks]
        first = min([dock, *together], key=docks.index)
        group = groups.setdefault(id(first), len(groups))
        # The tab shown in its group (a tab behind it has no visible region).
        front = not together or not dock.visibleRegion().isEmpty()
        plot = by_dock[id(dock)].saved_plot()
        saved.append(SavedPlot(plot.script, plot.path, plot.root_key, plot.values, plot.backend, plot.live,
                               plot.instance_id, plot.title, plot.settings_open, plot.settings_width, floating,
                               group, front, dock.objectName(), plot.preset, plot.preset_saved_at))
    state = bytes(area.saveState().toBase64().data()).decode("ascii") if docks else ""
    return Arrangement(tuple(saved), folder, root_key, live, state)


def open_arrangement(scripts: TreePanelWidget, cache: FolderCache, arrangement: Arrangement, *,
                     keep_ids: bool = False, folder: str = "",
                     layout: bool = True) -> Tuple[List[Tuple[AnalysisInstance, SavedPlot]],
                                                   List[Tuple[SavedPlot, str]]]:
    """Open ``arrangement``'s plots, each with its saved settings, waiting for its folder's data
    (every plot's ``folder`` when given: an arrangement preset is one folder's), in their tab
    groups, floating or docked, then (``layout``) the plot area's recorded state on top (positions
    and sizes, when Qt can restore them; not when plots are added beside open ones, which it
    would move). The plots opened (with their records), and each plot that couldn't, with why."""
    plots = scripts.workspace
    opened: List[Tuple[AnalysisInstance, SavedPlot]] = []
    failed: List[Tuple[SavedPlot, str]] = []
    if plots is None:
        return opened, [(plot, "no plot area") for plot in arrangement.plots]
    area = plots.middle_mainwindow
    firsts: Dict[int, QDockWidget] = {}
    fronts: List[QDockWidget] = []
    for saved in arrangement.plots:
        path = folder or saved.path
        root = arrangement.root_key if folder else saved.root_key
        wait = FolderWait(cache, path, root)
        made = scripts.reopen_plot(saved, wait, keep_id=keep_ids, place=False)
        if isinstance(made, str):
            wait.stop()
            wait.deleteLater()
            failed.append((saved, made))
            continue
        wait.setParent(made)
        dock = made.dock_widget
        if not isinstance(dock, AnalysisDock):
            continue
        dock.setObjectName(saved.dock_name or DOCK_NAME.format(len(opened)))
        if saved.settings_width:
            dock.settings.open_width = saved.settings_width
        if saved.settings_open:
            dock.set_settings_open(True)
        first = None if saved.floating else firsts.get(saved.group)
        scripts.place_dock(made, first)
        if saved.floating:
            dock.setFloating(True)
        elif first is None:
            firsts[saved.group] = dock
        if saved.front:
            fronts.append(dock)
        opened.append((made, saved))
    if layout and arrangement.dock_state and opened:
        # Docks closed just before (an arrangement preset replacing the open plots) are deleted
        # later and still carry recorded names: Qt's restoreState mustn't take them for these.
        mine = {id(instance.dock_widget) for instance, _ in opened}
        for other in area.findChildren(QDockWidget):
            if id(other) not in mine and other.objectName().startswith(DOCK_NAME.format("")):
                other.setObjectName("")
        try:
            state = QByteArray(base64.b64decode(arrangement.dock_state.encode("ascii"), validate=True))
        except (ValueError, UnicodeEncodeError):  # (``parse`` drops a layout that isn't base64 already.)
            state = QByteArray()
        if state.isEmpty() or not area.restoreState(state):
            logging.info("Plot area: its recorded layout couldn't be restored; plots are in their tab groups")
    for dock in fronts:
        if not sip.isdeleted(dock) and area.tabifiedDockWidgets(dock):
            dock.raise_()
    return opened, failed


class PlotReopen(QObject):
    """The plots that reopen at start (Settings → General, "Reopen plots at start", on by
    default): the open plots are recorded (``OPEN_PLOTS_SETTING``, an arrangement) when one opens
    or closes and when HeLab quits (``quit``, before the plots close); at the next start
    (``restore``) they open again, each waiting for its folder's data.

    Plots that can't (their script isn't loaded, e.g. a Load Scripts… folder; or it has no such
    action now) are asked about once, in one question for all of them (``ask``, not modal): Keep
    leaves them in the record for a later start, Drop forgets them. Until the user answers they
    are kept. A plot whose record can't be read at all is named in a notice and not kept."""

    def __init__(self, plots: PlotWorkspace, scripts: TreePanelWidget,
                 settings: Callable[[], QSettings] = app_settings) -> None:
        super().__init__(plots.host)
        self.plots, self.scripts, self._settings = plots, scripts, settings
        store = settings()
        self.enabled = bool(read_setting(store, REOPEN_PLOTS_SETTING, typed=True))
        self._saved_text = read_setting(store, OPEN_PLOTS_SETTING, typed=True)
        self._stopped = False
        self._restoring = False
        # Plots that couldn't reopen, kept in the record (Keep, or not answered yet).
        self.kept: List[SavedPlot] = []
        # Asks Keep or Drop for these plots (names with why); ``answer`` takes the reply.
        self.ask: Callable[[List[str]], None] = self._ask
        self._question: Optional[QMessageBox] = None
        scripts.plotsChanged.connect(self.record)

    def restore(self) -> List[AnalysisInstance]:
        """Open the plots recorded last time (if the setting says so); the plots opened."""
        text, self._saved_text = self._saved_text, ""
        if not self.enabled or not text or self._stopped:
            return []
        try:
            arrangement = parse(text)
        except RecordError as error:
            logging.warning("The plots open last time can't be read (%s): %r", error, text[:2000])
            self.plots.notice(f"The plots open last time can't be reopened: their record can't be read ({error})")
            return []
        cache = self._cache()
        self._restoring = True
        try:
            opened, failed = open_arrangement(self.scripts, cache, arrangement, keep_ids=True)
        finally:
            self._restoring = False
        if arrangement.layout_error:
            self.plots.notice(f"The plots open last time reopened in their tab groups: {arrangement.layout_error}")
        if arrangement.unreadable:
            unreadable = "; ".join(arrangement.unreadable)
            self.plots.notice(f"Not reopened (their records can't be read): {unreadable}")
            logging.info("Plots not reopened, records unreadable: %s", unreadable)
        self.kept = [saved for saved, _ in failed]
        if failed:
            names = [f"{saved.script.label()} ({why})" for saved, why in failed]
            logging.info("Plots not reopened: %s", "; ".join(names))
            self.ask(names)
        self.record()
        return [instance for instance, _ in opened]

    def _ask(self, names: List[str]) -> None:
        count = len(names)
        box = QMessageBox(QMessageBox.Icon.Information, "Plots not reopened",
                          f"{count:,} plot{'' if count == 1 else 's'} open last time couldn't reopen: "
                          + "; ".join(names) + ".\n\nKeep "
                          + ("it" if count == 1 else "them") + " for a later start (for example once "
                          "the scripts are loaded), or drop " + ("it" if count == 1 else "them") + "?",
                          QMessageBox.StandardButton.NoButton, self.plots.host)
        keep = box.addButton("Keep for later", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Drop", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(keep)
        box.setWindowModality(Qt.WindowModality.NonModal)
        box.buttonClicked.connect(lambda button: self.answer(button is keep))
        self._question = box
        box.open()

    def answer(self, keep: bool) -> None:
        """The reply to ``ask``: Keep leaves the plots that couldn't reopen in the record, Drop forgets them."""
        self._question = None
        if not keep:
            self.kept = []
            self.record()

    def _cache(self) -> FolderCache:
        budget = self.plots.ram_budget
        if budget is not None:
            return budget.cache
        from helab.utils.folder_cache import get_folder_cache
        from helab.utils.io_service import get_io_service
        return get_folder_cache(get_io_service())

    @pyqtSlot()
    def record(self) -> None:
        """Record the open plots now, and the plots kept that couldn't reopen (not while plots are
        being reopened, nor once HeLab quits)."""
        if self._stopped or self._restoring or sip.isdeleted(self.plots.middle_mainwindow):
            return
        instances = self.scripts.instances()
        try:
            arrangement = capture(self.plots, instances) if instances else Arrangement()
        except Exception:  # A script's parameters() failing: the record keeps what it had.
            logging.exception("The open plots couldn't be recorded")
            return
        if self.kept:
            # Each on its own after the open plots: no dock in the saved layout, no tab group shared.
            first = max((plot.group for plot in arrangement.plots), default=-1) + 1
            kept = tuple(dataclasses.replace(plot, group=first + index, floating=False, front=True, dock_name="")
                         for index, plot in enumerate(self.kept))
            arrangement = dataclasses.replace(arrangement, plots=(*arrangement.plots, *kept))
        self._settings().setValue(OPEN_PLOTS_SETTING, arrangement.dumps() if arrangement.plots else "")

    def quit(self) -> None:
        """HeLab quits: the open plots are recorded once more (before they close), and no more."""
        self.record()
        self._stopped = True
        if self._question is not None and not sip.isdeleted(self._question):
            self._question.close()  # Unanswered: the plots stay kept.
