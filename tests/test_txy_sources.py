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
from helab.convert.pipeline import convert_raw
from helab.convert.profile import MATLAB_2019, MATLAB_2023_LAB_EDIT
from helab.io_ops import fingerprints, helab_txy, stores
from helab.io_ops.convert import convert_folder, folder_for
from helab.io_ops.live import live_check
from helab.io_ops.loading import load
from helab.io_ops.save_held import save_held
from helab.utils import txy_sources
from helab.utils.cache_store import store_root
from helab.utils.folder_cache import Dataset, FolderCache
from test_convert_helab import OLD, raw_bytes, write_raw
from test_folder_cache import service_for_test

PROFILE = MATLAB_2019.content_hash()

# A folder as FolderCache keys it (``FolderCache.key``: on Windows with a drive letter).
RUN = os.path.abspath("/data/run")


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


# The built-in tags by hash, as ``FolderCache.with_txy`` sends a profile's (Q18.4); "" any.
TAGS = {PROFILE: "m19v1", MATLAB_2023_LAB_EDIT.content_hash(): "m23v1", "": ""}


def options(tmp_path: Path, private_store: str, source: str = txy_sources.MATLAB,
            profile_hash: str = PROFILE) -> dict[str, Any]:
    return {"source": source, "profile_hash": profile_hash, "profile_tag": TAGS[profile_hash],
            "cache_base": private_store, "temps": str(tmp_path / "temps")}


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
    assert result["txy"]["source"] == "matlab-priority"  # (Asked as "matlab", its name before Q18.2.)
    assert result["txy"]["origins"] == {"3": f"helab:{PROFILE}", "4": f"helab:{PROFILE}"}
    assert result["txy"]["profiles"] == {PROFILE: {"name": "matlab-2019", "version": 1, "calibrated": False,
                                                   "names": ["matlab-2019 v1"]}}
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
    # The default (Q18.2): HeLab's where they exist, MATLAB's for the rest.
    assert origins(txy_sources.HELAB_PRIORITY) == ([1, 2, 3, 4], helab)
    assert origins(txy_sources.MATLAB_PRIORITY) == ([1, 2, 3, 4], {"3": f"helab:{PROFILE}", "4": f"helab:{PROFILE}"})
    # Without the option (a helper of before): the default, but without the app's folders HeLab's aren't found.
    events = run_load(source, tmp_path, None, None)
    assert sorted(shots_read(events)) == [1, 2] and loaded(events)["txy"]["source"] == "helab-priority"
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
    assert (beside / "d_txy_helab_m19v1_7.txt").is_file()
    events = run_load(beside, tmp_path, None, options(tmp_path, private_store))
    assert sorted(shots_read(events)) == [7]
    assert loaded(events)["names"] == ["d_txy_helab_m19v1_7.txt"]


def test_a_beside_txy_is_current_by_its_tag_and_date_alone(tmp_path: Path, private_store: str) -> None:
    """Q18.4: no record beside the raw files, so another computer's TXY of the profile's tag counts while
    it is newer than its raw file; one older, of another tag, or of HeLab's untagged names doesn't."""
    source = tmp_path / "beside"
    source.mkdir()
    for shot in (1, 2, 3, 4):
        write_raw(source, shot, raw_bytes(10_000, 20_000))
    made = convert_raw(raw_bytes(10_000, 20_000), MATLAB_2019, "reference")
    assert made
    for name, mtime in (("d_txy_helab_m19v1_1.txt", OLD + 60), ("d_txy_helab_m19v1_2.txt", OLD - 60),
                        ("d_txy_helab_m23v1_3.txt", OLD + 60), ("d_txy_helab_4.txy", OLD + 60)):
        (source / name).write_bytes(made)
        os.utime(source / name, (mtime, mtime))
    found = loaded(run_load(source, tmp_path, None, options(tmp_path, private_store, txy_sources.HELAB_ONLY)))
    assert found["names"] == ["d_txy_helab_m19v1_1.txt"]
    assert found["txy"]["origins"] == {"1": txy_sources.helab_origin(PROFILE)}
    # The other profile's tag, asked for, finds its own.
    other = options(tmp_path, private_store, txy_sources.HELAB_ONLY, MATLAB_2023_LAB_EDIT.content_hash())
    assert loaded(run_load(source, tmp_path, None, other))["names"] == ["d_txy_helab_m23v1_3.txt"]
    # Beside ones need a tag asked for: "any" finds none of them.
    with pytest.raises(ValueError, match="No current HeLab TXY"):
        run_load(source, tmp_path, None, options(tmp_path, private_store, txy_sources.HELAB_ONLY, ""))
    # A conversion beside takes the current one as it is, keeps the older one, and converts the rest
    # under the tagged name, leaving the untagged file alone.
    events = convert(source, tmp_path, private_store, beside=True, beside_confirmed=True)
    assert [event["shot"] for event in events if event["kind"] == "shot_kept"] == [2]
    assert sorted(event["shot"] for event in events if event["kind"] == "shot_converted") == [3, 4]
    assert sorted(path.name for path in source.glob("d_txy_helab_*")) == [
        "d_txy_helab_4.txy", "d_txy_helab_m19v1_1.txt", "d_txy_helab_m19v1_2.txt", "d_txy_helab_m19v1_3.txt",
        "d_txy_helab_m19v1_4.txt", "d_txy_helab_m23v1_3.txt"]


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
    ("matlab-priority", True, True, None, "matlab"), ("matlab-priority", False, True, None, "helab"),
    ("helab-priority", True, True, None, "helab"), ("helab-priority", True, False, None, "matlab"),
    ("matlab-only", False, True, None, None), ("helab-only", True, False, None, None),
    ("matlab-only", True, True, None, "matlab"), ("helab-only", True, True, None, "helab"),
    # Held shots keep their kind while it is there.
    ("matlab-priority", True, True, "helab:x", "helab"), ("helab-priority", True, True, "", "matlab"),
    ("matlab-priority", True, False, "helab:x", "matlab"),
    # The names before Q18.2 read as the priority sources.
    ("matlab", True, True, None, "matlab"), ("helab", True, True, None, "helab"),
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


def dataset(origins: dict[str, str], source: str = "helab-priority", signature: str = "sig",
            tag: str = "m19v1") -> Dataset:
    fingerprint = [[1, 10, 100], [2, 20, 200]]
    data = {1: np.zeros((2, 3)), 2: np.ones((2, 3))}
    metadata = {"fingerprint": fingerprint, "txy": {"source": source, "origins": origins, "profile_tag": tag,
                                                    "profiles": {"h": {"name": "plates-2022", "version": 1}}}}
    return Dataset(RUN, signature, data, metadata, 0)


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
    assert restore(plain, dataset({}, source="matlab-priority")).changed == (1, 2)
    # The two priority sources share the identity (their origins tell their data apart), but a view of one
    # is never revised by, or restored from, the other's data (Q18.2), nor another profile's.
    other = build_view(dataset({}, source="matlab-priority"))
    assert other.identity == plain.identity and other.txy_choice != plain.txy_choice
    assert revise(plain, dataset({}, source="matlab-priority")).revision == 1
    assert revise(plain, dataset({}, tag="m23v1")).revision == 1
    assert restore(plain, dataset({}, tag="m23v1")).changed == (1, 2)


# FolderCache: each source's datasets and jobs apart; the options a load is sent.


def test_folder_cache_keeps_each_sources_datasets_apart(qtbot: Any, monkeypatch: pytest.MonkeyPatch,
                                                         tmp_path: Path) -> None:
    from helab.utils import constants
    service = service_for_test(monkeypatch)
    cache = FolderCache(service)
    path = RUN
    # The tab's choice (Q18.2): the setting's source, helab-priority, with the conversion profile's tag.
    assert cache.tab_choice() == "helab-priority@m19v1"
    tab, plot = dataset({"2": "helab:h"}), dataset({"1": "helab:h"}, source="matlab-priority")
    other = dataset({"1": "helab:h", "2": "helab:h"}, tag="m23v1")  # Another profile's HeLab TXY.
    # (Loaded by the tab, or by plots: as FolderCache records them, ``_with_choice``.)
    tab.metadata["txy"]["tab"], plot.metadata["txy"]["tab"], other.metadata["txy"]["tab"] = True, False, False
    for entry in (tab, plot, other):
        cache.datasets[cache.dataset_key(entry)] = entry
    assert cache.dataset_choice(plot) == "matlab-priority@m19v1" and cache.dataset_choice(other) == "helab-priority@m23v1"
    assert cache.dataset(path, "sig") is tab and cache.dataset(path, "sig", "matlab-priority@m19v1") is plot
    assert cache.dataset(path, "sig", "helab-priority@m23v1") is other
    assert cache.latest_dataset(path) is tab and cache.latest_dataset(path, "matlab-priority@m19v1") is plot
    assert cache._base(path) is tab and cache._base(path, "", "matlab-priority@m19v1") is plot
    assert cache._base(path, "", "helab-only@m19v1") is None
    # Data naming no source (before Q6.6: MATLAB's alone) is the tab's, whatever its source.
    assert cache.is_tab_dataset(Dataset(RUN, "sig", {}, {"fingerprint": []}, 0))
    cache._drop_superseded(dataset({}, signature="newer"))  # (A newer tab dataset: the others stay.)
    assert cache.dataset(path, "sig", "matlab-priority@m19v1") is plot and cache.dataset(path, "sig") is None
    # The tab's source changed (Settings; Avocet's review): it applies when a folder loads again. The data
    # a tab shows stays the tab's (its record says the tab loaded it), and a plot's stays the plot's.
    shown, plotted = dataset({"2": "helab:h"}, signature="shown"), dataset({}, "matlab-priority", "shown")
    shown.metadata["txy"]["tab"], plotted.metadata["txy"]["tab"] = True, False
    for entry in (shown, plotted):
        cache.datasets[cache.dataset_key(entry)] = entry
    cache.set_tab_source("matlab-priority")
    assert cache.tab_choice() == "matlab-priority@m19v1" and cache.is_tab_dataset(shown)
    assert cache.dataset(path, "shown") is shown and cache.current_dataset(path) is shown
    assert cache.latest_dataset(path) is shown and cache._base(path) is shown
    # ... but it is no base for a load of the new choice (Avocet's review, round 2): its held kinds of TXY
    # would carry over into the new source's data.
    assert cache._base(path, "", None, cache.tab_choice()) is None
    assert cache._base(path, "", None, "helab-priority@m19v1") is shown
    assert cache.dataset(path, "shown", "matlab-priority@m19v1") is plotted and not cache.is_tab_dataset(plotted)
    # A tab load's options now ask for the new source, marked the tab's; a plot's isn't.
    assert cache.with_txy(path, {})["txy"]["tab"] is True
    assert cache.with_txy(path, {"txy": {"source": "helab-only"}})["txy"]["tab"] is False
    cache.set_tab_source("helab")  # (Its name before Q18.2.)
    assert cache.tab_source() == "helab-priority" and cache.dataset(path, "shown") is shown
    # The options: the tab's source unless asked, the profile from the settings, the bases.
    sent = cache.with_txy(str(tmp_path), {"memory": []})["txy"]
    assert sent["source"] == "helab-priority" and sent["profile_hash"] == MATLAB_2019.content_hash()
    assert sent["profile_tag"] == "m19v1" and sent["profile"]["name"] == "matlab-2019"
    assert sent["temps"] == constants.DIR_TEMPS and sent["cache_base"] == os.path.dirname(store_root(constants.cache_dir()))
    assert cache.with_txy(str(tmp_path), {"txy": {"source": "helab-only"}})["txy"]["source"] == "helab-only"
    cache.set_convert_profile(MATLAB_2023_LAB_EDIT)
    assert cache.with_txy(str(tmp_path), {})["txy"]["profile_hash"] == MATLAB_2023_LAB_EDIT.content_hash()
    assert cache.tab_choice() == "helab-priority@m23v1" and cache.dataset(path, "shown") is shown
    service.shutdown()


def test_a_tab_load_of_a_new_choice_waits_for_the_running_one(qtbot: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Avocet's review: after Settings changes the tabs' source, a tab's load doesn't join the running load of
    the old choice (it would answer with that choice's data): it waits for it to end, then runs as its own."""
    service = service_for_test(monkeypatch)
    cache = FolderCache(service)
    try:
        assert cache.submit("tab-a", 0, RUN, "load", {})
        old = cache.jobs[("load", RUN)]
        assert old.payload["txy"]["source"] == "helab-priority"
        # The same choice joins it.
        assert cache.submit("tab-b", 0, RUN, "load", {}) and ("tab-b", 0) in old.subscribers
        cache.set_tab_source("matlab-priority")
        answers: list[str] = []
        cache.resultReady.connect(lambda request, event: answers.append(event["kind"])
                                  if request.owner == "tab-c" else None)
        assert cache.submit("tab-c", 0, RUN, "load", {})
        assert ("tab-c", 0) not in old.subscribers and answers == ["queued"]
        for owner in ("tab-a", "tab-b"):
            cache.cancel(owner, "load", RUN)
        qtbot.waitUntil(lambda: (job := cache.jobs.get(("load", RUN))) is not None and job is not old)
        new = cache.jobs[("load", RUN)]
        assert new.payload["txy"]["source"] == "matlab-priority" and ("tab-c", 0) in new.subscribers
    finally:
        service.shutdown()


# Review (Egret) fixes: held HeLab shots are never a mismatch; trust needs the profile; Live's summary is
# the folder's; records only for shots HeLab could give.


def kinds_of(events: list[dict[str, Any]]) -> list[str]:
    return [event["kind"] for event in events]


def test_clearing_helabs_never_makes_a_mismatch(tmp_path: Path, private_store: str) -> None:
    source = make_run(tmp_path, private_store)
    first = loaded(run_load(source, tmp_path, None, options(tmp_path, private_store)))
    origins = first["txy"]["origins"]
    helab_txy.clear_converted(helab_txy.converted_root(store_root(private_store)))
    # Live: shots 3 and 4 (HeLab's, no MATLAB TXY) are dropped, not "another folder".
    events = live(source, tmp_path, private_store, first["fingerprint"], memory_origins=origins)
    assert "shots_missing" not in kinds_of(events)
    result = loaded(events)
    assert result["memory_shots"] == [1, 2] and [entry[0] for entry in result["fingerprint"]] == [1, 2]
    assert result["load_counts"]["removed"] == 2 and result["txy"]["origins"] == {}
    # A load holding them, and one finding them in the cache: removed, not a mismatch.
    events = run_load(source, tmp_path, None, options(tmp_path, private_store), memory=first["fingerprint"],
                      memory_origins=origins, base_signature=first["signature"])
    assert "shots_missing" not in kinds_of(events) and loaded(events)["memory_shots"] == [1, 2]
    source2 = tmp_path / "second"
    source2.mkdir()
    for shot in (1, 2, 3):
        write_raw(source2, shot, raw_bytes(10_000 * shot))
    matlab_txy(source2, 1)
    convert(source2, tmp_path, private_store)
    cached = loaded(run_load(source2, tmp_path, private_store, options(tmp_path, private_store)))
    assert cached["txy"]["origins"] == {"2": f"helab:{PROFILE}", "3": f"helab:{PROFILE}"}
    helab_txy.clear_converted(helab_txy.converted_root(store_root(private_store)))
    events = run_load(source2, tmp_path, private_store, options(tmp_path, private_store))
    assert "shots_missing" not in kinds_of(events) and sorted(shots_read(events)) in ([], [1])
    assert [entry[0] for entry in loaded(events)["fingerprint"]] == [1]


def test_a_held_shot_converted_again_is_read_again(tmp_path: Path, private_store: str) -> None:
    source = make_run(tmp_path, private_store)
    first = loaded(run_load(source, tmp_path, None, options(tmp_path, private_store)))
    origins = first["txy"]["origins"]
    convert(source, tmp_path, private_store, profile=MATLAB_2023_LAB_EDIT)  # The profile changed.
    other = MATLAB_2023_LAB_EDIT.content_hash()
    txy = {**options(tmp_path, private_store, profile_hash=other), "key": _key(source, private_store)}

    def check(**kwargs: Any) -> list[dict[str, Any]]:
        output = tmp_path / f"live-{time.monotonic_ns()}"
        output.mkdir()
        events: list[dict[str, Any]] = []
        live_check(str(source), str(output), events.append, first["fingerprint"], txy=txy,  # type: ignore[arg-type]
                   memory_origins=origins, check_level="full", **kwargs)
        return events
    look = check()
    assert "shots_missing" not in kinds_of(look)
    seen = last(look, "live_unchanged")["live_seen"]
    assert sorted(entry[0] for entry in seen) == [3, 4]  # Read again once seen unchanged a check apart.
    result = loaded(check(seen=seen))
    assert sorted(entry["shot"] for entry in result["live_reread"]) == [3, 4]
    assert result["txy"]["origins"] == {"3": f"helab:{other}", "4": f"helab:{other}"}


def test_live_finds_the_store_key_itself(tmp_path: Path, private_store: str) -> None:
    """With no root known to the app (FolderCache sends key ""), Live asks the store as a load does."""
    source = make_run(tmp_path, private_store)
    first = loaded(run_load(source, tmp_path, None, options(tmp_path, private_store)))
    assert first["txy"]["key"].startswith("root://")  # (FolderCache sends it back from the data's record.)
    output = tmp_path / "out"
    output.mkdir()
    events: list[dict[str, Any]] = []
    txy = {**options(tmp_path, private_store), "key": "", "cache_directory": store_root(private_store)}
    write_raw(source, 5, raw_bytes(10_000))
    convert(source, tmp_path, private_store, shots=[5])
    live_check(str(source), str(output), events.append, first["fingerprint"], txy=txy,  # type: ignore[arg-type]
               memory_origins=first["txy"]["origins"])
    assert "shots_missing" not in kinds_of(events)
    assert [entry[0] for entry in last(events, "live_unchanged")["live_seen"]] == [5]


def test_a_held_shot_of_another_profile_isnt_trusted(tmp_path: Path, private_store: str) -> None:
    source = make_run(tmp_path, private_store)
    first = loaded(run_load(source, tmp_path, None, options(tmp_path, private_store)))
    other = {**options(tmp_path, private_store), "profile_hash": MATLAB_2023_LAB_EDIT.content_hash(),
             "key": _key(source, private_store)}
    held = loaded(run_load(source, tmp_path, None, other, memory=first["fingerprint"],
                           memory_origins=first["txy"]["origins"], full_check=True))
    assert held["txy"]["origins"] == {} and held["memory_shots"] == [1, 2]
    # Live's shortcut is the profile's too: the same folders with another profile asked for list again.
    steady = last(live(source, tmp_path, private_store, first["fingerprint"], memory_origins=first["txy"]["origins"]),
                  "live_unchanged")["live_helab"]
    assert steady["profile_hash"] == PROFILE
    output = tmp_path / "out"
    output.mkdir()
    events: list[dict[str, Any]] = []
    live_check(str(source), str(output), events.append, first["fingerprint"], txy=other,  # type: ignore[arg-type]
               memory_origins=first["txy"]["origins"], since=os.stat(source).st_mtime_ns, helab_since=steady)
    assert last(events, "live_unchanged" if "live_unchanged" in kinds_of(events) else "loaded")["live_listed"]


def test_lives_summary_is_the_folders_when_matlab_arrives_for_a_held_shot(tmp_path: Path, private_store: str) -> None:
    source = make_run(tmp_path, private_store)
    first = loaded(run_load(source, tmp_path, None, options(tmp_path, private_store)))
    origins = first["txy"]["origins"]
    matlab_txy(source, 3)  # MATLAB's TXY of held HeLab shot 3,
    matlab_txy(source, 9)  # and a new MATLAB shot.
    seen = last(live(source, tmp_path, private_store, first["fingerprint"], memory_origins=origins),
                "live_unchanged")["live_seen"]
    result = loaded(live(source, tmp_path, private_store, first["fingerprint"], memory_origins=origins, seen=seen))
    scan = loaded(run_load(source, tmp_path, None, options(tmp_path, private_store, txy_sources.MATLAB_ONLY)))
    assert result["signature"] == scan["signature"]  # As the next scan computes it: the tab doesn't reload.
    assert result["txy"]["origins"]["3"] == f"helab:{PROFILE}"  # (Still held from HeLab's.)


def test_a_dont_cache_folders_txy_are_found_in_the_temp_folder(tmp_path: Path, private_store: str) -> None:
    """Q27.4: converted to the temp folder (by its root key), a load finds them there and marks it used."""
    from helab.convert import provenance
    from test_convert_helab import flag_no_cache
    source = tmp_path / "run"
    source.mkdir()
    for shot in (1, 2):
        write_raw(source, shot, raw_bytes(10_000 * shot))
    flag_no_cache(private_store, source)
    [plan] = [event for event in convert(source, tmp_path, private_store) if event["kind"] == "convert_plan"]
    assert plan["output"] == "temp" and plan["folder"] == folder_for(str(tmp_path / "temps"), plan["key"])
    root, name = os.path.split(plan["folder"])
    with provenance.open_index(root, write=False) as index:  # type: ignore[union-attr]
        index.conn.execute("UPDATE folders SET last_used = 1.0")
    result = loaded(run_load(source, tmp_path, private_store, options(tmp_path, private_store, txy_sources.HELAB)))
    assert result["txy"]["origins"] == {"1": f"helab:{PROFILE}", "2": f"helab:{PROFILE}"}
    with provenance.open_index(root, write=False) as index:  # type: ignore[union-attr]
        assert index.folders()[0][4] > time.time() - 60


def test_a_load_whose_last_used_mark_times_out_still_returns_its_shots(tmp_path: Path, private_store: str) -> None:
    """A load moves its folder's ``last_used`` on, waiting at most 200 ms for a lock: with a conversion
    holding the index's write lock, the load still returns HeLab's shots, soon, and ``last_used`` stays."""
    import contextlib
    import sqlite3
    from helab.convert import provenance
    source = make_run(tmp_path, private_store)
    [folder] = [path for path in helab_txy.folders(str(source), options(tmp_path, private_store),
                                                   _key(source, private_store)) if os.path.isdir(path)]
    root = os.path.dirname(folder)
    with provenance.open_index(root, write=False) as index:  # type: ignore[union-attr]
        index.conn.execute("UPDATE folders SET last_used = 1.0")
    with contextlib.closing(sqlite3.connect(os.path.join(root, provenance.INDEX_NAME), isolation_level=None)) as holder:
        holder.execute("BEGIN IMMEDIATE")  # (A conversion's write, held.)
        started = time.monotonic()
        result = loaded(run_load(source, tmp_path, private_store, options(tmp_path, private_store, txy_sources.HELAB)))
        took = time.monotonic() - started
        holder.execute("ROLLBACK")
    assert result["txy"]["origins"] == {str(shot): f"helab:{PROFILE}" for shot in (1, 2, 3, 4)}
    assert took < 5.0  # (Not the index's 10 s busy timeout.)
    with provenance.open_index(root, write=False) as index:  # type: ignore[union-attr]
        assert index.folders()[0][4] == 1.0


def test_records_are_read_only_for_shots_helab_could_give(tmp_path: Path, private_store: str,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.convert import provenance
    source = make_run(tmp_path, private_store)  # MATLAB's TXY for 1 and 2; HeLab's for 1-4.
    read: list[int] = []
    original = provenance.read_shots

    def counting(root: str, folder: str, **kwargs: Any) -> Any:
        rows = original(root, folder, **kwargs)
        read.extend(shot for _, shot in rows)
        return rows
    monkeypatch.setattr(provenance, "read_shots", counting)
    run_load(source, tmp_path, None, options(tmp_path, private_store))
    assert sorted(read) == [3, 4]
    read.clear()
    run_load(source, tmp_path, None, options(tmp_path, private_store, txy_sources.HELAB))
    assert sorted(read) == [1, 2, 3, 4]


def test_profiles_of_one_output_are_all_named() -> None:
    shots = {1: helab_txy.HelabShot(1, "f", 1, 1, "h", {"name": "matlab-2019", "version": 1}, 0.0),
             2: helab_txy.HelabShot(2, "g", 1, 1, "h", {"name": "plates-2017", "version": 1}, 0.0)}
    record = helab_txy.record("matlab", {1: "helab:h", 2: "helab:h"}, shots, None, {}, [])
    assert record["profiles"]["h"]["names"] == ["matlab-2019 v1", "plates-2017 v1"]
    assert txy_sources.describe("helab-only", {1: "helab:h", 2: "helab:h"}, record["profiles"], 2) == \
        "TXY: HeLab's (matlab-2019 v1 / plates-2017 v1)"


def test_a_cache_save_marks_only_the_default_sources_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.utils.io_service import IORequest
    service = service_for_test(monkeypatch)
    cache = FolderCache(service)
    try:
        tab, plot = dataset({}, signature="sig"), dataset({"1": "helab:h", "2": "helab:h"}, source="helab-only")
        for entry in (tab, plot):
            cache.datasets[cache.dataset_key(entry)] = entry
        cache._finishing["saver"] = RUN
        cache._finishing_epochs["saver"] = 0
        cache._finishing_created["saver"] = time.monotonic()
        cache._on_finishing_event(IORequest("saver", 0, RUN, "load", {}, 60.0),
                                  {"kind": "cache_saved", "cache_info": {"signature": "sig", "saved_at": 1.0}})
        assert tab.metadata.get("disk_cached") is True and "disk_cached" not in plot.metadata
    finally:
        service.shutdown()


# Review round 2 (Egret): Live's and its saves' signature is the data's; the store asked once.


def test_a_matlab_only_live_revision_keeps_the_signature_it_had(tmp_path: Path, private_store: str) -> None:
    import hashlib
    import json
    source = tmp_path / "plain"
    source.mkdir()
    old = time.time() - 600
    for shot in (1, 2):
        os.utime(matlab_txy(source, shot), (old, old))
    first = loaded(run_load(source, tmp_path, None, options(tmp_path, private_store)))
    os.utime(matlab_txy(source, 3), (old, old))
    seen = last(live(source, tmp_path, private_store, first["fingerprint"]), "live_unchanged")["live_seen"]
    os.utime(matlab_txy(source, 4), (old, old))  # First seen at the next check: waiting, not in the data.
    events = live(source, tmp_path, private_store, first["fingerprint"], seen=seen)
    result = loaded(events)
    assert [entry[0] for entry in result["fingerprint"]] == [1, 2, 3]
    assert [entry[0] for entry in result["live_seen"]] == [4]
    # As before this floor: the hash of the data's fingerprint (a waiting file isn't claimed).
    assert result["signature"] == hashlib.sha256(json.dumps(result["fingerprint"]).encode()).hexdigest()
    assert result["signature"] == summary_signature(events)


def test_a_live_save_has_the_folders_signature(tmp_path: Path, private_store: str) -> None:
    source = make_run(tmp_path, private_store)
    events = run_load(source, tmp_path, None, options(tmp_path, private_store))
    first = loaded(events)
    held_dir = tmp_path / "held"
    held_dir.mkdir()
    for shot, array in shots_read(events).items():
        np.save(held_dir / f"{shot}.npy", array)
    matlab_txy(source, 3)  # MATLAB's TXY of held HeLab shot 3 arrives.
    saved: list[dict[str, Any]] = []
    save_held(str(source), saved.append, {"directory": store_root(private_store)},  # type: ignore[arg-type]
              first["fingerprint"], [], str(held_dir), txy=options(tmp_path, private_store), held_txy=first["txy"])
    scan = loaded(run_load(source, tmp_path, None, options(tmp_path, private_store, txy_sources.MATLAB_ONLY)))
    assert loaded(saved)["signature"] == scan["signature"]


def held_from_a_load(source: Path, tmp_path: Path, private_store: str) -> tuple[dict[str, Any], Path]:
    """A load's ``loaded`` (no store) and its arrays where the app keeps held data for a Live save."""
    events = run_load(source, tmp_path, None, options(tmp_path, private_store))
    held_dir = tmp_path / "held"
    held_dir.mkdir()
    for shot, array in shots_read(events).items():
        np.save(held_dir / f"{shot}.npy", array)
    return loaded(events), held_dir


def saved_info(source: Path, private_store: str) -> dict[str, Any]:
    with stores._cache_store(store_root(private_store), [str(source)]) as store:
        row = store.read_dataset_row(str(source)).value
    assert row is not None
    return dict(row["info"])


def test_a_live_save_whose_held_helab_txy_went_saves_the_rest(tmp_path: Path, private_store: str) -> None:
    """Codex 4424923880: held shots 3 and 4 were read from HeLab's TXY, since cleared, and the folder has no
    MATLAB TXY for them: the save goes on (they count as unsettled), with a name for each shot."""
    source = make_run(tmp_path, private_store)
    first, held_dir = held_from_a_load(source, tmp_path, private_store)
    helab_txy.clear_converted(helab_txy.converted_root(store_root(private_store)))
    saved: list[dict[str, Any]] = []
    save_held(str(source), saved.append, {"directory": store_root(private_store)},  # type: ignore[arg-type]
              first["fingerprint"], [], str(held_dir), txy=options(tmp_path, private_store), held_txy=first["txy"])
    assert "shots_missing" not in kinds_of(saved) and "cache_saved" in kinds_of(saved)
    result = loaded(saved)
    assert result["fingerprint"] == [list(entry) for entry in first["fingerprint"]] and result["unsettled_files"] == 2
    assert result["names"] == ["d_txy_forc1.txt", "d_txy_forc2.txt", "d_txy_helab_m19v1_3.txt",
                               "d_txy_helab_m19v1_4.txt"]
    info = saved_info(source, private_store)
    assert info["names"] == result["names"] and info["unsettled"] == 2


def test_a_live_saves_dataset_has_the_signature_it_sent(tmp_path: Path, private_store: str) -> None:
    """Codex 4424923889: a settled MATLAB TXY of held HeLab shot 3 counts in the ``loaded`` signature (the
    folder's); the dataset saved must carry that one, or the tab can't match ``cache_saved``."""
    source = make_run(tmp_path, private_store)
    first, held_dir = held_from_a_load(source, tmp_path, private_store)
    old = time.time() - 600
    os.utime(matlab_txy(source, 3), (old, old))
    saved: list[dict[str, Any]] = []
    save_held(str(source), saved.append, {"directory": store_root(private_store)},  # type: ignore[arg-type]
              first["fingerprint"], [], str(held_dir), txy=options(tmp_path, private_store), held_txy=first["txy"])
    result = loaded(saved)
    assert result["txy"]["origins"]["3"] == f"helab:{PROFILE}"  # (Still held from HeLab's.)
    assert result["signature"] != first["signature"]  # (Shot 3's MATLAB TXY counts now.)
    assert saved_info(source, private_store)["signature"] == result["signature"]


def test_a_shot_held_from_matlabs_keeps_it_when_helabs_is_converted(tmp_path: Path, private_store: str) -> None:
    """Codex 4425456506: under HeLab priority, shot 1 held from MATLAB's TXY (HeLab had none then) stays
    MATLAB's in Live's check and its save when HeLab's TXY of it is converted later: no mismatch ("changed")."""
    source = tmp_path / "run"
    source.mkdir()
    for shot in (1, 2, 3):
        write_raw(source, shot, raw_bytes(*(10_000 * k for k in range(1, shot + 1))))
    old = time.time() - 600
    os.utime(matlab_txy(source, 1), (old, old))
    convert(source, tmp_path, private_store, shots=[2, 3])
    priority = options(tmp_path, private_store, txy_sources.HELAB_PRIORITY)
    events = run_load(source, tmp_path, None, priority)
    first = loaded(events)
    assert sorted(first["txy"]["origins"]) == ["2", "3"]  # (Shot 1 is MATLAB's.)
    convert(source, tmp_path, private_store, shots=[1])  # HeLab's TXY of shot 1, current, arrives.
    txy = {**priority, "key": _key(source, private_store)}

    def check() -> list[dict[str, Any]]:
        output = tmp_path / "live"
        output.mkdir()
        sent: list[dict[str, Any]] = []
        live_check(str(source), str(output), sent.append, first["fingerprint"],  # type: ignore[arg-type]
                   txy=txy, memory_origins=first["txy"]["origins"])
        return sent
    assert kinds_of(check()) == ["live_unchanged"]  # (The held data stands: nothing to read.)
    held_dir = tmp_path / "held"
    held_dir.mkdir()
    for shot, array in shots_read(events).items():
        np.save(held_dir / f"{shot}.npy", array)
    saved: list[dict[str, Any]] = []
    save_held(str(source), saved.append, {"directory": store_root(private_store)},  # type: ignore[arg-type]
              first["fingerprint"], [], str(held_dir), txy=priority, held_txy=first["txy"])
    assert "shots_missing" not in kinds_of(saved)
    assert sorted(loaded(saved)["txy"]["origins"]) == ["2", "3"] and loaded(saved)["names"][0] == "d_txy_forc1.txt"
    # A load takes HeLab's for it, as the source asks (read anew: another kind than the one held).
    again = loaded(run_load(source, tmp_path, None, priority, memory=first["fingerprint"],
                            memory_origins=first["txy"]["origins"], base_signature=first["signature"]))
    assert sorted(again["txy"]["origins"]) == ["1", "2", "3"]
    # So does one from the saved dataset (as after a restart): its other shots reused, shot 1 read.
    restored = run_load(source, tmp_path, private_store, priority)
    assert sorted(loaded(restored)["txy"]["origins"]) == ["1", "2", "3"]
    assert loaded(restored)["cache_reason"] == "Reused 2 shots from disk cache; 1 new or changed TXY file to read"


def aged(*folders: str | Path) -> None:
    """Folders' mtimes moved back, so a quick check trusts them (a fresh mtime is too recent to)."""
    old = time.time() - 600
    for folder in folders:
        if os.path.isdir(folder):
            os.utime(folder, (old, old))


def test_the_quick_check_never_reuses_ram_of_another_kind(tmp_path: Path, private_store: str) -> None:
    """Codex 4425801677 (P1): this HeLab holds shots 1-3 from MATLAB's TXY; another HeLab on this computer (the
    same store) converts shot 3 and saves the dataset with it from HeLab's TXY. The signature (the folder's
    MATLAB TXY) is the same, so the cached quick check passed and RAM's MATLAB shot 3 was reused labelled
    HeLab's. It must be read."""
    source = tmp_path / "run"
    source.mkdir()
    old = time.time() - 600
    for shot in (1, 2, 3):
        write_raw(source, shot, raw_bytes(*(10_000 * k for k in range(1, shot + 1))))
        os.utime(matlab_txy(source, shot), (old, old))
    aged(source)
    priority = options(tmp_path, private_store, txy_sources.HELAB_PRIORITY)
    first = loaded(run_load(source, tmp_path, private_store, priority))
    assert first["txy"]["origins"] == {}
    # The other HeLab: shot 3 converted, the folder loaded and saved.
    convert(source, tmp_path, private_store, shots=[3])
    aged(source, *helab_txy.folders(str(source), priority, _key(source, private_store)))
    other = loaded(run_load(source, tmp_path, private_store, priority))
    assert sorted(other["txy"]["origins"]) == ["3"] and other["signature"] == first["signature"]
    # This one asks again with what it holds.
    events = run_load(source, tmp_path, private_store, priority, memory=first["fingerprint"],
                      base_signature=first["signature"], memory_origins=first["txy"]["origins"])
    result = loaded(events)
    assert 3 not in result["memory_shots"] and sorted(result["txy"]["origins"]) == ["3"]
    assert result["memory_shots"] == [1, 2] and result["source"] != "memory"


def test_helab_only_leaves_out_matlabs_shots_without_a_mismatch(tmp_path: Path, private_store: str) -> None:
    """Codex 4425801688: shots cached (or held) from MATLAB's TXY that HeLab only leaves out aren't deleted: their
    MATLAB TXY are there. The load gives HeLab's shots, with no ``shots_missing``."""
    source = tmp_path / "run"
    source.mkdir()
    old = time.time() - 600
    for shot in (1, 2, 3):
        write_raw(source, shot, raw_bytes(*(10_000 * k for k in range(1, shot + 1))))
        os.utime(matlab_txy(source, shot), (old, old))
    convert(source, tmp_path, private_store, shots=[3])
    first = loaded(run_load(source, tmp_path, private_store, options(tmp_path, private_store, txy_sources.MATLAB_ONLY)))
    assert first["txy"]["origins"] == {} and [entry[0] for entry in first["fingerprint"]] == [1, 2, 3]
    only = options(tmp_path, private_store, txy_sources.HELAB_ONLY)
    for kwargs in ({}, {"memory": first["fingerprint"], "base_signature": first["signature"]}):
        events = run_load(source, tmp_path, private_store, only, **kwargs)
        assert "shots_missing" not in kinds_of(events), kwargs
        result = loaded(events)
        assert [entry[0] for entry in result["fingerprint"]] == [3] and sorted(result["txy"]["origins"]) == ["3"]
        # (Counted as removed from the data shown: the shots the source leaves out.)
        assert result["total_files"] == result["files"] == 1 and result["load_counts"]["removed"] == 2


def test_live_asks_the_store_for_a_key_once_a_session(tmp_path: Path, private_store: str,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.io_ops import live as live_module
    source = tmp_path / "unrooted"
    source.mkdir()
    matlab_txy(source, 1)
    first = loaded(run_load(source, tmp_path, None, options(tmp_path, private_store)))
    txy = {**options(tmp_path, private_store), "key": "", "cache_directory": str(tmp_path / "no-store")}
    events: list[dict[str, Any]] = []
    output = tmp_path / "out"
    output.mkdir()
    live_check(str(source), str(output), events.append, first["fingerprint"], txy=txy)  # type: ignore[arg-type]
    state = last(events, "live_unchanged")["live_helab"]
    assert state["key"] == "" and state["key_asked"] is True
    # Told the store was asked (FolderCache sends ``key_asked``): not opened again.
    monkeypatch.setattr(stores, "_cache_store", lambda *args, **kwargs: pytest.fail("store opened again"))
    assert live_module._helab_key(str(source), {**txy, "key_asked": True}) == ""
    # FolderCache remembers it for the folder.
    service = service_for_test(monkeypatch)
    cache = FolderCache(service)
    try:
        cache._live_helab[cache.key(str(source))] = state
        assert cache.with_txy(str(source), {})["txy"]["key_asked"] is True
    finally:
        service.shutdown()


@pytest.mark.parametrize(("before", "after", "expected"), [
    ("helab-priority", "matlab-priority", {"3", "4"}), ("matlab-priority", "helab-priority", {"1", "2", "3", "4"})])
def test_after_a_settings_change_live_and_its_save_read_the_new_sources_txy(
        qtbot: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, private_store: str,
        before: str, after: str, expected: set[str]) -> None:
    """Avocet's review, round 2: the tab's data of the source before a Settings change is no base for Live's
    checks or save under the new one, so no held kind of TXY carries over: with both kinds for shots 1 and 2,
    the new source's origins come back (both directions), never the old ones saved under the new name."""
    source = make_run(tmp_path, private_store)  # MATLAB's TXY for 1 and 2, HeLab's for 1-4.
    path = FolderCache.key(str(source))
    service = service_for_test(monkeypatch)
    cache = FolderCache(service)
    try:
        cache.set_tab_source(before)
        first = loaded(run_load(source, tmp_path, None, options(tmp_path, private_store, before)))
        held = shots_read(run_load(source, tmp_path, None, options(tmp_path, private_store, before)))
        metadata = {**first, "txy": {**first["txy"], "tab": True}}
        shown = Dataset(path, first["signature"], held, metadata, 0)
        cache.datasets[cache.dataset_key(shown)] = shown
        old = set(first["txy"]["origins"])
        assert old != expected and cache._base(path) is shown
        cache.set_tab_source(after)
        helper_txy = {**options(tmp_path, private_store, after), "key": _key(source, private_store)}

        def request_of(owner: str) -> Any:
            job = next(job for job in cache.jobs.values() if owner in {key[0] for key in job.subscribers})
            return next(request for request in service.pending if request.owner == job.owner)

        # Live's check: nothing held, the folder listed, every shot read (a check later, once seen).
        assert cache.submit("live-owner", 0, path, "load", {
            "live": True, "live_since": first.get("folder_mtime_ns"), "prefer_base": shown.signature, "seen": [],
            "identity": "", "check_level": "full"})
        payload = request_of("live-owner").payload
        assert payload["memory"] == [] and "memory_origins" not in payload and payload["live_since"] is None
        assert payload["txy"]["source"] == after and payload["txy"]["tab"] is True

        def check(seen: list[Any]) -> list[dict[str, Any]]:
            output = tmp_path / f"live-{time.monotonic_ns()}"
            output.mkdir()
            events: list[dict[str, Any]] = []
            # (The identity as this test's helpers find it: Live's first listing records it.)
            live_check(str(source), str(output), events.append, payload["memory"],  # type: ignore[arg-type]
                       txy=helper_txy, seen=seen, check_level="full")
            return events
        looked = check([])
        read = next(event for event in check(last(looked, "live_unchanged" if any(
            event["kind"] == "live_unchanged" for event in looked) else "loaded")["live_seen"])
            if event["kind"] == "loaded")
        assert set(read["txy"]["origins"]) == expected and read["txy"]["source"] == after
        # Live's save: no held data of the new source to save as it is, so a load of it.
        cache.cancel("live-owner", "load", path)
        assert cache.submit("save-owner", 0, path, "load", {"save_memory": True, "save": True,
                                                            "prefer_base": shown.signature})
        payload = request_of("save-owner").payload
        assert "save_memory" not in payload and "memory_origins" not in payload
        saved = loaded(run_load(source, tmp_path, None, {**helper_txy, "source": payload["txy"]["source"]}))
        assert set(saved["txy"]["origins"]) == expected and saved["txy"]["source"] == after
    finally:
        service.shutdown()


def test_a_load_finding_the_cache_whole_with_a_new_signature_saves_it(tmp_path: Path, private_store: str) -> None:
    """Area review io-5 (2026-10-31): shots 1–3 held from HeLab's TXY under helab-priority, MATLAB's for 1–2.
    MATLAB's TXY of shot 3 arrives: the data's fingerprint is unchanged but the folder's signature (its
    MATLAB TXY) is new. The load reads no TXY file and the cached dataset takes the new signature, so the
    next check of the data in RAM is the quick one again."""
    source = tmp_path / "run"
    source.mkdir()
    old = time.time() - 600
    for shot in (1, 2, 3):
        write_raw(source, shot, raw_bytes(*(10_000 * k for k in range(1, shot + 1))))
    for shot in (1, 2):
        os.utime(matlab_txy(source, shot), (old, old))
    convert(source, tmp_path, private_store, shots=[1, 2, 3])
    priority = options(tmp_path, private_store, txy_sources.HELAB_PRIORITY)
    aged(source, *helab_txy.folders(str(source), priority, _key(source, private_store)))
    first = loaded(run_load(source, tmp_path, private_store, priority))
    assert saved_info(source, private_store)["signature"] == first["signature"]
    os.utime(matlab_txy(source, 3), (old, old))
    aged(source)
    events = run_load(source, tmp_path, private_store, priority)
    second = loaded(events)
    assert second["fingerprint"] == first["fingerprint"] and second["signature"] != first["signature"]
    assert not [event for event in events if event["kind"] == "file_started"]  # (No TXY file read.)
    assert saved_info(source, private_store)["signature"] == second["signature"]
    # The data in RAM is the cached data again: the next check doesn't list the folder.
    third = loaded(run_load(source, tmp_path, private_store, priority, memory=second["fingerprint"],
                            base_signature=second["signature"], memory_origins=second["txy"]["origins"]))
    assert third["source"] == "memory" and third["unchanged"], third["cache_reason"]
