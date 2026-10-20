"""Render Mean X, Y against T and T spectrum on synthetic data to PNGs (offscreen), to look at
them without the app: ``python .ai/sessions/2026-10-20-claude-dld-d5-d6/render_plots.py <out dir>``
from the repository root."""
from __future__ import annotations

import os
import sys
import tempfile

scratch = tempfile.mkdtemp(prefix="helab-render-")
for kind in ("CACHES", "TEMPS"):
    os.environ.setdefault(f"HELAB_DIR_{kind}_OVERRIDE", os.path.join(scratch, kind.lower()))
os.environ.setdefault("HELAB_APP_DIR_OVERRIDE", os.path.join(scratch, "app"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))

from PyQt6.QtWidgets import QApplication  # noqa: E402

import test_mean_position as d5  # noqa: E402
import test_t_spectrum as d6  # noqa: E402


def main(out: str) -> None:
    app = QApplication.instance() or QApplication([])
    os.makedirs(out, exist_ok=True)
    cases = [("mean_position.png", d5.SCRIPT, d5.run(d5.sloshing(), {**d5.FULL, "t_bin": 0.5e-3, "spectrum": True})),
             ("t_spectrum.png", d6.SCRIPT, d6.run(d6.modulated(envelope=0.01), {**d6.FULL, "peaks_above": 500.0}))]
    for name, script, result in cases:
        widget = script.render(result)
        widget.resize(1000, 900)
        widget.show()
        app.processEvents()
        widget.grab().save(os.path.join(out, name))
        print(name, script.describe_run("Plot", result.parameters, d5.sloshing(shots=1, per_shot=10))[1], "·",
              script.describe_result("Plot", result))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
