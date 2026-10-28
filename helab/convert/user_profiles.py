"""The user's detector profiles: JSON files in a folder of the app folder (Q6.11), beside the built-ins.

Each user profile is one ``<name>.json`` file (``DetectorProfile.to_json``), so it can be copied,
mailed or kept in Git as it is; import and export are copies of such files. A user profile's name
never matches a built-in's (ignoring case: file systems may), and is plain enough to be its file's
name on every OS. Nothing here removes a file unless asked: ``delete`` is called only after the user
confirms (AGENTS.md).

Qt-free; standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
import tempfile

from helab.convert.profile import BUILTIN_PROFILES, DetectorProfile, ProfileError

FOLDER_NAME = "profiles"
# Letters, digits, space, ".", "_" and "-", starting with a letter or digit, ending without a dot
# or space (Windows drops those), at most 64 characters.
NAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9 ._-]{0,62}[A-Za-z0-9_-])?$", re.ASCII)
# File names Windows reserves, with any extension.
_RESERVED = frozenset({"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)),
                       *(f"lpt{n}" for n in range(1, 10))})
SUFFIX = ".json"


@dataclass(frozen=True)
class UserProfile:
    profile: DetectorProfile
    file: str


@dataclass(frozen=True)
class Unreadable:
    """A file in the profiles folder that isn't a valid profile, and why."""
    file: str
    reason: str


def check_name(name: str) -> str | None:
    """Why ``name`` can't be a user profile's, or None."""
    if not NAME_PATTERN.fullmatch(name):
        return ("A profile's name is 1 to 64 letters, digits, spaces, '.', '_' or '-', starting with a letter "
                "or digit and not ending with a dot or space")
    if name.split(".")[0].lower() in _RESERVED:
        return f"{name!r} can't be a file name on Windows"
    if name.lower() in {builtin.lower() for builtin in BUILTIN_PROFILES}:
        return f"{name!r} is a built-in profile's name"
    return None


class ProfileLibrary:
    """The user profiles in ``folder`` (made when the first is saved)."""

    def __init__(self, folder: str) -> None:
        self.folder = folder

    def file_for(self, name: str) -> str:
        return os.path.join(self.folder, name + SUFFIX)

    def scan(self) -> tuple[list[UserProfile], list[Unreadable]]:
        """The valid profiles by name, and the files that aren't (a file whose profile's name isn't
        its file name is unreadable: renaming one by hand would otherwise make two of a name)."""
        found: list[UserProfile] = []
        bad: list[Unreadable] = []
        try:
            names = sorted(os.listdir(self.folder))
        except FileNotFoundError:
            return found, bad
        for entry in names:
            if not entry.endswith(SUFFIX) or entry.startswith("."):
                continue
            path = os.path.join(self.folder, entry)
            try:
                with open(path, encoding="utf-8") as stream:
                    profile = DetectorProfile.from_json(stream.read())
            except (OSError, UnicodeDecodeError, ProfileError) as error:
                bad.append(Unreadable(path, str(error)))
                continue
            problem = check_name(profile.name)
            if problem is None and profile.name + SUFFIX != entry:
                problem = f"its profile is named {profile.name!r}, not {entry[:-len(SUFFIX)]!r}"
            if problem is not None:
                bad.append(Unreadable(path, problem))
            else:
                found.append(UserProfile(profile, path))
        return found, bad

    def profiles(self) -> dict[str, DetectorProfile]:
        return {entry.profile.name: entry.profile for entry in self.scan()[0]}

    def find(self, name: str) -> DetectorProfile | None:
        """A built-in or user profile by name, or None."""
        if name in BUILTIN_PROFILES:
            return BUILTIN_PROFILES[name]
        return self.profiles().get(name)

    def exists(self, name: str) -> bool:
        """A user profile's file of this name, whatever the case (file systems may ignore it)."""
        try:
            return any(entry.lower() == (name + SUFFIX).lower() for entry in os.listdir(self.folder))
        except FileNotFoundError:
            return False

    def save(self, profile: DetectorProfile, *, replace: bool = False) -> str:
        """Write ``profile`` as its file (atomically: a reader never sees half of it). A new name
        that is taken is refused unless ``replace`` (an edit of that profile)."""
        problem = check_name(profile.name)
        if problem is not None:
            raise ProfileError(problem)
        if not replace and self.exists(profile.name):
            raise ProfileError(f"A profile named {profile.name!r} exists already")
        os.makedirs(self.folder, exist_ok=True)
        target = self.file_for(profile.name)
        handle, temporary = tempfile.mkstemp(prefix="." + profile.name, suffix=".partial", dir=self.folder)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(profile.to_json())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        return target

    def delete(self, name: str) -> None:
        """Remove a user profile's file (the caller asked the user first)."""
        if name in BUILTIN_PROFILES:
            raise ProfileError(f"{name!r} is built in")
        os.unlink(self.file_for(name))

    @staticmethod
    def read_file(path: str) -> DetectorProfile:
        """A profile from any JSON file (import), checked; not saved."""
        try:
            with open(path, encoding="utf-8") as stream:
                return DetectorProfile.from_json(stream.read())
        except (OSError, UnicodeDecodeError) as error:
            raise ProfileError(f"Can't read {os.path.basename(path)}: {error}") from error

    @staticmethod
    def export(profile: DetectorProfile, path: str) -> None:
        with open(path, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(profile.to_json())

    def free_name(self, base: str) -> str:
        """``base`` if it can be a new user profile's name, else ``base-2``, ``base-3``, …"""
        base = re.sub(r"[^A-Za-z0-9 ._-]", "-", base).strip(" .")[:56] or "profile"
        if not base[0].isalnum():
            base = "p" + base
        candidate, n = base, 1
        while check_name(candidate) is not None or self.exists(candidate):
            n += 1
            candidate = f"{base}-{n}"
        return candidate


def duplicate(profile: DetectorProfile, name: str) -> DetectorProfile:
    """A copy of ``profile`` named ``name``, version 1, its notes saying where it came from."""
    origin = f"Copied from {profile.name} v{profile.version} (content hash {profile.content_hash()[:12]})."
    return profile.replace(name=name, version=1, notes=f"{origin} {profile.notes}".strip())
