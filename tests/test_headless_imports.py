"""The analysis core stays Qt-free, for a headless runner (``roadmaps/analysis-job-runner.md``).

The script contract (``helab.scripts.base``), the science modules in ``helab.analysis``, the
follow logic (``follow``), the RAM budget's pure parts (``budget_core``) and the runner's queue
and worker (``runner_core``) import no PyQt6, pyqtgraph, Matplotlib, Dash or Plotly, nor
``helab.utils.constants`` (which imports Qt). The Qt parts live apart: ``live_feed``,
``budget``, ``runner`` and the drawing modules. A new ``helab.analysis`` module must be listed
as one or the other here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pkgutil
import subprocess
import sys

import helab.analysis

HEAVY = ("PyQt6", "pyqtgraph", "matplotlib", "dash", "plotly", "helab.utils.constants")

PURE = (
    "helab.scripts.base",
    *(f"helab.convert.{name}" for name in (
        "backends.reference", "backends.numba_backend", "check", "pipeline", "profile", "raw", "reconstruct", "samples", "timing", "txy")),
    "helab.utils.ram_buffers",
    *(f"helab.analysis.{name}" for name in (
        "bec", "bec_readout", "bootstrap", "budget_core", "constant_layers", "correlations",
        "dataset_view", "display_units", "estimates", "fits", "follow", "hotspots", "identity",
        "masks", "orders", "parameters", "peaks", "physics", "presets", "profiles", "release", "result_cache",
        "result_codec", "result_types", "results", "runner_core", "selection", "spectrum", "stats", "trends",
        "velocity")),
)
# Modules of helab.analysis that use Qt (signals, timers or drawing).
QT = {"backends", "budget", "empty", "live_feed", "overlay", "panes", "parameter_tree", "plot_axes", "plot_text", "runner"}

SCRIPT = """
import importlib, json, sys
for name in sys.argv[1:]:
    importlib.import_module(name)
print(json.dumps(sorted(name for name in %r if name in sys.modules)))
""" % (HEAVY,)

ROOT = Path(__file__).resolve().parents[1]


def test_every_analysis_module_is_listed_as_pure_or_qt() -> None:
    modules = {info.name for info in pkgutil.iter_modules(helab.analysis.__path__)}
    pure = {name.rsplit(".", 1)[1] for name in PURE if name.startswith("helab.analysis.")}
    assert not pure & QT
    assert modules == pure | QT, f"Unlisted: {sorted(modules - pure - QT)}; gone: {sorted((pure | QT) - modules)}"


def test_the_analysis_core_imports_no_qt_or_plotting_library() -> None:
    done = subprocess.run([sys.executable, "-c", SCRIPT, *PURE], capture_output=True, text=True,
                          timeout=120, env=dict(os.environ), cwd=ROOT)
    assert done.returncode == 0, done.stderr
    heavy = json.loads(done.stdout.splitlines()[-1])
    assert heavy == [], f"Imported by the analysis core: {heavy}"
