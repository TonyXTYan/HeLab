"""Help › Record I/O trace's check of the temp folder and its earlier recordings (``trace_check``)."""
from __future__ import annotations

import os
from typing import Any

from helab.io_ops.infra import Emit


def trace_check(temps: str, folder: str, send: Emit) -> None:
    """Before Help › Record I/O trace starts, in a local-lane helper (the mount table can stall on a
    disconnected network drive, never on the GUI thread): whether HeLab's temp folder ``temps`` is on a
    network or synced folder (``problem``), and the recordings already in its io-traces ``folder``,
    sorted by name, each with its trace files and their size (``earlier``): a recording's folder
    (``io-trace-*``, its ``*.jsonl`` files) or a single-file trace of an earlier build
    (``io-trace-*.jsonl``). Not traced: the temp folder is no source folder."""
    from helab.utils.cache_location import cache_location_problem
    problem = cache_location_problem(temps)
    earlier: list[dict[str, Any]] = []
    if problem:
        send({"kind": "trace_folder", "problem": problem, "earlier": earlier})
        return
    try:
        with os.scandir(folder) as entries:
            found = sorted((entry.path, entry.is_dir(follow_symlinks=False)) for entry in entries
                           if entry.name.startswith("io-trace-"))
    except OSError:
        found = []

    def size(path: str) -> int | None:
        try:
            return os.stat(path, follow_symlinks=False).st_size
        except OSError:
            return None
    for path, is_dir in found:
        if is_dir:
            try:
                with os.scandir(path) as entries:
                    names = sorted(entry.path for entry in entries
                                   if entry.name.endswith(".jsonl") and entry.is_file(follow_symlinks=False))
            except OSError:
                names = []
        elif path.endswith(".jsonl") and os.path.isfile(path):
            names = [path]
        else:
            continue
        sizes = {name: size(name) for name in names}
        files = [name for name, value in sizes.items() if value is not None]
        earlier.append({"path": path, "files": files, "size": sum(sizes[name] or 0 for name in files)})
    send({"kind": "trace_folder", "problem": problem, "earlier": earlier})
