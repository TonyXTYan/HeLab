"""D8 part 2: the Velocity distributions plot (events → velocities at release, z up)."""
from __future__ import annotations

import json
import re
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtWidgets import QLabel

from helab.analysis import constant_layers
from helab.analysis.parameters import effective
from helab.analysis.physics import DEFAULTS, TABLE, ResolvedConstants, resolve
from helab.analysis.dataset_view import DatasetView, build_view
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.velocity import RECOIL_WAVELENGTH, arrival_time, recoil_velocity
from helab.scripts import standard
from helab.scripts.standard import velocity_distributions
from helab.scripts.standard.velocity_distributions import VelocityData, VelocityDistributions, VelocityWidget
from helab.utils.colours import AMBER
from helab.utils.folder_cache import Dataset

Array = npt.NDArray[np.float64]
RELEASE = 20.0312  # s, DLD time
ORIGIN = (3e-3, -2e-3)  # m
PATH = "/data/root/run_8"
SCRIPT = VelocityDistributions()
SIGMA_V = 0.02  # m/s: a ~0.2 µK cloud
ARRIVAL = RELEASE + DEFAULTS.fall_time
# The folder's saved arrival and origin (what the Release time plot's Use for this folder saves).
SAVED = {"arrival_time": ARRIVAL, "trap_x": ORIGIN[0], "trap_y": ORIGIN[1]}


def cloud(rng: np.random.Generator, count: int, mean: tuple[float, float, float] = (0.0, 0.0, 0.0),
          sigma_v: float = SIGMA_V, release: float = RELEASE, origin: tuple[float, float] = ORIGIN,
          constants: ResolvedConstants = DEFAULTS) -> Array:
    """TXY events of atoms released at ``release`` from above ``origin`` with velocities (v_z, v_x, v_y)
    ~ N(``mean``, ``sigma_v``), z up."""
    v = rng.normal(mean, sigma_v, (count, 3))
    t = arrival_time(v[:, 0], release, constants)
    tau = t - release
    return np.column_stack([t, origin[0] + v[:, 1] * tau, origin[1] + v[:, 2] * tau])


def view_of(clouds: list[tuple[tuple[float, float, float], int]], shots: int = 4, seed: int = 0,
            origin: tuple[float, float] = ORIGIN) -> DatasetView:
    """Shots of clouds, each (mean velocity, events per shot)."""
    rng = np.random.default_rng(seed)
    data = {}
    for shot in range(1, shots + 1):
        events = np.concatenate([cloud(rng, count, mean, origin=origin) for mean, count in clouds]) if clouds \
            else np.empty((0, 3))
        data[shot] = events[np.argsort(events[:, 0])]
    prints = [[shot, 100 + shot, 1_700_000_000_000_000_000 + shot] for shot in data]
    return build_view(Dataset(PATH, "sig-velocity", data, {"fingerprint": prints}, 0))


def run(view: DatasetView, values: dict[str, Any] | None = None, folder: dict[str, float] | None = None
        ) -> AnalysisResult:
    params = effective(SCRIPT.parameters("Plot"), {"keep_percent": 100.0, **(values or {})})
    layers = {"lab": {}, "folder": dict(folder or {})}
    context = AnalysisContext("v1", "Plot", view, params, SCRIPT.get_metadata().identity(), constants=layers,
                              resolved_constants=SCRIPT.run_constants("Plot", params, layers),
                              constant_keys=SCRIPT.constant_keys("Plot"))
    data = SCRIPT.compute("Plot", context)
    return AnalysisResult.of(context, "completed", data, found=SCRIPT.result_found("Plot", data))


def means(data: VelocityData) -> list[float]:
    """Each axis's mean velocity (m/s) from its histogram."""
    out = []
    for item in data.axes:
        centres = (item.edges[:-1] + item.edges[1:]) / 2
        out.append(float(np.average(centres, weights=item.counts)))
    return out


@pytest.fixture(scope="module")
def at_rest() -> AnalysisResult:
    return run(view_of([((0.0, 0.0, 0.0), 3000)]), {"fit": True}, SAVED)


def test_a_cloud_released_at_rest_is_at_zero_velocity_with_the_folder_s_arrival(at_rest: AnalysisResult) -> None:
    data = at_rest.data
    assert data.release_source == "folder" and data.release_from == "arrival_time"
    assert data.release.value.value == pytest.approx(RELEASE, abs=1e-12)  # t_a − this run's t_f
    assert data.origin == ORIGIN and data.origin_how == "manual" and data.origin_source == "folder"
    assert data.detection is None  # Both set: nothing detected.
    assert data.converted == data.velocities == 4 * 3000 and data.invalid == 0
    for item in data.axes:
        assert item.fit is not None and item.fit.ok
        centre = item.fit["centre"]
        assert abs(centre.value) < 4 * centre.se + 1e-4, item.axis
        assert item.sigma.value == pytest.approx(SIGMA_V, rel=0.05), item.axis
        # T = m σ_v² / k_B for the cloud's σ_v.
        assert item.temperature.value == pytest.approx(DEFAULTS.mass * item.sigma.value ** 2 / DEFAULTS.k_B)
    record = dict(at_rest.found)
    assert json.loads(json.dumps(record, allow_nan=False)) == record
    assert record["release"]["source"] == "folder" and record["release"]["from"] == "arrival_time"
    assert record["origin"] == {"x": ORIGIN[0], "y": ORIGIN[1], "how": "manual", "source": "folder"}
    assert set(record["fits"]) == {"v_z", "v_x", "v_y"} and record["detection"] is None
    key = at_rest.reuse_key()
    assert json.loads(json.dumps(key)) == key
    assert set(key["constants"]["values"]) == set(velocity_distributions.CONSTANT_KEYS)


def test_a_launch_velocity_maps_to_itself() -> None:
    launched = (0.05, -0.03, 0.02)  # m/s: v_z up, v_x, v_y
    data = run(view_of([((0.0, 0.0, 0.0), 1500), (launched, 1500)], seed=1), {}, SAVED).data
    good = data.axes[0]
    # Two clouds per axis: the histograms' weighted means are the clouds' average velocity.
    np.testing.assert_allclose(means(data), [v / 2 for v in launched], atol=2e-3)
    alone = run(view_of([(launched, 2000)], seed=2), {"fit": True}, SAVED).data
    for item, expected in zip(alone.axes, launched):
        assert item.fit is not None and item.fit["centre"].value == pytest.approx(expected, abs=2e-3), item.axis
    assert good.total == 4 * 3000


def test_a_plot_s_own_fall_distance_keeps_the_cloud_at_rest() -> None:
    """t_r = t_a − *this run's* t_f: another h moves t_r, never the cloud at rest off v_z = 0."""
    view = view_of([((0.0, 0.0, 0.0), 2000)], seed=3)
    own = {"const.fall_distance.from": "this plot", "const.fall_distance": 0.86, "fit": True}
    data = run(view, own, SAVED).data
    assert data.constants.fall_distance == 0.86 and data.release.value.value == pytest.approx(
        ARRIVAL - data.constants.fall_time)
    assert abs(data.axes[0].fit["centre"].value) < 2e-3


def test_the_recoil_units() -> None:
    view = view_of([((2 * recoil_velocity(DEFAULTS), 0.0, 0.0), 2000)], seed=4)
    data = run(view, {"velocity_unit": "2ħk/m", "fit": True}, SAVED).data
    assert data.unit == "2ħk/m" and data.factor == pytest.approx(2 * recoil_velocity(DEFAULTS))
    assert data.axes[0].fit["centre"].value / data.factor == pytest.approx(1.0, abs=0.02)
    one = run(view, {"velocity_unit": "ħk/m"}, SAVED).data
    assert one.factor == pytest.approx(recoil_velocity(DEFAULTS)) and one.factor == pytest.approx(0.0920, abs=1e-4)
    # The wavelength is a lab constant: another one changes the unit.
    lab = run(view, {"velocity_unit": "ħk/m", "const.recoil_wavelength.from": "this plot",
                     "const.recoil_wavelength": 2 * RECOIL_WAVELENGTH}, SAVED).data
    assert lab.factor == pytest.approx(one.factor / 2)
    lines = velocity_distributions.titles(run(view, {"velocity_unit": "2ħk/m"}, SAVED), data)
    assert "1 2ħk/m = 184" in lines[1]
    record = "\n".join(velocity_distributions.record_lines(data))
    assert "λ 1,083.331 nm" in record and "1 2ħk/m = 184.0" in record


def test_the_recoil_wavelength_is_a_lab_row() -> None:
    row = TABLE["recoil_wavelength"]
    assert row.level == "lab" and row.unconfirmed and row.unit == "m" and row.value == RECOIL_WAVELENGTH
    assert DEFAULTS.recoil_wavelength == pytest.approx(1083.331e-9, rel=1e-6)
    assert constant_layers.value_text("recoil_wavelength", RECOIL_WAVELENGTH) == "1,083.331 nm"
    assert constant_layers.fixed_prefix("recoil_wavelength") == "n" and constant_layers.fixed_prefix("g") is None
    specs = {spec.name: spec for spec in SCRIPT.parameters("Plot")}
    assert specs["const.recoil_wavelength"].unit_prefix == "n"
    assert resolve(lab={"recoil_wavelength": 1.0e-6}).origins["recoil_wavelength"] == "lab"


def test_the_origin_is_subtracted_detected_or_assumed() -> None:
    view = view_of([((0.0, 0.0, 0.0), 2000)], seed=5)
    # Set in the folder: X and Y measured from it.
    manual = run(view, {"fit": True}, SAVED).data
    assert abs(manual.axes[1].fit["centre"].value) < 1e-3
    # Only the arrival saved: the origin is detected from the cloud at rest.
    detected = run(view, {"fit": True}, {"arrival_time": ARRIVAL}).data
    assert detected.origin_how == "detected" and detected.release_source == "folder"
    assert detected.detection is not None and detected.detection.ok
    np.testing.assert_allclose(detected.origin, ORIGIN, atol=2e-4)
    assert abs(detected.axes[1].fit["centre"].value) < 1e-3
    # One of x₀ and y₀ alone isn't an origin; with detection failing (no cloud in Search T), (0, 0).
    assumed = run(view, {"fit": True, "search_min": 25.0}, {"arrival_time": ARRIVAL, "trap_x": ORIGIN[0]}).data
    assert assumed.origin_how == "assumed" and assumed.origin == (0.0, 0.0)
    # Then every atom gets a spurious v_x = x₀/τ: about x₀/t_f.
    spurious = assumed.axes[1].fit["centre"].value
    assert spurious == pytest.approx(ORIGIN[0] / DEFAULTS.fall_time, rel=0.05)
    assert velocity_distributions.ASSUMED_NOTE in assumed.notes()
    result = run(view, {"search_min": 25.0}, {"arrival_time": ARRIVAL, "trap_x": ORIGIN[0]})
    lines = velocity_distributions.titles(result, result.data)
    assert any(line.startswith("⚠ origin assumed (0, 0): no trap origin set or detected") for line in lines)
    assert result.found["origin"]["how"] == "assumed"


def test_a_detected_release_time_is_said_and_recorded() -> None:
    view = view_of([((0.0, 0.0, 0.0), 2000)], seed=6)
    result = run(view, {"fit": True})
    data = result.data
    assert data.release_source == "detected" and data.release_from == "data" and data.release is data.detection
    assert data.release.error == "within run" and data.release.value.value == pytest.approx(RELEASE, abs=2e-5)
    assert data.origin_how == "detected" and abs(data.axes[0].fit["centre"].value) < 2e-3
    assert result.found["release"]["source"] == "detected" and result.found["detection"]["source"] == "detected"
    lines = velocity_distributions.titles(result, data)
    assert lines[1].startswith("t_r (20,031.2") and " ms (detected in this run, within run)" in lines[1]
    assert re.search(r"origin \((2\.9|3\.0)\d*, −(1\.9|2\.0)\d*\) mm \(detected\)$", lines[1]), lines[1]
    assert any(line.startswith("⚠ t_r detected in this run") for line in lines)
    brief = SCRIPT.describe_result("Plot", result)
    assert brief.startswith("t_r 20,031.") and "ms (detected) · origin (" in brief and brief.endswith("mm (detected)")
    # Set by hand for this plot: used as it is, nothing about detection.
    by_hand = run(view, {"const.release_time.from": "this plot", "const.release_time": RELEASE,
                         "const.trap_x.from": "this plot", "const.trap_x": ORIGIN[0],
                         "const.trap_y.from": "this plot", "const.trap_y": ORIGIN[1]})
    assert by_hand.data.release_source == "plot" and by_hand.data.release_from == "release_time"
    assert by_hand.data.detection is None and by_hand.data.origin_source == "plot"
    hand_lines = velocity_distributions.titles(by_hand, by_hand.data)
    assert "(this plot, by hand)" in hand_lines[1] and "origin (3, −2) mm (this plot)" in hand_lines[1]
    assert not any("detected" in line for line in hand_lines)
    # A plot's own arrival wins over the folder's t_r by hand (the more specific layer).
    mixed = run(view, {"const.arrival_time.from": "this plot", "const.arrival_time": ARRIVAL},
                {"release_time": RELEASE + 0.01, **{k: v for k, v in SAVED.items() if k != "arrival_time"}})
    assert mixed.data.release_source == "plot" and mixed.data.release_from == "arrival_time"
    assert mixed.data.release.value.value == pytest.approx(RELEASE)


def test_the_view_range_and_mask_choose_the_events() -> None:
    view = view_of([((0.0, 0.0, 0.0), 2000)], seed=7)
    whole = run(view, {}, SAVED).data
    # A cut circle around the cloud's centre takes most of its events.
    masked = run(view, {"mask_mode": "custom", "mask_circles": "3, -2, 2, cut"}, SAVED).data
    assert masked.masked > 0 and masked.events == whole.events - masked.masked
    assert sum(item.total for item in masked.axes[:1]) < whole.axes[0].total
    # A manual T window keeps the early (downward) half only: every v_z below 0.
    window = run(view, {"range_mode": "manual", "t_min": 20.0, "t_max": ARRIVAL}, SAVED).data
    assert 0 < window.converted < whole.converted and window.axes[0].edges[-1] <= 1e-3
    # Mask everything: said so.
    every = run(view, {"mask_mode": "custom", "mask_circles": "0, 0, 1000, cut"}, SAVED)
    assert velocity_distributions.empty_reason(every.data).startswith("All ")


def test_empty_cases_say_why(qtbot: QtBot) -> None:
    def reason(result: AnalysisResult) -> str:
        widget = SCRIPT.render(result)
        qtbot.addWidget(widget)
        assert isinstance(widget, QLabel)
        return widget.text()

    assert reason(run(view_of([], shots=0), {}, SAVED)) == "No shots yet"
    assert reason(run(view_of([], shots=2), {}, SAVED)) == "No events in the chosen shots"
    assert reason(run(view_of([((0.0, 0.0, 0.0), 50)]), {"first_shot": 10}, SAVED)).startswith("None of the 4 shots")
    # No release time anywhere and no cloud to detect it from.
    flat = build_view(Dataset(PATH, "sig-flat", {1: np.column_stack([np.sort(np.random.default_rng(0).uniform(
        20.0, 21.0, 20)), np.zeros((20, 2))])}, {"fingerprint": [[1, 1, 1]]}, 0))
    text = reason(run(flat))
    assert text.startswith("No release time: too few events") and "Use for this folder" in text
    # Every event in range before t_r: no velocities.
    early = reason(run(view_of([((0.0, 0.0, 0.0), 100)]), {}, {"arrival_time": 30.0}))
    assert early.startswith("None of the 400 events in the view range arrived after t_r")
    outside = reason(run(view_of([((0.0, 0.0, 0.0), 100)]), {"range_mode": "manual", "t_min": 30.0,
                                                            "t_max": 31.0}, SAVED))
    assert outside.startswith("None of the 400 events in the chosen shots is inside the view range")


def test_titles_and_settings_in_ms_mm_and_the_unit(qtbot: QtBot, at_rest: AnalysisResult) -> None:
    lines = velocity_distributions.titles(at_rest, at_rest.data)
    assert lines[0].endswith("4 shots · 12,000 of 12,000 events in range")
    assert lines[1] == ("t_r 20,031.2 ms (folder: saved arrival t_a − this run's t_f) · t_f 416.0908 ms (h 848 mm) · "
                        "origin (3, −2) mm (folder)")
    fit = velocity_distributions.fit_text(at_rest.data.axes[0], at_rest.data)
    assert re.fullmatch(r"centre \(−?0\.\d+ ± 0\.\d+\) mm/s · σ_v \((19|20)\.\d+ ± 0\.\d+\) mm/s · T \(.+\) nK", fit), fit
    first, second = SCRIPT.describe_run("Plot", effective(SCRIPT.parameters("Plot"), {
        "fit": True, "density": "v_x–v_z", "search_min": 20.4}), view_of([], shots=1))
    assert second == "auto-crop 99 % · mm/s · bins auto · fit Gaussians · density v_x–v_z · search T from 20,400 ms"
    record = "\n".join(SCRIPT.result_record("Plot", at_rest))
    assert "Release time t_r 20,031.2 ms" in record and "Fit v_z: centre" in record
    assert "Origin (3 mm, −2 mm): manual (folder)" in record
    specs = {spec.name: spec for spec in SCRIPT.parameters("Plot")}
    for name in ("search_min", "search_max", "t_min", "x_max", "const.fall_distance", "const.arrival_time",
                 "const.trap_x"):
        assert specs[name].unit_prefix == "m", name
    widget = SCRIPT.render(at_rest)
    qtbot.addWidget(widget)
    assert isinstance(widget, VelocityWidget) and len(widget.plots) == 3 and widget.density_plot is None
    assert widget.plots[0].getAxis("bottom").labelText == "v_z (mm/s)"
    xs, _ = widget.bars[0].getOriginalDataset()
    assert xs[0] == pytest.approx(at_rest.data.axes[0].edges[0] * 1e3)  # Drawn in mm/s.


def test_amber_notes_density_and_in_place_updates(qtbot: QtBot) -> None:
    view = view_of([((0.0, 0.0, 0.0), 1000)], seed=8)
    result = run(view, {"density": "v_x–v_y", "colour_scale": "sqrt"})
    data = result.data
    assert data.density is not None and data.density.image.sum() == data.velocities
    widget = SCRIPT.render(result)
    qtbot.addWidget(widget)
    assert isinstance(widget, VelocityWidget) and widget.density_plot is not None and widget.bar is not None
    assert f'<span style="color: {AMBER}">⚠ t_r detected in this run' in widget.title.text
    assert widget.density_plot.getAxis("left").labelText == "v_y (mm/s)"
    # Live's next shots: drawn in place; another density mode or the fits: anew.
    later = run(view_of([((0.0, 0.0, 0.0), 1000)], shots=5, seed=8), {"density": "v_x–v_y", "colour_scale": "sqrt"})
    assert SCRIPT.update(widget, later)
    assert not SCRIPT.update(widget, run(view, {"density": "v_x–v_z"}))
    assert not SCRIPT.update(widget, run(view, {"density": "v_x–v_y", "fit": True}))
    side = run(view, {"density": "v_x–v_z"}, SAVED)
    other = SCRIPT.render(side)
    qtbot.addWidget(other)
    assert isinstance(other, VelocityWidget) and other.density_plot.getAxis("left").labelText == "v_z (mm/s)"
    assert not SCRIPT.update(widget, run(view_of([], shots=0)))


def test_registered_with_its_constants_and_live_policy() -> None:
    assert velocity_distributions in standard.MODULES
    metadata = SCRIPT.get_metadata()
    assert (metadata.name, metadata.analysis_id, metadata.version, metadata.group) == (
        "Velocity distributions", "helab.velocity_distributions", "1", "Basic plots v1")
    assert SCRIPT.constant_keys("Plot") == ("fall_distance", "fall_time", "g", "release_time", "arrival_time",
                                            "trap_x", "trap_y", "recoil_wavelength", "mass", "k_B", "hbar")
    assert SCRIPT.live_policy("Plot").min_delay == 1.0
    warnings = SCRIPT.parameter_warnings("Plot", effective(SCRIPT.parameters("Plot"), {
        "search_min": 21.0, "search_max": 20.0}))
    assert warnings == ["Search T: from 21,000 ms is at or above to 20,000 ms: searching every event"]
    assert velocity_distributions.unit_factor("mm/s", DEFAULTS) == 1e-3
