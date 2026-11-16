"""Where HeLab's per-user folders are, with the standard library only.

``helab.utils.constants`` gives the same names (it loads Qt and the settings); this module is for code
that runs before either: the check for a running update at the very start of ``helab.main``, and
``helab cache``.
"""
from __future__ import annotations

import os
import sys


def default_app_dir(kind: str) -> str:
    """Persistent per-user folder for HeLab's ``"caches"`` or ``"temps"``.

    macOS ``~/Library/Caches/HeLab``, Windows ``%LOCALAPPDATA%\\HeLab``, otherwise
    ``$XDG_CACHE_HOME/HeLab`` (``~/.cache/HeLab``). Unlike the system temp folder,
    the OS does not delete these after a few days without use.
    """
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        base = os.path.join(home, "Library", "Caches")
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
    return os.path.join(base, "HeLab", kind)


def app_folder() -> str:
    """The per-user app folder, outside every cache: the cache-move record and the locks."""
    return os.environ.get("HELAB_APP_DIR_OVERRIDE") or os.path.dirname(default_app_dir("caches"))
