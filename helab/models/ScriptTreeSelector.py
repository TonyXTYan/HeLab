from __future__ import annotations
import logging
import os
from typing import Any, Callable, Dict, Optional, cast, no_type_check, TYPE_CHECKING, List, Tuple, Union, Literal

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent
# from uuid import uuid4

# Import QWidget types first to avoid forward references
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QVBoxLayout,
    QTreeWidgetItem, QHeaderView, QTabWidget, QDockWidget, QFileDialog,
    QComboBox, QMainWindow, QTabBar
)
from pyqtgraph.parametertree import Parameter
import pyqtgraph.parametertree as ptree

from helab.analysis.dataset_view import DatasetView
from helab.analysis.parameter_tree import build_tree, tree_values
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


class AnalysisDock(QDockWidget):
    """A plot dock that says when the user closes it (hiding, e.g. behind another tabbed
    dock, is not closing)."""
    closed = pyqtSignal()

    def closeEvent(self, event: QCloseEvent | None) -> None:
        super().closeEvent(event)
        self.closed.emit()


class LinkedAnalysisInstance:
    """Manages a linked pair of dock widget and parameter tab.
    
    This class handles:
    - Unique instance identification
    - Synchronized closing of linked UI components
    - Cleanup of resources when either component is closed
    
    Args:
        name: Base name of the analysis (used for display)
        instance_id: Unique identifier for this instance
        main_window: Reference to main window for cleanup
    """
    
    def __init__(self, name: str, instance_id: str, main_window: Optional['HelabMainWindow']):
        self.name = name
        self.instance_id = instance_id
        self.main_window = main_window
        self.dock_widget: Optional[QDockWidget] = None
        self.param_tab: Optional[QWidget] = None
        self.param_tab_index: int = -1
        self.is_closed = False
        
    def setup_dock_widget(self, content: QWidget) -> None:
        """Create and setup the dock widget."""
        if not self.main_window:
            return
            
        dock = AnalysisDock(f"{self.name} ({self.instance_id})", self.main_window)
        dock.setStyleSheet(QDOCKWIDGET_STYLESHEET)
        dock.setWidget(content)
        dock.closed.connect(self.close)
        self.dock_widget = dock
        
    def setup_param_tab(self, param_tree: QWidget) -> None:
        """Create and setup the parameter tab."""
        if not self.main_window:
            return
            
        self.param_tab = param_tree
        self.param_tab_index = self.main_window.panel_right_top_params_tab_widget.addTab(
            param_tree,
            f"{self.name} ({self.instance_id})"
        )
        tab_bar = self.main_window.panel_right_top_params_tab_widget.tabBar()
        if tab_bar:
            tab_bar.setTabData(
                self.param_tab_index,
                self.instance_id
            )
        
    def close(self) -> None:
        """Close and cleanup both components."""
        if self.is_closed:
            return
            
        self.is_closed = True
        
        if self.main_window:
            # Remove dock widget
            if self.dock_widget:
                self.main_window.middle_mainwindow.removeDockWidget(self.dock_widget)
                if self.dock_widget in self.main_window.dock_widgets:
                    self.main_window.dock_widgets.remove(self.dock_widget)
                self.dock_widget.deleteLater()
                
            # Remove parameter tab (its index moves as other tabs close)
            if self.param_tab:
                tabs = self.main_window.panel_right_top_params_tab_widget
                index = tabs.indexOf(self.param_tab)
                if index >= 0:
                    tabs.removeTab(index)
                self.param_tab.deleteLater()
            update = getattr(self.main_window, "update_placeholder_visibility", None)
            if callable(update):
                update()


class AnalysisInstance(LinkedAnalysisInstance):
    """One run of a dataset analysis: its plot dock and parameter tab, bound to the dataset
    view it started with. **Rerun with these settings** runs again on that same view; a new
    run on other data is a new instance (the script's button again)."""

    def __init__(self, metadata: ScriptMetadata, script: DatasetAnalysis, action: str, view: DatasetView,
                 instance_id: str, main_window: Optional['HelabMainWindow'],
                 runner: Optional[AnalysisRunner] = None) -> None:
        super().__init__(metadata.name, instance_id, main_window)
        self.metadata, self.script, self.action, self.view = metadata, script, action, view
        self.runner = runner or get_analysis_runner()
        self.job_id = ""
        self.result: Optional[AnalysisResult] = None
        self.parameter_root: Optional[Parameter] = None
        self.status_label = QLabel()
        self.runner.finished.connect(self._finished)

    def start(self) -> None:
        """Open the dock and parameter tab, then run with the defaults."""
        self.setup_dock_widget(self._message(f"Running {self.name} on {self.view.key.short()}…"))
        specs = self.script.parameters(self.action)
        self.parameter_root = build_tree(specs)
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        source = QLabel(f"Input: {self.view.key.short()} (stays with this plot)")
        source.setToolTip(self.view.identity.source_path)
        layout.addWidget(source)
        tree = ptree.ParameterTree()
        tree.setParameters(self.parameter_root, showTop=False)
        layout.addWidget(tree, 1)
        self.rerun_button = QPushButton("Rerun with these settings")
        self.rerun_button.setEnabled(bool(specs))
        self.rerun_button.clicked.connect(self.run)
        layout.addWidget(self.rerun_button)
        layout.addWidget(self.status_label)
        self.setup_param_tab(tab)
        self.run()

    def values(self) -> Dict[str, Any]:
        root = self.parameter_root
        return tree_values(root, self.script.parameters(self.action)) if root is not None else {}

    def run(self) -> None:
        if self.is_closed:
            return
        if self.job_id:
            self.runner.cancel(self.job_id)
        context = self.runner.submit(self.script, self.metadata, self.action, self.view, self.values())
        self.job_id = context.job_id
        self.status_label.setText(f"Running ({context.job_id})…")

    def _finished(self, result: AnalysisResult) -> None:
        if self.is_closed or result.job_id != self.job_id:
            return
        self.job_id = ""
        if result.state == "cancelled":
            self.status_label.setText("Cancelled")
            return
        if self.result is not None:
            self.runner.results.unpin(self.result.job_id)
        self.result = result
        specs = self.script.parameters(self.action)
        if result.state == "completed":
            self.runner.results.pin(result.job_id)
            try:
                content = self.script.render(result)
            except Exception as error:
                logging.exception("Could not draw %s", self.name)
                content = self._message(f"Could not draw {self.name}: {error}")
            self.status_label.setText("")
        else:
            content = self._message(f"{self.name} failed: {result.error}")
            self.status_label.setText(f"Failed: {result.error}")
        if self.dock_widget is None:
            return
        show = getattr(self.main_window, "set_plot_result", None)
        if callable(show):
            show(self.dock_widget, content, result, describe(specs, result.parameters),
                 describe(specs, result.parameters, every=True))
        else:
            old = self.dock_widget.widget()
            self.dock_widget.setWidget(content)
            if old is not None:
                old.deleteLater()

    @staticmethod
    def _message(text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        return label

    def close(self) -> None:
        if self.is_closed:
            return
        if self.job_id:
            self.runner.cancel(self.job_id)
        if self.result is not None:
            self.runner.results.unpin(self.result.job_id)
        try:
            self.runner.finished.disconnect(self._finished)
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
    - Groups: HeLab's bundled analyses ("Plots") and those of scripts loaded from a folder
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
        dock.closed.connect(lambda: self._analysis_instances.pop(instance.instance_id, None))
        shown = [other for other in window.dock_widgets if other.isVisible()]
        window.middle_mainwindow.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        if shown:
            # Plots share the area as tabs; the new one comes to the front.
            window.middle_mainwindow.tabifyDockWidget(shown[-1], dock)
            dock.show()
            dock.raise_()
        window.dock_widgets.append(dock)
        update = getattr(window, "update_placeholder_visibility", None)
        if callable(update):
            update()

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

class ParamTreeTabWidget(QTabWidget):
    """A widget that provides parameter tree functionality in a tabbed interface.
    
    This widget extends QTabWidget to display and manage script parameters using
    pyqtgraph's parameter tree system. It supports:
    - Multiple parameter tabs
    - Hierarchical parameter organization
    - Various parameter types (int, float, bool, str, list)
    - Nested parameter groups
    
    Each plot's parameter tab is added by its ``AnalysisInstance``; a first,
    non-closable tab says where the settings come from.
    
    This is primarily used for configuring and controlling script behavior
    through a user-friendly interface.
    """
    
    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.tabCloseRequested.connect(self._on_tab_close)
        
    def _on_tab_close(self, index: int) -> None:
        """Handle tab close requests by finding and closing the associated instance."""
        tab_bar = self.tabBar()
        if not tab_bar:
            return
            
        instance_id = tab_bar.tabData(index)
        if not instance_id:
            # If no instance ID, just remove the tab
            self.removeTab(index)
            return
        
        # Find the HelabMainWindow and access the TreePanelWidget through it
        from helab.views.HelabMainWindow import HelabMainWindow
        parent_window = None
        parent = self.parent()
        
        # Find the parent main window
        while parent:
            if isinstance(parent, HelabMainWindow):
                parent_window = parent
                break
            parent = parent.parent()
        
        if parent_window and hasattr(parent_window, 'panel_right_bottom_script_selector'):
            tree_panel = parent_window.panel_right_bottom_script_selector
            
            # Now we can access the TreePanelWidget's instance dictionary
            if instance_id in tree_panel._analysis_instances:
                instance = tree_panel._analysis_instances[instance_id]
                instance.close()
                del tree_panel._analysis_instances[instance_id]
                return
        
        # If we couldn't find the instance or tree panel, just remove the tab
        self.removeTab(index)

    def add_hint_tab(self) -> None:
        """A first, non-closable tab: plots' settings appear in tabs beside it."""
        hint = QLabel("Run a plot from Scripts below; its settings appear in a tab here.")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        tab_index = self.addTab(hint, "Settings")
        self.setTabsClosable(True)
        tab_bar = self.tabBar()
        if tab_bar is not None:
            tab_bar.setTabButton(tab_index, QTabBar.ButtonPosition.RightSide, None)
