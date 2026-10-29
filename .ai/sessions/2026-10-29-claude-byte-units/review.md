# Review: byte units by OS (`agent/byte-units`)

Reviewer (Claude Code), 2026-10-29. Reviewed `git diff 9f0b21f...HEAD` at `9ebea5f` (the floor's
own changes on top of `dev/v0.0.7` at `9f0b21f`) against [brief.md](brief.md) and
[handoff.md](handoff.md).

**Verdict: no blocker.** 0 blocker, 0 major, 3 minor, 2 nits. Each minor finding is small and
local to `CacheTab` and the tests.

## Checks I ran (floor venv, `floor-env.sh` sourced, macOS, Python 3.13)

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`: **8201 passed, 669
  skipped, 2 warnings (pyqtgraph NumPy deprecation), no RERUN** (126 s).
- `mypy helab/ --strict`, `mypy tests --strict`, both again with `--platform win32`: no issues
  (191 / 159 files). `pyright helab tests` and `pyright --pythonplatform Windows helab tests`:
  0 errors.
- All 30 changed `.py` files parse with Python 3.11 (`ast.parse`, uv's cpython 3.11). The compat
  jobs are skipped on this branch's CI.
- An offscreen probe in a subprocess with `HELAB_UNITS_PLATFORM_OVERRIDE=win32` (scratch script, not
  committed) gave: `MIN_DISK_BUDGET` 2^30, `DEFAULT_DISK_BUDGET` 8 GiB, `app_log.MB` 2^20 / "MiB",
  and the budget box suffix " GiB" with a minimum of 1.0. The import-time values are right on
  Windows. The probe also confirmed findings 1 and 2.
- CI run 40862606115: see the end of this file.

## What I checked and found right

- **Sorting.** All 64 `byte_size` calls (`grep` finds 66 matches; the other two are the `def` and a
  docstring) and the one `byte_rate` call match the handoff table, and each is sorted correctly.
  Memory measures are `ram`: large-folder estimates, the RAM budget box, In use, "in RAM when
  loaded", the workspace RAM notice and tooltip, and the RAM-budget-lowered notice. Everything
  else is `disk`: the store, its budget, cached data and results, converted TXY, I/O traces,
  free space on a move, and the read rate. `kind` is required, so mypy and pyright reject a call
  without it, and both pass.
- **Hard-coded units.** No unit strings remain in UI text. The status bar RAM and the Debug memory
  window use GiB and MiB. The log texts take `MB_UNIT`. The only SI numbers left are
  `result_cache.LARGE_RESULT_BYTES` (a threshold, never printed), estimates in comments, and
  `helab/convert/timing.py` (the TXY Index floor's package). The handoff lists all of these.
- **Defaults and minimums.**
  - The disk budget is 8 GB on macOS/Linux and 8 GiB on Windows, set through
    `settings_defaults.default_disk_budget`; the table row is still the one place it is defined.
  - The disk minimum is 1 GB / 1 GiB, and the RAM minimum is 1 GiB.
  - On real machines (RAM a whole number of GiB), the RAM step minimum is unchanged.
- **A stored budget keeps its bytes** when the box is left as shown, including 8 GB on Windows
  (shown as 7.5 GiB, saved as 8 000 000 000). This is tested and I confirmed it in the probe.
  Exceptions: findings 1 and 2.
- **The env override `HELAB_UNITS_PLATFORM_OVERRIDE` is needed.**
  - `MIN_DISK_BUDGET`, the table default and `app_log.MB` are fixed at import, so a fixture that
    patches `PLATFORM` can't reach them. Only an environment variable set before the import can.
  - It follows the existing `HELAB_*_OVERRIDE` pattern: read once at import, the way
    `constants.py` reads its own overrides.
  - It is not a QSettings key, so the `settings_defaults` / `read_setting` rule doesn't apply.
  - `number_format` stays standard-library only.
  - Helpers inherit the variable, so they agree with the GUI.
- **Log sizes in MB/MiB (the handoff's flagged choice).** I accept it. It is consistent with
  "defaults follow", and the thresholds (1/20/50) change by under 5 % on Windows. If Tony prefers
  SI thresholds with only the label changed, it is a one-line change in `app_log.py:30`. I see no
  need to ask him unless the Coordinator wants to.
- **3.11 f-string compatibility** and the `FolderExplorer._ask_remove_cached` local variable: fine.

## Findings

### 1. Minor — after a step from an off-grid budget, the box shows one value and saves another

`helab/views/CacheTab.py:668-672` (`disk_budget_bytes`).

**Why.** Once the box no longer shows the stored value, the saved bytes are snapped to half a unit,
but the box itself is not snapped. Before this change, every budget a user typed was on the
half-GB grid, so only hand-edited values could hit this. On Windows, almost every budget typed
earlier in GB is now off the half-GiB grid.

The probe, with the override set to win32 and a stored 20 GB:
- the box shows 18.6 GiB;
- one step up shows **19.1 GiB**;
- `disk_budget_bytes()` returns 20 401 094 656 (**19.0 GiB**);
- the next open shows 19.0.

The "Lower the disk budget?" question names the snapped value, so the user also sees two
different numbers.

**Fix.** Snap the box to the grid as soon as its value leaves the shown one. For example, connect
`valueChanged` and, when `value != shown` and `value * 2` is not a whole number, call
`setValue(round(value * 2) / 2)`. Overriding `stepBy` would also work. Add a test: Windows, 20 GB
stored, `stepBy(1)` gives `value() * disk_unit == disk_budget_bytes()`.

### 2. Minor — a stored 1 GB budget on Windows is rewritten to 1 GiB by any Settings Save

`helab/views/CacheTab.py:724-725` (`save`), with `helab/utils/constants.py:121` and
`read_disk_budget`'s clamp at `constants.py:130`.

**Why.**
- `show_disk_budget` receives the clamped `read_disk_budget` value (2^30), not the stored 10^9.
- `apply_budget` then acknowledges 2^30. Without a cache, `save` writes `read_disk_budget(settings)`,
  which is also clamped.
- So any Save writes 1 073 741 824 over 1 000 000 000, even when the user didn't touch the box. The
  probe confirmed it: stored 10^9, Save, stored 1073741824.
- The handoff says the setting "isn't rewritten unless Save applies a change", which is incorrect.
  The brief says "no rewrite of anyone's setting".
- The effect is tiny: the store already runs at 1 GiB from startup (`set_disk_budget(read_disk_budget(…))`).
  Before this change, saved values under the minimum were rewritten the same way.

**Fix (Coordinator's choice).**
- (a) Accept it. Correct the handoff and the proposed `cache-store.md` text ("a budget under the
  OS's minimum reads as the minimum and is saved as it on the next Save"), and add a test of it.
- (b) Keep 10^9 legal everywhere: `read_disk_budget` clamps at `min(10**9, MIN_DISK_BUDGET)`
  while the box's minimum stays 1 GiB, and `show_disk_budget` keeps the stored bytes.

I recommend (a): it is the smaller change, and the effective budget is unchanged either way.

### 3. Minor — no CI job runs Windows' import-time values; the pin hides them

`tests/conftest.py:62`, `tests/test_settings_defaults.py:35-45`, `tests/test_cache_tab.py:430-458`.

**Why.**
- Every OS runs with `darwin` units, including Windows CI. Patching `number_format.PLATFORM` doesn't
  change values computed at import.
- The Windows `CacheTab` test therefore runs with `MIN_DISK_BUDGET = 10**9`. Its box minimum is
  10^9 / 2^30 ≈ 0.93 GiB, not Windows' 1.0.
- `test_the_disk_budget_default_and_minimums_follow_the_os_units` checks
  `byte_unit(3, "disk", "win32")` rather than the values HeLab actually uses on Windows.
- Untested on any OS:
  - `constants.MIN_DISK_BUDGET` and `DEFAULT_DISK_BUDGET` under win32;
  - the table default;
  - `read_disk_budget(10**9)` on Windows (finding 2);
  - `app_log.MB` / `MB_UNIT`, `OldLogs.QUESTION`'s unit and the log tooltip under win32.
- My probe shows these are right today; nothing would catch a regression.

**Fix.** Add one subprocess test that sets `HELAB_UNITS_PLATFORM_OVERRIDE=win32`, inherits
conftest's directory overrides, imports `constants`, `app_log` and `CacheTab` offscreen, and
asserts:
- `MIN_DISK_BUDGET == 2**30` and `DEFAULT_DISK_BUDGET == 8 << 30`;
- `setting_default(DISK_BUDGET_SETTING) == 8 << 30`;
- `read_disk_budget` of a stored 10^9 (finding 2's chosen behaviour);
- `app_log.MB == 2**20` and `MB_UNIT == "MiB"`;
- the box's `minimum() == 1.0` and suffix `" GiB"`.

Optionally add the mirror test with `darwin` unset, run only where `sys.platform == "win32"`, so
real Windows CI goes through `sys.platform` once.

### 4. Nit — where the override is documented

`helab/utils/number_format.py:14` reads `HELAB_UNITS_PLATFORM_OVERRIDE` in production. The
handoff's `testing.md` proposal should put it in the list of environment seams that production
reads (`testing.md` line 11, beside `HELAB_DIR_*_OVERRIDE`). It should also mention that
`HELAB_UNITS_PLATFORM_OVERRIDE=win32 helab` shows Windows' units on a Mac, and that helpers
inherit it.

### 5. Nit — `byte_rate` now goes up to TB/s

`helab/utils/time_format.py:42`. Through the shared `scaled`, rates now go up to TB/s (TiB/s);
before, they stopped at GB/s. This is harmless and arguably better, but the handoff doesn't
mention it. No fix needed.

## Doc proposals

The handoff's proposals are right, with two changes:
- finding 2 changes the `cache-store.md` sentence "a saved budget keeps its bytes while left as
  shown": add the under-the-minimum case;
- finding 4 adds the seams list in `testing.md`.

M~1 (a Windows smoke check) and A~2 (the RAM box clipping its text) are good follow-ups. A~2's
clipping existed before this change: the text was already clipped at 23 characters.

## CI run 40862606115 (head `9ebea5f`)

**Green: conclusion `success`, every non-skipped job passed.** I read each job's log with `gh api
.../actions/jobs/<id>/logs`. **No RERUN in any job:** the only lines matching "rerun" are the
`pytest-rerunfailures` install lines, and no log has a "rerun reasons" section. The 3.11, 3.12 and
3.14 compat jobs were skipped (they run on PRs only).

| Job ID | Job | Result |
|---|---|---|
| 123409446683 | windows Tests (1/2) | 4073 passed, 333 skipped |
| 123409446769 | windows Tests (2/2) | 4099 passed, 361 skipped |
| 123409446790 | windows Converter backends | 661 passed, 517 skipped |
| 123409447146 | macos Tests (1/2) | 4086 passed, 322 skipped |
| 123409447095 | macos Tests (2/2) | 4115 passed, 347 skipped |
| 123409447011 | macos Converter backends | 662 passed, 516 skipped |
| 123409447089 | ubuntu Tests (1/2) | 4083 passed, 324 skipped |
| 123409447002 | ubuntu Tests (2/2) | 4115 passed, 347 skipped |
| 123409446839 | ubuntu Converter backends | 662 passed, 516 skipped |
| 123409447505 / 123409447339 / 123409447151 | Build windows / macos / ubuntu | success |
| 123409333830 | Detect branch and version bump | success |

## Re-check after the fixes (`9ebea5f..28dc03c`, 2026-10-29)

**All five findings are closed. No open findings.**

| # | Finding | Outcome |
|---|---|---|
| 1 | Minor: after a step from an off-grid budget, the box shows one value and saves another | **Closed.** `CacheTab._snap_disk_budget` (`CacheTab.py:670-674`) runs on `valueChanged` and snaps the box to the half-unit grid when it leaves the shown value. `show_disk_budget` sets the shown value to -1 first, so showing a stored off-grid budget doesn't snap. There is no loop, because a snapped value is on the grid. Tested in `test_cache_tab.py:454-465` (Windows, 20 GB stored, `stepBy(1)` gives 19.0 = 19 GiB, then `stepBy(-3)` gives 17.5, and showing it again gives 18.6 = 20 GB). My offscreen probe typed into the Windows box: "25" gives 25 GiB, "7.5" gives 7.5 GiB, "18.7" snaps to 18.5 (saves 18.5 GiB), and "18.6" keeps the stored 20 GB. Shown and saved agree in every case. |
| 2 | Minor: a stored 1 GB on Windows is rewritten to 1 GiB by any Settings Save | **Closed as (a).** The handoff is corrected ("For the Reviewer" and the `cache-store.md` proposal), and the behaviour goes to Tony as Q~1 with (a) proposed. It is tested in a fresh interpreter: with win32, a stored 10^9 is saved as 2^30; on macOS/Linux it stays 10^9. |
| 3 | Minor: no CI job runs Windows' import-time values | **Closed.** `test_number_format.py::test_units_set_at_import_follow_the_platform[win32/darwin/None]` runs a fresh interpreter. It checks `MIN_DISK_BUDGET`, `DEFAULT_DISK_BUDGET`, the table row, `MIN_RAM_BUDGET`, `read_disk_budget` of a stored 1 GB, the box's minimum, suffix and value, apply and Save, and `app_log.MB`/`MB_UNIT`. The `None` case uses `sys.platform`, so on Windows CI it runs with Windows' units. It passed in Windows Tests (2/2) (`[win32]`, `[darwin]`) and Tests (1/2) (`[None]`, i.e. real win32). It follows the existing `sys.executable -c` subprocess pattern (`test_cache_store.py`). |
| 4 | Nit: where the override is documented | **Closed.** The `testing.md` proposal now goes into the list of environment seams, with the Mac preview and helper inheritance. |
| 5 | Nit: `byte_rate` goes up to TB/s | **Closed.** Noted in the handoff. |

**Checks (floor venv, `floor-env.sh`, macOS).**
- Touched tests (`test_number_format`, `test_cache_tab`, `test_settings_defaults`, `test_load_clock`,
  `test_settingsDialog`): 101 passed.
- Full suite `-n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`: **8204 passed, 669
  skipped, 2 warnings, no RERUN** (116 s).
- mypy `--strict` on helab (191 files) and tests (159), both again with `--platform win32`: no issues.
  pyright and `--pythonplatform Windows`: 0 errors.

### CI run 40865344851 (head `28dc03c`)

**Conclusion `success`. All 13 non-skipped jobs passed. One RERUN, a known Windows flake.** I read
each job log with `gh api .../actions/jobs/<id>/logs`.

| Job ID | Job | Result |
|---|---|---|
| 123418722310 | windows Tests (1/2) | 4074 passed, 333 skipped |
| 123418722344 | windows Tests (2/2) | 4101 passed, 361 skipped, **1 rerun** |
| 123418722322 | windows Converter backends | 661 passed, 517 skipped |
| 123418722151 | macos Tests (1/2) | 4087 passed, 322 skipped |
| 123418722319 | macos Tests (2/2) | 4117 passed, 347 skipped |
| 123418722129 | macos Converter backends | 662 passed, 516 skipped |
| 123418722183 | ubuntu Tests (1/2) | 4084 passed, 324 skipped |
| 123418722109 | ubuntu Tests (2/2) | 4117 passed, 347 skipped |
| 123418722060 | ubuntu Converter backends | 662 passed, 516 skipped |
| 123418722276 / 123418722119 / 123418722152 | Build windows / macos / ubuntu | success |
| 123418586000 | Detect branch and version bump | success |

**The RERUN (job 123418722344, windows Tests (2/2)):**
`tests/test_plot_backends.py::test_2d_plots_draw_with_every_library[values0-Plotly-CountsPerShot]`.
The rerun reason reads: "worker 'gw3' crashed while running
'tests/test_plot_backends.py::test_2d_plots_draw_with_every_library[values0-Plotly-CountsPerShot]'"
("[gw3] node down: Not properly terminated"). The log has no traceback and no faulthandler dump.
The test passed on retry.

This is the same test and the same symptom as the existing `roadmaps/known-issues.md` entry
(lines 98-100, Windows CI run 40803552596). It is unrelated to this branch: a Plotly/QtWebEngine
drawing test, with no byte units involved. gw3 had run the new subprocess test about 3 % earlier,
but that test runs in its own process and passed. The Coordinator should add run 40865344851 to
that known-issues entry when landing.
