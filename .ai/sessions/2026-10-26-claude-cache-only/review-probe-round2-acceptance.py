from pathlib import Path
import sys
from typing import Any
import pytest
from unittest.mock import patch

sys.path.insert(0, '/Users/tonyyan/GitHub-Local/.maestri/floors/HeLab--agentcache-only/.ai/temp/review-cache-only/tests')
from test_offline_browsing import (back_online, offline_restart, no_source_io, cached_read, deny_source,
                                  answer, frozen_service, experiment, browse_online)
from test_result_cache_plots import Costly, close, make_window, stop_runners
from helab.analysis.presets import SavedPlot, ScriptRef
from helab.utils.folder_cache import get_folder_cache, store_options
from helab.utils.io_service import IOService
from helab.views.plots.arrangement import FolderWait
from helab.views.plots.instance import AnalysisInstance
from helab.views.plots.script_tree import TreePanelWidget
from helab.io_ops import stores, infra
from helab.utils.cache_paths import Mount
from helab.utils.data_roots import DataRoots, LocalVolumes, RootLocation

def test_offline_reopened_plot_with_real_cache_read_and_denied_source(qtbot, monkeypatch, tmp_path, offline_restart):
    service, cache, data = offline_restart
    run = str(data / 'day/run_1')
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    script = Costly()
    panel = TreePanelWidget(window.plots)
    qtbot.addWidget(panel)
    metadata = script.get_metadata()
    monkeypatch.setattr(panel, 'find_script', lambda ref: (metadata, script))
    wait = FolderWait(cache, run)
    try:
        instance = panel.reopen_plot(SavedPlot(ScriptRef.of(metadata.identity(), 'Plot', metadata.name), run), wait)
        assert isinstance(instance, AnalysisInstance) and instance.waiting()
        cached_read(qtbot, service, run, tmp_path)
        from helab.io_ops.results import result_find
        lookup = next(r for r in service.pending if r.operation == 'result_find').payload
        output = tmp_path / 'lookup'
        output.mkdir()
        answer(qtbot, service, 'result_find', run, lambda send: result_find(run, str(output), store_options(), lookup['lookup'], lookup.get('family', ''), send))
        qtbot.waitUntil(lambda: instance.shown is not None and not instance.job_id, timeout=10000)
        assert script.computed == 1
        assert not any(r.operation not in IOService.OFFLINE_OPERATIONS for r in service.pending)
        assert window.budget.measure().total > 0
    finally:
        wait.stop()
        close(window)

def test_custom_local_volume_beats_stale_nested_share_hint():
    class Hints:
        def mount_hints(self):
            return {'/srv/lab/subdir': 'smb://old-server/old-share'}
    current = Mount('/dev/sdb1', '/srv/lab', 'ext4', False)
    paths, volumes = stores._offline_mounts(Hints(), [current], LocalVolumes([(current, 'new-disk')]))
    roots = [RootLocation('smb://old-server/old-share', 'old-root'), RootLocation('vol://new-disk', 'new-root')]
    resolver = DataRoots(paths, roots, local_location=volumes.location, local_source=volumes.source)
    assert resolver.key('/srv/lab/subdir/run') == 'root://new-root/subdir/run'

def test_finished_load_real_helper_is_killed_at_offline_switch(qtbot, monkeypatch, tmp_path):
    import json
    import numpy as np
    from helab.io_ops.loading import load
    from helab.utils.folder_cache import Dataset
    source = tmp_path / 'run'
    source.mkdir()
    for shot in (1, 2):
        (source / f'd_txy_forc{shot}.txt').write_text(f'{shot},2,3\n')
    file = source / 'd_txy_forc1.txt'
    fingerprint = [1, file.stat().st_size, file.stat().st_mtime_ns]
    data = {1: np.ones((1, 3))}
    service = IOService()
    cache = get_folder_cache(service)
    path = str(source)
    entry = Dataset(path, 'old', data, {'fingerprint': [fingerprint], 'bytes': 24}, 0)
    cache.datasets[(path, entry.signature, 0)] = entry
    gate = tmp_path / 'gate'
    gate.mkdir()
    (gate / 'd_txy_forc2.txt.go').touch()
    trace = tmp_path / 'trace'
    trace.mkdir()
    monkeypatch.setenv('HELAB_TEST_READ_GATE', str(gate))
    monkeypatch.setenv('HELAB_TEST_IO_TRACE', str(trace))
    loaded = []
    def event(request, result):
        if request.owner == 'tab' and result['kind'] == 'loaded':
            loaded.append(result)
            cache.set_offline(True)
    cache.resultReady.connect(event)
    try:
        assert cache.submit('tab', 0, path, 'load', {'cache': store_options()})
        qtbot.waitUntil(lambda: bool(loaded), timeout=10000)
        qtbot.waitUntil(lambda: not service.active and not service.retired, timeout=10000)
        assert cache.latest_dataset(path) is not None
        events = [json.loads(line) for file in trace.glob('*.jsonl') for line in file.read_text().splitlines()]
        assert not any(e.get('reason') == 'cache save: read' for e in events)
        assert cache.cache_status(path).error == IOService.OFFLINE_SAVE_STOPPED
        assert not cache.quit_saves()
    finally:
        service.shutdown()

@pytest.mark.parametrize('a_kind', ['found', 'missing', 'saved', 'not_saved', 'pending', 'adopted', 'adopt_failed', 'adopt_replanned', 'presets', 'presets_ack', 'inventory', 'counts', 'usage'])
@pytest.mark.parametrize('b_kind', ['presets', 'missing', 'not_saved', 'inventory', 'counts'])
def test_store_identity_and_quit_accounting_still_hold_offline(monkeypatch, a_kind, b_kind):
    import test_store_identity as identity
    service = frozen_service(monkeypatch)
    cache = get_folder_cache(service)
    cache.set_offline(True)
    try:
        identity.test_every_order_of_two_stores_answers_ends_on_the_store_the_folder_holds(
            cache, 'A in use', a_kind, b_kind, 'B then A', 'A asked first', 'fails, then recovers')
        assert all(request.operation in IOService.OFFLINE_OPERATIONS for request in service.pending)
    finally:
        service.shutdown()
