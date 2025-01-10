import logging
import os
import sys
from typing import Dict, Tuple

from PyQt6.QtCore import QThreadPool

from helab.workers.directoryCheckWorker import DirectoryCheckWorker
from helab.workers.loadFolderToRamWorker import LoadFolderToRamWorker
from helab.workers.statusDeepWorker import StatusDeepWorker
from helab.workers.statusWorker import StatusWorker

running_workers_status: Dict[str, StatusWorker] = {}
running_workers_deep: Dict[str, StatusDeepWorker] = {}
running_workers_hasChildren: Dict[str, DirectoryCheckWorker] = {}
running_workers_ramLoading: Dict[str, LoadFolderToRamWorker] = {}

os_cpu_count = os.cpu_count()
if os_cpu_count is None: os_cpu_count = 1
num_threads_half_os_cpu_count: int = int(max(2, round(os_cpu_count / 2)))
logging.info(f"{os_cpu_count = }, {num_threads_half_os_cpu_count = }")


# thread_pool_global: QThreadPool
# thread_pool_global_instance = QThreadPool.globalInstance()
# if thread_pool_global_instance is None:
#     logging.fatal("QThreadPool.globalInstance() is None")
#     sys.exit(1)
#     # thread_pool_global = QThreadPool()
#     # QThreadPool.globalInstance(thread_pool_global)
# else:
#     thread_pool_global = thread_pool_global_instance
thread_pool_global = QThreadPool()
thread_pool_global.setMaxThreadCount(num_threads_half_os_cpu_count)


thread_pool_load_data_ram = QThreadPool()
thread_pool_load_data_ram.setMaxThreadCount(1)


def running_worker_queues_len() -> Tuple[int,int,int,int]:
    return (
        len(running_workers_status),
        len(running_workers_deep),
        len(running_workers_hasChildren),
        len(running_workers_ramLoading),
    )

def all_pools_total_activeThreadCount() -> int:
    return  thread_pool_global.activeThreadCount() + \
            thread_pool_load_data_ram.activeThreadCount()


def clear_all_thread_pools() -> None:
    thread_pool_global.clear()
    thread_pool_load_data_ram.clear()
    logging.info("All thread pools cleared.")


# TODO QRunnableCancellable