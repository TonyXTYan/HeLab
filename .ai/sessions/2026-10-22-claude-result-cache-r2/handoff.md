# Result cache R2: handoff (Cellar, 2026-10-22)

Branch `agent/result-cache-r2` from `c3d4b50`; commits `c31ac10` (schema, reported to CoCo),
`ef486d3` (back end), `bcdc12d` (plots), `3e5a934` (Settings), plus this session folder. Measurements
and evidence: [notes.md](notes.md).

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

1. **Budget refusal, no pending save.** A result that doesn't fit isn't saved (its file retired at
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
reopened plot's first run goes through `AnalysisInstance.run()` → `_submit(..., one_off=True)`, which
looks itself up; an exact match shows without computing. A Qt-free key for other uses:
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
