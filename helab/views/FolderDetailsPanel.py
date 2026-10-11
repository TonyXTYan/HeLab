"""Folder details: the current tab's selected folder, its load and the I/O activity, from memory only."""
from __future__ import annotations

import math
import os
import time
from datetime import datetime
from typing import Any, Mapping

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QProgressBar, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from helab.models.StatusReport import StatusReport
from helab.utils.number_format import fnum
from helab.utils.io_service import IOService
from helab.utils.time_format import clock as stopwatch, relative_age
from helab.views.ElidedLabel import ElidedLabel
from helab.views.FolderExplorer import (
    AMBER, AUTO_LOAD_PAUSED, AUTO_LOAD_PAUSED_TOOLTIP, LARGE_TOOLTIP, LOAD_ORIGINS, REFUSED_TOOLTIP, FolderExplorer,
    large_text,
)


# Marks the large-folder part of a state row, which is then amber.
LARGE_MARK = "Update not loaded: "


class FolderDetailsPanel(QScrollArea):
    """Single-line rows that hide when empty; longer details are in each row's tooltip."""

    ROWS = (("folder", "Folder"), ("state", "State"), ("files", "Files"), ("time", "Time"), ("rate", "Rate"),
            ("data", "Data"), ("loaded", "Loaded"), ("source", "Source"), ("cache", "Disk cache"),
            ("errors", "Problems"),
            ("tab", "This tab"), ("io", "All I/O"))

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(0)
        self.title = QLabel("Folder details")
        font = QFont(self.title.font())
        font.setBold(True)
        self.title.setFont(font)
        layout.addWidget(self.title)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(0)
        grid.setColumnStretch(1, 1)
        self.names: dict[str, QLabel] = {}
        self.values: dict[str, ElidedLabel] = {}
        # The selected load's progress, under its state.
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(min(8, self.fontMetrics().height()))
        self.progress.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.progress.hide()
        row = 0
        for key, name in self.ROWS:
            label = QLabel(name)
            label.setEnabled(False)  # Dimmed, like a form's field names.
            value = ElidedLabel()
            grid.addWidget(label, row, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(value, row, 1)
            self.names[key], self.values[key] = label, value
            row += 1
            if key == "state":
                grid.addWidget(self.progress, row, 1)
                row += 1
        layout.addLayout(grid)
        layout.addStretch(1)
        self.setWidget(body)
        self.show_explorer(None, None)

    def set_row(self, key: str, text: str, tooltip: str = "") -> None:
        value = self.values[key]
        # Refreshed every GUI tick: touch the widgets only when something changed.
        if value.text() != text:
            value.setText(text)
        tooltip = tooltip or text
        if value.toolTip() != tooltip:
            value.setToolTip(tooltip)
        if value.isHidden() == bool(text):
            self.names[key].setVisible(bool(text))
            value.setVisible(bool(text))

    def text(self, key: str) -> str:
        """A row's full text ("" when hidden), for tests and other readers."""
        return self.values[key].text()

    def show_explorer(self, explorer: FolderExplorer | None, service: IOService | None) -> None:
        """Show this tab's selected folder; reads memory only, so it can run on every GUI tick."""
        rows: dict[str, tuple[str, str]] = {key: ("", "") for key in self.values}
        self.progress.hide()
        if explorer is None:
            rows["state"] = ("Select a data folder", "")
        else:
            rows.update(self._folder_rows(explorer))
            if explorer.activity_text:
                rows["tab"] = (explorer.activity_text, "\n\n".join(filter(None, (
                    "Other work in this tab; the selected folder's load is above.", explorer.activity_tooltip))))
        if service is not None:
            rows["io"] = (service.activity_summary(), service.queue_tooltip())
        for key, (text, tooltip) in rows.items():
            self.set_row(key, text, tooltip)
        # A large folder's state is amber, as on the summary line.
        large = explorer is not None and explorer.large_state(explorer.selected_path_globally) is not None
        style = f"color: {AMBER};" if large and rows["state"][0].startswith(("Large folder", "Too large")) else ""
        if large and rows["state"][0] and not style and LARGE_MARK in rows["state"][0]:
            style = f"color: {AMBER};"
        if self.values["state"].styleSheet() != style:
            self.values["state"].setStyleSheet(style)

    def _folder_rows(self, explorer: FolderExplorer) -> dict[str, tuple[str, str]]:
        path = explorer.selected_path_globally
        rows: dict[str, tuple[str, str]] = {"folder": (os.path.basename(path.rstrip(os.sep)) or path, path)}
        node = explorer.model.nodes.get(path)
        dataset = explorer.displayed_dataset
        shown = dataset is not None and dataset.path == path
        opened = explorer.folder_opened_path == path
        unchecked = explorer.shows_unchecked(path)
        loading = explorer.loading and explorer.load_path == path
        if loading:
            self._load_rows(explorer, rows)
        elif explorer.load_error:
            prefix = "Check failed · " if unchecked else ""
            rows["state"] = (prefix + explorer.load_error, "\n".join(filter(None, (
                "The cached data is still shown; it was not checked against the folder." if unchecked else "",
                explorer.load_error))))
        elif explorer.load_waiting:
            rows["state"] = (f"Waiting · queues in {explorer.dwell_seconds_left} s if still selected",
                             "Another load is running; browsing past folders does not queue them.")
        elif explorer.auto_load_paused_path == path and not shown:
            rows["state"] = (AUTO_LOAD_PAUSED + " · Load data", AUTO_LOAD_PAUSED_TOOLTIP)
        elif (large := explorer.large_state(path)) is not None and not shown:
            rows["state"] = (large_text(*large) + ("" if large[1] else " · Load anyway…"),
                             REFUSED_TOOLTIP if large[1] else LARGE_TOOLTIP)
        elif opened:
            # Not loading: shown from the cache with auto-load off, or its check was cancelled.
            rows["state"] = ("Loaded from cache · not checked yet", "Shown from memory or the disk cache; "
                             "Load data checks it against the folder.") if unchecked else ("Loaded", "")
        elif shown:
            changed = node is not None and dataset is not None and FolderExplorer._changed_since_load(node, dataset)
            rows["state"] = ("Folder changed · showing previous data" if changed else "Showing previous data",
                             "The loaded data no longer matches the folder. Load data to update it.")

        elif node and node.error:
            rows["state"] = (node.error, node.error)
        elif explorer.scan_message:
            rows["state"] = (explorer.scan_message, "")
        elif node is None or node.report is None:
            rows["state"] = ("TXY count not checked", "")
        elif node.txy_count or node.report.d_txy_shots or node.report.status in StatusReport.STATUS_CONTAINS_DATA_HERE:
            rows["state"] = ("Not loaded", "Right-click it › Load data, or turn on View › Toggle Auto Load to RAM.")
        else:
            rows["state"] = ("No TXY files here", "")
        if not loading and not shown and node is not None and (node.txy_count or node.report and node.report.d_txy_shots):
            found = node.txy_count or (len(node.report.d_txy_shots or []) if node.report else 0)
            rows["files"] = (f"{found:,} TXY found", "")
        large = explorer.large_state(path)
        if large is not None and (shown or opened) and not loading and not explorer.load_error:
            # The update didn't load for being large: say so beside the data still shown.
            rows["state"] = (f"{rows['state'][0]} · {LARGE_MARK}{large_text(*large)}"
                             + ("" if large[1] else " · Load anyway…"),
                             REFUSED_TOOLTIP if large[1] else LARGE_TOOLTIP)
        cache = explorer.model.cache
        if path in cache.pending_saves and (waiting := cache.cache_status(path).error):
            # A save held for the user's answer (Make room / Save update); one question at a time.
            rows["cache"] = (waiting, "The disk cache asks before this save: Make room or Save update, or don't "
                                      "cache it now. The loaded data stays in RAM either way.")
        if dataset is None or not shown:
            return rows
        self._data_rows(explorer, dataset.metadata, rows, loading, opened)
        return rows

    def _load_rows(self, explorer: FolderExplorer, rows: dict[str, tuple[str, str]]) -> None:
        """State, progress, time and rate of the selected folder's running load."""
        if explorer.load_queued:
            state = "Queued"
        else:
            phase = [f"Retrying file (attempt {explorer.load_attempt} of 3)"] \
                if explorer.load_attempt > 1 and explorer.load_filename else []
            phase += [explorer.load_listing] if explorer.load_listing else []
            verb = explorer.load_verb
            # A check that reads nothing ends here; one that finds changes shows its progress.
            verb = "Checking for changes" if verb == "Checking" and not phase else verb
            state = " · ".join([verb, *phase])
        rows["state"] = (state, explorer.loading_tooltip)
        if explorer.load_progress is not None:
            self.progress.setRange(0, 1000)
            self.progress.setValue(round(explorer.load_progress * 1000))
            rows["files"] = (explorer.loading_progress_message, "")
        elif not explorer.load_queued:
            # Busy until the first file is counted; a paused bar stays still.
            self.progress.setRange(0, 1000 if explorer.load_paused else 0)
            self.progress.setValue(0)
        self.progress.setVisible(not explorer.load_queued)
        self.progress.setToolTip(explorer.loading_message)
        timing = explorer.loading_timing_message
        if timing:
            rows["time"] = (timing, "Running time: queued and paused time is not counted.\n"
                                    "Time left is estimated from the TXY bytes still to read; "
                                    "files reused from memory or the disk cache are not counted.")
        rate = explorer.loading_rate_message
        clock = explorer.load_clock
        if rate and clock is not None:
            rows["rate"] = (rate, f"TXY files read from the folder over the last {clock.WINDOW_SECONDS:.0f} s "
                                  "of running time (files reused from memory or the disk cache are not counted)")

    @staticmethod
    def _data_rows(explorer: FolderExplorer, meta: Mapping[str, Any], rows: dict[str, tuple[str, str]],
                   loading: bool, opened: bool) -> None:
        """The shown dataset: counts, size, when it was loaded, where from and its problem shots."""
        def number(key: str) -> int:
            value = meta.get(key, 0)
            return int(value) if isinstance(value, (int, float)) and math.isfinite(value) else 0

        def plural(count: int, noun: str) -> str:
            return f"{count:,} {noun}{'' if count == 1 else 's'}"

        if not loading:
            loaded, failed, unsettled = number("files"), number("failed_files"), number("unsettled_files")
            found = number("total_files") or loaded + failed + unsettled
            files = " · ".join(filter(None, (
                f"{found:,} TXY found · {loaded:,} loaded", f"{failed:,} unreadable" if failed else "",
                f"{unsettled:,} still being written" if unsettled else "")))
            rows["files"] = (files, "Counts from when this data was loaded")
        rows["data"] = (f"{plural(number('rows'), 'data row')} · {fnum(number('bytes')).strip()}B in RAM",
                        "Rows (t, x, y) across the loaded TXY files, and the memory their arrays use")
        loaded_at = meta.get("loaded_at")
        if isinstance(loaded_at, (int, float)) and math.isfinite(loaded_at):
            try:
                when = datetime.fromtimestamp(loaded_at).astimezone()
            except (OverflowError, OSError, ValueError):
                when = None
            if when is not None:
                today = when.date() == datetime.now().astimezone().date()
                parts = [f"{when:%H:%M:%S}" if today else f"{when:%Y-%m-%d %H:%M}",
                         relative_age(time.time() - loaded_at)]
                seconds = meta.get("load_seconds")
                took = seconds if isinstance(seconds, (int, float)) and math.isfinite(seconds) else None
                if took is not None:
                    parts.append(f"took {stopwatch(took)}")
                elif meta.get("unchanged"):
                    parts.append("checked, unchanged")
                rows["loaded"] = (" · ".join(parts), "\n".join(filter(None, (
                    f"Read into memory {when:%Y-%m-%d %H:%M:%S %Z}",
                    "Load time: running time, without queued or paused time" if took is not None else "",
                    "The folder was not modified since the disk cache; nothing was read"
                    if meta.get("unchanged") else ""))))
        origin = LOAD_ORIGINS.get(explorer.load_source) if opened else None
        if origin:
            rows["source"] = (origin, "\n".join(filter(None, (
                explorer.load_cache_reason, " · ".join(explorer.load_count_details), explorer.load_cache_warning))))
        raw = meta.get("problematic", [])
        problematic = [int(shot) for shot in raw if isinstance(shot, (int, float))] if isinstance(raw, list) else []
        if problematic:
            shown = ", ".join(map(str, problematic[:50])) + (" …" if len(problematic) > 50 else "")
            rows["errors"] = (f"{plural(len(problematic), 'shot')} unreadable or with invalid rows",
                              f"Shots: {shown}\nUnreadable files are left out; rows that are not "
                              "three numbers are dropped.")
