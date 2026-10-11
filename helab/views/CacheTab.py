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

from helab.utils.cache_store import KINDS, purge_estimate, trim_estimate
from helab.utils.constants import (
    DISK_BUDGET_SETTING, MIN_DISK_BUDGET, RAM_BUDGET_SETTING, RAM_STEPS, read_disk_budget,
    cache_dir_refused, read_ram_budget_steps, ram_step_bytes, ram_step_range, total_ram,
)
from helab.utils.folder_cache import FolderCache, store_options
from helab.utils.number_format import byte_size
from helab.utils.time_format import relative_age

GB = 1 << 30
DAY = 86400.0
DEFAULT_PURGE_DAYS = 90
# The rows of the disk cache, by record kind: label and button.
KIND_ROWS = {"datasets": ("Cached data", "Clear…"), "summaries": ("Folder summaries", "Clear…"),
             "histories": ("Scan failures", "Forget…"), "subtrees": ("Subfolder status", "Clear…")}
# What a Clear of each kind loses and keeps, for its confirmation.
CLEAR_TEXT = {
    "datasets": "Loaded data stays open; the next load of each folder reads its TXY files again.",
    "summaries": "Folders show their counts and status again after their next check.",
    "histories": "Automatic checks will try these folders again.",
    "subtrees": "Each folder's status from its subfolders is derived again when it is listed.",
}


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
        self.enabled = bool(cache is not None and store_options())
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
            QUrl.fromLocalFile(str(store_options().get("directory", "")))))
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
            "Counts live data: cached datasets and the records database. Removed files waiting out their "
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
        layout.addLayout(grid)

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
        for row, (text, days, estimate, button) in enumerate((
                ("Cached data not used in the last", self.dataset_days, self.dataset_estimate,
                 self.purge_datasets_button),
                ("Folder records not checked in the last", self.record_days, self.record_estimate,
                 self.purge_records_button))):
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
            "fit. Folders shown in tabs are never dropped, so HeLab can use more than this.")
        memory.addWidget(self.ram_budget)
        self.memory_label = QLabel("")
        memory.addWidget(self.memory_label, 1)
        layout.addLayout(memory)
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
        root = str(store_options().get("directory", ""))
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

    def clear(self, kinds: list[str]) -> None:
        inventory = self.inventory
        if inventory is None or self.busy:
            return
        if set(kinds) == set(KINDS):
            title = "Clear the disk cache?"
            text = (f"Removes everything in the disk cache: cached data for "
                    f"{plural(inventory['datasets']['count'], 'folder')} ({byte_size(inventory['datasets']['bytes'])}),"
                    " folder summaries, scan failures and subfolder status.\n\n"
                    "Loaded data stays open. Automatic checks will try failed folders again.")
            verb, label = "Clear all", "Clear all"
        else:
            kind = kinds[0]
            name = KIND_ROWS[kind][0]
            count = inventory["histories"]["blocked"] if kind == "histories" else inventory[kind]["count"]
            size = f" ({byte_size(inventory['datasets']['bytes'])})" if kind == "datasets" else ""
            verb = "Forget" if kind == "histories" else "Clear"
            title = f"{verb} {name.lower()}?"
            text = f"{verb}s {name.lower()} for {plural(count, 'folder')}{size}.\n\n{CLEAR_TEXT[kind]}"
            label = f"{verb} {name.lower()}"
        if self.confirm(title, text, verb):
            self._run(label, "clear", kinds=list(kinds))

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
                        f"{plural(days, 'day')}: summaries, subfolder status and scan histories.\n\n"
                        f"Cached data stays. {stays}", "Remove"):
            self._run("Remove old folder records", "purge", what="records", cutoff=cutoff,
                      include_failures=failures)

    def show_memory(self) -> None:
        if self.cache is None:
            self.memory_label.setText("")
            return
        count, total, shown = self.cache.memory_usage()
        self.memory_label.setText(f"In use: {plural(count, 'folder')} · {byte_size(total)} "
                                  f"({byte_size(shown)} shown in tabs)")

    def _show_estimates(self) -> None:
        inventory = self.inventory
        if inventory is None:
            for label in (self.dataset_estimate, self.record_estimate):
                label.setText("")
            self.purge_datasets_button.setEnabled(False)
            self.purge_records_button.setEnabled(False)
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
                                        f"{plural(records['histories'], 'scan history')}")
        writable = not inventory.get("read_only") and not self.busy
        self.purge_datasets_button.setEnabled(writable and datasets["datasets"] > 0)
        self.purge_records_button.setEnabled(writable and sum(records.values()) > 0)

    def _update(self) -> None:
        inventory = self.inventory
        writable = inventory is not None and not inventory.get("read_only") and not self.busy
        for button in (*self.kind_buttons.values(), self.clear_all_button):
            button.setEnabled(writable)
        self.refresh_button.setEnabled(self.enabled and not self.busy and not self._inventory_owner)
        self.disk_budget.setEnabled(not self.applying)
        status = ("Off for this session" if not store_options() else
                  "Changing the disk budget…" if self._budget_job else f"{self._job_label}…" if self.busy else "Checking…" if self._inventory_owner and inventory is None
                  else "")
        if inventory is None:
            for label in self.kind_labels.values():
                label.setText(status or "Not checked")
            self.usage_label.setText(status or "Not checked")
            self.checked_label.setText(self.message or status)
            self._show_estimates()
            return
        budget = int(store_options().get("budget") or read_disk_budget(self.settings))
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
        saved = int(store_options().get("budget") or read_disk_budget(self.settings))
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
        """Save both budgets (after :meth:`apply_budget`)."""
        # Never a value the store hasn't recorded (e.g. edited while it was recording another).
        settings.setValue(DISK_BUDGET_SETTING,
                          self._acknowledged if self._acknowledged is not None else read_disk_budget(settings))
        settings.setValue(RAM_BUDGET_SETTING, self.ram_budget.value())

