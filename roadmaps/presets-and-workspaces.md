# Analysis presets and workspaces

Horizon: medium term. Added: 2026-10-08. Direction agreed; detailed design is draft.
Priority and completion: [overview](_readme.md).

## Purpose

Reuse analysis settings and resume an analysis arrangement without manually
rebuilding it on each launch. Treat a preset as reusable configuration and a
workspace as an arrangement tied to data and analysis instances.

## Scope

- Save named parameter presets for a script, including units and shot-selection
  rules where appropriate; applying one shows its effective settings.
- Save enough workspace state to reopen source references, chosen scripts,
  parameters and plot/panel arrangements.
- Validate saved configuration against the installed script's parameter schema.
  Identify incompatible settings instead of silently replacing them.
- On reopening, distinguish restored configuration from computed results and
  source data that still needs loading or validation.

User behaviour defaults may be overridden per folder and script. Saving changed
parameters and caching results are separate toggles; a new folder/script starts
from script parameter defaults. Each folder/script can retain run history with
its own length and size limits. A workspace can hold multiple instances of one script,
including pinned result panels. See [behaviour notes](../.ai/sessions/2026-10-14-codex-planning-for-future/analysis-behaviour.md).

## Dependencies and acceptance

Depends on stable parameter/result interfaces from the
[analysis workflow](analysis-workflow.md). Integrate with
[cache-only browsing](cache-only-browsing.md) where data is retained.

Saving and applying a preset preserves all effective analysis settings. A
workspace can reopen with its source unavailable without blocking the GUI or
claiming that absent/stale results are current. Script changes, missing sources
and corrupt configuration yield clear recoverable states. Restoring a layout
does not implicitly run expensive analysis unless the user has chosen that policy.

## Open decisions

- Preset/workspace formats, versioning and compatibility rules.
- Whether selections store explicit shot IDs, dynamic rules or both.
- Result persistence versus recomputation; saved references versus embedded data.
- Startup restoration and automatic-run behavior.

Full scientific result records belong to the later
[reproducibility milestone](reproducible-workflows.md), though this feature
should avoid a format that prevents adding them.
