"""Transfer fractions (ported from Momentum_Bells_test's monitor_momentum.m): orders found in
the T histogram, counted per shot inside the XY box, and editable from the detection."""
from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtWidgets import QWidget

from helab.analysis.dataset_view import DatasetView, build_view
from helab.analysis.parameter_tree import build_tree, tree_values
from helab.analysis.parameters import effective
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.models.ScriptTreeSelector import AnalysisInstance
from helab.scripts.standard import transfer_fractions as tf
from helab.utils.folder_cache import Dataset

CENTRE, SPACING, SIGMA = 2.1375, 0.0125, 0.001
POPULATIONS = {-2: 20, -1: 100, 0: 600, 1: 250, 2: 30}


def shot_events(rng: np.random.Generator, shot: int, scale: int = 1) -> Any:
    parts = []
    for order, count in POPULATIONS.items():
        count = count * scale + (shot if order == 1 else 0)  # +1 grows with the shot number
        times = rng.normal(CENTRE + order * SPACING, SIGMA, count)
        parts.append(np.column_stack((times, rng.normal(0, 0.005, (count, 2)))))
    hot_spot = np.column_stack((rng.normal(CENTRE, SIGMA, 400), np.full(400, 0.05), np.zeros(400)))
    return np.concatenate(parts + [hot_spot])


def view(shots: dict[int, Any]) -> DatasetView:
    for array in shots.values():
        array.setflags(write=False)
    fingerprint = [[shot, 100 + shot, 1_000 + shot] for shot in sorted(shots)]
    return build_view(Dataset("/data/root/run_1", "sig-1", shots, {"fingerprint": fingerprint, "source": "files",
                                                                   "loaded_at": 1_700_000_000.0}, 0))


def context(data: DatasetView, values: dict[str, Any] | None = None) -> AnalysisContext:
    script = tf.TransferFractions()
    return AnalysisContext("a1", "Plot", data, effective(script.parameters("Plot"), values),
                           script.get_metadata().identity())


@pytest.fixture(params=[3, 5, 8, 13])
def run(request: pytest.FixtureRequest) -> DatasetView:
    rng = np.random.default_rng(request.param)
    shots = {shot: shot_events(rng, shot) for shot in range(1, 11)}
    shots[11] = shot_events(rng, 11)[:30]  # too few counts in the box: left out
    return view(shots)


def test_orders_are_found_and_counted_inside_the_box(run: DatasetView) -> None:
    script = tf.TransferFractions()
    data = script.compute("Plot", context(run))
    assert isinstance(data, tf.Fractions) and data.auto
    assert data.orders.centre == pytest.approx(CENTRE, abs=2e-4)
    assert data.orders.spacing == pytest.approx(SPACING, rel=0.02)
    assert data.orders.half_width == pytest.approx(data.orders.spacing / 2)
    assert data.orders.numbers == (-2, -1, 0, 1, 2)
    assert data.shots.tolist() == list(range(1, 11)) and data.chosen == 11 and data.total_shots == 11
    assert data.notes == ("1 shot with ≤ 50 counts left out",)
    # The hot spot at X = 50 mm is outside the box: order 0 holds its own 600 (± a tail).
    counts = data.counts[0]
    assert abs(int(counts[2]) - 600) <= 5 and abs(int(counts[3]) - 251) <= 5
    fractions = data.fractions
    assert np.allclose(fractions.sum(axis=1), 1.0)
    assert fractions[-1, 3] > fractions[0, 3]  # +1 grows with the shot number
    assert script.detected_parameters("Plot", AnalysisResult.of(context(run), "completed", data)) == {
        "centre": data.orders.centre, "spacing": data.orders.spacing}


def test_manual_orders_shots_and_no_box(run: DatasetView) -> None:
    script = tf.TransferFractions()
    values = {"orders_mode": tf.MANUAL, "centre": CENTRE, "spacing": SPACING, "half_width": 0.003,
              "orders_each_side": 1, "xy_half": 0.0, "shots": "range", "first_shot": 3, "last_shot": 5}
    data = script.compute("Plot", context(run, values))
    assert not data.auto and data.orders == tf.Orders(CENTRE, SPACING, 0.003, 1)
    assert data.shots.tolist() == [3, 4, 5] and data.notes == ()
    assert int(data.counts[0, 1]) > 900  # order 0 now holds the hot spot too
    assert script.detected_parameters("Plot", AnalysisResult.of(context(run, values), "completed", data)) == {}
    _, settings = script.describe_run("Plot", effective(script.parameters("Plot"), values), run)
    assert settings == "shots 3–5 · manual orders ±1 · no XY limit · > 50 counts"


def test_search_range_and_a_lone_peak() -> None:
    rng = np.random.default_rng(1)
    lone = view({shot: np.column_stack((rng.normal(1.0, SIGMA, 500), np.zeros((500, 2)))) for shot in (1, 2)})
    script = tf.TransferFractions()
    data = script.compute("Plot", context(lone))
    assert data.orders.centre == pytest.approx(1.0, abs=2e-4) and data.orders.spacing == tf.SPACING.default
    assert data.notes == ("no side peak found: spacing as set",)
    outside = script.compute("Plot", context(lone, {"search_min": 2.0, "search_max": 3.0}))
    assert outside.notes == ("no events in the search range: orders as set",)
    assert outside.orders.centre == tf.CENTRE.default


def test_render_and_detected_values_fill_the_settings(run: DatasetView, qtbot: QtBot) -> None:
    script = tf.TransferFractions()
    result = AnalysisResult.of(context(run), "completed", script.compute("Plot", context(run)))
    widget = script.render(result)
    qtbot.addWidget(widget)
    assert isinstance(widget, QWidget)
    empty = view({})
    nothing = AnalysisResult.of(context(empty), "completed", script.compute("Plot", context(empty)))
    qtbot.addWidget(script.render(nothing))
    # A run's detection goes into the (hidden, manual) centre and spacing, for switching to manual.
    instance = AnalysisInstance(script.get_metadata(), script, "Plot", run, "1", None)
    specs = script.parameters("Plot")
    instance.parameter_root = build_tree(specs)
    instance._show_detected(result)
    values = tree_values(instance.parameter_root, specs)
    assert values["centre"] == pytest.approx(result.data.orders.centre)
    assert values["spacing"] == pytest.approx(result.data.orders.spacing)
    instance.close()
