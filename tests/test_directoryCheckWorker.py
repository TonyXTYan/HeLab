# test_directoryCheckWorker.py

import os
from pathlib import Path
from sqlite3 import Time
import pytest
import pytestqt

from PyQt6.QtCore import QEventLoop
from pytestqt.qtbot import QtBot

from helab.workers.directoryCheckWorker import DirectoryCheckWorker
from helab.utils.threadingSetup import running_workers_hasChildren


@pytest.mark.usefixtures("qtbot")
class TestDirectoryCheckWorker:
    def teardown_method(self) -> None:
        running_workers_hasChildren.clear()

    def test_has_children_false(self, tmp_path: Path, qtbot: QtBot) -> None:
        """
        Folder with no subdirectory => result = False.
        """
        folder_path = tmp_path / "no_subdirs"
        folder_path.mkdir()

        worker = DirectoryCheckWorker(str(folder_path))
        with qtbot.waitSignal(worker.signals.finished, timeout=2000) as blocker:
            worker.run()

        path_arg, has_children = blocker.args       # type: ignore[reportGeneralTypeIssues, unused-ignore]
        assert path_arg == str(folder_path)
        assert has_children is False

    def test_has_children_true(self, tmp_path: Path, qtbot: QtBot) -> None:
        """
        Folder with subdirectories => result = True.
        """
        folder_path = tmp_path / "has_subdirs"
        folder_path.mkdir()

        # Create a subdir
        (folder_path / "child1").mkdir()

        worker = DirectoryCheckWorker(str(folder_path))
        with qtbot.waitSignal(worker.signals.finished, timeout=2000) as blocker:
            worker.run()

        path_arg, has_children = blocker.args       # type: ignore[reportGeneralTypeIssues, unused-ignore]
        assert path_arg == str(folder_path)
        assert has_children is True

    def test_cancel_worker(self, tmp_path: Path, qtbot: QtBot) -> None:
        """
        Test that if we cancel the worker before it runs, it never emits a result.
        But since we forcibly call run(), it might just skip logic.
        We'll see if it yields no signal or an immediate return.
        For safety, let's check we can still handle it.
        """
        folder_path = tmp_path / "canceled_dir"
        folder_path.mkdir()

        worker = DirectoryCheckWorker(str(folder_path))
        worker.cancel()

        # If the worker is canceled, it might short-circuit.
        # We'll still wait a short time for a signal.
        # We can't rely on a canceled worker always never emitting.
        # We can do a try/except.
        with pytest.raises(pytestqt.exceptions.TimeoutError):   # type: ignore[reportAttributeAccessIssue, unused-ignore]
            # We expect NO signal => test that waitSignal times out
            with qtbot.waitSignal(worker.signals.finished, timeout=500) as blocker:
                worker.run()
            blocker.disconnect()                                # type: ignore[reportGeneralTypeIssues, unused-ignore]
        # If we get here, we confirm no signal was emitted in the given timeframe.
