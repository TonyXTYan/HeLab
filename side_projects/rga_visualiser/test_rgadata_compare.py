"""Focused tests for RGA comparison trace preparation."""

from pathlib import Path

import pytest

from side_projects.rga_visualiser.rga_visualiser import RGAData, Scan
from side_projects.rga_visualiser.rgadata_compare import (
    ReductionMode,
    TraceSelection,
    discover_rgadata_files,
    normalise_spectrum,
    reduce_scans,
    selection_label,
)


def sample_data() -> RGAData:
    return RGAData(
        metadata={},
        masses=(1.0, 2.0, 3.0),
        scans=(
            Scan(0, 0.0, (1.0, 2.0, 3.0)),
            Scan(0, 1.0, (3.0, 4.0, 5.0)),
            Scan(0, 2.0, (5.0, 6.0, 7.0)),
        ),
    )


def test_reduce_single_scan() -> None:
    selection = TraceSelection(ReductionMode.SINGLE, {1})
    assert reduce_scans(sample_data(), selection) == (3.0, 4.0, 5.0)
    assert selection_label(selection) == "scan 2"


def test_reduce_mean_of_all_scans() -> None:
    selection = TraceSelection(ReductionMode.MEAN_ALL, {0})
    assert reduce_scans(sample_data(), selection) == (3.0, 4.0, 5.0)
    assert selection_label(selection) == "mean: all scans"


def test_reduce_mean_of_selected_scans() -> None:
    selection = TraceSelection(ReductionMode.MEAN_SELECTED, {0, 2})
    assert reduce_scans(sample_data(), selection) == (3.0, 4.0, 5.0)
    assert selection_label(selection) == "mean: scans 1, 3"


def test_normalise_spectrum_uses_positive_maximum() -> None:
    assert normalise_spectrum((-1.0, 2.0, 4.0)) == (-0.25, 0.5, 1.0)


def test_normalise_spectrum_rejects_non_positive_data() -> None:
    with pytest.raises(ValueError, match="no positive values"):
        normalise_spectrum((-1.0, 0.0))


def test_discover_rgadata_files_is_non_recursive(tmp_path: Path) -> None:
    (tmp_path / "b.rgadata").write_bytes(b"")
    (tmp_path / "A.RGADATA").write_bytes(b"")
    (tmp_path / "ignore.txt").write_text("", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "hidden.rgadata").write_bytes(b"")

    assert [path.name for path in discover_rgadata_files(tmp_path)] == [
        "A.RGADATA",
        "b.rgadata",
    ]
