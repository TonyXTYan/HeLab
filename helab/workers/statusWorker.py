from datetime import datetime
import os
import random
import re
import time
from copy import deepcopy
from typing import Optional, Set, List, Tuple

from PyInstaller.compat import is_openbsd
from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, QTimer
import logging

from PyQt6.QtTest import QTest
from babel.dates import time_
from mypyc.namegen import candidate_suffixes

from helab.resources.icons import StatusIcons, IconsInitUtil, circular_progress_QIcon_cached
from helab.utils.cachingSetup import data_ram_cache, status_cache
from helab.utils.os_cached import os_isdir, os_listdir


# from helab.models.helabFileSystemModel import helabFileSystemModel


class StatusReport:
    def __init__(self,
                 path: str,
                 status: str,
                 count: int,
                 extra_icons: list[str],
                 d_dld_shots:
                 Optional[List[int]] = None,
                 d_txy_shots: Optional[List[int]] = None,
                 time_last_updated: Optional[datetime] = datetime.now()
                 ):
        self.path = path
        self.status = status
        self.count = count
        self.extra_icons = extra_icons
        self.d_dld_shots = d_dld_shots
        self.d_txy_shots = d_txy_shots
        self.problematic_txy_ns: Optional[List[int]] = None
        self.payload_progress_ram: Optional[float] = None
        self.time_last_updated = time_last_updated
        self.time_load_ram: Optional[datetime] = None

    def _update_cache(self) -> None:
        status_cache[self.path] = self

    def update_extend_extras(self, extra_icons: list[str] | str ) -> None:
        if isinstance(extra_icons, str):
            extra_icons = [extra_icons]
        current_set = set(self.extra_icons)
        current_set.update(extra_icons)
        self.extra_icons = sorted(list(current_set),
                                  key=lambda x: StatusIcons.STATUS_ICONS_EXTRA_NAME_SORT_KEY.get(x, 0))
        self._update_cache()

    def update_remove_extras(self, to_remove: list[str] | str) -> None:
        if isinstance(to_remove, str):
            to_remove = [to_remove]
        current_set = set(self.extra_icons)
        current_set.difference_update(to_remove)
        self.extra_icons = sorted(list(current_set),
                                  key=lambda x: StatusIcons.STATUS_ICONS_EXTRA_NAME_SORT_KEY.get(x, 0))
        self._update_cache()
    
    def update_ram_status(self, is_opened: bool = False, time_load_ram: Optional[datetime] = None) -> None:
        if time_load_ram: self.time_load_ram = time_load_ram
        try:
            self.update_remove_extras(['ram', 'ram_single', 'ram_opened', 'loading_ram', 'progress_ram'])
            data_files = data_ram_cache[self.path]
            if not data_files is None:
                if is_opened:
                    self.update_extend_extras('ram_opened')
                else:
                    self.update_extend_extras('ram')
        except KeyError:
            # self.update_remove_extras(['ram', 'ram_single', 'ram_opened'])
            if is_opened:
                self.update_extend_extras('ram_single')
        except Exception as e:
            logging.error(f"StatusReport.update_ram_status: error accessing cache for {self.path}: {e}")
            # self.update_remove_extras(['ram', 'ram_single', 'ram_opened'])
            # if e == KeyError and is_opened:
            #     self.update_extend_extras('ram_single')
            # self.time_load_ram = None
        self._update_cache()

    def set_loading_ram_status(self) -> None:
        self.update_remove_extras(['ram', 'ram_single', 'ram_opened', 'progress_ram'])
        self.update_extend_extras('loading_ram')

    def set_loading_ram_progress(self, progress: float) -> None:
        self.update_remove_extras(['ram', 'ram_single', 'ram_opened', 'loading_ram'])
        self.update_extend_extras('progress_ram')
        self.payload_progress_ram = progress
        self._update_cache()

    def update_problematic_txy_ns(self, problematic_txy_ns: List[int]) -> None:
        self.problematic_txy_ns = problematic_txy_ns
        self._update_cache()

    def return_extra_icons_paintable(self) -> object:
        # return sorted([StatusIcons.ICONS_EXTRA.get(icon_key) for icon_key in self.extra_icons],
        #               key=lambda x: StatusIcons.STATUS_ICONS_EXTRA_NAME_SORT_KEY.get(x,0))

        candidate = deepcopy(self.extra_icons)
        if 'progress_ram' in self.extra_icons:
            candidate.remove('progress_ram')
            candidate_return = self._sorted_extra_icons_to_QIcons(candidate)
            if self.payload_progress_ram is None:
                logging.warning(f"StatusReport.return_extra_icons_paintable: progress_ram icon found but no progress value for {self.path}")
                self.update_remove_extras('progress_ram')
                return candidate_return
            else:
                candidate_return.insert(0, circular_progress_QIcon_cached(self.payload_progress_ram))
                return candidate_return
        else:
            return self._sorted_extra_icons_to_QIcons(candidate)


    def validate_ok(self) -> Tuple[bool, bool, bool]:
        ok_path = True
        ok_file = True
        ok_data = True
        try:
            if self.time_last_updated is None:
                # logging.debug(f"StatusReport.validate_ok: time_last_updated is None")
                return (False, False, False)

            path_last_modified_time = datetime.fromtimestamp(os.path.getatime(self.path))
            # if path_last_modified_time is None:
            #     logging.warning(f"StatusReport.validate_ok: path {self.path} does not exist")
            #     return (False, False)
            if path_last_modified_time > self.time_last_updated:
                # logging.debug(f"StatusReport.validate_ok: path {self.path} was modified after last update")
                ok_path = False

            if self.time_load_ram and path_last_modified_time > self.time_load_ram:
                ok_data = False

            files_inside_path = os_listdir(self.path, invalidate_cache=True)
            for f in files_inside_path:
                file_path = os.path.join(self.path, f)
                file_last_modified_time = datetime.fromtimestamp(os.path.getatime(file_path))
                # if file_last_modified_time is None:
                #     logging.warning(f"StatusReport.validate_ok: file {f} does not exist")
                #     ok_file = False
                #     break
                if file_last_modified_time > self.time_last_updated:
                    # logging.debug(f"StatusReport.validate_ok: file {file_path} was modified after last update")
                    ok_file = False
                    break

            return (ok_path, ok_file, ok_data)
        except AttributeError as e:
            logging.debug(f"StatusReport.validate_ok: (pop) AttributeError validating {self.path}: {e}")
            status_cache.pop(self.path)
            return (False, False ,False)
        except PermissionError as e:
            logging.debug(f"StatusReport.validate_ok: PermissionError validating {self.path}: {e}")
            return (ok_path, ok_file ,ok_data)
        except Exception as e:
            logging.warning(f"StatusReport.validate_ok: error validating {self.path}: {e}")
            return (False, False, False)


    @staticmethod
    def _sort_extra_icons(extra_icons: list[str]) -> list[str]:
        return sorted(extra_icons, key=lambda x: StatusIcons.STATUS_ICONS_EXTRA_NAME_SORT_KEY.get(x, 0))

    @staticmethod
    def _extra_icons_to_QIcons(extra_icons: list[str]) -> list[object]:
        return [StatusIcons.ICONS_EXTRA.get(icon_key) for icon_key in extra_icons]

    @staticmethod
    def _sorted_extra_icons_to_QIcons(extra_icons: list[str]) -> list[object]:
        return [StatusIcons.ICONS_EXTRA.get(icon_key) for icon_key in StatusReport._sort_extra_icons(extra_icons)]

# Define WorkerSignals to communicate between threads
class StatusWorkerSignals(QObject):
    # finished = pyqtSignal(str, str, int, list)  # file_path, status, count, extra_icons
    finished = pyqtSignal(StatusReport)  # file_path, status, count, extra_icons

# Define the Worker class with cancellation support
class StatusWorker(QRunnable):
    def __init__(self, file_path: str, invalidate_cache:bool=False):
        # QObject.__init__(self)
        # QRunnable.__init__()
        super().__init__()
        self.file_path = file_path
        self.signals = StatusWorkerSignals()
        self._is_canceled = False
        self.invalidate_cache = invalidate_cache

    def run(self) -> None:
        logging.debug(f"StatusWorker started for: {self.file_path}")
        if self._is_canceled:
            logging.debug(f"StatusWorker canceled for: {self.file_path}")
            self.signals.finished.emit(StatusReport(self.file_path, 'canceled', -1, []))
            return

        # self._run_helper_simulate()
        self._run_helper_v1()

    def _run_helper_simulate(self) -> None:
        # Simulate a long-running computation
        # QTest.qWait(int(random.randint(300, 500)))  # Simulate computation delay
        time.sleep(random.uniform(0.2, 0.4))  # Simulate computation delay
        # QTimer.singleShot(random.randint(200, 500), self._compute_status)

        # Replace the following with your actual status computation logic
        # statuses = ['ok', 'warning', 'critical', 'nothing']
        statuses = StatusIcons.STATUS_ICONS_NAME
        status = random.choice(statuses)
        # count = random.randint(1, 100)
        count = random.randint(10 ** (length := random.randint(0, 5)), 10 ** (length + 1) - 1)

        extra_icons = sorted(
            random.sample(StatusIcons.STATUS_ICONS_EXTRA_NAME, random.randint(0, 4)),
            key=lambda x: StatusIcons.STATUS_ICONS_EXTRA_NAME_SORT_KEY.get(x, 0)
        )
        # extra_icons = []

        logging.debug(
            f"StatusWorker._run_helper_simulate: path = {self.file_path}, status = {status}, count = {count}, extra icons = {extra_icons}")
        self.signals.finished.emit(StatusReport(self.file_path, status, count, extra_icons))

    def _run_helper_v1(self) -> None:
        # This method is designed currently to work only with downstairs lab data structure.
        # Expected data format: 
        #   about.txt
        #   d123.txt                  # raw data collected by TDC Launcher in channels and timestamps (?)
        #   d_txy_forc123.txt         # tdc_autoconverter d123.txt in (t, x, y) format 
        #   log_KeysightMatlab.txt    # Optional
        #   log_LabviewMatlab.txt     # Optional

        try:
            # check if self.file_path is a directory
            # if not os.path.isdir(self.file_path):
            if not os_isdir(self.file_path, self.invalidate_cache):
                logging.error(f"StatusWorker._run_helper_v1: {self.file_path} is not a directory")
                self.signals.finished.emit(StatusReport(self.file_path, 'missing', -1, []))
                return
            # check if self.file_path contains any directory
            # dirs = os.listdir(self.file_path)

            # just_for_the_sake_of_testing = os_scandir(self.file_path)

            # list all files in the directory
            files = os_listdir(self.file_path, self.invalidate_cache)
            # future = os_scandir_async(self.file_path)
            # files_scan = future.result()
            # files_scan = os_scandir(self.file_path)
            # files = [entry.name for entry in files_scan if entry.is_file()]
            # with os_scandir(self.file_path) as it:
            #     files = [entry.name for entry in it if entry.is_file()]
            logging.debug(f"StatusWorker._run_helper_v1: files in {self.file_path}: counted {len(files)}")

        except PermissionError as e:
            logging.error(f"StatusWorker._run_helper_v1: PermissionError accessing {self.file_path}: {e}")
            self.signals.finished.emit(StatusReport(self.file_path, 'missing', -1, []))
            return
        except Exception as e:
            logging.error(f"StatusWorker._run_helper_v1: Error accessing {self.file_path}: {e}")
            self.signals.finished.emit(StatusReport(self.file_path, 'missing', -1, []))
            return


        # pattern match and list all files of d123.txt
        # d_dld_pattern = re.compile(r'^d\d+\.txt$')
        d_dld_pattern = re.compile(r'^d(\d+)\.txt$')
        # d_files = [f for f in files if d_dld_pattern.match(f)]
        d_dld_shots = [int(match.group(1)) for f in files if (match := d_dld_pattern.match(f))]
        d_dld_files_len = len(d_dld_shots)

        # pattern match and list all files of d_txy_forc123.txt
        # d_txy_pattern = re.compile(r'^d_txy_forc\d+\.txt$')
        d_txy_pattern = re.compile(r'^d_txy_forc(\d+)\.txt$')
        # d_txy_files = [f for f in files if d_txy_pattern.match(f)]
        d_txy_shots = [int(match.group(1)) for f in files if (match := d_txy_pattern.match(f))]
        d_txy_files_len = len(d_txy_shots)

        d_union_shots = set(d_dld_shots) | set(d_txy_shots)
        d_inter_shots = set(d_dld_shots) & set(d_txy_shots)
        d_only_dld_shots = set(d_dld_shots) - d_inter_shots
        d_only_txy_shots = set(d_txy_shots) - d_inter_shots

        d_union_shots_len = len(d_union_shots)
        d_inter_shots_len = len(d_inter_shots)
        d_only_dld_shots_len = len(d_only_dld_shots)
        d_only_txy_shots_len = len(d_only_txy_shots)


        logging.debug(f"StatusWorker._run_helper_v1: d_dld_files: {d_dld_files_len}, d_txy_files: {d_txy_files_len}, "
                      f"d_union_shots: {d_union_shots_len}, d_inter_shots: {d_inter_shots_len}, "
                      f"d_only_dld_shots: {d_only_dld_shots_len}, d_only_txy_shots: {d_only_txy_shots_len}"
                      )

        if len(d_dld_shots) != len(set(d_dld_shots)):
            logging.fatal(f"StatusWorker._run_helper_v1: IMPOSSIBLE?! {self.file_path = }\t d_dld_shots contains duplicates: {d_dld_shots[:min(10,len(d_dld_shots))]}")
        if len(d_txy_shots) != len(set(d_txy_shots)):
            logging.fatal(f"StatusWorker._run_helper_v1: IMPOSSIBLE?! {self.file_path = }\t d_txy_shots contains duplicates: {d_txy_shots[:min(10,len(d_txy_shots))]}")


        emit_status = 'canceled'
        emit_counts = -2
        emit_eicons = []
        if (d_only_dld_shots_len == 0 and d_only_txy_shots_len == 0) and d_union_shots_len == 0:
            # no data files found
            assert d_union_shots_len == d_inter_shots_len, "Impossible logic! d_union_shots_len != d_inter_shots_len"
            emit_status, emit_counts = 'nothing', -1
        elif (d_only_dld_shots_len == 0 and d_only_txy_shots_len == 0) and d_union_shots_len > 0:
            # consistent data folder
            assert d_union_shots_len == d_inter_shots_len, "Impossible logic! d_union_shots_len != d_inter_shots_len"
            emit_status, emit_counts = 'ok', d_union_shots_len
        elif (d_only_dld_shots_len > 0 and d_only_txy_shots_len == 0) and d_inter_shots_len > 0:
            emit_status, emit_counts = 'fixable', d_inter_shots_len
        elif (d_only_dld_shots_len > 0 and d_only_txy_shots_len > 0) and d_inter_shots_len > 0:
            # inconsistent data folder
            emit_status, emit_counts = 'warning', d_inter_shots_len
        elif (d_only_dld_shots_len == 0 and d_only_txy_shots_len > 0) and d_inter_shots_len > 0:
            emit_status, emit_counts = 'critical', d_inter_shots_len
        elif (d_only_dld_shots_len > 0 or d_only_txy_shots_len > 0) and d_inter_shots_len == 0:
            # terribly inconsistent data folder
            if d_only_dld_shots_len == 0:
                logging.warning(f"StatusWorker._run_helper_v1: folder only contain txy data: {d_only_txy_shots_len} at {self.file_path}")
                emit_status, emit_counts = 'warning', d_only_txy_shots_len
            elif d_only_txy_shots_len == 0:
                logging.warning(f"StatusWorker._run_helper_v1: folder only contain dld data: {d_only_dld_shots_len} at {self.file_path}")
                emit_status, emit_counts = 'warning', d_only_dld_shots_len
            else:
                # This means there are some dld files and some txy files but none of them are matching
                logging.critical(f"StatusWorker._run_helper_v1: serverly fucked up dataset at {self.file_path} (no matching pairs)")
                emit_status, emit_counts = 'critical', 0
        else:
            logging.fatal(f"StatusWorker._run_helper_v1: unexpected condition for {self.file_path}"
                          f"d_dld_files: {d_dld_files_len}, d_txy_files: {d_txy_files_len}, "
                          f"d_union_shots: {d_union_shots_len}, d_inter_shots: {d_inter_shots_len}, "
                          f"d_only_dld_shots: {d_only_dld_shots_len}, d_only_txy_shots: {d_only_txy_shots_len}"
                          )
            assert False, "Impossible logic! Unexpected condition"

        if emit_counts >= 0:
            try:
                # data_files = data_ram_cache.__getitem__(self.file_path)
                data_files = data_ram_cache[self.file_path]
                if not data_files is None:
                    emit_eicons.append('ram')
                    logging.debug(f"StatusWorker._run_helper_v1: data in data_ram_cache for {self.file_path}")
                else:
                    logging.warning(f"StatusWorker._run_helper_v1: data_ram_cache None for {self.file_path}")
            except KeyError:
                logging.debug(f"StatusWorker._run_helper_v1: no key in data_ram_cache {self.file_path}")
                pass
            except Exception as e:
                logging.error(f"StatusWorker._run_helper_v1: error accessing cache for {self.file_path}: {e}")
                pass

        self.signals.finished.emit(StatusReport(self.file_path, emit_status, emit_counts, emit_eicons, d_dld_shots, d_txy_shots, datetime.now()))


    def cancel(self) -> None:
        self._is_canceled = True

    # def _compute_status(self):
    #     # Replace the following with your actual status computation logic
    #     statuses = ['ok', 'warning', 'critical', 'nothing']
    #     status = random.choice(statuses)
    #     # count = random.randint(1, 100)
    #     count = random.randint(10**(length := random.randint(0, 5)), 10**(length + 1) - 1)
    #
    #     extra_icons = sorted(random.sample(StatusIcons.STATUS_ICONS_EXTRA_NAME, random.randint(0, 4)), key=StatusIcons.STATUS_ICONS_EXTRA_NAME_SORT_KEY.get)
    #     # extra_icons = []
    #
    #     logging.debug(f"Worker finished for: {self.file_path} with status: {status}, count: {count}, extra icons: {extra_icons}")
    #     self.signals.finished.emit(StatusReport(self.file_path, status, count, extra_icons)





