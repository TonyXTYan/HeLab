#helab/workers/statusWorker.py
from __future__ import annotations
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

from helab.utils.cachingSetup import *
from helab.utils.threadingSetup import *
from helab.resources.icons import StatusIcons, IconsInitUtil, circular_progress_QIcon_cached
from helab.utils.os_cached import os_isdir, os_listdir, os_listdir_filtered, os_listdirdir


# from helab.models.helabFileSystemModel import helabFileSystemModel


class StatusReport:
    STATUS_CONTAINS_DATA = ['ok', 'fixable', 'warning', 'critical', 'something']
    STATUS_MISTRY = ['canceled', 'unknown', 'loading', 'maybe']
    STATUS_NOTHING = ['nothing', 'missing']

    def __init__(self,
                 path: str,
                 status: str,
                 count: int,
                 extra_icons: list[str],
                 d_dld_shots:
                 Optional[List[int]] = None,
                 d_txy_shots: Optional[List[int]] = None,
                 time_last_updated: datetime = datetime.now()
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

        self.log_LabviewMatlab_txt: Optional[str] = None
        self.log_KeysightMatlab_txt: Optional[str] = None
        self.about_txt: Optional[str] = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StatusReport):
            return False
        # self.path == other.path
        return (self.path == other.path and
                self.status == other.status and
                self.count == other.count and
                self.extra_icons == other.extra_icons and
                self.d_dld_shots == other.d_dld_shots and
                self.d_txy_shots == other.d_txy_shots and
                self.problematic_txy_ns == other.problematic_txy_ns and
                self.payload_progress_ram == other.payload_progress_ram and
                self.time_last_updated == other.time_last_updated and
                self.time_load_ram == other.time_load_ram and
                self.log_LabviewMatlab_txt == other.log_LabviewMatlab_txt and
                self.log_KeysightMatlab_txt == other.log_KeysightMatlab_txt and
                self.about_txt == other.about_txt
                )

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __le__(self, other: StatusReport) -> bool:
        return self.time_last_updated <= other.time_last_updated

    def __lt__(self, other: StatusReport) -> bool:
        return self.time_last_updated < other.time_last_updated

    def __ge__(self, other: StatusReport) -> bool:
        return self.time_last_updated >= other.time_last_updated

    def __gt__(self, other: StatusReport) -> bool:
        return self.time_last_updated > other.time_last_updated


    def _update_cache(self) -> None:
        status_cache[self.path] = self

    def merge_with(self, status_report: StatusReport) -> None:
        if self.path != status_report.path:
            logging.warning(f"StatusReport.update_overwrite_status: path mismatch for {self.path} and {status_report.path}")
            return
        if self.time_last_updated > status_report.time_last_updated:
            logging.warning(f"StatusReport.update_overwrite_status: time_last_updated mismatch for {self.path}")
            return
        self.status = status_report.status
        self.count = status_report.count
        self.extra_icons = status_report.extra_icons
        self.d_dld_shots = status_report.d_dld_shots
        self.d_txy_shots = status_report.d_txy_shots
        self.problematic_txy_ns = status_report.problematic_txy_ns
        self.payload_progress_ram = status_report.payload_progress_ram
        self.time_last_updated = status_report.time_last_updated
        self.time_load_ram = status_report.time_load_ram
        self.log_LabviewMatlab_txt = status_report.log_LabviewMatlab_txt
        self.log_KeysightMatlab_txt = status_report.log_KeysightMatlab_txt
        self.about_txt = status_report.about_txt
        self._update_cache()

    def update_extend_extras(self, extra_icons: list[str]|str, update_cache:bool = True) -> None:
        if isinstance(extra_icons, str):
            extra_icons = [extra_icons]
        current_set = set(self.extra_icons)
        current_set.update(extra_icons)
        self.extra_icons = sorted(list(current_set),
                                  key=lambda x: StatusIcons.STATUS_ICONS_EXTRA_NAME_SORT_KEY.get(x, 0))
        if update_cache: self._update_cache()

    def update_remove_extras(self, to_remove: list[str]|str, update_cache:bool = True) -> None:
        if isinstance(to_remove, str):
            to_remove = [to_remove]
        current_set = set(self.extra_icons)
        current_set.difference_update(to_remove)
        self.extra_icons = sorted(list(current_set),
                                  key=lambda x: StatusIcons.STATUS_ICONS_EXTRA_NAME_SORT_KEY.get(x, 0))
        if update_cache: self._update_cache()
    
    def update_ram_status(self, is_opened: bool = False, time_load_ram: Optional[datetime] = None, update_cache:bool = True) -> None:
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
        if update_cache: self._update_cache()

    def update_there_is_something(self) -> None:
        # self.update_remove_extras('nothing', update_cache=False)
        # self.update_extend_extras('something', update_cache=True)
        if self.status not in StatusReport.STATUS_CONTAINS_DATA:
            self.status = 'something'
            self._update_cache()

    def update_to_unknown_status(self) -> None:
        if self.status in StatusReport.STATUS_CONTAINS_DATA:
            logging.warning(f"StatusReport.update_to_maybe_status: do not call this function like this for {self.path} with {self.status = }"
                            f", (this call will not doing anything)")
            return
        if self.status == 'loading':
            logging.warning(f"StatusReport.update_to_maybe_status: status still updating for {self.path}"
                            f", (this call will not doing anything, but anyway this line should never be reached)")
            return
        self.status = 'unknown'
        self._update_cache()


    def set_loading_ram_status(self) -> None:
        self.update_remove_extras(['ram', 'ram_single', 'ram_opened', 'progress_ram'], update_cache=False)
        self.update_extend_extras('loading_ram', update_cache=True)

    def set_loading_ram_progress(self, progress: float) -> None:
        self.update_remove_extras(['ram', 'ram_single', 'ram_opened', 'loading_ram'], update_cache=False)
        self.update_extend_extras('progress_ram', update_cache=False)
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
            # if 'progress_ram' in self.extra_icons:
            if any([icon in self.extra_icons for icon in ['loading_ram', 'progress_ram']]):
                if self.path not in running_workers_ramLoading.keys():
                    logging.debug(f"StatusReport.validate_ok: {self.path} is in loading_ram but not in running_workers_ramLoading")
                    return (False, False, False)

            # if self.time_last_updated is None:
            #     # logging.debug(f"StatusReport.validate_ok: time_last_updated is None")
            #     return (False, False, False)

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
                    # logging.debug(f"StatusReport.validate_ok: file {path} was modified after last update")
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
    # finished = pyqtSignal(str, str, int, list)  # path, status, count, extra_icons
    finished = pyqtSignal(StatusReport)  # path, status, count, extra_icons

# Define the Worker class with cancellation support

class StatusWorker(QRunnable):
    def __init__(self, file_path: str, invalidate_cache:bool=False):
        # QObject.__init__(self)
        # QRunnable.__init__()
        super().__init__()
        self.path = file_path
        self.signals = StatusWorkerSignals()
        self._is_canceled = False
        self.invalidate_cache = invalidate_cache

    def run(self) -> None:
        logging.debug(f"StatusWorker started for: {self.path}")
        if self._check_cancel_status(): return
        # self._run_helper_simulate()
        time.sleep(0.05)
        self._run_helper_v1()

    def _check_cancel_status(self) -> bool:
        if self._is_canceled:
            logging.debug(f"StatusWorker canceled for: {self.path}")
            # self.signals.finished.emit(StatusReport(self.path, 'canceled', -1, []))
            self._finished_emit_helper(StatusReport(self.path, 'canceled', -1, []))
            return True
        else: return False

    def _finished_emit_helper(self, status_report: StatusReport) -> None:
        if self.path in status_cache:
            logging.debug(f"StatusWorker._finished_emit_helper: overwriting cache for {self.path} with status = {status_report.status}")
        # status_cache[self.path] = status_report
        time.sleep(0.10)
        status_report.merge_with(status_report)
        time.sleep(0.05)
        self._finished_emit_helper_parent_path(status_report)
        time.sleep(0.05)
        self._finished_emit_helper_children_path(status_report)
        time.sleep(0.10)
        self.signals.finished.emit(status_report)

    def _finished_emit_helper_parent_path(self, status_report: StatusReport) -> None:
        if status_report.status in StatusReport.STATUS_CONTAINS_DATA:
            parent_path = os.path.dirname(self.path)

            if parent_path == self.path:
                logging.warning(f"StatusWorker._finished_emit_helper: parent_path is same as path for {self.path}, this is root path?")
                return

            if parent_path not in hasChildren_cache:
                logging.warning(f"StatusWorker._finished_emit_helper: hasChildren not found for {parent_path}")
            elif not hasChildren_cache[parent_path]:
                logging.warning(f"StatusWorker._finished_emit_helper: hasChildren is False for {parent_path}")
            else:
                pass

            parent_status_report = status_cache.get(parent_path, None)
            if isinstance(parent_status_report, StatusReport):
                parent_status_report.update_there_is_something()
            else:
                logging.warning(f"StatusWorker._finished_emit_helper: parent_status_report not found for {parent_path}")
                return

    def _finished_emit_helper_children_path(self, status_report: StatusReport) -> None:
        if status_report.status == 'nothing':
            children_paths = os_listdirdir(self.path, invalidate_cache=self.invalidate_cache)
            at_least_one_mystry = False
            for child_path_name in children_paths:
                child_path = os.path.join(self.path, child_path_name)
                # logging.debug(f"StatusWorker._finished_emit_helper: checking child_path = {child_path}")
                child_status_report = status_cache.get(child_path, None)
                if not isinstance(child_status_report, StatusReport):
                    # logging.warning(f"StatusWorker._finished_emit_helper: child_status_report not found for {child_path}")
                    continue
                elif child_status_report.status in StatusReport.STATUS_CONTAINS_DATA:
                    status_report.update_there_is_something()
                    return
                elif child_status_report.status in StatusReport.STATUS_MISTRY:
                    at_least_one_mystry = True
                elif child_status_report.status in StatusReport.STATUS_NOTHING:
                    continue
                else:
                    logging.critical(f"StatusWorker._finished_emit_helper: unexpected case {child_status_report.status = }")
                    continue
            if at_least_one_mystry:
                status_report.update_to_unknown_status()



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
            f"StatusWorker._run_helper_simulate: path = {self.path}, status = {status}, count = {count}, extra icons = {extra_icons}")
        # self.signals.finished.emit(StatusReport(self.path, status, count, extra_icons))
        self._finished_emit_helper(StatusReport(self.path, status, count, extra_icons))

    def _run_helper_v1(self) -> None:
        # This method is designed currently to work only with downstairs lab data structure.
        # Expected data format: 
        #   about.txt
        #   d123.txt                  # raw data collected by TDC Launcher in channels and timestamps (?)
        #   d_txy_forc123.txt         # tdc_autoconverter d123.txt in (t, x, y) format 
        #   log_KeysightMatlab.txt    # Optional
        #   log_LabviewMatlab.txt     # Optional

        try:
            # check if self.path is a directory
            # if not os.path.isdir(self.path):
            if not os_isdir(self.path, self.invalidate_cache):
                logging.error(f"StatusWorker._run_helper_v1: {self.path} is not a directory")
                # self.signals.finished.emit(StatusReport(self.path, 'missing', -1, []))
                self._finished_emit_helper(StatusReport(self.path, 'missing', -1, []))
                return
            # check if self.path contains any directory
            # dirs = os.listdir(self.path)

            # just_for_the_sake_of_testing = os_scandir(self.path)

            if self._check_cancel_status(): return
            time.sleep(0.05)  # slight delay to void GIL
            files_filtered = os_listdir_filtered(self.path, self.invalidate_cache)
            time.sleep(0.05)
            files_filtered_len = len(files_filtered)
            time.sleep(0.05)

            if self._check_cancel_status(): return

            # list all files in the directory
            files = os_listdir(self.path, self.invalidate_cache)

            if self._check_cancel_status(): return

            # future = os_scandir_async(self.path)
            # files_scan = future.result()
            # files_scan = os_scandir(self.path)
            # files = [entry.name for entry in files_scan if entry.is_file()]
            # with os_scandir(self.path) as it:
            #     files = [entry.name for entry in it if entry.is_file()]
            logging.debug(f"StatusWorker._run_helper_v1: files in {self.path}: counted {len(files)}")

        except PermissionError as e:
            logging.error(f"StatusWorker._run_helper_v1: PermissionError accessing {self.path}: {e}")
            # self.signals.finished.emit(StatusReport(self.path, 'missing', -1, []))
            self._finished_emit_helper(StatusReport(self.path, 'missing', -1, []))
            return
        except Exception as e:
            logging.error(f"StatusWorker._run_helper_v1: Error accessing {self.path}: {e}")
            # self.signals.finished.emit(StatusReport(self.path, 'missing', -1, []))
            self._finished_emit_helper(StatusReport(self.path, 'missing', -1, []))
            return

        time.sleep(0.01)  # slight delay to void GIL

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

        if self._check_cancel_status(): return

        logging.debug(f"StatusWorker._run_helper_v1: d_dld_files: {d_dld_files_len}, d_txy_files: {d_txy_files_len}, "
                      f"d_union_shots: {d_union_shots_len}, d_inter_shots: {d_inter_shots_len}, "
                      f"d_only_dld_shots: {d_only_dld_shots_len}, d_only_txy_shots: {d_only_txy_shots_len}, "
                      f"files_filtered_len: {files_filtered_len}"
                      )

        if len(d_dld_shots) != len(set(d_dld_shots)):
            logging.fatal(f"StatusWorker._run_helper_v1: IMPOSSIBLE?! {self.path = }\t d_dld_shots contains duplicates: {d_dld_shots[:min(10, len(d_dld_shots))]}")
        if len(d_txy_shots) != len(set(d_txy_shots)):
            logging.fatal(f"StatusWorker._run_helper_v1: IMPOSSIBLE?! {self.path = }\t d_txy_shots contains duplicates: {d_txy_shots[:min(10, len(d_txy_shots))]}")


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
                logging.warning(f"StatusWorker._run_helper_v1: folder only contain txy data: {d_only_txy_shots_len} at {self.path}")
                emit_status, emit_counts = 'warning', d_only_txy_shots_len
            elif d_only_txy_shots_len == 0:
                logging.warning(f"StatusWorker._run_helper_v1: folder only contain dld data: {d_only_dld_shots_len} at {self.path}")
                emit_status, emit_counts = 'warning', d_only_dld_shots_len
            else:
                # This means there are some dld files and some txy files but none of them are matching
                logging.critical(f"StatusWorker._run_helper_v1: serverly fucked up dataset at {self.path} (no matching pairs)")
                emit_status, emit_counts = 'critical', 0
        else:
            logging.fatal(f"StatusWorker._run_helper_v1: unexpected condition for {self.path}"
                          f"d_dld_files: {d_dld_files_len}, d_txy_files: {d_txy_files_len}, "
                          f"d_union_shots: {d_union_shots_len}, d_inter_shots: {d_inter_shots_len}, "
                          f"d_only_dld_shots: {d_only_dld_shots_len}, d_only_txy_shots: {d_only_txy_shots_len}"
                          )
            assert False, "Impossible logic! Unexpected condition"

        if emit_counts >= 0:
            try:
                # data_files = data_ram_cache.__getitem__(self.path)
                data_files = data_ram_cache[self.path]
                if not data_files is None:
                    emit_eicons.append('ram')
                    logging.debug(f"StatusWorker._run_helper_v1: data in data_ram_cache for {self.path}")
                else:
                    logging.warning(f"StatusWorker._run_helper_v1: data_ram_cache None for {self.path}")
            except KeyError:
                logging.debug(f"StatusWorker._run_helper_v1: no key in data_ram_cache {self.path}")
                pass
            except Exception as e:
                logging.error(f"StatusWorker._run_helper_v1: error accessing cache for {self.path}: {e}")
                pass

        # self.signals.finished.emit(StatusReport(self.path, emit_status, emit_counts, emit_eicons, d_dld_shots, d_txy_shots, datetime.now()))
        self._finished_emit_helper(StatusReport(self.path, emit_status, emit_counts, emit_eicons, d_dld_shots, d_txy_shots, datetime.now()))

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
    #     logging.debug(f"Worker finished for: {self.path} with status: {status}, count: {count}, extra icons: {extra_icons}")
    #     self.signals.finished.emit(StatusReport(self.path, status, count, extra_icons)





