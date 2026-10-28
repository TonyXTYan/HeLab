"""Wording shared by the folder explorer (``FolderExplorer``), its Live controller
(``helab/views/explorer_live.py``) and the panels that describe a tab's loads."""
from __future__ import annotations

from helab.utils.number_format import byte_size


def plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def large_text(estimate: int, refused: bool) -> str:
    """How the summary line, Folder details and the status bar name a large folder."""
    if refused:
        return f"Too large to load · ~{byte_size(estimate)} in RAM, over 30% of RAM"
    return f"Large folder · ~{byte_size(estimate)} in RAM"
