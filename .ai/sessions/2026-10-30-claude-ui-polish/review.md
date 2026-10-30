# UI polish: review (Reviewer, 2026-10-30)

Diff reviewed: `git diff 43cb202..e53f0f8` (12 code commits + session docs), on the floor
(`.maestri/floors/HeLab--agentui-polish`, `agent/ui-polish` at `e53f0f8`). Read against the brief, the handoff,
AGENTS.md and the areas' architecture files. No code edited.

**Two High findings block landing: CI run 41005221588 fails on Windows** (High 1 and High 2 below). Two Low
findings and some Nits follow. Locally (macOS) everything passes.

## Checks rerun here

- Full suite, `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`:
  **8401 passed, 669 skipped, 2 warnings in 150.31 s; no RERUN** (the SIGSEGV in
  `test_every_script_and_each_library` did not occur in this run).
- `mypy helab/ --strict`, `mypy tests --strict`, `mypy helab/ --strict --platform win32`, `pyright helab tests`,
  `pyright --pythonplatform Windows helab tests`: all clean (0 issues / 0 errors).
- CI run **41005221588** (head `e53f0f8`): see "CI" at the end.
- Extra checks (scratch, outside the repo):
  - Every script of both groups opened in turn in a real main window: the split stayed `[380, 570, 327]` after
    each one (Basic plots v1 ×4, DLD Front Panel Port ×12). Q33.2's "a plot never narrows the folder panel"
    holds for every script, not only the two in `test_main_split.py`.
  - Restoring the arrangement: `setFloating(True)` (which now runs `place_floating`) followed by
    `restoreState` puts a floating plot back at its saved geometry (moved to 123,140 410×330 → restored
    exactly). So restarting still restores where the user left a plot, as the handoff says.

## Findings

### High 1: on Windows the settings panel won't go below ~548 px, so the default split doesn't hold (Q33.2)

CI on Windows, `tests/test_main_split.py`. Three tests fail after 5 reruns each. macOS and Ubuntu pass.
- `test_the_default_split_gives_the_plots_the_room_and_a_plot_keeps_it`: `assert (306 == 380)` at line 46.
  The five attempts gave 306, 318, 306, 294 and 294: the folder panel starts narrower than 380.
- `test_a_collapsed_panel_saves_the_width_it_had`: `assert '294,548' == '450,350'` (five times; once
  `'306,548'`).
- `test_the_users_widths_last_to_the_next_start`: `assert '500,548' == '500,400'` at line 68 (every attempt).

The right (settings) panel is 548 px every time, with or without a plot open, so on Windows its least width
is ~548. On macOS here it is 310 at start and 327 with any script's plot. Whatever sets it (a widget in the
right panel whose size hint is wider under Windows fonts or styles) then squeezes the folder panel to its
minimum, and a saved `"<left>,400"` can't be restored. The lab PCs run Windows, so this probably isn't only a
CI problem: users there would get folders at ~300 px and settings at ~548 px, not 380/320.
**Fix:** find the widget, for example by having the test report each of `right_panel`'s descendants with a
`minimumSizeHint().width()` over 320 when it fails, then make it shrink as was done for the TXY row and the
Presets row. Then rerun Windows CI.

### High 2: `mypy tests --strict` fails on Windows (unused `type: ignore`)

`tests/test_user_tags.py:92` has `error.winerror = winerror  # type: ignore[attr-defined]`. On win32, typeshed
gives `OSError` its `winerror` attribute, so mypy reports `error: Unused "type: ignore" comment
[unused-ignore]`. That fails `tests/test_typing.py::test_mypy_helab_tests_strict` on Windows CI (5 reruns,
then FAILED, job 123898541905). The worker's type checks ran `mypy tests --strict` only for darwin.
**Fix:** `setattr(error, "winerror", winerror)`, or `# type: ignore[attr-defined, unused-ignore]`. Then run
`mypy tests --strict --platform win32` locally.

### Low 1: a double-click on a plot's title floats it but doesn't place it (Q33.3)

`helab/views/plots/dock.py:244-250` (`_floated`), and its docstring at `dock.py:203-206`. The docstring and
the handoff both say a plot floated "other than by a drag (its title's float button, **a double-click on its
title**)" opens at 800×600, 40 px from the last one. But QDockWidget floats on the double-click's *press*
(`MouseButtonDblClick`), so `topLevelChanged` arrives while the button is down: `mouse_held()` is True and
`place_floating` is skipped, as for a drag. Seen offscreen: `QTest.mouseDClick` on the title gives
`topLevelChanged True mouse_held True`, and the plot stays where Qt put it (`QRect(32, 32, 347, 17)`, its
docked size), while `setFloating(True)` gives `800×600` a step from its docked place. No test covers the
double-click; `test_a_dragged_plot_stays_where_it_is_let_go` patches `mouse_held` to True, so it treats a
double-click as a drag too.
**Fix:** note the double-click before Qt acts on it. For example, override `event()` in `AnalysisDock` to set a
flag on `QEvent.Type.MouseButtonDblClick`, call `super().event`, then clear the flag, and in `_floated` place
the plot when that flag is set or no button is held. Add a test that uses `qtbot.mouseDClick` on the title.
The other fix is to drop "a double-click on its title" from the docstring and the handoff's Q33.3/M~2. That
would be Tony's call (behaviour users see), so the first fix is the better one.

### Low 2: on Windows, any "not found" on a long path is reported as "Path too long" and the shot is refused for the session (Q23.6)

`helab/io_ops/convert.py:135-139` (`path_too_long`), used at `convert.py:677-680`. On Windows, any
`FileNotFoundError` (or WinError 3) on a path of 260 characters or more counts as "too long". The message then
says "Path too long for Windows … unless long paths are turned on", and the shot is refused as `failed`. It is
not tried again while its raw file is unchanged, for the rest of the session. Before this change, such an
error failed the whole conversion, which the next Live check retried.
**Concrete case:** a Windows PC with long paths **on** (GitHub's runners, and possibly the lab PCs). A
beside-mode conversion runs in a folder deeper than 210 characters. The folder is renamed or moved, or a share
drops, partway through the run. `write_atomic` raises `FileNotFoundError`, and every remaining shot gets a
misleading "Path too long" message. Those shots stay unconverted for the session even after the folder comes
back.
**Fix (any one):**
- Count ENOENT/WinError 3 only when the parent folder still exists (`os.path.isdir(os.path.dirname(name))`,
  helper-side I/O, which is allowed).
- Count it only when long paths are off (`HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled`
  is 0, read once per helper).
- At least keep WinError 206 (`ERROR_FILENAME_EXCED_RANGE`) as the per-shot refusal, and let a plain
  not-found on a long path raise as before.

Add a test for whichever you choose (the existing parametrised `win32` cases make that easy).

### Nits

- **Stale docstring:** `helab/io_ops/convert.py:12-13` still says "unmodified for
  ``fingerprints.SETTLE_SECONDS`` (5 s)". It should be "(the settle time, Settings › General, default 5 s;
  sent with each request)".
- **The GUI now imports helper modules:** `helab/views/SettingsDialog.py:10` imports
  `helab.io_ops.fingerprints`, which brings `helab.io_ops.infra` and `helab.io_ops.stores` into the GUI process.
  Until now the GUI imported only `io_ops.events`, whose types are standard library only. This is harmless
  today: `infra` only reads environment variables at import, and nothing there touches a source folder or the
  store. But it blurs the GUI/helper line that AGENTS.md draws. `DEFAULT/MIN/MAX_SETTLE_SECONDS` and
  `settle_seconds()` could live in a standard-library-only module that both sides import (for example beside
  `settings_defaults`, or in a small `io_ops` module with no `infra` import); A~2 could cover this.
- **Arrow style:** `helab/utils/settings_defaults.py:102-106`: the new row's help says "Settings › General",
  while the neighbouring rows (Live interval, autosave) say "Settings → General". The same mix appears in
  `main_window_split`'s neighbours. Pick one.
- **Repeated ID:** `helab/views/plots/dock.py:130`: every floating plot window's Dock button has the ID
  `plot_dock`, as `floating_settings_toggle` already does. IDs are unique within each window, but a runner or
  agent that addresses controls by ID across windows can't tell two floating plots' Dock buttons apart. It
  follows the existing toggle, so this is fine as is; it's worth a line in the testing or accessible-ID docs.
- **Deep-path test:** `tests/test_user_tags.py:142` (`test_a_deep_folder_converts_or_says_its_path_is_too_long`):
  on GitHub's Windows runners (long paths on) only the "converts" branch runs. The real "too long" branch is
  covered only by the patched tests, which the handoff acknowledges (M~3). The test is fine; testing.md should
  say which branch CI exercises.
- **Online wording change:** `FolderDetailsPanel._data_rows`
  (`helab/views/FolderDetailsPanel.py:397-409`) changes the online wording too. For data shown unchecked while
  online (auto-load off, or a cancelled check), the Loaded row no longer says "checked, unchanged" from an
  earlier check. That is consistent with "not checked yet", and the new test covers it. It goes a little beyond
  A33.2 (offline only), so it belongs in app-runtime-and-ui.md's Folder details wording.

## Checked and fine

- **Q33.1:** `without_subfolders` reads memory only: `model.nodes` (`loaded`/`children`/`has_dirs`), the cache's
  `snapshot()` and `scan_summaries`. A listing's entries are folders only (`io_ops/browse.py:130`), so "no
  entries" means no subfolders. A typed leaf path opens its parent, then selects the row on `rowsInserted`,
  and the pending selection is dropped when the user opens or picks something else. An empty typed path is now
  ignored (before, it opened the current directory). `rowsInserted` is connected to a bound method, so no
  lambda captures its sender.
- **Q33.2:** stretch is 0/1/0. `main_window_split` is a settings row, read through `read_setting`, with its
  values bounded. It is saved in `closeEvent`, and a collapsed panel keeps its earlier width. No plot's settings
  page sets the right panel's width any more (checked for every script, above). Live remains the only thing
  that collapses the folder panel.
- **Q33.3/Q33.4:** a plot is placed only when floated by the float button or `setFloating`, not by a drag, and
  kept on its screen. The Dock button has an accessible name and an ID, and connects to a bound slot.
- **A33.4:** option (a) as CoCo chose. The old assertion in
  `test_a_hidden_floating_plot_falls_back_to_a_visible_one` was removed and replaced by
  `test_back_in_the_main_window_the_docked_plot_beside_the_panel_shows`, which fails on the base (it uses
  `away_label`). The reversal is flagged for Tony as Q~1. Suggestion for M~2: also pick the floating plot from
  the Settings panel's chooser on macOS and check that the panel ends on it. The chooser popup closing gives
  focus back to the main window, which now switches to the docked plot, before the floating window activates;
  offscreen can't show which wins.
- **Q33.5:** the three placeholders and their handler are gone, along with now-unused imports (`getsizeof`,
  `fnum`, `assert_warn`). The runner items stay, and a test checks both.
- **A33.1:** only numeric and choice rows use `EndsEditOnReturn`, so text rows are unaffected. On Tab, a valid
  entry is committed synchronously through `editingFinishedEvent` (no delayed signal) and an invalid one is put
  back. The new tests fail on the old code, where the next row's editor opened.
- **A33.2/A33.3:** the wording matches the summary and the cache folder's row. Folder details reads
  `cache.offline` from memory.
- **Q33.7 (settle time):**
  - Every helper read takes `fingerprints.SETTLE_SECONDS` / `RACY_SECONDS` from the module when it runs:
    `_settled`, `_raw_mtime`, `_quick_mtime`, `live.py:92`, and `convert.py:507`.
  - Nothing imports either constant by value: grep of `helab/` finds no `from … fingerprints import
    SETTLE_SECONDS|RACY_SECONDS`, and `save_held`/`loading` import only functions.
  - Converter worker processes get only bytes, and the settle decision is made in the helper, so they don't
    need the value.
  - The frozen app reaches the same `io_helper.main` (`main.py:7-15`), so `configure_settle` runs there too.
  - `_start_trace` uses `.update`, so the `settle` field survives onto every trace line.
  - The setting is applied in `create_menus` before `_open_first_tab`'s first listing.
  - `helab convert` falls back to 5 s (or 60 s with `--once`), as the brief asks.
  - `DAMAGED_SECONDS` (20 s) against settle times up to 60 s: a file is read only once settled, so a damaged
    file is simply reported at its first read after that. No conflict.
  - Neither the GUI nor `helab convert` reads the constant for any decision.
- **Q23.6 (user tags):**
  - `USER_TAG_DIGITS` is 32, and the built-in tags are pinned.
  - `NAME_TAG` `{1,32}` is spelled out identically in `file_kinds.HELAB_TXY`, `provenance._NAME`/`BARE_NAME`
    (and so in `partial()`/`own_partial()`) and `helab_txy._OWN_FILE`, and a test checks each.
  - `TAG_PATTERN` (built-ins, 16 characters) is still used only to validate a built-in profile's tag
    (`profile.py:173`).
  - No 8-digit rule is left in `helab/`.
  - Tonight's old `u`+8 TXY files are left alone and converted again under the new tag (tested).
- **Rules:** no GUI waits were added, and no rendering reads disk. Every new control has an accessible name and
  an ID. No new lambda captures a sender Qt made. No store or `store-v3` change. Settings go only through
  `app_settings()`/`read_setting`.

## Docs the handoff should also propose (beyond its list)

- converter.md: whatever the fix for Low 2 decides (which errors count as "too long").
- app-runtime-and-ui.md: the online Loaded-row change (last Nit).
- known-issues: the SIGSEGV (A~1) is already proposed. Nothing new from this review.

## CI

Run 41005221588 on `e53f0f8`, every job checked by job ID:

| Job | ID | Result |
|---|---|---|
| ubuntu Tests (1/2) | 123898541608 | success: 4183 passed, 324 skipped; no RERUN |
| ubuntu Tests (2/2) | 123898541624 | success: 4216 passed, 347 skipped; no RERUN |
| macos Tests (1/2) | 123898541658 | success: 4185 passed, 322 skipped; no RERUN |
| macos Tests (2/2) | 123898541667 | success: 4216 passed, 347 skipped; no RERUN |
| ubuntu / macos / windows Converter backends | 123898541676 / …682 / …738 | success: 693 / 693 / 692 passed; no RERUN |
| ubuntu / macos / windows Build | …790 / …775 / …806 | success |
| Detect branch and version bump | 123898485592 | success |
| windows Tests (1/2) | 123898541789 | **failure**: 2 failed, 4170 passed, 333 skipped, 10 rerun. FAILED `test_main_split.py::test_the_default_split_gives_the_plots_the_room_and_a_plot_keeps_it` and `::test_a_collapsed_panel_saves_the_width_it_had` (High 1); their 10 RERUNs are these same two tests |
| windows Tests (2/2) | 123898541905 | **failure**: 2 failed, 4198 passed, 361 skipped, 11 rerun. FAILED `test_typing.py::test_mypy_helab_tests_strict` (High 2) and `test_main_split.py::test_the_users_widths_last_to_the_next_start` (High 1). The other RERUN: `test_gui_responsiveness.py::test_timeout_retry_releases_dead_helper_slot_while_artifact_reader_is_blocked[1]`, "waitUntil timed out in 3000 milliseconds" at line 292, passed on rerun. It is the known-issues entry for `[2]` (same line, same cause), now seen for `[1]`: add it to that entry |

The compat jobs (3.11/3.12/3.14) were skipped: this is not a PR. Overall conclusion: **failure**. Q23.6's
`test_a_deep_folder_converts_or_says_its_path_is_too_long` PASSED on Windows (the "converts" branch: the runner has
long paths on). All three `test_a_real_helper_leaves_a_file_newer_than_the_settle_time` cases PASSED there too.
