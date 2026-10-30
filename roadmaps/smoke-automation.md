# Unsupervised smoke runs (build changes for computer use)

Added 2026-10-28. Tony approved these in Chat the same day (Q5.2), after the first dry run of the
[runbook](../.ai/sessions/2026-10-28-claude-smoke-automation/plan.md) on his Mac. The evidence is in
[results](../.ai/sessions/2026-10-28-claude-smoke-mac/results.md) and
[computer-use notes](../.ai/sessions/2026-10-28-claude-smoke-mac/computer-use-notes.md).

**Goal:** a model drives the whole release smoke pass (M1.1–M1.10) in the background, without
taking the user's cursor or full-screen control, and saves its own screenshots.

## Approved (Tony, 2026-10-28)

1. **Menu-bar actions.** A menu item for every action a runner needs: run a plot, pick the script
   group, switch to and close a plot tab, open each Settings tab. `app_menu` works in the
   background and needs no cursor, so the dropdown, popup and tab-icon blockers go away.
2. **Save screenshot.** An in-app command that writes a window (or plot pane) image to a folder,
   so `shots/M1.x-n.png` exists without the screen tools.
3. **Test control channel (`--smoke`).** JSON commands in (`select_folder`, `run_script`,
   `set_param`, `quit`), memory state out (summary lines, Folder details, status bar, each plot's
   source line and tooltip). Off by default. Design first (it must keep the I/O rules in
   AGENTS.md: the GUI never touches source folders or the store, and the channel only drives
   existing UI actions and reads memory).
4. **Apple accessibility labels** (Tony's addition): `setAccessibleName` and descriptions on the
   path bar, toolbar buttons, Group combo, each script's Plot button and preset buttons, so
   `app_ax_find` finds them by title instead of by pixel.
5. **A dedicated debug/smoke menu** (Tony's addition, with a question mark: shape to confirm).
   One place for the runner-facing items: screenshot, trace on/off, state dump, quit that waits
   for the exit. Decide whether it extends the existing Debug menu or is a separate "Smoke" menu
   shown only with a flag.
6. **The rest, as they come:** a bundle ID for source runs on macOS; a quit that confirms the
   process exited; a fixed window geometry option; a small fixture tree with a `.helab-root`
   so M1.2–M1.6 run in seconds; a note command that appends to `results.md`.

## Status (2026-10-30)

Items 1, 2 and 4 are done (`agent/smoke-ready`, landed `4ad8ac5`): names, descriptions and stable IDs
on every control (test-enforced), the runner's items in the existing Debug menu (item 5, answered by
Q5.2.5), Save Window Screenshot (to a picked file or, without a dialog, to the temp folder). Of item 6
and the Mac pass's extras (Q31.2): stable IDs, Dump State, Quit that confirms (with the quit window
listing every pending operation), `--geometry` and the two plot bugs are done there; milestone log lines and the dev `.app` stub (`dev/dev_app.py`) landed from `agent/runner-tools` (`0316bae`); test data is Q31.4. Item 3 (`--smoke`)
waits for v0.0.8. The runbook's routes: [runbook](../.ai/sessions/2026-10-28-claude-smoke-automation/plan.md#runner-routes-v007).

## Order (proposed)

Items 1, 2 and 4 are small and independent: do them first, one change each. Item 5's shape is
decided with item 1, since both add menu entries. Item 3 follows a design note. Item 6 as needed.

## Done when

A runner on the built `.app` completes M1.1–M1.6 and M1.8 with only `app_*` background tools,
saves every `Shot:` image itself, and leaves no popup or second instance behind.
