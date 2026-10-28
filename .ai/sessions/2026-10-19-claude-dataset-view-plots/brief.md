# Brief: Dataset view + first plots

Coordinator: Maestro (ground). Floor: "Dataset view plots", branch
`agent/dataset-view-plots`, base: `dev/v0.0.6` at the commit that adds this
brief. Rules: `AGENTS.md`, `roadmaps/agent-workflow.md`.

## Objective

Refactoring milestone 1 ([plan](../../../roadmaps/refactoring.md#milestones-feature-driven-decided-2026-10-15))
with its first consumers: the [3D scatter](../../../roadmaps/analysis-workflow.md#first-analysis-3d-scatter-decided-2026-10-15)
and two basic plots, results in RAM only ([result caching](../../../roadmaps/result-caching.md#stages) R1).

1. **Dataset view** (new module, beside the browser; e.g.
   `helab/analysis/dataset_view.py`): read-only, immutable snapshot of a loaded
   dataset — input identity (source path, data root key if known, signature),
   a revision that changes when shots are added (Live will add them), shot map
   (shot id → read-only T/X/Y array, file fingerprint), provenance (load
   source, loaded/checked time, still-being-written count). Built from what
   `FolderExplorer.displayed_dataset` holds today without changing the
   browser. Arrays stay shared and read-only; no copies unless an analysis
   asks.
2. **Script context**: an analysis action receives a dataset view and its
   parameters, not the tab. Changing the selection during a run never changes
   its input. Keep existing scripts working.
3. **3D scatter** (rebuild `helab/scripts/plotly_3d_sactter.py`; Plotly via
   the Dash server): auto-crop to regions of interest as its one parameter,
   a display-sample cap labelled on the figure (the sample never becomes the
   analysed data), an **Open in browser** button (lab PCs can't paint
   QtWebEngine), the plot dock showing its source and revision. Remove the
   `print`s and the silent 10k cut.
4. **Basic plots**: counts per shot (vs shot number), and T, X, Y histograms.
   Choose PyQtGraph or Plotly and say why (fast redraw for Live later favours
   PyQtGraph).
5. Results in RAM bound to the view's identity and revision (R1), shown with
   their parameters.

6. **Analysis identity and version** (minimal now, per
   [job runner](../../../roadmaps/analysis-job-runner.md) and
   [result caching](../../../roadmaps/result-caching.md)): every analysis
   declares a stable ID and a version it bumps when its output changes
   (e.g. in `ScriptMetadata`), and HeLab records the script file's hash
   beside it. Every result and plot dock carries analysis ID, version, file
   hash, effective parameters and the dataset view's identity and revision,
   shown in the dock's source line or tooltip. These plots will change a lot:
   a result made by an older version must be recognisable as such later (the
   key for R2 reuse and "outdated" marks). No result store yet; just the
   record and its display.

Defaults (Tony, 2026-10-19): auto-crop is configurable and by default keeps
the region holding **99 % of the events** (define the rule, e.g. per-axis
central intervals sized so the box holds 99 %, and show the bounds on the
plot); display cap **100k points**; histogram bins automatic (e.g.
Freedman–Diaconis), with a bin-count override.

## Ownership

- Owns: the new dataset-view/analysis package, `helab/scripts/`
  (except `legacy_plotly/`), `helab/models/ScriptTreeSelector.py`, the plot
  dock code in `helab/views/HelabMainWindow.py` (`_set_plot_source`,
  `_update_plot_source_label`, plot creation), `helab/utils/dash_server.py`,
  tests for all of these, small TXY fixtures under `tests/` if you need them.
- Don't touch: `helab/views/FolderExplorer.py`, `helab/utils/folder_cache.py`,
  `helab/utils/io_service.py`, `helab/io_helper.py`, the Live action and
  `closeEvent`: the "Live L1" floor owns those. Read `displayed_dataset` only;
  if the view needs a new field from the browser, ask the coordinator first.
- Docs: write only this session folder. Put proposed changes to `AGENTS.md`,
  `roadmaps/`, `.ai/memory/` and `.ai/MANUAL_TODO.md` in `handoff.md`.

## Checks

- Floor setup: `python -c "import helab; print(helab.__file__)"` must print a
  path inside this floor, and `source .ai/local/floor-env.sh` before running
  the app or scripts. Native QSettings are not isolated yet: prefer offscreen
  scripts with a tmp `QSettings` file; standalone scripts import
  `PyQt6.QtWebEngineWidgets` before creating the QApplication.
- Numerical tests on known arrays (crop bounds, counts, histogram totals,
  sampling label vs analysed count); a test that changing selection mid-run
  leaves the input unchanged; screenshots at `QT_SCALE_FACTOR=2` for Tony.
- `pytest -n 6 --reruns 5 --reruns-delay 1` (another floor runs too), report
  any RERUN; `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`.

## Handoff

Commit as you go (subject + body with what, why, validation; Co-Authored-By
line). When done: `handoff.md` here (what changed, the view's contract for L3,
decisions, open questions, proposed doc changes, manual checks), push
`agent/dataset-view-plots` once, `maestri floor status "…" --state review`,
and tell the coordinator.
