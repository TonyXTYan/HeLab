# Brief: Plot RAM budget

Floor "Plot RAM budget", branch agent/plot-ram-budget, base 531ec41 (dev/v0.0.6, after the SMB audit). Worker: Claude Code, Opus 5.5, high, Worker role. Review: a fresh Claude reviewer. Rules: your role, AGENTS.md (Caching: RAM budget; Script system; Live), roadmaps/agent-workflow.md.

## Tony's decisions (2026-10-19/20)

- **Counter.** Plots count toward the existing RAM budget (Settings → Cache, a fraction of the machine's RAM; `FolderCache.set_ram_budget`). The counter is datasets held in RAM plus each open plot's own data (its dataset view and result arrays). Arrays a plot shares with a counted dataset are counted once.
- **Thresholds, as a share of that budget:**
  - **50 %:** a status-bar warning only.
  - **75 %:** a dialog warning, once per crossing, listing the biggest plots and folders.
  - **80 %:** start releasing plots, least recently viewed first, until back under 80 %.
- **Order and exemptions.**
  - Datasets no tab shows are evicted first, as today. Plots are released only if that isn't enough.
  - Never close a plot.
  - Never release the shown plot, a running plot, or one following Live.
- **A released plot:**
  - keeps its picture, flattened to a static image (no longer interactive), with a Reload button
  - frees its view and result arrays
  - the 3D scatter keeps a static snapshot of its last frame
- **Reload when shown again.** A released plot reloads automatically when it is shown again. This is a setting, on by default. The manual Reload button always works.
- **Reviving a released plot (Tony, confirmed):** it reads only RAM (the folder's dataset still loaded) or the local disk cache, never the source folder. There is no "Reload from folder" button. If neither has the data, the plot says so and keeps its static image. A reload picks exactly the plot's shots, by their fingerprints, and says so if some changed or are missing.

## Ownership

- You own:
  - the RAM accounting in `helab/utils/folder_cache.py` (`set_ram_budget`, eviction)
  - the plot-dock and Settings code in `helab/views/HelabMainWindow.py` and `helab/models/ScriptTreeSelector.py` (AnalysisInstance/AnalysisDock)
  - `helab/analysis/results.py` / `runner.py` for releasing and reloading
  - `helab/views/CacheTab.py` for the setting
  - tests for all of the above
- Ask Maestro before touching anything else in the I/O files.

## Checks and handoff

- The usual full checks: the suite with `--reruns`, `mypy --strict` and pyright, including Windows mode, plus `git diff --check`.
- Tests: the thresholds; release order and exemptions; the static image; auto reload (on and off); a reload that finds changed or missing shots; shared arrays counted once.
- `handoff.md` with an on-screen checklist for Tony. Commit freely; push when Maestro says.
