import unittest
import sys
from unittest.mock import MagicMock, patch
from typing import Dict, Tuple, List

from diskcache import FanoutCache

from helab.models.helabFileSystemModel import helabFileSystemModel
from helab.workers.directoryCheckWorker import DirectoryCheckWorker
from helab.workers.statusWorker import StatusWorker
from helab.workers.statusDeepWorker import StatusDeepWorker
from cachetools import LRUCache, TTLCache
from PyQt6.QtCore import QThreadPool

# helab/models/test_helabFileSystemModel.py

from helab.utils.cachingSetup import status_cache, hasChildren_cache


class TestHelabFileSystemModel(unittest.TestCase):
    def setUp(self) -> None:
        # Initialize the cache and thread pool
        # self.status_cache: FanoutCache
        # self.hasChildren_cache: FanoutCache
        self.thread_pool = QThreadPool()

        # Initialize the running_workers dictionaries
        self.running_workers_status: Dict[str, StatusWorker] = {}
        self.running_workers_deep: Dict[str, StatusDeepWorker] = {}
        self.running_workers_hasChildren: Dict[str, DirectoryCheckWorker] = {}

        # Create an instance of helabFileSystemModel
        self.model = helabFileSystemModel(
            status_cache=status_cache,
            hasChildren_cache=hasChildren_cache,
            thread_pool=self.thread_pool,
            running_workers_status=self.running_workers_status,
            running_workers_deep=self.running_workers_deep,
            running_workers_hasChildren=self.running_workers_hasChildren,
        )

    @patch('helab.models.helabFileSystemModel.logging')
    def test_stop_all_scans_cancels_and_removes_status_workers(self, mock_logging: MagicMock) -> None:
        # Create mock StatusWorker instances
        worker1 = MagicMock(spec=StatusWorker)
        worker2 = MagicMock(spec=StatusWorker)
        self.running_workers_status['/path/to/file1'] = worker1
        self.running_workers_status['/path/to/file2'] = worker2

        # Call stop_all_scans
        self.model.stop_all_scans()

        # Assert cancel was called on all status workers
        worker1.cancel.assert_called_once()
        worker2.cancel.assert_called_once()

        # Assert running_workers_status is empty
        self.assertEqual(len(self.model.running_workers_status), 0)

        # Assert logging messages
        mock_logging.debug.assert_any_call("Stopping all scans...")
        mock_logging.debug.assert_any_call("Worker canceled for: /path/to/file1")
        mock_logging.debug.assert_any_call("Worker canceled for: /path/to/file2")
        mock_logging.debug.assert_any_call("All scans have been requested to stop.")

    @patch('helab.models.helabFileSystemModel.logging')
    def test_stop_all_scans_cancels_and_removes_deep_workers(self, mock_logging: MagicMock) -> None:
        # Create mock StatusDeepWorker instances
        workerD1 = MagicMock(spec=StatusDeepWorker)
        workerD2 = MagicMock(spec=StatusDeepWorker)
        workerD1.root_path = '/path/to/deep1'
        workerD2.root_path = '/path/to/deep2'
        self.running_workers_deep['/path/to/deep1'] = workerD1
        self.running_workers_deep['/path/to/deep2'] = workerD2

        # Call stop_all_scans
        self.model.stop_all_scans()

        # Assert cancel was called on all deep workers
        workerD1.cancel.assert_called_once()
        workerD2.cancel.assert_called_once()

        # Assert running_workers_deep is empty
        self.assertEqual(len(self.model.running_workers_deep), 0)

        # Assert logging messages
        mock_logging.debug.assert_any_call("Cancelled StatusDeepWorker for: /path/to/deep1")
        mock_logging.debug.assert_any_call("Cancelled StatusDeepWorker for: /path/to/deep2")

    @patch('helab.models.helabFileSystemModel.logging')
    def test_stop_all_scans_with_no_running_workers(self, mock_logging: MagicMock) -> None:
        # Ensure no workers are running
        self.assertEqual(len(self.model.running_workers_status), 0)
        self.assertEqual(len(self.model.running_workers_deep), 0)

        # Call stop_all_scans
        try:
            self.model.stop_all_scans()
        except Exception as e:
            self.fail(f"stop_all_scans raised an exception unexpectedly: {e}")

        # Assert logging messages
        mock_logging.debug.assert_any_call("Stopping all scans...")
        mock_logging.debug.assert_any_call("All scans have been requested to stop.")

    @patch('helab.models.helabFileSystemModel.StatusDeepWorker')
    def test_start_deep_status_worker(self, mock_StatusDeepWorker: MagicMock) -> None:
        mock_worker_instance = MagicMock()
        mock_worker_instance.signals = MagicMock()
        mock_worker_instance.signals.finished = MagicMock()
        mock_worker_instance.signals.finished.connect = MagicMock()
        mock_StatusDeepWorker.return_value = mock_worker_instance

        root_path = '/test/root/path'
        self.model.start_deep_status_worker(root_path)

        # Assert that StatusDeepWorker is instantiated with correct arguments
        mock_StatusDeepWorker.assert_called_once_with(root_path, sys.maxsize)

        # Assert that signals.finished.connect is connected to process_deep_status
        mock_worker_instance.signals.finished.connect.assert_called_once_with(self.model.process_deep_status)

        # Assert that the worker is started via thread_pool.start
        # self.assertIn(mock_worker_instance, self.thread_pool.activeThreadCount())

        # Assert that the worker is added to running_workers_deep
        self.assertIn(root_path, self.model.running_workers_deep)
        self.assertEqual(self.model.running_workers_deep[root_path], mock_worker_instance)



if __name__ == '__main__':
    unittest.main()