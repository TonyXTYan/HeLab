"""Live scripts in the Scripts panel (helab/views/plots/script_tree.py) and their open plots
(``AnalysisInstance.adopt_script``, ``keep_script``): Reload, remembered folders, auto-reload, load
errors, and plots rerunning on the new code with their settings, or keeping the old code. Scripts
are written into ``tmp_path``; no real data (datasets are made in memory).

The manager's reload alone: tests/test_scripts_reload.py.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import pytest
from typing import Iterator

from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from helab.analysis.dataset_view import view_of
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.utils.folder_cache import FolderCache
from helab.utils.settings_defaults import SCRIPT_AUTO_RELOAD_SETTING, SCRIPT_FOLDERS_SETTING, read_setting
from helab.utils.settings_store import app_settings
from helab.views.plots.instance import AnalysisInstance
from helab.analysis.presets import Arrangement, SavedPlot, ScriptRef
from helab.utils.cache_paths import Mount
from helab.utils.settings_defaults import OPEN_PLOTS_SETTING
from helab.views.plots import script_tree
from helab.views.plots.arrangement import PlotReopen
from helab.views.plots.script_tree import ProbeFailure, TreePanelWidget, loading_marker, marker_path, on_network, read_script_folders
from test_presets_plots import (Window, Windows, cache, dataset, folder, fresh_presets, new_window,  # noqa: F401
                                      no_disk_cache, runner, set_values, windows)
from test_scripts_reload import restored_imports  # noqa: F401

HEADER = '''
from typing import Any, List, Optional
from PyQt6.QtWidgets import QLabel, QWidget
from helab.analysis.parameters import ParameterSpec
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
'''

# A script with three settings; its result names its helper's TAG, so a test sees which code ran.
SCRIPT = HEADER + '''
import {helper}

class Live(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata("{name}", "test", "Lab", __file__, "lab.live", "{version}")

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [{specs}]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        {wait}return ({helper}.TAG, dict(context.parameters))

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        return QLabel(str(result.data), parent)
'''
SPECS = ('ParameterSpec("bins", "Bins", "int", 10, (1, 100)), ParameterSpec("scale", "Scale", "float", 1.0), '
         'ParameterSpec("mode", "Mode", "choice", "a", choices=("a", "b"))')
# The edited script: Scale removed, Mode now a number, Extra new.
EDITED = ('ParameterSpec("bins", "Bins", "int", 10, (1, 100)), ParameterSpec("mode", "Mode", "int", 0, (0, 9)), '
          'ParameterSpec("extra", "Extra", "bool", True)')


@pytest.fixture(autouse=True)
def no_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Folders import at once, without their test import in a separate process (Q49.3 (b), whose own tests
    are tests/test_script_probe.py)."""
    monkeypatch.setattr(script_tree, "PROBING", False)


@pytest.fixture(autouse=True)
def no_marker() -> Iterator[None]:
    """No loading marker before or after a test (the app folder lasts the xdist worker)."""
    def remove() -> None:
        try:
            os.remove(marker_path())
        except FileNotFoundError:
            pass

    remove()
    yield
    remove()


# A compute that says it started, then blocks until the test opens its gate (ignoring cancellation).
BLOCKS = "{helper}.STARTED.set()\n        {helper}.GATE.wait(30)\n        "


def write_script(folder_: Path, helper: str, tag: str, *, specs: str = SPECS, name: str = "Live",
                 version: str = "1", wait: str = "") -> None:
    (folder_ / f"{helper}.py").write_text(f"import threading\nTAG = {tag!r}\nGATE = threading.Event()\n"
                                         "STARTED = threading.Event()\n")
    (folder_ / "live.py").write_text(SCRIPT.format(helper=helper, specs=specs, name=name, version=version,
                                                   wait=wait))


def open_plot(qtbot: QtBot, window: Window, cache: FolderCache) -> AnalysisInstance:
    """A plot of the folder's ``Live`` script on three shots, once it has drawn."""
    scripts = window.scripts
    window.view = view_of(dataset("run", range(1, 4)), cache.root_of(folder("run")))
    (metadata,) = scripts.script_manager.get_scripts_in_group("Lab")
    script_class = scripts.script_manager.get_script(metadata.script_id)
    assert script_class is not None
    script = script_class()
    assert isinstance(script, DatasetAnalysis)
    instance = scripts.run_analysis(metadata, script, "Plot")
    assert instance is not None
    qtbot.waitUntil(lambda: instance.shown is not None, timeout=10_000)
    return instance


def shown_tag(instance: AnalysisInstance) -> Any:
    assert instance.shown is not None
    return instance.shown.data[0]


def test_reload_reruns_an_open_plot_on_the_new_code_keeping_its_settings(
        qtbot: QtBot, cache: FolderCache, windows: Windows, tmp_path: Path) -> None:
    window = new_window(qtbot, cache, windows)
    write_script(tmp_path, "lab_live_a", "old")
    window.scripts.add_folder(str(tmp_path))
    instance = open_plot(qtbot, window, cache)
    assert shown_tag(instance) == "old"
    set_values(instance, {"bins": 5, "scale": 2.5, "mode": "b"})
    dock, number, old_script = instance.dock_widget, instance.instance_id, instance.script
    write_script(tmp_path, "lab_live_a", "new", specs=EDITED, name="Live, edited")
    window.scripts.reload_scripts()
    qtbot.waitUntil(lambda: instance.shown is not None and shown_tag(instance) == "new", timeout=10_000)
    assert instance.script is not old_script and instance.name == "Live, edited"
    assert instance.dock_widget is dock and instance.instance_id == number
    assert dock is not None and dock.windowTitle() == f"Live, edited ({number})"
    # Bins kept; Mode retyped and Extra new: at their defaults; Scale gone.
    assert instance.values() == {"bins": 5, "mode": 0, "extra": True}
    assert instance.shown is not None and instance.shown.data[1] == {"bins": 5, "mode": 0, "extra": True}
    assert instance.presets is not None
    note = instance.presets.note.text()
    assert note.startswith("Reloaded · ⚠ 3 settings at the script's defaults: Mode")
    assert "scale: not a setting of this script now" in instance.presets.note.toolTip()
    assert "another copy" not in instance.presets.note.toolTip()
    assert any(text.startswith("Reloaded 1 script folder · 1 plot rerun") for text in window.notices)


def test_a_script_that_fails_to_reload_leaves_its_plot_on_the_old_code(
        qtbot: QtBot, cache: FolderCache, windows: Windows, tmp_path: Path) -> None:
    window = new_window(qtbot, cache, windows)
    write_script(tmp_path, "lab_live_b", "old")
    window.scripts.add_folder(str(tmp_path))
    instance = open_plot(qtbot, window, cache)
    old_script, shown = instance.script, instance.shown
    (tmp_path / "live.py").write_text("def broken(:\n")
    window.scripts.reload_scripts()
    assert instance.script is old_script and instance.shown is shown  # Its last result stays.
    assert instance._script_note.startswith("⚠ Script didn't reload (SyntaxError: ")
    assert "still running the code loaded at" in instance.status_label.text()
    dock = instance.dock_widget
    assert dock is not None and str(dock.property("plotError")).startswith("⚠ Script didn't reload")
    (line,) = window.scripts.error_items()
    assert line.text(0).startswith("live.py: SyntaxError: ") and "Traceback" in line.toolTip(0)
    # Rerun runs the code it has.
    instance.run()
    qtbot.waitUntil(lambda: instance.shown is not shown and instance.shown is not None, timeout=10_000)
    assert shown_tag(instance) == "old"
    # Fixed: the next reload gives it the new code, and the error goes.
    write_script(tmp_path, "lab_live_b", "fixed")
    window.scripts.reload_scripts()
    qtbot.waitUntil(lambda: shown_tag(instance) == "fixed", timeout=10_000)
    assert instance._script_note == "" and window.scripts.error_items() == []


def test_a_vanished_class_or_a_removed_folder_keeps_the_old_code(
        qtbot: QtBot, cache: FolderCache, windows: Windows, tmp_path: Path) -> None:
    window = new_window(qtbot, cache, windows)
    write_script(tmp_path, "lab_live_c", "old")
    window.scripts.add_folder(str(tmp_path))
    instance = open_plot(qtbot, window, cache)
    (tmp_path / "live.py").write_text((tmp_path / "live.py").read_text().replace('"lab.live"', '"lab.other"'))
    window.scripts.reload_scripts()
    assert "(its class is gone from its folder)" in instance._script_note
    window.scripts.remove_folder(str(tmp_path))
    assert "(its folder was removed from the Scripts list)" in instance._script_note
    assert window.scripts.script_manager.folders() == [] and read_script_folders() == []
    assert "Lab" not in window.scripts.groups


def test_a_reload_waits_for_a_run_of_its_scripts_on_the_worker_thread(
        qtbot: QtBot, cache: FolderCache, windows: Windows, tmp_path: Path) -> None:
    """CoCo: a reload never runs while a compute of that script is on the worker thread; this one
    ignores cancellation, so the reload waits until its compute returns."""
    window = new_window(qtbot, cache, windows)
    write_script(tmp_path, "lab_live_d", "old", wait=BLOCKS.format(helper="lab_live_d"))
    window.scripts.add_folder(str(tmp_path))
    gate, started = sys.modules["lab_live_d"].GATE, sys.modules["lab_live_d"].STARTED
    gate.set()
    instance = open_plot(qtbot, window, cache)
    gate.clear()
    started.clear()
    instance.run()
    # Its compute has started on the worker (queued only, the cancel would end it before it runs).
    qtbot.waitUntil(started.is_set, timeout=10_000)
    old_class = type(instance.script)
    write_script(tmp_path, "lab_live_d", "new")
    window.scripts.reload_scripts()
    assert window.scripts.reload_button.text() == "Reload (waiting)"
    assert window.scripts.script_manager.get_script(f"{tmp_path / 'live.py'}::Live") is old_class  # Not yet.
    # L1: held meanwhile: a Rerun (or a Live revision) submits nothing on the old code.
    job = instance.job_id
    instance.run()
    assert instance.status_label.text() == "Waiting for its script to reload…"
    assert len(instance.runner.in_flight()) == 1 and instance.job_id == job
    gate.set()  # Its compute returns (as cancelled): the reload goes on.
    qtbot.waitUntil(lambda: instance.shown is not None and shown_tag(instance) == "new", timeout=10_000)
    assert window.scripts.reload_button.text() == "Reload"


def test_folders_are_remembered_restored_and_removed(qtbot: QtBot, tmp_path: Path) -> None:
    first, missing = tmp_path / "first", tmp_path / "missing"
    first.mkdir()
    write_script(first, "lab_live_e", "one")
    scripts = TreePanelWidget()
    qtbot.addWidget(scripts)
    assert not scripts.reload_button.isEnabled()
    scripts.add_folder(str(first))
    scripts.add_folder(str(missing))
    assert json.loads(read_setting(app_settings(), SCRIPT_FOLDERS_SETTING, typed=True)) == [str(first), str(missing)]
    assert scripts.reload_button.isEnabled()
    # At the next start: both listed, the missing one with its line (once the deferred restore has run).
    again = TreePanelWidget()
    qtbot.addWidget(again)
    again.restore_folders()
    assert again.script_manager.folders() == [str(first), str(missing)] and "Lab" in again.groups
    assert [item.text(0) for item in again.error_items()] == ["missing: folder not found"]
    again._fill_folders_menu()
    titles = [action.text() for action in again.folders_menu.actions()]
    assert str(first) in titles and str(missing) in titles and "Reload when a script is saved" in titles
    again.remove_folder(str(missing))
    assert read_script_folders() == [str(first)] and again.error_items() == []
    # An unreadable setting: none restored.
    app_settings().setValue(SCRIPT_FOLDERS_SETTING, "not json")
    assert read_script_folders() == []


def test_auto_reload_watches_only_the_script_folders_while_on(qtbot: QtBot, tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    write_script(tmp_path, "lab_live_f", "one")
    scripts = TreePanelWidget()
    qtbot.addWidget(scripts)
    scripts.add_folder(str(tmp_path))
    assert scripts.watched() == [] and scripts._watcher is None  # Off by default: no watcher at all.
    scripts.auto_reload_action.setChecked(True)
    assert read_setting(app_settings(), SCRIPT_AUTO_RELOAD_SETTING, typed=True) is True
    assert scripts.watched() == sorted([str(tmp_path), str(tmp_path / "lab_live_f.py"), str(tmp_path / "live.py")])
    reloaded: List[Optional[List[str]]] = []
    monkeypatch.setattr(scripts, "reload_scripts", lambda folders=None, deliberate=True: reloaded.append(folders))
    scripts._check_changes()
    assert reloaded == []  # Nothing changed.
    (tmp_path / "notes.txt").write_text("not a script")
    scripts._check_changes()
    assert reloaded == []
    (tmp_path / "lab_live_f.py").write_text("TAG = 'two, longer'\n")
    scripts._check_changes()
    assert reloaded == [[str(tmp_path)]]
    # A file event starts the settle wait, after which it compares.
    scripts._changed(str(tmp_path / "live.py"))
    assert scripts._settle.isActive()
    # Restored at the next start; off again drops the watcher.
    again = TreePanelWidget()
    qtbot.addWidget(again)
    again.restore_folders()
    assert again.auto_reload_action.isChecked() and again.watched()
    again.set_auto_reload(False)
    assert again._watcher is None and again.watched() == []
    assert read_setting(app_settings(), SCRIPT_AUTO_RELOAD_SETTING, typed=True) is False


def test_a_load_error_shows_its_traceback_in_a_details_window(qtbot: QtBot, tmp_path: Path) -> None:
    (tmp_path / "raises.py").write_text("raise ValueError('lab script failed')\n")
    scripts = TreePanelWidget()
    qtbot.addWidget(scripts)
    scripts.add_folder(str(tmp_path))
    (line,) = scripts.error_items()
    assert line.text(0) == "raises.py: lab script failed"
    parent = line.parent()
    assert parent is not None and parent.text(0) == "⚠ 1 script file didn't load"
    # Whatever group is shown.
    scripts.group_selector.setCurrentText("DLD Front Panel Port")
    assert [item.text(0) for item in scripts.error_items()] == ["raises.py: lab script failed"]
    (error,) = scripts.script_manager.errors()
    box = scripts.show_error_details(error)
    assert isinstance(box, QMessageBox) and not box.isModal() and box.objectName() == "script_error_details"
    assert "ValueError: lab script failed" in box.detailedText()
    box.close()
    scripts._show_error_details(scripts.error_items()[0], 0)  # (A double-click; the tree was made again.)
    assert scripts._details is not None
    scripts._details.close()


def test_loading_a_loaded_folder_again_is_a_reload(qtbot: QtBot, tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    write_script(tmp_path, "lab_live_g", "one")
    scripts = TreePanelWidget()
    qtbot.addWidget(scripts)
    scripts.add_folder(str(tmp_path))
    called: List[Any] = []
    monkeypatch.setattr(scripts, "reload_scripts", lambda folders=None, deliberate=True: called.append(folders))
    scripts.add_folder(str(tmp_path) + "/.")
    assert called == [[str(tmp_path)]]



# M3: remembered folders at start


def test_remembered_folders_load_after_the_panel_is_made_and_plots_wait_for_them(
        qtbot: QtBot, cache: FolderCache, windows: Windows, tmp_path: Path) -> None:
    """M3: no user code runs while the panel (and the window) is made; the folders load once the event
    loop runs, and the plots to reopen wait for them, so a plot of a user's script reopens."""
    write_script(tmp_path, "lab_live_h", "start")
    app_settings().setValue(SCRIPT_FOLDERS_SETTING, json.dumps([str(tmp_path)]))
    app_settings().setValue(OPEN_PLOTS_SETTING, Arrangement((SavedPlot(ScriptRef("lab.live", "Plot", "1"),
                                                                       folder("run")),)).dumps())
    window = new_window(qtbot, cache, windows)
    scripts = window.scripts
    assert scripts.folders_pending and "Lab" not in scripts.groups and "lab_live_h" not in sys.modules
    reopen = PlotReopen(window.plots, scripts)
    assert reopen.restore() == []  # (Waits for the folders.)
    with qtbot.waitSignal(scripts.foldersRestored, timeout=10_000):
        pass
    assert not scripts.folders_pending and "Lab" in scripts.groups
    qtbot.waitUntil(lambda: len(scripts.instances()) == 1, timeout=10_000)
    assert scripts.instances()[0].name == "Live"


def test_a_load_that_never_ended_skips_the_remembered_folders_at_the_next_start(
        qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M3: the loading marker is set while a folder loads; a start that finds it (a script blocked or
    crashed HeLab) loads no remembered folder and says so in one line; Reload loads them."""
    write_script(tmp_path, "lab_live_i", "one")
    seen: List[Optional[str]] = []
    scripts = TreePanelWidget()
    qtbot.addWidget(scripts)
    load = scripts.script_manager.add_folder

    def spying(folder_: str) -> bool:
        seen.append(loading_marker())
        return load(folder_)

    monkeypatch.setattr(scripts.script_manager, "add_folder", spying)
    scripts.add_folder(str(tmp_path))
    assert seen == [str(tmp_path)] and loading_marker() is None  # Set during the load, removed after.
    # A start after a load that never ended.
    with open(marker_path(), "w", encoding="utf-8") as handle:
        json.dump({"folder": str(tmp_path)}, handle)
    again = TreePanelWidget()
    qtbot.addWidget(again)
    again.restore_folders()
    assert "Lab" not in again.groups and again.script_manager.folders() == []
    assert not again.start_note.isHidden() and again.start_note.objectName() == "scripts_start_note"
    assert again.start_note.text().startswith("⚠ 1 script folder not loaded at start (HeLab stopped while loading")
    assert loading_marker() == str(tmp_path)  # (Kept until that folder loads.)
    assert read_script_folders() == [str(tmp_path)]  # Still remembered.
    again._fill_folders_menu()
    assert any("not loaded" in action.text() for action in again.folders_menu.actions())
    again.reload_scripts()
    assert "Lab" in again.groups and again.start_note.isHidden() and loading_marker() is None


def test_a_remembered_folder_on_a_share_waits_for_reload_and_is_never_watched(
        qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M3: a folder on a network share isn't listed at start (it may be unreachable): it waits for Reload,
    and auto-reload never stats it."""
    write_script(tmp_path, "lab_live_j", "one")
    app_settings().setValue(SCRIPT_FOLDERS_SETTING, json.dumps([str(tmp_path)]))
    app_settings().setValue(SCRIPT_AUTO_RELOAD_SETTING, True)
    monkeypatch.setattr(script_tree, "on_network", lambda folder_: True)
    scripts = TreePanelWidget()
    qtbot.addWidget(scripts)
    scripts.restore_folders()
    assert scripts.script_manager.folders() == [] and "on a network share" in scripts.start_note.text()
    assert scripts.watched() == []
    scripts.reload_scripts()  # The user's word: loaded.
    assert "Lab" in scripts.groups and scripts.start_note.isHidden()
    assert scripts.watched() == []  # Never watched.


def test_on_network_reads_the_mount_table_only(monkeypatch: pytest.MonkeyPatch) -> None:
    mounts = [Mount("/dev/disk1", "/", "apfs"), Mount("//lab@server/data", "/Volumes/data", "smbfs", True),
              Mount("server:/export", "/mnt/nfs", "nfs")]
    monkeypatch.setattr("helab.utils.cache_paths.current_mounts", lambda: mounts)
    assert on_network("/Volumes/data/scripts") and on_network("/mnt/nfs/lab")
    assert not on_network("/Users/lab/scripts") and not on_network("/Volumes/database")

    def broken() -> List[Mount]:
        raise OSError("no mount table")

    monkeypatch.setattr("helab.utils.cache_paths.current_mounts", broken)
    assert not on_network("/Volumes/data/scripts")  # (Unknown: taken as local, as before.)


# Lows and nits


def test_removing_the_folder_a_reload_waits_for_ends_the_wait(
        qtbot: QtBot, cache: FolderCache, windows: Windows, tmp_path: Path) -> None:
    """L2: "Reload (waiting)" ends when the folder it waits for is removed from the list."""
    window = new_window(qtbot, cache, windows)
    write_script(tmp_path, "lab_live_k", "old", wait=BLOCKS.format(helper="lab_live_k"))
    window.scripts.add_folder(str(tmp_path))
    gate, started = sys.modules["lab_live_k"].GATE, sys.modules["lab_live_k"].STARTED
    gate.set()
    instance = open_plot(qtbot, window, cache)
    gate.clear()
    started.clear()
    instance.run()
    qtbot.waitUntil(started.is_set, timeout=10_000)  # (Computing, not only queued.)
    window.scripts.reload_scripts()
    assert window.scripts.reload_button.text() == "Reload (waiting)"
    window.scripts.remove_folder(str(tmp_path))
    assert window.scripts.reload_button.text() == "Reload" and window.scripts._waiting_on == []
    gate.set()
    qtbot.waitUntil(lambda: not instance.runner.in_flight(), timeout=10_000)


Round = Tuple[List[str], Callable[[Dict[str, Optional[ProbeFailure]]], None]]


def fake_probes(monkeypatch: pytest.MonkeyPatch, scripts: TreePanelWidget) -> List[Round]:
    """Test imports on (Q49.3 (b)), each round's answer the test's to give: ``answer({folder: None})``."""
    rounds: List[Round] = []
    monkeypatch.setattr(script_tree, "PROBING", True)
    monkeypatch.setattr(scripts._probes, "probe", lambda folders, answer: rounds.append((list(folders), answer)))
    return rounds


def imports_seen(monkeypatch: pytest.MonkeyPatch, scripts: TreePanelWidget) -> List[int]:
    """For each real import of a folder: how many runs of its scripts were queued or computing then."""
    seen: List[int] = []
    manager = scripts.script_manager
    add = manager.add_folder

    def adding(folder_: str) -> bool:
        seen.append(scripts._busy({folder_}))
        return add(folder_)
    monkeypatch.setattr(manager, "add_folder", adding)
    return seen


def lab_script(scripts: TreePanelWidget) -> Tuple[ScriptMetadata, DatasetAnalysis]:
    (metadata,) = scripts.script_manager.get_scripts_in_group("Lab")
    script_class = scripts.script_manager.get_script(metadata.script_id)
    assert script_class is not None
    script = script_class()
    assert isinstance(script, DatasetAnalysis)
    return metadata, script


def test_a_plot_opened_while_its_folder_is_tested_waits_for_the_reload(
        qtbot: QtBot, cache: FolderCache, windows: Windows, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C-4 (PR #11): a plot opened from the folder while Reload reads "Reload (checking)" is held from its
    start: no compute of the old code runs under the real import, and it opens on the new code."""
    window = new_window(qtbot, cache, windows)
    scripts = window.scripts
    write_script(tmp_path, "lab_live_p", "old", wait=BLOCKS.format(helper="lab_live_p"))
    scripts.add_folder(str(tmp_path))
    started = sys.modules["lab_live_p"].STARTED
    rounds, seen = fake_probes(monkeypatch, scripts), imports_seen(monkeypatch, scripts)
    window.view = view_of(dataset("run", range(1, 4)), cache.root_of(folder("run")))
    scripts.reload_scripts()
    assert scripts.reload_button.text() == "Reload (checking)" and len(rounds) == 1
    instance = scripts.run_analysis(*lab_script(scripts), "Plot")
    assert instance is not None
    qtbot.waitUntil(lambda: started.is_set() or instance.status_label.text() == "Waiting for its script to reload…",
                    timeout=10_000)
    write_script(tmp_path, "lab_live_p", "new")
    folders, answer = rounds[0]
    old_gate = sys.modules["lab_live_p"].GATE
    answer({folder_: None for folder_ in folders})
    assert seen == [0]  # (Imported at once: no run of the old code under it.)
    old_gate.set()  # (Had the old compute run, it would return now.)
    qtbot.waitUntil(lambda: instance.shown is not None and shown_tag(instance) == "new", timeout=10_000)
    assert seen == [0] and not started.is_set() and len(rounds) == 1
    assert scripts.reload_button.text() == "Reload"


@pytest.mark.parametrize("kept", ["test import failed", "folder removed"])
def test_a_plot_held_from_its_start_whose_folder_keeps_its_code_runs_it(
        qtbot: QtBot, cache: FolderCache, windows: Windows, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        kept: str) -> None:
    """C4-1 (PR #11, round 2): a plot opened during the round is held before its first run; when the round
    keeps its folder's code (its test import failed, or the folder was removed meanwhile), it runs that code
    then (``keep_script``) and draws, saying why it kept it."""
    window = new_window(qtbot, cache, windows)
    scripts = window.scripts
    write_script(tmp_path, "lab_live_s", "old")
    scripts.add_folder(str(tmp_path))
    rounds = fake_probes(monkeypatch, scripts)
    window.view = view_of(dataset("run", range(1, 4)), cache.root_of(folder("run")))
    scripts.reload_scripts()
    instance = scripts.run_analysis(*lab_script(scripts), "Plot")
    assert instance is not None and instance.status_label.text() == "Waiting for its script to reload…"
    folders, answer = rounds[0]
    if kept == "folder removed":
        scripts.remove_folder(str(tmp_path))
    answer({folder_: ProbeFailure("it hung") for folder_ in folders})
    qtbot.waitUntil(lambda: instance.shown is not None, timeout=10_000)
    assert shown_tag(instance) == "old" and "⚠ Script didn't reload" in instance._script_note
    assert not scripts._probing and len(rounds) == 1


def test_the_import_waits_for_a_run_that_started_while_its_folder_was_tested(
        qtbot: QtBot, cache: FolderCache, windows: Windows, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C-4 (PR #11): a run of the folder's scripts queued during the round (any way) still computing when the
    test imports answer: the real import waits for it ("Reload (waiting)"), keeping the answers (no second
    round), then goes on. A reload asked meanwhile follows in its own round."""
    window = new_window(qtbot, cache, windows)
    scripts = window.scripts
    write_script(tmp_path, "lab_live_q", "old", wait=BLOCKS.format(helper="lab_live_q"))
    scripts.add_folder(str(tmp_path))
    gate, started = sys.modules["lab_live_q"].GATE, sys.modules["lab_live_q"].STARTED
    gate.set()
    instance = open_plot(qtbot, window, cache)
    gate.clear()
    started.clear()
    rounds, seen = fake_probes(monkeypatch, scripts), imports_seen(monkeypatch, scripts)
    old_class = type(instance.script)
    scripts.reload_scripts()
    assert len(rounds) == 1
    instance.runner.submit(old_class(), instance.metadata, "Plot", instance.view)  # (Not the plot's: held.)
    qtbot.waitUntil(started.is_set, timeout=10_000)
    write_script(tmp_path, "lab_live_q", "new")
    folders, answer = rounds[0]
    answer({folder_: None for folder_ in folders})
    assert scripts.reload_button.text() == "Reload (waiting)" and seen == []
    assert scripts.script_manager.get_script(f"{tmp_path / 'live.py'}::Live") is old_class  # Not yet.
    scripts.reload_scripts()  # (Follows this round in its own.)
    assert len(rounds) == 1
    gate.set()
    qtbot.waitUntil(lambda: len(rounds) == 2, timeout=10_000)
    assert seen == [0] and scripts.reload_button.text() == "Reload (checking)"
    folders, answer = rounds[1]
    answer({folder_: None for folder_ in folders})
    assert seen == [0, 0] and scripts.reload_button.text() == "Reload" and not scripts._probing
    qtbot.waitUntil(lambda: instance.shown is not None and shown_tag(instance) == "new", timeout=10_000)


def test_a_run_ending_as_the_reload_counts_it_doesnt_leave_the_reload_waiting(
        qtbot: QtBot, cache: FolderCache, windows: Windows, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C4-2 (PR #11, round 2): the run the answered round counts ends, its ``finished`` emitted, before the
    count returns. The panel listens before it counts, so that ``finished`` reaches it and the import goes on
    (it never stays "Reload (waiting)" with nothing left to wait for)."""
    window = new_window(qtbot, cache, windows)
    scripts = window.scripts
    write_script(tmp_path, "lab_live_t", "old", wait=BLOCKS.format(helper="lab_live_t"))
    scripts.add_folder(str(tmp_path))
    gate, started = sys.modules["lab_live_t"].GATE, sys.modules["lab_live_t"].STARTED
    gate.set()
    instance = open_plot(qtbot, window, cache)
    gate.clear()
    started.clear()
    rounds, seen = fake_probes(monkeypatch, scripts), imports_seen(monkeypatch, scripts)
    scripts.reload_scripts()
    instance.runner.submit(type(instance.script)(), instance.metadata, "Plot", instance.view)
    qtbot.waitUntil(started.is_set, timeout=10_000)
    ended = threading.Event()
    # (Direct: called on the worker thread as it emits. PyQt6's stubs lack connect's type argument.)
    instance.runner.finished.connect(lambda _result: ended.set(), Qt.ConnectionType.DirectConnection)  # type: ignore[call-arg]
    busy = scripts._busy
    counts: List[int] = []

    def counting(folders: Set[str]) -> int:
        count = busy(folders)
        if not counts:
            counts.append(count)
            gate.set()
            assert ended.wait(10)  # (The run ended and said so on the worker thread, before this count returns.)
        return count
    monkeypatch.setattr(scripts, "_busy", counting)
    write_script(tmp_path, "lab_live_t", "new")
    folders, answer = rounds[0]
    answer({folder_: None for folder_ in folders})
    assert counts == [1]
    qtbot.waitUntil(lambda: seen == [0] and scripts.reload_button.text() == "Reload", timeout=10_000)
    qtbot.waitUntil(lambda: instance.shown is not None and shown_tag(instance) == "new", timeout=10_000)
    assert len(rounds) == 1 and not scripts._probing


def test_removing_the_folder_a_tested_reload_waits_for_lets_it_go_on(
        qtbot: QtBot, cache: FolderCache, windows: Windows, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C-4 (PR #11): answered, the round waits for a run of its folder; the folder removed meanwhile, the
    round ends without importing it (L2's wait, after the test imports)."""
    window = new_window(qtbot, cache, windows)
    scripts = window.scripts
    write_script(tmp_path, "lab_live_r", "old", wait=BLOCKS.format(helper="lab_live_r"))
    scripts.add_folder(str(tmp_path))
    gate, started = sys.modules["lab_live_r"].GATE, sys.modules["lab_live_r"].STARTED
    gate.set()
    instance = open_plot(qtbot, window, cache)
    gate.clear()
    started.clear()
    rounds, seen = fake_probes(monkeypatch, scripts), imports_seen(monkeypatch, scripts)
    scripts.reload_scripts()
    instance.runner.submit(type(instance.script)(), instance.metadata, "Plot", instance.view)
    qtbot.waitUntil(started.is_set, timeout=10_000)
    folders, answer = rounds[0]
    answer({folder_: None for folder_ in folders})
    assert scripts.reload_button.text() == "Reload (waiting)"
    scripts.remove_folder(str(tmp_path))
    assert scripts.reload_button.text() == "Reload" and scripts._waiting_on == [] and not scripts._probing
    assert seen == [] and "Lab" not in scripts.groups
    gate.set()
    qtbot.waitUntil(lambda: not instance.runner.in_flight(), timeout=10_000)
    assert seen == [] and len(rounds) == 1


def test_a_helper_first_imported_in_a_run_isnt_a_change(qtbot: QtBot, tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """L5: a helper in a subpackage imported lazily after the load is stamped, not a change; an edit of
    it afterwards is one."""
    package = tmp_path / "lab_pkg_l"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "inner.py").write_text("TAG = 'one'\n")
    (tmp_path / "live.py").write_text(SCRIPT.replace("import {helper}\n", "").replace(
        "{wait}return ({helper}.TAG", "import lab_pkg_l.inner\n        return (lab_pkg_l.inner.TAG").format(
        specs=SPECS, name="Live", version="1"))
    scripts = TreePanelWidget()
    qtbot.addWidget(scripts)
    scripts.add_folder(str(tmp_path))
    reloaded: List[Optional[List[str]]] = []
    monkeypatch.setattr(scripts, "reload_scripts", lambda folders=None, deliberate=True: reloaded.append(folders))
    script_class = scripts.script_manager.get_script(f"{tmp_path / 'live.py'}::Live")
    assert script_class is not None
    __import__("lab_pkg_l.inner")  # (As its compute would, in a run after the load.)
    (tmp_path / "notes.txt").write_text("an unrelated save")
    scripts._check_changes()
    assert reloaded == []
    inner = package / "inner.py"
    inner.write_text("TAG = 'two, edited'\n")
    os.utime(inner, ns=(inner.stat().st_atime_ns, inner.stat().st_mtime_ns + 2_000_000_000))
    scripts._check_changes()
    assert reloaded == [[str(tmp_path)]]


def test_the_menus_actions_and_the_details_window_have_ids_and_submenus_go(qtbot: QtBot, tmp_path: Path) -> None:
    """N1, N2."""
    (tmp_path / "raises.py").write_text("raise ValueError('x')\n")
    scripts = TreePanelWidget()
    qtbot.addWidget(scripts)
    scripts.add_folder(str(tmp_path))
    assert scripts.auto_reload_action.objectName() == "script_auto_reload"
    scripts._fill_folders_menu()
    (old,) = scripts._submenus
    assert sorted(action.objectName() for action in old.actions()) == ["script_folder_reload", "script_folder_remove"]
    scripts._fill_folders_menu()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(old) and len(scripts._submenus) == 1
    (error,) = scripts.script_manager.errors()
    box = scripts.show_error_details(error)
    names = [button.objectName() for button in box.buttons()]
    assert "script_error_details_close" in names and all(name.startswith("script_error_details_") for name in names)
    box.close()


# R1 (Prismo's re-check): a marker never sticks


def stale_marker(folder_: object) -> None:
    with open(marker_path(), "w", encoding="utf-8") as handle:
        if folder_ is None:
            handle.write("{not json")
        else:
            json.dump({"folder": folder_}, handle)


def test_a_marker_naming_no_remembered_folder_is_dropped_at_start(qtbot: QtBot, tmp_path: Path) -> None:
    """R1: HeLab stopped while Load Scripts… loaded a new folder, not yet remembered: the next start drops
    that marker and loads the remembered folders."""
    write_script(tmp_path, "lab_live_m", "one")
    app_settings().setValue(SCRIPT_FOLDERS_SETTING, json.dumps([str(tmp_path)]))
    stale_marker(str(tmp_path / "never-remembered"))
    scripts = TreePanelWidget()
    qtbot.addWidget(scripts)
    scripts.restore_folders()
    assert "Lab" in scripts.groups and scripts.start_note.isHidden() and loading_marker() is None


def test_an_unreadable_marker_skips_one_start_only(qtbot: QtBot, tmp_path: Path) -> None:
    """R1: a marker that can't be read still means a load never ended (this start skips the folders), but it
    is dropped, so the next start loads them."""
    write_script(tmp_path, "lab_live_n", "one")
    app_settings().setValue(SCRIPT_FOLDERS_SETTING, json.dumps([str(tmp_path)]))
    stale_marker(None)
    first = TreePanelWidget()
    qtbot.addWidget(first)
    first.restore_folders()
    assert "Lab" not in first.groups and not first.start_note.isHidden() and loading_marker() is None
    second = TreePanelWidget()
    qtbot.addWidget(second)
    second.restore_folders()
    assert "Lab" in second.groups


@pytest.mark.parametrize("how", ["reload", "menu", "load another"])
def test_a_deliberate_load_clears_a_marker_it_didnt_make(qtbot: QtBot, tmp_path: Path, how: str) -> None:
    """R1: Reload, or Load Scripts… of another folder, ends a marker left by a load that never ended (of a
    folder Remove can't reach); an automatic reload doesn't."""
    first, other = tmp_path / "first", tmp_path / "other"
    first.mkdir()
    other.mkdir()
    write_script(first, "lab_live_o", "one")
    write_script(other, "lab_live_p", "two")
    scripts = TreePanelWidget()
    qtbot.addWidget(scripts)
    scripts.add_folder(str(first))
    stale_marker(str(tmp_path / "gone"))
    scripts.reload_scripts([str(first)], deliberate=False)  # (Auto-reload: not the user's word.)
    assert loading_marker() == str(tmp_path / "gone")
    if how == "reload":
        scripts.reload_button.click()  # (As the button sends it.)
    elif how == "menu":
        scripts._fill_folders_menu()
        (sub,) = scripts._submenus
        (reload,) = [action for action in sub.actions() if action.objectName() == "script_folder_reload"]
        reload.trigger()  # (As the menu sends it.)
    else:
        scripts.add_folder(str(other))
    assert loading_marker() is None


# A Scripts panel the garbage collector frees during its first polish (tests drop theirs at once)

# A pytest plugin for the nested run: a collection at the worst moment, whenever ElidedLabel sees a change.
COLLECT_IN_CHANGES = """
import gc


def pytest_configure(config):
    from helab.views.ElidedLabel import ElidedLabel
    change = ElidedLabel.changeEvent

    def collecting(self, event):
        change(self, event)
        gc.collect()

    ElidedLabel.changeEvent = collecting
"""


def test_a_dropped_scripts_panel_survives_a_collection_in_its_first_polish(tmp_path: Path) -> None:
    """The crash of CI 41471378031 (test_live_plots, its worker's SIGSEGV in QWidgetPrivate::updateIsOpaque):
    the panel test_live_plots' ``plot`` makes is Python's (no Qt parent) and cyclic garbage at once; the
    collector freed it while Qt polished it, inside the PaletteChange its note's style sheet sent to
    ElidedLabel's Python changeEvent. That test, run here with a collection forced in every ElidedLabel
    change, crashed every time before the note lost its style sheet. Nested (its own process): a crash can't
    take this worker with it."""
    import subprocess
    (tmp_path / "collect_in_changes.py").write_text(COLLECT_IN_CHANGES)
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, (str(tmp_path), os.environ.get("PYTHONPATH"))))}
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-m", "pytest", "-q", "-p", "collect_in_changes",
                           "-p", "no:randomly", "-p", "no:cacheprovider", "-p", "no:xdist", "-p", "no:rerunfailures",
                           f"--basetemp={tmp_path / 'nested'}",
                           "tests/test_live_plots.py::test_transfer_fractions_highlight_follows_lives_newest_shot"],
                          capture_output=True, text=True, timeout=300, cwd=str(root), env=env)
    assert done.returncode == 0, (done.returncode, done.stdout[-1500:], done.stderr[-1500:])


def test_the_panels_polish_runs_no_python_code(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing in the Scripts panel reaches Python while Qt polishes it: its amber note is coloured by its
    palette, not a style sheet (whose polish sets the palette, a PaletteChange for ElidedLabel)."""
    from PyQt6.QtGui import QPalette
    from helab.utils.colours import AMBER
    from helab.views.ElidedLabel import ElidedLabel
    seen: List[QEvent.Type] = []
    change = ElidedLabel.changeEvent

    def spying(self: ElidedLabel, event: Optional[QEvent]) -> None:
        if event is not None:
            seen.append(event.type())
        change(self, event)

    scripts = TreePanelWidget()
    qtbot.addWidget(scripts)
    monkeypatch.setattr(ElidedLabel, "changeEvent", spying)
    scripts.ensurePolished()
    assert QEvent.Type.PaletteChange not in seen and QEvent.Type.StyleChange not in seen
    assert scripts.start_note.palette().color(QPalette.ColorRole.WindowText).name().lower() == AMBER.lower()
