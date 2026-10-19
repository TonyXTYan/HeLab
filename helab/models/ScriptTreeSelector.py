from __future__ import annotations
import logging
import math
import os
import time
from typing import Any, Callable, Dict, Optional, cast, no_type_check, TYPE_CHECKING, List, Tuple, Union, Literal

from PyQt6 import sip
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QWindow
# from uuid import uuid4

# Import QWidget types first to avoid forward references
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QVBoxLayout,
    QTreeWidgetItem, QHeaderView, QDockWidget, QFileDialog,
    QComboBox, QMainWindow, QApplication, QStackedWidget, QTabBar, QToolButton
)
from pyqtgraph.parametertree import Parameter

from helab.analysis.dataset_view import DatasetView, ViewKey
from helab.analysis.follow import FOLLOW, Follow, LiveFeed, changes, live_specs, policy_of, shots_text
from helab.analysis.parameter_tree import build_tree, parameter_of, settings_widget, tree_values
from helab.analysis.parameters import describe
from helab.analysis.results import AnalysisResult
from helab.analysis.runner import AnalysisRunner, get_analysis_runner
from helab.scripts import standard
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.utils.constants import QDOCKWIDGET_STYLESHEET
from helab.scripts.scripts_manager import ScriptsManager
if TYPE_CHECKING:
    from helab.views.FolderExplorer import FolderExplorer
    from helab.views.HelabMainWindow import HelabMainWindow

import numpy.typing as npt
import numpy as np

# A wrapped object's C++ address (PyQt6's stub types it as returning None).
address_of = cast(Callable[[QObject], int], sip.unwrapinstance)


class AnalysisDock(QDockWidget):
    """A plot dock that says when the user closes it (hiding, e.g. behind another tabbed
    dock, is not closing)."""
    closed = pyqtSignal()

    def closeEvent(self, event: QCloseEvent | None) -> None:
        super().closeEvent(event)
        self.closed.emit()


class DockTabCloser(QObject):
    """Gives the tabs of docks tabbed together in ``area`` a close button that closes that dock.
    Qt makes those tab bars itself as docks are tabbed; they are fitted on the next pass of the
    event loop after a watched dock is added, moved, floated, docked, shown or hidden (dock
    signals, no event filter). A tab is matched to its dock by identity: Qt's dock tab bars
    keep each tab's dock widget as its tab data (its address). Titles needn't be unique."""

    def __init__(self, area: QMainWindow) -> None:
        super().__init__(area)
        self.area = area
        self._fit_soon = QTimer(self)
        self._fit_soon.setSingleShot(True)
        self._fit_soon.setInterval(0)
        self._fit_soon.timeout.connect(self.fit)

    def watch(self, dock: QDockWidget) -> None:
        for signal in (dock.dockLocationChanged, dock.topLevelChanged, dock.visibilityChanged):
            signal.connect(self.schedule_fit)
        self.schedule_fit()

    @pyqtSlot()
    def schedule_fit(self) -> None:
        self._fit_soon.start()

    def fit(self) -> None:
        layout = self.area.layout()
        if layout is not None:
            layout.activate()  # Qt makes or reuses the tab bars as it lays the docks out.
        for bar in self.area.findChildren(QTabBar, options=Qt.FindChildOption.FindDirectChildrenOnly):
            if not bar.property("helabClosable"):
                bar.setProperty("helabClosable", True)
                bar.setTabsClosable(True)
                bar.tabCloseRequested.connect(lambda index, bar=bar: self.close_tab(bar, index))

    def close_tab(self, bar: QTabBar, index: int) -> None:
        dock = self.dock_at(bar, index)
        if dock is not None:
            dock.close()

    def dock_at(self, bar: QTabBar, index: int) -> Optional[QDockWidget]:
        """The dock of tab ``index`` (None if Qt ever stops keeping it as the tab data)."""
        address = bar.tabData(index)
        for dock in self.area.findChildren(QDockWidget):
            if address_of(dock) == address:
                return dock
        return None


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
        main_window: Reference to main window for cleanup
    """
    
    ended = pyqtSignal(str)  # instance_id, once closed

    def __init__(self, name: str, instance_id: str, main_window: Optional['HelabMainWindow']):
        super().__init__()
        self.name = name
        self.instance_id = instance_id
        self.main_window = main_window
        self.dock_widget: Optional[QDockWidget] = None
        self.param_tab: Optional[QWidget] = None
        self.is_closed = False
        
    def setup_dock_widget(self, content: QWidget) -> None:
        """Create and setup the dock widget."""
        if not self.main_window:
            return
            
        dock = AnalysisDock(f"{self.name} ({self.instance_id})", self.main_window)
        dock.setStyleSheet(QDOCKWIDGET_STYLESHEET)
        dock.setWidget(content)
        dock.closed.connect(self.close)
        # A dock deleted unclosed (its window went) still ends the run and its connections.
        dock.destroyed.connect(self.close)
        self.dock_widget = dock
        
    def setup_param_tab(self, param_tree: QWidget, title: str = "") -> None:
        """Add this plot's page to the Settings panel (after its dock is made)."""
        if not self.main_window or self.dock_widget is None:
            return
        self.param_tab = param_tree
        self.main_window.panel_right_top_plot_settings.add_plot(
            self.dock_widget, param_tree, title or f"{self.name} ({self.instance_id})")
        
    @pyqtSlot()
    def close(self) -> None:
        """Close and cleanup both components (only what is still there: after the main window
        went, its widgets are deleted already)."""
        if self.is_closed:
            return
            
        self.is_closed = True
        self.ended.emit(self.instance_id)
        window, dock = self.main_window, self.dock_widget
        if window is None or sip.isdeleted(window):
            return
        if dock is not None and dock in window.dock_widgets:
            window.dock_widgets.remove(dock)
        if self.param_tab is not None and not sip.isdeleted(self.param_tab):
            self.param_tab.deleteLater()
        if dock is None or sip.isdeleted(dock):
            return  # Deleted with the plot area: the Settings panel drops the page itself.
        window.middle_mainwindow.removeDockWidget(dock)
        dock.deleteLater()
        if self.param_tab is not None:
            window.panel_right_top_plot_settings.remove_plot(dock)
        update = getattr(window, "update_placeholder_visibility", None)
        if callable(update):
            update()


class AnalysisInstance(LinkedAnalysisInstance):
    """One plot of a dataset analysis: its dock and settings page, bound to the dataset view it
    started with. **Rerun with these settings** runs again on that data (cancelling a run in
    flight: the settings changed); a run on other data is a new plot (the script's button).

    A plot of the folder Live watches follows it (roadmaps/live-monitoring.md, L3): each newer
    revision of the folder's view (``LiveFeed``) is offered to it, and it reruns on the newest
    one as its Live settings allow (``Follow``: hold and coalesce, never cancelled for new data).
    Turning Follow Live off pins it at its revision. A failed run keeps the last plot drawn,
    with the error in amber, and following goes on."""

    def __init__(self, metadata: ScriptMetadata, script: DatasetAnalysis, action: str, view: DatasetView,
                 instance_id: str, main_window: Optional['HelabMainWindow'],
                 runner: Optional[AnalysisRunner] = None) -> None:
        super().__init__(metadata.name, instance_id, main_window)
        self.metadata, self.script, self.action = metadata, script, action
        self.runner = runner or get_analysis_runner()
        self.job_id = ""
        # The last result (whatever its state), and the completed one whose plot shows.
        self.result: Optional[AnalysisResult] = None
        self.shown: Optional[AnalysisResult] = None
        # The data of the run in flight, and of the result shown (what Follow Live off pins).
        self._job_view: Optional[DatasetView] = None
        self._shown_view: Optional[DatasetView] = None
        self.error = ""  # The last run's failure, while the plot before it stays
        self.policy = script.live_policy(action)
        self.follow = Follow(view, self.policy)
        self.parameter_root: Optional[Parameter] = None
        self.status_label = QLabel()
        self.input_label = QLabel()
        feed = getattr(main_window, "live_feed", None)
        self.feed: Optional[LiveFeed] = feed if isinstance(feed, LiveFeed) else None
        self._follow_timer = QTimer(self)
        self._follow_timer.setSingleShot(True)
        self._follow_timer.timeout.connect(self._follow_next)
        self.runner.finished.connect(self._finished)
        if self.feed is not None:
            self.feed.revised.connect(self._revised)
            self.feed.ended.connect(self._live_ended)

    @property
    def view(self) -> DatasetView:
        """The plot's data: the input of its run in flight, or of its last run."""
        return self.follow.ran

    @property
    def path(self) -> str:
        return self.follow.ran.identity.source_path

    def start(self) -> None:
        """Open the dock and its settings page, then run with the defaults."""
        self.setup_dock_widget(self._message(f"Running {self.name} on {self.view.key.short()}…"))
        specs = self.script.parameters(self.action)
        live = live_specs(self.policy, specs[0].page if specs else "")
        self.parameter_root = build_tree([*specs, *live])
        for spec in live:
            parameter_of(self.parameter_root, spec).sigValueChanged.connect(self._live_settings_changed)
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.input_label.setToolTip(self.path)
        layout.addWidget(self.input_label)
        layout.addWidget(settings_widget(self.parameter_root, [*specs, *live]), 1)
        self.rerun_button = QPushButton("Rerun with these settings")
        self.rerun_button.setEnabled(bool(specs))
        self.rerun_button.clicked.connect(self.run)
        layout.addWidget(self.rerun_button)
        layout.addWidget(self.status_label)
        self.setup_param_tab(tab, self._title())
        self.run()

    def values(self) -> Dict[str, Any]:
        """The analysis's parameters as set (not the plot's Live settings)."""
        root = self.parameter_root
        return tree_values(root, self.script.parameters(self.action)) if root is not None else {}

    def live_values(self) -> Dict[str, Any]:
        root = self.parameter_root
        return tree_values(root, live_specs(self.policy)) if root is not None else {}

    def run(self) -> None:
        """Run with the settings shown, on the newest data the plot has (what waits for it while
        it follows Live, else its own); a run in flight is cancelled, its settings are old."""
        if self.is_closed:
            return
        if self.job_id:
            self.runner.cancel(self.job_id)
        self._submit(self.follow.latest)

    def _submit(self, view: DatasetView) -> None:
        self._follow_timer.stop()
        try:
            context = self.runner.submit(self.script, self.metadata, self.action, view, self.values())
        except RuntimeError as error:  # The runner is stopping: HeLab is closing.
            self.status_label.setText(str(error))
            return
        self.job_id, self._job_view = context.job_id, view
        self.follow.start(view)
        self.status_label.setText(f"Running ({context.job_id})…")
        self._show_follow()

    def _finished(self, result: AnalysisResult) -> None:
        if self.is_closed or result.job_id != self.job_id:
            return
        self.job_id = ""
        self.follow.end(time.monotonic())
        view, self._job_view = self._job_view, None
        if result.state == "cancelled":
            self.status_label.setText("Cancelled")
            self._show_follow()
            return
        if not self.follow.on and view is not None and view.key != self.follow.ran.key:
            # A Live rerun that started before Follow Live went off: the plot stays pinned.
            self.status_label.setText(f"Pinned at rev {self.follow.ran.revision}: "
                                      f"the run on rev {view.revision} isn't shown")
            self._show_follow()
            return
        self.result = result
        specs = self.script.parameters(self.action)
        warnings = "; ".join(self.script.parameter_warnings(self.action, result.parameters))
        content: Optional[QWidget] = None
        error = result.error if result.state == "failed" else ""
        if result.state == "completed":
            self._show_detected(result)
            try:
                content = self.script.render(result)
            except Exception as exc:
                logging.exception("Could not draw %s", self.name)
                error = f"could not draw it: {exc}"
        if error:
            self.status_label.setText(f"Failed: {error}")
            if self.shown is not None:
                # The last plot stays; the error shows above it until a run succeeds.
                self.error = f"rev {result.input.revision} failed: {error} · showing rev {self.shown.input.revision}"
                self._show_follow()
                self._follow_next()
                return
            content = self._message(f"{self.name} failed: {error}")
        else:
            self.status_label.setText(f"⚠ {warnings}" if warnings else "")
        assert content is not None
        self.error = ""
        if self.shown is not None:
            self.runner.results.unpin(self.shown.job_id)
            self.shown = None
        if result.state == "completed" and not error:
            self.shown, self._shown_view = result, view
            self.runner.results.pin(result.job_id)
        self._show_content(content, result, specs, warnings)
        self._follow_next()

    def _show_content(self, content: QWidget, result: AnalysisResult, specs: List[Any], warnings: str) -> None:
        if self.dock_widget is None:
            content.deleteLater()
            return
        show = getattr(self.main_window, "set_plot_result", None)
        if callable(show):
            chosen, settings = self.script.describe_run(self.action, result.parameters, self.view)
            record = describe(specs, result.parameters, every=True)
            if warnings:
                settings = " · ".join(filter(None, (settings, f"⚠ {warnings}")))
                record = f"{record}\nWarning: {warnings}"
            show(self.dock_widget, content, result, settings, record, chosen)
        else:
            old = self.dock_widget.widget()
            self.dock_widget.setWidget(content)
            if old is not None:
                old.deleteLater()
        self._show_follow()

    def _show_detected(self, result: AnalysisResult) -> None:
        """Put what the run found into the settings (they don't rerun it)."""
        root = self.parameter_root
        if root is None:
            return
        specs = {spec.name: spec for spec in self.script.parameters(self.action)}
        for name, value in self.script.detected_parameters(self.action, result).items():
            if name in specs:
                parameter_of(root, specs[name]).setValue(specs[name].coerce(value))

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
            self._submit(view)
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
        self.input_label.setText(f"Input: {self._shown_key().short()}"
                                 + (" · following Live" if following else " (stays with this plot)"))
        dock, window = self.dock_widget, self.main_window
        if dock is None or window is None or sip.isdeleted(dock):
            return
        dock.setProperty("plotFollow", self.follow_text())
        dock.setProperty("plotFollowing", following)
        dock.setProperty("plotError", self.error)
        update = getattr(window, "update_plot_source", None)
        if callable(update):
            update(dock)
        if self.param_tab is not None:
            window.panel_right_top_plot_settings.set_title(dock, self._title())

    def _shown_key(self) -> ViewKey:
        """The data the plot shows (before its first result: what it runs on)."""
        return self.shown.input if self.shown is not None else self.view.key

    def _title(self) -> str:
        return f"{self.name} ({self.instance_id}) · {self._shown_key().short()}"

    @staticmethod
    def _message(text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        return label

    @pyqtSlot()
    def close(self) -> None:
        if self.is_closed:
            return
        self._follow_timer.stop()
        if self.job_id:
            self.runner.cancel(self.job_id)
        if self.shown is not None:
            self.runner.results.unpin(self.shown.job_id)
        for signal, slot in ((self.runner.finished, self._finished),
                             *(((self.feed.revised, self._revised), (self.feed.ended, self._live_ended))
                               if self.feed is not None else ())):
            try:
                signal.disconnect(slot)
            except TypeError:
                pass
        super().close()


GroupType = Literal["dynamic"]

class GroupData:
    """Stores information about a script group in the tree widget.
    
    This class maintains the state and metadata for each script group, including:
    - The group's name and type (scripts registered with the ScriptsManager)
    - Reference to the group's tree widget item
    - Loading status
    
    The group's tree item is set when the group is displayed in the tree widget,
    and the loading status helps prevent duplicate loading of group contents.
    """
    def __init__(self, name: str, group_type: GroupType):
        self.name = name
        self.type = group_type
        self.tree_item: Optional[QTreeWidgetItem] = None
        self.is_loaded = False

class TreePanelWidget(QWidget):
    """A widget that displays and manages analysis scripts in a tree structure.
    
    This widget provides:
    1. A GUI for browsing and organizing analysis scripts
    2. Script grouping by each script's metadata group
    3. Action buttons for executing script functions
    4. Dynamic loading of scripts from directories
    
    The widget consists of:
    - A group selector dropdown
    - A "Load Scripts" button for importing new scripts
    - A tree view showing scripts organized by groups
    - Action buttons for each script
    
    Key concepts:
    - Groups: HeLab's bundled analyses ("Basic plots v1", `helab.scripts.standard.group`) and those of scripts loaded from a folder
    - Actions: Each script can have up to 2 executable actions
    """
    
    # Signal emitted when selected group changes (group_name, group_type)
    group_changed = pyqtSignal(str, str)
    
    def __init__(self, helab_main_window: Optional[HelabMainWindow] = None,
                 parent: Any = None) -> None:
        super().__init__(parent)

        self.helab_main_window = helab_main_window
        self.script_manager = ScriptsManager()
        
        # Group tracking
        self.groups: Dict[str, GroupData] = {}
        self.current_group: Optional[GroupData] = None
        
        # Analysis instance tracking
        self._instance_counter = 0
        self._analysis_instances: Dict[str, LinkedAnalysisInstance] = {}

        # Layout for the right-bottom panel
        self.panel_layout_right_bottom = QVBoxLayout(self)
        self.panel_layout_right_bottom.setContentsMargins(0, 0, 0, 0)

        # Add controls at the top
        controls_layout = QHBoxLayout()
        
        # Add group selector
        self.group_selector = QComboBox()
        self.group_selector.currentTextChanged.connect(self._on_group_changed)
        controls_layout.addWidget(QLabel("Group:"))
        controls_layout.addWidget(self.group_selector)

        # Add script directory button
        self.load_dir_button = QPushButton("Load Scripts...")
        self.load_dir_button.clicked.connect(self._on_load_directory)
        controls_layout.addWidget(self.load_dir_button)

        controls_layout.addStretch()
        self.panel_layout_right_bottom.addLayout(controls_layout)

        # Tree list widget
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["Script", "Run", "Run"])
        self.tree_widget.setColumnCount(3)
        header = self.tree_widget.header()
        if header:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
            header.setStretchLastSection(False)
            self.tree_widget.setColumnWidth(1, 100)
            self.tree_widget.setColumnWidth(2, 100)

        # Dictionary to map group names to QTreeWidgetItem objects
        self.group_mapping: Dict[str, QTreeWidgetItem] = {}

        # Add tree widget to the layout
        self.panel_layout_right_bottom.addWidget(self.tree_widget)

        # HeLab's bundled analyses
        self._load_default_scripts()

        logging.info(f"TreePanelWidget initialized. {type(self.parent()) = }")

    def _register_group(self, name: str, group_type: GroupType) -> None:
        """Register a new group with type tracking in the widget.
        
        Creates and tracks a new GroupData instance for managing script groups.
        Only registers if the group doesn't already exist to prevent duplicates.
        
        Args:
            name: The unique name for the group
            group_type: Type of group (only "dynamic": scripts from the ScriptsManager)
        """
        if name not in self.groups:
            self.groups[name] = GroupData(name, group_type)
            logging.debug(f"Registered group: {name} (type: {group_type})")

    def _load_default_scripts(self) -> None:
        """Register HeLab's bundled analyses (``helab.scripts.standard``) and show the first group."""
        for module in standard.MODULES:
            try:
                self.script_manager.load_module(module)
            except Exception as e:
                logging.error(f"Error loading bundled analyses from {module.__name__}: {e}")
        self._update_groups()
        if self.group_selector.count() > 0:
            self.group_selector.setCurrentIndex(0)

    def _on_load_directory(self) -> None:
        """Handle loading a new script directory selected by the user.
        
        This method:
        1. Opens a file dialog for directory selection
        2. Loads Python script files from the selected directory
        3. Updates available groups in the UI
        4. Reloads the current group if one is selected
        
        Error handling:
        - Logs any errors that occur during script loading
        - Maintains UI state even if script loading fails
        """
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "Select Script Directory",
            os.path.expanduser("~"),
            QFileDialog.Option.ShowDirsOnly
        )
        
        if dir_path:
            try:
                self.script_manager.load_directory(dir_path)
                self._update_groups()
                if self.group_selector.currentText():
                    self._load_current_group()
            except Exception as e:
                logging.error(f"Error loading scripts: {e}")

    def _update_groups(self) -> None:
        """Update the group selector with available groups.
        
        This method manages the UI state when groups are added or removed:
        1. Preserves the current selection if possible
        2. Updates the dropdown with all available groups
        3. Attempts to restore the previous selection
        4. Falls back to first item if previous selection is gone
        5. Clears the tree widget if no groups are available
        
        This provides a smooth transition when the available groups change,
        maintaining user selection when possible while ensuring the UI
        stays in a valid state.
        """
        current = self.group_selector.currentText()
        groups = self.script_manager.get_groups()
        # Groups of newly loaded scripts are registered before they are listed.
        for group in groups:
            self._register_group(group, "dynamic")
        self.group_selector.clear()
        if groups:
            self.group_selector.addItems(groups)
            
            # Try to restore previous selection
            index = self.group_selector.findText(current)
            if index >= 0:
                self.group_selector.setCurrentIndex(index)
            else:
                self.group_selector.setCurrentIndex(0)
        else:
            self.tree_widget.clear()
            self.group_mapping.clear()

    def _on_group_changed(self, group_name: str) -> None:
        """Handle group selection changes in the UI.
        
        This method is called when the user selects a different group:
        1. Validates that the selected group exists
        2. Updates current group tracking
        3. Loads the group's scripts and items
        4. Emits group_changed signal for parent widgets
        
        Args:
            group_name: Name of the newly selected group
            
        The method ensures proper error handling and state management
        when switching between groups.
        """
        if group_name:
            if group_name in self.groups:
                group_data = self.groups[group_name]
                self.current_group = group_data
                self._load_current_group()
                self.group_changed.emit(group_name, group_data.type)
            else:
                logging.error(f"Unknown group: {group_name}")

    def _load_current_group(self) -> None:
        """Load the currently selected group's scripts into the tree widget.
        
        1. Loads script metadata from ScriptsManager
        2. Creates script class instances
        3. Sets up action buttons for each script
        4. Handles errors by displaying them in red
        
        The loaded scripts appear as child items under their group in the tree,
        with up to two action buttons for each script.
        """
        group_name = self.group_selector.currentText()
        if not group_name or group_name not in self.groups:
            return

        group_data = self.groups[group_name]
        self.current_group = group_data

        # Clear existing items
        self.tree_widget.clear()
        self.group_mapping.clear()

        # Create group item
        group_item = QTreeWidgetItem(self.tree_widget, [group_name])
        group_item.setFirstColumnSpanned(True)
        self.group_mapping[group_name] = group_item
        group_data.tree_item = group_item

        for metadata in self.script_manager.get_scripts_in_group(group_name):
            script_class = self.script_manager.get_script(metadata.script_id)
            if script_class:
                try:
                    script = script_class()
                    actions = script.get_actions()

                    item = QTreeWidgetItem(group_item, [metadata.name])
                    item.setToolTip(0, f"{metadata.description}\n{metadata.identity().text()}")
                    for column, action in enumerate(actions[:2], start=1):
                        self.tree_widget.setItemWidget(
                            item, column, self.create_button(action, self._action_callback(metadata, script, action)))
                except Exception as e:
                    logging.error(f"Error loading script {metadata.name}: {e}")
                    error_item = QTreeWidgetItem(group_item, [f"{metadata.name} (Error)"])
                    error_item.setForeground(0, Qt.GlobalColor.red)

        group_item.setExpanded(True)
        group_data.is_loaded = True

    def _action_callback(self, metadata: ScriptMetadata, script: Any, action: str) -> Callable[[], None]:
        if isinstance(script, DatasetAnalysis):
            def run() -> None:
                self.run_analysis(metadata, script, action)
            return run
        return lambda: script.execute_action(action)

    def run_analysis(self, metadata: ScriptMetadata, script: DatasetAnalysis,
                     action: str) -> Optional[AnalysisInstance]:
        """Run ``action`` on the current tab's shown dataset, in a new plot dock."""
        window = self.helab_main_window
        current = getattr(window, "current_dataset_view", None)
        view = current() if callable(current) else None
        if window is None or not isinstance(view, DatasetView):
            notice = getattr(window, "show_status_notice", None)
            if callable(notice):
                notice(f"{metadata.name}: load a folder's data first")
            return None
        self._instance_counter += 1
        instance_id = f"{self._instance_counter}"
        instance = AnalysisInstance(metadata, script, action, view, instance_id, window)
        self._analysis_instances[instance_id] = instance
        instance.start()
        self._add_dock(instance)
        return instance

    def _add_dock(self, instance: LinkedAnalysisInstance) -> None:
        window, dock = self.helab_main_window, instance.dock_widget
        if window is None or not isinstance(dock, AnalysisDock):
            return
        instance.ended.connect(self._forget_instance)
        settings = window.panel_right_top_plot_settings
        area = window.middle_mainwindow
        settings.follow(area)
        closer = area.findChild(DockTabCloser) or DockTabCloser(area)
        target = self.tab_target(area, window.dock_widgets, settings.current_plot())
        area.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        # In a shown area Qt hides the new dock and shows it later, and it won't tab a plot
        # opened meanwhile with a hidden one: show it now.
        dock.show()
        if target is not None:
            # Plots share the area as tabs; the new one comes to the front.
            area.tabifyDockWidget(target, dock)
            dock.raise_()
        closer.watch(dock)
        window.dock_widgets.append(dock)
        update = getattr(window, "update_placeholder_visibility", None)
        if callable(update):
            update()

    @staticmethod
    def tab_target(area: QMainWindow, open_docks: List[QDockWidget],
                   shown: Optional[QDockWidget]) -> Optional[QDockWidget]:
        """The open plot a new plot is tabbed with in ``area``: the plot whose settings show
        (``shown``) if it is docked there, else the newest docked one. Docked means in the
        area and not floating; a plot behind another tab counts, and whether docks are
        visible yet doesn't matter (``addDockWidget`` shows a dock later, and the area may not
        be shown). Never a floating plot (Qt would put the new one in its old place, beside
        some other plot), nor a hidden plot on its own (unticked in the area's menu: the new
        one would sit alone in its place); a hidden plot in a tab group still stands for that
        group. Closed plots aren't open. None: the new plot docks on its own (no plot open,
        or all floating or hidden)."""
        docked = [dock for dock in open_docks if not sip.isdeleted(dock) and not dock.isFloating()
                  and area.dockWidgetArea(dock) != Qt.DockWidgetArea.NoDockWidgetArea
                  and (not dock.isHidden() or area.tabifiedDockWidgets(dock))]
        if shown in docked:
            return shown
        return docked[-1] if docked else None

    @pyqtSlot(str)
    def _forget_instance(self, instance_id: str) -> None:
        self._analysis_instances.pop(instance_id, None)

    def create_button(self, label: str, callback: Callable[..., Any]) -> QPushButton:
        """Create a standardized action button for script items.
        
        Creates a QPushButton with consistent styling and behavior:
        - Fixed maximum width for visual consistency
        - Connected callback for action handling
        - Standard appearance across all script items
        
        Args:
            label: Text to display on the button
            callback: Function to call when button is clicked
            
        Returns:
            QPushButton: Configured button ready to be added to the UI
        """
        button = QPushButton(label)
        button.setMaximumWidth(100)
        button.clicked.connect(callback)
        return button

class PlotSettingsPanel(QWidget):
    """The settings of the active plot: one page per open plot, showing the page of the plot
    last clicked, focused or brought to the front among tabbed docks, floating ones included.
    The chooser on top names it and picks another plot (raising its dock). A page keeps its
    edits while another plot's page shows. With no plot open, a hint shows instead.

    It follows Qt's own signals, which fire only when something changes: the app's focus
    (a click anywhere in a plot focuses it, as its dock takes click focus), the active window
    (a floating plot), the plot area's tab activations and the plots' visibility (the shown
    plot hidden: the most recently shown plot still visible shows, as when it closes). No
    Python runs per event (no event filter), and the connections end with the panel or
    ``detach()``. Whenever a plot shows, focus left in another plot moves to it, so focus is
    never in a plot other than the shown one, and a click in any other plot changes focus."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.chooser = QComboBox()
        self.chooser.setToolTip("The plot these settings are for; click a plot to show its settings")
        self.chooser.activated.connect(lambda index: self.show_plot(self._order[index], raise_dock=True))
        self.close_button = QToolButton()
        self.close_button.setText("✕")
        self.close_button.setToolTip("Close this plot")
        self.close_button.clicked.connect(self.close_current)
        self.chooser_row = QWidget()
        row = QHBoxLayout(self.chooser_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        row.addWidget(self.chooser, 1)
        row.addWidget(self.close_button)
        layout.addWidget(self.chooser_row)
        self.stack = QStackedWidget()
        self.hint = QLabel("Run a plot from Scripts below; its settings appear here.")
        self.hint.setWordWrap(True)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.stack.addWidget(self.hint)
        layout.addWidget(self.stack, 1)
        self._pages: Dict[QDockWidget, QWidget] = {}
        self._order: List[QDockWidget] = []  # the chooser's order: as opened
        self._recent: List[QDockWidget] = []  # most recently shown last
        self._followed: List[QMainWindow] = []
        self._check_shown = QTimer(self)
        self._check_shown.setSingleShot(True)
        self._check_shown.setInterval(0)
        self._check_shown.timeout.connect(self._shown_still_visible)
        self._update_chooser()
        app = QApplication.instance()
        self._app = app if isinstance(app, QApplication) else None
        if self._app is not None:
            self._app.focusChanged.connect(self._focus_changed)
            self._app.focusWindowChanged.connect(self._window_activated)

    def detach(self) -> None:
        """Stop following the app's focus and tab activations (the window is closing)."""
        if self._app is not None:
            self._app.focusChanged.disconnect(self._focus_changed)
            self._app.focusWindowChanged.disconnect(self._window_activated)
            self._app = None
        for area in self._followed:
            if not sip.isdeleted(area):
                area.tabifiedDockWidgetActivated.disconnect(self._tab_activated)
        self._followed.clear()

    def add_plot(self, dock: QDockWidget, page: QWidget, title: str) -> None:
        """A new plot's page; it shows at once, as its dock comes to the front. The dock takes
        click focus, so a click anywhere in it (title, plot, label) focuses it and shows its page."""
        self._pages[dock] = page
        self._order.append(dock)
        self.stack.addWidget(page)
        self.chooser.addItem(title)
        dock.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        dock.destroyed.connect(self._forget_deleted)
        dock.visibilityChanged.connect(self._visibility_changed)
        self.show_plot(dock)

    def remove_plot(self, dock: QDockWidget) -> None:
        """A closed plot's page goes; the most recently shown plot still open shows."""
        page = self._pages.pop(dock, None)
        if page is None:
            return
        index = self._order.index(dock)
        self._order.pop(index)
        self.chooser.removeItem(index)
        if dock in self._recent:
            self._recent.remove(dock)
        if not sip.isdeleted(page):
            self.stack.removeWidget(page)
        fallback = self._fallback()
        if fallback is not None:
            self.show_plot(fallback)
        else:
            self.stack.setCurrentWidget(self.hint)
        self._update_chooser()

    def show_plot(self, dock: QDockWidget, raise_dock: bool = False) -> None:
        page = self._pages.get(dock)
        if page is None:
            return
        if dock in self._recent:
            self._recent.remove(dock)
        self._recent.append(dock)
        self.stack.setCurrentWidget(page)
        self.chooser.setCurrentIndex(self._order.index(dock))
        self._update_chooser()
        if raise_dock:
            dock.show()
            dock.raise_()
            if dock.isFloating():
                dock.activateWindow()
        # Focus left in another plot (this one came by its tab, its window or the chooser)
        # moves here, so a click back in that plot changes focus and shows it again.
        if self._plot_of(QApplication.focusWidget()) not in (None, dock) and dock.isVisible():
            dock.setFocus(Qt.FocusReason.OtherFocusReason)

    def current_plot(self) -> Optional[QDockWidget]:
        return self._recent[-1] if self._recent else None

    def plots(self) -> List[QDockWidget]:
        """The open plots, in the chooser's order."""
        return list(self._order)

    def page(self, dock: QDockWidget) -> Optional[QWidget]:
        return self._pages.get(dock)

    def set_title(self, dock: QDockWidget, title: str) -> None:
        """A plot's name in the chooser (it changes as the plot follows Live to newer data)."""
        if dock in self._pages:
            self.chooser.setItemText(self._order.index(dock), title)

    def follow(self, area: QMainWindow) -> None:
        """Show a plot's page when its tab is clicked among tabbed docks in ``area``."""
        if area not in self._followed:
            self._followed.append(area)
            area.tabifiedDockWidgetActivated.connect(self._tab_activated)

    def close_current(self) -> None:
        dock = self.current_plot()
        if dock is not None:
            dock.close()

    def _update_chooser(self) -> None:
        self.chooser_row.setVisible(bool(self._order))

    def _plot_of(self, widget: Optional[QWidget]) -> Optional[QDockWidget]:
        while widget is not None:
            if isinstance(widget, QDockWidget) and widget in self._pages:
                return widget
            widget = widget.parentWidget()
        return None

    def _fallback(self, leaving: Optional[QDockWidget] = None) -> Optional[QDockWidget]:
        """The plot to show when the shown one goes: the most recently shown one still
        visible, else the most recently shown one."""
        others = [dock for dock in reversed(self._recent) if dock is not leaving and not sip.isdeleted(dock)]
        return next((dock for dock in others if dock.isVisible()), others[0] if others else None)

    def _activate(self, dock: Optional[QDockWidget]) -> None:
        if dock is not None and dock is not self.current_plot():
            self.show_plot(dock)

    @pyqtSlot(QDockWidget)
    def _tab_activated(self, dock: QDockWidget) -> None:
        self._activate(dock)

    @pyqtSlot(QWidget, QWidget)
    def _focus_changed(self, old: Optional[QWidget], now: Optional[QWidget]) -> None:
        """Focus moved into a plot: the user clicked or tabbed into it. Focus that moves only
        because the focused widget was hidden (its dock went behind another tab, or closed)
        is Qt's choice, not the user's, and shows nothing."""
        if old is not None and not old.isVisible():
            return
        self._activate(self._plot_of(now))

    @pyqtSlot(QWindow)
    def _window_activated(self, window: Optional[QWindow]) -> None:
        """A floating plot's window became active (clicked, even where nothing takes focus)."""
        if window is None:
            return
        for dock in self._order:
            if dock.isFloating() and dock.windowHandle() is window:
                self._activate(dock)
                return

    @pyqtSlot(bool)
    def _visibility_changed(self, visible: bool) -> None:
        if not visible and self.sender() is self.current_plot():
            self._check_shown.start()

    def _shown_still_visible(self) -> None:
        """The shown plot was hidden (unticked in the plot area's menu, its window minimised,
        behind another tab on screen): a visible plot shows instead, as when it closes; if
        none is visible, it stays. Checked a pass of the event loop later: floating or docking
        a plot hides it for a moment, and a tab click shows the plot it brings forward."""
        shown = self.current_plot()
        if shown is None or sip.isdeleted(shown) or shown.isVisible():
            return
        fallback = self._fallback(shown)
        if fallback is not None and fallback.isVisible():
            self.show_plot(fallback)

    @pyqtSlot()
    def _forget_deleted(self) -> None:
        """A plot's dock was deleted without being closed (its window went): drop its page."""
        for dock in [dock for dock in self._order if sip.isdeleted(dock)]:
            self.remove_plot(dock)
