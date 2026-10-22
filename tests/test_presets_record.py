"""The preset and arrangement records (helab/analysis/presets.py): each saved value checked against
the installed parameters, every incompatibility named and never applied, records that can't be
read named, and the formats round-tripping."""
from __future__ import annotations

import json

import pytest

from helab.analysis.follow import LivePolicy, live_specs
from helab.analysis.identity import AnalysisIdentity
from helab.analysis.parameters import ParameterSpec
from helab.analysis.presets import (FORMAT, Arrangement, RecordError, SavedPlot, ScriptPreset, ScriptPresets,
                                    ScriptRef, check_plot, check_value, check_values, is_waiting, parse, preset_note,
                                    waiting_view)

SPECS = [
    ParameterSpec("bins", "Bins", "int", 100, (1, 1000)),
    ParameterSpec("width", "Width", "float", 0.002, (0.0, 1.0), " s", si=True, unit_prefix="m"),
    ParameterSpec("mode", "Mode", "choice", "counts", choices=("counts", "rate")),
    ParameterSpec("log", "Log Y", "bool", False),
    ParameterSpec("mask", "Mask", "text", ""),
]
IDENTITY = AnalysisIdentity("tests.plot", "2", "plot.py", "abc")
REF = ScriptRef("tests.plot", "Plot", "2", "abc", "Test plot")


def test_values_that_fit_apply_exactly() -> None:
    checked = check_values(SPECS, {"bins": 5, "width": 0.25, "mode": "rate", "log": True, "mask": "0, 0, 1"})
    assert checked.values == {"bins": 5, "width": 0.25, "mode": "rate", "log": True, "mask": "0, 0, 1"}
    assert checked.problems == ()
    assert type(checked.values["width"]) is float
    # A whole number for a float, and a whole float for an int, are the same value: they fit.
    assert check_value(SPECS[1], 0) == (0.0, "") and check_value(SPECS[0], 7.0) == (7, "")


@pytest.mark.parametrize("name, value, reason", [
    ("bins", 5000, "saved 5,000 is outside 1 to 1,000"),
    ("bins", 2.5, "saved 2.5 isn't a whole number"),
    ("bins", "many", "saved 'many' isn't a number"),
    ("bins", True, "saved True isn't a number"),
    ("width", 2.0, "saved 2,000 ms is outside 0 ms to 1,000 ms"),
    ("width", float("nan"), "saved nan isn't a number"),
    ("mode", "radial", "saved “radial” is no longer a choice (counts, rate)"),
    ("mode", 3, "saved 3 isn't one of its choices"),
    ("log", "yes", "saved 'yes' isn't on or off"),
    ("mask", 4, "saved 4 isn't text"),
])
def test_each_incompatible_value_is_named_and_not_applied(name: str, value: object, reason: str) -> None:
    saved = {spec.name: spec.default for spec in SPECS} | {name: value}
    checked = check_values(SPECS, saved)
    assert name not in checked.values  # Never clamped or replaced: left to the caller's value.
    assert [(problem.name, problem.reason) for problem in checked.problems] == [(name, reason)]


def test_unknown_and_missing_keys_are_named() -> None:
    saved = {"bins": 5, "width": 0.1, "mode": "rate", "log": True, "old_setting": 1}
    checked = check_values(SPECS, saved)
    assert [(problem.title, problem.reason) for problem in checked.problems] == [
        ("Mask", "not saved"), ("old_setting", "not a setting of this script now")]
    assert set(checked.values) == {"bins", "width", "mode", "log"}


def test_a_plot_check_covers_library_live_and_version() -> None:
    live = live_specs(LivePolicy(5, 2.0))
    saved = SavedPlot(ScriptRef("tests.plot", "Plot", "1", "old"), "/data/run",
                      values={"bins": 5000, "width": 0.1, "mode": "rate", "log": True, "mask": ""},
                      backend="Bokeh", live={"live_follow": False, "live_every": 10, "live_delay": 1.0})
    check = check_plot(saved, IDENTITY, SPECS, ("PyQtGraph", "Plotly"), live)
    assert check.values == {"width": 0.1, "mode": "rate", "log": True, "mask": ""}
    assert check.live == {"live_follow": False, "live_every": 10, "live_delay": 1.0}
    assert check.backend == ""
    assert [problem.title for problem in check.problems] == ["Bins", "Library"]
    assert check.notes == ("saved with v1, now v2",)
    summary = check.summary()
    assert summary.startswith("⚠ 2 settings at the script's defaults: Bins, Library") and "saved with v1, now v2" in summary
    assert check.summary("left as they were").startswith("⚠ 2 settings left as they were")
    assert "Library: saved “Bokeh” is no longer a choice (PyQtGraph, Plotly)" in check.details()
    # A library saved for a script that no longer chooses one, and none saved for one that does.
    assert check_plot(SavedPlot(REF, "/d", values={}, backend="Plotly"), IDENTITY, [], (), ()).problems[0].reason \
        == "this plot no longer chooses a library"
    assert check_plot(SavedPlot(REF, "/d"), IDENTITY, [], ("A", "B"), ()).problems[0].reason == "not saved"
    # The same version from another copy of the file: said, applied the same.
    other = check_plot(SavedPlot(ScriptRef("tests.plot", "Plot", "2", "zzz"), "/d"), IDENTITY, [], (), ())
    assert other.notes == ("saved from another copy of v2 (its file differs)",) and not other.problems


def test_a_script_preset_has_no_live_group() -> None:
    preset = ScriptPreset("fast", REF, {spec.name: spec.default for spec in SPECS}, "Plotly", 1.0)
    check = check_plot(preset, IDENTITY, SPECS, ("PyQtGraph", "Plotly"), live_specs(LivePolicy()))
    assert check.live == {} and check.problems == () and check.backend == "Plotly"


def test_an_arrangement_round_trips() -> None:
    plot = SavedPlot(REF, "/data/run", "root://u/run", {"bins": 5, "mask": "1, 2, 3"}, "Plotly",
                     {"live_follow": False}, "3", "Test plot (3)", True, 420, True, 1, True, "helab-plot-0",
                     "fast", 12.5)
    arrangement = Arrangement((plot,), "/data/run", "root://u/run", True, "AAAA", 99.0)
    again = parse(arrangement.dumps())
    assert again == arrangement
    assert json.loads(arrangement.dumps())["format"] == FORMAT


@pytest.mark.parametrize("text, reason", [
    ("{not json", "not valid JSON"),
    ("[]", "not an arrangement record"),
    ('{"plots": []}', "no format version"),
    (json.dumps({"format": FORMAT + 1, "plots": []}), "saved by a newer HeLab"),
    (json.dumps({"format": FORMAT, "plots": {}}), "its plots aren't a list"),
    (None, "not text"),
])
def test_an_unreadable_arrangement_says_why(text: str | None, reason: str) -> None:
    with pytest.raises(RecordError, match=reason):
        parse(text)


def test_an_unreadable_plot_is_left_out_and_named() -> None:
    good = SavedPlot(REF, "/data/run").to_json()
    text = json.dumps({"format": FORMAT, "plots": [good, {"script": {"analysis_id": "x", "action": "Plot"}},
                                                   {"script": {}}, "nonsense"]})
    arrangement = parse(text)
    assert [plot.script.analysis_id for plot in arrangement.plots] == ["tests.plot"]
    assert arrangement.unreadable == ("x: no folder", "no script id", "not a plot record")


def test_script_presets_keep_what_they_cant_read() -> None:
    first = ScriptPreset("fast", REF, {"bins": 5}, "", 1.0)
    text = ScriptPresets().with_preset(first)
    data = json.loads(text)
    data["presets"]["broken"] = {"format": FORMAT, "values": 3}
    data["presets"]["newer"] = {"format": FORMAT + 1}
    presets = ScriptPresets.parse(json.dumps(data))
    assert presets.names() == ["fast"] and presets.presets["fast"] == first
    assert presets.unreadable == {"broken": "its settings aren't a record", "newer": "saved by a newer HeLab (format 2)"}
    # Saving or deleting another keeps the unreadable ones as they were.
    kept = json.loads(presets.with_preset(ScriptPreset("slow", REF, {}, "", 2.0)))["presets"]
    assert kept["broken"] == data["presets"]["broken"] and set(kept) == {"fast", "broken", "newer", "slow"}
    assert set(json.loads(presets.without("fast"))["presets"]) == {"broken", "newer"}


@pytest.mark.parametrize("text, reason", [
    ("{oops", "not valid JSON"), ('{"presets": {}}', "no format version"), ('{"format": 1}', "not a presets record"),
    (json.dumps({"format": FORMAT + 1, "presets": {}}), "saved by a newer HeLab")])
def test_unreadable_script_presets_are_named_never_raised(text: str, reason: str) -> None:
    presets = ScriptPresets.parse(text)
    assert reason in presets.error and presets.names() == []
    with pytest.raises(RecordError, match="can't be read"):
        presets.with_preset(ScriptPreset("x", REF))
    assert ScriptPresets.parse(None).error == "" and ScriptPresets.parse("").names() == []


def test_a_preset_changed_or_deleted_since_is_said() -> None:
    plot = SavedPlot(REF, "/d", preset="fast", preset_saved_at=1.0)
    same = ScriptPresets.parse(ScriptPresets().with_preset(ScriptPreset("fast", REF, {}, "", 1.0)))
    changed = ScriptPresets.parse(ScriptPresets().with_preset(ScriptPreset("fast", REF, {}, "", 2.0)))
    assert preset_note(plot, same) == ""
    assert preset_note(plot, changed) == "preset “fast” changed since: this arrangement's values are used"
    assert preset_note(plot, ScriptPresets()) == "preset “fast” deleted since: this arrangement's values are used"
    assert preset_note(SavedPlot(REF, "/d"), changed) == ""


def test_a_waiting_view_has_no_data() -> None:
    view = waiting_view("/data/run", "root://u/run")
    assert is_waiting(view) and view.identity.root_key == "root://u/run" and view.shot_numbers == ()
