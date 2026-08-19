#!/usr/bin/env python3
"""Compare two individual scans from the same or different .rgadata files."""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .plotly_view import PlotlyPlotView
from .rga_visualiser import COMMON_GAS_PEAKS, RGAData, Scan, parse_rgadata
from .rgadata_compare import DEFAULT_RGADATA_FOLDER, normalise_spectrum


def align_masses(
    masses_a: Sequence[float],
    values_a: Sequence[float],
    masses_b: Sequence[float],
    values_b: Sequence[float],
) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    """Return (masses, values_a, values_b) on a shared mass grid.

    If the two grids already match, they're returned unchanged. Otherwise
    the overlapping mass range is used, with scan A's own points as the
    common grid and scan B linearly interpolated onto it.
    """

    if tuple(masses_a) == tuple(masses_b):
        return tuple(masses_a), tuple(values_a), tuple(values_b)

    low = max(masses_a[0], masses_b[0])
    high = min(masses_a[-1], masses_b[-1])
    if low > high:
        raise ValueError("Scans have no overlapping mass range")

    common = tuple(mass for mass in masses_a if low <= mass <= high)
    if not common:
        raise ValueError("Scans have no overlapping mass range")

    aligned_a = tuple(
        value for mass, value in zip(masses_a, values_a) if low <= mass <= high
    )
    aligned_b = tuple(np.interp(common, masses_b, values_b).tolist())
    return common, aligned_a, aligned_b


def compute_difference(
    masses_a: Sequence[float],
    values_a: Sequence[float],
    masses_b: Sequence[float],
    values_b: Sequence[float],
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Return (masses, values_b - values_a) on a shared mass grid.

    Scan A is the baseline: a higher scan B shows up as positive.
    """

    masses, aligned_a, aligned_b = align_masses(masses_a, values_a, masses_b, values_b)
    diff = tuple(b - a for a, b in zip(aligned_a, aligned_b))
    return masses, diff


class _ScanPicker(QWidget):
    """File-open + scan-selection controls for one side (A or B) of the diff."""

    def __init__(self, label: str, initial_folder: Path) -> None:
        super().__init__()
        self._initial_folder = initial_folder
        self.data: Optional[RGAData] = None
        self.path: Optional[Path] = None

        self.open_button = QPushButton(f"Open file for {label}…")
        self.path_label = QLabel("No file selected")
        self.path_label.setWordWrap(True)
        self.scan_combo = QComboBox()
        self.scan_combo.setEnabled(False)

        box = QGroupBox(f"Scan {label}")
        layout = QVBoxLayout(box)
        layout.addWidget(self.open_button)
        layout.addWidget(self.path_label)
        layout.addWidget(self.scan_combo)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)

        self.open_button.clicked.connect(self._choose_file)

    def _choose_file(self) -> None:
        start = str(self.path.parent if self.path is not None else self._initial_folder)
        selected, _ = QFileDialog.getOpenFileName(
            self, "Choose .rgadata file", start, "RGA data files (*.rgadata)"
        )
        if selected:
            self.load_file(Path(selected))

    def load_file(self, path: Path) -> None:
        try:
            data = parse_rgadata(path)
        except (OSError, ValueError, struct.error) as exc:
            QMessageBox.warning(self, "Cannot read RGA data", f"{path.name}\n\n{exc}")
            return

        self.data = data
        self.path = path
        self.path_label.setText(path.name)
        self.scan_combo.clear()
        for index, scan in enumerate(data.scans):
            self.scan_combo.addItem(f"Scan {index + 1}  (+{scan.elapsed_seconds:.3f} s)")
        self.scan_combo.setCurrentIndex(len(data.scans) - 1)
        self.scan_combo.setEnabled(True)

    def selected_scan(self) -> Optional[Scan]:
        if self.data is None or self.scan_combo.currentIndex() < 0:
            return None
        return self.data.scans[self.scan_combo.currentIndex()]

    def label(self) -> str:
        if self.path is None:
            return "(no file)"
        return f"{self.path.name} — scan {self.scan_combo.currentIndex() + 1}"


class ScanDiffWindow(QMainWindow):
    """Overlay and difference plot for two individually picked scans."""

    def __init__(self, initial_folder: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("RGA scan difference")
        self.resize(1280, 780)

        folder = initial_folder or DEFAULT_RGADATA_FOLDER

        self.picker_a = _ScanPicker("A", folder)
        self.picker_b = _ScanPicker("B", folder)
        self.swap_button = QPushButton("Swap A ↔ B")
        self.normalise_checkbox = QCheckBox("Normalise each scan to its own maximum")
        self.gas_markers_checkbox = QCheckBox("Show common gas markers")
        self.gas_markers_checkbox.setChecked(True)
        self.log_scale_checkbox = QCheckBox("Log Y scale (top panel)")
        self.log_scale_checkbox.setChecked(True)
        self.diff_log_scale_checkbox = QCheckBox("Log Y scale (bottom panel)")
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.addWidget(self.picker_a)
        controls_layout.addWidget(self.picker_b)
        controls_layout.addWidget(self.swap_button)
        controls_layout.addWidget(self.normalise_checkbox)
        controls_layout.addWidget(self.gas_markers_checkbox)
        controls_layout.addWidget(self.log_scale_checkbox)
        controls_layout.addWidget(self.diff_log_scale_checkbox)
        controls_layout.addWidget(self.status_label)
        controls_layout.addStretch(1)

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

        self.picker_a.open_button.clicked.connect(self._update_plot)
        self.picker_b.open_button.clicked.connect(self._update_plot)
        self.picker_a.scan_combo.currentIndexChanged.connect(self._update_plot)
        self.picker_b.scan_combo.currentIndexChanged.connect(self._update_plot)
        self.swap_button.clicked.connect(self._swap)
        self.normalise_checkbox.stateChanged.connect(self._update_plot)
        self.gas_markers_checkbox.stateChanged.connect(self._update_plot)
        self.log_scale_checkbox.stateChanged.connect(self._update_plot)
        self.diff_log_scale_checkbox.stateChanged.connect(self._update_plot)

        self._update_plot()

    def _swap(self) -> None:
        # _ScanPicker widgets keep their own layout position (under the
        # "A"/"B" group box titles), so swap the loaded file/scan each one
        # displays rather than the widgets themselves.
        path_a, index_a = self.picker_a.path, self.picker_a.scan_combo.currentIndex()
        path_b, index_b = self.picker_b.path, self.picker_b.scan_combo.currentIndex()
        if path_a is None or path_b is None:
            return
        self.picker_a.load_file(path_b)
        self.picker_a.scan_combo.setCurrentIndex(index_b)
        self.picker_b.load_file(path_a)
        self.picker_b.scan_combo.setCurrentIndex(index_a)
        self._update_plot()

    def _update_plot(self) -> None:
        scan_a = self.picker_a.selected_scan()
        scan_b = self.picker_b.selected_scan()
        figure = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            row_heights=[0.65, 0.35],
            vertical_spacing=0.06,
            subplot_titles=("Scans A and B", "Difference (B − A)"),
        )

        data_a, data_b = self.picker_a.data, self.picker_b.data
        if scan_a is None or scan_b is None or data_a is None or data_b is None:
            self.status_label.setText("Pick a file and scan for both A and B.")
            self.plot_view.show_figure(figure)
            return

        try:
            masses_a = data_a.masses
            masses_b = data_b.masses
            values_a = scan_a.values
            values_b = scan_b.values
            if self.normalise_checkbox.isChecked():
                values_a = normalise_spectrum(values_a)
                values_b = normalise_spectrum(values_b)

            diff_masses, diff_values = compute_difference(
                masses_a, values_a, masses_b, values_b
            )
        except (ValueError, ZeroDivisionError) as exc:
            self.status_label.setText(str(exc))
            self.plot_view.show_figure(figure)
            return

        log_scale = self.log_scale_checkbox.isChecked()
        top_a = [v if v > 0 else None for v in values_a] if log_scale else list(values_a)
        top_b = [v if v > 0 else None for v in values_b] if log_scale else list(values_b)

        diff_log_scale = self.diff_log_scale_checkbox.isChecked()
        bottom_diff = (
            [v if v > 0 else None for v in diff_values] if diff_log_scale else list(diff_values)
        )

        figure.add_trace(
            go.Scatter(x=masses_a, y=top_a, mode="lines", name=f"A: {self.picker_a.label()}"),
            row=1,
            col=1,
        )
        figure.add_trace(
            go.Scatter(x=masses_b, y=top_b, mode="lines", name=f"B: {self.picker_b.label()}"),
            row=1,
            col=1,
        )
        figure.add_trace(
            go.Scatter(
                x=diff_masses,
                y=bottom_diff,
                mode="lines",
                name="B − A",
                line=dict(color="#9333ea"),
            ),
            row=2,
            col=1,
        )
        # plotly's add_hline/add_vline stubs infer row/col as `str` from
        # their "all" default, so an explicit int row triggers a false
        # positive under pyright even though the runtime accepts one.
        figure.add_hline(y=0, line_width=1, line_dash="dot", line_color="#999999", row=2, col=1)  # pyright: ignore[reportArgumentType]

        if self.gas_markers_checkbox.isChecked():
            mass_min = min(masses_a[0], masses_b[0])
            mass_max = max(masses_a[-1], masses_b[-1])
            for mass, label in COMMON_GAS_PEAKS:
                if mass_min <= mass <= mass_max:
                    # Label only the top panel (row=1); an unlabelled line
                    # marks the same mass on the diff panel below.
                    figure.add_vline(x=mass, line_width=1, line_dash="dot", line_color="#999999", row=1, col=1, annotation_text=f"{label} ({mass})", annotation_position="top", annotation_textangle=-90, annotation_font_size=10, annotation_font_color="#666666", annotation_yshift=4)  # pyright: ignore[reportArgumentType]
                    figure.add_vline(x=mass, line_width=1, line_dash="dot", line_color="#999999", row=2, col=1)  # pyright: ignore[reportArgumentType]

        y_title = "Normalised ion current" if self.normalise_checkbox.isChecked() else "Ion current (A)"
        figure.update_yaxes(title_text=y_title, type="log" if log_scale else "linear", row=1, col=1)
        figure.update_yaxes(
            title_text="Difference", type="log" if diff_log_scale else "linear", row=2, col=1
        )
        figure.update_xaxes(title_text="Mass-to-charge ratio (amu/e)", row=2, col=1)
        figure.update_layout(
            template="plotly_white",
            hovermode="x unified",
            margin=dict(l=75, r=25, t=100, b=65),
            legend=dict(
                yanchor="top",
                y=0.99,
                xanchor="right",
                x=0.99,
                bgcolor="rgba(255,255,255,0.85)",
                bordercolor="#cccccc",
                borderwidth=1,
            ),
        )

        self.status_label.setText(f"A: {self.picker_a.label()}\nB: {self.picker_b.label()}")
        self.plot_view.show_figure(figure)

    def closeEvent(  # noqa: N802 - Qt API name
        self,
        event: Optional[QCloseEvent],
    ) -> None:
        self.plot_view.cleanup()
        super().closeEvent(event)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file_a", nargs="?", type=Path, help="scan A's .rgadata file")
    parser.add_argument("file_b", nargs="?", type=Path, help="scan B's .rgadata file")
    parser.add_argument("--scan-a", type=int, help="1-based scan number for A (default: last)")
    parser.add_argument("--scan-b", type=int, help="1-based scan number for B (default: last)")
    args = parser.parse_args()

    application = QApplication(sys.argv)
    window = ScanDiffWindow()
    if args.file_a is not None:
        window.picker_a.load_file(args.file_a)
        if args.scan_a is not None:
            window.picker_a.scan_combo.setCurrentIndex(args.scan_a - 1)
    if args.file_b is not None:
        window.picker_b.load_file(args.file_b)
        if args.scan_b is not None:
            window.picker_b.scan_combo.setCurrentIndex(args.scan_b - 1)
    window.show()
    raise SystemExit(application.exec())


if __name__ == "__main__":
    main()
