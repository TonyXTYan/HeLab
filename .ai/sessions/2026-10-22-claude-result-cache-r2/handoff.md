# Result cache R2: handoff (Cellar, 2026-10-22)

Branch `agent/result-cache-r2` from `c3d4b50`; commits `c31ac10` (schema, reported to CoCo),
`ef486d3` (back end), `bcdc12d` (plots), `3e5a934` (Settings), plus this session folder. Measurements
and evidence: [notes.md](notes.md).

## Merged with `dev/v0.0.6` (Presets Reopen, 2026-10-23)

`7daa133` commits CoCo's session notes. `29429fb` merges `dev/v0.0.6` at `c204d4b`. `8cb7886` fixes the
reopen seam. None of them is pushed.

Conflicts, both sides kept:

| File | Resolution |
|---|---|
| `helab/utils/cache_store.py` | The open records `_presets_table` beside `_results_table` / `_pending_results`; `_migrate` checks four things (constants, raw times, presets, results) and adds the presets table and `RESULT_SCHEMA` + `gen_results` as needed; docstring names all of them. |
| `helab/io_ops/admin.py` | Imports `PresetRowFields` and `ResultCountField`; `ADMIN_ACTIONS` has `presets` and `clear_results`, `clear_root_results`, `adopt_result`, `discard_result`. |
| `helab/views/plots/instance.py` | Imports both: presets (`PlotCheck`, `SavedPlot`, …) and `DISK_CACHED`, `RAM_ONLY`, `AnalysisContext`. |
| `tests/test_headless_imports.py` | `presets` beside `result_cache`, `result_codec`, `result_types` in the Qt-free list. |

`events.py`, `CacheTab.py` (the Presets row sits below Folder preferences, after the Cached analysis
row and the reuse check box), `folder_cache.py`, `SettingsDialog.py` and `settings_defaults.py` merged
without conflicts. No remover names the `presets` table. `test_no_removal_of_results_touches_presets`
checks that Make room, Clear cached analysis (all, a root's, a folder's), a purge by age, Clear all and
a root's Clear cached data… all keep presets.

**The seam (`8cb7886`).** `AnalysisInstance.run_reopened` is where a plot reopened at start, or opened
from an arrangement preset, runs once `FolderWait` finds its data. It called a plain `_submit(view)`,
which never looked up or saved a result. It now submits as the user's first run does
(`one_off=True`): an exact saved match shows without computing, and a new result is saved.
`test_a_reopened_plot_shows_its_exact_saved_result_without_computing` (real helpers, reopened through
`TreePanelWidget.reopen_plot` and `FolderWait.found`) fails before the fix. A reopened plot whose data
is already in RAM still goes through `run_reopened`; a plot opened when no saved record exists goes
through `run()` as before.

**Tony's answers (via CoCo):** Make room keeps its order (least recently shown first), with no extra
skip for results used this session or on screen. The presets inspector stays as built.

**Checks at `8cb7886`:** full suite (`-n 12 --reruns 5 --reruns-delay 1`) 2727 passed, 2 skipped,
2 xfailed, **no RERUN** (the 2 warnings are the existing pyqtgraph/NumPy deprecation in
`test_t_spectrum`). `mypy --strict helab` (162 files) and `tests` (130), `pyright helab tests` and
`git diff --check` are clean.

## What it does

A completed one-off run (the plot's first run, Rerun, a reload; never Live's reruns) of a plot that
supports it is saved in the disk cache. Before such a run the plot asks a local-lane helper for an
exact match; one shows at once ("from disk cache, computed 2026-10-22 14:03" on the source line and in
the record) and the run is skipped, also after a restart. A saved result of the same plot and settings
whose script, environment, data or constants changed shows at once with one amber line ("saved result
from … is outdated (script version 1 → 2): rerunning") while the run goes on and replaces it. Saved
results count toward the one disk budget. Settings → Cache and Settings → Data roots each get Clear
cached analysis, apart from Clear cached data.

## Store schema (`c31ac10`; unchanged since)

In `store-v3` (`helab/utils/cache_store.py`, `RESULT_SCHEMA`, added to older stores by `_migrate`):

```sql
CREATE TABLE results (
  result_id TEXT PRIMARY KEY, path TEXT NOT NULL,      -- the folder's root:// key, as datasets
  lookup TEXT NOT NULL, family TEXT NOT NULL,          -- SHA-256 of the exact key / of plot + settings
  analysis_id TEXT NOT NULL, action TEXT NOT NULL,
  record TEXT NOT NULL,                                -- {"key": lookup key, "result": AnalysisResult record}
  file TEXT NOT NULL, bytes INTEGER NOT NULL,          -- results/<uuid>.npz and its size
  computed_at REAL NOT NULL, saved_at REAL NOT NULL, last_used REAL NOT NULL,
  UNIQUE (path, lookup));
CREATE INDEX results_family ON results (path, family);
CREATE INDEX results_last_used ON results (last_used);
-- meta: gen_results (its own generation, outside KINDS)
-- folder_epochs rows: root-results-clear://<uuid> (a root's Clear cached analysis),
--                     results:<root key> (one folder's results: purges)
```

- `lookup` and `family` leave the folder out, so a nested root's re-key moves rows by `path` alone
  (`_rekey_results`: the one saved later wins a collision, the other's file retired).
- Files live in `results/` beside `datasets/`; `retired_files` names them `results/<file>`; the sweep,
  orphan cleanup (older than an hour), inventory and `root_usage` know them.
- A read-only store (a newer HeLab's) without the table reads as nothing saved and saves nothing.
- Results count toward `_live` (Tony: one budget). An older HeLab never reads or clears results, its
  sweep of a retired `results/…` entry deletes nothing (the file becomes an orphan ours deletes), and
  its re-key of a nested root leaves results behind (as with folder constants).

## Script contract (`helab/scripts/base.py`)

| Hook | Default | Meaning |
|---|---|---|
| `cache_supported(action)` | False | Rule 4: completed one-off runs may be saved and reused |
| `cache_types(action)` | () | dataclasses, enums and `Reducer`s the data may hold: the only types rebuilt |
| `cache_pack(action, data)` | `result_codec.encode` | data → JSON tree + named NumPy arrays (worker thread) |
| `cache_unpack(action, tree, arrays)` | `result_codec.decode` | back (GUI thread; arrays read-only) |
| `cache_holds_state(action, owner)` | False | the plot keeps something a next run starts from: no lookup |
| `cache_result(action, result)` | True | the run gave what a fresh plot would: may be saved |

`helab/analysis/result_codec.py` writes one `.npz` (`npz-json-1`: the arrays, and the tree as UTF-8 in
`__tree__`), read with `allow_pickle=False`; object arrays and undeclared types are refused
(`CodecError`), nothing is imported from a file. A `Reducer` saves an object by its data and rebuilds
it with HeLab's own code: `result_types.FIT_MODEL` saves a fit model by key, title, parameters and
fixed constants and rebuilds a registered model or the arrival-time profile; any other (Correlations'
g² peak) comes back without functions for the script's `cache_unpack` to replace
(`result_types.unavailable_model`). `result_types.COMMON` lists the shared numerics' result types.

Opted in, from the measurements: **Correlations** (`cache_holds_state`: a kept box, detection or pair
counts; `cache_result`: none of them used, the count complete within its time budget, not Live's;
`cache_unpack` rebuilds the peak model from the result's spec) and **Release time** (not a Live
rerun's bootstrap-skipped result).

## The key (`helab/analysis/result_cache.py`)

`lookup_key(context)` is `AnalysisResult.reuse_key()` of the run as submitted, without `root_key` (the
row's `path`) and `found` (known only after the run; runs that depend on kept plot state are kept out
by `cache_holds_state`/`cache_result`), **plus the execution environment** (added: `python` minor,
`numpy`, `scipy`, `helab` versions; the shared numerics in `helab/analysis` don't change a script's
hash). `family_key` is analysis ID, action, the parameters in use and a preset mask's circles: data,
script identity, environment and lab/folder constants changing keep the family (shown outdated, with
`outdated_reasons` in words); a parameter or the mask changing doesn't (a different question).

## Flow and save guard

`AnalysisQueue.prepare`/`enqueue` (`submit` does both; `runner_core.py`, a small split outside the
listed paths) let the plot look up before queuing. `CachedRuns` (`helab/views/plots/cached_results.py`)
asks `FolderCache.find_result` (`result_find`, local lane, `IOService.LOCAL_OPERATIONS`); the answer
(`result_found` / `result_missing` / `error`) carries the guard taken then, as the run starts
(`start_result_job`: `gen_results`, the folder's `results:` epoch, the root's `root-results-clear://`
epoch; never the dataset kinds' or `root-clear://`, which leave results). The worker packs a to-cache
run's completed result (`AnalysisResult.packed`, never kept in `RamResults`); `_finished` hands it to
`FolderCache.save_result` (`result_save`, the bytes written to the helper's private folder by the
reader thread, `IORequest.blob`), which checks the guard, Don't cache this folder and the budget in its
transaction. A found result's file is copied to the helper's private folder and unpacked by the
reader thread: the GUI never opens the store. An error is said ("the disk cache couldn't be read (…):
computing") and never saves (no guard).

## Decisions I took (please confirm or change)

1. *(Replaced by Follow-up 1: Make room or Discard.)* **Budget refusal, no pending save.** A result that doesn't fit isn't saved (its file retired at
   once; nothing removed to make room) and the status line says "⚠ not saved in the disk cache: it
   doesn't fit the disk budget (Settings → Cache)". The dataset cache's Make room flow would ask a
   question per plot run; results are cheap to recompute relative to that.
2. **Don't cache this folder** also refuses result saves, and lookups answer nothing saved: the user
   said not to cache that folder. (Results saved before the flag stay until a clear.)
3. **Wording.** 50 MB notice (status bar, once per save, plus a WARNING log line with the folder):
   "Saved Correlations (halo_run) in the disk cache: 63.0 MB". Source line: "from disk cache, computed
   2026-10-22 14:03" / "saved result of 2026-10-22 14:03, outdated". Record: "From disk cache, computed
   … (job a3)" / "· outdated: …"; a computed one "· saved in the disk cache". Buttons: "Clear cached
   analysis…" (Data roots), Cache tab row "Cached analysis" with "Clear…", purge row "Cached analysis
   not shown in the last N days". 50 MB is 50 MiB (`50 << 20`), as HeLab shows sizes.
4. **Purge by age** of results goes by `last_used` (when a saved result was last shown), like datasets.
5. **Opt-in list**: Correlations and Release time only (table in notes.md). Velocity distributions
   measured 0.5 s on 500,000 events (one detection, no bootstrap): left off, with the other quick plots.
6. **Which runs**: only runs the user asked for. The catch-up run when Live stops is a follow run and
   isn't saved (R4's "final one-off save" stays for R4).
7. After Clear cached analysis a plot showing a saved result keeps its plot; its record says "kept in
   RAM only" again.

## Left for Tony

- The opt-in list and the timings; the refusal (vs pending save); the wording above; 50 MiB vs 50 MB.
- Whether a per-user setting should turn result reuse off (Rule 3 mentions user defaults): not built.

## Shared files outside my parts (minimal, for the Presets Reopen floor to sync)

- `helab/views/plots/instance.py`: `run()` (cancels a lookup too; marks one-off) and one argument in
  `_show_follow` (the amber line adds `self._cache_note`); class-level attributes `_cached_link`,
  `_cache_note`, `_cache_status` (not in `__init__`). Everything else is in `_submit`, `_finished`,
  `_reload_from` and new `_cached_*` methods.
- `helab/analysis/runner_core.py`, `runner.py`: `prepare`/`enqueue` split, packing in `_run`.
- Tests updated: `test_root_clear.py` (Clear cached data's new text), `test_root_remove.py` (menu
  list), `test_helper_dispatch.py` (routes), `test_headless_imports.py` (three Qt-free modules).
- No `settings_defaults.py` rows.

**For the Presets Reopen floor** ("find a cached result for this plot's run"): nothing to call. A
reopened plot runs through `AnalysisInstance.run_reopened` → `_submit(view, one_off=True)` (fixed at
the merge, `8cb7886`), which looks itself up; an exact match shows without computing. A Qt-free key for other uses:
`result_cache.lookup_key(context)` with `AnalysisQueue.prepare(...)`.

## What Tony should check on screen

1. A Correlations plot (radial, a few seconds) on a folder below a `.helab-root`: after it draws, its
   record (tooltip of the source line) ends "saved in the disk cache". Quit, start HeLab, load the
   folder, open Correlations again: it draws at once, the source line says "from disk cache, computed …".
2. Change a setting and Rerun: computes; change it back and Rerun: shown at once.
3. Edit the script file (a comment) or bump its version, reopen the plot: the old result shows with
   the amber "outdated (script file changed): rerunning" line until the run ends.
4. Settings → Cache: the Cached analysis row (count, size); Clear… asks first; Clear all says cached
   analysis stays. Settings → Data roots: Clear cached analysis… (button and right-click) asks first
   and leaves the Cached column's data; Clear cached data… leaves the saved results.
5. Release time with the default 1,000-replicate bootstrap: the second open is instant.
6. A folder without a `.helab-root`: plots work as before, nothing saved (RAM only).
7. (Follow-up 2) After a plot saves, its folder's row shows the grey REPORT badge after the data
   cache's; the row tooltip and Folder details' cache line say "Cached analysis: 1 result, <size>".
   Settings → Cache › Reuse saved analysis results off: the badge and lines go; on: back. Clear cached
   analysis…: they go.
8. (Follow-up 2) With a small budget, Make room for a result removes the least recently shown other
   results; a plot that recomputes one of those right after saves its newer copy (or asks its own
   Make room), never refused.

## Proposed documentation edits (for the Coordinator)

**AGENTS.md › Caching** (after the dataset cache paragraph): "**Saved analysis results** (result caching
R2): a completed one-off run of a plot whose script sets `cache_supported` (Correlations, Release time)
is saved in `store-v3`'s `results` table (one row per folder `root://` key and exact lookup key; data in
`results/<uuid>.npz`, NumPy arrays and a JSON tree, never a pickle: `helab/analysis/result_codec.py`)
by a local-lane helper (`result_save`) under a guard its lookup took as the run started (`gen_results`,
the folder's `results:` and the root's `root-results-clear://` epochs; not the dataset ones). Before
such a run the plot asks `result_find` (`CachedRuns`, `helab/views/plots/cached_results.py`): an exact
match (`result_cache.lookup_key`: `reuse_key` without folder and `found`, plus Python/NumPy/SciPy/HeLab
versions) shows at once and skips the run; one of the same plot and settings whose script, environment,
data or constants changed shows marked outdated (amber) until the run replaces it. Never Live's reruns;
a folder without a disk cache, or with Don't cache, saves nothing. Results count toward the one disk
budget (a save that doesn't fit isn't made and the plot says so); one over 50 MB is said once per save.
Clear cached analysis (Settings → Cache, and per root in Settings → Data roots) removes only results
(`cache_admin clear_results` / `clear_root_results`, `removed` kind `results`); Clear all and a root's
Clear cached data leave them; purge by `last_used`."

**AGENTS.md › Script system** (after the Hooks paragraph): "**Saved results** (R2): `cache_supported`
(default off), `cache_types` (dataclasses, enums, `result_codec.Reducer`s such as
`result_types.FIT_MODEL`), `cache_pack`/`cache_unpack` (default: the codec), `cache_holds_state` (kept
plot state: no lookup) and `cache_result` (a fresh plot's result: may be saved). `AnalysisQueue.prepare`
and `enqueue` split `submit`; a to-cache run's result is packed on the worker (`AnalysisResult.packed`)."
Also add `result_cache`, `result_codec`, `result_types` to the Qt-free module list.

**roadmaps/result-caching.md**: R2 row → "done 2026-10-22 (`agent/result-cache-r2`): disk-cached
one-off results (`cache_supported`: Correlations, Release time, from measured run times), exact
lookup key with the execution environment, outdated marker, results in the one disk budget (Tony),
Clear cached analysis in Settings → Cache and Data roots". Open decisions: replace "Result storage
format and location … budget default" with "Decided 2026-10-22: `store-v3` `results` table + `results/`
`.npz` files (NumPy arrays and a JSON tree, no pickle), owned by helpers; no separate budget (Tony)".
Rule 6's "The disk result cache has its own budget" → "Saved results count toward the disk cache's
budget (Tony, 2026-10-22)"; Rule 1's "budgets … never touch the other" → "clearing and eviction".

**roadmaps/cache-storage-and-settings.md**: under the store layout, the `results` table and `results/`
folder; under Settings → Cache, the Cached analysis row and purge; under Data roots, Clear cached
analysis…; note that `cache_move.verify` doesn't yet check result files' sizes (follow-up below).

**roadmaps/_readme.md**: mark R2 done; add follow-ups: (a) `cache_move.verify` to check `results`
files; (b) optional per-user "Reuse saved analysis results" setting (Rule 3); (c) R4 next.

**.ai/MANUAL_TODO.md**: "Result cache R2 on screen" with the six checks above, on the Mac and on a lab
PC (Windows process start makes a lookup ~0.1–0.5 s there: confirm it still beats the runs).

## Follow-ups

- `cache_move.verify` (not an owned path): include `SELECT file, bytes FROM results` with the files in
  `results/` (today they are copied with the folder but not size-checked).
- A plot whose run started from kept state (Correlations after its first run) is neither looked up nor
  saved unless `cache_result` says the result equals a fresh plot's; reopening the plot (or a restart)
  finds it again.

## Follow-up 1 (after Tony's answers, 2026-10-22)

Commits `b4b435e` (Make room or Discard), `67f9266` (reuse setting and plot mark); not pushed yet
(CoCo: wait for the review findings). The CI run on `6906d96` (39746062230) was green on macOS,
Windows and Ubuntu with no RERUN.

**Schema change, with its reason.** A new table `pending_results` (in `RESULT_SCHEMA`, added to older
stores by `_migrate`, including stores made by `c31ac10`): a result that doesn't fit the budget must
wait for the user's answer, with its file, record, the plot's name and its run's save guard, several
per folder. The dataset `pending_saves` table allows one per folder and checks dataset kinds, so it
couldn't hold them. `results` itself is unchanged.

**Make room or Discard** (replaces decision 1): `CacheDialogs` asks it in the same queue as the
dataset saves, also after a restart (the startup inventory restores waiting results):
"Not enough room in the disk cache to save Correlations's result for halo_run (63.0 MB, 7.9 GB of
8.0 GB used)." with "Make room removes 3 saved analysis results (70.0 MB) not shown since 4 Oct,
least recently shown first. Cached data isn't touched. The plot stays as it is either way." and the
buttons Make room / Discard. Decisions:
- **Make room removes other saved results only, never cached datasets** (Rule 1: one budget, but
  clearing stays the user's per kind). When results alone can't free enough, only Discard is offered,
  with where to free space (Settings → Cache: Clear cached data, Remove old entries) or to raise the
  budget.
- **No 80 % approval question for results**: the dataset rule asks before a cached folder's update
  grows; a result never updates another (one key, one result), so it doesn't apply.
- A waiting result expires after an hour unanswered (as dataset saves), goes with Clear cached
  analysis, is discarded on Make room if a clear or a nested root's re-key happened since its run
  started (its guard), and doesn't count toward the budget meanwhile.
- The plot says "not saved yet: the disk cache is full (Make room or Discard)", then shows "saved in
  disk cache" or "not saved in the disk cache (discarded)".

**Reuse setting**: Settings → Cache › "Reuse saved analysis results" (`result_reuse`, default on, read
at each run; off: no lookups, no saves; saved results stay until cleared).

**Plot mark** (wording to confirm): the source line's first line ends with "disk cache reuse on" (its
runs are looked up and saved), "saved in disk cache", "from disk cache, computed 2026-10-22 14:03" or
"saved result of 2026-10-22 14:03, outdated". Nothing for quick plots, RAM-only folders or reuse off.

**Not done yet**: the folder-row badge and Folder details' cache line (waiting for CoCo's
confirmation of the reading); the merge with `dev/v0.0.6` and the `run_reopened` seam (after Presets
Reopen lands); the review findings.

Proposed doc edits, in addition to those above: AGENTS.md › Caching: "a result that doesn't fit waits
in `pending_results` and CacheDialogs asks Make room (other saved results, least recently shown, never
datasets) or Discard; Settings → Cache › Reuse saved analysis results (`result_reuse`, default on)";
`roadmaps/cache-storage-and-settings.md`: the same under pending saves and the Cache tab.

## Review fixes (Gauge on `6906d96`)

All four findings fixed, each with a regression test in `tests/test_result_cache_review.py`:

1. **[P2] Stale result events after a Clear cached analysis.** `FolderCache` remembers when each
   result read or save was asked (`_result_ops`, the newest 1,024, kept after the helper ends); a
   `result_found`, `result_saved` or `result_pending` for a folder whose results a removal took since
   (all, a root's or a purge: `removed(..., ["results"])`) is answered as nothing found (with no
   guard: a save of that run would be refused), or as not saved (reason `cleared`); a stale waiting
   result is dropped from the store (`discard_result`), never asked. So a late answer can't mark a
   cleared plot as saved, and a pre-clear exact lookup no longer skips computing. A purge that took
   another result of the same folder also makes a save in flight read as not saved: conservative.
2. **[P2] Sweep for files retired by result saves.** `result_saved`, `result_not_saved` and
   `result_pending` carry the store's `next_deadline` (typed); `FolderCache` schedules the sweep.
3. **[P3] Retention after clearing a result reused from disk.** A result read back is marked
   `DISK_CACHED` (exact and outdated); `describe` says "From disk cache, computed … · in the disk
   cache", and "· kept in RAM only" after a Clear cached analysis.
4. **[P3] Damaged files.** `result_codec.unpack` turns `zipfile.BadZipFile`, `TypeError` and
   `KeyError` into `CodecError` too, so the lookup keeps its guard and the computed result replaces the
   damaged file.

Also the blank line at the end of `result_cache.py`.

**Mixed versions** (Gauge; add to AGENTS.md's note on lab machines running mixed versions): an older
HeLab opens the migrated store fine and its Clear all and sweep leave results, but it counts result
rows and not result files in the usage, so its saves can go past the shared budget; an older sweep
removes a retired result's `retired_files` row and leaves its file, which the new orphan sweep deletes
after an hour; an older nested-root re-key leaves result rows under the old key: misses, never reuse
across folders.

**Manual check to add**: clear cached analysis while a plot shows a result reused from disk: the plot
stays, its record says "kept in RAM only", and its next Rerun computes.

## Review fixes, round 2 (Gauge on `b2f342e`)

1. **[P2] Make room evicting another result of the same folder.** The eviction's `removed` event says
   `evicted`: `FolderCache.removed(..., evicted=True)` still resets the evicted folders' plots'
   marks but leaves waiting results (the one being saved among them) and doesn't make reads or saves
   asked before stale. One adoption now answers `[True]` and the plot shows "saved in disk cache".
   Plots of that folder showing another saved result also say "kept in RAM only" after an eviction
   (the event names folders, not results): conservative.
2. **[P2] A delayed inventory** keeps waiting results an event added after it was asked for
   (`_pending_result_added`), as the dataset merge does.
3. **[P3] The plot's warning** "not saved yet: the disk cache is full (Make room or Discard)" is
   replaced once answered: cleared when saved, replaced by "not saved in the disk cache (discarded)";
   other warnings on the status line stay.

Each has a regression test in `tests/test_result_cache_review.py` through real helpers, the dialog
and FolderCache's events; all three fail without the fixes.

## Review fixes, round 3 (Gauge on `81a9529`): evictions by result, the lifecycle table

**The cause, fixed once.** Make room's eviction no longer acts as a clear of the folder:
- The store's eviction moves no epoch (only clears and purges do), so the folder's other saves and
  waiting results keep their guards. Its removal names the evicted results, `[folder, lookup]` each
  (`ResultRemoval.evicted`, the `removed` event's `evicted`).
- `FolderCache._results_evicted` records them by (folder, lookup) (`_evicted`, the newest 1,024), never
  in `_removed_paths`: a `result_found` of an evicted row asked before is answered as missing *with its
  guard* (the run computes and may save again); a `result_saved` of that key asked before reads as not
  saved; `resultsEvicted` tells plots, and only a plot whose shown result was evicted says RAM only.
- The helper's `result_found` carries the row's `lookup` (an outdated one's differs from the one asked).
- A purge also removes the waiting results of the folders it took results from (their guards no
  longer hold, so Make room would refuse them): the GUI's question and the store now agree.

**The table**: what the store keeps · what the plot shows · the question. Each cell is a test in
`tests/test_result_lifecycle.py` through real helpers and FolderCache events (the cell's event held
until the removal is done, then delivered).

| In flight ↓ / meanwhile → | Make room evicts the same result | Make room evicts another of the folder | Clear cached analysis (all / root) | Purge by age (the folder's results) | Discard |
|---|---|---|---|---|---|
| **Lookup** (answer held) | row gone · computes (the stale `result_found` reads as missing, guard kept) · — `lookup_x_eviction_of_the_same_result_computes` | row kept · shown from disk, 0 computations · — `lookup_x_eviction_of_another_result_shows_it_from_disk` | rows gone · computes, not saved (guard predates the clear) · — `lookup_x_clear_or_purge_computes[all, root]` | rows gone · computes, not saved · — `lookup_x_clear_or_purge_computes[purge]` | can't happen (a lookup has no question) |
| **Save** (acknowledgement held) | row gone · RAM only · — `save_x_eviction_of_the_same_result_is_ram_only` | its row kept · "saved in disk cache" · — `save_x_eviction_of_another_result_is_saved` | rows gone · RAM only · — `save_x_clear_or_purge_is_ram_only[all, root]` | rows gone · RAM only · — `save_x_clear_or_purge_is_ram_only[purge]` | can't happen |
| **Waiting result** (question open) | can't happen (Make room never evicts its own key; a waiting key isn't saved) | waiting row kept, guard holds · its Make room saves it · question stays, then answered True — `waiting_x_another_waiting_ones_eviction_keeps_its_question_and_saves` | waiting row gone · "not saved in the disk cache (discarded)" · question gone — `waiting_x_clear_drops_the_question[all, root]` | waiting row gone (guard broken) · "discarded" · question gone — `waiting_x_purge_of_its_folder_drops_the_question` | waiting row gone · "discarded" · question gone — `waiting_x_discard` |
| **Adoption** (Make room asked) | can't happen | another adoption evicted the row its plan named: nothing removed, still waiting · question asked again with the new plan — `adoption_x_another_adoptions_eviction_asks_again_with_the_new_plan` | the clear's transaction first: "gone" · RAM only · question gone — `adoption_x_clear_before_it_is_gone[all, root]` | the purge's first: "gone" · RAM only · question gone — `adoption_x_purge_before_it_is_gone` | can't happen (one answer per question) |

(The adoption's own transaction first, then a clear: the clear removes the newly saved row as any saved
row, covered by the Clear cached analysis tests.)

Conservative, as before: a save acknowledged after an eviction of its own key reads as not saved even
when its transaction came after the eviction (the store has it; the next lookup finds it).

## Review fixes, round 4 (Gauge on `de6825f`): a key's own epoch, and the table completed

**Store.** Make room's eviction now bumps a persisted epoch of each evicted key, `folder_epochs`
row `result-key:<root key>#<lookup>` (no new table). `start_result_job(path, lookup)` takes it with
the folder's and root's (the lookup passes its key), and both `save_result` and `adopt_pending_result`
check it (a guard without it counts from 0): a save already running for an evicted key can't write it
back, by any helper or HeLab, while the folder's other keys keep their guards; a run started after the
eviction takes a fresh guard and saves it again. A waiting replacement of an evicted key (a saved row
and a waiting result can share a key: an over-budget replacement keeps the saved row) goes with it,
its file retired, named in the removal (`dropped`, the event's `dropped`); FolderCache forgets its
question and answers it False. A Make room acknowledgement that arrives after a Clear cached analysis
of its folder is answered False (not saved).

**The table, completed** (replaces round 3's; each cell a test in `tests/test_result_lifecycle.py`,
store-only cells in `tests/test_result_cache_store.py`):

| In flight ↓ / meanwhile → | Make room evicts the same key | Make room evicts another key of the folder | Clear cached analysis (all / root) | Purge by age | Discard |
|---|---|---|---|---|---|
| **Lookup** | computes, RAM only (its pre-eviction guard: the save is refused); a run asked for later saves it · `lookup_x_eviction_of_the_same_result_computes_ram_only_then_a_rerun_saves` | shown from disk · `lookup_x_eviction_of_another_result_shows_it_from_disk` | computes, RAM only · `lookup_x_clear_or_purge_computes[all, root]` | computes, RAM only · `…[purge]` | of a waiting replacement of the key: the saved row is shown · `lookup_x_discard_of_a_waiting_replacement_shows_the_saved_row` |
| **Save**, answer after its transaction | RAM only · `save_x_eviction_of_the_same_result_is_ram_only` | saved · `save_x_eviction_of_another_result_is_saved` | RAM only · `save_x_clear_or_purge_is_ram_only[all, root]` | RAM only · `…[purge]` | can't happen (per request) |
| **Save**, transaction after the eviction | refused by the key's epoch, nothing written, RAM only · `save_x_eviction_of_the_same_key_before_its_transaction_is_refused`; store: `a_save_running_since_before_an_eviction_cant_write_the_key_back` | saved (its guard holds) · same store test | refused (folder/root epoch), as before | refused (folder epoch) | — |
| **Waiting result** | its replacement goes with the evicted saved row (Make room's question says so): question gone, "discarded" · `waiting_x_eviction_of_its_keys_saved_row_drops_the_replacement`; store: `a_waiting_replacement_goes_when_its_saved_row_is_evicted`; its `result_pending` still in transit: ends "discarded", nothing kept · `waiting_in_transit_x_eviction_of_its_key_ends_not_saved` | stays, its Make room saves it · `waiting_x_another_waiting_ones_eviction_keeps_its_question_and_saves` | question gone, "discarded" · `waiting_x_clear_drops_the_question[all, root]` | question gone, "discarded" · `waiting_x_purge_of_its_folder_drops_the_question` | question gone, "discarded" · `waiting_x_discard` |
| **Adoption** (Make room asked) | "gone" · `adoption_x_eviction_of_its_keys_saved_row_is_gone` | the plan changed: nothing removed, asked again · `adoption_x_another_adoptions_eviction_asks_again_with_the_new_plan` | the clear first: "gone" · `adoption_x_clear_before_it_is_gone[all, root]`; the adoption first, its acknowledgement after the clear: not saved · `adoption_acknowledged_after_a_clear_is_not_saved` | "gone" · `adoption_x_purge_before_it_is_gone` | another HeLab's Discard at once: one wins, the other is "gone" · `two_processes_answering_one_waiting_result_one_wins` (4 rounds, two processes) |

**Scope.** One question per waiting result in one HeLab (CacheDialogs asks one at a time and sends one
answer); Discard and Make room of one pending id from two HeLabs are decided by the store's
transactions (one success, one "gone"). Message order (answers held until the removal is done) and
transaction order (a save or adoption reaching the store after the removal) are both covered where they
differ. Conservative, as before: a save acknowledged after an eviction of its own key reads as not
saved, and a purge that took another result of a folder makes a save in flight there read as not saved.


## Review fixes, round 5 (Gauge on `4c50d01`)

1. **[P2] A late `result_pending` for an id already gone** (dropped by Make room's eviction of its
   key, or otherwise answered) becomes a terminal `result_not_saved` (reason `dropped`) in
   `FolderCache._on_result_event`: the plot says "not saved in the disk cache (discarded)" and keeps
   nothing waiting. The table's Waiting row gains the in-transit cell
   (`waiting_in_transit_x_eviction_of_its_key_ends_not_saved`).
2. **Make room's question names what it also discards.** The room plan carries the waiting
   replacements of the keys it evicts (`ResultRoom.dropped`, `dropped_labels`), and
   `CacheDialogs.result_room_text` adds: "It also discards 1 newer result of it still waiting to be
   saved (Correlations)." Old guards aren't rebased.
3. **Lifetime of the per-key epochs** (`folder_epochs` rows `result-key:<root key>#<lookup>`): made by
   Make room's eviction of that key; deleted only where a broader fence now covers them, in the same
   transaction after that fence moves: Clear cached analysis of everything (after `gen_results`)
   deletes them all; a root's (after its `root-results-clear://` epoch) deletes that root's; a
   folder's clear or a purge that took the folder's results (after its `results:` epoch) deletes that
   folder's. Never by age or by the sweep. A guard taken before stays refused by the broader fence;
   one taken after counts the key from 0 again (`key_epochs_are_compacted_under_the_broader_fence`).
4. **The lookup cell and comment corrected**: a lookup answered after Make room evicted its key
   computes and stays in RAM (the store refuses that run's save: its guard predates the eviction); a
   run asked for later takes a fresh guard and saves it.

## Review fix, round 6 (Gauge on `339ed5b`: review complete, one P3)

Make room removes exactly what its question named, waiting replacements included: the answer sends
the plan's dropped pending ids (`dropped_ids`, empty when none) beside its `room_ids`, and
`adopt_pending_result(expected_dropped=…)` removes nothing if the replacements it would discard
differ (a replacement queued after the question was shown); the plan comes back and the question,
whose identity now includes those ids (`CacheDialogs.question`), is asked again naming it
(`test_a_waiting_replacement_that_appears_after_the_question_makes_it_ask_again`).

## Follow-up 2 (Tony's answers, 2026-10-22)

Commits `e6f56ae` (Make room), `f1a6c08` (row badge); not pushed (Gauge reviews the delta first).

**Make room removes old saved results only** (Tony: "make room only should remove very old saved
results so any newer copy saving in cache is fine"). It still removes the least recently shown other
saved results (by `last_used`) and nothing else, and no longer fences or drops anything:
- Gone: the per-key epoch (`folder_epochs` rows `result-key:…`, their compaction, the `lookup` of
  `start_result_job`), the dropping of waiting replacements (`dropped`, `expected_dropped`,
  `dropped_ids`, `ResultRoom.dropped`/`dropped_labels`) and the question's "It also discards…" sentence.
  Rounds 4–6's notes above on those are superseded. (No store outside this unpushed branch has
  `result-key:` rows.)
- A newer copy of an evicted result, being saved or waiting, keeps its guard and checks the budget in
  its own transaction like any save: saved if it fits, else its own Make room question.
- Every save gives its row a new `result_id` (a replacement's too), so a plan, which names ids, never
  removes a copy saved after the question was shown: the answer then removes nothing and the question
  is asked again with the new plan, in which that copy (just saved, so most recently used) comes last.
- The app tracks evictions by `result_id` (`result_found`, `result_saved` and an adoption's answer
  carry it; `removed.evicted` names `[folder, lookup, result_id]`): an answer about an evicted row
  isn't current, while a newer copy stays "saved in disk cache". A plot saved by Make room is now
  tracked too (`resultPendingAnswered` carries the row's id), so a later eviction marks it RAM only.
- The user's clears (Clear cached analysis…, Clear all, a root's) fence running saves as before.

**Should Make room also skip results used this session or shown by a plot? I recommend not.** The
order already puts them last: showing an exact match and saving both set `last_used`, so results
from earlier sessions that nobody showed since go first. A shown plot keeps its result in RAM either
way (its record then says "kept in RAM only"). Skipping them would make Make room fail ("only
Discard") more often exactly when this session's work filled the budget. Easy to add if Tony wants it.
*Tony (2026-10-23, via CoCo): keep this order, no extra skip.*

**The table now** (replaces round 4's; tests in `tests/test_result_lifecycle.py`, store cells in
`tests/test_result_cache_store.py`; the Clear, Purge and Discard columns are unchanged):

| In flight ↓ / meanwhile → | Make room evicts the same key's old row | Make room evicts another key of the folder |
|---|---|---|
| **Lookup** | computes and saves the newer copy (its guard holds) · `lookup_x_eviction_of_the_same_result_computes_and_saves_the_newer_copy` | shown from disk · `lookup_x_eviction_of_another_result_shows_it_from_disk` |
| **Save**, answer after its transaction (its row was the one evicted) | RAM only (by `result_id`) · `save_x_eviction_of_the_same_result_is_ram_only` | saved · `save_x_eviction_of_another_result_is_saved` |
| **Save**, transaction after the eviction | the newer copy is saved · `save_x_eviction_of_the_same_key_before_its_transaction_saves_the_newer_copy`; no room: its own question · `save_x_eviction_of_the_same_key_then_no_room_is_its_own_question`; store: `a_save_running_since_before_an_eviction_saves_its_newer_copy`, `a_newer_copy_that_doesnt_fit_after_an_eviction_is_its_own_question` | saved |
| **Waiting result** (a newer copy of the key) | stays, asked; its Make room saves it · `waiting_x_eviction_of_its_keys_saved_row_keeps_the_replacement`; its `result_pending` in transit: still asked · `waiting_in_transit_x_eviction_of_its_key_is_still_asked`; store: `a_waiting_newer_copy_stays_when_its_old_saved_row_is_evicted` | stays, saved by its Make room · `waiting_x_another_waiting_ones_eviction_keeps_its_question_and_saves` |
| **Adoption** (Make room asked) | saves · `adoption_x_eviction_of_its_keys_saved_row_still_saves`; its acknowledgement after another Make room evicted the row it saved: RAM only (round 7) · `adoption_acknowledged_after_another_make_room_evicted_its_row_is_ram_only` | the plan changed: nothing removed, asked again · `adoption_x_another_adoptions_eviction_asks_again_with_the_new_plan` |

Plus: a copy saved after the question is never removed by it (asked again, the new plan takes the
oldest) · `a_newer_copy_saved_after_the_question_is_never_removed_by_it`; a result saved by Make room
and evicted later says RAM only · `adopted_then_evicted_says_ram_only`.

**Folder-row badge: `report`** (REPORT_ANALYTICS, grey like no_cache, from Debug › Show all Icons;
`chart3d` is the 3D scatter's own picture, `report` reads as analysis results). It shows after the
data cache's badge when the folder has saved results that reuse will use (reuse on, the folder has a
disk cache). The row tooltip and Folder details' cache line add "Cached analysis: 2 results, 3.0 MB".
Debug Icons' `report` row has a tooltip saying so.
- Where the counts come from: a listing sends each subfolder's (`results` on its entries, and the
  listed folder's own on its status; from the store's records only, like the other saved flags); a save
  sends its folder's count after it, an adoption those of its folder and the folders it took results
  from. Each carries the store's `[store_id, writes]`; FolderCache keeps the newest
  (`result_counts`, `analysis_cached`, `resultCountsChanged`); a Clear cached analysis zeroes them, and a
  listing or answer asked before it is ignored. Rendering reads memory only.
- Known limit: a folder whose data root is forgotten while HeLab runs keeps its last count in memory,
  hidden (no disk cache) until a listing says otherwise.

**Owned-path note:** the listing's field is added in `helab/io_ops/browse.py` (not `metadata.py`'s
`_saved_folders`), so a details scan's entries don't carry it; listings do. `helab/resources/icons.py`
is unchanged (the icon exists).

**Proposed doc edits** (in addition to those above):
- AGENTS.md › Caching, the saved-results paragraph: "Make room for a result removes the least recently
  shown other saved results only (never datasets, never a waiting result or a save running: a newer copy
  of an evicted result checks the budget in its own transaction); each save gets a new `result_id` and
  the plan names ids, so a copy saved after the question makes it ask again."
- AGENTS.md › UI (or `.ai/memory/results/folder-summary-indicators.md` and `folder-row-tooltip.md`): "A
  folder with saved analysis results that reuse will use shows REPORT after the data cache's badge; its
  tooltip and Folder details' cache line say 'Cached analysis: N results, X MB' (listing counts, memory
  only)."
- `.ai/memory/results/disk-cache-and-budgets.md`: Make room for results, as above.

**Checks:** full suite (`pytest -n 4 --reruns 5 --reruns-delay 1`): see the summary sent to CoCo.

## Review fixes, round 7 (Gauge on `a2c581f..ca7e4cd`)

1. **[P2] A delayed Make room acknowledgement after its row was evicted.** Adoption A commits, Make
   room B evicts A's row, then A's acknowledgement arrives: it was answered "saved" and its plot said
   "saved in disk cache". Its answer now also checks the row's `result_id` against the evicted ids
   (as `result_found` and `result_saved` do), so it says RAM only; a newer copy, with another id, is
   unaffected. Cell added to the table above
   (`adoption_acknowledged_after_another_make_room_evicted_its_row_is_ram_only`; fails before the fix).
2. **[P3] The REPORT badge on a Don't cache folder.** The helper refuses reuse there, so
   `FolderCache.analysis_cached` now gives None while the folder's own `no_cache` is set: no badge, no
   tooltip or Folder details line; it comes back when the flag is cleared (the flag's change repaints
   the row). Tested in `test_folder_cache_keeps_the_newest_measurement_and_drops_counts_with_a_clear`.
