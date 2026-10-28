# Repository bug review

Reviewed clean HEAD `43aa3de5af063d8226754332e9fb4de76e5596ff`, focusing on the latest DLD analysis merge, constants/root identity and cache interactions. This is a targeted review, not an exhaustive audit of the repository.

## Findings

1. **P1: folder constants survive a change of data-root identity.** `FolderCache` stores constants and their confirmed fallback by source path. The `root_changed` event resets status/cache kinds but neither that handler nor `_constants_roots_moved` resets the constants. A subsequent successful read of a root with no constants omits the constants field, leaving the previous root's values active. Even another root's explicitly saved constants can lose to the old root's larger `set_at`. Scientific analyses silently use the previous run's fall distance, trap frequencies or release settings. Preserve session-only choices intentionally, but bind confirmed records and their timestamp comparisons to root identity and replace them after a successful read for a different root.

2. **P2: correlations retain data outside RAM accounting and release.** `compute_correlations` keeps a global per-owner `_PlotState`, whose `PairCounts` owns converted events, KDTree blocks and per-shot pair counts. `AnalysisInstance.ram_buffers` sees input views and returned result data only; the private state is absent. `AnalysisInstance.release` hollows its views and results without clearing this state. The only state cleanup hook is `Correlations.plot_closed`. Thus a released plot can retain large arrays while the budget reports them freed. Account for private analysis buffers and provide a release hook that discards reusable state without marking an open owner permanently closed.

## Verification

- Existing focused suite: `venv/bin/pytest tests/test_folder_constants.py tests/test_correlations_plot.py tests/test_plot_ram_budget.py -n 4 --reruns 5 --reruns-delay 1 -q --tb=short`: **60 passed**, 9.06 s, no reruns.
- `repro_tests.py`: three probes intentionally assert the expected behavior. All three fail at the relevant assertions: old `fall_distance=0.91` remains after `root_changed` and Refresh; converted event buffers are absent from `ram_buffers`; a weak reference to a private event array remains alive after successful `plot.release()` and garbage collection.
- Replay by temporarily copying `repro_tests.py` to `tests/test_repo_review_probe.py`, then running `venv/bin/pytest tests/test_repo_review_probe.py -q --tb=short`. Keep it under `tests/` when executing, so the real test isolation fixtures load. It imports helper fixtures from existing test modules. Move it out again after execution; it is review evidence, not a proposed permanent test implementation.
- One initial release probe was obstructed by a closed owner ID reused across independent test windows. The final release probe clears that test-only global history before opening its window and then fails specifically because the array survives release. The production main window has one script selector, so no separate production finding is claimed for that test artifact.
- No production source changed. No commit, full suite, type checks, native UI or real-volume checks performed. Tests used isolated caches and synthetic data.
- User authorized `codegraph init -i`: completed, 800 files, 18,938 nodes and 51,289 edges; parse warnings in legacy MATLAB files. Initial index lookup failed before initialization; review used direct file reads.

## Fixes (Claude, 2026-10-20)

1. `FolderCache._root_constants_gone`, called from the `root_changed` handler: drops `folder_constant_records` and `_confirmed_constants` at and below the root, except folders with unsaved session choices (`_session_constants`) or a constants write still running. The next listing's answer then stands whatever its `set_at`. Test: `test_a_replaced_root_drops_the_old_roots_constants_but_not_unsaved_choices`.
2. New `DatasetAnalysis` hooks `plot_buffers(action, owner)` (merged into `AnalysisInstance.ram_buffers`) and `plot_released(action, owner, path)` (called from `AnalysisInstance.release`); both guarded and logged like `plot_closed`. Correlations implements them with `state_buffers` (`PairCounts.held_arrays`: events, counts, pair matrix rows, block events/owners, KDTree data/indices, plus the in-shot cache) and `release_state` (drops the state without marking the owner closed). Tests: `test_a_plots_state_counts_toward_ram_and_a_release_drops_it_but_not_for_good`, `test_a_scripts_private_arrays_count_and_go_when_the_plot_is_released`.

Validation: all three `repro_tests.py` probes pass (run from `tests/`, then removed); full suite `pytest -n 12 --reruns 5 --reruns-delay 1`: 2185 passed, 2 skipped, 2 xfailed, no reruns; `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests` clean.
