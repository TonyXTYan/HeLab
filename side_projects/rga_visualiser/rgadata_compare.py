#!/usr/bin/env python3
"""Compare spectra from multiple SRS RGASoft .rgadata files."""

from __future__ import annotations

import argparse
import math
import struct
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Optional, Sequence

import plotly.graph_objects as go
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .plotly_view import PlotlyPlotView
from .rga_visualiser import COMMON_GAS_PEAKS, RGAData, parse_rgadata

if TYPE_CHECKING:
    from .rgadata_diff import ScanDiffWindow

_RGADATA_HOST = "100.123.123.201"
_RGADATA_SUBPATH = Path("Users/helium/Documents/RGAData")


def _detect_default_rgadata_folder() -> Path:
    """Locate the lab's RGAData share under ``/Volumes``.

    The share is mounted by Tailscale IP, and macOS appends a ``-1``,
    ``-2``, ... suffix to disambiguate it from other mounts of the same
    name; which suffix ends up on the actual data share depends on mount
    order, not on anything stable. Instead of assuming a suffix, try
    every ``100.123.123.201*`` volume and use the first one that really
    contains the RGAData folder.
    """

    volumes = Path("/Volumes")
    candidates = sorted(volumes.glob(f"{_RGADATA_HOST}*")) if volumes.is_dir() else []
    for candidate in candidates:
        target = candidate / _RGADATA_SUBPATH
        if target.is_dir():
            return target
    first = candidates[0] if candidates else volumes / f"{_RGADATA_HOST}-1"
    return first / _RGADATA_SUBPATH


DEFAULT_RGADATA_FOLDER = _detect_default_rgadata_folder()


class ReductionMode(Enum):
    """How a file's scans are reduced to one comparison trace."""

    SINGLE = "Single scan"
    MEAN_ALL = "Mean of all scans"
    MEAN_SELECTED = "Mean of selected scans"


@dataclass
class TraceSelection:
    """Per-file reduction settings retained while browsing a folder.

    An empty ``scan_indices`` means "not yet resolved" — ``_load_data``
    fills it in with the file's latest scan the first time it is loaded.
    """

    mode: ReductionMode = ReductionMode.SINGLE
    scan_indices: set[int] = field(default_factory=set)


def discover_rgadata_files(folder: Path) -> list[Path]:
    """Return .rgadata files directly inside *folder*, without recursion."""

    return sorted(
        (
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() == ".rgadata"
        ),
        key=lambda path: path.name.casefold(),
    )


def reduce_scans(data: RGAData, selection: TraceSelection) -> tuple[float, ...]:
    """Reduce selected scans to a single spectrum."""

    if selection.mode is ReductionMode.MEAN_ALL:
        indices = list(range(len(data.scans)))
    else:
        indices = sorted(selection.scan_indices)

    if not indices:
        raise ValueError("Select at least one scan")
    if any(index < 0 or index >= len(data.scans) for index in indices):
        raise IndexError("Selected scan is outside the file's scan range")
    if selection.mode is ReductionMode.SINGLE and len(indices) != 1:
        raise ValueError("Single-scan mode requires exactly one scan")

    scans = [data.scans[index].values for index in indices]
    if len(scans) == 1:
        return scans[0]
    return tuple(
        math.fsum(scan[point] for scan in scans) / len(scans)
        for point in range(len(scans[0]))
    )


def normalise_spectrum(values: Sequence[float]) -> tuple[float, ...]:
    """Scale a spectrum by its largest positive value."""

    positive_maximum = max((value for value in values if value > 0), default=0.0)
    if positive_maximum <= 0:
        raise ValueError("Spectrum has no positive values to normalise")
    return tuple(value / positive_maximum for value in values)


def selection_label(selection: TraceSelection) -> str:
    """Return a concise legend label for a file's reduction setting."""

    if selection.mode is ReductionMode.MEAN_ALL:
        return "mean: all scans"
    indices = sorted(selection.scan_indices)
    if selection.mode is ReductionMode.SINGLE:
        return f"scan {indices[0] + 1}"
    scan_numbers = ", ".join(str(index + 1) for index in indices)
    return f"mean: scans {scan_numbers}"


class RGAComparisonWindow(QMainWindow):
    """Folder browser and Plotly comparison window."""

    PATH_ROLE = int(Qt.ItemDataRole.UserRole)
    INDEX_ROLE = PATH_ROLE + 1

    def __init__(self, initial_folder: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("RGA data visualiser and comparison")
        self.resize(1280, 780)

        self._folder: Path | None = None
        self._data_cache: dict[Path, RGAData] = {}
        self._selections: dict[Path, TraceSelection] = {}
        self._updating_controls = False
        self._diff_window: ScanDiffWindow | None = None

        self.open_folder_button = QPushButton("Open folder…")
        self.compare_scans_button = QPushButton("Compare two scans…")
        self.folder_label = QLabel("No folder selected")
        self.folder_label.setWordWrap(True)
        self.file_list = QListWidget()
        self.file_list.setMinimumWidth(300)
        self.file_list.setToolTip(
            "Tick files to plot. Highlight a file to configure its scans."
        )

        self.selected_file_label = QLabel("Select a file to configure its scans")
        self.selected_file_label.setWordWrap(True)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([mode.value for mode in ReductionMode])
        self.scan_list = QListWidget()
        self.scan_list.setMinimumHeight(170)
        self.normalise_checkbox = QCheckBox("Normalise each trace to its maximum")
        self.gas_markers_checkbox = QCheckBox("Show common gas markers")
        self.gas_markers_checkbox.setChecked(True)
        self.log_scale_checkbox = QCheckBox("Log Y scale")
        self.log_scale_checkbox.setChecked(True)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.addWidget(self.open_folder_button)
        controls_layout.addWidget(self.compare_scans_button)
        controls_layout.addWidget(self.folder_label)
        controls_layout.addWidget(QLabel("Files"))
        controls_layout.addWidget(self.file_list, 1)
        controls_layout.addWidget(self.selected_file_label)
        controls_layout.addWidget(QLabel("Trace from highlighted file"))
        controls_layout.addWidget(self.mode_combo)
        controls_layout.addWidget(QLabel("Scans"))
        controls_layout.addWidget(self.scan_list)
        controls_layout.addWidget(self.normalise_checkbox)
        controls_layout.addWidget(self.gas_markers_checkbox)
        controls_layout.addWidget(self.log_scale_checkbox)
        controls_layout.addWidget(self.status_label)

        self.plot_view = PlotlyPlotView()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(controls)
        splitter.addWidget(self.plot_view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 950])

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        self.setCentralWidget(container)

        self.open_folder_button.clicked.connect(self._choose_folder)
        self.compare_scans_button.clicked.connect(self._open_diff_window)
        self.file_list.currentItemChanged.connect(self._current_file_changed)
        self.file_list.itemChanged.connect(self._file_check_state_changed)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.scan_list.itemChanged.connect(self._scan_check_state_changed)
        self.normalise_checkbox.stateChanged.connect(self._normalise_changed)
        self.gas_markers_checkbox.stateChanged.connect(self._gas_markers_changed)
        self.log_scale_checkbox.stateChanged.connect(self._log_scale_changed)

        self._set_configuration_enabled(False)
        self._update_plot()
        if initial_folder is not None:
            self.load_folder(initial_folder)

    def _set_configuration_enabled(self, enabled: bool) -> None:
        self.mode_combo.setEnabled(enabled)
        self.scan_list.setEnabled(enabled)

    def _choose_folder(self) -> None:
        if self._folder is not None:
            default_start = self._folder
        elif DEFAULT_RGADATA_FOLDER.is_dir():
            default_start = DEFAULT_RGADATA_FOLDER
        else:
            default_start = Path.home()
        start = str(default_start)
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose folder containing RGA data",
            start,
        )
        if selected:
            self.load_folder(Path(selected))

    def _open_diff_window(self) -> None:
        from .rgadata_diff import ScanDiffWindow

        if self._diff_window is None:
            self._diff_window = ScanDiffWindow(self._folder or DEFAULT_RGADATA_FOLDER)
        self._diff_window.show()
        self._diff_window.raise_()
        self._diff_window.activateWindow()

    def load_folder(self, folder: Path) -> None:
        """Load the non-recursive file list for *folder*."""

        try:
            files = discover_rgadata_files(folder)
        except OSError as exc:
            QMessageBox.critical(self, "Cannot open folder", str(exc))
            return

        self._folder = folder
        self._data_cache.clear()
        self._selections.clear()
        self._updating_controls = True
        self.file_list.clear()
        self.scan_list.clear()
        for path in files:
            item = QListWidgetItem(path.name)
            item.setData(self.PATH_ROLE, str(path))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.file_list.addItem(item)
            self._selections[path] = TraceSelection()
        self._updating_controls = False

        self.folder_label.setText(str(folder))
        self.selected_file_label.setText("Select a file to configure its scans")
        self._set_configuration_enabled(False)
        if files:
            self.file_list.setCurrentRow(0)
            self.status_label.setText(
                f"Found {len(files)} .rgadata file{'s' if len(files) != 1 else ''}."
            )
        else:
            self.status_label.setText("No .rgadata files found at this folder level.")
        self._update_plot()

    def _path_from_item(self, item: QListWidgetItem | None) -> Path | None:
        if item is None:
            return None
        value = item.data(self.PATH_ROLE)
        return Path(str(value)) if value else None

    def _load_data(self, path: Path) -> RGAData:
        cached = self._data_cache.get(path)
        if cached is None:
            cached = parse_rgadata(path)
            self._data_cache[path] = cached
            selection = self._selections.get(path)
            if selection is not None and not selection.scan_indices:
                selection.scan_indices = {len(cached.scans) - 1}
        return cached

    def _current_file_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        path = self._path_from_item(current)
        if path is None:
            self.selected_file_label.setText(
                "Select a file to configure its scans"
            )
            self.scan_list.clear()
            self._set_configuration_enabled(False)
            return

        try:
            data = self._load_data(path)
        except (OSError, ValueError, struct.error) as exc:
            self._show_file_error(path, exc)
            return

        selection = self._selections[path]
        self._updating_controls = True
        self.selected_file_label.setText(path.name)
        self.mode_combo.setCurrentText(selection.mode.value)
        self.scan_list.clear()
        for index, scan in enumerate(data.scans):
            item = QListWidgetItem(
                f"Scan {index + 1}  (+{scan.elapsed_seconds:.3f} s)"
            )
            item.setData(self.INDEX_ROLE, index)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if index in selection.scan_indices
                else Qt.CheckState.Unchecked
            )
            self.scan_list.addItem(item)
        self._updating_controls = False
        self._set_configuration_enabled(True)
        self.scan_list.setEnabled(selection.mode is not ReductionMode.MEAN_ALL)

    def _show_file_error(self, path: Path, exc: BaseException) -> None:
        QMessageBox.warning(
            self,
            "Cannot read RGA data",
            f"{path.name}\n\n{exc}",
        )
        current = self.file_list.currentItem()
        if current is not None and self._path_from_item(current) == path:
            self._updating_controls = True
            current.setCheckState(Qt.CheckState.Unchecked)
            self._updating_controls = False
        self._set_configuration_enabled(False)

    def _file_check_state_changed(self, _item: QListWidgetItem) -> None:
        if not self._updating_controls:
            self._update_plot()

    def _normalise_changed(self, _state: int) -> None:
        self._update_plot()

    def _gas_markers_changed(self, _state: int) -> None:
        self._update_plot()

    def _log_scale_changed(self, _state: int) -> None:
        self._update_plot()

    def _mode_changed(self, _index: int) -> None:
        if self._updating_controls:
            return
        path = self._path_from_item(self.file_list.currentItem())
        if path is None:
            return
        selection = self._selections[path]
        selection.mode = ReductionMode(self.mode_combo.currentText())
        if selection.mode is ReductionMode.SINGLE:
            first = min(selection.scan_indices, default=0)
            selection.scan_indices = {first}
        elif not selection.scan_indices:
            selection.scan_indices = {0}
        self._refresh_scan_checks(selection)
        self.scan_list.setEnabled(selection.mode is not ReductionMode.MEAN_ALL)
        self._update_plot()

    def _scan_check_state_changed(self, item: QListWidgetItem) -> None:
        if self._updating_controls:
            return
        path = self._path_from_item(self.file_list.currentItem())
        if path is None:
            return
        index = int(item.data(self.INDEX_ROLE))
        selection = self._selections[path]
        checked = item.checkState() is Qt.CheckState.Checked

        if selection.mode is ReductionMode.SINGLE:
            if checked:
                selection.scan_indices = {index}
            elif index in selection.scan_indices:
                selection.scan_indices = {index}
        elif checked:
            selection.scan_indices.add(index)
        else:
            selection.scan_indices.discard(index)
            if not selection.scan_indices:
                selection.scan_indices.add(index)
        self._refresh_scan_checks(selection)
        self._update_plot()

    def _refresh_scan_checks(self, selection: TraceSelection) -> None:
        self._updating_controls = True
        for row in range(self.scan_list.count()):
            item = self.scan_list.item(row)
            if item is None:
                continue
            index = int(item.data(self.INDEX_ROLE))
            item.setCheckState(
                Qt.CheckState.Checked
                if index in selection.scan_indices
                else Qt.CheckState.Unchecked
            )
        self._updating_controls = False

    def _checked_paths(self) -> Iterable[Path]:
        for row in range(self.file_list.count()):
            item = self.file_list.item(row)
            if item is None:
                continue
            if item.checkState() is Qt.CheckState.Checked:
                path = self._path_from_item(item)
                if path is not None:
                    yield path

    def _update_plot(self) -> None:
        figure = go.Figure()
        errors: list[str] = []
        normalise = self.normalise_checkbox.isChecked()
        log_scale = self.log_scale_checkbox.isChecked()
        trace_count = 0
        mass_min: float | None = None
        mass_max: float | None = None

        for path in self._checked_paths():
            try:
                data = self._load_data(path)
                selection = self._selections[path]
                values = reduce_scans(data, selection)
                if normalise:
                    values = normalise_spectrum(values)
                plotted_values: list[float | None] = (
                    [value if value > 0 else None for value in values]
                    if log_scale
                    else list(values)
                )
                figure.add_trace(
                    go.Scatter(
                        x=data.masses,
                        y=plotted_values,
                        mode="lines",
                        name=f"{path.name} — {selection_label(selection)}",
                        customdata=[path.name] * len(data.masses),
                        hovertemplate=(
                            "%{customdata}<br>"
                            "Mass: %{x:.2f} amu/e<br>"
                            "Signal: %{y:.4e}<extra></extra>"
                        ),
                    )
                )
                trace_count += 1
                mass_min = data.masses[0] if mass_min is None else min(mass_min, data.masses[0])
                mass_max = data.masses[-1] if mass_max is None else max(mass_max, data.masses[-1])
            except (OSError, ValueError, IndexError) as exc:
                errors.append(f"{path.name}: {exc}")

        if self.gas_markers_checkbox.isChecked() and mass_min is not None and mass_max is not None:
            for mass, label in COMMON_GAS_PEAKS:
                if mass_min <= mass <= mass_max:
                    figure.add_vline(
                        x=mass,
                        line_width=1,
                        line_dash="dot",
                        line_color="#999999",
                        annotation_text=f"{label} ({mass})",
                        annotation_position="top",
                        annotation_textangle=-90,
                        annotation_font_size=10,
                        annotation_font_color="#666666",
                        annotation_yshift=4,
                    )

        y_title = (
            "Normalised ion current (maximum = 1)"
            if normalise
            else "Ion current (A)"
        )
        figure.update_layout(
            template="plotly_white",
            xaxis_title="Mass-to-charge ratio (amu/e)",
            yaxis_title=y_title,
            yaxis_type="log" if log_scale else "linear",
            hovermode="x unified",
            legend=dict(
                title_text="File and scan reduction",
                orientation="v",
                yanchor="top",
                y=0.99,
                xanchor="right",
                x=0.99,
                bgcolor="rgba(255,255,255,0.85)",
                bordercolor="#cccccc",
                borderwidth=1,
            ),
            margin=dict(l=75, r=25, t=90, b=65),
        )
        if trace_count == 0:
            figure.add_annotation(
                text="Open a folder, then tick one or more .rgadata files.",
                x=0.5,
                y=0.5,
                xref="paper",
                yref="paper",
                showarrow=False,
                font=dict(size=16, color="#666666"),
            )

        self.status_label.setText(
            "\n".join(errors)
            if errors
            else f"Plotting {trace_count} file{'s' if trace_count != 1 else ''}."
        )
        self.plot_view.show_figure(figure)

    def closeEvent(  # noqa: N802 - Qt API name
        self,
        event: Optional[QCloseEvent],
    ) -> None:
        self.plot_view.cleanup()
        if self._diff_window is not None:
            self._diff_window.close()
        super().closeEvent(event)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "folder",
        nargs="?",
        type=Path,
        help=(
            "optional initial folder containing .rgadata files "
            f"(defaults to {DEFAULT_RGADATA_FOLDER} if mounted)"
        ),
    )
    args = parser.parse_args()
    initial_folder = args.folder
    if initial_folder is None and DEFAULT_RGADATA_FOLDER.is_dir():
        initial_folder = DEFAULT_RGADATA_FOLDER

    application = QApplication(sys.argv)
    window = RGAComparisonWindow(initial_folder)
    window.show()
    raise SystemExit(application.exec())


if __name__ == "__main__":
    main()
