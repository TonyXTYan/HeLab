"""Every interactive control in HeLab's windows and dialogs has an accessible name, which a test
runner (macOS ``app_ax_find``, Windows UI Automation) searches for instead of clicking by pixel
(roadmaps/smoke-automation.md, item 4).

Each case opens a window or dialog (with synthetic data where a control only appears with a folder
or a plot), walks its interactive widgets and fails listing every one whose effective accessible
name is empty. A guard fails on any widget class in ``helab/views/`` that no case opens and that
isn't skipped with a reason, so a new window, dialog or widget can't escape the walk.

**The effective name.** PyQt6 doesn't bind ``QAccessible``, so ``effective_name`` follows Qt 6.11's
own rules (``src/widgets/accessible``): ``QAccessibleWidget::text(Name)`` is the widget's
``accessibleName()``, else a window's title, else the text of a ``QLabel`` whose buddy it is, or its
``QGroupBox`` parent's title (``buddyString``); a button's (``QAccessibleButton``) falls back to its
text, "&" stripped; a tab (``QAccessibleTabButton``) is its ``accessibleTabName`` or its text. A
combo box's current text and a line edit's placeholder are not counted, though Qt on Linux names a
combo by its current text: a runner needs a name that doesn't change with the choice. Tooltips are
the description (Qt's fallback for ``Description``), never the name.

**Interactive classes** (``INTERACTIVE``): ``QAbstractButton`` (push, tool, check and radio
buttons, and HeLab's own), ``QComboBox``, ``QLineEdit``, ``QAbstractSpinBox``, ``QAbstractSlider``,
``QTabBar`` (each tab), ``QAbstractItemView`` (trees, lists, tables), and editable ``QTextEdit`` /
``QPlainTextEdit``: everything a runner clicks, types into or picks from. Labels, progress bars and
frames are read, not operated, and Qt names labels by their text. Left out as parts of another
control, named by it (``part_of_another``): a scroll area's scroll bars, an item view's header,
the line edit inside a spin box or combo box, a combo's popup list, and Qt's own buttons that Qt
names itself (a tab bar's scroll arrows, a dock's Float and Close, a toolbar's extension arrow).
"""
from __future__ import annotations

import ast
import os
import time
from pathlib import Path
from typing import Callable, Iterable, Iterator

import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before any QApplication: the main window)
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractScrollArea, QAbstractSlider,
                             QAbstractSpinBox, QComboBox, QDialog, QDockWidget, QGroupBox, QHeaderView, QLabel,
                             QLineEdit, QPlainTextEdit, QPushButton, QScrollBar, QTabBar, QTextEdit, QToolBar,
                             QWidget)
from pytestqt.qtbot import QtBot

from helab.utils.folder_cache import FolderCache, get_folder_cache
from helab.utils.io_service import IORequest, IOService, get_io_service
from helab.utils.settings_store import app_settings

VIEWS = Path(__file__).resolve().parent.parent / "helab" / "views"

INTERACTIVE: tuple[type[QWidget], ...] = (
    QAbstractButton, QComboBox, QLineEdit, QAbstractSpinBox, QAbstractSlider, QTabBar, QAbstractItemView,
    QTextEdit, QPlainTextEdit)

# Qt's own buttons that Qt names itself (qtabbar.cpp, qdockwidget.cpp, qtoolbarextension.cpp).
QT_NAMED_PARTS = ("ScrollLeftButton", "ScrollRightButton", "qt_dockwidget_floatbutton",
                  "qt_dockwidget_closebutton", "qt_toolbar_ext_button",
                  # A menu bar's ">>", shown only when it is too narrow for its menus, which a runner uses.
                  "qt_menubar_ext_button")


def strip_amp(text: str) -> str:
    """``qt_accStripAmp``: "&" marks a mnemonic, "&&" is a literal "&"."""
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def buddy_text(widget: QWidget) -> str:
    """``buddyString``: a sibling label's text whose buddy is ``widget``, or its group box's title."""
    parent = widget.parentWidget()
    if parent is None:
        return ""
    for child in parent.children():
        if isinstance(child, QLabel) and child.buddy() is widget:
            return strip_amp(child.text())
    return strip_amp(parent.title()) if isinstance(parent, QGroupBox) else ""


def effective_name(widget: QWidget) -> str:
    """The accessible name Qt reports for ``widget`` (see the module docstring)."""
    if widget.accessibleName():
        return widget.accessibleName()
    if isinstance(widget, QAbstractButton) and widget.text():
        return strip_amp(widget.text())
    if widget.isWindow():
        return widget.windowTitle()
    return buddy_text(widget)


def unnamed_tabs(bar: QTabBar) -> list[int]:
    return [index for index in range(bar.count()) if not (bar.accessibleTabName(index) or bar.tabText(index))]


def part_of_another(widget: QWidget) -> bool:
    """A control's own part, named by that control (see the module docstring)."""
    parent = widget.parentWidget()
    if isinstance(widget, QScrollBar):
        return True
    if isinstance(widget, QHeaderView) and isinstance(parent, QAbstractItemView):
        return True
    if isinstance(widget, QLineEdit) and isinstance(parent, (QAbstractSpinBox, QComboBox)):
        return True
    if isinstance(widget, QAbstractItemView) and any(
            isinstance(ancestor, QComboBox) or ancestor.inherits("QComboBoxPrivateContainer")
            for ancestor in ancestors(widget)):
        return True
    return widget.objectName() in QT_NAMED_PARTS


def ancestors(widget: QWidget) -> Iterator[QWidget]:
    parent = widget.parentWidget()
    while parent is not None:
        yield parent
        parent = parent.parentWidget()


def interactive(widget: QWidget) -> bool:
    if isinstance(widget, (QTextEdit, QPlainTextEdit)):
        return not widget.isReadOnly()
    return isinstance(widget, INTERACTIVE)


def where(widget: QWidget) -> str:
    chain = [widget, *ancestors(widget)][:4]
    path = " < ".join(f"{type(w).__name__}{'#' + w.objectName() if w.objectName() else ''}" for w in chain)
    hint = widget.toolTip().splitlines()[0][:50] if widget.toolTip() else ""
    return f"{path}" + (f" (tooltip: {hint!r})" if hint else "")


def controls(window: QWidget) -> list[QWidget]:
    """The interactive controls of ``window``, shown or not, enabled or not (those of a window of
    their own, such as a floating plot or a tool window, are walked as that window)."""
    return [widget for widget in window.findChildren(QWidget)
            if interactive(widget) and not part_of_another(widget) and widget.window() is window]


def unnamed(window: QWidget) -> list[str]:
    """Every control of ``window`` without an accessible name or a stable ID: an ``objectName``, the
    same as its accessible identifier (what macOS and Windows report). Among the controls it shows,
    each ID is unique; hidden ones may share one with a shown one (each plot's settings page has
    the same controls, one page shown at a time; each folder tab the same path bar)."""
    missing = []
    ids: dict[str, QWidget] = {}
    for widget in controls(window):
        if isinstance(widget, QTabBar):
            missing += [f"{where(widget)}: tab {index} has no name" for index in unnamed_tabs(widget)]
        elif not effective_name(widget):
            missing.append(f"{where(widget)}: no name")
        ident = widget.objectName()
        if not ident:
            missing.append(f"{where(widget)}: no ID")
        elif widget.accessibleIdentifier() != ident:
            missing.append(f"{where(widget)}: accessible identifier {widget.accessibleIdentifier()!r} isn't its ID")
        elif not widget.isVisibleTo(window):
            continue
        elif ident in ids:
            missing.append(f"{where(widget)}: ID {ident!r} also used by {where(ids[ident])}")
        else:
            ids[ident] = widget
    return missing


class Walk:
    """The windows a case walked: every control without a name, and the classes seen."""

    def __init__(self) -> None:
        self.missing: list[str] = []
        self.seen: set[type] = set()

    def __call__(self, window: QWidget, label: str = "") -> None:
        name = label or type(window).__name__
        self.missing += [f"{name}: {line}" for line in unnamed(window)]
        self.seen |= {type(window), *(type(child) for child in window.findChildren(QWidget))}

    def check(self, covers: Iterable[str]) -> None:
        names = {cls.__name__ for cls in self.seen if cls.__module__.startswith("helab.views")}
        assert not self.missing, "Controls without an accessible name:\n" + "\n".join(self.missing)
        assert not set(covers) - names, f"Not walked: {sorted(set(covers) - names)}"


# Every QWidget subclass in helab/views and the case that opens it, or why none does.
COVERED: dict[str, str] = {}
SKIPPED: dict[str, str] = {}


def covers(*names: str) -> Callable[[Callable[..., None]], Callable[..., None]]:
    def mark(test: Callable[..., None]) -> Callable[..., None]:
        for name in names:
            COVERED[name] = test.__name__
        test.covers = names  # type: ignore[attr-defined]
        return test
    return mark


def frozen(monkeypatch: pytest.MonkeyPatch) -> tuple[IOService, FolderCache]:
    """A cache whose helpers never start (dialogs that only show its state)."""
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    return service, FolderCache(service)


def run_folder(root: Path, shots: int = 3) -> Path:
    """A synthetic TXY folder, settled (modified a minute ago)."""
    run = root / "run"
    run.mkdir()
    old = time.time() - 60
    for shot in range(1, shots + 1):
        path = run / f"d_txy_forc{shot}.txt"
        path.write_text("".join(f"{0.1 + i * 1e-3:.6f},{(i % 7) * 1e-3:.6f},{(i % 5) * 1e-3:.6f}\n"
                                for i in range(300)))
        os.utime(path, (old, old))
    return run


def quit_window(qtbot: QtBot, window: QWidget) -> None:
    """Close the main window as quitting does, and wait until it has (tests/test_presets_window.py)."""
    window.close()
    qtbot.waitUntil(lambda: getattr(window, "_closing"), timeout=30_000)


def script_button(window: QWidget, name: str) -> QPushButton:
    from helab.views.HelabMainWindow import HelabMainWindow
    assert isinstance(window, HelabMainWindow)
    tree = window.panel_right_bottom_script_selector.tree_widget
    group = tree.topLevelItem(0)
    assert group is not None
    for index in range(group.childCount()):
        item = group.child(index)
        if item is not None and item.text(0) == name:
            button = tree.itemWidget(item, 1)
            assert isinstance(button, QPushButton)
            return button
    raise AssertionError(f"No script {name!r} in {window.panel_right_bottom_script_selector.group_selector.currentText()}")


@covers("HelabMainWindow", "FolderTabWidget", "FolderExplorer", "FolderDetailsPanel", "LoadBar", "CentralHint",
        "ClickableLabel", "ElidedLabel", "HoverMenuToolButton", "TreePanelWidget", "PlotSettingsPanel", "PresetBar",
        "TxySourceRow", "AnalysisDock", "FloatingSettings", "SettingsToggle", "ReleasedPlot", "PlotPicture")
def test_the_main_window_with_a_folder_and_plots(qtbot: QtBot, tmp_path: Path) -> None:
    """The main window empty, then with a synthetic folder loaded, two plots tabbed together, one
    released (its picture and Reload) and one floating (its own settings section)."""
    from helab.views.FolderExplorer import FolderExplorer
    from helab.views.HelabMainWindow import HelabMainWindow
    from helab.views.plots.dock import AnalysisDock
    from helab.views.plots.instance import AnalysisInstance
    run = run_folder(tmp_path)
    walk = Walk()
    window = HelabMainWindow()
    qtbot.addWidget(window)
    window.show()
    try:
        qtbot.waitUntil(lambda: isinstance(window.tab_widget.currentWidget(), FolderExplorer), timeout=10_000)
        walk(window, "empty")
        window.add_new_folder_explorer_tab(target_path=str(run))
        explorer = window.tab_widget.currentWidget()
        assert isinstance(explorer, FolderExplorer)
        qtbot.waitUntil(lambda: explorer.displayed_dataset is not None
                        and explorer.displayed_dataset.path == str(run), timeout=30_000)
        walk(window, "loaded")
        for name in ("Counts per shot", "T, X, Y histograms"):
            script_button(window, name).click()
        scripts = window.panel_right_bottom_script_selector
        qtbot.waitUntil(lambda: len(scripts.instances()) == 2
                        and all(i.shown is not None for i in scripts.instances()), timeout=30_000)
        qtbot.wait(100)  # The docks' tab bar gets its close buttons on the next pass (DockTabCloser).
        walk(window, "plots")
        first, second = scripts.instances()
        assert isinstance(first, AnalysisInstance) and first.release()
        walk(window, "released")
        dock = second.dock_widget
        assert isinstance(dock, AnalysisDock)
        dock.setFloating(True)
        qtbot.waitUntil(lambda: dock.settings.page is not None, timeout=10_000)
        walk(dock, "floating plot")
        dock.set_settings_open(True)
        walk(dock, "floating plot, its settings open")
        walk(window, "with a floating plot")
    finally:
        quit_window(qtbot, window)
    walk.check(test_the_main_window_with_a_folder_and_plots.covers)  # type: ignore[attr-defined]


def settled(qtbot: QtBot, service: IOService) -> None:
    """The app's helpers have answered (a window's lists filled from them)."""
    qtbot.waitUntil(lambda: not service.active and not service.pending, timeout=30_000)


@covers("SettingsDialog", "LabParametersTab", "ConverterTab", "CacheTab", "RamBudgetSpinBox", "DataRootsTab",
        "ProfileEditor")
def test_settings_and_each_of_its_tabs(qtbot: QtBot) -> None:
    from helab.convert.profile import MATLAB_2019
    from helab.views.ConverterTab import ProfileEditor
    from helab.views.SettingsDialog import SettingsDialog
    service = get_io_service()
    dialog = SettingsDialog(settings=app_settings(), cache=get_folder_cache(service))
    qtbot.addWidget(dialog)
    dialog.show()
    walk = Walk()
    try:
        settled(qtbot, service)
        for index in range(dialog.tabs.count()):
            dialog.tabs.setCurrentIndex(index)
            walk(dialog, f"Settings › {dialog.tabs.tabText(index)}")
        editor = ProfileEditor(MATLAB_2019.replace(name="mine"), dialog)
        editor.show()
        walk(editor)
        editor.reject()
    finally:
        dialog.reject()
    walk.check(test_settings_and_each_of_its_tabs.covers)  # type: ignore[attr-defined]


def sighting(cache: FolderCache, path: str) -> None:
    """A .helab-root also seen elsewhere (tests/test_root_duplicates.py)."""
    request = IORequest("tab", 0, path, "list", {}, 60.0)
    cache.service.resultReady.emit(request, {
        "kind": "root_duplicate", "path": path, "location": "smb://host/second", "uuid": "u", "label": "second",
        "other_locations": ["smb://host/first"], "marker": {"size": 10, "mtime": 1.0, "ino": 7},
        "others": [{"location": "smb://host/first", "path": "/helab-test-nowhere/first",
                    "marker": {"size": 10, "mtime": 1.0, "ino": 7}}]})


def presets_inspector(cache: FolderCache, path: Path) -> QWidget:
    from helab.views.PresetsInspector import PresetsInspector
    return PresetsInspector(cache)


def folder_constants(cache: FolderCache, path: Path) -> QWidget:
    from helab.views.FolderConstantsDialog import FolderConstantsDialog
    cache.set_lab_constants({"g": 9.8})
    return FolderConstantsDialog(str(path), cache)


def missing_shots(cache: FolderCache, path: Path) -> QWidget:
    from helab.views.MissingShotsWindow import MissingShotsWindow
    window = MissingShotsWindow(cache)
    for run in ("run1", "run2"):
        cache._mismatch(str(path / run), {"missing": [1, 2], "missing_count": 2, "known_count": 3,
                                          "listed_count": 1}, "load")
    return window


def root_duplicates(cache: FolderCache, path: Path) -> QWidget:
    from helab.views.RootDuplicatesWindow import RootDuplicatesWindow
    window = RootDuplicatesWindow(cache)
    sighting(cache, str(path / "second"))
    return window


def copy_root(cache: FolderCache, path: Path) -> QWidget:
    from helab.views.RootDuplicatesWindow import CopyRootDialog
    return CopyRootDialog(None, {"location": "smb://host/second", "path": str(path / "second"),
                                 "others": [{"location": "smb://host/first", "path": ""}]})


def manual_marker(cache: FolderCache, path: Path) -> QWidget:
    from helab.utils import data_roots
    from helab.views.DataRootDialogs import ManualMarkerDialog
    _, contents = data_roots.new_marker(str(path))
    return ManualMarkerDialog(None, cache, str(path), ".helab-root", contents.decode("utf-8"), "Read-only file system")


def place_root(cache: FolderCache, path: Path) -> QWidget:
    from helab.views.DataRootDialogs import PlaceRootBox
    return PlaceRootBox(None, cache, str(path / "data" / "run"))


def large_folder(cache: FolderCache, path: Path) -> QWidget:
    from helab.views.LargeFolderDialog import LargeFolderDialog
    return LargeFolderDialog(str(path), 2 * 10**9, 16 * 10**9, 128 * 10**9)


def quit_save(cache: FolderCache, path: Path) -> QWidget:
    from helab.views.QuitSaveDialog import QuitSaveDialog
    return QuitSaveDialog(cache)


def debug_icons(cache: FolderCache, path: Path) -> QWidget:
    from helab.resources.icons import IconsInitUtil
    from helab.views.DebugIconsWindow import DebugIconsWindow
    IconsInitUtil.initialise_icons()  # (As main.py does before the window opens.)
    return DebugIconsWindow()


def memory_usage(cache: FolderCache, path: Path) -> QWidget:
    from helab.views.MemoryUsageWindow import MemoryUsageWindow
    return MemoryUsageWindow()


DIALOGS: dict[str, tuple[Callable[[FolderCache, Path], QWidget], tuple[str, ...]]] = {
    "presets inspector": (presets_inspector, ("PresetsInspector",)),
    "folder constants": (folder_constants, ("FolderConstantsDialog",)),
    "missing shots": (missing_shots, ("MissingShotsWindow",)),
    "root duplicates": (root_duplicates, ("RootDuplicatesWindow",)),
    "copy root": (copy_root, ("CopyRootDialog",)),
    "manual marker": (manual_marker, ("ManualMarkerDialog",)),
    "place root": (place_root, ("PlaceRootBox",)),
    "large folder": (large_folder, ("LargeFolderDialog",)),
    "quit save": (quit_save, ("QuitSaveDialog",)),
    "debug icons": (debug_icons, ("DebugIconsWindow", "_IconGroup")),
    "memory usage": (memory_usage, ("MemoryUsageWindow",)),
}
COVERED.update({name: f"test_dialog[{case}]" for case, (_, names) in DIALOGS.items() for name in names})


@pytest.mark.parametrize("case", list(DIALOGS))
def test_dialog(case: str, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    make, names = DIALOGS[case]
    service, cache = frozen(monkeypatch)
    try:
        window = make(cache, tmp_path)
        qtbot.addWidget(window)
        window.show()
        qtbot.wait(50)
        walk = Walk()
        walk(window, case)
        walk.check(names)
        if isinstance(window, QDialog):
            window.reject()
        window.close()
    finally:
        service.shutdown()


def test_the_walk_finds_unnamed_controls_and_repeated_ids(qtbot: QtBot) -> None:
    """The walk itself: an icon-only button, an unlabelled box and a reused ID are each listed; a
    labelled button, a buddy's box and a hidden page's repeat are not."""
    from PyQt6.QtWidgets import QSpinBox, QToolButton, QVBoxLayout
    window = QWidget()
    qtbot.addWidget(window)
    layout = QVBoxLayout(window)
    icon_only, named = QToolButton(), QPushButton("&Save")
    labelled, unlabelled = QSpinBox(), QSpinBox()
    buddy = QLabel("&Shots")
    buddy.setBuddy(labelled)
    hidden = QPushButton("Save")
    for widget in (icon_only, named, buddy, labelled, unlabelled, hidden):
        layout.addWidget(widget)
    for widget, ident in ((icon_only, "icon"), (named, "save"), (labelled, "shots"), (unlabelled, "shots"),
                          (hidden, "save")):
        widget.setObjectName(ident)
        widget.setAccessibleIdentifier(ident)
    hidden.hide()
    window.show()
    assert effective_name(named) == "Save" and effective_name(labelled) == "Shots"
    missing = unnamed(window)
    assert [line.split(": ", 1)[1] for line in missing] == [
        "no name", "no name", "ID 'shots' also used by QSpinBox#shots < QWidget"], missing
    icon_only.setObjectName("other")
    assert any("accessible identifier 'icon' isn't its ID" in line for line in unnamed(window))


def widget_classes() -> dict[str, type]:
    """Every QWidget subclass defined in a module of helab/views (by class name; unique there)."""
    import importlib
    import inspect
    found: dict[str, type] = {}
    for path in sorted(VIEWS.rglob("*.py")):
        module = importlib.import_module(".".join(("helab", *path.relative_to(VIEWS.parent).with_suffix("").parts)))
        for name, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__ and issubclass(cls, QWidget):
                assert found.setdefault(name, cls) is cls, f"Two widget classes named {name}"
    return found


def test_every_widget_class_in_views_is_walked_or_skipped_with_a_reason() -> None:
    """A new window, dialog or widget in helab/views must be opened by a case here (``covers``,
    ``DIALOGS``) or skipped with its reason (``SKIPPED``)."""
    classes = set(widget_classes())
    assert not classes - set(COVERED) - set(SKIPPED), (
        f"Widget classes no case opens: {sorted(classes - set(COVERED) - set(SKIPPED))}. Open each in a case "
        "here (with synthetic data if its controls need a folder or a plot), or add it to SKIPPED with why.")
    assert not (set(COVERED) | set(SKIPPED)) - classes, f"Listed but gone: {sorted((set(COVERED) | set(SKIPPED)) - classes)}"
    assert not set(COVERED) & set(SKIPPED)
