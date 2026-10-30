"""In a plot's settings, Return or Enter takes a typed value and closes the row's editor, as moving
on with Tab takes it; Escape closes it with the value put back (known-issues: Return looked as if it
didn't commit, because the editor stayed open)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import Qt
from pytestqt.qtbot import QtBot

from helab.analysis.parameter_tree import build_tree, parameter_of, settings_widget
from helab.analysis.parameters import ParameterSpec
from helab.views.HelabMainWindow import HelabMainWindow
from test_debug_runner_menu import load, plot, run_folder, window  # noqa: F401  (the window fixture)

SPECS = [ParameterSpec("scale", "Scale", "float", 1.0, (0.0, 100.0), suffix="s", si=True),
         ParameterSpec("count", "Count", "int", 3, (1, 10)),
         ParameterSpec("mode", "Mode", "choice", "a", choices=("a", "b", "c"))]


def tree_of(qtbot: QtBot) -> tuple[Any, Any]:
    root = build_tree(SPECS)
    tree = settings_widget(root, SPECS)
    qtbot.addWidget(tree)
    tree.show()
    return root, tree


def open_row(qtbot: QtBot, tree: Any, param: Any) -> Any:
    """Select ``param``'s row, as a click does: its editor opens with the focus."""
    item = next(iter(param.items))
    tree.setCurrentItem(item)
    qtbot.waitUntil(lambda: item.widget.isVisible() and item.widget.hasFocus())
    return item


def type_into(qtbot: QtBot, item: Any, text: str, key: Qt.Key) -> None:
    """Type ``text`` over the box's text, then ``key``, sent to the box as the focus gets them."""
    box = item.widget
    box.lineEdit().selectAll()
    qtbot.keyClicks(box, text)  # type: ignore[no-untyped-call]
    qtbot.keyClick(box, key)  # type: ignore[no-untyped-call]


def closed(item: Any) -> bool:
    return not item.widget.isVisible() and item.displayLabel.isVisible()


def test_return_and_enter_take_the_value_and_close_the_editor(qtbot: QtBot) -> None:
    root, tree = tree_of(qtbot)
    for spec, typed, key, value, shown in ((SPECS[0], "7.5", Qt.Key.Key_Return, 7.5, "7.5 s"),
                                           (SPECS[1], "9", Qt.Key.Key_Enter, 9, "9")):
        param = parameter_of(root, spec)
        item = open_row(qtbot, tree, param)
        type_into(qtbot, item, typed, key)
        assert param.value() == value  # Taken at once, by the box's own Return.
        qtbot.waitUntil(lambda: closed(item))
        assert item.displayLabel.text() == shown and not tree.selectedItems() and tree.hasFocus()
        item = open_row(qtbot, tree, param)  # A click opens it again.
        assert item.widget.value() == value


def test_escape_closes_the_editor_with_the_value_put_back(qtbot: QtBot) -> None:
    root, tree = tree_of(qtbot)
    param = parameter_of(root, SPECS[0])
    item = open_row(qtbot, tree, param)
    type_into(qtbot, item, "42", Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: closed(item))
    assert param.value() == 1.0 and item.widget.lineEdit().text() == "1 s"
    open_row(qtbot, tree, parameter_of(root, SPECS[1]))  # Leaving it later takes nothing either.
    assert param.value() == 1.0


def test_an_invalid_entry_then_return_or_tab_gives_the_value_back(qtbot: QtBot) -> None:
    root, tree = tree_of(qtbot)
    param = parameter_of(root, SPECS[1])
    after: dict[Qt.Key, tuple[Any, str]] = {}
    for key in (Qt.Key.Key_Tab, Qt.Key.Key_Return):
        item = open_row(qtbot, tree, param)
        type_into(qtbot, item, "x7", key)
        qtbot.wait(20)
        after[key] = (param.value(), item.widget.lineEdit().text())
    assert after[Qt.Key.Key_Return] == after[Qt.Key.Key_Tab] == (3, "3")
    qtbot.waitUntil(lambda: closed(item))


@pytest.mark.parametrize("key", [Qt.Key.Key_Tab, Qt.Key.Key_Backtab], ids=["tab", "backtab"])
def test_tab_takes_the_value_and_closes_the_editor_without_opening_the_next(qtbot: QtBot, key: Qt.Key) -> None:
    """A33.1: Tab (or Shift+Tab) out of a value commits and stops, like Return; no other row's editor opens."""
    root, tree = tree_of(qtbot)
    param = parameter_of(root, SPECS[0])
    item = open_row(qtbot, tree, param)
    type_into(qtbot, item, "7.5", key)
    assert param.value() == 7.5
    qtbot.waitUntil(lambda: closed(item))
    assert item.displayLabel.text() == "7.5 s" and not tree.selectedItems() and tree.hasFocus()
    for other in (parameter_of(root, spec) for spec in SPECS[1:]):
        assert all(not row.widget.isVisible() for row in other.items)


def test_tab_out_of_a_choice_closes_it(qtbot: QtBot) -> None:
    root, tree = tree_of(qtbot)
    param = parameter_of(root, SPECS[2])
    item = open_row(qtbot, tree, param)
    qtbot.keyClick(item.widget, Qt.Key.Key_Down)  # type: ignore[no-untyped-call]
    qtbot.keyClick(item.widget, Qt.Key.Key_Tab)  # type: ignore[no-untyped-call]
    qtbot.waitUntil(lambda: closed(item))
    assert param.value() == "b" and not tree.selectedItems()


def test_a_choice_is_taken_as_picked_and_return_closes_it(qtbot: QtBot) -> None:
    root, tree = tree_of(qtbot)
    param = parameter_of(root, SPECS[2])
    item = open_row(qtbot, tree, param)
    qtbot.keyClick(item.widget, Qt.Key.Key_Down)  # type: ignore[no-untyped-call]
    assert param.value() == "b"
    qtbot.keyClick(item.widget, Qt.Key.Key_Return)  # type: ignore[no-untyped-call]
    qtbot.waitUntil(lambda: closed(item))
    assert param.value() == "b" and item.displayLabel.text() == "b"


@pytest.mark.no_auto_data_root  # RAM only: nothing left saving at quit (test_debug_runner_menu.py).
def test_the_value_taken_by_return_is_the_one_the_plot_runs_with(
        window: HelabMainWindow, qtbot: QtBot, tmp_path: Path) -> None:  # noqa: F811
    load(window, qtbot, run_folder(tmp_path, shots=3))
    plot(window, qtbot, "Counts per shot")
    [instance] = window.panel_right_bottom_script_selector.instances()
    assert instance.parameter_root is not None
    param = instance.parameter_root.child("Shots", "first_shot")
    tree = next(iter(param.items)).treeWidget()
    item = open_row(qtbot, tree, param)
    type_into(qtbot, item, "2", Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: closed(item))
    assert instance.values()["first_shot"] == 2
    before = instance.result
    instance.rerun_button.click()
    qtbot.waitUntil(lambda: instance.result is not before and instance.result is not None
                    and not instance.job_id, timeout=30_000)
    assert instance.result is not None and instance.result.parameters["first_shot"] == 2
