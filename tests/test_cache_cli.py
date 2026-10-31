"""``helab cache dump|export`` (Tony's export item, after caching v2's step 5): read only; a raw layer's
columns to npz, mat and csv; a folder's raw layers from store-v4 through a read-only connection that
leaves the store's files as they were; never replaces a file or writes into a store; starts no Qt.
And the format page's sample reader without HeLab reads what HeLab writes."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import zlib
from typing import Any

import numpy as np
import pytest

from helab import cache_cli
from helab.convert import raw_layer
from helab.io_ops.raw_fill import raw_fill
from helab.utils import hlb

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "tests" / "data" / "convert" / "cases" / "basic" / "d1.txt"


def layer_file(tmp_path: Path, data: bytes | None = None) -> Path:
    path = tmp_path / "layers" / "d1.hlb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw_layer.to_hlb(raw_layer.encode(CASE.read_bytes() if data is None else data),
                                      meta={"name": "d1.txt"}))
    return path


def expected() -> dict[str, Any]:
    return raw_layer.columns(raw_layer.encode(CASE.read_bytes()))


def test_dump_prints_the_header_and_refuses_a_damaged_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = layer_file(tmp_path)
    assert cache_cli.main(["dump", str(path)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["kind"] == "raw" and shown["format"] == hlb.FORMAT and shown["meta"]["encoding"] == raw_layer.COMPACT
    assert [entry["name"] for entry in shown["arrays"]] == ["channel", "time"]
    assert all(entry["compressed_bytes"] > 0 and "chunks" not in entry for entry in shown["arrays"])
    damaged = tmp_path / "damaged.hlb"
    damaged.write_bytes(path.read_bytes()[:-5])
    assert cache_cli.main(["dump", str(damaged)]) == 2
    assert "damaged.hlb" in capsys.readouterr().err


@pytest.mark.parametrize("to", ["npz", "mat", "csv"])
def test_a_layer_exports_its_columns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, to: str) -> None:
    path = layer_file(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cache_cli.main(["export", str(path), "--to", to]) == 0
    out = tmp_path / f"d1.{to}"  # (Named by the raw file, in the current folder: never beside the .hlb.)
    columns = expected()
    if to == "npz":
        with np.load(out) as found:
            for name in ("channel", "time_bins", "time_s"):
                assert np.array_equal(found[name], columns[name]) and found[name].dtype == columns[name].dtype
            assert json.loads(str(found["header"]))["kind"] == "raw"
    elif to == "mat":
        from scipy.io import loadmat
        found = loadmat(out)
        assert np.array_equal(found["time_bins"].ravel(), columns["time_bins"])
        assert np.array_equal(found["channel"].ravel(), columns["channel"])
        assert np.allclose(found["time_s"].ravel(), columns["time_s"], rtol=0, atol=0)
        assert json.loads(str(found["header"][0]))["meta"]["name"] == "d1.txt"
    else:
        with open(out, newline="", encoding="ascii") as handle:
            rows = list(csv.reader(handle))
        assert rows[0] == ["channel", "time_bins", "time_s"] and len(rows) == len(columns["channel"]) + 1
        assert (int(rows[1][0]), int(rows[1][1]), float(rows[1][2])) == (
            int(columns["channel"][0]), int(columns["time_bins"][0]), float(columns["time_s"][0]))
    assert columns["time_s"][0] == columns["time_bins"][0] * 25e-12
    assert cache_cli.main(["export", str(path), "--to", to]) == 2  # (Never replaced without --force.)
    assert cache_cli.main(["export", str(path), "--to", to, "--force"]) == 0


def test_an_export_is_never_written_into_a_store(tmp_path: Path) -> None:
    path = layer_file(tmp_path)
    store = tmp_path / "caches" / "store-v4"
    (store / "raw").mkdir(parents=True)
    (store / "records.sqlite").write_bytes(b"")
    assert cache_cli.main(["export", str(path), "--out", str(store / "raw" / "x.npz")]) == 2
    assert not (store / "raw" / "x.npz").exists()
    assert cache_cli.main(["export"]) == 2 and cache_cli.main(["export", str(path), "--folder", "x"]) == 2


def files(folder: Path) -> dict[str, str]:
    return {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob("*")) if path.is_file() and not path.name.endswith(("-wal", "-shm"))}


def test_a_folders_raw_layers_export_from_store_v4_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                             capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "data" / "run"
    source.mkdir(parents=True)
    for shot in (1, 2):
        (source / f"d{shot}.txt").write_bytes(CASE.read_bytes())
        os.utime(source / f"d{shot}.txt", (1_700_000_000, 1_700_000_000))
    caches = tmp_path / "caches"
    sent: list[Any] = []
    raw_fill(str(source), {"directory": str(caches / "store-v4")}, sent.append)
    assert sent[-1]["saved"] == 2
    before = files(caches / "store-v4")
    out = tmp_path / "exported"
    assert cache_cli.main(["export", "--folder", str(source), "--cache", str(caches), "--out", str(out)]) == 0
    assert sorted(os.listdir(out)) == ["d1.npz", "d2.npz"] and files(caches / "store-v4") == before
    with np.load(out / "d2.npz") as found:
        assert np.array_equal(found["time_bins"], expected()["time_bins"])
    assert cache_cli.folder_key(str(source)).startswith("root://") and cache_cli.folder_key(
        str(source)).endswith("/data/run")
    other = tmp_path / "data" / "empty"
    other.mkdir()
    assert cache_cli.main(["export", "--folder", str(other), "--cache", str(caches)]) == 1
    assert cache_cli.main(["export", "--folder", str(source), "--cache", str(tmp_path / "none")]) == 2
    assert "no store-v4" in capsys.readouterr().err


def test_helab_cache_starts_no_qt(tmp_path: Path) -> None:
    """``helab/main.py`` dispatches ``cache`` before anything starts the GUI: a dump imports no Qt at all."""
    path = layer_file(tmp_path)
    code = ("import runpy, sys\n"
            f"sys.argv = ['helab', 'cache', 'dump', {str(path)!r}]\n"
            "try:\n    runpy.run_module('helab', run_name='__main__')\n"
            "except SystemExit as done:\n    code = done.code\n"
            "print(code, any(name.startswith('PyQt6') for name in sys.modules), file=sys.stderr)\n")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=ROOT,
                          env=dict(os.environ))
    assert done.stderr.strip().splitlines()[-1] == "0 False", done.stderr
    assert json.loads(done.stdout)["kind"] == "raw"


def test_the_format_pages_reader_without_helab_reads_what_helab_writes(tmp_path: Path) -> None:
    """hlb-format.md's "Python, without HeLab" sample, as written there."""
    import blosc

    def read_hlb(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        data = open(path, "rb").read()
        if data[:8] != b"\x89HLB\r\n\x1a\n":
            raise ValueError("not a .hlb file")
        length, crc = struct.unpack_from("<II", data, 8)
        header_bytes = data[16:16 + length]
        if zlib.crc32(header_bytes) != crc:
            raise ValueError("header damaged")
        header = json.loads(header_bytes)
        base, arrays = 16 + length, {}
        for entry in header["arrays"]:
            pieces = []
            for chunk in entry["chunks"]:
                packed = data[base + chunk["offset"]:base + chunk["offset"] + chunk["length"]]
                if zlib.crc32(packed) != chunk["crc32"]:
                    raise ValueError(entry["name"] + ": chunk damaged")
                pieces.append(blosc.decompress(packed))
            arrays[entry["name"]] = np.frombuffer(b"".join(pieces), dtype=entry["dtype"]).reshape(entry["shape"])
        return header, arrays

    path = layer_file(tmp_path)
    header, arrays = read_hlb(path)
    assert header == hlb.read(path)[0]
    channel, bins = arrays["channel"], np.cumsum(arrays["time"])
    columns = expected()
    assert np.array_equal(channel, columns["channel"]) and np.array_equal(bins, columns["time_bins"])
