"""``helab cache``: look into caching v2's ``.hlb`` files and export them, read only (Tony, 2026-10-31).

    helab cache dump FILE.hlb
    helab cache export FILE.hlb [--to npz|mat|csv] [--out PATH] [--bin-time SECONDS] [--force]
    helab cache export --folder FOLDER [--cache DIR] [--to …] [--out DIR] [--bin-time SECONDS] [--force]

``dump`` prints a file's header as JSON (each array's name, dtype, shape and compressed bytes instead of
its chunk list). ``export`` writes a raw layer's columns (``raw_layer.columns``: ``channel``, ``time_bins``
absolute TDC bins, ``time_s``) and its header (JSON text) to ``.npz`` (NumPy), ``.mat`` (``scipy.io.savemat``,
for MATLAB) or ``.csv`` (one row per pulse). ``--folder`` exports every raw layer store-v4 holds for a
source folder (found by its nearest ``.helab-root``, as the app keys it) as ``d<N>.<ext>``.

It never writes into a store or a source folder, and never replaces a file without ``--force``: a file's
export goes to the current folder unless ``--out`` says where, a folder's to ``./helab-export-<name>/``;
an ``--out`` inside a store folder is refused. A store is read through a read-only SQLite connection that
never checkpoints, so it works beside a running HeLab and changes nothing. The format:
``helab.utils.hlb`` and the format page.

Exit codes: 0 done, 1 nothing to export, 2 a file damaged or of a newer format, or a usage error.
Imports no Qt widgets (``helab/main.py`` dispatches it before anything starts the GUI).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import sqlite3
import sys
from typing import Any, Sequence

FORMATS = ("npz", "mat", "csv")


class CliError(Exception):
    """A usage problem or a file that can't be read: exit code 2, the message on stderr."""


def _summary(header: dict[str, Any]) -> dict[str, Any]:
    arrays = [{"name": entry.get("name"), "dtype": entry.get("dtype"), "shape": entry.get("shape"),
               "compressed_bytes": sum(int(chunk.get("length", 0)) for chunk in entry.get("chunks") or ()),
               "codec": entry.get("codec")} for entry in header.get("arrays") or ()]
    return {**{key: value for key, value in header.items() if key != "arrays"}, "arrays": arrays}


def _inside_store(path: pathlib.Path) -> bool:
    for parent in (path, *path.parents):
        if parent.name.startswith("store-v") and (parent / "records.sqlite").exists():
            return True
    return False


def _write(columns: dict[str, Any], header: dict[str, Any], out: pathlib.Path, to: str, force: bool) -> None:
    import numpy as np
    if out.exists() and not force:
        raise CliError(f"{out} exists (--force replaces it)")
    if _inside_store(out.resolve()):
        raise CliError(f"{out} is inside a disk cache store: never written to")
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(header, sort_keys=True)
    if to == "npz":
        with open(out, "wb") as handle:
            np.savez_compressed(handle, header=np.array(text), **columns)
    elif to == "mat":
        from scipy.io import savemat
        savemat(str(out), {**columns, "header": text}, do_compression=True)
    else:
        with open(out, "w", newline="", encoding="ascii") as handle:
            writer = csv.writer(handle)
            writer.writerow(["channel", "time_bins", "time_s"])
            for channel, bins, seconds in zip(columns["channel"].tolist(), columns["time_bins"].tolist(),
                                              columns["time_s"].tolist()):
                writer.writerow([channel, bins, repr(seconds)])


def _layer(data: bytes, where: str) -> tuple[Any, dict[str, Any]]:
    from helab.convert import raw_layer
    from helab.utils import hlb
    try:
        return raw_layer.from_hlb(data)
    except hlb.HlbError as exc:
        raise CliError(f"{where}: {exc}") from None


def _export_file(path: pathlib.Path, args: argparse.Namespace) -> int:
    from helab.convert import raw_layer
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CliError(f"{path}: {exc}") from None
    layer, header = _layer(data, str(path))
    stem = pathlib.Path(str(header.get("meta", {}).get("name") or path.stem)).stem
    out = pathlib.Path(args.out) if args.out else pathlib.Path.cwd() / f"{stem}.{args.to}"
    _write(raw_layer.columns(layer, args.bin_time), header, out, args.to, args.force)
    print(f"{path} -> {out} ({layer.pulses:,} pulses)", file=sys.stderr)
    return 0


def folder_key(folder: str) -> str:
    """The store key the app gives ``folder``: ``root://<uuid>/<path below its nearest .helab-root>``."""
    from helab.utils.data_roots import MARKER_NAME, read_marker
    path = pathlib.Path(os.path.abspath(folder))
    for parent in (path, *path.parents):
        if (parent / MARKER_NAME).is_file():
            marker = read_marker(str(parent))
            below = path.relative_to(parent).as_posix()
            return f"root://{marker.uuid}" + ("" if below in ("", ".") else "/" + below)
    raise CliError(f"{folder}: no .helab-root here or above (it has no disk cache)")


def _read_only(database: pathlib.Path) -> sqlite3.Connection:
    if not database.is_file():
        raise CliError(f"no store-v4 at {database.parent} (the store_v4 switch is off, or nothing cached yet)")
    conn = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=5, isolation_level=None)
    conn.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
    conn.execute("PRAGMA query_only = 1")
    return conn


def _export_folder(args: argparse.Namespace) -> int:
    from helab.convert import raw_layer
    from helab.utils.store_v4 import DIRNAME
    if args.cache:
        cache = pathlib.Path(args.cache)
    else:
        from helab.utils.constants import cache_dir
        cache = pathlib.Path(cache_dir())
    store = cache / DIRNAME
    key = folder_key(args.folder)
    try:
        conn = _read_only(store / "records.sqlite")
    except sqlite3.Error as exc:  # (Unreadable here, or a WAL store without its -shm in a read-only folder.)
        raise CliError(f"{store}: can't be opened read only ({exc})") from None
    try:
        rows = [(int(shot), str(file)) for shot, file in conn.execute(
            "SELECT shot, file FROM raw_layers WHERE path = ? ORDER BY shot", (key,))]
    except sqlite3.Error as exc:
        raise CliError(f"{store}: {exc}") from None
    finally:
        conn.close()
    if not rows:
        print(f"Nothing to export: store-v4 holds no raw pulses of {args.folder}", file=sys.stderr)
        return 1
    name = pathlib.Path(os.path.abspath(args.folder)).name or "folder"
    out = pathlib.Path(args.out) if args.out else pathlib.Path.cwd() / f"helab-export-{name}"
    for shot, file in rows:
        source = store / pathlib.PurePosixPath(file)
        try:
            data = source.read_bytes()
        except OSError as exc:
            raise CliError(f"{source}: {exc}") from None
        layer, header = _layer(data, str(source))
        _write(raw_layer.columns(layer, args.bin_time), header, out / f"d{shot}.{args.to}", args.to, args.force)
    print(f"{args.folder}: {len(rows)} raw layers -> {out}", file=sys.stderr)
    return 0


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="helab cache", description=(__doc__ or "").split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    dump = commands.add_parser("dump", help="print a .hlb file's header")
    dump.add_argument("file")
    export = commands.add_parser("export", help="a raw layer (.hlb) or a folder's raw layers to npz, mat or csv")
    export.add_argument("file", nargs="?")
    export.add_argument("--folder", help="every raw layer store-v4 holds for this source folder")
    export.add_argument("--cache", help="the cache folder (default: HeLab's)")
    export.add_argument("--to", choices=FORMATS, default="npz")
    export.add_argument("--out", help="the output file (a file) or folder (--folder)")
    export.add_argument("--bin-time", type=float, default=25e-12, help="seconds per TDC bin (default 25e-12)")
    export.add_argument("--force", action="store_true", help="replace an existing output file")
    args = parser.parse_args(list(argv))
    try:
        if args.command == "dump":
            from helab.utils import hlb
            try:
                data = pathlib.Path(args.file).read_bytes()
                header = hlb.read_header(data)
                hlb.unpack(data)  # (Every part checked, not only the header.)
            except (OSError, hlb.HlbError) as exc:
                raise CliError(f"{args.file}: {exc}") from None
            print(json.dumps(_summary(header), indent=2, sort_keys=True))
            return 0
        if bool(args.file) == bool(args.folder):
            raise CliError("give a .hlb file or --folder FOLDER")
        return _export_folder(args) if args.folder else _export_file(pathlib.Path(args.file), args)
    except CliError as exc:
        print(f"helab cache: {exc}", file=sys.stderr)
        return 2
