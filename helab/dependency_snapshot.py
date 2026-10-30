"""Send ``requirements.lock`` to GitHub's dependency graph (``.github/workflows/dependency-graph.yml``).

Dependabot reads ``requirements.txt`` (unpinned) but not ``requirements.lock``, and its own scan of
this repository can fail on a submodule (Q6.4), so the exact versions HeLab installs are submitted
as a snapshot through the dependency submission API: Dependabot alerts then cover them. A package
the lock says comes ``via -r requirements.txt`` is direct; the rest are indirect. Standard library
only, run by CI with ``gh`` (``python -m helab.dependency_snapshot --submit``).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

LOCK = "requirements.lock"
CORRELATOR = "helab-requirements-lock"
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)")


def locked(text: str) -> dict[str, tuple[str, bool]]:
    """Each pinned package in a ``uv pip compile`` lock: its version, and whether it is direct
    (listed in ``requirements.txt``). Names are normalised (PEP 503)."""
    packages: dict[str, tuple[str, bool]] = {}
    name = ""
    for line in text.splitlines():
        if match := _PIN.match(line):
            name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
            packages[name] = (match.group(2), False)
        elif name and line.startswith(" ") and "-r requirements.txt" in line:
            packages[name] = (packages[name][0], True)
        elif line and not line.startswith(" "):
            name = ""
    return packages


def snapshot(text: str, sha: str, ref: str, run_id: str, repository: str, scanned: str) -> dict[str, Any]:
    """The dependency submission API's snapshot of the lock."""
    resolved = {name: {"package_url": f"pkg:pypi/{name}@{version}",
                       "relationship": "direct" if direct else "indirect", "scope": "runtime"}
                for name, (version, direct) in sorted(locked(text).items())}
    return {"version": 0, "sha": sha, "ref": ref, "job": {"correlator": CORRELATOR, "id": run_id},
            "detector": {"name": "helab-dependency-snapshot", "version": "1",
                         "url": f"https://github.com/{repository}"},
            "scanned": scanned,
            "manifests": {LOCK: {"name": LOCK, "file": {"source_location": LOCK}, "resolved": resolved}}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true", help="POST it with gh (else print it)")
    args = parser.parse_args()
    repository = os.environ.get("GITHUB_REPOSITORY", "TonyXTYan/HeLab")
    body = snapshot(Path(LOCK).read_text(encoding="utf-8"), os.environ.get("GITHUB_SHA", ""),
                    os.environ.get("GITHUB_REF", ""), os.environ.get("GITHUB_RUN_ID", "local"), repository,
                    datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))
    if not args.submit:
        print(json.dumps(body, indent=2))
        return
    subprocess.run(["gh", "api", "--method", "POST", f"repos/{repository}/dependency-graph/snapshots",
                    "--input", "-"], input=json.dumps(body), text=True, check=True, timeout=120)


if __name__ == "__main__":
    main()
