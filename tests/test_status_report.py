"""``StatusReport``: plain data for the folder browser."""
from __future__ import annotations

from datetime import datetime

from helab.models.StatusReport import StatusReport


def test_a_report_made_without_a_time_has_the_time_it_was_made() -> None:
    """Not HeLab's start time: a default argument would be evaluated once, at import."""
    before = datetime.now()
    report = StatusReport("/data/F", "unknown", -1, [])
    assert before <= report.time_last_updated <= datetime.now()
