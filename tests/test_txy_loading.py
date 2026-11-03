"""Caching v2 stage 2, step 3a: loads and Live's save in store-v4 (design addendum §4–§7). A load writes the
folder's TXY layers and its view, never a dataset; a later load reuses the layers and appends only new or
changed shots; a load that finds every shot unchanged rewrites nothing, its new signature included (A40.3);
a cached read is served from the view; a listing marks a layer whose TXY files are gone as the only copy;
Live's save writes only what its layers lack. Store-v3 loads are unchanged (the rest of the suite). Temp
stores only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

import numpy as np
import pytest

from helab.io_ops.loading import load, read_cached
from helab.io_ops.save_held import save_held
from helab.io_ops import stores
from helab.utils.cache_store import CacheStore


def data_folder(tmp_path: Path, shots: range = range(1, 3)) -> Path:
    source = tmp_path / "data" / "run"
    source.mkdir(parents=True, exist_ok=True)
    for shot in shots:
        write_shot(source, shot)
    return source


def write_shot(source: Path, shot: int, rows: int = 2) -> None:
    (source / f"d{shot}.txt").write_text(f"5,{shot}\n")
    (source / f"d_txy_forc{shot}.txt").write_text("".join(f"{shot}.{i},2,3\n" for i in range(rows)))
    old = time.time() - 600  # (Settled.)
    for name in (f"d{shot}.txt", f"d_txy_forc{shot}.txt"):
        os.utime(source / name, (old, old))


def v4_options(tmp_path: Path) -> dict[str, Any]:
    return {"directory": str(tmp_path / "caches" / "store-v4"), "budget": 8 << 30, "budget_set_at": 1.0}


def run_load(source: Path, tmp_path: Path, options: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
    output = tmp_path / f"artifacts-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    load(str(source), str(output), events.append, options, **kwargs)  # type: ignore[arg-type]
    return events


def first(events: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(event for event in events if event["kind"] == kind)


def opened(options: dict[str, Any], source: Path) -> CacheStore:
    return stores._cache_store(options["directory"], [str(source)])


def segments(options: dict[str, Any], source: Path) -> list[tuple[int, int]]:
    with opened(options, source) as store:
        key = store._path_key(str(source))
        return [(int(seq), int(count)) for seq, count in store._conn.execute(
            "SELECT seq, all_shots FROM txy_segments WHERE path = ? ORDER BY seq", (key,))]


def test_a_load_writes_layers_and_a_view_and_the_next_one_reuses_them(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    options = v4_options(tmp_path)
    events = run_load(source, tmp_path, options)
    assert first(events, "cache_saved")["cache_info"]["format"] == "txy-views-1"
    with opened(options, source) as store:
        assert store.read_dataset_row(str(source)).missing  # (Q45.4: never a dataset in store-v4.)
        layers = store.txy_layers(str(source)).value or {}
        assert set(layers) == {"matlab"} and sorted(layers["matlab"].entries) == [1, 2]
        assert {entry.kind for entry in layers["matlab"].entries.values()} == {"txy"}
        view = store.read_view(str(source), "", "").value
        assert view is not None and [entry[4] for entry in view.fingerprint] == ["matlab", "matlab"]
    again = run_load(source, tmp_path, options)
    loaded = first(again, "loaded")
    assert loaded["source"] == "disk" and loaded["cached"] and loaded["load_counts"]["read"] == 0
    assert not any(event["kind"] == "cache_saved" for event in again)  # (Nothing new: nothing written.)
    assert segments(options, source) == [(1, 2)]
    memory = [list(entry) for entry in loaded["fingerprint"]]
    quick = first(run_load(source, tmp_path, options, memory=memory, base_signature=loaded["signature"]), "loaded")
    assert quick.get("unchanged") is True  # (The quick check reads the view.)


def test_a_new_shot_appends_a_segment_of_that_shot_alone(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    options = v4_options(tmp_path)
    run_load(source, tmp_path, options)
    write_shot(source, 3, rows=5)
    events = run_load(source, tmp_path, options)
    assert first(events, "loaded")["load_counts"]["read"] == 1 and first(events, "cache_saved")
    assert segments(options, source) == [(1, 2), (2, 1)]  # (Shots 1 and 2 aren't written again.)
    with opened(options, source) as store:
        assert len((store.read_txy_shots(str(source), "matlab").value or {})[3]) == 5


def test_a_signature_only_change_rewrites_nothing(tmp_path: Path) -> None:
    """A40.3: every shot unchanged, the folder's signature not the view's (as when a MATLAB TXY arrives for a
    shot taken from HeLab's): the layers are reused whole and only the view's info is written."""
    source = data_folder(tmp_path)
    options = v4_options(tmp_path)
    run_load(source, tmp_path, options)
    with opened(options, source) as store:
        key = store._path_key(str(source))
        (info,) = store._conn.execute("SELECT info FROM txy_views WHERE path = ?", (key,)).fetchone()
        with store.transaction():
            store._conn.execute("UPDATE txy_views SET info = ? WHERE path = ?",
                                (json.dumps({**json.loads(info), "signature": "an older one"}), key))
    events = run_load(source, tmp_path, options)
    loaded = first(events, "loaded")
    assert loaded["cached"] and loaded["load_counts"]["read"] == 0 and segments(options, source) == [(1, 2)]
    with opened(options, source) as store:
        view = store.read_view(str(source), "", "").value
        assert view is not None and view.info["signature"] == loaded["signature"] != "an older one"


def test_a_cached_read_is_served_from_the_view(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    options = v4_options(tmp_path)
    run_load(source, tmp_path, options)
    output = tmp_path / "cached"
    output.mkdir()
    events: list[dict[str, Any]] = []
    read_cached(str(source), str(output), events.append, options)  # type: ignore[arg-type]
    shots = [event for event in events if event["kind"] == "shot"]
    assert sorted(event["shot"] for event in shots) == [1, 2] and first(events, "loaded")["disk_cached"]
    assert np.array_equal(np.load(shots[0]["artifact"]), np.array([[shots[0]["shot"] + 0.0, 2, 3],
                                                                   [shots[0]["shot"] + 0.1, 2, 3]]))


def test_a_listing_without_a_layers_files_makes_it_the_only_copy(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    options = v4_options(tmp_path)
    run_load(source, tmp_path, options)
    write_shot(source, 3)  # (So a load still has a file.)
    (source / "d_txy_forc1.txt").unlink()
    run_load(source, tmp_path, options, allow_missing=True)
    with opened(options, source) as store:
        assert (store.txy_layers(str(source)).value or {})["matlab"].gone_at is not None


def test_lives_save_writes_only_what_its_layers_lack(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    options = v4_options(tmp_path)
    loaded = first(run_load(source, tmp_path, options), "loaded")
    held_dir = tmp_path / "held"
    held_dir.mkdir()
    for shot in (1, 2):
        np.save(held_dir / f"{shot}.npy", np.array([[shot + 0.0, 2, 3], [shot + 0.1, 2, 3]]), allow_pickle=False)
    sent: list[dict[str, Any]] = []
    save_held(str(source), sent.append, options, loaded["fingerprint"], [], str(held_dir))  # type: ignore[arg-type]
    assert first(sent, "cache_saved") and segments(options, source) == [(1, 2)]  # (Both kept already.)
    write_shot(source, 3)
    info = (source / "d_txy_forc3.txt").stat()
    np.save(held_dir / "3.npy", np.array([[3.0, 2, 3], [3.1, 2, 3]]), allow_pickle=False)
    sent.clear()
    held = [*loaded["fingerprint"], [3, info.st_size, info.st_mtime_ns]]
    save_held(str(source), sent.append, options, held, [], str(held_dir))  # type: ignore[arg-type]
    assert first(sent, "cache_saved") and segments(options, source) == [(1, 2), (2, 1)]


def test_a_cached_read_follows_its_source_and_without_one_the_last_used_view(tmp_path: Path) -> None:
    """The ``cached`` request carries the tab's TXY source (FolderCache, stage 2): its view is read. An older
    request without one reads the folder's view used last."""
    source = data_folder(tmp_path)
    options = v4_options(tmp_path)
    run_load(source, tmp_path, options)  # (The priority modes' view, "".)
    run_load(source, tmp_path, options, txy={"source": "matlab-only"})
    with opened(options, source) as store:
        assert sorted(view[0] for view in store.folder_views(str(source))) == ["", "matlab-only"]
        key = store._path_key(str(source))
        with store.transaction():  # (The priority view used last.)
            store._conn.execute("UPDATE txy_views SET last_used = 10 WHERE path = ? AND source = 'matlab-only'", (key,))

    def read(txy: dict[str, Any] | None) -> dict[str, Any]:
        output = tmp_path / f"cached-{time.monotonic_ns()}"
        output.mkdir()
        events: list[dict[str, Any]] = []
        read_cached(str(source), str(output), events.append, options, txy=txy)  # type: ignore[arg-type]
        return first(events, "loaded")
    assert read({"source": "matlab-only"})["txy"]["source"] == "matlab-only"
    assert read(None)["txy"]["source"] != "matlab-only"


def test_folder_cache_sends_the_tabs_source_with_a_cached_read(monkeypatch: Any, tmp_path: Path) -> None:
    from test_raw_fill import frozen
    service, cache = frozen(monkeypatch)
    try:
        assert cache.submit("tab", 0, str(tmp_path), "cached", {"cache": {}})
        request = next(item for item in service.pending if item.operation == "cached")
        assert request.payload["txy"]["source"] == cache.tab_source()
    finally:
        service.shutdown()


def test_a_plots_own_choice_is_cached_quietly_in_store_v4(tmp_path: Path) -> None:
    """Q19.3: a plot's TXY choice (a ``no_cache`` request) is cached under its own view in store-v4, sends none of
    the tab's cache events and never waits for an answer; the folder's Don't cache flag still keeps it RAM only."""
    source = data_folder(tmp_path)
    options = v4_options(tmp_path)
    choice = {"source": "matlab-only"}
    events = run_load(source, tmp_path, options, no_cache=True, txy=choice)
    loaded = first(events, "loaded")
    assert not any(event["kind"] in ("cache_saved", "disk_cached", "cache_full", "cache_approval") for event in events)
    assert "disk_cached" not in loaded and loaded["disk_cache_pending"] is False
    with opened(options, source) as store:
        assert store.read_view(str(source), "matlab-only", "").found and store.read_view(str(source), "", "").missing
    again = first(run_load(source, tmp_path, options, no_cache=True, txy=choice), "loaded")
    assert again["source"] == "disk" and again["load_counts"]["read"] == 0  # (From its layers now.)
    write_shot(source, 3)
    over = run_load(source, tmp_path, {**options, "budget": 1, "budget_set_at": time.time()}, no_cache=True, txy=choice)
    with opened(options, source) as store:
        assert not store._conn.execute("SELECT 1 FROM pending_saves").fetchone()  # (Never asks.)
        assert 3 not in (store.txy_layers(str(source)).value or {})["matlab"].entries
    assert not any(event["kind"] == "cache_full" for event in over)
    other = data_folder(tmp_path / "other")
    with opened(options, other) as store:
        store.set_prefs(str(other), True, False, time.time())
    run_load(other, tmp_path, options, no_cache=True, txy=choice)
    with opened(options, other) as store:
        assert store.txy_layers(str(other)).value == {} and store.read_view(str(other), "matlab-only", "").missing


def test_a_plots_own_choice_stays_ram_only_in_store_v3(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    options = {"directory": str(tmp_path / "caches" / "store-v3")}
    run_load(source, tmp_path, options, no_cache=True, txy={"source": "matlab-only"})
    with opened(options, source) as store:
        assert store.read_dataset_row(str(source)).missing


# The folder's own TXY source (Q45.2, step 3c)

def test_a_tab_load_follows_the_folders_own_source_and_says_so(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    options = v4_options(tmp_path)
    with opened(options, source) as store:
        store.set_txy_source_pref(str(source), "matlab-only", "", time.time())
    events = run_load(source, tmp_path, options)  # (The tab's: no choice of its own.)
    assert first(events, "folder_choices")["choices"]["source"] == "matlab-only"
    assert first(events, "loaded")["txy"]["source"] == "matlab-only"
    with opened(options, source) as store:
        assert store.read_view(str(source), "matlab-only", "").found and store.read_view(str(source), "", "").missing
    plot = run_load(source, tmp_path, options, no_cache=True, txy={"source": "matlab-priority", "tab": False})
    assert first(plot, "loaded")["txy"]["source"] == "matlab-priority"  # (A plot's choice is its own.)


def test_setting_a_folders_choice_tells_the_app(tmp_path: Path) -> None:
    from helab.io_ops.admin import cache_admin
    source = data_folder(tmp_path)
    options = v4_options(tmp_path)
    with opened(options, source):
        pass  # (The folder's data root, recorded as a load would.)
    events: list[Any] = []
    cache_admin(options, "folder_choice", events.append, path=str(source), source="helab-only", tag="m19v1",
                set_at=time.time())
    assert first(events, "folder_choices")["choices"]["tag"] == "m19v1"


def test_folder_cache_applies_a_folders_own_source_to_the_tab_only(monkeypatch: Any, tmp_path: Path) -> None:
    from helab.utils import txy_sources
    from test_raw_fill import frozen
    service, cache = frozen(monkeypatch)
    try:
        path = str(tmp_path)
        cache.remember_choices(path, {"policy": "", "source": "helab-only", "tag": "m19v1", "source_set_at": 2.0})
        tab = cache.with_txy(path, {})["txy"]
        assert tab["source"] == "helab-only" and tab["profile_tag"] == "m19v1" and tab["profile_hash"]
        plot = cache.with_txy(path, {"txy": {"source": "matlab-only"}})["txy"]
        assert plot["source"] == "matlab-only"  # (A plot's choice stays its own.)
        cache.remember_choices(path, {"source": "matlab-only", "source_set_at": 1.0})  # (Older: ignored.)
        assert cache.with_txy(path, {})["txy"]["source"] == "helab-only"
        assert txy_sources.with_choices({"tab": True}, {"source": "", "tag": "x"}, lambda tag: None) == {"tab": True}
    finally:
        service.shutdown()


# Seeds: store-v4's own datasets (Q45.4) and store-v3's under Keep (Q45.5), step 3d

def tree(folder: Path) -> dict[str, bytes]:
    return {str(item.relative_to(folder)): item.read_bytes() for item in sorted(folder.rglob("*"))
            if item.is_file() and not item.name.endswith(("-wal", "-shm"))}


def test_store_v3s_dataset_seeds_the_layers_on_use_and_stays_as_it_was(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    v3 = {"directory": str(tmp_path / "caches" / "store-v3")}
    run_load(source, tmp_path, v3)
    before = tree(tmp_path / "caches" / "store-v3")
    options = v4_options(tmp_path)  # (Beside it; not answered yet: kept, Q22.3.)
    loaded = first(run_load(source, tmp_path, options), "loaded")
    assert loaded["load_counts"]["read"] == 0 and loaded["load_counts"]["reused_disk"] == 2
    with opened(options, source) as store:
        assert sorted((store.txy_layers(str(source)).value or {})["matlab"].entries) == [1, 2]
        assert store.read_dataset_row(str(source)).missing
    again = first(run_load(source, tmp_path, options), "loaded")
    assert again["cached"] and again["source"] == "disk"  # (The layers now.)
    assert tree(tmp_path / "caches" / "store-v3") == before


def test_store_v4s_own_dataset_seeds_the_layers(tmp_path: Path, monkeypatch: Any) -> None:
    from helab.io_ops import txy_cache
    source = data_folder(tmp_path)
    options = v4_options(tmp_path)
    with monkeypatch.context() as patch:  # (As stage 1 saved it: a dataset in store-v4.)
        patch.setattr(txy_cache, "layered", lambda store: False)
        run_load(source, tmp_path, options)
    with opened(options, source) as store:
        assert store.read_dataset_row(str(source)).found and store.txy_layers(str(source)).value == {}
    loaded = first(run_load(source, tmp_path, options), "loaded")
    assert loaded["load_counts"]["read"] == 0 and not loaded["cached"]
    with opened(options, source) as store:
        assert sorted((store.txy_layers(str(source)).value or {})["matlab"].entries) == [1, 2]


def test_a_store_v3_dataset_store_v4_removed_is_never_read_through(tmp_path: Path) -> None:
    source = data_folder(tmp_path)
    run_load(source, tmp_path, {"directory": str(tmp_path / "caches" / "store-v3")})
    options = v4_options(tmp_path)
    with opened(options, source) as store:
        store.remove(("datasets",), [str(source)])  # (The user cleared the folder's data in store-v4.)
    loaded = first(run_load(source, tmp_path, options), "loaded")
    assert loaded["load_counts"]["read"] == 2  # (From the files, not store-v3.)


# The loading order's second step: from the raw layer (step 3e)

@pytest.mark.parametrize(("backend", "runs"), [(None, "numpy"), ("numpy", "numpy"), ("reference", "reference"),
                                              ("numba", "numpy"), ("no-such-backend", "numpy")])
def test_a_helab_shot_comes_from_the_raw_layer_equal_to_its_text(tmp_path: Path, monkeypatch: Any,
                                                                 backend: str | None, runs: str) -> None:
    """A conversion into the cache folder (store-v4) saved the raw layers; a load of HeLab's TXY then makes the
    shots from them without reading the TXY text, on Settings' backend (A47.6: the app's, numpy, when it can't
    run here or is numba), and the data is the text's exactly."""
    import pandas as pd
    from helab.convert import reconstruct as reconstruct_module
    from helab.convert.profile import MATLAB_2019
    from helab.io_ops import infra
    from helab.io_ops.convert import convert_folder
    from test_convert_helab import raw_bytes, write_raw
    source = tmp_path / "data" / "run"
    source.mkdir(parents=True)
    for shot in (1, 2):
        write_raw(source, shot, raw_bytes(*(10_000 * k for k in range(1, shot + 2))))
    caches = tmp_path / "caches"
    options = v4_options(tmp_path)
    request: dict[str, Any] = {"path": str(source), "profile": MATLAB_2019.to_dict(), "temps": str(tmp_path / "temps"),
                               "seen": None, "destination": "cache", "workers": 1, "cache": options}
    convert_folder(str(source), request, lambda event: None)  # type: ignore[arg-type]
    with opened(options, source) as store:
        assert sorted(store.raw_rows(str(source)).value or {}) == [1, 2]
    texts = sorted(caches.rglob("d_txy_helab_*.txt"))
    assert len(texts) == 2
    expected = {int(path.stem.rsplit("_", 1)[1]): np.asarray(pd.read_csv(path, names=["t", "x", "y"]), dtype=float)
                for path in texts}
    read = infra._read_txy_file

    def refuse_helab(filename: str, reason: str) -> Any:
        if "d_txy_helab_" in os.path.basename(filename):
            raise AssertionError(f"read HeLab's TXY text {filename}")
        return read(filename, reason)
    monkeypatch.setattr(infra, "_read_txy_file", refuse_helab)
    ran: list[str] = []
    real = reconstruct_module.reconstruct

    def spy(pulses: Any, profile: Any, backend: str = reconstruct_module.DEFAULT_BACKEND) -> Any:
        ran.append(backend)
        return real(pulses, profile, backend)
    monkeypatch.setattr(reconstruct_module, "reconstruct", spy)
    txy: dict[str, Any] = {"source": "helab-only", "profile_hash": MATLAB_2019.content_hash(), "profile_tag": "m19v1",
                           "cache_base": str(caches), "temps": str(tmp_path / "temps")}
    if backend is not None:
        txy["backend"] = backend
    events = run_load(source, tmp_path, options, txy=txy)
    assert ran == [runs, runs]
    shots = {event["shot"]: np.load(event["artifact"]) for event in events if event["kind"] == "shot"}
    assert sorted(shots) == [1, 2] and first(events, "loaded")["problematic"] == []
    assert all(np.array_equal(shots[shot], expected[shot]) for shot in shots)
    with opened(options, source) as store:  # (Saved into the HeLab layer, keyed by the raw files.)
        layer = (store.txy_layers(str(source)).value or {})["helab:" + MATLAB_2019.content_hash()]
        assert {entry.kind for entry in layer.entries.values()} == {"raw"}


# Live's segments and compaction (Q45.7, step 4)

def test_lives_autosaves_append_a_segment_each_and_compact_when_they_pile_up(tmp_path: Path) -> None:
    """Each Live save writes one segment of its new shots; once a layer has more than eight, the save that
    makes it so rewrites it as one (it fits here), and the data reads back the same."""
    from helab.utils.cache_store import COMPACT_SEGMENTS
    source = data_folder(tmp_path, range(1, 2))
    options = v4_options(tmp_path)
    held = [list(entry) for entry in first(run_load(source, tmp_path, options), "loaded")["fingerprint"]]
    held_dir = tmp_path / "held"
    held_dir.mkdir()
    np.save(held_dir / "1.npy", np.array([[1.0, 2, 3], [1.1, 2, 3]]), allow_pickle=False)
    counts: list[int] = []
    for shot in range(2, COMPACT_SEGMENTS + 3):  # (One new shot per autosave.)
        write_shot(source, shot)
        np.save(held_dir / f"{shot}.npy", np.array([[shot + 0.0, 2, 3], [shot + 0.1, 2, 3]]), allow_pickle=False)
        info = (source / f"d_txy_forc{shot}.txt").stat()
        held.append([shot, info.st_size, info.st_mtime_ns])
        sent: list[dict[str, Any]] = []
        save_held(str(source), sent.append, options, held, [], str(held_dir))  # type: ignore[arg-type]
        assert first(sent, "cache_saved")
        counts.append(len(segments(options, source)))
    # (A segment per save, up to eight; the save that makes nine compacts them into one; the next appends.)
    assert counts == [*range(2, COMPACT_SEGMENTS + 1), 1, 2]
    assert [count for _, count in segments(options, source)] == [COMPACT_SEGMENTS + 1, 1]
    with opened(options, source) as store:
        data = store.read_txy_shots(str(source), "matlab").value or {}
    assert sorted(data) == list(range(1, COMPACT_SEGMENTS + 3)) and np.array_equal(data[5], [[5.0, 2, 3], [5.1, 2, 3]])


# PR #11's review (C-1): a view's shots are its layer entries' as it saved them

def test_a_view_leaves_out_a_shot_another_views_save_replaced_in_the_layer(tmp_path: Path) -> None:
    """Two views share the MATLAB layer. Shot 2's TXY changes and the priority view's load saves it again, which
    replaces the layer's entry; the External-only view, saved before, no longer has its data: a cached read of
    it leaves shot 2 out rather than sending the new arrays under the old fingerprint."""
    source = data_folder(tmp_path)
    options = v4_options(tmp_path)
    old = first(run_load(source, tmp_path, options, txy={"source": "matlab-only"}), "loaded")
    old_print = {int(entry[0]): list(entry) for entry in old["fingerprint"]}
    write_shot(source, 2, rows=5)  # (Its TXY rewritten: another size and date.)
    later = time.time() - 300
    os.utime(source / "d_txy_forc2.txt", (later, later))
    assert first(run_load(source, tmp_path, options), "loaded")["load_counts"]["read"] >= 1  # (The priority view.)
    with opened(options, source) as store:
        entry = (store.txy_layers(str(source)).value or {})["matlab"].entries[2]
        assert [entry.size, entry.mtime_ns] != old_print[2][1:]  # (The layer holds the new shot 2.)
    output = tmp_path / "cached"
    output.mkdir()
    events: list[dict[str, Any]] = []
    read_cached(str(source), str(output), events.append, options, txy={"source": "matlab-only"})  # type: ignore[arg-type]
    sent = {event["shot"]: event for event in events if event["kind"] == "shot"}
    assert sorted(sent) == [1] and first(events, "loaded")["failed_files"] == 1
    assert sent[1]["fingerprint"] == old_print[1] and len(np.load(sent[1]["artifact"])) == 2


def test_a_view_saved_before_entry_keys_serves_its_matlab_shots(tmp_path: Path) -> None:
    """A view an earlier build saved (five items a shot, no entry key): a MATLAB shot's key is its TXY file's
    fingerprint, so it is served as before; the next save gives the view its keys."""
    source = data_folder(tmp_path)
    options = v4_options(tmp_path)
    run_load(source, tmp_path, options)
    with opened(options, source) as store:
        key = store._path_key(str(source))
        with store.transaction():
            (text,) = store._conn.execute("SELECT fingerprint FROM txy_views WHERE path = ?", (key,)).fetchone()
            assert all(len(item) == 6 for item in json.loads(text))
            store._conn.execute("UPDATE txy_views SET fingerprint = ? WHERE path = ?",
                                (json.dumps([item[:5] for item in json.loads(text)]), key))
    output = tmp_path / "cached"
    output.mkdir()
    events: list[dict[str, Any]] = []
    read_cached(str(source), str(output), events.append, options)  # type: ignore[arg-type]
    assert sorted(event["shot"] for event in events if event["kind"] == "shot") == [1, 2]
    again = first(run_load(source, tmp_path, options), "loaded")
    assert again["cached"] and again["load_counts"]["read"] == 0
    write_shot(source, 3)
    run_load(source, tmp_path, options)
    with opened(options, source) as store:
        view = store.read_view(str(source), "", "").value
        assert view is not None and all(len(item) == 6 for item in view.fingerprint)


# PR #11's review (C-2): a listing checks each layer against its own source

def test_helabs_txy_doesnt_make_a_gone_matlab_txys_layer_recoverable(tmp_path: Path) -> None:
    """A MATLAB TXY goes while HeLab's TXY of that shot stays. A load of HeLab's TXY lists the folder: the MATLAB
    layer's shot has no source of its own left, so the layer is the only copy (``gone_at``), whatever HeLab's
    conversion of that shot; ordinary removal (a purge by age) then leaves it."""
    from helab.convert.profile import MATLAB_2019
    from helab.io_ops.convert import convert_folder
    from test_convert_helab import raw_bytes, write_raw
    source = tmp_path / "data" / "run"
    source.mkdir(parents=True)
    old = time.time() - 600
    for shot in (1, 2):
        write_raw(source, shot, raw_bytes(*(10_000 * k for k in range(1, shot + 2))), mtime=old)
        (source / f"d_txy_forc{shot}.txt").write_text(f"{shot}.0,2,3\n{shot}.1,2,3\n")
        os.utime(source / f"d_txy_forc{shot}.txt", (old, old))
    caches = tmp_path / "caches"
    options = v4_options(tmp_path)
    request: dict[str, Any] = {"path": str(source), "profile": MATLAB_2019.to_dict(), "temps": str(tmp_path / "temps"),
                               "seen": None, "destination": "cache", "workers": 1, "cache": options}
    convert_folder(str(source), request, lambda event: None)  # type: ignore[arg-type]
    run_load(source, tmp_path, options, txy={"source": "matlab-only"})  # (The MATLAB layer.)
    (source / "d_txy_forc1.txt").unlink()
    helab = {"source": "helab-only", "profile_hash": MATLAB_2019.content_hash(), "profile_tag": "m19v1",
             "cache_base": str(caches), "temps": str(tmp_path / "temps")}
    assert first(run_load(source, tmp_path, options, txy=helab), "loaded")["files"] == 2
    with opened(options, source) as store:
        layers = store.txy_layers(str(source)).value or {}
        assert layers["matlab"].gone_at is not None  # (Shot 1's MATLAB TXY is gone: the only copy.)
        assert layers["helab:" + MATLAB_2019.content_hash()].gone_at is None  # (Its raw files are there.)
        removal = store.purge_cached(time.time() + 3600, ("txy",))
        left = store.txy_layers(str(source)).value or {}
        assert "matlab" in left and (str(source), "matlab") not in removal.txy_seen  # (The only copy stays.)


# PR #11's review (C-3): the profile's completion check before converting cached raw pulses

def test_a_raw_layer_not_starting_on_the_trigger_is_rejected_as_its_file_is(tmp_path: Path) -> None:
    """``raw_fill`` caches a raw file whose first line isn't on a trigger channel (it has no profile to check
    with). A HeLab load converting on read rejects that file as damaged (``raw.not_done``); from the raw layer it
    must too, not make an apparently valid shot with the wrong first row as time zero and keep it in a layer."""
    from helab.convert.profile import MATLAB_2019
    from helab.io_ops.raw_fill import raw_fill
    from test_convert_helab import raw_bytes, write_raw
    options = v4_options(tmp_path)
    txy = {"source": "helab-only", "profile_hash": MATLAB_2019.content_hash(), "profile_tag": "m19v1",
           "cache_base": str(tmp_path / "caches"), "temps": str(tmp_path / "temps"),
           "profile_def": MATLAB_2019.to_dict()}
    helab = "helab:" + MATLAB_2019.content_hash()
    results: dict[str, dict[str, Any]] = {}
    for name in ("from-file", "from-layer"):
        source = tmp_path / "data" / name
        source.mkdir(parents=True)
        write_raw(source, 1, raw_bytes(10_000, 20_000))
        write_raw(source, 2, raw_bytes(10_000, 20_000, trigger=0))  # (Its first line: channel 0, a hit's.)
        if name == "from-layer":
            sent: list[dict[str, Any]] = []
            raw_fill(str(source), options, sent.append)  # type: ignore[arg-type]
            assert first(sent, "raw_fill_done")["saved"] == 2  # (Both cached: no profile to check with.)
        events = run_load(source, tmp_path, options, txy=txy)
        results[name] = first(events, "loaded")
        with opened(options, source) as store:
            layer = (store.txy_layers(str(source)).value or {}).get(helab)
            assert layer is not None and sorted(layer.entries) == [1], name  # (Shot 2 isn't kept.)
    assert results["from-file"]["problematic"] == [2]
    assert results["from-layer"]["problematic"] == results["from-file"]["problematic"]
    assert results["from-layer"]["files"] == results["from-file"]["files"]


def test_old_helab_view_is_read_again_once_then_keyed(tmp_path: Path) -> None:
    """PR-1 (the landing review of C-1): a HeLab view an earlier build saved (five items a shot) can't say which
    layer entries it saved. It serves no cached read; its next load reads its HeLab shots again ("Cached dataset
    invalid"), once, and saves the view with keys; the load after it is served from the layers."""
    from helab.convert.profile import MATLAB_2019
    from helab.io_ops.txy_cache import view_key
    from test_convert_helab import raw_bytes, write_raw
    source = tmp_path / "data" / "run"
    source.mkdir(parents=True)
    for shot in (1, 2):
        write_raw(source, shot, raw_bytes(*(10_000 * k for k in range(1, shot + 2))))
    options = v4_options(tmp_path)
    txy = {"source": "helab-only", "profile_hash": MATLAB_2019.content_hash(), "profile_tag": "m19v1",
           "cache_base": str(tmp_path / "caches"), "temps": str(tmp_path / "temps"),
           "profile_def": MATLAB_2019.to_dict()}
    assert first(run_load(source, tmp_path, options, txy=txy), "loaded")["load_counts"]["converted"] == 2
    with opened(options, source) as store:
        key = store._path_key(str(source))
        with store.transaction():
            (text,) = store._conn.execute("SELECT fingerprint FROM txy_views WHERE path = ?", (key,)).fetchone()
            store._conn.execute("UPDATE txy_views SET fingerprint = ? WHERE path = ?",
                                (json.dumps([item[:5] for item in json.loads(text)]), key))
    output = tmp_path / "cached"
    output.mkdir()
    with pytest.raises(ValueError, match="No cached data for this folder"):
        read_cached(str(source), str(output), lambda event: None, options, txy=txy)
    again = first(run_load(source, tmp_path, options, txy=txy), "loaded")
    assert not again["cached"] and again["load_counts"]["read"] == 2
    assert again["cache_reason"] == "Cached dataset invalid"
    with opened(options, source) as store:
        view = store.read_view(str(source), *view_key("helab-only", txy)).value
        assert view is not None and all(len(item) == 6 for item in view.fingerprint)
    last = first(run_load(source, tmp_path, options, txy=txy), "loaded")
    assert last["cached"] and last["load_counts"]["read"] == 0
