"""Temporary regression probes for the branch review; private stores only."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from helab.convert import txy_layer
from helab.io_ops.txy_cache import Access
from helab.utils import hlb, txy_sources
from helab.utils.cache_store import CacheStore, TxyPart, TxyShot, ViewRecord


@pytest.mark.no_auto_data_root
def test_a_view_cannot_return_changed_layer_data_with_its_old_fingerprint(tmp_path: Path) -> None:
    path = "root://aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/run"
    original = np.array([[11.0, 2.0, 3.0]])
    replacement = np.array([[99.0, 2.0, 3.0]])
    with CacheStore(str(tmp_path / "store-v4")) as store:
        def save(source: str, values: Any, size: int, modified: int) -> None:
            file = store.write_txy_file(txy_layer.pack_segment({1: values}, layer="matlab"))
            part = TxyPart("matlab", file, (TxyShot(1, size, modified, "txy", 1),))
            view: ViewRecord = {"fingerprint": [[1, size, modified, "txy", "matlab"]],
                                "problematic": [], "info": {"signature": str(modified)}}
            store.save_txy(path, source, "", [part], view, store.start_txy_job(path))

        save(txy_sources.MATLAB_ONLY, original, 10, 100)
        save("", replacement, 20, 200)
        read = Access(store, txy_sources.MATLAB_ONLY, {}).full(path)
        if read.value is not None:
            row, loader = read.value
            data = loader()
            print("view fingerprint", row["fingerprint"], "data", data)
            assert data is None or 1 not in data or np.array_equal(data[1], original), (
                "old view fingerprint was attached to newer data from another view's layer")


def test_fractional_shot_ids_are_rejected_instead_of_silently_merged() -> None:
    packed = hlb.pack({"shots": np.array([1.1, 1.9], dtype="<f8"),
                       "offsets": np.array([0, 1, 2], dtype="<i8"),
                       "hits": np.array([[11., 2., 3.], [99., 2., 3.]], dtype="<f8"),
                       "problematic": np.array([0, 0], dtype="|u1")},
                      kind="txy", meta={"layer": "matlab", "precision": "g8"})
    with pytest.raises(hlb.HlbError):
        shots, _, _ = txy_layer.unpack_segment(packed)
        print("invalid shot IDs were accepted as", shots)


def test_a_helab_file_cannot_make_a_missing_matlab_file_recoverable(tmp_path: Path) -> None:
    import os
    from helab.convert.profile import MATLAB_2019
    from test_txy_loading import data_folder, opened, run_load, v4_options

    source = data_folder(tmp_path, range(1, 2))
    options = v4_options(tmp_path)
    run_load(source, tmp_path, options, txy={"source": "matlab-only"})
    (source / "d_txy_forc1.txt").unlink()
    own = source / "d_txy_helab_m19v1_1.txt"
    own.write_text("99,2,3\n")
    modified = (source / "d1.txt").stat().st_mtime + 20
    os.utime(own, (modified, modified))
    txy = {"source": "helab-priority", "profile_hash": MATLAB_2019.content_hash(),
           "profile_tag": "m19v1"}
    run_load(source, tmp_path, options, txy=txy)
    with opened(options, source) as store:
        before = store.txy_layers(str(source)).value or {}
        print("MATLAB original gone; gone_at is", before["matlab"].gone_at)
        store.trim(1)  # This path must keep only copies unless a plan names them.
        remaining = store.txy_layers(str(source)).value or {}
        assert "matlab" in remaining, "budget trim deleted the only MATLAB copy without naming it"


def test_replacing_a_root_drops_its_txy_source_override(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.utils.io_service import IORequest
    from test_root_change_flags import A, B, frozen

    root, run = str(tmp_path), str(tmp_path / "run")
    service, cache = frozen(monkeypatch)
    try:
        default = cache.tab_source()
        cache._root_seen(root, A, "old")
        cache.remember_choices(run, {"source": "matlab-only", "tag": "", "source_set_at": 10.0})
        service.resultReady.emit(IORequest("probe", 0, root, "list", {}, 60), {
            "kind": "root_changed", "path": root, "uuid": B, "location": "vol://test/new", "label": "new"})
        cache.remember_choices(run, {"policy": "", "source": "", "tag": "", "source_set_at": 0.0})
        actual = cache.with_txy(run, {})["txy"]["source"]
        print("new root's expected source", default, "actual source", actual)
        assert actual == default, "the new root inherited the old root's per-folder TXY override"
    finally:
        service.shutdown()


def test_segment_offset_bounds_are_checked_without_int64_overflow() -> None:
    limit = np.iinfo(np.int64)
    packed = hlb.pack({"shots": np.array([1, 2, 3, 4], dtype="<i8"),
                       "offsets": np.array([0, limit.max, limit.min, -1, 2], dtype="<i8"),
                       "hits": np.array([[11., 2., 3.], [99., 2., 3.]], dtype="<f8"),
                       "problematic": np.array([0, 0, 0, 0], dtype="|u1")},
                      kind="txy", meta={"layer": "matlab", "precision": "g8"})
    with pytest.raises(hlb.HlbError):
        shots, _, _ = txy_layer.unpack_segment(packed)
        print("invalid offsets produced", shots)
