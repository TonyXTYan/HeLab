"""A plot's controller: ``AnalysisInstance`` runs a dataset analysis, draws it in its dock
and Settings page, follows Live, and is released and reloaded for the RAM budget."""
from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import replace
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple, TYPE_CHECKING
from uuid import uuid4

from PyQt6 import sip
from PyQt6.QtCore import QObject, QSize, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QDockWidget, QLabel, QPushButton, QVBoxLayout, QWidget
from pyqtgraph.parametertree import Parameter

from helab.analysis.backends import BACKEND, backend_specs
from helab.analysis.constant_layers import (changed_keys, describe_constants, source_name, value_and_origin,
                                           without_constants)
from helab.analysis.physics import TABLE, ResolvedConstants
from helab.analysis.budget import RamBudget
from helab.analysis.budget_core import RELOAD_GRACE, Restored, hollow, restore, shots_list, view_buffers
from helab.analysis.dataset_view import DatasetView, ViewKey
from helab.analysis.follow import FOLLOW, Follow, changes, live_specs, policy_of, shots_text
from helab.analysis.live_feed import LiveFeed
from helab.analysis.parameter_tree import build_tree, commit_pending_text, parameter_of, settings_widget, tree_values
from helab.analysis import result_cache
from helab.analysis.parameters import describe
from helab.analysis.presets import PlotCheck, SavedPlot, ScriptPreset, ScriptRef, check_plot, is_waiting
from helab.analysis.results import DISK_CACHED, RAM_ONLY, AnalysisContext, AnalysisResult
from helab.analysis.runner import AnalysisRunner, get_analysis_runner
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.utils.constants import QDOCKWIDGET_STYLESHEET
from helab.utils.folder_cache import Dataset, FolderCache, get_folder_cache, store_options
from helab.utils.io_service import IORequest, get_io_service
from helab.utils.number_format import byte_size
from helab.utils.ram_buffers import Buffers, arrays_in, buffers
from helab.views.plots.cached_results import PENDING_NOTE, CachedRuns
from helab.views.plots.dock import AnalysisDock
from helab.views.plots.pictures import ReleasedPlot, snapshot
if TYPE_CHECKING:
    from helab.views.plots.arrangement import FolderWait
    from helab.views.plots.presets import PresetBar
    from helab.views.plots.workspace import PlotWorkspace


class LinkedAnalysisInstance(QObject):
    """Manages a linked pair of dock widget and its page in the Settings panel.
    
    This class handles:
    - Unique instance identification
    - Synchronized closing of linked UI components
    - Cleanup of resources when either component is closed, or the dock is deleted unclosed
      (its window went). That runs through Qt slots: PyQt can drop a plain Python callable
      connected to ``destroyed`` before it runs.
    
    Args:
        name: Base name of the analysis (used for display)
        instance_id: Unique identifier for this instance
        workspace: The plot area it opens in (None: no dock, as in tests of the plot alone)
    """
    
    ended = pyqtSignal(str)  # instance_id, once closed

    def __init__(self, name: str, instance_id: str, workspace: Optional[PlotWorkspace]):
        super().__init__()
        self.name = name
        self.instance_id = instance_id
        self.workspace = workspace
        self.dock_widget: Optional[QDockWidget] = None
        self.param_tab: Optional[QWidget] = None
        self.is_closed = False
        
    def setup_dock_widget(self, content: QWidget) -> None:
        """Create and setup the dock widget."""
        if self.workspace is None:
            return
            
        dock = AnalysisDock(f"{self.name} ({self.instance_id})", self.workspace.host)
        dock.setStyleSheet(QDOCKWIDGET_STYLESHEET)
        dock.setWidget(content)
        dock.closed.connect(self.close)
        # A dock deleted unclosed (its window went) still ends the run and its connections.
        dock.destroyed.connect(self.close)
        self.dock_widget = dock
        
    def setup_param_tab(self, param_tree: QWidget, title: str = "") -> None:
        """Add this plot's page to the Settings panel (after its dock is made)."""
        if self.workspace is None or self.dock_widget is None:
            return
        self.param_tab = param_tree
        self.workspace.panel_right_top_plot_settings.add_plot(
            self.dock_widget, param_tree, title or f"{self.name} ({self.instance_id})")
        
    @pyqtSlot()
    def close(self) -> None:
        """Close and cleanup both components (only what is still there: after the main window
        went, its widgets are deleted already)."""
        if self.is_closed:
            return
            
        self.is_closed = True
        self.ended.emit(self.instance_id)
        plots, dock = self.workspace, self.dock_widget
        if plots is None or sip.isdeleted(plots.host):
            return
        if dock is not None and dock in plots.dock_widgets:
            plots.dock_widgets.remove(dock)
        if self.param_tab is not None and not sip.isdeleted(self.param_tab):
            self.param_tab.deleteLater()
        if dock is None or sip.isdeleted(dock):
            return  # Deleted with the plot area: the Settings panel drops the page itself.
        plots.middle_mainwindow.removeDockWidget(dock)
        dock.deleteLater()
        if self.param_tab is not None:
            plots.panel_right_top_plot_settings.remove_plot(dock)
        plots.update_placeholder_visibility()


class AnalysisInstance(LinkedAnalysisInstance):
    """One plot of a dataset analysis: its dock and settings page, bound to the dataset view it
    started with. **Rerun with these settings** runs again on that data (cancelling a run in
    flight: the settings changed); a run on other data is a new plot (the script's button).

    A plot of the folder Live watches follows it (roadmaps/live-monitoring.md, L3): each newer
    revision of the folder's view (``LiveFeed``) is offered to it, and it reruns on the newest
    one as its Live settings allow (``Follow``: hold and coalesce, never cancelled for new data).
    Turning Follow Live off pins it at its revision. A failed run keeps the last plot drawn,
    with the error in amber, and following goes on.

    Plots count toward the RAM budget (``RamBudget``, helab/analysis/budget.py): one may be
    released to free RAM (``release``: a picture stays, its view and result go) and reloads
    from RAM or the disk cache, never its folder (``reload``), when shown again or on Reload."""

    def __init__(self, metadata: ScriptMetadata, script: DatasetAnalysis, action: str, view: DatasetView,
                 instance_id: str, workspace: Optional[PlotWorkspace],
                 runner: Optional[AnalysisRunner] = None, cache: Optional[FolderCache] = None) -> None:
        # The script's hooks first: one that raises leaves nothing connected (``run_analysis`` says so).
        policy, constant_keys = script.live_policy(action), script.constant_keys(action)
        super().__init__(metadata.name, instance_id, workspace)
        # The app's FolderCache unless given (tests); its lab and folder constants feed each run.
        self._given_cache = cache
        self.metadata, self.script, self.action = metadata, script, action
        self.runner = runner or get_analysis_runner()
        self.job_id = ""
        # The last result (whatever its state), and the completed one whose plot shows.
        self.result: Optional[AnalysisResult] = None
        self.shown: Optional[AnalysisResult] = None
        # The data of the run in flight, and of the result shown (what Follow Live off pins).
        self._job_view: Optional[DatasetView] = None
        self._shown_view: Optional[DatasetView] = None
        self._content: Optional[QWidget] = None  # The plot drawn (``render``), updated in place if it can
        self._drawn_with = ""  # The library ``_content`` was drawn with (``backend``)
        self.error = ""  # The last run's failure, while the plot before it stays
        self.policy = policy
        self.follow = Follow(view, self.policy)
        self.parameter_root: Optional[Parameter] = None
        self.status_label = QLabel()
        self.input_label = QLabel()
        self.feed: Optional[LiveFeed] = workspace.live_feed if workspace is not None else None
        self._follow_timer = QTimer(self)
        self._follow_timer.setSingleShot(True)
        self._follow_timer.timeout.connect(self._follow_next)
        self.runner.finished.connect(self._finished)
        if self.feed is not None:
            self.feed.revised.connect(self._revised)
            self.feed.ended.connect(self._live_ended)
        self.budget: Optional[RamBudget] = workspace.ram_budget if workspace is not None else None
        # Released to free RAM: the picture shown instead of the plot, until a run draws it again.
        self.released: Optional[ReleasedPlot] = None
        self._reload_owner = ""  # The disk-cache read of a reload in flight (its request's owner).
        self._reload_found: Optional[Restored] = None  # Meanwhile, the best match RAM had.
        self._reload_values: Optional[Dict[str, Any]] = None  # The settings it runs with.
        self._reload_shots: Optional[Tuple[int, ...]] = None  # The shots it takes (None: the view's).
        self._reload_note = ""  # What the last reload left out (changed or missing shots).
        self._picture_cost = 0  # Bytes its picture took when last taken (0: not yet).
        # A reload found its data nowhere: showing it doesn't try again until its folder's data
        # in RAM or its disk cache changes (Reload always tries).
        self._nowhere = False
        self._watching_folder = False
        self.reloaded_at = -math.inf  # Monotonic: when a reload last drew it.
        # Its runs, whose completed results RamResults may keep (counted as the plot's RAM).
        self._runs: List[str] = []
        # The constants its settings let it override (helab/analysis/constant_layers.py): each run
        # resolves them (lab, folder, this plot) when it is submitted. A lab or folder value that
        # changes afterwards marks the plot (open decision 5, proposed); the next run uses it.
        self.constant_keys = constant_keys
        self._constants_note = ""
        self._reload_constants: Optional[Mapping[str, Mapping[str, float]]] = None
        if self.constant_keys:
            self._cache().constantsChanged.connect(self._constants_changed)
        # Presets (helab/views/plots/presets.py): the settings page's Presets row, and the script
        # preset last applied (its name and when it was saved), which an arrangement records.
        self.presets: Optional[PresetBar] = None
        self.preset_from: Tuple[str, float] = ("", 0.0)
        # Reopened (at start, or from an arrangement preset): until its folder's data is found in
        # RAM or the disk cache, the plot waits (``FolderWait``) and holds ``waiting_view``.
        self._wait: Optional[FolderWait] = None
        self._waiting_message: Optional[QLabel] = None
        self.reopen_check: Optional[PlotCheck] = None  # What its saved settings gave when reopened

    @property
    def view(self) -> DatasetView:
        """The plot's data: the input of its run in flight, or of its last run."""
        return self.follow.ran

    @property
    def path(self) -> str:
        return self.follow.ran.identity.source_path

    def start(self, saved: Optional[SavedPlot] = None, wait: Optional[FolderWait] = None) -> None:
        """Open the dock and its settings page, then run with the defaults. Reopened (``saved``,
        with ``wait`` on its folder): with its saved settings (those that fit the script now;
        ``reopen_check``), and it waits for its folder's data instead of running."""
        waiting = saved is not None and wait is not None
        message = self._message(f"Running {self.name} on {self.view.key.short()}…" if not waiting
                                else f"Looking for {self.view.identity.name}'s data…")
        self.setup_dock_widget(message)
        try:
            self._open_settings()
        except Exception as error:
            # A script's parameters(), backends() or minimum_size() failing: the dock says so (in this
            # Qt slot the exception would abort the app).
            logging.exception("%s could not open its settings", self.name)
            message.setText(f"{self.name} failed: {error}")
            return
        if saved is None or wait is None:
            self.run()
            return
        self.reopen_check = self.apply_saved(saved, "at the script's defaults")
        self.preset_from = (saved.preset, saved.preset_saved_at)
        self._waiting_message = message
        self._wait = wait
        wait.waiting = self.waiting
        wait.found.connect(self.run_reopened)
        wait.noted.connect(self._waiting_noted)
        wait.look()

    def _open_settings(self) -> None:
        """The plot's settings page (its parameters, Drawing and Live) and its RAM budget entry."""
        if isinstance(self.dock_widget, AnalysisDock):
            self.dock_widget.set_minimum_plot_size(*self.script.minimum_size(self.action))
        specs = self.script.parameters(self.action)
        page = specs[0].page if specs else ""
        drawing = backend_specs(self.script.backends(self.action), page)
        live = live_specs(self.policy, page)
        self.parameter_root = build_tree([*specs, *drawing, *live])
        for spec in drawing:
            parameter_of(self.parameter_root, spec).sigValueChanged.connect(self._backend_changed)
        for spec in live:
            parameter_of(self.parameter_root, spec).sigValueChanged.connect(self._live_settings_changed)
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.input_label.setToolTip(self.path)
        layout.addWidget(self.input_label)
        layout.addWidget(settings_widget(self.parameter_root, [*specs, *drawing, *live]), 1)
        self.rerun_button = QPushButton("Rerun with these settings")
        self.rerun_button.setEnabled(bool(specs))
        self.rerun_button.clicked.connect(self.run)
        layout.addWidget(self.rerun_button)
        layout.addWidget(self.status_label)
        if specs:
            from helab.views.plots.presets import PresetBar
            self.presets = PresetBar(self)
            layout.insertWidget(1, self.presets)
        self.setup_param_tab(tab, self._title())
        if self.param_tab is not None and self.workspace is not None:
            self.workspace.panel_right_top_plot_settings.plotShown.connect(self._plot_shown)
        if self.budget is not None:
            self.budget.add(self)

    def values(self) -> Dict[str, Any]:
        """The analysis's parameters as set (not the plot's Live settings)."""
        root = self.parameter_root
        return tree_values(root, self.script.parameters(self.action)) if root is not None else {}

    def backend(self) -> str:
        """The library the plot is drawn with (Drawing › Library), "" when the script names none."""
        specs = backend_specs(self.script.backends(self.action))
        root = self.parameter_root
        if not specs:
            return ""
        return str(tree_values(root, specs)[BACKEND]) if root is not None else str(specs[0].default)

    def live_values(self) -> Dict[str, Any]:
        root = self.parameter_root
        return tree_values(root, live_specs(self.policy)) if root is not None else {}

    def run(self) -> None:
        """Run with the settings shown, on the newest data the plot has (what waits for it while
        it follows Live, else its own); a run in flight is cancelled, its settings are old. A
        reopened plot still waiting for its folder's data looks for it again (RAM, then the disk
        cache) instead: deliberately, so its data under another data root is taken too."""
        if self.is_closed:
            return
        commit_pending_text()  # Text being typed (e.g. mask circles) counts for a deliberate run.
        if self.waiting():
            assert self._wait is not None
            self._wait.look(deliberate=True)
            return
        if self.released is not None and not self.job_id:
            # Its data was released: drawn again from RAM or the disk cache, with these settings.
            if self._reload_owner:
                self._reload_values = self.values()
            else:
                self.reload(self.values())
            return
        if self.job_id:
            self._cancel_run()
        self._submit(self.follow.latest, one_off=True)

    # Saved results (result caching R2, ``helab.views.plots.cached_results``): set on the first run
    # that may use them.
    _cached_link: Optional[CachedRuns] = None
    # The amber line's note while an outdated saved result shows (the run replacing it goes on), and
    # what the disk cache said of the last run (not saved, couldn't be read) for the status line.
    _cache_note = ""
    _cache_status = ""

    def _cancel_run(self) -> None:
        """Cancel the run in flight, or its disk-cache lookup."""
        if self._cached_link is not None:
            self._cached_link.forget(self.job_id)
        self.runner.cancel(self.job_id)

    def _cached_runs(self) -> CachedRuns:
        if self._cached_link is None:
            self._cached_link = CachedRuns(self._cache(), self.script, self.action, self.name,
                                           found=self._cached_found, run=self._cached_run, saved=self._cached_saved,
                                           note=self._cached_status, closed=lambda: self.is_closed,
                                           removed=self._cached_removed, evicted=self._cached_evicted)
        return self._cached_link

    def _submit(self, view: DatasetView, values: Optional[Dict[str, Any]] = None, *, reloading: bool = False,
                constants: Optional[Mapping[str, Mapping[str, float]]] = None, live: bool = False,
                one_off: bool = False) -> None:
        """Run on ``view``. A ``one_off`` run (the user's: Rerun, the first run, a reload, a reopened
        plot's; never Live's) of a script whose results may be saved looks itself up in the disk
        cache first (R2)."""
        self._follow_timer.stop()
        if not reloading:
            self._reload_note = ""
        try:
            values = self.values() if values is None else values
        except Exception as error:  # The script's parameters() (a Qt slot: never raised from here).
            logging.exception("Parameters of %s failed", self.name)
            self.status_label.setText(f"Failed: {error}")
            return
        if constants is None:
            constants = self.constant_layers(view.identity.source_path)
        link = self._cached_runs() if one_off and not live else None
        cached = link is not None and link.supported() and not link.off_reason(view)
        if link is not None and self.dock_widget is not None and not sip.isdeleted(self.dock_widget):
            # The source line's mark: this plot's runs are looked up and saved (``disk cache reuse on``).
            self.dock_widget.setProperty("plotReuse", cached)
        context = self.runner.prepare(self.script, self.metadata, self.action, view, values, constants,
                                      owner=self.instance_id, live=live, to_cache=cached)
        waiting = cached and link is not None and link.start(context)
        if not waiting:
            try:
                self.runner.enqueue(self.script, context)
            except RuntimeError as error:  # The runner is stopping: HeLab is closing.
                if link is not None:
                    link.forget(context.job_id)
                self.status_label.setText(str(error))
                return
        self._cache_status = ""
        self.job_id, self._job_view = context.job_id, view
        self._runs.append(context.job_id)
        self.follow.start(view)
        self.status_label.setText(f"Looking in the disk cache ({context.job_id})…" if waiting
                                  else f"Running ({context.job_id})…")
        self._show_constant_titles(context.resolved_constants)
        self._show_follow()

    def _cached_run(self, context: AnalysisContext) -> None:
        """Nothing saved matched exactly: the run computes now."""
        if self.is_closed or context.job_id != self.job_id:
            return
        try:
            self.runner.enqueue(self.script, context)
        except RuntimeError as error:  # The runner is stopping: HeLab is closing.
            self.job_id = ""
            self.follow.end(time.monotonic())
            self.status_label.setText(str(error))
            return
        if self._cache_note:
            self.status_label.setText(f"Showing a saved result; rerunning ({context.job_id})…")
        else:
            self.status_label.setText(f"Running ({context.job_id})…")

    def _cached_found(self, context: AnalysisContext, result: AnalysisResult) -> None:
        """A saved result for the run: an exact match is its result (the run is skipped); an
        outdated one shows while the run goes on."""
        if self.is_closed or context.job_id != self.job_id:
            return
        if not result.outdated:
            self.runner.results.add(result)
            self._finished(result)
            return
        specs = self.script.parameters(self.action)
        warnings = "; ".join(self._hook("parameter_warnings", [], result.parameters))
        try:
            content = self._updated(result) or self._draw(result)
        except Exception:
            logging.exception("Could not draw %s's saved result", self.name)
            return
        if self.shown is not None:
            self.runner.results.unpin(self.shown.job_id)
        self.shown = result
        if self.released is not None:
            self.reloaded_at = time.monotonic()
        self.released = None
        when = datetime.fromtimestamp(result.finished_at).strftime("%Y-%m-%d %H:%M") if result.finished_at else "?"
        self._cache_note = f"saved result from {when} is outdated ({'; '.join(result.outdated)}): rerunning"
        self._show_content(content, result, specs, warnings)

    def _cached_saved(self, result: AnalysisResult, size: int) -> None:
        """The run's result is now in the disk cache: its record says so; a large one is said."""
        if self._cache_status == PENDING_NOTE:
            self._cached_status("")  # Saved after Make room: the question is answered.
        if size > result_cache.LARGE_RESULT_BYTES and self.workspace is not None:
            self.workspace.notice(f"Saved {self.name} ({self.view.identity.name}) in the disk cache: {byte_size(size)}")
        shown = self.shown
        if shown is None or shown.job_id != result.job_id or self.released is not None:
            return
        self.shown = replace(shown, policy=DISK_CACHED)
        if self.result is shown:
            self.result = self.shown
        content = self._content
        if content is not None and not sip.isdeleted(content):
            specs = self.script.parameters(self.action)
            self._show_content(content, self.shown, specs,
                               "; ".join(self._hook("parameter_warnings", [], self.shown.parameters)))

    def _cached_removed(self, paths: Optional[List[str]]) -> None:
        """Clear cached analysis removed the folder's saved results: the record says RAM only again."""
        shown = self.shown
        if (shown is None or shown.policy != DISK_CACHED or self.released is not None
                or (paths is not None and FolderCache.key(self.path) not in paths)):
            return
        self.shown = replace(shown, policy=RAM_ONLY)
        if self.result is shown:
            self.result = self.shown
        content = self._content
        if content is not None and not sip.isdeleted(content):
            self._show_content(content, self.shown, self.script.parameters(self.action),
                               "; ".join(self._hook("parameter_warnings", [], self.shown.parameters)))

    def _cached_evicted(self, job_id: str) -> None:
        """Make room removed this run's saved result for another: the record says RAM only again."""
        shown = self.shown
        if shown is not None and shown.job_id == job_id:
            self._cached_removed(None)

    def _cached_status(self, text: str) -> None:
        """What the disk cache said of the run (not saved, couldn't be read, waiting for an answer): on
        the status line, in place of what it said before ("" clears it); other warnings stay."""
        previous, self._cache_status = self._cache_status, text
        if self.is_closed:
            return
        parts = [part for part in self.status_label.text().split(" · ") if part and part != f"⚠ {previous}"]
        self.status_label.setText(" · ".join([*parts, *([f"⚠ {text}"] if text else [])]))

    @pyqtSlot(object)
    def _finished(self, result: AnalysisResult) -> None:
        # A slot (no PyQt proxy object): closing disconnects it at once, not at a later deletion.
        if self.is_closed or result.job_id != self.job_id:
            return
        if self._cached_link is not None:
            self._cached_link.finished(result)  # Saves a completed result packed for the disk cache.
        if result.packed is not None:
            result = replace(result, packed=None)
        self.job_id = ""
        self.follow.end(time.monotonic())
        view, self._job_view = self._job_view, None
        if self.released is not None:
            self.released.set_state("")  # A reload's run ended; a failure shows in the amber line.
        if result.state == "cancelled":
            self.status_label.setText("Cancelled")
            self._still_released()
            self._show_follow()
            return
        if not self.follow.on and view is not None and view.key != self.follow.ran.key:
            # A Live rerun that started before Follow Live went off: the plot stays pinned.
            self.status_label.setText(f"Pinned at rev {self.follow.ran.revision}: "
                                      f"the run on rev {view.revision} isn't shown")
            self._still_released()
            self._show_follow()
            return
        self.result = result
        specs = self.script.parameters(self.action)
        warnings = "; ".join(self._hook("parameter_warnings", [], result.parameters))
        content: Optional[QWidget] = None
        error = result.error if result.state == "failed" else ""
        if result.state == "completed":
            self._show_detected(result)
            try:
                content = self._updated(result)
                if content is None:
                    content = self._draw(result)
            except Exception as exc:
                logging.exception("Could not draw %s", self.name)
                error = f"could not draw it: {exc}"
        if self.budget is not None:
            self.budget.schedule()
        if error:
            self.status_label.setText(f"Failed: {error}")
            if self.shown is not None:
                # The last plot stays; the error shows above it until a run succeeds.
                self.error = f"rev {result.input.revision} failed: {error} · showing rev {self.shown.input.revision}"
                self._still_released()
                self._show_follow()
                self._follow_next()
                return
            content = self._message(f"{self.name} failed: {error}")
        else:
            self.status_label.setText(" · ".join(filter(None, (f"⚠ {warnings}" if warnings else "",
                                                               self._cache_status and f"⚠ {self._cache_status}"))))
        assert content is not None
        self.error = ""
        if self.shown is not None:
            self.runner.results.unpin(self.shown.job_id)
            self.shown = None
        if result.state == "completed" and not error:
            self._cache_note = ""  # An outdated saved result shown meanwhile is replaced.
            self.shown, self._shown_view = result, view
            self.runner.results.pin(result.job_id)
            if self.released is not None:
                self.reloaded_at = time.monotonic()
            self.released = None  # Drawn again: its picture goes.
            self._nowhere = False
        self._check_constants()
        self._show_content(content, result, specs, warnings)
        self._follow_next()

    def _still_released(self) -> None:
        """A run ended without drawing while the plot is released (a reload failed or was
        cancelled): it keeps no data, so the data that run had goes (it couldn't be freed
        otherwise: a released plot isn't released again)."""
        if self.released is not None and self.follow.ran.event_count:
            self.follow.ran = hollow(self.follow.ran)
            if self.budget is not None:
                self.budget.schedule()

    def _updated(self, result: AnalysisResult) -> Optional[QWidget]:
        """The plot drawn, showing ``result`` in place (the script's ``update``), or None."""
        drawn = self._content
        if (self.shown is None or self.released is not None or drawn is None or sip.isdeleted(drawn)
                or self._drawn_with != self.backend()):
            return None
        return drawn if self.script.update(drawn, result) else None

    def _draw(self, result: AnalysisResult) -> QWidget:
        """``result``'s plot drawn anew, with the library chosen."""
        backend = self.backend()
        content = self.script.draw(result, backend) if backend else self.script.render(result)
        self._drawn_with = backend
        return content

    def _backend_changed(self) -> None:
        """Another library: the plot shown is drawn again with it, from its result (no rerun). A
        released plot is drawn with it when it reloads."""
        result = self.shown
        if self.is_closed or result is None or self.released is not None or self._drawn_with == self.backend():
            return
        specs = self.script.parameters(self.action)
        warnings = "; ".join(self._hook("parameter_warnings", [], result.parameters))
        try:
            content = self._draw(result)
        except Exception as exc:
            logging.exception("Could not draw %s with %s", self.name, self.backend())
            self.status_label.setText(f"Failed: could not draw it with {self.backend()}: {exc}")
            return
        self._show_content(content, result, specs, warnings)

    def _show_content(self, content: QWidget, result: AnalysisResult, specs: List[Any], warnings: str) -> None:
        self._content = content
        if self.dock_widget is None:
            content.deleteLater()
            return
        if self.workspace is not None:
            chosen, settings = self._hook("describe_run", ("", ""), result.parameters, self.view)
            record = describe(without_constants(specs), result.parameters, every=True)
            if (constants := result.resolved_constants) is not None:
                # The constants not at their defaults (all of them, with origins, are in the record).
                used = describe_constants(constants, result.constant_keys)
                settings = " · ".join(filter(None, (settings, used and f"constants: {used}",
                                                    *(f"⚠ {note}" for note in constants.notes))))
            found = self._hook("result_record", [], result) if result.state == "completed" else []
            if found:
                record = "\n".join((record, *found))
            if self._drawn_with:
                record = f"{record}\nDrawn with {self._drawn_with}"
            if result.state == "completed":
                settings = " · ".join(filter(None, (settings, self._hook("describe_result", "", result))))
            if warnings:
                settings = " · ".join(filter(None, (settings, f"⚠ {warnings}")))
                record = f"{record}\nWarning: {warnings}"
            self.workspace.set_plot_result(self.dock_widget, content, result, settings, record, chosen)
        elif self.dock_widget.widget() is not content:
            old = self.dock_widget.widget()
            self.dock_widget.setWidget(content)
            if old is not None:
                old.deleteLater()
        self._show_follow()

    def _hook(self, name: str, fallback: Any, *args: Any) -> Any:
        """The script's ``name`` hook for this action, or ``fallback`` if it raises (logged): these run
        in Qt slots, where an exception from a user's script would abort the app."""
        try:
            return getattr(self.script, name)(self.action, *args)
        except Exception:
            logging.exception("%s of %s failed", name, self.name)
            return fallback

    def _show_detected(self, result: AnalysisResult) -> None:
        """Put what the run found into the settings (they don't rerun it), except a setting changed
        since the run started (what was typed meanwhile stays) or already holding the value."""
        root = self.parameter_root
        if root is None:
            return
        specs = {spec.name: spec for spec in self.script.parameters(self.action)}
        for name, value in self._hook("detected_parameters", {}, result).items():
            if name in specs:
                parameter, value = parameter_of(root, specs[name]), specs[name].coerce(value)
                if parameter.value() == result.parameters.get(name) and parameter.value() != value:
                    parameter.setValue(value)

    # Presets and reopening (helab/views/plots/presets.py, arrangement.py)

    def script_ref(self) -> ScriptRef:
        return ScriptRef.of(self.metadata.identity(), self.action, self.metadata.name)

    def apply_saved(self, saved: SavedPlot | ScriptPreset, kept: str) -> PlotCheck:
        """Put saved settings into the plot's settings: each that fits the script now (``check_plot``);
        the others aren't applied, named in the Presets row's note (one line, the rest in its tooltip),
        ``kept`` as they are ("at the script's defaults" for a plot just opened, "left as they were"
        for an open one). An edit like any other: it reruns only as an edit would (a library
        draws the plot again)."""
        root = self.parameter_root
        specs = self.script.parameters(self.action)
        backends = self.script.backends(self.action)
        check = check_plot(saved, self.metadata.identity(), specs, backends, live_specs(self.policy))
        if root is None:
            return check
        for spec in specs:
            if spec.name in check.values:
                parameter_of(root, spec).setValue(check.values[spec.name])
        if check.backend:
            for spec in backend_specs(backends):
                parameter_of(root, spec).setValue(check.backend)
        for spec in live_specs(self.policy):
            if spec.name in check.live:
                parameter_of(root, spec).setValue(check.live[spec.name])
        if self.presets is not None:
            if isinstance(saved, ScriptPreset):
                self.presets.set_note(f"Preset “{saved.name}”", check, kept)
            else:  # Reopened: said only if a setting wasn't restored, or the script changed.
                self.presets.set_note("Reopened", check, kept, quiet=True)
        return check

    def saved_plot(self) -> SavedPlot:
        """The plot as an arrangement records it (its place is added by ``arrangement.capture``)."""
        view = self.view
        dock = self.dock_widget
        open_, width = ((dock.settings.is_open, dock.settings.open_width) if isinstance(dock, AnalysisDock)
                        else (False, 0))
        commit_pending_text()
        return SavedPlot(self.script_ref(), view.identity.source_path, view.identity.root_key, self.values(),
                         self.backend(), self.live_values(), self.instance_id, f"{self.name} ({self.instance_id})",
                         open_, width, preset=self.preset_from[0], preset_saved_at=self.preset_from[1])

    def waiting(self) -> bool:
        """Reopened and still waiting for its folder's data (no run yet)."""
        return self._wait is not None and self.result is None and not self.job_id and is_waiting(self.follow.ran)

    @pyqtSlot(object)
    def run_reopened(self, view: DatasetView) -> None:
        """The one place a reopened plot decides to run: its folder's data was found (in RAM or
        the disk cache, ``FolderWait``), so it runs on it with its settings, as the user's first run
        does: a result saved for exactly these settings and data shows instead (R2)."""
        if self.is_closed or not self.waiting():
            return
        self._end_wait()
        self._submit(view, one_off=True)

    @pyqtSlot(str)
    def _waiting_noted(self, text: str) -> None:
        message = self._waiting_message
        if message is not None and not sip.isdeleted(message) and self.waiting():
            message.setText(text)
            self.status_label.setText(text)
        self._show_follow()

    def _end_wait(self) -> None:
        wait, self._wait = self._wait, None
        if wait is not None:
            for signal, slot in ((wait.found, self.run_reopened), (wait.noted, self._waiting_noted)):
                try:
                    signal.disconnect(slot)
                except TypeError:
                    pass
            wait.stop()
        self._waiting_message = None

    # Constants (F0b)

    def constant_layers(self, path: Optional[str] = None) -> Dict[str, Dict[str, float]]:
        """The lab and folder layers a run on ``path`` (default: the plot's folder) takes now, from
        memory (``AnalysisContext.constants``): Settings → Lab parameters, and the folder's own or
        inherited values (``FolderCache.effective_folder_constants``)."""
        cache = self._cache()
        return {"lab": dict(cache.lab_constants), "folder": cache.effective_folder_constants(path or self.path)}

    def resolve_constants(self, values: Dict[str, Any], path: Optional[str] = None) -> Optional[ResolvedConstants]:
        """What a run with ``values`` on ``path`` would resolve now (the script's ``run_constants``
        on ``constant_layers``); None if the plot uses no constants."""
        if not self.constant_keys:
            return None
        return self.script.run_constants(self.action, values, self.constant_layers(path))

    @pyqtSlot(str)
    def _constants_changed(self, path: str) -> None:
        """A lab value ("") or a folder's own values changed: this plot's, if it is that folder or below."""
        mine = self.path
        if self.is_closed or (path and path != mine and not mine.startswith(path.rstrip(os.sep) + os.sep)):
            return
        self._check_constants()
        self._show_follow()

    def _check_constants(self) -> None:
        """Mark the plot when the constants it would use now differ from those its plot was drawn
        with (open decision 5, proposed): it keeps its plot until Rerun or the next Live update."""
        shown = self.shown
        if shown is None or shown.resolved_constants is None:
            self._constants_note = ""
            return
        try:
            now = self.resolve_constants(dict(shown.parameters))
        except Exception:
            logging.exception("Constants of %s: not compared", self.name)
            now = None
        if now is None:
            self._constants_note = ""
            return
        # The keys the shown run used (``run_constant_keys``): another one changing doesn't concern it.
        changed = changed_keys(shown.resolved_constants, now, shown.constant_keys)
        self._constants_note = (f"constants changed ({', '.join(TABLE[key].title for key in changed)}): "
                                "Rerun to use them") if changed else ""
        self._show_constant_titles(now)

    def _show_constant_titles(self, constants: Optional[ResolvedConstants]) -> None:
        """Each constant's choice in the settings names the value a run takes and where it comes
        from: "Fall distance h: 0.848 m (folder)"."""
        root = self.parameter_root
        if constants is None or root is None:
            return
        specs = {spec.name: spec for spec in self.script.parameters(self.action)}
        for key in self.constant_keys:
            spec = specs.get(source_name(key))
            if spec is None:
                continue
            parameter = parameter_of(root, spec)
            title = f"{TABLE[key].title}: {value_and_origin(constants, key)}"
            if parameter.opts.get("title") != title:
                parameter.setOpts(title=title)

    # Following Live

    def live(self) -> Optional[DatasetView]:
        """The newest revision of the plot's folder while Live watches it (None: it doesn't)."""
        return self.feed.latest(self.path) if self.feed is not None else None

    @pyqtSlot(object)
    def _revised(self, view: DatasetView) -> None:
        if self.is_closed or view.identity.source_path != self.path:
            return  # Plots of other folders stay put.
        self.follow.live_on()
        if self.follow.offer(view):
            self._follow_next()
        self._show_follow()

    @pyqtSlot(str)
    def _live_ended(self, path: str) -> None:
        """Live stopped for the plot's folder: shots held back run once more, at once."""
        if not self.is_closed and path == self.path:
            self.follow.live_ended()
            self._follow_timer.stop()
            self._follow_next()

    @pyqtSlot()
    def _follow_next(self) -> None:
        """Run on the newest revision waiting if the run in flight has ended and the policy
        allows; else wait for the policy's delay, or for more shots."""
        if self.is_closed:
            return
        view, wait = self.follow.due(time.monotonic())
        if view is not None:
            # While Live watches the folder (not the catch-up once it stops: the feed has dropped it).
            self._submit(view, live=self.live() is not None)
            return
        if wait > 0:
            self._follow_timer.start(max(1, math.ceil(wait * 1000)))
        self._show_follow()

    @pyqtSlot()
    def _live_settings_changed(self) -> None:
        values = self.live_values()
        self.follow.policy = policy_of(values, self.policy)
        if not values.get(FOLLOW, True):
            self.follow.pin(self._shown_view)  # Not newer data a run in flight may bring.
            self._follow_timer.stop()
        elif not self.follow.on:
            self.follow.unpin()
            if (latest := self.live()) is not None:
                self.follow.offer(latest)  # Catch up with what came while pinned.
        self._follow_next()

    def follow_text(self) -> str:
        """The plot's Live state for its source line: ``following Live · 3 new shots waiting``
        ("" when Live doesn't watch its folder and nothing waits)."""
        live = self.live()
        follow = self.follow
        if not follow.on:
            if live is None:
                return ""
            added, other = changes(live, follow.ran)
            return "pinned (Follow Live off)" + (f" · {shots_text(added, other, 'newer')}" if added + other else "")
        parts = ["following Live"] if live is not None else []
        shown = self.shown.input if self.shown is not None else None
        if follow.running and shown is not None and follow.ran.key != shown:
            parts.append(f"updating to rev {follow.ran.revision}")
        added, other = follow.changes()
        waiting, shots = added + other, shots_text(added, other)
        if not waiting:
            pass
        elif live is None:
            parts.append(f"Live off · {shots} waiting")  # The catch-up, after the run in flight.
        elif self._follow_timer.isActive():
            parts.append(f"{shots} waiting (runs {follow.policy.min_delay:g} s after the last run)")
        elif follow.running:
            parts.append(f"{shots} waiting")
        else:
            parts.append(f"{shots} waiting (runs every {follow.policy.every_shots:,})")
        return " · ".join(parts)

    def _show_follow(self) -> None:
        """The source line's Live state and error, the settings' input line and title."""
        following = self.follow.on and self.live() is not None
        if self.waiting():
            self.input_label.setText(f"Input: {self.view.identity.name} (waiting for its data)")
        else:
            self.input_label.setText(f"Input: {self._shown_key().short()}"
                                     + (" · following Live" if following else " (stays with this plot)"))
        dock, plots = self.dock_widget, self.workspace
        if dock is None or plots is None or sip.isdeleted(dock):
            return
        dock.setProperty("plotFollow", self.follow_text())
        dock.setProperty("plotFollowing", following)
        dock.setProperty("plotError", " · ".join(filter(None, (self.error or self._reload_note,
                                                               self._constants_note, self._cache_note))))
        plots.update_plot_source(dock)
        if self.param_tab is not None:
            plots.panel_right_top_plot_settings.set_title(dock, self._title())

    def _shown_key(self) -> ViewKey:
        """The data the plot shows (before its first result: what it runs on)."""
        return self.shown.input if self.shown is not None else self.view.key

    def _title(self) -> str:
        if is_waiting(self._shown_view or self.view) and self.shown is None:
            return f"{self.name} ({self.instance_id}) · {self.view.identity.name} · waiting for its data"
        return f"{self.name} ({self.instance_id}) · {self._shown_key().short()}"

    @staticmethod
    def _message(text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        return label

    # The RAM budget (helab/analysis/budget.py)

    @property
    def is_released(self) -> bool:
        return self.released is not None

    def following(self) -> bool:
        """Whether the plot follows Live now (Live watches its folder and Follow Live is on)."""
        return self.follow.on and self.live() is not None

    def ram_buffers(self) -> Buffers:
        """The memory this plot's data uses: the views it shows, runs on or holds waiting, and
        its results' arrays, older ones RamResults keeps included; once released, its picture
        (its view keeps no events)."""
        merged: Buffers = dict(self.released.ram_buffers()) if self.released is not None else {}
        for view in (self.follow.ran, self.follow.pending, self._shown_view, self._job_view):
            if view is not None:
                merged.update(view_buffers(view))
        kept = [(job, self.runner.results.peek(job)) for job in self._runs]
        self._runs = [job for job, result in kept if result is not None or job == self.job_id]
        results = {id(result): result for result in (self.shown, self.result, *(result for _, result in kept))
                   if result is not None}
        for result in results.values():
            merged.update(buffers(arrays_in(result.data)))
        try:
            merged.update(self.script.plot_buffers(self.action, self.instance_id))
        except Exception:  # A script's hook never stops the budget's count.
            logging.exception("%s: plot_buffers failed", self.name)
        return merged

    def _forget_runs(self) -> None:
        """Its older results go from RamResults (released or closed: nothing reads them again)."""
        for job in self._runs:
            if job != self.job_id:
                self.runner.results.discard(job)
        self._runs = [self.job_id] if self.job_id else []

    def ram_label(self) -> str:
        return self._title()

    def releasable(self) -> bool:
        """Whether the budget may release it: a plot drawn, not released, not running or
        reloading, nothing waiting to run, not following Live. (The budget never offers the
        shown plot.)"""
        content = self._content
        return (not self.is_closed and self.released is None and not self.job_id and not self._reload_owner
                and self.shown is not None and content is not None and not sip.isdeleted(content)
                and self.dock_widget is not None and self.follow.pending is None and not self.following())

    def picture_cost(self) -> int:
        """What its picture took last time it was released or tried (0: not known yet)."""
        return self._picture_cost

    def release(self, frees: Optional[int] = None) -> bool:
        """Free the plot's data to keep RAM within the budget: its views and results go, and a
        picture of the plot stays in its place (no longer interactive), with Reload. It keeps
        its shot numbers and fingerprints, to reload exactly those (``reload``). With ``frees``
        (the bytes releasing it frees), not if its picture would take as much. Whether it did."""
        if not self.releasable():
            return False
        assert self.shown is not None and self._content is not None
        area = self.workspace.middle_mainwindow if self.workspace is not None else None
        picture = snapshot(self._content, area.size() if isinstance(area, QWidget) else QSize())
        self._picture_cost = len(picture.png)
        if frees is not None and self._picture_cost >= frees:
            return False  # It would cost more than it frees.
        last, shown = self.result, self.runner.results.released(self.shown)
        self.result = shown if last is None or last is self.shown else self.runner.results.released(last)
        self.shown = shown
        self._forget_runs()
        try:
            self.script.plot_released(self.action, self.instance_id, self.path)
        except Exception:  # A script's cleanup never stops a release.
            logging.exception("%s: plot_released failed", self.name)
        drawn = self._shown_view or self.follow.ran
        view = hollow(drawn)
        self.follow.ran = view if self.follow.ran is drawn else hollow(self.follow.ran)
        self._shown_view = view
        self.released = ReleasedPlot(picture, self.reload)
        self._content = self.released
        self._swap_content(self.released)
        self.status_label.setText("Released to free RAM: Reload or Rerun draws it again")
        self._show_follow()
        logging.info("Released plot %s (RAM budget)", self._title())
        return True

    def _swap_content(self, content: QWidget) -> None:
        """Show ``content`` in the dock in place of the plot, keeping its source lines."""
        dock, plots = self.dock_widget, self.workspace
        if dock is None or sip.isdeleted(dock):
            content.deleteLater()
            return
        if plots is not None:
            plots.replace_plot_content(dock, content)
            return
        old = dock.widget()
        dock.setWidget(content)
        if old is not None:
            old.deleteLater()

    @pyqtSlot(QDockWidget)
    def _plot_shown(self, dock: QDockWidget) -> None:
        """Shown again (its settings show): a released plot reloads, if Settings → Cache says so."""
        if (dock is self.dock_widget and self.released is not None and self.budget is not None
                and self.budget.auto_reload and not self._nowhere):
            self.reload()

    def recently_reloaded(self) -> bool:
        """Drawn again by a reload in the last ``RELOAD_GRACE`` seconds: the budget releases
        other plots before it, so two plots don't keep releasing and reloading each other."""
        return time.monotonic() - self.reloaded_at < RELOAD_GRACE

    @pyqtSlot(str)
    def _folder_changed(self, path: str) -> None:
        """The folder's data in RAM or its disk cache changed: a reload may find it now."""
        if self._nowhere and FolderCache.key(path) == FolderCache.key(self.path):
            self._nowhere = False

    def _cache(self) -> FolderCache:
        if self._given_cache is not None:
            return self._given_cache
        return self.budget.cache if self.budget is not None else get_folder_cache(get_io_service())

    def reload(self, values: Optional[Dict[str, Any]] = None) -> None:
        """Draw a released plot again: by default with the settings it was drawn with, on exactly
        the shots it drew (``coverage``), by their fingerprints, never a shot it didn't draw; with
        ``values`` (Rerun's new settings), on its view's shots. From the folder's dataset in RAM,
        else from the local disk cache, never from the folder. If neither has them, it says so
        and keeps its picture; shots changed or missing are left out and named."""
        if self.is_closed or self.released is None or self.shown is None or self.job_id:
            return
        self._reload_values = dict(self.shown.parameters) if values is None else values
        # Drawn again as it was: with the constants it was drawn with (new settings resolve anew).
        self._reload_constants = self.shown.constant_layers if values is None else None
        self._reload_shots = tuple(self.shown.coverage.shots) if values is None else None
        if self._reload_owner:
            return  # Reading the disk cache already.
        cache, view = self._cache(), self._shown_view or self.follow.ran
        found = self._in_ram(cache, view, self._reload_shots)
        if found is not None and not found.changed and not found.missing:
            self._reload_from(found, "RAM")
            return
        self._reload_found = found
        if self._read_disk_cache(cache, view.identity.source_path):
            self.released.set_state("reading the disk cache…", busy=True)
            self.status_label.setText("Reloading from the disk cache…")
            return
        self._reload_found = None
        if found is not None:
            self._reload_from(found, "RAM")
        else:
            self._reload_failed("its data isn't in RAM or in the disk cache")

    @staticmethod
    def _in_ram(cache: FolderCache, view: DatasetView, shots: Optional[Tuple[int, ...]]) -> Optional[Restored]:
        """The folder's dataset held in RAM (shown in a tab or not) with most of the shots wanted."""
        path = cache.key(view.identity.source_path)
        held = {id(entry): entry for entry in (*cache.pins.values(), *cache.datasets.values()) if entry.path == path}
        found = [restore(view, entry, shots) for entry in held.values()]
        return max(found, key=lambda item: (len(item.kept), -len(item.changed)), default=None)

    def _read_disk_cache(self, cache: FolderCache, path: str) -> bool:
        """Ask a helper for the folder's dataset from the local disk cache (the local lane: it
        never reads the folder). False if the disk cache is off or can't be asked now."""
        options = store_options()
        if not options or path in cache.mismatched:
            return False
        owner = f"plot-reload:{uuid4().hex}"
        cache.resultReady.connect(self._reload_event)
        self._reload_owner = owner
        if cache.submit(owner, 0, path, "cached",
                        {"cache": options, "verified_volumes": cache.verified_volumes(),
                         "limits": cache.large_limits(), "deliberate": True, "allow_large": True}, priority=True):
            return True
        self._end_disk_read(cache)
        return False

    def _end_disk_read(self, cache: FolderCache) -> None:
        owner, self._reload_owner = self._reload_owner, ""
        if owner:
            try:
                cache.resultReady.disconnect(self._reload_event)
            except TypeError:
                pass
            cache.cancel(owner)

    @pyqtSlot(object, object)
    def _reload_event(self, request: IORequest, event: Dict[str, Any]) -> None:
        if request.owner != self._reload_owner or self.is_closed:
            return
        kind = event.get("kind")
        dataset = event.get("dataset")
        if kind not in ("loaded", "error", "too_large", "cancelled"):
            return  # Progress.
        cache = self._cache()
        self._end_disk_read(cache)
        found, self._reload_found = self._reload_found, None
        if self.released is None or self.shown is None:
            return
        if self.job_id:
            # A run started meanwhile (Live's next revision): it draws the plot, not this reload.
            self._reload_values = self._reload_shots = None
            self.released.set_state("", busy=True)
            return
        view = self._shown_view or self.follow.ran
        read = restore(view, dataset, self._reload_shots) if kind == "loaded" and isinstance(dataset, Dataset) else None
        if read is not None and (found is None or len(read.kept) >= len(found.kept)):
            self._reload_from(read, "the disk cache")
        elif found is not None:
            self._reload_from(found, "RAM")
        else:
            why = str(event.get("message") or "") if kind == "error" else (
                "it is too large to read back" if kind == "too_large" else "")
            self._reload_failed("its data isn't in RAM, and the disk cache couldn't give it"
                                + (f" ({why})" if why else ""))

    def _reload_from(self, found: Restored, where: str) -> None:
        """Run on the restored view; name the plot's shots it lacks."""
        assert self.released is not None and self.shown is not None
        changed, missing, asked = found.changed, found.missing, found.asked
        if asked and not found.kept:
            self._reload_failed(f"none of its {asked:,} shots are in RAM or the disk cache as they were")
            return
        lost = []
        if changed:
            lost.append(f"shot{'' if len(changed) == 1 else 's'} {shots_list(changed)} changed since")
        if missing:
            lost.append(f"shot{'' if len(missing) == 1 else 's'} {shots_list(missing)} missing")
        self._reload_note = (f"Reloaded from {where} without {len(changed) + len(missing):,} of its "
                             f"{asked:,} shots: {'; '.join(lost)}") if lost else ""
        values, self._reload_values = self._reload_values, None
        constants, self._reload_constants = self._reload_constants, None
        self.released.set_state(f"reloading from {where}…", busy=True)
        self._submit(found.view, values, reloading=True, constants=constants, one_off=True)
        self.status_label.setText(f"Reloading from {where}…")

    def _reload_failed(self, why: str) -> None:
        """Nothing to reload from: the picture stays and says why. Showing it again won't try
        again until the folder's data or disk cache changes."""
        self._reload_values = None
        self._nowhere = True
        if not self._watching_folder:
            cache = self._cache()
            cache.datasetChanged.connect(self._folder_changed)
            cache.diskCacheChanged.connect(self._folder_changed)
            self._watching_folder = True
        if self.released is not None:
            self.released.set_state(f"can't reload: {why}")
        self.status_label.setText(f"Can't reload: {why}. Load the folder again, then Reload.")
        self._show_follow()

    @pyqtSlot()
    def close(self) -> None:
        if self.is_closed:
            return
        self._end_wait()
        self._follow_timer.stop()
        if self.job_id:
            self.runner.cancel(self.job_id)
        if self.shown is not None:
            self.runner.results.unpin(self.shown.job_id)
        self._forget_runs()
        if self._reload_owner:
            self._end_disk_read(self._cache())
        if self._watching_folder:
            cache = self._cache()
            for signal in (cache.datasetChanged, cache.diskCacheChanged):
                try:
                    signal.disconnect(self._folder_changed)
                except TypeError:
                    pass
        plots = self.workspace
        panel = (plots.panel_right_top_plot_settings
                 if self.param_tab is not None and plots is not None and not sip.isdeleted(plots.host) else None)
        for signal, slot in ((self.runner.finished, self._finished),
                             *(((self.feed.revised, self._revised), (self.feed.ended, self._live_ended))
                               if self.feed is not None else ()),
                             *(((panel.plotShown, self._plot_shown),) if panel is not None and not sip.isdeleted(panel)
                               else ())):
            try:
                signal.disconnect(slot)
            except TypeError:
                pass
        if self.constant_keys:
            try:
                self._cache().constantsChanged.disconnect(self._constants_changed)
            except TypeError:
                pass
        if self.budget is not None:
            self.budget.remove(self)
        try:
            self.script.plot_closed(self.action, self.instance_id, self.path)
        except Exception:  # A script's cleanup never stops a plot from closing.
            logging.exception("%s: plot_closed failed", self.name)
        super().close()


