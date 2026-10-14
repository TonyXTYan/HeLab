# helab/models/StatusReport.py
"""A folder's status as the folder browser shows it: plain data, no I/O."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple


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
