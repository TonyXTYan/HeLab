# HeLab Roadmap

The product overview, priority list and index of the feature plans in this folder.
Horizons describe sequencing, not promised dates. Feature scope and implementation
details remain drafts until resolved during design.

Manual work lives in [.ai/MANUAL_TODO.md](../.ai/MANUAL_TODO.md) and known issues in
[known-issues.md](known-issues.md); review history and
validation evidence live in `.ai/sessions/`; settled decisions live in `.ai/memory/results/`.

How to use it:

- Add new items under the right heading with the date added (YYYY-MM-DD).
- When an item is done, tick it and add the commit hash, then move ticked items
  to **Done** at the next tidy-up.
- Keep each item to one or two lines; link substantial features to a document
  in this folder. Keep priority/completion here rather than duplicating task lists.

## Now: v0.0.7

v0.0.6a1 went to `main` by PR on 2026-10-28 (Tony: released on his own use of HeLab on his
Mac and the lab PCs through v0.0.6, plus the Mac smoke pass; Q6.1). Work for v0.0.7 branches
from `dev/v0.0.7` (agents: `agent/<task>`, [workflow](agent-workflow.md)) and lands back
there; `dev/v0.0.7` goes to `main` by PR, with the version bump on that branch.

**Focus for v0.0.7 (Tony, 2026-10-28; Q6.12):** the TXY converter port. Distributed results
compute is postponed until the converter works well (Q6.2).

- [ ] The TXY converter port (`HeBECANU/tdc_autoconverter`, `lib/dld_raw_to_txy_counts.m`;
  [Live L4](live-monitoring.md#stages)): a headless HeLab converter (`helab convert --watch`) and
  Live's auto-convert toggle replace MATLAB's converter (Q6.3, Q6.8). Output
  `d_txy_helab_<tag>_<N>.txt` (Q18.4), written to a temporary name and renamed, into HeLab's cache
  (the default) or temp folder, or beside the raw files as a per-folder option (Q9.3, Q9.7). **The
  bar is byte-identical output:** `matlab-2019` reproduces 303 of the 309 sample shots and the
  other 6 are proved reference faults
  ([findings](../.ai/sessions/2026-10-28-claude-txy-converter-plan/findings.md),
  [legacy notes](../.ai/sessions/2026-10-20-claude-dld-front-panel-review/core-update.md#import-and-reconstruction)).
  Stage 1, the reference cross-checked against MATLAB run headless: **done 2026-10-29**
  (`d26e196`). Stage 2, one floor per backend: **done 2026-10-29** (`3bd791c`); NumPy the default,
  Cython optional, the reference kept; numba, MLX and Rust left the build (Q11.2, `134e2ec`).
  Stage 4, in HeLab: **done 2026-10-29** (`02cda86`; Tony's follow-ups: tagged names, four source
  modes, one launch folder, damaged raw files, `c718c71`). Stage 3 (calibration) and stage 5
  (replacing MATLAB) **not started**, after v0.0.7 (Q9.9); the post-2025 plate findings feed stage 3
  (a 180° orientation from July 2026, Q25.1; an opt-in burst veto, Q25.5). Open: Q6.7, Q6.9–Q6.11,
  Q12.6, Q14.2, Q14.4, Q15.3, Q23.x, Q25.2, Q25.4 ([plan](txy-converter.md#open-decisions)). [Plan](txy-converter.md)
  (2026-10-29; focus 2026-10-28).
- [ ] Release v0.0.7 (Q9.9: stages 1, 2 and 4 plus the smoke pass). Left: the smoke pass on a Mac
  and a lab PC (M1.1–M1.10; the converter step is M1.9, Q24.3); byte units by OS (A26.1) done
  (landed `8bf810f`); the runner aids for the smoke pass (floors Smoke ready and Runner Tools, Tony
  2026-10-30); `converted-txy/index.sqlite` with Q19.5 and A19.1 (Q26.2, Q27.4, Q27.5) done (landed
  `460360b`, 2026-10-30), its follow-up A30.4; saved results off by default (Q27.1, done); Q23.1 confirmed;
  the version bump on the PR branch to the pre-release **`0.0.7a1`** (Tony, 2026-10-29; then v0.0.8
  development straight away); the PR to `main`; the release tidy-up (Q8.3) (2026-10-29).
- [ ] Caching v2: the raw d files as the cached source (a raw layer of pulses plus TXY layers per
  profile, with a per-folder policy) in a fresh store-v4, with versioning (Q27.2). v0.0.7 covers its
  planning only; it is built in **v0.0.8** (Q28.2), stage by stage after Tony's go (block 28;
  [plan](caching-v2.md), Q19.x, Q22.x, 2026-10-29).
- [ ] Distributed results compute: one machine computes analysis results and other HeLabs use
  them without repeating the work. It builds on the [headless runner](headless-analysis.md)
  and the [network extension](network-runners-and-web.md#cross-machine-result-sharing).
  **Postponed** until the converter works well (Q6.2, Tony 2026-10-28).

**Carried over from v0.0.6:**

- [ ] Parallel agent workflow on Maestri floors (cloud agents kept open): pilot
  the first floor with the setup hook ([setup](../.ai/maestri-setup.md)), then
  the pytest `pythonpath` guard, a hard-coded settings-defaults table (also for
  Restore default and tooltips in the release) and per-checkout share/isolated
  profiles, with `HELAB_SETTINGS_OVERRIDE` ([plan](agent-workflow.md)) (2026-10-15).
  The settings factory (`app_settings()`) landed in TonyXTYan/HeLab#7 (2026-10-21).
  Floors piloted; the pytest `pythonpath` guard (`50fa36b`) and the settings-defaults
  table with `read_setting` (`0f4df65`) landed from `agent/ci-robustness-2` (merge
  `51c0ee2`, 2026-10-22). Left: Restore default and default tooltips, the profiles.

- [x] Release v0.0.6a1 (Tony, 2026-10-28: Q1.1–Q1.3, Q6.1). The smoke pass ran on a Mac by
  computer use ([results](../.ai/sessions/2026-10-28-claude-smoke-mac/results.md)). Tony
  released on that and on his own use through v0.0.6, so the lab PC pass and Live (M1.3) are
  the first checks of v0.0.7. Merged to `main` (`9c477c2`) and tagged `v0.0.6a1`, with no
  RERUN in the test jobs (2026-10-28). Its draft has no assets, since the release job
  couldn't find it under GitHub's `untagged-…` name (run 40675311830; fixed in `d36a20e` on
  `dev/v0.0.7`, [known issues](known-issues.md#fixed)); Tony leaves it as it is, and v0.0.7's
  release is the first with zips (Q8.1). The `v0.0.5a1` draft stays unpublished.

- [ ] Unsupervised smoke runs: menu-bar actions, an in-app save-screenshot command,
  accessibility labels, a debug/smoke menu, then a `--smoke` control channel (design first),
  so a model drives the smoke pass (M1.1–M1.10) without taking the cursor. Approved by Tony 2026-10-28 (Q5.2)
  ([plan](smoke-automation.md)) (2026-10-28).

- [ ] Release repos: develop and release on `TonyXTYan/HeLab`; fast-forward
  `HeBECANU/HeLab` `main` only for lab-ready versions, which drafts the same
  release there; stop pushing dev branches to `HeBECANU`. Confirmed by Tony
  2026-10-28 (Q1.4); v0.0.6a1 is not lab-ready, so HeBECANU waits for a later version (Q1.4.1)
  ([plan](app-updates.md#release-repos-proposed-2026-10-13-tony-to-confirm)) (2026-10-13).

- [ ] Build size: exclude unused packages (pyarrow, mypy), replace
  pytablericons/pygame, and decide on QtWebEngine ([plan](build-size.md))
  (2026-10-13). Step 1 done: the macOS zip holds only `HeLab.app` with its
  symlinks (275 MiB instead of 2152 MiB, checked on the PR #5 build).

- [ ] Data roots follow-ups: smaller items (Remove .helab-root… in the tree,
  every location in the duplicates window, NFS/AFP caching, label rename)
  ([list](../.ai/sessions/2026-10-16-claude-data-roots/follow-ups.md)) (2026-10-18).

## Known issues

Bugs, gaps and flaky tests, open and recently fixed: [known issues](known-issues.md).

## Near term: useful analysis from loaded data

- [ ] Decouple browser/cache, dataset, analysis and UI responsibilities so
  agents can develop separate features in supervised, isolated worktrees
  without changing current behaviour. Feature-driven: the dataset view first,
  then splits where work collides ([plan](refactoring.md)) (2026-10-13;
  revised 2026-10-15). Milestone 1 (dataset view) and the two-floor pilot
  done (2026-10-19). Milestone 2 mostly done (TonyXTYan/HeLab#7, 2026-10-21): `io_ops`,
  `views/plots`, the Qt-free analysis core, `PlotWorkspace`, `LiveController`; left: the
  explorer's load logic, `FolderCache`'s stores, `_on_event`.

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
- [ ] Complete the dataset → parameters → background script → results workflow,
  with folder-following views, pinning, progress, cancellation and errors
  ([plan](analysis-workflow.md)) (2026-10-08; revised 2026-10-14).
- [ ] Analysis result caching: RAM results (R1), then disk-cached one-off
  results with exact-match reuse (R2); Live stages follow
  ([plan](result-caching.md)) (2026-10-15). R1 done (2026-10-19), R2 done (2026-10-23).
- [ ] One Settings panel follows the active plot (click, focus, tabbed or
  floating dock; chooser raises a plot; settings pages as tabs via
  `ParameterSpec.page`). Quick version on Ground (Tony, 2026-10-19); hardened
  2026-10-19 (signals instead of an event filter, many plots, tab rule, tab
  close by identity, activation sources, typed numbers). Left: the on-screen
  checks (MANUAL_TODO) and a pin to keep one plot's settings shown.
- [ ] Transfer fractions plot (port of Momentum_Bells_test's `monitor_momentum.m`):
  orders auto-found in T, manual centre/spacing filled from the detection. Quick
  version on Ground; hardened 2026-10-20 (detection edge cases with "order 0
  unsure" and "moved", clipped manual windows, typed values kept across reruns,
  From-shot wording, counts checked against a Python `fraction_calc`); a
  Reference spacing (15 ms) guides auto's spacing, so a bump 5 ms from order 0
  no longer gives 5 ms (2026-10-20); the DLD port's Transfer fractions uses the same
  detection and Reference spacing (R-19, `f7d06e6`…`6fac7df`, merge `0ee6ca2`, 2026-10-22). Left:
  detection on real Bragg/magnetic data (MANUAL_TODO); a hot spot near the XY
  box's edge without MATLAB's `dld_xy_rot` (to investigate; new detector since);
  draggable windows on the T histogram; the averaged-vs-detuning view (Tony,
  2026-10-19/20).
- [ ] How auto detection should find orders 0, ±1, ±2 (it also covers a first run
  at high transfer, where +1 can be taken for order 0): Tony to describe; not built
  (2026-10-20).
- [ ] Show the analysis worker beside I/O: status-bar counts and Folder
  details' activity, each job with script, input, revision, time and Cancel;
  later remote/CLI workers in the same list (Tony, 2026-10-19).
- [ ] Packaged builds: record bundled scripts' SHA-256 at build time (in
  `_build_info.json`), since PyInstaller leaves no `.py` files to hash
  (2026-10-19).
- [ ] Standard analyses: per-shot counts, T/X/Y distributions (v1 done
  2026-10-19; in s and m with SI prefixes, while the DLD port's plots use ms/mm) and shot
  selection ([plan](analysis-workflow.md#standard-analyses)) (2026-10-08).
- [ ] Features from the old MATLAB DLD front panel. Built 2026-10-20 (F0, D1–D10,
  D12, D14, D15 placeholder), on `agent/dld-front-panel-port`: constants at
  three levels (Settings → Lab parameters, folder constants, plot overrides) with
  bounded fits ± SE; fits, Bose/bimodal condensate fits and BEC properties on the
  T/X/Y histograms; density images; mean X/Y against T and the T spectrum; shot times
  from the raw files; Shot trends with an opt-in low-count notification in Live;
  hot-spot masks with a placeholder finder; Release time and Velocity distributions;
  g² and back-to-back Correlations. T in ms and X/Y in mm everywhere (Tony, 2026-10-20). Next: D13's
  per-shot halo centring, then the plan's
  left-to-do list; raw-pulse diagnostics after the TXY converter port. 33 open
  decisions, each built as proposed, and on-screen and real-data checks
  ([plan](dld-front-panel-port.md#open-decisions),
  [register](../.ai/sessions/2026-10-20-claude-dld-coordinator/register.md),
  [manual to-do](../.ai/MANUAL_TODO.md#dld-front-panel-port-added-2026-10-20)) (2026-10-20).
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
  L1–L3 done (2026-10-19): plots follow Live. L4 auto-convert done 2026-10-29 (`6454b4a`,
  `c718c71`); converter stage 5 replaces MATLAB.
- [ ] QC script catalogue and safe derived-file repairs, kept in HeLab's cache
  folder; migrate the current status scan as its first provider
  ([plan](quality-control-and-repair.md)) (2026-10-14; revised 2026-10-15).
- [ ] Save analysis presets and reopen analysis workspaces
  ([plan](presets-and-workspaces.md)) (2026-10-08). Stage 1 done (2026-10-23,
  `agent/presets-reopen`): script and one-folder arrangement presets, plots
  reopening at start, Settings → Cache › Presets…; the full workspace file is
  still open.
- [ ] Compare folders or experimental runs using consistent settings
  ([plan](run-comparison-and-batch.md#run-comparison)) (2026-10-08).
- [ ] Version drift across lab PCs: show which HeLab version and PC converted a folder or saved a
  result, and note when the acquisition PC runs an older release than this one (Tony,
  2026-10-29; with caching v2's [versioning](caching-v2.md#versioning) and the self-update below).
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
  ([plan](cache-storage-and-settings.md#decisions-tony-2026-10-10)) (2026-10-10). Planned in
  store-v4 as pickle-free `.hlb` files ([caching v2](caching-v2.md)), not yet approved.

- [ ] Lower a load's peak memory: the helper compresses the saved `.npy` artifacts
  for the cache instead of holding a second copy of every shot (2026-10-10).

- [ ] Plot-area hints when no plot is open: usage tips, or a daily motivational
  quote. Usage tips done on Ground (`CentralHint.TIPS`, a new one every 30 s
  while shown, click for the next; keep them current as features change); the
  quote stays unchosen (2026-10-09; tips 2026-10-19).

- [ ] Lock the tree view during a recursive status check? (from the old README
  list; may no longer be needed).

## Done

v0.0.6a1 (`main` `9c477c2`, 2026-10-28; native checks in [MANUAL_TODO](../.ai/MANUAL_TODO.md)):

- [x] Status-message audit: load-phase labels for `merged`/`updated` sources
  (2026-10-08; Quick Fixes 2, `8de9ea6`, `93fb3dd`, 2026-10-26).
- [x] Refresh applies other tabs' finished status checks without source I/O
  (2026-10-08; cache-only C1, `9c75340`, 2026-10-26).
- [x] First analysis: interactive 3D scatter with auto-crop; the crop rule awaits Tony's check
  on real data ([plan](analysis-workflow.md#first-analysis-3d-scatter-decided-2026-10-15)) (2026-10-15; v1 2026-10-19).
- [x] Open plots count toward the RAM budget: 50 % status bar, 75 % window, 80 % release least
  recently shown plots, never closed (Tony, 2026-10-19/20; landed 2026-10-20).
- [x] Floating plot settings travel with the plot's window (Tony, 2026-10-19; landed 2026-10-20).
- [x] Cache-only browsing: File › Work Offline (C0–C3, merge `9bb1ff7`)
  ([plan](cache-only-browsing.md)) (2026-10-08; done 2026-10-26).

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
