# helab/utils/threading_setup.py
from __future__ import annotations
import logging
import os
import sys
import psutil
from typing import Dict, Tuple, TYPE_CHECKING, List

from PyQt6.QtCore import QCoreApplication, QThreadPool
from humanfriendly.terminal import message

from helab.utils.synchronised_dict import SynchronisedDict

logging.warn("threading_setup.py: initializing...")

if TYPE_CHECKING:
    from helab.workers.DirectoryCheckWorker import DirectoryCheckWorker
    from helab.workers.LoadFolderToRamWorker import LoadFolderToRamWorker
    from helab.workers.StatusDeepWorker import StatusDeepWorker
    from helab.workers.StatusWorker import StatusWorker
    from helab.workers.HelabFSModelThrottleDataChangedEmit import HelabFSModelThrottleDataChangedEmit

running_workers_status: SynchronisedDict[str, StatusWorker] = SynchronisedDict()
running_workers_deep: SynchronisedDict[str, StatusDeepWorker] = SynchronisedDict()
running_workers_hasChildren: SynchronisedDict[str, DirectoryCheckWorker] = SynchronisedDict()
running_workers_ramLoading: SynchronisedDict[str, LoadFolderToRamWorker] = SynchronisedDict()
running_workers_ThrottleDataChangedEmits: SynchronisedDict[str, HelabFSModelThrottleDataChangedEmit] = SynchronisedDict()

os_cpu_count = psutil.cpu_count(logical=False)
if os_cpu_count is None: os_cpu_count = 1
num_threads_half_os_cpu_count: int = int(max(2, round(os_cpu_count / 2)))
num_threads_quater_os_cpu_count: int = int(max(1, round(os_cpu_count / 4)))
logging.info(f"{os_cpu_count = }, {num_threads_half_os_cpu_count = }, {num_threads_quater_os_cpu_count = }")

thread_pool_general = QThreadPool()
thread_pool_general.setMaxThreadCount(num_threads_half_os_cpu_count)
logging.debug(f"thread_pool_general setup with .maxThreadCount = {num_threads_half_os_cpu_count}")

thread_pool_load_data_ram = QThreadPool()
thread_pool_load_data_ram.setMaxThreadCount(num_threads_quater_os_cpu_count)
logging.debug(f"thread_pool_load_data_ram setup with .maxThreadCount = {num_threads_quater_os_cpu_count}")

thread_pool_gui_update = QThreadPool()
thread_pool_gui_update.setMaxThreadCount(num_threads_half_os_cpu_count)
logging.debug(f"thread_pool_gui_update setup with .maxThreadCount = {num_threads_half_os_cpu_count}")

def pending_gui_update_calls() -> int:
    # total = 0
    # for workerE in running_workers_ThrottleDataChangedEmits.values():
    #     total += len(workerE.pending_updates)
    # return total
    return sum(len(w.pending_updates) for w in running_workers_ThrottleDataChangedEmits.values())


def running_worker_queues_len() -> Tuple[int,int,int,int,int]:
    return (
        len(running_workers_status),
        len(running_workers_deep),
        len(running_workers_hasChildren),
        len(running_workers_ramLoading),
        # len(running_workers_ThrottleDataChangedEmits),
        pending_gui_update_calls()
    )

def running_workers_persistent_queues_len() -> Tuple[int]:
    return (
        len(running_workers_ThrottleDataChangedEmits),
    )

def running_workers_single_run_queues_len() -> Tuple[int,int,int,int]:
    return (
        len(running_workers_status),
        len(running_workers_deep),
        len(running_workers_hasChildren),
        len(running_workers_ramLoading),
    )

def all_pools_total_activeThreadCount() -> int:
    return  thread_pool_general.activeThreadCount() + \
            thread_pool_load_data_ram.activeThreadCount() + \
            thread_pool_gui_update.activeThreadCount() + \
            getattr(QThreadPool.globalInstance(), 'activeThreadCount', lambda: 0)()
            # QThreadPool.globalInstance().activeThreadCount()

def single_run_pools_total_activeThreadCount() -> int:
    return  thread_pool_general.activeThreadCount() + \
            thread_pool_load_data_ram.activeThreadCount()

def emit_data_changed_signal(path: str) -> None:
    for e in running_workers_ThrottleDataChangedEmits.values():
        e.add_update(path)

# A cancel() call only sets a flag; a QRunnable that's already executing
# keeps running in its own thread until it notices the flag and returns.
# This is how long to block for that to happen so no cancelled worker
# outlives a clear/cancel call and races whatever runs next (e.g. a test's
# setUp() clearing these same global dicts, or the app exiting mid-worker).
WORKER_DRAIN_TIMEOUT_MS = 5000

def _wait_for_pools_to_drain() -> None:
    pools: Tuple[QThreadPool, ...] = (thread_pool_general, thread_pool_load_data_ram, thread_pool_gui_update)
    global_pool = QThreadPool.globalInstance()
    if global_pool is not None:
        pools += (global_pool,)

    # A worker finishing on its own thread delivers its "finished" signal to
    # the GUI thread via a queued connection, i.e. as a posted event that
    # only gets handled the next time the event loop turns. A plain
    # pool.waitForDone() blocks this (GUI) thread without turning that loop,
    # so any such signal sits queued until whenever the caller lets the loop
    # run again - by which point the receiver (e.g. a model/widget) may
    # already have been torn down, and the stale callback then crashes.
    # Poll instead of blocking, giving processEvents() a chance to deliver
    # each signal promptly, while its receiver is still known to be alive.
    STEP_MS = 10
    app = QCoreApplication.instance()
    elapsed_ms = 0
    while any(pool.activeThreadCount() > 0 for pool in pools):
        for pool in pools:
            pool.waitForDone(STEP_MS)
        if app is not None:
            app.processEvents()
        elapsed_ms += STEP_MS
        if elapsed_ms >= WORKER_DRAIN_TIMEOUT_MS:
            logging.warning(f"thread pool(s) did not drain within {WORKER_DRAIN_TIMEOUT_MS}ms")
            break

    # One final flush so signals from the very last workers to finish are
    # delivered before the caller proceeds (e.g. to delete the receiver).
    if app is not None:
        app.processEvents()

def clear_all_thread_pools() -> None:
    # QThreadPool.globalInstance().clear()
    getattr(QThreadPool.globalInstance(), 'clear', lambda: None)()  # emm ya just trying this way to do it
    thread_pool_general.clear()
    thread_pool_load_data_ram.clear()
    thread_pool_gui_update.clear()

    _wait_for_pools_to_drain()

    logging.info("All thread pools cleared.")


def cancel_all_workers() -> None:
    for workerE in running_workers_ThrottleDataChangedEmits.values():
        workerE.cancel()
    running_workers_ThrottleDataChangedEmits.clear()

    for workerS in running_workers_status.values():
        workerS.cancel()
    running_workers_status.clear()

    for workerD in running_workers_deep.values():
        workerD.cancel()
    running_workers_deep.clear()

    for workerC in running_workers_hasChildren.values():
        workerC.cancel()
    running_workers_hasChildren.clear()

    from helab.workers.LoadFolderToRamWorker import LoadFolderToRamWorker   # FIXME I don't like this
    for workerL in running_workers_ramLoading.values():
        workerL.cancel(message=LoadFolderToRamWorker.CANCEL_MSG_SHUTDOWN_REQUESTED)
    running_workers_ramLoading.clear()

    thread_pool_general.clear()
    thread_pool_load_data_ram.clear()
    thread_pool_gui_update.clear()

    _wait_for_pools_to_drain()

    logging.info("All workers cancelled.")


# TODO QRunnableCancellable