"""Offscreen renders of the density images on synthetic data (a pulsed atom laser)."""
import os
import sys
import time

S = os.path.dirname(os.path.abspath(__file__))
for name, sub in (("HELAB_DIR_TEMPS_OVERRIDE", "t"), ("HELAB_DIR_CACHES_OVERRIDE", "c"), ("HELAB_APP_DIR_OVERRIDE", "a")):
    os.makedirs(f"{S}/env/{sub}", exist_ok=True)
    os.environ[name] = f"{S}/env/{sub}"
import numpy as np  # noqa: E402
from helab.scripts.standard.density_images import PROJECTIONS, DensityImages  # noqa: E402
from helab.analysis.dataset_view import build_view  # noqa: E402
from helab.analysis.parameters import effective  # noqa: E402
from helab.analysis.results import AnalysisContext, AnalysisResult  # noqa: E402
from helab.utils.folder_cache import Dataset  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
out = sys.argv[1] if len(sys.argv) > 1 else S
shots = int(sys.argv[2]) if len(sys.argv) > 2 else 20
rng = np.random.default_rng(1)


def shot(n: int) -> np.ndarray:
    # Pulses every 2 ms in T, drifting in X, plus a flat background.
    t = 0.415 + 0.002 * rng.integers(0, 6, n) + rng.normal(0, 0.0002, n)
    x = rng.normal(0, 0.004, n) + 0.3 * (t - 0.42)
    y = rng.normal(0.001, 0.003, n)
    bg = rng.uniform([0.41, -0.02, -0.02], [0.43, 0.02, 0.02], (n // 10, 3))
    return np.vstack([np.column_stack([t, x, y]), bg])


data = {s: shot(4000) for s in range(1, shots + 1)}
for a in data.values():
    a.setflags(write=False)
ds = Dataset("/data/root/synthetic_run", "sig", data,
             {"fingerprint": [[s, 1, 1] for s in data], "source": "merged", "loaded_at": 1.0}, 0)
view = build_view(ds)
sc = DensityImages()
for proj in PROJECTIONS:
    vals = effective(sc.parameters("Plot"), {"projection": proj, "blur": 1.0, "colour_scale": "sqrt",
                                             "quantity": "rate per shot", "highlight_newest": True})
    ctx = AnalysisContext("a", "Plot", view, vals, sc.get_metadata().identity())
    t0 = time.time()
    d = sc.compute("Plot", ctx)
    print(proj, d.image.shape, d.events, d.total, round(time.time() - t0, 3), d.time_unit, d.quantity_text())
    r = AnalysisResult.of(ctx, "completed", d)
    w = sc.render(r)
    w.resize(760, 520)
    w.show()
    app.processEvents()
    print(sc.update(w, r), sc.describe_run("Plot", vals, view))
    app.processEvents()
    w.grab().save(f"{out}/render-{proj}.png")
