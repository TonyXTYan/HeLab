"""The Scripts panel (``TreePanelWidget``): HeLab's bundled analyses and loaded scripts by
group, with each script's run buttons; it opens each new plot's dock in the plot area."""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING, Union

from PyQt6 import sip
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (QComboBox, QDockWidget, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
                             QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from helab.analysis.dataset_view import DatasetView
from helab.analysis.presets import SavedPlot, ScriptRef, waiting_view
from helab.scripts import dld, standard
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.scripts_manager import ScriptsManager
from helab.utils.accessible import id_part, identify
from helab.views.plots.dock import AnalysisDock, DockTabCloser
from helab.views.plots.instance import AnalysisInstance, LinkedAnalysisInstance
if TYPE_CHECKING:
    from helab.views.plots.arrangement import FolderWait
    from helab.views.plots.workspace import PlotWorkspace

# ``_add_dock``'s default: tab the new plot with the shown one (``tab_target``).
AUTO = "auto"


class TreePanelWidget(QWidget):
    """The Scripts panel: a group selector, Load Scripts… and the selected group's scripts, each
    with up to two run buttons (its first actions).

    Groups are each script's metadata group: HeLab's bundled analyses ("Basic plots v1",
    ``helab.scripts.standard.group``; "DLD Front Panel Port", ``helab.scripts.dld.group``) and
    those of scripts loaded from a folder (``ScriptsManager``).

    ``plotsChanged`` says when a plot opened or closed (the plots to reopen at start are recorded
    then, helab/views/plots/arrangement.py).
    """

    plotsChanged = pyqtSignal()

    def __init__(self, workspace: Optional[PlotWorkspace] = None,
                 parent: Any = None) -> None:
        super().__init__(parent)

        self.workspace = workspace  # The plot area new plots open in.
        self.script_manager = ScriptsManager()
        
        self.groups: List[str] = []  # As the group selector lists them.

        # Analysis instance tracking
        self._instance_counter = 0
        self._analysis_instances: Dict[str, LinkedAnalysisInstance] = {}

        # Layout for the right-bottom panel
        self.panel_layout_right_bottom = QVBoxLayout(self)
        self.panel_layout_right_bottom.setContentsMargins(0, 0, 0, 0)

        # Add controls at the top
        controls_layout = QHBoxLayout()
        
        # Add group selector
        self.group_selector = identify(QComboBox(), "script_group", "Script group",
                                       "Choose which group's scripts are listed")
        self.group_selector.currentTextChanged.connect(self._on_group_changed)
        controls_layout.addWidget(QLabel("Group:"))
        controls_layout.addWidget(self.group_selector)

        # Add script directory button
        self.load_dir_button = identify(QPushButton("Load Scripts..."), "load_scripts",
                                        description="Load analysis scripts from a folder")
        self.load_dir_button.clicked.connect(self._on_load_directory)
        controls_layout.addWidget(self.load_dir_button)
        # The row shrinks with the panel, never sets its width (Q33.2; on Windows it held the settings panel at
        # ~548 px): the combo to a few characters, the button to its text.
        self.group_selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.group_selector.setMinimumContentsLength(4)
        self.load_dir_button.setMinimumWidth(
            self.load_dir_button.fontMetrics().horizontalAdvance(self.load_dir_button.text()) + 8)

        controls_layout.addStretch()
        self.panel_layout_right_bottom.addLayout(controls_layout)

        # Tree list widget
        self.tree_widget = identify(QTreeWidget(), "scripts", "Scripts", "The group's scripts and their run buttons")
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

        # Add tree widget to the layout
        self.panel_layout_right_bottom.addWidget(self.tree_widget)

        # HeLab's bundled analyses
        self._load_default_scripts()

        logging.info(f"TreePanelWidget initialized. {type(self.parent()) = }")

    def _load_default_scripts(self) -> None:
        """Register HeLab's bundled analyses (``helab.scripts.standard``, then the DLD front panel port, ``helab.scripts.dld``) and show the first group."""
        for module in (*standard.MODULES, *dld.MODULES):
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
        self.groups = list(groups)  # Known before the selector lists them (it selects one at once).
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

    def _on_group_changed(self, group_name: str) -> None:
        """The selector chose another group: list its scripts."""
        if group_name:
            if group_name in self.groups:
                self._load_current_group()
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

        self.tree_widget.clear()
        group_item = QTreeWidgetItem(self.tree_widget, [group_name])
        group_item.setFirstColumnSpanned(True)

        for metadata in self.script_manager.get_scripts_in_group(group_name):
            script_class = self.script_manager.get_script(metadata.script_id)
            if script_class:
                try:
                    script = script_class()
                    actions = script.get_actions()

                    item = QTreeWidgetItem(group_item, [metadata.name])
                    item.setToolTip(0, f"{metadata.description}\n{metadata.identity().text()}")
                    for column, action in enumerate(actions[:2], start=1):
                        button = self.create_button(action, self._action_callback(metadata, script, action))
                        # "Plot Counts per shot", its ID from the script's analysis ID (not its name).
                        identify(button, f"run_{id_part(metadata.identity().analysis_id)}_{id_part(action)}",
                                 f"{action} {metadata.name}", f"Run {metadata.name} on this tab's loaded data")
                        self.tree_widget.setItemWidget(item, column, button)
                except Exception as e:
                    logging.error(f"Error loading script {metadata.name}: {e}")
                    error_item = QTreeWidgetItem(group_item, [f"{metadata.name} (Error)"])
                    error_item.setForeground(0, Qt.GlobalColor.red)

        group_item.setExpanded(True)

    def _action_callback(self, metadata: ScriptMetadata, script: Any, action: str) -> Callable[[], None]:
        if isinstance(script, DatasetAnalysis):
            def run() -> None:
                self.run_analysis(metadata, script, action)
            return run
        return lambda: script.execute_action(action)

    def run_analysis(self, metadata: ScriptMetadata, script: DatasetAnalysis,
                     action: str) -> Optional[AnalysisInstance]:
        """Run ``action`` on the current tab's shown dataset, in a new plot dock."""
        plots = self.workspace
        view = plots.current_dataset_view() if plots is not None else None
        if plots is None or not isinstance(view, DatasetView):
            if plots is not None:
                plots.notice(f"{metadata.name}: load a folder's data first")
            return None
        self._instance_counter += 1
        instance_id = f"{self._instance_counter}"
        try:
            instance = AnalysisInstance(metadata, script, action, view, instance_id, plots)
        except Exception as error:
            # The script's live_policy() or constant_keys() failing (in this Qt slot it would abort the app).
            logging.exception("%s could not open its plot", metadata.name)
            plots.notice(f"{metadata.name} failed: {error}")
            return None
        self._analysis_instances[instance_id] = instance
        instance.start()
        self._add_dock(instance)
        return instance

    def instances(self) -> List[AnalysisInstance]:
        """The open plots (of dataset analyses), as opened."""
        return [instance for instance in self._analysis_instances.values()
                if isinstance(instance, AnalysisInstance) and not instance.is_closed]

    def find_script(self, ref: ScriptRef) -> Union[Tuple[ScriptMetadata, DatasetAnalysis], str]:
        """The loaded script ``ref`` names (by its analysis id) with its action, a new instance of
        it, or why there is none (for the user: "its script isn't loaded …")."""
        for group in self.script_manager.get_groups():
            for metadata in self.script_manager.get_scripts_in_group(group):
                if metadata.identity().analysis_id != ref.analysis_id:
                    continue
                script_class = self.script_manager.get_script(metadata.script_id)
                try:
                    script = script_class() if script_class is not None else None
                    actions = script.get_actions() if script is not None else []
                except Exception as error:
                    logging.exception("%s could not be made", metadata.name)
                    return f"its script failed: {error}"
                if not isinstance(script, DatasetAnalysis):
                    return "its script no longer plots a folder's data"
                if ref.action not in actions:
                    return f"its script has no “{ref.action}” now"
                return metadata, script
        return "its script isn't loaded (Load Scripts… its folder, then open it again)"

    def reopen_plot(self, saved: SavedPlot, wait: FolderWait, *, keep_id: bool = False,
                    place: bool = True) -> Union[AnalysisInstance, str]:
        """Open ``saved`` again (at start, or from an arrangement preset): a plot of its script with
        its saved settings, waiting for its folder's data (``wait``) instead of running. Its number
        is its saved one if ``keep_id`` and free. Not ``place``: its dock isn't added to the plot
        area yet (the caller places it, ``place_dock``). The plot, or why it couldn't open."""
        plots = self.workspace
        if plots is None:
            return "no plot area"
        found = self.find_script(saved.script)
        if isinstance(found, str):
            return found
        metadata, script = found
        if keep_id and saved.instance_id.isdecimal() and saved.instance_id not in self._analysis_instances:
            instance_id = saved.instance_id
            self._instance_counter = max(self._instance_counter, int(instance_id))
        else:
            self._instance_counter += 1
            instance_id = f"{self._instance_counter}"
        try:
            instance = AnalysisInstance(metadata, script, saved.script.action,
                                        waiting_view(saved.path, saved.root_key), instance_id, plots)
        except Exception as error:
            logging.exception("%s could not open its plot", metadata.name)
            return f"it failed: {error}"
        self._analysis_instances[instance_id] = instance
        instance.start(saved, wait)
        if instance.open_error:
            # Without its settings page it would be recorded with none: it couldn't reopen (kept).
            del self._analysis_instances[instance_id]
            instance.close()
            return f"it failed: {instance.open_error}"
        if place:
            self._add_dock(instance)
        return instance

    def place_dock(self, instance: LinkedAnalysisInstance, tab_with: Optional[QDockWidget]) -> None:
        """Add a reopened plot's dock to the plot area: tabbed with ``tab_with``, else on its own."""
        self._add_dock(instance, tab_with)

    def _add_dock(self, instance: LinkedAnalysisInstance, tab_with: Union[Optional[QDockWidget], str] = AUTO) -> None:
        plots, dock = self.workspace, instance.dock_widget
        if plots is None or not isinstance(dock, AnalysisDock):
            return
        instance.ended.connect(self._forget_instance)
        settings = plots.panel_right_top_plot_settings
        area = plots.middle_mainwindow
        settings.follow(area)
        closer = area.findChild(DockTabCloser) or DockTabCloser(area)
        target = (self.tab_target(area, plots.dock_widgets, settings.current_plot()) if tab_with == AUTO
                  else tab_with if isinstance(tab_with, QDockWidget) else None)
        area.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        # In a shown area Qt hides the new dock and shows it later, and it won't tab a plot
        # opened meanwhile with a hidden one: show it now.
        dock.show()
        if target is not None:
            # Plots share the area as tabs; the new one comes to the front.
            area.tabifyDockWidget(target, dock)
            dock.raise_()
        closer.watch(dock)
        plots.dock_widgets.append(dock)
        plots.update_placeholder_visibility()
        self.plotsChanged.emit()

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
        if self._analysis_instances.pop(instance_id, None) is not None:
            self.plotsChanged.emit()

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

