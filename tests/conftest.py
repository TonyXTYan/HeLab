# tests/conftest.py
from typing import Iterator

import pytest

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
