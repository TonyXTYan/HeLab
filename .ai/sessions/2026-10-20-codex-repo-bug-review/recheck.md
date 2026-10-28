# Independent recheck of Claude's fixes

Reviewed clean commit `4b779f652fb62e89a76dea8fafaa563fd5df9cc4` against its parent, including the new regression tests and callers of the changed code.

The three original probes pass. Correlation state arrays now count toward the plot's budget, release frees the private event arrays, and a released owner can retain newly computed state again. The explicit `root_changed` scenario clears the old constants.

## Remaining findings

1. **P1: identity changes arriving through other root events retain old constants.** Cleanup is called only by the `root_changed` branch (`folder_cache.py:2216`). Both `root_found` and ordinary `data_root` metadata update the same `data_roots` mapping through `_root_seen`, without clearing constants from the previous UUID. A different volume/share at the same source path can report `root_found`: `io_helper._discover_root` checks the persisted row for the *new location* and sends `root_found` when no row existed there (`io_helper.py:616`). A listing/load/cached result can also report `data_root`. Both probes change the known UUID successfully but retain `fall_distance=0.91` from the previous root. Compare UUIDs and invalidate the previous identity's confirmed constants on every route that changes the known root, rather than only one event kind.

2. **P2: cleanup removes constants from unaffected nested roots.** `_root_constants_gone` selects every source path below the outer root (`folder_cache.py:1068-1074`), without considering the nearest data root. Removing only the outer marker leaves a nested root's UUID unchanged, but removes its confirmed values too. An analysis of the still-open nested folder can therefore fall back to lab/default values until those constants are fetched again. Restrict cleanup to records whose owning logical root changed.

## Verification

`venv/bin/pytest tests/test_repo_review_probe.py tests/test_folder_constants.py tests/test_correlations_plot.py tests/test_plot_ram_budget.py -q --tb=short`

**66 passed, 3 failed**, 25.23 seconds, no reruns. The existing focused tests and all three original probes passed. The failures are exactly the two alternate-event cases and the unchanged-nested-root case above. All use synthetic paths and frozen I/O dispatch, with the repository's isolated test caches and source guard.

`recheck_repro_tests.py` preserves the probes. As with the original reproduction file, temporarily copy it into `tests/test_repo_review_probe.py` to execute with `tests/conftest.py` and its helper modules, then move it out. No production source or existing tests changed. Full-suite/type-check results in Claude's earlier notes were not independently rerun here. No native UI or real-volume testing performed. `git diff --check` passed.

## Fixes (Claude, 2026-10-20)

1. The cleanup now runs where the known identity changes, whatever the event: `FolderCache._root_seen` (a different UUID at a known root folder: `root_changed`, `root_found`, a result's `data_root`) and `_root_gone`, both before `data_roots` changes. `root_changed` for a folder this session hadn't known as a root still cleans up directly.
2. `_root_constants_gone` skips folders whose nearest known root is a nested one strictly below the changed root.

Tests: `test_another_root_reported_at_a_folder_drops_the_old_roots_constants[root_found|data_root]`, `test_removing_an_outer_root_keeps_a_nested_roots_constants`. All five `recheck_repro_tests.py` probes pass (run from `tests/`, then removed). Full suite `-n 12 --reruns 5 --reruns-delay 1`: 2188 passed, 2 skipped, 2 xfailed. Reruns: 1 in the first run (not identified), 2 in a second run (`test_folder_cache.py::test_disk_cache_reused_after_process_restart_and_rejects_changed_files`, `test_window_resize.py::test_label_keeps_painting_after_resize[repeated]`). Both pass alone and are timing tests unrelated to this change. mypy --strict (helab, tests) and pyright clean.
