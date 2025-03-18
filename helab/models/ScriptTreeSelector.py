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
    """Stores information about a script group"""
    def __init__(self, name: str, group_type: GroupType):
        self.name = name
        self.type = group_type
        self.tree_item: Optional[QTreeWidgetItem] = None
        self.is_loaded = False

class TreePanelWidget(QWidget):
    group_changed = pyqtSignal(str, str)  # group_name, group_type
    
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
        """Register a new group with type tracking"""
        if name not in self.groups:
            self.groups[name] = GroupData(name, group_type)
            logging.debug(f"Registered group: {name} (type: {group_type})")

    def _load_default_scripts(self) -> None:
        """Load the default example scripts bundled with HeLab"""
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
        """Handle loading a new script directory"""
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
        """Update the group selector with available groups"""
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
        """Handle group selection changes"""
        if group_name:
            if group_name in self.groups:
                group_data = self.groups[group_name]
                self.current_group = group_data
                self._load_current_group()
                self.group_changed.emit(group_name, group_data.type)
            else:
                logging.error(f"Unknown group: {group_name}")

    def _load_current_group(self) -> None:
        """Load the currently selected group's scripts"""
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
        """Create a button with the given label and callback."""
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