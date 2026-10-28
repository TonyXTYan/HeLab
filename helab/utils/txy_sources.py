"""Which TXY a dataset is made of (Q6.6): MATLAB's ``d_txy_forc<N>.txt``, HeLab's ``d_txy_helab_<N>.txy``,
or both, per shot.

A load is asked for one **source**:

- ``matlab`` (the default, Q6.6 (a)): MATLAB's TXY, HeLab's filling the shots MATLAB lacks;
- ``helab`` ((b)): HeLab's wherever they exist, MATLAB's for the rest;
- ``matlab-only`` and ``helab-only`` ((c), both as two datasets for comparing): one kind each.

Each shot then has an **origin**: ``""`` for MATLAB's, ``helab:<profile hash>`` for HeLab's (only a
TXY whose provenance is current is used, so the hash is the profile it was made with). A dataset
records its source and its shots' origins (``TXY_FIELD`` in its metadata), and so do the views,
results and saved-result keys made from it, so data of one source is never taken for another's. A
dataset of MATLAB's TXY alone keeps the identity it had before HeLab converted anything: existing
caches and saved results stay valid.

Standard library only: helpers import it.
"""
from __future__ import annotations

from typing import Any, Mapping

MATLAB = "matlab"
HELAB = "helab"
MATLAB_ONLY = "matlab-only"
HELAB_ONLY = "helab-only"
SOURCES = (MATLAB, HELAB, MATLAB_ONLY, HELAB_ONLY)
DEFAULT_SOURCE = MATLAB
# A load's payload field (the app's options for finding HeLab's TXY) and a dataset's metadata field
# (what it is made of), both ``txy``.
TXY_FIELD = "txy"
HELAB_ORIGIN = "helab:"

LABELS = {
    MATLAB: "MATLAB's, HeLab's for shots MATLAB lacks",
    HELAB: "HeLab's wherever they exist",
    MATLAB_ONLY: "Both, as two datasets: MATLAB's",
    HELAB_ONLY: "Both, as two datasets: HeLab's",
}
SHORT = {MATLAB: "MATLAB + HeLab fill", HELAB: "HeLab + MATLAB fill", MATLAB_ONLY: "MATLAB only",
         HELAB_ONLY: "HeLab only"}


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
    if held is not None and source in (MATLAB, HELAB):
        if is_helab(held) and helab:
            return HELAB
        if not is_helab(held) and matlab:
            return MATLAB
    order = {MATLAB: (MATLAB, HELAB), HELAB: (HELAB, MATLAB), MATLAB_ONLY: (MATLAB,),
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


def source_of(metadata: Mapping[str, Any]) -> str:
    record = metadata.get(TXY_FIELD)
    value = record.get("source") if isinstance(record, Mapping) else None
    return value if isinstance(value, str) and value in SOURCES else DEFAULT_SOURCE


def identity_source(source: str) -> str:
    """The source as a view's identity names it: "" for the default, so MATLAB's TXY alone keep
    the identity (and saved results) they had."""
    return "" if source == DEFAULT_SOURCE else source


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
