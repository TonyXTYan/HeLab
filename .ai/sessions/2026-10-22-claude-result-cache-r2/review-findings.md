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

## Round 3: Gauge, `b2f342e..81a9529`

The three round-2 fixes are accepted (probes pass). No P0/P1, no schema change, no wrong result.
Two **[P2]** eviction cases remain, opposite sides of one cause: **Make room's eviction invalidates
by folder, not by the saved results it removed.**

1. **Eviction skips invalidating a delayed lookup of the result actually evicted.**
   `helab/utils/folder_cache.py:2088-2090`: the `evicted=True` branch skips all `_removed_paths`
   tracking, not only pending-save cancellation, so a `result_found` captured before Make room
   removed that exact row is still accepted as a current exact disk result. Reproduced with real
   helpers: save Scale 1; hold another plot's `result_found` for Scale 1; run Scale 2 with a budget
   forcing Scale 1's eviction; adopt Scale 2 with Make room; deliver the held Scale 1 event: the store
   has Scale 2, but the delayed plot shows Scale 1 with policy disk and 0 computations.
2. **Make room still invalidates the folder's other pending saves in the store.**
   `helab/utils/cache_store.py:1716-1717` with `FolderCache.removed(evicted=True)`: every evicted row
   bumps its folder-wide results epoch, so other `pending_results` of that folder keep stale guards
   and their later Make room raises `SaveRejected("cleared")` and deletes their file and row, though
   the user only agreed to remove the named saved results. Reproduced (private temp store): save
   "old"; queue "pending-a" and "pending-b" under one folder (distinct lookup keys); adopt pending-a
   with Make room, evicting "old"; pending-b is still listed, but adopting it even with an 8 GiB budget
   fails "Cached analysis was cleared before saving completed" and deletes it. (Pre-existing store
   behaviour; the round-2 GUI fix exposes it.)

**CoCo: fix the cause, once, for both.** Invalidate an eviction by the **saved results it removed**
(their ids / lookup keys), not by the folder: the store's guard for a save or lookup checks whether
*its* key was evicted after it started (e.g. per-key eviction records, or the evicted keys in the
`removed` event and in the guard check), while Clear cached analysis, root clears and purges keep the
folder/root epochs. Then check the whole pending-result lifecycle as one table, each through real
helper and GUI events: {lookup, save, pending save, adoption} in flight × {Make room eviction of the
same key, of another key of the same folder, Clear cached analysis (all / root), purge, Discard}:
what the store keeps, what the plot shows, which question stays. Add tests for each cell that can
happen; reply to CoCo with the commits and the table.

Gauge's checks at `81a9529`: full suite 2563 passed, 2 skipped, 2 xfailed, no RERUN; strict mypy
(158 / 122) and pyright clean; `git diff --check` clean.

## Round 4: Gauge, `81a9529..de6825f`

Both round-3 cases fixed (probes pass). No P0/P1, no schema change in this delta, no wrong result.

1. **[P2] The store no longer stops an in-flight save from resurrecting the evicted key.**
   `helab/utils/cache_store.py:1718-1722` (guard checks at `:1579`, `start_result_job` /
   `_check_result_guard`). Eviction dropped the folder epoch bump without a persistent per-(folder,
   lookup) replacement, so a guard taken before the eviction still passes for the very key the user
   removed. `FolderCache._evicted` only hides the late GUI acknowledgement; it can't stop a helper (or
   another HeLab process) committing the row. Reproduced (private temp store): save key `old`; take
   guard G for a running save of `old`; queue/adopt `pending-a` with Make room so `old` is evicted;
   make the budget sufficient; `save_result(old, …, G)` returns saved and `find_result(old).found`.
   Add a **key-specific persisted epoch/sequence** (per folder and lookup), checked by save and by
   adoption, leaving other keys' guards alone. A computation restarted after the eviction takes a
   fresh guard; a save already running must not reuse its old one.
2. **[P3, table/test gap] A waiting key can also have a saved row**, so "Waiting × eviction of the
   same key" and "Adoption × eviction of the same key" are possible (`cache_store.py:1583-1592`): an
   over-budget replacement rolls back its upsert, keeping the existing `results` row, then inserts a
   `pending_results` row under the same (path, lookup); nothing prevents both. Probe: save
   `same-key` with enough budget; save it again with the budget at 1: `find_result` finds it and
   `pending_results` has it too. A run that bypasses reuse, or concurrent runs/processes, can produce
   that replacement; another key's Make room can then evict the saved row while its replacement waits
   or is adopted. ("Make room never evicts its own key" excludes only the adopting request's key.)
   Replace those two "impossible" cells with explicit semantics and tests, with the per-key guard.

Table audit (fold into the table): the lookup/save tests hold answers *after* the store
read/save completes, covering message order but not a save transaction that runs *after* the
eviction (finding 1 is that order). Discard is "impossible" only per request / for one local dialog
answer: with a saved row and a pending replacement of the same key, Discard can overlap a lookup of
the saved row, and two HeLab processes can adopt and discard one pending id at once (the store must
give one success and one "gone"): state the table's scope. "Adoption transaction first, clear
second" doesn't cover a held successful adoption acknowledgement delivered after the clear: test that
order too (no failure found there).

Gauge's checks at `de6825f`: full suite 2582 passed, 2 skipped, 2 xfailed, no RERUN; strict mypy
(158 / 123) and pyright clean; `git diff --check` clean.

## Round 5: Gauge, `de6825f..4c50d01`

The per-key store guard is accepted (a pre-eviction guard is refused; a sibling key's pending save
adopts; a fresh keyed guard saves). No P0/P1, no wrong result. Fix before landing:

1. **[P2] A late `result_pending` restores a permanently unresolved plot state after eviction
   already dropped that pending row.** `helab/utils/folder_cache.py:2005-2013, 2023-2026`;
   `helab/views/plots/cached_results.py:287-290`. `_results_evicted` remembers dropped ids in
   `_pending_gone`, but when their `result_pending` arrives later, `_on_result_event` only skips
   inserting it in `pending_results` and still forwards it to `CachedRuns`, which puts the result in
   `_waiting` ("not saved yet: the disk cache is full (Make room or Discard)") with no question and
   no answer to come, and keeps its arrays alive. Reproduced through real helpers: two Scale 1 runs
   look up before saving; save the first, lower the budget and send the second's replacement,
   holding its `result_pending`; Make room for Scale 2 evicts Scale 1 and drops that replacement;
   deliver the held message: store (1 saved, 0 waiting), `pending_results` `{}`, but the plot waits
   with that status. Turn a pending event for a known-gone id into a terminal `result_not_saved`
   before forwarding; add this message-in-transit variant to the table (the Waiting tests start with
   the question already open).

**Tony-facing choices (Gauge's judgement, CoCo agrees; do these):**
2. **Dropping a waiting replacement when Make room evicts its exact saved key** stays (consistent
   with the per-key guard), but **the Make room confirmation must say so**:
   `CacheDialogs.result_room_text` names only the saved results and their bytes; add the waiting
   replacements of those keys it will also discard (count / names). Don't rebase old guards.
3. **Per-key `folder_epochs` rows (`result-key:…`) grow without bound** (20 evictions of distinct
   keys → 20 rows, kept through all / root clears and the sweep; their bytes count in `_live()`, so
   budgeted). Compact them where a broader fence already covers them, never by age: in a global
   result clear, bump `gen_results`, then delete the per-key rows; in a root clear, bump the
   root-results epoch, then delete that root's per-key rows; a folder purge / clear likewise with the
   folder-results epoch. Write the lifetime rule in the handoff.
4. **Stale table cell and comment:** "Lookup × same-key eviction" says it may save with a fresh key
   epoch, but `_on_result_event:2001` keeps the pre-eviction guard, so the fallback computation's
   save is refused (a later, newly asked run can save); the comment "its guard holds" is stale.
   Describe the conservative RAM-only fallback (or reacquire a fresh guard for a newly authorised
   restart; never reuse the invalid one).

Gauge's checks at `4c50d01`: full suite 2590 passed, 2 skipped, 2 xfailed, no RERUN; strict mypy
(158 / 123) and pyright clean; `git diff --check` clean.

## Round 6: Gauge, `4c50d01..339ed5b`: review complete

**No findings above P3.** All round-5 fixes accepted: the held late `result_pending` ends terminal
(no question, no `_waiting`); tombstone compaction runs under the broader fence in the same
transaction for global, root and folder clears and an age purge (tombstones 3 → 0, the pre-clear guard
still refused, a fresh guard saves); dropping a waiting replacement of an evicted key is disclosed in
the room plan; the Lookup cell and comment are right.

**[P3, non-blocking] disclosure race:** `helab/utils/cache_store.py:1755-1757`,
`helab/views/CacheDialogs.py:118-119`. The plan now includes dropped pending ids and labels, but the
confirmation's identity and `expected_room` validation compare only saved `result_ids`, so a waiting
replacement that appears after the question was shown is discarded without the question saying so.
(Save old; queue new and get its plan, 0 waiting drops; queue an over-budget replacement of old; adopt
new with the original plan: succeeds and drops 1.) **CoCo: fix it (small):** include the expected
dropped pending ids in the plan's validation and the question's identity, so a changed plan asks again.

Gauge's checks at `339ed5b`: full suite 2594 passed, 2 skipped, 2 xfailed, no RERUN; strict mypy
(158 / 123) and pyright clean.

## Round 7 (Gauge, a2c581f..ca7e4cd, Follow-up 2)

No P0/P1. Suite 2601 passed, no RERUN; mypy/pyright clean. Per-key epoch removal matches Tony's policy.

1. [P2] A delayed successful adoption acknowledgement can mark an already evicted row as disk-cached
   (`helab/utils/folder_cache.py:2402-2407`, `helab/views/plots/cached_results.py:188-201`). The
   `result_saved` path checks `event.result_id` against `_evicted`; the `adopt_result` admin-result
   path checks only clears/purges (`_removed_after`). Adoption A commits, Make room B evicts A's row,
   then A's ack arrives: `resultPendingAnswered` sends saved=True with the evicted id; `CachedRuns`
   installs it after the eviction signal and the plot shows disk. Fix: include result_id eviction in
   `saved_now` (without invalidating a newer copy with another id); add "adoption ack after its row
   is evicted" to the lifecycle table (adopted_then_evicted tests only the other order).
2. [P3] The report badge shows on Don't cache folders although the helper refuses reuse
   (`folder_cache.py:2035-2041`, `result_cache_off` 1958-1969; `io_ops/results.py:38-43`):
   `analysis_cached` ignores the folder's `no_cache`. Hide it while no_cache is set (in-memory
   preference; the prefs-change repaint updates it).

## Round 8 (Gauge, ca7e4cd..81e6a2a)

REVIEW COMPLETE, no findings. Both round-7 fixes accepted (eviction check by row id, a newer copy of the same key stays disk-cached; badge hidden under no_cache). Suite 2602 passed, no RERUN; mypy/pyright clean; 3 probes passed.
