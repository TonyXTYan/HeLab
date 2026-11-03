"""Caching v2 stage 2, the step 3 review's fixes. S3-1: in store-v4 a folder's Clear data cache (``invalidate``)
and a purge of cached data by age take its TXY layers, views and seen raw layers too; only copies stay. S3-2: a
HeLab shot converted from the raw layer is converted before any file is announced, under the converter's ticker.
Temp stores only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

import pytest

from helab.io_ops.admin import cache_admin
from helab.utils import cache_store
from helab.utils.cache_store import CacheStore
from test_txy_loading import data_folder, first, opened, run_load, v4_options


def test_clear_data_cache_takes_a_folders_layers_and_views_in_store_v4(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """S3-1: the helper's ``invalidate`` (FolderExplorer.clear_data_cache) in store-v4: the folder's layers and
    views go, so the next load reads its files; an only copy (another folder's, its TXY gone) stays."""
    from test_helper_dispatch import send
    source = data_folder(tmp_path)
    options = v4_options(tmp_path)
    run_load(source, tmp_path, options)
    gone = data_folder(tmp_path / "other")
    run_load(gone, tmp_path, options)
    with opened(options, gone) as store:
        store.mark_txy_seen(str(gone), {"matlab": {}}, time.time() + 60)  # (Its TXY gone: the only copy.)
    for folder in (source, gone):
        events = send(monkeypatch, capsys, {"operation": "invalidate", "path": str(folder), "cache": options})
        assert any(event["kind"] == "removed" for event in events)
    with opened(options, source) as store:
        assert store.txy_layers(str(source)).value == {} and store.read_view(str(source), "", "").missing
    with opened(options, gone) as store:
        assert store.txy_layers(str(gone)).value  # (Only a question that names it may take it.)
    loaded = first(run_load(source, tmp_path, options), "loaded")
    assert loaded["load_counts"]["read"] == 2 and not loaded["cached"]


@pytest.mark.parametrize("what", ["txy", "raw", "all"])
def test_a_purge_by_age_takes_its_kind_only_and_never_only_copies(tmp_path: Path, what: str) -> None:
    """A47.4 (and S3-1, C2S2-2): each purge by age takes its own kind of old cached data, ``all`` every kind,
    only copies stay, and the question's estimate is what the purge frees."""
    from test_raw_fill import done, fill, write_raw
    source = data_folder(tmp_path)
    for shot in (1, 2):
        write_raw(source, shot)
    options = v4_options(tmp_path)
    run_load(source, tmp_path, options)
    assert done(fill(source, options))["saved"] == 2
    kept = data_folder(tmp_path / "other")
    run_load(kept, tmp_path, options)
    with opened(options, kept) as store:
        store.mark_txy_seen(str(kept), {"matlab": {}}, time.time() + 60)  # (Its TXY gone: the only copy.)
    cutoff = time.time() + 3600
    with opened(options, kept) as store:
        inventory = store.inventory()
        layers = store.txy_layers(str(source)).value
        raw = store.raw_rows(str(source)).value
        assert layers and raw
        layer_bytes = sum(row.bytes for row in layers.values())
    assert inventory["txy"]["only_copy_folders"] == 1
    kinds = cache_store.PURGE_KINDS if what == "all" else (what,)
    estimate = cache_store.purge_estimate(inventory, cutoff, datasets=True, kinds=kinds)
    assert estimate.get("txy_folders", 0) == (1 if "txy" in kinds else 0)
    assert estimate.get("raw_folders", 0) == (1 if "raw" in kinds else 0)
    if "txy" in kinds:
        assert estimate["txy_bytes"] == layer_bytes > 0
    events: list[Any] = []
    cache_admin(options, "purge", events.append, what=what, cutoff=cutoff)
    [result] = [event for event in events if event["kind"] == "admin_result"]
    assert result["bytes"] == estimate["bytes"] > 0
    removed = {kind for event in events if event["kind"] == "removed" for kind in event["kinds"]}
    assert ("txy" in removed) == ("txy" in kinds) and ("raw" in removed) == ("raw" in kinds)
    assert not any(event["kind"] == "removed" and not event["kinds"] for event in events)
    with opened(options, source) as store:
        assert (store.txy_layers(str(source)).value == {}) == ("txy" in kinds)
        assert (store.read_view(str(source), "", "").missing) == ("txy" in kinds)
        assert (store.raw_rows(str(source)).value == {}) == ("raw" in kinds)
    with opened(options, kept) as store:
        assert store.txy_layers(str(kept)).value  # (Only a question that names it may take it.)


def test_an_unknown_purge_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown purge"):
        cache_admin(v4_options(tmp_path), "purge", lambda event: None, what="everything", cutoff=time.time())
    with CacheStore(str(tmp_path / "caches" / "store-v4")) as store, pytest.raises(ValueError, match="kinds"):
        store.purge_cached(time.time(), ("results",))


def test_a_conversion_from_the_raw_layer_comes_before_any_file_and_keeps_heartbeats_going(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """S3-2: a slow decode (a large shot on a slow PC) isn't inside a file's 15 s window: no ``file_started``
    for the shot, and heartbeats go on meanwhile."""
    import threading
    from helab.convert import raw_layer
    from helab.convert.profile import MATLAB_2019
    from helab.io_ops.convert import convert_folder
    from helab.io_ops.infra import Heartbeat
    from test_convert_helab import raw_bytes, write_raw
    source = tmp_path / "data" / "run"
    source.mkdir(parents=True)
    write_raw(source, 1, raw_bytes(10_000, 20_000))
    options = v4_options(tmp_path)
    request: dict[str, Any] = {"path": str(source), "profile": MATLAB_2019.to_dict(), "temps": str(tmp_path / "temps"),
                               "seen": None, "destination": "cache", "workers": 1, "cache": options}
    convert_folder(str(source), request, lambda event: None)  # type: ignore[arg-type]
    monkeypatch.setattr(Heartbeat, "INTERVAL", 0.02)
    events: list[dict[str, Any]] = []
    beating = threading.Event()
    decode = raw_layer.decode

    def slow(layer: Any) -> Any:
        beating.wait(10)  # (Until heartbeats came: a long conversion.)
        return decode(layer)
    monkeypatch.setattr(raw_layer, "decode", slow)

    def collect(event: dict[str, Any]) -> None:
        events.append(event)
        if sum(item["kind"] == "heartbeat" for item in events) >= 3:
            beating.set()
    from helab.io_ops.loading import load
    output = tmp_path / "out"
    output.mkdir()
    txy = {"source": "helab-only", "profile_hash": MATLAB_2019.content_hash(), "profile_tag": "m19v1",
           "cache_base": str(tmp_path / "caches"), "temps": str(tmp_path / "temps")}
    load(str(source), str(output), collect, options, txy=txy)  # type: ignore[arg-type]
    assert beating.is_set() and first(events, "loaded")["files"] == 1
    assert not any(event["kind"] == "file_started" and "d_txy_helab_" in os.path.basename(event["filename"])
                   for event in events)
