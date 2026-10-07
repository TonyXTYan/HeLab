# HeLab Agent Notes

HeLab (Helium Experiment Lab Analysis Board) is a PyQt6 desktop GUI application for real-time scientific data analysis in the ANU Helium BEC lab. It monitors experiment data folders, runs pluggable analysis scripts, and renders interactive visualizations.

Two repos exist: this one (`TonyXTYan/HeLab`) is the development branch; `HeBECANU/HeLab` is the stable lab deployment.

## Working conventions

- Address the user as "🎓Tony" in conversation.
- Always ask Tony before running `git commit`. Staging, diffing and reviewing are fine without asking.
- Every Git commit must include both a concise subject and a meaningful description in the message body, separated by a blank line. The description should explain what changed and why, and include relevant validation.

## AI workspace (`.ai/`)

- `.ai/coding-workspace.md` — shared AI-workspace conventions for Tony's repos (what goes in memory vs sessions, working rules).
- `.ai/memory/MEMORY.md` — index of project memory. Read it first; load individual files only when relevant. Settled design decisions (with the reasons and Tony's chosen wording/icons) live in `.ai/memory/results/`; this file keeps only the codebase rules.
- `.ai/sessions/YYYY-MM-DD-<tool>-<title>/` — per-session notes. `.ai/session-export-codex/` and `.ai/session-export-claude/` — raw exported transcripts. Search these for history; don't auto-load them.
- `.ai/temp/` and `.ai/local/` are gitignored scratch space.

## Setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install -e .
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

## Architecture

**Package layout:** `helab/models/`, `helab/views/`, `helab/workers/`, `helab/scripts/`, `helab/utils/`

**Responsive filesystem I/O:** The active folder browser uses `IOService` (`helab/utils/io_service.py`) and isolated `helab/io_helper.py` processes. Requests are deduplicated, queues and concurrency are bounded, and cancellation/deadlines never wait on the GUI thread. Daemon reader threads deliver results through a bounded queue; a Qt timer applies small batches. Source folders are never queried by the GUI model. The frozen helper entry point in `helab/main.py` must run before imports that initialize GUI services, caches, or Dash. `GUIWatchdog` records event-loop stalls and dumps thread stacks independently of GUI timers.

Rules for the shared I/O queue (decisions, timings and the stopping-helper display: `.ai/memory/results/folder-io-queue.md`):
- One app-wide queue with two lanes. The **foreground** lane runs the current tab's listings (`list`, `resolve`) and its selected load (in queue mode, its queued loads one at a time): one listing and one load at once, at most 3 processes including stopping ones, and it never waits for background work. The **background** lanes (Settings → General, "Simultaneous background I/O operations", default 1) run everything else: background loads, `details`, basic scans, cache writes and history saves. Navigation and loads precede bulk scans; FIFO within each group. `FolderCache` decides the lane (`foreground_owners`, set by the current `FolderExplorer`); switching tabs makes the old tab's work background.
- While the foreground works, background loads and scans **pause cooperatively** (a `pause` file in the helper's private folder, checked between files/entries; `paused`/`resumed` events) and no new ones start; the selected load pauses while the tab lists a folder. Resume is 0.5 s after the foreground goes idle; a listing silent for 3 s no longer counts. A paused helper keeps its slot and its no-progress timer is frozen. A load leaving the foreground takes a free background slot, or is stopped and requeued to restart from its RAM shots.
- A helper occupies its slot **until its exit is confirmed** by the daemon reaper's in-memory exit flag — including cancelled/timed-out helpers and background cache writers. Never free a slot on message delivery or reader completion; duplicate exit notifications are matched by request identity.
- Browsing is two steps. `list` (one scandir, names only, no source stat) gives counts and status at once, plus each subfolder's saved summary, history and cache flags from the local cache — so saved badges appear immediately and automatic visible scans don't redo them. `details` (the full scan) follows in the background for the signature, dates and subfolder identities (a replaced folder's saved summary is then dropped). It is skipped while a load of a folder **without subfolders** runs — the load sends and saves the same folder summary. A listing never writes to the cache and never clears a scan failure; a listing error records one. An empty `signature` means unknown, never "changed".
- Timeouts measure **time without progress**; helpers send heartbeats while listing or checking files. Listings, scans and a load's listing phase get one 60 s attempt with no retry (a timeout is one scan failure). Only a load's per-file reads retry, with 15/20/30 s attempts per file. Right-click Retry / Refresh and the status-line Retry list one folder with no timeout, showing elapsed time and a Cancel action; a load retry keeps its per-file timeouts. **A retry never runs beside the attempt it replaces** — it is held until that helper exits. Cancellation stops retries. Timed-out loads restart from completed RAM shots after fingerprint validation.

**Folder icons:** The name column starts with a generic folder icon. Visible rows get native folder/volume icons (including macOS custom icons) from a separate `icons` helper in the shared background I/O lane, in batches of at most 64 with a 5-second no-progress timeout and cooperative pausing. `FolderCache` holds up to 4096 icons in session memory, shared across tabs; failed lookups retain the generic icon until Refresh. Icon lookup never runs during listing or model rendering. Refresh clears visible icons for another lookup. Keep the native Qt platform plugin in the helper; offscreen Qt cannot supply macOS custom icons.

**Threading:** Three `QThreadPool` instances in `helab/utils/threading_setup.py`:
- `thread_pool_general` — general tasks (½ CPU count)
- `thread_pool_load_data_ram` — data loading (¼ CPU count)
- `thread_pool_gui_update` — GUI updates (½ CPU count)

Workers are tracked in a `SynchronisedDict` for graceful cancellation on shutdown.

**Caching:** Three `diskcache.FanoutCache` instances (`helab/utils/caching_setup.py`):
- `status_cache` — file status info (2 GB)
- `os_file_system_cache` — OS operations (used by the `helab/utils/os_cached.py` memoized wrappers around `os.listdir`/`os.scandir`)
- `data_ram_cache` — loaded data (8 GB)

Cache dirs resolve via `QSettings` (`dir_caches` / `dir_temps`) to `DIR_CACHES` / `DIR_TEMPS` in `helab/utils/constants.py`. Defaults are persistent per-user folders (`default_app_dir`): macOS `~/Library/Caches/HeLab/{caches,temps}`, Windows `%LOCALAPPDATA%\HeLab\{caches,temps}`, else `~/.cache/HeLab`. A saved path is used only if a probe file can be written there. Older `helab_<kind>_*` folders in the system temp dir (which the OS may delete) are renamed to the default on launch. Tests never touch these: `tests/conftest.py` sets `HELAB_DIR_*_OVERRIDE` to private temp folders.

The active browser additionally uses session-only `FolderCache` (`helab/utils/folder_cache.py`), shared by models using the same IOService. Completed directory snapshots have a 10-second freshness window; explicit refresh bypasses it. Shared scan/load/resolve jobs have per-tab subscriptions, so closing one tab does not cancel another's work. Datasets share read-only NumPy arrays with private dictionaries per tab; analysis code that intentionally modifies an array must call `.copy()`. The 512 MiB array-data budget evicts unused datasets, while open tabs pin their current datasets. Directory snapshots are bounded to 256 folders and 100,000 retained entries. This memory store supplements the compressed disk cache and **never reads disk during rendering**.

Persisted folder metadata lives in `data_ram_cache` under versioned keys, separate from arrays, and is **written only by isolated helpers**: compact basic-scan summaries (counts, status, signature, scan date) and basic-scan failure history (`helab/utils/scan_history.py`, `folder-scan-history-v1`). A failure is the final outcome after all attempts; cancellation, queue rejection and metadata-save errors are not failures. **Every automatic basic-scan entry point must honour the failure flag**, and only a fresh successful scan clears it. Defaults, edge cases and display: `.ai/memory/results/basic-scan-defaults-and-failures.md`.

**UI:** Model-View pattern. The active `FolderExplorer` uses `SnapshotFileSystemModel` (`helab/models/SnapshotFileSystemModel.py`), a `QAbstractItemModel` that only reads memory during rendering — badges, tooltips, summaries and relative ages must never touch the source filesystem, the disk cache, or submit I/O. Directory contents are scanned on selection or expansion; automatic basic scanning of visible folders is off by default and never rescans folders with saved results. Freshness indicators are hints only and never schedule scans or loads. Navigation and direct path entry stay available during I/O. The folder summary panel, cache-freshness icons and their wording are described in `.ai/memory/results/folder-summary-indicators.md`. The main window (`helab/views/HelabMainWindow.py`) uses dockable panels: left tree view, right properties panel, center plot area. The earlier `HelabFileSystemModel` extending `QFileSystemModel` and its worker/throttling classes remain for compatibility and legacy tests.

**Script system:** Analysis scripts live in `helab/scripts/`. Each script inherits from `HelabAnalysisScript` (`helab/scripts/base.py`) and implements `get_metadata()`, `get_actions()`, `execute_action()`. Scripts are discovered dynamically by `ScriptsManager` (`helab/scripts/scripts_manager.py`) via `importlib.util`, scanning a directory for `.py` files and grouping loaded scripts by their `ScriptMetadata.group`.

**Data loading:** The active browser loads TXY data in `helab/io_helper.py`, streams per-shot results through local artifacts read by daemon threads, and retains the existing dictionary-of-float64-arrays format. It stores compatible Blosc-compressed dictionaries in `data_ram_cache`, with per-shot `(size, mtime)` fingerprint metadata: when a folder changes, unchanged shots are reused from the cache and only new/modified TXY files are read, then the merged dataset is written back (load source `merged`). When an open tab still holds the folder's dataset, `FolderCache` sends its per-shot fingerprints with the load (`memory`); the helper skips those shots entirely (`memory_shots`, load source `updated`), sends `loaded` first, and only then rewrites the compressed disk cache in the background (`disk_cached` event). Cache reads/writes and compression run outside the GUI process. `LoadFolderToRamWorker` remains available for legacy consumers.

**Visualization:** Plotly is used for interactive 3D scatter; Matplotlib for publication-quality output. PyQtGraph is available for fast real-time plots. Avoid PyVista/VisPy (known data-point issues with large files). `helab/utils/dash_server.py` runs a background-thread Dash server (`127.0.0.1:8050`) to serve interactive Plotly figures in a browser tab via `/plot/<id>` routes.

**Legacy submodule:** `legacy/tdc_autoconverter` (git submodule from `HeBECANU/tdc_autoconverter`) is a MATLAB TDC data auto-converter kept for reference/compatibility, not part of the Python package.

**Settings persistence:** Uses `QSettings` with org `ANU_HE_BEC_GROUP`, app `HeLab` (`helab/utils/constants.py`). macOS plist: `~/Library/Preferences/com.anu-he-bec-group.HeLab.plist` (Qt derives the name from the org). Tests must not create native settings stores; pass a tmp-dir `QSettings(path, IniFormat)` instead.

## CI/CD

`.github/workflows/dev-cicd.yml` runs the full test matrix (macOS, Windows, Ubuntu × Python 3.10–3.13) with coverage upload to Codecov, and builds PyInstaller releases on git tags.
