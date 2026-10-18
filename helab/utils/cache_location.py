"""Where the disk cache may live: never on a network or synced folder.

SQLite's WAL mode doesn't work on network filesystems (https://www.sqlite.org/wal.html),
and sync clients can move files to the cloud or create conflicts under the database.
"""
from __future__ import annotations

import os
import sys

NETWORK_FILESYSTEMS = frozenset({
    "smbfs", "afpfs", "nfs", "nfs4", "webdav", "cifs", "smb", "smb2", "smb3", "9p", "davfs", "sshfs",
    "fuse.sshfs", "fuse.rclone", "fuse.davfs"})
# Folder names sync clients use; OneDrive's carries the organisation ("OneDrive - ANU").
SYNCED_PREFIXES = ("OneDrive", "Dropbox", "Google Drive", "GoogleDrive", "iCloudDrive", "iCloud Drive", "Box Sync")
# macOS keeps iCloud Drive and File Provider clients' folders here.
SYNCED_PAIRS = (("Library", "Mobile Documents"), ("Library", "CloudStorage"))


def _parts(path: str) -> list[str]:
    rest = os.path.splitdrive(path)[1]
    return [part for part in rest.replace("\\", "/").split("/") if part]


def _synced(parts: list[str]) -> str:
    for name in parts:
        if name.startswith(SYNCED_PREFIXES):
            return name
    for first, second in zip(parts, parts[1:]):
        if (first, second) in SYNCED_PAIRS:
            return second
    return ""


def _filesystem(path: str) -> tuple[str, bool]:
    """The filesystem type of the volume holding ``path``, and whether the OS calls it remote."""
    import psutil

    def normalize(value: str) -> str:
        return os.path.normcase(value) if sys.platform == "win32" else value

    target = normalize(path)
    best: tuple[int, str, bool] = (-1, "", False)
    for partition in psutil.disk_partitions(all=True):
        mount = normalize(partition.mountpoint)
        inside = target == mount or target.startswith(mount.rstrip("/\\") + os.sep) or mount in ("/", "")
        if inside and len(mount) > best[0]:
            best = (len(mount), partition.fstype.lower(), "remote" in partition.opts.split(","))
    return best[1], best[2]


def cache_location_problem(path: str) -> str:
    """Why ``path`` can't hold the disk cache (e.g. "on a network drive (smbfs)"), or "" if it can."""
    real = os.path.realpath(os.path.abspath(path))
    if real.startswith(("\\\\", "//")):
        return "on a network drive"
    if synced := _synced(_parts(real)):
        return f"in a synced folder ({synced})"
    try:
        fstype, remote = _filesystem(real)
    except Exception:
        return ""  # Unknown: a folder we can't classify is allowed.
    if remote or fstype in NETWORK_FILESYSTEMS:
        return f"on a network drive ({fstype})" if fstype else "on a network drive"
    return ""
