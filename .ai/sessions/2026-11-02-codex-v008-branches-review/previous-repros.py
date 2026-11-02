"""Temporary regression probes for the v0.0.8 review; no production edits."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from helab import cache_cli
from helab.convert import raw_layer
from helab.io_ops.raw_fill import raw_fill
from helab.utils.cache_store import CacheStore


@pytest.mark.parametrize("folder", ["run 1", "run%20", "測定"])
def test_export_folder_uses_the_actual_store_key(tmp_path: Path, folder: str) -> None:
    source = tmp_path / folder
    source.mkdir()
    case = Path(__file__).parent / "data/convert/cases/basic/d1.txt"
    raw = source / "d1.txt"
    raw.write_bytes(case.read_bytes())
    os.utime(raw, (1_700_000_000, 1_700_000_000))
    caches = tmp_path / "caches"
    events: list[Any] = []
    raw_fill(str(source), {"directory": str(caches / "store-v4")}, events.append)
    assert events[-1]["saved"] == 1
    with CacheStore(str(caches / "store-v4")) as store:
        actual = store._conn.execute("SELECT path FROM raw_layers").fetchone()[0]
    print(f"stored key: {actual}; export key: {cache_cli.folder_key(str(source))}")
    assert cache_cli.main(["export", "--folder", str(source), "--cache", str(caches),
                           "--out", str(tmp_path / "exports")]) == 0


@pytest.mark.no_auto_data_root
def test_an_unreadable_kept_store_reports_an_error(tmp_path: Path) -> None:
    legacy = tmp_path / "store-v3"
    legacy.mkdir()
    (legacy / "records.sqlite").write_bytes(b"damaged database")
    with CacheStore(str(tmp_path / "store-v4")) as store:
        answer = store.read_record("histories", "root://example/run")
        print(f"legacy history: {answer}; inventory legacy: {store.measure_legacy()}")
        assert answer.failed, "unreadable legacy failure history must not be a cache miss"


@pytest.mark.parametrize("to", ["npz", "mat", "csv"])
def test_export_never_overwrites_a_file_created_after_its_check(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, to: str) -> None:
    out = tmp_path / "exports" / f"d1.{to}"
    mkdir = Path.mkdir
    original = b"data from another exporter"

    def another_export_finished(self: Path, *args: Any, **kwargs: Any) -> None:
        mkdir(self, *args, **kwargs)
        if self == out.parent:
            out.write_bytes(original)

    monkeypatch.setattr(Path, "mkdir", another_export_finished)
    layer = raw_layer.encode(b"5,1000\r\n1,2000\r\n")
    try:
        cache_cli._write(raw_layer.columns(layer), {}, out, to, False)
    except cache_cli.CliError:
        pass
    assert out.read_bytes() == original, "an output created after exists() was overwritten without --force"


@pytest.mark.parametrize("to", ["npz", "mat", "csv"])
def test_a_late_output_symlink_cannot_overwrite_the_store(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, to: str) -> None:
    store = tmp_path / "store-v4"
    store.mkdir()
    victim = store / "records.sqlite"
    original = b"user's existing cache database"
    victim.write_bytes(original)
    out = tmp_path / "exports" / f"d1.{to}"
    mkdir = Path.mkdir

    def attacker_swaps_output(self: Path, *args: Any, **kwargs: Any) -> None:
        mkdir(self, *args, **kwargs)
        if self == out.parent:
            out.symlink_to(victim)

    monkeypatch.setattr(Path, "mkdir", attacker_swaps_output)
    layer = raw_layer.encode(b"5,1000\r\n1,2000\r\n")
    try:
        cache_cli._write(raw_layer.columns(layer), {}, out, to, False)
    except cache_cli.CliError:
        pass
    assert victim.read_bytes() == original, "a late symlink bypassed the store and no-overwrite checks"
