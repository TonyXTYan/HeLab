"""Focused tests for scan-diff mass alignment and subtraction."""

import pytest

from side_projects.rga_visualiser.rgadata_diff import align_masses, compute_difference


def test_align_masses_is_noop_when_grids_match() -> None:
    masses, values_a, values_b = align_masses(
        (1.0, 2.0, 3.0), (10.0, 20.0, 30.0), (1.0, 2.0, 3.0), (1.0, 2.0, 3.0)
    )
    assert masses == (1.0, 2.0, 3.0)
    assert values_a == (10.0, 20.0, 30.0)
    assert values_b == (1.0, 2.0, 3.0)


def test_align_masses_interpolates_b_onto_as_grid() -> None:
    masses, values_a, values_b = align_masses(
        (1.0, 2.0, 3.0), (10.0, 20.0, 30.0), (1.0, 3.0), (0.0, 4.0)
    )
    assert masses == (1.0, 2.0, 3.0)
    assert values_a == (10.0, 20.0, 30.0)
    assert values_b == pytest.approx((0.0, 2.0, 4.0))


def test_align_masses_restricts_to_overlap() -> None:
    masses, values_a, values_b = align_masses(
        (1.0, 2.0, 3.0, 4.0), (1.0, 2.0, 3.0, 4.0), (2.0, 3.0), (20.0, 30.0)
    )
    assert masses == (2.0, 3.0)
    assert values_a == (2.0, 3.0)
    assert values_b == pytest.approx((20.0, 30.0))


def test_align_masses_rejects_disjoint_ranges() -> None:
    with pytest.raises(ValueError, match="no overlapping mass range"):
        align_masses((1.0, 2.0), (1.0, 2.0), (5.0, 6.0), (5.0, 6.0))


def test_compute_difference_matching_grids() -> None:
    masses, diff = compute_difference(
        (1.0, 2.0, 3.0), (10.0, 20.0, 30.0), (1.0, 2.0, 3.0), (1.0, 2.0, 3.0)
    )
    assert masses == (1.0, 2.0, 3.0)
    assert diff == pytest.approx((-9.0, -18.0, -27.0))


def test_compute_difference_differing_grids() -> None:
    masses, diff = compute_difference(
        (1.0, 2.0, 3.0), (10.0, 20.0, 30.0), (1.0, 3.0), (0.0, 4.0)
    )
    assert masses == (1.0, 2.0, 3.0)
    assert diff == pytest.approx((-10.0, -18.0, -26.0))
