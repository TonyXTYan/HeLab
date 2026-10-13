# HeLab Roadmap

The product overview, priority list and index of the feature plans in this folder.
Horizons describe sequencing, not promised dates. Feature scope and implementation
details remain drafts until resolved during design.

Manual work lives in [.ai/MANUAL_TODO.md](../.ai/MANUAL_TODO.md); review history and
validation evidence live in `.ai/sessions/`; settled decisions live in `.ai/memory/results/`.

How to use it:

- Add new items under the right heading with the date added (YYYY-MM-DD).
- When an item is done, tick it and add the commit hash, then move ticked items
  to **Done** at the next tidy-up.
- Keep each item to one or two lines; link substantial features to a document
  in this folder. Keep priority/completion here rather than duplicating task lists.

## Now: v0.0.5a folder browser

- [x] Cache rebuild: SQLite records + compressed dataset files (old cache dropped),
  remove the old folder browser, editable disk and RAM budgets, large-folder warning,
  per-folder don't-cache/don't-auto-load flags, cache-folder move, rebuilt Settings →
  Cache tab. Eleven sessions S1–S11
  ([plan](cache-storage-and-settings.md#sessions)) (2026-10-10; done 2026-10-11,
  `fe5a5b7`…`eafcf4b`; native checks in [MANUAL_TODO](../.ai/MANUAL_TODO.md)).

- [x] App version and build info: package version `0.0.5a1`, embedded build provenance,
  Help → About, and explicit CI tagging plus draft releases on new versions merged
  to `main` ([implementation](app-versioning.md#implemented-workflow-authoritative))
  (2026-10-12; release/native checks in [MANUAL_TODO](../.ai/MANUAL_TODO.md)).

- [ ] Release repos: develop and release on `TonyXTYan/HeLab`; fast-forward
  `HeBECANU/HeLab` `main` only for lab-ready versions, which drafts the same
  release there; stop pushing dev branches to `HeBECANU`. Proposed, Tony to
  confirm ([plan](app-updates.md#release-repos-proposed-2026-10-13-tony-to-confirm)) (2026-10-13).

- [ ] Build size: ship one copy of the app per asset with symlinks kept (macOS
  artifact 2152 MiB, `HeLab.app` alone zips to 276 MB), then exclude unused
  packages (pyarrow, mypy), replace pytablericons/pygame, and decide on
  QtWebEngine ([plan](build-size.md)) (2026-10-13). Step 1 (macOS zip of
  `HeLab.app` only, symlinks kept) done 2026-10-13; CI result to check.

- [ ] Finish the status-message audit: verify load-phase labels for `merged`/
  `updated` sources ([notes](../.ai/sessions/2026-10-08-codex-roadmap-review/notes.md#status-messages)) (2026-10-08).

- [x] Folder details panel (replaces the left-bottom placeholder and the plot
  area's loading text), shorter status bar with its running helpers listed in
  the tooltip, load elapsed time and time left (2026-10-10, `3af4fea`).

## Known issues

- [x] Resize repaint freeze: removed main-window repaint suppression; pytest covers
  painting and scan cancellation ([fix](../.ai/sessions/2026-10-11-codex-resize-during-scan/notes.md#implementation)) (2026-10-11; native check in [MANUAL_TODO](../.ai/MANUAL_TODO.md)).

- [x] Disk-cache eviction can drop scan-failure history and other records to make room
  for data, until the cache rebuild (S5/S6). Fixed: records are never removed to make room
  (`fd4e020`, `ef4c0ca`). The contention part (reads silently
  returning "nothing saved", so an automatic scan could run on a blocked folder) was
  fixed in S1 ([audit](../.ai/sessions/2026-10-10-claude-cache-audit/notes.md#storage-findings-ranked)) (2026-10-10).
- [x] Settings → Cache: parameter edits never apply, Clear blocks the GUI and
  leaves badges stale ([audit](../.ai/sessions/2026-10-10-claude-cache-audit/notes.md#settings--cache-tab-helabviewssettingsdialogpy)) (2026-10-10).
  Fixed by the rebuilt Cache tab (`52201ca`).

- [ ] Folder status icons vanish soon after startup: saved statuses show, then most
  disappear; only folders checked again get theirs back (seen by Tony 2026-10-13, no
  screenshot or log). Ruled out: changed folder identities (all 133 saved summaries
  match) and removals at startup. Suspect: a parent's derived status recalculated
  from unchecked subfolders and saved blank. It happened with caches saved before
  the PR #5 fixes and went away after Clear all. Dropped or cleared statuses now
  log their reason at DEBUG; if it recurs, run
  `python -m helab 2>&1 | tee .ai/temp/helab-run.log` (2026-10-13).
- [ ] Folders with over 100,000 entries record a scan failure.
- [ ] Quitting cancels cache writes still running in the background (a finished
  load's `disk_cache_pending` save), so the next check redoes them. Quit should
  finish them first, with Quit now to skip, as planned for
  [live monitoring](live-monitoring.md#cache-writes-while-monitoring-decided-2026-10-13) (2026-10-13).
- [ ] With the default of one background lane, folder details and status checks
  (including manual ones) wait for the selected load. As planned; revisit if
  it feels slow.
- [ ] When a tab's shown data is dropped while it is shown (a folder status check finds
  the folder mismatched, or its cache is cleared), the tab keeps its arrays and later
  plots on screen; a load finding missing shots clears them. Clear the analysis view
  or mark it stale, once plotting exists (Tony, 2026-10-14).

## Near term: useful analysis from loaded data

- [ ] Refactor the largest modules into focused ones, without changing behaviour
  (`FolderExplorer` 1908 lines/116 methods, `folder_cache` 1644, `io_helper`
  1332, `cache_store` 1326), before live monitoring and the analysis workflow
  add to them ([plan](refactoring.md)) (2026-10-13).

- [ ] Apply other tabs' finished status checks during Refresh without source
  I/O ([notes](../.ai/sessions/2026-10-08-codex-roadmap-review/notes.md#cross-tab-status-results)) (2026-10-08).
- [ ] Explain when disk-cache failure skips automatic status checks and offer
  a manual check (2026-10-08).
- [ ] Add small anonymized TXY fixtures with known counts/arrays, including
  interrupted and malformed writes ([notes](../.ai/sessions/2026-10-08-codex-roadmap-review/notes.md#sample-data)) (2026-10-08).
- [ ] Empty folders in lighter grey; hidden folders that contain data in black
  (from the old README list).
- [ ] Shared analysis job runner for GUI/agents: language adapters, ownership,
  results and validated reuse ([plan](analysis-job-runner.md)) (2026-10-13).
- [ ] Complete the dataset → parameters → background script → results workflow,
  with progress, cancellation and errors ([plan](analysis-workflow.md)) (2026-10-08).
- [ ] Standard analyses: per-shot counts, T/X/Y distributions and shot selection
  ([plan](analysis-workflow.md#standard-analyses)) (2026-10-08).
- [ ] Export results and figures with their data source and analysis settings
  ([plan](analysis-workflow.md#export)) (2026-10-08).
- [ ] Headless analysis runner sharing GUI jobs/results; add its CLI afterward
  for batch and agent use ([plan](headless-analysis.md)) (2026-10-13).
- [ ] Update check (notify only): compare the running version with published
  GitHub releases, from source checkouts and frozen builds alike
  ([plan](app-updates.md#stage-1-notify-only)) (2026-10-13).

## Medium term: repeated lab work

- [ ] Live monitoring: load new settled shots and update chosen analyses
  ([plan](live-monitoring.md)) (2026-10-08). New shots stay in RAM and the disk
  cache is written once when monitoring stops or HeLab quits
  ([decided](live-monitoring.md#cache-writes-while-monitoring-decided-2026-10-13)) (2026-10-13).
- [ ] Save analysis presets and reopen analysis workspaces
  ([plan](presets-and-workspaces.md)) (2026-10-08).
- [ ] Cache-only browsing: browse and analyse cached data while the source is
  unavailable ([plan](cache-only-browsing.md)) (2026-10-08).
- [ ] Compare folders or experimental runs using consistent settings
  ([plan](run-comparison-and-batch.md#run-comparison)) (2026-10-08).
- [ ] Self-update button for source checkouts (git + uv) and frozen builds
  (verified download, separate updater, rollback), then a lab self-check
  ([plan](app-updates.md#stage-2-self-update-button)) (2026-10-13).

## Long term: reproducible scientific workflows

- [ ] Network extension: mobile and cross-machine results, SSH remote runners,
  machine/root mapping ([plan](network-runners-and-web.md)) (2026-10-13).
- [ ] Batch analysis across multiple runs with per-run outcomes and cancellation
  ([plan](run-comparison-and-batch.md#batch-analysis)) (2026-10-08).
- [ ] Integrate experiment metadata with shot/run data
  ([plan](reproducible-workflows.md#experiment-metadata)) (2026-10-08).
- [ ] Reuse sequences of analyses and save reproducible result records
  ([plan](reproducible-workflows.md#analysis-sequences-and-result-records)) (2026-10-08).
- [ ] Add specialist analyses driven by agreed lab needs and scientific definitions
  ([plan](reproducible-workflows.md#specialist-analyses)) (2026-10-08).

## Unchosen ideas

- [ ] Cache folder listings to reduce source I/O: expand shows the saved listing
  at once, then one folder stat skips the scandir when the folder is unmodified
  (like the cache-first data check). Shares persisted listings with
  [cache-only browsing](cache-only-browsing.md) (2026-10-09).

- [ ] More file kinds: measure raw `d*.txt` sizes, and load/cache other data formats.
  The cache rebuild keeps file kinds table-driven for this
  ([plan](cache-storage-and-settings.md#file-kinds)) (2026-10-10).

- [ ] Dataset format without pickle (JSON header + Blosc-compressed raw buffers, possibly
  Blosc2), for safety and numpy-version independence. Kept as pickle for now
  ([plan](cache-storage-and-settings.md#decisions-tony-2026-10-10)) (2026-10-10).

- [ ] Lower a load's peak memory: the helper compresses the saved `.npy` artifacts
  for the cache instead of holding a second copy of every shot (2026-10-10).

- [ ] Plot-area hints when no plot is open: usage tips, or a daily motivational
  quote. `CentralHint` already has a second line and `add_widget` for this (2026-10-09).

- [ ] Lock the tree view during a recursive status check? (from the old README
  list; may no longer be needed).

## Done

Ticked items from the old README TODO list, kept for reference:

- [x] Automatic status check of folders in view (View menu and Settings).
- [x] Cancel a recursive status check; choose the recursion depth.
- [x] Strict typing (mypy and Pyright, run inside `pytest`).
- [x] Unit tests, run by CI on macOS, Windows and Ubuntu.
- [x] PyInstaller builds on git tags; pip caching in GitHub Actions.
- [x] File reading off the GUI thread (`IOService` and helper processes).
- [x] Slow `hasChildren()` at the root (replaced by `SnapshotFileSystemModel`).
