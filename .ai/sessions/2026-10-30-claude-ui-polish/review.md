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

---

# Round 2 (Reviewer, 2026-10-30): `e53f0f8..3af2791`

**Verdict: one finding is still open (High R2-1), so the floor can't land yet.** It is a small fix. Round 1's
High 1, High 2, Low 1, Low 2 and the nits are fixed. CI 41011506627 is green on every job with no RERUN.

## Checks rerun here (macOS, HEAD 3af2791)

- **Full suite:** `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review -rR` gave
  **8468 passed, 669 skipped, 0 RERUN** (146 s; log in `.ai/temp/review-r2-suite.log`).
- **Type checks, all clean:**
  - `mypy helab/ --strict`: 195 files.
  - `mypy tests --strict`: 173 files.
  - Both again with `--platform win32`.
  - `pyright helab tests`, and again with `--pythonplatform Windows`: 0 errors.
- **Touched tests three times** (destroyed connections, main split, floating plots, user tags, settle setting,
  presets plots, accessible names, Debug runner menu; `-n 4` with reruns): 186 passed each time, no RERUN.
- **Probes,** scratch tests under pytest's conftest; nothing in the repo was edited:
  - whether a closed Plotly plot's figure leaves the server without `gc.collect()`;
  - which object keeps it;
  - the RAM-budget release;
  - the settings panel at 320→80 px, at fonts ×1, ×1.25 and ×1.5, listing cut and squashed controls, with
    screenshots;
  - which forms of a `destroyed` connection the AST guard catches.

## Findings

### High R2-1: a closed Plotly plot's figure stays on the Dash server until Python's next full cyclic GC (86d32ce)

`helab/analysis/panes.py:34`: `weakref.finalize(self, server.remove_plot, self.plot_id)` frees the figure only
when the pane's Python object goes. The handoff (line 15) says "the plot's instance is dropped on close". It is
not reachable, but it isn't freed either:

- **What holds it:** the closed `AnalysisInstance` is cyclic garbage. Its own children hold bound methods back to
  it: `PresetBar`, `TxySourceRow` and `CachedRuns` hold `set_txy_source`, `_cached_found`, `_cached_run` and so
  on. Its `__dict__['_content']` holds the `PlotlyPane`, and a closure cell holds the pane too.
- **So nothing frees it on its own.** Reference counting never does. Only a cyclic collection does, and by the
  time the plot closes these objects are old, so it takes a full one.

**Failure, reproduced:**
- **Steps:** a real `HelabMainWindow` opens 3D scatter (Plotly). Close Plot Tab closes it. The test then sends
  `DeferredDelete` events every 50 ms, with no `gc.collect()`.
- **Result:** `dash_server.snapshot(plot_id)` was still the figure **after 30 s**, with GC enabled (Python
  3.13.15, thresholds 2000/10/10). One `gc.collect()` freed it at once.
- **Before 86d32ce:** the lambda on `destroyed` freed it at the C++ deletion, right after the close.

**What a user sees:**
- **A stale browser page.** The page in the browser keeps showing the closed plot. `DashServer`'s contract
  (`helab/utils/dash_server.py:30`) is that a page still open says the plot is closed and stops polling.
  Lab PCs can't paint QtWebEngine, so on those PCs the browser page is where Plotly plots are seen
  (memory `results/lab-pc-qtwebengine-black-render.md`). An idle HeLab may keep it for minutes.
- **Memory.** Each closed Plotly plot's figure (3D scatter: up to the 100k-point sample) stays in RAM until a
  full GC. The RAM budget doesn't see it.

**The RAM-budget release is fine.** I probed it without `gc.collect()`: `release()` replaces `_content` on a
live instance, the old pane is freed by reference counting, and the figure leaves at once.

**Fix (small; keeps the SIGSEGV fix):**
- Keep the finalizer, `self._free = weakref.finalize(...)`, and call `self._free()` when the plot closes.
  `finalize` objects run once, so calling it again is harmless.
- The call could go in `LinkedAnalysisInstance.close` (`helab/views/plots/instance.py:134`), for each
  `PlotlyPane` in the dock before `dock.deleteLater()`. Or add a `PlotlyPane.release_figure()` that the close
  path calls.
- This is a plain Python call on the GUI thread from a `@pyqtSlot`, not a callable on `destroyed`. The finalizer
  stays as the fallback for a dock deleted unclosed.

**Tests that would catch it:** the new real-window test, `test_closing_a_plotly_plot_frees_its_figure_once_the_plot_is_dropped`
(`tests/test_destroyed_connections.py:87-89`), and the three `figure_freed` helpers call `gc.collect()` inside
their wait, so they pass even though the app never frees the figure. Without the fix, at least the real-window
test and one of the older close tests should:
- wait with `gc.disable()`, or simply without `gc.collect()`;
- and fail.

### Low R2-2: the settings panel can be dragged to 80 px, where it is unusable, and that width comes back at the next start (afd6b32)

`helab/views/HelabMainWindow.py:1007` sets `right_panel.setMinimumWidth(self.MIN_PANEL_WIDTH)`, which is 80
(line 1268). That fixes High 1: the default 380/320 holds on Windows CI, and the split tests ask for it exactly
and pass on all three OSes. But 80 px is far below what the panel's controls need. Measured with 4 interactive
controls cut or squashed ("cut": the control runs past the panel's right edge; "squashed": narrower than Qt's
least width for it):

**Test window, macOS, offscreen (Fusion), 9 pt, with T, X, Y histograms:**
- **The contents' least width is 327 px.** At the default 320 nothing is cut.
  - The preset row's buttons sit just under Qt's 80 px least width for a button with text. Their text still
    shows; "Delete…" is just cut.
  - The parameter tree's Value column needs its horizontal scroll bar.
- **At 240 px:** "Load Scripts…" (`load_scripts`) and Delete… (`preset_delete`) run past the panel's edge.
- **At 200 px:** both are still cut, and the TXY combos are unreadable.
- **At 80 px:** Apply, Save… and Delete… are cut, every combo is 13–24 px wide, and Rerun is cut to "with these
  se". The panel is unusable.

**Wider fonts (×1.5, near Windows' Segoe UI at a higher scale):**
- The contents' least width is 408 px.
- At the default 320, "Load Scripts…" and Delete… are cut but usable (screenshot checked).
- At ×1.25 nothing is cut at 320.
- So the handoff's M~1 note (a large display scale may cut the Scripts row's button) is right.

**Why Low:** it is the user's own drag and it recovers by dragging back. But:
- `_remember_panel_widths` keeps any width ≥ 80, and `read_split` restores it, so an accidental near-collapse
  comes back at every start;
- before this change the splitter stopped at the contents' least width.

**Fix (either):**
- set the panel's least width to about **240 px** (where nothing is cut at the macOS font) instead of 80, and use
  the same threshold in `read_split` and `_remember_panel_widths`;
- or `min(contents' least width, 320)`.

Both keep Windows at 320 and stop the unusable range. Tony's call if he prefers 80; then it's a DECISIONS_TODO
line, not a blocker.

### Nit R2-3: the `destroyed` guard has blind spots (none of which exist in helab today)

`tests/test_destroyed_connections.py:35` checks only `<x>.destroyed.connect(<positional non-Attribute>)`. I ran
its rule on each form:
- **Caught:** a lambda; `functools.partial(...)`.
- **Missed:**
  - `w.destroyed.connect(slot=lambda: ...)`: the keyword form (`node.args` is empty);
  - `w.destroyed[QObject].connect(...)`: the overload subscript;
  - `sig = w.destroyed; sig.connect(...)`: a signal stored first;
  - `w.destroyed.connect(self.cb)` where `self.cb` is a lambda or partial: an attribute passes as a "bound
    method".

**No false negatives on what exists.** `grep destroyed helab/` finds exactly two connections. Both are
`@pyqtSlot` methods on QObjects, which are real Qt slots and need no PyQt proxy:
- `instance.py:122`: `dock.destroyed.connect(self.close)`;
- `settings_panel.py:162`: `dock.destroyed.connect(self._forget_deleted)`.

**Cheap tightening:** also scan `node.keywords`, and accept `node.func.value` being an `ast.Subscript` of
`.destroyed`.

## Round 1 findings: fixed

- **High 1 (afd6b32):** fixed (with Low R2-2's caveat).
  - What it changed: the Scripts row shrinks (the combo to 8 characters, the button to its text), the panel's
    least width is set, and the widths are applied again at the first show from the splitter's real width.
  - On Windows CI the default split test (exactly 380/320) and the restart test pass.
  - Each split assertion now reports any wide widget when it fails.
- **High 2 (4bfd6ad):** fixed. `setattr(error, "winerror", …)`, and `mypy tests --strict --platform win32` is
  clean here.
- **Low 1 (6ef90bb):** fixed. `AnalysisDock.event` marks a `MouseButtonDblClick` while Qt handles it, and
  `_floated` places the plot then. There is a new test that double-clicks the title.
- **Low 2 (0de7d3c):** fixed as proposed.
  - The new rule: on Windows, a not-found error on a path of 260+ characters counts as "too long" only while the
    target's folder still exists. That check is a traced `_isdir`, run in the helper.
  - When the folder is gone, the run fails and the next check retries.
  - WinError 206 and `ENAMETOOLONG` still refuse the shot.
  - `PLATFORM` is a module name that tests patch.
  - The docstring's "(5 s)" is fixed too.
- **Nits (4a6174d, a909960):**
  - **Settle limits:** they're in `helab/utils/settle_time.py` (standard library only), and `SettingsDialog` no
    longer imports any `helab.io_ops` module (test-enforced).
  - **Arrow style:** the help text says "Settings →".
  - **No settle constant read by value.** Every reader still goes through `fingerprints.SETTLE_SECONDS` /
    `RACY_SECONDS` as module attributes. This includes what came in from dev: `convert.py:519`, `live.py:92`,
    `fingerprints.py:85/99/101`. `helab convert` still falls back to the default.

## The merges (ff4abb4 ← cb05f27, 04e9ac0 ← 7b51c84): nothing of the landed floors changed

For each merge M, I looked at:
- **`git diff M^2 M`:** every file that differs from dev is one this floor changed (none outside).
- **`git show --remerge-diff M`:** empty for both, so the merges were clean and nothing was resolved by hand.
- **Files both sides changed:**
  - ff4abb4: `explorer_live.py`.
  - 04e9ac0: `convert.py`, `helab_txy.py`, `HelabMainWindow.py`, `test_convert_helab.py`.
  - Git merged them without conflicts, and the merged code passes the suite and type checks.

## The four older Plotly tests (971c348)

They now drop their own references to the pane and instance before waiting. That part is legitimate: a test that
holds the pane keeps it alive. But each wait now calls `gc.collect()` (`figure_freed`):
- `tests/test_analysis_gui.py:793`
- `tests/test_live_plots.py:1558`
- `tests/test_plot_ram_budget.py:873`

So the tests no longer prove that **closing** frees the figure, only that a forced full collection does, which
HeLab never runs. That is exactly how High R2-1 got through. All their other assertions are unchanged (the page
updated in place, the camera kept, the snapshot of the released plot).

- **RAM-budget test** (`test_plot_ram_budget.py`): this one would pass without the collection too (probed).
- **Two close tests** (`test_analysis_gui.py`, `test_live_plots.py`): after the fix, they should wait without
  `gc.collect()`.

The Presets test (`test_presets_plots.py:1683-1691`) collects so it can count receivers. That's fine: an extra
connection to a label that is gone does nothing (`shown()` checks the weak ref).

## CI 41011506627 (3af2791, agent/ui-polish): success

| Job | ID | Result |
|---|---|---|
| Detect branch and version bump | 123918212423 | success |
| macos Build / ubuntu Build / windows Build | 123918278075 / 123918277961 / 123918278044 | success |
| macos Tests (1/2) | 123918278264 | 4222 passed, 322 skipped, no RERUN |
| macos Tests (2/2) | 123918278348 | 4246 passed, 347 skipped, no RERUN |
| ubuntu Tests (1/2) | 123918278230 | 4220 passed, 324 skipped, no RERUN |
| ubuntu Tests (2/2) | 123918278174 | 4246 passed, 347 skipped, no RERUN |
| windows Tests (1/2) | 123918278222 | 4207 passed, 335 skipped, no RERUN |
| windows Tests (2/2) | 123918278100 | 4228 passed, 363 skipped, no RERUN |
| Converter backends macos / ubuntu / windows | 123918278261 / 123918278097 / 123918278167 | 696 / 696 / 695 passed, no RERUN |

- **No RERUN:** I grepped every Tests and Converter job's log for "RERUN".
- **Passed on all three OSes:**
  - `test_every_script_and_each_library`;
  - every `test_main_split` test, including the exact 380/320 one on Windows;
  - every `test_destroyed_connections` test.
- **Skipped:** the compat jobs (3.11/3.12/3.14) and the draft-release job. This isn't a PR.
- **Round 1's single RERUN** (`test_gui_responsiveness ...[1]` on Windows) didn't recur. The round 1 proposal
  still stands: add `[1]` to its known-issues entry.

## Docs the handoff should propose (round 2)

- **app-runtime-and-ui.md / plots-and-scripts.md:**
  - a Plotly figure leaves the server when its plot closes, with `weakref.finalize` as the fallback, once
    R2-1's fix is in;
  - the "no Python callable on `destroyed`" rule (the handoff already proposes it for AGENTS.md).
- **testing.md:** a test of freeing on close must not call `gc.collect()` in its wait, or it can't tell
  "freed at close" from "freed by a full collection".

---

# Round 3 (Reviewer, 2026-10-30): `3af2791..9d19098`

**Verdict: nothing open that blocks landing.** Round 2's High R2-1, Low R2-2 and Nit R2-3 are all fixed. CI
41016672207 is green on every job with no RERUN. I have two optional nits (below); they don't need a code
change before landing and could go to AI_TODO.

## Checks rerun here (macOS, HEAD 9d19098)

- **Full suite:** `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review -rR` gave
  **8473 passed, 669 skipped, 0 RERUN** (146 s; `.ai/temp/review-r3-suite.log`).
- **Type checks, all clean:**
  - `mypy helab/ --strict`: 195 files.
  - `mypy tests --strict`: 173 files.
  - Both again with `--platform win32`.
  - `pyright helab tests`, and again with `--pythonplatform Windows`: 0 errors.
- **Round 2's probe again** (a real window, 3D scatter in Plotly, Close Plot Tab, posted deletes, **no
  `gc.collect()`**): the figure is off the server **at once (0.0 s)**, with GC enabled and with GC disabled.
  Before this fix it was still there after 30 s.

## R2-1 (2c13796): fixed

- **What changed:**
  - `PlotlyPane.release_figure()` (`helab/analysis/panes.py:58`) calls the stored `weakref.finalize`.
  - `release_figures()` (`helab/views/plots/dock.py:178`) runs from two places:
    - `AnalysisDock.setWidget` (`dock.py:315`), on the plot it replaces;
    - `LinkedAnalysisInstance.close` (`instance.py:153`), before `deleteLater`.
  - The finalizer stays as the fallback, for a dock deleted unclosed.
  - No Python callable sits on `destroyed`, and the guard still passes.
- **Tests:**
  - The four older Plotly tests are back to their original form (971c348 reverted).
  - The real-window test checks `snapshot is None` straight after the close, while it still holds the pane.
  - New: release twice frees the figure once; a wrapper around the same pane keeps it; a plot drawn anew frees it.

**Your two questions:**
- **Closed twice: safe.** `LinkedAnalysisInstance.close` returns early once `is_closed` is set. A
  `weakref.finalize` runs at most once, so later calls, and the pane's own collection, do nothing (the new test
  checks this).
- **Replaced while Live updates it: safe on every path I traced.**
  - **Live update in place:** `script.update` calls `server.update_plot` on the same pane, and
    `set_plot_result` keeps the wrapper (`content.parentWidget() is old`). So there's no `setWidget` and nothing
    is released.
  - **A wrapper around the same pane:** `_wrap_plot` moves the pane into the new wrapper *before*
    `dock.setWidget(wrapper)`. So the old wrapper's `findChildren` no longer holds the pane, and it isn't
    released.
  - **Another library, an error message, or a RAM-budget release:** the old pane is released at once and
    `_content` points to the new widget. A Live result that lands after that updates the new widget:
    `_updated` uses `self._content`, and skips when `released` is set or the library differs.
  - **After close:** `_finished` returns on `is_closed`, so no update reaches a closed pane.

### Nit R3-1: `update_figure` after `release_figure` would put the figure back for good (unreachable today)

`helab/analysis/panes.py:53`: `update_figure` calls `server.update_plot`, which is `add_plot`. If it ever ran
after `release_figure`, the figure would go back on the server, and the spent finalizer would never remove it.

Probed: `release_figure()` then `update_figure(go.Figure())` leaves `snapshot` present, with
`_free.alive == False`.

None of the app's callers can do this (the paths above). A one-line guard would make it impossible:
`if not self._free.alive: return` at the top of `update_figure`.

## R2-2 (e0afa54, 9d19098): fixed

- **What changed:**
  - `MIN_SETTINGS_WIDTH = 250` (`HelabMainWindow.py:1272`) is now the panel's least width.
  - `read_split` and `_remember_panel_widths` use the same threshold. The settings row's help says "settings
    250 to 4000".
  - The Presets and Scripts combos shrink to 3–4 characters, and their buttons to their text + 8 px.
- **The new test** (`test_the_settings_panel_goes_no_narrower_than_its_controls_need`) drags the panel shut. It
  checks that the panel stops at 250 and that no button or combo outside a scroll area is cut.
  - It runs on macOS only, with the reason in the skip.
  - CI: PASSED on macOS, SKIPPED on Windows and Ubuntu.
  - `read_split` cases `80,249` → default and `80,250` → kept are added.

**Your question, a fixed 250 vs a least width per platform:**

**Keep the fixed 250. A per-platform constant isn't worth it.**
- **The default holds.** It is 320 everywhere and the split test checks it exactly on all three OSes. A width
  under 320 only happens if the user drags it there, and dragging back fixes it.
- **CI's fonts aren't the lab's.** CI's Windows and Ubuntu runs use the offscreen platform's fonts, not
  Segoe UI at the lab PC's scale. A Windows constant tuned to CI ("Load Scripts… is 188 px") would be a guess
  about the real PCs. The handoff's M~1 (look at the lab PC) is the right check.
- **At 250 on those fonts, only one row end is cut.** Windows CI cuts "Load Scripts…"; Ubuntu cuts Delete… by
  3 px. Both are still recognisable and come back when the panel is widened. Round 2's ×1.5 screenshot shows
  the same kind of cut.
- **If Tony wants "never cut" everywhere:** the adaptive form `max(250, min(contents' least width, 320))` does it
  on every font without per-platform numbers. On a wider font that means the panel can't go below 320. That is a
  behaviour choice, so it would be a DECISIONS_TODO line, not something to do before landing.

### Nit R3-2: the wider-font test lost its lower bound again

`tests/test_main_split.py:100` is now `assert right <= 320`. Round 2 had `0 < right <= 320 and left > 0`. A
settings panel collapsed to 0 at the doubled font would pass now. Restoring `0 < right` would still pass on
Windows CI, which gave 154 px in round 2's run. Optional.

## R2-3 (2c13796): fixed

The guard now catches:
- `connect(slot=…)`;
- `destroyed[QObject].connect(…)`;
- a signal stored in a name first.

The scan test covers each form, and also that `w.clicked.connect(gone)` is not flagged. The only form still
passing is an attribute that holds a lambda (`self.cb`). An AST scan can't tell that from a bound method, so
that's fine. helab still has exactly the two `@pyqtSlot` connections.

## CI 41016672207 (9d19098, agent/ui-polish): success

| Job | ID | Result |
|---|---|---|
| Detect branch and version bump | 123934455895 | success |
| macos / ubuntu / windows Build | 123934534910 / 123934534892 / 123934534744 | success |
| macos Tests (1/2) | 123934534900 | 4225 passed, 322 skipped, no RERUN |
| macos Tests (2/2) | 123934534856 | 4248 passed, 347 skipped, no RERUN |
| ubuntu Tests (1/2) | 123934534703 | 4221 passed, 325 skipped, no RERUN |
| ubuntu Tests (2/2) | 123934534669 | 4249 passed, 347 skipped, no RERUN |
| windows Tests (1/2) | 123934534729 | 4209 passed, 336 skipped, no RERUN |
| windows Tests (2/2) | 123934534888 | 4230 passed, 363 skipped, no RERUN |
| Converter backends macos / ubuntu / windows | 123934534717 / 123934534777 / 123934534755 | 696 / 696 / 695 passed, no RERUN |

- **No RERUN:** no "RERUN" appears in any of the nine test logs.
- **On all three OSes:**
  - `test_closing_a_plotly_plot_frees_its_figure_as_it_closes` and
    `test_a_plot_drawn_anew_in_its_dock_frees_the_old_figure` PASSED;
  - the 250 px test PASSED on macOS and was SKIPPED on Windows and Ubuntu.
- **Skipped:** the compat and release jobs. This isn't a PR.

## Still to apply at landing (from earlier rounds)

- Add `test_gui_responsiveness …[1]` to its known-issues entry (round 1; no rerun since).
- The docs proposals from rounds 1 and 2, including:
  - AGENTS.md: the "no Python callable on `destroyed`" rule;
  - testing.md: a test of freeing on close doesn't call `gc.collect()` in its wait.
- M~1: a look at the lab PC at 250–320 px.
