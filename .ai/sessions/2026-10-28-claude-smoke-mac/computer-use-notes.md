# Computer-use notes: the smoke-pass dry run on Tony's Mac (A5.1)

Written 2026-10-28 by Claude (Sonnet 5.5) during the dry run, while M1.7 was still loading. The
per-check results are in [results.md](results.md); the runbook is
[../2026-10-28-claude-smoke-automation/plan.md](../2026-10-28-claude-smoke-automation/plan.md).
This note is what the run taught about driving HeLab with computer use, and what the next build
could change so a full pass runs unsupervised, without taking Tony's cursor.

## What worked

- A built `dist/HeLab.app` is drivable (bundle ID `au.edu.anu.he-bec-lab`). Menus, tabs, text
  fields, buttons and dialogs all responded.
- The path bar takes a full path, so the tree never needs expanding.
- Reading state from screenshots was reliable: the summary lines, Folder details, status bar and
  plot tooltips contain enough literal text to pass or fail a check (e.g. "saved in the disk
  cache", "From disk cache", "not listed while online").
- M1.1, M1.2, M1.4, M1.5 and M1.6 passed end to end this way.

## What forced full-screen control (took Tony's cursor)

| Blocker | Why | Workaround used |
|---|---|---|
| Source run (`venv/bin/helab`) | It is a bare `python` process with no bundle ID, so no `app_*` tool can target it and its window is hidden from screenshots | Build the `.app` (`pyinstaller HeLab.spec --clean -y`, several minutes) |
| Dropdowns and menu buttons (script Group, Presets row) | `app_click` refuses pop-up controls in the background | Full-screen click, or keyboard: click an empty part of the script list, shift+Tab twice, Down |
| An open Qt popup | Every click and key then failed ("Could not verify which document this window is editing") until Tony clicked the item himself | Don't open the popup; use the keyboard route |
| Plot tab "x" icons | Clicks did nothing | The dock title-bar "x" worked |
| Quit | File › Quit clicked before the menu opened left the process running, and two instances then shared the bundle ID | Check `pgrep` after quitting; quit each instance in turn |
| Cmd+Q | Needs the `systemKeyCombos` grant | File › Quit |
| Saving screenshots | `app_*` tools can't write files, and `screencapture -l <id>` from the shell fails ("could not create image from window") | Quote the seen text in `results.md` instead of `shots/` |
| Waiting | A 768 MB folder takes about 10 minutes to load from the share | Background timers |

The background (`app_*`) route handles about 70% of the steps. The rest is dropdowns, popups and
the missing bundle ID. Fixing those in the app is cheaper than working around them each time.

## Suggestions for the next build

Ordered by how much unsupervised time they save.

1. **Give every action a menu-bar item.** `app_menu` works in the background and never needs the
   cursor. Candidates: Scripts › <group> › <plot> (run a plot), Scripts › Group › <name>, Window
   › <tab>, Window › Close plot, Settings tabs, Help › About HeLab (it is under the HeLab menu on
   macOS, which the runbook got wrong). This removes the dropdown and tab-icon problems entirely.
2. **A control channel for tests.** A `--smoke` flag or `HELAB_SMOKE_CONTROL=<socket>` that accepts
   JSON commands (`select_folder`, `run_script`, `set_param`, `quit`) and returns state (summary
   lines, Folder details, status bar, each plot's source line and tooltip text, plot count). A
   runner then asserts on text instead of reading pixels, and the runbook's `See:` lines become
   fields. It must stay off by default and never touch source folders or the cache store itself,
   so the I/O invariants in AGENTS.md hold.
3. **Save the screenshots from inside the app.** A `Debug › Save window screenshot…` (or the
   control channel's `shot <name>`) writing `shots/M1.x-n.png` with `QWidget.grab()`. This closes
   the gap with the runbook's `Shot:` lines, and it works on the lab PCs where the QtWebEngine
   pane renders black (the grab of the Qt side still works; the plot HTML export covers the
   rest).
4. **Accessibility names.** `setAccessibleName` on the path bar, Live, Settings, Cancel loading,
   preset buttons, the Group combo and each script's Plot button, so `app_ax_find` can find them
   by title. Today several show as "(title withheld)" or an index, and clicks go by pixel.
5. **A bundle ID for source runs on macOS.** Either a `helab-dev` launcher that runs inside a
   small `.app` stub (a copy of `python.app` with its own `CFBundleIdentifier`), or a documented
   `make app` step that rebuilds `dist/HeLab.app` in under a minute (a `--debug`/alias-mode build).
   Until then the runbook's `START_COMMAND` on macOS must be the built app.
6. **Quit that confirms.** `File › Quit` should exit within a second or show why not, and the
   control channel's `quit` should return only when the process has exited, so a runner never
   starts a second instance.
7. **No modal popups in routine paths.** Prefer a plain list or a menu-bar item over a combo whose
   popup can wedge the accessibility tree. The Replace / Cancel / Add dialog is fine (a native
   sheet worked), but a popup combo was not.
8. **Stable window geometry.** Open at a fixed size and position (`--geometry 1600x928+0+39`) so
   coordinates in the runbook match what the runner sees. Panels shifted when the preset status
   line appeared, so every click after it needed a fresh screenshot.
9. **Test data that doesn't need the lab share.** A small bundled fixture tree with a
   `.helab-root` (a few TXY folders, a few hundred shots) so M1.2 to M1.6 run in seconds and the
   dry run never waits ten minutes on a share. The release pass on real data stays as M1.7.
10. **A results file the app helps write.** The control channel's `note <text>` appends to
    `results.md` with a timestamp, so an interrupted run keeps its findings.

## Runbook changes to make (for Tony or the Assistant to apply)

- About HeLab is in the HeLab menu on macOS; there is no About in Help.
- `START_COMMAND` on macOS is the built `.app`, not `venv/bin/helab`. Quit any running HeLab
  first, because the bundle ID is shared and an old build can answer instead of the new one.
- "Presets row › Save as new preset…" is the plot settings panel's **Save…** button. The
  arrangement preset is Presets › `<name>` (not a submenu) and opens Replace / Cancel / Add.
- File menu items to avoid: **Place .helab-root in "<folder>"…**. Work Offline is in this menu.
- M1.5-3 clears the machine's own saved results too (3 saved results, 107 kB, here), so the
  runner must ask the supervisor first, or the runbook must say it is expected.
- The app restores the last session (folder, plots, script group resets to "Basic plots v1"), so
  M1.1-1 does not start blank; M1.2 step 3 needs a re-select of CACHED_FOLDER after the restart.
- Rule 5 (stop on unknown dialogs) held up: nothing unexpected appeared except the stuck popup.

## Open questions for Tony

- Which of suggestions 1 to 3 should become roadmap items? 1 and 3 are small; 2 is a real design.
- Is a control channel acceptable against the "GUI never touches source folders" rule? Proposed
  answer: yes, if it only drives the existing UI actions and reads memory state.
- Should the dry-run model stay Sonnet 5.5 (Q5.1)? Sonnet read every screen correctly, but most
  of the cost was waiting and recovering from the blockers above, not reading text, so a smaller
  model would likely do as well once those blockers are gone.
