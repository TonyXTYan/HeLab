# Handoff: Plot RAM budget

Branch `agent/plot-ram-budget` (base 531ec41). Design and reasoning: [notes.md](notes.md).
Review: [review.md](review.md) (changes requested on ebf674d); the fixes are listed under
"After review" below.

## Summary

Plots now count toward the RAM budget (Settings → Cache) beside loaded folders: each
plot's view and result arrays, by the memory they use, so arrays shared with a held
dataset or another plot count once. From 50 % the status bar shows "RAM N% of
budget" (amber from 75 %, click for details); at 75 % a non-modal window lists the
biggest plots and folders, once per crossing; above 80 % the datasets no tab shows go
first, then plots are released least recently viewed first, until under 80 %. The
shown, running and Live-following plots are never released and no plot is closed.
A released plot shows a picture of itself (the 3D scatter's last frame included) with
Reload, frees its view, result and Dash figure, and reloads from RAM or the local disk
cache only, by its shots' fingerprints, naming changed or missing shots; with neither
it says so and keeps its picture. It reloads when shown again (new Settings → Cache
checkbox, on by default) or on Reload; Rerun on it reloads with the settings shown.

## Files

- New `helab/analysis/budget.py`: buffer accounting, thresholds, `RamBudget`,
  `hollow`/`restore`, the `plot_auto_reload` setting.
- `helab/utils/folder_cache.py`: RAM accounting only (`ram_users`, `plot_bytes`,
  `held_buffers`, `held_sizes`, `evict_to`; `_evict` counts plots and keeps a dataset
  whose arrays plots hold anyway).
- `helab/models/ScriptTreeSelector.py`: `ReleasedPlot`, `snapshot`,
  `AnalysisInstance` release/reload, `PlotSettingsPanel.plotShown` and `recent()`.
- `helab/utils/ram_buffers.py` (new: buffer counting), `helab/utils/constants.py` (the
  setting), `helab/analysis/dataset_view.py` (`fingerprints_of` made public).
- `helab/analysis/results.py` (`RamResults.released`, `peek`, `discard`), `runner.py` (the worker no
  longer keeps the last job's input alive while idle).
- `helab/views/HelabMainWindow.py` (`setup_ram_budget`, status-bar button, the 75 %
  window, `replace_plot_content`), `helab/views/CacheTab.py` (checkbox, plots' bytes
  in the memory line).
- Outside the listed paths: one line in `helab/views/SettingsDialog.py` so Reset all
  settings resets the checkbox.
- `tests/test_plot_ram_budget.py` (16 tests).

## Checks

- After review (at 498e1df): full suite `pytest -n 4 --reruns 5 --reruns-delay 1
  --basetemp=.ai/temp/pytest -rR`: 1281 passed, 2 skipped, 2 xfailed, no RERUN (67.7 s);
  `mypy --strict` helab and tests, also `--platform win32`: clean; `pyright helab tests`
  and `--pythonplatform Windows`: 0 errors; `git diff --check 531ec41`: clean.
  tests/test_plot_ram_budget.py: 25 tests.
- First round (ebf674d): 1272 passed, 2 skipped, 2 xfailed, no RERUN (61.8 s).
- `mypy --strict helab/` and `mypy --strict tests`: clean. `pyright helab tests` and
  `pyright --pythonplatform Windows helab tests`: 0 errors. `git diff --check`: clean.
- Tests cover: shared arrays counted once (and a dataset whose arrays plots hold
  isn't evicted); thresholds (hidden < 50 %, button at 55 %, window at 76 % once per
  crossing, again after dropping under 75 %); release order (datasets first, least
  recently viewed first, stop under 80 %) and exemptions (shown, running, Live; none
  closed); the static picture and freed arrays (weakref gone after release); the
  scatter's snapshot and its Dash figure freed; auto reload on and off and the manual
  Reload; changed and missing shots named; reload asking only a `cached` read (never
  a load or listing); no data anywhere; Rerun on a released plot; the setting saved.

## On-screen checklist for Tony

Set Settings → Cache → RAM budget low (e.g. the minimum) to reach the thresholds.

1. Load a large folder and open several plots (histograms, 3D scatter, transfer
   fractions) on it and on other folders. From 50 % the status bar shows "RAM N% of
   budget" right of the other buttons; its tooltip splits folders and plots.
2. At 75 % a window "RAM nearly at its budget" lists the biggest plots and folders;
   it doesn't block the main window, comes once, and again only after RAM drops
   under 75 % and rises again. Settings… opens Settings.
3. Push past 80 % (more plots, or lower the budget): the status line says "Released N
   plots…"; the plots behind other tabs show "Released to free RAM: a picture, not
   interactive" with Reload over a picture that looks like the plot (right size, not
   a thumbnail). The shown plot, a plot still running and a plot following Live stay.
4. **3D scatter**: released, its picture is its last frame as rotated. Check on macOS
   and on a lab PC (on the lab PCs whose GPU can't paint QtWebEngine it will be black,
   like the pane). **A scatter never on screen** (opened behind another tab and never
   brought to the front) has a web view that never painted: its picture is expected to
   be blank; check what it looks like. Open in browser no longer exists once released.
5. Click a released plot's tab: it reloads (once per show: clicks in it don't ask again) (from RAM if the folder is still loaded,
   else from the disk cache) and becomes interactive again. Untick Settings → Cache →
   "Reload a released plot when it is shown again": showing it keeps the picture;
   Reload still works.
6. Clear the folder's cached data (Settings → Data roots / Cache) and unload it, then
   Reload: the line says it can't reload and the picture stays. No source-folder
   access: with Help › Record I/O trace on, a reload records nothing.
7. Rewrite or remove a TXY file of a plotted folder, load it again, then Reload a
   released plot of it: the amber line names the changed/missing shots.
8. Activity Monitor: releasing plots of folders no longer loaded lowers HeLab's RAM.

## After review (one commit each)

1. `61aad80` Datasets first again after each release (`evict_to` and new held buffers
   after every release). Test: the reviewer's probe (P_A released, A dropped, P_B kept).
2. `2ccc757` A reload that fails or is cancelled puts `follow.ran` back to a hollow
   view: nothing counted that can't be freed. Test: failed and cancelled.
3. `1db5dba` Pictures are PNG bytes (decoded only to paint), counted as the released
   plot's RAM; a candidate whose freeable bytes (`RamBudget.frees`: buffers no held
   dataset or other plot has) are at most its picture's last cost is skipped, and
   `release(frees)` gives up if the PNG is as large (cost remembered, no repeated grabs).
4. `22cebcd` Reload and auto reload restore exactly `shown.coverage.shots` by
   fingerprint, never a shot the plot didn't draw; the amber line names the changed or
   missing ones among those. Rerun with new settings on a released plot takes the
   view's shots.
5. `562b89a` Counted rather than capped: each plot records its runs' job ids and
   counts every result of those RamResults still keeps (`peek`); releasing and closing a
   plot discard them (`RamResults.discard`; in R1 nothing reads them again).
6. `37a16f6` A disk reload ending while a run is in flight (Live's revision) is dropped:
   that run draws the plot.
7. `6bfa985` `plotShown` fires only when a plot becomes the shown one. A reload that
   finds nothing marks the plot: shows don't try again until the folder's
   `datasetChanged` or `diskCacheChanged`; Reload always tries. A plot a reload drew in
   the last 10 s (`RELOAD_GRACE`) goes after every other candidate. With two plots and
   room for one, switching still reloads one and releases the other (by design).
8. `4ed7361` The 75 % window re-arms only below 70 % (`REARM_SHARE`).
9. `498e1df` Buffer counting moved to `helab/utils/ram_buffers.py` (utils no longer
   imports analysis); `PLOT_AUTO_RELOAD_SETTING` / `read_plot_auto_reload` in
   `constants.py`; one `fingerprints_of` (`dataset_view`).
10. Checklist item 4 keeps the scatter-never-on-screen check.

## Proposed doc changes (for the coordinator)

- AGENTS.md, **Caching** paragraph, after "The RAM budget (Settings → Cache, …)
  evicts datasets no tab shows, least recently used first, while open tabs pin their
  current datasets.": add "Plots count too (`helab/analysis/budget.py`, `RamBudget`):
  each plot's view and result arrays, by buffer (`buffer_of`), so arrays shared with a
  held dataset count once (`FolderCache.plot_bytes`); eviction keeps a dataset whose
  arrays plots hold anyway. From 50 % of the budget the status bar shows it, at 75 % a
  non-modal window lists the biggest plots and folders (once per crossing), above 80 %
  datasets no tab shows go first (`evict_to`, again after each release), then plots are
  released, least recently viewed first (one a reload drew in the last 10 s last), until
  under 80 %, if releasing frees more than the picture costs (never the shown, a running
  or a Live-following plot; none closed). The 75 % window re-arms below 70 %. A plot's
  RAM includes its older results RamResults keeps; release and close drop them. A
  released plot shows a PNG picture (`ReleasedPlot`, counted) with Reload and keeps a
  hollow view (its shots' numbers and fingerprints); it reloads from RAM or a local
  `cached` read only, never its folder, exactly the shots it drew by fingerprint,
  naming changed or missing ones, when it becomes the shown plot (Settings → Cache,
  `plot_auto_reload`, default on; not again after finding nothing until its folder's
  data or disk cache changes) or on Reload. Buffer counting: `helab/utils/ram_buffers.py`."
- AGENTS.md, **Script system**: "Results stay in RAM (`RamResults`, R1)" → add "; a
  released plot's result keeps its record without data (`RamResults.released`)".
- `.ai/memory/results/disk-cache-and-budgets.md` (or analysis-plots.md): Tony's
  thresholds and release/reload decisions (2026-10-19/20) as in the brief.
- roadmaps: mark the plot RAM budget item done in `_readme.md` once landed.

## Open points for Tony

- Datasets are dropped below 100 % of the budget (down to 80 %) only when a plot could
  otherwise be released ("datasets first"); with no releasable plot the old rule
  (100 %) stands. Confirm.
- "Least recently viewed" = least recently shown in the Settings panel, with plots not
  on screen before plots on screen (a floating window or a side-by-side dock counts
  as on screen).
- Not counted: plot widgets' own copies (pyqtgraph items, the Dash figure, ~10 MB for a
  100k-point scatter) and Live's feed (the tab's own arrays). Older results in
  `RamResults` and released plots' pictures are counted (after review).
