"""Which analysis made a result: its stable ID, its declared version and its file's hash."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisIdentity:
    """``analysis_id`` never changes for an analysis; ``version`` is bumped by its author when
    its output changes; ``file_hash`` (SHA-256 of the script file as loaded, "" when the file
    couldn't be read, e.g. in a packaged build) catches edits that didn't bump it."""
    analysis_id: str
    version: str
    file_name: str = ""
    file_hash: str = ""

    def short(self) -> str:
        return f"{self.analysis_id} v{self.version}" if self.version else self.analysis_id

    def text(self) -> str:
        digest = f"sha256 {self.file_hash[:12]}" if self.file_hash else "hash unknown"
        return f"{self.short()} · {self.file_name or 'no file'} ({digest})"


def file_hash(path: str) -> str:
    """SHA-256 of a file's bytes, "" if it can't be read."""
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return ""


def file_name(path: str) -> str:
    return os.path.basename(path)
