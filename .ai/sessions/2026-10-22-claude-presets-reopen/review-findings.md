# Review findings: Flint (Codex), `a74fd07` against `c3d4b50`

Request changes: four reproduced issues; 1 is the blocker. Fix all four with a regression test each
(Flint's probes are below in outline), alongside Follow-up 1. Reply to CoCo with the fix commits.

1. **[P1] `helab/views/plots/arrangement.py:107-114`: `FolderWait._in_ram` accepts pinned RAM for a
   known mismatched folder.** `FolderCache._mismatch` drops datasets but leaves tab pins until
   released (`folder_cache.py:1467-1485`). `FolderWait` scans pins without testing
   `cache.mismatched`, emits `found` and runs on data known not to match the folder. Probe:
   `cache.retain("existing-tab", dataset)`, `cache._mismatch(dataset.path, {"missing": [1]})`, then
   `FolderWait.look()` emits `found` with that dataset. Applying an arrangement while another tab pins
   old data bypasses the Review / Load as it is now protection. Guard the RAM path as the cached
   path already does, until a normal load resolves the mismatch.
2. **[P2] `arrangement.py:149-172` and `:119`: an `unverified=True` cached-read error becomes a
   permanent cache miss.** `_read_tried` stays true and nothing retries on `volumesVerified`, so a
   startup reopen on an external volume can race verification and wait for ever despite local
   cached data. `FolderExplorer._cached_event` / `_volumes_verified` handle this (as `read_cached`
   documents). Probe: send an unverified error to the wait's request, emit `cache.volumesVerified`:
   no cached read is resubmitted. Retry this transient failure through the local lane; disconnect on
   stop.
3. **[P2] `helab/views/plots/presets.py:512-514` / `:352-353`: applying a Live-off preset to the
   current folder leaves Live on.** `open_to_path` (which stops Live) is skipped when `selected_path`
   and `view_path` already match; `PresetFolder` just finishes for `live=False`. Probe (real window,
   offscreen): apply an empty-folder arrangement with `live=True`, wait for Live, apply `live=False`
   for the same folder: `explorer.live` stays active. Reconcile the existing Live with the saved
   choice explicitly.
4. **[P2] `arrangement.py:273`: a malformed `dock_state` aborts reopening/applying instead of being
   recovered.** The parser accepts any string; a valid JSON record with a non-ASCII `dock_state`
   reaches `encode("ascii")` and raises `UnicodeEncodeError` (confirmed with U+2603).
   `PlotReopen.restore` and `ArrangementPresets.apply` don't catch it around `open_arrangement`, so
   Apply aborts before `PresetFolder` is installed, losing the folder-load / Live phase. Validate and
   decode defensively, name the bad layout, keep compatible plots in fallback tab groups.

Flint's checks at `a74fd07` (detached worktree): full suite 2531 passed, 2 skipped, 2 xfailed,
1 RERUN (`tests/test_cache_first.py::test_a_folder_changed_within_its_mtime_tick_is_listed[cached]`,
`assert 1792659756000000000 is None`, `:841`, already in known-issues); strict mypy (helab, tests)
and pyright clean. Doc note: that RERUN stays in `roadmaps/known-issues.md` (CoCo handles).

## Round 2: Flint's delta review, `a74fd07..ffc2d4e`

All four original probes now pass. Request changes: one remaining data-safety blocker and two new
issues. Fix each with a regression test **through the real production event order** (not by
inserting state the order wouldn't give), then reply to CoCo with the commits.

1. **[P1] `helab/views/plots/arrangement.py:205-209`: `mismatchesChanged` wakes the waiter before
   the replacement dataset is published.** `FolderCache`'s real `loaded` handler calls
   `_matched(job.path)` (`folder_cache.py:2649`), which emits `mismatchesChanged` synchronously
   *before* installing the new dataset. `FolderWait` searches RAM at once, finds the old tab pin,
   emits `found` and stops; the later `datasetChanged` with the fresh data can't correct the plot.
   Reproduced through `cache._on_event`: pin shots (1,2,3), mark mismatched with shot 1 missing,
   start `FolderWait`, submit an `allow_missing` load, send `shot` events for (2,3), then `loaded`
   (fresh signature): the waiter got (1,2,3). The new regression test inserts the replacement before
   emitting `mismatchesChanged`, hiding the production order. Defer the lookup until publication, or
   rely on the following `datasetChanged`, so the stale pin can't win.
   **Same protection, related hole, `arrangement.py:175-179`:** a cached read already in flight is
   accepted without rechecking `cache.mismatched`. Reproduced: start the cached read, mark the
   folder mismatched, deliver `loaded` with the old cached dataset: `found` fires while the path is
   still in `cache.mismatched`. Guard result acceptance as well as starting a read / `_in_ram`.
2. **[P2] `helab/views/plots/presets.py:265-266`: changed-value marks bypass the strict validator**
   with `spec.coerce(wanted)`, which raises for incompatible values. A script preset with
   `bins="many"` is rejected and named by `apply_saved` / `check_plot`, but `PresetBar.apply` →
   `set_applied` → `update_marks` → `changes` raises `ValueError` from `int("many")`, and the bad
   preset stays the comparison baseline, so later edits raise again (confirmed offscreen with
   Counted). None, arrays and invalid numeric text carry the same risk. Compare only values
   `check_value` / `check_plot` accepted; invalid entries stay named in the note with no mark.
3. **[P2] `arrangement.py:392-395`: the Keep/Drop question is window-modal.** `NonModal` then
   `QMessageBox.open()` doesn't keep it: the box shown reports `WindowModality.WindowModal`, so it
   blocks the main window at startup (against the non-blocking reopen requirement). Confirmed through
   the real `PlotReopen._ask` (current tests replace `reopen.ask`). Use a non-modal show path and test
   the actual dialog's modality.

Flint's checks at `ffc2d4e`: full suite 2541 passed, 2 skipped, 2 xfailed, no RERUN; strict mypy
and pyright clean. Follow-up items 1–3 otherwise reviewed fine (mark/save flows, Replace/Add, kept
records).

## Round 3: Flint, `ffc2d4e..0098d8d`

The four round-2 probes now pass. One **[P1]** remains, in the same guard: `arrangement.py:69-71,
128-137, 149`. Stale-data rejection lives only in each `FolderWait`'s `_stale`, so a waiter created
**after** a mismatch was resolved has no history, while the old mismatched dataset is still pinned by
a tab. If the replacement dataset has since left RAM, the new waiter accepts the old pin and runs on
the wrong shots. Reproduced (real event order, offscreen): retain old (1,2,3) under `existing-tab`;
`cache._mismatch(path, missing=[1])`; `load_through_the_cache(cache, path, range(2, 4), "fresh")`
(real `shot` / `loaded` / `done` for `allow_missing` through `cache.service.resultReady`); mismatch
resolved, latest is fresh, `existing-tab` still pins old; evict the unpinned fresh dataset
(`cache._evict(target=0)`, behind `evict_to`); a **new** `FolderWait(cache, path).look()` emits
(1,2,3) instead of reading the fresh local cache. Happens after a background replacement load, or
when the tab showing the fresh data releases it and RAM pressure evicts it.

**CoCo: third round on this guard, so fix it at the root, not per path.** Don't keep "known bad" in
the waiter: decide from what `FolderCache` itself still holds as the folder's current data. One rule,
for example: a reopened plot takes only a dataset `FolderCache` still keeps in its own datasets for
that path (never a dataset that survives only as some tab's pin after the cache dropped it, which is
what `_mismatch` and `_folder_changed` do); else a local `cached` read; else wait. Check that rule
against every path a reopened or preset-opened plot takes data (initial look, `mismatchesChanged`,
`datasetChanged`, deliberate Rerun, an in-flight cached read, arrangement apply) and against a dropped
dataset for any reason (mismatch, folder changed, a clear), not only mismatch. If it needs a small
public query on `FolderCache` (e.g. "is this dataset still the cache's own for this path"), add it,
minimal, and name it in the handoff (the Result Cache floor also edits `folder_cache.py`; it merges
after you). Test each order through the real events, including this one, then reply to CoCo.

## Round 4: Flint, `0098d8d..222bcdb`

The round-3 stale-pin probe passes; the `current_dataset` / `latest_dataset` rule excludes pins. A
real offscreen `FolderExplorer` probe passes too: a cached read cancelled *while* mismatched, then
Review / Load as it is now (no old dataset stored or shown, the replacement has `allow_missing=True`,
`cache_base=False`, shot 9 shows, the mismatch clears).

**[P1] one ordering hole left in the shared guard, `helab/utils/folder_cache.py:2659-2661`.** It
checks *current* membership in `mismatched`, so a `cached` job started **before** the mismatch that
lands **after** a replacement load cleared it is admitted and stored: `_mismatch` neither cancels nor
fences it, and `FolderWait` then trusts it because the cache holds it. Reproduced with a real
`FolderExplorer` and producer events: (1) a tab's cached read of old shot 1 and its source check
start; (2) a status check reports the mismatch (`cache._mismatch`), the source check errors, the
cached read stays in flight; (3) `browser.load_as_it_is_now`: the replacement's `scan_summary`, shot
9, `loaded(fresh)`, `done`: signature fresh, mismatch cleared, tab shows shot 9; (4) the original
cached read then sends shot 1, `loaded(old, verified=False)`, `done`: admitted, old data back in
`cache.datasets`; (5) a queued check with an older tab signature touches that entry, cancelled on
navigation; the fresh pin released and `cache.evict_to(24)`: fresh evicted, old survives while the
snapshot's signature is still fresh; (6) a new `FolderWait.look` emits shot 1 through the
`latest_dataset` fallback.

**CoCo:** this race predates the branch (before 51b8a87 a cached read landing while mismatched was
stored too); fix it where the invariant lives. Fence the folder's jobs when a mismatch is recorded
(e.g. `_mismatch` moves the folder's epoch, or cancels its in-flight `cached` jobs), so a job from
before the mismatch can never be admitted afterwards, whatever lands in between; then drop the
`in self.mismatched` condition if the fence makes it redundant. Keep legitimate recovery working: a
new `allow_missing` load and cached reads submitted after resolution, and a tab's own loads at the
new epoch. Test Flint's order end to end, plus a cached read submitted after resolution (accepted).
Name the change in the handoff (`folder_cache.py`, for the Result Cache merge).

Flint's checks at `222bcdb`: full suite 2549 passed, 2 skipped, 2 xfailed, no RERUN; strict mypy
(156 / 117) and pyright clean.

## Round 5: Flint, `222bcdb..760a69f`

The late cached-job probe passes: the narrow cached-job fence works.

**[P1] The mismatch fence is incomplete for other work started before the mismatch.**
`helab/utils/folder_cache.py:1488-1493` cancels only `cached` jobs and deliveries, and the `loaded`
handling at `:2653-2658` clears `mismatched` for **every** load (Live and held saves included)
*before* the epoch / signature / base validation; `_mismatch` doesn't move the folder's epoch or
fence load / Live jobs. Each family tested through the real producer-event handler (helpers paused,
no source I/O): start the old job; a *different* details helper sends `cache_mismatch(missing=[1])`,
held before its final status (the mismatch known before the replacement's signature is published);
then deliver the earlier job's `loaded`:
- **ordinary load**: mismatch gone, `cache.latest_dataset` old, a new `FolderWait` emits (1,);
- **memory_check** (payload has `memory_check`): its old `memory_shots=[1]` clears the mismatch,
  rebuilds and stores the old data, a new waiter emits (1,);
- **Live check** (separate `("live", path)` job, `live=True`): same;
- **save_held** (`save_memory=True`, `save=True`, held arrays): same;
- **cache_base check**: its `cached` job is cancelled, but its older `loaded(memory_shots=[1],
  base_signature=old)` calls `_matched` first, then fails at `:2689` (no cached base): no dataset
  **and no mismatch warning**: a failed old check must not resolve the mismatch.
- **queued RAM fast path**: with a checked old dataset, `cache.submit(fast-tab, …, load,
  signature=old)` queues `_deliver(loaded)` instead of a helper; recording the mismatch before the
  zero-timer runs leaves that load delivery live, so it still hands the rejected dataset to the tab
  (FolderWait rejects it, since the cache no longer holds it, but a tab gets it back).

**CoCo: these races predate the branch** (tabs hit them too); fix them once, contained, here, since
reopened plots depend on the invariant and you have the context:
1. `_mismatch` fences every generation of the folder's work, not one job kind: e.g. move the
   folder's epoch (so `job.epoch != self._epochs[path]` cancels loads, Live checks, memory checks,
   held saves and cached reads started before it) and mark pending deliveries of the folder
   cancelled (load as well as cached), as `_invalidate_data` does for jobs and deliveries; but keep
   the mismatch record, its window and Review / Retry, and don't treat it as a cache clear.
2. Only an **accepted** post-fence load clears the mismatch, **after** epoch / signature / base
   validation (move `_matched` after it; a failed or cancelled load leaves the mismatch).
3. Recovery still works: Load as it is now (`allow_missing`), the tab's own loads and Live after the
   mismatch, cached reads asked after resolution.
4. Tests through the real producer events, one per family above plus the queued RAM delivery, and
   the recovery paths; show first (for `known-issues.md`) that the ordinary-load case fails on
   `c3d4b50` too.
Name the change in the handoff (net diff of `folder_cache.py` vs `c3d4b50`). If this needs more than
a contained change in `_mismatch`, the `loaded` branch and the delivery path, stop and tell CoCo:
it then becomes its own floor.

Flint's checks at `760a69f`: full suite 2551 passed, 2 skipped, 2 xfailed, no RERUN; strict mypy
(156 / 118) and pyright clean.

## Round 6: Flint, `760a69f..2c7c2dc`: review complete

**Nothing above P3.** All six family probes pass (ordinary load, cache_base check, memory_check, Live
`loaded`, save_held, queued RAM delivery); old results neither republish cache-held data nor clear the
mismatch; queued loads are cancelled, not delivered. Side effects judged acceptable: a pre-mismatch
Live result is refused and Live halts "Cancelled" with the mismatch kept (verified recovery with real
test files: stop Live → Load as it is now → `allow_missing`, no old base → [2,3] → mismatch cleared →
Live starts again); a finishing load's late `cache_saved` / `done` is ignored for the badge, its save
and quit bookkeeping completes, and the next valid load restores the badge.

P3 notes:
1. **Do now (small):** `folder_cache.py:2667` checks the epoch only for `loaded`; a pre-mismatch
   `live_unchanged` still reaches `explorer_live.py:484` and schedules another check instead of
   stopping (no data escapes: the next check halts "Live needs the folder's loaded data"). Gate
   `live_unchanged` by the same epoch check so it ends cancelled too, with a test through the real
   Live helper's events; then the handoff's "a Live check in flight ends cancelled" is exact.
2. **Note only:** stop Live → Review recovery needs Qt's model update between the two actions (one
   stack: no replacement on the first call). Not a blocker; list it in the handoff for a later
   test/API cleanup, and add "stop Live → Review / Load as it is now → start Live again" to the
   on-screen checks.

Flint's checks at `2c7c2dc`: full suite 2560 passed, 2 skipped, 2 xfailed, no RERUN; strict mypy
(156 / 119) and pyright clean.

## Round 7 (Flint, 5923fe7..9a338fd, Follow-up 2: presets in the store)

Suite 2575 passed, no RERUN; mypy/pyright clean. Three findings, each reproduced by a probe.

1. [P1] Saving before the first preset read can overwrite an existing preset without the Replace
   question (`helab/views/plots/presets.py:388`, `helab/utils/folder_cache.py:1197`): the UI checks
   only the still-empty RAM names and `set_presets` submits a disk write while `presets_read` is
   false. Keep changes pending (RAM only) until a store answer establishes the names; an unknown or
   unreadable name list never authorizes replacing.
2. [P2] An older read snapshot can remove a committed preset from RAM (`folder_cache.py:1242`):
   read submitted while a write is pending; the write lands first, then the older empty read's
   pruning (by submission time > set_at) deletes p from RAM though it is on disk. Submission time
   can't order a snapshot against committed writes.
3. [P2] Unknown/unreadable presets are described as empty (`presets.py:587`,
   `helab/views/PresetsInspector.py:224`): with `presets_read=false` (initial or failed read) the
   menu shows "No presets saved" and the inspector "(none saved)". Claim empty only after a
   successful read.

## Round 8 (Flint, 9a338fd..393d2af)

Round-7 findings fixed in their scenarios. Suite 2583 passed, no RERUN; mypy/pyright clean. Two P2s in
the recreated-store path, each reproduced with a store recreated at the same test path:

1. [P2] A late acknowledgement from the retired store marks a change saved in the replacement store
   (`helab/utils/folder_cache.py:1262-1266`, `:1270-1275`): the held A write answer, delivered after
   B's read, clears p from `presets_unsaved` before checking store identity and makes A current
   again; B's table is empty, `quit_saves()` is `[]`. A retired store's answer must neither
   acknowledge a save nor make the old store current.
2. [P2] Reconciling with a recreated store keeps the previous store's same-name value
   (`folder_cache.py:1273`, `:1283-1284`): only names absent from B are reset, and
   `_remember_preset` compares `set_at` across unrelated stores (A p="old" set_at=100, B
   p="replacement" set_at=10: RAM keeps "old"). On identity change drop the previous store's saved
   rows, keep this session's unsaved changes, then merge B.

## Round 9 (Flint, 393d2af..3ba07eb)

Round-8 probes pass. Suite 2586 passed, no RERUN; mypy/pyright clean. Two P2s, reproduced with real
helper output and a store recreated at the same path:

1. [P2] Interleaved retired/current write replies can leave quit waiting forever with no jobs left
   (`helab/utils/folder_cache.py:1267-1268`, `:1285`, `:1316`): A's write held; store recreated as
   B; p saved to B; A's presets event, then B's, then each job's admin_result/done. A skips its
   rewrite because B is still writing; B skips clearing `presets_unsaved` because A is still
   writing; neither done handler settles it. B holds p="second", `_preset_jobs` empty, yet
   `quit_saves()==["Presets"]` and nothing is left to time out.
2. [P2] A replacement store's failed read inherits the previous store's successful-read flag
   (`folder_cache.py:1272-1281`): on A→B `presets_read` stays true, so B's error ("no such column:
   kind") still shows "(none saved)" and lets `set_presets` bypass PRESETS_WAIT_READ. Reset name
   knowledge on identity change until that store supplies rows.

## Round 10 (Flint, 3ba07eb..4fc315b)

Round-9 findings fixed; the rule held in all 1680 commit/delivery/end orders of three writes and all
720 success/failure orders during quit. Suite 2592 passed, no RERUN; mypy/pyright clean. One P2:

1. [P2] Quit can complete before an already requested read retry is queued
   (`helab/utils/folder_cache.py:1356`, also `:1328`, `:1358-1360`): p saved before names are known,
   `read_presets` asked again (`_presets_again`), quit, first read fails: p is marked not saved and
   `quitSavesChanged` fires while `quit_saves` is briefly empty, so `QuitSaveDialog` accepts; only
   then does `_preset_job_ended` queue the retry (p back to PRESETS_WAIT_READ, `quit_saves()==["Presets"]`).
   The window may quit and stop that retry, losing p. Schedule the requested continuation before
   publishing a quit-ready state (including the earlier presets-error notification).

## Round 11 (Flint, 4fc315b..3bb153a)

Round-10 orders pass. Suite 2594 passed, no RERUN; mypy/pyright clean. One P2:

1. [P2] Another job's failure can let quit accept while the replacement-store read retry is already
   running (`helab/utils/folder_cache.py:1336`, called at `:1328` and `:1357`): `_names_unread`
   protects only `_presets_again`, which is false once the retry is queued. An older write job
   ending with a helper error, or answering with a B read error, marks p "not saved" and notifies
   quit with `[]`; the dialog accepts while the retry, which would save p, is still in
   `_preset_jobs`.

## Round 12 (Flint, 3bb153a..5a99168)

REVIEW COMPLETE: no blocker, nothing above P3. The structural quit rule holds across every notification and failure path reviewed (53-case enumeration instrumented at each notification; queue refusals; done/error/cancelled ends; both round-11 orders). Suite 2597 passed, no RERUN; mypy/pyright clean.
