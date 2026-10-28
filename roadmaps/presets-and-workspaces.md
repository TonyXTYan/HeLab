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

## Stage 1 (done 2026-10-23, `agent/presets-reopen`, merge `c204d4b`)

- **Script presets**, per analysis id and action, in each plot's settings page (Presets row):
  every parameter and the library, not the Live group. Settings changed from the preset applied
  are marked, with Save to preset “p” / Save as new preset….
- **Arrangement presets** of one folder (Presets menu): the folder, Live, the plots with their
  own values, library, Live group and places. Applying asks Replace / Add / Cancel.
- **Reopen at start** (Settings → General, default on): plots run on their folder's data from
  RAM or the local disk cache only, else wait for a tab's load. Plots that can't reopen: Keep for
  later (default) or Drop, asked once per start.
- **Validation** against the installed script names every value that doesn't fit; nothing is
  clamped or replaced.
- **Storage:** the disk cache store's `presets` table (helpers only, newest `set_at` wins, kept
  through Clear all, purges and Reset all settings); the plots to reopen stay in QSettings.
- **Settings → Cache › Presets…** lists them (fits the installed script or not) with Rename,
  Duplicate and Delete.

Decided by Tony (2026-10-22): both kinds of preset; the change marks with Save to preset / Save as
new; Replace or Add; Keep or Drop; storage apart from QSettings; the inspector without editing
for now. Taken by the worker and not challenged: an arrangement stores each plot's values (a
script preset's name is provenance only, and a later change to it isn't followed); script presets
leave out the Live group. Details: `.ai/sessions/2026-10-22-claude-presets-reopen/handoff.md`.

Later: editing values in the inspector (perhaps an "Edit in a plot" button), the full workspace
file (several folders, pinned results), result caching for reopened plots
([result caching](result-caching.md)).

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
- Result persistence versus recomputation; saved references versus embedded data (stage 1:
  arrangements embed each plot's values).
- Workspaces beyond one folder; editing presets outside a plot.

Full scientific result records belong to the later
[reproducibility milestone](reproducible-workflows.md), though this feature
should avoid a format that prevents adding them.
