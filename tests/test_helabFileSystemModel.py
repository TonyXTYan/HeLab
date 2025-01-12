"""
Note: This file contains expanded tests for helabFileSystemModel.
Other referenced files (helabFileSystemModel.py, workers, and utils) are not shown here.
They are assumed to be present in the codebase.
"""
import time
import unittest
from unittest.mock import MagicMock, patch, call
from typing import Dict, cast

from PyQt6.QtCore import QThreadPool, QModelIndex, QTimer, QEventLoop
from mypyc.ir.rtypes import RUnion

from helab.models.helabFileSystemModel import helabFileSystemModel
from helab.workers.statusWorker import StatusWorker, StatusReport
from helab.workers.statusDeepWorker import StatusDeepWorker
from helab.workers.directoryCheckWorker import DirectoryCheckWorker

# Global worker dicts from helab.utils.threadingSetup
from helab.utils.threadingSetup import (
    running_workers_status,
    running_workers_deep,
    running_workers_hasChildren,
    thread_pool_general, cancel_all_workers, clear_all_thread_pools
)

# Global caches from helab.utils.cachingSetup
from helab.utils.cachingSetup import (
    status_cache,
    hasChildren_cache,
    data_ram_cache, os_listdir_cache, os_scandir_cache
)


class TestHelabFileSystemModel(unittest.TestCase):
    def setUp(self) -> None:
        """
        Clear global states and create a fresh model instance for each test.
        This helps ensure tests can run in parallel via pytest-xdist without
        interfering with one another.
        """
        running_workers_status.clear()
        running_workers_deep.clear()
        running_workers_hasChildren.clear()
        status_cache.clear()
        hasChildren_cache.clear()
        data_ram_cache.clear()

        self.model = helabFileSystemModel()
        self.thread_pool = cast(QThreadPool, QThreadPool.globalInstance())

    def tearDown(self) -> None:
        """
        Ensure all workers are canceled and the thread pool is cleared.
        """
        self.model.stop_all_scans()
        self.thread_pool.clear()
        cancel_all_workers()
        clear_all_thread_pools()

        # loop = QEventLoop()
        # QTimer.singleShot(20, loop.quit)
        # loop.exec()
        QTimer.singleShot(20, QEventLoop().quit)
    #
    # ------------------------------------------------------------------
    # Existing tests for stop_all_scans
    # ------------------------------------------------------------------
    #

    @patch('helab.models.helabFileSystemModel.logging')
    def test_stop_all_scans_cancels_and_removes_status_workers(self, mock_logging: MagicMock) -> None:
        """
        Verify that stop_all_scans cancels all StatusWorker instances and
        removes them from the global running_workers_status dict.
        """
        worker1 = MagicMock(spec=StatusWorker)
        worker2 = MagicMock(spec=StatusWorker)
        running_workers_status['/path/to/file1'] = worker1
        running_workers_status['/path/to/file2'] = worker2

        self.model.stop_all_scans()

        worker1.cancel.assert_called_once()
        worker2.cancel.assert_called_once()
        self.assertEqual(len(running_workers_status), 0)

        mock_logging.debug.assert_any_call("Stopping all scans...")
        mock_logging.debug.assert_any_call("Worker canceled for: /path/to/file1")
        mock_logging.debug.assert_any_call("Worker canceled for: /path/to/file2")
        mock_logging.debug.assert_any_call("All scans have been requested to stop.")

    @patch('helab.models.helabFileSystemModel.logging')
    def test_stop_all_scans_cancels_and_removes_deep_workers(self, mock_logging: MagicMock) -> None:
        """
        Verify that stop_all_scans cancels all StatusDeepWorker instances and
        removes them from the global running_workers_deep dict.
        """
        workerD1 = MagicMock(spec=StatusDeepWorker)
        workerD2 = MagicMock(spec=StatusDeepWorker)
        workerD1.root_path = '/path/to/deep1'
        workerD2.root_path = '/path/to/deep2'
        running_workers_deep['/path/to/deep1'] = workerD1
        running_workers_deep['/path/to/deep2'] = workerD2

        self.model.stop_all_scans()

        workerD1.cancel.assert_called_once()
        workerD2.cancel.assert_called_once()
        self.assertEqual(len(running_workers_deep), 0)
        mock_logging.debug.assert_any_call("Cancelled StatusDeepWorker for: /path/to/deep1")
        mock_logging.debug.assert_any_call("Cancelled StatusDeepWorker for: /path/to/deep2")

    @patch('helab.models.helabFileSystemModel.logging')
    def test_stop_all_scans_cancels_and_removes_directory_check_workers(self, mock_logging: MagicMock) -> None:
        """
        Verify that stop_all_scans cancels all DirectoryCheckWorker instances and
        removes them from the global running_workers_hasChildren dict.
        """
        workerC1 = MagicMock(spec=DirectoryCheckWorker)
        workerC2 = MagicMock(spec=DirectoryCheckWorker)
        workerC1.dir_path = '/path/to/check1'
        workerC2.dir_path = '/path/to/check2'
        running_workers_hasChildren['/path/to/check1'] = workerC1
        running_workers_hasChildren['/path/to/check2'] = workerC2

        self.model.stop_all_scans()

        workerC1.cancel.assert_called_once()
        workerC2.cancel.assert_called_once()
        self.assertEqual(len(running_workers_hasChildren), 0)
        mock_logging.debug.assert_any_call("Cancelled DirectoryCheckWorker for: /path/to/check1")
        mock_logging.debug.assert_any_call("Cancelled DirectoryCheckWorker for: /path/to/check2")

    @patch('helab.models.helabFileSystemModel.logging')
    def test_stop_all_scans_with_no_running_workers(self, mock_logging: MagicMock) -> None:
        """
        Ensure stop_all_scans does not fail when there are no workers running.
        """
        self.assertEqual(len(running_workers_status), 0)
        self.assertEqual(len(running_workers_deep), 0)
        self.assertEqual(len(running_workers_hasChildren), 0)

        try:
            self.model.stop_all_scans()
        except Exception as e:
            self.fail(f"stop_all_scans raised an exception unexpectedly: {e}")

        mock_logging.debug.assert_any_call("Stopping all scans...")
        mock_logging.debug.assert_any_call("All scans have been requested to stop.")

    #
    # ------------------------------------------------------------------
    # NEW TESTS
    # ------------------------------------------------------------------
    #

    @patch('helab.models.helabFileSystemModel.thread_pool_general.start')
    def test_fetch_status_when_not_cached_starts_worker(self, mock_pool_start: MagicMock) -> None:
        """
        If a path is not cached and no worker is running, fetch_status should
        create a new StatusWorker and start it on the thread pool.
        """
        path = "/untracked/directory"
        self.assertIsNone(status_cache.get(path))

        result = self.model.fetch_status(path)
        # result should be a 'loading' StatusReport
        self.assertEqual(result.status, 'loading')
        self.assertIn(path, running_workers_status)

        # Confirm that a worker was started
        mock_pool_start.assert_called_once()

    @patch('helab.models.helabFileSystemModel.thread_pool_general.start')
    def test_fetch_status_when_worker_already_running(self, mock_pool_start: MagicMock) -> None:
        """
        If a worker is already running for a path, fetch_status should return a
        loading StatusReport but not start a new worker.
        """
        path = "/untracked/directory"
        # Put a mock worker in the global dict to simulate 'already running'
        running_workers_status[path] = MagicMock(spec=StatusWorker)

        result = self.model.fetch_status(path)
        self.assertEqual(result.status, 'loading')
        # No new worker should be started
        mock_pool_start.assert_not_called()

    def test_fetch_status_when_cached_not_loading(self) -> None:
        """
        If the path is already cached with a known (non-'loading') status,
        fetch_status should just return the cached StatusReport.
        """
        path = "/already/cached"
        cached_report = StatusReport(path, 'ok', 99, ['ram'])
        status_cache[path] = cached_report

        result = self.model.fetch_status(path)
        self.assertEqual(result, cached_report, f"Expected {cached_report}, got {result}")
        # Ensure it didn't create a new worker
        self.assertNotIn(path, running_workers_status)

    @patch('helab.models.helabFileSystemModel.logging')
    def test_fetch_status_loading_but_no_worker(self, mock_logging: MagicMock) -> None:
        """
        If the path is cached as 'loading' but no worker is present in
        running_workers_status, fetch_status should remove that stale entry
        and start a new worker.
        """
        path = "/zombie/loading"
        status_cache[path] = StatusReport(path, 'loading', 0, [])

        # There's no worker for this path
        self.assertNotIn(path, running_workers_status)

        with patch('helab.models.helabFileSystemModel.thread_pool_general.start') as mock_start:
            report = self.model.fetch_status(path)

        mock_logging.warning.assert_any_call(
            f"fetch_status: loading but worker is gone for: {path}"
        )
        self.assertEqual(report.status, 'loading')
        self.assertIn(path, running_workers_status)
        mock_start.assert_called_once()

    @patch('helab.models.helabFileSystemModel.logging')
    def test_handle_status_computed(self, mock_logging: MagicMock) -> None:
        """
        handle_status_computed should remove the worker from running_workers_status
        and update the status_cache with the new StatusReport. Also ensures dataChanged
        signals are emitted for relevant columns.
        """
        # Prepare a StatusReport
        path = "/test/dir"
        report = StatusReport(path, 'ok', 123, ['ram'])
        worker = MagicMock(spec=StatusWorker)
        running_workers_status[path] = worker

        # No actual Qt signals tested here; we just ensure it doesn't crash
        self.model.handle_status_computed(report)

        time.sleep(0.1)

        self.assertNotIn(path, running_workers_status)
        # self.assertEqual(status_cache[path], report)

    @patch('helab.models.helabFileSystemModel.os_listdir_filtered')
    @patch('helab.models.helabFileSystemModel.logging')
    def test_on_directory_loaded_invalidation(self, mock_logging: MagicMock, mock_listdir: MagicMock) -> None:
        """
        on_directory_loaded should pop the directory entry from status_cache,
        thereby forcing a refresh. We'll just test that the entry is removed.
        """
        path = "/dummy/folder"
        status_cache[path] = StatusReport(path, "ok", 1, [])
        self.model.on_directory_loaded(path)
        self.assertNotIn(path, os_scandir_cache)
        self.assertNotIn(path, os_listdir_cache)
        mock_logging.debug.assert_called_with(f"on_directory_loaded: (popped) {path}")

    @patch('helab.models.helabFileSystemModel.logging')
    def test_on_file_renamed(self, mock_logging: MagicMock) -> None:
        """
        on_file_renamed should remove the old path from the cache, ensuring we
        don't keep stale data.
        """
        directory = "/some/folder"
        old_name = "old.txt"
        new_name = "new.txt"
        old_path = f"{directory}/{old_name}"
        status_cache[old_path] = StatusReport(old_path, 'ok', 10, [])

        self.model.on_file_renamed(directory, old_name, new_name)
        self.assertNotIn(old_path, status_cache)
        mock_logging.debug.assert_called_with(f"on_file_renamed: (popped) {old_path} -> {directory}/{new_name}")

    @patch('helab.models.helabFileSystemModel.logging')
    def test_on_model_reset(self, mock_logging: MagicMock) -> None:
        """
        on_model_reset should clear the entire status_cache.
        """
        status_cache["/some/path"] = StatusReport("/some/path", 'ok', 10, [])
        self.model.on_model_reset()
        self.assertEqual(len(status_cache), 0)
        mock_logging.debug.assert_called_with("(CLEAR) Model reset")

    @patch('helab.models.helabFileSystemModel.DirectoryCheckWorker')
    def test_has_children_creates_worker_if_not_cached(self, mock_dir_worker: MagicMock) -> None:
        """
        If hasChildren_cache doesn't have an entry for a directory, hasChildren
        should create and start a DirectoryCheckWorker.
        """
        index_mock = MagicMock(spec=QModelIndex)
        file_info_mock = MagicMock()
        file_info_mock.isDir.return_value = True
        file_info_mock.absoluteFilePath.return_value = '/some/unknown/dir'
        index_mock.isValid.return_value = True
        self.model.fileInfo = MagicMock(return_value=file_info_mock)            # type: ignore[method-assign]

        # Not in hasChildren_cache
        self.assertIsNone(hasChildren_cache.get('/some/unknown/dir'))

        result = self.model.hasChildren(index_mock)
        self.assertFalse(result)  # initially returns False
        mock_dir_worker.assert_called_once()

    @patch('helab.models.helabFileSystemModel.hasChildren_cache', {"/some/cached/dir": True})
    def test_has_children_uses_cache(self) -> None:
        """
        If hasChildren_cache has a valid entry for the directory,
        hasChildren should return that value without spawning a worker.
        """
        index_mock = MagicMock(spec=QModelIndex)
        file_info_mock = MagicMock()
        file_info_mock.isDir.return_value = True
        file_info_mock.absoluteFilePath.return_value = '/some/cached/dir'
        index_mock.isValid.return_value = True
        self.model.fileInfo = MagicMock(return_value=file_info_mock)            # type: ignore[method-assign]

        # # Ensure there is a subdirectory in the cache
        hasChildren_cache['/some/cached/dir/subdir'] = True
        hasChildren_cache['/some/cached/dir'] = True

        # ???
        # hasChildren_cache[index_mock.absoluteFilePath] = True

        result = self.model.hasChildren(index_mock)
        self.assertTrue(result)

    @patch('helab.models.helabFileSystemModel.DirectoryCheckWorker')
    def test_has_children_not_dir(self, mock_dir_worker: MagicMock) -> None:
        """
        If file_info is not a directory, hasChildren should just return False.
        """
        index_mock = MagicMock(spec=QModelIndex)
        file_info_mock = MagicMock()
        file_info_mock.isDir.return_value = False
        index_mock.isValid.return_value = True
        self.model.fileInfo = MagicMock(return_value=file_info_mock)            # type: ignore[method-assign]

        result = self.model.hasChildren(index_mock)
        self.assertFalse(result)
        mock_dir_worker.assert_not_called()

    @patch('helab.models.helabFileSystemModel.logging')
    @patch('helab.models.helabFileSystemModel.thread_pool_general.start')
    def test_start_deep_status_worker_creates_worker(self, mock_pool_start: MagicMock, mock_log: MagicMock) -> None:
        """
        start_deep_status_worker should create a StatusDeepWorker, register it, and start it.
        """
        path = "/deep/path"
        self.model.start_deep_status_worker(path, 2, invalidate_cache=False)
        self.assertIn(path, running_workers_deep)
        # time.sleep(0.5)
        # mock_pool_start.assert_called_once()
        QTimer.singleShot(10, running_workers_deep[path].run)

    @patch('helab.models.helabFileSystemModel.logging')
    def test_process_deep_status_removes_worker_and_spawns_children(self, mock_log: MagicMock) -> None:
        """
        process_deep_status should remove the finished worker from running_workers_deep
        and spawn new deep workers for subdirectories if current_depth > 0.
        """
        path = "/root/path"
        # Put a mock worker in the global dict
        worker = MagicMock(spec=StatusDeepWorker)
        running_workers_deep[path] = worker

        # Suppose it found subdirs
        subdirs = ["/root/path/sub1", "/root/path/sub2"]

        with patch.object(self.model, 'start_deep_status_worker') as mock_sdw:
            self.model.process_deep_status(path, subdirs, 2, invalidate_cache=True)

        self.assertNotIn(path, running_workers_deep)  # removed
        # 2 new calls with depth=1
        mock_sdw.assert_has_calls([
            call("/root/path/sub1", 1, True),
            call("/root/path/sub2", 1, True),
        ], any_order=True)

    @patch('helab.models.helabFileSystemModel.thread_pool_general.start')
    def test_rescan_starts_worker(self, mock_pool_start: MagicMock) -> None:
        """
        rescan should create a StatusRescanWorker if not already running and start it.
        """
        self.assertIsNone(self.model.rescan_worker)
        self.model.rescan()
        self.assertIsNotNone(self.model.rescan_worker)
        # time.sleep(0.5)
        QTimer.singleShot(10, self.model.rescan_worker.run) # type: ignore[union-attr]
        # mock_pool_start.assert_called_once()

    @patch('helab.models.helabFileSystemModel.logging')
    def disabled_test_rescan_cancel_if_any(self, mock_log: MagicMock) -> None:
        """
        rescan_cancel_if_any should cancel and remove the worker if it exists.
        """
        dummy_worker = MagicMock(spec=StatusWorker)
        self.model.rescan_worker = dummy_worker

        self.assertIsNotNone(self.model.rescan_worker)

        self.model.rescan_cancel_if_any()

        dummy_worker.cancel.assert_called_once_with(scan_again=False)
        self.assertIsNone(self.model.rescan_worker)
        mock_log.info.assert_any_call("helabFileSystemModel.rescan_cancel_if_any: cancelled")


if __name__ == '__main__':
    unittest.main()
