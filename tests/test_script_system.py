import hashlib
from pathlib import Path
from typing import List, cast

import pytest
from PyQt6.QtWidgets import QDockWidget, QFileDialog, QMainWindow, QPushButton, QTabBar, QTreeWidgetItem
from pytestqt.qtbot import QtBot

from helab.scripts.scripts_manager import ScriptsManager
from helab.models import TreePanelWidget
from helab.models.ScriptTreeSelector import ParamTreeTabWidget
from helab.views.HelabMainWindow import HelabMainWindow

# A user's script folder: an older-style script with plain actions.
USER_SCRIPT = '''
from typing import Any, List
from helab.scripts.base import HelabAnalysisScript, ScriptMetadata

CALLS: List[str] = []

class Logged(HelabAnalysisScript):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata("Logged", "Records its actions", "Lab", __file__, "lab.logged", "2")

    def get_actions(self) -> List[str]:
        return ["First", "Second"]

    def execute_action(self, action_name: str, **kwargs: Any) -> None:
        CALLS.append(action_name)
'''

# Mock HelabMainWindow for testing
class MockHelabMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.middle_mainwindow = QMainWindow()
        self.dock_widgets: List[QDockWidget] = []


@pytest.fixture
def script_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "lab_scripts"
    folder.mkdir()
    (folder / "logged.py").write_text(USER_SCRIPT)
    (folder / "notes.txt").write_text("not a script")
    return folder


def group_items(widget: TreePanelWidget) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for i in range(widget.tree_widget.topLevelItemCount()):
        item = widget.tree_widget.topLevelItem(i)
        assert isinstance(item, QTreeWidgetItem)
        children = [item.child(j) for j in range(item.childCount())]
        groups[item.text(0)] = [child.text(0) for child in children if child is not None]
    return groups


def test_script_loading(script_folder: Path) -> None:
    """A folder's scripts are loaded, grouped and identified by their file's hash."""
    manager = ScriptsManager()
    manager.load_directory(str(script_folder))
    assert manager.get_groups() == ["Lab"]
    (metadata,) = manager.get_scripts_in_group("Lab")
    assert (metadata.name, metadata.analysis_id, metadata.version) == ("Logged", "lab.logged", "2")
    assert metadata.file_hash == hashlib.sha256((script_folder / "logged.py").read_bytes()).hexdigest()
    assert manager.get_script(metadata.script_id) is not None


def test_tree_panel_lists_only_working_scripts(qtbot: QtBot) -> None:
    """HeLab's bundled analyses, each with its Plot button; no placeholder groups."""
    widget = TreePanelWidget(cast(HelabMainWindow, MockHelabMainWindow()))
    qtbot.addWidget(widget)
    assert [widget.group_selector.itemText(i) for i in range(widget.group_selector.count())] == ["Plots"]
    assert group_items(widget) == {"Plots": ["3D scatter", "Counts per shot", "T, X, Y histograms"]}
    plots = widget.tree_widget.topLevelItem(0)
    assert plots is not None
    for i in range(plots.childCount()):
        button = widget.tree_widget.itemWidget(plots.child(i), 1)
        assert isinstance(button, QPushButton) and button.text() == "Plot"
        assert widget.tree_widget.itemWidget(plots.child(i), 2) is None


def test_load_scripts_adds_a_working_group(qtbot: QtBot, script_folder: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    widget = TreePanelWidget(cast(HelabMainWindow, MockHelabMainWindow()))
    qtbot.addWidget(widget)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(script_folder))
    widget.load_dir_button.click()
    assert sorted(widget.group_selector.itemText(i) for i in range(widget.group_selector.count())) == ["Lab", "Plots"]
    widget.group_selector.setCurrentText("Lab")
    assert group_items(widget) == {"Lab": ["Logged"]}
    lab = widget.tree_widget.topLevelItem(0)
    assert lab is not None and lab.child(0) is not None
    for column, action in ((1, "First"), (2, "Second")):
        button = widget.tree_widget.itemWidget(lab.child(0), column)
        assert isinstance(button, QPushButton) and button.text() == action
        button.click()
    metadata = widget.script_manager.get_scripts_in_group("Lab")[0]
    script_class = widget.script_manager.get_script(metadata.script_id)
    assert script_class is not None
    # Loaded from its file, not imported: its module is reached through its functions.
    assert script_class.execute_action.__globals__["CALLS"] == ["First", "Second"]


def test_parameter_panel_starts_with_a_hint(qtbot: QtBot) -> None:
    tabs = ParamTreeTabWidget()
    qtbot.addWidget(tabs)
    tabs.add_hint_tab()
    assert tabs.count() == 1 and tabs.tabText(0) == "Settings"
    tab_bar = tabs.tabBar()
    assert tab_bar is not None and tab_bar.tabButton(0, QTabBar.ButtonPosition.RightSide) is None
