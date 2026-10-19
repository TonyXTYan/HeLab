# Notes: dataset view + first plots

Worker: Claude (Opus 5.5) on the Maestri floor "Dataset view plots", branch
`agent/dataset-view-plots`, base `376c7dd`. Brief: [brief.md](brief.md).
Handoff: [handoff.md](handoff.md).

## What I found

- `plotly_3d_sactter.Plotly3DScatter` wasn't reachable from the UI. The Scripts
  panel imported it but never used it. The main window called
  `add_example_groups_and_items()` straight after building the panel, which
  replaced the loaded script groups with the two placeholder groups. So no real
  script was ever on screen, and dynamic buttons called `execute_action(name)`
  without any data.
- `HelabMainWindow._set_plot_source` was only called from a test.
- `Dataset.metadata` is the helper's `loaded` event, which `FolderCache` changes
  in place (`checked_at = -inf` on removal, `verified = True`). `checked_at` is
  `time.monotonic()`. So the view copies the metadata and converts that time to
  wall-clock time.
- TXY columns are t, x, y in s, m, m (`io_helper.read_txy`; the legacy Plotly
  figures multiply x and y by 1e3 for mm).
- Bundled scripts were loaded by scanning a folder. A PyInstaller build has no
  `.py` files there, so the bundled analyses are now imported normally
  (`helab/scripts/standard/__init__.py`).

## Auto-crop rule: how it was chosen

1. **Per-axis central intervals** (equal counts trimmed from each end, the
   brief's example): with 2 % late T events, a 98 % box still reached the late
   events, because only 1 % could come off each end. Rejected.
2. **Per-axis shortest intervals with a common window m**: this fails when the
   late T events sit inside the XY core. X then cuts core events, m has to
   grow, and T takes the tail back. Rejected (the test
   `test_crop_leaves_out_one_sided_tails` shows the case).
3. **Peeling** (kept): start from the full box and repeatedly leave out the
   events at one end of one axis. Each step picks the end whose removal narrows
   its axis the most, relative to that axis's current width, per event left
   out. Ties go to the end that has left out fewer events, so symmetric data is
   cut symmetrically. Stop before the box would hold fewer than ceil(keep · n)
   events. The box then holds exactly the remaining events.
   Measured with 2 % one-sided tails: 1 M events in 0.29 s, 5 M in 1.9 s,
   counts exact. It runs in the analysis worker thread.

On the 60-shot synthetic run in the screenshots, the 99 % budget is shared
across axes, so T still reaches about 4.16 s. It does that because half the 2 %
tail has to stay to keep 99 %.

## Validation

- `pytest -n 6 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: see
  [handoff.md](handoff.md#checks) for the final run.
- New tests: `tests/test_analysis.py` (known arrays, runner, RAM results) and
  `tests/test_analysis_gui.py` (a real `FolderExplorer` fed with helper events:
  a selection change mid-run, rerun on the same input, closing a dock, the 3D
  scatter end to end through the Dash server).
- Screenshots (offscreen, `QT_SCALE_FACTOR=2`, synthetic data: 60 shots,
  293,584 events, 2 % late T tail) in `screenshots/`. The 3D scatter's
  QtWebEngine pane can't paint offscreen (`scatter_3d_dock.png` shows the
  note row and Open in browser). `scatter_3d_browser.png` is the same Dash page
  from headless Chrome with software WebGL (`--use-angle=swiftshader
  --enable-unsafe-swiftshader`); without it Chrome shows "WebGL is not
  supported". The script is not in the repo; it builds docks with
  `HelabMainWindow.set_plot_result` and grabs them.
