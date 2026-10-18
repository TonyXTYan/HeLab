#!/usr/bin/env python3
"""A QWebEngineView that renders Plotly figures via temporary HTML files."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import plotly.graph_objects as go
from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView


class PlotlyPlotView(QWebEngineView):
    """Renders Plotly figures, cleaning up its temporary HTML files.

    Each ``show_figure`` call writes a fresh temp file and loads it; the
    previous file is only deleted once the new one has finished loading, so
    the view never briefly shows a blank page while swapping plots.

    As a non-top-level child widget, this view never receives its own
    ``closeEvent`` when the owning window closes, so callers must invoke
    :meth:`cleanup` from their own ``closeEvent`` to remove any remaining
    temporary files.
    """

    def __init__(self) -> None:
        super().__init__()
        self._plot_path: Optional[Path] = None
        self._obsolete_plot_paths: list[Path] = []
        self.loadFinished.connect(self._plot_loaded)

    def show_figure(self, figure: go.Figure) -> None:
        html = figure.to_html(
            full_html=True,
            include_plotlyjs=True,
            config={"displaylogo": False, "responsive": True},
        )
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="rgadata_plot_",
            suffix=".html",
            delete=False,
        ) as handle:
            handle.write(html)
            new_path = Path(handle.name)

        if self._plot_path is not None:
            self._obsolete_plot_paths.append(self._plot_path)
        self._plot_path = new_path
        self.load(QUrl.fromLocalFile(str(new_path)))

    def _plot_loaded(self, _success: bool) -> None:
        obsolete, self._obsolete_plot_paths = self._obsolete_plot_paths, []
        for path in obsolete:
            path.unlink(missing_ok=True)

    def cleanup(self) -> None:
        """Remove any temporary plot HTML files. Call from the owning window's closeEvent."""

        for path in [*self._obsolete_plot_paths, self._plot_path]:
            if path is not None:
                path.unlink(missing_ok=True)
        self._obsolete_plot_paths = []
        self._plot_path = None
