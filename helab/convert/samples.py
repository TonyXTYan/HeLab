"""The converter's sample set: a folder of raw ``d<N>.txt`` and MATLAB's ``d_txy_forc<N>.txt``
per set, described by ``manifest.json`` (``~/HeLab-samples/txy-v1/``, Q8.6). Every file read
through ``read_verified`` is checked against its SHA-256 first.

The manifest: ``{"source_share": …, "sets": {name: {"source": …, "shots_in_source": n,
"shots": [{"shot": N, "raw_sha256": …, "txy_sha256": …, "raw_bytes": …}, …]}}}``.

Held-out shots (stage 1's brief): the builder develops on the shots at even positions of each
set's list, the cross-checker checks the odd ones first.

Tests never read the sample set (tests never touch real data); they use a manifest they write.

Qt-free; standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, Literal

DEFAULT_ROOT = Path("~/HeLab-samples/txy-v1")
MANIFEST = "manifest.json"
Positions = Literal["even", "odd", "all"]


class SampleError(ValueError):
    """The manifest is malformed, or a file isn't the one it names."""


@dataclass(frozen=True)
class SampleShot:
    set_name: str
    position: int
    shot: int
    raw_path: Path
    txy_path: Path
    raw_sha256: str
    txy_sha256: str
    raw_bytes: int

    @property
    def label(self) -> str:
        return f"{self.set_name}/d{self.shot}"


@dataclass(frozen=True)
class SampleSet:
    name: str
    source: str
    shots_in_source: int
    shots: tuple[SampleShot, ...]

    def select(self, positions: Positions = "all") -> list[SampleShot]:
        if positions == "all":
            return list(self.shots)
        parity = 0 if positions == "even" else 1
        return [shot for shot in self.shots if shot.position % 2 == parity]


def load_manifest(root: str | os.PathLike[str] = DEFAULT_ROOT) -> list[SampleSet]:
    folder = Path(root).expanduser()
    try:
        data = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        sets = data["sets"]
        out = []
        for name, entry in sets.items():
            shots = tuple(
                SampleShot(set_name=name, position=position, shot=int(item["shot"]),
                           raw_path=folder / name / f"d{int(item['shot'])}.txt",
                           txy_path=folder / name / f"d_txy_forc{int(item['shot'])}.txt",
                           raw_sha256=str(item["raw_sha256"]), txy_sha256=str(item["txy_sha256"]),
                           raw_bytes=int(item["raw_bytes"]))
                for position, item in enumerate(entry["shots"]))
            out.append(SampleSet(name=name, source=str(entry["source"]),
                                 shots_in_source=int(entry["shots_in_source"]), shots=shots))
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SampleError(f"Can't read the sample manifest in {folder}: {error!r}") from error
    return out


def select_shots(sets: Iterable[SampleSet], positions: Positions = "all",
                 names: Iterable[str] | None = None) -> list[SampleShot]:
    wanted = None if names is None else set(names)
    return [shot for sample_set in sets if wanted is None or sample_set.name in wanted
            for shot in sample_set.select(positions)]


def read_verified(path: str | os.PathLike[str], sha256: str) -> bytes:
    data = Path(path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        raise SampleError(f"{path} has SHA-256 {digest}, the manifest says {sha256}")
    return data
