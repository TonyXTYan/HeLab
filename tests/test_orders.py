"""Transfer fractions' order detection (``helab/analysis/orders.py``) on its own: the parts the
plot's tests (``test_transfer_fractions*.py``) reach only through a whole run."""
from __future__ import annotations

import subprocess
import sys

import numpy as np
import pytest

from helab.analysis.orders import Orders, chosen_by_search, guided_spacing, in_box, order_label, unsure, window_half


def test_orders_import_no_qt_or_plotting_library() -> None:
    script = ("import sys, helab.analysis.orders; "
              "print(sorted({m.split('.')[0] for m in sys.modules} & {'PyQt6', 'pyqtgraph', 'plotly', 'matplotlib'}))")
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"


def test_labels_and_xy_box() -> None:
    assert [order_label(order) for order in (-2, 0, 1)] == ["−2", "0", "+1"]
    events = np.array([[1.0, 0.0, 0.0], [2.0, 0.02, -0.02], [3.0, 0.04, 0.0], [4.0, 0.0, -0.04]])
    assert in_box(events, 0.0) is events  # 0: no XY limit
    assert in_box(events, 0.03)[:, 0].tolist() == [1.0, 2.0]


def test_window_half_is_clipped_to_half_the_spacing() -> None:
    assert window_half(0.0, 0.01) == (0.005, "")
    assert window_half(0.002, 0.01) == (0.002, "")
    half, note = window_half(0.008, 0.01)
    assert half == 0.005 and note.startswith("Window ± 8 ms is over half the spacing: using 5 ms")


def test_guided_spacing_takes_peaks_near_whole_reference_spacings() -> None:
    clusters = (0.0, 0.005, 0.015, -0.015)
    times = np.concatenate([position + np.linspace(-0.0005, 0.0005, 21) for position in clusters])
    bump, plus, minus = (0.005, 50.0), (0.015, 30.0), (-0.015, 30.0)
    assert guided_spacing(times, 0.0, [bump, plus, minus], 0.015, 1, 0.002) == pytest.approx(0.015)
    assert guided_spacing(times, 0.0, [bump], 0.015, 1, 0.002) is None  # a bump between orders is none


def test_unsure_warns_unless_search_t_leaves_the_rival_out() -> None:
    orders = Orders(1.0, 0.1, 0.05, 1)
    totals = np.array([60, 100, 10], dtype=np.int64)  # orders −1, 0, +1
    assert unsure(orders, totals, -np.inf, np.inf) == (
        "⚠ order 0 unsure: order −1 holds 60% as many events as order 0; set both ends of Search T around "
        "order 0, or the orders by hand",)
    assert unsure(orders, totals, 0.95, 1.2) == ("order −1 (outside Search T) holds 60% as many events as order 0",)
    assert unsure(orders, np.array([40, 100, 10], dtype=np.int64), -np.inf, np.inf) == ()


def test_chosen_by_search_needs_both_ends() -> None:
    assert chosen_by_search(2.0, 1.0, 1.5)
    assert not chosen_by_search(1.2, 1.0, 1.5)
    assert not chosen_by_search(2.0, 1.0, np.inf)
