# Codebase review 2 and fixes: handoff

Floor "Codebase Review 2", branch `agent/codebase-review-2`, from `3eb0fbf` (`dev/v0.0.6`).
- **Reviewer:** Sextant (Claude Fable 5.1), [findings.md](findings.md).
- **Fixer:** Rasp (Claude Opus 5.5), [notes.md](notes.md).
- **Brief:** [brief.md](brief.md).

## Counts

28 findings: **0 blocker, 0 high, 2 medium, 11 low, 14 quality, 1 doc.**

| Outcome | Findings |
|---|---|
| Fixed | C-1, C-3, C-13, C-17, C-18, C-19, C-20, C-21, C-22, C-25 |
| Fixed in part (rest held for Cache Only, needs Tony or declined) | C-7, C-8, C-9, C-23, C-24, C-26, C-27 |
| Kept, made explicit | C-11 |
| Needs Tony | C-2, C-4, C-10, C-12, C-14, C-15, parts of C-23 and C-27 |
| Held for Cache Only (its files) | C-5, and the parts of C-7, C-8, C-9, C-24, C-26, C-27 in its files |
| Handoff only (docs, proposals) | C-6, C-16, C-28 |

Plus the brief's first job: the Windows rerun of the store test (`5607182`).

Every fix has a test. Each new test fails before its fix and passes after, except C-1's fallback
test (it pins the old behaviour after the timeout) and C-25 (a test-hygiene change). Sextant read
every commit in full and reran the checks: [findings.md, Review of Rasp's fixes](findings.md#review-of-rasps-fixes).

Checks at `1a010ef` (Rasp at `e47242b`, Sextant at `1a010ef`): `pytest -n 4 --reruns 5
--reruns-delay 1` gave 4354 passed, 2 skipped, 2 xfailed, **no RERUN**. `mypy helab/ --strict`,
`mypy tests --strict` and `pyright helab tests` are clean. CI on the pushed branch: see the end.

## Job 1: the Windows rerun of the store test (`5607182`)

The test was `test_result_cache_quit.py::test_an_old_stores_answer_never_says_saved_in_the_recreated_one`
(WinError 32 deleting `records.sqlite`).

**Cause:** a plot's Presets row (`PresetBar`) reads presets through the **app-wide** IOService
(`get_folder_cache(get_io_service())`), not the test's own `cache`.
- That service lives for a worker's whole run, and its helpers use `store_options()`, i.e. the
  *current* test's private store.
- Opening the second plot therefore started presets, identity and inventory helpers on the store
  the test then deleted, and `cache.service.cache_busy()` never counted them. A tracing plugin
  measured 8 such helpers in that test.
- macOS and Linux unlink open files, so only Windows failed.

**Fix:**
- `tests/conftest.py` has `store_free(*services)`, which also counts the app-wide service.
- The three tests that delete a store through real helpers wait for it. Two of them waited only for
  `_preset_jobs`, which `done` clears before the helper exits.
- No retry of the delete.
- A regression test fails with the old rule.

The structural cause is C-28.

## Outcomes by finding

The detail is in [notes.md](notes.md#findings); one line each here.

- **C-17, C-18 (medium):** fixed, `f863c9f`. `capture` named docks for good, so presets put plots in
  each other's places. It now names them only during its `saveState` and names other docks apart.
- **C-1 (low):** fixed, `5d495e4`. A saved-result lookup or save refused for an unverified volume
  waits for `volumesVerified` and is asked again once. After `VERIFY_WAIT` (15 s, my choice) it goes
  on as before.
- **C-19 (low):** fixed, `82fc79c`. A waiting reopened plot looks for its data instead of taking
  Live's revision.
- **C-20 (low):** fixed, `1628c3e`. Closing "Plots not reopened" keeps the plots.
- **C-21 (low):** fixed, `6fef992`. `isHidden()` replaces `isVisible()` for the preset note.
- **C-22 (low):** fixed, `8651eb4`. Three things:
  - a reopened plot whose settings fail to open is kept, not saved empty;
  - `isdecimal()` replaces `isdigit()`;
  - the settings width is clamped.
- **C-25 (low):** fixed, `0e44f0d`. A fake home in the cache-location tests.
- **C-2 (low):** needs Tony; see the questions below.
- **C-4 (low):** needs Tony; see the questions below.
- **C-10, C-12, C-15 (low):** needs Tony; see the questions below.
- **C-3 (quality):** fixed, `5d495e4`. A failed run forgets its lookup.
- **C-13 (quality):** fixed, `197056f`. The event test reads `helab/views/plots`.
- **C-11 (quality):** kept, `197056f`. `root_rekeyed` and `subtree_saved` are receipts, listed as
  `RECEIPTS`; any other unhandled kind fails the test.
- **C-7, C-8, C-9 (quality):** fixed in part, `7471081`; the rest are held, listed below.
- **C-23 (quality):** fixed in part, `fe9a582`. A leaked `presetsChanged` connection,
  `PlotWorkspace.folder_cache()`, a stale name. Two wording items need Tony.
- **C-24 (quality):** fixed in part, `e47242b`. `CacheDialogs`, `SettingsDialog` and `cache_move`
  call through the module now.
  - **Declined** for `helab/views/plots/arrangement.py` and `instance.py`. Their by-value import is
    the presets tests' narrow seam; moving it turned the presets store off and failed two tests.
    Sextant agrees.
  - The Cache Only importers are held.
- **C-26 (quality):** fixed in part, `7abba35`. `check_target` returns `MoveCheckFields`, and the
  `main.py` ignore is gone. The rest is held.
- **C-27 (quality):** fixed in part, `33fbf95`. One overlay module, and two docstrings.
  `HelabMainWindow.named_temp_files` is held; `RATE_SECONDS` needs Tony.
- **C-14 (quality):** needs Tony; see the questions below.
- **C-5 (quality):** held for Cache Only.
- **C-16, C-28 (quality):** handoff, below.
- **C-6 (doc):** handoff, below.

## Needs Tony (the questions)

1. **C-4:** a result waiting for Make room expires an hour after it was held (`PENDING_MAX_AGE`,
   like a waiting dataset save), and the startup sweep runs before the inventory. AGENTS.md says
   waiting results "stay for the next session". Should the docs say "for an hour", or should waiting
   results get a longer age (a day?) in `sweep()` and `next_deadline()`?
2. **C-2:** "not saved in the disk cache (discarded)" also shows for a waiting result that expired
   or whose store was recreated. Should `resultPendingAnswered` carry a reason, worded "(expired)" /
   "(the disk cache was recreated)"? It spans `folder_cache.py` (Cache Only) and
   `cached_results.py`.
3. **C-10:** View › "Toggle Thread Status Auto Pop-up" reads and writes a setting nothing else
   reads, so it does nothing. Remove it and retire `THREAD_STATUS_SETTING`, or say what it should do.
4. **C-12:** `RACY_SECONDS` is defined twice: `fingerprints.py` (0 under tests' settle seam) and
   `live.py` (a fixed 2.0). Should there be one constant, and which? Proposal: Live imports
   fingerprints'. Also rename `FolderExplorer.SETTLE_SECONDS` (the selection settle) to
   `SELECTION_SETTLE_SECONDS`.
5. **C-14:** `time_format.duration` has no hour unit ("75 min 12 s"), and `byte_rate` is SI while
   `byte_size` is binary, under the same labels. Changing either changes text users read
   (stopping helpers, no-timeout retries, rates). Should `duration` gain an hour unit, and which
   byte unit should both use?
6. **C-15:** the store's `root://` keys are percent-quoted, while `dataset_view.root_key` isn't
   (`run 1` vs `run%201`). Nothing compares them today. Quoting the view's key changes the
   `root_key` saved in arrangement and reopen records: records with spaces would read as another
   root's. Should old records' keys be read both ways, or the gap left latent?
7. **C-23:** the presets inspector says nothing when `set_presets` refuses (quitting) or keeps a
   change in RAM only. Proposal: its note line says `Renamed “a” to “b”` + `saved_note(why)`, as
   `PresetBar` does. Separately, a script with no parameters has no `PresetBar`, so its reopen
   note (library or Live group not restored) never shows. Proposal: show it on the status line.
8. **C-27:** `events.RATE_SECONDS = 60.0` is commented "proposed, for Tony", while AGENTS.md states
   it as settled. Is 60 s decided? If so, drop the comment.
9. **C-1:** is `VERIFY_WAIT` = 15 s right (how long a saved-result lookup waits for volume
   verification before computing without saving)?

## Held for Cache Only (apply after it lands and this branch merges `dev/v0.0.6`)

Each is small, and none changes behaviour.
- **C-5:** remove `CacheStore.remove_results`' unused `paths=` / `_stored_keys` parameters, their
  branch and the `by_path` folder-epoch bookkeeping (`cache_store.py` ~:1955–2006), or keep them
  with a test if a per-folder Clear cached analysis is planned. Run `test_result_store.py` and
  `test_result_lifecycle.py`.
- **C-7:** delete `cache_paths.current_cache_paths` and
  `FolderTabWidget.rescan_current_folder_explorer`.
- **C-8:** delete `cache_store.DEFAULT_BUDGET` (the default is `settings_defaults`') and
  `RESULT_FORMAT` (`result_codec.FORMAT` is the one written), `IOService.LISTINGS`, and
  `HelabMainWindow.STATUS_LEFT_*`.
- **C-9:** drop `FolderCache.diskUsageChanged` and `FolderExplorer.itemExpandedSignal`, or connect
  `diskUsageChanged` where the status bar shows usage.
- **C-24:**
  - make `SnapshotFileSystemModel`, `CacheTab`, `DataRootsTab`, `explorer_live` and
    `FolderExplorer` call `folder_cache.store_options()`;
  - change the tests that patch those modules' own names (`test_helabMainWindow.py:285`,
    `test_ram_only_status.py:145`, `test_root_gui.py:268`, `test_result_cache_settings.py:155`,
    `test_root_clear.py:135`) to patch `folder_cache.store_options`;
  - before each change, check that the test doesn't rely on faking it for one consumer only (as
    the presets tests do for plots).
- **C-26:**
  - `IOService._put`/`messages` and FolderCache's `_on_result_event`/`_on_admin_event` should take
    `HelperEvent`;
  - `CacheStore.event()` should return `ResultCountField`/`UsageFields`, and `write_presets`
    should return `list[PresetRowFields]`, removing the casts in `browse.py`, `admin.py`,
    `results.py` and `stores.py`;
  - `store_options()` should be a TypedDict, `save_result(guard)` a `ResultGuard`, and
    `cache_admin(action)` a `Literal`;
  - `pending_saves`, `pending_results`, `mismatched` and `root_duplicates` should be typed by
    their event shapes.
- **C-27:** delete `HelabMainWindow.named_temp_files` (never appended to).
- **C-28:** hand `PresetBar` and `PlotReopen` the workspace's FolderCache (one injection point, as
  `CachedRuns` has), so a test's preset traffic stays on its own service. Then `store_free`'s
  app-wide check becomes a backstop. The presets tests (`test_presets_plots.py`'s `fresh_presets`
  uses the app-wide `preset_store()`) need a look first.

## Open risks

- **Windows venv redirector and cache moves (unsure; not seen):**
  - On Windows a venv's `python.exe` is a redirector that runs the real interpreter as a child.
    CI and the lab PCs run from venvs; frozen builds don't.
  - Killing the redirector (`_reap`'s `process.kill()` for a cancelled helper) ends the child only
    through its job object, so the child may still hold files a moment after `wait()` returns.
  - A cache move kills running cache helpers (`IOService.hold_cache`), waits for `cache_busy()`,
    then renames the folder, which could now and then hit WinError 32 on a venv install.
  - The move's verify/recovery would catch a failed rename, but the user would see a failed move.
  - Not the cause of job 1: no helper was cancelled before that delete (traced).
- **Cross-test leaks through the app-wide IOService (C-28):**
  - Its timers (sweep deadline, budget, restore, markers) and the plots' preset reads start
    helpers in later tests, on the store of the test running then.
  - `store_free` covers store deletes. The real-data guard can still blame a later test for an
    earlier test's helper: seen in a snapshot run whose basetemp was outside the checkout.
  - A per-test shutdown of the app-wide service in conftest would end it, but the presets tests
    rely on the service persisting (`fresh_presets`), so it needs care.
- **C-1's `VERIFY_WAIT`:** one timer per plot, started by the first refusal, so a later refusal
  may wait less than 15 s. A refused save keeps its packed bytes for up to 15 s outside the RAM
  budget's count. It isn't in `quit_saves`: quitting refuses it, and the plot says not saved.

## Part 2's structural proposal: splitting `helab/utils/folder_cache.py` (for Tony)

From [findings.md](findings.md#helabutilsfolder_cachepy-size-and-structure-a-proposal-for-tony-not-a-change).

The file has 3,749 lines. `FolderCache` takes up 3,486 of them, with 191 methods, 35 signals and 112
attributes. `_on_event` alone is 395 lines. It is six subsystems behind one QObject, each already
marked by a section comment and keeping to its own attributes. In order of payoff and least risk:

1. Extract the **store identity and presets** into `helab/utils/presets_state.py`: a Qt-free class
   over a small protocol (`cache_admin`, `submit`, `resultReady.emit`, two signals). FolderCache
   keeps thin delegating methods; the 1560-cell `test_store_identity.py` already drives it through
   them.
2. Extract **saved results and disk usage** (`find_result`, `save_result`, `_on_result_event`, result
   counts, `pending_results`, `_note_usage`, the 80 % pause) as `results_state.py`, sharing
   `store_answer` with (1).
3. Extract **data roots and constants** (`roots_state.py`: root and verification events, duplicates,
   the constants' root-move rules).
4. Leave the **job machinery** in `folder_cache.py` (~1,500 lines), and split `_on_event` by
   operation (`_on_load_event`, `_on_cached_event`, `_on_scan_event`), each under 100 lines.

Rules for keeping it a pure refactor:
- the helper contract and every public FolderCache name stay;
- each extracted class owns the signals it emits;
- it comes after the Cache Only floor, which owns the file today.

Other structural notes:
- **C-28:** inject the workspace's cache into `PresetBar` and `PlotReopen`; see above.
- **C-15:** one function for a folder's `root://` key.
- **C-14:** one duration formatter and one byte-unit convention.

## Proposed doc edits

### AGENTS.md (from findings.md, updated for this branch's fixes)

1. **Saved analysis results / Caching:** "results still waiting for an answer stay for the next
   session" and "At startup an inventory restores saves still waiting from an earlier session":
   both last `PENDING_MAX_AGE` = 1 h from when they were held, and the startup sweep expires them
   first. Change the code instead if Tony decides so (C-4).
2. **Architecture, Package layout:** `helab/workers/` doesn't exist; add `helab/analysis/` and
   `helab/io_ops/`.
3. **Responsive filesystem I/O:** add `results` to the `helab/io_ops/` operation families.
4. **The local lane** also runs `cache_move`, `result_find` and `result_save`
   (`IOService.LOCAL_OPERATIONS`).
5. **Caching, `FolderCache.cache_admin(action, …)`:** the list also has `prefs`, `clear_prefs`,
   `constants`, `presets`, `adopt_result`, `discard_result`, `clear_results`,
   `clear_root_results`, `identity` and `budget` (`admin.ADMIN_ACTIONS`). The folder-flags sentence
   should mention Settings → Cache's Clear folder preferences (`clear_prefs`).
6. **Caching, the sweep:** it also expires pending saves and results over an hour old, and deletes
   store files no row names once they are over an hour old (`_sweep_orphans`).
7. **Visualization:** `127.0.0.1:8050` is the preferred port; another free one is taken when it is
   in use (`dash_server.py`).
8. **Threading:** besides the readers, the GUI process also has the short daemon threads
   `HeLab-artifact-cleanup` and `HeLab-cancel` (`io_service.py`) and `HeLab-shutdown`
   (`HelabMainWindow.py`).
9. **Live:** "(not within `RACY_SECONDS` = 2 s …)" refers to Live's own `live.RACY_SECONDS`, until
   C-12 merges them.
10. **Script system:** the `helab/views/plots/` package also has `workspace`, `arrangement`,
    `presets` and `cached_results`.
11. **Transfer fractions:** now true after `33fbf95`. Both groups use `helab/analysis/overlay.py`,
    which also has `newest_values` and `update_newest`. No edit needed.
12. **The patched-names rule:** add that `folder_cache.store_options` is called as a module name,
    except in `helab/views/plots/arrangement.py` and `instance.py`, whose own copies the presets
    tests patch (C-24). Also add `cache_location.cache_location_problem` (called so by `cache_move`
    now, which the main-window GUI-thread guard relies on).
13. **Testing:** `tests/conftest.py`'s `store_free(*services)`: before a test deletes a store
    through real helpers, wait until neither its services nor the app-wide one has a cache helper
    running or unconfirmed. Windows refuses to delete an open file, and plots' Presets rows use
    the app-wide service.
14. **Saved analysis results:** a lookup or save refused because its folder's volume isn't verified
    this session waits for `volumesVerified` and is asked again once. After `VERIFY_WAIT` (15 s) it
    goes on as for any error (`CachedRuns`).
15. **Testing:** `tests/test_helper_events.py` reads every module under `helab/views` (the `plots`
    package too) and fails on a helper kind the app never matches, except `RECEIPTS`
    (`root_rekeyed`, `subtree_saved`).

### roadmaps/known-issues.md

- **Move to Fixed:**
  - "`cache_move.verify` doesn't check saved results' files": `9d90156` (C-6).
  - "`roots_verify` is missing from `io_helper.CACHE_ONLY`": `778641a`.
- **Add to Tests and CI, as Fixed:** the Windows rerun of
  `test_result_cache_quit.py::test_an_old_stores_answer_never_says_saved_in_the_recreated_one`
  (run 40270085653): the app-wide service's preset helpers held the store; fixed in `5607182`.
- **Add to App** (or roadmaps, per Tony): the Windows venv-redirector risk for cache moves (open
  risks above), marked unconfirmed.

### Others

- `roadmaps/cache-storage-and-settings.md:665`: "the Dash server uses it" (`SynchronisedDict`) is
  stale; nothing uses it, and Tony kept the module (R-21).
- `roadmaps/live-monitoring.md`: note C-16. A local folder without a `.helab-root` has the device
  node as its Live identity (`io_ops/identity.py`), not the volume ID, so a disk swapped at the same
  device node keeps the identity; only the held shots' sampled stats can catch it.
- `roadmaps/result-caching.md:148`: as AGENTS.md edit 1 (C-4).

## CI

(Filled in after the push.)
