# HeLab Agent Notes

HeLab (Helium Experiment Lab Analysis Board) is a PyQt6 desktop GUI application for real-time scientific data analysis in the ANU Helium BEC lab. It monitors experiment data folders, runs pluggable analysis scripts, and renders interactive visualizations.

Two repos exist: this one (`TonyXTYan/HeLab`) is the development branch; `HeBECANU/HeLab` is the stable lab deployment.

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
mypy helab/
pyright
```

`pyrightconfig.json` and `mypy.ini` exclude `helab/scripts/legacy_plotly/` from type checks.

## Building executables

```bash
pyinstaller HeLab.spec --clean -y    # all platforms
```

The `.spec` file produces `HeLab.app` on macOS (bundle ID `au.edu.anu.he-bec-lab`).

## Architecture

**Package layout:** `helab/models/`, `helab/views/`, `helab/workers/`, `helab/scripts/`, `helab/utils/`

**Responsive filesystem I/O:** The active folder browser uses `IOService` (`helab/utils/io_service.py`) and isolated `helab/io_helper.py` processes. Requests are deduplicated, queues and concurrency are bounded, and cancellation/deadlines never wait on the GUI thread. Daemon reader threads deliver results through a bounded queue; a Qt timer applies small batches. Source folders are never queried by the GUI model. The frozen helper entry point in `helab/main.py` must run before imports that initialize GUI services, caches, or Dash. `GUIWatchdog` records event-loop stalls and dumps thread stacks independently of GUI timers.

Folder loads run one at a time across tabs, with no overall folder deadline. Each file has 15-, 20-, and 30-second timeout attempts; successful file progress resets the timer for the next file. Timed-out helpers restart using completed shots from RAM after fingerprint validation. Other I/O requests use the same three timeout attempts for the request. Cancellation stops retries, and retries wait for the previous helper to exit.

**Threading:** Three `QThreadPool` instances in `helab/utils/threading_setup.py`:
- `thread_pool_general` — general tasks (½ CPU count)
- `thread_pool_load_data_ram` — data loading (¼ CPU count)
- `thread_pool_gui_update` — GUI updates (½ CPU count)

Workers are tracked in a `SynchronisedDict` for graceful cancellation on shutdown.

**Caching:** Three `diskcache.FanoutCache` instances (`helab/utils/caching_setup.py`):
- `status_cache` — file status info (2 GB)
- `os_file_system_cache` — OS operations (used by the `helab/utils/os_cached.py` memoized wrappers around `os.listdir`/`os.scandir`)
- `data_ram_cache` — loaded data (8 GB)

Cache dirs resolve via `QSettings` with fallback candidates; configured via `DIR_TEMPS` / `DIR_CACHES` in `helab/utils/constants.py`.

The active browser additionally uses session-only `FolderCache` (`helab/utils/folder_cache.py`), shared by models using the same IOService. Completed directory snapshots have a 10-second freshness window; explicit refresh bypasses it. Shared scan/load/resolve jobs have per-tab subscriptions, so closing one tab does not cancel another's work. Datasets share read-only NumPy arrays with private dictionaries per tab; analysis code that intentionally modifies an array must call `.copy()`. The 512 MiB array-data budget evicts unused datasets, while open tabs pin their current datasets. Directory snapshots are bounded to 256 folders and 100,000 retained entries. This memory store supplements the existing compressed disk cache and never reads disk during rendering.

**UI:** Model-View pattern. The active `FolderExplorer` uses `SnapshotFileSystemModel` (`helab/models/SnapshotFileSystemModel.py`), a `QAbstractItemModel` that only reads memory during rendering. Folders load on selection or expansion; refresh traverses the current view's expanded branches in batches. Loading indicators, timeout/retry states, and direct path entry keep navigation available during I/O. The main window (`helab/views/HelabMainWindow.py`) uses dockable panels: left tree view, right properties panel, center plot area. The earlier `HelabFileSystemModel` extending `QFileSystemModel` and its worker/throttling classes remain for compatibility and legacy tests.

**Script system:** Analysis scripts live in `helab/scripts/`. Each script inherits from `HelabAnalysisScript` (`helab/scripts/base.py`) and implements `get_metadata()`, `get_actions()`, `execute_action()`. Scripts are discovered dynamically by `ScriptsManager` (`helab/scripts/scripts_manager.py`) via `importlib.util`, scanning a directory for `.py` files and grouping loaded scripts by their `ScriptMetadata.group`.

**Data loading:** The active browser loads TXY data in `helab/io_helper.py`, streams per-shot results through local artifacts read by daemon threads, and retains the existing dictionary-of-float64-arrays format. It stores compatible Blosc-compressed dictionaries in `data_ram_cache`, with per-shot `(size, mtime)` fingerprint metadata: when a folder changes, unchanged shots are reused from the cache and only new/modified TXY files are read, then the merged dataset is written back (load source `merged`). When an open tab still holds the folder's dataset, `FolderCache` sends its per-shot fingerprints with the load (`memory`); the helper skips those shots entirely (`memory_shots`, load source `updated`), sends `loaded` first, and only then rewrites the compressed disk cache in the background (`disk_cached` event). Cache reads/writes and compression run outside the GUI process. `LoadFolderToRamWorker` remains available for legacy consumers.

**Visualization:** Plotly is used for interactive 3D scatter; Matplotlib for publication-quality output. PyQtGraph is available for fast real-time plots. Avoid PyVista/VisPy (known data-point issues with large files). `helab/utils/dash_server.py` runs a background-thread Dash server (`127.0.0.1:8050`) to serve interactive Plotly figures in a browser tab via `/plot/<id>` routes.

**Legacy submodule:** `legacy/tdc_autoconverter` (git submodule from `HeBECANU/tdc_autoconverter`) is a MATLAB TDC data auto-converter kept for reference/compatibility, not part of the Python package.

**Settings persistence:** Uses `QSettings` with org `ANU_HE_BEC_GROUP`, app `HeLab` (`helab/utils/constants.py`). macOS plist: `~/Library/Preferences/com.anu-he-bec-group.HeLab.plist` (Qt derives the name from the org). Tests must not create native settings stores; pass a tmp-dir `QSettings(path, IniFormat)` instead.

## CI/CD

`.github/workflows/dev-cicd.yml` runs the full test matrix (macOS, Windows, Ubuntu × Python 3.10–3.13) with coverage upload to Codecov, and builds PyInstaller releases on git tags.
