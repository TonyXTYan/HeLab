"""D4/D14 in the T, X, Y histograms: the TF + Bose fits' condensate decision on the fit line, and the
"BEC properties" readout (``bec_readout``) on synthetic events of a known condensate, a thermal cloud
and a slice fit; the trap's constants only while a bimodal fit or the readout uses them."""
from __future__ import annotations

import html
import json
import math
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest
from pytestqt.qtbot import QtBot

from helab.analysis import bec, bec_readout
from helab.analysis.dataset_view import DatasetView
from helab.analysis.parameter_tree import build_tree, parameter_of
from helab.analysis.physics import ResolvedConstants, resolve
from helab.analysis.profiles import BIMODAL_BOSE, BIMODAL_SLICE, GAUSSIAN
from helab.analysis.results import AnalysisResult
from helab.scripts.dld import basic_plots
from helab.utils.colours import AMBER

sys.path.insert(0, str(Path(__file__).parent))
from test_histogram_fits import run, view_of  # noqa: E402

Array = npt.NDArray[np.float64]
# X is a radial axis (Y the trap's long one), so a TF radius on X gives R(0).
LAYERS = {"folder": {"trap_axial_axis": 3.0}}
CONSTANTS = resolve(folder={"trap_axial_axis": 3.0})
QE, SHOTS, CONDENSED, TEMPERATURE = 0.1, 5, 3e5, 0.6e-6
ALL_EVENTS = {"keep_percent": 100.0}  # N counts the events in range: keep them all


@lru_cache(maxsize=None)
def truth(constants: ResolvedConstants = CONSTANTS) -> dict[str, float]:
    """The thermal atoms of a saturated ideal cloud at ``TEMPERATURE``, the condensate's R(0), its
    R at the detector along a radial axis, and the thermal σ there (bec tests' synthetic cloud)."""
    trap = bec.Trap.from_constants(constants)
    thermal = bec.ZETA3 * (constants.k_B * TEMPERATURE / (constants.hbar * trap.mean)) ** 3
    a_ho = trap.oscillator_length(constants)
    mu = 0.5 * constants.hbar * trap.mean * (15 * CONDENSED * constants.scattering_length / a_ho) ** 0.4
    r0 = math.sqrt(2 * mu / (constants.mass * trap.radial ** 2))
    return {"thermal": thermal, "r0": r0, "radius": r0 * bec.scaling_factors(trap.omegas, constants.fall_time)[0],
            "sigma": math.sqrt(constants.k_B * TEMPERATURE / constants.mass) * constants.fall_time}


def tf_sample(rng: np.random.Generator, count: int, radius: float) -> Array:
    """X of a TF condensate's full projection (1 − u²)², by its CDF."""
    u = np.linspace(-1.0, 1.0, 20_001)
    cdf = (u - 2 * u ** 3 / 3 + u ** 5 / 5) * 15 / 16 + 0.5
    return np.asarray(np.interp(rng.random(count), cdf, u) * radius, dtype=np.float64)


def bose_sample(rng: np.random.Generator, count: int, sigma: float, fugacity: float) -> Array:
    """X of an ideal Bose gas's full projection g_5/2(z e^{−x²/2σ²}): Gaussians of σ/√k weighted
    z^k/k³ (``test_bose_fits.bose_counts``'s terms)."""
    k = np.arange(1, 400, dtype=np.float64)
    weights = fugacity ** k / k ** 3
    terms = rng.choice(k, count, p=weights / weights.sum())
    return np.asarray(rng.normal(0.0, sigma / np.sqrt(terms)), dtype=np.float64)


def events_view(condensed: float, fugacity: float = 1.0, seed: int = 5) -> DatasetView:
    """``SHOTS`` shots of a condensate of ``condensed`` atoms on a thermal cloud (saturated, or at
    ``fugacity`` and the saturated cloud's atom number), detected at ``QE``, along X."""
    known, rng = truth(), np.random.default_rng(seed)
    shots = {}
    for shot in range(1, SHOTS + 1):
        x = np.concatenate([tf_sample(rng, int(rng.poisson(condensed * QE)), known["radius"]),
                            bose_sample(rng, int(rng.poisson(known["thermal"] * QE)), known["sigma"], fugacity)])
        shots[shot] = np.column_stack([rng.normal(0.4165, 0.003, len(x)), x, rng.normal(0.0, 0.01, len(x))])
    return view_of(shots)


@lru_cache(maxsize=None)
def condensate_view() -> DatasetView:
    return events_view(CONDENSED)


def bec_run(values: dict[str, Any], layers: dict[str, dict[str, float]] | None = None,
            view: DatasetView | None = None) -> AnalysisResult:
    return run(view or condensate_view(), {**ALL_EVENTS, "bec_properties": True, **values},
               LAYERS if layers is None else layers)


def within(estimate: Any, value: float, sigmas: float = 3.0) -> bool:
    return bool(abs(estimate.value - value) < sigmas * estimate.se)


def test_a_condensate_gives_n0_over_n_and_its_properties_within_their_errors(qtbot: QtBot) -> None:
    """3·10⁵ condensed atoms on 1.9·10⁵ thermal ones at 0.6 µK, QE 0.1, 5 shots: the fit line says
    N0/N, and N, N0, N0/N, T, R(0) (from N0 and fitted), and both QE checks come back within 3 SE."""
    result = bec_run({"fit_x": True, "fit_x_model": BIMODAL_BOSE})
    data = result.data
    fit = data.fits[1]
    assert fit is not None and fit.ok and fit.decision.startswith("condensate: ")
    assert "N0/N 0.6" in fit.text() and "± " in fit.text()
    readout = data.bec
    assert readout is not None and readout.axis == "X" and readout.properties is not None
    props, known = readout.properties, truth()
    atoms = CONDENSED + known["thermal"]
    assert within(props.atoms, atoms) and within(props.condensed, CONDENSED)
    assert within(props.fraction, CONDENSED / atoms) and within(props.temperature, TEMPERATURE)
    assert within(props.radii[0], known["r0"])
    check = props.from_radius
    assert check is not None and within(check.in_trap, known["r0"]) and within(check.implied_qe, QE)
    assert within(props.implied_qe_thermal, QE)
    # Tc from N (hand formula: bec tests), T/Tc below 1.
    assert math.isfinite(props.tc.value) and 0 < props.t_over_tc.value < 1
    block = readout.title_lines()[0]
    for words in ("BEC properties from X (Bimodal TF² + Bose g_5/2)", "N (", "N0/N 0.6", "T (", "nK", "Tc (",
                  "Tc0 (", "T/Tc ", "μ/k_B (", "R(0) ⊥ (", "µm", "n0 (", "cm⁻³", "QE from R ", "QE from thermal "):
        assert words in block, words
    lines = readout.record_lines()
    assert lines[0].startswith("BEC properties from X") and "Tc ideal (" in lines[0] and "Tc finite size (" in lines[0]
    assert any(line.startswith("BEC note: N and N0 per shot") for line in lines)
    # The record: strict JSON, with every number; its lines are the dock's.
    record = json.loads(json.dumps(dict(result.found), allow_nan=False))
    assert record["bec"]["axis"] == "X" and record["bec"]["properties"]["fraction"]["value"] == pytest.approx(
        props.fraction.value)
    assert set(lines) <= set(record["record_lines"])
    # Drawn: the block in the header, the fit line in X's title.
    widget: Any = basic_plots.TxyHistograms().render(result)
    qtbot.addWidget(widget)
    header = html.unescape(widget.header.text)
    assert "BEC properties from X" in header and "QE from R" in header
    title = html.unescape(widget.plots[1].titleLabel.text)
    assert html.unescape(fit.text()) in title and "condensate: " not in title  # The why is in the record.


def test_a_thermal_cloud_says_no_condensate() -> None:
    """A Bose cloud at z = 0.5 (above Tc): the TF + Bose choice keeps the free-z fit and says
    "no condensate (z = …)" on its line (not in amber); the readout has N, T, Tc and T/Tc only."""
    view = events_view(0.0, fugacity=0.5, seed=8)
    result = bec_run({"fit_x": True, "fit_x_model": BIMODAL_BOSE}, view=view)
    fit = result.data.fits[1]
    assert fit is not None and fit.ok and fit.fit.model.key == "bose_g2_5"
    assert "no condensate (z = " in fit.text() and "N0/N" not in fit.text()
    readout = result.data.bec
    assert readout is not None and readout.properties is not None
    assert readout.properties.condensed.value == 0
    items = readout.items()
    assert items[0].startswith("N (") and "no condensate (thermal fit)" in items
    assert not any(item.startswith(("N0", "μ", "R(0)", "n0", "QE")) for item in items)
    assert any(item.startswith("Tc (") for item in items) and any(item.startswith("T/Tc") for item in items)
    widget: Any = basic_plots.TxyHistograms().render(result)
    title = widget.plots[1].titleLabel.text
    assert f'<span style="color: {AMBER}">no condensate' not in title and "no condensate (z = " in html.unescape(title)
    widget.deleteLater()


def test_a_possible_condensate_is_named_in_amber() -> None:
    """With a QE 10× too low the condensate's μ from N0 disagrees with its R/σ_th: "possible
    condensate, not reported" on the line, and why in amber."""
    result = bec_run({"fit_x": True, "fit_x_model": BIMODAL_BOSE},
                     {"lab": {"detector_qe": 0.01}, "folder": {"trap_axial_axis": 3.0}})
    fit = result.data.fits[1]
    assert fit is not None and fit.decision.startswith("possible condensate")
    assert "possible condensate, not reported (z = " in fit.text()
    widget: Any = basic_plots.TxyHistograms().render(result)
    title = widget.plots[1].titleLabel.text
    assert f'<span style="color: {AMBER}">possible condensate' in title
    widget.deleteLater()


def test_a_slice_fit_gives_t_and_r0_only() -> None:
    result = bec_run({"fit_x": True, "fit_x_model": BIMODAL_SLICE})
    readout = result.data.bec
    assert readout is not None and readout.slice and readout.properties is not None
    names = [item.split(" (")[0] for item in readout.items()]
    assert names == ["T", "R(0) fitted on X"], names
    assert "slice: T and R(0) only" in readout.heading()
    assert "N0/N (slice)" in result.data.fits[1].text()
    # A slice gives no atom numbers: the QE isn't flagged, the trap frequencies are.
    assert readout.unconfirmed == ("trap_radial", "trap_axial")
    json.dumps(dict(result.found), allow_nan=False)


def test_unconfirmed_constants_are_flagged_in_amber(qtbot: QtBot) -> None:
    result = bec_run({"fit_x": True, "fit_x_model": BIMODAL_BOSE})
    widget: Any = basic_plots.TxyHistograms().render(result)
    qtbot.addWidget(widget)
    assert f'<span style="color: {AMBER}">⚠ unconfirmed: QE 0.1' in widget.header.text
    assert "trap 500 Hz / 50 Hz" in widget.header.text
    confirmed = bec_run({"fit_x": True, "fit_x_model": BIMODAL_BOSE},
                        {"lab": {"detector_qe": 0.1}, "folder": {"trap_axial_axis": 3.0, "trap_radial": 500.0,
                                                                 "trap_axial": 50.0}})
    assert confirmed.data.bec is not None and confirmed.data.bec.unconfirmed == ()
    assert confirmed.data.bec.unconfirmed_text() == ""


def test_the_readout_is_off_by_default_and_names_why_it_has_nothing() -> None:
    script = basic_plots.TxyHistograms()
    assert basic_plots.BEC.default is False and basic_plots.BEC.page == basic_plots.FITS_PAGE
    plain = run(condensate_view(), {"fit_x": True})
    assert plain.data.bec is None and "bec" not in plain.found
    no_fit = run(condensate_view(), {"bec_properties": True})
    assert no_fit.data.bec is not None and no_fit.data.bec.properties is None
    assert no_fit.data.bec.warnings() == ["BEC properties: need a fit: turn on Fit T, X or Y"]
    assert "BEC properties need a fit" in " ".join(script.parameter_warnings("Plot", no_fit.parameters))
    json.dumps(dict(no_fit.found), allow_nan=False)
    missing = bec_run({"fit_t": True, "bec_axis": "Y"})
    assert missing.data.bec.reason == "no fit on Y: turn on Fit Y"
    # auto: the fit with a condensate, here X (T is radial too, but a Gaussian).
    auto = bec_run({"fit_t": True, "fit_x": True, "fit_x_model": BIMODAL_BOSE})
    assert auto.data.bec.axis == "X"
    assert bec_run({"fit_t": True, "fit_x": True}).data.bec.axis == "T"  # radial (X is too), first
    settings = script.describe_run("Plot", auto.parameters, condensate_view())[1]
    assert settings.endswith("BEC properties (auto)")


def test_the_trap_constants_are_used_only_with_a_bimodal_fit_or_the_readout() -> None:
    script = basic_plots.TxyHistograms()
    assert script.constant_keys("Plot") == basic_plots.CONSTANT_KEYS
    assert len(set(basic_plots.CONSTANT_KEYS)) == len(basic_plots.CONSTANT_KEYS)
    plain = run(condensate_view(), {})
    assert plain.resolved_constants is None and "constants" not in plain.reuse_key()
    gaussian = run(condensate_view(), {"fit_x": True, "fit_x_model": GAUSSIAN})
    assert gaussian.constant_keys == basic_plots.FIT_KEYS and "QE =" not in gaussian.describe()
    assert "constants" in gaussian.reuse_key()
    for values in ({"fit_x": True, "fit_x_model": BIMODAL_BOSE}, {"fit_x": True, "bec_properties": True}):
        used = run(condensate_view(), values)
        assert used.constant_keys == basic_plots.CONSTANT_KEYS
        assert used.describe().count("Constants: ") == 1 and "QE = 0.1 (default, unconfirmed)" in used.describe()
        assert used.reuse_key()["constants"]["values"]["detector_qe"] == 0.1
    # The fits' record of the constants is the result's own (the keys the run used, both ways).
    for values in ({"fit_x": True}, {"fit_x": True, "bec_properties": True}):
        used = run(condensate_view(), values, LAYERS)
        record = used.constants_record
        assert record is not None and used.found["constants"] == {key: record[key] for key in record if key != "layers"}
    # A setting the run doesn't use (hidden) doesn't change the reuse key; a used one does.
    base = run(condensate_view(), {"fit_x": True})
    assert run(condensate_view(), {"fit_x": True, "smooth_xy": 3e-4}).reuse_key() == base.reuse_key()
    assert run(condensate_view(), {"fit_x": True, "bec_axis": "Y"}).reuse_key() == base.reuse_key()
    assert run(condensate_view(), {"fit_x": True, "fit_x_model": BIMODAL_BOSE}).reuse_key() != base.reuse_key()
    assert "fit_y_model" not in base.reuse_key()["parameters"] and "fit_x_model" in base.reuse_key()["parameters"]
    # A bimodal model chosen for an axis that isn't fitted uses nothing more.
    assert not basic_plots.bec_constants_used({"fit_x": False, "fit_x_model": BIMODAL_BOSE})
    # The settings list the trap's rows (once each) only then.
    specs = script.parameters("Plot")
    names = [spec.name for spec in specs]
    assert len(names) == len(set(names))
    root = build_tree(specs)
    by_name = {spec.name: spec for spec in specs}
    qe = parameter_of(root, by_name["const.detector_qe.from"])
    fall = parameter_of(root, by_name["const.fall_distance.from"])
    bec_axis = parameter_of(root, by_name["bec_axis"])
    assert not qe.opts["visible"] and fall.opts["visible"] and not bec_axis.opts["visible"]
    parameter_of(root, by_name["fit_x"]).setValue(True)
    assert not qe.opts["visible"]
    parameter_of(root, by_name["fit_x_model"]).setValue(BIMODAL_BOSE)
    assert qe.opts["visible"]
    parameter_of(root, by_name["fit_x_model"]).setValue(GAUSSIAN)
    parameter_of(root, by_name["bec_properties"]).setValue(True)
    assert qe.opts["visible"] and bec_axis.opts["visible"]
    own = parameter_of(root, by_name["const.detector_qe"])
    assert not own.opts["visible"]
    qe.setValue("this plot")
    assert own.opts["visible"]
    parameter_of(root, by_name["bec_properties"]).setValue(False)
    assert not own.opts["visible"] and not qe.opts["visible"]


def test_the_readout_chooses_by_condensate_projection_and_role() -> None:
    """``choose`` without a usable fit says why."""
    assert bec_readout.choose({}, CONSTANTS) == ("", "need a fit: turn on Fit T, X or Y")
    assert basic_plots.TxyHistograms().get_metadata().version == "1"
