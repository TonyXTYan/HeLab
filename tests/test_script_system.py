import os
import pytest
from PyQt6.QtWidgets import QApplication, QMainWindow, QTreeWidgetItem
from PyQt6.QtCore import Qt

from helab.scripts.base import HelabAnalysisScript, ScriptMetadata
from helab.scripts.scripts_manager import ScriptsManager
from helab.models import TreePanelWidget

# Mock HelabMainWindow for testing
class MockHelabMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.middle_mainwindow = QMainWindow()
        self.dock_widgets = []

def test_script_loading(qtbot):
    """Test loading and managing analysis scripts"""
    manager = ScriptsManager()
    
    # Load example scripts
    example_dir = os.path.join(os.path.dirname(__file__), '..', 'helab', 'scripts', 'examples')
    manager.load_directory(example_dir)
    
    # Verify groups were loaded
    groups = manager.get_groups()
    assert "Examples" in groups
    assert "Advanced" in groups
    
    # Check scripts in Examples group
    example_scripts = manager.get_scripts_in_group("Examples")
    assert len(example_scripts) == 1
    assert example_scripts[0].name == "Basic Analysis"
    
    # Check scripts in Advanced group
    advanced_scripts = manager.get_scripts_in_group("Advanced")
    assert len(advanced_scripts) == 1
    assert advanced_scripts[0].name == "Advanced Analysis"

def test_tree_panel_widget(qtbot):
    """Test TreePanelWidget functionality"""
    # Create mock main window
    mock_main = MockHelabMainWindow()
    widget = TreePanelWidget(mock_main)
    qtbot.addWidget(widget)
    
    # Load example scripts
    example_dir = os.path.join(os.path.dirname(__file__), '..', 'helab', 'scripts', 'examples')
    widget.script_manager.load_directory(example_dir)
    
    # Check if widget has required attributes
    assert hasattr(widget, 'group_selector'), "Widget should have group_selector"
    assert hasattr(widget, 'tree_widget'), "Widget should have tree_widget"
    
    # Check group selector
    assert widget.group_selector.count() == 2, "Should have two groups"
    
    # Select Examples group
    widget.group_selector.setCurrentText("Examples")
    qtbot.wait(100)  # Allow time for the group change to process
    
    # Find Examples group item
    example_group = None
    for i in range(widget.tree_widget.topLevelItemCount()):
        item = widget.tree_widget.topLevelItem(i)
        if isinstance(item, QTreeWidgetItem) and item.text(0) == "Examples":
            example_group = item
            break
            
    assert example_group is not None, "Examples group should exist"
    assert example_group.childCount() == 1, "Should have one script"
    
    script_item = example_group.child(0)
    assert isinstance(script_item, QTreeWidgetItem), "Script item should be QTreeWidgetItem"
    assert script_item.text(0) == "Basic Analysis", "Script should be named 'Basic Analysis'"
    
    # Verify buttons are present
    action1_widget = widget.tree_widget.itemWidget(script_item, 1)
    action2_widget = widget.tree_widget.itemWidget(script_item, 2)
    assert action1_widget is not None, "Action 1 button should exist"
    assert action2_widget is not None, "Action 2 button should exist"