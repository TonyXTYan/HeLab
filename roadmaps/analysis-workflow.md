# Analysis workflow

Horizon: near term. Added: 2026-10-08. Direction agreed; detailed design is draft.
Priority and completion: [overview](_readme.md).

## Purpose

Turn loaded experiment data into useful analyses without requiring users to edit
Python for routine parameter changes. Establish one complete real lab workflow
before expanding the script catalogue.

## Current foundation

Script discovery and action buttons exist in `ScriptsManager` and
`ScriptTreeSelector`. Dynamic buttons currently call `execute_action` directly
without providing a selected dataset or parameter context. Bundled example
scripts simulate actions through logging. Parameter-tree and docked-plot UI
components exist, but a common data-to-result workflow still needs definition.

## Scope

- Supply the chosen loaded dataset and validated parameters to an analysis.
  Bind each execution to a dataset identity so changing tabs cannot redirect it.
- Let scripts describe editable parameters, defaults, constraints and units.
- Run expensive computation outside the GUI thread; expose progress,
  cancellation and actionable errors. Define computation execution separately
  from the source-I/O queue rather than assuming they have identical needs.
- Display results and plots with their source dataset, settings and outcome.
- Preserve read-only shared arrays; analysis requiring mutation uses a copy.

### Standard analyses

Start with per-shot event counts, T/X/Y distributions and explicit shot selection
or exclusion. Choose the first real analysis from Tony's daily lab work. Specify
units, bins, normalization, aggregation and treatment of unreadable/unsettled
shots before claiming a scientific result is correct.

### Export

Export numerical results and figures with enough context to identify their
source folder, dataset, script and settings. Keep plotted sampling separate
from numerical analysis: a display subset must not silently become the analysed
dataset. Select supported formats during design; use the existing plotting
backends where appropriate.

## Dependencies and acceptance

Build on the browser's retained datasets, identities and truthful load outcomes.
Use small fixtures with known counts/arrays for numerical verification.

A user can select a loaded dataset, edit parameters, run a real analysis, see
its results and export them without coding. A long run leaves navigation
responsive, can be cancelled and reports failure without losing the input data.
Changing selection during execution does not change its source. Exports include
the settings used and agree with the displayed numerical results.

## Open decisions

- First daily-use analysis and its scientific definitions.
- Script context, parameter and result interfaces; compatibility with existing scripts.
- Execution isolation, cancellation semantics and memory limits.
- Initial numerical/figure export formats and lab-PC plotting fallback.

Live reruns, presets and batch execution build on this workflow; they are
separate milestones, not required to deliver the first useful analysis.
