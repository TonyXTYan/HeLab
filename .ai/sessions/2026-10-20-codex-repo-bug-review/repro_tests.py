"""Temporary review probes; moved to session evidence after execution."""
import weakref

from test_plot_ram_budget import cache, runner, window, open_plot  # noqa: F401
from test_correlations_plot import txy_view, poisson_velocities
from helab.scripts.dld import correlations_plot
from helab.utils.io_service import IORequest
from helab.utils.ram_buffers import buffer_of


def test_root_replacement_does_not_inherit_previous_roots_constants(cache, qtbot):
    root = "/data/root"
    cache._root_seen(root, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "old")
    cache.remember_constants(root, {"values": {"fall_distance": 0.91}, "set_at": 20.0})
    request = IORequest("probe", 0, root, "list", {}, 60)
    cache.service.resultReady.emit(request, {
        "kind": "root_changed", "path": root, "location": "vol://test/data/root",
        "uuid": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "label": "replacement"})
    # The replacement root has no constants in its store. A successful read omits that field.
    cache.refresh_saved([root])
    assert cache.effective_folder_constants(root + "/run") == {}


class FastCorrelations(correlations_plot.Correlations):
    def parameters(self, action):
        from dataclasses import replace
        return [replace(spec, default=0) if spec.name in ("n_boot", "budget")
                else spec for spec in super().parameters(action)]


def test_correlations_state_counts_toward_ram(window, qtbot):
    plot = open_plot(window, qtbot, txy_view(poisson_velocities(43, 3, 100)), FastCorrelations())
    state = correlations_plot.plot_state(plot.instance_id, plot.path)
    assert state.counts is not None
    arrays = [entry.events for entry in state.counts._entries.values()]
    assert sum(a.nbytes for a in arrays) > 0
    measured = plot.ram_buffers()
    assert all(buffer_of(a)[0] in measured for a in arrays)


def test_releasing_correlations_frees_private_arrays(window, qtbot):
    correlations_plot._CLOSED.clear()
    plot = open_plot(window, qtbot, txy_view(poisson_velocities(44, 3, 100)), FastCorrelations())
    state = correlations_plot.plot_state(plot.instance_id, plot.path)
    assert state.counts is not None
    array = weakref.ref(next(iter(state.counts._entries.values())).events)
    del state
    assert plot.release()
    import gc
    gc.collect()
    assert array() is None
