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

- [ ] Finish the status-message audit: verify load-phase labels for `merged`/
  `updated` sources ([notes](../.ai/sessions/2026-10-08-codex-roadmap-review/notes.md#status-messages)) (2026-10-08).

## Known issues

- [ ] Folders with over 100,000 entries record a scan failure.
- [ ] With the default of one background lane, folder details and status checks
  (including manual ones) wait for the selected load. As planned; revisit if
  it feels slow.

## Near term: useful analysis from loaded data

- [ ] Apply other tabs' finished status checks during Refresh without source
  I/O ([notes](../.ai/sessions/2026-10-08-codex-roadmap-review/notes.md#cross-tab-status-results)) (2026-10-08).
- [ ] Explain when disk-cache failure skips automatic status checks and offer
  a manual check (2026-10-08).
- [ ] Add small anonymized TXY fixtures with known counts/arrays, including
  interrupted and malformed writes ([notes](../.ai/sessions/2026-10-08-codex-roadmap-review/notes.md#sample-data)) (2026-10-08).
- [ ] Empty folders in lighter grey; hidden folders that contain data in black
  (from the old README list).
- [ ] Complete the dataset → parameters → background script → results workflow,
  with progress, cancellation and errors ([plan](analysis-workflow.md)) (2026-10-08).
- [ ] Standard analyses: per-shot counts, T/X/Y distributions and shot selection
  ([plan](analysis-workflow.md#standard-analyses)) (2026-10-08).
- [ ] Export results and figures with their data source and analysis settings
  ([plan](analysis-workflow.md#export)) (2026-10-08).

## Medium term: repeated lab work

- [ ] Live monitoring: load new settled shots and update chosen analyses
  ([plan](live-monitoring.md)) (2026-10-08).
- [ ] Save analysis presets and reopen analysis workspaces
  ([plan](presets-and-workspaces.md)) (2026-10-08).
- [ ] Cache-only browsing: browse and analyse cached data while the source is
  unavailable ([plan](cache-only-browsing.md)) (2026-10-08).
- [ ] Compare folders or experimental runs using consistent settings
  ([plan](run-comparison-and-batch.md#run-comparison)) (2026-10-08).

## Long term: reproducible scientific workflows

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
