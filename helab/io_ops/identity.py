"""A folder's identity for Live and saves from RAM: its data root, else its location."""
from __future__ import annotations

import os

from helab.io_ops.infra import _mounts, _read_marker


def _folder_identity(path: str, root: str | None = None, reason: str = "live: identity") -> tuple[str, str]:
    """Which folder ``path`` is, beyond its spelling: the nearest data root's UUID, else its
    location (an SMB share's server and share, or a local mount's device) and relative path; and
    the folder whose .helab-root names it ("" for a location). "" if a marker is there but unreadable.

    ``root``: what an earlier call found. Then only that folder's marker is read (one open instead
    of one per level up to it), or none for "" (the location, from the mount table): another drive
    or share at this path has another marker there, or none, or another location. A marker gone or
    invalid is looked for again from ``path``."""
    if root:
        try:
            return "root:" + _read_marker(root, reason).uuid, root
        except (FileNotFoundError, ValueError):
            pass
        except OSError:
            return "", root
    elif root == "":
        return _location_identity(path, reason), ""
    folder = path
    while True:
        try:
            return "root:" + _read_marker(folder, reason).uuid, folder
        except FileNotFoundError:
            pass
        except ValueError:
            pass  # An invalid marker is no data root.
        except OSError:
            return "", ""
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return _location_identity(path, reason), ""


def _location_identity(path: str, reason: str) -> str:
    """Where ``path`` is, from the mount table alone (no source I/O): its SMB share's server and share,
    or its local mount's device, and the path below it."""
    from helab.utils.cache_paths import _inside, _normal, _smb_source
    mounts = [mount for mount in _mounts(reason) if _inside(_normal(path), _normal(mount.path))]
    if not mounts:
        return "location:" + path
    mount = max(mounts, key=lambda item: len(_normal(item.path)))
    source = _smb_source(mount.source, mount.fstype) or f"{mount.fstype}:{mount.source}"
    return f"location:{source}|{path[len(mount.path):]}"
