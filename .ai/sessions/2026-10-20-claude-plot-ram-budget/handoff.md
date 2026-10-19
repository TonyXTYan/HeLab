# Handoff: Plot RAM budget

Branch `agent/plot-ram-budget` (base 531ec41). Design and reasoning: [notes.md](notes.md).
Not pushed yet (waiting for Maestro).

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
- `helab/analysis/results.py` (`RamResults.released`), `runner.py` (the worker no
  longer keeps the last job's input alive while idle).
- `helab/views/HelabMainWindow.py` (`setup_ram_budget`, status-bar button, the 75 %
  window, `replace_plot_content`), `helab/views/CacheTab.py` (checkbox, plots' bytes
  in the memory line).
- Outside the listed paths: one line in `helab/views/SettingsDialog.py` so Reset all
  settings resets the checkbox.
- `tests/test_plot_ram_budget.py` (16 tests).

## Checks

- Full suite `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest -rR`:
  1272 passed, 2 skipped, 2 xfailed, no RERUN (61.8 s).
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
4. **3D scatter**: released, its picture is its last frame as rotated (check on macOS
   and on a lab PC; on the lab PCs whose GPU can't paint QtWebEngine it will be
   black, like the pane). Open in browser for it no longer exists once released.
5. Click a released plot's tab: it reloads (from RAM if the folder is still loaded,
   else from the disk cache) and becomes interactive again. Untick Settings → Cache →
   "Reload a released plot when it is shown again": showing it keeps the picture;
   Reload still works.
6. Clear the folder's cached data (Settings → Data roots / Cache) and unload it, then
   Reload: the line says it can't reload and the picture stays. No source-folder
   access: with Help › Record I/O trace on, a reload records nothing.
7. Rewrite or remove a TXY file of a plotted folder, load it again, then Reload a
   released plot of it: the amber line names the changed/missing shots.
8. Activity Monitor: releasing plots of folders no longer loaded lowers HeLab's RAM.

## Proposed doc changes (for the coordinator)

- AGENTS.md, **Caching** paragraph, after "The RAM budget (Settings → Cache, …)
  evicts datasets no tab shows, least recently used first, while open tabs pin their
  current datasets.": add "Plots count too (`helab/analysis/budget.py`, `RamBudget`):
  each plot's view and result arrays, by buffer (`buffer_of`), so arrays shared with a
  held dataset count once (`FolderCache.plot_bytes`); eviction keeps a dataset whose
  arrays plots hold anyway. From 50 % of the budget the status bar shows it, at 75 % a
  non-modal window lists the biggest plots and folders (once per crossing), above 80 %
  datasets no tab shows go first (`evict_to`), then plots are released, least recently
  viewed first, until under 80 % (never the shown, a running or a Live-following plot;
  none closed). A released plot shows a picture (`ReleasedPlot`) with Reload and keeps
  a hollow view (its shots' numbers and fingerprints); it reloads from RAM or a local
  `cached` read only, never its folder, exactly its shots by fingerprint, naming
  changed or missing ones, when shown again (Settings → Cache, `plot_auto_reload`,
  default on) or on Reload."
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
- Not counted: plot widgets' own copies (pyqtgraph items, the Dash figure), unpinned
  older results in `RamResults` (small), Live's feed (the tab's own arrays).
