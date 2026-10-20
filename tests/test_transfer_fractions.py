"""Transfer fractions (ported from Momentum_Bells_test's monitor_momentum.m): orders found in
the T histogram, counted per shot inside the XY box, and editable from the detection."""
from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtWidgets import QLabel, QWidget

from helab.analysis.dataset_view import DatasetView, build_view
from helab.analysis.orders import Fractions, Orders, count_orders, jump
from helab.analysis.parameter_tree import build_tree, tree_values
from helab.analysis.parameters import effective
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.views.plots.instance import AnalysisInstance
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
    assert isinstance(data, Fractions) and data.auto
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
    assert not data.auto and data.orders == Orders(CENTRE, SPACING, 0.003, 1)
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
    assert len(data.notes) == 1 and data.notes[0].startswith("no side peak found beyond order 0's width (")
    assert data.notes[0].endswith(" ms): spacing as set")
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


# Detection edge cases: each gives the right orders or says why not, never a crash or a silent
# wrong order 0.

def orders_events(rng: np.random.Generator, populations: dict[int, int], centre: float = CENTRE,
                  spacing: float = SPACING, sigma: float = SIGMA) -> Any:
    times = np.concatenate([rng.normal(centre + order * spacing, sigma, count) for order, count in populations.items()])
    return np.column_stack((times, rng.normal(0, 0.005, (len(times), 2))))


def shots_of(populations: dict[int, int], count: int = 3, seed: int = 0, **orders: float) -> DatasetView:
    rng = np.random.default_rng(seed)
    return view({shot: orders_events(rng, populations, **orders) for shot in range(1, count + 1)})


def fractions(data: DatasetView, values: dict[str, Any] | None = None) -> Fractions:
    result = tf.TransferFractions().compute("Plot", context(data, values))
    assert isinstance(result, Fractions)
    return result


def rendered(data: DatasetView, values: dict[str, Any] | None, qtbot: QtBot) -> QWidget:
    script = tf.TransferFractions()
    result = AnalysisResult.of(context(data, values), "completed", script.compute("Plot", context(data, values)))
    widget = script.render(result)
    qtbot.addWidget(widget)
    return widget


def pane_text(widget: QWidget) -> str:
    """The empty plot's message."""
    assert isinstance(widget, QLabel)
    return widget.text()


def unsure_notes(data: Fractions) -> list[str]:
    return [note for note in data.notes if "order 0 unsure" in note]


SIDES = {-1: 150, 0: 600, 1: 150}


@pytest.mark.parametrize("seed", range(6))
def test_one_shot_finds_the_orders(seed: int) -> None:
    data = fractions(shots_of({-2: 30, -1: 100, 0: 600, 1: 250, 2: 30}, count=1, seed=seed))
    assert data.orders.centre == pytest.approx(CENTRE, abs=2e-4)
    assert data.orders.spacing == pytest.approx(SPACING, rel=0.02) and data.notes == ()


def test_no_events_and_all_outside_the_box_say_so(qtbot: QtBot) -> None:
    empty = view({1: np.empty((0, 3)), 2: np.empty((0, 3))})
    data = fractions(empty, {"min_counts": 0})
    assert not data.detected and len(data.shots) == 0
    assert "No events in the chosen shots" in pane_text(rendered(empty, {"min_counts": 0}, qtbot))
    rng = np.random.default_rng(2)
    events = orders_events(rng, SIDES)
    events[:, 1] += 0.1  # 100 mm off centre: outside the ±30 mm box
    outside = view({1: events})
    assert not fractions(outside).detected
    text = pane_text(rendered(outside, None, qtbot))
    assert text.startswith("No shot has more than 50 counts in the XY box")
    assert "1 shot with ≤ 50 counts left out" in text


def test_not_a_number_in_t_is_left_out_and_said(qtbot: QtBot) -> None:
    rng = np.random.default_rng(4)
    events = orders_events(rng, SIDES)
    events[:4, 0], events[4:6, 0], events[6, 0] = np.nan, np.inf, -np.inf
    events[7:9, 1] = np.nan  # outside any box, so not counted
    data = fractions(view({1: events}))
    assert data.orders.centre == pytest.approx(CENTRE, abs=2e-4)
    assert data.orders.spacing == pytest.approx(SPACING, rel=0.02)
    assert data.notes == ("7 events with T not a number left out",)
    assert int(data.counts.sum()) <= len(events) - 9
    events = np.full((80, 3), np.nan)
    assert fractions(view({1: events})).notes == ("80 events with T not a number left out",
                                                    "1 shot with ≤ 50 counts left out")
    rendered(view({1: orders_events(rng, SIDES)}), None, qtbot)


def test_a_lone_peak_keeps_the_spacing_and_says_so() -> None:
    data = fractions(shots_of({0: 600}))
    assert data.orders.centre == pytest.approx(CENTRE, abs=2e-4) and data.orders.spacing == tf.SPACING.default
    assert [note.split(" (")[0] for note in data.notes] == ["no side peak found beyond order 0's width"]


@pytest.mark.parametrize("populations", [{-1: 590, 0: 600, 1: 580}, {-1: 100, 0: 300, 1: 600}],
                         ids=["similar heights", "+1 taller"])
def test_another_order_nearly_as_tall_makes_order_0_unsure(populations: dict[int, int]) -> None:
    data = fractions(shots_of(populations))
    # Order 0 is the tallest peak, which may be another order: the plot says so.
    assert data.orders.spacing == pytest.approx(SPACING, rel=0.02)
    notes = unsure_notes(data)
    assert len(notes) == 1 and notes[0].startswith("⚠ order 0 unsure: order ")
    assert notes[0].endswith("set both ends of Search T around order 0, or the orders by hand")
    # Search T around the real order 0 settles it: a plain line names the taller order outside.
    settled = fractions(shots_of(populations), {"search_min": CENTRE - SPACING / 2, "search_max": CENTRE + SPACING / 2})
    assert settled.orders.centre == pytest.approx(CENTRE, abs=2e-4) and not unsure_notes(settled)
    assert any(note.startswith("order ") and "(outside Search T)" in note for note in settled.notes)


def test_a_search_range_holding_only_side_peaks_says_order_0_is_outside() -> None:
    populations = {-2: 30, -1: 100, 0: 600, 1: 250, 2: 100}
    data = fractions(shots_of(populations), {"search_min": CENTRE + SPACING / 2, "search_max": CENTRE + 3 * SPACING})
    assert data.orders.centre == pytest.approx(CENTRE + SPACING, abs=2e-4)  # +1, the tallest in the range
    # Both ends set: the user's word on order 0, so no warning, but a plain line says what's outside.
    assert not unsure_notes(data) and "order −1 (outside Search T) is taller than order 0" in data.notes


def test_orders_closer_than_their_width_are_not_split() -> None:
    data = fractions(shots_of(SIDES, spacing=0.0015))
    assert data.orders.centre == pytest.approx(CENTRE, abs=3e-4) and data.orders.spacing == tf.SPACING.default
    assert [note.split(" (")[0] for note in data.notes] == ["no side peak found beyond order 0's width"]


@pytest.mark.parametrize("seed", range(4))
def test_a_bump_between_the_orders_is_not_taken_for_one(seed: int) -> None:
    # Orders 15 ms apart with a small bump 5 ms after order 0: the nearest peak would make the
    # spacing 5 ms (the real +1 then counting as +3); the reference spacing keeps it 15 ms.
    rng = np.random.default_rng(seed)
    populations = {-1: 150, 0: 600, 1: 250}
    shots = {}
    for shot in range(1, 4):
        orders = orders_events(rng, populations, spacing=0.015)
        bump = np.column_stack((rng.normal(CENTRE + 0.005, 0.0007, 15), np.zeros((15, 2))))
        shots[shot] = np.concatenate((orders, bump))
    data = fractions(view(shots))
    assert data.orders.centre == pytest.approx(CENTRE, abs=2e-4)
    assert data.orders.spacing == pytest.approx(0.015, rel=0.02) and data.notes == ()


def test_the_reference_spacing_guides_auto_and_shows_in_the_settings() -> None:
    data = shots_of({-2: 30, -1: 100, 0: 600, 1: 250, 2: 30})
    # 12.5 ms orders: within 30 % of the 15 ms default, and of 10 ms.
    assert fractions(data).orders.spacing == pytest.approx(SPACING, rel=0.02)
    assert fractions(data, {"reference_spacing": 0.010}).orders.spacing == pytest.approx(SPACING, rel=0.02)
    # Twice the orders' spacing: ±1 lands on ±2, which says the reference is off by a whole order.
    doubled = fractions(data, {"reference_spacing": 0.025, "orders_each_side": 1})
    assert doubled.orders.spacing == pytest.approx(2 * SPACING, rel=0.02)
    # No peak near any multiple: the spacing as set, and the note names the reference.
    far = fractions(shots_of(SIDES), {"reference_spacing": 0.04})
    assert far.orders.spacing == tf.SPACING.default
    assert far.notes[0].startswith("no side peak found beyond order 0's width (")
    assert far.notes[0].endswith(" ms) within 30 % of k × the reference spacing (40 ms): spacing as set")
    script = tf.TransferFractions()
    _, settings = script.describe_run("Plot", effective(script.parameters("Plot"), {}), data)
    assert settings == "auto orders ±2 ~15 ms · XY ±30 mm · > 50 counts"


@pytest.mark.parametrize("seed", range(4))
def test_wide_peaks_say_the_orders_overlap(seed: int) -> None:
    data = fractions(shots_of(SIDES, seed=seed, sigma=0.004))
    assert data.orders.centre == pytest.approx(CENTRE, abs=1e-3)
    assert any(note.startswith("orders overlap: order 0's width (FWHM ") for note in data.notes)
    resolved = fractions(shots_of({-1: 400, 0: 600, 1: 400}, seed=seed, sigma=0.0025))
    assert resolved.orders.spacing == pytest.approx(SPACING, rel=0.05)


@pytest.mark.parametrize("sigma", [1e-6, 2e-5])
def test_narrow_peaks_are_found(sigma: float) -> None:
    data = fractions(shots_of(SIDES, sigma=sigma))
    assert data.orders.centre == pytest.approx(CENTRE, abs=1e-5)
    assert data.orders.spacing == pytest.approx(SPACING, rel=1e-3) and data.notes == ()


def test_stray_events_far_out_and_the_bin_cap() -> None:
    rng = np.random.default_rng(6)

    def with_strays(strays: int, end: float, sigma: float) -> DatasetView:
        return view({shot: np.concatenate((orders_events(rng, SIDES, sigma=sigma),
                                           np.column_stack((rng.uniform(0, end, strays), np.zeros((strays, 2))))))
                     for shot in range(1, 4)})
    # A few per cent of stray events over the whole acquisition, and a few far out: the bins
    # still resolve the orders.
    for data in (with_strays(40, 4.0, 1e-5), with_strays(5, 100.0, 2e-5)):
        found = fractions(data)
        assert found.orders.centre == pytest.approx(CENTRE, abs=1e-4)
        assert found.orders.spacing == pytest.approx(SPACING, rel=1e-2) and found.notes == ()
    # Strays over 100 s that the capped bins can't leave out: they're too coarse, and it says so.
    coarse = fractions(with_strays(400, 100.0, 2e-5))
    assert any("are coarse for order 0, narrow Search T" in note for note in coarse.notes)
    narrowed = fractions(with_strays(400, 100.0, 2e-5), {"search_min": 2.0, "search_max": 2.3})
    assert narrowed.orders.spacing == pytest.approx(SPACING, rel=1e-2)


def test_search_t_ends_open_alone_and_a_reversed_range_says_so() -> None:
    data = shots_of(SIDES)
    script = tf.TransferFractions()
    # From alone: to the last event (it holds only +1, so order 0 is unsure and says so).
    upper = fractions(data, {"search_min": CENTRE + SPACING / 2})
    assert upper.orders.centre == pytest.approx(CENTRE + SPACING, abs=3e-4)
    assert unsure_notes(upper)[0].startswith("⚠ order 0 unsure: order −1 (outside Search T) holds ")
    lower = fractions(data, {"search_max": CENTRE + SPACING / 2})
    assert lower.orders.centre == pytest.approx(CENTRE, abs=2e-4) and lower.notes == ()
    values = {"search_min": 2.2, "search_max": 2.1}
    flipped = fractions(data, values)
    assert flipped.orders.centre == pytest.approx(CENTRE, abs=2e-4)
    assert flipped.notes == ("Search T: from ≥ to, searching every event",)
    assert script.parameter_warnings("Plot", effective(script.parameters("Plot"), values)) == [
        "Search T: from ≥ to, searching every event"]
    manual = effective(script.parameters("Plot"), {**values, "orders_mode": tf.MANUAL})
    assert script.parameter_warnings("Plot", manual) == []


def test_malformed_shots_and_identical_times_do_not_crash(qtbot: QtBot) -> None:
    rng = np.random.default_rng(8)
    same_time = np.column_stack((np.full(200, 2.0), np.zeros((200, 2))))
    data = view({1: np.zeros(5), 2: orders_events(rng, SIDES), 3: same_time})
    for values in (None, {"shots": "range", "first_shot": 3}):
        rendered(data, values, qtbot)
    same = fractions(data, {"shots": "range", "first_shot": 3})
    assert same.orders.centre == 2.0 and same.detected


# Manual mode

def test_a_window_wider_than_half_the_spacing_is_clipped_and_said(qtbot: QtBot) -> None:
    data = shots_of(SIDES)
    script = tf.TransferFractions()
    values = {"orders_mode": tf.MANUAL, "centre": CENTRE, "spacing": SPACING, "half_width": 0.01}
    clipped = fractions(data, values)
    said = ("Window ± 10 ms is over half the spacing: using 6.25 ms, so neighbouring windows touch without "
            "sharing events")
    assert clipped.orders.half_width == SPACING / 2 and clipped.notes == (said,)
    assert script.parameter_warnings("Plot", effective(script.parameters("Plot"), values)) == [said]
    # Every event in the orders' span counts once: the windows touch and are half-open.
    assert np.array_equal(clipped.counts, fractions(data, {**values, "half_width": 0.0}).counts)
    within = fractions(data, {**values, "half_width": SPACING / 2})
    assert within.notes == () and within.orders.half_width == SPACING / 2
    # Auto clips against the spacing it found, and says so in the plot only.
    auto = fractions(data, {"half_width": 0.01})
    assert auto.orders.half_width == pytest.approx(auto.orders.spacing / 2)
    assert auto.notes[0].startswith("Window ± 10 ms")
    assert script.parameter_warnings("Plot", effective(script.parameters("Plot"), {"half_width": 0.01})) == []
    rendered(data, values, qtbot)


def test_a_window_edge_on_an_event_counts_it_once() -> None:
    orders = Orders(1.0, 0.5, 0.25, 1)  # windows [0.25, 0.75), [0.75, 1.25), [1.25, 1.75)
    times = np.array([0.25, 0.75, 1.25, 1.75, 1.0])
    assert count_orders(times, orders).tolist() == [1, 2, 1]


def test_a_centre_outside_the_data_says_where_the_events_are(qtbot: QtBot) -> None:
    data = shots_of(SIDES)
    values = {"orders_mode": tf.MANUAL, "centre": 5.0, "spacing": SPACING}
    outside = fractions(data, values)
    assert not outside.counts.any() and len(outside.shots) == 3
    text = pane_text(rendered(data, values, qtbot))
    assert text.startswith("No events in the orders' windows: order 0 at 5 s, spacing 12.5 ms, and the events counted "
                           "are at T 2.1") and text.endswith(" s (Orders settings)")


def test_shots_with_no_events_in_the_windows_have_no_fractions(qtbot: QtBot) -> None:
    rng = np.random.default_rng(9)
    elsewhere = np.column_stack((rng.normal(3.0, SIGMA, 200), np.zeros((200, 2))))
    data = view({1: orders_events(rng, SIDES), 2: elsewhere, 3: orders_events(rng, SIDES)})
    values = {"orders_mode": tf.MANUAL, "centre": CENTRE, "spacing": SPACING, "orders_each_side": 1}
    result = fractions(data, values)
    assert result.shots.tolist() == [1, 2, 3] and result.counts[1].tolist() == [0, 0, 0]
    assert result.notes == ("1 shot with no events in the windows: no fractions",)
    shares = result.fractions
    assert np.isnan(shares[1]).all() and np.allclose(shares[[0, 2]].sum(axis=1), 1.0)
    rendered(data, values, qtbot)


# Detected values and Live reruns

def test_live_reruns_refill_the_detection_and_keep_what_was_typed(qtbot: QtBot) -> None:
    script = tf.TransferFractions()
    rng = np.random.default_rng(10)
    first = view({shot: orders_events(rng, SIDES) for shot in (1, 2)})
    instance = AnalysisInstance(script.get_metadata(), script, "Plot", first, "1", None)
    specs = script.parameters("Plot")
    instance.parameter_root = build_tree(specs)
    root = instance.parameter_root
    changes: list[str] = []
    for name in ("centre", "spacing"):
        root.child(tf.ORDERS_GROUP, name).sigValueChanged.connect(
            lambda parameter, _value: changes.append(parameter.name()))

    def ran(data: DatasetView) -> AnalysisResult:
        """A run as the plot submits it: with the settings shown when it starts."""
        start = context(data, instance.values())
        return AnalysisResult.of(start, "completed", script.compute("Plot", start))

    one = ran(first)
    instance._show_detected(one)
    assert instance.values()["centre"] == one.data.orders.centre and changes == ["centre", "spacing"]
    # Live adds shots with order 0 a little later: each auto rerun fills in its own detection.
    later = first.with_shots({shot: orders_events(rng, SIDES, centre=CENTRE + 0.002) for shot in (3, 4, 5, 6)})
    two = ran(later)
    assert two.data.orders.centre > one.data.orders.centre + 5e-4
    instance._show_detected(two)
    assert instance.values()["centre"] == two.data.orders.centre
    # The same data again finds the same values: nothing is written (no flicker).
    changes.clear()
    instance._show_detected(ran(later))
    assert changes == []
    # Switching to manual keeps the last detection, and a manual run uses it.
    root.child(tf.ORDERS_GROUP, "orders_mode").setValue(tf.MANUAL)
    manual = ran(later)
    assert (manual.data.orders.centre, manual.data.orders.spacing) == (two.data.orders.centre, two.data.orders.spacing)
    # An auto run still in flight when manual is chosen and a centre typed doesn't overwrite it.
    root.child(tf.ORDERS_GROUP, "orders_mode").setValue(tf.AUTO)
    in_flight = context(later.with_shots({7: orders_events(rng, SIDES, centre=CENTRE + 0.004)}), instance.values())
    root.child(tf.ORDERS_GROUP, "orders_mode").setValue(tf.MANUAL)
    root.child(tf.ORDERS_GROUP, "centre").setValue(2.14)
    instance._show_detected(AnalysisResult.of(in_flight, "completed", script.compute("Plot", in_flight)))
    assert instance.values()["centre"] == 2.14
    instance.close()


def test_detection_uses_only_the_shots_chosen() -> None:
    rng = np.random.default_rng(11)
    moved = CENTRE + 0.003  # order 0 arrives later from shot 4 on
    data = view({shot: orders_events(rng, SIDES, centre=CENTRE if shot < 4 else moved) for shot in range(1, 7)})
    assert fractions(data, {"first_shot": 4}).orders.centre == pytest.approx(moved, abs=2e-4)
    assert fractions(data, {"shots": "range", "last_shot": 3}).orders.centre == pytest.approx(CENTRE, abs=2e-4)
    past = fractions(data, {"first_shot": 7})
    assert not past.detected and past.chosen == 0 and past.total_shots == 6


# A strong transfer: +1 the tallest peak

def transferred(share: float) -> dict[int, int]:
    """Orders −1…+2 with ``share`` of order 0's atoms moved to +1 and +2."""
    return {-1: 30, 0: round(800 * (1 - share)), 1: round(680 * share), 2: round(120 * share)}


@pytest.mark.parametrize("share", [0.75, 0.9, 0.97])
def test_a_first_run_over_two_thirds_transfer_takes_plus_1_for_order_0(share: float) -> None:
    # A known limit: with no earlier detection, the tallest peak (+1) is taken for order 0 and
    # the real order 0 holds under half of its events, so nothing is said.
    data = fractions(shots_of(transferred(share)))
    assert data.orders.centre == pytest.approx(CENTRE + SPACING, abs=3e-4)
    assert data.jumped == 0 and data.notes == ()


def test_order_0_jumping_a_whole_order_from_the_last_detection_warns_until_settled() -> None:
    script = tf.TransferFractions()
    before = fractions(shots_of(transferred(0.3)))
    assert before.orders.centre == pytest.approx(CENTRE, abs=2e-4) and before.notes == ()
    last = {"centre": before.orders.centre, "spacing": before.orders.spacing}  # what the run filled in
    for share in (0.75, 0.97):
        values = {**last}
        start = context(shots_of(transferred(share), seed=1), values)
        result = AnalysisResult.of(start, "completed", script.compute("Plot", start))
        data = result.data
        assert data.jumped == 1 and data.orders.centre == pytest.approx(CENTRE + SPACING, abs=3e-4)
        moved = [note for note in data.notes if note.startswith("⚠ order 0 moved by +1 order from the last detection")]
        accept = f"set Order 0 at {data.orders.centre:.6g} s in manual mode, Rerun, then back to Auto"
        assert len(moved) == 1 and moved[0].endswith(accept)
        # The last detection's centre stays in the settings, so the next rerun warns again.
        assert script.detected_parameters("Plot", result) == {"spacing": data.orders.spacing}
    # Back to a low transfer: order 0 is where it was, no warning, and the centre is filled in again.
    again = context(shots_of(transferred(0.3), seed=2), last)
    settled = AnalysisResult.of(again, "completed", script.compute("Plot", again))
    assert settled.data.jumped == 0 and settled.data.notes == ()
    assert script.detected_parameters("Plot", settled) == {"centre": settled.data.orders.centre,
                                                           "spacing": settled.data.orders.spacing}


def test_no_jump_from_the_default_centre_part_of_an_order_or_in_manual_mode() -> None:
    assert jump(float(tf.CENTRE.default), CENTRE + SPACING, SPACING, 2) == 0  # the default is no detection
    assert jump(CENTRE, CENTRE + 0.5 * SPACING, SPACING, 2) == 0
    assert jump(CENTRE + 1e-4, CENTRE + 1e-4 - 1.25 * SPACING, SPACING, 2) == -1
    assert jump(CENTRE + 1e-4, CENTRE + 1e-4 + 3 * SPACING, SPACING, 2) == 3
    assert jump(CENTRE + 1e-4, CENTRE + 1e-4 + 4 * SPACING, SPACING, 2) == 0  # beyond the orders counted
    manual = fractions(shots_of(transferred(0.9)), {"orders_mode": tf.MANUAL, "centre": CENTRE - SPACING})
    assert manual.jumped == 0 and manual.notes == ()


# Search T with both ends set: the user's word on where order 0 is

AROUND_0 = {"search_min": CENTRE - SPACING / 2, "search_max": CENTRE + SPACING / 2}


@pytest.mark.parametrize(("share", "said"), [(0.45, "order +1 (outside Search T) holds 70% as many events as order 0"),
                                             (0.6, "order +1 (outside Search T) is taller than order 0")])
def test_search_t_around_order_0_clears_unsure_and_says_what_is_outside(share: float, said: str) -> None:
    data = shots_of(transferred(share))
    assert unsure_notes(fractions(data))  # Without Search T: unsure.
    found = fractions(data, AROUND_0)
    assert found.orders.centre == pytest.approx(CENTRE, abs=2e-4) and not unsure_notes(found) and said in found.notes
    # No side peak inside such a narrow Search T: the spacing is the hidden (last) one.
    assert found.orders.spacing == tf.SPACING.default
    assert any(note.startswith("no side peak found beyond order 0's width") for note in found.notes)


def test_a_wrong_first_pick_fixed_by_search_t_updates_the_centre() -> None:
    script = tf.TransferFractions()
    data = shots_of(transferred(0.6))

    def run(values: dict[str, Any]) -> AnalysisResult:
        start = context(data, values)
        return AnalysisResult.of(start, "completed", script.compute("Plot", start))
    first = run({})
    assert first.data.orders.centre == pytest.approx(CENTRE + SPACING, abs=3e-4)  # +1 taken for order 0
    last = script.detected_parameters("Plot", first)
    # Search T around the real order 0 leaves the last centre out: the new one replaces it, no "moved".
    fixed = run({**last, **AROUND_0})
    assert fixed.data.orders.centre == pytest.approx(CENTRE, abs=2e-4) and fixed.data.jumped == 0
    assert not [note for note in fixed.data.notes if note.startswith("⚠")]
    assert (f"order 0 now at {fixed.data.orders.centre:.6g} s; the last detection, {last['centre']:.6g} s, was "
            f"outside Search T") in fixed.data.notes
    filled = script.detected_parameters("Plot", fixed)
    assert filled["centre"] == fixed.data.orders.centre
    again = run({**filled, **AROUND_0})
    assert again.data.jumped == 0 and not [note for note in again.data.notes if note.startswith(("⚠", "order 0 now"))]
    # An open end keeps today's rules: the last centre is compared, and the warning sticks.
    open_end = run({**last, "search_max": CENTRE + SPACING / 2})
    assert open_end.data.orders.centre == pytest.approx(CENTRE, abs=2e-4) and open_end.data.jumped == -1
    assert "centre" not in script.detected_parameters("Plot", open_end)


def test_search_t_around_the_wrong_peak_says_what_it_replaced() -> None:
    """A right detection at 10 % transfer, then 90 % with both ends of Search T around +1 by
    mistake: +1 is the user's order 0 (no ⚠, and the real order 0 holds too few events for the
    outside line), but a plain line says the last detection was elsewhere."""
    script = tf.TransferFractions()
    first = context(shots_of(transferred(0.1)), {})
    right = AnalysisResult.of(first, "completed", script.compute("Plot", first))
    assert right.data.orders.centre == pytest.approx(CENTRE, abs=2e-4)
    last = script.detected_parameters("Plot", right)
    around_plus_1 = {"search_min": CENTRE + SPACING / 2, "search_max": CENTRE + 3 * SPACING / 2}
    data = fractions(shots_of(transferred(0.9), seed=1), {**last, **around_plus_1})
    assert data.orders.centre == pytest.approx(CENTRE + SPACING, abs=3e-4) and data.jumped == 0
    assert not [note for note in data.notes if note.startswith("⚠") or "(outside Search T)" in note]
    assert (f"order 0 now at {data.orders.centre:.6g} s; the last detection, {last['centre']:.6g} s, was outside "
            f"Search T") in data.notes
    # No last detection (the default centre): nothing replaced, no line.
    assert not [note for note in fractions(shots_of(transferred(0.9)), around_plus_1).notes
                if note.startswith("order 0 now")]
