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

## Now: v0.0.6

v0.0.5a1 merged to `main` as `5a8ae6f` (2026-10-19); its items are under
**Done**. Work for v0.0.6 branches from `dev/v0.0.6` (agents: `agent/<task>`,
[workflow](agent-workflow.md)) and lands back there; `dev/v0.0.6` goes to
`main` by PR, with the version bump on that branch. Priorities for v0.0.6 are
still to choose (Tony, with the coordinator's proposal).

- [ ] Parallel agent workflow on Maestri floors (cloud agents kept open): pilot
  the first floor with the setup hook ([setup](../.ai/maestri-setup.md)), then
  the pytest `pythonpath` guard, a hard-coded settings-defaults table (also for
  Restore default and tooltips in the release) and per-checkout share/isolated
  profiles, with `HELAB_SETTINGS_OVERRIDE` ([plan](agent-workflow.md)) (2026-10-15).

- [ ] Native checks for v0.0.5a1 on macOS and a Windows lab PC: data roots,
  cache first and remounts on `/Volumes/dld_output`, the packaged app and the
  release flow ([manual to-do](../.ai/MANUAL_TODO.md)) (2026-10-19). Then
  publish the `v0.0.5a1` draft release.

- [ ] Release repos: develop and release on `TonyXTYan/HeLab`; fast-forward
  `HeBECANU/HeLab` `main` only for lab-ready versions, which drafts the same
  release there; stop pushing dev branches to `HeBECANU`. Proposed, Tony to
  confirm ([plan](app-updates.md#release-repos-proposed-2026-10-13-tony-to-confirm)) (2026-10-13).

- [ ] Build size: exclude unused packages (pyarrow, mypy), replace
  pytablericons/pygame, and decide on QtWebEngine ([plan](build-size.md))
  (2026-10-13). Step 1 done: the macOS zip holds only `HeLab.app` with its
  symlinks (275 MiB instead of 2152 MiB, checked on the PR #5 build).

- [ ] Finish the status-message audit: verify load-phase labels for `merged`/
  `updated` sources ([notes](../.ai/sessions/2026-10-08-codex-roadmap-review/notes.md#status-messages)) (2026-10-08).

- [ ] Data roots follow-ups: smaller items (Remove .helab-root… in the tree,
  every location in the duplicates window, NFS/AFP caching, label rename)
  ([list](../.ai/sessions/2026-10-16-claude-data-roots/follow-ups.md)) (2026-10-18).

## Known issues

- [ ] `test_folder_cache.py::test_two_tabs_share_snapshot_arrays_and_default_resolution`
  needed one rerun in each of three full runs on the RSPE Windows PC
  (2026-10-19); investigate if it fails outright.
- [ ] Folders with over 100,000 entries record a scan failure.
- [ ] The temp folder (`DIR_TEMPS`, Settings → General) is created and can be
  changed, but nothing uses it: helpers' private folders go to the system temp
  dir (`tempfile.mkdtemp` in `IOService`). Remove the setting, or move helper
  folders into it (2026-10-15).
- [x] Quitting cancels cache writes still running in the background (a finished
  load's `disk_cache_pending` save), so the next check redoes them. Fixed by the
  quit window (`QuitSaveDialog`, with Quit now) in Live L1 (2026-10-19).
- [ ] Ordinary loads read a file once its mtime is 5 s old (`SETTLE_SECONDS`); on
  SMB with stale or coarse metadata a file still being written can pass. Live
  reads a new file only once it is unchanged a check later and ends with a whole
  row; use the same rules for loads. The real fix is the converter writing to a
  temp name and renaming (below) (2026-10-19, Live review).
- [ ] Main-window tests resolve the default data path, which is
  `/Volumes/dld_output` when it is mounted: tests should never touch the real
  volume (2026-10-19).
- [x] `tests/test_live_io.py`'s pause test assumed a 3000-file background load
  was still running after setup. Fixed with `HELAB_TEST_READ_GATE`; both Live
  I/O tests now run on Windows too (Plots v1 polish, 2026-10-19).
- [ ] With the default of one background lane, folder details and status checks
  (including manual ones) wait for the selected load. As planned; revisit if
  it feels slow.
- [ ] When a tab's shown data is dropped while it is shown (a folder status check finds
  the folder mismatched, or its cache is cleared), the tab keeps its arrays and later
  plots on screen; a load finding missing shots clears them. Clear the analysis view
  or mark it stale, once plotting exists (Tony, 2026-10-14).
- [ ] `test_two_step_browse::test_refresh_cancels_only_automatic_subscriptions_and_suppresses_new_checks`
  needed one rerun on macOS CI in 2 of 4 runs (2026-10-18); it doesn't reproduce
  locally. Investigate if it fails outright.

## Near term: useful analysis from loaded data

- [ ] TXY converter (`HeBECANU/tdc_autoconverter`, `lib/dld_raw_to_txy_counts.m`):
  write each TXY to a temporary name and `movefile` it to the final name, so
  HeLab never sees a partly written file (Tony, 2026-10-19).
- [ ] Decouple browser/cache, dataset, analysis and UI responsibilities so
  agents can develop separate features in supervised, isolated worktrees
  without changing current behaviour. Feature-driven: the dataset view first,
  then splits where work collides ([plan](refactoring.md)) (2026-10-13;
  revised 2026-10-15). Milestone 1 (dataset view) and the two-floor pilot
  done (2026-10-19).

- [ ] Apply other tabs' finished status checks during Refresh without source
  I/O ([notes](../.ai/sessions/2026-10-08-codex-roadmap-review/notes.md#cross-tab-status-results)) (2026-10-08).
- [ ] Explain when disk-cache failure skips automatic status checks and offer
  a manual check (2026-10-08).
- [ ] Add small anonymized TXY fixtures with known counts/arrays, including
  interrupted and malformed writes ([notes](../.ai/sessions/2026-10-08-codex-roadmap-review/notes.md#sample-data)) (2026-10-08).
- [ ] Empty folders in lighter grey; hidden folders that contain data in black
  (from the old README list).
- [ ] Shared analysis job runner for GUI/agents: language adapters, ownership,
  results, validated reuse and optional versioned script bundles; plain files
  remain usable. Local runner first, open to remote later
  ([plan](analysis-job-runner.md)) (2026-10-13; revised 2026-10-15).
- [x] First analysis: interactive 3D scatter (Plotly via the Dash server),
  default auto-crop to regions of interest. v1 done 2026-10-19; the crop rule
  awaits Tony's check on real data
  ([plan](analysis-workflow.md#first-analysis-3d-scatter-decided-2026-10-15)) (2026-10-15).
- [ ] Complete the dataset → parameters → background script → results workflow,
  with folder-following views, pinning, progress, cancellation and errors
  ([plan](analysis-workflow.md)) (2026-10-08; revised 2026-10-14).
- [ ] Analysis result caching: RAM results (R1), then disk-cached one-off
  results with exact-match reuse (R2); Live stages follow
  ([plan](result-caching.md)) (2026-10-15). R1 done (2026-10-19).
- [ ] Open plots count toward the RAM budget and release their data when it is
  exceeded, least recently used first; Rerun reloads it (Tony, 2026-10-19).
- [ ] One Settings panel follows the active plot (click, focus, tabbed or
  floating dock; chooser raises a plot; settings pages as tabs via
  `ParameterSpec.page`). Quick version on Ground, hardening pending: real-app
  focus with QtWebEngine and pyqtgraph, many plots, a pin to keep one plot's
  settings shown (Tony, 2026-10-19).
- [ ] Show the analysis worker beside I/O: status-bar counts and Folder
  details' activity, each job with script, input, revision, time and Cancel;
  later remote/CLI workers in the same list (Tony, 2026-10-19).
- [ ] Packaged builds: record bundled scripts' SHA-256 at build time (in
  `_build_info.json`), since PyInstaller leaves no `.py` files to hash
  (2026-10-19).
- [ ] Standard analyses: per-shot counts, T/X/Y distributions (v1 done
  2026-10-19, in s and m; units to confirm) and shot selection
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
  locally first, in stages L1–L5 ([plan](live-monitoring.md#stages)) (2026-10-08;
  staged 2026-10-15). New shots stay in RAM; the disk cache is written every
  N shots (configurable) and when monitoring stops or HeLab quits
  ([decided](live-monitoring.md#dataset-cache-writes-while-monitoring)) (2026-10-13).
  L1 and L2 done (2026-10-19); L3 next with the dataset view.
- [ ] QC script catalogue and safe derived-file repairs, kept in HeLab's cache
  folder; migrate the current status scan as its first provider
  ([plan](quality-control-and-repair.md)) (2026-10-14; revised 2026-10-15).
- [ ] Save analysis presets and reopen analysis workspaces
  ([plan](presets-and-workspaces.md)) (2026-10-08).
- [ ] Cache-only browsing: browse and analyse cached data while the source is
  unavailable; offline mode makes no network request
  ([plan](cache-only-browsing.md)) (2026-10-08; revised 2026-10-14).
- [ ] Compare folders or experimental runs using consistent settings
  ([plan](run-comparison-and-batch.md#run-comparison)) (2026-10-08).
- [ ] Self-update button for source checkouts (git + uv) and frozen builds
  (verified download, separate updater, rollback), then a lab self-check
  ([plan](app-updates.md#stage-2-self-update-button)) (2026-10-13).

## Long term: reproducible scientific workflows

- [ ] Network extension, after local Live/results: connect machines for
  metadata and result access, then remote Live updates and later remote jobs;
  start the mobile web with a view-only recent-results page
  ([plan](network-runners-and-web.md)) (2026-10-13; revised 2026-10-14).
- [ ] Batch analysis across multiple runs with per-run outcomes and cancellation
  ([plan](run-comparison-and-batch.md#batch-analysis)) (2026-10-08).
- [ ] Integrate experiment metadata with shot/run data
  ([plan](reproducible-workflows.md#experiment-metadata)) (2026-10-08).
- [ ] Reuse sequences of analyses and extend the local result record for
  full reproducibility
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

v0.0.5a1 (`main` `5a8ae6f`, 2026-10-19; native checks in [MANUAL_TODO](../.ai/MANUAL_TODO.md)):

- [x] Cache rebuild: SQLite records + compressed dataset files, editable disk and
  RAM budgets, large-folder warning, per-folder flags, cache-folder move, rebuilt
  Settings → Cache tab; sessions S1–S11 ([plan](cache-storage-and-settings.md#sessions))
  (2026-10-10; `fe5a5b7`…`eafcf4b`).
- [x] App version and build info, Help → About, explicit CI tagging and draft
  releases ([implementation](app-versioning.md#implemented-workflow-authoritative)) (2026-10-12).
- [x] Folder details panel, shorter status bar, load elapsed time and time left
  (2026-10-10, `3af4fea`).
- [x] Data roots: disk caching keyed by a hidden `.helab-root` marker (UUID),
  RAM only without one; SMB share and local-volume locations; Same folder / Copy
  for duplicates with warnings; Place .helab-root (right-click and File menu,
  Windows `C:\` allowed); Settings → Data roots with Show, Copy path, Clear
  cached data, Forget, Delete and Review; store `store-v3`
  ([plan](data-roots.md), [stages](../.ai/sessions/2026-10-16-claude-data-roots/plan.md)) (2026-10-16…18).
  It replaces the SMB-key remount fix ([investigation](../.ai/sessions/2026-10-15-codex-status-remount/notes.md)).
- [x] Folders without a disk cache get their status from browsing (session
  failure history only) (2026-10-18).
- [x] Resize repaint freeze: no main-window repaint suppression; pytest covers
  painting and scan cancellation ([fix](../.ai/sessions/2026-10-11-codex-resize-during-scan/notes.md#implementation)) (2026-10-11).
- [x] Disk-cache eviction no longer drops records to make room (`fd4e020`,
  `ef4c0ca`); reads never mean "nothing saved" on contention (S1)
  ([audit](../.ai/sessions/2026-10-10-claude-cache-audit/notes.md#storage-findings-ranked)) (2026-10-10).
- [x] Settings → Cache edits apply, Clear doesn't block the GUI (rebuilt Cache
  tab, `52201ca`) (2026-10-10).

Ticked items from the old README TODO list, kept for reference:

- [x] Automatic status check of folders in view (View menu and Settings).
- [x] Cancel a recursive status check; choose the recursion depth.
- [x] Strict typing (mypy and Pyright, run inside `pytest`).
- [x] Unit tests, run by CI on macOS, Windows and Ubuntu.
- [x] PyInstaller builds on git tags; pip caching in GitHub Actions.
- [x] File reading off the GUI thread (`IOService` and helper processes).
- [x] Slow `hasChildren()` at the root (replaced by `SnapshotFileSystemModel`).
