from __future__ import annotations
import logging
import os
from typing import Any, Callable, Dict, Optional, cast, no_type_check, TYPE_CHECKING, List, Tuple, Union, Literal

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QVBoxLayout, 
    QTreeWidgetItem, QHeaderView, QTabWidget, QDockWidget, QFileDialog,
    QComboBox, QMainWindow
)
from pyqtgraph.parametertree import Parameter
import pyqtgraph.parametertree as ptree

from helab.scripts.plotly_3d_sactter import Plotly3DScatter
from helab.utils.constants import QDOCKWIDGET_STYLESHEET
from helab.scripts.scripts_manager import ScriptsManager
if TYPE_CHECKING:
    from helab.views.FolderExplorer import FolderExplorer
    from helab.views.HelabMainWindow import HelabMainWindow

import numpy.typing as npt
import numpy as np
ExampleGroup = List[Tuple[str, Callable[[], None], Callable[[], None]]]

GroupType = Literal["dynamic", "example"]

class GroupData:
    """Stores information about a script group in the tree widget.
    
    This class maintains the state and metadata for each script group, including:
    - The group's name and type (dynamic or example)
    - Reference to the group's tree widget item
    - Loading status
    
    Types of groups:
    - dynamic: Groups loaded from script files in a directory
    - example: Built-in groups with example functionality
    
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
    2. Script grouping functionality (dynamic and example groups)
    3. Action buttons for executing script functions
    4. Dynamic loading of scripts from directories
    
    The widget consists of:
    - A group selector dropdown
    - A "Load Scripts" button for importing new scripts
    - A tree view showing scripts organized by groups
    - Action buttons for each script
    
    Key concepts:
    - Dynamic Groups: Groups loaded from script files
    - Example Groups: Built-in groups with example functionality
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
        self.tree_widget.setHeaderLabels(["Script", "Action 1", "Action 2"])
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

        # Load default example scripts
        self._load_default_scripts()

        logging.info(f"TreePanelWidget initialized. {type(self.parent()) = }")

    def _register_group(self, name: str, group_type: GroupType) -> None:
        """Register a new group with type tracking in the widget.
        
        Creates and tracks a new GroupData instance for managing script groups.
        Only registers if the group doesn't already exist to prevent duplicates.
        
        Args:
            name: The unique name for the group
            group_type: Type of group ("dynamic" or "example")
        """
        if name not in self.groups:
            self.groups[name] = GroupData(name, group_type)
            logging.debug(f"Registered group: {name} (type: {group_type})")

    def _load_default_scripts(self) -> None:
        """Load the default example scripts bundled with HeLab.
        
        This method attempts to:
        1. Locate and load scripts from the 'scripts/examples' directory
        2. Register each found script group as a "dynamic" group
        3. Update the group selector with available groups
        
        Error handling:
        - If the examples directory is not found, falls back to example groups
        - If there's an error loading scripts, falls back to example groups
        - Ensures there are always some available scripts by using examples
        
        The fallback mechanism ensures the widget always has some functionality
        even if the actual script files are not available.
        """
        try:
            # Get the examples directory path
            examples_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'scripts',
                'examples'
            )
            
            if os.path.exists(examples_dir):
                self.script_manager.load_directory(examples_dir)
                for group in self.script_manager.get_groups():
                    self._register_group(group, "dynamic")
                self._update_groups()
                if self.group_selector.count() > 0:
                    self.group_selector.setCurrentIndex(0)
            else:
                logging.warning(f"Examples directory not found: {examples_dir}")
                # Add default example items if example scripts not available
                self.add_example_groups_and_items()
        except Exception as e:
            logging.error(f"Error loading default scripts: {e}")
            # Fall back to example items
            self.add_example_groups_and_items()

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
        self.group_selector.clear()
        groups = self.script_manager.get_groups()
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
        
        This method handles both dynamic and example groups differently:
        
        For dynamic groups:
        1. Loads script metadata from ScriptsManager
        2. Creates script class instances
        3. Sets up action buttons for each script
        4. Handles errors by displaying them in red
        
        For example groups:
        1. Creates predefined example items
        2. Sets up example action buttons
        3. Supports "Basic Analysis" and "Advanced Analysis" groups
        
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

        if group_data.type == "dynamic":
            # Load dynamic scripts
            for metadata in self.script_manager.get_scripts_in_group(group_name):
                script_class = self.script_manager.get_script(metadata.file_path)
                if script_class:
                    try:
                        script = script_class()
                        actions = script.get_actions()
                        
                        item = QTreeWidgetItem(group_item, [metadata.name])
                        if len(actions) >= 1:
                            self.tree_widget.setItemWidget(
                                item, 1,
                                self.create_button(actions[0], lambda s=script, a=actions[0]: s.execute_action(a))
                            )
                        if len(actions) >= 2:
                            self.tree_widget.setItemWidget(
                                item, 2,
                                self.create_button(actions[1], lambda s=script, a=actions[1]: s.execute_action(a))
                            )
                    except Exception as e:
                        logging.error(f"Error loading script {metadata.name}: {e}")
                        error_item = QTreeWidgetItem(group_item, [f"{metadata.name} (Error)"])
                        error_item.setForeground(0, Qt.GlobalColor.red)
        else:  # Example group
            if group_name == "Basic Analysis":
                # Recreate Basic Analysis items
                items: ExampleGroup = [
                    ("Example 1",
                     lambda: logging.info("Example 1 Analyze clicked"),
                     lambda: logging.info("Example 1 Plot clicked"))
                ]
                for name, callback1, callback2 in items:
                    item = QTreeWidgetItem(group_item, [name])
                    self.tree_widget.setItemWidget(item, 1, self.create_button("Action 1", callback1))
                    self.tree_widget.setItemWidget(item, 2, self.create_button("Action 2", callback2))
            elif group_name == "Advanced Analysis":
                # Recreate Advanced Analysis items
                items: ExampleGroup = [
                    ("Example 2",
                     lambda: logging.info("Example 2 Process clicked"),
                     lambda: logging.info("Example 2 Visualize clicked"))
                ]
                for name, callback1, callback2 in items:
                    item = QTreeWidgetItem(group_item, [name])
                    self.tree_widget.setItemWidget(item, 1, self.create_button("Action 1", callback1))
                    self.tree_widget.setItemWidget(item, 2, self.create_button("Action 2", callback2))

        group_item.setExpanded(True)
        group_data.is_loaded = True

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

    def add_group_with_items(self, group_name: str, items: ExampleGroup) -> None:
        """Add a group with a list of items to the tree widget."""
        # Register as example group if not already registered
        if group_name not in self.groups:
            self._register_group(group_name, "example")
            group_data = self.groups[group_name]
        else:
            group_data = self.groups[group_name]
            if group_data.type != "example":
                logging.error(f"Group '{group_name}' exists but is not an example group")
                return

        # Create group item if not already created
        if group_name in self.group_mapping:
            logging.warning(f"Group '{group_name}' tree item already exists. Skipping creation.")
            return

        group_item = QTreeWidgetItem(self.tree_widget, [group_name])
        group_item.setFirstColumnSpanned(True)
        self.group_mapping[group_name] = group_item
        group_data.tree_item = group_item

        # Add items under the group
        for name, callback1, callback2 in items:
            item = QTreeWidgetItem(group_item, [name])
            try:
                self.tree_widget.setItemWidget(item, 1, self.create_button("Action 1", callback1))
                self.tree_widget.setItemWidget(item, 2, self.create_button("Action 2", callback2))
            except Exception as e:
                logging.error(f"Error creating buttons for {name}: {e}")
                item.setForeground(0, Qt.GlobalColor.red)

        group_item.setExpanded(True)
        group_data.is_loaded = True

    def add_example_groups_and_items(self) -> None:
        """Add example groups and items to the tree widget."""
        # Clean up any existing groups and items
        self.tree_widget.clear()
        self.group_mapping.clear()
        
        # Remove any example groups from tracking
        example_groups = [name for name, data in self.groups.items() if data.type == "example"]
        for group_name in example_groups:
            del self.groups[group_name]
            
        # Register example groups
        example_groups = ["Basic Analysis", "Advanced Analysis"]
        for group_name in example_groups:
            self._register_group(group_name, "example")
            
        # Update group selector and select first group
        self.group_selector.clear()
        self.group_selector.addItems(example_groups)
        
        # Select first group by default
        if self.group_selector.count() > 0:
            first_group = self.group_selector.itemText(0)
            self.current_group = self.groups[first_group]
            self.group_selector.setCurrentIndex(0)
            self._load_current_group()  # This will create items only for the selected group

class ParamTreeTabWidget(QTabWidget):
    """A widget that provides parameter tree functionality in a tabbed interface.
    
    This widget extends QTabWidget to display and manage script parameters using
    pyqtgraph's parameter tree system. It supports:
    - Multiple parameter tabs
    - Hierarchical parameter organization
    - Various parameter types (int, float, bool, str, list)
    - Nested parameter groups
    
    The widget currently provides:
    - An example parameter tab demonstrating different parameter types
    - A TODO tab for future parameter tree implementations
    
    This is primarily used for configuring and controlling script behavior
    through a user-friendly interface.
    """
    
    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)

    def add_example_tab(self) -> None:
        params = [
            {'name': 'Parameter 1', 'type': 'int', 'value': 10},
            {'name': 'Parameter 2', 'type': 'float', 'value': 0.5},
            {'name': 'Parameter 3', 'type': 'bool', 'value': True},
            {'name': 'Parameter 4', 'type': 'str', 'value': 'default'},
            {'name': 'Advanced Settings', 'type': 'group', 'children': [
                {'name': 'Sub-Parameter 1', 'type': 'int', 'value': 5},
                {'name': 'Sub-Parameter 2', 'type': 'float', 'value': 1.5},
                {'name': 'Sub-Parameter 3', 'type': 'bool', 'value': False},
            ]},
            {'name': 'Parameter 5', 'type': 'list', 'value': [1, 2, 3]},
        ]
        param_tree = ptree.ParameterTree()
        param_tree.setParameters(Parameter.create(name='params', type='group', children=params), showTop=False)
        self.addTab(param_tree, "Parameters")

    def add_example_todo_tab(self) -> None:
        todo = QLabel("TODO: Add a tab with a parameter tree.")
        self.addTab(todo, "TODO")