# test_statusDeepWorker.py

import os
import pytest
import logging
from pathlib import Path

from PyQt6.QtCore import QEventLoop
from pytestqt.qtbot import QtBot

from helab.workers.statusDeepWorker import StatusDeepWorker
from helab.utils.threadingSetup import running_workers_deep

@pytest.mark.usefixtures("qtbot")
class TestStatusDeepWorker:
    def teardown_method(self) -> None:
        running_workers_deep.clear()

    def test_no_subdirs(self, tmp_path: Path, qtbot: QtBot) -> None:
        """
        Test a folder with no subdirectories => worker emits an empty list.
        """
        folder_path = tmp_path / "empty_parent"
        folder_path.mkdir()

        worker = StatusDeepWorker(str(folder_path))
        with qtbot.waitSignal(worker.signals.finished, timeout=2000) as blocker:
            worker.run()

        root_path, subdirs = blocker.args       # type: ignore[reportGeneralTypeIssues, unused-ignore]
        assert root_path == str(folder_path)
        assert subdirs == []

    def test_multiple_subdirs(self, tmp_path: Path, qtbot: QtBot) -> None:
        """
        Test a folder with multiple subdirectories => worker emits all of them.
        """
        folder_path = tmp_path / "some_parent"
        folder_path.mkdir()

        # Create 3 subdirs
        for i in range(3):
            (folder_path / f"subdir_{i}").mkdir()

        # Also create a file
        (folder_path / "file.txt").write_text("just a file")

        worker = StatusDeepWorker(str(folder_path))
        with qtbot.waitSignal(worker.signals.finished, timeout=2000) as blocker:
            worker.run()

        root_path, subdirs = blocker.args       # type: ignore[reportGeneralTypeIssues, unused-ignore]
        assert root_path == str(folder_path)
        # We expect exactly the 3 subdirs
        subdirs_set = set(subdirs)
        expected = {str(folder_path / "subdir_0"),
                    str(folder_path / "subdir_1"),
                    str(folder_path / "subdir_2")}
        assert subdirs_set == expected

    def test_cancel_worker(self, tmp_path: Path, qtbot: QtBot) -> None:
        """
        Test that if we cancel the worker before it runs, we get an empty list (or no BFS).
        """
        folder_path = tmp_path / "canceled_parent"
        folder_path.mkdir()

        worker = StatusDeepWorker(str(folder_path))
        worker.cancel()

        with qtbot.waitSignal(worker.signals.finished, timeout=2000) as blocker:
            worker.run()

        root_path, subdirs = blocker.args       # type: ignore[reportGeneralTypeIssues, unused-ignore]
        assert root_path == str(folder_path)
        # Because it was canceled, we expect subdirs = []
        # The code in run() typically emits (root_path, []), with special argument for depth if canceled
        # but in the posted code we see: "self.signals.finished.emit(self.root_path, directory_list, -100)"
        # or "self.signals.finished.emit(self.root_path, directory_list)"
        # So subdirs might be [] or something else. Let's check for empty.
        assert len(subdirs) == 0
