# tests/conftest.py
import os
import tempfile
from typing import Iterator

import pytest

# Run Qt headless (offscreen) by default so tests don't pop up windows.
# Set HELAB_SHOW_GUI=1 to force a real, visible display (e.g. when a test
# genuinely needs to be watched/debugged interactively).
if not os.environ.get("HELAB_SHOW_GUI") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

# helab.utils.constants normally resolves DIR_TEMPS/DIR_CACHES from a
# QSettings value that's shared (and persisted) across every process on the
# machine, including other pytest-xdist workers running concurrently. That
# makes every process's status_cache/os_file_system_cache/data_ram_cache the
# *same* on-disk FanoutCache, so one worker's test clearing a cache in
# setUp() races another worker's test reading/writing it. Give this process
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

from helab.utils.threading_setup import cancel_all_workers


@pytest.fixture(autouse=True)
def _cancel_leftover_workers() -> Iterator[None]:
    yield
    # Tests that create HelabFileSystemModel/FolderExplorer/HelabMainWindow
    # instances without going through a full closeEvent (e.g. a test that
    # fails before its own teardown, or a widget never explicitly closed)
    # can leave persistent QRunnables (HelabFSModelThrottleDataChangedEmit)
    # looping in a shared QThreadPool. Those never return on their own, and
    # PyQt's atexit QThreadPool cleanup then blocks forever waiting for them
    # to finish, hanging the whole test process at interpreter shutdown.
    cancel_all_workers()
