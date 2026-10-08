# Reproducible scientific workflows

Horizon: long term. Added: 2026-10-08. Direction agreed; detailed design is draft.
Priority and completion: [overview](_readme.md).

## Purpose

Let a user identify how a result was produced and repeat the same analysis, while
supporting lab-specific scientific tasks through the common script workflow.
Earlier exports and presets should provide a foundation without claiming full
reproducibility before input, code and settings are recorded.

## Experiment metadata

Associate shot/run data with the experiment settings needed for analysis,
selection and comparison. Establish the actual metadata sources and join keys
before designing an importer. Report missing or conflicting matches; do not
infer experimental parameters from ambiguous folder names.

Acceptance: a known fixture joins the intended shots/runs exactly, preserves
units and source attribution, and exposes unmatched or ambiguous records.
Metadata access must follow the same responsiveness and offline boundaries as
data access.

## Analysis sequences and result records

Save reusable ordered analyses with explicit inputs, outputs and dependencies.
Reuse the single-analysis execution, cancellation and error conventions rather
than inventing a second runner.

Save result records containing dataset identity, script/code version, effective
parameters, shot inclusion/exclusion and relevant metadata. Record enough
environment information to explain numerical differences. Existing size/mtime
fingerprints identify cached snapshots under the write-once TXY assumption;
they are not cryptographic proofs of source content. Decide the required level
of input preservation or verification during design.

Acceptance: a saved result can be traced to its inputs and settings, and an
available matching input can be rerun under documented numerical tolerances.
Missing source data or changed code/settings is identified rather than silently
presented as an equivalent rerun. Sequence failures retain completed outcomes
and block dependent steps appropriately.

## Specialist analyses

Add specialist scripts according to agreed lab demand. Correlations, fitting,
ROI-based selection or calibration are candidate areas, not chosen algorithms.
For each, define the observable, units, normalization, assumptions and expected
results before implementation. Validate against known inputs or independent
calculations; visual agreement alone is insufficient.

## Dependencies and open decisions

Build on [analysis execution/export](analysis-workflow.md),
[presets/workspaces](presets-and-workspaces.md) and
[comparison/batch](run-comparison-and-batch.md).

Open choices include metadata formats and keys, sequence representation,
script-version capture, result-record schema, input retention, rerun tolerances
and which scientific analysis has the strongest immediate lab use.
