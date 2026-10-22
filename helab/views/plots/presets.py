"""Presets (roadmaps/presets-and-workspaces.md, stage 1; the records: helab/analysis/presets.py).

- **Script presets**: a plot's settings page has a Presets row (``PresetBar``): save the plot's
  settings under a name, apply a saved one, delete one. They belong to the script and action,
  shared by every plot of it, saved under ``script_presets/<id>/<action>`` (one record per script).
- **Arrangement presets** (``ArrangementPresets``, the main window's Presets menu): one folder,
  whether Live watched it, and its plots with their settings and places. Applying one selects
  the folder in the current tab as typing its path would, loads it as a deliberate selection
  (the normal rules: cache first, large-folder questions), opens the plots, each waiting for the
  folder's data, and turns Live on only once the folder's data shows (``LiveWhenShown``), saying
  why if it can't. Saved under ``arrangement_presets/<name>``.

Saved settings that don't fit the script now are named, never replaced or clamped
(``helab.analysis.presets.check_plot``). A record that can't be read is named and left as it is.
"""
from __future__ import annotations

import dataclasses
import logging
import time
from typing import TYPE_CHECKING, Callable, List, Optional
from urllib.parse import quote, unquote

from PyQt6 import sip
from PyQt6.QtCore import QObject, QSettings, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox, QPushButton,
                             QSizePolicy, QVBoxLayout, QWidget)

from helab.analysis.dataset_view import root_key
from helab.analysis.presets import (Arrangement, PlotCheck, RecordError, ScriptPreset, ScriptPresets, ScriptRef,
                                    parse, preset_note)
from helab.utils.colours import AMBER
from helab.utils.folder_cache import FolderCache
from helab.utils.settings_defaults import ARRANGEMENT_PRESETS_PREFIX, SCRIPT_PRESETS_PREFIX, read_setting
from helab.utils.settings_store import app_settings
from helab.views.plots.arrangement import capture, folder_name, open_arrangement

if TYPE_CHECKING:
    from helab.views.FolderExplorer import FolderExplorer
    from helab.views.plots.instance import AnalysisInstance
    from helab.views.plots.script_tree import TreePanelWidget
    from helab.views.plots.workspace import PlotWorkspace


# Storage


def script_key(ref: ScriptRef) -> str:
    return f"{SCRIPT_PRESETS_PREFIX}{quote(ref.analysis_id, safe='')}/{quote(ref.action, safe='')}"


def read_script_presets(ref: ScriptRef, settings: Optional[QSettings] = None) -> ScriptPresets:
    settings = settings or app_settings()
    settings.sync()  # Another HeLab may have saved since.
    found = ScriptPresets.parse(read_setting(settings, script_key(ref)))
    if found.error:
        logging.warning("Presets of %s can't be read (%s): %r", ref.label(), found.error,
                        str(read_setting(settings, script_key(ref)))[:2000])
    return found


def write_script_presets(ref: ScriptRef, text: str, settings: Optional[QSettings] = None) -> None:
    settings = settings or app_settings()
    settings.setValue(script_key(ref), text)
    settings.sync()
    signals().scriptPresetsChanged.emit(script_key(ref))


def arrangement_key(name: str) -> str:
    return f"{ARRANGEMENT_PRESETS_PREFIX}{quote(name, safe='')}"


def arrangement_names(settings: Optional[QSettings] = None) -> List[str]:
    settings = settings or app_settings()
    settings.sync()
    settings.beginGroup(ARRANGEMENT_PRESETS_PREFIX.rstrip("/"))
    try:
        keys = settings.childKeys()
    finally:
        settings.endGroup()
    return sorted((unquote(key) for key in keys), key=str.casefold)


def read_arrangement(name: str, settings: Optional[QSettings] = None) -> Arrangement:
    """The arrangement preset ``name``; ``RecordError`` (naming why) if it can't be read."""
    settings = settings or app_settings()
    text = read_setting(settings, arrangement_key(name))
    try:
        return parse(text)
    except RecordError:
        logging.warning("Preset %r can't be read: %r", name, str(text)[:2000])
        raise


def write_arrangement(name: str, arrangement: Arrangement, settings: Optional[QSettings] = None) -> None:
    settings = settings or app_settings()
    settings.setValue(arrangement_key(name), arrangement.dumps())
    settings.sync()


def delete_arrangement(name: str, settings: Optional[QSettings] = None) -> None:
    settings = settings or app_settings()
    settings.remove(arrangement_key(name))
    settings.sync()


class PresetSignals(QObject):
    """A script's presets changed (its ``script_key``): every plot of it lists them again."""
    scriptPresetsChanged = pyqtSignal(str)


_signals: Optional[PresetSignals] = None


def signals() -> PresetSignals:
    global _signals
    if _signals is None or sip.isdeleted(_signals):
        _signals = PresetSignals()
    return _signals


# Questions (replaceable in tests)


def ask_name(parent: Optional[QWidget], title: str, label: str, text: str) -> Optional[str]:
    name, ok = QInputDialog.getText(parent, title, label, text=text)
    return name.strip() if ok and name.strip() else None


def confirm(parent: Optional[QWidget], title: str, text: str, action: str) -> bool:
    """Ask first; Cancel is the default."""
    box = QMessageBox(QMessageBox.Icon.Question, title, text, QMessageBox.StandardButton.Cancel, parent)
    yes = box.addButton(action, QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    return box.clickedButton() is yes


# A plot's Presets row


class PresetBar(QWidget):
    """A plot's Presets row in its settings page: the script's presets, Apply, Save… and Delete…,
    and below it, only when there is something to say, one line on the last preset applied or
    reopened (settings not applied named; the rest in its tooltip)."""

    def __init__(self, plot: AnalysisInstance, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.plot = plot
        self.ref = plot.script_ref()
        self.ask_name: Callable[[Optional[QWidget], str, str, str], Optional[str]] = ask_name
        self.confirm: Callable[[Optional[QWidget], str, str, str], bool] = confirm
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        row.addWidget(QLabel("Preset:"))
        self.combo = QComboBox()
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(self.combo, 1)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setToolTip("Put this preset's settings into the plot's (Rerun runs with them)")
        self.apply_button.clicked.connect(self.apply)
        self.save_button = QPushButton("Save…")
        self.save_button.setToolTip(f"Save these settings as a preset of {plot.name}, for every plot of it")
        self.save_button.clicked.connect(self.save)
        self.delete_button = QPushButton("Delete…")
        self.delete_button.setToolTip("Delete this preset")
        self.delete_button.clicked.connect(self.delete)
        for button in (self.apply_button, self.save_button, self.delete_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.note = QLabel()
        self.note.setTextFormat(self.note.textFormat().PlainText)
        self.note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.note.hide()
        layout.addWidget(self.note)
        self.presets = ScriptPresets()
        self.refresh()
        signals().scriptPresetsChanged.connect(self._changed)

    def refresh(self) -> None:
        """List the script's presets again (keeping the one chosen, if still there)."""
        chosen = self.combo.currentText()
        self.presets = read_script_presets(self.ref)
        names = self.presets.names()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(names)
        if chosen in names:
            self.combo.setCurrentText(chosen)
        self.combo.blockSignals(False)
        problems = []
        if self.presets.error:
            problems.append(f"{self.plot.name}'s saved presets can't be read ({self.presets.error}); saving one "
                            "asks to replace them")
        problems += [f"Preset “{name}” can't be read ({why})" for name, why in self.presets.unreadable.items()]
        self.combo.setEnabled(bool(names))
        self.combo.setToolTip("\n".join(problems) if problems else
                              f"Presets of {self.ref.label()}, shared by every plot of it" if names else
                              f"No presets of {self.ref.label()} yet: Save… saves these settings as one")
        self.combo.setPlaceholderText("none saved" if not problems else "⚠ can't be read")
        self.apply_button.setEnabled(bool(names))
        self.delete_button.setEnabled(bool(names))
        if problems and not self.note.isVisible():
            self._show(f"⚠ {problems[0]}", "\n".join(problems), amber=True)

    @pyqtSlot(str)
    def _changed(self, key: str) -> None:
        if key == script_key(self.ref) and not sip.isdeleted(self):
            self.refresh()

    def set_note(self, what: str, check: PlotCheck, kept: str, quiet: bool = False) -> None:
        """Say what applying saved settings did: ``what`` ("Preset “X”", "Reopened"), then the settings
        not applied (``kept`` as they are) and notes. ``quiet``: nothing to say if all applied."""
        summary = check.summary(kept)
        if quiet and not summary:
            self._show("", "", amber=False)
            return
        text = " · ".join(filter(None, (f"{what} applied" if not quiet else what, summary)))
        self._show(text, check.details() or text, amber=bool(check.problems))

    def _show(self, text: str, tip: str, amber: bool) -> None:
        self.note.setText(text)
        self.note.setToolTip(tip)
        self.note.setStyleSheet(f"color: {AMBER};" if amber else "")
        self.note.setVisible(bool(text))

    def save(self) -> None:
        plot = self.plot
        name = self.ask_name(self, "Save preset", f"Save these settings of {plot.name} as:",
                             self.combo.currentText())
        if not name:
            return
        presets = read_script_presets(self.ref)
        if presets.error:
            if not self.confirm(self, "Replace unreadable presets?",
                                f"{plot.name}'s saved presets can't be read ({presets.error}). Saving “{name}” "
                                "replaces them (what was there is in HeLab's log).", "Replace them"):
                return
            presets = ScriptPresets()
        elif name in presets.presets or name in presets.unreadable:
            if not self.confirm(self, "Replace preset?", f"A preset “{name}” of {plot.name} exists. Replace it?",
                                "Replace"):
                return
        preset = ScriptPreset(name, self.ref, plot.values(), plot.backend(), time.time())
        try:
            text = presets.with_preset(preset)
        except ValueError as error:  # A value JSON can't hold (not a finite number).
            self._show(f"⚠ Preset “{name}” not saved: {error}", str(error), amber=True)
            return
        write_script_presets(self.ref, text)
        plot.preset_from = (name, preset.saved_at)
        self.combo.setCurrentText(name)
        self._show(f"Saved preset “{name}”", f"Every plot of {self.ref.label()} lists it", amber=False)

    def apply(self) -> None:
        name = self.combo.currentText()
        if not name:
            return
        presets = read_script_presets(self.ref)
        preset = presets.presets.get(name)
        if preset is None:
            self.refresh()
            self._show(f"⚠ Preset “{name}” isn't there now", "", amber=True)
            return
        self.plot.apply_saved(preset, "left as they were")
        self.plot.preset_from = (name, preset.saved_at)

    def delete(self) -> None:
        name = self.combo.currentText()
        if not name or not self.confirm(self, "Delete preset?", f"Delete the preset “{name}” of {self.plot.name}? "
                                        "Every plot of it loses it; plots keep their settings.", "Delete"):
            return
        presets = read_script_presets(self.ref)
        if presets.error:
            self.refresh()
            return
        write_script_presets(self.ref, presets.without(name))
        self._show(f"Deleted preset “{name}”", "", amber=False)


# Arrangement presets


class LiveWhenShown(QObject):
    """After an arrangement preset is applied: turn Live on for its folder once the tab shows its
    data, under the normal rules (``FolderExplorer.start_live``), never forced; if it can't, say
    why once. Also names the folder once if it can't be listed or loaded (unmounted, moved).
    Gives up if the tab selects another folder or closes."""

    def __init__(self, explorer: FolderExplorer, folder: str, name: str, live: bool,
                 notice: Callable[[str], None]) -> None:
        super().__init__(explorer)
        self.explorer, self.folder, self.name, self.live = explorer, folder, name, live
        self._notice = notice
        self.done = False
        self._missing_named = False
        self._signals = [explorer.dataLoaded, explorer.loadStateChanged, explorer.liveChanged,
                         explorer.model.activityChanged]
        for signal in self._signals:
            signal.connect(self.check)
        QTimer.singleShot(0, self.check)

    def check(self, *_: object) -> None:
        if self.done:
            return
        explorer = self.explorer
        if sip.isdeleted(explorer) or explorer.closed:
            self.finish()
            return
        if explorer.selected_path_globally != self.folder:
            if self.live:
                self._notice(f"Preset “{self.name}”: Live not started: another folder was selected")
            self.finish()
            return
        missing = self._missing()
        if missing and not self._missing_named:
            self._missing_named = True
            self._notice(f"Preset “{self.name}”: {folder_name(self.folder)} can't be opened now ({missing}): "
                         "its plots wait for its data")
        if not self.live:
            if missing or self._shown():
                self.finish()
            return
        if explorer.live is not None:
            self.finish()  # On (by the user, or already).
            return
        if self._busy():
            return
        reason = explorer.live_unavailable(self.folder)
        if not reason and explorer.start_live():
            self._notice(f"Preset “{self.name}”: Live on for {folder_name(self.folder)}")
        else:
            self._notice(f"Preset “{self.name}”: Live not started: {reason or 'it could not start'}")
        self.finish()

    def _shown(self) -> bool:
        explorer = self.explorer
        return explorer.folder_opened_path == self.folder and explorer.folder_opened_data is not None

    def _busy(self) -> bool:
        """The folder's load (or its wait to start) is still going: its data may yet show."""
        explorer = self.explorer
        return ((explorer.loading and explorer.load_path == self.folder) or explorer.load_waiting
                or explorer.settling or (not self._shown() and not explorer.load_error and not self._missing()
                                         and explorer.large_state(self.folder) is None
                                         and self._listing()))

    def _listing(self) -> bool:
        """Its listing hasn't answered yet (a Live from no shots needs it)."""
        node = self.explorer.model.nodes.get(self.folder)
        return node is None or (node.report is None and not node.error)

    def _missing(self) -> str:
        explorer = self.explorer
        node = explorer.model.nodes.get(self.folder)
        if node is not None and node.error:
            return node.error.removesuffix(" — Retry")
        if explorer.load_error and explorer.selected_path_globally == self.folder:
            return explorer.load_error.removesuffix(" — Retry")
        return ""

    def finish(self) -> None:
        if self.done:
            return
        self.done = True
        for signal in self._signals:
            try:
                signal.disconnect(self.check)
            except (TypeError, RuntimeError):
                pass
        self.deleteLater()


class ArrangementPresets(QObject):
    """The Presets menu's arrangement presets: Save the current folder's arrangement as a preset…,
    apply one, delete one (asks first). Applying one replaces the open plots, after asking.

    Saving takes the current tab's folder (its data shown, else its selection), whether Live
    watches it, and the open plots of that folder (plots of other folders are left out, and
    named): each plot's settings, library, Live group and the script preset its settings came
    from, and where the plots sit."""

    def __init__(self, plots: PlotWorkspace, scripts: TreePanelWidget,
                 current_explorer: Callable[[], Optional[FolderExplorer]], parent: QWidget,
                 cache: Optional[FolderCache] = None) -> None:
        super().__init__(parent)
        self.plots, self.scripts, self.current_explorer, self.parent_widget = plots, scripts, current_explorer, parent
        self._given_cache = cache
        self.ask_name: Callable[[Optional[QWidget], str, str, str], Optional[str]] = ask_name
        self.confirm: Callable[[Optional[QWidget], str, str, str], bool] = confirm
        self.warn: Callable[[str, str], None] = self._warn
        self.live_starter: Optional[LiveWhenShown] = None

    def _warn(self, title: str, text: str) -> None:
        QMessageBox.warning(self.parent_widget, title, text)

    def cache(self) -> FolderCache:
        if self._given_cache is not None:
            return self._given_cache
        budget = self.plots.ram_budget
        if budget is not None:
            return budget.cache
        from helab.utils.folder_cache import get_folder_cache
        from helab.utils.io_service import get_io_service
        return get_folder_cache(get_io_service())

    def fill_menu(self, menu: QMenu) -> None:
        """The Presets menu, as it shows: Save…, then each preset (applies it), then Delete ▸."""
        menu.clear()
        save = QAction("Save Folder and Plots as Preset…", menu)
        save.setToolTip("Save the current tab's folder, whether Live watches it, and its open plots with their "
                        "settings and places, under a name")
        save.triggered.connect(self.save)
        menu.addAction(save)
        names = arrangement_names()
        menu.addSeparator()
        if not names:
            empty = QAction("No presets saved", menu)
            empty.setEnabled(False)
            menu.addAction(empty)
            return
        delete = QMenu("Delete Preset", menu)
        for name in names:
            action = QAction(name, menu)
            try:
                arrangement = read_arrangement(name)
            except RecordError as error:
                action.setText(f"⚠ {name} (can't be read)")
                action.setToolTip(f"This preset can't be read: {error}")
                action.setEnabled(False)
            else:
                count = len(arrangement.plots)
                action.setToolTip(f"Open {folder_name(arrangement.folder)} with its {count:,} plot"
                                  f"{'' if count == 1 else 's'}" + (", and Live" if arrangement.live else ""))
                action.triggered.connect(lambda _=False, name=name: self.apply(name))
            menu.addAction(action)
            remove = QAction(name, delete)
            remove.triggered.connect(lambda _=False, name=name: self.delete(name))
            delete.addAction(remove)
        menu.addSeparator()
        menu.addMenu(delete)
        menu.setToolTipsVisible(True)

    def save(self) -> Optional[Arrangement]:
        explorer = self.current_explorer()
        if explorer is None or explorer.closed:
            self.plots.notice("Presets: open a folder tab first")
            return None
        folder = (explorer.folder_opened_path if explorer.folder_opened_path and explorer.folder_opened_data is not None
                  else explorer.selected_path_globally)
        if not folder:
            self.plots.notice("Presets: select a folder first")
            return None
        key = FolderCache.key(folder)
        instances = self.scripts.instances()
        mine = [instance for instance in instances if FolderCache.key(instance.path) == key]
        others = len(instances) - len(mine)
        name = self.ask_name(self.parent_widget, "Save preset",
                             f"Save {folder_name(folder)} with its {len(mine):,} plot{'' if len(mine) == 1 else 's'}"
                             + (f" (not the {others:,} of other folders)" if others else "") + " as:", "")
        if not name:
            return None
        if name in arrangement_names() and not self.confirm(
                self.parent_widget, "Replace preset?", f"A preset “{name}” exists. Replace it?", "Replace"):
            return None
        root = self.cache().root_of(key)
        live = explorer.live is not None and FolderCache.key(explorer.live.path) == key
        arrangement = capture(self.plots, mine, folder=key,
                              root_key=root_key(root[0], root[1], key) if root else "", live=live)
        try:
            write_arrangement(name, arrangement)
        except ValueError as error:
            self.warn("Preset not saved", f"“{name}” couldn't be saved: {error}")
            return None
        self.plots.notice(f"Saved preset “{name}”: {folder_name(folder)}, {len(mine):,} plot"
                          f"{'' if len(mine) == 1 else 's'}" + (", Live" if live else ""))
        return arrangement

    def apply(self, name: str) -> List[AnalysisInstance]:
        """Apply preset ``name``: the open plots close (after asking), its folder is selected and
        loaded in the current tab, its plots open in their places, waiting for its data, and Live
        starts once the data shows if the preset says so. The plots opened."""
        try:
            arrangement = read_arrangement(name)
        except RecordError as error:
            self.warn("Preset can't be read", f"The preset “{name}” can't be read ({error}). It is left as it is.")
            return []
        explorer = self.current_explorer()
        if explorer is None or explorer.closed:
            self.plots.notice("Presets: open a folder tab first")
            return []
        open_plots = self.scripts.instances()
        if open_plots and not self.confirm(
                self.parent_widget, "Apply preset?",
                f"Applying “{name}” closes the {len(open_plots):,} open plot{'' if len(open_plots) == 1 else 's'} "
                f"and opens {folder_name(arrangement.folder)} with its {len(arrangement.plots):,}.", "Apply"):
            return []
        for instance in open_plots:
            instance.close()
        if self.live_starter is not None and not sip.isdeleted(self.live_starter):
            self.live_starter.finish()
        folder = arrangement.folder
        if FolderCache.key(explorer.selected_path_globally) != folder or explorer.view_path != folder:
            explorer.open_to_path(folder)  # As typing its path in the tab's path bar
        # A deliberate selection: it loads (cache first) even where automatic loads wouldn't, and a
        # large folder asks.
        explorer.load_to_ram_cache(folder, dwell=False, explicit=True)
        opened, failed = open_arrangement(self.scripts, self.cache(), arrangement, folder=folder)
        presets = {plot.script: read_script_presets(plot.script) for plot in arrangement.plots if plot.preset}
        for instance, saved in opened:
            # Its values are the arrangement's own; the script preset they came from may have changed.
            note = preset_note(saved, presets.get(saved.script))
            check = instance.reopen_check
            if note and instance.presets is not None and check is not None:
                instance.presets.set_note(f"Preset “{name}”", dataclasses.replace(check, notes=(*check.notes, note)),
                                          "at the script's defaults", quiet=True)
        failed += [f"a plot ({why})" for why in arrangement.unreadable]
        if failed:
            self.plots.notice(f"Preset “{name}”: not opened: {'; '.join(failed)}")
        self.live_starter = LiveWhenShown(explorer, folder, name, arrangement.live, self.plots.notice)
        return [instance for instance, _ in opened]

    def delete(self, name: str) -> bool:
        if not self.confirm(self.parent_widget, "Delete preset?", f"Delete the preset “{name}”? Open plots stay.",
                            "Delete"):
            return False
        delete_arrangement(name)
        self.plots.notice(f"Deleted preset “{name}”")
        return True

