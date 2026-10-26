"""Settings → Cache: what the disk cache holds, clearing and purging it, and both budgets.

The GUI never opens the store: the numbers come from a ``cache_admin inventory`` helper job
(``FolderCache.cache_admin``), and every Clear or Remove is another such job. Memory numbers
come from ``FolderCache``. See roadmaps/cache-storage-and-settings.md.
"""
from __future__ import annotations

from datetime import datetime
from fractions import Fraction
import re
import time
from typing import Any, Callable

from PyQt6.QtCore import QSettings, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QValidator
from PyQt6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from helab.analysis.budget_core import RELEASE_SHARE
from helab.utils.cache_store import KINDS, purge_estimate, results_purge_estimate, trim_estimate
from helab.utils.constants import (
    DISK_BUDGET_SETTING, LIVE_AUTOSAVE_SETTING, PLOT_AUTO_RELOAD_SETTING, MAX_LIVE_AUTOSAVE, MIN_DISK_BUDGET, RAM_BUDGET_SETTING, RAM_STEPS,
    read_disk_budget, cache_dir_refused, read_live_autosave, read_plot_auto_reload, read_ram_budget_steps, ram_step_bytes, ram_step_range,
    total_ram,
)
from helab.utils import folder_cache
from helab.utils.folder_cache import FolderCache
from helab.utils.number_format import byte_size
from helab.utils.settings_defaults import RESULT_REUSE_SETTING, read_setting
from helab.utils.time_format import relative_age

GB = 10**9  # SI, as every size HeLab shows: budgets typed and shown in GB (Tony, 2026-10-26)
DAY = 86400.0
DEFAULT_PURGE_DAYS = 90
# The rows of the disk cache, by record kind: label and button.
KIND_ROWS = {"datasets": ("Cached data", "Clear…"), "summaries": ("Folder summaries", "Clear…"),
             "histories": ("Scan failures", "Forget…"), "subtrees": ("Subfolder status", "Clear…"),
             "listings": ("Folder listings", "Clear…")}
# What a Clear of each kind loses and keeps, for its confirmation.
CLEAR_TEXT = {
    "datasets": "Loaded data stays open; the next load of each folder reads its TXY files again.",
    "summaries": "Folders show their counts and status again after their next check.",
    "histories": "Automatic checks will try these folders again.",
    "subtrees": "Each folder's status from its subfolders is derived again when it is listed.",
    "listings": "Browsing offline can't show these folders' subfolders until they are listed again.",
}
# Saved analysis results (result caching R2): apart from the kinds above (Clear all keeps them).
RESULTS_LABEL = "Cached analysis"
RESULTS_TEXT = ("Plots shown now stay as they are; the next run of each plot computes again. Cached data, "
                "folder records and exported files are kept.")


def read_result_reuse(settings: QSettings) -> bool:
    return bool(read_setting(settings, RESULT_REUSE_SETTING, typed=True))


def plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


class RamBudgetSpinBox(QSpinBox):
    """The RAM budget in steps of 1/128 of RAM, shown as e.g. "16.0 GB (1/8 of 128 GB)".
    A typed size in GB snaps to the nearest step."""

    def __init__(self, total: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.total = total
        self.step = ram_step_bytes(total)
        self.setRange(*ram_step_range(total))

    def textFromValue(self, v: int) -> str:
        share = Fraction(v, RAM_STEPS)
        return f"{byte_size(v * self.step)} ({share.numerator}/{share.denominator} of {byte_size(self.total)})"

    def valueFromText(self, text: str | None) -> int:
        match = re.match(r"\s*(\d*\.?\d+)", text or "")
        if match is None:
            return self.value()
        return max(self.minimum(), min(self.maximum(), round(float(match.group(1)) * GB / self.step)))

    def validate(self, input: str | None, pos: int) -> tuple[QValidator.State, str, int]:
        text = input or ""
        state = (QValidator.State.Acceptable if re.match(r"\s*\d*\.?\d+", text)
                 else QValidator.State.Intermediate)
        return state, text, pos


class CacheTab(QWidget):
    """Rows of the disk cache by kind, purges by age, and the disk and RAM budgets.

    Buttons are disabled while a job runs and until the inventory arrives. Every Clear
    or Remove asks first, saying what is lost and what stays (``confirm``, replaceable
    in tests). The budgets are saved with the Settings dialog (``save``).
    """

    # The store recorded a changed disk budget (True), or couldn't (False): Settings saves only then.
    budgetApplied = pyqtSignal(bool)

    def __init__(self, cache: FolderCache | None, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cache = cache
        self.settings = settings
        self.enabled = bool(cache is not None and folder_cache.store_options())
        self.inventory: dict[str, Any] | None = None
        self._inventory_owner = ""
        self._job = ""
        self._job_label = ""
        self._budget_job = ""
        # The disk budget the store has recorded (``apply_budget``): the only one Save writes.
        self._acknowledged: int | None = None
        self._applying_budget = 0
        # The budget job found more cached than the lowered budget allows (its usage).
        self._too_full: int | None = None
        self.message = ""
        self.confirm: Callable[[str, str, str], bool] = self._confirm

        layout = QVBoxLayout(self)
        layout.setSpacing(2)
        layout.addWidget(self._heading("Disk cache"))
        location = QHBoxLayout()
        self.location_label = QLabel()
        self.location_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        location.addWidget(self.location_label, 1)
        self.open_button = QPushButton("Open")
        self.open_button.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(folder_cache.store_options().get("directory", "")))))
        location.addWidget(self.open_button)
        self.show_location(refresh=False)
        layout.addLayout(location)
        if cache_dir_refused():
            refused = QLabel(cache_dir_refused())
            refused.setWordWrap(True)
            layout.addWidget(refused)

        usage = QHBoxLayout()
        self.usage_label = QLabel("Checking…")
        usage.addWidget(self.usage_label)
        self.usage_bar = QProgressBar()
        self.usage_bar.setRange(0, 1000)
        self.usage_bar.setTextVisible(False)
        self.usage_bar.setMaximumHeight(self.usage_label.fontMetrics().height())
        usage.addWidget(self.usage_bar, 1)
        usage.addWidget(QLabel("Budget"))
        self.disk_budget = QDoubleSpinBox()
        self.disk_budget.setRange(MIN_DISK_BUDGET / GB, 1 << 20)
        self.disk_budget.setDecimals(1)
        self.disk_budget.setSingleStep(0.5)
        self.disk_budget.setSuffix(" GB")
        self.disk_budget.setValue(read_disk_budget(settings) / GB)
        self.disk_budget.setToolTip(
            "Counts live data: cached datasets, cached analysis and the records database. Removed files waiting out their "
            "10-minute grace period don't count. Nothing is removed to make room without asking. At 80%, "
            "automatic loads of folders without cached data pause.")
        usage.addWidget(self.disk_budget)
        layout.addLayout(usage)

        grid = QGridLayout()
        grid.setVerticalSpacing(0)
        grid.setColumnStretch(1, 1)
        self.kind_labels: dict[str, QLabel] = {}
        self.kind_buttons: dict[str, QPushButton] = {}
        for row, (kind, (label, button_text)) in enumerate(KIND_ROWS.items()):
            grid.addWidget(QLabel(label), row, 0)
            self.kind_labels[kind] = QLabel("Checking…")
            grid.addWidget(self.kind_labels[kind], row, 1)
            button = QPushButton(button_text)
            button.clicked.connect(lambda checked=False, k=kind: self.clear([k]))
            self.kind_buttons[kind] = button
            grid.addWidget(button, row, 2)
        self.kind_labels["listings"].setToolTip(
            "Each listed folder's subfolder names and counts (below data roots), for browsing cached folders "
            "when their drive or share isn't there.")
        # Saved analysis results (R2): their own Clear, not part of Clear all.
        row = len(KIND_ROWS)
        grid.addWidget(QLabel(RESULTS_LABEL), row, 0)
        self.results_label = QLabel("Checking…")
        self.results_label.setToolTip("Results of costly plots (Correlations, Release time…), reused when a plot "
                                      "runs again with the same data, script and settings. They count toward the "
                                      "budget; Clear all keeps them.")
        grid.addWidget(self.results_label, row, 1)
        self.results_button = QPushButton("Clear…")
        self.results_button.clicked.connect(self.clear_results)
        grid.addWidget(self.results_button, row, 2)
        layout.addLayout(grid)
        self.result_reuse = QCheckBox("Reuse saved analysis results")
        self.result_reuse.setChecked(read_result_reuse(settings))
        self.result_reuse.setToolTip(
            "On: a costly plot (Correlations, Release time) shows its result saved for the same data, script and "
            "settings at once instead of computing it again, and saves new ones; its source line says so. Off: "
            "plots compute every run and save nothing (saved results stay until cleared).")
        layout.addWidget(self.result_reuse)

        footer = QHBoxLayout()
        self.checked_label = QLabel("Checking…")
        footer.addWidget(self.checked_label, 1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        footer.addWidget(self.refresh_button)
        self.clear_all_button = QPushButton("Clear all…")
        self.clear_all_button.clicked.connect(lambda: self.clear(list(KINDS)))
        footer.addWidget(self.clear_all_button)
        layout.addLayout(footer)

        # The user's choices (S10): not part of Clear all, never removed to make room.
        prefs = QHBoxLayout()
        prefs.addWidget(QLabel("Folder preferences"))
        self.prefs_label = QLabel("Checking…")
        self.prefs_label.setToolTip("Folders you chose not to cache or not to auto-load (right-click a folder). "
                                    "Clear all and purges keep them.")
        prefs.addWidget(self.prefs_label, 1)
        self.prefs_button = QPushButton("Clear…")
        self.prefs_button.clicked.connect(self.clear_prefs)
        prefs.addWidget(self.prefs_button)
        layout.addLayout(prefs)

        # Presets (helab/views/PresetsInspector.py): the user's too, kept by Clear all and purges.
        presets = QHBoxLayout()
        presets.addWidget(QLabel("Presets"))
        self.presets_label = QLabel()
        presets.addWidget(self.presets_label, 1)
        self.presets_button = QPushButton("Presets…")
        self.presets_button.setToolTip("The saved presets of plots and of folders with their plots: their values, "
                                       "whether they fit the installed scripts; rename, duplicate or delete one")
        self.presets_button.clicked.connect(self.show_presets)
        presets.addWidget(self.presets_button)
        layout.addLayout(presets)
        from helab.views.PresetsInspector import show_summary
        self.presets_store = show_summary(self.presets_label, cache)
        self.presets_window: QWidget | None = None

        # Live (roadmaps/live-monitoring.md): new shots wait in RAM, then the folder is saved.
        live = QHBoxLayout()
        live.addWidget(QLabel("Live: save to the disk cache every"))
        self.live_autosave = QSpinBox()
        self.live_autosave.setRange(1, MAX_LIVE_AUTOSAVE)
        self.live_autosave.setSuffix(" new shots")
        self.live_autosave.setValue(read_live_autosave(settings))
        self.live_autosave.setToolTip(
            "While Live watches a folder, new shots stay in RAM; once this many wait, the folder's cached data "
            "is rewritten in the background (one save at a time), and again when Live stops. A crash or Quit "
            "now loses at most these: the next check reads them from the folder again.")
        live.addWidget(self.live_autosave)
        live.addStretch(1)
        layout.addLayout(live)

        layout.addWidget(self._heading("Remove old entries"))
        purges = QGridLayout()
        purges.setVerticalSpacing(0)
        purges.setColumnStretch(2, 1)
        self.dataset_days = self._days()
        self.dataset_estimate = QLabel("")
        self.purge_datasets_button = QPushButton("Remove…")
        self.purge_datasets_button.clicked.connect(self.purge_datasets)
        self.record_days = self._days()
        self.record_estimate = QLabel("")
        self.purge_records_button = QPushButton("Remove…")
        self.purge_records_button.clicked.connect(self.purge_records)
        self.result_days = self._days()
        self.result_estimate = QLabel("")
        self.purge_results_button = QPushButton("Remove…")
        self.purge_results_button.clicked.connect(self.purge_results)
        for row, (text, days, estimate, button) in enumerate((
                ("Cached data not used in the last", self.dataset_days, self.dataset_estimate,
                 self.purge_datasets_button),
                ("Folder records not checked in the last", self.record_days, self.record_estimate,
                 self.purge_records_button),
                ("Cached analysis not shown in the last", self.result_days, self.result_estimate,
                 self.purge_results_button))):
            purges.addWidget(QLabel(text), row, 0)
            purges.addWidget(days, row, 1)
            purges.addWidget(estimate, row, 2)
            purges.addWidget(button, row, 3)
        layout.addLayout(purges)
        self.include_failures = QCheckBox("Include scan failures (automatic checks will try those folders again)")
        self.include_failures.toggled.connect(self._show_estimates)
        layout.addWidget(self.include_failures)

        layout.addWidget(self._heading("Memory"))
        memory = QHBoxLayout()
        memory.addWidget(QLabel("RAM budget"))
        self.ram_budget = RamBudgetSpinBox(total_ram())
        self.ram_budget.setValue(read_ram_budget_steps(settings, self.ram_budget.total))
        self.ram_budget.setToolTip(
            "Loaded folders not shown in a tab are dropped from RAM, least recently used first, until the rest "
            "fit. Plots count too: from 50 % the status bar says so, at 75 % a window lists the biggest plots and "
            f"folders, and above {RELEASE_SHARE:.0%} plots not viewed lately are released (each keeps a picture). "
            "Folders shown in tabs and the shown, running or Live plots are never dropped, so HeLab can use "
            "more than this.")
        memory.addWidget(self.ram_budget)
        self.memory_label = QLabel("")
        memory.addWidget(self.memory_label, 1)
        layout.addLayout(memory)
        self.plot_auto_reload = QCheckBox("Reload a released plot when it is shown again")
        self.plot_auto_reload.setChecked(read_plot_auto_reload(settings))
        self.plot_auto_reload.setToolTip(
            "A plot released to free RAM keeps a picture of itself. On: showing it again (its tab, its window or "
            "its settings) draws it again from RAM or the disk cache, never from its folder. Off: only its "
            "Reload button does.")
        layout.addWidget(self.plot_auto_reload)
        layout.addStretch(1)

        if cache is not None:
            cache.cacheAdminResult.connect(self._on_result)
            cache.cacheAdminDone.connect(self._on_done)
        self.show_memory()
        self._update()
        self.refresh()

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        return label

    def _days(self) -> QSpinBox:
        days = QSpinBox()
        days.setRange(1, 3650)
        days.setValue(DEFAULT_PURGE_DAYS)
        days.setSuffix(" days")
        days.valueChanged.connect(self._show_estimates)
        return days

    def show_location(self, *, refresh: bool = True) -> None:
        """Where the disk cache is now (it can move while Settings is open)."""
        root = str(folder_cache.store_options().get("directory", ""))
        self.location_label.setText(root or "Off for this session")
        self.location_label.setToolTip("\n".join(filter(None, (
            root, cache_dir_refused(), "Move it with Change… on the General tab."))))
        self.open_button.setEnabled(bool(root))
        if refresh:
            self.refresh()

    def detach(self) -> None:
        """Stop listening to the cache (the dialog is closing)."""
        if self.cache is not None:
            self.cache.cacheAdminResult.disconnect(self._on_result)
            self.cache.cacheAdminDone.disconnect(self._on_done)
            self.cache = None

    def _confirm(self, title: str, text: str, verb: str) -> bool:
        box = QMessageBox(QMessageBox.Icon.Warning, title, text, parent=self)
        accept = box.addButton(verb, QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return box.clickedButton() is accept

    @property
    def busy(self) -> bool:
        return bool(self._job or self._budget_job)

    @property
    def applying(self) -> bool:
        """A changed disk budget is on its way to the store; Settings hasn't saved it yet."""
        return bool(self._budget_job)

    def refresh(self) -> None:
        """Ask a helper for the inventory; the tab shows Checking… until it arrives."""
        if self.cache is None or not self.enabled or self._inventory_owner:
            return
        self._inventory_owner = self.cache.cache_admin("inventory")
        if not self._inventory_owner:
            self.message = "Disk cache queue full — Refresh to try again"
        self._update()

    def _run(self, label: str, action: str, **params: Any) -> None:
        if self.cache is None:
            return
        self._job = self.cache.cache_admin(action, **params)
        self._job_label = label
        self.message = "" if self._job else "Disk cache queue full — try again"
        self._update()

    def _on_result(self, action: str, event: dict[str, Any]) -> None:
        if (action == "budget" and self._budget_job and event.get("kind") == "admin_result"
                and event.get("recorded") is False):
            self._too_full = int(event.get("usage") or 0)  # The data cached by now doesn't fit.
        if action == "inventory" and event.get("kind") == "inventory":
            self.inventory = event["inventory"]
            self._update()

    def _on_done(self, owner: str, action: str, message: str) -> None:
        if owner == self._inventory_owner:
            self._inventory_owner = ""
            if message:
                self.message = f"Could not read the disk cache: {message}"
        elif owner == self._budget_job:
            self._budget_job = ""
            too_full, self._too_full = self._too_full, None
            if not message and too_full is not None:
                # More was cached since the tab looked: it needs a trim, so ask now.
                self.message = ""
                if self._ask_trim(self._applying_budget, None, too_full):
                    self._send_budget("trim", self._applying_budget)
                    if self._budget_job:
                        return
                else:
                    self.message = "Budget not lowered — nothing saved"
                self.budgetApplied.emit(False)
            elif message:
                # It may have been recorded before failing: the budget in effect is set again.
                if self.cache is not None:
                    self.cache.restore_budget()
                self.message = f"Changing the disk budget failed: {message} — nothing saved"
                self.budgetApplied.emit(False)
            else:
                self._acknowledged = self._applying_budget
                self.message = ""
                self.budgetApplied.emit(True)
            self.refresh()
        elif owner == self._job:
            self._job = ""
            self.message = f"{self._job_label} failed: {message}" if message else ""
            self.refresh()  # Show what is left.
        else:
            return
        self._update()

    def show_presets(self) -> None:
        """Presets…: the presets window (one at a time)."""
        from helab.views.PresetsInspector import open_inspector
        self.presets_window = open_inspector(self.presets_store, self, self.presets_window)

    def clear_prefs(self) -> None:
        inventory = self.inventory
        if inventory is None or self.busy:
            return
        prefs = inventory.get("prefs") or {}
        if not self.confirm("Clear folder preferences?",
                            f"Forgets your choices: {plural(int(prefs.get('no_cache', 0)), 'folder')} not cached and "
                            f"{plural(int(prefs.get('no_auto_load', 0)), 'folder')} not auto-loaded. Those folders "
                            "are cached and auto-loaded again. Cached data is kept.", "Clear"):
            return
        self._run("Clear folder preferences", "clear_prefs")

    def clear(self, kinds: list[str]) -> None:
        inventory = self.inventory
        if inventory is None or self.busy:
            return
        if set(kinds) == set(KINDS):
            title = "Clear the disk cache?"
            text = (f"Removes everything in the disk cache: cached data for "
                    f"{plural(inventory['datasets']['count'], 'folder')} ({byte_size(inventory['datasets']['bytes'])}),"
                    " folder summaries, scan failures, subfolder status and folder listings.\n\n"
                    "Loaded data stays open. Automatic checks will try failed folders again. Cached analysis "
                    "stays (its own Clear).")
            verb, label = "Clear all", "Clear all"
        else:
            kind = kinds[0]
            name = KIND_ROWS[kind][0]
            count = (inventory["histories"]["blocked"] if kind == "histories"
                     else (inventory.get(kind) or {"count": 0})["count"])
            size = f" ({byte_size(inventory['datasets']['bytes'])})" if kind == "datasets" else ""
            verb = "Forget" if kind == "histories" else "Clear"
            title = f"{verb} {name.lower()}?"
            text = f"{verb}s {name.lower()} for {plural(count, 'folder')}{size}.\n\n{CLEAR_TEXT[kind]}"
            label = f"{verb} {name.lower()}"
        if self.confirm(title, text, verb):
            self._run(label, "clear", kinds=list(kinds))

    def clear_results(self) -> None:
        """Clear cached analysis: every saved result, nothing else (asks first)."""
        inventory = self.inventory
        if inventory is None or self.busy:
            return
        results = inventory.get("results") or {"count": 0, "bytes": 0}
        if self.confirm("Clear cached analysis?",
                        f"Removes {plural(int(results['count']), 'saved result')} ({byte_size(int(results['bytes']))})"
                        f".\n\n{RESULTS_TEXT}", "Clear"):
            self._run("Clear cached analysis", "clear_results")

    def purge_results(self) -> None:
        if self.inventory is None or self.busy:
            return
        days = self.result_days.value()
        cutoff = time.time() - days * DAY
        estimate = results_purge_estimate(self.inventory, cutoff)
        if self.confirm("Remove old cached analysis?",
                        f"Removes {plural(estimate['results'], 'saved result')} ({byte_size(estimate['bytes'])}) "
                        f"not shown in the last {plural(days, 'day')}.\n\n{RESULTS_TEXT}", "Remove"):
            self._run("Remove old cached analysis", "purge", what="results", cutoff=cutoff)

    def purge_datasets(self) -> None:
        if self.inventory is None or self.busy:
            return
        days = self.dataset_days.value()
        cutoff = time.time() - days * DAY
        estimate = purge_estimate(self.inventory, cutoff, datasets=True)
        if self.confirm("Remove old cached data?",
                        f"Removes cached data for {plural(estimate['datasets'], 'folder')} "
                        f"({byte_size(estimate['bytes'])}) not used in the last {plural(days, 'day')}.\n\n"
                        f"{CLEAR_TEXT['datasets']} TXY files are never touched.", "Remove"):
            self._run("Remove old cached data", "purge", what="datasets", cutoff=cutoff)

    def purge_records(self) -> None:
        if self.inventory is None or self.busy:
            return
        days = self.record_days.value()
        cutoff = time.time() - days * DAY
        failures = self.include_failures.isChecked()
        estimate = purge_estimate(self.inventory, cutoff, datasets=False, include_failures=failures)
        stays = ("Automatic checks will try folders whose scan failed again." if failures else
                 "Scan failures are kept, so automatic checks still skip those folders.")
        if self.confirm("Remove old folder records?",
                        f"Removes {plural(sum(estimate.values()), 'folder record')} not checked in the last "
                        f"{plural(days, 'day')}: summaries, subfolder status, listings and scan histories.\n\n"
                        f"Cached data stays. {stays}", "Remove"):
            self._run("Remove old folder records", "purge", what="records", cutoff=cutoff,
                      include_failures=failures)

    def show_memory(self) -> None:
        if self.cache is None:
            self.memory_label.setText("")
            return
        count, total, shown = self.cache.memory_usage()
        plots = self.cache.plot_bytes()
        self.memory_label.setText(f"In use: {plural(count, 'folder')} · {byte_size(total)} "
                                  f"({byte_size(shown)} shown in tabs)"
                                  + (f" · plots {byte_size(plots)} more" if plots else ""))

    def _show_estimates(self) -> None:
        inventory = self.inventory
        if inventory is None:
            for label in (self.dataset_estimate, self.record_estimate, self.result_estimate):
                label.setText("")
            self.purge_datasets_button.setEnabled(False)
            self.purge_records_button.setEnabled(False)
            self.purge_results_button.setEnabled(False)
            return
        now = time.time()
        datasets = purge_estimate(inventory, now - self.dataset_days.value() * DAY, datasets=True)
        self.dataset_estimate.setText(f"— frees ~{byte_size(datasets['bytes'])} "
                                      f"({plural(datasets['datasets'], 'folder')})")
        records = purge_estimate(inventory, now - self.record_days.value() * DAY, datasets=False,
                                 include_failures=self.include_failures.isChecked())
        self.record_estimate.setText(f"— {plural(sum(records.values()), 'record')}")
        self.record_estimate.setToolTip(f"{plural(records['summaries'], 'folder summary')} · "
                                        f"{plural(records['subtrees'], 'subfolder status')} · "
                                        f"{plural(records['listings'], 'folder listing')} · "
                                        f"{plural(records['histories'], 'scan history')}")
        results = results_purge_estimate(inventory, now - self.result_days.value() * DAY)
        self.result_estimate.setText(f"— frees ~{byte_size(results['bytes'])} "
                                     f"({plural(results['results'], 'result')})")
        writable = not inventory.get("read_only") and not self.busy
        self.purge_datasets_button.setEnabled(writable and datasets["datasets"] > 0)
        self.purge_records_button.setEnabled(writable and sum(records.values()) > 0)
        self.purge_results_button.setEnabled(writable and results["results"] > 0)

    def _update(self) -> None:
        inventory = self.inventory
        writable = inventory is not None and not inventory.get("read_only") and not self.busy
        for button in (*self.kind_buttons.values(), self.clear_all_button):
            button.setEnabled(writable)
        self.prefs_button.setEnabled(False)
        self.results_button.setEnabled(False)
        self.refresh_button.setEnabled(self.enabled and not self.busy and not self._inventory_owner)
        self.disk_budget.setEnabled(not self.applying)
        status = ("Off for this session" if not folder_cache.store_options() else
                  "Changing the disk budget…" if self._budget_job else f"{self._job_label}…" if self.busy else "Checking…" if self._inventory_owner and inventory is None
                  else "")
        if inventory is None:
            for label in (*self.kind_labels.values(), self.prefs_label, self.results_label):
                label.setText(status or "Not checked")
            self.usage_label.setText(status or "Not checked")
            self.checked_label.setText(self.message or status)
            self._show_estimates()
            return
        budget = int(folder_cache.store_options().get("budget") or read_disk_budget(self.settings))
        usage = int(inventory["usage"])
        extras = []
        if inventory["retired"]["bytes"]:
            extras.append(f"freeing {byte_size(inventory['retired']['bytes'])}")
        if inventory["pending"]:
            extras.append(f"{plural(len(inventory['pending']), 'save')} waiting for your answer")
        if inventory.get("read_only"):
            extras.append("read only: written by a newer HeLab")
        self.usage_label.setText(" · ".join([f"{byte_size(usage)} of {byte_size(budget)} budget", *extras]))
        self.usage_label.setToolTip("Freeing: removed cached data waiting out its 10-minute grace period; it "
                                    "doesn't count toward the budget." if inventory["retired"]["bytes"] else "")
        self.usage_bar.setValue(min(1000, round(1000 * usage / budget)) if budget else 0)
        datasets = inventory["datasets"]
        text = f"{plural(datasets['count'], 'folder')} · {byte_size(datasets['bytes'])}"
        last_used = datasets.get("last_used")
        if isinstance(last_used, (int, float)):
            text += f" · last used {relative_age(time.time() - last_used)}"
            self.kind_labels["datasets"].setToolTip(
                f"Last used: {datetime.fromtimestamp(last_used):%Y-%m-%d %H:%M}\n"
                f"About {byte_size(datasets.get('ram_bytes', 0))} in RAM when loaded")
        self.kind_labels["datasets"].setText(text)
        self.kind_labels["summaries"].setText(plural(inventory["summaries"]["count"], "folder"))
        histories = inventory["histories"]
        self.kind_labels["histories"].setText(f"{plural(histories['blocked'], 'folder')} skip automatic checks")
        self.kind_labels["histories"].setToolTip(f"{plural(histories['count'], 'folder')} with a scan history")
        self.kind_labels["subtrees"].setText(plural(inventory["subtrees"]["count"], "folder"))
        self.kind_labels["listings"].setText(plural((inventory.get("listings") or {"count": 0})["count"], "folder"))
        results = inventory.get("results") or {"count": 0, "bytes": 0, "last_used": None}
        text = f"{plural(int(results['count']), 'result')} · {byte_size(int(results['bytes']))}"
        if isinstance(results.get("last_used"), (int, float)):
            text += f" · last shown {relative_age(time.time() - results['last_used'])}"
        self.results_label.setText(text)
        self.results_button.setEnabled(writable and bool(results["count"]))
        prefs = inventory.get("prefs") or {"no_cache": 0, "no_auto_load": 0}
        self.prefs_label.setText(f"{plural(prefs['no_cache'], 'folder')} not cached · "
                                 f"{plural(prefs['no_auto_load'], 'folder')} not auto-loaded")
        self.prefs_button.setEnabled(writable and bool(prefs["no_cache"] or prefs["no_auto_load"]))
        checked = f"Checked {datetime.fromtimestamp(inventory['checked_at']):%H:%M}"
        self.checked_label.setText(" · ".join(filter(None, (status or checked, self.message))))
        self._show_estimates()

    def focus_purge(self) -> None:
        """Opened from the 80% warning: start at Remove old entries."""
        self.dataset_days.setFocus()
        self.dataset_days.selectAll()

    def disk_budget_bytes(self) -> int:
        return max(MIN_DISK_BUDGET, round(self.disk_budget.value() * 2) * GB // 2)

    def apply_budget(self) -> bool | None:
        """Before Settings writes anything, the store records a changed disk budget: from then
        on, loads already running save within it too. Lowering it below current use asks first,
        and the same job removes the least recently used cached data until the rest fits.

        True: nothing to wait for. None: wait for ``budgetApplied``. False: declined, or the job
        couldn't be queued; nothing is saved.
        """
        budget = self.disk_budget_bytes()
        # Compared with the budget in effect (the store's), not the saved setting, which
        # "Reset all settings…" may already have changed.
        saved = int(folder_cache.store_options().get("budget") or read_disk_budget(self.settings))
        if self.applying:
            return False
        if budget == saved or not self.enabled or self.cache is None:
            self._acknowledged = budget  # Unchanged, or no store to tell.
            return True
        inventory = self.inventory
        trim = budget < saved and (inventory is None or int(inventory["usage"]) > budget)
        if trim and not self._ask_trim(budget, inventory, None):
            return False
        # Lowering it without a trim: the helper checks it still fits (more may be cached by now).
        self._send_budget("trim" if trim else "budget", budget, fit=budget < saved and not trim)
        return None if self._budget_job else False

    def _ask_trim(self, budget: int, inventory: dict[str, Any] | None, usage: int | None) -> bool:
        if inventory is not None:
            estimate = trim_estimate(inventory, budget)
            removes = (f"Removes cached data for up to {plural(estimate['datasets'], 'folder')} "
                       f"({byte_size(estimate['bytes'])}), least recently used first.")
        else:
            removes = "Removes the least recently used cached data until the rest fits."
        uses = f"now uses {byte_size(usage)}, more than" if usage is not None else "uses more than"
        return self.confirm("Lower the disk cache budget?",
                            f"The disk cache {uses} {byte_size(budget)}. {removes}\n\n{CLEAR_TEXT['datasets']}",
                            "Lower budget")

    def _send_budget(self, action: str, budget: int, *, fit: bool = False) -> None:
        assert self.cache is not None
        self._applying_budget = budget
        params: dict[str, Any] = {"budget": budget, "budget_set_at": time.time()}
        if fit:
            params["fit"] = True
        self._budget_job = self.cache.cache_admin(action, **params)
        self.message = "" if self._budget_job else "Disk cache queue full — nothing saved. Save again to retry."
        self._update()

    def save(self, settings: QSettings) -> None:
        """Save both budgets (after :meth:`apply_budget`), and how often Live saves."""
        # Never a value the store hasn't recorded (e.g. edited while it was recording another).
        settings.setValue(DISK_BUDGET_SETTING,
                          self._acknowledged if self._acknowledged is not None else read_disk_budget(settings))
        settings.setValue(RAM_BUDGET_SETTING, self.ram_budget.value())
        settings.setValue(PLOT_AUTO_RELOAD_SETTING, self.plot_auto_reload.isChecked())
        settings.setValue(RESULT_REUSE_SETTING, self.result_reuse.isChecked())
        if self.cache is not None:
            self.cache.set_result_reuse(self.result_reuse.isChecked())  # (The folder rows' badge.)
        settings.setValue(LIVE_AUTOSAVE_SETTING, self.live_autosave.value())

