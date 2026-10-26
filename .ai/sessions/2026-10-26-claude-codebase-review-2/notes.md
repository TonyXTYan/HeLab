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

### Batch 2 (C-7 … C-28)

In severity order.

- **C-17 (medium): fixed, `f863c9f`.** `capture` no longer renames docks for good.
  `_named_state` names the recorded docks `DOCK_NAME` by place and every other dock
  `OTHER_DOCK_NAME` just for the `saveState`, then gives each its own name back. So
  `open_arrangement`'s names survive the `record()` calls its `place_dock` triggers.
  Test: `test_plots_opened_while_the_open_plots_are_recorded_keep_their_places`.
- **C-18 (medium): fixed, `f863c9f`** (same change: no recorded name twice in a state).
  - Test: `test_a_folders_preset_keeps_its_plots_places_beside_other_folders_plots`.
  - `test_a_replaced_plots_dock_isnt_taken_for_a_new_one` set its scenario up through `capture`'s
    lasting rename. It now gets a replaced dock with a recorded name from an earlier apply, and
    still fails without `open_arrangement`'s clean-up of such names (checked).
- **C-19 (low): fixed, `82fc79c`.** `_revised` / `_live_ended` hand a still-waiting reopened plot to
  `FolderWait.look()`; only `run_reopened` runs it.
  Test: `test_a_waiting_reopened_plot_never_runs_on_a_live_revision_by_itself`.
- **C-20 (low): fixed, `1628c3e`.** Keep for later is also the box's escape button.
  Test: `test_the_not_reopened_question_closes_as_keep` (Esc, then quit).
- **C-21 (low): fixed, `6fef992`.** `isHidden()` instead of `isVisible()`.
  Test: `test_a_store_problem_keeps_a_background_plots_note`. It confirmed Sextant's reading,
  which wasn't run before.
- **C-22 (low): fixed, `8651eb4`.**
  - `start` keeps `open_error`, and `reopen_plot` closes such a plot and returns why, so it is kept
    and asked about.
  - `isdecimal()` replaces `isdigit()`.
  - `settings_width` is clamped to the section's minimum and the primary screen's available width.
  - Note: `parameters()` raising is caught already in `__init__` (via `constant_keys`). The
    reachable case is a hook only `_open_settings` calls (`minimum_size`, `backends`).
  - Tests: `test_a_plot_whose_settings_fail_to_open_isnt_reopened_but_kept`,
    `test_a_reopened_plots_odd_number_and_width_are_taken_safely`.
- **C-23 (quality): fixed in part, `fe9a582`.**
  - `show_summary` disconnects when its label goes; test:
    `test_the_cache_tabs_presets_line_lets_go_of_the_store_with_its_label`.
  - One `PlotWorkspace.folder_cache()` replaces the two copies of the workspace-cache fallback.
    `preset_store()` stays the app's, by design.
  - The stale `reopen.py` name is fixed.
  - **Needs Tony (wording / a place on screen):**
    - the inspector's rename/duplicate/delete say nothing when `set_presets` refuses (QUITTING) or
      keeps a change in RAM only. Proposal: its note line says `Renamed “a” to “b”` +
      `saved_note(why)`, as `PresetBar` does;
    - a script with no parameters has no `PresetBar`, so its reopen note never shows. Proposal:
      the status line.
- **C-7 (quality): fixed in part, `7471081`.** Removed: `DataFolder`, `icons.str_to_QIcon` /
  `circular_progress_QIcon_cached` (and the cutoffs only it read), `CentralHint.set_extra` /
  `add_widget` / `extra`, `masks.apply_mask` (docstring fixed). **Held for Cache Only:**
  `cache_paths.current_cache_paths`; `FolderTabWidget.rescan_current_folder_explorer` (held
  because Cache Only's Work Online relists every tab, so it may touch that file).
- **C-8 (quality): fixed in part, `7471081`.** Removed: `profiles.BOSES`,
  `release_time.FOLDER_KEYS`, `FileKind.ram_per_byte`. **Held:** `cache_store.DEFAULT_BUDGET`,
  `RESULT_FORMAT`, `IOService.LISTINGS`, `HelabMainWindow.STATUS_LEFT_*`.
- **C-9 (quality): fixed in part, `7471081`.** Removed: `AnalysisRunner.started`,
  `OldLogs.trimmed`. **Held:** `FolderCache.diskUsageChanged`,
  `FolderExplorer.itemExpandedSignal`.
- **C-10 (low): needs Tony.** View › "Toggle Thread Status Auto Pop-up" does nothing. Should it be
  removed and its key retired? (`HelabMainWindow.py`, Cache Only.)
- **C-11 (quality): kept as receipts, `197056f`.** `root_rekeyed` and `subtree_saved` are the only
  kinds the app never matches. Both are receipts: a re-key reaches the app as `removed` plus
  `root_found` / `root_changed`, and skipped subtree paths come with a `cache_warning`. Listed as
  `RECEIPTS` in `tests/test_helper_events.py`, which now fails on any other unmatched kind.
- **C-12 (low): needs Tony.** The two `RACY_SECONDS` differ under the test seam; which one should
  hold? Proposal: Live imports `fingerprints.RACY_SECONDS`, and rename `FolderExplorer.SETTLE_SECONDS`
  (Cache Only) to `SELECTION_SETTLE_SECONDS`.
- **C-13 (quality): fixed, `197056f`.** `rglob` over `helab/views`, an assertion that
  `cached_results.py`'s kinds are found, and the unhandled-kinds test.
- **C-14 (quality): needs Tony (what users read).**
  - `duration` has no hour unit; adding one changes the text of stopping helpers and no-timeout
    retries.
  - `byte_rate` is SI and `byte_size` binary under the same labels; pick one.
  - `time_format.py` is mine, but its callers are Cache Only's.
- **C-15 (low, latent): needs Tony.** Quoting `dataset_view.root_key` changes the `root_key` saved
  in arrangement and reopen records. Existing records with spaces would then read as another
  root's (FolderWait's other-root rule). It's a record-format change. Alternative: a shared helper,
  with old records' keys read both ways.
- **C-16 (quality): handoff** (a note for `roadmaps/live-monitoring.md`).
- **C-24 (quality): fixed in part, `e47242b`.**
  - `CacheDialogs`, `SettingsDialog` call `folder_cache.store_options()`, and `cache_move` calls
    `cache_location.cache_location_problem()`.
  - **Declined** for `helab/views/plots/arrangement.py` and `instance.py`. There the by-value
    import is a narrow seam: presets tests fake the disk cache for `FolderWait` and reloads only,
    while the app-wide presets store keeps the real one. Moving them broke two presets tests,
    since patching `folder_cache.store_options` turned the presets store off.
  - **Held:** the Cache Only importers (`SnapshotFileSystemModel`, `CacheTab`, `DataRootsTab`,
    `explorer_live`, `FolderExplorer`).
  - AGENTS.md's patched-names list could name `folder_cache.store_options`, with those two
    exceptions.
- **C-25 (low): fixed, `0e44f0d`.** A fake home under `tmp_path` in both cache-location tests.
- **C-26 (quality): fixed in part, `7abba35`.** `cache_move.check_target` returns `MoveCheckFields`
  (no cast in `admin.py`); `main.py`'s `union-attr` ignore became an assert. **Held:** items 1, 2,
  4, 5 and `write_presets` (Cache Only's files).
- **C-27 (quality): fixed in part, `33fbf95`.** One overlay module (`helab/analysis/overlay.py`,
  with `newest_values` and `update_newest`); docstrings in `results.py` and `bootstrap.py`
  (`masks.py` went with C-7). **Held:** `HelabMainWindow.named_temp_files`. **Needs Tony:**
  `events.RATE_SECONDS`'s "proposed, for Tony". AGENTS.md states 60 s, but no decision is recorded.
- **C-28 (quality): handoff** (job 1's cause: `PresetBar` / `PlotReopen` on the app-wide cache).

Snapshot run note (not a code fault): two full runs of a snapshot worktree at `f863c9f` each
reran `test_helper_dispatch.py::…[subtree_save-6]`. Rerun reason: "Tests never touch real data, but
this test's I/O asked for: [.ai/temp/pytest-wt/popen-gw3/test_window_icon_is_found_from0]".
- I had put that basetemp outside the snapshot's checkout and outside the system temp, so the
  real-data guard counts it as real data.
- A helper the earlier main-window test's app-wide service started then ran on into the dispatch
  test (C-28's cross-test leak).
- The floor's own runs use a basetemp inside the checkout.

Checks for batch 2, at `e47242b` (before C-26): full suite 4354 passed, 2 skipped, 2 xfailed, **no
RERUN**; strict mypy on helab and tests and pyright clean. C-26 after: affected tests 170 passed,
types clean.

## Follow-up: Tony's answers (2026-10-26, via CoCo)

### Batch 3, before the merge (accepted by Sextant)

- **Item 8, `a40ef18`:** the per-minute cap is dropped.
  - The hub keeps "once per key". `RATE_SECONDS`, `rate_key`, the clock and the held-back count are
    gone.
  - Shot trends' tooltip no longer says "at most one a minute".
  - `explorer_live` never passed `rate_key`.
- **Item 9, `33849f4`:** two waits, `VERIFY_WAIT` (15 s, compute) and `SAVE_VERIFY_WAIT` (120 s,
  save).
  - The status bar notice and the plot's status line show `VERIFY_NOTE`, cleared like
    `PENDING_NOTE`.
  - The amber line shows `UNCHECKED_NOTE` (a new `AnalysisInstance._save_note`), with one log line.
  - A late guard is fenced by a Clear after the run started (`_cache_removed`; mutation-checked).
- **C-12, `d1aa85b`:** Live reads `fingerprints.RACY_SECONDS`.
  `test_a_recently_modified_folder_is_listed_again` sets the margin and checks a margin of 0
  compares.
- **C-15, `898966f`:** `dataset_view.root_key` quotes each part, as `cache_paths`. Test against
  `DataRoots.key`.
- **C-23, `3e04f03`:** the inspector's `_say` names refused or RAM-only changes. `note_saved` puts a
  parameterless script's note on the status line, kept in front of the waiting text and after runs.
- **C-14** was set aside as a patch: its tests pinned binary sizes built from `N << 30`, and the
  budget unit needed Tony's word.

### Merge

`c1da54d` merged `dev/v0.0.6` at `117b578` cleanly: 4447 passed, no RERUN.

### Batch 4, after the merge (accepted by Sextant)

- **C-2, `cb6fa23`:** `resultPendingAnswered(str, bool, str, str)` with `PENDING_*` reasons, and the
  plot's `NOT_SAVED_NOTES`. Lifecycle tests now expect "its cached analysis was cleared" for a clear
  or purge.
- **Sextant's remarks, `8026637`:**
  - the fence covers `not entry.wait` (holds-state scripts too);
  - a run already going says "this result isn't saved" instead of "computing";
  - remark 3 is a handoff doc edit.
- **C-10, `dce92c7`.**
- **The rename, `d95b18b`.**
- **Held cleanups, `fce2de0`.** C-5 keeps `paths=` because `test_result_cache_store.py:98` uses it.
- **C-24 rest, `0d7a83c`.**
- **C-26 part, `1a15f61`.**
- **C-28: declined for `PresetBar`** (reasons in the handoff). `PlotReopen` already injected.

### Batch 5

- **C-14, `bbed82c`:** SI `byte_size`, `app_log.MB`, the memory window; SI budgets
  (`DISK_BUDGET_SETTING` default 8e9, `MIN_DISK_BUDGET` and `MIN_RAM_BUDGET` 10^9,
  `CacheTab.GB = 10**9`, SettingsDialog's Reset); `duration` = `span` on whole seconds. The tests
  build sizes in SI.
- **C-29, C-30, `28c0dff`:**
  - `PresetFolder._busy()` counts an asked load until the data shows, the load fails, or the folder
    is held back as large. The instrumented probe showed `loading` cleared before `opened` was set.
  - Offline, a never-listed folder is named.
  - Tests in `tests/test_preset_folder_live.py`, built from Sextant's probes.

Checks at `28c0dff`: 4464 passed, 2 skipped, no RERUN; mypy --strict on helab and tests, and
pyright, clean.
