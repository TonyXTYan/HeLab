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

**UI:** Model-View pattern. `HelabFileSystemModel` (`helab/models/HelabFileSystemModel.py`) extends `QFileSystemModel`. The main window (`helab/views/HelabMainWindow.py`) uses dockable panels: left tree view, right properties panel, center plot area. Signals are throttled (`helab/workers/HelabFSModelThrottleDataChangedEmit.py`) to avoid flooding the GUI thread.

**Script system:** Analysis scripts live in `helab/scripts/`. Each script inherits from `HelabAnalysisScript` (`helab/scripts/base.py`) and implements `get_metadata()`, `get_actions()`, `execute_action()`. Scripts are discovered dynamically by `ScriptsManager` (`helab/scripts/scripts_manager.py`) via `importlib.util`, scanning a directory for `.py` files and grouping loaded scripts by their `ScriptMetadata.group`.

**Data loading:** `LoadFolderToRamWorker` (`helab/workers/LoadFolderToRamWorker.py`) lazily loads large datasets with streaming decompression (zstandard, blosc, lz4) and cancellation support.

**Visualization:** Plotly is used for interactive 3D scatter; Matplotlib for publication-quality output. PyQtGraph is available for fast real-time plots. Avoid PyVista/VisPy (known data-point issues with large files). `helab/utils/dash_server.py` runs a background-thread Dash server (`127.0.0.1:8050`) to serve interactive Plotly figures in a browser tab via `/plot/<id>` routes.

**Legacy submodule:** `legacy/tdc_autoconverter` (git submodule from `HeBECANU/tdc_autoconverter`) is a MATLAB TDC data auto-converter kept for reference/compatibility, not part of the Python package.

**Settings persistence:** Uses `QSettings` with org `ANU_HE_BEC_GROUP`, app `HeLab` (sandbox variant: `Helab_SANDBOX`). macOS plist: `~/Library/Preferences/com.anu.HeLab.plist`.

## CI/CD

`.github/workflows/dev-cicd.yml` runs the full test matrix (macOS, Windows, Ubuntu × Python 3.10–3.13) with coverage upload to Codecov, and builds PyInstaller releases on git tags.
