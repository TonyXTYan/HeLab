# Handoff: byte units by OS (`agent/byte-units`)

Worker: Gauge (Claude Code), 2026-10-29. Brief: [brief.md](brief.md). Decision Q26.1, item A26.1.

## What changed

- **One helper** (`helab/utils/number_format.py`, still standard library only):
  `byte_size(num, kind, *, platform=None)` with `kind: ByteKind = Literal["disk", "ram"]`,
  **required** (no default; mypy and pyright catch a call without it). Disk: SI (`B kB MB GB TB`)
  on macOS and Linux, powers of 1024 (`B KiB MiB GiB TiB`) on Windows; RAM: powers of 1024 on
  every OS. Same significant figures as before (whole numbers from 99.95 up, else one decimal;
  the next unit past 999.5 in both systems, so at most three digits). Also `binary_units(kind,
  platform)`, `byte_unit(power, kind, platform)` (`(10**9, "GB")` / `(2**30, "GiB")`) and
  `scaled(num, kind, platform)`, which `time_format.byte_rate(per_second, *, platform=None)` uses
  (rates are disk; same three significant figures). Through `scaled`, rates now go up to TB/s
  (TiB/s on Windows); before, they stopped at GB/s (review nit 5).
- **How the platform is chosen at run time:** `number_format.PLATFORM`, set once at import to
  `sys.platform`, or to `HELAB_UNITS_PLATFORM_OVERRIDE` when that is set (`units_platform`).
  Windows is `"win32"`. A call with `platform=` uses that instead; a call without reads
  `PLATFORM` at call time, so a test can monkeypatch it. The override also lets a developer see
  Windows' units on a Mac (`HELAB_UNITS_PLATFORM_OVERRIDE=win32 helab`). Helpers inherit the
  environment, so they agree with the GUI.
- **Tests pin macOS's units:** `tests/conftest.py` sets `HELAB_UNITS_PLATFORM_OVERRIDE=darwin`
  (beside the other overrides), so the ~70 existing label assertions compare the same on Windows
  CI. Windows' units are tested explicitly on every OS (helper, rate, default, minimum, the disk
  budget spin box), and `units_platform({})` is checked to be `sys.platform`.
- **Defaults and minimums:** `settings_defaults.default_disk_budget(platform=None)` = `8 *
  byte_unit(3, "disk")[0]` (8 GB / 8 GiB, Q22.7 keeps 8); the table's row takes this platform's
  value at import, so `settings_defaults.py` stays the one place (it now imports `number_format`,
  standard library only; docstring updated). `constants.MIN_DISK_BUDGET = byte_unit(3, "disk")[0]`
  (1 GB / 1 GiB), `MIN_RAM_BUDGET = 2**30` (1 GiB everywhere; `ram_step_range`'s minimum step
  follows: on a 16 GB machine it is 9 steps, was 8).
- **Spin boxes:** Settings → Cache's disk budget shows the platform's unit (`" GB"` / `" GiB"`, steps
  of half a unit, `CacheTab.disk_unit`). A stored budget keeps its bytes: `show_disk_budget(bytes)`
  remembers what it showed, and `disk_budget_bytes()` returns the stored bytes while the box still
  shows that value (8 GB on Windows shows 7.5 GiB and is saved as 8 GB unless changed). Moved off a
  stored value that isn't on the half-unit grid, the box snaps to the grid at once
  (`_snap_disk_budget`), so the value shown is the value saved (20 GB on Windows shows 18.6 GiB; one
  step up shows 19.0 and saves 19 GiB; review finding 1). A stored budget under the OS's minimum
  (1 GB on Windows) reads as the minimum (1 GiB) and the next Save writes it (review finding 2;
  Q~1). "Reset all settings…" uses `show_disk_budget` (`SettingsDialog`). `CacheTab.GB` is gone. The RAM budget box
  reads `"16.0 GiB (1/8 of 128 GiB)"` and a typed number is GiB.
- **Hard-coded units:** the status bar's RAM (`HelabMainWindow.update_status_bar_right`) and the
  Debug memory window are GiB / MiB (RAM). Log sizes are disk: `app_log.MB, app_log.MB_UNIT =
  byte_unit(2, "disk")`, so rotation (1), the old-logs question (50) and its trim (20) are MB on
  macOS/Linux and MiB on Windows, and the texts say so (`OldLogs.QUESTION` gained `{unit}`;
  Settings → General's log tooltip). (Choice, see "For the Reviewer".)
- **3.11 compat:** kinds inside f-string fields use single quotes (`{byte_size(n, 'disk')}`), and
  `FolderExplorer._ask_remove_cached`'s nested f-string became a local, so the files still parse on
  Python 3.11 (checked with `ast.parse` under 3.11.16).

## Sorting: every call (module, line at `HEAD`, kind)

66 `byte_size` calls and 1 `byte_rate` (lines at the merge with TXY Index, `8a03bbe`). RAM: the RAM budget, In use, "in RAM when loaded", large
folders' RAM estimate, plots' memory, RAM budget drops. Disk: the store, its budget, cached data
and results, folders, files, converted TXY, I/O traces, free space, rates.

| Module | Line | Kind | What |
|---|---|---|---|
| `helab/utils/folder_cache.py` | 4235 | disk | Cached analysis badge: results' size |
| `helab/utils/cache_move.py` | 282 | disk ×2 | Move refused: needs / free on the volume |
| `helab/models/SnapshotFileSystemModel.py` | 460, 461 | ram | Large / too large folder: ~size in RAM |
| `helab/views/explorer_text.py` | 15, 16 | ram | the same, summary text |
| `helab/views/LargeFolderDialog.py` | 20 | ram | "would take about X in RAM (its TXY files' size on disk)" |
| `helab/views/LargeFolderDialog.py` | 21 | ram ×2 | RAM budget, the computer's RAM |
| `helab/views/HelabMainWindow.py` | 625 | disk | earlier I/O traces' size |
| `helab/views/HelabMainWindow.py` | 716 | ram | RAM budget lowered: dropped folders' size |
| `helab/views/FolderExplorer.py` | 1565 | disk (`byte_rate`) | load read rate |
| `helab/views/FolderExplorer.py` | 2317 | disk | Don't cache: remove its cached data (size) |
| `helab/views/CacheMover.py` | 218 | disk | moving the cache (size) |
| `helab/views/DataRootsTab.py` | 272, 289, 362, 377 | disk | a root's cached data and saved results |
| `helab/views/CacheTab.py` | 87 | ram ×2 | RAM budget box: budget and total RAM |
| `helab/views/CacheTab.py` | 476, 664, 667, 668 | disk | converted TXY: Clear, row, per-base tooltip (TXY Index's rows: units only) |
| `helab/views/CacheTab.py` | 495, 505, 520, 531, 543 | disk | Clear / purge confirmations |
| `helab/views/CacheTab.py` | 569, 570, 571 | ram | In use: total, shown in tabs, plots |
| `helab/views/CacheTab.py` | 584, 594, 625 | disk | purge estimates, retired files |
| `helab/views/CacheTab.py` | 630 | disk ×2 | usage of budget |
| `helab/views/CacheTab.py` | 635, 650 | disk | cached data, cached analysis rows |
| `helab/views/CacheTab.py` | 641 | ram | "About X in RAM when loaded" (row tooltip) |
| `helab/views/CacheTab.py` | 730, 733, 735 | disk | Lower the disk budget? |
| `helab/views/CacheDialogs.py` | 38, 55 | disk | Make room (datasets, results) |
| `helab/views/CacheDialogs.py` | 201, 222 | disk ×3 | Not enough room: entry, usage, budget |
| `helab/views/CacheDialogs.py` | 215 | disk ×3 | Save update: growth, usage, budget |
| `helab/views/CacheDialogs.py` | 290 | disk ×2 | 80% full: usage, budget |
| `helab/views/plots/instance.py` | 459 | disk | Saved a large result in the disk cache |
| `helab/views/plots/cached_results.py` | 507 | disk | the same, logged |
| `helab/views/plots/workspace.py` | 109, 110 | ram ×4 | RAM budget notice: total, budget, folders, plots |
| `helab/views/plots/workspace.py` | 125, 126 | ram | RAM budget tooltip: total, budget |
| `helab/views/plots/workspace.py` | 129, 134 | ram | biggest plots, folders in RAM |

Hard-coded units outside the helper: `HelabMainWindow.py` 348–356 (ram, GiB), `MemoryUsageWindow.py`
(ram, MiB), `app_log.py` 29/123 + `OldLogs.py` + `SettingsDialog.py` log tooltip (disk, MB/MiB),
`CacheTab.py` disk budget box (disk) and RAM box parse (ram).

Left as they are (not shown sizes, or not mine): `result_cache.LARGE_RESULT_BYTES = 50 * 10**6` (a
threshold; never printed as a number); comments that estimate memory in MB (`trends.py`,
`correlations.py`, `density_images.py`, `mlx_gpu.py`); `helab/convert/timing.py`'s SI MB/s
(developer harness, the TXY Index floor's package).

## Checks

On the merged state (`f58e161`: this work plus `origin/dev/v0.0.7` at `9f0b21f`), macOS, Python 3.13:

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: **8201 passed, 669 skipped,
  2 warnings, no RERUN** (116 s).
- The same without `--basetemp` (outside the checkout): **8201 passed, 669 skipped, 2 warnings, no
  RERUN** (122 s).
- `mypy helab/ --strict`, `mypy tests --strict`, both again with `--platform win32`: no issues;
  `pyright helab tests` and `pyright --pythonplatform Windows helab tests`: 0 errors.
- Every changed file parses with Python 3.11.16 (`ast.parse`; compat CI).
- An earlier full run before the merge had one failure, mine: `test_memroyUsageWindow.py::
  test_memory_usage_window_initialization` (`assert 0.95367431640625 == 1.0`, the window now in MiB);
  its 5 RERUNs were that same assertion. Fixed in `37896da`; no RERUN since.
- Offscreen render (floor-env sourced, a throwaway settings ini) with
  `HELAB_UNITS_PLATFORM_OVERRIDE=win32` and `darwin`: Settings → Cache's budget shows "7.5 GiB" / "8.0 GB"
  for a saved 8 GB; the RAM box "16.0 GiB (1/8 of 128 GiB)" on both; the large-folder dialog in GiB.
  Real Windows not run (M~1).

### After the review ([review.md](review.md): 3 minor, 2 nits, all addressed)

- Finding 1: `CacheTab._snap_disk_budget`, tested (`test_cache_tab.py`, Windows, 20 GB stored, `stepBy`).
- Finding 2: accepted as (a), tested; handoff text corrected; Q~1; `cache-store.md` wording above.
- Finding 3: `test_number_format.py::test_units_set_at_import_follow_the_platform`, a fresh
  interpreter with the override `win32`, `darwin`, and unset (`sys.platform`, so Windows CI runs
  Windows' units there): `MIN_DISK_BUDGET`, `DEFAULT_DISK_BUDGET`, the table row, `MIN_RAM_BUDGET`,
  `read_disk_budget` of a stored 1 GB, the box's minimum and suffix, Save, `app_log.MB`/`MB_UNIT`.
- Nits 4, 5: `testing.md` proposal (env seam), `byte_rate` up to TB/s noted.
- Checks: strict mypy helab + tests (also `--platform win32`), pyright (also Windows): clean. Full
  suite with `--basetemp=.ai/temp/pytest`: **8204 passed, 669 skipped, no RERUN** (125 s); without it:
  **8204 passed, 669 skipped, no RERUN** (117 s).
- CI run 40865344851 (head `28dc03c`): success, every non-skipped job passed. **One RERUN**, windows
  Tests (2/2) (job 123418722344): `test_plot_backends.py::test_2d_plots_draw_with_every_library[values0-Plotly-CountsPerShot]`,
  "worker 'gw3' crashed while running" it, passed on retry. Already in known-issues (line 98, first
  seen on run 40803552596); not related to units. Proposed: add this run as a second sighting there.
  No other job had a "rerun reasons" section.

### After merging TXY Index (`origin/dev/v0.0.7` at `c492242`, merge `8a03bbe`)

- `CacheTab.py` conflicted in two hunks (the Clear confirm text; the converted row's label, tooltip
  and button): TXY Index's logic and text kept (bases, newer, clearable, the per-base tooltip), every
  `byte_size` there given `"disk"`; its new bare calls in `tests/test_converter_tab.py` too. No
  `byte_size` call in `helab/` or `tests/` is left without a kind. Units only.
- Strict mypy helab + tests (also `--platform win32`), pyright (also Windows): clean. Full suite
  with `--basetemp=.ai/temp/pytest`: **8250 passed, 669 skipped, no RERUN** (136 s); without it:
  **8250 passed, 669 skipped, no RERUN** (150 s).
- CI run 40989130996 (head `1e5c166`).

## For the Reviewer

- `kind` is required, positional or keyword; `platform` is keyword-only.
- Log sizes follow the disk units, thresholds included (1/20/50 MiB on Windows). The alternative is
  to keep the SI thresholds and only relabel; I chose consistency with "defaults follow".
- A stored disk budget under the new minimum (an old 1 GB on Windows) reads as 1 GiB
  (`read_disk_budget`'s clamp, unchanged code), and **any Settings Save writes 1 GiB over it**, even
  with the box untouched (the earlier text here said otherwise; the review's finding 2 corrected it).
  Accepted (Coordinator, option (a)): Q26.1 (c) sets the minimum, the store already runs at 1 GiB from
  startup, and values under the minimum were rewritten the same way before. Tested in a fresh
  interpreter (`test_units_set_at_import_follow_the_platform`). For Tony: Q~1.
- `LargeFolderDialog` line 20 says "in RAM (its TXY files' size on disk)": sorted RAM, since the
  number is the RAM estimate.
- The Windows disk budget box shows a stored 8 GB as 7.5 GiB (one decimal); typing 7.5 back is
  "unchanged" (keeps 8 GB); any other value is half-GiB steps.

## Proposed doc changes (Coordinator applies)

- **AGENTS.md**, "The disk cache", replace the units line with: "Byte sizes go through
  `number_format.byte_size(n, kind)` (`kind` "disk" or "ram", required): disk sizes and rates SI
  (kB/MB/GB) on macOS and Linux and KiB/MiB/GiB on Windows, RAM in GiB everywhere (Q26.1)."
- **`cache-store.md`** line 15: "default 8 GB, SI (Q26.1 changes …), at least 1 GB" → "default 8 GB
  on macOS and Linux and 8 GiB on Windows (`settings_defaults.default_disk_budget`), at least 1 GB /
  1 GiB"; and "Every byte size HeLab shows is SI (…), and Settings → Cache edits the budget in GB =
  10^9; a saved budget keeps its bytes (Tony, 2026-10-26)" → "Byte sizes are disk or RAM
  (`number_format.byte_size(n, kind)`): disk SI on macOS/Linux and KiB/MiB/GiB on Windows, RAM in
  GiB everywhere (Q26.1); Settings → Cache edits the disk budget in GB or GiB (half-unit steps) and
  the RAM budget in GiB; a saved budget keeps its bytes while left as shown (`CacheTab.show_disk_budget`),
  and goes to the half-unit grid once changed; a budget under the OS's minimum (1 GB on Windows)
  reads as the minimum and is saved as it on the next Save."
  The platform: `number_format.PLATFORM` (`sys.platform`, or `HELAB_UNITS_PLATFORM_OVERRIDE`).
- **`settings.md`**: after "reads 8 GB wrong": "The disk budget's default is platform-dependent
  (`default_disk_budget()`, 8 GB / 8 GiB), evaluated once when the table is built; the RAM budget's
  minimum is 1 GiB."
- **`app-runtime-and-ui.md`** line 27: "`number_format.py` (SI byte sizes)" → "`number_format.py`
  (byte sizes by kind and OS, Q26.1)"; the status bar's RAM is GiB.
- **`testing.md`**, in the list of environment seams production reads (line 11, beside
  `HELAB_DIR_*_OVERRIDE`): "`HELAB_UNITS_PLATFORM_OVERRIDE` (`number_format.PLATFORM`, read once at
  import): the platform whose byte units HeLab shows, `sys.platform` when unset. conftest pins
  `darwin`, so labels compare the same on every OS; test Windows' units with `platform="win32"`, by
  patching `number_format.PLATFORM` (call time), or in a fresh interpreter for what is set at import
  (the disk budget's default and minimum, `app_log.MB`: `test_units_set_at_import_follow_the_platform`).
  `HELAB_UNITS_PLATFORM_OVERRIDE=win32 helab` shows Windows' units on a Mac; helpers inherit it."
- **Memory** `results/disk-cache-and-budgets.md` ("8 GB disk budget"): add "8 GiB on Windows
  (Q26.1)"; `caching-v2.md` already says units by OS.

## Follow-ups and manual checks (provisional IDs)

- **Q~1** (for Tony, decided for now by the Coordinator as (a)) A disk budget saved under the OS's
  minimum, in practice 1 GB on a Windows PC (the old minimum), becomes 1 GiB at the next Settings
  Save. (a) Accept: the minimum is 1 GiB (Q26.1 (c)) and HeLab already uses 1 GiB from startup; (b)
  keep 1 GB legal on Windows (the box's minimum 1 GiB, a stored 1 GB kept). Proposed: (a).

- **M~1** On Windows (lab PC or CI artefact), Settings → Cache shows "8.0 GiB" for a fresh setting,
  and an existing 8 GB setting shows "7.5 GiB" and stays 8 000 000 000 after Save; Folder details'
  rate reads MiB/s; the status bar RAM reads GiB.
- **A~2** The RAM budget box clips its text: Qt's `QAbstractSpinBox.sizeHint` measures at most 18
  characters, and "16.0 GiB (1/8 of 128 GiB)" is 25 (it was 23 as "17.2 GB (1/8 of 137 GB)", clipped
  as well; checked offscreen, widths 131 and 135 px). A `sizeHint` override on `RamBudgetSpinBox`
  measuring the longest of its texts would fix it; not done here (units only). For known-issues.
- **A~1** (optional) `result_cache.LARGE_RESULT_BYTES` (50 MB) could follow the disk unit like the
  log thresholds, if Tony wants every threshold by OS.
