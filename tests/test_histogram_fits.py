"""D1: the T/X/Y histograms' units, rates, smoothing and fits, and the arrival-time thermal
model, on synthetic clouds of known temperature."""
from __future__ import annotations

import html
import json
import math
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest
from PyQt6.QtWidgets import QTabWidget
from pytestqt.qtbot import QtBot
from scipy.integrate import quad

from helab.analysis import constant_layers, display_units, fits, physics, profiles
from helab.analysis.dataset_view import DatasetView, build_view
from helab.analysis.fits import MODELS, arrival_time_model, bin_centres, fit_histogram
from helab.analysis.parameter_tree import apply_visibility, build_tree, parameter_of, settings_widget
from helab.analysis.parameters import effective
from helab.analysis.physics import DEFAULTS, ResolvedConstants
from helab.analysis.plot_axes import GroupedAxis
from helab.analysis.profiles import (ARRIVAL, BIMODAL, GAUSSIAN, RATE, SMOOTHED, fit_axis,
                                     Smoothing, rate_factor, smooth, smoothing_bins)
from helab.analysis.results import AnalysisContext, AnalysisResult, Cancelled, RamResults
from helab.scripts.standard import basic_plots
from helab.utils.folder_cache import Dataset

Array = npt.NDArray[np.float64]
RELEASE = 1.5  # s: when the trap switched off, in DLD time


def velocity_spread(temperature: float, constants: ResolvedConstants = DEFAULTS) -> float:
    return math.sqrt(constants.k_B * temperature / constants.mass)


def arrival_times(velocities: Array, constants: ResolvedConstants = DEFAULTS) -> Array:
    """When atoms leaving at rest height h with vertical velocity v (z up) reach the detector:
    the positive root of ½ g t² − v t − h = 0."""
    g, h = constants.g, constants.fall_distance
    return (velocities + np.sqrt(velocities ** 2 + 2 * g * h)) / g


def cloud(rng: np.random.Generator, count: int, temperature: float,
          constants: ResolvedConstants = DEFAULTS) -> Array:
    """T/X/Y events of a thermal cloud from a point source: Maxwell–Boltzmann velocities, T the
    arrival time (since the DLD trigger), X and Y = v t at arrival."""
    v = rng.normal(0, velocity_spread(temperature, constants), (count, 3))
    t = arrival_times(v[:, 0], constants)
    return np.column_stack([t + RELEASE, v[:, 1] * t, v[:, 2] * t])


def histogram_of(values: Array, bins: int = 120, margin: float = 0.1) -> tuple[Array, Array]:
    low, high = np.percentile(values, [0.05, 99.95])
    span = high - low
    counts, edges = np.histogram(values, bins=bins, range=(low - margin * span, high + margin * span))
    return edges.astype(np.float64), counts.astype(np.float64)


def view_of(events: dict[int, Array]) -> DatasetView:
    for array in events.values():
        array.setflags(write=False)
    fingerprint = [[shot, 100 + shot, 1_000 + shot] for shot in sorted(events)]
    return build_view(Dataset("/data/root/run_fit", "sig-fit", events, {"fingerprint": fingerprint}, 0))


def run(view: DatasetView, values: dict[str, Any] | None = None,
        layers: dict[str, dict[str, float]] | None = None) -> AnalysisResult:
    """A run as the runner makes it: the constants resolved at submit (``run_constants``)."""
    script = basic_plots.TxyHistograms()
    parameters = effective(script.parameters("Plot"), values)
    resolved = script.run_constants("Plot", parameters, layers or {})
    context = AnalysisContext("a1", "Plot", view, parameters, script.get_metadata().identity(),
                              constants=layers or {}, resolved_constants=resolved,
                              constant_keys=script.run_constant_keys("Plot", parameters) if resolved is not None else ())
    data = script.compute("Plot", context)
    return AnalysisResult.of(context, "completed", data, found=script.result_found("Plot", data))


# The arrival-time model

def test_the_arrival_time_profile_is_the_velocity_distribution_through_its_jacobian() -> None:
    """p(T) dT = p(v) dv: its area is A σ √(2π) (as the Gaussian's), it peaks near T₀, is skewed
    (a longer late tail), and is only the offset before release."""
    model = arrival_time_model(DEFAULTS.fall_distance, DEFAULTS.g)
    centre, sigma = RELEASE + DEFAULTS.fall_time, 0.03
    area, _ = quad(lambda x: float(model(np.array([x]), [2.0, centre, sigma, 0.0])[0]), RELEASE,
                   centre + 1.0, points=[centre], limit=400)
    assert area == pytest.approx(2.0 * sigma * math.sqrt(2 * math.pi), rel=1e-4)
    areas = model.areas
    assert areas is not None and areas(np.array([2.0, centre, sigma, 0.0]))["thermal"] == pytest.approx(area, rel=1e-4)
    assert model(np.array([centre]), [2.0, centre, sigma, 0.5])[0] == pytest.approx(2.5)  # v = 0: Jacobian 1
    early, late = model(np.array([centre - 2 * sigma, centre + 2 * sigma]), [1.0, centre, sigma, 0.0])
    assert late > early  # the slow (late) side is stretched
    assert model(np.array([RELEASE - 0.1, RELEASE]), [1.0, centre, sigma, 0.25]).tolist() == [0.25, 0.25]
    # Narrow profiles are the Gaussian of width σ = σ_v / g.
    x = np.linspace(centre - 4e-4, centre + 4e-4, 9)
    assert model(x, [1.0, centre, 1e-4, 0.0]) == pytest.approx(fits.gaussian(x, 1.0, centre, 1e-4, 0.0), abs=2e-3)


def test_the_arrival_time_model_is_registered_and_records_its_constants() -> None:
    assert MODELS["arrival_time"].fixed == {"fall_distance": DEFAULTS.fall_distance, "g": DEFAULTS.g}
    assert MODELS["arrival_time"].names == MODELS["gaussian"].names
    model = arrival_time_model(0.9, 9.8)
    edges, counts = histogram_of(arrival_times(np.random.default_rng(3).normal(0, 0.05, 4000),
                                               physics.resolve(lab={"fall_distance": 0.9, "g": 9.8})))
    result = fit_histogram(bin_centres(edges), counts, model)
    assert result.ok, result.failure
    record = json.loads(json.dumps(result.as_record(), allow_nan=False))
    assert record["model"] == "arrival_time" and record["fixed"] == {"fall_distance": 0.9, "g": 9.8}
    assert json.loads(json.dumps(fit_histogram([0, 1, 2, 3, 4], [0, 1, 5, 1, 0]).as_record()))["fixed"] == {}
    for bad in ((0.0, 9.8), (0.9, -1.0), (math.inf, 9.8)):
        with pytest.raises(ValueError):
            arrival_time_model(*bad)


@pytest.mark.parametrize("temperature", [1e-6, 20e-6])
def test_the_arrival_time_fit_recovers_the_temperature_within_its_error(temperature: float) -> None:
    pulls = []
    for seed in range(25):
        rng = np.random.default_rng(seed)
        edges, counts = histogram_of(arrival_times(rng.normal(0, velocity_spread(temperature), 5000)) + RELEASE)
        fitted = fit_axis("T", edges, counts, ARRIVAL, DEFAULTS)
        assert fitted.ok, fitted.failure
        pulls.append((fitted.temperature.value - temperature) / fitted.temperature.se)
        assert abs(fitted.centre.value - RELEASE - DEFAULTS.fall_time) < 4 * fitted.centre.se
    assert np.mean(np.abs(pulls) < 2) >= 0.8 and abs(float(np.mean(pulls))) < 0.5


def test_the_gaussian_underestimates_a_hot_cloud_the_arrival_profile_does_not() -> None:
    """At 50 µK the arrival-time spread is ~8 % of the fall time: the Gaussian's T is biased low."""
    temperature = 50e-6
    pulls: dict[str, list[float]] = {GAUSSIAN: [], ARRIVAL: []}
    for seed in range(15):
        rng = np.random.default_rng(seed)
        edges, counts = histogram_of(arrival_times(rng.normal(0, velocity_spread(temperature), 20_000)) + RELEASE,
                                     bins=150)
        for choice, values in pulls.items():
            fitted = fit_axis("T", edges, counts, choice, DEFAULTS)
            values.append((fitted.temperature.value - temperature) / fitted.temperature.se)
    assert float(np.mean(pulls[GAUSSIAN])) < -0.8
    assert abs(float(np.mean(pulls[ARRIVAL]))) < 0.4


# Gaussian fits on each axis

@pytest.mark.parametrize("axis", [0, 1, 2])
def test_gaussian_fits_recover_the_temperature_on_each_axis(axis: int) -> None:
    temperature = 1e-6
    pulls = []
    for seed in range(25):
        events = cloud(np.random.default_rng(100 + seed), 5000, temperature)
        edges, counts = histogram_of(events[:, axis], bins=80)
        fitted = fit_axis("TXY"[axis], edges, counts, GAUSSIAN, DEFAULTS)
        assert fitted.ok, fitted.failure
        pulls.append((fitted.temperature.value - temperature) / fitted.temperature.se)
    assert np.mean(np.abs(pulls) < 2) >= 0.8 and abs(float(np.mean(pulls))) < 0.5


def test_the_temperature_uses_the_runs_constants() -> None:
    """σ_v = g σ along T, σ / t_f along X: a longer fall time halves σ_v for the same width."""
    events = cloud(np.random.default_rng(5), 20_000, 2e-6)
    edges, counts = histogram_of(events[:, 1])
    usual = fit_axis("X", edges, counts, GAUSSIAN, DEFAULTS)
    doubled = fit_axis("X", edges, counts, GAUSSIAN,
                       physics.resolve(plot={"fall_time": 2 * DEFAULTS.fall_time}))
    assert doubled.sigma_v.value == pytest.approx(usual.sigma_v.value / 2)
    assert doubled.temperature.value == pytest.approx(usual.temperature.value / 4)
    assert usual.sigma_v.value == pytest.approx(usual.width.value / DEFAULTS.fall_time)
    edges, counts = histogram_of(events[:, 0])
    along_t = fit_axis("T", edges, counts, GAUSSIAN, DEFAULTS)
    assert along_t.sigma_v.value == pytest.approx(DEFAULTS.g * along_t.width.value)


def thomas_fermi_ball(rng: np.random.Generator, count: int, radius: float) -> Array:
    """Positions (x, y, z) of atoms in a 3D Thomas–Fermi cloud: density ∝ (1 − r²/R²)₊."""
    found: list[Array] = []
    total = 0
    while total < count:
        points = rng.uniform(-1, 1, (4 * count, 3))
        squared = (points ** 2).sum(axis=1)
        kept = points[(squared < 1) & (rng.uniform(0, 1, len(points)) < 1 - squared)]
        found.append(kept)
        total += len(kept)
    return np.concatenate(found)[:count] * radius


def test_the_tf_exponent_follows_how_the_histogram_integrates_the_cloud() -> None:
    """Tony's decision 3, checked physically: a full projection of a 3D Thomas–Fermi cloud (both
    other axes integrated) is (1 − u²)², a thin slice of one other axis (integrated over one axis
    only) (1 − u²)^{3/2}; each fits its own exponent better and finds R, the other biases R."""
    rng = np.random.default_rng(21)
    radius = 1e-3
    atoms = thomas_fermi_ball(rng, 400_000, radius)
    full = histogram_of(atoms[:, 0], bins=120)
    thin = histogram_of(atoms[np.abs(atoms[:, 1]) < 0.05 * radius, 0], bins=120)
    for (edges, counts), right, wrong in ((full, "thomas_fermi_2", "thomas_fermi_1_5"),
                                          (thin, "thomas_fermi_1_5", "thomas_fermi_2")):
        centres = bin_centres(edges)
        good, bad = fit_histogram(centres, counts, right), fit_histogram(centres, counts, wrong)
        assert good.ok and bad.ok
        assert good["radius"].value == pytest.approx(radius, rel=0.02)
        assert good.reduced_chi2 < bad.reduced_chi2
        assert abs(bad["radius"].value / radius - 1) > 0.04  # the wrong exponent biases R


@pytest.mark.parametrize(("choice", "power"), [(BIMODAL, 2.0), (profiles.BIMODAL_SLICE, 1.5)])
def test_both_bimodal_exponents_fit_data_made_with_each(choice: str, power: float) -> None:
    rng = np.random.default_rng(22)
    edges = np.linspace(-6e-3, 6e-3, 201)
    centres = bin_centres(edges)
    model = MODELS[profiles.MODEL_KEYS[choice]]
    assert model.key == f"bimodal_tf{'2' if power == 2 else '1_5'}_gaussian"
    sigma, ratio = 1.5e-3, 1.2  # R = 1.8 mm
    truth = model.function(centres, 400.0, 2e-4, ratio, 120.0, sigma, 2.0)
    counts = rng.poisson(truth).astype(np.float64)
    fitted = fit_axis("X", edges, counts, choice, DEFAULTS)
    assert fitted.ok and fitted.choice == choice
    assert fitted.fit["radius"].value == pytest.approx(ratio * sigma, rel=0.05)
    assert fitted.width.value == pytest.approx(sigma, rel=0.05)
    assert "R (" in fitted.text() and "σ thermal" in fitted.text() and " mm" in fitted.text()
    assert choice in profiles.T_MODELS and choice in profiles.XY_MODELS


def test_the_arrival_time_model_uses_the_effective_fall_distance() -> None:
    """A hand-set fall time makes the model's distance ½ g t_f² (as D8's velocities), so v = 0
    arrives t_f after release; derived, it is h."""
    timed = physics.resolve(plot={"fall_time": 0.417})
    model = profiles.model_for(ARRIVAL, timed)
    assert model.fixed["fall_distance"] == pytest.approx(0.5 * timed.g * 0.417 ** 2)
    assert profiles.model_for(ARRIVAL, DEFAULTS).fixed["fall_distance"] == DEFAULTS.fall_distance


def test_the_model_choice_explains_the_tf_exponent() -> None:
    tip = basic_plots.FIT_SPECS["X"][1].tip
    for words in ("p = 2: a full projection", "p = 3/2: a thin slice", "p = 1", "8–9 %", "g_5/2", "g_2"):
        assert words in tip


def test_a_bimodal_fit_takes_its_temperature_from_the_thermal_width() -> None:
    rng = np.random.default_rng(8)
    thermal = cloud(rng, 20_000, 1e-6)[:, 1]
    u = rng.uniform(-1, 1, 40_000)
    condensate = (u[rng.uniform(0, 1, len(u)) < (1 - u * u) ** 2] * 2e-3)[:8000]
    edges, counts = histogram_of(np.concatenate([thermal, condensate]), bins=150)
    fitted = fit_axis("X", edges, counts, BIMODAL, DEFAULTS)
    assert fitted.ok, fitted.failure
    assert abs(fitted.temperature.value - 1e-6) < 4 * fitted.temperature.se
    assert "R (" in fitted.text() and "σ thermal" in fitted.text()


# Units, rates and smoothing

def override(key: str, value: float) -> dict[str, Any]:
    """The plot's own value of a constant (its Constants group)."""
    return {constant_layers.source_name(key): constant_layers.SET_HERE, constant_layers.value_name(key): value}


def test_display_units() -> None:
    assert display_units.axis_label("X") == "X (mm)" and display_units.axis_label("T") == "T (ms)"
    assert display_units.axis_scale("T") == display_units.axis_scale("Y") == 1e3
    assert profiles.value_label("T", RATE) == "Rate (kHz per shot)"
    assert profiles.value_label("X", RATE) == "Rate (per mm per shot)"
    assert profiles.value_label("Y", "counts") == "Events"


def test_rate_per_shot_is_counts_per_bin_width_per_shot() -> None:
    # 50 counts in a 0.1 ms bin over 10 shots: 50 per ms per shot... / 10 = 50 kHz per shot.
    assert 50 * rate_factor(1e-4, 10) == pytest.approx(50.0)
    # 30 counts in a 0.5 mm bin over 3 shots: 20 per mm per shot.
    assert 30 * rate_factor(5e-4, 3) == pytest.approx(20.0)
    assert math.isnan(rate_factor(1e-4, 0)) and math.isnan(rate_factor(0.0, 3))


def test_smoothing_keeps_the_area_and_sets_bins_of_a_fifth_of_sigma() -> None:
    assert smoothing_bins(0.0, 1e-2, 1e-4) == (500, "")
    count, note = smoothing_bins(0.0, 1.0, 1e-4)
    assert count == profiles.SMOOTH_MAX_BINS and "widened" in note and "50,000" in note
    assert smoothing_bins(1.0, 1.0, 1e-4) == (1, "")
    rng = np.random.default_rng(2)
    counts = np.histogram(rng.normal(0, 1, 5000), bins=200, range=(-3, 3))[0].astype(np.float64)
    for sigma_bins in (0.5, 5.0, 40.0, 300.0):  # 300: wider than the histogram
        smoothed = smooth(counts, sigma_bins)
        assert smoothed.shape == counts.shape and smoothed.sum() == pytest.approx(counts.sum())
        assert smoothed.std() <= counts.std()
    # A spike becomes the kernel; at an edge, what spreads past it folds back.
    spike = np.zeros(101)
    spike[50] = 10.0
    assert smooth(spike, 5.0).sum() == pytest.approx(10.0) and smooth(spike, 5.0).argmax() == 50
    edge = np.zeros(101)
    edge[0] = 10.0
    assert smooth(edge, 5.0).sum() == pytest.approx(10.0)
    # The operator: every raw bin's counts go somewhere (columns sum to 1); its variance map is Σ S².
    operator = Smoothing(60, 4.0)
    assert np.asarray(operator.matrix.sum(axis=0)).ravel() == pytest.approx(np.ones(60))
    assert operator.variance(np.ones(60)) == pytest.approx(np.asarray(operator.squared.sum(axis=1)).ravel())
    assert operator.apply(spike[:60]) == pytest.approx(smooth(spike[:60], 4.0))


def test_fits_use_the_unsmoothed_counts_by_default(qtbot: QtBot) -> None:
    """Smoothing changes what is drawn, not the fit (unless Fit to says the smoothed curve:
    then the model is smoothed too, so its parameters are the unsmoothed profile's)."""
    events = cloud(np.random.default_rng(4), 20_000, 1e-6)
    view = view_of({1: events})
    values: dict[str, Any] = {"fit_t": True, "fit_x": True, "smooth": True, "smooth_t": 1e-3,
                              "smooth_xy": 1e-3}
    plain = run(view, values).data
    t_fit, x_fit = plain.fits[0], plain.fits[1]
    assert t_fit is not None and x_fit is not None and not t_fit.on_smoothed
    histogram = plain.items[0]
    assert len(histogram.counts) == math.ceil((histogram.edges[-1] - histogram.edges[0]) / 2e-4)
    assert plain.smoothed[0].sum() == pytest.approx(histogram.counts.sum())
    direct = fit_axis("T", histogram.edges, histogram.counts, GAUSSIAN, DEFAULTS)
    assert t_fit.width.value == direct.width.value
    on_curve = run(view, {**values, "fit_data": SMOOTHED}).data
    smoothed_fit = on_curve.fits[0]
    assert smoothed_fit is not None and smoothed_fit.ok and smoothed_fit.on_smoothed
    # The smoothing is in the model: the width is the profile's, as the unsmoothed fit's.
    assert smoothed_fit.width.value == smoothed_fit.fit["sigma"].value
    assert abs(smoothed_fit.width.value - t_fit.width.value) < 0.5 * t_fit.width.se
    assert smoothed_fit.width.se == pytest.approx(t_fit.width.se, rel=0.15)  # the same information
    assert any("smoothing in the model" in note for note in smoothed_fit.notes)
    assert smoothed_fit.fit.model.key == "gaussian+smoothing"
    assert smoothed_fit.text().startswith("Gaussian ⊗ smoothing")
    # The drawn curve is the smoothed model on the bins, next to the smoothed counts.
    assert len(smoothed_fit.x) == len(histogram.counts)
    assert np.abs(smoothed_fit.y - on_curve.smoothed[0]).max() < 0.2 * on_curve.smoothed[0].max()
    # Smoothing nearly as wide as the cloud (σ_s 3 ms against ~4.7 ms): still the cloud's width.
    span = float(histogram.edges[-1] - histogram.edges[0])
    wide = fit_axis("T", histogram.edges, histogram.counts, GAUSSIAN, DEFAULTS, smoothing=0.003)
    assert wide.ok, wide.failure
    assert abs(wide.width.value - t_fit.width.value) < 3 * wide.width.se
    assert wide.width.se >= 0.95 * t_fit.width.se  # no more certain than the raw counts allow
    # Beyond a fifth of the range, the smoothed curve isn't fitted, and the plot says why.
    too_wide = fit_axis("T", histogram.edges, histogram.counts, GAUSSIAN, DEFAULTS, smoothing=0.21 * span)
    assert not too_wide.ok and "too wide for this range" in too_wide.failure and too_wide.on_smoothed
    result = run(view, values)
    widget: Any = basic_plots.TxyHistograms().render(result)
    qtbot.addWidget(widget)
    items = widget.getItem(1, 0).listDataItems()
    assert len(items) == 3  # the faint bars, the smoothed curve and the fit


# The plot

def test_the_plot_shows_mm_and_ms_and_rates_per_shot(qtbot: QtBot) -> None:
    rng = np.random.default_rng(6)
    view = view_of({shot: cloud(rng, 2000, 1e-6) for shot in (1, 2, 3, 4)})
    counted = run(view, {"bins": 50})
    rated = run(view, {"bins": 50, "units": RATE})
    for index, item in enumerate(rated.data.items):
        width = float(item.edges[1] - item.edges[0])
        assert rated.data.factor(index) == pytest.approx(1 / (width * 1e3 * 4))
        assert counted.data.factor(index) == 1.0
        assert (item.counts == counted.data.items[index].counts).all()
    t_rate = rated.data.items[0].counts * rated.data.factor(0)
    # Summed over bins × bin width in ms: events per shot, per ms × ms.
    assert float(t_rate.sum()) * (rated.data.items[0].edges[1] - rated.data.items[0].edges[0]) * 1e3 == \
        pytest.approx(rated.data.items[0].counts.sum() / 4)
    widget: Any = basic_plots.TxyHistograms().render(rated)
    qtbot.addWidget(widget)
    labels = [(widget.getItem(row, 0).getAxis("bottom").labelText, widget.getItem(row, 0).getAxis("left").labelText)
              for row in (1, 2, 3)]
    assert labels == [("T (ms)", "Rate (kHz per shot)"), ("X (mm)", "Rate (per mm per shot)"),
                      ("Y (mm)", "Rate (per mm per shot)")]
    (bars,) = widget.getItem(2, 0).listDataItems()
    xs, ys = bars.getOriginalDataset()
    assert xs[0] == pytest.approx(rated.data.items[1].edges[0] * 1e3)
    assert ys == pytest.approx(rated.data.items[1].counts * rated.data.factor(1))
    describe = basic_plots.TxyHistograms().describe_run("Plot", rated.parameters, view)[1]
    assert describe == "auto-crop 99 % · bins 50 · rate per shot"


def test_the_box_counts_only_events_inside_the_other_ranges() -> None:
    background = np.column_stack([np.full(100, 5.0), np.zeros(100), np.zeros(100)])  # far outside T's window
    atoms = cloud(np.random.default_rng(1), 1000, 1e-6)
    view = view_of({1: np.concatenate([atoms, background])})
    manual = {"range_mode": "manual", "t_min": 1.8, "t_max": 2.0}
    loose = run(view, manual).data
    boxed = run(view, {**manual, "box_first": True}).data
    assert loose.items[1].total == 1100 and boxed.items[1].total == 1000 == boxed.items[2].total
    assert boxed.items[0].total == 1100 and boxed.items[0].outside == 100  # the background is at X = Y = 0
    assert boxed.box and basic_plots.TxyHistograms().describe_run("Plot", {**effective(
        basic_plots.TxyHistograms().parameters("Plot"), {**manual, "box_first": True})}, view)[1].endswith("box")


def test_fits_are_drawn_titled_and_recorded_with_their_constants(qtbot: QtBot) -> None:
    rng = np.random.default_rng(9)
    view = view_of({shot: cloud(rng, 5000, 1e-6) for shot in (1, 2)})
    script = basic_plots.TxyHistograms()
    values = {"fit_t": True, "fit_t_model": ARRIVAL, "fit_x": True, "fit_y": True, **override("fall_distance", 0.85)}
    result = run(view, values)
    data = result.data
    assert all(fit is not None and fit.ok for fit in data.fits)
    assert data.constants.origins["fall_distance"] == "plot" and data.constants.fall_distance == 0.85
    assert data.constants.origins["fall_time"] == "derived"
    record = json.loads(json.dumps(data.record(), allow_nan=False))
    assert set(record["fits"]) == {"T", "X", "Y"}
    assert record["fits"]["T"]["fit"]["model"] == "arrival_time"
    assert record["fits"]["T"]["fit"]["fixed"]["fall_distance"] == 0.85  # the model used the plot's value
    assert record["constants"]["values"]["fall_distance"] == 0.85
    assert not {"fall_distance", "fall_time"} & set(record["constants"]["unconfirmed"])
    assert record["fits"]["X"]["temperature"]["value"] == pytest.approx(1e-6, rel=0.2)
    # The structured record is the result's ``found``: the dock's lines come from it, and it stays
    # when the plot is released (its data dropped).
    assert json.loads(json.dumps(dict(result.found), allow_nan=False)) == record
    released = RamResults().released(result)
    assert released.data is None and script.result_record("Plot", released) == record["record_lines"]
    lines = script.result_record("Plot", result)
    assert lines[0].startswith("Fit T: Arrival-time thermal: centre (") and "T (" in lines[0] and "K" in lines[0]
    assert lines[1].startswith("Fit X: Gaussian: centre (") and "reduced χ²" in lines[1]
    # The constants are in the record once, from the run (not among the fit lines).
    assert len(lines) == 3 and not any("Constants" in line for line in lines)
    record_text = result.describe()
    assert record_text.count("Constants: ") == 1
    assert "h = 850 mm (this plot)" in record_text and "t_f = 416.5812 ms (derived)" in record_text
    assert "ħ =" not in record_text  # only the constants the fits use
    default = run(view, {"fit_x": True})
    assert default.resolved_constants is not None and default.resolved_constants.origins["fall_distance"] == "default"
    assert default.data.fits[0] is None and default.data.fits[2] is None
    plain = run(view, {})
    assert script.result_record("Plot", plain) == []  # no fits: nothing beyond the parameters
    assert "constants" not in plain.data.record()
    # Without a fit the histograms use no constants: not keyed on them, no Constants line.
    assert plain.resolved_constants is None and "constants" not in plain.reuse_key()
    assert "Constants: " not in plain.describe()
    settings = script.describe_run("Plot", result.parameters, view)[1]
    assert settings.endswith("fit T Arrival-time thermal, X Gaussian, Y Gaussian")
    widget: Any = script.render(result)
    qtbot.addWidget(widget)
    for row, fit in zip((1, 2, 3), data.fits):
        plot = widget.getItem(row, 0)
        title = plot.titleLabel.text
        assert fit is not None and html.unescape(fit.text()) in html.unescape(title)
        bars, curve = plot.listDataItems()
        xs, ys = curve.getOriginalDataset()
        factor = 1e3
        assert xs == pytest.approx(fit.x * factor) and ys == pytest.approx(fit.y)
    header = widget.getItem(0, 0).text
    assert "g 9.79602" not in header  # Only the values not at their defaults (the record has all).
    assert "Fits with h 850 mm (this plot)" in header and "t_f 416.5812 ms (derived)" in header


def test_a_lab_or_folder_layer_reaches_the_fits() -> None:
    """F0b's hook: the run's context carries the lab and folder layers; the plot's own override wins."""
    view = view_of({1: cloud(np.random.default_rng(2), 3000, 1e-6)})
    folder = run(view, {"fit_x": True}, {"lab": {"g": 9.8}, "folder": {"fall_distance": 0.86}}).data.constants
    assert (folder.origins["g"], folder.origins["fall_distance"], folder.fall_distance) == ("lab", "folder", 0.86)
    plot = run(view, {"fit_x": True, **override("fall_distance", 0.9)}, {"folder": {"fall_distance": 0.86}}
               ).data.constants
    assert (plot.origins["fall_distance"], plot.fall_distance) == ("plot", 0.9)
    timed = run(view, {"fit_x": True, **override("fall_time", 0.5)}).data.constants
    assert timed.origins["fall_time"] == "plot" and timed.notes and "disagree" in timed.notes[0]
    # Bad layer values are left out, never raised (as every analysis's constants).
    bad = run(view, {"fit_x": True}, {"lab": {"g": -1.0, "fall_distance": float("nan")}}).data.constants
    assert bad.origins["g"] == "default" and bad.origins["fall_distance"] == "default"
    # The run's key and the record carry them: a lab fall distance makes another key.
    first = run(view, {"fit_x": True})
    other = run(view, {"fit_x": True}, {"lab": {"fall_distance": 0.86}})
    assert first.reuse_key()["constants"] != other.reuse_key()["constants"]
    assert other.reuse_key()["constants"]["layers"]["lab"] == {"fall_distance": 0.86}


def test_empty_single_bin_and_failed_fits_give_notes(qtbot: QtBot) -> None:
    script = basic_plots.TxyHistograms()
    values = {"fit_t": True, "fit_x": True, "fit_y": True}
    empty = run(view_of({}), values)
    widget: Any = script.render(empty)
    qtbot.addWidget(widget)  # The empty pane, as without fits.
    assert all(fit is not None and not fit.ok for fit in empty.data.fits)
    same = run(view_of({1: np.tile([[2.0, 0.001, 0.0]], (50, 1))}), values)
    for fit in same.data.fits:
        assert fit is not None and not fit.ok and "one bin" in fit.failure
    lines = script.result_record("Plot", same)
    assert lines[0] == "Fit T: Gaussian fit failed: all counts in one bin: no width to fit"
    drawn: Any = script.render(same)
    qtbot.addWidget(drawn)
    title = drawn.getItem(1, 0).titleLabel.text
    assert basic_plots.NOTE_COLOUR in title and "Gaussian fit failed: all counts in one bin" in title
    few = run(view_of({1: np.array([[2.0, 0.0, 0.0], [2.1, 0.001, 0.0], [2.2, 0.002, 0.0]])}),
              {**values, "bins": 3, "keep_percent": 100.0})
    assert all(fit is not None and not fit.ok and "too few bins" in fit.failure for fit in few.data.fits)
    drawn = script.render(few)
    qtbot.addWidget(drawn)


def test_fits_stop_when_the_run_is_cancelled() -> None:

    view = view_of({1: cloud(np.random.default_rng(2), 3000, 1e-6)})
    script = basic_plots.TxyHistograms()
    context = AnalysisContext("a1", "Plot", view, effective(script.parameters("Plot"), {"fit_t": True}),
                              script.get_metadata().identity())
    context.cancel_event.set()
    with pytest.raises(Cancelled):
        script.compute("Plot", context)


def test_the_fits_have_their_own_settings_tab(qtbot: QtBot) -> None:
    specs = basic_plots.TxyHistograms().parameters("Plot")
    root = build_tree(specs)
    widget = settings_widget(root, specs)
    qtbot.addWidget(widget)
    assert isinstance(widget, QTabWidget)
    assert [widget.tabText(index) for index in range(widget.count())] == ["Settings", "Fits"]
    model = parameter_of(root, basic_plots.FIT_SPECS["T"][1])
    assert not model.opts["visible"]  # shown once Fit T is on
    parameter_of(root, basic_plots.FIT_SPECS["T"][0]).setValue(True)
    apply_visibility(root, specs)
    assert model.opts["visible"] and model.opts["limits"] == list(profiles.T_MODELS)
    assert parameter_of(root, basic_plots.FIT_SPECS["X"][1]).opts["limits"] == list(profiles.XY_MODELS)


@pytest.mark.parametrize("count, bins", [(5000, 200), (300, 600)])  # the second: ≤ 1 count per raw bin
def test_smoothed_curve_fits_have_honest_errors_and_no_low_count_bias(count: int, bins: int) -> None:
    """With the smoothing in the model and the sandwich covariance, the widths' scatter over
    seeds matches their SE (smoothed bins treated as independent gave SEs ~4× too small), and
    model-based weights leave no bias at about one count per bin."""
    widths, errors = [], []
    counts = np.zeros(bins, dtype=np.int64)
    for seed in range(40):
        rng = np.random.default_rng(1000 + seed)
        counts, edges = np.histogram(rng.normal(0, 1e-3, count), bins, range=(-5e-3, 5e-3))
        fitted = fit_axis("X", edges.astype(np.float64), counts.astype(np.float64), GAUSSIAN, DEFAULTS,
                          smoothing=5 * float(edges[1] - edges[0]))
        assert fitted.ok, fitted.failure
        widths.append(fitted.width.value)
        errors.append(fitted.width.se)
    if bins == 600:
        assert counts.max() <= 6 and np.mean(counts[counts > 0]) < 2
    scatter_over_se = float(np.std(widths) / np.mean(errors))
    assert 0.7 <= scatter_over_se <= 1.4, scatter_over_se
    pulls = (np.array(widths) - 1e-3) / np.array(errors)
    assert abs(float(np.mean(pulls))) < 0.5, float(np.mean(pulls))


def test_fit_curves_follow_the_rate_scale_and_log_y(qtbot: QtBot) -> None:
    rng = np.random.default_rng(12)
    view = view_of({shot: cloud(rng, 3000, 1e-6) for shot in (1, 2, 3)})
    script = basic_plots.TxyHistograms()
    for log_y in (False, True):
        result = run(view, {"fit_x": True, "units": RATE, "log_y": log_y, "bins": 60})
        fit = result.data.fits[1]
        assert fit is not None and fit.ok
        widget: Any = script.render(result)
        qtbot.addWidget(widget)
        plot = widget.getItem(2, 0)
        assert plot.ctrl.logYCheck.isChecked() == log_y
        bars, curve = plot.listDataItems()
        xs, ys = curve.getOriginalDataset()
        expected = fit.y * result.data.factor(1)
        assert xs == pytest.approx(fit.x * 1e3)
        if log_y:
            # Where the model is ≤ 0 (the offset can be negative) it has no logarithm: left out.
            assert np.array_equal(np.isnan(ys), expected <= 0)
            assert ys[~np.isnan(ys)] == pytest.approx(expected[expected > 0])
        else:
            assert ys == pytest.approx(expected)
        assert np.nanmax(bars.getOriginalDataset()[1]) == pytest.approx(
            result.data.items[1].counts.max() * result.data.factor(1))


def test_t_is_shown_in_ms_even_over_a_long_range(qtbot: QtBot) -> None:
    rng = np.random.default_rng(13)
    events = cloud(rng, 2000, 1e-6)
    events[:1000, 0] += 1.5  # a second cloud 1.5 s later: T spans over 1 s
    result = run(view_of({1: events}), {"keep_percent": 100.0, "bins": 100, "fit_t": True})
    widget: Any = basic_plots.TxyHistograms().render(result)
    qtbot.addWidget(widget)
    plot = widget.getItem(1, 0)
    axis = plot.getAxis("bottom")
    assert axis.labelText == "T (ms)" and isinstance(axis, GroupedAxis)
    bars = plot.listDataItems()[0]
    assert bars.getOriginalDataset()[0][0] == pytest.approx(result.data.items[0].edges[0] * 1e3)
    assert axis.tickStrings([1900.0, 3400.0], 1.0, 500.0) == ["1,900", "3,400"]


def test_a_smoothed_bimodal_fit_of_a_thermal_cloud_finds_no_condensate() -> None:
    """The gating ("consistent with 0") reads the honest SEs: a thermal-only cloud's condensate
    is noted as absent as often as in the unsmoothed fit (with the weights-only SEs, ~4×
    too small, it was in 4 of 30 seeds against 28)."""
    sigma_s = 2e-4
    gated = {"smoothed": 0, "unsmoothed": 0}
    for seed in range(10):
        x = np.random.default_rng(seed).normal(0, velocity_spread(1e-6) * DEFAULTS.fall_time, 20_000)
        low, high = np.percentile(x, [0.5, 99.5])
        bins, _ = smoothing_bins(float(low), float(high), sigma_s)
        counts, edges = np.histogram(x, bins=bins, range=(low, high))
        for name, smoothing in (("smoothed", sigma_s), ("unsmoothed", None)):
            fitted = fit_axis("X", edges.astype(np.float64), counts.astype(np.float64), BIMODAL, DEFAULTS,
                              smoothing=smoothing)
            assert fitted.ok, fitted.failure
            if any("consistent with 0" in note for note in fitted.notes):
                gated[name] += 1
                assert math.isnan(fitted.fit["radius"].se)  # R isn't determined without a condensate
    assert gated["smoothed"] >= 8 and abs(gated["smoothed"] - gated["unsmoothed"]) <= 1, gated


def test_the_smoothed_model_is_smoothed_on_its_own_bins_only() -> None:
    centres = np.linspace(-1.0, 1.0, 41)
    smoothing = Smoothing(41, 3.0)
    model = profiles.smoothed_model(MODELS["gaussian"], smoothing, centres)
    values = (1.0, 0.0, 0.2, 0.0)
    lower, upper = fits.bin_bounds(centres)
    plain = fits.bin_means(fits.gaussian, lower, upper, values)  # the model averaged over each bin
    assert model.function(centres, *values) == pytest.approx(smoothing.apply(plain))
    shifted = centres + 0.01  # same count, other positions: not the bins S belongs to
    assert model.function(shifted, *values) == pytest.approx(fits.gaussian(shifted, *values))
    fine = np.linspace(-1.0, 1.0, 400)
    assert model.function(fine, *values) == pytest.approx(fits.gaussian(fine, *values))
