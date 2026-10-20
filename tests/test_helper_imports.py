"""Browsing helpers stay light: listings and scans import no numpy, pandas, Blosc or Qt.

Only TXY reads (loads, cached reads, Live) import numpy and pandas, and only the icon
helper imports Qt, each inside the function that needs it (``helab/io_ops/``). A
listing on a slow share should start at once, and moving helper code into modules must
keep it that way.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

HEAVY = ("numpy", "pandas", "blosc", "PyQt6")

SCRIPT = """
import json, sys
import helab.io_helper  # noqa: F401  (the whole helper's imports, as every helper process starts)
from helab.io_ops.browse import list_folder
from helab.io_ops.scanning import scan
path, store = sys.argv[1], sys.argv[2]
events = []
for options in ({}, {"directory": store}):
    list_folder(path, events.append, options)
    scan(path, events.append, options, manual=True)
    scan(path, events.append, options, manual=False, automatic=True)
print(json.dumps({"events": [e.get("kind") for e in events],
                  "errors": [e for e in events if e.get("kind") == "error"],
                  "heavy": sorted(name for name in %r if name in sys.modules)}))
""" % (HEAVY,)


def test_listings_and_scans_import_no_numpy_pandas_blosc_or_qt(tmp_path: Path) -> None:
    folder = tmp_path / "run"
    (folder / "sub").mkdir(parents=True)
    for shot in range(3):
        (folder / f"d_txy_forc{shot}.txt").write_text("1,2,3\n", encoding="utf-8")
        (folder / f"d{shot}.txt").write_text("raw\n", encoding="utf-8")
    # Without the tests' real-data guard: its rules come from helab.utils.constants, which
    # imports Qt. Production helpers never run it, and this one reads only tmp_path.
    env = {key: value for key, value in os.environ.items() if key != "HELAB_TEST_SOURCE_GUARD"}
    done = subprocess.run([sys.executable, "-c", SCRIPT, str(folder), str(tmp_path / "store")],
                          capture_output=True, text=True, timeout=120, env=env)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout.splitlines()[-1])
    assert "entries" in result["events"] and "status" in result["events"], result["events"]
    assert result["errors"] == []
    assert result["heavy"] == [], f"Imported by browsing: {result['heavy']}"
