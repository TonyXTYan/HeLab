# tests/test_status_worker.py:

import unittest
from PyQt6.QtCore import QCoreApplication, QThreadPool
from helab.workers.statusWorker import StatusWorker

class TestStatusWorker(unittest.TestCase):
    def setUp(self):
        self.app = QCoreApplication([])
        self.threadpool = QThreadPool()

    def test_worker_emits_finished_signal(self):
        worker = StatusWorker("test_file.txt")
        self.signal_received = False

        def on_finished(file_path, status, count, extra_icons):
            self.signal_received = True
            self.assertEqual(file_path, "test_file.txt")
            self.assertIn(status, ['ok', 'warning', 'critical', 'nothing'])
            self.assertIsInstance(count, int)
            self.assertIsInstance(extra_icons, list)

        worker.signals.finished.connect(on_finished)
        self.threadpool.start(worker)

        while not self.signal_received:
            self.app.processEvents()

    def test_worker_can_be_canceled(self):
        worker = StatusWorker("test_file.txt")
        worker.cancel()
        self.signal_received = False

        def on_finished(file_path, status, count, extra_icons):
            self.signal_received = True

        worker.signals.finished.connect(on_finished)
        self.threadpool.start(worker)

        self.app.processEvents()
        self.assertFalse(self.signal_received)

if __name__ == '__main__':
    unittest.main()