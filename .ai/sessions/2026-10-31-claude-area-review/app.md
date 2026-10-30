# Area review: `app` (Reviewer 5, Keel)

App runtime, UI, settings, release: `helab/main.py`, `helab/views/` (not `plots/`, not `explorer_live.py`),
`helab/models/`, `helab/utils/settings_*`, `settings_defaults.py`, `app_log.py`, `gui_watchdog.py`,
`accessible.py`, `helab/release*.py`, `build_info.py`, `.github/workflows/`, `HeLab.spec`. Tree: `agent/area-review`
at `c3a503f` (same code as 0.0.7a1). Read-only; scratch tests under `.ai/temp/app-review/` (run with
`pytest -p tests.conftest <file>`, so conftest's isolation applies).

**Summary: 6 findings, 0 High, 2 Medium, 4 Low**, plus a test gap and three nits. No blocker for v0.0.8 work.

## Findings

### app-1 · Medium · Reset all settings doesn't reset the TXY converter tab, and Save puts the old values back

`helab/views/SettingsDialog.py:404-428` (`reset_settings`), `helab/views/ConverterTab.py:454-463` (`save`),
`helab/views/HelabMainWindow.py:919-944` (`show_settings_dialog`'s re-apply).

`reset_settings` clears the store and reloads General, Lab parameters and Cache, but never reloads the
ConverterTab. Its combos keep the pre-reset profile, backend, output and "Tabs and Live read" source, and
`_write_settings` → `converter_tab.save` writes them straight back. Reset's confirmation says "Resets every
HeLab setting to its default".

Second half: after **Reset, then Cancel** (the settings are already cleared), `show_settings_dialog` re-applies
load mode, concurrency, check level, Live and settle time, lab constants, both budgets, auto-reload and auto-scan
from the cleared store. It doesn't re-apply what only the dialog's Save applies: `FolderCache.set_convert_profile`,
`set_tab_source`, `set_result_reuse`, nor Work Offline (`work_offline` is cleared, but the session stays offline
with File › Work Offline checked). For the rest of the session, conversions use the old profile, tabs read the
old TXY source, and saved results are still reused, while the saved settings (and the next start) say otherwise.

*Scenario:* set TXY output = temp and Tabs and Live read = matlab-only → Settings › Reset all settings › confirm
→ the TXY converter tab still shows temp / matlab-only → Save → both saved again as temp / matlab-only.
*Verified:* scratch test `.ai/temp/app-review/test_app_review_reset.py` (passes, meaning the bug is there: the tab
shows `temp matlab-only` after reset; `converted_txy_output` and `txy_source` read back `temp` and `matlab-only`
after Save). Reset, then Cancel: read the code path (`HelabMainWindow.py:919-944`; `ConverterTab.save` and
`CacheTab.save` are the only callers of those three setters from the dialog).
*Fix direction:* add `ConverterTab.load(settings)` (the `__init__` reads at lines 268-271) and call it from
`reset_settings`. After the dialog closes, re-apply the profile, tab source and result reuse from the settings
(as is done for the other rows), and `_offline_changed`/`set_work_offline` from `work_offline`. Or decide that
Reset leaves Work Offline alone, and say so in the confirmation. Add a test that Reset, then Save, saves every
converter row's default.

### app-2 · Medium · Widths saved on a wider screen collapse the plot area to 0 px, and quitting saves the squeezed widths

`helab/views/HelabMainWindow.py:1295-1303` (`showEvent`), `1305-1317` (`save_split`/`_remember_panel_widths`),
`1276-1293` (`read_split` accepts up to `MAX_PANEL_WIDTH` 4000 each).

`showEvent` sets `[left, max(0, width - left - right), right]` from the saved widths without checking that they
fit the window. When they don't, QSplitter gives the plots 0 px (the middle pane is collapsible and has no least
width) and squeezes the panels. At quit, `save_split` records the squeezed widths, so the user's real choice is
lost too.

*Scenario:* on a wide lab monitor the user widens the folders to 1500 px and the settings to 600, then quits. The
next start is in a 1600 px window (laptop without the monitor, Windows DPI scaling, or `--geometry`): the plot
area isn't there at all (the plots open into a 0 px pane until the user finds and drags the splitter handle).
Quitting saves "1027,250", not 1500,600.
*Verified:* scratch test `.ai/temp/app-review/test_app_review_split.py` (real `HelabMainWindow`, offscreen): window
1600 → `splitter.sizes() == [1027, 0, 250]`, saved after quit `1027,250`.
*Fix direction:* in `showEvent` (and `apply_geometry`), scale the two panels down so the plots keep a least
width (e.g. `MIN_PLOTS_WIDTH`), or `setCollapsible(1, False)` with a minimum. Save only widths the user set (not
the ones a narrow window forced). Add a test for a saved split wider than the window.

### app-3 · Low · The GUI stall dumps never reach the log file, so the packaged app loses them

`helab/utils/gui_watchdog.py:36-43`, `HeLab.spec:87` (`console=False`).

When the event loop stalls for 2 s or more, `GUIWatchdog` logs "GUI stalled … capturing thread stacks" and then
writes the stacks with `faulthandler.dump_traceback(file=sys.__stderr__)`. The log file
(`<app folder>/logs/helab-<pid>.log`) gets the one line but never the stacks. In the packaged app there is no
console: on Windows a windowed PyInstaller app has `sys.__stderr__` None, so the dump is skipped; on macOS a
Finder-launched `.app`'s stderr isn't the log file. The stacks are the only evidence of where a lab PC's GUI froze,
and AGENTS.md lists `gui_watchdog.py` as "stall dumps".
*Verified:* read the code path. The Windows behaviour is PyInstaller's documented windowed mode (`sys.stderr`/
`__stderr__` None). Not run on a built app.
*Fix direction:* write the dump into the log file as well: format the stacks with `sys._current_frames()`, as
`quit_watch.still_running` already does, and `logging.error` them. Or open a `faulthandler` file in the logs
folder.

### app-4 · Low · Startup recovery of an interrupted cache move waits with no timeout and no way out

`helab/main.py:111-145` (`_recover_in_helper`: `timeout=math.inf`, a `QMessageBox` with `NoButton`, then
`loop.exec()`). Boundary: `cache`, since `io_ops/admin.py` `cache_move_job("recover")` sends no heartbeats.

If the recovery helper hangs (the cache folder, or the move's target, on a share that stopped answering, which
the cache-move UI allows), HeLab never gets past "Finishing an interrupted cache move…". The box has no button, so
there's no way to skip it and start with the disk cache off, and the next start does the same. AGENTS.md: "Timeouts
measure time without progress (helpers send heartbeats)". This one has neither.
*Verified:* read the code path (`submit(..., timeout=math.inf)`; no heartbeat in `_cache_move_step`'s `recover`
branch). *Unverified:* that a recovery can hang in practice; a stalled SMB mount under a scratch move record would
confirm it.
*Fix direction:* a finite no-progress timeout plus heartbeats from the recover step, or a "Start without the disk
cache" button that cancels the helper. Either way `start_cache_dir(usable=False, reason)`, as the error path does
already.

### app-5 · Low · Unverified · A release recovery build on Windows likely passes the build job's 25-minute limit

`.github/workflows/ci-build.yml:44` (`timeout-minutes: 25`), `129-140` (the recovery step runs the **whole** suite
in the build job, ungrouped, with cython built and `HELAB_REQUIRE_BACKENDS` set).

By the repo's own timings (release-and-ci.md: Windows groups 11:02 + 10:02 of pytest alone; `ci-test.yml:131`:
"Windows 20-25" for the whole suite), the recovery step takes about 21 minutes on `windows-latest`. Before it come
dependency install and the cython build, and after it PyInstaller and `check_build.py` (the job's own comment says
5-10 minutes for those). That passes 25 minutes, so a Windows recovery build would be cancelled and the draft
release never completes. Recovery is rare (an existing tag whose draft is incomplete), which is why it's only Low.
*Verified:* read the workflows and the documented timings. Not run (no recovery has happened since the split into
groups).
*Fix direction:* when `build-sha != github.sha`, raise the limit (e.g. 50 minutes), or run the tagged commit's
tests as their own grouped job (reuse `ci-test.yml` with a `ref` input) before the build.

### app-6 · Low (docs) · "The PR's own run tests the same commit" isn't quite true

`.github/workflows/dev-cicd.yml:27-29`, `.ai/architecture/release-and-ci.md` ("since the PR's own run tests the
same commit"). A `pull_request` run checks out `refs/pull/N/merge`, the head merged into `main`, not the head
commit itself. While a PR is open, the branch head alone is never tested. That's usually what you want (it tests
what will land), but the wording, and the landing rule's "the branch's latest CI run … checked by run ID", should
say which run counts.
*Verified:* read the workflow. This is GitHub's documented `pull_request` checkout ref.
*Fix direction:* doc wording only, e.g. "the PR's run tests the branch merged into main".

## Tests

- **No test of `main.py`'s startup glue** (`_start_cache`, `_recover_in_helper`): its event wiring, the `usable`
  flag, and a `submit` that fails (the disk cache turns off with no message). The pieces are tested
  (`test_cache_mover.py`: `startup` with fakes, `cache_move_job("recover")`), but not the function HeLab runs.
  Low; a test with a scratch move record and the real helper would cover it.
- **No test of Reset all settings for the TXY converter tab, or of Reset, then Cancel** (app-1). Existing reset
  tests: `test_settingsDialog.py:75` (General), `test_lab_parameters.py:81`, `test_cache_tab.py:321` (budget),
  `test_presets_store.py:289`.
- **No test of a saved split wider than the window** (app-2); `test_main_split.py` covers the defaults, the
  window narrower than the default, and the user's widths when they fit.

## Checked and fine

- `main.py` dispatch order: `freeze_support` (frozen only), `--helab-io-helper`, `convert`, `--version`, all
  before Qt/caches/Dash imports; the instance lock (`cache_locks.startup`/`instance_lock`) is taken before any
  cache use and released on `aboutToQuit`; `quit_watch.exit_soon` after `app.exec()`.
- Settings: `app_settings()` is the only constructor (no other `QSettings(org, app)` in `helab/`); every
  `.value(` read in `helab/` goes through `read_setting`; no `type=int`/`float` reads (`read_setting` refuses
  them); out-of-range values are clamped in their readers (`read_split`, `read_settle_seconds`,
  `constants.read_*`). The disk budget after Reset, then Cancel is synced to the store
  (`HelabMainWindow.py:926-932`).
- Rendering is memory only: `SnapshotFileSystemModel.data()`/tooltips call only `FolderCache` getters
  (`scan_history`, `folder_prefs`, `pending_root`, `analysis_cached`, `cache_status`, `current_dataset`,
  `disk_cached`, `subtree`), none of which submits or touches disk. `fetchMore` submits a scan on expansion,
  which is the documented "scanned on … expansion".
- No GUI-thread waits in views and models: only modal `exec()`s and the two startup waits in `main.py` (before
  the window exists; app-4 aside). No filesystem calls on the GUI thread in `views/`/`models/` except the temp
  folder, app folder (profiles, move record) and runner screenshot/state files, and `CacheMover._existing`
  (a "Show in Finder" click on the cache folder; nit below).
- Quit: `closeEvent` → `_wait_for_saves` (Live off in every tab, last-uses flush, `quit_saves`, quit window).
  Esc/close keep waiting, only Quit now skips. A second close while waiting is ignored. Then `save_split`,
  plots recorded, timers stopped, `IOService.shutdown`, `QApplication.quit`.
- Closing a tab: `removeTab` → stop button (cancels this tab's loads/scans only), `close_cleanup` (Live stopped
  with its save, foreground released, every `FolderCache` signal disconnected, pins released).
- Live at launch (`live_launch.py`): never under pytest unless asked; offline opens the tab without Live;
  `auto_convert` is added only when not offline; the old list key is migrated once and removed.
- Logs: `deletable` never takes a running HeLab's files (instance locks plus own pid, and the 60 s
  `STARTING_SECONDS`), and tidying runs off the GUI thread (`OldLogs`). The excepthooks log once a minute per
  site, with repeats counted.
- Release: `_version.py` is the only version; `_build_info.json` is written to PyInstaller's `workpath`, never
  the package; `read_build_info` rejects a stamp for another version; the tag step refuses a tag that points
  elsewhere and never moves one; `decide_release` refuses a version below the latest tag.
- Workflows: the reusable `ci-test.yml`/`ci-build.yml` drop to `contents: read`; fail-fast is off; both test
  groups and the converter backends job use `--reruns 5 --reruns-delay 5 --timeout=120`; the `pip list` guard
  for unshipped backends really fails the job (`exit 1` inside `{ }`, not caught by `|| true`).
- `HeLab.spec`: the resources HeLab reads by path (`ai-icon.icns`, `menu-right.svg`, the profiles' JSON) are in
  `datas`; the unshipped backends are excluded.

## Nits

- `HelabMainWindow.py:105`: `os.makedirs(DIR_TEMPS)` on the GUI thread at window creation (the temp folder, so
  allowed; if a user points it at a share, the first window waits on it).
- `CacheMover.py:386-391` (`_existing`): `os.path.exists` walk on the GUI thread after "Show in Finder" (the cache
  folder may be on a share).
- `SettingsDialog.closeEvent` has a dead `# self.save_settings()` and a TODO ("warning box if unsaved changes");
  `HelabMainWindow.handle_exit` has a commented `closeEvent(None)`.

## Runs

All on this floor's tree (`c3a503f`), with `floor-env.sh`, on a machine shared with the other four Reviewers' runs:

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-app`: **8510 passed, 672 skipped, 2 warnings
  in 527.77 s; no RERUN, no failure.** The warnings are pyqtgraph's NumPy 2.5 `arr.shape` DeprecationWarning in
  `test_t_spectrum.py` (known, unrelated). Log: `.ai/temp/app-review-suite.log`.
- `mypy helab/ --strict`: no issues in 195 files; `mypy tests --strict`: no issues in 175; `pyright helab tests`:
  0 errors, 0 warnings (`.ai/temp/app-review-types.log`).
- Scratch tests (not in the suite): `.ai/temp/app-review/test_app_review_reset.py` (app-1) and
  `test_app_review_split.py` (app-2), each run alone with `pytest -p tests.conftest <file> -s`.
