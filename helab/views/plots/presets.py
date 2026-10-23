"""Presets (roadmaps/presets-and-workspaces.md, stage 1; the records: helab/analysis/presets.py).

- **Script presets**: a plot's settings page has a Presets row (``PresetBar``): save the plot's
  settings under a name, apply a saved one, delete one. They belong to the script and action,
  shared by every plot of it.
- **Arrangement presets** (``ArrangementPresets``, the main window's Presets menu): one folder,
  whether Live watched it, and its plots with their settings and places. Applying one selects
  the folder in the current tab as typing its path would, loads it as a deliberate selection
  (the normal rules: cache first, large-folder questions), opens the plots, each waiting for the
  folder's data, and turns Live on only once the folder's data shows (``PresetFolder``), saying
  why if it can't.

Both are saved in the disk cache store (its ``presets`` table, written only by helpers, like
folder constants): Clear all, purges and Reset all settings leave them. Settings → Cache ›
Presets… lists them (``helab/views/PresetsInspector.py``).

Saved settings that don't fit the script now are named, never replaced or clamped
(``helab.analysis.presets.check_plot``). A record that can't be read is named and left as it is.
"""
from __future__ import annotations

import dataclasses
import logging
import os
import time
from typing import TYPE_CHECKING, Callable, List, Optional
from urllib.parse import quote

from PyQt6 import sip
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox,
                             QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from helab.analysis.backends import BACKEND, backend_specs
from helab.analysis.dataset_view import root_key
from helab.analysis.parameter_tree import parameter_of
from helab.analysis.parameters import ParameterSpec
from helab.analysis.presets import (Arrangement, PlotCheck, RecordError, ScriptPreset, ScriptPresets, ScriptRef,
                                    check_value, dumps, parse, preset_note)
from helab.utils.colours import AMBER
from helab.utils.folder_cache import PRESETS_WAIT_READ, FolderCache
from helab.views.plots.arrangement import capture, folder_name, open_arrangement

if TYPE_CHECKING:
    from helab.views.FolderExplorer import FolderExplorer
    from helab.views.plots.instance import AnalysisInstance
    from helab.views.plots.script_tree import TreePanelWidget
    from helab.views.plots.workspace import PlotWorkspace


# Storage: the disk cache store's ``presets`` table, through the app's FolderCache (helpers read
# and write it; ``FolderCache.read_presets``, ``set_presets``). Each write returns "" or why the
# change lasts only this session for now (RAM only; saved once the store is there).

SCRIPT, ARRANGEMENT = "script", "arrangement"


def preset_store() -> FolderCache:
    """The app's FolderCache, which holds the presets (replaceable in tests)."""
    from helab.utils.folder_cache import get_folder_cache
    from helab.utils.io_service import get_io_service
    return get_folder_cache(get_io_service())


def script_scope(ref: ScriptRef) -> str:
    """A script preset's ``scope``: its script's id and action, both percent-encoded."""
    return f"{quote(ref.analysis_id, safe='')}/{quote(ref.action, safe='')}"


def read_script_presets(ref: ScriptRef) -> ScriptPresets:
    store = preset_store()
    records = {name: text for (_, name), text in store.preset_records(SCRIPT, script_scope(ref)).items()}
    return ScriptPresets.from_records(records, store.presets_error)


def presets_known() -> bool:
    """The store's presets have been read (or this session's are all there are)."""
    return preset_store().presets_known()


def take_conflicts(kind: str, scope: str | None = None) -> List[str]:
    """The presets of ``kind`` (``scope``) saved before the store's names were read under a name it
    held: each said once, as "Preset “p” not saved: …" (the saved one is kept)."""
    store = preset_store()
    found = [key for key in store.presets_conflicts if key[0] == kind and (scope is None or key[1] == scope)]
    return [f"Preset “{key[2]}” not saved: {store.presets_conflicts.pop(key)}" for key in found]


def write_script_preset(preset: ScriptPreset) -> str:
    """Save ``preset``; ``ValueError`` for a value JSON can't hold."""
    return preset_store().set_presets([(SCRIPT, script_scope(preset.script), preset.name, dumps(preset))])


def delete_script_preset(ref: ScriptRef, name: str) -> str:
    return preset_store().set_presets([(SCRIPT, script_scope(ref), name, None)])


def arrangement_names() -> List[str]:
    return sorted((name for _, name in preset_store().preset_records(ARRANGEMENT)), key=str.casefold)


def read_arrangement(name: str) -> Arrangement:
    """The arrangement preset ``name``; ``RecordError`` (naming why) if it can't be read."""
    text = preset_store().preset_records(ARRANGEMENT).get(("", name))
    if text is None:
        raise RecordError("it isn't saved now")
    try:
        return parse(text)
    except RecordError:
        logging.warning("Preset %r can't be read: %r", name, text[:2000])
        raise


def write_arrangement(name: str, arrangement: Arrangement) -> str:
    """Save ``arrangement`` as ``name``; ``ValueError`` for a value JSON can't hold."""
    return preset_store().set_presets([(ARRANGEMENT, "", name, dumps(arrangement))])


def delete_arrangement(name: str) -> str:
    return preset_store().set_presets([(ARRANGEMENT, "", name, None)])


def folder_now(cache: FolderCache, key: str) -> str:
    """Where the folder ``key`` (``root://<uuid>/<relative>``) is now, by its data root as seen this
    session ("" if it hasn't been): an arrangement's folder that moved with its root."""
    if not key.startswith("root://"):
        return ""
    identifier, _, relative = key[len("root://"):].partition("/")
    for folder, (uuid, _) in cache.data_roots.items():
        if uuid == identifier:
            return os.path.join(folder, *relative.split("/")) if relative else folder
    return ""


def saved_note(why: str) -> str:
    """After saving: "" if a helper saves it now, else why not yet: " (RAM only: why)", or " (saved
    once the saved presets are read)" before the store's names are known."""
    if why == PRESETS_WAIT_READ:
        return " (saved once the saved presets are read)"
    return f" ({why if why.startswith('RAM only') else f'RAM only for now: {why}'})" if why else ""


# Questions (replaceable in tests)


def ask_name(parent: Optional[QWidget], title: str, label: str, text: str) -> Optional[str]:
    name, ok = QInputDialog.getText(parent, title, label, text=text)
    return name.strip() if ok and name.strip() else None


def replace_or_add(parent: Optional[QWidget], title: str, text: str) -> Optional[str]:
    """Replace the open plots, or Add beside them ("replace", "add"); None: Cancel (the default)."""
    box = QMessageBox(QMessageBox.Icon.Question, title, text, QMessageBox.StandardButton.Cancel, parent)
    replace = box.addButton("Replace", QMessageBox.ButtonRole.AcceptRole)
    add = box.addButton("Add", QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    clicked = box.clickedButton()
    return "replace" if clicked is replace else "add" if clicked is add else None


def confirm(parent: Optional[QWidget], title: str, text: str, action: str) -> bool:
    """Ask first; Cancel is the default."""
    box = QMessageBox(QMessageBox.Icon.Question, title, text, QMessageBox.StandardButton.Cancel, parent)
    yes = box.addButton(action, QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    return box.clickedButton() is yes


# A plot's Presets row


def changed_mark() -> QIcon:
    """The dot beside a setting changed from the preset applied (the palette's highlight colour)."""
    size = 10
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    app = QApplication.instance()
    colour = app.palette().highlight().color() if isinstance(app, QApplication) else QColor("#3070d0")
    painter.setBrush(colour)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return QIcon(pixmap)


class PresetBar(QWidget):
    """A plot's Presets row in its settings page: the script's presets, Apply, Save… and Delete…,
    and below it, only when there is something to say, one line on the last preset applied or
    reopened (settings not applied named; the rest in its tooltip).

    Once a preset is applied (or saved) here, each setting that differs from it has a dot beside
    its name, the preset's value in its tooltip (memory only: the preset as applied), and the row
    shows "Save N changes ▾": Save to preset “<name>” (asks first) or Save as new preset…."""

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
        self.changes_button = QToolButton()
        self.changes_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        changes = QMenu(self.changes_button)
        self.save_to_action = QAction("Save to preset", changes)
        self.save_to_action.triggered.connect(self.save_to_applied)
        self.save_new_action = QAction("Save as new preset…", changes)
        self.save_new_action.triggered.connect(self.save)
        changes.addAction(self.save_to_action)
        changes.addAction(self.save_new_action)
        self.changes_button.setMenu(changes)
        self.changes_button.hide()
        for button in (self.apply_button, self.save_button, self.delete_button):
            row.addWidget(button)
        row.addWidget(self.changes_button)
        layout.addLayout(row)
        self.note = QLabel()
        self.note.setTextFormat(self.note.textFormat().PlainText)
        self.note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.note.hide()
        layout.addWidget(self.note)
        self.presets = ScriptPresets()
        self._problems: List[str] = []
        # The preset applied (or saved) here last, as it was then: what changed settings differ from.
        self.applied: Optional[ScriptPreset] = None
        self._mark = changed_mark()
        self._marked: set[str] = set()
        self._marks_soon = QTimer(self)
        self._marks_soon.setSingleShot(True)
        self._marks_soon.setInterval(0)
        self._marks_soon.timeout.connect(self.update_marks)
        self.refresh()
        store = preset_store()
        store.presetsChanged.connect(self._changed)
        store.read_presets()  # Another HeLab may have changed them since.
        if plot.parameter_root is not None:
            plot.parameter_root.sigTreeStateChanged.connect(self._tree_changed)

    def _tree_changed(self, *_: object) -> None:
        if self.applied is not None and not sip.isdeleted(self):
            self._marks_soon.start()

    def set_applied(self, preset: Optional[ScriptPreset]) -> None:
        self.applied = preset
        self.update_marks()

    def _compared(self) -> List[ParameterSpec]:
        plot = self.plot
        return [*plot.script.parameters(plot.action), *backend_specs(plot.script.backends(plot.action))]

    def changes(self) -> List[tuple[ParameterSpec, object]]:
        """The settings that differ from the preset applied: (spec, the preset's value). Settings the
        preset doesn't hold, or holds a value the script's settings don't accept (``check_value``),
        aren't compared: its note named them."""
        preset, root = self.applied, self.plot.parameter_root
        if preset is None or root is None:
            return []
        saved = {**preset.values, **({BACKEND: preset.backend} if preset.backend else {})}
        found: List[tuple[ParameterSpec, object]] = []
        for spec in self._compared():
            if spec.name not in saved:
                continue
            wanted, _ = check_value(spec, saved[spec.name])
            if wanted is not None and wanted != parameter_of(root, spec).value():
                found.append((spec, wanted))
        return found

    def update_marks(self) -> None:
        """A dot beside each setting changed from the preset applied, and the Save changes button."""
        root = self.plot.parameter_root
        if root is None or sip.isdeleted(self):
            return
        changed = {spec.name: (spec, wanted) for spec, wanted in self.changes()}
        name = self.applied.name if self.applied is not None else ""
        for spec in self._compared():
            if spec.name not in changed and spec.name not in self._marked:
                continue
            tip = ""
            if spec.name in changed:
                shown = spec.text(changed[spec.name][1])[len(spec.title) + 1:]
                tip = f"Changed from preset “{name}”, which has {shown}"
            for item in list(parameter_of(root, spec).items.keys()):
                item.setIcon(0, self._mark if tip else QIcon())
                item.setToolTip(0, tip)
        self._marked = set(changed)
        count = len(changed)
        self.changes_button.setVisible(bool(count))
        if count:
            self.changes_button.setText(f"Save {count:,} change{'' if count == 1 else 's'}")
            self.changes_button.setToolTip(f"Settings changed from preset “{name}”: "
                                           + ", ".join(spec.title for spec, _ in changed.values()))
            self.save_to_action.setText(f"Save to preset “{name}”")

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
        elif names:
            self.combo.setCurrentIndex(0)  # (With a placeholder, Qt chooses none itself.)
        self.combo.blockSignals(False)
        problems = []
        if self.presets.error:
            problems.append(f"Saved presets can't be read ({self.presets.error}): only this session's are listed")
        problems += [f"Preset “{name}” can't be read ({why})" for name, why in self.presets.unreadable.items()]
        self._problems = problems
        note = preset_store().presets_note()
        self.combo.setEnabled(bool(names))
        self.combo.setToolTip("\n".join(problems) if problems else "\n".join(filter(None, (
            f"Presets of {self.ref.label()}, shared by every plot of it" if names else
            f"No presets of {self.ref.label()} yet: Save… saves these settings as one" if presets_known() else
            "", note))))
        self.combo.setPlaceholderText("⚠ can't be read" if problems else "reading…" if not presets_known()
                                      else "none saved")
        self.apply_button.setEnabled(bool(names))
        self.delete_button.setEnabled(bool(names))
        if problems and not self.note.isVisible():
            self._show_problems()
        conflicts = take_conflicts(SCRIPT, script_scope(self.ref))
        if conflicts:
            self._show(f"⚠ {conflicts[0]}", "\n".join(conflicts), amber=True)
            if self.applied is not None and any(f"“{self.applied.name}”" in text for text in conflicts):
                self.set_applied(None)  # The saved one is kept: these settings aren't it.
        applied = self.applied
        row = preset_store().presets.get((SCRIPT, script_scope(self.ref), applied.name)) if applied else None
        if applied is not None and applied.name not in self.presets.presets and (
                (row is not None and row["record"] is None) or (presets_known() and not self.presets.error)):
            self.set_applied(None)  # Deleted (by another plot of the script): nothing to compare with.

    def _show_problems(self) -> None:
        """The saved presets that can't be read (or nothing)."""
        problems = self._problems
        self._show(f"⚠ {problems[0]}" if problems else "", "\n".join(problems), amber=bool(problems))

    @pyqtSlot()
    def _changed(self) -> None:
        if not sip.isdeleted(self):
            self.refresh()

    def set_note(self, what: str, check: PlotCheck, kept: str, quiet: bool = False) -> None:
        """Say what applying saved settings did: ``what`` ("Preset “X”", "Reopened"), then the settings
        not applied (``kept`` as they are) and notes. ``quiet``: nothing to say if all applied."""
        summary = check.summary(kept)
        if quiet and not summary:
            self._show_problems()
            return
        text = " · ".join(filter(None, (f"{what} applied" if not quiet else what, summary)))
        self._show(text, check.details() or text, amber=bool(check.problems))

    def _show(self, text: str, tip: str, amber: bool) -> None:
        self.note.setText(text)
        self.note.setToolTip(tip)
        self.note.setStyleSheet(f"color: {AMBER};" if amber else "")
        self.note.setVisible(bool(text))

    def save_to_applied(self) -> None:
        """Save to preset “<name>”: the preset applied takes these settings (asks first)."""
        if self.applied is None:
            return
        name = self.applied.name
        if not self.confirm(self, "Save to preset?", f"Replace the settings of preset “{name}” of {self.plot.name} "
                            "with these? Every plot of it gets them the next time it applies it.", "Save to preset"):
            return
        self._save_as(name, ask=False)

    def save(self) -> None:
        plot = self.plot
        name = self.ask_name(self, "Save preset", f"Save these settings of {plot.name} as:",
                             self.combo.currentText())
        if name:
            self._save_as(name)

    def _save_as(self, name: str, ask: bool = True) -> None:
        plot = self.plot
        presets = read_script_presets(self.ref)
        if ask and (name in presets.presets or name in presets.unreadable):
            if not self.confirm(self, "Replace preset?", f"A preset “{name}” of {plot.name} exists. Replace it?",
                                "Replace"):
                return
        preset = ScriptPreset(name, self.ref, plot.values(), plot.backend(), time.time())
        try:
            why = write_script_preset(preset)
        except ValueError as error:  # A value JSON can't hold (not a finite number).
            self._show(f"⚠ Preset “{name}” not saved: {error}", str(error), amber=True)
            return
        plot.preset_from = (name, preset.saved_at)
        self.combo.setCurrentText(name)
        self.set_applied(preset)
        self._show(f"Saved preset “{name}”{saved_note(why)}", f"Every plot of {self.ref.label()} lists it",
                   amber=bool(why))

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
        self.set_applied(preset)

    def delete(self) -> None:
        name = self.combo.currentText()
        if not name or not self.confirm(self, "Delete preset?", f"Delete the preset “{name}” of {self.plot.name}? "
                                        "Every plot of it loses it; plots keep their settings.", "Delete"):
            return
        why = delete_script_preset(self.ref, name)
        if self.applied is not None and self.applied.name == name:
            self.set_applied(None)  # Nothing to compare with any more.
        self._show(f"Deleted preset “{name}”{saved_note(why)}", "", amber=bool(why))


# Arrangement presets


class PresetFolder(QObject):
    """An arrangement preset's folder after it is applied (the tab has opened it as typing its path
    would): it loads as a deliberate selection (cache first; a large folder asks) once it is known
    to hold data (cached, in RAM, or listed with TXY files; a folder with none isn't loaded: there
    is nothing to load), and with the preset's Live, Live turns on once the tab shows its data, or
    finds it has no shots yet, under the normal rules (``FolderExplorer.start_live``), never
    forced: if it can't, it says why, once. A folder that can't be listed (unmounted, moved) is
    named once; its plots go on waiting. It gives up if the tab selects another folder or closes."""

    def __init__(self, explorer: FolderExplorer, folder: str, name: str, live: bool,
                 notice: Callable[[str], None], root_key: str = "") -> None:
        super().__init__(explorer)
        self.explorer, self.folder, self.name, self.live = explorer, folder, name, live
        self.root_key = root_key
        self._notice = notice
        self.done = False
        self.load_asked = False
        self._signals = [explorer.dataLoaded, explorer.loadStateChanged, explorer.liveChanged,
                         explorer.model.activityChanged]
        for signal in self._signals:
            signal.connect(self.check)
        self.check()

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
        node = explorer.model.nodes.get(self.folder)
        if node is not None and node.error:
            now = folder_now(explorer.model.cache, self.root_key)
            moved = f"; its data root is seen at another place now: {now}" if now and now != self.folder else ""
            self._notice(f"Preset “{self.name}”: {folder_name(self.folder)} can't be opened now "
                         f"({node.error.removesuffix(' — Retry')}): its plots wait for its data{moved}")
            self.finish()
            return
        listed = node is not None and node.report is not None
        if not self.load_asked:
            has_shots = node is not None and node.report is not None and node.txy_count > 0
            if self._shown() or explorer.model.cache.disk_cached(self.folder) or has_shots:
                self.load_asked = True
                explorer.load_to_ram_cache(self.folder, dwell=False, explicit=True)
                if self.done:
                    return  # (A load answered at once, and this ran again meanwhile.)
            elif listed:
                self.load_asked = True  # No TXY files: nothing to load (Live may start before the first shot).
            else:
                return  # Until the tab's listing answers.
        if self._busy():
            return
        if not self.live or explorer.live is not None:
            self.finish()  # Done; or Live on already (by the user, or before).
            return
        reason = explorer.live_unavailable(self.folder)
        if not reason and explorer.start_live():
            self._notice(f"Preset “{self.name}”: Live on for {folder_name(self.folder)}")
        else:
            why = explorer.load_error.removesuffix(" — Retry") if explorer.load_error else reason
            self._notice(f"Preset “{self.name}”: Live not started: {why or 'it could not start'}")
        self.finish()

    def _shown(self) -> bool:
        explorer = self.explorer
        return explorer.folder_opened_path == self.folder and explorer.folder_opened_data is not None

    def _busy(self) -> bool:
        """The folder's load (or its wait to start) is still going: its data may yet show."""
        explorer = self.explorer
        return (explorer.loading and explorer.load_path == self.folder) or explorer.load_waiting or explorer.settling

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
    apply one, delete one (asks first). Applying one with plots open asks first: Replace them, or
    Add the preset's plots beside them (numbered after them; the open plots stay where they are).

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
        self.replace_or_add: Callable[[Optional[QWidget], str, str], Optional[str]] = replace_or_add
        self.warn: Callable[[str, str], None] = self._warn
        self.applying: Optional[PresetFolder] = None
        self._menu: Optional[QMenu] = None
        store = preset_store()
        store.presetsChanged.connect(self._presets_changed)
        store.read_presets()  # At startup: the store's presets, for the menu and the plots' pages.

    @pyqtSlot()
    def _presets_changed(self) -> None:
        """The store answered (or presets changed) while the menu shows: list them again."""
        for conflict in take_conflicts(ARRANGEMENT):
            self.plots.notice(conflict)
        menu = self._menu
        if menu is not None and not sip.isdeleted(menu) and menu.isVisible():
            self.fill_menu(menu, read=False)

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

    def fill_menu(self, menu: QMenu, read: bool = True) -> None:
        """The Presets menu, as it shows: Save…, then each preset (applies it), then Delete ▸; and,
        when the store's presets aren't all known, why (they are read again as it opens)."""
        self._menu = menu
        store = preset_store()
        if read:
            store.read_presets()  # Another HeLab may have changed them; listed again when it answers.
        menu.clear()
        save = QAction("Save Folder and Plots as Preset…", menu)
        save.setToolTip("Save the current tab's folder, whether Live watches it, and its open plots with their "
                        "settings and places, under a name")
        save.triggered.connect(self.save)
        menu.addAction(save)
        names = arrangement_names()
        menu.addSeparator()
        note = store.presets_note()
        if note:
            shown = QAction(note, menu)
            shown.setEnabled(False)
            menu.addAction(shown)
        if not names:
            if store.presets_known():  # (Else the note says why none are listed yet.)
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
            why = write_arrangement(name, arrangement)
        except ValueError as error:
            self.warn("Preset not saved", f"“{name}” couldn't be saved: {error}")
            return None
        self.plots.notice(f"Saved preset “{name}”: {folder_name(folder)}, {len(mine):,} plot"
                          f"{'' if len(mine) == 1 else 's'}" + (", Live" if live else "") + saved_note(why))
        return arrangement

    def apply(self, name: str) -> List[AnalysisInstance]:
        """Apply preset ``name``: with plots open, asks whether they close (Replace) or stay (Add);
        its folder is selected and loaded in the current tab, its plots open in their places (with
        Add, in their tab groups only: the open plots aren't moved), waiting for its data, and Live
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
        how = "replace"
        if open_plots:
            count = len(open_plots)
            how = self.replace_or_add(
                self.parent_widget, "Apply preset?",
                f"“{name}” opens {folder_name(arrangement.folder)} with its {len(arrangement.plots):,} plot"
                f"{'' if len(arrangement.plots) == 1 else 's'}. Replace the {count:,} open plot"
                f"{'' if count == 1 else 's'}, or Add the preset's beside {'it' if count == 1 else 'them'}?") or ""
            if not how:
                return []
        if how == "replace":
            for instance in open_plots:
                instance.close()
        if self.applying is not None and not sip.isdeleted(self.applying):
            self.applying.finish()
        folder = arrangement.folder
        if FolderCache.key(explorer.selected_path_globally) != folder or explorer.view_path != folder:
            explorer.open_to_path(folder)  # As typing its path in the tab's path bar (it stops Live)
        elif explorer.live is not None and not arrangement.live:
            explorer.stop_live()  # Already there with Live on: the preset says off.
            self.plots.notice(f"Preset “{name}”: Live off for {folder_name(folder)}")
        opened, failed = open_arrangement(self.scripts, self.cache(), arrangement, folder=folder,
                                          layout=how == "replace")
        presets = ({plot.script: read_script_presets(plot.script) for plot in arrangement.plots if plot.preset}
                   if presets_known() else {})
        for instance, saved in opened:
            # Its values are the arrangement's own; the script preset they came from may have changed.
            note = preset_note(saved, presets.get(saved.script))
            check = instance.reopen_check
            if note and instance.presets is not None and check is not None:
                instance.presets.set_note(f"Preset “{name}”", dataclasses.replace(check, notes=(*check.notes, note)),
                                          "at the script's defaults", quiet=True)
        if arrangement.layout_error:
            self.plots.notice(f"Preset “{name}”: its plots are in their tab groups: {arrangement.layout_error}")
        missing = [f"{saved.script.label()} ({why})" for saved, why in failed]
        missing += [f"a plot ({why})" for why in arrangement.unreadable]
        if missing:
            self.plots.notice(f"Preset “{name}”: not opened: {'; '.join(missing)}")
        # Loaded as a deliberate selection, and Live once its data shows (``PresetFolder``).
        self.applying = PresetFolder(explorer, folder, name, arrangement.live, self.plots.notice,
                                     arrangement.root_key)
        return [instance for instance, _ in opened]

    def delete(self, name: str) -> bool:
        if not self.confirm(self.parent_widget, "Delete preset?", f"Delete the preset “{name}”? Open plots stay.",
                            "Delete"):
            return False
        why = delete_arrangement(name)
        self.plots.notice(f"Deleted preset “{name}”{saved_note(why)}")
        return True

