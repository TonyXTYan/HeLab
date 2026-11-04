"""The Scripts panel (``TreePanelWidget``): HeLab's bundled analyses and loaded scripts by
group, with each script's run buttons; it opens each new plot's dock in the plot area."""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, TYPE_CHECKING, Union

from PyQt6 import sip
from PyQt6.QtCore import (QCoreApplication, QFileSystemWatcher, QObject, QProcess, QProcessEnvironment, Qt, QTimer,
                          pyqtSignal, pyqtSlot)
from PyQt6.QtGui import QAction, QBrush, QColor, QPalette
from PyQt6.QtWidgets import (QComboBox, QDockWidget, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
                             QMenu, QMessageBox, QPushButton, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                             QWidget)

from helab.analysis.dataset_view import DatasetView
from helab.analysis.presets import SavedPlot, ScriptRef, waiting_view
from helab.analysis.runner import AnalysisRunner, get_analysis_runner
from helab.scripts import dld, probe, standard
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.scripts_manager import LoadError, ScriptsManager
from helab.utils.accessible import id_part, identify, identify_buttons
from helab.utils.colours import AMBER
from helab.utils.settings_defaults import SCRIPT_AUTO_RELOAD_SETTING, SCRIPT_FOLDERS_SETTING, read_setting
from helab.utils.settings_store import app_settings
from helab.views.ElidedLabel import ElidedLabel
from helab.views.plots.dock import AnalysisDock, DockTabCloser
from helab.views.plots.instance import AnalysisInstance, LinkedAnalysisInstance
if TYPE_CHECKING:
    from helab.views.plots.arrangement import FolderWait
    from helab.views.plots.workspace import PlotWorkspace

# ``_add_dock``'s default: tab the new plot with the shown one (``tab_target``).
AUTO = "auto"
# Auto-reload: a change starts this wait (ms) before the folder's files are compared, so an editor's save
# (often a temporary file, then a rename) has finished.
SETTLE_MS = 750
# The remembered folders load this long after the panel is made: once the event loop runs, so after the main
# window has shown (M3), and before the plots reopen (``PlotReopen.restore`` waits for ``foldersRestored``).
RESTORE_DELAY_MS = 200
# In the app folder while a script folder loads (written before, removed after): found at start, the last
# load never ended (a script that blocks or crashes at import), so the remembered folders aren't loaded.
LOADING_MARKER = "scripts-loading.json"
# Q49.3 (b): before HeLab imports a user script folder, it test-imports it in a process of its own
# (``helab.scripts.probe``, ``FolderProbes``). A folder whose test import hasn't finished this many seconds
# after it began (the probe's ``ready``: its own start doesn't count) isn't imported ...
PROBE_SECONDS = 10.0
# ... nor one whose probe isn't ready within this (Python, NumPy and Qt starting; a cold frozen app is slow).
PROBE_START_SECONDS = 60.0
# A probe that answered ``done`` but hasn't exited this long after is killed, its folder still passed (it
# finished): no exit path can hold a round (review FU-1).
PROBE_EXIT_SECONDS = 5.0
PROBES_AT_ONCE = 2
PROBE_POLL_MS = 100  # How often a running probe's answers are read (only while one runs).
# Whether folders are test-imported first: tests that aren't about it turn it off (folders then import at once).
PROBING = True
PROBED_NOTE = ("HeLab first test-imports each script folder in a separate process, so a script that hangs or "
               "crashes at import can't stop HeLab.")
# File systems that are network shares (as ``cache_paths``' mounts name them).
NETWORK_TYPES = ("smbfs", "cifs", "smb", "smb2", "smb3", "afpfs", "nfs", "nfs4", "webdav", "davfs", "remote")


def marker_path() -> str:
    from helab.utils.constants import app_folder
    return os.path.join(app_folder(), LOADING_MARKER)


def loading_marker() -> Optional[str]:
    """The folder named by the loading marker ("" if it names none), or None when there is no marker."""
    path = marker_path()
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return ""  # (There, but unreadable: still a load that never ended.)
    folder = data.get("folder") if isinstance(data, dict) else None
    return folder if isinstance(folder, str) else ""


def on_network(folder: str) -> bool:
    """Whether ``folder`` is on a network share, from the mount table alone (never touching the folder, which
    may be unreachable): a UNC path on Windows, else the longest mount holding it is remote."""
    if sys.platform == "win32" and folder.replace("/", "\\").startswith("\\\\"):
        return True
    from helab.utils import cache_paths
    try:
        mounts = cache_paths.current_mounts()
    except Exception:  # (The mount table can't be read: taken as local, as before live scripts.)
        logging.exception("Mounts unreadable: %s taken as local", folder)
        return False
    path = os.path.normcase(folder)
    holding = [mount for mount in mounts if mount.path and (
        path == os.path.normcase(mount.path) or path.startswith(os.path.normcase(mount.path).rstrip("/\\") + os.sep))]
    if not holding:
        return False
    mount = max(holding, key=lambda entry: len(entry.path))
    return mount.remote or mount.fstype.lower() in NETWORK_TYPES


def read_script_folders() -> List[str]:
    """The remembered script folders (``script_folders``: a JSON list of paths); unreadable: none."""
    text = read_setting(app_settings(), SCRIPT_FOLDERS_SETTING, typed=True)
    if not text:
        return []
    try:
        folders = json.loads(text)
    except ValueError:
        logging.warning("Remembered script folders unreadable (%r): none restored", text)
        return []
    return [folder for folder in folders if isinstance(folder, str) and folder] if isinstance(folders, list) else []


@dataclass(frozen=True)
class ProbeFailure:
    """Why a folder's test import failed (``reason``: a few words, after "didn't load: "), and what the probe
    wrote to stderr (``details``; "" if nothing)."""
    reason: str
    details: str = ""


@dataclass
class _Probe:
    folder: str
    process: Optional[QProcess] = None
    output: str = ""  # Its private temp folder (the response, stdout and stderr files).
    response: str = ""
    read: int = 0  # Bytes of the response read so far.
    started: float = 0.0  # monotonic
    ready: Optional[float] = None  # monotonic: when it began importing the folder.
    done: bool = False
    done_at: float = 0.0  # monotonic: when ``done`` was read.
    lingered: bool = False  # Killed for not exiting after ``done`` (still passed).
    application: str = ""  # What the probe ran its import under (``probe.OFFSCREEN``, or none and why).
    killed: str = ""  # Why it was killed ("": it wasn't).


class FolderProbes(QObject):
    """Q49.3 (b): test-import user script folders, each in a process of its own (``helab.scripts.probe``), at
    most ``PROBES_AT_ONCE`` at a time. ``probe(folders, answer)`` calls ``answer({folder: failure})`` on the
    GUI thread once each folder's probe has ended, its exit confirmed (``finished``): failure None when its
    import finished, or when the probe couldn't start at all (imported anyway, logged: Q49.3 P4); else why
    not. One probe per folder at a time: a folder asked for again while its probe runs gets that probe's
    answer. Nothing waits: ``QProcess`` signals and one poll timer, running only while probes do. Killed
    probes (time limit, ``stop``) end asynchronously. One that answered ``done`` but hasn't exited
    ``PROBE_EXIT_SECONDS`` later is killed and still passes."""

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._queue: List[_Probe] = []
        self._running: Dict[int, _Probe] = {}  # id(process) -> probe
        self._rounds: List[Tuple[Dict[str, Optional[ProbeFailure]], Set[str],
                                 Callable[[Dict[str, Optional[ProbeFailure]]], None]]] = []
        self._timer = QTimer(self)
        self._timer.setInterval(PROBE_POLL_MS)
        self._timer.timeout.connect(self._poll)
        application = QCoreApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self.stop)

    def busy(self) -> bool:
        return bool(self._queue or self._running)

    def probe(self, folders: List[str], answer: Callable[[Dict[str, Optional[ProbeFailure]]], None]) -> None:
        if not folders:
            answer({})
            return
        self._rounds.append(({}, set(folders), answer))
        known = {probe.folder for probe in (*self._queue, *self._running.values())}
        self._queue.extend(_Probe(folder) for folder in folders if folder not in known)
        self._start_more()

    @pyqtSlot()
    def stop(self) -> None:
        """Kill every probe and forget the rounds (HeLab quits): no answer comes."""
        self._rounds.clear()
        self._queue.clear()
        for item in list(self._running.values()):
            if item.process is not None and not sip.isdeleted(item.process):
                item.killed = "HeLab stopped it"
                item.process.kill()

    def _start_more(self) -> None:
        while self._queue and len(self._running) < PROBES_AT_ONCE:
            self._start(self._queue.pop(0))

    def _start(self, item: _Probe) -> None:
        item.output = tempfile.mkdtemp(prefix="helab_probe_")
        item.response = os.path.join(item.output, "response.jsonl")
        Path(item.response).touch()
        process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        package_root = str(Path(__file__).resolve().parents[3])
        environment.insert("PYTHONPATH", os.pathsep.join(filter(None, (package_root, environment.value("PYTHONPATH")))))
        process.setProcessEnvironment(environment)
        # (A script's prints go to files; stdin stays an open pipe never written, so input() at import waits
        # there as it would in HeLab started from a terminal, and meets the time limit.)
        process.setStandardOutputFile(os.path.join(item.output, "stdout.txt"))
        process.setStandardErrorFile(os.path.join(item.output, "stderr.txt"))
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._failed)
        item.process, item.started = process, time.monotonic()
        self._running[id(process)] = item
        program, arguments = probe.command(item.folder, item.response)
        process.start(program, arguments)
        self._timer.start()

    def _read(self, item: _Probe) -> None:
        """The response's new complete lines: ``ready`` starts the time limit, ``done`` says it finished."""
        try:
            with open(item.response, "rb") as handle:
                handle.seek(item.read)
                text = handle.read()
        except OSError:
            return
        end = text.rfind(b"\n") + 1
        item.read += end
        for line in text[:end].splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("kind") == probe.READY and item.ready is None:
                item.ready, item.application = time.monotonic(), str(event.get("application", ""))
            elif isinstance(event, dict) and event.get("kind") == probe.DONE and not item.done:
                item.done, item.done_at = True, time.monotonic()

    @pyqtSlot()
    def _poll(self) -> None:
        now = time.monotonic()
        for item in list(self._running.values()):
            self._read(item)
            if item.killed or item.lingered or item.process is None:
                continue
            if item.done:
                if now - item.done_at > PROBE_EXIT_SECONDS:
                    logging.warning("Script folder %s: HeLab's test import finished but its process didn't exit "
                                    "within %g s; ended", item.folder, PROBE_EXIT_SECONDS)
                    item.lingered = True
                    item.process.kill()  # (Passed all the same: ``finished`` answers.)
                continue
            if item.ready is None and now - item.started > PROBE_START_SECONDS:
                item.killed = f"HeLab's test import didn't start within {PROBE_START_SECONDS:g} s"
            elif item.ready is not None and now - item.ready > PROBE_SECONDS:
                item.killed = f"its import didn't finish within {PROBE_SECONDS:g} s"
            if item.killed:
                item.process.kill()  # (Its ``finished`` ends it: a probe holds its folder until its exit.)
        if not self._running:
            self._timer.stop()

    def _item(self) -> Optional[_Probe]:
        sender = self.sender()
        return self._running.get(id(sender)) if isinstance(sender, QProcess) else None

    @pyqtSlot(QProcess.ProcessError)
    def _failed(self, error: QProcess.ProcessError) -> None:
        item = self._item()
        if item is None or error != QProcess.ProcessError.FailedToStart:
            return  # (Any other error: ``finished`` follows.)
        logging.warning("Script folder %s: HeLab's test import couldn't start (%s); imported without it", item.folder,
                        item.process.errorString() if item.process is not None else error)
        self._ended(item, None)

    @pyqtSlot(int, QProcess.ExitStatus)
    def _finished(self, code: int, status: QProcess.ExitStatus) -> None:
        item = self._item()
        if item is None:
            return
        self._read(item)
        failure: Optional[ProbeFailure] = None
        if item.killed or not item.done:
            details = self._stderr_tail(item)
            reason = item.killed or ("its import crashed HeLab's test import"
                                     if status == QProcess.ExitStatus.CrashExit
                                     else f"its import stopped HeLab's test import (exit code {code})")
            failure = ProbeFailure(reason, details.strip())
        seconds = time.monotonic() - item.started
        logging.info("Script folder %s test-imported in a separate process (QApplication: %s) in %.1f s: %s",
                     item.folder, item.application or "not started", seconds,
                     "finished" if failure is None else failure.reason)
        self._ended(item, failure)

    @staticmethod
    def _stderr_tail(item: _Probe, size: int = 4000) -> str:
        """The last ``size`` bytes the probe wrote to stderr (a script may have written a lot)."""
        try:
            with open(os.path.join(item.output, "stderr.txt"), "rb") as handle:
                handle.seek(0, os.SEEK_END)
                handle.seek(max(0, handle.tell() - size))
                return handle.read().decode("utf-8", errors="replace")
        except OSError:
            return ""

    def _ended(self, item: _Probe, failure: Optional[ProbeFailure]) -> None:
        if item.process is not None:
            self._running.pop(id(item.process), None)
            if not sip.isdeleted(item.process):
                item.process.deleteLater()
        shutil.rmtree(item.output, ignore_errors=True)
        for round_ in list(self._rounds):
            answers, waiting, answer = round_
            if item.folder in waiting:
                answers[item.folder] = failure
                waiting.discard(item.folder)
                if not waiting:
                    self._rounds.remove(round_)
                    answer(answers)
        self._start_more()
        if not self._running:
            self._timer.stop()


class TreePanelWidget(QWidget):
    """The Scripts panel: a group selector, Load Scripts… and the selected group's scripts, each
    with up to two run buttons (its first actions).

    Groups are each script's metadata group: HeLab's bundled analyses ("Basic plots v1",
    ``helab.scripts.standard.group``; "DLD Front Panel Port", ``helab.scripts.dld.group``) and
    those of scripts loaded from a folder (``ScriptsManager``).

    ``plotsChanged`` says when a plot opened or closed (the plots to reopen at start are recorded
    then, helab/views/plots/arrangement.py).

    **Live scripts:** the folders added with Load Scripts… are remembered (``script_folders``) and
    loaded again at start (``restore_folders``: after the window shows, before plots reopen; never a
    folder on a network share, nor any after a start whose load never ended, ``LOADING_MARKER``: those
    wait for Reload, said in the panel's one-line note); Load Scripts…'s menu removes one from the list and
    turns on reloading when a script is saved (``script_auto_reload``, off by default: only then a
    ``QFileSystemWatcher`` watches the script folders and their helper modules, never a data
    folder). **Reload** loads the folders again with their helper modules (``ScriptsManager``); a
    reload waits until no run of those folders' scripts is queued or computing (their plots are held
    and their runs cancelled first), then each open plot of them takes the new code
    (``AnalysisInstance.adopt_script``) or, its script gone or failing, keeps its old code and says
    so (``keep_script``). Files that didn't load are listed at the tree's end, whatever the group,
    with their traceback in the tooltip and, on a double-click, a details window.

    **The try-import** (Q49.3 (b)): every import of a user folder (at start, Reload, auto-reload, Load
    Scripts…) is first a test import in a separate process (``FolderProbes``, ``helab.scripts.probe``), one
    round at a time (Reload reads "Reload (checking)"; a reload asked meanwhile follows in its own round).
    Folders whose test import finished are imported here, as before; one that didn't finish within
    ``PROBE_SECONDS`` of its start, or ended the process, isn't: at start it waits for Reload (the start
    note), else it is listed as not loaded (``ScriptsManager.skip_folder``) and its plots keep their code.
    The loading marker stays the backstop for what the test can't catch.
    """

    plotsChanged = pyqtSignal()
    foldersRestored = pyqtSignal()  # The remembered folders were loaded (or skipped) at start.

    def __init__(self, workspace: Optional[PlotWorkspace] = None,
                 parent: Any = None) -> None:
        super().__init__(parent)

        self.workspace = workspace  # The plot area new plots open in.
        self.script_manager = ScriptsManager()
        
        self.groups: List[str] = []  # As the group selector lists them.

        # Analysis instance tracking
        self._instance_counter = 0
        self._analysis_instances: Dict[str, LinkedAnalysisInstance] = {}

        # Layout for the right-bottom panel
        self.panel_layout_right_bottom = QVBoxLayout(self)
        self.panel_layout_right_bottom.setContentsMargins(0, 0, 0, 0)

        # Add controls at the top
        controls_layout = QHBoxLayout()
        
        # Add group selector
        self.group_selector = identify(QComboBox(), "script_group", "Script group",
                                       "Choose which group's scripts are listed")
        self.group_selector.currentTextChanged.connect(self._on_group_changed)
        controls_layout.addWidget(QLabel("Group:"))
        controls_layout.addWidget(self.group_selector)

        # Add script directory button; its menu: the remembered folders and auto-reload.
        self.load_dir_button = identify(QToolButton(), "load_scripts", "Load Scripts...",
                                        "Load analysis scripts from a folder; the menu lists the folders loaded")
        self.load_dir_button.setText("Load Scripts...")
        self.load_dir_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.load_dir_button.clicked.connect(self._on_load_directory)
        self.folders_menu = QMenu(self.load_dir_button)
        self.folders_menu.aboutToShow.connect(self._fill_folders_menu)
        self.load_dir_button.setMenu(self.folders_menu)
        self.auto_reload_action = QAction("Reload when a script is saved", self)
        self.auto_reload_action.setObjectName("script_auto_reload")
        self.auto_reload_action.setCheckable(True)
        self.auto_reload_action.setToolTip("Watch the script folders (only those) and reload one when a script or "
                                           "helper module in it is saved")
        self.auto_reload_action.toggled.connect(self.set_auto_reload)
        controls_layout.addWidget(self.load_dir_button)
        self.reload_button = identify(QPushButton("Reload"), "reload_scripts", "Reload scripts",
                                      "Import the loaded folders' scripts and their helper modules again; open "
                                      "plots of them rerun on the new code")
        self.reload_button.clicked.connect(self._reload_clicked)
        controls_layout.addWidget(self.reload_button)
        # The row shrinks with the panel, never sets its width (Q33.2; on Windows it held the settings panel at
        # ~548 px): the combo to a few characters, the button to its text.
        self.group_selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.group_selector.setMinimumContentsLength(4)
        for button in (self.load_dir_button, self.reload_button):
            button.setMinimumWidth(button.fontMetrics().horizontalAdvance(button.text()) + 8)

        controls_layout.addStretch()
        self.panel_layout_right_bottom.addLayout(controls_layout)
        # One line, only when remembered folders weren't loaded at start (the folders and why: its tooltip).
        self.start_note = identify(ElidedLabel(), "scripts_start_note")
        # Amber by its palette, not a style sheet: polishing a style sheet sets the palette, which runs
        # ElidedLabel's Python changeEvent during the panel's polish; a panel the garbage collector frees
        # then (tests drop theirs at once) is deleted mid-polish and Qt crashes (SIGSEGV in updateIsOpaque).
        palette = self.start_note.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor(AMBER))
        self.start_note.setPalette(palette)
        self.start_note.hide()
        self.panel_layout_right_bottom.addWidget(self.start_note)

        # Tree list widget
        self.tree_widget = identify(QTreeWidget(), "scripts", "Scripts", "The group's scripts and their run buttons")
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

        # Add tree widget to the layout
        self.panel_layout_right_bottom.addWidget(self.tree_widget)

        # Live scripts: the remembered folders (the setting's list: loaded or not), those not loaded at start
        # and why, what each folder's files were when last loaded and when (auto-reload compares), the
        # folders on a network share (never watched), the folders waiting to reload (until their runs end),
        # and the watcher (only while auto-reload is on).
        self._remembered: List[str] = [ScriptsManager.normal(folder) for folder in read_script_folders()]
        self._skipped: Dict[str, str] = {}
        self._stamps: Dict[str, Dict[str, Tuple[int, int]]] = {}
        self._stamped_at: Dict[str, int] = {}
        self._remote: Set[str] = set()
        self._submenus: List[QMenu] = []
        self._pending: Set[str] = set()
        self._pending_deliberate = False  # A reload waiting is the user's (Reload, its menu, Load Scripts…)
        self._waiting_on: List[AnalysisRunner] = []
        self._watcher: Optional[QFileSystemWatcher] = None
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_MS)
        self._settle.timeout.connect(self._check_changes)
        self._details: Optional[QMessageBox] = None
        self.tree_widget.itemDoubleClicked.connect(self._show_error_details)
        # Q49.3 (b): folders are test-imported in a separate process first, one round at a time (a reload asked
        # meanwhile waits for it); the folders added by Load Scripts… in that round (their own notice); those
        # whose last test import failed (the start note's tooltip says how they were checked).
        self._probes = FolderProbes(self)
        self._probing = False
        # C-4: the round's folders (a plot of one opened meanwhile is held from its start, ``_hold_if_reloading``),
        # and, once its test imports answered, what the real import waits with until no run of them is in flight.
        self._round: Set[str] = set()
        self._answered: Optional[Tuple[Set[str], Dict[str, Optional[ProbeFailure]],
                                       Callable[[Dict[str, Optional[ProbeFailure]]], None]]] = None
        self._adding: Set[str] = set()
        self._probe_failed: Set[str] = set()

        # HeLab's bundled analyses now; the user's remembered folders once the window has shown (M3)
        self._load_default_scripts()
        auto = bool(read_setting(app_settings(), SCRIPT_AUTO_RELOAD_SETTING, typed=True))
        self.auto_reload_action.blockSignals(True)
        self.auto_reload_action.setChecked(auto)
        self.auto_reload_action.blockSignals(False)
        self.folders_pending = bool(self._remembered)
        self.reload_button.setEnabled(bool(self._remembered))
        if self.folders_pending:
            QTimer.singleShot(RESTORE_DELAY_MS, self.restore_folders)
        else:
            self._watch(auto)

        logging.info(f"TreePanelWidget initialized. {type(self.parent()) = }")

    def _load_default_scripts(self) -> None:
        """Register HeLab's bundled analyses (``helab.scripts.standard``, then the DLD front panel port, ``helab.scripts.dld``) and show the first group."""
        for module in (*standard.MODULES, *dld.MODULES):
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
            self.add_folder(dir_path)

    # Live scripts: the user's folders

    def restore_folders(self) -> None:
        """At start, once the window has shown (M3): load the remembered folders, but not a folder on a
        network share (it may be unreachable: listing it could stall HeLab), and none if the last start's load
        never ended (the loading marker: a script that blocks or crashes at import). Those wait for Reload,
        named in the panel's note. Then watch them if auto-reload is on, and say so (``foldersRestored``)."""
        if not self.folders_pending:
            return
        self.folders_pending = False
        stuck = loading_marker()
        if stuck == "":
            # (Unreadable: a load never ended, of a folder it can't name. This start skips them; dropped, so it
            # never sticks: R1.)
            self._unmark()
        elif stuck is not None and not any(os.path.normcase(stuck) == os.path.normcase(folder)
                                           for folder in self._remembered):
            # (It names no remembered folder: a new folder Load Scripts… was loading. Not loaded at start: R1.)
            self._unmark()
            stuck = None
        chosen: List[str] = []
        for folder in self._remembered:
            if stuck is not None:
                self._skipped[folder] = (f"HeLab stopped while loading {stuck} last time" if stuck else
                                         "HeLab stopped while loading script folders last time")
            elif on_network(folder):
                self._skipped[folder] = "on a network share"
            else:
                chosen.append(folder)
        self._probe_then(chosen, lambda answers: self._restored(chosen, answers))

    def _restored(self, chosen: List[str], answers: Dict[str, Optional[ProbeFailure]]) -> None:
        """The start's folders tested: those whose test import finished load, in the remembered order; the
        others wait for Reload with the reason (Q49.3 (b))."""
        for folder in chosen:
            if not self._is_remembered(folder):
                continue  # (Removed from the list while it was tested.)
            failure = answers.get(folder)
            if failure is None:
                self._probe_failed.discard(folder)
                self._load_folder(folder)
            else:
                self._probe_failed.add(folder)
                self._skipped[folder] = failure.reason
                logging.warning("Script folder %s not loaded at start: %s", folder, failure.reason)
        self._refresh()
        self._show_start_note()
        self._watch(self.auto_reload_action.isChecked())
        self.foldersRestored.emit()

    def _is_remembered(self, folder: str) -> bool:
        return any(os.path.normcase(known) == os.path.normcase(folder) for known in self._remembered)

    def _probe_then(self, folders: List[str],
                    then: Callable[[Dict[str, Optional[ProbeFailure]]], None]) -> None:
        """Test-import ``folders`` in separate processes (``FolderProbes``), then ``then(answers)``; at once
        (all passed) when there are none or ``PROBING`` is off. ``then`` imports, so it waits (``_end_round``)
        until no run of those folders' scripts is queued or computing (C-4: one may have started during the
        round). A reload asked meanwhile runs after it."""
        if not folders or not PROBING:
            then({folder: None for folder in folders})
            return
        self._probing = True
        self._round = set(folders)
        self.reload_button.setText("Reload (checking)")
        self.reload_button.setToolTip(f"Test-importing {len(folders):,} script folder{'' if len(folders) == 1 else 's'} "
                                      "in a separate process first")

        def answered(answers: Dict[str, Optional[ProbeFailure]]) -> None:
            if sip.isdeleted(self):
                return
            self._answered = (set(folders), answers, then)
            self._end_round()
        self._probes.probe(folders, answered)

    def _end_round(self) -> None:
        """The round's test imports answered: its import (``then``) runs once no run of its folders' scripts
        (those still listed) is queued or computing, on any runner; until then their plots are held and the
        reload waits for ``finished`` ("Reload (waiting)"), the answers kept (no second round). Then a reload
        asked meanwhile follows in its own round, its plots held again (this round's import let them run)."""
        if self._answered is None:
            return
        folders, answers, then = self._answered
        listed = {folder for folder in folders if self._is_remembered(folder) or
                  any(os.path.normcase(known) == os.path.normcase(folder) for known in self.script_manager.folders())}
        self._listen()  # (Before counting: a run ending meanwhile still reaches ``_run_ended``, C4-2.)
        busy = self._busy(listed)
        if busy:
            for instance in self._plots_of(listed):
                instance.hold_for_reload()  # (Held already, or opened another way: it submits no more meanwhile.)
            self._wait_for_runs(busy)
            return
        self._answered, self._round = None, set()
        self._probing = False
        self._stop_waiting()
        then(answers)
        if self._pending:
            for instance in self._plots_of(self._pending):
                instance.hold_for_reload()
            self._try_reload()

    def _show_start_note(self) -> None:
        """One line while remembered folders wait for Reload; their reasons in its tooltip."""
        skipped = self._skipped
        if not skipped:
            self.start_note.hide()
            self.start_note.setText("")
            return
        count = len(skipped)
        reasons = sorted(set(skipped.values()))
        self.start_note.setText(f"⚠ {count:,} script folder{'' if count == 1 else 's'} not loaded at start "
                                f"({reasons[0]}{'; …' if len(reasons) > 1 else ''}): Reload to load "
                                f"{'it' if count == 1 else 'them'}")
        tip = "\n".join(f"{folder}: {why}" for folder, why in sorted(skipped.items()))
        if any(folder in self._probe_failed for folder in skipped):
            tip += f"\n\n{PROBED_NOTE}"
        self.start_note.setToolTip(tip)
        self.start_note.show()

    def _load_folder(self, folder: str) -> bool:
        """Load one folder (on the GUI thread, as Load Scripts… always has), the loading marker set around it:
        if a script blocks or crashes HeLab at import, the next start loads no remembered folder. A marker
        left by an earlier load stays until that folder loads or is removed."""
        folder = ScriptsManager.normal(folder)
        stuck = loading_marker()
        own = stuck is None
        if own:
            self._mark(folder)
        try:
            loaded = self.script_manager.add_folder(folder)
        except Exception:  # (Never expected: the manager keeps each file's failure. It stays listed.)
            logging.exception("Error loading scripts from %s", folder)
            loaded = False
        finally:
            if own or stuck == folder:
                self._unmark()
        self._skipped.pop(folder, None)
        if on_network(folder):
            self._remote.add(folder)  # (Never watched: auto-reload stats only local folders.)
        else:
            self._remote.discard(folder)
        self._stamps[folder] = self._stamp_of(folder)
        self._stamped_at[folder] = time.time_ns()
        return loaded

    @staticmethod
    def _mark(folder: str) -> None:
        path = marker_path()
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"folder": folder, "pid": os.getpid(), "at": time.time()}, handle)
        except OSError:
            logging.exception("The script loading marker couldn't be written (%s)", path)

    @staticmethod
    def _unmark() -> None:
        try:
            os.remove(marker_path())
        except FileNotFoundError:
            pass
        except OSError:
            logging.exception("The script loading marker couldn't be removed")

    def _stamp_of(self, folder: str) -> Dict[str, Tuple[int, int]]:
        manager = self.script_manager
        return {file: (size, mtime) for file, size, mtime in manager.stamp(manager.watched_files(folder))}

    def add_folder(self, folder: str) -> None:
        """Load Scripts…: a new folder is loaded and remembered; one loaded already reloads (its plots
        take the new code)."""
        folder = ScriptsManager.normal(folder)
        if any(os.path.normcase(known) == os.path.normcase(folder)
               for known in (*self.script_manager.folders(), *self._remembered)):
            self.reload_scripts([folder])
            return
        self._unmark()  # (The user's load: a marker left by a load that never ended goes, R1.)
        self._remembered.append(folder)
        self._save_folders()
        self._adding.add(folder)
        self.reload_scripts([folder])  # (Test-imported first, then loaded: Q49.3 (b).)

    def remove_folder(self, folder: str) -> None:
        """Remove from the list: its scripts go from the panel (its files stay); its open plots keep
        the code they have and say so."""
        folder = ScriptsManager.normal(folder)
        for instance in self._plots_of({folder}):
            instance.keep_script("its folder was removed from the Scripts list")
        self._pending.discard(folder)
        self._adding.discard(folder)
        self._probe_failed.discard(folder)
        self.script_manager.remove_folder(folder)
        self._remembered = [known for known in self._remembered if os.path.normcase(known) != os.path.normcase(folder)]
        self._skipped.pop(folder, None)
        if loading_marker() == folder:
            self._unmark()  # (Its load never ended: gone from the list, it can't stop a start now.)
        for table in (self._stamps, self._stamped_at):
            table.pop(folder, None)
        self._remote.discard(folder)
        self._save_folders()
        self._refresh()
        self._show_start_note()
        self._sync_watch()
        if self._answered is not None:
            self._end_round()  # (Its answered round may have waited for this folder's runs only: L2, C-4.)
        elif not self._pending:
            self._stop_waiting()  # (A reload waiting only for this folder's runs: nothing waits now, L2.)

    def _save_folders(self) -> None:
        app_settings().setValue(SCRIPT_FOLDERS_SETTING, json.dumps(self._remembered))

    def _fill_folders_menu(self) -> None:
        menu = self.folders_menu
        menu.clear()
        for old in self._submenus:  # (clear() deletes the actions, not the submenus: N2.)
            old.deleteLater()
        self._submenus = []
        folders = list(self._remembered)
        if folders:
            menu.addSection("Script folders")
        for folder in folders:
            why = self._skipped.get(folder)
            sub = menu.addMenu(folder + (f" (not loaded: {why})" if why else ""))
            assert sub is not None
            self._submenus.append(sub)
            reload = sub.addAction("Reload")
            remove = sub.addAction("Remove from the list")
            assert reload is not None and remove is not None
            reload.setObjectName("script_folder_reload")
            remove.setObjectName("script_folder_remove")
            reload.setData(folder)
            remove.setData(folder)
            reload.triggered.connect(self._reload_chosen)
            remove.triggered.connect(self._remove_chosen)
        if not folders:
            none = menu.addAction("No script folders loaded")
            assert none is not None
            none.setEnabled(False)
        menu.addSeparator()
        menu.addAction(self.auto_reload_action)

    @pyqtSlot()
    def _reload_chosen(self) -> None:
        action = self.sender()
        if isinstance(action, QAction) and isinstance(action.data(), str):
            self.reload_scripts([action.data()])

    @pyqtSlot()
    def _remove_chosen(self) -> None:
        action = self.sender()
        if isinstance(action, QAction) and isinstance(action.data(), str):
            self.remove_folder(action.data())

    # Live scripts: reloading

    def _plots_of(self, folders: Set[str]) -> List[AnalysisInstance]:
        """The open plots whose script was loaded from one of ``folders``."""
        keys = {os.path.normcase(folder) for folder in folders}
        return [instance for instance in self.instances() if self._folder_key(instance) in keys]

    def _folder_key(self, instance: AnalysisInstance) -> str:
        manager = self.script_manager
        return os.path.normcase(manager.folder_of(instance.metadata.script_id)
                                or manager.class_folder(type(instance.script)))

    def _hold_if_reloading(self, instance: AnalysisInstance) -> None:
        """C-4: a plot opened while its folder waits to reload or is in a round of test imports is held from
        its start (before it runs): it computes nothing on the code about to be replaced, and takes the new
        code with the folder's other plots (``_adopt``)."""
        if self._folder_key(instance) in {os.path.normcase(folder) for folder in self._round | self._pending}:
            instance.hold_for_reload()

    @pyqtSlot()
    def _reload_clicked(self) -> None:
        self.reload_scripts()  # (Not connected directly: ``clicked`` would pass its ``checked`` as the folders.)

    def reload_scripts(self, folders: Optional[List[str]] = None, deliberate: bool = True) -> None:
        """Reload ``folders`` (default: every remembered one). Their plots are held and their runs cancelled;
        the reload itself waits until no run of those folders' scripts is queued or computing (a
        ``compute`` on the worker thread is never under a reload), then runs (``_try_reload``).
        ``deliberate`` (not auto-reload): it also ends a loading marker it didn't make (R1)."""
        chosen = list(self._remembered) if folders is None else [ScriptsManager.normal(f) for f in folders]
        if not chosen:
            return
        self._pending.update(chosen)
        self._pending_deliberate = self._pending_deliberate or deliberate
        for instance in self._plots_of(set(chosen)):
            instance.hold_for_reload()
        self._try_reload()

    def _runners(self) -> List[AnalysisRunner]:
        runners = [get_analysis_runner()]
        for instance in self.instances():
            if instance.runner not in runners:
                runners.append(instance.runner)
        return runners

    def _busy(self, folders: Set[str]) -> int:
        """Runs of ``folders``' scripts queued or computing, on any runner the plots use."""
        keys = {os.path.normcase(folder) for folder in folders}
        manager = self.script_manager
        return sum(1 for runner in self._runners() for script in runner.in_flight()
                   if os.path.normcase(manager.class_folder(type(script))) in keys)

    def _try_reload(self) -> None:
        if not self._pending:
            if not self._probing:
                self._stop_waiting()  # (L2: the folder it waited for was removed meanwhile.)
            return
        if self._answered is not None:
            self._end_round()  # (Answered, waiting for runs: count them again; this reload follows it.)
            return
        if self._probing:
            return  # (A round of test imports runs: this reload's round follows it, ``_probe_then``.)
        self._listen()  # (Before counting: a run ending meanwhile still reaches ``_run_ended``, C4-2.)
        busy = self._busy(self._pending)
        if busy:
            self._wait_for_runs(busy)
            return
        self._stop_waiting()
        folders, self._pending = set(self._pending), set()
        deliberate, self._pending_deliberate = self._pending_deliberate, False
        if deliberate:
            self._unmark()  # (The user's reload: a marker left by a load that never ended goes, R1.)
        self._probe_then(sorted(folders), lambda answers: self._finish_reload(folders, answers))

    def _finish_reload(self, asked: Set[str], answers: Dict[str, Optional[ProbeFailure]]) -> None:
        """The folders tested (Q49.3 (b)): those whose test import finished load, the others are listed as not
        loaded with the reason; then the plots take the new code or keep theirs, and the notice says so."""
        folders = {folder for folder in asked if self._is_remembered(folder) or
                   any(os.path.normcase(known) == os.path.normcase(folder) for known in self.script_manager.folders())}
        adding, self._adding = self._adding & folders, self._adding - asked
        for folder in sorted(folders):
            failure = answers.get(folder)
            if failure is None:
                self._probe_failed.discard(folder)
                self._load_folder(folder)
            else:
                self._skip_folder(folder, failure)
        self._refresh()
        self._show_start_note()
        self._sync_watch()
        adopted, kept = self._adopt(folders)
        self.plotsChanged.emit()  # (Their records name the new code.)
        reloaded = folders - adding
        if not reloaded:
            for folder in sorted(adding):
                self._say_errors(folder)
            return
        errors = [error for error in self.script_manager.errors()
                  if any(self._in_folder(error.path, folder) for folder in folders)]
        parts = [f"Reloaded {len(reloaded):,} script folder{'' if len(reloaded) == 1 else 's'}"]
        if adopted:
            parts.append(f"{adopted:,} plot{'' if adopted == 1 else 's'} rerun")
        if kept:
            parts.append(f"⚠ {kept:,} plot{'' if kept == 1 else 's'} kept the old code")
        if errors:
            parts.append(f"⚠ {len(errors):,} file{'' if len(errors) == 1 else 's'} didn't load (listed in Scripts)")
        if self.workspace is not None:
            self.workspace.notice(" · ".join(parts))

    def _skip_folder(self, folder: str, failure: ProbeFailure) -> None:
        """A folder whose test import hung or crashed (Q49.3 (b)): not imported; listed as not loaded, with how
        it was checked in its tooltip and details; its plots keep their code (``_adopt``). Stamped, so a save
        reloads (and tests) it again."""
        logging.warning("Script folder %s not imported: %s", folder, failure.reason)
        details = (f"{PROBED_NOTE} This folder's test import failed ({failure.reason}), so it wasn't imported. "
                   "Fix its scripts and Reload.")
        if failure.details:
            details += f"\n\n{failure.details}"
        self.script_manager.skip_folder(folder, f"didn't load: {failure.reason}", details)
        self._probe_failed.add(folder)
        self._skipped.pop(folder, None)
        if on_network(folder):
            self._remote.add(folder)
        else:
            self._remote.discard(folder)
        self._stamps[folder] = self._stamp_of(folder)
        self._stamped_at[folder] = time.time_ns()

    @staticmethod
    def _in_folder(path: str, folder: str) -> bool:
        return os.path.normcase(path) == os.path.normcase(folder) or \
            os.path.normcase(os.path.dirname(path)) == os.path.normcase(folder)

    def _listen(self) -> None:
        """Each runner's ``finished`` checks again (``_run_ended``); connected before the runs are counted, since
        Qt queues a signal only to the receivers connected when it is emitted (``_stop_waiting`` disconnects)."""
        for runner in self._runners():
            if runner not in self._waiting_on:
                runner.finished.connect(self._run_ended)
                self._waiting_on.append(runner)

    def _wait_for_runs(self, busy: int) -> None:
        """Wait (never blocking) for ``busy`` runs to end: each runner's ``finished`` checks again."""
        self._listen()
        self.reload_button.setText("Reload (waiting)")
        self.reload_button.setToolTip(f"The reload waits for {busy:,} run{'' if busy == 1 else 's'} of these "
                                      "scripts to end (cancelled)")

    @pyqtSlot(object)
    def _run_ended(self, _result: object) -> None:
        if self._answered is not None:
            self._end_round()
        elif self._pending:
            self._try_reload()

    def _stop_waiting(self) -> None:
        for runner in self._waiting_on:
            try:
                runner.finished.disconnect(self._run_ended)
            except TypeError:
                pass
        self._waiting_on.clear()
        self.reload_button.setText("Reload")
        self.reload_button.setToolTip("Import the loaded folders' scripts and their helper modules again; open "
                                      "plots of them rerun on the new code")

    def _adopt(self, folders: Set[str]) -> Tuple[int, int]:
        """Each open plot of ``folders`` takes its script's new code, or keeps its old one and says why:
        (plots that took it, plots that kept theirs)."""
        adopted = kept = 0
        manager = self.script_manager
        for instance in self._plots_of(folders):
            found = self._reloaded(instance)
            if isinstance(found, str):
                instance.keep_script(found)
                kept += 1
            elif instance.adopt_script(*found):
                instance.code_loaded_at = manager.loaded_at(found[0].script_id)
                adopted += 1
            else:
                kept += 1
        return adopted, kept

    def _reloaded(self, instance: AnalysisInstance) -> Union[Tuple[ScriptMetadata, DatasetAnalysis], str]:
        """The reloaded script of ``instance`` (its file's class of the same analysis id, else another
        of its folder's), a new instance of it, or why there is none."""
        manager = self.script_manager
        old = instance.metadata
        folder = manager.folder_of(old.script_id) or manager.class_folder(type(instance.script))
        file = old.script_id.rpartition("::")[0]
        failed = next((error for error in manager.errors() if os.path.normcase(error.path) == os.path.normcase(file)
                       or os.path.normcase(error.path) == os.path.normcase(folder)), None)
        candidates = [metadata for script_id in manager.script_ids(folder)
                      if (metadata := manager.get_script_metadata(script_id)) is not None
                      and metadata.identity().analysis_id == old.identity().analysis_id]
        candidates.sort(key=lambda metadata: metadata.script_id != old.script_id)
        if not candidates:
            return failed.message if failed is not None else "its class is gone from its folder"
        metadata = candidates[0]
        script_class = manager.get_script(metadata.script_id)
        try:
            script = script_class() if script_class is not None else None
            actions = script.get_actions() if script is not None else []
        except Exception as error:
            logging.exception("%s could not be made", metadata.name)
            return f"{type(error).__name__}: {error}"
        if not isinstance(script, DatasetAnalysis):
            return "its script no longer plots a folder's data"
        if instance.action not in actions:
            return f"its script has no “{instance.action}” now"
        return metadata, script

    # Live scripts: auto-reload

    def set_auto_reload(self, on: bool) -> None:
        """Reload when a script is saved: saved (``script_auto_reload``), and the watcher made or dropped."""
        app_settings().setValue(SCRIPT_AUTO_RELOAD_SETTING, bool(on))
        if self.auto_reload_action.isChecked() != on:
            self.auto_reload_action.blockSignals(True)
            self.auto_reload_action.setChecked(on)
            self.auto_reload_action.blockSignals(False)
        self._watch(on)

    def _watch(self, on: bool) -> None:
        if not on:
            self._settle.stop()
            if self._watcher is not None:
                self._watcher.deleteLater()
                self._watcher = None
            return
        if self._watcher is None:
            self._watcher = QFileSystemWatcher(self)
            self._watcher.directoryChanged.connect(self._changed)
            self._watcher.fileChanged.connect(self._changed)
        self._sync_watch()

    def watched(self) -> List[str]:
        """What the watcher watches now (none while auto-reload is off)."""
        watcher = self._watcher
        return sorted([*watcher.directories(), *watcher.files()]) if watcher is not None else []

    def _sync_watch(self) -> None:
        """Watch exactly the script folders that are there and their watched files (an editor that saves by
        replacing a file ends the watch on it: it is added again here, after each change)."""
        watcher = self._watcher
        if watcher is None:
            return
        manager = self.script_manager
        wanted: Set[str] = set()
        for folder in self._local_folders():
            if os.path.isdir(folder):
                wanted.add(folder)
                wanted.update(os.path.dirname(file) for file in manager.watched_files(folder))
                wanted.update(manager.watched_files(folder))
        now = set(watcher.directories()) | set(watcher.files())
        if gone := sorted(now - wanted):
            watcher.removePaths(gone)
        if new := sorted(wanted - now):
            watcher.addPaths(new)

    @pyqtSlot(str)
    def _changed(self, _path: str) -> None:
        self._settle.start()  # (Restarted by each event: compared once they stop.)

    def _local_folders(self) -> List[str]:
        """The loaded folders auto-reload watches and stats: never one on a network share."""
        return [folder for folder in self.script_manager.folders() if folder not in self._remote]

    def _check_changes(self) -> None:
        """After the settle wait: reload each folder whose ``.py`` files or helper modules changed (added,
        removed, resized or modified), only those."""
        self._sync_watch()
        changed = [folder for folder in self._local_folders() if self._folder_changed(folder)]
        if changed:
            self.reload_scripts(changed, deliberate=False)

    def _folder_changed(self, folder: str) -> bool:
        """Whether a file of ``folder`` changed since its load: one stamped then changed or went, or a new
        ``.py`` file in it. A helper file first imported since the load (lazily, in a run) that wasn't
        modified since the load isn't a change: it is stamped from now on (L5)."""
        old, now = self._stamps.get(folder), self._stamp_of(folder)
        if old is None:
            return True
        if any(now.get(file) != stamp for file, stamp in old.items()):
            return True
        since = self._stamped_at.get(folder, 0)
        for file in now.keys() - old.keys():
            if os.path.normcase(os.path.dirname(file)) == os.path.normcase(folder) or now[file][1] > since:
                return True
            old[file] = now[file]
        return False

    # Live scripts: load errors

    def _say_errors(self, folder: str) -> None:
        errors = [error for error in self.script_manager.errors() if self._in_folder(error.path, folder)]
        if errors and self.workspace is not None:
            self.workspace.notice(f"⚠ {len(errors):,} script file{'' if len(errors) == 1 else 's'} didn't load "
                                  "(listed in Scripts)")

    def _refresh(self) -> None:
        """The groups and the shown group's scripts again (after a load), and the load errors."""
        self._update_groups()
        if self.group_selector.currentText():
            self._load_current_group()
        else:
            self._show_errors()
        self.reload_button.setEnabled(bool(self._remembered or self.script_manager.folders()))

    def _show_errors(self) -> None:
        """``⚠ N script files didn't load`` at the tree's end, one line per file, its traceback in the tooltip."""
        errors = self.script_manager.errors()
        if not errors:
            return
        count = len(errors)
        top = QTreeWidgetItem(self.tree_widget, [f"⚠ {count:,} script file{'' if count == 1 else 's'} didn't load"])
        top.setFirstColumnSpanned(True)
        amber = QBrush(QColor(AMBER))
        top.setForeground(0, amber)
        top.setToolTip(0, "Fix them and Reload; double-click one for its traceback")
        for error in errors:
            item = QTreeWidgetItem(top, [error.line()])
            item.setFirstColumnSpanned(True)
            item.setForeground(0, amber)
            item.setToolTip(0, f"{error.path}\n\n{error.details or error.message}")
            item.setData(0, Qt.ItemDataRole.UserRole, error.path)
        top.setExpanded(True)

    def error_items(self) -> List[QTreeWidgetItem]:
        """The load errors' lines in the tree (none when all loaded)."""
        for index in range(self.tree_widget.topLevelItemCount()):
            top = self.tree_widget.topLevelItem(index)
            if top is not None and top.text(0).startswith("⚠ ") and "didn't load" in top.text(0):
                return [child for row in range(top.childCount()) if (child := top.child(row)) is not None]
        return []

    def _show_error_details(self, item: QTreeWidgetItem, _column: int) -> None:
        path = item.data(0, Qt.ItemDataRole.UserRole)
        error = next((error for error in self.script_manager.errors() if error.path == path), None)
        if not isinstance(path, str) or error is None:
            return
        self.show_error_details(error)

    def show_error_details(self, error: LoadError) -> QMessageBox:
        """A details window for one load error (non-modal; one at a time): its line and its traceback."""
        if self._details is not None and not sip.isdeleted(self._details):
            self._details.close()
        box = QMessageBox(QMessageBox.Icon.Warning, "Script didn't load", error.line(),
                          QMessageBox.StandardButton.Close, self)
        identify(box, "script_error_details", "Script didn't load")
        box.setInformativeText(error.path)
        box.setDetailedText(error.details or error.message)
        identify_buttons(box, "script_error_details")
        box.setModal(False)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.show()
        self._details = box
        return box

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
        self.groups = list(groups)  # Known before the selector lists them (it selects one at once).
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
            self._show_errors()

    def _on_group_changed(self, group_name: str) -> None:
        """The selector chose another group: list its scripts."""
        if group_name:
            if group_name in self.groups:
                self._load_current_group()
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

        self.tree_widget.clear()
        group_item = QTreeWidgetItem(self.tree_widget, [group_name])
        group_item.setFirstColumnSpanned(True)

        for metadata in self.script_manager.get_scripts_in_group(group_name):
            script_class = self.script_manager.get_script(metadata.script_id)
            if script_class:
                try:
                    script = script_class()
                    actions = script.get_actions()

                    item = QTreeWidgetItem(group_item, [metadata.name])
                    item.setToolTip(0, f"{metadata.description}\n{metadata.identity().text()}")
                    for column, action in enumerate(actions[:2], start=1):
                        button = self.create_button(action, self._action_callback(metadata, script, action))
                        # "Plot Counts per shot", its ID from the script's analysis ID (not its name).
                        identify(button, f"run_{id_part(metadata.identity().analysis_id)}_{id_part(action)}",
                                 f"{action} {metadata.name}", f"Run {metadata.name} on this tab's loaded data")
                        self.tree_widget.setItemWidget(item, column, button)
                except Exception as e:
                    logging.error(f"Error loading script {metadata.name}: {e}")
                    error_item = QTreeWidgetItem(group_item, [f"{metadata.name} (Error)"])
                    error_item.setForeground(0, Qt.GlobalColor.red)
                    error_item.setToolTip(0, f"{type(e).__name__}: {e}")

        group_item.setExpanded(True)
        self._show_errors()

    def _action_callback(self, metadata: ScriptMetadata, script: Any, action: str) -> Callable[[], None]:
        if isinstance(script, DatasetAnalysis):
            def run() -> None:
                self.run_analysis(metadata, script, action)
            return run
        return lambda: script.execute_action(action)

    def run_analysis(self, metadata: ScriptMetadata, script: DatasetAnalysis,
                     action: str) -> Optional[AnalysisInstance]:
        """Run ``action`` on the current tab's shown dataset, in a new plot dock."""
        plots = self.workspace
        view = plots.current_dataset_view() if plots is not None else None
        if plots is None or not isinstance(view, DatasetView):
            if plots is not None:
                plots.notice(f"{metadata.name}: load a folder's data first")
            return None
        self._instance_counter += 1
        instance_id = f"{self._instance_counter}"
        try:
            instance = AnalysisInstance(metadata, script, action, view, instance_id, plots)
        except Exception as error:
            # The script's live_policy() or constant_keys() failing (in this Qt slot it would abort the app).
            logging.exception("%s could not open its plot", metadata.name)
            plots.notice(f"{metadata.name} failed: {error}")
            return None
        instance.code_loaded_at = self.script_manager.loaded_at(metadata.script_id)
        self._analysis_instances[instance_id] = instance
        self._hold_if_reloading(instance)
        instance.start()
        self._add_dock(instance)
        return instance

    def instances(self) -> List[AnalysisInstance]:
        """The open plots (of dataset analyses), as opened."""
        return [instance for instance in self._analysis_instances.values()
                if isinstance(instance, AnalysisInstance) and not instance.is_closed]

    def find_script(self, ref: ScriptRef) -> Union[Tuple[ScriptMetadata, DatasetAnalysis], str]:
        """The loaded script ``ref`` names (by its analysis id) with its action, a new instance of
        it, or why there is none (for the user: "its script isn't loaded …")."""
        for group in self.script_manager.get_groups():
            for metadata in self.script_manager.get_scripts_in_group(group):
                if metadata.identity().analysis_id != ref.analysis_id:
                    continue
                script_class = self.script_manager.get_script(metadata.script_id)
                try:
                    script = script_class() if script_class is not None else None
                    actions = script.get_actions() if script is not None else []
                except Exception as error:
                    logging.exception("%s could not be made", metadata.name)
                    return f"its script failed: {error}"
                if not isinstance(script, DatasetAnalysis):
                    return "its script no longer plots a folder's data"
                if ref.action not in actions:
                    return f"its script has no “{ref.action}” now"
                return metadata, script
        return "its script isn't loaded (Load Scripts… its folder, then open it again)"

    def reopen_plot(self, saved: SavedPlot, wait: FolderWait, *, keep_id: bool = False,
                    place: bool = True) -> Union[AnalysisInstance, str]:
        """Open ``saved`` again (at start, or from an arrangement preset): a plot of its script with
        its saved settings, waiting for its folder's data (``wait``) instead of running. Its number
        is its saved one if ``keep_id`` and free. Not ``place``: its dock isn't added to the plot
        area yet (the caller places it, ``place_dock``). The plot, or why it couldn't open."""
        plots = self.workspace
        if plots is None:
            return "no plot area"
        found = self.find_script(saved.script)
        if isinstance(found, str):
            return found
        metadata, script = found
        if keep_id and saved.instance_id.isdecimal() and saved.instance_id not in self._analysis_instances:
            instance_id = saved.instance_id
            self._instance_counter = max(self._instance_counter, int(instance_id))
        else:
            self._instance_counter += 1
            instance_id = f"{self._instance_counter}"
        try:
            instance = AnalysisInstance(metadata, script, saved.script.action,
                                        waiting_view(saved.path, saved.root_key), instance_id, plots)
        except Exception as error:
            logging.exception("%s could not open its plot", metadata.name)
            return f"it failed: {error}"
        instance.code_loaded_at = self.script_manager.loaded_at(metadata.script_id)
        self._analysis_instances[instance_id] = instance
        self._hold_if_reloading(instance)
        instance.start(saved, wait)
        if instance.open_error:
            # Without its settings page it would be recorded with none: it couldn't reopen (kept).
            del self._analysis_instances[instance_id]
            instance.close()
            return f"it failed: {instance.open_error}"
        if place:
            self._add_dock(instance)
        return instance

    def place_dock(self, instance: LinkedAnalysisInstance, tab_with: Optional[QDockWidget]) -> None:
        """Add a reopened plot's dock to the plot area: tabbed with ``tab_with``, else on its own."""
        self._add_dock(instance, tab_with)

    def _add_dock(self, instance: LinkedAnalysisInstance, tab_with: Union[Optional[QDockWidget], str] = AUTO) -> None:
        plots, dock = self.workspace, instance.dock_widget
        if plots is None or not isinstance(dock, AnalysisDock):
            return
        instance.ended.connect(self._forget_instance)
        settings = plots.panel_right_top_plot_settings
        area = plots.middle_mainwindow
        settings.follow(area)
        closer = area.findChild(DockTabCloser) or DockTabCloser(area)
        target = (self.tab_target(area, plots.dock_widgets, settings.current_plot()) if tab_with == AUTO
                  else tab_with if isinstance(tab_with, QDockWidget) else None)
        area.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        # In a shown area Qt hides the new dock and shows it later, and it won't tab a plot
        # opened meanwhile with a hidden one: show it now.
        dock.show()
        if target is not None:
            # Plots share the area as tabs; the new one comes to the front.
            area.tabifyDockWidget(target, dock)
            dock.raise_()
        closer.watch(dock)
        plots.dock_widgets.append(dock)
        plots.update_placeholder_visibility()
        self.plotsChanged.emit()

    @staticmethod
    def tab_target(area: QMainWindow, open_docks: List[QDockWidget],
                   shown: Optional[QDockWidget]) -> Optional[QDockWidget]:
        """The open plot a new plot is tabbed with in ``area``: the plot whose settings show
        (``shown``) if it is docked there, else the newest docked one. Docked means in the
        area and not floating; a plot behind another tab counts, and whether docks are
        visible yet doesn't matter (``addDockWidget`` shows a dock later, and the area may not
        be shown). Never a floating plot (Qt would put the new one in its old place, beside
        some other plot), nor a hidden plot on its own (unticked in the area's menu: the new
        one would sit alone in its place); a hidden plot in a tab group still stands for that
        group. Closed plots aren't open. None: the new plot docks on its own (no plot open,
        or all floating or hidden)."""
        docked = [dock for dock in open_docks if not sip.isdeleted(dock) and not dock.isFloating()
                  and area.dockWidgetArea(dock) != Qt.DockWidgetArea.NoDockWidgetArea
                  and (not dock.isHidden() or area.tabifiedDockWidgets(dock))]
        if shown in docked:
            return shown
        return docked[-1] if docked else None

    @pyqtSlot(str)
    def _forget_instance(self, instance_id: str) -> None:
        if self._analysis_instances.pop(instance_id, None) is not None:
            self.plotsChanged.emit()

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

