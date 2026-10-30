# UI polish: handoff (Worker, 2026-10-30)

Branch `agent/ui-polish` from `43cb202` (`dev/v0.0.7`). Brief: [brief.md](brief.md); working notes: [notes.md](notes.md).
Not merged with `dev/v0.0.7` yet (waiting for CoCo's word, after Runner Tools and the TXY Index follow-up land;
expect a small conflict in `helab/io_ops/helab_txy.py`'s `_OWN_FILE`, where this floor changes only `{1,15}` to
`{1,32}`).

## Commits (one per item, brief order except A33.4, built with Q33.3/Q33.4)

| Commit | Item |
|---|---|
| `9c3b12e` | Q33.1 a folder without subfolders is selected, not made the tree's top |
| `fcded20` | Q33.2 default split 380 / rest / 320, kept across restarts; nothing widens the settings panel |
| `f68d63f` | Q33.3 + Q33.4 floated plots open a step apart at 800×600, on screen; a Dock button (one commit: both in `dock.py`) |
| `242d815` | A33.4 the Settings panel names the plot the title-bar Float acts on (option (a), CoCo) |
| `8d196f8` | Q33.5 the Debug menu's three placeholders go |
| `6b21713` | A33.1 Tab out of a plot setting commits and stops, like Return |
| `f9cbd38` | A33.2 offline, Folder details agrees with the summary |
| `6b3e3bd` | A33.3 the temp folder row in prose |
| `401e954` | Q33.7 the settle time is a setting, sent with every request |
| `c274f4e` | tests import sibling modules by bare name (mypy tests found one twice); Q33.2's plot check relaxed |
| `e8bf139` | Q23.6 user tags `u` + 32 hex; path too long said plainly |
| `78db15f` | Q23.6 test fix: the deep folder is always its own (a long basetemp made it `tmp_path` itself) |

## What each does, and the brief's questions

**Q33.1** (`FolderExplorer.on_double_click`, `_navigate_input`, `without_subfolders`, `_select_listed`). Memory only:
the row's listing (`loaded` and no children) or `has_dirs`, else the session's snapshot of the folder (no
subfolder entries) or its scan summary (`has_dirs` False). Double-click on such a row selects it (and the
selection loads it, as a click does). A typed path to such a folder opens its parent and selects the row, at once
when the parent's rows come from memory, else when its listing inserts them (dropped if the user picks another row
first, or opens another path). A folder with subfolders, or never listed, opens as the top as before. Tests:
`tests/test_leaf_navigation.py` (8; frozen IOService, listing events replayed).

**Q33.2** (`HelabMainWindow`). Default 380 px folders, 320 px settings, plots the rest; stretch 0/1/0 so a window
resize changes only the plots. New row `main_window_split` ("<folders>,<settings>", each 80–4000, else the
default), saved as HeLab quits (`save_split` in `closeEvent`); a collapsed panel saves the width it had.
**`--geometry`** sizes and places the window for its one run; the saved widths apply inside it, and the plots take
what is left (a runner's run saves its own widths into its own settings file). **Why the folder panel lost its
room when a plot opened:** the plot's settings page set the right panel's least width to 647 px: the TXY row's note
was a plain unwrapped label (639 px), its two combos sized to their longest item (289 + 211 px), and the Presets
row's three buttons held the style's 80 px least width. Now the note is an `ElidedLabel` (full text in its
tooltip), the combos `AdjustToMinimumContentsLengthWithIcon` (8 characters, the Presets combo 6), the buttons'
least width their text + 16 px. At 1600 px wide with two plots open: [380, 564, 333]. Only Live collapses the
folder panel (Q18.3). On a 1000 px window both side panels shrink toward their least widths when a plot needs room
(no collapse). Tests: `tests/test_main_split.py` (11).

**Q33.3** (`AnalysisDock.place_floating`, from its own `topLevelChanged`). Floated other than by a drag (the
title's float button, a double-click on the title), a plot opens at 800×600, 40 px right of and below the visible
plot floated last (the first: of its docked place), shrunk to and kept on its screen's available area. A drag still
leaves it where it is let go. **Restart:** nothing new needed. The arrangement record (`open_plots`) already keeps
each plot's `floating` flag and the plot area's `saveState`, which holds floating windows' geometry and is restored
after the plots open (`open_arrangement`), so a restart puts them back where the user left them (finding 8's
"come back there" was that, from where Qt had placed them). Tests: `tests/test_floating_plots.py`.

**Q33.4** (`FloatingSettings.dock_button`). The floating window's settings section starts with a Dock button: "⇲"
on the closed strip, "⇲ Dock" open; accessible name "Dock plot", ID `plot_dock`; it docks the plot, whose settings
page returns to the panel. The accessible-names test stays green.

**A33.4** (`PlotSettingsPanel._window_activated`, `_place`, `_show_page`). HeLab has no Float button of its own:
the one beside the Settings panel is Qt's, on the docked plot's title, and acts on that plot. Now, whenever the main
window is active while the shown plot floats (and right after a float if the main window stays active), the panel
shows the most recently shown plot still docked and on screen, so that button acts on the plot the panel names; the
floating plot's window shows its own settings and activating it names it again. Where the panel still says a plot
is away (none docked), it names it: "Settings are in <plot>'s window". **This reverses one tested behaviour**
(`test_a_hidden_floating_plot_falls_back_to_a_visible_one` said "focus back in the main window, not in a plot: two
stays"): the floating plot no longer stays shown in the main window's panel once the main window is active. Why:
it is what made the title's Float act on a plot the panel didn't name. CoCo chose (a); Tony may still choose (b)
(keep the old behaviour and only name the plot): Q~1.

**Q33.5**: "Draw a line in debug console", "Debug - validate tab status" (and its handler) and "Debug - 6" gone;
the runner items, Show all Icons, Show Memory Usage, the visible-rows item and gc.collect() stay.

**A33.1** (`EndsEditOnReturn.widgetEventFilter`). Tab and Shift+Tab take a valid entry (the spin box's
editing-finished step), give the value back for an invalid one, and close the editor (deselecting the row), as
Return does; pyqtgraph's own Tab opened the next row's editor. Choice rows close with the value picked. Three new
tests in `test_parameter_return.py`, which fail on the old code.

**A33.2** (`FolderDetailsPanel`). Offline, data shown unchecked: State "Loaded from cache · not checked (offline)"
(tooltip: work online to check it), and the Loaded row never repeats an earlier "checked, unchanged" for data shown
unchecked (online it is being checked; offline it says "not checked (offline)").

**A33.3**: "Temp folder (a change applies at the next start):" (it is read once at start), worded like "Cache
folder (moving it keeps its contents):"; its Browse dialog says "Choose the temp folder".

**Q33.7** (settle time).
- Setting: row `settle_seconds` (float, 5.0), Settings › General "Read files unmodified for" under Live's check
  interval (3 s default already), 2–60 s, step 0.5; help: it applies to every read (browsing, loads, Live, checks of
  cached data, conversions); below 2 s HeLab can't tell a file still being written. Reader `read_settle_seconds`
  (in `SettingsDialog.py`; constants.py isn't this floor's), range and default from `io_ops.fingerprints`
  (`MIN/MAX/DEFAULT_SETTLE_SECONDS`, `settle_seconds()`), since helpers can't import Qt.
- **Which requests carry it:** every request. `HelabMainWindow._apply_live_settings` (at start and after Settings)
  sets `IOService.settle_seconds`; `IOService._start` stamps it on the attempt (`IORequest.settle`), and `_run`
  sends it as the payload's `settle_seconds`, beside `trace`. So list, details, scan, load, Live checks and saves,
  cached reads, conversions and the local-lane operations all get it (harmless where nothing reads files).
- **Helper side:** `io_helper.main` calls `fingerprints.configure_settle(request.get("settle_seconds"))` first,
  before the trace and any handler; it sets `SETTLE_SECONDS` and `RACY_SECONDS = min(2, settle)`. Every read already
  takes those module values when it runs (`_settled`, `_raw_mtime`, `_quick_mtime`, live's racy margin, convert's
  settle), so no other helper code changed.
- **Fallback:** no `settle_seconds` (`helab convert`, which reads no settings and runs in-process; a request from an
  older HeLab; an in-process caller) or a value that isn't a finite number: the helper keeps its default,
  `DEFAULT_SETTLE_SECONDS` 5 s. A number out of range takes the nearest limit. `HELAB_SETTLE_SECONDS`, when set,
  wins over the request, so tests keep 0. `helab convert --once` still wants 60 s (`ONCE_SETTLE_SECONDS`).
- **`RACY_SECONDS` stays 2 s in practice** (the setting's least is 2 s; only the env override can make it less).
- Logged once per helper (one request each): a debug log line (helpers have no log handler, so it shows only where
  one is configured) and `settle` on every line of the helper's I/O trace.
- Live's reread note no longer says "> 5 s" ("writer paused past the settle time?").
- Tests: `tests/test_settle_setting.py` (49): every dispatch route runs with the request's value; fallbacks and
  limits; the env override; the trace field; `IOService` sends it (or not, with none); a real helper process without
  the env var leaves a 10 s old TXY at 60 s and reads it at 5 s or with none; the reader and default; the spin box;
  the main window passing it on.

**Q23.6** (user tags).
- `USER_TAG_DIGITS` 32; built-in tags unchanged and pinned (`test_convert_profile.py::test_a_builtins_tag_never_changes`). Name patterns take a
  1 + 1–32 character tag (`profile.NAME_TAG`, spelled out in `file_kinds.HELAB_TXY`, `provenance._NAME`/`BARE_NAME`
  and so `partial()`/`own_partial()`, `helab_txy._OWN_FILE`; a test checks each contains it). `TAG_PATTERN`
  (built-ins) stays at 16. A name is 50 characters plus the shot's digits (52 for shot 12, 55 for 99999), 26 more
  while temporary (81 for 99999); the brief's ~56/~82.
- **Tonight's `u` + 8 TXY:** still HeLab TXY (they match), of another tag: a load for the profile ignores them, its
  shots convert again under the 33-character tag, and the old files are never deleted or replaced (Settings › Cache
  still measures and clears them with HeLab's own). Test: `test_tonights_u8_txy_is_another_tags_converted_again_and_kept`.
- **Path too long** (`io_ops.convert.path_too_long`): the OS's own refusal only. ENAMETOOLONG anywhere; on Windows
  WinError 206, or WinError 3 or a FileNotFoundError on a path of 260 characters or more (the error's own file name
  when longer, e.g. the temporary name). A Windows PC with long paths on (as GitHub's runners may be), macOS and
  Linux just write it. Where it's raised: a shot's `txy.write_atomic` (its row is forgotten as before), and making
  HeLab's folder (`os.makedirs`). **What the user sees:** the shot becomes `shot_unconvertible` ("failed") with
  "Path too long for Windows (N characters; the limit is 259 unless long paths are turned on in Windows): <path>.
  Choose a shorter cache or temp folder (Settings), or a shorter folder path": in the Live line's "N unconvertible"
  and its tooltip, a log warning, and `helab convert`'s output; the run goes on with the other shots (each refused
  alike), and like any unconvertible shot it isn't tried again while its raw file is unchanged, this session.
  HeLab's folder that can't be made fails that conversion with the same wording (the convert error the Live line
  shows). **A Windows PC without long paths** converting beside raw files in a folder of ~210+ characters, or with a
  cache/temp folder that deep, sees that message per shot (or once for the folder).
- Tests: `tests/test_user_tags.py` (18), including the message from a patched failing write on every OS, and a real
  conversion in a folder whose TXY path passes 260 characters that converts (macOS here) or must give exactly that
  message (Windows CI without long paths).

## Checks

- Full suite inside the checkout (`pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`) and once
  outside (`--basetemp` in the scratchpad): results below. Type checks: `mypy helab/ --strict` and with
  `--platform win32`, `mypy tests --strict`, `pyright helab tests` and `--pythonplatform Windows`: all clean.
- No GUI launch: every check here is offscreen; the manual checks are M~1–M~3.

Results (at the Q23.6 test fix, before any merge of `dev/v0.0.7`):

- Inside the checkout, `--basetemp=.ai/temp/pytest`: **8401 passed, 669 skipped, 2 warnings in 134.57 s; no RERUN.**
- Outside, `--basetemp=<scratchpad>/pytest out` (a space in the path): first run **1 failed after 5 reruns**,
  `test_user_tags.py::test_a_deep_folder_converts_or_says_its_path_is_too_long`, rerun reasons `FileExistsError:
  [Errno 17] File exists: …/pytest out/popen-gw1/test_a_deep_folder_converts_or0` (and or1–or3): my test's bug, a
  temp folder already 230+ characters long made it create `tmp_path` itself. Fixed (next commit); the run again:
  **8401 passed, 669 skipped, 2 warnings in 142.98 s; no RERUN.**
- Partial runs during the work had two RERUNs, both the pre-existing worker crash in
  `test_accessible_names.py::test_every_script_and_each_library` ("worker 'gw0' crashed while running …"; the
  finding below). Not seen in the full runs.

## Finding (for known-issues; not this floor's code)

`test_accessible_names.py::test_every_script_and_each_library` crashed its xdist worker in 2 of ~5 partial runs here,
passing on rerun. The macOS crash reports are **SIGSEGV**, not the known SIGTRAP: main thread, a `QDockWidget` deleted
(DeferredDelete) → children deleted → `QObject::destroyed` → `PyQtSlotProxy::unislot` → a Python callable →
segfault in `_PyEval_EvalFrameDefault`. The likely connection is `helab/analysis/panes.py:32` (`PlotlyPane`:
`self.destroyed.connect(lambda *_: server.remove_plot(plot_id))`). **The base `43cb202` does it too** (a temporary
worktree, the same three test files 4×: 3 crashes, the same stack). CoCo has asked Smoke ready's floor to look (A~1).

## Proposed doc changes (for the Coordinator)

- **AGENTS.md**, I/O rules, "Files still being written (modified within `SETTLE_SECONDS` = 5 s, …)": → "modified
  within the settle time (Settings › General, `settle_seconds`, default 5 s, 2–60 s; `fingerprints.SETTLE_SECONDS`
  in helpers, sent with every request), …". UI rules: nothing new (Dock button and splitter are area detail).
- **app-runtime-and-ui.md**, UI: Q33.1 (double-click / typed path to a folder without subfolders selects it, memory
  only, `FolderExplorer.without_subfolders`); the main split (380/rest/320, `main_window_split`, saved at quit,
  stretch 0/1/0, `--geometry` one run with the saved widths inside it; nothing in a plot's settings sets the panel's
  width: elided TXY note, shrinking combos, Presets buttons to their text); Debug menu: drop the placeholders from
  any list; Folder details offline wording (A33.2).
- **plots-and-scripts.md**, "The Settings panel and floating plots": floated (not dragged) plots open 800×600, 40 px
  from the last floated, on screen (`AnalysisDock.place_floating`); restart via the arrangement's dock state; the Dock
  button (`FloatingSettings.dock_button`, `plot_dock`); A33.4's rule (main window active while the shown plot floats
  → the docked plot in front shows; away line "Settings are in <plot>'s window"); A33.1 (Tab/Shift+Tab commit and
  close like Return) next to the Return/Escape sentence.
- **settings.md**: rows `main_window_split` and `settle_seconds` (with `read_settle_seconds` in SettingsDialog.py;
  range/default in `io_ops.fingerprints`).
- **io-and-browsing.md**: "Files still being written" and the "Settle means two things" sentence: the setting, its
  default, every request carries `settle_seconds`, `configure_settle` first in `io_helper.main`, fallback 5 s
  (`helab convert`, old requests), `HELAB_SETTLE_SECONDS` wins, `RACY_SECONDS` 2 s in practice, `settle` on trace
  lines. The patched-names list: `fingerprints.SETTLE_SECONDS` is now also set by `configure_settle` (tests patch it
  as before).
- **converter.md**: "other profiles are tagged `u` + 8 hex digits" → 32 (Q23.6), `NAME_TAG` (33 characters at most in
  names; `TAG_PATTERN` 16 for built-ins), old `u`+8 TXY treatment, `path_too_long` and its message.
- **testing.md**: `tests/test_settle_setting.py` (the env override wins; tests that need the request's value patch
  `fingerprints._SETTLE_OVERRIDE`); sibling test modules are imported by bare name (`from test_x import …`), never
  `tests.test_x` (mypy sees the file twice); the SIGSEGV note above.

## Proposals (provisional numbers)

- **Q~1** A33.4: keep (a) (the main window's panel shows the docked plot in front while the shown plot floats), or
  (b) the old behaviour with only the away line naming the plot? Proposed: (a), as built.
- **Q~2** The temp folder row says a change applies at the next start; should Settings offer to restart, or apply it
  live like the cache folder's move? Proposed: leave it (rarely changed).
- **A~1** Fix the SIGSEGV on plot dock deletion (`panes.py:32`'s lambda on `destroyed`; connect a module-level
  function holding only the server and ID, or disconnect in the pane's close) and add it to known-issues meanwhile.
- **A~2** `read_settle_seconds` could move to `constants.py` beside `read_live_interval` (not this floor's file).
- **A~3** `events.ShotUnconvertibleEvent`'s docstring could name the path-too-long message among "failed" reasons.
- **M~1** On a real screen: open two plots and check the split (folders 380, settings ~330, plots the rest), drag the
  splitters, quit, relaunch: the widths come back; Live on still collapses the folder panel.
- **M~2** Float two plots from their title's float button: they open 800×600 a step apart; the Dock button docks
  each; with one floating and the main window active, the panel names the docked plot and its title's Float floats
  that one.
- **M~3** On a lab Windows PC without long paths, a user profile converting beside raw files in a deep folder shows
  "Path too long for Windows …" in the Live line's tooltip (or check `LongPathsEnabled` there and note it).
- **M~4** Settings › General: set the settle time to 10 s and watch Live on a run being written: shots appear ~10 s
  after their file stops changing (fold into M33.1's measurement on a live run).
