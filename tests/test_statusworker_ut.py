# tests/test_status_worker.py:
import time
import unittest
from PyQt6.QtCore import QCoreApplication, QThreadPool
from PyQt6.QtTest import QSignalSpy, QTest
from helab.workers.statusWorker import StatusWorker

class TestStatusWorker(unittest.TestCase):
    app: QCoreApplication
    threadpool: QThreadPool

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication([])
        thread_pool = QThreadPool.globalInstance()
        cls.threadpool = thread_pool if thread_pool is not None else QThreadPool()
        # cls.threadpool = QThreadPool()
        cls.threadpool.setMaxThreadCount(4)
        cls.threadpool.waitForDone()

    @classmethod
    def tearDownClass(cls) -> None:
        # QTest.qWait(100)  # Wait for 100ms to process events
        # cls.app.quit()
        # del cls.app
        # del cls.threadpool
        try:
            # QTest.qWait(100)  # Wait to process events
            time.sleep(0.05)
            # QThreadPool.globalInstance().deleteLater()
            # QThreadPool.globalInstance().clear()
            # QThreadPool.globalInstance().waitForDone()
            while not cls.threadpool.activeThreadCount() == 0: time.sleep(0.05)
            cls.app.quit()
            del cls.app
            # del cls.threadpool
            time.sleep(0.05)
        except Exception:
            pass

    def test_worker_emits_finished_signal(self) -> None:
        worker = StatusWorker("/")
        spy = QSignalSpy(worker.signals.finished)
        self.threadpool.waitForDone()
        self.threadpool.start(worker)

        if not spy.wait(1000):  # wait for up to this many ms
            self.fail("Timeout waiting for finished signal")

        self.assertEqual(len(spy), 1)
        args = spy[0]
        self.assertEqual(args[0], "/")
        self.assertIn(args[1], ['ok', 'warning', 'critical', 'nothing'])
        self.assertIsInstance(args[2], int)
        self.assertIsInstance(args[3], list)

    def test_worker_can_be_canceled(self) -> None:
        worker = StatusWorker("test_file.txt")
        worker.cancel()
        spy = QSignalSpy(worker.signals.finished)
        self.threadpool.waitForDone()
        self.threadpool.start(worker)

        self.app.processEvents()
        self.assertFalse(spy.wait(1000))  # wait for up to 1 second

if __name__ == '__main__':
    unittest.main()