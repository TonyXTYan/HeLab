"""Settings → Cache › Presets…: every saved preset, in a window of its own (``PresetsInspector``).

Script presets by script, then arrangement presets. Selecting one shows its values, the script
version it was saved with, and whether it still fits the installed script (the same check
applying it makes, ``helab.analysis.presets.check_plot``: each value that wouldn't apply named).
Rename…, Duplicate… and Delete… (each asks first where something would be replaced or lost)
change the store's presets through the app's FolderCache, as the plots' Presets rows do. Values
are edited in a plot (apply the preset, change its settings, Save to preset), not here.

The installed scripts come from the main window's Scripts panel (``set_script_finder``); without
it (a Settings dialog of its own), presets are listed but not checked.
"""
from __future__ import annotations

import json
import time
import weakref
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple, Union

from PyQt6 import sip
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSplitter, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

from helab.analysis.follow import live_specs
from helab.analysis.parameters import ParameterSpec
from helab.analysis.presets import (Arrangement, PlotCheck, RecordError, SavedPlot, ScriptPreset, ScriptRef,
                                    check_plot, check_value, parse)
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.utils.colours import AMBER
from helab.utils.folder_cache import FolderCache
from helab.views.plots.arrangement import folder_name
from helab.views.plots.presets import ARRANGEMENT, SCRIPT, ask_name, confirm, preset_store

Found = Union[Tuple[ScriptMetadata, DatasetAnalysis], str]
ScriptFinder = Callable[[ScriptRef], Found]

_finder: Optional[Callable[[], Optional[ScriptFinder]]] = None


def set_script_finder(finder: ScriptFinder) -> None:
    """The installed scripts to check presets against (the main window's Scripts panel's
    ``find_script``; held weakly, so a closed window's isn't kept)."""
    global _finder
    _finder = weakref.WeakMethod(finder) if hasattr(finder, "__self__") else (lambda: finder)


def script_finder() -> Optional[ScriptFinder]:
    return _finder() if _finder is not None else None


@dataclass(frozen=True)
class Entry:
    """One saved preset: its key in the store and its record as saved."""
    kind: str
    scope: str
    name: str
    text: str


def check_saved(saved: Union[SavedPlot, ScriptPreset], finder: Optional[ScriptFinder]
                ) -> Tuple[Optional[PlotCheck], str, Sequence[ParameterSpec]]:
    """``saved`` against the installed script: (the check, "" ) or (None, why it can't be checked),
    and the script's parameters (to show values by their titles)."""
    if finder is None:
        return None, "the installed scripts aren't known here", ()
    found = finder(saved.script)
    if isinstance(found, str):
        return None, found, ()
    metadata, script = found
    action = saved.script.action
    try:
        specs = script.parameters(action)
        backends = script.backends(action)
        live = live_specs(script.live_policy(action)) if isinstance(saved, SavedPlot) else ()
    except Exception as error:
        return None, f"its script failed: {error}", ()
    return check_plot(saved, metadata.identity(), specs, backends, live), "", specs


def describe(saved: Union[SavedPlot, ScriptPreset], finder: Optional[ScriptFinder]) -> Tuple[List[str], str]:
    """Lines describing ``saved`` (its script, version, values, what doesn't fit), and its verdict
    ("✓ fits", "⚠ N settings don't fit", or why it can't be checked)."""
    check, why, specs = check_saved(saved, finder)
    ref = saved.script
    lines = [f"Script: {ref.label()} ({ref.analysis_id} › {ref.action}), saved with v{ref.version or '?'}"]
    titled = {spec.name: spec for spec in specs}
    for key, value in saved.values.items():
        spec = titled.get(key)
        fits = spec is not None and check_value(spec, value)[0] is not None
        lines.append(f"  {spec.text(value) if spec is not None and fits else f'{key} = {json.dumps(value)}'}")
    if saved.backend:
        lines.append(f"  Library: {saved.backend}")
    if check is None:
        lines.append(f"Not checked: {why}")
        return lines, f"not checked: {why}"
    lines.extend(f"  ⚠ {problem.text()}" for problem in check.problems)
    lines.extend(f"  {note}" for note in check.notes)
    count = len(check.problems)
    verdict = (f"⚠ {count:,} setting{'' if count == 1 else 's'} wouldn't apply" if count
               else "✓ fits the installed script")
    return lines, verdict + (f" · {check.notes[0]}" if check.notes else "")


def presets_summary(cache: FolderCache) -> str:
    """Settings → Cache's line: how many presets, and what may be missing."""
    scripts, arrangements = len(cache.preset_records(SCRIPT)), len(cache.preset_records(ARRANGEMENT))
    text = (f"{scripts:,} script preset{'' if scripts == 1 else 's'}, {arrangements:,} arrangement"
            f"{'' if arrangements == 1 else 's'}")
    note = cache.presets_note()
    return f"{text} · {note}" if note else text


def show_summary(label: QLabel, cache: Optional[FolderCache]) -> FolderCache:
    """Keep Settings → Cache's Presets line (``label``) current; the FolderCache holding them."""
    store = cache if cache is not None else preset_store()

    def shown() -> None:
        if not sip.isdeleted(label):
            label.setText(presets_summary(store))
    shown()
    store.presetsChanged.connect(shown)
    return store


def open_inspector(cache: FolderCache, parent: QWidget, current: Optional[QWidget]) -> PresetsInspector:
    """Presets…: the presets window, ``current`` if it is still open (one at a time)."""
    window = current if isinstance(current, PresetsInspector) and not sip.isdeleted(current) else None
    if window is None:
        window = PresetsInspector(cache, parent)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    window.show()
    window.raise_()
    return window


class PresetsInspector(QDialog):
    """The saved presets: by script, then arrangements; the selected one's values and whether it
    fits the installed script; Rename…, Duplicate…, Delete…."""

    def __init__(self, cache: Optional[FolderCache] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.cache = cache if cache is not None else preset_store()
        self.ask_name: Callable[[Optional[QWidget], str, str, str], Optional[str]] = ask_name
        self.confirm: Callable[[Optional[QWidget], str, str, str], bool] = confirm
        self.setWindowTitle("Presets")
        self.resize(760, 480)
        layout = QVBoxLayout(self)
        layout.setSpacing(2)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Saved with", "Installed script", "Saved"])
        self.tree.setColumnWidth(0, 220)
        self.tree.setColumnWidth(1, 150)
        self.tree.setColumnWidth(2, 220)
        self.tree.currentItemChanged.connect(self._selected)
        splitter.addWidget(self.tree)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        splitter.addWidget(self.details)
        splitter.setSizes([300, 160])
        layout.addWidget(splitter, 1)
        buttons = QHBoxLayout()
        self.rename_button = QPushButton("Rename…")
        self.rename_button.clicked.connect(self.rename)
        self.duplicate_button = QPushButton("Duplicate…")
        self.duplicate_button.clicked.connect(self.duplicate)
        self.delete_button = QPushButton("Delete…")
        self.delete_button.clicked.connect(self.delete)
        for button in (self.rename_button, self.duplicate_button, self.delete_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.entries: dict[int, Entry] = {}
        self._items: dict[int, QTreeWidgetItem] = {}
        self.cache.presetsChanged.connect(self.refresh)
        self.refresh()
        self.cache.read_presets()  # Another HeLab may have changed them; listed again when it answers.

    # Listing

    @pyqtSlot()
    def refresh(self) -> None:
        if sip.isdeleted(self):
            return
        chosen = self.selected()
        self.note.setText(self.cache.presets_note())
        self.note.setStyleSheet(f"color: {AMBER};" if self.cache.presets_note().startswith("⚠") else "")
        self.note.setVisible(bool(self.note.text()))
        self.tree.clear()
        self.entries.clear()
        self._items.clear()
        finder = script_finder()
        scripts = QTreeWidgetItem(self.tree, ["Script presets"])
        by_scope: dict[str, List[Entry]] = {}
        for (scope, name), text in self.cache.preset_records(SCRIPT).items():
            by_scope.setdefault(scope, []).append(Entry(SCRIPT, scope, name, text))
        for scope, entries in sorted(by_scope.items()):
            labels = []
            for entry in entries:
                try:
                    labels.append(ScriptPreset.from_json(entry.name, json.loads(entry.text)).script.label())
                except ValueError:
                    pass
            group = QTreeWidgetItem(scripts, [labels[0] if labels else scope.replace("/", " › ")])
            for entry in sorted(entries, key=lambda entry: entry.name.casefold()):
                self._add(group, entry, finder)
        arrangements = QTreeWidgetItem(self.tree, ["Arrangement presets"])
        for (scope, name), text in sorted(self.cache.preset_records(ARRANGEMENT).items(),
                                          key=lambda item: item[0][1].casefold()):
            self._add(arrangements, Entry(ARRANGEMENT, scope, name, text), finder)
        for top in (scripts, arrangements):
            if not top.childCount():
                QTreeWidgetItem(top, ["(none saved)"]).setDisabled(True)
        self.tree.expandAll()
        if chosen is not None:
            for item_id, entry in self.entries.items():
                if (entry.kind, entry.scope, entry.name) == (chosen.kind, chosen.scope, chosen.name):
                    self.tree.setCurrentItem(self._items[item_id])
        self._selected()

    def _add(self, parent: QTreeWidgetItem, entry: Entry, finder: Optional[ScriptFinder]) -> None:
        row = self.cache.presets.get((entry.kind, entry.scope, entry.name)) or {}
        saved_at = float(row.get("set_at") or 0.0)
        unsaved = self.cache.preset_unsaved(entry.kind, entry.scope, entry.name)
        lines, verdict, saved_with = self._describe(entry, finder)
        item = QTreeWidgetItem(parent, [entry.name + (" (RAM only)" if unsaved else ""), saved_with, verdict,
                                        time.strftime("%Y-%m-%d %H:%M", time.localtime(saved_at)) if saved_at else ""])
        item.setToolTip(0, f"Not saved yet: {unsaved}" if unsaved else entry.name)
        item.setToolTip(2, verdict)
        if verdict.startswith("⚠"):
            item.setForeground(2, QColor(AMBER))
        item.setData(0, Qt.ItemDataRole.UserRole, "\n".join(lines))
        self.entries[id(item)] = entry
        self._items[id(item)] = item

    def _describe(self, entry: Entry, finder: Optional[ScriptFinder]) -> Tuple[List[str], str, str]:
        """Its details, verdict and "saved with" text."""
        if entry.kind == SCRIPT:
            try:
                preset = ScriptPreset.from_json(entry.name, json.loads(entry.text))
            except ValueError as error:
                why = str(error) if isinstance(error, RecordError) else f"not valid JSON ({error})"
                return [f"Preset “{entry.name}” can't be read: {why}"], f"⚠ can't be read: {why}", ""
            lines, verdict = describe(preset, finder)
            return [f"Preset “{entry.name}”", *lines], verdict, f"v{preset.script.version or '?'}"
        try:
            arrangement: Arrangement = parse(entry.text)
        except RecordError as error:
            return [f"Preset “{entry.name}” can't be read: {error}"], f"⚠ can't be read: {error}", ""
        count = len(arrangement.plots)
        lines = [f"Preset “{entry.name}”: {arrangement.folder}"
                 + (f" ({arrangement.root_key})" if arrangement.root_key else "")
                 + (", Live on" if arrangement.live else ""),
                 f"{count:,} plot{'' if count == 1 else 's'}:"]
        problems = 0
        unchecked = ""
        for plot in arrangement.plots:
            plot_lines, verdict = describe(plot, finder)
            lines.append(f"• {plot.title or plot.script.label()}: {verdict}")
            lines.extend(f"  {line}" for line in plot_lines)
            if verdict.startswith("⚠"):
                problems += 1
            elif verdict.startswith("not checked") and not unchecked:
                unchecked = verdict
        lines.extend(f"⚠ a plot can't be read: {why}" for why in arrangement.unreadable)
        problems += len(arrangement.unreadable)
        verdict = (f"⚠ {problems:,} plot{'' if problems == 1 else 's'} wouldn't open as saved" if problems
                   else unchecked or "✓ fits the installed scripts")
        return lines, verdict, f"{folder_name(arrangement.folder)}, {count:,} plot{'' if count == 1 else 's'}"

    def selected(self) -> Optional[Entry]:
        item = self.tree.currentItem()
        return self.entries.get(id(item)) if item is not None else None

    def _selected(self, *_: object) -> None:
        entry = self.selected()
        item = self.tree.currentItem()
        self.details.setPlainText(str(item.data(0, Qt.ItemDataRole.UserRole) or "") if entry and item else "")
        for button in (self.rename_button, self.duplicate_button, self.delete_button):
            button.setEnabled(entry is not None)

    # Actions

    def _taken(self, entry: Entry, name: str) -> bool:
        """Saving ``entry``'s record as ``name`` would replace another preset, and the user said no."""
        kind_records = self.cache.preset_records(entry.kind, entry.scope)
        return (entry.scope, name) in kind_records and not self.confirm(
            self, "Replace preset?", f"A preset “{name}” exists. Replace it?", "Replace")

    def rename(self) -> None:
        entry = self.selected()
        if entry is None:
            return
        name = self.ask_name(self, "Rename preset", f"Rename “{entry.name}” to:", entry.name)
        if not name or name == entry.name or self._taken(entry, name):
            return
        self.cache.set_presets([(entry.kind, entry.scope, entry.name, None),
                                (entry.kind, entry.scope, name, entry.text)])

    def duplicate(self) -> None:
        entry = self.selected()
        if entry is None:
            return
        name = self.ask_name(self, "Duplicate preset", f"Save a copy of “{entry.name}” as:", f"{entry.name} copy")
        if not name or name == entry.name or self._taken(entry, name):
            return
        self.cache.set_presets([(entry.kind, entry.scope, name, entry.text)])

    def delete(self) -> None:
        entry = self.selected()
        if entry is None or not self.confirm(
                self, "Delete preset?", f"Delete the preset “{entry.name}”? Open plots keep their settings.",
                "Delete"):
            return
        self.cache.set_presets([(entry.kind, entry.scope, entry.name, None)])
