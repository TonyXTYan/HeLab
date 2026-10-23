# Disk-cached results R2 (Worker brief)

Floor "Result Cache", branch `agent/result-cache-r2` from `c3d4b50` (`dev/v0.0.6`, 2026-10-22).
Session folder: `.ai/sessions/2026-10-22-claude-result-cache-r2/` (this brief is `brief.md`; write
`notes.md` and `handoff.md` here). Approved by Tony (Chat, 2026-10-22). A parallel floor, "Presets
Reopen" (`agent/presets-reopen`), works on parameter presets and reopening plots at start; see
Overlap.

Start by reading `AGENTS.md` (Caching, Data roots, Responsive filesystem I/O, Script system,
DLD analyses' Hooks), `roadmaps/agent-workflow.md`, `roadmaps/result-caching.md` (the one home
for result rules: follow its Rules 1–8), `roadmaps/cache-storage-and-settings.md`, then
`helab/analysis/results.py` (`AnalysisResult.reuse_key`, `RamResults`), `helab/scripts/base.py`,
`helab/views/plots/instance.py` (`_submit`, `_finished`, `reload`), `helab/utils/cache_store.py`
(`SCHEMA`, `_migrate`, save guards, epochs, retiring files), `helab/io_ops/admin.py`,
`helab/io_ops/stores.py`, `helab/io_ops/events.py`, `helab/utils/folder_cache.py`
(`store_options`, `cache_admin`, `removed`) and `helab/views/CacheTab.py`.

> **Updated with Tony's answers (Chat, 2026-10-22):** no separate result budget (saved results
> count toward the disk cache budget, with a warning per save over 50 MB); the costly scripts opt
> in, the list proposed from measured run times; separate Clear cached data and Clear cached
> analysis actions in Settings → Data roots and the Cache tab. Items 2 and 5 below say how.

## Objective

Stage R2 of [result caching](../../../roadmaps/result-caching.md), about a day or two of work:
one-off results saved to disk and reused on an exact `reuse_key` match after a restart. The main
gain is Correlations and the bootstraps (Release time, the fits' bootstraps).

1. **Store schema first.** Design the result tables (and result data files, beside the dataset
   files, retired never deleted at once like them) in `store-v3`, added to older stores by
   `cache_store._migrate` (never only in `SCHEMA`; read-only stores without them read as empty).
   Results are keyed below their folder's `root://` key; a folder without a disk cache (no data
   root, pending duplicate, unsupported mount, volume unverified) keeps results in RAM only.
   **Commit the schema and its migration (with tests) as your first commit and tell CoCo its
   hash** (`maestri ask "CoCo" …`): cache-only browsing will branch from it later, so change it
   afterwards only with a reason in the handoff.
2. **Script capability.** `cache_supported` (Rule 4) declared by the script, default off. A
   cached result must be read back **without running code from the file**: no pickle. Propose
   the contract (e.g. the script turns its result data into NumPy arrays plus JSON values and
   back, or a declared plain shape the runner can save) in `helab/scripts/base.py`, and turn it on
   for the costly plots (Tony, 2026-10-22): Correlations, and plots that bootstrap or take long to
   compute (Release time, Velocity distributions and the like). **Propose the list from measured
   run times** (a table in the handoff: plot, typical settings, data size, cold run time, cached
   reuse time); leave quick plots off. The drawing still goes through `draw`/`update` as now.
3. **Save and reuse.** After a completed one-off run of a `cache_supported` script (never a Live
   rerun, never per shot: Rule 7; R4's Auto-update cache is not in scope), a helper on the local
   lane saves it with a save guard taken when the job started (per-kind generation, the folder's
   epoch and the root's `root-clear://` epoch), so a clear can't be undone by a save already
   running. Before a run, the plot asks the local lane for an exact `reuse_key` match (Rule 5:
   dataset snapshot and fingerprints, script version or file hash, effective parameters, shot
   selection, constants, `found["reuse"]`, mask; add the execution environment the roadmap names
   if `reuse_key` lacks it, and say what you added); a match shows at once, recorded as "from
   disk cache, computed <date>" in the dock's record, and the run is skipped. The GUI never
   opens the store; reads answer found / missing / error, and an error is never "nothing saved".
   Cached-result reads never wait on foreground or background source I/O.
4. **Outdated marker.** A cached result of the same plot, folder and parameters whose script
   version/hash or dataset no longer matches may show at once, marked outdated (amber, one line,
   `AMBER`), while the permitted rerun runs, and is replaced when it finishes (Rule 5). A result
   that never matched stays viewable with its original identity in the record.
5. **Budget (Tony, 2026-10-22): no separate result budget.** Saved results count toward the
   existing disk cache budget (`store_options()["budget"]`, 8 GiB default, `budget_set_at`), with
   its 80 % rules: they add to the store's live usage (`usage`, `usage_seq`), so the 80 % pause of
   automatic loads and `diskNearlyFull` see them, and a result save checks the budget in its save
   transaction like a dataset save. A result save that doesn't fit isn't made and the plot says so
   with a pointer to Settings → Cache (or use the dataset cache's pending-save flow if it fits
   naturally; say which). **Warn each time a saved result is larger than 50 MB**: once per save,
   naming the plot and the size (non-modal: a notice / status-bar line and the log; propose the
   wording). Nothing is removed without the user asking (Rule 6).
6. **Clearing (Tony, 2026-10-22): two separate actions**, "Clear cached data" (datasets, as
   today) and "Clear cached analysis" (saved results only), each in **Settings → Data roots**
   (button and row menu, per root: `DataRootsTab`, beside the existing Clear cached data…) and in
   the **Cache tab** (`CacheTab`: results shown in the inventory with their size, Clear cached
   analysis, purge by age if it falls out naturally). A root's Clear cached data **leaves its
   saved results**; Clear cached analysis removes only results; Clear all of the dataset cache
   leaves them too. Same rules as the existing clears: every action asks first
   (`CacheTab.confirm`), an epoch per root and kind so a running save can't bring results back,
   `removed` events (a new kind) that reset exactly the RAM state they name, through
   `FolderCache.cache_admin`.
7. **RAM budget.** A result read from disk counts toward the plot RAM budget like any other
   result (`RamBudget`, `plot_buffers`).

Not in scope: R4 (Auto-update cache during Live) and Export, which follow on this floor or a short
one of its own; R5; showing cached results in plots reopened at start (the Presets Reopen floor
builds reopening; leave a call it can use: "find a cached result for this plot's run").

## Overlap with the Presets Reopen floor

Both floors touch the plot dock. Split:

- **Yours**: in `helab/views/plots/instance.py`, the run path (`_submit`, `_finished`, `reload`
  and its helpers `_in_ram`, `_read_disk_cache`, `_end_disk_read`, `_reload_event`,
  `_reload_from`, `_reload_failed`); in `helab/views/plots/workspace.py`, `set_plot_result`,
  `update_plot_source`, `_wrap_plot` and `_update_plot_source_label` (the record and outdated line).
- **Theirs**: `script_tree.py`, `settings_panel.py`, `dock.py`, the rest of `workspace.py`, and
  in `instance.py` construction, `start`, `_open_settings`, `values`, `backend`, `live_values`,
  `close`. If you must change one, keep it minimal and name it in the handoff.
- Prefer new modules and small hooks in shared files. `settings_defaults.py`: both floors append
  rows; keep yours together. Whichever lands second syncs.

## Owned paths

`helab/analysis/results.py` and new `helab/analysis/` modules for result caching;
`helab/scripts/base.py` (the capability and save/restore contract) and the `cache_supported`
opt-ins with their round-trip in `helab/scripts/dld/` and `helab/scripts/standard/`;
`helab/utils/cache_store.py`; `helab/io_ops/` (a new results module, `admin.py`, `events.py`,
`stores.py`), `helab/io_helper.py` dispatch; `helab/utils/folder_cache.py` and
`helab/utils/io_service.py` (local-lane request kinds, `store_options`, inventory, `removed`);
`helab/views/CacheTab.py`; `helab/views/DataRootsTab.py` (Clear cached analysis); your parts of `instance.py`/`workspace.py` above;
`helab/utils/settings_defaults.py` (new rows); new test files and minimal edits to existing
cache/plot tests. Don't touch: the Presets Reopen floor's parts above, `parameter_tree.py`,
`HelabMainWindow.py` beyond wiring a signal if unavoidable, `roadmaps/`, `AGENTS.md`,
`.ai/MANUAL_TODO.md`, `.ai/memory/`, `requirements*`.

## Checks

From the floor root, after `source venv/bin/activate && source .ai/local/floor-env.sh`:
`pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest` (report every RERUN with
its reason), `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`. Tests to add:
migration of an older store-v3 (and a read-only one); save → new process → exact-match reuse
per opted-in script (the restored result draws the same); each part of the key changing (a shot's
fingerprint, the script hash, a parameter, a constant, the mask) gives no reuse and, where it
applies, the outdated marker; a clear or root clear racing a running save (the guard wins);
results counted in the disk budget's usage (the 80 % pause sees them), budget refusal, the
50 MB warning once per save, Clear cached data leaving results and Clear cached analysis leaving
datasets (root and Cache tab, each asks first, epoch against a running save); a RAM-only folder writes nothing;
no source I/O and no GUI store open (`helab/` never opens the store outside helpers). Timing
evidence: the measured run-time table behind the opt-in list. Don't launch the HeLab GUI.

## Handoff

Commit as you go on `agent/result-cache-r2` (subject + body with validation); the schema commit
first, reported to CoCo. Keep `maestri floor status` current (start, milestones, `--state blocked`
when you need Tony, `--state review` when ready). When done: `handoff.md` with the schema, the
script contract, the decisions you took and those left for Tony (the opt-in list and its
timings, pending-save or refusal, wording of the 50 MB warning and the two clear actions), what Tony should check on screen, proposed edits to `AGENTS.md`
(Caching, Script system), `roadmaps/result-caching.md` (R2 done, storage format decided),
`roadmaps/cache-storage-and-settings.md`, `roadmaps/_readme.md` and `.ai/MANUAL_TODO.md`; push
the branch once to `TonyXTYan/HeLab`, watch its CI (`gh run watch`) and report every RERUN by
test and OS. Then `--state review` and `maestri ask "CoCo" "<handoff summary>"`. Ask CoCo
(`maestri ask "CoCo" …`) when blocked or unsure of scope.

## Follow-up 1 (Tony, Chat, 2026-10-22, after the handoff)

A Codex Reviewer (Gauge) is reviewing `6906d96` on this floor at the same time, in its own detached
worktree under `.ai/temp/review-results` (don't touch it). Its findings come to you through CoCo;
fold them in with these changes. Commit as you go; **don't push until CoCo says the review findings
are in too**. Landing order (Tony): Presets Reopen lands first, then you merge `dev/v0.0.6` into
this branch, resolve the two import conflicts (`instance.py`, `tests/test_headless_imports.py`) and
fix the seam CoCo found: once merged, `AnalysisInstance.run_reopened` calls `self._submit(view)`
without `one_off=True`, so reopened and preset-applied plots neither look up nor save results;
make it a one-off run and test that a reopened plot shows an exact cached match without computing.
CoCo tells you when to merge.

1. **A result that doesn't fit the disk budget: a popup with Discard or Make room**, replacing
   decision 1: the dataset cache's pending-save flow (`CacheDialogs`, `pending_saves`, `adopt` /
   `discard`, one question at a time, also restored at startup if that falls out naturally), with
   the result's plot, folder and size in the question. Same 80 % approval rule as datasets if it
   applies naturally; say what you chose.
2. **Show when result reuse is on.** Tony: "an indicator when result reuse is on (perhaps the
   folder explorer's row status icon and somewhere else in case the explorer is folded, so maybe
   the plot window should show indication too)". CoCo's reading, to confirm with Tony:
   - a **setting to turn reuse off** (Settings → Cache, default on; off: no lookups and no saves);
   - the **folder row** shows a small badge when the folder has saved analysis results that reuse
     will use (beside the status icon, like ANCHOR / no_cache; from the listing's per-subfolder
     flags, memory only during rendering, never a store read), with a tooltip line ("Cached
     analysis: N results, X MB"); Folder details' cache line says the same;
   - the **plot dock** shows it too: an icon or short mark on the source line when the shown result
     came from the disk cache or will be saved (reuse on for this plot), wording to propose.
   Start with the setting and the plot mark; do the row badge after CoCo confirms the reading.
3. Decisions 2–7 (Don't cache blocks result saves, wording, 50 MiB, purge by `last_used`, opt-in
   Correlations + Release time, which runs, kept plot after a clear): Tony is fine with them.

Owned paths add `helab/views/CacheDialogs.py`, `helab/models/SnapshotFileSystemModel.py` (the badge),
`helab/io_ops/browse.py` (the listing's flag), `helab/views/FolderDetailsPanel.py` (its cache line)
and `helab/views/SettingsDialog.py` (the reuse setting only).

## Follow-up 2 (Tony, Chat, 2026-10-22)

Tony: keep Make room (no "doesn't fit" fallback), and:

1. **Folder-row badge: yes**, as Follow-up 1 item 2 read it. Use one of the icons Tony already
   chose, in Debug › Show all Icons (`StatusIcons.STATUS_ICONS_EXTRA_NAME`, `helab/resources/icons.py`),
   rather than a new one: `report` (`ICON_REPORT`, REPORT_ANALYTICS) and `chart3d` are there and
   unused so far; CoCo suggests `report`. Pick, say why, and add its row's description in
   `DebugIconsWindow.py` if that window describes where each is used.
2. **Make room removes only old saved results** (Tony: "make room only should remove very old saved
   results so any newer copy saving in cache is fine"). Make room evicts the oldest saved results
   (by `last_used`, as datasets do) and never drops or fences a newer copy of the same result that
   is waiting or being saved: that copy goes through the budget check in its own save transaction
   like any save (and may become its own question). The user's clears (Clear cached analysis…,
   Clear all, a root's Clear cached data…) keep fencing running saves as now. Drop the
   confirmation's disclosure about waiting copies. Say whether Make room should also skip results
   used this session or by a shown plot.
3. The `run_reopened` seam and the merge are unchanged: wait for CoCo's word to merge. Presets
   Reopen will also add a presets table to `cache_store.py`, a presets action in `io_ops/admin.py`
   and a hook in `CacheTab.py` (its preset inspector), so expect conflicts there at the merge.

Then: commit, tell CoCo; Gauge reviews the delta before you push once.

Owned paths add `helab/views/DebugIconsWindow.py` (the badge's description only).
