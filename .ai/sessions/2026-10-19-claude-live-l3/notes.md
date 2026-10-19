# Live L3 — notes

Floor "Live L3", branch `agent/live-l3`, base `d0b8fbe`. Brief: [brief.md](brief.md). Handoff:
[handoff.md](handoff.md).

## How following works

```
FolderExplorer (Live tab)            HelabMainWindow                 AnalysisInstance (each plot)
  _display → dataLoaded ─────────▶  follow_live(explorer)
  start/stop → liveChanged ──────▶    LiveFeed.publish(dataset) ──▶ _revised(view)  (same folder only)
                                       └ revise(view, dataset)          Follow.offer → one pending slot
                                      LiveFeed.stop(path) ─────────▶ _live_ended     Follow.due(now)
                                                                          → submit on the newest, or
                                                                            wait (N shots / delay timer)
                                                                        _finished → Follow.end → due…
```

- `revise(view, dataset)` (`helab/analysis/dataset_view.py`): a newer dataset of the folder with
  all of the view's shots becomes `view.with_shots(added)` (revision + 1, the dataset's own
  signature and provenance), and `view_of(dataset)` returns it from then on, so a plot opened
  during Live starts from the revision the following plots have. A dataset missing shots is a
  fresh view (revision 1); Live never removes shots (`shots_missing` stops it).
- `Follow` (`helab/analysis/follow.py`) is pure Python and holds the rules: `ran` (input of the
  run in flight or the last), `pending` (one slot), `running`, `finished_at`; `due(now)` returns
  the view to run, or the seconds a delay still holds it.
- The plot's Live settings (`live_specs`: Follow Live, Rerun every N new shots, Wait after a run)
  sit in the plot's parameter tree as a "Live" group but are read apart from the analysis's
  parameters (`AnalysisInstance.values()` reads only the script's specs), so they never reach
  `compute`, a result's parameters or its reuse key.
- Coverage: `AnalysisRunner.submit` asks `script.covered_shots(action, parameters, view)` (the
  shared Shots selection by default) and puts `Coverage.of(view, shots)` in the context; every
  `AnalysisResult.of` copies it, whatever the state.

## Item 6 (Live on an empty folder)

Separate commit `672a96b` ("Let Live start on an empty folder"), as Maestro asked, so it rebases
cleanly against the SMB I/O audit floor (which rewrites parts of `live_check` and the Live save
path). Touches: `io_helper.live_check` (`memory is None` refused, `[]` accepted: 2 lines),
`FolderCache.empty_dataset`, `FolderExplorer._no_shots_yet` / `live_unavailable` /
`start_live` / `live_line`, the plot-area hint and the Live action's first tooltip. Tests at
three levels: helper in-process (`tests/test_live_check.py`), helper processes with the read gate
(`tests/test_live_io.py`, every OS), tab (`tests/test_live.py`).

The first version let Live start on any listed folder without TXY files. The existing
`test_the_live_action_follows_the_current_tab_and_locks_navigation` (real main window) showed
why that's wrong: the default folder (a home folder or a drive's top) would offer Live as soon
as its listing landed. The rule is now a run folder: no TXY files **and no subfolders**
(`node.loaded and not node.children`), amended into the same commit with a test.

## A test-isolation trap (not a product bug)

`tests/test_analysis_gui.py::test_closing_the_main_window_ends_its_plots` compares the app-wide
runner's `receivers(finished)` before and after. With L3 it failed in the full file (never
alone): the preceding test leaves four plots open (its stub window never closed them), and they
were freed by a garbage collection that ran inside the next test. A freed plot's connection to
`runner.finished` (a plain bound method) goes through a PyQt slot proxy that is deleted later,
so the receiver count fell mid-test. At the base the same plots happened to stay alive until
their docks were deleted (and closed properly); L3's extra objects moved the collection earlier.
Fix: the `window` fixture closes its plots at teardown (`made.close_plots()`), as the real main
window's close does. Also made `_live_settings_changed` a `pyqtSlot` so a pyqtgraph parameter
never holds a plot strongly. In the app, plots are held by the Scripts panel until closed and the
window closes them all, so nothing similar happens there.

## Floor setup note

The floor's `tests/__pycache__` (copy-on-write from Ground) held Ground's paths, so pytest's
tracebacks named `../../../HeLab/tests/...` until the caches were deleted; the code that ran
was the floor's (helab resolves to the floor through the editable finder). Worth adding to the
floor setup script: delete `__pycache__` folders after cloning.

## Renders

`render_live_plots.py` (offscreen, run from the floor's root with the floor's environment):

- `following-waiting.png`: rev 1 shown, a run on rev 2 in flight, 3 new shots waiting.
- `following-current.png`: caught up (rev 5).
- `rerun-failed.png`: the amber line under the source line; the rev 5 plot stays.
- `settings-live-group.png`: the plot's settings with the Live group (script defaults).
- `empty-no-shots-yet.png`: Live on an empty folder, Counts per shot before the first shot.

The renders found two slips, fixed in `d1eb244`: the settings' input line and the plot chooser
named the failed run's revision instead of the one shown, and the delay showed "0 ms".
