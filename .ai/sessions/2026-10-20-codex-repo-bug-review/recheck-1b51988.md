# Independent recheck of 1b51988

Reviewed clean HEAD `1b51988e5b3f46c23c7783e0f7d826a658508fd3` against `4b779f6`. No new findings in the reviewed changes.

- Root identity replacement is now handled in `_root_seen` before replacing the known mapping, covering `root_found`, explicit `root_changed`, and a result's `data_root`. Removal calls cleanup in `_root_gone` before dropping the mapping. The unknown-root `root_changed` fallback remains covered by the event handler.
- Cleanup checks each folder's nearest known root and leaves records inside unchanged nested roots intact. The existing protections for unsaved choices remain.
- All six collected cases in `recheck_repro_tests.py` pass, including the original correlation RAM accounting/release probes. The previous recheck text incorrectly called these five probes: there are five test functions, six collected cases due to parametrization.

Independent validation:

`venv/bin/pytest tests/test_repo_review_probe.py tests/test_folder_constants.py tests/test_correlations_plot.py tests/test_plot_ram_budget.py tests/test_root_discovery.py tests/test_root_remove.py tests/test_root_duplicates.py -n 4 --reruns 5 --reruns-delay 1 -q --tb=short`

**125 passed in 20.28 seconds, no reruns.** The reproduction file was temporarily copied under `tests/` to load the real isolation fixtures and then removed. Synthetic data and isolated caches only. `git diff --check` passed. No production source or existing tests changed; no commit made.

This verifies the reported defects and nearby root lifecycle behavior. The full suite, type checks, native UI and real-volume behavior were not independently rerun. Claude's recorded full-suite result had reruns (see `recheck.md`); this targeted run did not.
