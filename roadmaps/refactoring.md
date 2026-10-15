# Refactoring for independent feature work

Added: 2026-10-13. Revised: 2026-10-15. Draft; nothing implemented.
Priority and completion: [overview](_readme.md).
Detailed design, code survey and proposed validation:
[2026-10-14 session notes](../.ai/sessions/2026-10-14-codex-planning-for-future/refactoring.md).

## Goal

Make it practical for multiple AI agents to develop separate HeLab features
at the same time. Tony should be able to start another idea while existing
workers continue, when the tasks have independent ownership and agreed
interfaces. A human-supervised coordinator reviews the roadmap and active
work, recommends assignments, and asks Tony before spawning workers,
committing, pushing or merging.

**Functional decoupling comes first.** Split responsibilities and ownership
of mutable state so a feature can change behind a tested interface without
editing several unrelated areas. Smaller files help reading and token use,
but size alone is not a reason to move code. Refactoring preserves current
user-visible behaviour, wording and timing.

This is a development workflow. The [shared analysis job
runner](analysis-job-runner.md) is a separate product feature for running
scientific analyses from the GUI or headless clients.

## Direction

- Give source I/O and cache operations an explicit owner and public
  request/result boundary. Keep their current scheduling, cache and recovery
  safeguards.
- Define a read-only dataset view with stable input identity and provenance
  for analysis consumers. Quick scripts reuse arrays in RAM; longer or Live
  work retains the view as needed, without per-update disk writes. Bind a
  job to its input view, not to a mutable tab selection.
- Keep analysis execution behind a versioned job/result contract and separate
  it from browser widgets and Qt presentation state.
- Let the browser, analysis and plot UI own their presentation workflows;
  keep the main window focused on composition.

These are proposed seams, not frozen APIs. The
[session notes](../.ai/sessions/2026-10-14-codex-planning-for-future/refactoring.md#architectural-target)
describe candidate ownership and the current coupling.

## Milestones (feature-driven, decided 2026-10-15)

Refactor **for features**, not from a complete map of the code first: each slice
is chosen because a planned feature, or two parallel pieces of work, would
otherwise edit the same code.

1. **Dataset view first.** Add the read-only dataset view (input identity,
   shot map, provenance, read-only arrays) as the seam between browser/cache
   and analysis, while building the first analysis (the
   [3D scatter](analysis-workflow.md#first-analysis-3d-scatter-decided-2026-10-15)).
   It adds code beside the browser rather than moving it.
2. **Split where work collides.** When two planned tasks need the same state
   (`FolderCache`, `FolderExplorer`, `HelabMainWindow` wiring), extract the
   smallest boundary that lets them proceed separately: characterize the
   change path first (including calls through attributes and test patches),
   then move ownership behind a typed contract.
3. **Pilot.** Run two independent tasks in parallel with the
   [agent workflow](agent-workflow.md),
   then revise boundaries and the workflow from what conflicted.

The [session notes](../.ai/sessions/2026-10-14-codex-planning-for-future/refactoring.md#candidate-implementation-slices)
list candidate slices to draw from when a collision calls for one.

## Parallel work

Roles, branch and approval rules, Maestri floors, cloud agents and settings
isolation: [parallel agent workflow](agent-workflow.md).

## Acceptance

- A feature can be changed and tested against documented contracts without
  editing unrelated areas' internals; shared mutable state has one owner.
- Two approved, distinct tasks can proceed in isolated worktrees and
  integrate without avoidable shared-file conflicts or unreviewed contract
  changes.
- Existing behaviour remains covered. The full suite, strict type checks
  and applicable packaged-helper checks pass for each integrated code slice;
  native and real-volume checks stay in
  [.ai/MANUAL_TODO.md](../.ai/MANUAL_TODO.md).

## Open decisions

- Whether to start after `v0.0.5a1` merges, as early v0.0.6 work, or sooner
  for an isolated preparatory slice.
- Exact contracts and package names, decided per slice.
- Which two tasks to use in the pilot (proposed: build size and small TXY
  test fixtures, which touch neither `FolderCache` nor UI wiring).
- Workflow and isolation questions: [agent workflow](agent-workflow.md).
