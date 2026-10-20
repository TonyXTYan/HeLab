"""D8 part 1: the release time and trap origin as optional ("from the data") constants, and the
Release time plot that detects them and saves them for a folder on request."""
from __future__ import annotations

import json
import math
import re
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from pytestqt.qtbot import QtBot

from helab.analysis import constant_layers
from helab.analysis.constant_layers import (clean_layer, constants_specs, describe_constants, record_text,
                                           value_and_origin, value_text)
from helab.analysis.dataset_view import DatasetView, build_view
from helab.analysis.parameters import effective
from helab.analysis.physics import DEFAULTS, TABLE, ResolvedConstants, resolve
from helab.analysis.release import layer_origin, layer_release_time
from helab.analysis.results import AnalysisContext, AnalysisResult, Cancelled
from helab.scripts import standard
from helab.scripts.standard import release_time
from helab.scripts.standard.release_time import ReleasePlot, ReleaseTimePlot
from helab.utils.colours import AMBER
from helab.utils.folder_cache import Dataset

Array = npt.NDArray[np.float64]
RELEASE = 20.0312  # s, DLD time
ORIGIN = (3e-3, -2e-3)  # m
PATH = "/data/root/run_7"
SCRIPT = ReleaseTimePlot()


# Optional rows: from the data unless a layer sets them

def test_optional_rows_resolve_as_detected_when_unset() -> None:
    for key in ("release_time", "trap_x", "trap_y"):
        assert math.isnan(DEFAULTS.value(key)) and DEFAULTS.origins[key] == "detected" and not DEFAULTS.is_set(key)
        assert key not in DEFAULTS.unconfirmed
    folder = resolve(folder={"release_time": 20.03, "trap_x": -0.003, "trap_y": 0.0})
    assert (folder.release_time, folder.origins["release_time"]) == (20.03, "folder")
    assert (folder.trap_x, folder.trap_y) == (-0.003, 0.0) and folder.is_set("trap_y")  # Signed: 0 and below.
    assert resolve(lab={"trap_x": 0.001}, plot={"trap_x": 0.002}).origins["trap_x"] == "plot"
    for bad in ({"release_time": math.nan}, {"trap_x": math.inf}, {"g": -9.8}):
        with pytest.raises(ValueError):
            resolve(folder=bad)
    # Equal resolutions compare and hash equal, nan and all.
    assert resolve() == DEFAULTS and hash(resolve()) == hash(DEFAULTS) and len({resolve(), DEFAULTS}) == 1
    assert resolve(folder={"trap_x": 0.001}) != DEFAULTS


def test_records_of_optional_rows_are_json_and_round_trip() -> None:
    record = json.loads(json.dumps(DEFAULTS.as_record(), allow_nan=False))
    assert record["values"]["release_time"] is None and record["origins"]["release_time"] == "detected"
    assert ResolvedConstants.from_record(record) == DEFAULTS
    folder = resolve(folder={"release_time": 20.03, "trap_x": -0.003})
    assert ResolvedConstants.from_record(json.loads(json.dumps(folder.as_record()))) == folder
    # An older record, from before these rows: they read back as unset.
    older = {"values": {key: value for key, value in record["values"].items() if key not in ("release_time", "trap_x",
                                                                                              "trap_y")},
             "origins": {key: value for key, value in record["origins"].items() if key not in ("release_time",
                                                                                               "trap_x", "trap_y")}}
    assert ResolvedConstants.from_record(older) == DEFAULTS
    for broken in ({"values": {**record["values"], "release_time": 1.0}, "origins": record["origins"]},
                   {"values": record["values"], "origins": {**record["origins"], "release_time": "folder"}},
                   {"values": record["values"], "origins": {**record["origins"], "g": "detected"}}):
        with pytest.raises(ValueError):
            ResolvedConstants.from_record(broken)


def test_layers_text_and_changes_of_optional_rows() -> None:
    assert clean_layer({"trap_x": -0.003, "release_time": 20.0, "trap_y": "x", "g": -1.0, "fall_distance": 0.0}) == {
        "trap_x": -0.003, "release_time": 20.0}
    assert value_text("release_time", math.nan) == "from the data"
    assert value_text("release_time", 20.0312) == "20,031.2 ms" and value_text("trap_x", -0.003) == "−3 mm"
    assert value_and_origin(DEFAULTS, "trap_x") == "from the data"
    folder = resolve(folder={"release_time": 20.0312})
    assert value_and_origin(folder, "release_time") == "20,031.2 ms (folder)"
    assert describe_constants(DEFAULTS, ("release_time",)) == ""  # Not set: nothing to point out.
    assert describe_constants(DEFAULTS, ("release_time",), every=True) == "t_r from the data"
    assert record_text(folder, ("release_time", "trap_x")) == "t_r = 20,031.2 ms (folder), x₀ from the data"
    assert constant_layers.changed_keys(DEFAULTS, resolve()) == []
    assert constant_layers.changed_keys(DEFAULTS, folder) == ["release_time"]
    # A plot's own value of an optional row starts at 0 and may be negative.
    specs = {spec.name: spec for spec in constants_specs(("release_time", "trap_x"))}
    value = specs[constant_layers.value_name("trap_x")]
    assert value.default == 0.0 and value.limits == constant_layers.SIGNED_LIMITS and value.unit_prefix == "m"
    assert specs[constant_layers.value_name("release_time")].unit_prefix == "m"  # ms, as the plots


def test_layer_release_time_and_origin_for_the_velocity_plots() -> None:
    assert layer_release_time(DEFAULTS) is None and layer_origin(DEFAULTS) is None
    folder = resolve(folder={"release_time": 20.0312, "trap_x": 0.003, "trap_y": -0.002})
    given = layer_release_time(folder)
    assert given is not None and given.source == "manual" and given.value.value == 20.0312 and given.error == "none"
    assert layer_origin(folder) == (0.003, -0.002)
    assert layer_origin(resolve(folder={"trap_x": 0.003})) is None  # One axis alone isn't an origin.


def test_the_folder_dialog_and_editors_show_unset_rows(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.utils.folder_cache import FolderCache
    from helab.utils.io_service import IOService
    from helab.views.FolderConstantsDialog import FOLDER_ROWS, FolderConstantsDialog
    from helab.views.LabParametersTab import constant_editor
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    cache = FolderCache(service)
    try:
        assert {"release_time", "trap_x", "trap_y"} <= {row.key for row in FOLDER_ROWS}
        cache.remember_constants(PATH, {"values": {"trap_x": -0.003}, "set_at": 1.0})
        dialog = FolderConstantsDialog(PATH, cache)
        qtbot.addWidget(dialog)
        assert dialog.source_text("release_time") == "from the data (Release time plot)"
        assert dialog.editors["release_time"].value() == 0.0 and not dialog.editors["release_time"].isEnabled()
        assert dialog.source_text("trap_x") == "this folder" and dialog.editors["trap_x"].value() == -0.003
        dialog.set_here["release_time"].setChecked(True)
        dialog.editors["release_time"].setValue(20.0312)
        assert dialog.values() == {"trap_x": -0.003, "release_time": 20.0312}
        box = constant_editor(TABLE["trap_y"], 0.0)
        box.setValue(-0.002)
        assert box.value() == -0.002 and "mm" in box.text()
    finally:
        service.shutdown()


# The plot

def trajectories(rng: np.random.Generator, count: int, release: float, sigma_v: float = 0.003) -> Array:
    """Atoms released at rest (z up) from a trap above ``ORIGIN``, with a ``sigma_v`` spread."""
    v = rng.normal(0, sigma_v, (count, 3))
    g, h = DEFAULTS.g, DEFAULTS.fall_distance
    tau = (v[:, 0] + np.sqrt(v[:, 0] ** 2 + 2 * g * h)) / g
    return np.column_stack([release + tau, ORIGIN[0] + v[:, 1] * tau, ORIGIN[1] + v[:, 2] * tau])


def cloud_view(shots: int = 20, count: int = 1500, jitter: float = 50e-6, background: int = 100,
               seed: int = 0) -> tuple[DatasetView, list[float]]:
    """A single cloud per shot on a flat background, its release jittering by ``jitter`` (s)."""
    rng = np.random.default_rng(seed)
    data, releases = {}, []
    for shot in range(1, shots + 1):
        release = RELEASE + rng.normal(0, jitter)
        releases.append(release)
        flat = np.column_stack([rng.uniform(20.2, 20.7, background), rng.uniform(-0.03, 0.03, (background, 2))])
        events = np.concatenate([trajectories(rng, count, release), flat])
        data[shot] = events[np.argsort(events[:, 0])]
    prints = [[shot, 100 + shot, 1_700_000_000_000_000_000 + shot] for shot in data]
    return build_view(Dataset(PATH, "sig-release", data, {"fingerprint": prints}, 0)), releases


def run(view: DatasetView, values: dict[str, Any] | None = None, cancelled: bool = False) -> AnalysisResult:
    context = AnalysisContext("r1", "Plot", view, effective(SCRIPT.parameters("Plot"), values or {}),
                              SCRIPT.get_metadata().identity())
    if cancelled:
        context.cancel_event.set()
    data = SCRIPT.compute("Plot", context)
    return AnalysisResult.of(context, "completed", data, found=SCRIPT.result_found("Plot", data))


@pytest.fixture(scope="module")
def jittered() -> tuple[AnalysisResult, list[float]]:
    view, releases = cloud_view()
    return run(view, {"n_boot": 100}), releases


def test_a_single_cloud_gives_the_release_time_and_origin_within_their_se(
        jittered: tuple[AnalysisResult, list[float]]) -> None:
    result, releases = jittered
    found = result.data.release
    assert found is not None and found.ok and found.error == "shot bootstrap" and found.origin_found
    truth = float(np.mean(releases))
    assert abs(found.value.value - truth) < 3 * found.value.se
    # The bootstrap's error reflects the shot jitter (50 µs over 20 shots), far above the fit's.
    assert found.value.se == pytest.approx(50e-6 / math.sqrt(20), rel=0.5)
    assert found.within_run_se < found.value.se / 2
    for axis, value in zip(found.origin, ORIGIN):
        assert abs(axis.value - value) < 4 * axis.se
    assert found.fit is not None and found.fit.model.key == "arrival_time"
    record = result.found["release"]
    assert json.loads(json.dumps(record, allow_nan=False)) == record and record["error"] == "shot bootstrap"
    assert record["bootstrap"]["n_boot"] == 100 and record["origin"]["window"][0][0] < ORIGIN[0]
    key = result.reuse_key()
    assert json.loads(json.dumps(key)) == key


def test_more_jitter_more_error() -> None:
    steady, _ = cloud_view(shots=12, jitter=0.0, seed=1)
    shaky, _ = cloud_view(shots=12, jitter=200e-6, seed=1)
    calm = run(steady, {"n_boot": 60}).data.release
    loud = run(shaky, {"n_boot": 60}).data.release
    assert loud.value.se > 5 * calm.value.se
    # Without the bootstrap, the SE is the fit's: the jitter is left out, and the plot says so.
    alone = run(shaky, {"n_boot": 0}).data
    assert alone.release.error == "within run" and alone.release.value.se < loud.value.se / 3
    assert any("bootstrap off" in note for note in alone.all_notes())


def test_titles_and_record_read_in_ms_and_mm(jittered: tuple[AnalysisResult, list[float]]) -> None:
    result, _ = jittered
    lines = release_time.titles(result, result.data)
    assert lines[1].startswith("release t_r = 20,031.") and "ms (shot bootstrap) · arrival 20,4" in lines[1]
    assert "t_f 416.0908 ms (h 848 mm)" in lines[1]
    pattern = r"origin \((2\.9|3\.0)\d* ± 0\.0\d+, −(1\.9|2\.0)\d* ± 0\.0\d+\) mm · background .+"
    assert re.fullmatch(pattern, lines[2]), lines[2]
    record = "\n".join(SCRIPT.result_record("Plot", result))
    assert "the fit's SE alone, within run" in record and "Shot bootstrap: 100 resamples of 20 shots" in record
    assert "Fit: " in record and "events within" in record
    brief = SCRIPT.describe_result("Plot", result)
    assert brief.startswith("t_r 20,031.") and " · origin (" in brief and brief.endswith(" mm")
    first, second = SCRIPT.describe_run("Plot", effective(SCRIPT.parameters("Plot"), {"search_min": 20.4}),
                                        cloud_view(shots=2)[0])
    assert second == "search T from 20,400 ms · bootstrap 100"


def test_failures_and_search_warnings_are_said(qtbot: QtBot) -> None:
    rng = np.random.default_rng(3)
    flat = {shot: np.column_stack([np.sort(rng.uniform(20.0, 21.0, 20)), rng.uniform(-0.03, 0.03, (20, 2))])
            for shot in (1, 2)}
    view = build_view(Dataset(PATH, "sig-flat", flat, {"fingerprint": [[1, 1, 1], [2, 2, 2]]}, 0))
    result = run(view, {"search_min": 21.0, "search_max": 20.5})
    lines = release_time.titles(result, result.data)
    assert any(line.startswith("⚠ no release time: too few events") for line in lines), lines
    assert any("Search T: from 21,000 ms is at or above to 20,500 ms" in line for line in lines)
    widget = SCRIPT.render(result)
    qtbot.addWidget(widget)
    assert isinstance(widget, ReleasePlot) and not widget.use_button.isEnabled()
    assert f'<span style="color: {AMBER}">⚠ no release time' in widget.title.text
    with pytest.raises(Cancelled):
        run(cloud_view(shots=3)[0], cancelled=True)


class FakeCache(QObject):
    folderConstantsFailed = pyqtSignal(str, str, str)

    def __init__(self) -> None:
        super().__init__()
        self.lab_constants: dict[str, float] = {}
        self.own: dict[str, float] = {"fall_distance": 0.85, "trap_x": 0.0}
        self.saved: list[tuple[str, dict[str, float], str]] = []

    def effective_folder_constants(self, path: str) -> dict[str, float]:
        return dict(self.own)

    def folder_constants(self, path: str) -> dict[str, float]:
        return dict(self.own)

    def set_folder_constants(self, path: str, values: dict[str, float], *, owner: str = "") -> bool:
        self.saved.append((path, values, owner))
        return True

    def constants_session_only(self, path: str) -> str:
        return ""


def test_use_for_this_folder_saves_only_once_confirmed(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
                                                       jittered: tuple[AnalysisResult, list[float]]) -> None:
    result, _ = jittered
    found = result.data.release
    widget = SCRIPT.render(result)
    qtbot.addWidget(widget)
    assert isinstance(widget, ReleasePlot) and widget.use_button.isEnabled()
    cache = FakeCache()
    widget.cache = cache  # type: ignore[assignment]
    asked: list[str] = []
    answer = False

    def confirm(text: str, unsure: bool) -> bool:
        asked.append(text)
        return answer

    monkeypatch.setattr(widget, "confirm", confirm)
    assert not widget.use_for_folder() and cache.saved == []  # Cancelled: nothing written.
    assert "Release time t_r: 20,031." in asked[0] and "(now: from the data)" in asked[0]
    assert "Trap origin X x₀: " in asked[0] and "(now: 0 mm (folder))" in asked[0]
    answer = True
    widget.use_button.click()
    assert len(cache.saved) == 1
    path, values, owner = cache.saved[0]
    assert path == PATH and owner == widget.owner
    assert values == {"fall_distance": 0.85, "release_time": found.value.value, "trap_x": found.origin[0].value,
                      "trap_y": found.origin[1].value}  # Merged with what the folder sets.
    assert widget.status.text().startswith("Set for this folder")
    cache.folderConstantsFailed.emit(PATH, "disk full", "another")
    assert "Couldn't" not in widget.status.text()
    cache.folderConstantsFailed.emit(PATH, "disk full", widget.owner)
    assert "Couldn't save the constants for this folder: disk full" in widget.status.text()


def test_registered_with_constants_and_a_slow_live_policy() -> None:
    assert release_time in standard.MODULES
    metadata = SCRIPT.get_metadata()
    assert (metadata.name, metadata.analysis_id, metadata.version, metadata.group) == (
        "Release time", "helab.release_time", "1", "Basic plots v1")
    assert SCRIPT.constant_keys("Plot") == ("fall_distance", "fall_time", "g")
    assert SCRIPT.live_policy("Plot").min_delay >= 3
    specs = {spec.name: spec for spec in SCRIPT.parameters("Plot")}
    assert specs["search_min"].unit_prefix == "m" and specs["n_boot"].default == release_time.N_BOOT.default
