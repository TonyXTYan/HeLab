# HeLab Agent Notes

HeLab (Helium Experiment Lab Analysis Board) is a PyQt6 desktop GUI application for real-time scientific data analysis in the ANU Helium BEC lab. It monitors experiment data folders, runs pluggable analysis scripts, and renders interactive visualizations.

Two repos exist: this one (`TonyXTYan/HeLab`) is the development branch; `HeBECANU/HeLab` is the stable lab deployment.

## Working conventions

- Address the user as "🎓Tony" in conversation.
- Always ask Tony before running `git commit`. Staging, diffing and reviewing are fine without asking.
- Every Git commit must include both a concise subject and a meaningful description in the message body, separated by a blank line. The description should explain what changed and why, and include relevant validation.
- CodeGraph (`codegraph_*` tools, `.cursor/rules/codegraph.mdc`) is reliable for definitions, signatures and source, but its callers, callees, trace and impact results miss many calls made through attributes (e.g. `self.model.cache.submit(...)` reaching `FolderCache.submit`). Confirm them with grep before relying on them.

## AI workspace (`.ai/`)

- `.ai/coding-workspace.md` — shared AI-workspace conventions for Tony's repos (what goes in memory vs sessions, working rules).
- `roadmaps/_readme.md` — the product overview, single priority/completion list and feature-plan index. Add new product items there, not to README or memory.
- `roadmaps/` — ongoing feature documents: purpose, scope, dependencies, acceptance criteria and open decisions. Link each from `_readme.md`; do not duplicate its priority/completion checklist. Session-specific investigations and validation evidence stay in `.ai/sessions/`.
- `.ai/MANUAL_TODO.md` — ongoing manual-action list, including native UI checks, real-volume testing and release validation. Detailed results and evidence belong in `.ai/sessions/`, linked from the item.
- `.ai/memory/MEMORY.md` — index of project memory. Read it first; load individual files only when relevant. Settled design decisions (with the reasons and Tony's chosen wording/icons) live in `.ai/memory/results/`; this file keeps only the codebase rules.
- `.ai/sessions/YYYY-MM-DD-<tool>-<title>/` — per-session notes. `.ai/session-export-codex/` and `.ai/session-export-claude/` — raw exported transcripts. Search these for history; don't auto-load them.
- `.ai/temp/` and `.ai/local/` are gitignored scratch space.

## Setup

Python 3.13 is the required version (CI gates on it). Use uv, as the README's "Setup (any machine)" guide does:

```bash
uv python install 3.13
uv venv --seed --python 3.13 venv && source venv/bin/activate   # Windows: venv\Scripts\activate
uv pip install -r requirements.txt -e .
git submodule update --init --recursive   # legacy/tdc_autoconverter
```

`venv/` may be a symlink to `venv.nosync/` (keeps it out of iCloud Drive sync on macOS) — both names are gitignored and activation/imports behave identically either way.

## Running

```bash
helab              # via entry point
python -m helab    # via module
```

## Testing

```bash
pytest                        # all tests
pytest -n 4 --verbose         # parallel (4 workers)
pytest tests/test_foo.py      # single file
pytest --cov=helab            # with coverage
```

Tests ending in `.disabled` are intentionally skipped (not collected) — don't try to "fix" them into passing without checking why they were disabled first.

## Type checking

Strict typing is enforced — everything should be typed.

```bash
mypy helab/ --strict
mypy tests --strict
pyright helab tests
```

`tests/test_typing.py` runs these (plus non-strict mypy) inside `pytest`, so type errors in tests fail the suite. Pass explicit paths to pyright: bare `pyright` also scans `dev/`, `dist/` and `side_projects/` and reports many unrelated errors. `pyrightconfig.json` and `mypy.ini` exclude `helab/scripts/legacy_plotly/` from type checks.

## Building executables

```bash
pyinstaller HeLab.spec --clean -y    # all platforms
```

The `.spec` file produces `HeLab.app` on macOS (bundle ID `au.edu.anu.he-bec-lab`).

**Versioning:** `helab/_version.py` is the only editable version source (PEP 440,
no `v` prefix). Branch names need not match it. `helab/build_info.py` writes
`_build_info.json` into PyInstaller/wheel build output; never generate it in the
source package. Runtime uses that stamp, or Git explicitly rooted in the package's
own checkout, never the launch directory. Help → About HeLab shows provenance.
CI stamps record the explicit source branch/build ref without replacing Git HEAD.
Put a release-version bump on the PR branch before final approval. A squash merge
to `main` with a new version triggers CI tagging and a draft release after required
checks pass; publication remains manual. An existing tag with an incomplete draft
is recoverable: rebuild/test that tagged SHA, validate clean archive stamps before
tagging/uploading, preserve manifest-verified assets and never modify a published
release or force-move a tag. See `roadmaps/app-versioning.md`.

## Architecture

**Package layout:** `helab/models/`, `helab/views/`, `helab/workers/`, `helab/scripts/`, `helab/utils/`

**Responsive filesystem I/O:** The active folder browser uses `IOService` (`helab/utils/io_service.py`) and isolated `helab/io_helper.py` processes. Requests are deduplicated, queues and concurrency are bounded, and cancellation/deadlines never wait on the GUI thread. Daemon reader threads deliver results through a bounded queue; a Qt timer applies small batches. Source folders are never queried by the GUI model. The frozen helper entry point in `helab/main.py` must run before imports that initialize GUI services, caches, or Dash. `GUIWatchdog` records event-loop stalls and dumps thread stacks independently of GUI timers.

Rules for the shared I/O queue (decisions, timings and the stopping-helper display: `.ai/memory/results/folder-io-queue.md`):
- One app-wide queue with two source-I/O lanes. The **foreground** lane runs the current tab's listings (`list`, `resolve`) and its selected load (in queue mode, its queued loads one at a time): one listing and one load at once, at most 3 processes including stopping ones, and it never waits for background work. The **background** lanes (Settings → General, "Simultaneous background I/O operations", default 1) run everything else: background loads, `details`, basic scans, cache writes and history saves. Navigation and loads precede bulk scans; FIFO within each group. `FolderCache` decides the lane (`foreground_owners`, set by the current `FolderExplorer`); switching tabs makes the old tab's work background.
- While the foreground works, background loads and scans **pause cooperatively** (a `pause` file in the helper's private folder, checked between files/entries; `paused`/`resumed` events) and no new ones start; the selected load pauses while the tab lists a folder. Resume is 0.5 s after the foreground goes idle; a listing silent for 3 s no longer counts. A paused helper keeps its slot and its no-progress timer is frozen. A load leaving the foreground takes a free background slot, or is stopped and requeued to restart from its RAM shots.
- A third, **local** lane (2 processes) runs `cached` reads of the local disk cache, batched `subtree_save` writes of derived subfolder status, and `cache_admin` maintenance (the startup sweep). They never touch source folders, never wait for or pause with foreground/background work, and are never paused.
- **Cache first.** Selecting a folder with a disk cache shows its data at once (memory, else a `cached` read), marked unchecked (`loaded (cached)` / `Checking for changes…`). The load that follows is the check: when the tab holds the cached dataset (`base_signature`) and the cache has no unsettled files, the helper stats only the folder and, if it is not modified since the cache's file list (`snapshot_at`), answers `unchanged` without listing. Otherwise it lists, fingerprints and merges as usual. Selecting a folder with saved counts and a disk cache does not list it (expanding still does). A failed check keeps the cached data with `Check failed` and Retry.
- **Files still being written** (modified within `SETTLE_SECONDS` = 5 s, or changing while read) are never read or cached: they are left out of fingerprints and signatures (loads and scans alike), counted as `still being written`, and the cache records `unsettled` so the next check is a full one. Tests set `HELAB_SETTLE_SECONDS=0`.
- A helper occupies its slot **until its exit is confirmed** by the daemon reaper's in-memory exit flag — including cancelled/timed-out helpers and background cache writers. Never free a slot on message delivery or reader completion; duplicate exit notifications are matched by request identity.
- Browsing is two steps. `list` (one scandir, names only, no source stat) gives counts and status at once, plus each subfolder's saved summary, history and cache flags from the local cache — so saved badges appear immediately and automatic visible scans don't redo them. `details` (the full scan) follows in the background for the signature, dates and subfolder identities (a replaced folder's saved summary is then dropped). It is skipped while a load of a folder **without subfolders** runs — the load sends and saves the same folder summary. A listing never writes to the cache and never clears a scan failure; a listing error records one. An empty `signature` means unknown, never "changed".
- Timeouts measure **time without progress**; helpers send heartbeats while listing or checking files. Listings, scans and a load's listing phase get one 60 s attempt with no retry (a timeout is one scan failure). Only a load's per-file reads retry, with 15/20/30 s attempts per file. Right-click Retry / Refresh and the status-line Retry list one folder with no timeout, showing elapsed time and a Cancel action; a load retry keeps its per-file timeouts. **A retry never runs beside the attempt it replaces** — it is held until that helper exits. Cancellation stops retries. Timed-out loads restart from completed RAM shots after fingerprint validation.

**Folder icons:** The name column starts with a generic folder icon. Visible rows get native folder/volume icons (including macOS custom icons) from a separate `icons` helper in the shared background I/O lane, in batches of at most 64 with a 5-second no-progress timeout and cooperative pausing. `FolderCache` holds up to 4096 icons in session memory, shared across tabs; failed lookups retain the generic icon until Refresh. Icon lookup never runs during listing or model rendering. Refresh clears visible icons for another lookup. Keep the native Qt platform plugin in the helper; offscreen Qt cannot supply macOS custom icons.

**Threading:** The GUI process has no worker pools. Source-folder and disk-cache work runs in isolated `io_helper` processes, whose results daemon reader threads deliver (see Responsive filesystem I/O). `GUIWatchdog` and the Dash server run on their own background threads.

**Window resizing:** Keep Qt's normal main-window resize and repaint handling. Disabling updates for the whole window during resize and restoring them with a timer can stop paint delivery while I/O continues. Resize regressions in `tests/test_window_resize.py` check continuing paint events and scan cancellation, not just `updatesEnabled()`.

**Caching:** The disk cache is `DIR_CACHES/store-v2` (`helab/utils/cache_store.py`, `CacheStore`): SQLite records in `records.sqlite` (WAL, JSON text) and one Blosc-compressed dataset file per folder in `datasets/`. **Only helpers open it**; the GUI sends `store_options()` (`helab/utils/folder_cache.py`) with each request and never opens the store, at startup or in Settings. Reads answer found / missing / error, and an error is never "nothing saved". Every write checks a save guard taken when its job started (per-kind generations, the folder's epoch, and for datasets a `job_seq`), so a save that was already running can't bring back removed data or overwrite newer data. Replaced dataset files are retired, never deleted at once; a `cache_admin sweep` helper on the local lane deletes them later (at startup, then by the deadline each helper reports, via one `FolderCache` timer), and at startup also deletes the old diskcache folders (`data_ram_cache`, `status_cache`, `os_file_system_cache`). **Nothing is removed without the user asking.** Maintenance goes through `FolderCache.cache_admin(action, …)` (`inventory`, `clear`, `purge`, `trim`, `adopt`, `discard`, `sweep`; results on `cacheAdminResult`). Every removal sends `removed` (kinds, paths); `FolderCache.removed()` resets exactly those flags and saved results in memory, and ignores results read before the removal. A load's save checks the disk budget (`store_options()["budget"]`, default 8 GiB, live data only) in its save transaction, using the budget the app set last (requests carry `budget_set_at`; the store records the newest, so a load started before the user lowered it saves within the new one): one that doesn't fit, or that grows a cached folder while usage is at 80%, becomes a pending save (`cache_full` / `cache_approval`, tracked in `FolderCache.pending_saves`) until Make room (`adopt`) or Don't cache (`discard`). Helpers report the store's live usage with their results (`usage`, `usage_seq`); `FolderCache` keeps the newest by the store's write count (never by clock time). At 80% of the budget, automatic loads of folders without cached data pause (`FolderCache.auto_load_paused`, `FolderExplorer.auto_load_paused_path`; deliberate loads and cached folders still work) and `diskNearlyFull` asks once per crossing; Ignore lasts the session until usage rises another 10% of the budget. At startup an inventory restores saves still waiting from an earlier session, and the usage. `CacheDialogs` (`helab/views/CacheDialogs.py`) asks the cache's questions one at a time: Make room / Don't cache this folder now, Save update / Don't cache this update now, and the 80% warning. The Settings → Cache tab (`helab/views/CacheTab.py`) shows the inventory, clears by kind, purges by age and sets both budgets; every action asks first (`CacheTab.confirm`), and a changed disk budget is saved only after the store has recorded it (`CacheTab.apply_budget`). Large folders (`helab/utils/large_folder.py`): a load's or cached read's estimate is its TXY files' size on disk, unscaled; above the RAM budget or 10% of RAM, automatic loads never start (amber "Large folder · ~X in RAM" with **Load anyway…**) and deliberate ones ask (`LargeFolderDialog`); above 30% of RAM nothing loads. The tab decides from saved sizes before submitting (`FolderCache.large_estimate`, `FolderExplorer._large_blocked`), and helpers check again (`limits`, `allow_large`, `too_large` events). Folder flags (right-click › Don't cache / Don't auto-load this folder; store `folder_prefs`, `FolderCache.folder_prefs`) apply to one folder only, come with listings, and are never removed by Clear all, purges or making room; every dataset save checks `no_cache` in its transaction. File kinds (TXY, raw `d*.txt`) are matched, counted and sized from one table, `FILE_KINDS` (`helab/utils/file_kinds.py`). Design and later sessions (large-folder warning, cache move, folder flags): `roadmaps/cache-storage-and-settings.md`.

Cache dirs resolve via `QSettings` (`dir_caches` / `dir_temps`) to `DIR_CACHES` / `DIR_TEMPS` in `helab/utils/constants.py`; the cache folder can change while HeLab runs, so read it with `cache_dir()` (never `DIR_CACHES`). It changes only by moving the cache (Settings → General → Change…, `helab/views/CacheMover.py`, `helab/utils/cache_move.py`): every helper that opens the cache is held (`IOService.hold_cache`), the folder is renamed or copied and verified, `dir_caches` is saved and synced before the switch (`set_cache_dir`), and a crash at any step is recovered at the next start (in a helper) from `cache-move.json` in the app folder (`app_folder()`), before any cache opens. OS file locks there (`cache.lock`, `move.lock`, `instances/<pid>.lock`; `helab/utils/cache_locks.py`) keep other HeLabs away from a move; tests set `HELAB_APP_DIR_OVERRIDE`. Defaults are persistent per-user folders (`default_app_dir`): macOS `~/Library/Caches/HeLab/{caches,temps}`, Windows `%LOCALAPPDATA%\HeLab\{caches,temps}`, else `~/.cache/HeLab`. A saved path is used only if a probe file can be written there. A cache folder on a network or synced folder (`helab/utils/cache_location.py`) is refused at startup: HeLab uses the default for that session and says why (`cache_dir_refused()`), leaving the setting for the user to change. Older `helab_<kind>_*` folders in the system temp dir (which the OS may delete) are renamed to the default on launch. Tests never touch these: `tests/conftest.py` sets `HELAB_DIR_*_OVERRIDE` to private temp folders.

The active browser additionally uses session-only `FolderCache` (`helab/utils/folder_cache.py`), shared by models using the same IOService. Completed directory snapshots have a 10-second freshness window; explicit refresh bypasses it. Shared scan/load/resolve jobs have per-tab subscriptions, so closing one tab does not cancel another's work. Datasets share read-only NumPy arrays with private dictionaries per tab; analysis code that intentionally modifies an array must call `.copy()`. The RAM budget (Settings → Cache, steps of 1/128 of RAM, default 1/8; `FolderCache.set_ram_budget`) evicts datasets no tab shows, least recently used first, while open tabs pin their current datasets. Directory snapshots are bounded to 256 folders and 100,000 retained entries. This memory store supplements the compressed disk cache and **never reads disk during rendering**.

Persisted folder metadata lives in the store's record tables, separate from datasets, and is **written only by isolated helpers**: compact basic-scan summaries (`folder_summaries`: counts, per-kind `files` with TXY sizes, status, signature, scan date) and basic-scan failure history (`scan_histories`, `helab/utils/scan_history.py`). A failure is the final outcome after all attempts; cancellation, queue rejection and metadata-save errors are not failures. **Every automatic basic-scan entry point must honour the failure flag**, and only a fresh successful scan clears it. Defaults, edge cases and display: `.ai/memory/results/basic-scan-defaults-and-failures.md`.

A folder's status shown in the tree can be **derived from its subfolders** (`something` if any listed subfolder has data; `nothing` only when the listing is complete and all were checked and empty) without changing its own `report`, which alone decides loading. Derivation reads only direct subfolders' in-memory statuses — never recursive. The result is saved in the store's `subtrees` table (via `subtree_save`) so it shows after a restart without listing the folder; listings attach each subfolder's saved result. Rules and tooltip wording: `.ai/memory/results/subfolder-derived-status.md`.

**UI:** Model-View pattern. The active `FolderExplorer` uses `SnapshotFileSystemModel` (`helab/models/SnapshotFileSystemModel.py`), a `QAbstractItemModel` that only reads memory during rendering — badges, tooltips, summaries and relative ages must never touch the source filesystem, the disk cache, or submit I/O. Directory contents are scanned on selection or expansion; an unlisted folder whose saved summary has no subfolders (`has_dirs`) shows no expand arrow until selecting it (or a load's listing) finds some; automatic basic scanning of visible folders is off by default and never rescans folders with saved results. Freshness indicators are hints only and never schedule scans or loads. Navigation and direct path entry stay available during I/O. The folder summary panel, cache-freshness icons and their wording are described in `.ai/memory/results/folder-summary-indicators.md`. The main window (`helab/views/HelabMainWindow.py`) uses dockable panels: left tree view with **Folder details** (`helab/views/FolderDetailsPanel.py`) below it, right properties panel, center plot area. Folder details shows the current tab's selected folder, its load (state, progress, files, elapsed time and time left, rate) and the loaded dataset, plus the tab's and app-wide I/O activity (State names the file being read and Files what is left; All I/O names a single running load's folder and a click shows it in its tab, and its tooltip lists each running helper with its tab, progress, file and time, `IOService.request_note`); the plot area keeps only a one-line hint (`CentralHint`, room for later tips). The status bar is short: this tab's main activity (`FolderExplorer.activity_brief`) │ app-wide counts (`IOService.activity_counts`); full wording is in its tooltip and Folder details. A load's running time and estimate come from `LoadClock` (`helab/utils/load_clock.py`) on the shared job: queued and paused time are excluded, and the rate counts only TXY files actually read (`read_bytes`/`read_files`/`total_read_bytes` in the helper's progress events), and a read with no progress for 5 s shows "no progress for M:SS" instead of an estimate.

**Script system:** Analysis scripts live in `helab/scripts/`. Each script inherits from `HelabAnalysisScript` (`helab/scripts/base.py`) and implements `get_metadata()`, `get_actions()`, `execute_action()`. Scripts are discovered dynamically by `ScriptsManager` (`helab/scripts/scripts_manager.py`) via `importlib.util`, scanning a directory for `.py` files and grouping loaded scripts by their `ScriptMetadata.group`. The right-hand panel (`ScriptTreeSelector`) loads `helab/scripts/examples/` by default; `helab/scripts/legacy_plotly/` holds older lab Plotly figures. Unmaintained plotting-library prototypes are in `dev/plotting-prototypes/`, outside the package.

**Data loading:** The active browser loads TXY data in `helab/io_helper.py`, streams per-shot results through local artifacts read by daemon threads, and retains the existing dictionary-of-float64-arrays format. It stores Blosc-compressed dictionaries as dataset files in the store, with per-shot `(size, mtime)` fingerprints, sizes and `last_used` in the `datasets` row: when a folder changes, unchanged shots are reused from the cache and only new/modified TXY files are read, then the merged dataset is written back (load source `merged`). When an open tab still holds the folder's dataset, `FolderCache` sends its per-shot fingerprints with the load (`memory`); the helper skips those shots entirely (`memory_shots`, load source `updated`), sends `loaded` first, and only then rewrites the compressed disk cache in the background (`disk_cached` event). Cache reads/writes and compression run outside the GUI process.

**Visualization:** Plotly is used for interactive 3D scatter; Matplotlib for publication-quality output. PyQtGraph is available for fast real-time plots. Avoid PyVista/VisPy (known data-point issues with large files). `helab/utils/dash_server.py` runs a background-thread Dash server (`127.0.0.1:8050`) to serve interactive Plotly figures in a browser tab via `/plot/<id>` routes.

**Legacy submodule:** `legacy/tdc_autoconverter` (git submodule from `HeBECANU/tdc_autoconverter`) is a MATLAB TDC data auto-converter kept for reference/compatibility, not part of the Python package.

**Settings persistence:** Uses `QSettings` with org `ANU_HE_BEC_GROUP`, app `HeLab` (`helab/utils/constants.py`). macOS plist: `~/Library/Preferences/com.anu-he-bec-group.HeLab.plist` (Qt derives the name from the org). Tests must not create native settings stores; pass a tmp-dir `QSettings(path, IniFormat)` instead.

## CI/CD

`.github/workflows/dev-cicd.yml` runs required Python 3.13 test/build matrices on
macOS, Windows and Ubuntu for every branch push and PR to `main`. Separate
Python 3.11, 3.12 and 3.14 compatibility matrices run only on PRs to `main`,
with soft failures. Shared steps live in `ci-test.yml` and `ci-build.yml`, with
Codecov uploads. Compatibility matrices expand on pushes, but pass `enabled: false`
to the called jobs, recording individual skips without starting runners. All
matrices disable fail-fast; required failures do not cancel
other OS tests/builds. All four matrices depend on branch/version selection;
release waits for all four, but only required matrices and version selection
must succeed (compatibility skips/failures are non-blocking). A new package
version on `main` creates an explicit tag and a draft
release; tag pushes do not
trigger releases. `python -m helab.release` validates/selects the version in CI.
`python -m helab.release_draft` validates archives and resumes draft uploads. API
errors fail selection; they never mean "no release". Only authenticated main runs
query release state. Build jobs may target an older tagged SHA during recovery;
the normal test jobs still check the current workflow commit, and recovery builds
add Python 3.13 tests of the tagged commit on each OS.
