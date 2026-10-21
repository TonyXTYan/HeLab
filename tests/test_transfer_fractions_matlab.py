"""Transfer fractions' counts against the lab's MATLAB, on synthetic shots.

``fraction_calc`` below is ``lib/fraction_calc.m`` (Momentum_Bells_test) with
``masktxy_square.m`` (Core_BEC_Analysis), line for line in Python: shots with more than
``num_lim`` counts (``num_counts``, counted by ``import_mcp_tdc_data`` inside the import's
``txylim``) are kept; each window counts the events strictly inside it and inside the XY
``bounds``; the fractions are over the last, wide window. HeLab counts the same events per
order. The intended differences are tested at the end:

- HeLab's fractions are over the sum of the orders, MATLAB's over a wide window holding
  them: the same when the windows touch, but events between narrower windows (or outside
  the wide one) count only in MATLAB's total.
- HeLab leaves out shots by their counts in the counting box; MATLAB by its import box
  (±35 mm in monitor_momentum.m, against ±30 mm for counting).
- Window edges: MATLAB's windows are open, so an event exactly on an edge counts nowhere;
  HeLab's are half-open [low, high), so it counts in the later order's window.
- monitor_momentum.m rotates X/Y by ``dld_xy_rot`` (0.61 rad) before both boxes; HeLab
  boxes the X/Y as loaded.
- The XY box: MATLAB's is open (|X|, |Y| < 30 mm, ``masktxy_square``), HeLab's closed
  (≤ ``XY box ±``), so an event exactly on its edge counts only here.
- MATLAB's import keeps only T within 0–4 s (``txylim``); HeLab has no T limit before the
  windows, so only Search T and the windows bound T.
- monitor_momentum.m waits until a shot's last event is past ``dld_aquire`` (2 s), its check
  that the file is written; HeLab reads only settled files (Live: a whole last row, unchanged
  since the previous check) and has no last-event check.
"""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import numpy.typing as npt
import pytest

from helab.analysis.dataset_view import DatasetView, build_view
from helab.analysis.orders import Fractions, Orders
from helab.analysis.parameters import effective
from helab.analysis.results import AnalysisContext
from helab.scripts.standard import transfer_fractions as tf
from helab.utils.folder_cache import Dataset

CENTRE, SPACING, SIGMA = 2.1375, 0.0125, 0.001
Bounds = Sequence[tuple[float, float]]


def masktxy_square(txy: npt.NDArray[np.float64], lims: Bounds) -> npt.NDArray[np.float64]:
    mask = np.ones(len(txy), dtype=bool)
    for axis, (low, high) in enumerate(lims):
        mask &= (txy[:, axis] > low) & (txy[:, axis] < high)
    return txy[mask]


def fraction_calc(shots: dict[int, npt.NDArray[np.float64]], t_bounds: Sequence[tuple[float, float]],
                  num_lim: int, bounds: Bounds, import_lims: Bounds) -> dict[str, Any]:
    """fraction_calc.m: ``t_bounds``' last entry is the wide window the fractions are over."""
    imported = {shot: masktxy_square(txy, import_lims) for shot, txy in shots.items()}
    shot_num = [shot for shot, txy in imported.items() if len(txy) > num_lim]
    ns = np.zeros((len(shot_num), len(t_bounds)))
    for row, shot in enumerate(shot_num):
        for column, window in enumerate(t_bounds):
            ns[row, column] = len(masktxy_square(imported[shot], [window, *bounds]))
    with np.errstate(invalid="ignore", divide="ignore"):
        fracs = ns / ns[:, -1:]
    return {"shot_num": shot_num, "Ns": ns, "fracs": fracs, "Ntotal": ns[:, -1]}


def shot_events(rng: np.random.Generator, shot: int, background: int = 0) -> npt.NDArray[np.float64]:
    populations = {-2: 20, -1: 90 + 5 * shot, 0: 500 - 20 * shot, 1: 60 + 15 * shot, 2: 25}
    times = np.concatenate([rng.normal(CENTRE + order * SPACING, SIGMA, count)
                            for order, count in populations.items()])
    times = np.concatenate((times, rng.uniform(CENTRE - 0.05, CENTRE + 0.05, background)))
    xy = rng.normal(0, 0.02, (len(times), 2))  # some fall outside the ±30 mm box
    return np.column_stack((times, xy))


def view(shots: dict[int, npt.NDArray[np.float64]]) -> DatasetView:
    fingerprint = [[shot, 100 + shot, 1_000 + shot] for shot in sorted(shots)]
    return build_view(Dataset("/data/root/run_1", "sig-1", {shot: array.copy() for shot, array in shots.items()},
                              {"fingerprint": fingerprint, "source": "files", "loaded_at": 1_700_000_000.0}, 0))


def helab(shots: dict[int, npt.NDArray[np.float64]], values: dict[str, Any]) -> Fractions:
    script = tf.TransferFractions()
    data = view(shots)
    context = AnalysisContext("a1", "Plot", data, effective(script.parameters("Plot"), values),
                              script.get_metadata().identity())
    result = script.compute("Plot", context)
    assert isinstance(result, Fractions)
    return result


def matlab_windows(orders: Orders) -> list[tuple[float, float]]:
    """HeLab's order windows, then the wide window from the first one's start to the last one's end."""
    windows = [orders.window(order) for order in orders.numbers]
    return [*windows, (windows[0][0], windows[-1][1])]


def manual(half_width: float = 0.0, xy: float = 0.03, minimum: int = 50) -> dict[str, Any]:
    return {"orders_mode": tf.MANUAL, "centre": CENTRE, "spacing": SPACING, "half_width": half_width,
            "xy_half": xy, "min_counts": minimum}


def box(half: float) -> list[tuple[float, float]]:
    return [(-half, half), (-half, half)]


ALL_T = (-np.inf, np.inf)


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("half_width", [0.0, 0.004])
def test_counts_per_shot_match_fraction_calc(seed: int, half_width: float) -> None:
    rng = np.random.default_rng(seed)
    shots = {shot: shot_events(rng, shot, background=40) for shot in range(1, 13)}
    shots[13] = shot_events(rng, 13)[:50]  # under 50 counts in the box: left out by both
    ours = helab(shots, manual(half_width))
    theirs = fraction_calc(shots, matlab_windows(ours.orders), 50, box(0.03), [ALL_T, *box(0.03)])
    assert ours.shots.tolist() == theirs["shot_num"] and 13 not in theirs["shot_num"]
    assert np.array_equal(ours.counts, theirs["Ns"][:, :-1])
    if half_width == 0.0:
        # Touching windows: MATLAB's wide window holds exactly the orders, so the fractions agree.
        assert np.array_equal(theirs["Ntotal"], ours.counts.sum(axis=1))
        assert np.allclose(ours.fractions, theirs["fracs"][:, :-1])
    else:
        # Narrower windows: the background between them is in MATLAB's total only.
        assert (theirs["Ntotal"] > ours.counts.sum(axis=1)).all()
        assert np.allclose(ours.fractions.sum(axis=1), 1.0)
        assert (theirs["fracs"][:, :-1].sum(axis=1) < 1.0).all()


def test_auto_orders_count_like_fraction_calc_with_their_windows() -> None:
    rng = np.random.default_rng(4)
    shots = {shot: shot_events(rng, shot) for shot in range(1, 9)}
    ours = helab(shots, {})
    assert ours.orders.centre == pytest.approx(CENTRE, abs=2e-4) and ours.notes == ()
    theirs = fraction_calc(shots, matlab_windows(ours.orders), 50, box(0.03), [ALL_T, *box(0.03)])
    assert np.array_equal(ours.counts, theirs["Ns"][:, :-1])
    assert np.allclose(ours.fractions, theirs["fracs"][:, :-1])


def test_zero_totals_are_not_a_number_in_both() -> None:
    rng = np.random.default_rng(5)
    shots = {1: shot_events(rng, 1), 2: np.column_stack((rng.normal(3.0, SIGMA, 300), np.zeros((300, 2))))}
    ours = helab(shots, manual())
    theirs = fraction_calc(shots, matlab_windows(ours.orders), 50, box(0.03), [ALL_T, *box(0.03)])
    assert theirs["Ntotal"][1] == 0 and ours.counts[1].sum() == 0
    assert np.array_equal(np.isnan(ours.fractions), np.isnan(theirs["fracs"][:, :-1]))
    assert np.isnan(ours.fractions[1]).all() and np.isfinite(ours.fractions[0]).all()


def test_shots_are_left_out_by_the_counting_box_not_the_import_box() -> None:
    """monitor_momentum.m imports within ±35 mm, which decides num_counts > 50, and counts within
    ±30 mm; HeLab decides with the counting box (Minimum counts, "in the XY box")."""
    rng = np.random.default_rng(6)
    times = rng.normal(CENTRE, SIGMA, 60)
    inner = np.column_stack((times[:45], np.zeros((45, 2))))  # 45 inside ±30 mm
    ring = np.column_stack((times[45:], np.full((15, 2), 0.032)))  # 15 between ±30 and ±35 mm
    shots = {1: np.concatenate((inner, ring)), 2: shot_events(rng, 2)}
    ours = helab(shots, manual())
    theirs = fraction_calc(shots, matlab_windows(ours.orders), 50, box(0.03), [(0.0, 4.0), *box(0.035)])
    assert theirs["shot_num"] == [1, 2] and ours.shots.tolist() == [2]
    assert theirs["Ns"][0, 2] == 45  # MATLAB keeps shot 1 and counts its 45 in order 0


def test_an_event_on_a_window_edge() -> None:
    orders = Orders(CENTRE, SPACING, SPACING / 2, 1)
    edge = orders.window(0)[1]  # order 0's end, order +1's start
    events = np.column_stack((np.concatenate(([edge], np.full(60, CENTRE))), np.zeros((61, 2))))
    ours = helab({1: events}, manual(minimum=0) | {"orders_each_side": 1})
    theirs = fraction_calc({1: events}, matlab_windows(ours.orders), 0, box(0.03), [ALL_T, *box(0.03)])
    assert ours.counts[0].tolist() == [0, 60, 1]  # HeLab: in +1's window
    assert theirs["Ns"][0, :-1].tolist() == [0, 60, 0]  # MATLAB: in neither
