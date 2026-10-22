"""Disk-cached results (result caching R2, roadmaps/result-caching.md): what a run's saved
result is found by, and its record as JSON.

A result is reused only on an exact match of its **lookup key** (Rule 5): ``AnalysisResult.
reuse_key`` of the run as submitted (the analysis's ID, version and file hash, the action, the
input's signatures, the parameters in use, the coverage with each shot's fingerprint, the
constants it uses and a mask preset's circles) without the folder (the store keys each row by
its folder's ``root://`` key) and without ``found`` (what the run decides, known only after it;
a script whose runs depend on what its plot kept between runs neither looks up nor saves them
then: ``DatasetAnalysis.cache_holds_state`` and ``cache_result``), plus the **execution
environment** (Python's minor version, NumPy's, SciPy's and HeLab's: the shared numerics in
``helab/analysis`` don't change the script's hash). Its **family key** is the same plot and
settings without the script's identity, the environment, the data and the constants: a saved
result of the family that isn't an exact match is shown at once, marked outdated, while the run
goes on (``outdated_reasons`` says what changed).

The record is the result without its data (``AnalysisResult`` through ``result_codec`` with its
own types), so a result read back keeps its original identity. Qt-free.
"""
from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import replace
from functools import lru_cache
from typing import Any, Mapping

from helab.analysis import result_codec
from helab.analysis.dataset_view import ViewIdentity, ViewKey
from helab.analysis.identity import AnalysisIdentity
from helab.analysis.masks import mask_key
from helab.analysis.physics import ResolvedConstants
from helab.analysis.results import DISK_CACHED, FROM_DISK, AnalysisContext, AnalysisResult, Coverage

# Types a result's record holds (``record_of``).
RECORD_TYPES: tuple[type, ...] = (AnalysisResult, AnalysisIdentity, ViewKey, ViewIdentity, Coverage, ResolvedConstants)
# Above this, saving a result is said each time (Tony, 2026-10-22): the plot and the size (50 MB as
# HeLab shows sizes, ``number_format.byte_size``).
LARGE_RESULT_BYTES = 50 << 20


@lru_cache(maxsize=1)
def environment() -> dict[str, str]:
    """What else a result depends on: Python's minor version, NumPy's, SciPy's and HeLab's."""
    import numpy
    from helab._version import __version__
    try:
        import scipy
        scipy_version = str(scipy.__version__)
    except ImportError:  # (A requirement: only a broken install lacks it.)
        scipy_version = ""
    return {"python": ".".join(platform.python_version_tuple()[:2]), "numpy": str(numpy.__version__),
            "scipy": scipy_version, "helab": __version__}


def lookup_key(context: AnalysisContext) -> dict[str, Any]:
    """The exact key a run's saved result is found by (JSON values; see the module)."""
    key = AnalysisResult.of(context, "completed").reuse_key()
    key.pop("root_key", None)
    key.pop("found", None)
    return {**key, "environment": environment()}


def family_key(context: AnalysisContext) -> dict[str, Any]:
    """The same plot and settings, whatever the script's identity, the data and the constants."""
    return {"analysis_id": context.analysis.analysis_id, "action": context.action,
            "parameters": {name: value for name, value in context.parameters.items() if name not in context.unused},
            **mask_key(context.parameters)}


def digest(key: Mapping[str, Any]) -> str:
    """SHA-256 of a key's canonical JSON."""
    text = json.dumps(key, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def outdated_reasons(saved: Mapping[str, Any], wanted: Mapping[str, Any]) -> tuple[str, ...]:
    """What differs between a saved result's lookup key and the one a run asks for, in words."""
    reasons = []
    if (saved.get("analysis_id"), saved.get("version")) != (wanted.get("analysis_id"), wanted.get("version")):
        reasons.append(f"script version {saved.get('version') or '?'} → {wanted.get('version') or '?'}")
    elif saved.get("file_hash") != wanted.get("file_hash"):
        reasons.append("script file changed")
    if saved.get("environment") != wanted.get("environment"):
        before, now = saved.get("environment") or {}, wanted.get("environment") or {}
        changed = [f"{name} {before.get(name, '?')} → {now.get(name, '?')}" for name in sorted({*before, *now})
                   if before.get(name) != now.get(name)]
        reasons.append(", ".join(changed) or "environment changed")
    if (saved.get("coverage"), saved.get("input_signature"), saved.get("signature")) != (
            wanted.get("coverage"), wanted.get("input_signature"), wanted.get("signature")):
        reasons.append(_data_change(saved.get("coverage"), wanted.get("coverage")))
    if saved.get("constants") != wanted.get("constants"):
        reasons.append("constants changed")
    return tuple(reasons) or ("settings or data changed",)


def _data_change(saved: Any, wanted: Any) -> str:
    """``data changed (2 shots new, 1 changed)``: the coverages' difference, as far as it can tell."""
    try:
        before = {int(entry[0]): list(entry) for entry in saved["fingerprints"]}
        now = {int(entry[0]): list(entry) for entry in wanted["fingerprints"]}
        shots_before, shots_now = set(saved["shots"]), set(wanted["shots"])
    except (KeyError, TypeError, ValueError, IndexError):
        return "data changed"
    parts = [f"{count:,} shot{'' if count == 1 else 's'} {what}" for count, what in (
        (len(shots_now - shots_before), "new"),
        (sum(1 for shot in shots_now & shots_before if before.get(shot) != now.get(shot)), "changed"),
        (len(shots_before - shots_now), "gone")) if count]
    return f"data changed ({', '.join(parts)})" if parts else "data changed"


def record_of(result: AnalysisResult) -> Any:
    """``result``'s record without its data, as a JSON tree (``result_codec``)."""
    tree, arrays = result_codec.encode(replace(result, data=None, packed=None, packing_error=""), RECORD_TYPES)
    if arrays:
        raise result_codec.CodecError("a result's record holds arrays")
    return tree


def result_from(record: Any, data: Any, *, outdated: tuple[str, ...] = ()) -> AnalysisResult:
    """A saved result read back: its record with ``data``, marked as from the disk cache."""
    result = result_codec.decode(record, {}, RECORD_TYPES)
    if not isinstance(result, AnalysisResult):
        raise result_codec.CodecError("not a saved result's record")
    return replace(result, data=data, source=FROM_DISK, outdated=outdated, policy=DISK_CACHED)
