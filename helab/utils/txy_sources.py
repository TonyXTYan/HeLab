"""Which TXY a dataset is made of (Q6.6, Q18.2): MATLAB's ``d_txy_forc<N>.txt``, HeLab's
``d_txy_helab_<tag>_<N>.txt``, or both, per shot.

A load is asked for one **source** (mode), and for HeLab's TXY of one profile, chosen by its tag
(``profile_tag``, Q18.4; the conversion profile's unless a plot picks another):

- ``helab-priority`` (the default for tabs and Live, the ``txy_source`` setting): HeLab's TXY where
  they exist, MATLAB's for the rest;
- ``matlab-priority`` (the default before Q18.2): MATLAB's TXY, HeLab's filling the shots MATLAB lacks;
- ``helab-only`` and ``matlab-only`` (for comparing, a plot on each): one kind each.

Each shot then has an **origin**: ``""`` for MATLAB's, ``helab:<profile hash>`` for HeLab's (only a
TXY that is current is used, so the hash is the profile it was made with). A dataset records its source
and its shots' origins (``TXY_FIELD`` in its metadata); views, results and saved-result keys carry the
origins, so data of one kind of TXY is never taken for another's. The two priority modes share the
identity "" (``identity_source``): they differ only on shots both kinds have, which their origins tell
apart; so data of MATLAB's TXY alone keeps the identity it had before HeLab converted anything, under
either default, and existing caches and saved results stay valid. A view still records its choice
(``DatasetView.txy_choice``), so a plot on one choice never takes another's data as its own.

Data saved before Q18.2 says ``matlab`` or ``helab`` (``LEGACY``): read as the priority modes.

Standard library only: helpers import it.
"""
from __future__ import annotations

from typing import Any, Mapping

# The two kinds of TXY a shot comes from (``choose``).
MATLAB = "matlab"
HELAB = "helab"
# The sources (modes).
HELAB_PRIORITY = "helab-priority"
MATLAB_PRIORITY = "matlab-priority"
HELAB_ONLY = "helab-only"
MATLAB_ONLY = "matlab-only"
SOURCES = (HELAB_PRIORITY, MATLAB_PRIORITY, HELAB_ONLY, MATLAB_ONLY)
# The tabs' and Live's when the setting says nothing valid (Tony, Q18.2).
DEFAULT_SOURCE = HELAB_PRIORITY
# Data that names no source (made before Q6.6): MATLAB's alone, as MATLAB priority reads it.
UNNAMED_SOURCE = MATLAB_PRIORITY
LEGACY = {MATLAB: MATLAB_PRIORITY, HELAB: HELAB_PRIORITY}
# A load's payload field (the app's options for finding HeLab's TXY) and a dataset's metadata field
# (what it is made of), both ``txy``.
TXY_FIELD = "txy"
HELAB_ORIGIN = "helab:"
# The source and profile tag of a dataset's choice, as one text (``choice_text``).
_CHOICE_SEPARATOR = "@"

LABELS = {
    HELAB_PRIORITY: "HeLab's where made, MATLAB's for the rest",
    MATLAB_PRIORITY: "MATLAB's, HeLab's for shots MATLAB lacks",
    HELAB_ONLY: "HeLab's only",
    MATLAB_ONLY: "MATLAB's only",
}
SHORT = {HELAB_PRIORITY: "HeLab priority", MATLAB_PRIORITY: "MATLAB priority", HELAB_ONLY: "HeLab only",
         MATLAB_ONLY: "MATLAB only"}


def normal_source(value: Any) -> str | None:
    """A source as saved or sent (an old name too), or None if it names none."""
    if not isinstance(value, str):
        return None
    value = LEGACY.get(value, value)
    return value if value in SOURCES else None


def requested_source(value: Any) -> str:
    """The source a load, Live check or save asks for: the default when it names none (``ValueError``
    for one that isn't a source)."""
    if value is None or value == "":
        return DEFAULT_SOURCE
    found = normal_source(value)
    if found is None:
        raise ValueError(f"Unknown TXY source {value!r} (have {', '.join(SOURCES)})")
    return found


def choice_tag(source: str, tag: str) -> str:
    """The profile tag a choice depends on: none for MATLAB's alone."""
    return "" if source == MATLAB_ONLY else tag


def helab_origin(profile_hash: str) -> str:
    return HELAB_ORIGIN + profile_hash


def is_helab(origin: str) -> bool:
    return origin.startswith(HELAB_ORIGIN)


def wants_helab(source: str) -> bool:
    return source != MATLAB_ONLY


def choose(source: str, matlab: bool, helab: bool, held: str | None = None) -> str | None:
    """Which kind a shot's TXY is taken from, ``"matlab"`` or ``"helab"`` (None: neither is there).
    ``held``: the origin the caller already holds the shot from (Live), kept while that kind is
    still there, so a MATLAB TXY appearing for a shot HeLab filled doesn't stop Live."""
    source = normal_source(source) or source
    if held is not None and source in (MATLAB_PRIORITY, HELAB_PRIORITY):
        if is_helab(held) and helab:
            return HELAB
        if not is_helab(held) and matlab:
            return MATLAB
    order = {MATLAB_PRIORITY: (MATLAB, HELAB), HELAB_PRIORITY: (HELAB, MATLAB), MATLAB_ONLY: (MATLAB,),
             HELAB_ONLY: (HELAB,)}[source]
    for kind in order:
        if (matlab if kind == MATLAB else helab):
            return kind
    return None


def origins_of(metadata: Mapping[str, Any]) -> dict[int, str]:
    """A dataset's shots that aren't MATLAB's, with their origin, from its metadata."""
    record = metadata.get(TXY_FIELD)
    origins = record.get("origins") if isinstance(record, Mapping) else None
    found: dict[int, str] = {}
    if isinstance(origins, Mapping):
        for shot, origin in origins.items():
            try:
                found[int(shot)] = str(origin)
            except (TypeError, ValueError):
                continue
    return found


def empty_helab_shots(metadata: Mapping[str, Any], data: Mapping[int, Any]) -> list[int]:
    """Shots read from HeLab's TXY that hold no hits (a 0-byte TXY: its conversion found none, A17.1), from
    the data in RAM (``len`` of each shot's array)."""
    return sorted(shot for shot, origin in origins_of(metadata).items()
                  if is_helab(origin) and shot in data and len(data[shot]) == 0)


def source_of(metadata: Mapping[str, Any]) -> str:
    """A dataset's source; data that names none (made before Q6.6) is MATLAB's alone."""
    record = metadata.get(TXY_FIELD)
    return normal_source(record.get("source") if isinstance(record, Mapping) else None) or UNNAMED_SOURCE


def tag_of(metadata: Mapping[str, Any]) -> str:
    """The profile tag a dataset's HeLab TXY were asked for ("" for MATLAB's alone, or data made before
    Q18.4)."""
    record = metadata.get(TXY_FIELD)
    tag = record.get("profile_tag") if isinstance(record, Mapping) else None
    return choice_tag(source_of(metadata), tag if isinstance(tag, str) else "")


def metadata_choice(metadata: Mapping[str, Any]) -> str:
    """A dataset's choice (``choice_text``) from its metadata; "" when it names none (made before Q6.6:
    MATLAB's alone)."""
    if not isinstance(metadata.get(TXY_FIELD), Mapping):
        return ""
    return choice_text(source_of(metadata), tag_of(metadata))


def same_choice(one: str, other: str) -> bool:
    """Two datasets' choices could hold each other's data: equal, or one naming none (MATLAB's alone, made
    before Q6.6) and the other a priority source's (which reads MATLAB's alone alike)."""
    if one == other:
        return True
    if one and other:
        return False
    return source_of_choice(one or other) in (HELAB_PRIORITY, MATLAB_PRIORITY)


def source_of_choice(choice: str) -> str:
    """The source of a choice text ("": MATLAB's alone, as data that names none)."""
    return normal_source(choice.split(_CHOICE_SEPARATOR, 1)[0]) or UNNAMED_SOURCE


def choice_text(source: str, tag: str) -> str:
    """A source and profile tag as one text (``helab-only@p22v1``; a MATLAB-only choice has no tag)."""
    tag = choice_tag(source, tag)
    return f"{source}{_CHOICE_SEPARATOR}{tag}" if tag else source


def identity_source(source: str) -> str:
    """The source as a view's identity names it: "" for the two priority modes (their shots' origins
    tell their data apart), so MATLAB's TXY alone keep the identity (and saved results) they had under
    either default; else the mode's name."""
    return "" if source in (HELAB_PRIORITY, MATLAB_PRIORITY) else source


def profiles_of(metadata: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Profile hash → {name, version, calibrated} of the HeLab TXY in a dataset."""
    record = metadata.get(TXY_FIELD)
    profiles = record.get("profiles") if isinstance(record, Mapping) else None
    return {str(key): dict(value) for key, value in profiles.items() if isinstance(value, Mapping)} \
        if isinstance(profiles, Mapping) else {}


def describe(source: str, origins: Mapping[int, str], profiles: Mapping[str, Mapping[str, Any]],
             shots: int) -> str:
    """``TXY: MATLAB's`` / ``TXY: HeLab's (matlab-2019 v1) for 3 of 10 shots, MATLAB's for the rest``."""
    count = len(origins)
    names = sorted({_profile_text(origin[len(HELAB_ORIGIN):], profiles) for origin in origins.values()})
    helab = f"HeLab's ({', '.join(names)})" if names else "HeLab's"
    if not count:
        return "TXY: none of HeLab's (no current HeLab TXY)" if source == HELAB_ONLY else "TXY: MATLAB's"
    if count >= shots:
        return f"TXY: {helab}"
    return f"TXY: {helab} for {count:,} of {shots:,} shots, MATLAB's for the rest"


def _profile_text(profile_hash: str, profiles: Mapping[str, Mapping[str, Any]]) -> str:
    profile = profiles.get(profile_hash)
    if not profile:
        return f"profile {profile_hash[:8]}"
    names = profile.get("names")
    if isinstance(names, list) and len(names) > 1:
        return " / ".join(str(name) for name in names)  # Profiles of one output: their TXY are alike.
    return f"{profile.get('name', '?')} v{profile.get('version', '?')}"
