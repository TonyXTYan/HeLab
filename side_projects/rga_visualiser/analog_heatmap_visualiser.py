#!/usr/bin/env python3
"""Visualise automated analogue RGA scans as a time--mass heat map."""

from __future__ import annotations

import argparse
import math
import re
import struct
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import plotly.graph_objects as go
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .plotly_view import PlotlyPlotView
from .rga_visualiser import COMMON_GAS_PEAKS, RGAData, parse_rgadata
from .rgadata_compare import DEFAULT_RGADATA_FOLDER


DEFAULT_ANALOG_FOLDER = DEFAULT_RGADATA_FOLDER / "Analog"
_ANALOG_NAME = re.compile(
    r"^Analog-(?P<date>\d{8})-(?P<time>\d{6})-(?P<millis>\d{3})\.rgadata$",
    re.IGNORECASE,
)
_VIRIDIS_STOPS: tuple[str, ...] = (
    "#440154",
    "#482878",
    "#3e4989",
    "#31688e",
    "#26828e",
    "#1f9e89",
    "#35b779",
    "#6dcd59",
    "#b4de2c",
    "#fde725",
)


@dataclass(frozen=True)
class HeatmapData:
    """A common mass grid and time-ordered collection of spectra."""

    masses: tuple[float, ...]
    times: tuple[datetime, ...]
    values: tuple[tuple[float, ...], ...]
    source_files: int
    skipped_files: tuple[str, ...] = ()


def parse_analog_timestamp(path: Path) -> datetime:
    """Read the acquisition timestamp encoded in an automated filename."""

    match = _ANALOG_NAME.fullmatch(path.name)
    if match is None:
        raise ValueError(
            f"Filename does not contain an analogue RGA timestamp: {path.name}"
        )
    timestamp = datetime.strptime(
        match.group("date") + match.group("time"), "%Y%m%d%H%M%S"
    )
    return timestamp.replace(microsecond=int(match.group("millis")) * 1000)


def discover_analog_files(folder: Path) -> list[Path]:
    """Return timestamped automated files in acquisition order."""

    files: list[tuple[datetime, Path]] = []
    for path in folder.iterdir():
        if not path.is_file() or path.suffix.lower() != ".rgadata":
            continue
        try:
            timestamp = parse_analog_timestamp(path)
        except ValueError:
            continue
        files.append((timestamp, path))
    return [path for _timestamp, path in sorted(files)]


def load_heatmap_data(
    paths: Sequence[Path],
    progress: Callable[[int, int], None] | None = None,
    max_scans: int | None = None,
) -> HeatmapData:
    """Load scans from files sharing one mass grid.

    When ``max_scans`` is set, files are read newest-first until enough scans
    have been collected, then the exact newest number is returned. Otherwise,
    the grid used by the most files is selected. Files with a different grid
    or invalid data are reported rather than interpolated, so the
    visualisation never invents measurements.
    """

    if not paths:
        raise ValueError("No automated .rgadata files were selected")
    if max_scans is not None and max_scans < 1:
        raise ValueError("max_scans must be positive or None")

    decoded: list[tuple[Path, datetime, RGAData]] = []
    grid_counts: dict[tuple[float, ...], tuple[int, int]] = {}
    newest_grid: tuple[float, ...] | None = None
    collected_scans = 0
    skipped: list[str] = []
    total = len(paths)
    for completed, path in enumerate(reversed(paths), start=1):
        try:
            file_time = parse_analog_timestamp(path)
            data = parse_rgadata(path)
            if max_scans is not None:
                if newest_grid is None:
                    newest_grid = data.masses
                if data.masses != newest_grid:
                    raise ValueError("mass grid differs from the newest grid")
            decoded.append((path, file_time, data))
            count, newest_position = grid_counts.get(data.masses, (0, completed))
            grid_counts[data.masses] = (count + 1, newest_position)
            collected_scans += len(data.scans)
        except (OSError, ValueError, struct.error) as exc:
            skipped.append(f"{path.name}: {exc}")
        if progress is not None:
            progress(completed, total)
        if max_scans is not None and collected_scans >= max_scans:
            break

    if not decoded:
        detail = skipped[0] if skipped else "no complete scans found"
        raise ValueError(f"Could not load automated RGA data: {detail}")

    if max_scans is not None:
        if newest_grid is None:
            raise ValueError("Could not determine the newest mass grid")
        reference_masses = newest_grid
    else:
        # Prefer the grid used by the most files; ties favour the newest grid.
        reference_masses = max(
            grid_counts,
            key=lambda masses: (grid_counts[masses][0], -grid_counts[masses][1]),
        )

    rows: list[tuple[datetime, tuple[float, ...], Path]] = []
    for path, file_time, data in decoded:
        if data.masses != reference_masses:
            skipped.append(f"{path.name}: mass grid differs from the dominant grid")
            continue
        rows.extend(
            (
                file_time + timedelta(seconds=scan.elapsed_seconds),
                scan.values,
                path,
            )
            for scan in data.scans
        )
    rows.sort(key=lambda row: row[0])
    if max_scans is not None:
        rows = rows[-max_scans:]
    return HeatmapData(
        masses=reference_masses,
        times=tuple(row[0] for row in rows),
        values=tuple(row[1] for row in rows),
        source_files=len({row[2] for row in rows}),
        skipped_files=tuple(reversed(skipped)),
    )


def transformed_values(
    values: Sequence[Sequence[float]], log_colour: bool
) -> tuple[tuple[float | None, ...], ...]:
    """Prepare ion current values for linear or base-10 logarithmic colour."""

    if not log_colour:
        return tuple(tuple(float(value) for value in row) for row in values)
    return tuple(
        tuple(math.log10(value) if value > 0 else None for value in row)
        for row in values
    )


def high_end_log_colorscale(
    log_values: Sequence[Sequence[float | None]],
    emphasised_decades: float = 4.0,
) -> str | list[list[float | str]]:
    """Expand colour contrast in the strongest logarithmic decades.

    Values below ``maximum - emphasised_decades`` retain only the first dark
    step of Viridis. The rest of the palette is allocated to the high-signal
    interval, while the colour bar continues to report the true log10 values.
    """

    finite = [
        value
        for row in log_values
        for value in row
        if value is not None and math.isfinite(value)
    ]
    if not finite or emphasised_decades <= 0:
        return "Viridis"
    minimum = min(finite)
    maximum = max(finite)
    span = maximum - minimum
    if span <= emphasised_decades:
        return "Viridis"

    high_contrast_start = (maximum - emphasised_decades - minimum) / span
    colourscale: list[list[float | str]] = [
        [0.0, _VIRIDIS_STOPS[0]],
        [high_contrast_start, _VIRIDIS_STOPS[1]],
    ]
    upper_intervals = len(_VIRIDIS_STOPS) - 2
    colourscale.extend(
        [
            high_contrast_start
            + (index - 1) / upper_intervals * (1.0 - high_contrast_start),
            colour,
        ]
        for index, colour in enumerate(_VIRIDIS_STOPS[2:], start=2)
    )
    return colourscale


def build_figure(
    data: HeatmapData,
    *,
    surface: bool,
    log_colour: bool,
    top_down: bool = False,
    gas_labels: bool = True,
) -> go.Figure:
    """Build a Plotly heat map or rotatable 3D surface."""

    z_values = transformed_values(data.values, log_colour)
    colour_scale = high_end_log_colorscale(z_values) if log_colour else "Viridis"
    time_labels = [
        time.isoformat(sep=" ", timespec="milliseconds") for time in data.times
    ]
    signal_label = "log10 ion current (A)" if log_colour else "Ion current (A)"
    hover = (
        "Time: %{y}<br>Mass: %{x:.2f} amu/e<br>"
        + signal_label
        + ": %{z:.4g}<extra></extra>"
    )
    visible_gases = [
        (mass, label)
        for mass, label in COMMON_GAS_PEAKS
        if data.masses[0] <= mass <= data.masses[-1]
    ]

    if surface:
        figure = go.Figure(
            go.Surface(
                x=data.masses,
                y=time_labels,
                z=z_values,
                colorscale=colour_scale,
                colorbar=dict(title=signal_label),
                hovertemplate=hover,
                connectgaps=False,
            )
        )
        camera = (
            dict(eye=dict(x=0.0, y=0.0, z=2.5), projection=dict(type="orthographic"))
            if top_down
            else dict(eye=dict(x=1.55, y=-1.55, z=1.15))
        )
        surface_annotations: list[dict[str, object]] = []
        if gas_labels:
            finite_values = [
                value for row in z_values for value in row if value is not None
            ]
            plot_floor = min(finite_values, default=0.0)
            surface_annotations = [
                dict(
                    x=mass,
                    y=time_labels[-1],
                    z=plot_floor,
                    text=label,
                    textangle=-45,
                    xanchor="left",
                    yshift=12 + 10 * (index % 2),
                    showarrow=False,
                    font=dict(size=10, color="#555555"),
                )
                for index, (mass, label) in enumerate(visible_gases)
            ]
        figure.update_layout(
            scene=dict(
                xaxis=dict(title="Mass-to-charge ratio (amu/e)"),
                yaxis=dict(
                    title="Acquisition time",
                    type="category",
                    categoryorder="array",
                    categoryarray=time_labels,
                ),
                zaxis_title=signal_label,
                camera=camera,
                aspectmode="manual",
                aspectratio=dict(x=1.7, y=1.25, z=0.7),
                annotations=surface_annotations,
            )
        )
    else:
        figure = go.Figure(
            go.Heatmap(
                x=data.masses,
                y=time_labels,
                z=z_values,
                colorscale=colour_scale,
                colorbar=dict(title=signal_label),
                hovertemplate=hover,
                connectgaps=False,
            )
        )
        figure.update_layout(
            xaxis_title="Mass-to-charge ratio (amu/e)",
            yaxis_title="Acquisition time (time-ordered scans)",
            yaxis=dict(type="category", categoryorder="array", categoryarray=time_labels),
        )
        if gas_labels:
            for mass, label in visible_gases:
                figure.add_annotation(
                    x=mass,
                    y=1,
                    xref="x",
                    yref="paper",
                    text=f"{label} ({mass:g})",
                    textangle=-90,
                    yanchor="bottom",
                    yshift=4,
                    showarrow=False,
                    font=dict(size=10, color="#555555"),
                )

    figure.update_layout(
        template="plotly_white",
        title="Automated analogue RGA history",
        margin=dict(l=85, r=35, t=65, b=70),
        uirevision="analogue-rga-history",
    )
    return figure


class _LoadSignals(QObject):
    finished = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)
    progress = pyqtSignal(int, int, int)


class _LoadWorker(QRunnable):
    def __init__(
        self,
        generation: int,
        paths: Sequence[Path],
        max_scans: int | None,
    ) -> None:
        super().__init__()
        self.generation = generation
        self.paths = tuple(paths)
        self.max_scans = max_scans
        self.signals = _LoadSignals()

    def run(self) -> None:
        try:
            result = load_heatmap_data(
                self.paths,
                lambda completed, total: self.signals.progress.emit(
                    self.generation, completed, total
                ),
                self.max_scans,
            )
        except (OSError, ValueError) as exc:
            self.signals.failed.emit(self.generation, str(exc))
            return
        self.signals.finished.emit(self.generation, result)


class AnalogHeatmapWindow(QMainWindow):
    """Qt window for 2D and 3D views of automated analogue RGA scans."""

    def __init__(self, initial_folder: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Analogue RGA time heat-map visualiser")
        self.resize(1320, 820)
        self._folder = initial_folder
        self._data: HeatmapData | None = None
        self._generation = 0
        self._thread_pool = QThreadPool(self)
        self._workers: list[_LoadWorker] = []

        self.open_folder_button = QPushButton("Open Analog folder…")
        self.reload_button = QPushButton("Load / refresh")
        self.folder_label = QLabel(
            str(initial_folder) if initial_folder else "No folder selected"
        )
        self.folder_label.setWordWrap(True)
        self.max_scans_spin = QSpinBox()
        self.max_scans_spin.setRange(0, 100000)
        self.max_scans_spin.setValue(30)
        self.max_scans_spin.setSpecialValueText("All")
        self.max_scans_spin.setToolTip(
            "Display exactly the newest N scans; choose All for the full archive"
        )
        self.view_combo = QComboBox()
        self.view_combo.addItems(["2D heat map", "3D surface"])
        self.log_colour_checkbox = QCheckBox("Log10 ion-current colour / height")
        self.log_colour_checkbox.setChecked(True)
        self.gas_labels_checkbox = QCheckBox("Show common gas labels")
        self.gas_labels_checkbox.setChecked(True)
        self.top_down_button = QPushButton("Flatten to top-down view")
        self.top_down_button.setEnabled(False)
        self.status_label = QLabel("Choose or load an automated Analog folder.")
        self.status_label.setWordWrap(True)

        controls = QWidget()
        controls.setMaximumWidth(330)
        controls_layout = QVBoxLayout(controls)
        controls_layout.addWidget(self.open_folder_button)
        controls_layout.addWidget(self.reload_button)
        controls_layout.addWidget(self.folder_label)
        controls_layout.addSpacing(8)
        controls_layout.addWidget(QLabel("Newest scans to display (0 = all)"))
        controls_layout.addWidget(self.max_scans_spin)
        controls_layout.addWidget(QLabel("View"))
        controls_layout.addWidget(self.view_combo)
        controls_layout.addWidget(self.log_colour_checkbox)
        controls_layout.addWidget(self.gas_labels_checkbox)
        controls_layout.addWidget(self.top_down_button)
        controls_layout.addStretch(1)
        controls_layout.addWidget(self.status_label)

        self.plot_view = PlotlyPlotView()
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addWidget(controls)
        layout.addWidget(self.plot_view, 1)
        self.setCentralWidget(central)

        self.open_folder_button.clicked.connect(self._choose_folder)
        self.reload_button.clicked.connect(self.load_folder)
        self.view_combo.currentIndexChanged.connect(self._view_changed)
        self.log_colour_checkbox.stateChanged.connect(self._redraw)
        self.gas_labels_checkbox.stateChanged.connect(self._redraw)
        self.top_down_button.clicked.connect(lambda: self._redraw(top_down=True))

        self._show_placeholder()
        if initial_folder is not None and initial_folder.is_dir():
            self.load_folder()

    def _choose_folder(self) -> None:
        start = self._folder or (
            DEFAULT_ANALOG_FOLDER
            if DEFAULT_ANALOG_FOLDER.is_dir()
            else Path.home()
        )
        selected = QFileDialog.getExistingDirectory(
            self, "Choose automated Analog RGA folder", str(start)
        )
        if selected:
            self._folder = Path(selected)
            self.folder_label.setText(selected)
            self.load_folder()

    def load_folder(self) -> None:
        if self._folder is None:
            self._choose_folder()
            return
        try:
            paths = discover_analog_files(self._folder)
        except OSError as exc:
            QMessageBox.warning(self, "Cannot open Analog folder", str(exc))
            return
        if not paths:
            QMessageBox.information(
                self,
                "No automated RGA data",
                "No timestamped Analog .rgadata files were found.",
            )
            return

        self._generation += 1
        generation = self._generation
        scan_limit = self.max_scans_spin.value() or None
        worker = _LoadWorker(generation, paths, scan_limit)
        self._workers.append(worker)
        worker.signals.progress.connect(self._load_progress)
        worker.signals.finished.connect(self._load_finished)
        worker.signals.failed.connect(self._load_failed)
        self.reload_button.setEnabled(False)
        self.status_label.setText(
            f"Loading the newest {scan_limit} scans…"
            if scan_limit is not None
            else f"Loading all scans from {len(paths)} files…"
        )
        self._thread_pool.start(worker)

    def _load_progress(self, generation: int, completed: int, total: int) -> None:
        if generation == self._generation:
            self.status_label.setText(f"Loading file {completed} of {total}…")

    def _load_finished(self, generation: int, result: object) -> None:
        self._discard_worker(generation)
        if generation != self._generation or not isinstance(result, HeatmapData):
            return
        self._data = result
        self.reload_button.setEnabled(True)
        skipped = len(result.skipped_files)
        self.status_label.setText(
            f"Loaded {len(result.times)} scans from {result.source_files} files."
            + (
                f" Skipped {skipped}; first issue: {result.skipped_files[0]}"
                if skipped
                else ""
            )
        )
        self._redraw()

    def _load_failed(self, generation: int, message: str) -> None:
        self._discard_worker(generation)
        if generation != self._generation:
            return
        self.reload_button.setEnabled(True)
        self.status_label.setText(message)
        QMessageBox.warning(self, "Cannot load RGA history", message)

    def _discard_worker(self, generation: int) -> None:
        self._workers = [
            worker for worker in self._workers if worker.generation != generation
        ]

    def _view_changed(self, _index: int) -> None:
        self.top_down_button.setEnabled(self.view_combo.currentIndex() == 1)
        self._redraw()

    def _redraw(self, _state: int = 0, *, top_down: bool = False) -> None:
        if self._data is None:
            return
        self.plot_view.show_figure(
            build_figure(
                self._data,
                surface=self.view_combo.currentIndex() == 1,
                log_colour=self.log_colour_checkbox.isChecked(),
                top_down=top_down,
                gas_labels=self.gas_labels_checkbox.isChecked(),
            )
        )

    def _show_placeholder(self) -> None:
        figure = go.Figure()
        figure.add_annotation(
            text="Load the automated Analog folder to build the time–mass map.",
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
            font=dict(size=16, color="#666666"),
        )
        figure.update_layout(template="plotly_white")
        self.plot_view.show_figure(figure)

    def closeEvent(self, event: Optional[QCloseEvent]) -> None:  # noqa: N802
        self._generation += 1
        self._thread_pool.clear()
        self.plot_view.cleanup()
        super().closeEvent(event)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "folder", nargs="?", type=Path, help="initial automated Analog folder"
    )
    args = parser.parse_args()
    initial = args.folder
    if initial is None and DEFAULT_ANALOG_FOLDER.is_dir():
        initial = DEFAULT_ANALOG_FOLDER

    application = QApplication(sys.argv)
    window = AnalogHeatmapWindow(initial)
    window.show()
    raise SystemExit(application.exec())


if __name__ == "__main__":
    main()
