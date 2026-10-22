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
