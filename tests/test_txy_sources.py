"""Which TXY a dataset is made of (Q6.6): loads, Live checks and Live's saves read HeLab's own TXY as
the source asks (``helab/utils/txy_sources.py``, ``helab/io_ops/helab_txy.py``), only with current
provenance, and every dataset, view, result key and cache records its source, so data of one source
is never taken for another's. Synthetic folders under ``tmp_path`` only (tests never touch real data)."""
from __future__ import annotations

import os
from pathlib import Path
import time
from types import MappingProxyType
from typing import Any

import numpy as np
import pytest

from helab.analysis.budget_core import restore
from helab.analysis.dataset_view import build_view, revise
from helab.analysis.identity import AnalysisIdentity
from helab.analysis.results import AnalysisContext, AnalysisResult, Coverage
from helab.convert.profile import MATLAB_2019, MATLAB_2023_LAB_EDIT
from helab.io_ops import fingerprints, helab_txy, stores
from helab.io_ops.convert import convert_folder, folder_for
from helab.io_ops.live import live_check
from helab.io_ops.loading import load
from helab.io_ops.save_held import save_held
from helab.utils import txy_sources
from helab.utils.cache_store import store_root
from helab.utils.folder_cache import Dataset
from test_convert_helab import OLD, raw_bytes, write_raw
from test_folder_cache import service_for_test

PROFILE = MATLAB_2019.content_hash()


def matlab_txy(folder: Path, shot: int) -> Path:
    path = folder / f"d_txy_forc{shot}.txt"
    path.write_text(f"{shot}.5,0.25,0.75\n{shot}.5,0.5,0.5\n")
    return path


def make_run(tmp_path: Path, private_store: str, shots: int = 4, matlab: tuple[int, ...] = (1, 2),
             output: str = "cache") -> Path:
    """Raw files 1..``shots`` (hits), MATLAB's TXY for ``matlab``, and HeLab's for every shot."""
    source = tmp_path / "run"
    source.mkdir()
    for shot in range(1, shots + 1):
        write_raw(source, shot, raw_bytes(*(10_000 * k for k in range(1, shot + 1))))
    for shot in matlab:
        matlab_txy(source, shot)
    convert(source, tmp_path, private_store, destination=output)
    return source


def convert(source: Path, tmp_path: Path, private_store: str, profile: Any = MATLAB_2019,
            **fields: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    request: dict[str, Any] = {"path": str(source), "profile": profile.to_dict(), "temps": str(tmp_path / "temps"),
                               "seen": None, "destination": "cache", "workers": 1,
                               "cache": {"directory": store_root(private_store)}}
    request.update(fields)
    convert_folder(str(source), request, events.append)  # type: ignore[arg-type]
    assert [event for event in events if event["kind"] == "shot_converted"] or fields.get("shots") == []
    return events


def options(tmp_path: Path, private_store: str, source: str = txy_sources.MATLAB,
            profile_hash: str = PROFILE) -> dict[str, Any]:
    return {"source": source, "profile_hash": profile_hash, "cache_base": private_store,
            "temps": str(tmp_path / "temps")}


def run_load(source: Path, tmp_path: Path, private_store: str | None, txy: dict[str, Any] | None,
             **kwargs: Any) -> list[dict[str, Any]]:
    output = tmp_path / f"artifacts-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    cache = {"directory": store_root(private_store)} if private_store else None
    if txy is not None and not private_store:
        # Without a store the root key is the app's (``FolderCache.with_txy``), as convert found it.
        txy = {**txy, "key": _key(source, str(tmp_path.parent / "never"))}
    load(str(source), str(output), events.append, cache, txy=txy, **kwargs)  # type: ignore[arg-type]
    return events


def loaded(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(event for event in events if event["kind"] == "loaded")


def shots_read(events: list[dict[str, Any]]) -> dict[int, Any]:
    return {event["shot"]: np.load(event["artifact"]) for event in events if event["kind"] == "shot"}


def summary_signature(events: list[dict[str, Any]]) -> str:
    return str(next(event for event in events if event["kind"] == "scan_summary")["status"]["signature"])


# Loads.


def test_the_default_takes_matlabs_and_fills_with_helabs(tmp_path: Path, private_store: str) -> None:
    source = make_run(tmp_path, private_store)
    events = run_load(source, tmp_path, private_store, options(tmp_path, private_store))
    result = loaded(events)
    data = shots_read(events)
    assert sorted(data) == [1, 2, 3, 4]
    assert data[1][0, 0] == 1.5  # MATLAB's (the fixture's values), not HeLab's conversion.
    assert result["txy"]["source"] == "matlab"
    assert result["txy"]["origins"] == {"3": f"helab:{PROFILE}", "4": f"helab:{PROFILE}"}
    assert result["txy"]["profiles"] == {PROFILE: {"name": "matlab-2019", "version": 1, "calibrated": False}}
    # The folder's signature, as a scan computes it: its MATLAB TXY alone.
    assert result["signature"] == summary_signature(events)
    matlab_only = loaded(run_load(source, tmp_path, None, options(tmp_path, private_store, txy_sources.MATLAB_ONLY)))
    assert result["signature"] == matlab_only["signature"]
    # HeLab's names (in HeLab's folder) are in full, MATLAB's as in the folder.
    assert result["names"][:2] == ["d_txy_forc1.txt", "d_txy_forc2.txt"]
    assert os.path.isabs(result["names"][2])


def test_each_source_takes_its_txy(tmp_path: Path, private_store: str) -> None:
    source = make_run(tmp_path, private_store)

    def origins(name: str) -> tuple[list[int], dict[str, str]]:
        events = run_load(source, tmp_path, None, options(tmp_path, private_store, name))
        return sorted(shots_read(events)), loaded(events)["txy"]["origins"]
    helab = {str(shot): f"helab:{PROFILE}" for shot in (1, 2, 3, 4)}
    assert origins(txy_sources.HELAB) == ([1, 2, 3, 4], helab)
    assert origins(txy_sources.HELAB_ONLY) == ([1, 2, 3, 4], helab)
    assert origins(txy_sources.MATLAB_ONLY) == ([1, 2], {})
    # Without the option (a helper of before): the default, but without the app's folders HeLab's aren't found.
    events = run_load(source, tmp_path, None, None)
    assert sorted(shots_read(events)) == [1, 2] and loaded(events)["txy"]["source"] == "matlab"
    with pytest.raises(ValueError, match="Unknown TXY source"):
        run_load(source, tmp_path, None, {"source": "both"})


def test_helabs_are_read_only_when_current_for_the_profile(tmp_path: Path, private_store: str) -> None:
    source = make_run(tmp_path, private_store)
    other = options(tmp_path, private_store, txy_sources.MATLAB, MATLAB_2023_LAB_EDIT.content_hash())
    assert sorted(shots_read(run_load(source, tmp_path, None, other))) == [1, 2]
    with pytest.raises(ValueError, match="No current HeLab TXY"):
        run_load(source, tmp_path, None, {**other, "source": txy_sources.HELAB_ONLY})
    # Any profile when none is asked for.
    anyone = options(tmp_path, private_store, txy_sources.MATLAB, "")
    assert sorted(shots_read(run_load(source, tmp_path, None, anyone))) == [1, 2, 3, 4]
    # A raw file changed since its conversion: its HeLab TXY isn't current.
    os.utime(source / "d3.txt", (OLD + 60, OLD + 60))
    assert sorted(shots_read(run_load(source, tmp_path, None, options(tmp_path, private_store)))) == [1, 2, 4]
    # Its raw file gone: no provenance to check it against.
    (source / "d4.txt").unlink()
    assert sorted(shots_read(run_load(source, tmp_path, None, options(tmp_path, private_store)))) == [1, 2]


def test_helabs_in_the_temp_folder_and_beside_are_found(tmp_path: Path, private_store: str) -> None:
    source = make_run(tmp_path, private_store, output="temp")
    events = run_load(source, tmp_path, None, options(tmp_path, private_store, txy_sources.HELAB_ONLY))
    assert sorted(shots_read(events)) == [1, 2, 3, 4]
    # Beside: the TXY in the source folder, its record in HeLab's folder.
    beside = tmp_path / "beside"
    beside.mkdir()
    write_raw(beside, 7, raw_bytes(10_000, 20_000))
    convert(beside, tmp_path, private_store, beside=True, beside_confirmed=True)
    assert (beside / "d_txy_helab_7.txy").is_file()
    events = run_load(beside, tmp_path, None, options(tmp_path, private_store))
    assert sorted(shots_read(events)) == [7]
    assert loaded(events)["names"] == ["d_txy_helab_7.txy"]


def test_a_helab_txy_of_no_hits_is_an_empty_shot(tmp_path: Path, private_store: str) -> None:
    source = tmp_path / "run"
    source.mkdir()
    write_raw(source, 1, b"5,1000\r\n")  # A trigger alone: converted, no hits, a 0-byte TXY.
    convert(source, tmp_path, private_store)
    events = run_load(source, tmp_path, None, options(tmp_path, private_store))
    assert shots_read(events)[1].shape == (0, 3)
    assert loaded(events)["problematic"] == []


def test_the_cache_and_ram_never_reuse_a_shot_of_the_other_kind(tmp_path: Path, private_store: str) -> None:
    source = make_run(tmp_path, private_store)
    first = loaded(run_load(source, tmp_path, private_store, options(tmp_path, private_store)))
    with stores._cache_store(store_root(private_store), [str(source)]) as store:
        row = store.read_dataset_row(str(source)).value
    assert row is not None and row["info"]["txy"]["origins"] == first["txy"]["origins"]
    assert row["info"]["signature"] == first["signature"]
    # MATLAB's TXY of shot 3 arrives: the cached HeLab one isn't reused for it.
    matlab_txy(source, 3)
    events = run_load(source, tmp_path, private_store, options(tmp_path, private_store))
    data = shots_read(events)
    assert data[3][0, 0] == 3.5 and loaded(events)["txy"]["origins"] == {"4": f"helab:{PROFILE}"}
    assert loaded(events)["signature"] != first["signature"]  # (The folder's MATLAB TXY changed.)
    # RAM: shots held from HeLab's TXY aren't reused for a MATLAB-only load, nor MATLAB's for HeLab's.
    held = loaded(run_load(source, tmp_path, None, options(tmp_path, private_store, txy_sources.HELAB_ONLY)))
    events = run_load(source, tmp_path, None, options(tmp_path, private_store, txy_sources.HELAB_ONLY),
                      memory=held["fingerprint"], memory_origins=held["txy"]["origins"])
    assert loaded(events)["memory_shots"] == [1, 2, 3, 4]
    events = run_load(source, tmp_path, None, options(tmp_path, private_store, txy_sources.HELAB_ONLY),
                      memory=held["fingerprint"])  # (Origins unknown: MATLAB's.)
    assert loaded(events)["memory_shots"] == [] and sorted(shots_read(events)) == [1, 2, 3, 4]


def test_a_conversion_since_the_cache_defeats_the_quick_check(tmp_path: Path, private_store: str) -> None:
    source = make_run(tmp_path, private_store)
    first = loaded(run_load(source, tmp_path, private_store, options(tmp_path, private_store)))
    write_raw(source, 5, raw_bytes(10_000))
    convert(source, tmp_path, private_store, shots=[5])
    events = run_load(source, tmp_path, private_store, options(tmp_path, private_store),
                      memory=first["fingerprint"], base_signature=first["signature"],
                      memory_origins=first["txy"]["origins"])
    result = loaded(events)
    assert not result.get("unchanged") and sorted(shots_read(events)) == [5]
    assert result["memory_shots"] == [1, 2, 3, 4] and result["txy"]["origins"]["5"] == f"helab:{PROFILE}"


def test_folder_state_and_its_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fingerprints, "RACY_SECONDS", 2.0)  # (Tests settle at once, so nothing is racy.)
    folder = tmp_path / "h"
    assert helab_txy.folder_state([str(folder)], time.time()) == []
    folder.mkdir()
    old = time.time() - 600
    os.utime(folder, (old, old))
    state = helab_txy.folder_state([str(folder)], time.time())
    assert state == [[str(folder), os.stat(folder).st_mtime_ns]]
    assert helab_txy.state_unchanged(state, state) and helab_txy.state_unchanged([], [])
    assert not helab_txy.state_unchanged([], state) and not helab_txy.state_unchanged(None, [])
    os.utime(folder, None)  # Just now: too close to trust.
    racy = helab_txy.folder_state([str(folder)], time.time())
    assert racy[0][1] is None and not helab_txy.state_unchanged(racy, racy)


def test_folders_are_where_convert_writes(tmp_path: Path) -> None:
    txy = {"cache_base": "/c", "temps": "/t"}
    path = str(tmp_path / "run")
    assert helab_txy.folders(path, txy, "root://u/run") == [
        folder_for("/c", "root://u/run"), folder_for("/t", "root://u/run"), folder_for("/t", "path:" + path)]
    assert helab_txy.folders(path, {"temps": "/t"}, "") == [folder_for("/t", "path:" + path)]


@pytest.mark.parametrize(("source", "matlab", "helab", "held", "expected"), [
    ("matlab", True, True, None, "matlab"), ("matlab", False, True, None, "helab"),
    ("helab", True, True, None, "helab"), ("helab", True, False, None, "matlab"),
    ("matlab-only", False, True, None, None), ("helab-only", True, False, None, None),
    # Held shots keep their kind while it is there.
    ("matlab", True, True, "helab:x", "helab"), ("helab", True, True, "", "matlab"),
    ("matlab", True, False, "helab:x", "matlab"),
])
def test_choose(source: str, matlab: bool, helab: bool, held: str | None, expected: str | None) -> None:
    assert txy_sources.choose(source, matlab, helab, held) == expected


# Live.


def live(source: Path, tmp_path: Path, private_store: str, memory: list[Any], **kwargs: Any) -> list[dict[str, Any]]:
    output = tmp_path / f"live-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    txy = {**options(tmp_path, private_store), "key": _key(source, private_store)}  # (FolderCache's root key.)
    live_check(str(source), str(output), events.append, memory, txy=txy, **kwargs)  # type: ignore[arg-type]
    return events


def last(events: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return [event for event in events if event["kind"] == kind][-1]


def test_live_finds_a_shot_converted_since_and_keeps_held_kinds(tmp_path: Path, private_store: str) -> None:
    source = make_run(tmp_path, private_store)
    first = loaded(run_load(source, tmp_path, None, options(tmp_path, private_store)))
    origins = first["txy"]["origins"]
    # Nothing converted since and the folder unchanged: one stat (and HeLab's folders') is the check.
    # (Fresh folders' mtimes are too recent to trust, so they are aged first.)
    old = time.time() - 600
    for folder in [*helab_txy.folders(str(source), options(tmp_path, private_store), _key(source, private_store)),
                   str(source)]:
        if os.path.isdir(folder):
            os.utime(folder, (old, old))
    folder_mtime = os.stat(source).st_mtime_ns
    steady = live(source, tmp_path, private_store, first["fingerprint"], memory_origins=origins)
    helab_since = last(steady, "live_unchanged")["live_helab"]
    again = live(source, tmp_path, private_store, first["fingerprint"], memory_origins=origins, since=folder_mtime,
                 helab_since=helab_since)
    assert [event["kind"] for event in again] == ["live_unchanged"] and not again[0]["live_listed"]
    # Shot 5 converted (its raw file into the folder, its TXY into HeLab's folder); MATLAB's TXY of held shot
    # 3 arrives too.
    write_raw(source, 5, raw_bytes(10_000))
    convert(source, tmp_path, private_store, shots=[5])
    matlab_txy(source, 3)
    first_look = live(source, tmp_path, private_store, first["fingerprint"], memory_origins=origins,
                      since=folder_mtime, helab_since=helab_since)
    waiting = last(first_look, "live_unchanged")
    assert waiting["live_listed"] and [entry[0] for entry in waiting["live_seen"]] == [5]
    events = live(source, tmp_path, private_store, first["fingerprint"], memory_origins=origins,
                  seen=waiting["live_seen"])
    result = loaded(events)
    assert sorted(shots_read(events)) == [5] and result["memory_shots"] == [1, 2, 3, 4]
    # Shot 3 stays HeLab's (held from it); shot 5 is HeLab's; the signature is the folder's MATLAB TXY.
    assert result["txy"]["origins"] == {"3": f"helab:{PROFILE}", "4": f"helab:{PROFILE}", "5": f"helab:{PROFILE}"}
    assert result["signature"] == summary_signature(events)
    assert "live_helab" in result


def _key(source: Path, private_store: str) -> str:
    """The folder's root key, as convert finds it (the store is only asked for its key)."""
    from helab.utils import constants
    with stores._cache_store(store_root(constants.cache_dir()), [str(source)]) as store:
        return helab_txy.store_key(store, str(source))


def test_live_saves_keep_the_origins(tmp_path: Path, private_store: str) -> None:
    source = make_run(tmp_path, private_store)
    events = run_load(source, tmp_path, None, options(tmp_path, private_store))
    first = loaded(events)
    held_dir = tmp_path / "held"
    held_dir.mkdir()
    for shot, array in shots_read(events).items():
        np.save(held_dir / f"{shot}.npy", array)
    saved: list[dict[str, Any]] = []
    save_held(str(source), saved.append, {"directory": store_root(private_store)},  # type: ignore[arg-type]
              first["fingerprint"], [], str(held_dir), txy=options(tmp_path, private_store), held_txy=first["txy"])
    assert not [event for event in saved if event["kind"] == "shots_missing"]
    result = loaded(saved)
    assert result["txy"]["origins"] == first["txy"]["origins"] and result["signature"] == first["signature"]
    with stores._cache_store(store_root(private_store), [str(source)]) as store:
        row = store.read_dataset_row(str(source)).value
    assert row is not None and row["info"]["txy"]["origins"] == first["txy"]["origins"]
    # Held without its record: HeLab's shots are taken for MATLAB's, which the folder lacks.
    lost: list[dict[str, Any]] = []
    save_held(str(source), lost.append, None, first["fingerprint"], [], str(held_dir),  # type: ignore[arg-type]
              txy=options(tmp_path, private_store, txy_sources.MATLAB_ONLY))
    assert [event["missing"] for event in lost if event["kind"] == "shots_missing"] == [[3, 4]]


# Views, results and their keys.


def dataset(origins: dict[str, str], source: str = "matlab", signature: str = "sig") -> Dataset:
    fingerprint = [[1, 10, 100], [2, 20, 200]]
    data = {1: np.zeros((2, 3)), 2: np.ones((2, 3))}
    metadata = {"fingerprint": fingerprint, "txy": {"source": source, "origins": origins,
                                                    "profiles": {"h": {"name": "plates-2022", "version": 1}}}}
    return Dataset("/data/run", signature, data, metadata, 0)


def context(view: Any) -> AnalysisContext:
    return AnalysisContext("job", "act", view, MappingProxyType({}), AnalysisIdentity("a", "1"),
                           coverage=Coverage.of(view))


def test_views_and_result_keys_carry_the_source() -> None:
    plain = build_view(dataset({}))
    filled = build_view(dataset({"2": "helab:h"}))
    helab = build_view(dataset({"1": "helab:h", "2": "helab:h"}, source="helab-only"))
    assert (plain.identity.source, filled.identity.source, helab.identity.source) == ("", "", "helab-only")
    assert dict(filled.origins) == {2: "helab:h"} and plain.txy_text() == "TXY: MATLAB's"
    assert filled.txy_text() == "TXY: HeLab's (plates-2022 v1) for 1 of 2 shots, MATLAB's for the rest"
    assert helab.txy_text() == "TXY: HeLab's (plates-2022 v1)"
    keys = [AnalysisResult.of(context(view), "completed").reuse_key() for view in (plain, filled, helab)]
    # MATLAB's alone: the key as it was before sources (no new fields).
    assert "txy_source" not in keys[0] and "origins" not in keys[0]["coverage"]
    assert keys[1]["coverage"]["origins"] == [[2, "helab:h"]] and keys[2]["txy_source"] == "helab-only"
    assert len({str(key) for key in keys}) == 3
    # A covered shot now from the other kind of TXY is changed.
    assert Coverage.of(filled).diff(plain).changed == (2,)


def test_a_revision_or_reload_never_crosses_sources() -> None:
    plain = build_view(dataset({}))
    assert revise(plain, dataset({}, source="helab-only")).revision == 1  # Its own view, no revision.
    swapped = revise(plain, dataset({"2": "helab:h"}))
    assert swapped.revision == 2 and swapped.added_shots == (2,) and dict(swapped.origins) == {2: "helab:h"}
    restored = restore(plain, dataset({"2": "helab:h"}))
    assert restored.kept == (1,) and restored.changed == (2,)
    assert restore(plain, dataset({}, source="helab")).changed == (1, 2)


# FolderCache: each source's datasets and jobs apart; the options a load is sent.


def test_folder_cache_keeps_each_sources_datasets_apart(qtbot: Any, monkeypatch: pytest.MonkeyPatch,
                                                         tmp_path: Path) -> None:
    from helab.utils import constants
    from helab.utils.folder_cache import FolderCache
    service = service_for_test(monkeypatch)
    cache = FolderCache(service)
    path = "/data/run"
    tab, plot = dataset({"2": "helab:h"}), dataset({"1": "helab:h", "2": "helab:h"}, source="helab")
    for entry in (tab, plot):
        cache.datasets[cache.dataset_key(entry)] = entry
    assert cache.dataset(path, "sig") is tab and cache.dataset(path, "sig", "helab") is plot
    assert cache.latest_dataset(path) is tab and cache.latest_dataset(path, "helab") is plot
    assert cache._base(path) is tab and cache._base(path, "", "helab") is plot
    assert cache._base(path, "", "helab-only") is None
    cache._drop_superseded(dataset({}, signature="newer"))  # (A newer tab dataset: the plot's stays.)
    assert cache.dataset(path, "sig", "helab") is plot and cache.dataset(path, "sig") is None
    # The options: the default source unless asked, the profile from the settings, the bases.
    sent = cache.with_txy(str(tmp_path), {"memory": []})["txy"]
    assert sent["source"] == "matlab" and sent["profile_hash"] == MATLAB_2019.content_hash()
    assert sent["temps"] == constants.DIR_TEMPS and sent["cache_base"] == os.path.dirname(store_root(constants.cache_dir()))
    assert cache.with_txy(str(tmp_path), {"txy": {"source": "helab-only"}})["txy"]["source"] == "helab-only"
    cache.set_convert_profile(MATLAB_2023_LAB_EDIT)
    assert cache.with_txy(str(tmp_path), {})["txy"]["profile_hash"] == MATLAB_2023_LAB_EDIT.content_hash()
    service.shutdown()
