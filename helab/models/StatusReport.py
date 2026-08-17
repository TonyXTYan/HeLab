#helab/models/StatusReport.py
from __future__ import annotations

import warnings
from datetime import datetime
import os
import random
import re
import time
from copy import deepcopy
from typing import Optional, Set, List, Tuple, cast, Callable, Any

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, QTimer, QDir, QThread, QModelIndex, Qt, QFileInfo
import logging

from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest

from helab.utils.caching_setup import *
from helab.utils.threading_setup import *
from helab.resources.icons import StatusIcons, IconsInitUtil, circular_progress_QIcon_cached
from helab.utils.os_cached import os_isdir, os_listdir, os_listdir_filtered, os_listdirdir, OSCMgmt
from helab.utils.constants import *
from helab.workers.DirectoryCheckWorker import DirectoryCheckWorker

class StatusReport:
    STATUS_CONTAINS_DATA = ['ok', 'fixable', 'warning', 'critical', 'something']
    STATUS_CONTAINS_DATA_HERE = ['ok', 'fixable', 'warning', 'critical']
    STATUS_MISTERY = ['cancelled', 'unknown', 'loading', 'maybe']
    STATUS_NOTHING = ['nothing', 'missing']
    ERROR_INVALID_STATUS_ICON = ("StatusReport: invalid status icon", LookupError())
    ATTRIBUTES_OPTIONAL: List[str] = [
        "payload_progress_ram",
        "problematic_txy_ns",
        "loaded_txy_files_count",
        "loaded_txy_rows_count",
        "data_dict_bytes",
        "data_comp_bytes",
        "time_load_ram",
        "_reviewed_path_parent_recursively",
        "log_LabviewMatlab_txt",
        "log_KeysightMatlab_txt",
        "about_txt",
        "payload_errors"
    ]

    def __init__(self,
                 path: str,
                 status: str,
                 count: int,
                 extra_icons: list[str],
                 d_dld_shots: Optional[List[int]] = None,
                 d_txy_shots: Optional[List[int]] = None,
                 time_last_updated: datetime = datetime.now()
                 ):
        self.path = path
        self.status = status
        self.count = count
        self.extra_icons = extra_icons
        self.d_dld_shots = d_dld_shots
        self.d_txy_shots = d_txy_shots
        self.time_last_updated = time_last_updated

        self.payload_progress_ram: Optional[float] = None
        self.problematic_txy_ns: Optional[List[int]] = None
        self.loaded_txy_files_count: Optional[int] = None
        self.loaded_txy_rows_count: Optional[int] = None
        self.data_dict_bytes: Optional[int] = None
        self.data_comp_bytes: Optional[int] = None
        self.time_load_ram: Optional[datetime] = None

        self._reviewed_path_parent_recursively: Optional[bool] = None

        self.log_LabviewMatlab_txt: Optional[str] = None
        self.log_KeysightMatlab_txt: Optional[str] = None
        self.about_txt: Optional[str] = None

        self.payload_errors: Optional[List[Tuple[str, Optional[Exception]]]] = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StatusReport):
            return False
        # self.path == other.path
        return (self.path == other.path
                and self.status == other.status
                and self.count == other.count
                and self.extra_icons == other.extra_icons
                and self.d_dld_shots == other.d_dld_shots
                and self.d_txy_shots == other.d_txy_shots
                and self.problematic_txy_ns == other.problematic_txy_ns
                and self.payload_progress_ram == other.payload_progress_ram
                and self.time_last_updated == other.time_last_updated
                and self.time_load_ram == other.time_load_ram
                and self.log_LabviewMatlab_txt == other.log_LabviewMatlab_txt
                and self.log_KeysightMatlab_txt == other.log_KeysightMatlab_txt
                and self.about_txt == other.about_txt
                and self.payload_errors == other.payload_errors
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

    def __str__(self) -> str:
        return (f"StatusReport({self.path})")

    def _update_cache(self) -> StatusReport:
        """
        Update the status cache with the current status report.
        :return:    The updated status report
        """
        status_cache[self.path] = self
        status_report = status_cache.get(self.path, None)
        if isinstance(status_report, StatusReport):
            return status_report
        else:
            logging.error(
                f"StatusReport._update_cache: error updating cache for {self.path = }, {type(status_report) = }")
            return self

    def merge_with(self, status_report: StatusReport) -> StatusReport:
        """
        This currently is mostly a simple overwrite of the status report with the passed in status report.
        same effect as calling override_cache_with()
        TODO: actual merge logic
        """
        if self.path != status_report.path:
            logging.warning(
                f"StatusReport.update_overwrite_status: path mismatch for {self.path} and {status_report.path}")
            return status_report
        if self.time_last_updated < status_report.time_last_updated:
            logging.warning(f"StatusReport.update_overwrite_status: time_last_updated mismatch for {self.path}")
            return status_report
        if status_report.validate_ok() != (True, True, True):
            logging.warning(f"StatusReport.update_overwrite_status: passed in status_report is not ok for {self.path}")
            return self

        self.status = status_report.status or self.status
        self.count = status_report.count or self.count
        self.extra_icons = status_report.extra_icons or self.extra_icons
        self.d_dld_shots = status_report.d_dld_shots or self.d_dld_shots
        self.d_txy_shots = status_report.d_txy_shots or self.d_txy_shots
        self.problematic_txy_ns = status_report.problematic_txy_ns or self.problematic_txy_ns
        self.payload_progress_ram = status_report.payload_progress_ram or self.payload_progress_ram
        self.time_last_updated = status_report.time_last_updated or self.time_last_updated
        self.time_load_ram = status_report.time_load_ram or self.time_load_ram
        self.log_LabviewMatlab_txt = status_report.log_LabviewMatlab_txt or self.log_LabviewMatlab_txt
        self.log_KeysightMatlab_txt = status_report.log_KeysightMatlab_txt or self.log_KeysightMatlab_txt
        self.about_txt = status_report.about_txt or self.about_txt
        return self._update_cache()

    def override_cache_with(self, status_report: StatusReport) -> StatusReport:
        """
        Overwrite the status cache with the passed in status report.
        :param status_report:   The status report to overwrite the cache with
        :return:                The updated status report
        """
        if self.path != status_report.path:
            logging.critical(
                f"StatusReport.update_overwrite_status: path mismatch for {self.path} and {status_report.path}")
            return status_report
        status_cache[self.path] = status_report
        return status_report

    def noticed_errors(self,
                       errors: List[Tuple[str, Optional[Exception]]] | Tuple[str, Optional[Exception]]) -> StatusReport:
        """
        Update the status report with a list of errors.
        :param errors: [error message, exception]
        :return: The updated status report
        """
        if isinstance(errors, tuple): errors = [errors]
        if not self.payload_errors:
            self.payload_errors = errors
        else:
            self.payload_errors.extend(errors)
        return self._update_cache()

    def update_extend_extras(self, extra_icons: list[str] | str, update_cache: bool = True) -> StatusReport:
        """
        Add extra icons to the status report.
        :param extra_icons: The extra icons to add
        :param update_cache: Whether to update the cache with the new status report
        :return: The updated status report
        """
        if isinstance(extra_icons, str):
            extra_icons = [extra_icons]
        current_set = set(self.extra_icons)
        current_set.update(extra_icons)
        self.extra_icons = sorted(list(current_set),
                                  key=lambda x: StatusIcons.STATUS_ICONS_EXTRA_NAME_SORT_KEY.get(x, 0))
        if update_cache:
            return self._update_cache()
        else:
            return self

    def update_remove_extras(self, to_remove: list[str] | str, update_cache: bool = True) -> StatusReport:
        """
        Remove extra icons from the status report.
        :param to_remove: The extra icons to remove
        :param update_cache: Whether to update the cache with the new status report
        :return: The updated status report
        """
        if isinstance(to_remove, str):
            to_remove = [to_remove]
        current_set = set(self.extra_icons)
        current_set.difference_update(to_remove)
        self.extra_icons = sorted(list(current_set),
                                  key=lambda x: StatusIcons.STATUS_ICONS_EXTRA_NAME_SORT_KEY.get(x, 0))
        if update_cache:
            return self._update_cache()
        else:
            return self

    def update_ram_status(self, is_opened: bool = False, time_load_ram: Optional[datetime] = None,
                          update_cache: bool = True) -> StatusReport:
        """
        Update the status report with the RAM status.
        :param is_opened:       Whether this data folder is opened by the editor
        :param time_load_ram:   The time the RAM was loaded
        :param update_cache:    Whether to update the cache with the new status report
        :return:    The updated status report
        """
        if time_load_ram: self.time_load_ram = time_load_ram
        try:
            self.update_remove_extras(['ram', 'ram_single', 'ram_opened', 'loading_ram', 'progress_ram'],
                                      update_cache=False)
            data_files = data_ram_cache[self.path]
            if not data_files is None:
                if is_opened:
                    self.update_extend_extras('ram_opened', update_cache=False)
                else:
                    self.update_extend_extras('ram', update_cache=False)
        except KeyError:
            # self.update_remove_extras(['ram', 'ram_single', 'ram_opened'])
            if is_opened:
                self.update_extend_extras('ram_single', update_cache=False)
        except Exception as e:
            logging.error(f"StatusReport.update_ram_status: error accessing cache for {self.path}: {e}")
            # self.update_remove_extras(['ram', 'ram_single', 'ram_opened'])
            # if e == KeyError and is_opened:
            #     self.update_extend_extras('ram_single')
            # self.time_load_ram = None
        if update_cache:
            return self._update_cache()
        else:
            return self

    def update_there_is_something(self, force: bool = False) -> StatusReport:
        """
        Update the status report to 'something' status.
        :param force: force set the status to 'something'
        :return: The updated status report
        """
        # self.update_remove_extras('nothing', update_cache=False)
        # self.update_extend_extras('something', update_cache=True)
        if force or self.status not in StatusReport.STATUS_CONTAINS_DATA:
            self.status = 'something'
            return self._update_cache()
        else:
            return self

    def update_to_unknown_status(self,
                                 force: bool = False) -> StatusReport:  # TODO: rename this to something like noticed_potential_unknown_status
        """
        Update the status report to 'unknown' status.
        :param force: force set the status to 'unknown'
        :return: The updated status report
        """
        if self.status in StatusReport.STATUS_CONTAINS_DATA and not force:
            # logging.warning(f"StatusReport.update_to_maybe_status: do not call this function like this for {self.path} with {self.status = }"
            #                 f", (this call will not doing anything)")
            return self
        if self.status == 'loading' and not force:
            # logging.warning(f"StatusReport.update_to_maybe_status: status still updating for {self.path}"
            #                 f", (this call will not doing anything, but anyway this line should never be reached)")
            return self
        self.status = 'unknown'
        return self._update_cache()

    def update_to_nothing_status(self, force: bool = False) -> StatusReport:
        """
        Update the status report to 'nothing' status.
        :param force: force set the status to 'nothing'
        :return: The updated status report
        """
        if self.status in StatusReport.STATUS_CONTAINS_DATA and not force:
            # logging.warning(f"StatusReport.update_to_nothing_status: do not call this function like this for {self.path} with {self.status = }"
            #                 f", (this call will not doing anything)")
            return self
        if self.status == 'loading' and not force:
            # logging.warning(f"StatusReport.update_to_nothing_status: status still updating for {self.path}"
            #                 f", (this call will not doing anything, but anyway this line should never be reached)")
            return self
        self.status = 'nothing'
        return self._update_cache()

    def set_loading_ram_status(self) -> StatusReport:
        """
        Set the status report to 'loading_ram' status.
        :return: The updated status report
        """
        self.update_remove_extras(['ram', 'ram_single', 'ram_opened', 'progress_ram'], update_cache=False)
        return self.update_extend_extras('loading_ram', update_cache=True)

    def cancel_loading_ram_status(self) -> None:
        """
        Cancel the 'loading_ram' status.
        :return: None
        """
        self.update_remove_extras(['ram', 'ram_single', 'ram_opened', 'progress_ram', 'loading_ram'], update_cache=True)
        self.validate_ram_status()

    def set_loading_ram_progress(self, progress: float) -> None:
        """
        Set the progress of the RAM loading.
        :param progress: float between 0 and 1
        :return: None
        """
        self.update_remove_extras(['ram', 'ram_single', 'ram_opened', 'loading_ram'], update_cache=False)
        self.update_extend_extras('progress_ram', update_cache=False)
        self.payload_progress_ram = progress
        self._update_cache()

    def update_problematic_txy_ns(self, problematic_txy_ns: List[int]) -> None:
        """
        Update the problematic txy_ns list.
        :param problematic_txy_ns: The problematic txy_ns list
        :return: None
        """
        self.problematic_txy_ns = problematic_txy_ns
        self._update_cache()

    def update_loaded_data_status(self,
                                  problematic_txy_ns: Optional[List[int]],
                                  loaded_txy_files_count: int,
                                  loaded_txy_rows_count: int,
                                  data_dict_bytes: int,
                                  data_comp_bytes: int,
                                  loaded_time: Optional[datetime] = None
                                  ) -> None:
        self.problematic_txy_ns = problematic_txy_ns
        self.loaded_txy_files_count = loaded_txy_files_count
        self.loaded_txy_rows_count = loaded_txy_rows_count
        self.data_dict_bytes = data_dict_bytes
        self.data_comp_bytes = data_comp_bytes
        if loaded_time: self.time_load_ram = loaded_time
        self._update_cache()

    def validate_ram_status(self) -> bool:
        """
        Validate the RAM status of the status report.
        :return: True if the RAM status is valid, False otherwise
        """
        # if 'progress_ram' in self.extra_icons:
        if any([icon in self.extra_icons for icon in ['loading_ram', 'progress_ram']]):
            if self.path not in running_workers_ramLoading:
                logging.debug(
                    f"StatusReport.validate_ram_status: {self.path} is in loading_ram but not in running_workers_ramLoading")
                return False
        if any([icon in self.extra_icons for icon in ['ram', 'ram_single', 'ram_opened']]):
            if self.path not in data_ram_cache:
                logging.debug(f"StatusReport.validate_ram_status: {self.path} is in ram but not in data_ram_cache")
                return False
        if self.path in data_ram_cache:
            if not any([icon in self.extra_icons for icon in ['ram_single', 'ram_opened']]):
                self.update_extend_extras('ram')
        return True

    def validate_ok(self) -> Tuple[bool, bool, bool]:
        """
        Validate the status report.
        :return: (ok_path, ok_file, ok_data)
            ok_path = False if the path was modified after the last update
            ok_file = False if any file in the path was modified after the last update
            ok_data = False if the path or any files in the path were modified after the last load to RAM
        """
        ok_path = True
        ok_file = True
        ok_data = True
        try:

            if self.status not in StatusIcons.STATUS_ICONS_NAME:
                logging.warning(f"StatusReport.validate_ok: {self.path} has unknown status {self.status}")
                return (False, False, False)

            if not self.validate_ram_status(): return (False, False, False)

            self.review_path_children(force_review=True)
            self.review_path_parent(force_review=True)

            # if self.time_last_updated is None:
            #     # logging.debug(f"StatusReport.validate_ok: time_last_updated is None")
            #     return (False, False, False)

            path_last_modified_time = datetime.fromtimestamp(os.path.getmtime(self.path))
            # if path_last_modified_time is None:
            #     logging.warning(f"StatusReport.validate_ok: path {self.path} does not exist")
            #     return (False, False)
            if path_last_modified_time > self.time_last_updated:
                # logging.debug(f"StatusReport.validate_ok: path {self.path} was modified after last update")
                ok_path = False

            files_inside_path = os_listdir(self.path, invalidate_cache=True)
            for f in files_inside_path:
                # file_path = os.path.join(self.path, f)
                file_path = QDir(self.path).filePath(f)
                file_last_modified_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                # if file_last_modified_time is None:
                #     logging.warning(f"StatusReport.validate_ok: file {f} does not exist")
                #     ok_file = False
                #     break
                if file_last_modified_time > self.time_last_updated:
                    # logging.debug(f"StatusReport.validate_ok: file {path} was modified after last update")
                    ok_file = False
                if self.time_load_ram and file_last_modified_time > self.time_load_ram:
                    ok_data = False
                if not ok_file and not ok_data:
                    break

            if self.time_load_ram and path_last_modified_time > self.time_load_ram:
                ok_data = False

            return (ok_path, ok_file, ok_data)
        except AttributeError as e:
            logging.debug(f"StatusReport.validate_ok: (pop) AttributeError validating {self.path}: {e}")
            status_cache.pop(self.path)
            return (False, False, False)
        except PermissionError as e:
            logging.debug(f"StatusReport.validate_ok: PermissionError validating {self.path}: {e}")
            return (ok_path, ok_file, ok_data)
        except Exception as e:
            logging.warning(f"StatusReport.validate_ok: error validating {self.path}: {e}")
            return (False, False, False)

    def review_path_parent(self, force_recursive: Optional[bool] = None, force_review: bool = False) -> StatusReport:
        """
        Review the parent path of the current path and update its status accordingly.

        :param force_recursive: If True, force recursive review of parent paths. NOT IMPLEMENTED YET!
                                If False, do not review recursively.
                                If None, review recursively if not already reviewed.
        :type force_recursive: Optional[bool]
        :return: None
        """
        try:
            return self._review_path_parent(force_recursive=force_recursive, force_review=force_review)
        except Exception as e:
            logging.error(f"StatusReport.review_path_parent: error reviewing parent for {self.path}: {e}")
            return self

    def _review_path_parent(self, force_recursive: Optional[bool] = None, force_review: bool = False) -> StatusReport:
        parent_path = os.path.dirname(self.path)
        if os.path.islink(parent_path):
            logging.warning(f"StatusReport.review_path_parent: symbolic link encountered at {parent_path}")
            return self
        if parent_path == self.path:
            # logging.warning(f"StatusReport.review_path_parent: parent_path is same as path for {self.path}, this is root path?")
            return self

        if not OSCMgmt.has_children_contains(parent_path):
            # logging.critical(f"StatusReport.review_path_parent: hasChildren not cached for {parent_path}")
            _ = DirectoryCheckWorker.has_children(parent_path)
            if parent_path not in running_workers_hasChildren:
                logging.critical(
                    f"StatusReport.review_path_parent: hasChildren not cached or caching for {parent_path}")
                logging.critical(
                    f"StatusReport.review_path_parent: {list(running_workers_hasChildren.keys()) = }, {OSCMgmt.has_children(parent_path) = }")

        # elif not OSCMgmt.has_children(parent_path):
        #     logging.critical(f"StatusReport.review_path_parent: hasChildren logical error for {parent_path}")
        else:
            pass

        parent_status_report = status_cache.get(parent_path, None)
        if isinstance(parent_status_report, StatusReport):
            # parent_status_report.update_there_is_something()
            # parent_status_report.review_path_children()
            if self.status == 'nothing':
                # logging.debug(f"StatusReport.review_path_parent: reviewing parent.children for parent of {self.path = } with {self.status = }")
                parent_status_report.review_path_children(
                    force_review=True)  # this is to get the nothing status if all children are
            elif self.status in StatusReport.STATUS_CONTAINS_DATA:
                # logging.debug(f"StatusReport.review_path_parent: updating parent to something for {self.path = } with {self.status = }")
                parent_status_report.update_there_is_something()
            elif self.status in StatusReport.STATUS_MISTERY:
                # logging.debug(f"StatusReport.review_path_parent: updating parent to unknown for {self.path = } with {self.status = }")
                parent_status_report.update_to_unknown_status()
            else:
                logging.debug(
                    f"StatusReport.review_path_parent: not reviewing parent for {self.path} with {self.status = }")
                return self
        else:
            logging.warning(
                f"StatusReport.review_path_parent: parent_status_report not found and attempted fetching for {parent_path}")
            StatusReport.fetch_status(parent_path, on_finished=StatusReport.on_fetch_status_finished_basic)
            return self

        if force_recursive is None:
            self._reviewed_path_parent_recursively = parent_status_report._reviewed_path_parent_recursively or not force_review
            if not self._reviewed_path_parent_recursively:
                logging.debug(f"StatusReport.review_path_parent: recursion for {self.path}")
                parent_status_report.review_path_parent(force_recursive=force_recursive)
            else:
                # logging.debug(f"StatusReport.review_path_parent: already recursively searched for {self.path}")
                pass
        elif force_recursive:
            self._reviewed_path_parent_recursively = True
            parent_status_report.review_path_parent(force_recursive=True)
            logging.warning(f"StatusReport.review_path_parent: forced recursion for {self.path}")
            warnings.warn("StatusReport.review_path_parent: force_recursive is not implemented yet", RuntimeWarning)
        else:
            # self._reviewed_path_parent_recursively = False
            # parent_status_report.review_path_parent(force_recursive = False)
            if self._reviewed_path_parent_recursively:
                logging.warning(
                    f"StatusReport.review_path_parent: force_recursive = False but already reviewed recursively for {self.path}")
            else:
                pass
                # logging.debug(f"StatusReport.review_path_parent: force_recursive = False and not reviewed recursively for {self.path}")
        return self

    def review_path_children(self, force_recursive: Optional[bool] = None, force_review: bool = False) -> StatusReport:
        """
        Review the children paths of the current path and update the status accordingly.

        :return: None
        """
        try:
            return self._review_path_children(force_recursive=force_recursive, force_review=force_review)
        except Exception as e:
            logging.error(f"StatusReport.review_path_children: error reviewing children for {self.path}: {e}")
            return self

    def _review_path_children(self, force_recursive: Optional[bool] = None, force_review: bool = False) -> StatusReport:
        """
        just a wrapper for review_path_children to catch exceptions
        """
        if force_recursive:
            warnings.warn("StatusReport.review_path_children: force_recursive is not implemented yet", RuntimeWarning)
            logging.warning(f"StatusReport.review_path_children: force_recursive is not implemented yet")

        if self.status not in ['nothing', 'unknown'] and not force_review:
            # logging.debug(f"StatusReport.review_path_children: not reviewing children for {self.path} with {self.status = }")
            return self

        children_paths = os_listdirdir(self.path, invalidate_cache=True)
        at_least_one_unknown = False

        for child_path_name in children_paths:
            child_path = QDir(self.path).filePath(child_path_name)
            # logging.debug(f"StatusReport.review_path_children: checking child_path = {child_path}")
            if os.path.islink(child_path):
                logging.debug(f"StatusReport.review_path_children: symbolic link encountered at {child_path}")
                continue
            child_status_report = status_cache.get(child_path, None)

            # if isinstance(child_status_report, StatusReport):
            #     logging.warning(f"StatusReport.review_path_children: child_status_report found for {child_path}, {child_status_report.status = }")
            # else:
            #     logging.warning(f"StatusReport.review_path_children: child_status_report not found for {child_path}")

            if not isinstance(child_status_report, StatusReport):
                # logging.warning(f"StatusReport.review_path_children: child_status_report not found for {child_path}")
                at_least_one_unknown = True
                continue
            elif child_status_report.status in StatusReport.STATUS_CONTAINS_DATA:
                self.update_there_is_something()  # 'something' take precedence over 'nothing' and 'unknown'
                return self
            elif child_status_report.status in StatusReport.STATUS_MISTERY:
                at_least_one_unknown = True  # indicate possible 'unknown' status
            elif child_status_report.status in StatusReport.STATUS_NOTHING:
                continue
            else:
                logging.critical(f"StatusReport.review_path_children: unexpected case {child_status_report.status = }")
                continue
        if at_least_one_unknown:
            # logging.debug(f"StatusReport.review_path_children: set to unknown for {self.path = }")
            self.update_to_unknown_status()  # 'unknown' take precedence over 'nothing'
        else:  # all children are nothing
            # logging.debug(f"StatusReport.review_path_children: is indeed nothing for {self.path = }")
            # if self.status == 'something' or force_review:
            #     self.update_to_nothing_status(force=True)
            # else:
            self.update_to_nothing_status()  # 'nothing' since all children are 'nothing'
        return self

    @staticmethod
    def _sort_extra_icons(extra_icons: list[str]) -> list[str]:
        return sorted(extra_icons, key=lambda x: StatusIcons.STATUS_ICONS_EXTRA_NAME_SORT_KEY.get(x, 0))

    @staticmethod
    def _extra_icons_to_QIcons(extra_icons: list[str]) -> list[object]:
        return [StatusIcons.ICONS_EXTRA.get(icon_key) for icon_key in extra_icons]

    @staticmethod
    def _sorted_extra_icons_to_QIcons(extra_icons: list[str]) -> list[object]:
        return [StatusIcons.ICONS_EXTRA.get(icon_key) for icon_key in StatusReport._sort_extra_icons(extra_icons)]

    @staticmethod
    def return_extra_icons_paintable(status_report: StatusReport) -> object:
        """
        Return Qt objects for .paint method for the extra icons.
        :param status_report:
        :return: QIcons
        """
        candidate = deepcopy(status_report.extra_icons)
        if 'progress_ram' in candidate:
            candidate.remove('progress_ram')
            candidate_return = StatusReport._sorted_extra_icons_to_QIcons(candidate)
            if status_report.payload_progress_ram is None:
                logging.warning(
                    f"StatusReport.return_extra_icons_paintable: progress_ram icon found but no progress value for {status_report.path}")
                status_report.update_remove_extras('progress_ram')
                return candidate_return
            else:
                candidate_return.insert(0, circular_progress_QIcon_cached(status_report.payload_progress_ram))
                return candidate_return
        else:
            return status_report._sorted_extra_icons_to_QIcons(candidate)

    @staticmethod
    def get_valid_status_report(file_path: str) -> Tuple[int, Optional[StatusReport]]:
        logging.debug(f"get_valid_status_report: file_path = {file_path}")
        status_report = status_cache.get(file_path)
        if status_report is None:
            logging.warning(f"  status_cache is None for {file_path = }")
            return (-1, None)
        if not isinstance(status_report, StatusReport):
            logging.warning(f"  status_cache is not a StatusReport for {file_path = }")
            return (-2, None)
        logging.debug(f"  {status_report.status = }")
        if not status_report.status in StatusReport.STATUS_CONTAINS_DATA_HERE:
            # logging.warning(f"  status is not STATUS_OK for {file_path = }")
            return (-3, None)
        return (0, status_report)

    @staticmethod
    def fetch_status(folder_path: str,
                     on_finished: Optional[Callable[[str], Any]] = None) -> StatusReport:
        """
        """
        # logging.debug(f"Getting status for: {folder_path}")
        # Check if the status is already cached
        status_data = status_cache.get(folder_path, None)
        if status_data is not None:
            if not isinstance(status_data, StatusReport):
                logging.warning(f"fetch_status: status_data is not StatusReport: {status_data}")
                scp = status_cache.pop(folder_path, None)
                if not scp: logging.critical(f"fetch_status: status_cache.pop failed for {folder_path}")
                return StatusReport.fetch_status(folder_path, on_finished)
            if status_data.status == 'loading':
                if folder_path in running_workers_status: # legit loading
                    return status_data
                else: # loading but worker is gone (unexpected)
                    logging.warning(f"fetch_status: loading but worker is gone for: {folder_path}")
                    scp = status_cache.pop(folder_path, None)
                    # REVIEW: potentially causing race condition, memory leak, race condition, etc.
                    if not scp: logging.critical(f"fetch_status: status_cache.pop failed for {folder_path}")
                    return StatusReport.fetch_status(folder_path, on_finished)
            else:
                return status_data
        else: # status_data is None from cache
            # Check if a worker is already running for this folder_path
            loading_status = StatusReport(folder_path, 'loading', -300, [])
            if folder_path in running_workers_status:
                # logging.debug(f"fetch_status worker already running for: {folder_path}")
                status_cache[folder_path] = loading_status
                return loading_status
            # else: # not in running_workers_status

            logging.debug(f"fetch_status: not cached for: {folder_path}")

            def callback(folder_path: str) -> None:
                StatusReport.on_fetch_status_finished_basic(folder_path)
                # if on_finished: on_finished(folder_path)
                if on_finished: QTimer.singleShot(1, lambda: on_finished(folder_path))  # type: ignore[reportOptionalCall, unused-ignore] # pyright problem (?)

            # Create and start the worker
            worker = StatusWorker(folder_path)
            worker.signals.finished.connect(callback)
            thread_pool_general.start(worker, priority=QThread.Priority.LowestPriority.value)   # type: ignore[call-overload]
            running_workers_status[folder_path] = worker
            return loading_status

    @staticmethod
    def on_fetch_status_finished_basic(path: str) -> None:
        status_report = status_cache.get(path, None)
        if not isinstance(status_report, StatusReport):
            logging.critical(f"on_fetch_status_finished_basic: (IMPOSSIBLE) status_report is not StatusReport: {status_report}")
            return

        logging.debug(f"on_fetch_status_finished_basic: path = {status_report.path}, status = {status_report.status}, count = {status_report.count}, extras = {status_report.extra_icons}")

        # if path != status_report.path:
        #     logging.critical(f"on_fetch_status_finished_basic: (IMPOSSIBLE) path mismatch: {path = }, {status_report.path = }")
        # if path in running_workers_status:
        #     worker = running_workers_status[path]
        #     del running_workers_status[path]
        # else:
        #     logging.warning(f"on_fetch_status_finished_basic: worker not in running_workers_status for {path}")

        if path in running_workers_status:
            logging.warning(f"on_fetch_status_finished_basic: worker should have already been removed, del anyway {path = }")
            del running_workers_status[path]

        if path in status_cache:
            pass
        else:
            logging.warning(f"on_fetch_status_finished_basic: worker not in status_cache for {path}")
        pass

from helab.workers.StatusWorker import StatusWorker