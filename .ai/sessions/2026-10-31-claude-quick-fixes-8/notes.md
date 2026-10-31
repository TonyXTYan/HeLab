# QF8 notes (Rivet, Ground, `dev/v0.0.8`)

One section per "Now" item: cause, evidence, fix, checks. Findings are the area review's (`573361f`).

## 1. convert-1: `helab convert --watch F --again` (f592519)

- **Cause.** `convert_cli.main` reset `redo` to `"stale"` after every pass. `--watch`'s first pass sends
  `seen=[]` and only records (every shot waits as `changed`), so by the first pass that can convert, `redo`
  was `"stale"` again and every current shot stayed current. `--again` only worked with `--once`.
- **Fix.** Keep `"always"` through a pass sent with `seen=[]`; reset it after the first pass that can
  convert. Each shot is converted once more, and later passes leave it current.
- **Edge.** A shot whose TXY is current but whose raw file is still within the settle time at the second
  pass waits, and isn't converted again once `redo` is `"stale"`. A current TXY means its raw file hasn't
  changed since a settled conversion, so this needs a conversion within the last few seconds.
- **Checks.** `test_again_converts_each_shot_once_more[watch, once]` runs `convert_cli.main` in-process for
  four passes, with `time.sleep` patched on the main thread only. Shots converted per pass: watch
  `[0, 1, 0, 0]`, `--once` `[1]`. The old code gives `[0, 0, 0, 0]`.

## 2. app-1: Reset all settings and the TXY converter tab (2f8b2f1)

- **Cause.** `reset_settings` reloaded General, Lab parameters and Cache, but not `ConverterTab`, so Save
  wrote the old profile, backend, output and source back. After Reset, then Cancel,
  `show_settings_dialog` re-applied everything except what only Save applies:
  `set_convert_profile`, `set_tab_source`, `set_result_reuse`.
- **Fix.**
  - `ConverterTab.load(settings)`, called from `__init__` and `reset_settings`.
  - The main window re-applies the profile, the tab source and result reuse after every close of the
    dialog. All three setters only store a value.
  - Work Offline is not changed: see Q~1.
- **Checks.** `test_reset_all_settings_resets_the_txy_converter_tab_and_what_it_applies[save, cancel]`, on
  the real `HelabMainWindow` with `SettingsDialog.exec` patched.
  - The old `SettingsDialog` fails both cases: the tab still shows plates-2022/reference/temp/matlab-only.
  - The old main window fails cancel: the profile stays plates-2022.

## 3. app-2: split widths saved on a wider screen (c4e5b25)

- **Cause.** `showEvent` set `[left, width - left - right, right]` without checking that the widths fit.
  QSplitter gave the plots 0 px, and quitting saved the squeezed widths.
- **Evidence.** The review's scenario reproduces exactly on the old code: saved 1500,600 in a 1600 px
  window gives `[1027, 0, 250]`.
- **Fix.**
  - `_set_split(left, right, total)` narrows the shown panels in proportion when the plots would get less
    than `MIN_PLOTS_WIDTH` (400 px). Each panel keeps at least its least width.
  - Each narrowed panel is recorded as (width shown, width chosen) in `_narrowed`.
  - `_chosen_sizes()` and `_remember_panel_widths` treat a panel still at its narrowed width as the width
    chosen, so Quit and collapse save the user's widths. A width the user drags to is saved as before.
  - The first show and both panels' "show again" toggles go through `_set_split`, measured from
    `splitter.width()`. The toggles used `self.width()` before.
  - The toggles no longer reopen a collapsed other panel. They used to pass its saved width.
- **Checks.** `test_widths_saved_on_a_wider_screen_leave_the_plots_room_and_stay_saved`:
  - the plots stay at least 400 px after the first show and after each toggle;
  - quitting saves "1500,600";
  - a later narrowing by the user is saved.

  The old code fails it with `[1027, 0, 250]`. All of `test_main_split.py` passes (17 tests).

## 4. A39.3: one running HeLab per computer (0335768)

- **Fix.**
  - `cache_locks.take_running(app_dir)` takes `running.lock` in the app folder and writes the pid in it.
    It is an OS file lock, like the others: `flock`, or `msvcrt.locking` on Windows.
  - `main._another_running()` runs right after `QApplication(argv)`. That is before the style, icons,
    `_start_cache`, helpers, the main window and `app_settings`.
  - If the lock is held: a message box ("HeLab is already running on this computer (process N). Use its
    window, or quit it before starting HeLab again."), then `sys.exit(1)`.
  - The lock is held until the process ends, not released at quit, so a new start waits for the old one
    to finish saving.
  - An app folder where the lock can't be checked (an OSError) is logged, and HeLab starts.
  - The log file starts before the check, so a refused start leaves one line in its own log file. It is
    neither the store, a helper nor a setting.
- **Stale lock.** A process that ended, crashed included, holds no OS lock, whatever pid the file names.
  A test covers this.
- **Override.** `HELAB_APP_DIR_OVERRIDE` gives its own app folder, so agents and tests have their own lock.
  `helab convert` is dispatched before `main()` and doesn't take the lock (Q~2).
- **Checks.** `tests/test_one_running.py` (5 tests); 3 fail on the old `main.py`. With the
  cache-lock, app-log, import and helper-event tests: 64 passed.
- **What only served several instances.** Listed in the handoff, nothing removed.

## 5. A39.1: the archive check on PR builds (c201c01)

- **Fix.**
  - `release_draft.validate_archive` is the one-archive check that `validate_archives` now loops over.
    The rules are unchanged.
  - `--check ARCHIVE --commit SHA` runs it with the checkout's `__version__`, with no tag and no draft.
  - `ci-build.yml`:
    - every 3.13 build makes the macOS zip (ditto);
    - Windows and Ubuntu zip `dist/HeLab` to `$RUNNER_TEMP` with `python -m zipfile -c`, which follows
      links as the artifact's copies do;
    - then `release_draft --check` runs against `inputs.build-sha`, when `build-sha == github.sha`.
- **Not covered.** A recovery build of an older tag checks out code without `--check`; the release job
  still validates it.
- **Checks.**
  - `test_release_recovery.py`, 29 tests; the new ones fail on the old code.
  - A scratch `dist/HeLab` with a linked stamp, zipped by `python -m zipfile`, passes `--check`, and its
    entries are `HeLab/...`.
  - The YAML parses (Ruby).
  - The real run is this round's CI: it is the first time the step runs on all three OSes.

## Suite and type checks (before the push)

- `pytest -n 12 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-qf8`: 8529 passed, 672 skipped,
  2 warnings, exit 0, no RERUN. The log is `.ai/temp/qf8-suite.log`.
- `mypy helab/ --strict`, `mypy tests --strict`, `mypy helab/ --strict --platform win32`, `pyright helab
  tests`, `pyright --pythonplatform Windows helab tests`: all exit 0. The logs are `.ai/temp/qf8-*.log`.
