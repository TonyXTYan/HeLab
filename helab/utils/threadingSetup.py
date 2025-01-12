# helab/utils/threadingSetup.py
from __future__ import annotations
import logging
import os
import sys
from typing import Dict, Tuple, TYPE_CHECKING, List

from PyQt6.QtCore import QThreadPool
from humanfriendly.terminal import message


logging.critical("threadingSetup.py: Loading")

if TYPE_CHECKING:
    from helab.workers.directoryCheckWorker import DirectoryCheckWorker
    from helab.workers.loadFolderToRamWorker import LoadFolderToRamWorker
    from helab.workers.statusDeepWorker import StatusDeepWorker
    from helab.workers.statusWorker import StatusWorker
    from helab.workers.helabFSModelThrottleDataChangedEmit import HeLabFSModelThrottleDataChangedEmit

running_workers_status: Dict[str, StatusWorker] = {}
running_workers_deep: Dict[str, StatusDeepWorker] = {}
running_workers_hasChildren: Dict[str, DirectoryCheckWorker] = {}
running_workers_ramLoading: Dict[str, LoadFolderToRamWorker] = {}
running_workers_ThrottleDataChangedEmits: Dict[str, HeLabFSModelThrottleDataChangedEmit] = {}

os_cpu_count = os.cpu_count()
if os_cpu_count is None: os_cpu_count = 1
num_threads_half_os_cpu_count: int = int(max(2, round(os_cpu_count / 2)))
logging.info(f"{os_cpu_count = }, {num_threads_half_os_cpu_count = }")

thread_pool_general = QThreadPool()
thread_pool_general.setMaxThreadCount(num_threads_half_os_cpu_count)

thread_pool_load_data_ram = QThreadPool()
thread_pool_load_data_ram.setMaxThreadCount(1)

thread_pool_gui_update = QThreadPool()
thread_pool_gui_update.setMaxThreadCount(num_threads_half_os_cpu_count)

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

def clear_all_thread_pools() -> None:
    # QThreadPool.globalInstance().clear()
    getattr(QThreadPool.globalInstance(), 'clear', lambda: None)()  # emm ya just trying this way to do it 
    thread_pool_general.clear()
    thread_pool_load_data_ram.clear()
    thread_pool_gui_update.clear()
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

    from helab.workers.loadFolderToRamWorker import LoadFolderToRamWorker   # FIXME I don't like this
    for workerL in running_workers_ramLoading.values():
        workerL.cancel(message=LoadFolderToRamWorker.CANCEL_MSG_SHUTDOWN_REQUESTED)
    running_workers_ramLoading.clear()

    thread_pool_general.clear()
    thread_pool_load_data_ram.clear()


    logging.info("All workers cancelled.")


# TODO QRunnableCancellable