"""The plots that save their results (result caching R2: Correlations, Release time): each run's
data is packed without pickle, read back in another process, and the restored result has the same
record and draws the same; what a plot keeps between runs (Correlations' box and detection) keeps a
run out of the cache, and a Live rerun's or an incomplete count's result isn't saved."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pyqtgraph as pg
import pytest
from PyQt6.QtWidgets import QLabel, QWidget
from pytestqt.qtbot import QtBot

from helab.analysis import result_cache, result_codec
from helab.analysis.results import AnalysisResult
from helab.scripts.base import DatasetAnalysis
from helab.scripts.dld import correlations_plot
import test_correlations_plot as correlation_tests
import test_release_time_plot as release_tests

CASES: dict[str, tuple[DatasetAnalysis, Callable[[], AnalysisResult]]] = {
    "correlations radial": (correlation_tests.SCRIPT, lambda: correlation_tests.run(
        correlation_tests.txy_view(correlation_tests.thermal_velocities(1, shots=12)), correlation_tests.RADIAL)),
    "correlations 1D": (correlation_tests.SCRIPT, lambda: correlation_tests.run(
        correlation_tests.txy_view(correlation_tests.thermal_velocities(2, shots=12)))),
    "release time": (release_tests.SCRIPT, lambda: release_tests.run(release_tests.cloud_view(shots=8)[0],
                                                                    {"n_boot": 20})),
}


def restored(script: DatasetAnalysis, result: AnalysisResult) -> AnalysisResult:
    packed = result_codec.pack(*script.cache_pack("Plot", result.data))
    record = json.loads(json.dumps(result_cache.record_of(result)))
    return result_cache.result_from(record, script.cache_unpack("Plot", *result_codec.unpack(packed)))


def drawn(widget: QWidget) -> list[Any]:
    """What a plot shows: its labels' text and its items' data, in order."""
    shown: list[Any] = [label.text() for label in widget.findChildren(QLabel)]
    for view in widget.findChildren(pg.GraphicsView):
        for item in view.items():
            if isinstance(item, pg.PlotDataItem):
                x, y = item.getData()
                shown.append(("curve", None if x is None else np.asarray(x).tolist(),
                              None if y is None else np.asarray(y).tolist()))
            elif isinstance(item, pg.ImageItem) and item.image is not None:
                shown.append(("image", np.asarray(item.image).tolist()))
            elif isinstance(item, pg.TextItem):
                shown.append(("text", item.toPlainText()))
    return shown


@pytest.mark.parametrize("case", CASES)
def test_a_saved_result_reads_back_and_draws_the_same(qtbot: QtBot, case: str) -> None:
    script, make = CASES[case]
    assert script.cache_supported("Plot")
    result = make()
    assert script.cache_result("Plot", result)
    back = restored(script, result)
    assert script.result_found("Plot", back.data) == script.result_found("Plot", result.data)
    original, again = script.render(result), script.render(back)
    qtbot.addWidget(original)
    qtbot.addWidget(again)
    assert drawn(again) == drawn(original) and drawn(original)


def test_a_saved_result_reads_back_in_a_new_process(tmp_path: Path) -> None:
    """No pickle and no in-process registry: a fresh interpreter rebuilds it from the file and the
    record (as a plot after a restart does)."""
    script, make = CASES["correlations radial"]
    result = make()
    (tmp_path / "result.npz").write_bytes(result_codec.pack(*script.cache_pack("Plot", result.data)))
    (tmp_path / "record.json").write_text(json.dumps(result_cache.record_of(result)))
    (tmp_path / "found.json").write_text(json.dumps(script.result_found("Plot", result.data), default=str))
    code = (
        "import json, sys\nfrom pathlib import Path\n"
        "from helab.analysis import result_cache, result_codec\n"
        "from helab.scripts.dld.correlations_plot import Correlations\n"
        "folder = Path(sys.argv[1]); script = Correlations()\n"
        "data = script.cache_unpack('Plot', *result_codec.unpack((folder / 'result.npz').read_bytes()))\n"
        "back = result_cache.result_from(json.loads((folder / 'record.json').read_text()), data)\n"
        "found = json.loads(json.dumps(script.result_found('Plot', back.data), default=str))\n"
        "assert found == json.loads((folder / 'found.json').read_text())\n"
        "assert back.data.result.fit.evaluate(back.data.result.centres[:3]).shape == (3,)\n"
        "print('ok')\n")
    ran = subprocess.run([sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True, timeout=120)
    assert ran.returncode == 0 and ran.stdout.strip() == "ok", ran.stderr


def test_correlations_kept_state_keeps_its_runs_out_of_the_cache() -> None:
    script = correlation_tests.SCRIPT
    view = correlation_tests.txy_view(correlation_tests.thermal_velocities(3, shots=10))
    owner = "cache-state-plot"
    assert not script.cache_holds_state("Plot", owner)
    first = correlation_tests.run(view, correlation_tests.RADIAL, owner=owner)
    assert script.cache_holds_state("Plot", owner) and script.cache_result("Plot", first)
    second = correlation_tests.run(view, correlation_tests.RADIAL, owner=owner)  # Keeps the box and t_r.
    assert not script.cache_result("Plot", second)
    script.plot_closed("Plot", owner, correlation_tests.PATH)
    live = correlation_tests.run(view, correlation_tests.RADIAL, live=True)
    assert not script.cache_result("Plot", live)


def test_an_incomplete_count_isnt_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter(range(0, 10_000, 1_000))
    monkeypatch.setattr(correlations_plot, "CLOCK", lambda: float(next(ticks)))
    result = correlation_tests.run(correlation_tests.txy_view(correlation_tests.thermal_velocities(4, shots=10)),
                                   {**correlation_tests.RADIAL, "budget": 1.0})
    data = correlation_tests.data_of(result)
    assert data.result is not None and not data.result.complete
    assert not correlation_tests.SCRIPT.cache_result("Plot", result)


def test_a_live_release_time_isnt_saved() -> None:
    result = release_tests.run(release_tests.cloud_view(shots=4)[0], {"n_boot": 10}, live=True)
    assert not release_tests.SCRIPT.cache_result("Plot", result)
