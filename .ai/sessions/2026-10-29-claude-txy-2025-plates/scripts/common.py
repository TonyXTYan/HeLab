"""Shared helpers for the 2025-plate investigation (session 2026-10-29-claude-txy-2025-plates).

Data is read-only: ~/HeLab-samples/{txy-2026,txy-v1,calib-v1,calib-2026}. Outputs go to this
session folder (figures/, *.json, *.csv) and the scratch folder. Before importing helab, call
helab_env() (sets the folder overrides AGENTS.md asks for).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SESSION = Path(__file__).resolve().parents[1]
FIG = SESSION / "figures"
OUT = SESSION / "out"
REPO = SESSION.parents[2]
SCRATCH = Path("/private/tmp/claude-501/-Users-tonyyan-GitHub-Local-HeLab--maestri-roles-19b8c99f-4d6b-42f4-a5aa-41fc8efbfedd/"
               "839a6ef5-0afc-40b3-bf0f-0a9378eb2d7f/scratchpad/c26inv")
SAMPLES = Path.home() / "HeLab-samples"
BIN = 25e-12
V_PERP = 5.2632e5
M_PER_BIN = V_PERP * BIN  # metres of X per bin of x1 - x2 (matlab-2019)


def helab_env() -> None:
    for name, sub in (("HELAB_APP_DIR_OVERRIDE", "app"), ("HELAB_DIR_CACHES_OVERRIDE", "caches"),
                      ("HELAB_DIR_TEMPS_OVERRIDE", "temps")):
        p = SCRATCH / "helab" / sub
        p.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault(name, str(p))
    os.environ.setdefault("HELAB_TEST_SETTINGS_FILE", str(SCRATCH / "helab" / "settings.ini"))
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))


def shot_number(path: Path | str) -> int:
    m = re.search(r"(\d+)\.txt$", str(path))
    return int(m.group(1)) if m else -1


def read_raw(path: Path | str) -> tuple[np.ndarray, np.ndarray]:
    """Channels and times (int64 bins), in file order."""
    df = pd.read_csv(path, header=None, names=["c", "t"], dtype={"c": np.int64, "t": np.int64})
    return df["c"].to_numpy(), df["t"].to_numpy()


def read_txy(path: Path | str) -> np.ndarray:
    if os.path.getsize(path) == 0:
        return np.zeros((0, 3))
    # on_bad_lines="skip": one MATLAB TXY in the 2026-07 tight-trap set has a corrupted 4-field line
    return pd.read_csv(path, header=None, names=["T", "X", "Y"], dtype=np.float64, on_bad_lines="skip").to_numpy()


def raw_files(folder: Path) -> list[Path]:
    return sorted((p for p in folder.rglob("d*.txt") if re.fullmatch(r"d\d+\.txt", p.name)), key=shot_number)


def txy_files(folder: Path) -> list[Path]:
    return sorted(folder.rglob("d_txy_forc*.txt"), key=shot_number)


def parse_labview_log(path: Path) -> pd.DataFrame:
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        d = {}
        for part in line.split(", "):
            if ":" in part:
                k, v = part.split(":", 1)
                d[k.strip()] = v.strip()
        if "shot n_um" in d:  # the 2026-06-20 LabVIEW log spells it "shot n_um"
            d["shot num"] = d.pop("shot n_um")
        if "shot num" in d:
            rows.append(d)
    df = pd.DataFrame(rows)
    df["shot"] = df["shot num"].astype(int)
    df["posix"] = df["posixtime"].astype(float)
    return df


def figure(w: float = 7, h: float = 4.5):
    from matplotlib.figure import Figure
    return Figure(figsize=(w, h), dpi=120, layout="constrained")


def save(fig, name: str) -> Path:
    FIG.mkdir(parents=True, exist_ok=True)
    p = FIG / name
    fig.savefig(p)
    return p
