# tests/test_status_worker.py:

import unittest
from PyQt6.QtCore import QCoreApplication, QThreadPool
from PyQt6.QtTest import QSignalSpy
from helab.workers.statusWorker import StatusWorker

class TestStatusWorker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication([])
        cls.threadpool = QThreadPool()

    @classmethod
    def tearDownClass(cls):
        cls.app.quit()
        del cls.app

    def test_worker_emits_finished_signal(self):
        worker = StatusWorker("test_file.txt")
        spy = QSignalSpy(worker.signals.finished)

        self.threadpool.start(worker)

        if not spy.wait(5000):  # wait for up to 5 seconds
            self.fail("Timeout waiting for finished signal")

        self.assertEqual(len(spy), 1)
        args = spy[0]
        self.assertEqual(args[0], "test_file.txt")
        self.assertIn(args[1], ['ok', 'warning', 'critical', 'nothing'])
        self.assertIsInstance(args[2], int)
        self.assertIsInstance(args[3], list)

    def test_worker_can_be_canceled(self):
        worker = StatusWorker("test_file.txt")
        worker.cancel()
        spy = QSignalSpy(worker.signals.finished)

        self.threadpool.start(worker)

        self.app.processEvents()
        self.assertFalse(spy.wait(1000))  # wait for up to 1 second

if __name__ == '__main__':
    unittest.main()