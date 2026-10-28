# helab/models/StatusReport.py
"""A folder's status as the folder browser shows it: plain data, no I/O."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional


class StatusReport:
    STATUS_CONTAINS_DATA = ['ok', 'fixable', 'warning', 'critical', 'something']
    STATUS_CONTAINS_DATA_HERE = ['ok', 'fixable', 'warning', 'critical']
    STATUS_NOTHING = ['nothing', 'missing']

    def __init__(self,
                 path: str,
                 status: str,
                 count: int,
                 extra_icons: list[str],
                 d_dld_shots: Optional[List[int]] = None,
                 d_txy_shots: Optional[List[int]] = None,
                 time_last_updated: Optional[datetime] = None
                 ):
        self.path = path
        self.status = status
        self.count = count
        self.extra_icons = extra_icons
        self.d_dld_shots = d_dld_shots
        self.d_txy_shots = d_txy_shots
        self.time_last_updated = datetime.now() if time_last_updated is None else time_last_updated

        # The loaded dataset's, set by the tab that shows it.
        self.problematic_txy_ns: Optional[List[int]] = None
        self.loaded_txy_files_count: Optional[int] = None
        self.loaded_txy_rows_count: Optional[int] = None
        self.data_dict_bytes: Optional[int] = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StatusReport):
            return False
        return (self.path == other.path
                and self.status == other.status
                and self.count == other.count
                and self.extra_icons == other.extra_icons
                and self.d_dld_shots == other.d_dld_shots
                and self.d_txy_shots == other.d_txy_shots
                and self.problematic_txy_ns == other.problematic_txy_ns
                and self.time_last_updated == other.time_last_updated
                )

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __str__(self) -> str:
        return (f"StatusReport({self.path})")
