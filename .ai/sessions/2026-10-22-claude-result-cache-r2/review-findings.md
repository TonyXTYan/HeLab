# Review findings: Gauge (Codex), `6906d96` against `c3d4b50`

No P0/P1 blocker and no demonstrated wrong scientific result. Fix the two P2s before landing, and
the two P3s too (both small), each with a regression test, alongside Follow-up 1. Reply to CoCo with
the fix commits.

1. **[P2] Ignore result events made stale by a Clear cached analysis.** `helab/utils/folder_cache.py:1971-1975`,
   `helab/views/plots/cached_results.py:153-157, 191-192, 235-241`. Result operations have no
   removal-time check like `_on_finishing_event`'s `_removed_after`. A clear updates only the shown
   result; pending `_lookups` and `_saves` stay valid. If the clear's `removed` arrives before a
   pre-clear lookup/save acknowledgement, the late event marks the plot DISK_CACHED again though its
   row was removed, and a pre-clear exact lookup skips computing after the clear. Reproduced by
   holding a real helper `result_found` / `result_saved`, running `clear_results`, then delivering
   the held event: store count 0, but `shown.policy` disk; the late exact lookup had 0 computations.
   The store's save guard works; this is the GUI event-ordering gap. Cover all/global, root and
   purge removals when invalidating pending results.
2. **[P2] Schedule the sweep for files retired by result saves.** `helab/io_ops/results.py:98-106`,
   `folder_cache.py:1971-1975`. Refused/over-budget saves and replacements retire result files, but
   none of their outcome events carries `next_deadline` and the result-event handler never schedules
   a sweep; without another cache-admin/dataset event they stay until a restart. Reproduced: a
   budget=1 refusal left one retired file and a non-null `CacheStore.next_deadline()`, while the
   `result_not_saved` event had no deadline. Add the typed deadline field, report it on every
   retiring outcome, schedule it in `FolderCache`.
3. **[P3] Keep retention status visible for a result reused from disk after clearing it.**
   `helab/analysis/results.py:230-236`. `_cached_removed` sets `RAM_ONLY`, but `describe`'s FROM_DISK
   branch ignores the policy, so the record never says "kept in RAM only" (the existing test clears
   only a freshly computed result). Keep the provenance and also report the current policy.
4. **[P3] Normalise malformed NPZ failures to `CodecError`.** `helab/analysis/result_codec.py:215-219`.
   A truncated ZIP header raises `zipfile.BadZipFile`; a valid NPY in place of NPZ raises `TypeError`
   at the context manager. Both escape the `CodecError` contract; `IOService`'s narrow catch then
   loses the returned guard and takes the generic error path, so the fallback computation can't
   replace the corrupt file and every reopen hits it until a clear.

Also: `git diff --check`: blank line at EOF in `helab/analysis/result_cache.py:127`.

Doc proposals (add to the handoff): extend AGENTS.md's mixed-version note with Gauge's
compatibility findings (an older HeLab opens the migrated store fine and its Clear all / sweep leave
results, but it counts result rows and not result files in usage, so its saves can exceed the shared
budget; an older sweep removes a retired result's row and leaves its file, which the new orphan sweep
collects later; an older nested-root re-key leaves result rows under the old key: misses, never
cross-folder reuse); add "clear a result reused from disk" to the manual checks.

Gauge's checks at `6906d96` (detached worktree): full suite 2541 passed, 2 skipped, 2 xfailed, no
RERUN; strict mypy (helab 158, tests 121) and pyright clean.

## Round 2: Gauge's delta review, `6906d96..b2f342e`

The four original fixes are accepted (Gauge's probes pass; codec errors normalised; sweep deadlines
scheduled). No P0/P1 or schema blocker; the `pending_results` migration was checked against stores
made by `c3d4b50` and `6906d96` code (both reopen, inventory, clear and sweep the migrated store).
Fix the two new P2s before landing, and the P3 (small), each with a regression test through the real
helper/GUI events, then reply to CoCo with the commits.

1. **[P2] Make room can report its successfully adopted result as discarded when another result of
   the same folder is evicted.** `helab/utils/folder_cache.py:2094-2100` (also `:2284-2291`;
   `helab/io_ops/admin.py:190`). `adopt_result` first sends `removed` for the evicted rows' folders;
   `removed()` treats every pending result of those folders as discarded, emitting
   `resultPendingAnswered(id, False)` and forgetting it. If the adopted result belongs to one of
   those folders (normal after changing a plot's settings), its `CachedRuns._waiting` entry is popped
   by that False, and the following True has nothing to update. Reproduced with real helpers: save a
   20,000-value random-array result; set the budget to current usage + 50,000; change Scale and run
   again; Make room with its actual `result_ids` plan: the store ends with the new result saved
   (1 row), but the plot's policy stays RAM and the status says discarded (answers [False, True] for
   one adoption). Distinguish evicting chosen saved rows from discarding pending saves, or exclude the
   pending id being adopted from the removal handling. (The store-only same-folder test passes because
   it doesn't exercise GUI events; the plot test raises the budget and removes no rows.)
2. **[P2] A delayed inventory snapshot drops pending results created since the request**, silently
   removing their Make room / Discard question. `folder_cache.py:2252-2257`. Unlike the dataset
   `pending_saves` merge just above it, the `pending_results` assignment keeps only ids in the
   inventory. Reproduced: hold a real empty inventory response (and its `done`), finish an
   over-budget plot so `result_pending` adds its question, release the old inventory:
   `pending_results` becomes `{}` while the store still holds the file; `CacheDialogs` closes the
   question and has nothing to ask until a fresh inventory or restart; `CachedRuns` keeps the waiting
   result with no resolution. Merge in pending additions/changes made since that inventory request
   (per-pending timestamps as appropriate), as the dataset merge does.
3. **[P3] A successful adoption leaves the full/pending warning on the plot.**
   `helab/views/plots/cached_results.py:175-179`, `helab/views/plots/instance.py:385-399`. The pending
   event adds "not saved yet: the disk cache is full (Make room or Discard)" to
   `_cache_status`/`status_label`; adoption only calls `_saved`. Reproduced without evictions
   (over-budget result, raise the budget, adopt: policy disk, row exists, status still says not saved
   yet). Clear that operation's pending warning when saved or discarded, keeping unrelated warnings.

Gauge's checks at `b2f342e`: full suite 2560 passed, 2 skipped, 2 xfailed, no RERUN; strict mypy
(helab 158, tests 122) and pyright clean; `git diff --check` clean.
