from __future__ import annotations
import logging
import os
from typing import Any, Callable, Dict, Optional, cast, no_type_check, TYPE_CHECKING, List, Tuple, Union, Literal

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent
# from uuid import uuid4

# Import QWidget types first to avoid forward references
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QVBoxLayout,
    QTreeWidgetItem, QHeaderView, QDockWidget, QFileDialog,
    QComboBox, QMainWindow, QApplication, QStackedWidget
)
from pyqtgraph.parametertree import Parameter

from helab.analysis.dataset_view import DatasetView
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


class AnalysisDock(QDockWidget):
    """A plot dock that says when the user closes it (hiding, e.g. behind another tabbed
    dock, is not closing)."""
    closed = pyqtSignal()

    def closeEvent(self, event: QCloseEvent | None) -> None:
        super().closeEvent(event)
        self.closed.emit()


class LinkedAnalysisInstance:
    """Manages a linked pair of dock widget and its page in the Settings panel.
    
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
        
    def setup_param_tab(self, param_tree: QWidget, title: str = "") -> None:
        """Add this plot's page to the Settings panel (after its dock is made)."""
        if not self.main_window or self.dock_widget is None:
            return
        self.param_tab = param_tree
        self.main_window.panel_right_top_plot_settings.add_plot(
            self.dock_widget, param_tree, title or f"{self.name} ({self.instance_id})")
        
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
                
            # Remove its page from the Settings panel
            if self.param_tab:
                if self.dock_widget:
                    self.main_window.panel_right_top_plot_settings.remove_plot(self.dock_widget)
                self.param_tab.deleteLater()
            update = getattr(self.main_window, "update_placeholder_visibility", None)
            if callable(update):
                update()


class AnalysisInstance(LinkedAnalysisInstance):
    """One run of a dataset analysis: its plot dock and settings page, bound to the dataset
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
        """Open the dock and its settings page, then run with the defaults."""
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
        layout.addWidget(settings_widget(self.parameter_root, specs), 1)
        self.rerun_button = QPushButton("Rerun with these settings")
        self.rerun_button.setEnabled(bool(specs))
        self.rerun_button.clicked.connect(self.run)
        layout.addWidget(self.rerun_button)
        layout.addWidget(self.status_label)
        self.setup_param_tab(tab, f"{self.name} ({self.instance_id}) · {self.view.key.short()}")
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
        warnings = "; ".join(self.script.parameter_warnings(self.action, result.parameters))
        if result.state == "completed":
            self.runner.results.pin(result.job_id)
            self._show_detected(result)
            try:
                content = self.script.render(result)
            except Exception as error:
                logging.exception("Could not draw %s", self.name)
                content = self._message(f"Could not draw {self.name}: {error}")
            self.status_label.setText(f"⚠ {warnings}" if warnings else "")
        else:
            content = self._message(f"{self.name} failed: {result.error}")
            self.status_label.setText(f"Failed: {result.error}")
        if self.dock_widget is None:
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

    def _show_detected(self, result: AnalysisResult) -> None:
        """Put what the run found into the settings (they don't rerun it)."""
        root = self.parameter_root
        if root is None:
            return
        specs = {spec.name: spec for spec in self.script.parameters(self.action)}
        for name, value in self.script.detected_parameters(self.action, result).items():
            if name in specs:
                parameter_of(root, specs[name]).setValue(specs[name].coerce(value))

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
        dock.closed.connect(lambda: self._analysis_instances.pop(instance.instance_id, None))
        window.panel_right_top_plot_settings.follow(window.middle_mainwindow)
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

class PlotSettingsPanel(QWidget):
    """The settings of the active plot: one page per open plot, showing the page of the plot
    last clicked, focused or brought to the front among tabbed docks, floating ones included.
    The chooser on top names it and picks another plot (raising its dock). A page keeps its
    edits while another plot's page shows. With no plot open, a hint shows instead."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.chooser = QComboBox()
        self.chooser.setToolTip("The plot these settings are for; click a plot to show its settings")
        self.chooser.activated.connect(lambda index: self.show_plot(self._order[index], raise_dock=True))
        layout.addWidget(self.chooser)
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
        self._update_chooser()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def add_plot(self, dock: QDockWidget, page: QWidget, title: str) -> None:
        """A new plot's page; it shows at once, as its dock comes to the front."""
        self._pages[dock] = page
        self._order.append(dock)
        self.stack.addWidget(page)
        self.chooser.addItem(title)
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
        self.stack.removeWidget(page)
        if self._recent:
            self.show_plot(self._recent[-1])
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

    def current_plot(self) -> Optional[QDockWidget]:
        return self._recent[-1] if self._recent else None

    def page(self, dock: QDockWidget) -> Optional[QWidget]:
        return self._pages.get(dock)

    def follow(self, area: QMainWindow) -> None:
        """Show a plot's page when its tab is clicked among tabbed docks in ``area``."""
        if area not in self._followed:
            self._followed.append(area)
            area.tabifiedDockWidgetActivated.connect(self.show_plot)

    def _update_chooser(self) -> None:
        self.chooser.setVisible(bool(self._order))

    def _plot_of(self, widget: Optional[QWidget]) -> Optional[QDockWidget]:
        while widget is not None:
            if isinstance(widget, QDockWidget) and widget in self._pages:
                return widget
            widget = widget.parentWidget()
        return None

    def eventFilter(self, a0: Optional[QObject], a1: Optional[QEvent]) -> bool:
        """A click or focus inside a plot, or activating a floating plot's window, shows its page."""
        # The filter is app-wide: it can outlive this wrapper's attributes as Python tears it down.
        if (getattr(self, "_pages", None) and a1 is not None and isinstance(a0, QWidget)
                and a1.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.FocusIn, QEvent.Type.WindowActivate)):
            dock = self._plot_of(a0)
            if dock is not None and dock is not self.current_plot():
                self.show_plot(dock)
        return False
