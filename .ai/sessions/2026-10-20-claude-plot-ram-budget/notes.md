# Notes: Plot RAM budget

Branch `agent/plot-ram-budget` from 531ec41. Brief: [brief.md](brief.md).

## Design

- **Counter** (`helab/analysis/budget.py`). Arrays are counted by the memory they use:
  `buffer_of` walks an array's `.base` chain to the array (or buffer, through
  `np.frombuffer`'s memoryview) that owns the memory, so a view's read-only shot
  views, the dataset's arrays and a restored view are one buffer. Datasets keep being
  counted as `FolderCache` always counted them (`metadata["bytes"]`, unchanged so the
  existing eviction tests and wording hold); plots add only buffers no held dataset
  has (`FolderCache.plot_bytes`). A plot's buffers: its views (`follow.ran`,
  `follow.pending`, `_shown_view`, `_job_view`) and its results' arrays (`arrays_in`
  walks dataclasses, tuples, lists, sets and mappings). Per-view and per-dataset
  measurements are cached in `WeakKeyDictionary`s (views never change; a dataset is
  measured again if its shot count changes).
- **Step 1, as today**: `FolderCache._evict` drops datasets no tab shows, LRU first,
  until datasets plus the plots' extra fit the budget. New: a dataset whose arrays a
  plot holds anyway is skipped (dropping it would free nothing). An early-out keeps
  selection changes cheap when everything fits even counting every plot array apart.
- **Step 2, the plots' 80 %** (`RamBudget.check`, a pass of the event loop after
  `datasetChanged`, after each plot run and plot open/close, and after Settings):
  only when there is a plot that may be released, unshown datasets go first down to
  80 % (`FolderCache.evict_to`), then plots, not-on-screen before on-screen, least
  recently shown first (`PlotSettingsPanel.recent()`), skipping plots whose data is
  all a held dataset's. Interpretation to confirm: datasets are dropped below 100 %
  of the budget only when a plot could otherwise be released ("datasets first");
  with no releasable plot the dataset rule is today's (100 %).
- **Exemptions** (`AnalysisInstance.releasable`): the shown plot (the Settings
  panel's current plot), a running or reloading plot, one with a revision waiting,
  one following Live (`follow.on` and Live watches its folder), a plot never drawn.
  No plot is ever closed.
- **Release**: `snapshot` grabs the plot widget (a plot never laid out, behind other
  tabs, is first given the plot area's size), the dock shows `ReleasedPlot` (one line
  "Released to free RAM: a picture, not interactive" + Reload, the picture scaled to
  fit) under the same source lines (`HelabMainWindow.replace_plot_content`). The
  result is replaced by a stub without data (`RamResults.released`), the views by a
  hollow one (`hollow`: same identity, revision, shot numbers and fingerprints, every
  shot the same empty read-only array). Deleting the plot widget frees the Dash
  page's figure for the scatter (`PlotlyPane`'s `destroyed` → `remove_plot`).
- **Reload** (`AnalysisInstance.reload`): RAM first (pins and datasets of the folder,
  best by shots kept); if that isn't every shot as it was, a `cached` read on the
  local lane (owner `plot-reload:<uuid>`, `deliberate`, `allow_large`), and the
  better of the two is used. `restore` keeps exactly the view's shots whose
  fingerprints match; changed and missing shots among those the plot drew are named
  in the dock's amber line ("Reloaded from RAM without 2 of its 5 shots: shot 2
  changed since; shot 4 missing") until the plot's next own run. None of its drawn
  shots, or nothing in RAM and the disk cache: the picture stays and its line says
  why ("can't reload: …"). Reload reruns with the parameters it was drawn with;
  Rerun on a released plot reloads with the settings shown. Auto reload on
  `PlotSettingsPanel.plotShown` when `RamBudget.auto_reload` (Settings → Cache
  checkbox, `plot_auto_reload`, default on).
- **Runner fix**: `AnalysisRunner._run_jobs` kept the last job's `(script, context)`
  in its loop variables while waiting for the next job, so the last run's view (and
  its shot arrays) stayed alive. The job now runs in `_run` and the loop drops it.

## Not counted (on purpose, to note)

- Plot widgets' own copies (pyqtgraph items, the Dash figure's JSON lists of up to
  the display cap). They go when the plot is released.
- `RamResults`' unpinned results (up to 64, older runs no plot shows): results are
  small next to shots; they can't hold views (only `ViewKey`s).
- `LiveFeed`'s views: they are the Live tab's pinned dataset's arrays.

## Outside the owned paths

- `helab/views/SettingsDialog.py`: one line so Reset all settings resets the new
  checkbox (else Save after Reset wrote the stale value). Not an I/O file.
- New module `helab/analysis/budget.py` (the counter, thresholds, `RamBudget`,
  `hollow`/`restore`); the setting key `plot_auto_reload` lives there, not in
  `helab/utils/constants.py`, which I didn't own.
- FolderCache: only the RAM accounting (`ram_users`, `plot_bytes`, `held_buffers`,
  `held_sizes`, `evict_to`, `_evict`). The reload uses the existing `submit(...,
  "cached")` API unchanged.

## Validation

See [handoff.md](handoff.md).
