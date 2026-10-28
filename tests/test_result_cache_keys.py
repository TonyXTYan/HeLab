"""What a saved result is found by (``helab.analysis.result_cache``): every part of the run's key
changing (a shot's fingerprint, the script's file hash or version, a parameter, a constant, the mask,
the environment) gives another lookup key; those of the data, the script, the constants and the
environment keep the family (the outdated marker), settings don't. A result's record comes back
with its identity."""
from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any, Mapping

import numpy as np
import pytest

from helab.analysis import result_cache
from helab.analysis.dataset_view import DatasetView, build_view
from helab.analysis.identity import AnalysisIdentity
from helab.analysis.physics import resolve
from helab.analysis.results import FROM_DISK, AnalysisContext, AnalysisResult, Coverage
from helab.utils.folder_cache import Dataset

IDENTITY = AnalysisIdentity("tests.keyed", "1", "keyed.py", "hash-1")


def view(changed: int | None = None) -> DatasetView:
    data = {shot: np.full((4, 3), float(shot)) for shot in (1, 2, 3)}
    prints = [[shot, 10 + shot + (1 if shot == changed else 0), 100 + shot] for shot in data]
    return build_view(Dataset("/data/root/run", f"sig-{changed}", data, {"fingerprint": prints}, 0))


def context(data: DatasetView | None = None, parameters: Mapping[str, Any] | None = None,
            identity: AnalysisIdentity = IDENTITY, fall: float | None = None) -> AnalysisContext:
    shown = data or view()
    constants = resolve(folder={"fall_distance": fall} if fall is not None else None)
    return AnalysisContext("a1", "Plot", shown, dict(parameters or {"bins": 10}), identity,
                           threading.Event(), Coverage.of(shown), resolved_constants=constants,
                           constant_keys=("fall_distance",), constants={"folder": {"fall_distance": fall}}
                           if fall is not None else {})


BASE = context()
CHANGES = {
    "fingerprint": (context(view(changed=2)), True),
    "file hash": (context(identity=replace(IDENTITY, file_hash="hash-2")), True),
    "version": (context(identity=replace(IDENTITY, version="2")), True),
    "constant": (context(fall=0.9), True),
    "parameter": (context(parameters={"bins": 20}), False),
    "mask": (context(parameters={"bins": 10, "mask_mode": "custom", "mask_circles": "0, 0, 1"}), False),
}


@pytest.mark.parametrize("part", CHANGES)
def test_every_part_of_the_key_changes_the_lookup(part: str) -> None:
    changed, same_family = CHANGES[part]
    assert result_cache.digest(result_cache.lookup_key(changed)) != result_cache.digest(result_cache.lookup_key(BASE))
    assert (result_cache.digest(result_cache.family_key(changed))
            == result_cache.digest(result_cache.family_key(BASE))) is same_family


def test_the_key_names_the_environment_and_not_the_folder_or_found(monkeypatch: pytest.MonkeyPatch) -> None:
    key = result_cache.lookup_key(BASE)
    assert "root_key" not in key and "found" not in key
    assert set(key["environment"]) == {"python", "numpy", "scipy", "helab"}
    monkeypatch.setattr(result_cache, "environment", lambda: {**key["environment"], "numpy": "0.0"})
    other = result_cache.lookup_key(BASE)
    assert result_cache.digest(other) != result_cache.digest(key)
    assert result_cache.outdated_reasons(key, other) == (f"numpy {key['environment']['numpy']} → 0.0",)


def test_outdated_reasons_name_what_changed() -> None:
    def reasons(changed: AnalysisContext) -> tuple[str, ...]:
        return result_cache.outdated_reasons(result_cache.lookup_key(BASE), result_cache.lookup_key(changed))
    assert reasons(CHANGES["version"][0]) == ("script version 1 → 2",)
    assert reasons(CHANGES["file hash"][0]) == ("script file changed",)
    assert reasons(CHANGES["fingerprint"][0]) == ("data changed (1 shot changed)",)
    assert reasons(CHANGES["constant"][0]) == ("constants changed",)
    more = view().with_shots({4: np.full((4, 3), 4.0)}, {4: (4, 14, 104)})
    assert reasons(context(more)) == ("data changed (1 shot new)",)


def test_a_record_comes_back_with_its_identity() -> None:
    result = AnalysisResult.of(BASE, "completed", {"x": 1}, started_at=1.0, found={"brief": "b", "reuse": {"k": 1}})
    record = result_cache.record_of(result)
    import json
    back = result_cache.result_from(json.loads(json.dumps(record)), {"x": 2}, outdated=("script file changed",))
    assert back.source == FROM_DISK and back.data == {"x": 2} and back.outdated == ("script file changed",)
    assert back.analysis == IDENTITY and back.input == result.input and back.coverage == result.coverage
    assert back.resolved_constants == result.resolved_constants and dict(back.found) == {"brief": "b",
                                                                                         "reuse": {"k": 1}}
    assert back.reuse_key() == result.reuse_key()
    assert "From disk cache, computed" in back.describe() and "outdated: script file changed" in back.describe()


def test_a_changed_preset_mask_changes_the_key_and_the_family(monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.analysis import masks
    preset = context(parameters={"bins": 10, masks.MASK_MODE.name: masks.PRESET, "mask_preset": masks.CURRENT})
    before = result_cache.lookup_key(preset), result_cache.family_key(preset)
    monkeypatch.setitem(masks.PRESETS, masks.CURRENT, (masks.Circle(0.001, 0.0, 0.002),))
    after = result_cache.lookup_key(preset), result_cache.family_key(preset)
    assert all(result_cache.digest(old) != result_cache.digest(new) for old, new in zip(before, after))
