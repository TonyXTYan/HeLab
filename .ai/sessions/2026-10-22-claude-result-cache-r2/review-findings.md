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
