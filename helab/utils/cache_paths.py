"""Stable disk-cache keys for mounted SMB shares.

The source path remains the OS mount path. Only keys stored in SQLite use the
share source, so macOS's order-dependent ``/Volumes/name-1`` suffix is never a
folder identity. A resolver is captured once per helper operation.
"""
from __future__ import annotations

from dataclasses import dataclass
import ntpath
import os
import sys
from typing import Iterable
from urllib.parse import quote, unquote, urlsplit


@dataclass(frozen=True)
class Mount:
    source: str
    path: str
    fstype: str
    remote: bool = False


class UnresolvedRemotePath(ValueError):
    """A remote folder cannot safely use its transient local mount path as a cache key."""

    def __init__(self, mount_path: str, mount_type: str, detail: str) -> None:
        super().__init__(detail)
        self.mount_path = mount_path
        self.mount_type = mount_type


def _webdav_unc(source: str) -> bool:
    parts = [part for part in source.replace("\\", "/").split("/") if part]
    return len(parts) >= 2 and ("@" in parts[0] or parts[1].lower() == "davwwwroot")


def current_mounts() -> list[Mount]:
    if sys.platform == "win32":
        return _windows_mounts()
    import psutil
    mounts = []
    for part in psutil.disk_partitions(all=True):
        mounts.append(Mount(part.device, part.mountpoint, part.fstype,
                            "remote" in part.opts.split(",")))
    return mounts


def _windows_mounts() -> list[Mount]:
    """Read mapped drive names without querying every drive's volume information."""
    import ctypes

    kernel32 = getattr(ctypes, "windll").kernel32
    mask = kernel32.GetLogicalDrives()
    mounts = []
    for index in range(26):
        if not mask & (1 << index):
            continue
        drive = f"{chr(65 + index)}:\\"
        if kernel32.GetDriveTypeW(drive) != 4:  # DRIVE_REMOTE
            continue
        source = _windows_unc(drive)
        mounts.append(Mount(source or drive, drive, "smb" if source else "remote", True))
    return mounts


def _windows_unc(drive: str) -> str | None:
    """Resolve a mapped drive to its SMB share without asking the source folder."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    size = wintypes.DWORD(32768)
    buffer = ctypes.create_unicode_buffer(size.value)
    result = getattr(ctypes, "windll").mpr.WNetGetConnectionW(drive[:2], buffer, ctypes.byref(size))
    # ERROR_CONNECTION_UNAVAIL means a remembered drive is disconnected; the
    # redirector still supplies its UNC name, which is the stable cache source.
    return buffer.value if result in (0, 1201) and buffer.value.startswith("\\\\") else None


def _normal(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path)) if sys.platform == "win32" else os.path.normpath(path)


def _inside(path: str, mount: str) -> bool:
    separator = "\\" if sys.platform == "win32" else os.sep
    return path == mount or path.startswith(mount.rstrip("/\\") + separator)


def _smb_source(source: str, fstype: str) -> str | None:
    """Return the normalized server/share URL without mount credentials."""
    if fstype.lower() not in ("smbfs", "cifs", "smb", "smb2", "smb3"):
        return None
    if sys.platform == "win32" and _webdav_unc(source):
        return None
    spelling = source.replace("\\", "/")
    if spelling.startswith("smb://"):
        spelling = spelling[4:]
    if not spelling.startswith("//"):
        return None
    parsed = urlsplit("smb:" + spelling)
    if not parsed.hostname or not parsed.path.strip("/"):
        return None
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if parsed.port is not None:
        host += f":{parsed.port}"
    # Quote after decoding: a nested automount such as Documents%20and%20Settings
    # gets the same key through its parent share mount.
    parts = [quote(unquote(part), safe="") for part in parsed.path.split("/") if part]
    parts[0] = parts[0].lower()  # SMB share names are case-insensitive.
    return f"smb://{host}/{'/'.join(parts)}"


class CachePaths:
    """Translate source paths to store keys and active store keys back to source paths."""

    def __init__(self, mounts: Iterable[Mount]) -> None:
        pairs = [(mount, _smb_source(mount.source, mount.fstype)) for mount in mounts]
        self._all_mounts = pairs
        self._mounts = [(mount, url) for mount, url in pairs if url is not None]
        self._direct_paths: dict[str, str] = {}

    def key(self, path: str) -> str:
        if path.startswith("smb://"):
            return path
        if sys.platform == "win32" and path.startswith(("\\\\", "//")):
            components = [part for part in ntpath.normpath(path).replace("\\", "/").split("/") if part]
            if _webdav_unc(path):
                raise UnresolvedRemotePath("\\\\" + "\\".join(components[:2]), "webdav",
                                           f"WebDAV network path is not supported for disk cache: {path}")
            direct = _smb_source("//" + "/".join(components[:2]), "smb")
            if direct is not None:
                if len(components) > 2:
                    direct += "/" + "/".join(quote(part, safe="") for part in components[2:])
                self._direct_paths[direct] = path
                return direct
            raise UnresolvedRemotePath(path, "unidentified SMB", f"UNC path has no SMB share: {path}")
        target = ntpath.normpath(path) if sys.platform == "win32" else os.path.normpath(path)
        matches = [(mount, url) for mount, url in self._all_mounts
                   if _inside(_normal(target), _normal(mount.path))]
        if not matches:
            return path
        mount, url = max(matches, key=lambda entry: len(_normal(entry[0].path)))
        if url is None:
            if mount.remote or mount.fstype.lower() in (
                    "smbfs", "cifs", "smb", "smb2", "smb3", "afpfs", "nfs", "nfs4", "webdav", "davfs"):
                kind = ("webdav" if sys.platform == "win32" and _webdav_unc(mount.source) else
                        "unidentified SMB" if mount.fstype.lower() in ("smbfs", "cifs", "smb", "smb2", "smb3")
                        else mount.fstype.lower() or "network")
                raise UnresolvedRemotePath(mount.path, kind,
                                           f"Remote mount source could not be identified: {mount.path} ({kind})")
            return path
        # Compare with normcase above, but retain the source path's spelling in
        # the relative part so GUI removal/adoption events use its exact case.
        mount_path = ntpath.normpath(mount.path) if sys.platform == "win32" else os.path.normpath(mount.path)
        relative = target[len(mount_path):].lstrip("/\\")
        if not relative:
            return url
        return url + "/" + "/".join(quote(part, safe="") for part in relative.replace("\\", "/").split("/"))

    def source(self, key: str) -> str:
        if not key.startswith("smb://"):
            return key
        matches = [(mount, url) for mount, url in self._mounts
                   if key == url or key.startswith(url + "/")]
        if not matches:
            return self._direct_paths.get(key, key)  # An unmounted share stays identifiable in Settings.
        mount, url = max(matches, key=lambda entry: len(entry[1]))
        relative = key[len(url):].lstrip("/")
        join = ntpath.join if sys.platform == "win32" else os.path.join
        return join(mount.path, *(unquote(part) for part in relative.split("/") if part))


def current_cache_paths() -> CachePaths:
    return CachePaths(current_mounts())
