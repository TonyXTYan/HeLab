# Analysis workflow

Horizon: near term. Added: 2026-10-08. Direction agreed; detailed design is draft.
Priority and completion: [overview](_readme.md).

## Purpose

Turn loaded experiment data into useful analyses without requiring users to edit
Python for routine parameter changes. Establish one complete real lab workflow
before expanding the script catalogue.

## Current foundation

Script discovery and action buttons exist in `ScriptsManager` and
`ScriptTreeSelector` (the right-hand panel). `helab/scripts/` is this analysis
script system: the panel lists the bundled analyses in `standard/` (group
"Plots": 3D scatter, counts per shot, T/X/Y histograms, 2026-10-19) and any
folder loaded with Load Scripts…; `legacy_plotly/` holds the lab's older Plotly figures.
Plotting-library prototypes that read the old cache directly moved out to
`dev/plotting-prototypes/` with the old browser's removal
([plan](cache-storage-and-settings.md#old-browser-removal)). Dataset analyses (`DatasetAnalysis`) get an immutable dataset view and
validated parameters, run in one analysis worker thread and keep their results
in RAM (see AGENTS.md › Script system); older `HelabAnalysisScript`s still get
`execute_action`. Folder-following views, export and saved results are still to
come.

## Scope

- Supply the chosen loaded dataset and validated parameters to an analysis.
  Bind each execution to a dataset identity so changing tabs cannot redirect it.
- Let scripts describe editable parameters, defaults, constraints and units.
- Run expensive computation outside the GUI thread; expose progress,
  cancellation and actionable errors. Define computation execution separately
  from the source-I/O queue rather than assuming they have identical needs.
- Display results and plots with their source dataset, settings and outcome.
- Preserve read-only shared arrays; analysis requiring mutation uses a copy.

## Folder-following analysis behaviour (decided 2026-10-14)

Selected scripts remain selected across folder changes. Unpinned analysis views
follow the new folder; pinned views retain their panel and result. A script can
have multiple instances. Each script declares whether it permits automatic
runs. Show a saved outdated result immediately with an indicator, then run in
the background only if permitted and notify when the new result is ready.
Use script parameter defaults for a new folder. User defaults govern behaviours
such as parameter saving and result caching; per-folder/script settings override
those behaviours and may save changed parameters, shot selection and history.
Parameter saving and result caching are separate settings. Every saved result retains its
exact inputs, parameters and script identity. Detailed interaction rules and
open cases: [planning notes](../.ai/sessions/2026-10-14-codex-planning-for-future/analysis-behaviour.md).

### First analysis: 3D scatter (decided 2026-10-15)

Tony's choice: an interactive **3D scatter** of the loaded T/X/Y events, built
on Plotly and served by the existing Dash server (`helab/utils/dash_server.py`)
so most interaction (rotate, zoom, hover, select) happens in Plotly itself. Its
only default setting at first is **auto-crop to regions of interest**; more
parameters come later. It replaced the old `plotly_3d_sactter.py` panel
action (2026-10-19) and is the real consumer for the dataset view, the job contract and
[result caching](result-caching.md) stage R1.

- Show it in a browser tab as well as the plot area: lab PCs can't paint
  QtWebEngine ([memory](../.ai/memory/results/lab-pc-qtwebengine-black-render.md)).
- WebGL scatter can't draw every event of a large folder. Any display sampling
  is labelled on the figure and never becomes the analysed data (see Export).
- Defaults (Tony, 2026-10-19): auto-crop is configurable and by default keeps
  the region holding 99 % of the events; the display cap is 100k points;
  histogram bins are automatic. Each analysis records a stable ID and version
  (plus its file's hash) with every result, since these first plots will change.
- v1 (2026-10-19): auto-crop is a heuristic box (peel the sparsest extreme
  events, then narrow each axis to its exact shortest window) keeping 99 % of
  all events; its bounds and kept share are on the figure, and they are derived
  results, not parameters (Keep % is). The display sample is a fixed-seed random
  100,000 events, labelled. Axes are in s and m as stored.
- Open (Tony to check on real data): 99 % of *all* events keeps part of a flat
  background tail, so the box can be much wider than the cloud; a
  background-subtracted "99 % of the signal" rule, presets, or a crop adjusted
  on the plot are the options. Units (mm vs m) to confirm.
- To decide while designing: how auto-crop finds the regions of interest (for
  example density or percentile bounds on T, X and Y), whether the crop is
  shown and adjustable, and whether crop limits count as parameters saved with
  the result.

### Standard analyses

Then per-shot event counts, T/X/Y distributions and explicit shot selection or
exclusion. Specify units, bins, normalization, aggregation and treatment of
unreadable/unsettled shots before claiming a scientific result is correct.

### Export

Export numerical results and figures with enough context to identify their
source folder, dataset, script and settings. Keep plotted sampling separate
from numerical analysis: a display subset must not silently become the analysed
dataset. Select supported formats during design; use the existing plotting
backends where appropriate.

## Dependencies and acceptance

Build on the browser's retained datasets, identities and truthful load outcomes.
Use small fixtures with known counts/arrays for numerical verification.
Use the shared [analysis job runner](analysis-job-runner.md) contract for
execution and results, so GUI and headless clients agree on the same run.

A user can select a loaded dataset, edit parameters, run a real analysis, see
its results and export them without coding. A long run leaves navigation
responsive, can be cancelled and reports failure without losing the input data.
Changing selection during execution does not change its source. Exports include
the settings used and agree with the displayed numerical results.

## Open decisions

- Auto-crop rule for the 3D scatter (above); the next analyses after it.
- Script context, parameter and result interfaces; compatibility with existing scripts.
- Execution isolation, cancellation semantics and memory limits.
- Initial numerical/figure export formats and lab-PC plotting fallback.

Live reruns, presets and batch execution build on this workflow; they are
separate milestones, not required to deliver the first useful analysis.
