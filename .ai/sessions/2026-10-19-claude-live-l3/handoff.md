# Live L3 — handoff: plots following Live

Branch `agent/live-l3` (floor "Live L3"), base `d0b8fbe`. Three commits:

| Commit | What |
|---|---|
| `672a96b` | **Let Live start on an empty folder** (item 6, separate as Maestro asked): `io_helper.live_check`, `FolderCache.empty_dataset`, `FolderExplorer`, with helper, helper-process and tab tests |
| `d15792a` | **Plots follow Live (L3)**: items 1–5, 7, 8 |
| `d1eb244` | Settings name the revision on screen; the delay in plain seconds (found in the renders) |

How it works, the test-isolation trap and renders: [notes.md](notes.md). Not pushed (push when
Maestro says).

## What changed

| File | Change |
|---|---|
| `helab/analysis/follow.py` (new) | `LivePolicy` (every N new shots, delay after a run), `Follow` (one plot's hold-and-coalesce state), `LiveFeed` (newest revision per watched folder: `revised`, `ended`), `live_specs` (the plot's Live settings), `policy_of`, `newer`, `new_shots` |
| `helab/analysis/dataset_view.py` | `revise(view, dataset)`: Live's next dataset as the next revision (registered as `view_of(dataset)`); `DatasetView.signature` / `dataset_signature` (each revision's own); `with_shots(…, provenance=, signature=)` |
| `helab/analysis/results.py` | `Coverage` (shots used + fingerprints; `diff`, `to_json`), `CoverageDiff`; `AnalysisContext.coverage`; `AnalysisResult.coverage`, `input_signature`, `reuse_key()`; the record names the coverage |
| `helab/analysis/runner.py` | `submit` records coverage from `script.covered_shots` (all shots if that fails) |
| `helab/analysis/empty.py` (new) | `empty_text`, `empty_pane`: "No shots yet", "None of the N shots is chosen (Shots settings)", "No events in the chosen shots" |
| `helab/scripts/base.py` | `DatasetAnalysis.live_policy` (default every shot), `covered_shots` (the shared Shots selection, else all); docstring: following, no I/O, empty views, JSON parameters |
| `helab/scripts/standard/*` | Empty states in all four plots; the 3D scatter declares a 5 s delay; Transfer fractions reports detected orders only when it detected them (`Fractions.detected`, `minimum`) |
| `helab/models/ScriptTreeSelector.py` | `AnalysisInstance` follows Live (feed → `Follow` → reruns), the Live settings group, keeps the last plot on a failed run (`shown` vs `result`, amber error), the follow state on the source line, the input line and chooser title; `PlotSettingsPanel.set_title` |
| `helab/views/HelabMainWindow.py` | `live_feed`, `follow_live(explorer)` (wired to each tab's `liveChanged` and `dataLoaded`), `update_plot_source(dock)`; source line = rev · follow state · selection · analysis; the amber `plot_error` line under it; a following plot counts as the folder's current data |
| `helab/io_helper.py`, `helab/utils/folder_cache.py`, `helab/views/FolderExplorer.py` | Item 6 only (commit `672a96b`) |
| Tests | New `tests/test_live_plots.py` (33); item 6 in `test_live.py`, `test_live_check.py`, `test_live_io.py`; `test_analysis_gui.py`'s fixture closes its plots |

## The decisions as built

1. **Follow Live** is on by default for every plot and acts while Live watches the plot's folder
   (same source path). Plots of other folders stay put. Off pins the plot: what waits is dropped,
   no revision is taken; on again, it catches up (as its policy allows).
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

1. **Empty start = a run folder**: this session's listing found no TXY files **and no
   subfolders**, no error, and none of its data is shown, held or cached. A folder with shots
   not yet loaded is loaded first (Live checks apply no large-folder limits); a folder of runs or
   a drive's top is never watched from no data. Its line says "waiting for the first shot".
2. **Live off doesn't drop what came during Live**: revisions already offered still run as the
   policy allows (a run in flight at Live off isn't left one revision short). Those held back by
   N say `Live off · K new shots not plotted: Rerun includes them`; **Rerun** runs on the newest
   data the plot received (a pinned plot: its own revision).
3. **Rerun with these settings** still cancels a run in flight (the settings changed); only
   Live's new data never cancels.
4. A failed **render** counts as a failed run (the last plot stays). A first run that fails
   shows the message in the dock, as before.
5. The **3D scatter** declares a 5 s delay: each rerun reloads its Plotly page (and resets the
   camera) and a large folder's crop takes seconds. The other plots rerun on every shot.
6. A plot made from data loaded **before** Live started on its folder follows too, and catches up
   if the shown data is newer.
7. The settings' input line and the plot chooser name the revision **on screen** (the last
   completed result's); "updating to rev N" on the source line names what runs.
8. Revision rule: a newer dataset missing some of the view's shots is no revision (a fresh view,
   revision 1); changed fingerprints count as replaced shots (a revision). Live never removes
   shots.

## Open questions for Tony

1. Live off with shots held back by "every N": run one last catch-up rerun automatically
   (now: the line says so and Rerun includes them)?
2. The 3D scatter's 5 s default, and its camera resetting on every rerun (keeping the camera
   needs client-side state in the Dash page: later work)?
3. Only folders without subfolders can be watched before their first shot: right for the lab's
   run folders?
4. Unchanged from L1: Live's RAM keeps growing during long runs (open question 2 there); open
   plots now also pin the views they show, newest revision included.

## Notes for the SMB I/O audit merge

Commit `672a96b` is self-contained. In `io_helper.live_check` it changes only the guard
(`if memory is None`) and one docstring sentence. `FolderCache` gains one method. The tests that
must keep passing after the merge: `test_live_check.py::test_live_can_start_before_the_first_shot`
and `::test_a_check_without_held_shots_given_is_refused`,
`test_live_io.py::test_live_on_an_empty_folder_through_the_helper_processes`, and
`test_live.py::test_live_starts_on_a_folder_with_no_shots_yet`,
`::test_a_folder_with_shots_not_yet_loaded_cant_be_watched`,
`::test_a_folder_of_runs_isnt_watched_as_an_empty_run`; plus
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
6. **Live off**: switch tabs (or Live off): plots keep their last revision and their lines drop
   `following Live`.
7. **Failed rerun**: not easy to provoke by hand; covered by tests (the last plot stays, amber
   line).

## For the coordinator: proposed doc changes

### AGENTS.md

- Live paragraph, after "Live never survives a restart.": "Live may start on a run folder this
  session listed with no TXY files and no subfolders: the tab shows data with no shots
  (`FolderCache.empty_dataset`, pinned), the first check lists the folder (`memory=[]`) and the
  line says "waiting for the first shot". Plots follow Live (L3): the main window publishes each
  dataset a Live tab shows to `HelabMainWindow.live_feed` (`LiveFeed`), `revise` makes it the next
  revision of the folder's view, and each plot of that folder reruns on the newest revision as
  its Live settings allow (`helab/analysis/follow.py`: `Follow`, `LivePolicy`)."
- Script system paragraph, after "Results stay in RAM (`RamResults`, R1).": "A plot follows Live
  by default (its settings' Live group: Follow Live, Rerun every N new shots, Wait after a run,
  from the script's `live_policy`; not parameters): a run is never cancelled for new data, one
  pending revision per plot (newest wins), a failed rerun keeps the last plot with an amber line.
  Every result records its coverage (shots used and fingerprints, `covered_shots`) and
  `reuse_key()` (JSON). Plots with nothing to draw say why (`helab/analysis/empty.py`)."
- Script system, the dock's source line example: add `following Live · 3 new shots waiting`
  after the revision.

### roadmaps/live-monitoring.md

- Stages: L3 done (2026-10-19, branch `agent/live-l3`), pending the on-screen check.
- "Plots following Live: L3": add "Built 2026-10-19" with judgement calls 1–8 above in short.
- Open decisions: remove "Watch a folder before its first shot" (built: run folders without
  subfolders); add open questions 1–3 above.

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
