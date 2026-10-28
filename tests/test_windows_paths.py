"""Every tracked path can be checked out on Windows.

A reserved device name (``CON``, ``PRN``, ``AUX``, ``NUL``, ``COM1``–``COM9``, ``LPT1``–``LPT9``,
with any extension, in any case), a character Windows refuses (``<>:"|?*`` or a control
character) or a name ending in a dot or a space makes ``git checkout`` fail on Windows, so every
Windows CI job fails before a test runs (``nul.txt``, 2026-10-29).
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.IGNORECASE)
REFUSED = re.compile(r'[<>:"|?*\x00-\x1f]')


def windows_problem(part: str) -> str | None:
    if RESERVED.match(part):
        return "a reserved device name"
    if REFUSED.search(part):
        return "a character Windows refuses"
    if part.endswith((".", " ")):
        return "a trailing dot or space"
    return None


def test_the_rule_catches_what_windows_refuses() -> None:
    for bad in ("nul.txt", "NUL", "Con.tar.gz", "com1.txt", "lpt9", "aux.", "a:b", "what?", "x|y", "end ", "end."):
        assert windows_problem(bad), bad
    for good in ("nul_padding.txt", "comma_nul.txt", "console.py", "com10.txt", "lpt0", "auxiliary", ".gitattributes"):
        assert windows_problem(good) is None, good


def test_every_tracked_path_is_valid_on_windows() -> None:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, timeout=60, check=True)
    bad = [f"{path} ({problem})" for path in listed.stdout.decode("utf-8", errors="replace").split("\0") if path
           for problem in [next((p for p in map(windows_problem, path.split("/")) if p), None)] if problem]
    assert bad == []
