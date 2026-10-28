"""Shared bits of the converter's dev scripts (``dev/txy/``): the import guard and arguments.

Run from the checkout's root, after ``source .ai/local/floor-env.sh`` (or with
``HELAB_DIR_CACHES_OVERRIDE``, ``HELAB_DIR_TEMPS_OVERRIDE`` and ``HELAB_APP_DIR_OVERRIDE`` set):
the scripts import helab, and AGENTS.md wants those set first. They read the sample set
(``~/HeLab-samples/txy-v1/``, read-only) and write only under ``.ai/temp/txy/``.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
TEMP = ROOT / ".ai" / "temp" / "txy"
OVERRIDES = ("HELAB_DIR_CACHES_OVERRIDE", "HELAB_DIR_TEMPS_OVERRIDE", "HELAB_APP_DIR_OVERRIDE")


def guard() -> None:
    missing = [name for name in OVERRIDES if not os.environ.get(name)]
    if missing:
        sys.exit(f"Set {', '.join(missing)} first (source .ai/local/floor-env.sh)")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def sample_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default="~/HeLab-samples/txy-v1", help="the sample set (read only)")
    parser.add_argument("--positions", choices=("even", "odd", "all"), default="even",
                        help="shots at even (held-in), odd (held-out) or all positions of each set")
    parser.add_argument("--sets", nargs="*", help="only these sets")
    parser.add_argument("--limit", type=int, help="at most this many shots per set")
    parser.add_argument("--profile", default="matlab-2019")
    parser.add_argument("--backend", default="reference")
