"""Presets of plots and the plots that reopen at start: the records and their validation
(roadmaps/presets-and-workspaces.md, stage 1).

A **script preset** (``ScriptPreset``) is one script's settings under a name: every parameter's
value as stored and its drawing library (not its Live group: when a plot reruns during Live is
about watching a folder, not about what the analysis computes), shared by every plot of that
script and action (``ScriptPresets``; each saved as its own record).

An **arrangement** is one folder's: the folder (its source path and, if known, its ``root://``
key), whether Live watches it, the plots open on it and where they sit (``dock_state``: the
plot area's ``saveState``, plus each plot's tab group and floating flag). Each plot
(``SavedPlot``) holds the script it was opened from (``ScriptRef``: id, action, version, file
hash), every parameter's value as stored (SI units, ``ParameterSpec``'s own storage), its drawing
library and its Live group. A named preset is one arrangement (Tony, 2026-10-22: one folder,
no several folders, pinned results or run history); the plots to reopen at start are another,
whose plots may each have their own folder. All are JSON with a format version (``FORMAT``).
An arrangement stores each plot's values itself and names the script preset last applied to the
plot (``SavedPlot.preset``) only as where they came from: changing or deleting that preset later
never changes the arrangement, and applying it says so (``preset_note``).

Saved values are checked against the installed script (``check_plot``): a key it no longer has,
a value of the wrong type, outside its limits or a choice it no longer offers, and a parameter
the record lacks are each named (``Problem``) and never replaced or clamped silently: the values
that fit apply, the others stay as they are (a new plot's: the script's defaults; an open plot
a script preset is applied to: its current values). A record saved by another version of the
script applies the same way, and says so (``PlotCheck.notes``).

No Qt, no I/O: the Qt side is ``helab/views/plots/presets.py`` and ``arrangement.py``.
"""
from __future__ import annotations

import base64
import binascii
import json
import math
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from helab.analysis.dataset_view import DatasetView, Provenance, ViewIdentity
from helab.analysis.identity import AnalysisIdentity
from helab.analysis.parameters import ParameterSpec, Value

FORMAT = 1  # The record's format; a newer one is read as unreadable (named), never guessed at.
LIBRARY = "Library"  # How the drawing library is named in problems.


class RecordError(ValueError):
    """A record (or one plot of it) that can't be read: its reason, for the user."""


@dataclass(frozen=True)
class ScriptRef:
    """The script a plot was opened from: its stable id and action, and the version and file
    hash it had then (``AnalysisIdentity``)."""
    analysis_id: str
    action: str
    version: str = ""
    file_hash: str = ""
    name: str = ""  # The script's name then, to name it when it isn't loaded.

    @classmethod
    def of(cls, identity: AnalysisIdentity, action: str, name: str = "") -> ScriptRef:
        return cls(identity.analysis_id, action, identity.version, identity.file_hash, name)

    def label(self) -> str:
        """``Name`` (or the id), with the action when it isn't the usual "Plot"."""
        text = self.name or self.analysis_id
        return text if self.action == "Plot" else f"{text} › {self.action}"

    def to_json(self) -> dict[str, str]:
        return {"analysis_id": self.analysis_id, "action": self.action, "version": self.version,
                "file_hash": self.file_hash, "name": self.name}

    @classmethod
    def from_json(cls, data: Any) -> ScriptRef:
        if not isinstance(data, dict) or not isinstance(data.get("analysis_id"), str) or not data["analysis_id"]:
            raise RecordError("no script id")
        if not isinstance(data.get("action"), str):
            raise RecordError("no script action")
        return cls(data["analysis_id"], data["action"], _text(data.get("version")), _text(data.get("file_hash")),
                   _text(data.get("name")))


@dataclass(frozen=True)
class SavedPlot:
    """One plot of an arrangement: what it shows, with what, and where."""
    script: ScriptRef
    path: str  # The folder whose data it shows (source path)
    root_key: str = ""  # Its ``root://<uuid>/<relative>`` key when known ("": none)
    values: Mapping[str, Any] = field(default_factory=dict)  # Every parameter, as stored
    backend: str = ""  # Its drawing library ("" when the script names none)
    live: Mapping[str, Any] = field(default_factory=dict)  # Its Live group (Follow Live, every N, wait)
    instance_id: str = ""  # Its number in the plot's title, "Counts per shot (3)"
    title: str = ""
    settings_open: bool = False  # Its settings section beside it while it floats: open or closed
    settings_width: int = 0  # … and its width open (0: the default)
    floating: bool = False
    group: int = 0  # Its tab group in the plot area (plots tabbed together share one), in order
    front: bool = False  # The tab shown in its group
    dock_name: str = ""  # Its dock's object name in ``Arrangement.dock_state``
    preset: str = ""  # The script preset last applied to it ("": none), and when that preset was saved
    preset_saved_at: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {"script": self.script.to_json(), "path": self.path, "root_key": self.root_key,
                "values": dict(self.values), "backend": self.backend, "live": dict(self.live),
                "instance_id": self.instance_id, "title": self.title, "settings_open": self.settings_open,
                "settings_width": self.settings_width, "floating": self.floating, "group": self.group,
                "front": self.front, "dock_name": self.dock_name, "preset": self.preset,
                "preset_saved_at": self.preset_saved_at}

    @classmethod
    def from_json(cls, data: Any) -> SavedPlot:
        if not isinstance(data, dict):
            raise RecordError("not a plot record")
        script = ScriptRef.from_json(data.get("script"))
        path = data.get("path")
        if not isinstance(path, str) or not path:
            raise RecordError(f"{script.label()}: no folder")
        values, live = data.get("values", {}), data.get("live", {})
        if not isinstance(values, dict) or not isinstance(live, dict):
            raise RecordError(f"{script.label()}: its settings aren't a record")
        return cls(script, path, _text(data.get("root_key")), dict(values), _text(data.get("backend")), dict(live),
                   _text(data.get("instance_id")), _text(data.get("title")), data.get("settings_open") is True,
                   _whole(data.get("settings_width")), data.get("floating") is True, _whole(data.get("group")),
                   data.get("front") is True, _text(data.get("dock_name")), _text(data.get("preset")),
                   _time(data.get("preset_saved_at")))


@dataclass(frozen=True)
class Arrangement:
    """One folder's plots and where they sit (a preset), or the plots to reopen at start."""
    plots: tuple[SavedPlot, ...] = ()
    folder: str = ""  # The folder a preset loads ("": none, as for the plots to reopen)
    root_key: str = ""
    live: bool = False  # Whether Live watched the folder (a preset starts it once its data shows)
    dock_state: str = ""  # The plot area's ``saveState``, base64 ("": none)
    saved_at: float = 0.0  # Wall-clock time
    unreadable: tuple[str, ...] = ()  # Plots of the record that couldn't be read, with why (not saved again)
    layout_error: str = ""  # Why the saved ``dock_state`` was dropped ("": none, or it was fine)

    def to_json(self) -> dict[str, Any]:
        return {"format": FORMAT, "folder": self.folder, "root_key": self.root_key, "live": self.live,
                "plots": [plot.to_json() for plot in self.plots], "dock_state": self.dock_state,
                "saved_at": self.saved_at or time.time()}

    def dumps(self) -> str:
        return json.dumps(self.to_json(), allow_nan=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, data: Any) -> Arrangement:
        """The arrangement ``data`` holds; ``RecordError`` if it isn't one. A plot that can't be read
        is left out and named (``unreadable``), the others kept."""
        if not isinstance(data, dict):
            raise RecordError("not an arrangement record")
        version = data.get("format")
        if not isinstance(version, int) or isinstance(version, bool):
            raise RecordError("no format version")
        if version > FORMAT:
            raise RecordError(f"saved by a newer HeLab (format {version}; this HeLab reads {FORMAT})")
        plots, unreadable = [], []
        entries = data.get("plots", [])
        if not isinstance(entries, list):
            raise RecordError("its plots aren't a list")
        for entry in entries:
            try:
                plots.append(SavedPlot.from_json(entry))
            except RecordError as error:
                unreadable.append(str(error))
        state, layout_error = _dock_state(data.get("dock_state"))
        return cls(tuple(plots), _text(data.get("folder")), _text(data.get("root_key")), data.get("live") is True,
                   state, _time(data.get("saved_at")), tuple(unreadable), layout_error)


def _dock_state(value: Any) -> tuple[str, str]:
    """A saved layout as stored (base64 text) if it is one, else ("", why it was dropped): the plots
    then open in their tab groups."""
    if value is None or value == "":
        return "", ""
    if not isinstance(value, str):
        return "", "its saved layout isn't text"
    try:
        base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError):
        return "", "its saved layout can't be read"
    return value, ""


def parse(text: Any) -> Arrangement:
    """The arrangement saved as ``text`` (JSON); ``RecordError`` naming why it can't be read."""
    if not isinstance(text, str):
        raise RecordError("not text")
    try:
        data = json.loads(text)
    except ValueError as error:
        raise RecordError(f"not valid JSON ({error})") from None
    return Arrangement.from_json(data)


def waiting_view(path: str, root_key: str = "") -> DatasetView:
    """What a reopened plot holds until its folder's data is found: the folder's identity, at
    revision 0, with no shots (never run on: the plot waits, ``FolderWait``)."""
    return DatasetView(ViewIdentity(path, root_key, ""), 0, MappingProxyType({}), MappingProxyType({}),
                       Provenance("", None, None, False, 0, 0, ()))


def is_waiting(view: DatasetView) -> bool:
    return view.revision == 0 and not view.shots and not view.identity.signature


# Checking a plot's saved settings against the installed script


@dataclass(frozen=True)
class Problem:
    """A saved setting that doesn't fit the installed script, and why: it isn't applied."""
    name: str  # The parameter's key
    title: str  # What its settings call it
    reason: str

    def text(self) -> str:
        return f"{self.title}: {self.reason}"


@dataclass(frozen=True)
class Checked:
    """Saved values against the installed parameters: those that fit, and the problems."""
    values: dict[str, Value]
    problems: tuple[Problem, ...] = ()


def _shown(spec: ParameterSpec, value: Any) -> str:
    """``value`` as the plot's source line writes it, without the title: "5,000", "20,450 ms"."""
    return spec.text(value)[len(spec.title) + 1:]


def check_value(spec: ParameterSpec, value: Any) -> tuple[Value | None, str]:
    """``value`` as ``spec``'s type if it fits exactly (no rounding, clamping or replacing), else
    (None, why)."""
    kind = spec.kind
    if kind == "bool":
        return (value, "") if isinstance(value, bool) else (None, f"saved {value!r} isn't on or off")
    if kind == "text":
        return (value, "") if isinstance(value, str) else (None, f"saved {value!r} isn't text")
    if kind == "choice":
        if not isinstance(value, str):
            return None, f"saved {value!r} isn't one of its choices"
        if value not in spec.choices:
            return None, f"saved “{value}” is no longer a choice ({', '.join(spec.choices)})"
        return value, ""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, f"saved {value!r} isn't a number"
    number: float | int
    if kind == "int":
        if isinstance(value, float) and not (math.isfinite(value) and value == int(value)):
            return None, f"saved {value!r} isn't a whole number"
        number = int(value)
    else:
        if not math.isfinite(value):
            return None, f"saved {value!r} isn't a number"
        number = float(value)
    if spec.limits is not None:
        lower, upper = spec.limits
        if not lower <= number <= upper:
            return None, f"saved {_shown(spec, number)} is outside {_shown(spec, type(number)(lower))} to " \
                         f"{_shown(spec, type(number)(upper))}"
    return number, ""


def check_values(specs: Sequence[ParameterSpec], saved: Mapping[str, Any]) -> Checked:
    """``saved`` against ``specs``: each value that fits (``check_value``), and a problem for each
    that doesn't, each key no spec has and each spec ``saved`` lacks (none of those is applied)."""
    names = {spec.name for spec in specs}
    values: dict[str, Value] = {}
    problems: list[Problem] = []
    for spec in specs:
        if spec.name not in saved:
            problems.append(Problem(spec.name, spec.title, "not saved"))
            continue
        value, why = check_value(spec, saved[spec.name])
        if value is None:
            problems.append(Problem(spec.name, spec.title, why))
        else:
            values[spec.name] = value
    for name in saved:
        if name not in names:
            problems.append(Problem(name, name, "not a setting of this script now"))
    return Checked(values, tuple(problems))


@dataclass(frozen=True)
class PlotCheck:
    """Saved settings against the installed script: what applies, and what it says about the rest."""
    values: dict[str, Value]  # The parameters that fit (the others aren't applied)
    backend: str  # The library to draw with ("": not applied, or the script names none)
    live: dict[str, Value]  # The Live group's values that fit
    problems: tuple[Problem, ...] = ()
    notes: tuple[str, ...] = ()  # E.g. "saved with v1, now v2" (applied all the same)

    def summary(self, kept: str = "at the script's defaults") -> str:
        """One line for the plot: the settings not applied, ``kept`` as they are ("at the script's
        defaults" for a new plot, "left as they were" for an open one), then the notes ("" if
        neither)."""
        parts = []
        if self.problems:
            count = len(self.problems)
            titles = ", ".join(problem.title for problem in self.problems[:4])
            more = f", {count - 4:,} more" if count > 4 else ""
            parts.append(f"⚠ {count:,} setting{'' if count == 1 else 's'} {kept}: {titles}{more}")
        parts.extend(self.notes)
        return " · ".join(parts)

    def details(self) -> str:
        """The tooltip: every problem and note, one per line."""
        return "\n".join([*(problem.text() for problem in self.problems), *self.notes])


def check_plot(saved: SavedPlot | ScriptPreset, identity: AnalysisIdentity, specs: Sequence[ParameterSpec],
               backends: Sequence[str], live_specs: Sequence[ParameterSpec] = ()) -> PlotCheck:
    """``saved`` (a plot of an arrangement, or a script preset, which has no Live group) against
    the installed script: its ``identity``, parameters, libraries and Live group specs."""
    parameters = check_values(specs, saved.values)
    live = check_values(live_specs, saved.live) if isinstance(saved, SavedPlot) else Checked({})
    problems = [*parameters.problems, *live.problems]
    backend = ""
    if len(backends) >= 2:
        if not saved.backend:
            problems.append(Problem(LIBRARY, LIBRARY, "not saved"))
        elif saved.backend not in backends:
            problems.append(Problem(LIBRARY, LIBRARY, f"saved “{saved.backend}” is no longer a choice "
                                                      f"({', '.join(backends)})"))
        else:
            backend = saved.backend
    elif saved.backend:
        problems.append(Problem(LIBRARY, LIBRARY, "this plot no longer chooses a library"))
    notes = []
    if saved.script.version != identity.version:
        notes.append(f"saved with v{saved.script.version or '?'}, now v{identity.version or '?'}")
    elif saved.script.file_hash and identity.file_hash and saved.script.file_hash != identity.file_hash:
        notes.append(f"saved from another copy of v{identity.version or '?'} (its file differs)")
    return PlotCheck(parameters.values, backend, live.values, tuple(problems), tuple(notes))


def preset_note(saved: SavedPlot, presets: ScriptPresets | None) -> str:
    """What became of the script preset a saved plot's values came from ("" if none, or unchanged):
    the arrangement keeps its own values either way."""
    if not saved.preset or presets is None or presets.error:
        return ""
    now = presets.presets.get(saved.preset)
    if now is None:
        return f"preset “{saved.preset}” deleted since: this arrangement's values are used"
    if saved.preset_saved_at and now.saved_at != saved.preset_saved_at:
        return f"preset “{saved.preset}” changed since: this arrangement's values are used"
    return ""


# Script presets


@dataclass(frozen=True)
class ScriptPreset:
    """One script's settings saved under a name."""
    name: str
    script: ScriptRef
    values: Mapping[str, Any] = field(default_factory=dict)
    backend: str = ""
    saved_at: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {"format": FORMAT, "script": self.script.to_json(), "values": dict(self.values),
                "backend": self.backend, "saved_at": self.saved_at}

    @classmethod
    def from_json(cls, name: str, data: Any) -> ScriptPreset:
        if not isinstance(data, dict):
            raise RecordError("not a preset record")
        version = data.get("format")
        if not isinstance(version, int) or isinstance(version, bool):
            raise RecordError("no format version")
        if version > FORMAT:
            raise RecordError(f"saved by a newer HeLab (format {version})")
        values = data.get("values")
        if not isinstance(values, dict):
            raise RecordError("its settings aren't a record")
        return cls(name, ScriptRef.from_json(data.get("script")), dict(values), _text(data.get("backend")),
                   _time(data.get("saved_at")))


@dataclass(frozen=True)
class ScriptPresets:
    """One script's saved presets, as read: those that can be read, those that can't (name →
    why), and ``error`` when the saved ones couldn't be read at all (then those known are
    this session's, never "none saved")."""
    presets: Mapping[str, ScriptPreset] = field(default_factory=dict)
    unreadable: Mapping[str, str] = field(default_factory=dict)
    error: str = ""

    @classmethod
    def from_records(cls, records: Mapping[str, str], error: str = "") -> ScriptPresets:
        """The presets saved as ``records`` (name → JSON text, one per preset); never raises."""
        presets: dict[str, ScriptPreset] = {}
        unreadable: dict[str, str] = {}
        for name, text in records.items():
            try:
                presets[name] = ScriptPreset.from_json(name, json.loads(text))
            except ValueError as error_:  # (RecordError too)
                unreadable[name] = str(error_) if isinstance(error_, RecordError) else f"not valid JSON ({error_})"
        return cls(presets, unreadable, error)

    def names(self) -> list[str]:
        """The readable presets' names, sorted without case."""
        return sorted(self.presets, key=str.casefold)


def dumps(record: ScriptPreset | Arrangement) -> str:
    """A preset's record as saved (JSON); ``ValueError`` for a value JSON can't hold (not a finite
    number)."""
    if isinstance(record, Arrangement):
        return record.dumps()
    return json.dumps(record.to_json(), allow_nan=False, separators=(",", ":"))


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _time(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) \
        else 0.0


def _whole(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
