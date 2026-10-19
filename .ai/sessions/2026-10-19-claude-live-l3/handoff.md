# Live L3 — handoff: plots following Live

Branch `agent/live-l3` (floor "Live L3"), base `d0b8fbe`. Commits:

| Commit | What |
|---|---|
| `672a96b` | **Let Live start on an empty folder** (item 6, separate as Maestro asked): `io_helper.live_check`, `FolderCache.empty_dataset`, `FolderExplorer`, with helper, helper-process and tab tests |
| `d15792a` | **Plots follow Live (L3)**: items 1–5, 7, 8 |
| `d1eb244` | Settings name the revision on screen; the delay in plain seconds (found in the renders) |
| `959bcf5` | This session folder |
| `2089da4`, `9d9c54e`, `f80091f` | Review fixes (below), with Codex's [review-codex.md](review-codex.md) |
| `7c63bdf`, `fbe13f0`, `7ec0032`, `b5dc449`, `768855f` | Round 2: Tony's answers (below) |
| `d33bb61`, `eab80a3` | Round 2 review fixes (below) |
| `80af689` | The histograms' newest shot on its own right axis (below) |
| `003b230` | Recheck fix: a highlighted histogram is freed with its widget (below) |

How it works, the test-isolation trap and renders: [notes.md](notes.md). Pushed to
`TonyXTYan/HeLab` after the review fixes and after round 2.

## What changed

| File | Change |
|---|---|
| `helab/analysis/follow.py` (new) | `LivePolicy` (every N new shots, delay after a run), `Follow` (one plot's hold-and-coalesce state), `LiveFeed` (newest revision per watched folder: `revised`, `ended`), `live_specs` (the plot's Live settings), `policy_of`, `newer`, `changes`, `shots_text` |
| `helab/analysis/dataset_view.py` | `revise(view, dataset)`: Live's next dataset as the next revision (registered as `view_of(dataset)`); `DatasetView.signature` / `dataset_signature` (each revision's own); `with_shots(…, provenance=, signature=)` |
| `helab/analysis/results.py` | `Coverage` (shots used + fingerprints; `diff`, `to_json`), `CoverageDiff`; `AnalysisContext.coverage`; `AnalysisResult.coverage`, `input_signature`, `reuse_key()`; the record names the coverage |
| `helab/analysis/runner.py` | `submit` records coverage from `script.covered_shots` (all shots if that fails) |
| `helab/analysis/empty.py` (new) | `empty_text`, `empty_pane`: "No shots yet", "None of the N shots is chosen (Shots settings)", "No events in the chosen shots" |
| `helab/scripts/base.py` | `DatasetAnalysis.live_policy` (default every shot), `covered_shots` (the shared Shots selection, else all); docstring: following, no I/O, empty views, JSON parameters |
| `helab/scripts/standard/*` | Empty states in all four plots; the 3D scatter declares a 5 s delay; Transfer fractions reports detected orders only when it detected them (`Fractions.detected`, `minimum`) |
| `helab/models/ScriptTreeSelector.py` | `AnalysisInstance` follows Live (feed → `Follow` → reruns), the Live settings group, keeps the last plot on a failed run (`shown` vs `result`, amber error), the follow state on the source line, the input line and chooser title; `PlotSettingsPanel.set_title` |
| `helab/views/HelabMainWindow.py` | `live_feed`, `follow_live(explorer)` (wired to each tab's `liveChanged` and `dataLoaded`), `update_plot_source(dock)`; source line = rev · follow state · selection · analysis; the amber `plot_error` line under it; a following plot counts as the folder's current data |
| `helab/io_helper.py`, `helab/utils/folder_cache.py`, `helab/views/FolderExplorer.py` | Item 6 only (commit `672a96b`) |
| Tests | New `tests/test_live_plots.py` (50 after round 2); item 6 in `test_live.py`, `test_live_check.py`, `test_live_io.py`; `test_analysis_gui.py`'s fixture closes its plots |

## Review fixes

Codex reviewed `959bcf5` ([review-codex.md](review-codex.md)): changes requested, its checks
matching mine (1115 passed, no reruns, typing clean). Maestro asked for the three findings, one
commit each:

| Commit | Finding | Fix |
|---|---|---|
| `2089da4` | **P1**: Follow Live turned off while a Live rerun ran still drew that newer revision into the pinned plot, and Rerun then used it | `Follow.pin(at)` pins at the data the plot shows (`AnalysisInstance._shown_view`; each job's view is kept while it runs). A run that ends while pinned on other data is dropped, not drawn ("Pinned at rev N: the run on rev M isn't shown"); Rerun stays on the pinned revision; Follow Live on again catches up. Test: `test_pinning_during_a_live_rerun_keeps_the_pinned_revision` (fails without the fix) |
| `9d9c54e` | **P2**: a plot made before Live never caught up when Live's data had the same shot numbers with a changed fingerprint (waiting counted shot numbers only) | `follow.changes()` compares by number and fingerprint (added; changed or gone). Live's revisions of one input still wait for "every N" new or changed shots; another input of the folder (loaded again before Live) with any difference runs once whatever N; identical data runs nothing. Source line: "K new or changed shots" when not all are additions. Tests: `test_follow_counts_changed_fingerprints_and_runs_another_input_once`, `test_a_plot_made_before_live_catches_up_with_changed_data` (both fail without the fix) |
| `f80091f` | **P2**: Counts per shot drew a flat line for chosen shots with no events | Its empty pane shows whenever the chosen shots hold no events ("No events in the chosen shots"). Test: a "no events" case (shots of shape (0, 3)) for all four bundled plots; Counts per shot's fails without the fix |

Not changed, as Maestro decided: with Live off, a delay timer already armed may still finish one
rerun on a revision that came while Live was on (judgement call 2; Maestro tells Tony).

Checks after the fixes: full suite **1122 passed, 2 skipped, 2 xfailed, no RERUN** (`-n 4`);
`mypy helab/ --strict`, `mypy tests --strict`, `mypy helab/ tests --strict --platform win32`:
clean; `pyright helab tests` and `--pythonplatform Windows`: 0 errors; `git diff --check d0b8fbe
HEAD`: clean.

## Round 2: Tony's answers to the open questions

Maestro passed on Tony's answers (2026-10-19). One commit each:

| Commit | Item | What was built |
|---|---|---|
| `7c63bdf` | **1. Live off catches up** | When Live stops for a folder (Live off, another tab, or an error stopping its checks), every plot following it that holds shots back (by "every N" or the delay) runs one final rerun on the last revision, at once, then stays there. `Follow.live_ended()` / `final` (no N, no delay; after a run in flight, which is never cancelled); `live_on()` brings the policy back when revisions come again. Pinned plots don't catch up. `follow_live` ends the feed while an error stops Live's checks and publishes again on Retry. Tests: held by N and by a 60 s delay, Live off during a run, a pinned plot, Follow alone, and a real tab whose checks an error stops. This replaces judgement call 2's "not plotted: Rerun includes them" and Maestro's note on the delay timer |
| `fbe13f0` | (found on the way) | `AnalysisInstance._finished` is a `pyqtSlot`: closing a plot disconnects it from the runner at once. A plain method went through a PyQt proxy deleted later, so `test_closing_the_main_window_ends_its_plots` miscounted the runner's receivers about once in seven runs of three files under `-n 4` (0 in 14 after) |
| `7ec0032` | **3. Live on any folder** | The "no subfolders" rule is gone: any folder this session listed without TXY files (no error, none of its data shown, held or cached) can be watched from no data. Live reads only the folder's own files: `live_check` scans the folder's entries only (a directory just sets `has_dirs`); tested in the tab (a shot written into a subfolder is never read) and in the helper. The real-window test that caught the rule now opens a temp folder with a shot not loaded (auto-load off) |
| `b5dc449` | **2a, 2b. Scatter camera** | The 5 s wait stays. The camera no longer resets: the Dash server keeps a revision per plot (`update_plot`), and each `/plot/<id>` page polls it every second (`dcc.Interval`) and swaps a newer figure in through a Dash callback without reloading the page; figures keep a constant `layout.uirevision` (`scatter_3d.UI_REVISION`), so rotation, zoom and pan stay. `DatasetAnalysis.update(widget, result)` (default no) lets a script update the plot drawn in place; the scatter passes its `PlotlyPane` the new figure. **Open in browser** tabs update in place too (same page). This touches `helab/utils/dash_server.py`, outside the brief's paths (Maestro told). Tests: the page's poll posted as a browser does (stale revision gets the figure with its uirevision, current gets 204), and a following scatter keeping its pane and page across a Live revision |
| `768855f` | **2c. Newest shot** | "Highlight the newest shot" (off) and "Newest shot colour" (red; orange, magenta, green, black) in the **3D scatter** (Points) and, as it was cheap, the **T/X/Y histograms** (Histogram); shared in `selection.newest_specs`. Scatter: the newest shot's events are a second trace in the colour, with a legend, and the display cap keeps all of them before sampling the rest. Histograms: the newest shot's counts in the same bins, drawn over each histogram as a coloured line **scaled to that histogram's total** (unscaled, one shot of 30 lies flat on the axis; scaled, a drift or a changed shape shows); the label says so. Versions: `helab.scatter_3d` v3, `helab.txy_histograms` v3. Renders: [histograms-newest-shot.png](histograms-newest-shot.png), [scatter-newest-shot.png](scatter-newest-shot.png) (the figure in headless Chrome; the dock shows the same page) |

Item 4 (a RAM budget for open plots) is not here: it is a floor of its own after the SMB audit.

### Round 2 review fixes

Codex reviewed `4492385` ("Round 2 review at 4492385" in [review-codex.md](review-codex.md)):
changes requested for two Dash page lifecycle issues; the rest checked out. One commit each:

| Commit | Finding | Fix |
|---|---|---|
| `d33bb61` | **P1**: the figure and the revision were read apart; an update landing between the reads sent the old figure tagged with the new revision, and the page stayed one figure behind for good | One `PlotSnapshot(revision, figure)` per plot, replaced whole under a lock; the page load (`page`) and each poll (`newer_snapshot` / `poll`) read one snapshot. Test: an update landing right after a poll's or a page load's read (a store whose `get` lets it land): each gets the old figure with its own revision, the next poll brings the new one; the old code, under the same interleaving, paired the old figure with revision 2 and never caught up |
| `eab80a3` | **P2**: a browser page still open after its plot closed kept the last graph and polled every second (204) | The poll of a plot no longer there empties and hides the graph, shows "Plot not found. It is removed when its plot is closed in HeLab." and disables the page's interval. Test: the poll as a browser posts it after `remove_plot` |

Not changed (Codex's other points): every open page polls once a second, a 204 when nothing is
new; no multi-page load measurement on a lab PC yet (on Tony's checklist, item 8).

### The newest shot's own axis (Tony, after the review fixes)

`80af689`: the histograms' newest-shot line stays drawn to each histogram's scale, and now reads
its **real counts on a y axis of its own on the right**, in the overlay's colour (axis line,
ticks, label "shot N events"); the left axis keeps all the counts ("Events (all)") in the
plot's colour. Built as pyqtgraph's second-axis pattern: a second ViewBox (`OverlayView`,
which leaves the mouse to the plot: zoom, pan and the menu work as before) linked on x, with
the right `AxisItem` attached; its y range follows the plot's divided by the histogram's total
over the shot's (log Y: shifted by log10 of it, both axes `DecadeLogAxis`), so zooming moves
both. It sits on the plot's exact geometry (its scene bounding rect is half a pixel larger and
shifted the pixel-mapped x link by a pixel) and is re-linked after each resize. Test: linear and
log Y. Renders: [histograms-newest-shot.png](histograms-newest-shot.png),
[histograms-newest-shot-log.png](histograms-newest-shot-log.png). This answers the open
question on the histograms' scaling. Full suite 1139 passed, 2 skipped, 2 xfailed, no RERUN;
typing clean (also Windows).

`003b230` (Codex's "Recheck at 69c2ced", P2): the overlay's follow callback was a closure on the
plot's signals, which PyQt held strongly, so every highlighted drawing's plot, overlay, curve
and counts outlived its widget (Live redraws on each revision). `follow` is now a `pyqtSlot` on
`OverlayView` (a Qt connection Qt ends with either side); its attributes are private, since a
`scale` attribute would have shadowed `QGraphicsItem.scale()`. Tests: weak references freed
after one deferred-delete pass and gc, linear and log Y, and after a Live redraw (all three fail
without the fix). Full suite 1142 passed, 2 skipped, 2 xfailed, no RERUN; typing clean (also
Windows).

Checks after these fixes: full suite **1137 passed, 2 skipped, 2 xfailed, no RERUN** (`-n 4`);
`mypy helab/ --strict`, `mypy tests --strict`, `mypy helab/ tests --strict --platform win32`:
clean; `pyright helab tests`, also `--pythonplatform Windows`: 0 errors; `git diff --check d0b8fbe
HEAD`: clean.

Checks after round 2: full suite **1135 passed, 2 skipped, 2 xfailed, no RERUN** (`-n 4`);
`mypy helab/ tests --strict`, also `--platform win32`: clean; `pyright helab tests`, also
`--pythonplatform Windows`: 0 errors; `git diff --check d0b8fbe HEAD`: clean.

## The decisions as built

1. **Follow Live** is on by default for every plot and acts while Live watches the plot's folder
   (same source path). Plots of other folders stay put. Off pins the plot at the revision it
   shows: what waits is dropped, no revision is taken, and a run already on newer data is
   dropped when it ends; on again, it catches up (as its policy allows).
2. **Cadence**: every new shot by default; `DatasetAnalysis.live_policy` declares N and/or a
   delay; the plot's settings show a **Live** group (Follow Live, Rerun every N new shots, Wait
   after a run) with the script's values as defaults (pyqtgraph's reset-to-default arrow).
3. **Hold and coalesce**: Live never cancels a run; revisions wait in one slot per plot (newest
   wins); when the run ends, one rerun takes the newest. A failed rerun keeps the last plot, says
   `⚠ rev N failed: <error> · showing rev M` in amber under the source line, and following goes
   on; the next good run clears it.
4. **Coverage**: every result (completed, failed, cancelled) records the shots it used with
   their fingerprints, plus its input revision's own signature; `Coverage.diff(view)` gives new,
   changed and gone shots. Full reruns only (R3's missing-shot updates later).
5. **No I/O in scripts**: plots get `DatasetView`s only; Live and the feed are HeLab's.
6. **Empty folder** (commit `672a96b`): see below.
7. **Ready for later**: `AnalysisResult.reuse_key()` gathers analysis ID, version, file hash,
   action, root key, signatures, effective parameters and coverage as JSON values (tested for
   all four plots). No storage added. The Live settings are not parameters.
8. **Source line**: `Data source: run_042 · rev 5 · following Live · updating to rev 6 · 3 new
   shots waiting · 44 shots · helab.counts_per_shot v2`; pinned: `… · rev 5 · pinned (Follow Live
   off) · 12 newer shots · …`. Transfer fractions' auto orders are found again on every rerun;
   manual keeps them (tested).

## Judgement calls (for review)

1. **Empty start** (round 2: any folder): this session's listing found no TXY files, no error,
   and none of its data is shown, held or cached; subfolders or not (Live reads only the
   folder's own files). A folder with shots not yet loaded is loaded first (Live checks apply no
   large-folder limits). Its line says "waiting for the first shot".
2. **Live off catches up** (round 2, Tony's answer): what waits runs once at once, then the plot
   stays; **Rerun** runs on the newest data the plot received (a pinned plot: its own revision).
3. **Rerun with these settings** still cancels a run in flight (the settings changed); only
   Live's new data never cancels.
4. A failed **render** counts as a failed run (the last plot stays). A first run that fails
   shows the message in the dock, as before.
5. The **3D scatter** declares a 5 s delay (kept, round 2): a large folder's crop takes seconds.
   Its page is now updated in place, keeping the camera. The other plots rerun on every shot.
6. A plot made from data loaded **before** Live started on its folder follows too, and catches up
   if the shown data is newer.
7. The settings' input line and the plot chooser name the revision **on screen** (the last
   completed result's); "updating to rev N" on the source line names what runs.
8. Revision rule: a newer dataset missing some of the view's shots is no revision (a fresh view,
   revision 1); changed fingerprints count as replaced shots (a revision). Live never removes
   shots.

## Open questions for Tony

Questions 1–3 of the first round are answered and built (round 2 above). Still open:

1. Unchanged from L1: Live's RAM keeps growing during long runs (open question 2 there); open
   plots now also pin the views they show, newest revision included (the plot RAM budget floor).
2. (Answered: the histograms' newest shot reads on its own right axis, `80af689`.)

## Notes for the SMB I/O audit merge

Commit `672a96b` is self-contained. In `io_helper.live_check` it changes only the guard
(`if memory is None`) and one docstring sentence. `FolderCache` gains one method. The tests that
must keep passing after the merge: `test_live_check.py::test_live_can_start_before_the_first_shot`
and `::test_a_check_without_held_shots_given_is_refused`,
`test_live_io.py::test_live_on_an_empty_folder_through_the_helper_processes`, and
`test_live.py::test_live_starts_on_a_folder_with_no_shots_yet`,
`::test_a_folder_with_shots_not_yet_loaded_cant_be_watched`,
`::test_a_folder_with_subfolders_is_watched_alone`, and
`test_live_check.py::test_live_reads_only_the_folders_own_files_never_its_subfolders`; plus
`test_live_plots.py::test_a_plot_follows_live_from_an_empty_folder_to_its_first_shots`, which
drives a real tab's Live checks (in-process helpers) into a following plot.

## Checks

- Full suite `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: **1115 passed,
  2 skipped, 2 xfailed, no RERUN** (at `d15792a` and at `d1eb244`).
- `mypy helab/ --strict`, `mypy tests --strict`, `mypy tests --strict --platform win32`: clean.
- `pyright helab tests`, `pyright tests --pythonplatform Windows`: 0 errors.
- `git diff --check d0b8fbe HEAD`: clean.
- One RERUN appeared during development (`test_analysis_gui.py::test_closing_the_main_window_ends_its_plots`):
  traced and fixed, see [notes.md](notes.md#a-test-isolation-trap-not-a-product-bug). None since.
- The Live I/O tests use the read gate and none is skipped by platform; Windows not run here
  (Maestro runs the suite on RSPE).

## Tony's on-screen checklist

On the Mac, then a lab PC (Windows). Replaces nothing in MANUAL_TODO; add under Live.

1. **Following during a run**: on `/Volumes/dld_output`, select the current run folder, open Counts
   per shot, T/X/Y histograms, Transfer fractions and the 3D scatter, then turn Live on. Each new
   shot appears in the plots within a few seconds (the scatter at most every 5 s). Source lines
   read `rev N · following Live`; while a heavy plot runs, `updating to rev N · K new shots
   waiting`. The GUI stays responsive (one analysis thread, reruns coalesce).
2. **Policy**: in Counts per shot's settings, Live group, set Rerun every N new shots = 5: it
   reruns every fifth shot, the line says `K new shots waiting (runs every 5)` meanwhile. Set
   Wait after a run = 10 s: each rerun starts no sooner than 10 s after the last one ended.
3. **Pin**: untick Follow Live: the line says `pinned (Follow Live off) · K newer shots`, the plot
   stays; Rerun with other settings stays on that revision. Tick it again: it catches up.
4. **Empty folder**: before a run starts, select the new (empty) run folder and turn Live on: the
   line says `waiting for the first shot`; open Counts per shot: "No shots yet". Start the run:
   the plot appears with the first shot and follows.
5. **Transfer fractions**: in auto, the orders (title) are found again as shots come; switch to
   manual: centre and spacing stay as set.
6. **Live off catches up**: set Counts per shot to rerun every 5 shots, let 2 shots come, then
   switch tabs (or Live off): it reruns once at once with those 2 shots, then stays; its line
   drops `following Live`. Same with Wait after a run = 60 s.
7. **Failed rerun**: not easy to provoke by hand; covered by tests (the last plot stays, amber
   line).
8. **3D scatter camera**: rotate and zoom the scatter during Live; new shots arrive and the view
   stays where you left it, in the dock and in **Open in browser** (both update within a second
   of a rerun). The modebar's Reset camera still resets it. Close the plot with its browser tab
   open: the tab says the plot was closed. On a lab PC, with several plot pages open, check the
   once-a-second polls cost nothing noticeable.
9. **Newest shot**: tick Highlight the newest shot in the scatter (Points) and the histograms
   (Histogram): the newest shot is red (other colours in the list); during Live it moves to each
   new shot. In the histograms its line is drawn to the histogram's scale and reads on its own
   red axis on the right (real counts); with Log Y both axes show decades; zooming and panning
   the plot move both.
10. **Any folder**: Live can start on a folder with subfolders and no TXY files of its own (e.g.
    the day's folder): it adds only TXY files written into that folder, never into its
    subfolders.

## For the coordinator: proposed doc changes

### AGENTS.md

- Live paragraph, after "Live never survives a restart.": "Live may start on any folder this
  session listed with no TXY files (it reads only the folder's own files, never its
  subfolders'): the tab shows data with no shots
  (`FolderCache.empty_dataset`, pinned), the first check lists the folder (`memory=[]`) and the
  line says "waiting for the first shot". Plots follow Live (L3): the main window publishes each
  dataset a Live tab shows to `HelabMainWindow.live_feed` (`LiveFeed`), `revise` makes it the next
  revision of the folder's view, and each plot of that folder reruns on the newest revision as
  its Live settings allow (`helab/analysis/follow.py`: `Follow`, `LivePolicy`); when Live stops
  (Live off, another tab, an error), plots holding shots back catch up once, at once."
- Script system paragraph, after "Results stay in RAM (`RamResults`, R1).": "A plot follows Live
  by default (its settings' Live group: Follow Live, Rerun every N new shots, Wait after a run,
  from the script's `live_policy`; not parameters): a run is never cancelled for new data, one
  pending revision per plot (newest wins), a failed rerun keeps the last plot with an amber line.
  Every result records its coverage (shots used and fingerprints, `covered_shots`) and
  `reuse_key()` (JSON). Plots with nothing to draw say why (`helab/analysis/empty.py`)."
- Script system, the dock's source line example: add `following Live · 3 new shots waiting`
  after the revision.
- Visualization: "The 3D scatter's page updates in place (`DashServer.update_plot`, a 1 s poll per
  page, constant `layout.uirevision`), keeping the camera across reruns, in the dock and in
  browser tabs; `DatasetAnalysis.update` lets a plot update in place. The scatter and the
  histograms can highlight the newest shot (`selection.newest_specs`)."

### roadmaps/live-monitoring.md

- Stages: L3 done (2026-10-19, branch `agent/live-l3`), pending the on-screen check.
- "Plots following Live: L3": add "Built 2026-10-19" with judgement calls 1–8 above in short.
- Open decisions: remove "Watch a folder before its first shot" (built: any folder, its own
  files only); record round 2's answers (Live off catches up; the scatter's 5 s wait and camera
  kept; the newest-shot highlight); add the histogram-scaling question above.

### roadmaps/result-caching.md

- R3: "Coverage recorded on every result (shots and fingerprints, `Coverage.diff`), and the reuse
  key assembled (`AnalysisResult.reuse_key`), 2026-10-19; missing-shot updates still to come."

### roadmaps/_readme.md

- Live monitoring: "L1–L3 done (2026-10-19); L4 (converter in HeLab) next".

### .ai/memory

- `results/live-monitoring.md`, add L3 wording: source line `rev N · following Live · K new shots
  waiting`, `updating to rev N`, `pinned (Follow Live off) · K newer shots`, `Live off · K new
  shots not plotted: Rerun includes them`; amber `⚠ rev N failed: <error> · showing rev M`;
  Live group labels (Follow Live, Rerun every N new shots, Wait after a run); `waiting for the
  first shot`; empty states "No shots yet", "None of the N shots is chosen (Shots settings)".
  Decisions 1–2 of the judgement calls with their reasons.
- `MEMORY.md` index line for Live: append "L3: plots follow Live (hold and coalesce, policy,
  pin), Live from an empty run folder".

### .ai/MANUAL_TODO.md

- Under Live: the on-screen checklist above.

### Floor setup (roadmaps/agent-workflow.md, floor setup step)

- Delete copied `__pycache__` folders after cloning a floor: they carry Ground's paths into
  tracebacks ([notes.md](notes.md#floor-setup-note)).
