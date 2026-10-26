# Fixer notes (Rasp, Claude Opus 5.5)

Floor "Codebase Review 2", branch `agent/codebase-review-2`, base `3eb0fbf`.

## Job 1: the Windows rerun of the store test

`tests/test_result_cache_quit.py::test_an_old_stores_answer_never_says_saved_in_the_recreated_one`
reran on Windows CI (run 40270085653, job 121400850933):
`PermissionError: [WinError 32] … caches575\store-v3\records.sqlite` at `shutil.rmtree`, after the
test had waited for `not cache.service.cache_busy()`.

### Cause (found)

The helper that still had the store open came from **another IOService**: the app-wide one
(`io_service._service`). The test's `cache.service.cache_busy()` never counts that service.

- A plot's settings page has a Presets row (`PresetBar`), which reads presets through
  `get_folder_cache(get_io_service())` (`helab/views/plots/presets.py:63`, `:583`), whatever cache
  the test gave the plot's workspace. `arrangement.py:422` does the same.
- So opening the second plot starts `cache_admin presets` on the app-wide service, followed by
  `identity` and `inventory`, all against the *current* test's store: `store_options()` resolves
  `cache_dir()`, which `private_store` sets per test.
- That service lives for the worker's whole run, so its FolderCache timers (sweep deadline, budget,
  restore, markers, subtrees) can also start helpers in a later test, on that test's store.
- Measured with a tracing plugin (scratchpad, not committed). Each of `test_result_cache_plots.py`,
  `test_result_cache_quit.py` and `test_presets_plots.py` started cache helpers on the app-wide
  service (231 helper starts over 87 tests). The failing test itself started 8, between the
  first plot and the delete.
- On macOS and Linux an open file can be unlinked, so the race is invisible there. Windows refuses
  the delete.

Ruled out:
- The test process opening the store: the GUI never opens it, `seed` closes its `CacheStore`, and
  no store is opened between setup and the delete.
- The exit bookkeeping (`active` → `retired` → `_forget`, only on the reaper's exit flag): sound.

One risk noted, not the cause here: on Windows a venv's `python.exe` is a redirector that runs
the real interpreter as a child. CI and the lab PCs run from venvs. Killing the redirector
(`_reap`'s `process.kill()` for a cancelled helper) ends the child only through its job object, so
the child may still hold files for a moment after `wait()` returns. A cache move holds and kills
running cache helpers (`IOService.hold_cache`), then renames the folder. On a venv install that
rename could hit the same WinError 32 once in a while (frozen builds have no redirector). In this
test no helper was cancelled before the delete (traced). One was killed at EOF in `_reap`, which on
the redirector means it was already exiting. **Unsure**; for Sextant / Tony.

### Fix

- `tests/conftest.py`: `store_free(*services)` checks that neither the given IOServices nor the
  app-wide one has a cache helper running or unconfirmed.
- The three tests that delete a store through real helpers now wait for `store_free` before
  `shutil.rmtree`:
  - `test_result_cache_quit.py::test_an_old_stores_answer_never_says_saved_in_the_recreated_one`
    (it waited for `cache.service.cache_busy()` only);
  - `test_presets_store.py::test_a_store_recreated_at_the_same_folder_is_read_as_itself` and
    `test_store_identity.py::test_a_store_in_the_folder_whatever_its_age_ends_quit` (they waited
    only for `not cache._preset_jobs`, which `done` clears before the helper exits, and a probe or
    inventory isn't a preset job). These carried the same risk, though they haven't rerun yet.
- No retry of the delete: the open handle has a cause, and waiting removes it.
- Regression test `test_a_store_is_free_only_once_the_app_wide_services_helpers_have_exited`:
  - it keeps the app-wide service's cache helpers unforgotten;
  - it opens a plot;
  - it asserts that the test's own service is idle while `store_free` is false;
  - checked: it fails with the old rule (only the given services) and passes with the fix.

Other tests checked: the others that delete or replace `records.sqlite` (`test_cache_move.py`,
`test_cache_store.py`, `test_presets_store.py`'s and `test_result_store.py`'s direct `sqlite3`
use, `test_store_identity.py:359`) work on stores no IOService has open. They call helper
functions in-process, or run a helper to completion first.

Note for Part 2 (Sextant): `PresetBar` and `PlotReopen`/`FolderWait` use the app-wide FolderCache.
`AnalysisInstance` uses its budget's cache first (`instance.py:1008`). In the app both are the same
object. In tests they differ, so preset traffic escapes the test's service. Passing the workspace's
cache would be cleaner but touches presets tests broadly. Not changed here.

## Job 2: open known-issues items

Read `roadmaps/known-issues.md`.
- Already fixed, but still listed as open (proposed doc edits for the handoff):
  - "`roots_verify` is missing from `io_helper.CACHE_ONLY`": fixed in `778641a` ("Refuse
    roots_verify without the disk cache, as the app's list says").
  - "`cache_move.verify` doesn't check saved results' files": fixed in `9d90156` (it reads
    `results` and `pending_results`).
- The rest are in the Cache Only floor's files (the identity probe's lane, the hidden saved-result
  count of a forgotten root: `folder_cache.py`/`io_service.py`) or need Tony (the unused temp
  folder setting, SMB leftovers). None taken.

## Findings

Outcomes: fixed + commit / declined + why / needs Tony / held for Cache Only.

### Batch 1 (C-1 … C-6)

- **C-1 (low): fixed, `5d495e4`.** `CachedRuns` treated an `unverified` refusal as a failed read.
  Now:
  - the lookup is asked again once `volumesVerified` fires (once), and the run waits with its guard
    still taken before it computes, so the fence rule is unchanged;
  - a refused save is asked again with its guard and packed bytes (the request's own `blob` object,
    no copy);
  - one asked before a verification that ran meanwhile is asked again at once (a verification
    counter);
  - after `VERIFY_WAIT` (15 s) without verification, both go on as before. The timer is one per
    plot, started by the first refusal, so a later refusal may wait less.

  No new wording: the status stays "Looking in the disk cache…". The 15 s constant is my choice
  (bounded, so a verification that errors never leaves a plot waiting). Tony may want another.
  Tests: `tests/test_result_cache_unverified.py`, 4 of 5 fail on the old code; the fifth pins the
  fallback.
- **C-2 (low, wording): needs Tony.** "not saved in the disk cache (discarded)" also shows for an
  expired or store-replaced waiting result. Question: carry a reason with
  `resultPendingAnswered` and word the note "(expired)" / "(the disk cache was recreated)"?
  The signal is sent from `folder_cache.py` (Cache Only), so the fix spans both floors.
- **C-3 (quality): fixed, `5d495e4`.** `finished` calls `forget()` for a failed or cancelled run.
  Test: `test_a_failed_run_cancels_its_lookup_still_out`, a holds-state script whose run starts
  beside the lookup.
- **C-4 (low): needs Tony.** Waiting results expire after an hour (`PENDING_MAX_AGE`), though
  AGENTS.md and the roadmap say they stay for the next session. Question: should the docs say "for
  an hour", or should waiting results get a longer age? `cache_store.py` is Cache Only's.
- **C-5 (quality): held for Cache Only.** Drop `remove_results`'s unused `paths` / `_stored_keys`
  branch and its `by_path` epoch bookkeeping (`cache_store.py:1955–2006`), or keep it with a test.
  Proposed change: remove the parameters and the branch; run `tests/test_result_store.py` and
  `test_result_lifecycle.py`.
- **C-6 (doc): handoff.** Move the `cache_move.verify` item to Fixed (`9d90156`). Job 2 above found
  the same, plus the `roots_verify` item (`778641a`).
