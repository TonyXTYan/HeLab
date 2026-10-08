# Run comparison and batch analysis

Horizons: comparison in the medium term; batch analysis in the long term.
Added: 2026-10-08. Direction agreed; detailed design is draft.
Priority and completion: [overview](_readme.md).

## Run comparison

Compare folders or experimental runs using the same analysis definitions and
effective settings. Start with selected runs and a defined summary/overlay view.
Keep each result's source, shot selection, units and normalization visible so
differences in configuration are not mistaken for differences in the experiment.

Depends on the [analysis workflow](analysis-workflow.md) and reusable settings
from [presets](presets-and-workspaces.md).

Acceptance: independently analysing the same input/settings gives the same
numerical outcome as comparison mode. Results stay associated with the correct
run, missing/unreadable shots are reported, and incompatible settings or units
are identified. Comparing large folders respects data and computation limits.

## Batch analysis

Apply a selected script or agreed analysis sequence to multiple runs. Provide
per-run queued/running/completed/failed outcomes, bounded concurrency and
cancellation. Retain completed results when another run fails; define retry
without duplicating successful work. Export a result table with source/settings
and explicit failure or missing-data entries.

Build this after single-run execution and comparison are useful. Coordinate data
loading with the existing I/O scheduler so bulk work does not block interactive
browsing. Computation scheduling needs its own design.

Acceptance: a batch agrees with independent single-run analyses, reports partial
success honestly, remains responsive and can stop without discarding completed
outcomes. If persistent resume is selected, it validates input/settings before
reusing results rather than relying on run names alone.

## Open decisions

- Definition of a run and initial folder-selection interaction.
- Overlay/table presentation, normalization and uncertainty treatment.
- Computation concurrency, memory budget and scheduling alongside Live.
- Retry semantics and whether restart-resume belongs in the first batch version.
- Metadata needed for scientifically meaningful grouping; integrate the later
  [metadata feature](reproducible-workflows.md#experiment-metadata) when available.
