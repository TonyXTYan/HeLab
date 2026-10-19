"""Marker based identities for disk cached experiment folders.

Locations describe where a marker was seen on this computer.  Only a marker's
UUID, never a mount name or a volume identifier, identifies cached data.
The resolver reads its supplied root records only; discovery belongs to source
I/O helpers and must never happen during a cached read.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import ntpath
import os
import plistlib
import stat
import sys
from typing import Callable, Iterable
import uuid

from helab.utils.cache_paths import CachePaths, Mount, UnresolvedRemotePath, _inside, _normal

MARKER_NAME = ".helab-root"
MARKER_VERSION = 1
MAX_MARKER_BYTES = 64 * 1024


class NoDataRoot(UnresolvedRemotePath):
    """A folder has no confirmed marker and must use session RAM only."""

    def __init__(self, path: str) -> None:
        super().__init__(path, "no data root", f"Disk cache off: no data root for {path}")


class VolumeUnverified(NoDataRoot):
    """A local lane read whose volume hint this session hasn't checked yet (the disk at that
    mount may have been swapped): it waits for verification instead of trusting the hint."""

    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.args = (f"The volume of {path} is not yet verified",)


def fixed_mount(mount: Mount) -> bool:
    """The system volume: another disk can't be mounted in its place, so its hint stays valid."""
    if sys.platform == "win32":
        drive = os.environ.get("SystemDrive", "C:")
        return _normal(mount.path) == _normal(drive.rstrip("\\") + "\\")
    return mount.path in ("/", "/System/Volumes/Data", "/home")


@dataclass(frozen=True)
class Marker:
    uuid: str
    label: str
    created_at: str


@dataclass(frozen=True)
class RootLocation:
    location: str
    uuid: str
    decision: str = "confirmed"


class LocalVolumes:
    """Translate local paths to location keys using supplied mounted volume IDs.

    IDs are captured by a source I/O helper and handed to local lane operations;
    this class never stats a source folder.
    """

    def __init__(self, volumes: Iterable[tuple[Mount, str]]) -> None:
        self.volumes = tuple(volumes)

    def location(self, path: str) -> str:
        matches = [(mount, identifier) for mount, identifier in self.volumes
                   if _inside(_normal(path), _normal(mount.path))]
        if not matches:
            raise NoDataRoot(path)
        mount, identifier = max(matches, key=lambda entry: len(_normal(entry[0].path)))
        relative = path[len(mount.path.rstrip("/\\")):].lstrip("/\\")
        from urllib.parse import quote
        return f"vol://{identifier}" + ("/" + "/".join(quote(p, safe="") for p in relative.replace("\\", "/").split("/")) if relative else "")

    def source(self, location: str) -> str:
        from urllib.parse import unquote
        join = ntpath.join if sys.platform == "win32" else os.path.join
        for mount, identifier in self.volumes:
            prefix = f"vol://{identifier}"
            suffix = _relative(location, prefix)
            if suffix is not None:
                return join(mount.path, *(unquote(part) for part in suffix.split("/") if part))
        return location


def current_local_volumes(mounts: Iterable[Mount],
                          *, paths: Iterable[str],
                          id_reader: Callable[[Mount], str | None] | None = None) -> LocalVolumes:
    """Capture IDs only for the volumes containing requested paths."""
    candidates = tuple(mounts)
    selected: list[Mount] = []
    for path in paths:
        matches = [mount for mount in candidates if _inside(_normal(path), _normal(mount.path))]
        if matches:
            best = max(matches, key=lambda mount: len(_normal(mount.path)))
            if best not in selected:
                selected.append(best)
    pairs: list[tuple[Mount, str]] = []
    reader = id_reader or _volume_id
    for mount in selected:
        if mount.remote or mount.fstype.lower() in ("smb", "smbfs", "cifs", "nfs", "nfs4", "afpfs", "webdav", "davfs"):
            continue
        identifier = reader(mount)
        if identifier:
            pairs.append((mount, identifier.lower()))
    return LocalVolumes(pairs)


def _volume_id(mount: Mount) -> str | None:
    """OS volume ID for a *location*, never for the data's identity."""
    test_id = os.environ.get("HELAB_TEST_VOLUME_ID")
    if test_id:
        return test_id
    if sys.platform == "darwin":
        import subprocess
        try:
            result = subprocess.run(("diskutil", "info", "-plist", mount.path),
                                    capture_output=True, check=True, timeout=5)
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        return _mac_volume_id_from_plist(result.stdout)
    if sys.platform == "win32":
        import ctypes
        serial = ctypes.c_ulong()
        kernel32 = getattr(ctypes, "windll").kernel32
        previous = kernel32.SetErrorMode(0x0001)  # SEM_FAILCRITICALERRORS: empty card readers do not prompt.
        try:
            ok = kernel32.GetVolumeInformationW(
                mount.path, None, 0, ctypes.byref(serial), None, None, None, 0)
        finally:
            kernel32.SetErrorMode(previous)
        return f"{serial.value:08x}" if ok else None
    # Linux's by-uuid names identify the device independently of mount path.
    directory = "/dev/disk/by-uuid"
    try:
        device = os.path.realpath(mount.source)
        for name in os.listdir(directory):
            if os.path.realpath(os.path.join(directory, name)) == device:
                return name
    except OSError:
        return None
    return None


def _mac_volume_id_from_plist(raw: bytes) -> str | None:
    """Prefer the APFS group ID shared by sealed System and firmlinked Data."""
    try:
        details = plistlib.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(details, dict):
        return None
    value = details.get("APFSVolumeGroupID") or details.get("VolumeUUID")
    return str(value) if value else None


def parse_marker(raw: bytes) -> Marker:
    """Validate a small UTF-8 JSON marker; ignore future metadata fields."""
    if len(raw) > MAX_MARKER_BYTES:
        raise ValueError("Data-root marker is too large")
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Data-root marker is not UTF-8 JSON") from exc
    if not isinstance(value, dict) or value.get("helab") != "root" or type(value.get("version")) is not int or value["version"] != MARKER_VERSION:
        raise ValueError("Unsupported data-root marker")
    try:
        supplied = value["uuid"]
        if not isinstance(supplied, str):
            raise ValueError("UUID must be a string")
        identifier = str(uuid.UUID(supplied))
        if supplied.lower() != identifier:
            raise ValueError("UUID must use canonical spelling")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Invalid data-root UUID") from exc
    label = value.get("label")
    if (not isinstance(label, str) or not label.strip() or label != label.strip()
            or label in (".", "..") or "/" in label or "\\" in label
            or any(ord(character) < 32 for character in label)):
        raise ValueError("Invalid data-root label")
    stamp = value.get("created_at")
    if not isinstance(stamp, str) or not stamp.endswith("Z"):
        raise ValueError("Invalid data-root creation time")
    try:
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid data-root creation time") from exc
    return Marker(identifier, label, stamp)


def new_marker(folder: str) -> tuple[Marker, bytes]:
    """A new root for ``folder``, and the exact bytes to write: the helper writes these, and
    the manual flow (no write permission) shows the same text."""
    marker = Marker(str(uuid.uuid4()), marker_label(folder),
                    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    text = json.dumps({"helab": "root", "version": MARKER_VERSION, "uuid": marker.uuid,
                       "label": marker.label, "created_at": marker.created_at},
                      indent=2, ensure_ascii=False) + "\n"
    return marker, text.encode("utf-8")


def marker_label(folder: str) -> str:
    """The folder's name (a drive's letter for a drive root), as ``parse_marker`` accepts it."""
    module = ntpath if sys.platform == "win32" else os.path
    name = module.basename(module.normpath(folder))
    if not name and sys.platform == "win32":
        name = ntpath.splitdrive(folder)[0].rstrip(":").lstrip("\\")
    name = "".join(character for character in name if ord(character) >= 32).replace("\\", "_").strip()
    return name if name and name not in (".", "..") else "data"


def read_marker(folder: str, *, trace: Callable[[str, dict[str, object]], None] | None = None) -> Marker:
    """Read a marker only from a source I/O operation, never from a local lane.

    ``trace`` (the helpers' I/O trace, ``HELAB_IO_TRACE``) hears of each step that succeeded: open,
    fstat (size, mtime_ns) and read (bytes)."""
    descriptor = os.open(os.path.join(folder, MARKER_NAME), os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    try:
        if trace is not None:
            trace("open", {})
        info = os.fstat(descriptor)
        if trace is not None:
            trace("fstat", {"size": info.st_size, "mtime_ns": info.st_mtime_ns})
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Data-root marker is not a regular file")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            raw = stream.read(MAX_MARKER_BYTES + 1)
            if trace is not None:
                trace("read", {"bytes": len(raw)})
            return parse_marker(raw)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _relative(path: str, prefix: str) -> str | None:
    if path == prefix:
        return ""
    if path.startswith(prefix.rstrip("/") + "/"):
        return path[len(prefix.rstrip("/")) + 1:]
    return None


class DataRoots:
    """Resolve paths using a snapshot of confirmed, persisted root locations."""

    def __init__(self, locations: CachePaths, roots: Iterable[RootLocation],
                 *, local_location: Callable[[str], str] | None = None,
                 local_source: Callable[[str], str] | None = None,
                 case_insensitive_volumes: bool = False) -> None:
        self.locations = locations
        self.local_location = local_location or (lambda path: path)
        self.local_source = local_source or (lambda location: location)
        self.case_insensitive_volumes = case_insensitive_volumes
        self.roots = tuple(roots)
        self._source: dict[str, str] = {}

    def location(self, path: str) -> str:
        location = self.locations.key(path)
        if location.startswith("smb://"):
            return location
        return self.local_location(path)

    def key(self, path: str) -> str:
        if path.startswith("root://"):
            return path
        location = self.location(path)
        matches = []
        for root in self.roots:
            insensitive = location.startswith("smb://") or self.case_insensitive_volumes
            matched = _relative(location.casefold() if insensitive else location,
                                root.location.casefold() if insensitive else root.location)
            if matched is not None:
                suffix = location[len(root.location):].lstrip("/")
                matches.append((root, suffix))
        if not matches:
            raise NoDataRoot(path)
        root, suffix = max(matches, key=lambda pair: len(pair[0].location))
        if root.decision != "confirmed":
            raise NoDataRoot(path)
        key = f"root://{root.uuid}" + ("/" + suffix if suffix else "")
        self._source[key] = path
        return key

    def source(self, key: str) -> str:
        if not key.startswith("root://"):
            return key
        if key in self._source:
            return self._source[key]
        identifier, _, suffix = key[7:].partition("/")
        candidates: list[str] = []
        for root in self.roots:
            if root.uuid == identifier and root.decision == "confirmed":
                location = root.location + ("/" + suffix if suffix else "")
                if location.startswith("smb://"):
                    candidates.append(self.locations.source(location))
                else:
                    candidates.append(self.local_source(location))
        return next((path for path in candidates if not path.startswith(("smb://", "vol://"))), key)
