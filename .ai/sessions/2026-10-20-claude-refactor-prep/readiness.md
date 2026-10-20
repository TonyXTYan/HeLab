# Refactor readiness and future-proofing (2026-10-20)

Cloud session (Claude), branch `agent/refactor-prep` from `dev/v0.0.6` at
`e908430`. Purpose: take stock before the next refactoring milestone
([plan](../../../roadmaps/refactoring.md), milestone 2 "split where work
collides") and propose the slices, their order and the decisions Tony needs to
make. Nothing in `helab/` is changed; the only code change is two test skips
(below). Four read-only surveys (io_helper; FolderCache/FolderExplorer; main
window and plot UI; standard vs DLD scripts) fed this note. Line numbers are at
`e908430`.

## Health

- **Tests (Linux cloud container, Python 3.13, `-n 4 --reruns 5 --reruns-delay 1`):**
  2181 passed, 7 skipped, 2 xfailed in 4 min 35 s. Two failed all six attempts,
  and both because the container runs as root, which ignores `chmod`:
  `test_constants.py::test_read_only_saved_folder_is_replaced` and
  `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`.
  They now skip under root, as `test_root_enable`, `test_root_duplicates` and
  `test_root_remove` already do (the cache-mover test still runs on Windows,
  where it ran before). All 10 reruns were those two tests: **no flaky reruns**
  otherwise. After the skips, both files: 37 passed, 2 skipped; strict mypy and
  pyright clean on them.
- **Typing:** strict mypy and pyright pass inside the suite (`test_typing.py`),
  the slowest tests at 17–35 s each; 8 `type: ignore` in `helab/`.
- **CI on `dev/v0.0.6`:** green on `e908430` and `43aa3de`; `d2833f1` and
  `919ff11` were red and were followed by green commits.
- **Size:** `helab/` 43.6k lines (without `legacy_plotly`), `tests/` 37.6k
  lines in 92 files. The hotspots grew fast since the 2026-10-14 survey:

  | File | 2026-10-14 | Now |
  |---|---:|---:|
  | `helab/io_helper.py` | 1442 | 3209 |
  | `helab/views/FolderExplorer.py` | 2112 | 2867 |
  | `helab/utils/folder_cache.py` | 1824 | 2790 |
  | `helab/models/ScriptTreeSelector.py` | — | 2055 |
  | `helab/utils/cache_store.py` | 1353 | 1736 |
  | `helab/views/HelabMainWindow.py` | 1283 | 1733 |
  | `helab/models/SnapshotFileSystemModel.py` | 1088 | 1166 |

## Where work collides now

1. **Plot UI: `ScriptTreeSelector.py`.** Every plot feature edits it. Only about
   340 of its 2055 lines are the script tree. The rest are `AnalysisDock`,
   `DockTabCloser`, the released-plot pictures, `AnalysisInstance` (550–1347:
   parameters, submit/finish, draw, constants, Live follow, release and
   reload), `PlotSettingsPanel` and `DragEnd`. Importing it pulls in both
   script groups and, through them, QtWebEngine, Dash and Matplotlib.
   `AnalysisInstance` reaches into the main window by attribute
   (`panel_right_top_plot_settings`, `dock_widgets`, `middle_mainwindow`) and
   duck-typed `getattr` (`live_feed`, `ram_budget`, `set_plot_result`,
   `update_plot_source`, …).
2. **Main window.** `HelabMainWindow` composes everything but also holds the
   plot-area presentation (1073–1221), the RAM-budget windows (691–757) and the
   Live feed bridge. Three test files (`test_live_plots`, `test_analysis_gui`,
   `test_plot_ram_budget`) skip its `__init__` and hand-build the plot area's
   attributes. That attribute set is the plot workspace's real interface.
3. **Standard vs DLD scripts, which have already drifted.** Transfer fractions'
   order detection is copied (standard 113–350, DLD 111–331; 358 identical
   lines). `6f71479` gave the standard version a reference spacing
   (`REFERENCE`, `guided_spacing`), but the DLD copy still uses nearest-peak
   spacing, and the default spacing differs (15 ms vs 12.5 ms). Basic plots
   (~30 % identical) and the 3D scatter (~135 identical lines) are copied too.
   Both transfer-fraction files copy `peaks.py`'s `smooth`,
   `half_maximum_width`, `refine` and their constants. Range/unit text exists
   three times (`stats.axis_text`, `selection.range_text`,
   `display_units.range_text`), titles go two ways (`backends.set_title`,
   `plot_text.set_plot_title`), and the tests are duplicated as well (417 of
   573 lines shared). Each new analysis or fix now needs doing twice.
4. **`io_helper.py`.** One 3209-line module holds about 20 operations behind
   an if/elif dispatcher (`main`, 3109–3205). The TXY converter (Live L4) will
   add another family. The operation families are separable (browse, scan,
   load/cached, save_held, live, icons, roots/markers, cache_admin/move,
   trace_check), on shared infrastructure: tracing, traced filesystem calls,
   test seams, `Pause`/`Heartbeat`, store opening, settle/fingerprint/raw shot
   times, saved metadata, summaries.
5. **`FolderCache` / `FolderExplorer`.** These are the largest stateful pair.
   `FolderCache.__init__` sets about 95 attributes, has 31 signals and a
   509-line `_on_event` handling about 50 event kinds behind a series of
   stale-result guards. `FolderExplorer`'s load, Live and summary code share
   widget state. Fewer near-term features land here than in the plot UI, so
   these come later.

Helper ↔ GUI traffic is untyped: about 65 `{"kind": …}` event kinds, matched
by string (`helab/utils/events.py` is the GUI's notification hub, not this
contract). The science modules in `helab/analysis/` are already Qt-free.
`follow`, `budget`, `runner`, `backends`, `panes`, `parameter_tree`, `empty`,
`plot_axes` and `plot_text` import Qt. Because `scripts/base.py` imports
`follow.LivePolicy`, every script, and so any headless runner, loads QtCore.

## Proposed slices

Each slice moves code without changing behaviour, is reviewable on its own, and
lands on `dev/v0.0.6` with the full suite and strict typing.

| # | Slice | Unblocks | Risk |
|---|---|---|---|
| A | **Guards first, nothing moved:** a test that scans and listings import no numpy, pandas or PyQt in the helper; a test that bundled analyses have unique `analysis_id` and a `version` (stated in `base.py:96`, not enforced; `scripts_manager.py:153` checks only name and group); remove verified dead code (`HelabMainWindow.load_folder_to_ram`, `connect_folder_explorer_signals`, unused imports at 30–41 incl. `humanfriendly`, `plotly`, `QWebEngineView`; `FolderCache.diskUsageChanged` has no listener) | safe moves later | low |
| B | **Split `ScriptTreeSelector.py`** into plot dock, settings panel, `AnalysisInstance` and script tree modules (e.g. `helab/views/plots/`), with the old module re-exporting | parallel plot features | low |
| C | **Qt-free analysis core:** `LiveFeed` out of `follow.py`, the pure parts of `budget.py` apart, `AnalysisRunner` as a plain core plus a thin `QObject` adapter; an import test that the core loads without PyQt6 | job runner, headless runner, R2 | low–medium |
| D | **One shared core for standard and DLD:** order detection into `helab/analysis/` (reusing `peaks.py`), overlay helpers out of the script files, one range/unit text and one title path | every new analysis | medium, needs decisions |
| E | **`PlotWorkspace` out of `HelabMainWindow`:** owns `middle_mainwindow`, docks, placeholder, Live feed, RAM budget and its windows, the settings panel and the plot presentation methods; `AnalysisInstance` takes it instead of the window | plot features without main-window edits | medium |
| F | **`io_helper` as a dispatcher over a package** (e.g. `helab/io_ops/`): one module per family, infrastructure in one shared module | TXY converter (L4), new operations | medium |
| G | **Typed helper events:** `TypedDict` per event kind, adopted family by family alongside F | remote runners, fewer string bugs | low per step |
| H | **Explorer and cache state:** a load-state dataclass with the summary text as pure functions (`FolderDetailsPanel` already reads ~20 `load_*` fields as a bag); `LiveController` (1397–1854); flags/constants and pending-save/budget stores out of `FolderCache`; split `_on_event` last, keeping its routing order and stale guards exactly | browser features | high |

**Order and parallelism.** A first, then three tracks that don't share files:
plot UI **B → C → E** (one floor, in order: B and E both edit
`ScriptTreeSelector`/`HelabMainWindow`), I/O **F → G**, and science **D**
(scripts and `helab/analysis/` only, once its decisions are made). H waits
until a browser feature needs it.

### Hazards to brief workers on

- **A re-export doesn't move a patch.** Tests patch names by string where
  they're looked up: `helab.models.ScriptTreeSelector.store_options` ×11,
  `.get_analysis_runner` ×4, `.mouse_held`, `.get_folder_cache`;
  `helab.views.HelabMainWindow.get_io_service` ×7, `.QSettings` ×3. When a
  class moves, its tests must patch its new module, or the patch silently does
  nothing.
- **`io_helper` runs as `__main__`** (`-m helab.io_helper`, 7 subprocess
  tests). A new module that imports `helab.io_helper` gets a second copy, with
  its own `TRACE` (rebound via `global`) and `Pause` state. The shared state
  must live in the infrastructure module, which the dispatcher imports too.
  The autouse fixtures patch `io_helper._cache_store` (`conftest.py:170`) and
  `_volume_id_cache` (`conftest.py:105`), and tests patch `SETTLE_SECONDS`
  ×6, `_read_txy_file` ×4, `_scan` ×4, the trace globals and
  `"helab.io_helper.time.time"`: each needs its new target. `HeLab.spec` lists
  only `helab.io_helper` as a hidden import, so new modules must be imported
  statically.
- **Lazy imports are a contract:** numpy/pandas only inside `_read_txy_file`,
  `read_cached`, `_load`, `save_held` and `live_check`; PyQt only inside
  `folder_icons`; blosc only via `cache_store`. Slice A's test keeps it.
- **Private names in tests:** ~130 FolderCache and ~190 FolderExplorer private
  accesses, e.g. `_update_activity` ×56, `_dispatch_deep` ×21, `_bg_paths`
  ×20, `_observe_cache` ×14, `_content` ×16, `_show_detected` ×10. Moves
  should keep these names on the same object, or move the tests with them.

## Future-proofing beyond the code split

- **Dependencies are unpinned.** `requirements.txt` names ~35 packages with no
  versions, so every CI run installs the newest releases. An upstream release
  (PyQt6, numpy, pyqtgraph, scipy) can turn CI red in the middle of a refactor
  and be mistaken for it. Proposal: a lock file (`uv pip compile
  requirements.txt -o requirements.lock`) that CI and the setup guide install
  from, refreshed on purpose (a manual or scheduled job that opens a PR).
  `requirements-pip.txt` is an old conda freeze with `file:///` paths that
  can't be installed: delete it.
- **Packaging metadata:** `setup.py`'s `install_requires` lists 4 of the
  runtime dependencies, and there is no `pyproject.toml`, so a wheel install
  is incomplete. Move metadata to `pyproject.toml` with the real dependencies,
  keeping the `build_py` stamp hook.
- **Native settings in tests** (known issue): `HelabMainWindow` reads the
  developer's QSettings at construction. A settings factory is the first step
  of the [agent workflow's](../../../roadmaps/agent-workflow.md) profiles, and
  slice E's tests need it too, so do it with or before E.
- **Quit:** `AnalysisRunner.stop()` is never called. The worker is a daemon
  thread, so quitting doesn't hang, but a running computation is cut off
  rather than cancelled. Call it from `closeEvent` when touching that path.
- **Script contract:** `base.py` documents every hook with defaults and nothing
  uses `hasattr` discovery. That is good. The standard scripts still pass state
  through ad-hoc widget attributes (`counts_curve`, `histogram_layout`,
  `order_numbers`, read back with `hasattr`), where the DLD scripts use typed
  widget subclasses. Adopt the latter in D.

## Decisions for Tony

1. **Standard vs DLD:** should the two groups share one behaviour (one order
   detection; DLD gets the reference spacing; one default spacing) or stay
   deliberately separate? Is "Basic plots v1" to be kept long-term beside the
   port?
2. **Start:** slice A and the dependency lock now, then B (plot UI) and F
   (I/O) as the first two parallel floors?
3. **Lock file:** pin dependencies for CI and setup (proposed), or keep
   unpinned?
4. **Package names:** `helab/views/plots/` and `helab/io_ops/` (proposed), or
   others.

### Tony's answers (2026-10-20)

1. **"Basic plots" is the group we keep developing.** The DLD group is a
   legacy port kept for reference. It will later be broken up into modernised
   code and features, then disabled. So slice D modernises Basic plots only.
   DLD scripts get mechanical import updates when code they use moves, and
   nothing else: no fixes ported to them and no dedupe into them.
2. **Start** with slice A and the dependency lock, then the plot-UI and I/O
   tracks.
3. **Pin dependencies** with a lock file.

## Proposed doc changes (for the coordinator)

- `roadmaps/refactoring.md`: under milestone 2, list slices A–H and the three
  tracks; refresh the size table in the 2026-10-14 notes by linking here.
- `roadmaps/_readme.md` Known issues: dependencies unpinned in CI; incomplete
  `install_requires`; stale `requirements-pip.txt`; standard/DLD transfer
  fractions drifted (reference spacing, default spacing).
- `AGENTS.md` Testing: tests that need POSIX permissions skip under root (cloud
  containers run as root).
