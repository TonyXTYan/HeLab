# Codebase review: Mend's notes

Worker: Mend (Claude Opus 5.5). Branch `agent/codebase-review` from `fc0f50d`.

## Baseline (2026-10-22, before any change)

From the floor root with `floor-env.sh`:

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: 2378 passed, 2 skipped,
  2 xfailed in 128 s; **no RERUN**. Two warnings, both pyqtgraph's NumPy 2.5 deprecation
  (`arr.shape = (3, 3)` in `pyqtgraph/functions.py`, from `test_t_spectrum.py`).
- `mypy helab/ --strict`: no issues (150 files). `mypy tests --strict`: no issues (104 files).
- `pyright helab tests`: 0 errors, 0 warnings.

## Findings

Each of Lens's findings (`findings.md`) as fixed (commit), declined (why) or needs Tony. Every
correctness fix has a test that fails without it and passes with it (checked by reverting the
`helab/` change and rerunning the test).

### Area 1 (I/O helpers, IOService, store, FolderCache, roots)

| ID | Outcome | Commit | Notes |
|---|---|---|---|
| R-1 | **Needs Tony** (held by CoCo, 2026-10-22) | — | Fix proposed: save the folder's pre-listing `st_mtime_ns` as an optional `info["folder_mtime_ns"]` and compare mtimes for equality in both quick checks (`_unchanged_since_cache`, `_unchanged_since_memory`), falling back to today's rule for caches without it. A new optional key in cached datasets' `info` (store format), hence the hold. |
| R-2 | Fixed | `265f35e` | Each array written to the helper's folder resets `last_activity` (no event, so no wording change). Test: `tests/test_io_service_run.py`. Handoff note: every Live autosave rewrites the whole held dataset to temp and the helper reads it back (by design). |
| R-3 | Fixed | `6299fdd` | After `poll()` says the helper exited, the reader reads the file to its end. Test: `tests/test_io_service_run.py`. |
| R-4 | Fixed | `af632a3` | `root_at`/`other_root_locations` raise `StoreError`; `list_folder` treats an unreadable table as "may have a row" (`_may_have_root`) and `_discover_root` also catches a root write's raw `sqlite3.Error`. Tests: `tests/test_root_marker_errors.py` (3). |
| R-5 | Fixed | `2447a66` | The store's own `StoreError`s pass through `_cache_store` unchanged; an `OSError` making its folder is `OPEN_FAILED`; "Mount information is unavailable" stays for the mount and resolver steps. The existing expectation at `test_cache_store_open.py:124` (a genuine mount error) is still right and unchanged. New test (needs `no_auto_data_root`: conftest's seeding opens the store first). |
| R-6 | Fixed | `d586f9d` | Decision: confirmed if the location is already confirmed with this UUID, else pending iff another confirmed location has it. Test: `tests/test_root_duplicates.py`. Handoff: a pending location whose other locations were all forgotten is now confirmed by its next listing (no question asked), with the UUID's cached data. |
| R-7 | Fixed (confirmed first) | `2559c77` | The test showed the tab's load cancelled ("Cancelled — Retry") when another tab's status check found a new signature. A signature change now only drops the folder's datasets (`_folder_changed`); `_invalidate_data` stays for Clear. Test: `tests/test_folder_cache.py`. |
| R-8 | Fixed | `34bcb78` | stderr goes to `stderr.txt` in the helper's folder; on an incomplete exit its last 2 KB are logged at WARNING. The error event's message is unchanged (no wording change). Test: `tests/test_io_service_run.py`. |
| R-9 | Fixed | `6ddec21` | `_entry_stat(..., follow_symlinks=False)`, traced as `lstat` with `syscall`, so `tests/test_io_trace.py` (other floor's) is unchanged. Test: `tests/test_two_step_browse.py`. |
| R-10 | Partly done | `f684720` | Lifted `_on_root_event`, `_on_verification_event`, `_on_finishing_event` out of `_on_event` unchanged. Declined: the scan and load blocks (they reassign `kind`/`event` for the shared tail, so a split needs a return protocol harder to follow than the blocks) and `_load`'s cache-read block (nine locals and an early stop through `stop_if_missing`). |

Batch checks after R-2..R-10 (`f684720`): full suite 2390 passed, 2 skipped, 2 xfailed, **no RERUN**
(twice, the second run covering R-10); strict mypy (helab, tests) and pyright clean. Lens reviewed
`265f35e..f684720`: no changes asked.
