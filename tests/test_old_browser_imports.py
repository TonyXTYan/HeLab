"""The old QFileSystemModel browser, deleted in roadmap session S3, stays out of the app."""
from __future__ import annotations

import json
import os
import subprocess
import sys

OLD_MODULES = (
    "helab.models.HelabFileSystemModel", "helab.models.LegacyStatusReport",
    "helab.views.StatusTreeView", "helab.views.StatusIconDelegate",
    "helab.workers", "helab.utils.os_cached", "helab.utils.threading_setup",
)


def test_main_window_imports_none_of_the_old_browser() -> None:
    # A fresh interpreter: this test process may already hold old modules from other tests.
    code = ("import json, sys\n"
            "import helab.main, helab.views.HelabMainWindow\n"
            "print(json.dumps(sorted(m for m in sys.modules if m.startswith('helab'))))\n")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, check=True)
    loaded = json.loads(result.stdout.strip().splitlines()[-1])
    assert "helab.views.HelabMainWindow" in loaded
    assert [m for m in loaded if m.startswith(OLD_MODULES)] == []
