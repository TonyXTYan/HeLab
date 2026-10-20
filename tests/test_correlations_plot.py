"""The Correlations plot (D12, D13): g²(0) ≈ 2 on a simulated thermal source, no peak and g² ≈ 1 on
an uncorrelated one, back-to-back pairs at 0 with the trap origin (and off it without), Live's
per-shot reuse, what starts the count again, the time budget, cancellation, closing a plot, and
drawing."""
from __future__ import annotations

import itertools
import json
import math
import threading
from typing import Any, Mapping

import numpy as np
import numpy.typing as npt
import pytest
from pytestqt.qtbot import QtBot

from helab.analysis import correlations
from helab.analysis.constant_layers import resolve_for_run
from helab.analysis.dataset_view import DatasetView, build_view
from helab.analysis.parameters import effective
from helab.analysis.physics import resolve
from helab.analysis.results import AnalysisContext, AnalysisResult, Cancelled
from helab.analysis.velocity import arrival_time
from helab.scripts import standard
from helab.scripts.standard import correlations_plot
from helab.scripts.standard.correlations_plot import CorrelationData, CorrelationPlot, Correlations
from helab.utils.folder_cache import Dataset

Array = npt.NDArray[np.float64]
SCRIPT = Correlations()
PATH = "/data/root/halo_run"
T_R = 20.0312  # s, DLD time
ORIGIN = (0.5e-3, -0.4e-3)  # m: the point below the trap
FOLDER = {"release_time": T_R, "trap_x": ORIGIN[0], "trap_y": ORIGIN[1]}
SCALE = 0.05  # m/s per simulation unit: the cloud σ 20 mm/s, the correlation length 5 mm/s
SIGMA_C, CLOUD, MODES = 0.1, 0.4, 512  # as tests/test_correlations.py's thermal source
CONSTANTS = resolve(folder=FOLDER)


def to_txy(velocities: Array, origin: tuple[float, float] = ORIGIN) -> Array:
    """TXY events of atoms released at T_R from above ``origin`` with these velocities (m/s)."""
    t = arrival_time(velocities[:, 0], T_R, CONSTANTS)
    tau = t - T_R
    return np.column_stack([t, origin[0] + velocities[:, 1] * tau, origin[1] + velocities[:, 2] * tau])


def thermal_velocities(seed: int, shots: int = 40, events: int = 400) -> list[Array]:
    """A chaotic source (tests/test_correlations.py's ``thermal_shots``), in m/s: g²(0) over the
    baseline is 1 + (1 − 1/K)/(1 + 1/K) = 1.9961 for K = 512 modes."""
    rng = np.random.default_rng(seed)
    k_sigma = 1 / (math.sqrt(2) * SIGMA_C)
    bound = 12.0
    result = []
    for _ in range(shots):
        k = rng.normal(0, k_sigma, (MODES, 3)).astype(np.float32)
        real, imag = (rng.normal(size=(2, MODES)) / math.sqrt(2 * MODES)).astype(np.float32)
        candidates = rng.normal(0, CLOUD, (rng.poisson(events * bound), 3))
        phase = candidates.astype(np.float32) @ k.T
        cos, sin = np.cos(phase), np.sin(phase)
        re, im = cos @ real - sin @ imag, cos @ imag + sin @ real
        keep = rng.random(len(candidates)) * bound < (re * re + im * im)
        result.append(candidates[keep] * SCALE)
    return result


EXPECTED_PEAK = 1 + (1 - 1 / MODES) / (1 + 1 / MODES)


def poisson_velocities(seed: int, shots: int, events: int) -> list[Array]:
    rng = np.random.default_rng(seed)
    return [rng.normal(0, CLOUD * SCALE, (int(rng.poisson(events)), 3)) for _ in range(shots)]


def pair_velocities(seed: int, shots: int = 30, pairs: int = 150, background: int = 150) -> list[Array]:
    """Back-to-back pairs from a source at rest: u on a halo of 15 mm/s, the partner at −u, each
    blurred by 0.5 mm/s; plus uncorrelated halo events."""
    rng = np.random.default_rng(seed)

    def sphere(n: int) -> Array:
        u = rng.normal(size=(n, 3))
        return 0.3 * SCALE * u / np.linalg.norm(u, axis=1, keepdims=True)
    result = []
    for _ in range(shots):
        u = sphere(pairs)
        events = np.concatenate([u, -u]) + rng.normal(0, 0.01 * SCALE, (2 * pairs, 3))
        events = np.concatenate([events, sphere(background)])
        result.append(events[rng.permutation(len(events))])
    return result


def view_of(per_shot: Mapping[int, Array], signature: str = "sig") -> DatasetView:
    shots = {shot: np.ascontiguousarray(events) for shot, events in per_shot.items()}
    prints = [[shot, 1_000 + len(events), 7_000 + shot] for shot, events in shots.items()]
    return build_view(Dataset(PATH, signature, shots, {"fingerprint": prints, "source": "merged"}, 0))


def txy_view(velocities: list[Array], origin: tuple[float, float] = ORIGIN) -> DatasetView:
    return view_of({shot: to_txy(v, origin) for shot, v in enumerate(velocities, start=1)})


def context_of(view: DatasetView, values: Mapping[str, Any] | None = None, folder: Mapping[str, float] | None = None,
               owner: str = "", live: bool = False, cancel: threading.Event | None = None) -> AnalysisContext:
    layer = dict(FOLDER if folder is None else folder)
    parameters = effective(SCRIPT.parameters("Plot"), dict(values or {}))
    return AnalysisContext("c1", "Plot", view, parameters, SCRIPT.get_metadata().identity(),
                           cancel_event=cancel or threading.Event(), constants={"folder": layer},
                           resolved_constants=resolve_for_run(parameters, None, layer),
                           constant_keys=correlations_plot.CONSTANT_KEYS, owner=owner, live=live)


def run(view: DatasetView, values: Mapping[str, Any] | None = None, **options: Any) -> AnalysisResult:
    context = context_of(view, values, **options)
    data = SCRIPT.compute("Plot", context)
    return AnalysisResult.of(context, "completed", data, found=SCRIPT.result_found("Plot", data))


def data_of(result: AnalysisResult) -> CorrelationData:
    data = result.data
    assert isinstance(data, CorrelationData)
    return data


RADIAL = {"corr_type": "radial", "corr_range": 0.4 * SCALE, "corr_bins": 40, "keep_percent": 100.0}


@pytest.fixture(scope="module")
def thermal() -> DatasetView:
    return txy_view(thermal_velocities(1))


# ---- the physics through the plot ----

def test_a_thermal_source_reads_g2_zero_of_two(thermal: DatasetView) -> None:
    result = run(thermal, RADIAL)
    data = data_of(result)
    found = data.result
    assert found is not None and found.ok, data.failure or (found.failure if found else "")
    zero = found.g2_zero
    assert math.isfinite(zero.se) and 0 < zero.se < 0.08
    assert abs(zero.value - EXPECTED_PEAK) < 3 * zero.se, zero
    assert found.fit is not None and abs(found.fit["sigma"].value - SIGMA_C * SCALE) < 0.01 * SCALE
    # The velocities came from the folder's t_r and origin, the events in mm/s.
    assert (data.release_how, data.origin_how) == ("folder", "manual") and data.origin == ORIGIN
    assert data.used == data.events == sum(len(v) for v in thermal.shots.values())
    line = correlations_plot.zero_line(data)
    assert line.startswith("g²(0) = ") and "over baseline" in line and line.endswith(" mm/s")
    assert correlations_plot.velocity_line(data) == "t_r 20,031.2 ms (folder) · origin (0.5, −0.4) mm (manual)"
    record = json.loads(json.dumps(result.found, allow_nan=False))
    assert record["correlation"]["g2_zero"]["value"] == pytest.approx(zero.value)
    assert record["velocity"]["release_time"] == T_R and record["velocity"]["origin_from"] == "manual"
    assert record["brief"].startswith("g²(0) ") and record["reuse"]["shots_used"] == list(range(1, 41))
    # The same events in recoils: the counts are the same, only the drawing's unit changes.
    recoil = data_of(run(thermal, {**RADIAL, "velocity_unit": "ħk"}))
    assert recoil.result is not None and np.array_equal(recoil.result.in_counts, found.in_counts)
    assert recoil.unit_value == pytest.approx(0.0920, rel=0.01)
    assert any("unconfirmed" in note for note in recoil.notes)


def test_an_uncorrelated_source_has_no_peak_and_g2_near_one() -> None:
    view = txy_view(poisson_velocities(5, 30, 400))
    for values in ({**RADIAL, "corr_bins": 20},
                   {"corr_range": 0.4 * SCALE, "corr_bins": 20, "corr_window": 0.05 * SCALE, "keep_percent": 100.0}):
        data = data_of(run(view, values))
        found = data.result
        assert found is not None and found.ok
        near = found.near_zero
        assert math.isfinite(near.se) and abs(near.value - 1) < 3 * near.se
        pulls = (found.g2 - 1) / found.se
        assert np.mean(np.abs(pulls) < 3) >= 0.9
        if math.isfinite(found.g2_zero.value):  # a spurious bump must be consistent with none
            assert abs(found.g2_zero.value - 1) < 3 * found.g2_zero.se + 0.05
        else:
            assert correlations_plot.zero_line(data).startswith("no peak: g² near 0 is ")


def test_back_to_back_pairs_peak_at_zero_with_the_trap_origin() -> None:
    values = {"corr_mode": "back-to-back", "corr_axis": "v_x", "corr_range": 0.1 * SCALE, "corr_bins": 40,
              "corr_window": 0.01 * SCALE, "keep_percent": 100.0, "n_boot": 100}
    events = pair_velocities(7)
    view = txy_view(events)
    data = data_of(run(view, values))
    found = data.result
    assert found is not None and found.fit is not None and found.fit.ok
    assert found.g2_zero.value - 1 > 5 * found.g2_zero.se
    assert abs(found.fit["centre"].value) < 0.003 * SCALE
    assert correlations_plot.separation_name(data.kind, data.source) == "v_x₁ + v_x₂"
    # Without the origin, X is measured from 0: v_x is off by x₀/τ and the pairs sum to 2x₀/t_f.
    unknown = data_of(run(view, values, folder={"release_time": T_R}))
    assert unknown.origin_how == "assumed" and "⚠ origin assumed (0, 0) mm" in correlations_plot.velocity_line(unknown)
    assert unknown.result is not None and unknown.result.fit is not None and unknown.result.fit.ok
    shift = 2 * ORIGIN[0] / CONSTANTS.fall_time
    assert abs(unknown.result.fit["centre"].value - shift) < 0.003 * SCALE
    # A source moving at v₀ set here: the peak at 0 again.
    moving = txy_view([v + np.array([0.0, 0.02, 0.0]) for v in events])
    off = data_of(run(moving, values))
    assert off.result is not None and off.result.fit is not None
    assert abs(off.result.fit["centre"].value - 0.04) < 0.003 * SCALE
    centred = data_of(run(moving, {**values, "bb_source": "set here", "bb_vx": 0.02}))
    assert centred.result is not None and centred.result.fit is not None
    assert abs(centred.result.fit["centre"].value) < 0.003 * SCALE
    assert correlations_plot.separation_name(centred.kind, centred.source) == "v_x₁ + v_x₂ − 2v₀"
    # Re-centring each shot does the same, from each shot's own centre.
    recentred = data_of(run(moving, {**values, "recentre": True}))
    assert recentred.result is not None and recentred.result.fit is not None
    assert abs(recentred.result.fit["centre"].value) < 0.003 * SCALE


def test_the_release_time_is_detected_when_unset_and_kept_while_within_its_se() -> None:
    velocities = poisson_velocities(9, 12, 400)
    view = txy_view(velocities[:11])
    first = data_of(run(view, {"keep_percent": 100.0}, folder={}, owner="detect-1"))
    assert first.release_how == "detected" and first.origin_how == "detected"
    assert first.release is not None and abs(first.release.value.value - T_R) < 1e-3
    assert abs(first.origin[0] - ORIGIN[0]) < 0.5e-3
    assert any(note.startswith("t_r detected in this run") for note in first.notes)
    later = view.with_shots({12: to_txy(velocities[11])}, {12: (12, 2_000, 8_000)})
    second = data_of(run(later, {"keep_percent": 100.0}, folder={}, owner="detect-1", live=True))
    assert second.release_how == "detected, kept" and second.origin_how == "detected, kept"
    assert second.release is not None and second.release.value.value == first.release.value.value
    assert second.reused == 11 and second.added == 1  # The kept t_r keeps the held counts.
    SCRIPT.plot_closed("Plot", "detect-1", PATH)
    # Nothing to detect from: a failure that says how to set it, never a crash.
    flat = view_of({1: np.full((5, 3), 1.0), 2: np.full((5, 3), 2.0)})
    data = data_of(run(flat, folder={}))
    assert data.failure.startswith("no release time: none set, and none detected")
    assert correlations_plot.empty_reason(data).startswith("No velocities: no release time")


# ---- Live, the cache, the budget, cancellation ----

def counting_in_shot(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count the in-shot histograms actually computed (not read from the cache)."""
    calls: list[int] = []
    original = correlations.in_shot_counts

    def counted(*args: Any, **kwargs: Any) -> correlations.InShot:
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(correlations, "in_shot_counts", counted)
    return calls


def test_live_adds_a_shot_without_counting_the_old_ones_again(monkeypatch: pytest.MonkeyPatch) -> None:
    velocities = thermal_velocities(3, shots=13, events=300)
    view = txy_view(velocities[:12])
    calls = counting_in_shot(monkeypatch)
    values = {"corr_range": 0.4 * SCALE, "corr_window": 0.05 * SCALE, "n_boot": 50}
    first = data_of(run(view, values, owner="live-1"))
    assert (first.reused, first.added, len(calls)) == (0, 12, 12)
    later = view.with_shots({13: to_txy(velocities[12])}, {13: (13, 1_300, 8_000)})
    second = data_of(run(later, values, owner="live-1", live=True))
    assert second.box_kept and (second.reused, second.added, len(calls)) == (12, 1, 13)
    # Exactly what a fresh count of all 13 shots gives.
    fresh = data_of(run(later, values, owner="live-fresh"))
    assert second.result is not None and fresh.result is not None
    assert np.array_equal(second.result.in_counts, fresh.result.in_counts)
    assert np.array_equal(second.result.between_counts, fresh.result.between_counts)
    assert "12 shots held, 1 counted" in correlations_plot.counts_line(second)
    # A rerun of the same data counts nothing; a binning change counts every shot again.
    again = data_of(run(later, values, owner="live-1"))
    assert (again.reused, again.added) == (13, 0)
    rebinned = data_of(run(later, {**values, "corr_bins": 30}, owner="live-1"))
    assert rebinned.reused == 0 and rebinned.added == 13
    # Partners aren't in the in-shot key: the in-shot cache serves them, only pairs between shots are counted.
    before = len(calls)
    banded = data_of(run(later, {**values, "corr_bins": 30, "partners": "neighbouring shots", "partners_k": 3},
                         owner="live-1"))
    assert banded.reused == 0 and len(calls) == before
    for owner in ("live-1", "live-fresh"):
        SCRIPT.plot_closed("Plot", owner, PATH)


@pytest.mark.parametrize("change", ["release time", "mask", "origin", "view range"])
def test_what_changes_the_velocities_starts_the_count_again(monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    view = txy_view(poisson_velocities(4, 6, 300))
    values: dict[str, Any] = {"corr_range": 0.4 * SCALE, "corr_window": 0.05 * SCALE, "n_boot": 0}
    calls = counting_in_shot(monkeypatch)
    owner = f"change-{change}"
    run(view, values, owner=owner)
    folder = dict(FOLDER)
    if change == "release time":
        folder["release_time"] = T_R + 1e-4
    elif change == "origin":
        folder["trap_x"] = ORIGIN[0] + 1e-4
    elif change == "mask":
        values |= {"mask_mode": "custom", "mask_circles": "0.5, -0.4, 1, cut"}
    else:
        values |= {"keep_percent": 90.0}
    changed = data_of(run(view, values, folder=folder, owner=owner))
    assert changed.reused == 0 and changed.added == 6 and len(calls) == 12
    if change == "mask":
        assert changed.masked > 0
    SCRIPT.plot_closed("Plot", owner, PATH)


def test_the_time_budget_covers_the_shots_counted_and_the_next_run_goes_on(monkeypatch: pytest.MonkeyPatch) -> None:
    view = txy_view(poisson_velocities(6, 10, 300))
    ticks = itertools.count()
    monkeypatch.setattr(correlations_plot, "CLOCK", lambda: float(next(ticks)))  # each add one "second"
    values = {"corr_range": 0.4 * SCALE, "corr_window": 0.05 * SCALE, "n_boot": 20, "budget": 4.0}
    result = run(view, values, owner="budget-1")
    partial = data_of(result)
    assert partial.result is not None and not partial.result.complete
    assert partial.result.shots_used == (1, 2, 3)  # read at the start and before each add
    assert any("stopped at the time budget: 3 of 10 shots used" in note for note in partial.all_notes())
    assert any(note.startswith("Rerun or Live's next shots continue") for note in partial.notes)
    assert "3 of 10 shots (time budget)" in correlations_plot.brief(partial)
    assert result.found["reuse"]["shots_used"] == [1, 2, 3]
    monkeypatch.setattr(correlations_plot, "CLOCK", lambda: 0.0)
    finished = data_of(run(view, values, owner="budget-1"))
    assert finished.result is not None and finished.result.complete and finished.reused == 3
    assert finished.added == 7
    SCRIPT.plot_closed("Plot", "budget-1", PATH)


class LateCancel(threading.Event):
    """Set after ``polls`` checks: a cancel that comes inside the pair loop."""

    def __init__(self, polls: int) -> None:
        super().__init__()
        self.polls = polls

    def is_set(self) -> bool:
        self.polls -= 1
        return self.polls < 0


def test_cancelling_stops_the_count_and_the_next_run_finishes_it() -> None:
    view = txy_view(poisson_velocities(8, 8, 2000))
    values = {"corr_type": "radial", "corr_range": 0.4 * SCALE, "n_boot": 0}
    with pytest.raises(Cancelled):
        run(view, values, owner="cancel-1", cancel=LateCancel(12))
    done = data_of(run(view, values, owner="cancel-1"))
    fresh = data_of(run(view, values))
    assert done.result is not None and fresh.result is not None and done.result.complete
    assert np.array_equal(done.result.in_counts, fresh.result.in_counts)
    assert np.array_equal(done.result.between_counts, fresh.result.between_counts)
    SCRIPT.plot_closed("Plot", "cancel-1", PATH)


def test_closing_a_plot_drops_its_state_for_good() -> None:
    view = txy_view(poisson_velocities(10, 4, 200))
    held = correlations_plot.held_states()
    run(view, {"n_boot": 0}, owner="closing-1")
    assert correlations_plot.held_states() == held + 1
    SCRIPT.plot_closed("Plot", "closing-1", PATH)
    assert correlations_plot.held_states() == held
    run(view, {"n_boot": 0}, owner="closing-1")  # A late run of the closed plot keeps nothing.
    assert correlations_plot.held_states() == held
    run(view, {"n_boot": 0})  # Nor does a run no plot asked for.
    assert correlations_plot.held_states() == held
    # Another folder starts anew.
    run(view, {"n_boot": 0}, owner="closing-2")
    other = view_of({shot: events for shot, events in view.shots.items()}, "other")
    state = correlations_plot.plot_state("closing-2", other.identity.source_path + "/x")
    assert state.counts is None
    SCRIPT.plot_closed("Plot", "closing-2", PATH)


# ---- drawing, text and registration ----

def test_the_plot_draws_g2_its_fit_and_the_pairs(qtbot: QtBot, thermal: DatasetView) -> None:
    result = run(thermal, RADIAL)
    widget = SCRIPT.render(result)
    qtbot.addWidget(widget)
    assert isinstance(widget, CorrelationPlot)
    data = data_of(result)
    assert data.result is not None
    x, y = widget.points.getData()
    assert len(x) == data.result.spec.bins and x[-1] == pytest.approx(data.result.centres[-1] / 1e-3)
    assert len(widget.curve.getData()[0]) > 100 and widget.level.isVisible()
    assert "g²(0) = " in widget.title.text and "|Δv| (mm/s)" in widget.g2.getAxis("bottom").labelText
    assert SCRIPT.update(widget, result)
    # An empty result draws anew: nothing chosen, everything masked, no velocities.
    view = txy_view(poisson_velocities(11, 3, 50))
    masked = run(view, {"mask_mode": "custom", "mask_circles": "0, 0, 1000, cut"})
    assert not SCRIPT.update(widget, masked)
    assert correlations_plot.empty_reason(data_of(masked)).endswith("masked out (Mask settings)")


def test_settings_lines_and_registration() -> None:
    view = txy_view(poisson_velocities(12, 3, 50))
    values = effective(SCRIPT.parameters("Plot"), {"corr_mode": "back-to-back", "bb_source": "set here",
                                                   "bb_vz": 0.001, "partners": "neighbouring shots"})
    selection, settings = SCRIPT.describe_run("Plot", values, view)
    assert selection == "3 shots"
    assert settings == ("auto-crop 99 % · back-to-back 1D v_z · ± 20 mm/s · 40 bins · window ± 2 mm/s · "
                        "v₀ (1, 0, 0) mm/s · reference ± 10 shots · bootstrap 200 · budget 30 s")
    names = {spec.name: spec for spec in SCRIPT.parameters("Plot")}
    for name in ("corr_range", "corr_window", "bb_vz", "release_search_min", "const.trap_x"):
        assert names[name].unit_prefix == "m", name
    assert SCRIPT.constant_keys("Plot") == correlations_plot.CONSTANT_KEYS
    assert SCRIPT.live_policy("Plot").min_delay == 5.0
    assert correlations_plot in standard.MODULES
    metadata = SCRIPT.get_metadata()
    assert (metadata.analysis_id, metadata.version, metadata.name) == ("helab.correlations", "1", "Correlations")
    assert SCRIPT.parameter_warnings("Plot", {**values, "release_search_min": 2.0, "release_search_max": 1.0})
