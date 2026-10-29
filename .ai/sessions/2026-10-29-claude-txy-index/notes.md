# Notes: TXY Index floor (Ledger)

## Checks (2026-10-29, macOS, on the merged state: `origin/dev/v0.0.7` 9f0b21f merged as a016792)

First full run (`pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`, before 35b50d0):
`1 failed, 8194 passed, 669 skipped, 2 warnings, 5 rerun`. The failure and all five reruns were
`tests/test_cache_switch.py::test_folder_cache_submits_the_cleanup_once`, deterministic: it pinned
the inventory payload's `params == {}`, and `FolderCache.cache_admin` now adds `temps` (Q27.5).
Fixed in 35b50d0 (the expectation), not a flake: nothing for known-issues.

Final runs (after 35b50d0):

- Inside the floor basetemp: `8195 passed, 669 skipped, 2 warnings in 130.56s`, no RERUN.
- Outside it (no `--basetemp`): `8195 passed, 669 skipped, 2 warnings in 131.23s`, no RERUN.
- The 2 warnings are pyqtgraph's NumPy 2.5 `arr.shape` deprecation in `tests/test_t_spectrum.py`
  (not this floor's).
- `mypy helab/ --strict`: Success, 191 files. `mypy tests --strict`: Success, 159 files.
  `pyright helab tests`: 0 errors. `mypy helab/ --strict --platform win32`: Success.
  `pyright --pythonplatform Windows helab tests`: 0 errors.

## New tests

- `tests/test_convert_helab.py`: `test_provenance_rows_round_trip_and_say_what_is_stale`,
  `test_write_atomic_calls_before_rename_with_the_files_stat`,
  `test_a_write_killed_after_its_row_is_converted_again[True|False]`,
  `test_a_failed_write_removes_its_row_only_if_still_its_own`,
  `test_the_own_folder_pattern_is_the_txys_temporary_names_alone`,
  `test_a_missing_or_damaged_index_only_means_shots_convert_again[missing|not a database|malformed|newer]`,
  `test_an_index_that_cant_be_written_fails_the_conversion_to_be_tried_again`,
  `test_two_writers_side_by_side_lose_nothing` (two processes),
  `test_a_dont_cache_folder_converts_to_the_temp_folder`,
  `test_a_dont_cache_flag_that_cant_be_read_converts_to_the_temp_folder`,
  `test_the_index_moves_with_the_cache_folder_and_its_shots_stay_current[rename|copy]`;
  rewritten for the index: the temp-folder, better-profile, beside, lost-race and leftovers tests.
- `tests/test_converter_tab.py`: measure and clear through the index (old builds' files, an unindexed
  TXY, a set-aside index, links), `test_a_clear_keeps_the_row_of_a_txy_written_again_meanwhile`, the
  Cache tab over both bases (label, per-base tooltip, Clear text, `temps` in both requests).
- `tests/test_txy_sources.py`: `test_a_dont_cache_folders_txy_are_found_in_the_temp_folder`; the
  read-count test counts index rows.
- `tests/test_helper_events.py`: `test_the_converted_txy_summary_is_the_declared_shape`.
- `tests/test_cache_switch.py`: the inventory payload carries `temps`.

## Review round 1 checks (after Tern's review; macOS, same merged base)

- Full suite, `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`:
  `8197 passed, 669 skipped, 2 warnings in 126.87s`, no RERUN (2 more tests than before: the
  set-aside-blocked and the newer-index Clear tests).
- `mypy helab/ --strict`: Success (191). `mypy tests --strict`: Success (159). `pyright helab tests`:
  0 errors. `mypy helab/ --strict --platform win32`: Success. `pyright --pythonplatform Windows helab
  tests`: 0 errors.
- CI run 40863356565 (head 1e7329c) had failed on Windows only, on `[newer]` (High-1), plus one
  unrelated RERUN in `test_io_service_run.py` (quoted in the handoff for known-issues).

## Review round 2 checks (Nit-4)

- Full suite, `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`:
  `8197 passed, 669 skipped, 2 warnings in 143.18s`, no RERUN.
- The five type checks: clean (mypy strict helab 191 / tests 159, win32; pyright, Windows).
- CI run 40866574094 (9691873): attempt 1 crashed one macOS worker (known-issue proposal in the
  handoff); attempt 2 green on every job, no RERUN.
- CI run 40874212130 (c546394): green, two RERUNs (handoff, last section); the one in this
  branch's two-writer test is fixed in the next commit (busy retried, `provenance._patient`).
- After that fix: full suite `8198 passed, 669 skipped, 2 warnings in 139.30s`, no RERUN; the five
  type checks clean.

## Review round 3 checks (WAL)

- CI 40879735789 (0e79897, diagnostics): busy starvation (SQLITE_BUSY after 10.65-13.41 s) in the
  two-writer test on Windows; quoted in the handoff's last section.
- After WAL: full suite `8199 passed, 669 skipped, 2 warnings in 142.08s`, no RERUN; the five type
  checks clean; local stress six writers x 300 rows, three trials, no error.

## Review round 4 checks

- Full suite, `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`:
  `8205 passed, 669 skipped, 2 warnings in 143.12s`, no RERUN.
- The five type checks clean (mypy strict helab 191 / tests 159, win32; pyright, Windows).
- The touch-timeout test fails without the 200 ms limit (`assert 10.971249207970686 < 5.0`) and passes
  with it.
