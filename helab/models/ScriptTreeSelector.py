#
from __future__ import annotations
import logging
from typing import Any, Callable, Dict, cast, no_type_check, TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QVBoxLayout, QTreeWidgetItem, \
    QHeaderView, QTabWidget, QDockWidget
from pyqtgraph.parametertree import ParameterItem
import pyqtgraph.parametertree as ptree

from helab.scripts.plotly_3d_sactter import Plotly3DScatter
from helab.utils.constants import QDOCKWIDGET_STYLESHEET
if TYPE_CHECKING:
    from helab.views.FolderExplorer import FolderExplorer
    from helab.views.HelabMainWindow import HelabMainWindow

import numpy.typing as npt
import numpy as np


class TreePanelWidget(QWidget):
    def __init__(self, helab_main_window: HelabMainWindow,
                 parent: Any = None) -> None:
        super().__init__(parent)

        self.helab_main_window = helab_main_window

        # Layout for the right-bottom panel
        self.panel_layout_right_bottom = QVBoxLayout(self)
        self.panel_layout_right_bottom.setContentsMargins(0, 0, 0, 0)

        # Tree list widget
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["Item", "Button 1", "Button 2"])
        self.tree_widget.setColumnCount(3)
        # self.tree_widget.setColumnWidth(0, 150)  # Adjust column width as needed
        header = self.tree_widget.header()
        if header: header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        # Dictionary to map group names to QTreeWidgetItem objects
        self.group_mapping: Dict[str, QTreeWidgetItem] = {}

        # Add tree widget to the layout
        self.panel_layout_right_bottom.addWidget(self.tree_widget)

        logging.info(f"TreePanelWidget initialized. {type(self.parent()) = }")

    def add_item(self, group_name: str, name: str, callable1: Callable[..., Any],
                 callable2: Callable[..., Any]) -> None:
        """Add an item with buttons to the specified group by name."""
        if group_name not in self.group_mapping:
            logging.warning(f"Group '{group_name}' does not exist. Item '{name}' not added.")
            return

        group_item = self.group_mapping[group_name]
        item = QTreeWidgetItem(group_item, [name])
        self.tree_widget.setItemWidget(item, 1, self.create_button("Button 1", callable1))
        self.tree_widget.setItemWidget(item, 2, self.create_button("Button 2", callable2))

    def add_group_with_items(self, group_name: str,
                             items: list[tuple[str, Callable[..., Any], Callable[..., Any]]]) -> None:
        """Add a group with a list of items to the tree widget."""
        if group_name in self.group_mapping:
            logging.warning(f"Group '{group_name}' already exists. Skipping creation.")
            return

        # Add a top-level group item
        group_item = QTreeWidgetItem(self.tree_widget, [group_name])
        group_item.setFirstColumnSpanned(True)
        self.group_mapping[group_name] = group_item

        # Add items under the group
        for name, callable1, callable2 in items:
            self.add_item(group_name, name, callable1, callable2)

        group_item.setExpanded(True)

    def create_button(self, label: str, callback: Callable[..., Any]) -> QPushButton:
        """Create a button with the given label and callback."""
        button = QPushButton(label)
        button.clicked.connect(callback)
        return button

    def add_example_groups_and_items(self) -> None:
        """Add example groups and items to the tree widget."""
        self.add_group_with_items("Group A", [
            ("Item 1A", lambda: self.example_callable("Item 1AL"), lambda: self.example_callable("Item 1AR")),
            ("Item 2A", lambda: self.example_callable("Item 2AL"), lambda: self.example_callable("Item 2AR")),
        ])

        self.add_group_with_items("Group B", [
            ("Item 1B", lambda: self.example_callable("Item 1BL"), lambda: self.example_callable("Item 1BR")),
            ("Item 2B", lambda: self.example_callable("Item 2BL"), lambda: self.example_callable("Item 2BR")),
            ("Item 3B", lambda: self.example_callable("Item 3BL"), lambda: self.example_callable("Item 3BR")),
        ])
        self.add_item("Group B", "Item 4B",
                      lambda: self.example_callable("Item 4BL"), self.example_callable)

        self.add_group_with_items("Dev Plots", [
            ("Plotly 3D Scatter", self.dev_add_plotly_3d_scatter_plot, self.example_callable),
        ])

    @staticmethod
    def example_callable(message: str = "NA") -> None:
        """An example callable for button actions."""
        logging.info(f"TreePanelWidget.example_callable: {message}")


    @no_type_check
    def dev_add_plotly_3d_scatter_plot(self) -> None:
        """An example callable for button actions."""
        logging.warning(f"TreePanelWidget.dev_app_plotly_3d_scatter_plot: Plotting 3D scatter plot. THIS IS FULLY OF HARDCODED VALUES.")
        from helab.views.HelabMainWindow import HelabMainWindow
        from helab.views.FolderExplorer import FolderExplorer
        # helab_main_window = self.parent()
        helab_main_window = self.helab_main_window
        logging.warning(f"{type(helab_main_window) = }")
        helab_main_window = cast(HelabMainWindow, helab_main_window)
        current_folder_explorer = helab_main_window.tab_widget.currentWidget()
        current_folder_explorer = cast(FolderExplorer, current_folder_explorer)
        data = current_folder_explorer.folder_opened_data
        data = cast(Dict[int, npt.NDArray[np.float64]], data)

        plotly_3d_scatter = Plotly3DScatter(data=data)
        plotly_3d_scatter_dock_widget = QDockWidget("Plotly 3D Scatter")
        plotly_3d_scatter_dock_widget.setWidget(plotly_3d_scatter)

        plotly_3d_scatter_dock_widget.visibilityChanged.connect(helab_main_window.update_placeholder_visibility)
        plotly_3d_scatter_dock_widget.setStyleSheet(QDOCKWIDGET_STYLESHEET)
        helab_main_window.middle_mainwindow.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, plotly_3d_scatter_dock_widget)
        helab_main_window.dock_widgets.append(plotly_3d_scatter_dock_widget)



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
        param_tree.setParameters(ptree.Parameter.create(name='params', type='group', children=params), showTop=False)

        self.addTab(param_tree, "Parameters")

    def add_example_todo_tab(self) -> None:
        todo = QLabel("TODO: Add a tab with a parameter tree.")
        self.addTab(todo, "TODO")