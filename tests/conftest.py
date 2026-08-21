# tests/conftest.py
import os
from typing import Iterator

import pytest

from helab.utils.threading_setup import cancel_all_workers

# Run Qt headless (offscreen) by default so tests don't pop up windows.
# Set HELAB_SHOW_GUI=1 to force a real, visible display (e.g. when a test
# genuinely needs to be watched/debugged interactively).
if not os.environ.get("HELAB_SHOW_GUI") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"


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
