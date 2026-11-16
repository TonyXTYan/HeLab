"""``helab cache``: look into caching v2's ``.hlb`` files and export them, read only.

    helab cache dump FILE.hlb
    helab cache export FILE.hlb [--to npz|mat|csv] [--out PATH] [--bin-time SECONDS] [--force]
    helab cache export --folder FOLDER [--kind raw|txy] [--layer L] [--cache DIR] [--to …] [--out DIR] [--force]

``dump`` prints a file's header as JSON (each array's name, dtype, shape and compressed bytes instead of
its chunk list). ``export`` writes a raw layer's columns (``raw_layer.columns``: ``channel``, ``time_bins``
absolute TDC bins, ``time_s``) and its header (JSON text) to ``.npz`` (NumPy), ``.mat`` (``scipy.io.savemat``,
for MATLAB) or ``.csv`` (one row per pulse). ``--folder`` exports every raw layer store-v4 holds for a
source folder (found by its nearest ``.helab-root``, as the app keys it) as ``d<N>.<ext>``. With ``--kind
txy`` (A44.1) it exports a TXY layer's shots instead (``t_s``, ``x_m``, ``y_m``) as ``d_txy<N>.<ext>``: the
layer ``--layer`` names (``matlab``, a tag such as ``m19v1``, or ``helab:<hash>``), or the only one there is.
A TXY segment ``.hlb`` exports as one file with a ``shot`` column.

Without ``--cache``, the cache folder is ``HELAB_DIR_CACHES_OVERRIDE``, else the one the app recorded in
its app folder's ``cache-folder.json`` (A44.2: no Qt), else the app's setting (QtCore, no GUI).

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
            writer.writerow(list(columns))  # (Raw: channel, time_bins, time_s; TXY: [shot,] t_s, x_m, y_m.)
            for row in zip(*(columns[name].tolist() for name in columns)):
                writer.writerow([repr(value) if isinstance(value, float) else value for value in row])


def _layer(data: bytes, where: str) -> tuple[Any, dict[str, Any]]:
    from helab.convert import raw_layer
    from helab.utils import hlb
    try:
        return raw_layer.from_hlb(data)
    except hlb.HlbError as exc:
        raise CliError(f"{where}: {exc}") from None


def _txy_columns(shots: dict[int, Any], with_shot: bool) -> dict[str, Any]:
    """A TXY layer's shots as columns, in shot order: ``t_s``, ``x_m``, ``y_m`` (and ``shot``)."""
    import numpy as np
    order = sorted(shots)
    hits = np.concatenate([shots[shot] for shot in order]) if order else np.empty((0, 3))
    columns: dict[str, Any] = {}
    if with_shot:
        columns["shot"] = np.repeat(np.asarray(order, dtype=np.int64), [len(shots[shot]) for shot in order])
    columns.update(t_s=np.ascontiguousarray(hits[:, 0]), x_m=np.ascontiguousarray(hits[:, 1]),
                   y_m=np.ascontiguousarray(hits[:, 2]))
    return columns


def _export_file(path: pathlib.Path, args: argparse.Namespace) -> int:
    from helab.convert import raw_layer, txy_layer
    from helab.utils import hlb
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CliError(f"{path}: {exc}") from None
    try:
        kind = hlb.read_header(data).get("kind")
    except hlb.HlbError as exc:
        raise CliError(f"{path}: {exc}") from None
    if kind == txy_layer.KIND:
        try:
            shots, _, segment = txy_layer.unpack_segment(data)
        except hlb.HlbError as exc:
            raise CliError(f"{path}: {exc}") from None
        out = pathlib.Path(args.out) if args.out else pathlib.Path.cwd() / f"{path.stem}.{args.to}"
        _write(_txy_columns(shots, True), segment, out, args.to, args.force)
        print(f"{path} -> {out} ({len(shots):,} shots)", file=sys.stderr)
        return 0
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


def _app_folder() -> pathlib.Path:
    """HeLab's app folder, as ``constants.app_folder`` gives it (that module loads Qt; both use
    ``helab.utils.app_dirs``)."""
    from helab.utils.app_dirs import app_folder
    return pathlib.Path(app_folder())


def cache_folder() -> pathlib.Path:
    """The cache folder ``helab cache`` reads without ``--cache`` (A44.2): ``HELAB_DIR_CACHES_OVERRIDE``; else
    the one the app recorded (``cache-folder.json``) if that folder exists; else the app's own setting, read
    through QtCore (no widgets, no GUI) when the file is missing, unreadable or names a folder that isn't
    there."""
    override = os.environ.get("HELAB_DIR_CACHES_OVERRIDE")
    if override:
        return pathlib.Path(override)
    try:
        recorded = json.loads((_app_folder() / "cache-folder.json").read_text(encoding="utf-8"))
        folder = pathlib.Path(str(recorded["cache_folder"]))
        if folder.is_dir():
            return folder
    except (OSError, ValueError, KeyError, TypeError):
        pass
    from helab.utils.constants import cache_dir
    return pathlib.Path(cache_dir())


def _rows(store: pathlib.Path, query: str, args: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    try:
        conn = _read_only(store / "records.sqlite")
    except sqlite3.Error as exc:  # (Unreadable here, or a WAL store without its -shm in a read-only folder.)
        raise CliError(f"{store}: can't be opened read only ({exc})") from None
    try:
        return [tuple(row) for row in conn.execute(query, args)]
    except sqlite3.Error as exc:
        raise CliError(f"{store}: {exc}") from None
    finally:
        conn.close()


def _export_folder(args: argparse.Namespace) -> int:
    from helab.convert import raw_layer
    from helab.utils.store_v4 import DIRNAME
    store = (pathlib.Path(args.cache) if args.cache else cache_folder()) / DIRNAME
    key = folder_key(args.folder)
    name = pathlib.Path(os.path.abspath(args.folder)).name or "folder"
    out = pathlib.Path(args.out) if args.out else pathlib.Path.cwd() / f"helab-export-{name}"
    if args.kind == "txy":
        return _export_layers(store, key, out, args)
    rows = [(int(shot), str(file)) for shot, file in _rows(
        store, "SELECT shot, file FROM raw_layers WHERE path = ? ORDER BY shot", (key,))]
    if not rows:
        print(f"Nothing to export: store-v4 holds no raw pulses of {args.folder}", file=sys.stderr)
        return 1
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


def _export_layers(store: pathlib.Path, key: str, out: pathlib.Path, args: argparse.Namespace) -> int:
    """A44.1: one TXY layer of the folder, a file per shot (``d_txy<N>``)."""
    from helab.convert import txy_layer
    from helab.utils import hlb
    layers = {str(layer): (json.loads(tags), json.loads(entries)) for layer, tags, entries in _rows(
        store, "SELECT layer, tags, entries FROM txy_layers WHERE path = ? ORDER BY layer", (key,))}
    if not layers:
        print(f"Nothing to export: store-v4 holds no TXY layers of {args.folder}", file=sys.stderr)
        return 1
    wanted = args.layer
    chosen = [layer for layer, (tags, _) in layers.items()
              if wanted is None or wanted == layer or wanted in tags]
    if len(chosen) != 1:
        names = ", ".join(f"{layer} ({', '.join(tags) or 'MATLAB'})" for layer, (tags, _) in layers.items())
        raise CliError(f"{args.folder}: name one layer with --layer: {names}" if wanted is None or not chosen
                       else f"{args.folder}: --layer {wanted} names more than one layer: {names}")
    layer = chosen[0]
    segments = {int(seq): str(file) for seq, file in _rows(
        store, "SELECT seq, file FROM txy_segments WHERE path = ? AND layer = ?", (key, layer))}
    by_seq: dict[int, list[int]] = {}
    for entry in layers[layer][1]:
        by_seq.setdefault(int(entry[4]), []).append(int(entry[0]))
    written = 0
    for seq, shots in sorted(by_seq.items()):
        source = store / pathlib.PurePosixPath(segments.get(seq, f"txy/missing-{seq}"))
        try:
            held, _, header = txy_layer.unpack_segment(source.read_bytes())
        except (OSError, hlb.HlbError) as exc:
            raise CliError(f"{source}: {exc}") from None
        for shot in shots:
            _write(_txy_columns({shot: held[shot]}, False), header, out / f"d_txy{shot}.{args.to}", args.to,
                   args.force)
            written += 1
    print(f"{args.folder}: {written} shots of {layer} -> {out}", file=sys.stderr)
    return 0


# ``--help``'s description: written for users, never taken from the docstring (its notes are for developers).
DESCRIPTION = ("Look into the .hlb files of HeLab's disk cache and export them as NumPy (.npz), MATLAB (.mat) "
               "or CSV files. Read only: it never writes into the disk cache or a source folder.")


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="helab cache", description=DESCRIPTION)
    commands = parser.add_subparsers(dest="command", required=True)
    dump = commands.add_parser("dump", help="print a .hlb file's header")
    dump.add_argument("file")
    export = commands.add_parser("export", help="a raw layer (.hlb) or a folder's raw layers to npz, mat or csv")
    export.add_argument("file", nargs="?")
    export.add_argument("--folder", help="every raw layer (or, with --kind txy, a TXY layer) store-v4 holds for "
                                         "this source folder")
    export.add_argument("--kind", choices=("raw", "txy"), default="raw", help="with --folder: raw pulses or TXY")
    export.add_argument("--layer", help="with --kind txy: matlab, a tag (m19v1, …) or helab:<hash>")
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
