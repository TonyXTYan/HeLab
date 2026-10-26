# Codebase review 2 and fixes: handoff

Floor "Codebase Review 2", branch `agent/codebase-review-2`, from `3eb0fbf` (`dev/v0.0.6`). It merged
`dev/v0.0.6` at `c1da54d` (after Cache Only landed) and then did the follow-up from Tony's answers.
- **Reviewer:** Sextant (Claude Fable 5.1), [findings.md](findings.md).
- **Fixer:** Rasp (Claude Opus 5.5), [notes.md](notes.md).
- **Brief:** [brief.md](brief.md).

## Counts and outcomes

31 findings: **0 blocker, 0 high, 2 medium, 13 low, 15 quality, 1 doc.**

| Outcome | Findings |
|---|---|
| Fixed | C-1, C-2, C-3, C-5, C-7, C-8, C-9, C-10, C-12, C-13, C-14, C-15, C-17, C-18, C-19, C-20, C-21, C-22, C-23, C-24, C-25, C-27, C-29, C-30, C-31 |
| Fixed in part | C-26 (the app side's event typing is left for the `folder_cache` split) |
| Kept, made explicit | C-11 (receipts listed in the event test) |
| Declined, with reasons | C-28 for `PresetBar`; C-24 for `helab/views/plots/arrangement.py` and `instance.py` |
| Docs only | C-4 (Tony), C-6, C-16 |

Also: the brief's first job (the Windows store-test rerun, `5607182`), and Tony's items 8 (no
per-minute notification cap) and 9 (the two verification waits).

Every behaviour change has a test, and each new test fails before its fix. The exceptions are
pinning or hygiene tests, named in [notes.md](notes.md). Sextant read and accepted every commit:
batches 1 to 5 in [findings.md](findings.md#review-of-rasps-fixes); C-31's small commit is with
Sextant at the time of writing.

**Checks at the final head** (`28c0dff`, before docs):
- `pytest -n 4 --reruns 5 --reruns-delay 1`: 4464 passed, 2 skipped, **no RERUN**.
- `mypy helab/ --strict`, `mypy tests --strict` and `pyright helab tests`: clean.
- CI: the first push (`253888d`) is at the end; the follow-up isn't pushed (see there).

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
- `tests/conftest.py`'s `store_free(*services)` also counts the app-wide service.
- The three tests that delete a store through real helpers wait for it.
- No retry of the delete.
- A regression test fails with the old rule.

The structural cause is C-28, declined below.

## Outcomes by finding (one line each; detail in notes.md)

**Review fixes (before Tony's answers):**
- **C-17, C-18 (medium):** `f863c9f`. `capture` names docks only during its `saveState`.
- **C-1 (low):** `5d495e4`. An unverified-volume lookup or save waits for verification. Tony then
  split the wait in two (item 9, below).
- **C-19:** `82fc79c`.
- **C-20:** `1628c3e`.
- **C-21:** `6fef992`.
- **C-22:** `8651eb4`.
- **C-25:** `0e44f0d`.
- **C-3:** `5d495e4`.
- **C-13 and C-11:** `197056f`.
- **Dead code:** `7471081`.
- **C-23:** `fe9a582`.
- **C-24, this floor's part:** `e47242b`.
- **C-26, first part:** `7abba35`.
- **C-27:** `33fbf95`.

**From Tony's answers (2026-10-26):**
- **Item 8:** `a40ef18`. No per-minute cap: a desktop notification shows once per key (once per
  shot), with no time limit. `RATE_SECONDS`, `rate_key` and the held-back count are gone.
- **Item 9:** `33849f4`, with Sextant's two follow-up remarks in `8026637`.
  - At 15 s the plot computes. The status bar and its status line say "Disk cache: still checking
    this drive; this result isn't saved yet."
  - The save waits up to 120 s. Verification asks for the guard alone; the result is saved and the
    note clears.
  - At 120 s, or refused again: the amber line "not saved: the drive couldn't be checked" and one
    log line.
  - A Clear after the run started fences the late guard; that includes holds-state scripts.
- **C-12:** `d1aa85b`. One `RACY_SECONDS`: Live reads `fingerprints.RACY_SECONDS`. `d95b18b`
  renames the selection settle to `FolderExplorer.SELECTION_SETTLE_SECONDS`.
- **C-14:** `bbed82c`.
  - Every byte size is SI (powers of 1000): `byte_size`, the log-size question and thresholds, and
    the memory window.
  - The disk budget is SI too: default 8 GB (8e9), minimum 1 GB, edited in GB = 10^9; the RAM
    budget's 1 GB floor follows. A saved budget keeps its bytes, so an old 8 GiB reads "8.6 GB".
  - `duration` gains an hour unit ("1 h 15 min").
- **C-15:** `898966f`. A view's `root://` key is percent-quoted as the store's. **What a user
  sees:**
  - An arrangement preset or reopen record saved before this, for a folder whose path below its
    data root needs quoting (a space, `%`, `#`…), carries the old unquoted key.
  - Reopened or applied, its plot waits with "<folder> is now another data root's folder: select
    it, then Rerun to use its data".
  - Selecting the folder and Rerun (or saving the preset again) uses the new key.
  - Folders without such characters are unaffected. No backward compatibility, as Tony chose.
- **C-23:** `3e04f03`.
  - The presets inspector names a refused change ("⚠ “a” not renamed: HeLab is quitting") or a
    RAM-only one (`saved_note`).
  - A script with no parameters shows its reopen or preset note on its status line
    (`AnalysisInstance.note_saved`).
- **C-4:** docs only. Waiting results expire after an hour (edit 1 below).
- **C-2:** `cb6fa23`. `resultPendingAnswered` carries why, and the plot says:
  - "not saved (expired): it waited over an hour for Make room";
  - "not saved: the disk cache was recreated";
  - "not saved: its cached analysis was cleared";
  - "(discarded)" only for Discard.
- **C-10:** `dce92c7`. View › "Toggle Thread Status Auto Pop-up" is gone; `view_toggle_thread_status`
  is in `RETIRED`.
- **Held cleanups, now applied:** `fce2de0`.
  - C-5 drops only `remove_results`' unused `_stored_keys`. Its `paths=` branch is tested, so it
    stays.
  - C-7, C-8, C-9.
  - C-27 removes `named_temp_files` and the `HeLab-shutdown` thread that only closed them.
- **C-24, the rest:** `0d7a83c`. The five Cache Only views call `folder_cache.store_options()`.
- **C-26, second part:** `1a15f61`. `CacheStore`'s events return their TypedDicts, and the casts go.
- **C-29, C-30 (low, Sextant's seam probes):** `28c0dff`.
  - Online, an arrangement preset's Live waits for the folder's first load to show its data (it gave
    up in the moment between the load's end and the data showing).
  - Offline, a folder never listed online is named: "<folder> can't be opened while working
    offline (not listed while online): its plots wait for its data".

- **C-31 (quality, C-14's leftover):** the commit after `41df9ce`. The status bar's RAM figures
  divide by 10^9, and `result_cache.LARGE_RESULT_BYTES` is 50 MB in SI (`50 * 10**6`), as its
  comment says.

**Declined:**
- **C-28 for `PresetBar`.** Presets are app-wide by design: one store in use, kept in one
  FolderCache, and every presets helper and test uses `preset_store()`. Moving only `PresetBar` to the
  workspace's cache would read and write presets in different FolderCaches in tests (the workspace
  cache is a frozen fixture there); in the app they are one object. `PlotReopen` already uses
  `plots.folder_cache()`, and `store_free` covers store deletes.
- **C-24 for `plots/arrangement.py` and `instance.py`.** Their by-value `store_options` is the
  presets tests' narrow seam. Sextant agrees.

## Left open

- **C-26, the app side.** `IOService.messages` and FolderCache's handlers should take `HelperEvent`.
  `store_options()` should be a TypedDict, `save_result(guard)` a `ResultGuard`, and
  `cache_admin(action)` a `Literal` of `ADMIN_ACTIONS`. `pending_saves`, `pending_results`,
  `mismatched` and `root_duplicates` should be typed by their event shapes. Best done with the
  `folder_cache` split below.
- **Open risks:**
  - **Windows venv redirector and cache moves (unsure; not seen):**
    - A venv's `python.exe` on Windows is a redirector that runs the real interpreter as a child.
      Killing it (`_reap`) ends the child only through its job object, so the child may hold files
      for a moment after `wait()` returns.
    - A cache move's rename could then hit WinError 32 now and then on a venv install (lab PCs, CI).
      Frozen builds don't have this.
    - The move's verify and recovery would catch it, but the user would see a failed move.
  - **Cross-test leaks through the app-wide IOService (C-28):**
    - Its timers and the plots' preset reads start helpers in later tests, on the store of the
      test running then.
    - `store_free` covers store deletes. The real-data guard can still blame a later test for an
      earlier one's helper (seen with a basetemp outside the checkout).
  - **Item 9's timer:** one per plot, set by the earliest limit; a refused save keeps its packed
    bytes outside the RAM budget's count while it waits, up to 120 s.

## Part 2's structural proposal: splitting `helab/utils/folder_cache.py` (for Tony)

From [findings.md](findings.md#helabutilsfolder_cachepy-size-and-structure-a-proposal-for-tony-not-a-change).

The file has ~3,750 lines. `FolderCache` has 191 methods, 35 signals and 112 attributes, and
`_on_event` alone is ~395 lines. It is six subsystems behind one QObject, each already marked by a
section comment and keeping to its own attributes. In order of payoff and least risk:
1. Extract the **store identity and presets** into `helab/utils/presets_state.py`: a Qt-free class
   over a small protocol. FolderCache keeps thin delegating methods; `test_store_identity.py`'s
   1560 cells already drive it through them.
2. Extract **saved results and disk usage** as `results_state.py`, sharing `store_answer` with (1).
3. Extract **data roots and constants** (`roots_state.py`).
4. Leave the **job machinery** in `folder_cache.py` (~1,500 lines), and split `_on_event` by
   operation, each part under 100 lines.

Rules for keeping it a pure refactor:
- the helper contract and every public FolderCache name stay;
- each extracted class owns the signals it emits;
- the C-26 app-side typing goes with it.

## Proposed doc edits

### AGENTS.md

1. **Saved analysis results / Caching (C-4, Tony):**
   - "results still waiting for an answer stay for the next session" and "At startup an inventory
     restores saves still waiting from an earlier session" → both last `PENDING_MAX_AGE` = 1 h from
     when they were held, and the startup sweep expires them first.
   - When one expires, or its store is recreated or its cached analysis cleared, the plot says why
     (C-2).
2. **Architecture, Package layout:** `helab/workers/` doesn't exist; add `helab/analysis/` and
   `helab/io_ops/`.
3. **The local lane** also runs `cache_move`, `result_find` and `result_save`.
4. **Caching, `FolderCache.cache_admin(action, …)`:** the list also has `prefs`, `clear_prefs`,
   `constants`, `presets`, `adopt_result`, `discard_result`, `clear_results`, `identity` and
   `budget`. Mention Settings → Cache's Clear folder preferences (`clear_prefs`).
5. **Caching, the sweep:** it also expires pending saves and results over an hour old, and deletes
   store files no row names once they are over an hour old (`_sweep_orphans`).
6. **Caching, the disk budget (C-14, Tony):** "default 8 GiB" → "default 8 GB (SI; at least 1 GB)".
   Every byte size HeLab shows is SI (kB/MB/GB = powers of 1000), and Settings → Cache edits the
   budget in GB = 10^9; a saved budget keeps its bytes. The settings paragraph's "reads 8 GiB as 0"
   → "reads 8 GB wrong".
7. **Visualization:** `127.0.0.1:8050` is the preferred port; another free one is taken when it is
   in use.
8. **Threading:** besides the readers, the GUI process has the short daemon threads
   `HeLab-artifact-cleanup` and `HeLab-cancel` (`io_service.py`). The `HeLab-shutdown` thread is
   gone (`fce2de0`).
9. **Live (C-12, Tony):** "not within `RACY_SECONDS` = 2 s" → one constant, `fingerprints.RACY_SECONDS`,
   used by the quick check and Live.
10. **Live, events (item 8, Tony):** "delivered once per key and at most once a minute per kind and
    folder (`RATE_SECONDS`), the held-back ones counted in the next" → "delivered once per key
    (once per shot), with no time limit".
11. **Script system:** the `helab/views/plots/` package also has `workspace`, `arrangement`,
    `presets` and `cached_results`.
12. **The patched-names rule:**
    - `folder_cache.store_options` is called as a module name, except in
      `helab/views/plots/arrangement.py` and `instance.py`, whose own copies the presets tests
      patch;
    - also `cache_location.cache_location_problem`;
    - `fingerprints.RACY_SECONDS` is read by `live` through the module.
13. **Testing:**
    - `tests/conftest.py`'s `store_free(*services)`: before a test deletes a store through real
      helpers, wait until neither its services nor the app-wide one has a cache helper running or
      unconfirmed.
    - `tests/test_helper_events.py` reads every module under `helab/views` and fails on a helper
      kind the app never matches, except `RECEIPTS`.
14. **Saved analysis results (item 9, Tony):**
    - A lookup or save refused because its folder's volume isn't verified this session waits for
      `volumesVerified` and is asked again once.
    - At `VERIFY_WAIT` (15 s) the plot computes, saying "Disk cache: still checking this drive; this
      result isn't saved yet."
    - The save waits up to `SAVE_VERIFY_WAIT` (120 s) for a guard-only lookup. A Clear after the run
      started fences that guard.
    - Then the amber line says "not saved: the drive couldn't be checked".
15. **Data roots (C-15, Tony):** a view's `root_key` is quoted exactly as the store's
    (`dataset_view.root_key`); records saved before with unquoted keys don't match.
16. **Presets:**
    - The inspector names refused or RAM-only changes.
    - A script with no parameters shows its reopen note on its status line.
    - An arrangement preset's Live waits for its folder's first load to show.
    - Offline, a never-listed folder is named (C-23, C-29, C-30).

### roadmaps/known-issues.md

- **Move to Fixed:**
  - "`cache_move.verify` doesn't check saved results' files": `9d90156` (C-6).
  - "`roots_verify` is missing from `io_helper.CACHE_ONLY`": `778641a`.
- **Add to Tests and CI, as Fixed:** the Windows rerun of
  `test_result_cache_quit.py::test_an_old_stores_answer_never_says_saved_in_the_recreated_one`
  (run 40270085653), fixed in `5607182`.
- **Add (unconfirmed):** the Windows venv-redirector risk for cache moves.

### Others

- `roadmaps/cache-storage-and-settings.md`:
  - ":665 'the Dash server uses it'" (`SynchronisedDict`) is stale;
  - "8 GiB" → 8 GB (C-14).
- `roadmaps/live-monitoring.md`:
  - note C-16 (a local folder's Live identity is its device node, not its volume ID);
  - item 8 (no per-minute cap).
- `roadmaps/result-caching.md:148`: as edit 1 (C-4), plus item 9's two waits.

## CI

The branch was pushed once at `253888d` (the reviewed state that `dev/v0.0.6` merged as
`9e88874`), giving CI run 40278222710: **success**, Python 3.13 tests and builds on every OS. Test
logs from `gh api repos/TonyXTYan/HeLab/actions/jobs/<id>/logs`:

| OS | Job | Result | RERUN |
|---|---|---|---|
| Windows | 121425551136 | 4334 passed, 18 skipped, 2 xfailed (14:08) | none |
| macOS | 121425551244 | 4354 passed, 2 skipped, 2 xfailed (8:06) | none |
| Ubuntu | 121425551270 | 4352 passed, 4 skipped, 2 xfailed (4:31) | none |

**The follow-up**, pushed at `e35df6f` (run 40289764951), **failed**; Ubuntu passed.
- **Windows:** the test step was cancelled at 83% after 18:25. My new offline test
  (`test_preset_folder_live.py`) left the app-wide IOService offline for the worker's next tests:
  two `test_presets_window.py` Live-preset tests ran offline, each with 5 reruns of a 30 s wait.
- **macOS:** `test_offline_browsing.py::test_a_source_request_left_queued_is_refused_as_it_starts`
  failed 6 times. Its `no_source_io` fixture sees every service's starts, and the app-wide
  FolderCache's local-lane inventory and identity probe (prompted by each test's new private store)
  started during it.
- **Fixed in `938b041`** (tests only):
  - the offline test ends online, in a `finally` and with an autouse fixture;
  - the macOS test checks only its own queued request.
  - The macOS collision wasn't reproduced locally, even in that worker's order. It's the C-28
    cross-test leak (open risks).

Pushed at `938b041`, run 40293473874: **success**, no RERUN on any OS:

| OS | Job | Result | RERUN |
|---|---|---|---|
| Windows | 121473849127 | 4437 passed, 25 skipped (pytest 12:42; the Run Tests step 12:46, dev's was 13:23) | none |
| macOS | 121473849306 | 4464 passed, 2 skipped (8:26) | none |
| Ubuntu | 121473849231 | 4462 passed, 4 skipped (7:37) | none |

Proposed known-issues entry, so it doesn't recur: the app-wide IOService and FolderCache last a
worker's run, and real-window tests that change their state (Work Offline, quitting) must restore it
(as `back_online` and `no_quitting_cache` do). A test may not assume no other service starts work
during it.
