# test_statusDeepWorker.py

import os
import pytest
import logging
from PyQt6.QtCore import QDir, QEventLoop
from pytestqt.qtbot import QtBot

from helab.workers.statusDeepWorker import StatusDeepWorker
from helab.utils.threadingSetup import running_workers_deep, running_workers_status


@pytest.mark.usefixtures("qtbot")
class TestStatusDeepWorker:
    def teardown_method(self) -> None:
        for workerS in running_workers_status.values():
            workerS.cancel()
        running_workers_status.clear()

        for workerD in running_workers_deep.values():
            workerD.cancel()
        running_workers_deep.clear()

        running_workers_deep.clear()

    def test_no_subdirs(self, tmp_path: str, qtbot: QtBot) -> None:
        """
        Test a folder with no subdirectories => worker emits an empty list.
        """
        folder_path = QDir(str(tmp_path)).filePath("empty_parent")
        QDir().mkpath(folder_path)

        worker = StatusDeepWorker(folder_path)
        with qtbot.waitSignal(worker.signals.finished, timeout=2000) as blocker:
            worker.run()

        root_path, subdirs = blocker.args  # type: ignore[reportGeneralTypeIssues, unused-ignore]
        assert root_path == folder_path
        assert subdirs == []

    def test_multiple_subdirs(self, tmp_path: str, qtbot: QtBot) -> None:
        """
        Test a folder with multiple subdirectories => worker emits all of them.
        """
        folder_path = QDir(str(tmp_path)).filePath("some_parent")
        QDir().mkpath(folder_path)

        # Create 3 subdirs
        for i in range(3):
            QDir().mkpath(QDir(folder_path).filePath(f"subdir_{i}"))

        # Also create a file
        with open(QDir(folder_path).filePath("file.txt"), "w") as f:
            f.write("just a file")

        worker = StatusDeepWorker(folder_path)
        with qtbot.waitSignal(worker.signals.finished, timeout=2000) as blocker:
            worker.run()

        root_path, subdirs = blocker.args  # type: ignore[reportGeneralTypeIssues, unused-ignore]
        assert root_path == folder_path
        # We expect exactly the 3 subdirs
        subdirs_set = set(subdirs)
        expected = {QDir(folder_path).filePath("subdir_0"),
                    QDir(folder_path).filePath("subdir_1"),
                    QDir(folder_path).filePath("subdir_2")}
        assert subdirs_set == expected

    def test_cancel_worker(self, tmp_path: str, qtbot: QtBot) -> None:
        """
        Test that if we cancel the worker before it runs, we get an empty list (or no BFS).
        """
        folder_path = QDir(str(tmp_path)).filePath("canceled_parent")
        QDir().mkpath(folder_path)

        worker = StatusDeepWorker(folder_path)
        worker.cancel()

        with qtbot.waitSignal(worker.signals.finished, timeout=2000) as blocker:
            worker.run()

        root_path, subdirs = blocker.args  # type: ignore[reportGeneralTypeIssues, unused-ignore]
        assert root_path == folder_path
        # Because it was canceled, we expect subdirs = []
        assert len(subdirs) == 0