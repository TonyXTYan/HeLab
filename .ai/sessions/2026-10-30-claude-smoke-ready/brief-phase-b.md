# Brief addendum: phase B (Tony's GO, 2026-10-30)

Coordinator: CoCo. Tony approved more of the computer-use extras
(`.ai/sessions/2026-10-28-claude-smoke-mac/computer-use-notes.md`). This floor takes items 1, 3, 4, 5
and 9; a second floor (Runner Tools, Kestrel, `agent/runner-tools`) takes item 2 (milestone log lines,
incl. one line in `explorer_live.py`'s `convert_summary` handling) and item 7 (a dev `.app` stub). Item 6
(test data) is Tony's and Side's, local and outside the repo: no fetch script or CI wiring. Item 8 is
dropped. Same rules as `brief.md`.

1. **Stable `objectName` IDs (item 1), in the same pass as the names** (don't make a second pass):
   every interactive control you name also gets an `objectName` a runner can rely on (macOS AX
   identifier, Windows UIA AutomationId): unique within its window, stable across runs and
   translations; per-script and per-tab ones built from the script ID / tab ID, not the title. The
   test checks every walked control has one and that they're unique per window. Check (and say)
   whether Qt exposes it as AXIdentifier / AutomationId on each OS; propose an `M~` for the Windows
   check.
2. **Debug › Dump state… (item 3)**: memory only, never I/O beyond writing its file: the summary lines,
   Folder details, the status bar, open folder and plot tabs, each plot's source line and tooltip text,
   plot count, Live state; JSON beside the screenshots (`screenshots/` in the temp folder, or a picked
   path). It is the read half of the future `--smoke` channel (v0.0.8): name its fields so that
   channel can return the same shape, and say so in the handoff.
3. **`--geometry WxH+X+Y` (item 5)**: opens the main window at that size and position, for this run
   only (saved geometry untouched); off by default. Arguments in `helab/main.py` (approved).
4. **The two bugs (item 9)**, both in known-issues: in the plot settings panel, Return commits a typed
   value (as Tab does); a plot tab's × responds to clicks (computer-use clicks included: check first
   whether its accessible name from phase A already fixes it, as the entry suspects). Tests for both.
5. **Quit that confirms (item 4)**, last, **after CoCo says TXY Index has landed** and you've merged
   `dev/v0.0.7`: TXY Index changes the quit path (a best-effort `last_used` flush at quit, with the
   windows hidden and a short grace; its length is still with Tony). File › Quit exits within 1 s, or
   shows why not (the quit window's reasons); the process never lingers unseen beyond that, and a quit
   clicked before the menu opened can't leave the process running (known-issues: "File › Quit
   sometimes left the process running"). Tony settled the flush (2026-10-30): the `last_used` write
   joins the quit window like the other saves (~5 s no-progress limit; Quit now skips it).
6. **The quit window lists every pending operation (Tony, 2026-10-30), with item 5**: `QuitSaveDialog`
   (today a list of folder names) lists each pending operation by kind and state (Live shots, a
   load's background save, folder flags, constants, a result save or Make room, presets, held writes,
   `last_used` marks, a conversion still finishing), each with its folder and how long it has run,
   updating from memory and closing by itself when all have ended; Quit now as today. Approved outside
   `helab/views/`: the shape of `FolderCache.quit_saves()` (or a sibling returning typed entries) and
   the smallest hooks to know each kind's start time; nothing else in `folder_cache.py`. Tests per kind
   and for closing by itself. Docs proposals: `live.md`'s quit paragraph and the dialog's docstring.

Order: finish phase A (names + IDs + test, the Debug run/group/tab/settings items, the screenshot) and
commit; then 2, 3, 4 above; 5 last. Wren reviews at the end of phase A (tell CoCo) and again at the end.
