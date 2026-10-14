# Refactoring for independent feature work

Added: 2026-10-13. Revised: 2026-10-14. Draft; nothing implemented.
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

## Milestones

1. Map representative feature change paths, shared state, signals, imports,
   tests and packaged entry points. Identify work that is already independent.
2. Define the smallest typed contracts needed by real consumers, characterize
   current behaviour and test both sides of each boundary.
3. Extract responsibilities in reviewable slices around those contracts.
   Sequence source I/O, cache, browser and UI changes by dependency rather
   than module size. Independent feature work can continue where scopes do
   not overlap.
4. With Tony's approval, pilot one refactor slice alongside one independent
   feature in isolated worktrees. Review and test the combined result, then
   revise boundaries from the conflicts and integration effort observed.

The [session notes](../.ai/sessions/2026-10-14-codex-planning-for-future/refactoring.md#candidate-implementation-slices)
give candidate code slices and the
[supervised agent workflow](../.ai/sessions/2026-10-14-codex-planning-for-future/refactoring.md#human-supervised-parallel-work).

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
- Exact contracts, package names and ownership after the change-path map.
- Which independent feature to use in the pilot. The first daily-use lab
  analysis can be selected later.
- Where to track active worktree ownership without duplicating this
  roadmap's priority and completion list.
