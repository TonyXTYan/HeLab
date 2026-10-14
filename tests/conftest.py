# tests/conftest.py
import os
import tempfile

# Run Qt headless (offscreen) by default so tests don't pop up windows.
# Set HELAB_SHOW_GUI=1 to force a real, visible display (e.g. when a test
# genuinely needs to be watched/debugged interactively).
if not os.environ.get("HELAB_SHOW_GUI") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

# helab.utils.constants normally resolves DIR_TEMPS/DIR_CACHES from a
# QSettings value that's shared (and persisted) across every process on the
# machine, including other pytest-xdist workers running concurrently. That
# makes every process's disk cache the *same* on-disk store, so one worker's
# test clearing a cache races another worker's test reading/writing it. Give this process
# its own private cache/temp dirs before helab.utils.constants (imported
# transitively below) ever computes DIR_TEMPS/DIR_CACHES.
#
# This must be an unconditional assignment, not setdefault(): the xdist
# *controller* process also imports this conftest (to collect tests) before
# it spawns worker subprocesses, and those workers inherit its environment.
# setdefault() would let the controller's one HELAB_DIR_*_OVERRIDE value leak
# into every worker unchanged, defeating the whole point of per-worker
# isolation. Each worker re-executes this module at its own startup, so an
# unconditional assignment here always lets it stomp the inherited value with
# a directory unique to itself.
_worker_id = os.environ.get("PYTEST_XDIST_WORKER", "main")
os.environ["HELAB_DIR_TEMPS_OVERRIDE"] = tempfile.mkdtemp(prefix=f"helab_test_temps_{_worker_id}_")
os.environ["HELAB_DIR_CACHES_OVERRIDE"] = tempfile.mkdtemp(prefix=f"helab_test_caches_{_worker_id}_")
os.environ["HELAB_APP_DIR_OVERRIDE"] = tempfile.mkdtemp(prefix=f"helab_test_app_{_worker_id}_")
# Tests write TXY files and load them at once; helpers would otherwise treat
# them as still being written. Settling has its own tests.
os.environ["HELAB_SETTLE_SECONDS"] = "0"


import pytest  # noqa: E402  (after the environment above is set)


@pytest.fixture(autouse=True)
def no_selection_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests select folders back to back and expect their loads at once; the wait for the
    selection to settle (Finish, Cancel) has its own tests, which set ``SETTLE_MAX`` again."""
    from helab.views.FolderExplorer import FolderExplorer
    monkeypatch.setattr(FolderExplorer, "SETTLE_MAX", 0.0)
