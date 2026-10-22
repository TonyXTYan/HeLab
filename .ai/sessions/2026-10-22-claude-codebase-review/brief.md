# Codebase review and fixes (brief for the Reviewer and the Coder)

Floor "Codebase Review", branch `agent/codebase-review` from `fc0f50d` (`dev/v0.0.6`, 2026-10-22).
Session folder: `.ai/sessions/2026-10-22-claude-codebase-review/` (this brief is `brief.md`; the
Reviewer keeps `findings.md`, the Coder `notes.md`; one shared `handoff.md` at the end).
Asked by Tony: a Fable reviewer goes through all existing implementations with an Opus partner who
fixes the issues found and makes code-quality improvements.

Two agents on this floor, connected to each other and to the Coordinator (CoCo):
- **Lens** (Reviewer, Claude Fable 5.1): reads code, finds issues, never edits, commits or pushes.
- **Mend** (Worker, Claude Opus 5.5): fixes what Lens sends, with tests; commits on the branch.

Both read `AGENTS.md` (the codebase rules: most findings are breaches of them), `roadmaps/agent-workflow.md`,
`roadmaps/known-issues.md` (already known: don't re-report, but say if you find the cause) and
the previous whole-repo review, `.ai/sessions/2026-10-20-codex-repo-bug-review/` (don't repeat
what was fixed).

## What to look for, most important first

1. **Correctness**: wrong results, lost or stale data, races between processes/threads/Qt timers,
   a helper slot freed early, a save guard skipped, a cache read treated as "nothing saved",
   cancellation that leaves work running, Windows/macOS/Linux path and file-lock differences.
2. **Rules in AGENTS.md broken**: source I/O or disk reads from the GUI thread or during rendering;
   tests touching real data; names tests patch imported by value; events outside `events.py`'s
   contract; anything that removes cached data without the user asking.
3. **Robustness**: unhandled errors, unbounded queues/memory, missing timeouts, error messages that
   lose the cause.
4. **Code quality**: duplication that has drifted, dead code, functions too long to follow, unclear
   names, types weaker than they could be (`Any`, casts, `# type: ignore`), comments that no longer
   match the code. Only where it clearly helps the next reader; no churn, no style-only rewrites.

## Order (Lens reviews an area, sends its findings, then moves on while Mend fixes)

1. `helab/io_ops/`, `helab/io_helper.py`, `helab/utils/io_service.py`, `cache_store.py`,
   `folder_cache.py` (and the rest of the cache/store/roots code in `helab/utils/`)
2. `helab/models/`, `helab/views/` explorer and tabs (`FolderExplorer`, `explorer_live.py`, dialogs)
3. `helab/analysis/` core (dataset view, runner, budget, follow, live feed, parameters) and
   `helab/views/plots/`
4. `helab/analysis/` numerics and `helab/scripts/dld/`, `helab/scripts/standard/`
5. The rest of `helab/` (main, release, build info, Dash server)

## Working together

- Lens writes each finding to `findings.md` with an ID (`R-1`, `R-2`, …): severity (blocker / high
  / medium / low / quality), file:line, what goes wrong and when (a concrete scenario), and the
  suggested fix. Then sends Mend the batch's IDs (`maestri ask "Mend" …`, short; the detail is in
  the file). Reread the code before reporting: report only what you'd defend; mark "unsure" what
  you couldn't confirm.
- Mend fixes in severity order: a test that fails before and passes after for each correctness
  fix, one commit per finding or tight group (subject names the IDs), and records each in
  `notes.md` as fixed (commit), declined (why) or needs Tony. Mend may ask Lens to clarify, and
  disagree with reasons; Lens then reviews Mend's commits for that batch (`git show`) before the
  batch counts as done.
- **Needs Tony** (don't change; list in the handoff): anything that changes user-visible behaviour,
  wording, settings or defaults, the cache/store format, or a decision recorded in AGENTS.md or
  `.ai/memory/results/`. Bug fixes that restore the documented behaviour don't need asking.
- Blocker or high finding: Lens also tells CoCo at once (`maestri ask "CoCo" …`, one line).
- After each area, Lens sends CoCo one line: area, counts by severity, fixed so far.
- `maestri floor status` stays current (Mend posts it).

## Owned paths (Mend)

`helab/` except what the other floor owns, plus new or changed tests for the code you change.

**Another floor ("CI Robustness", `agent/ci-robustness-2`) owns these; don't edit them**: report
findings there to CoCo instead:
- a new pytest config file (`pytest.ini` or similar), `tests/conftest.py`, `.github/workflows/`;
- `helab/utils/settings_store.py`, a new `helab/utils/settings_defaults.py`, and the `QSettings`
  reads in `helab/utils/constants.py`, `helab/views/SettingsDialog.py`, `helab/views/CacheTab.py`,
  `helab/views/CacheMover.py`, `helab/views/HelabMainWindow.py`, `helab/utils/cache_setting.py`,
  `helab/io_ops/admin.py`, `helab/utils/lab_parameters.py` (other code in those files is yours,
  but keep edits near settings reads to a minimum to avoid merge conflicts);
- these tests: `test_live_plots.py`, `test_cache_tab.py`, `test_io_trace.py`,
  `test_window_resize.py`, `test_dash_server.py`, `test_plot_settings_panel.py`,
  `test_gui_responsiveness.py`, and any main-window test fixture changes.

Never edit `roadmaps/`, `AGENTS.md`, `.ai/MANUAL_TODO.md`, `.ai/memory/`, `requirements*`,
`legacy/`. Proposed doc changes go in the handoff.

## Checks (Mend; Lens reruns the critical ones before signing off)

From the floor root, after `source venv/bin/activate && source .ai/local/floor-env.sh`:
`pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest` (Lens: `.ai/temp/pytest-review`;
report every RERUN), `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`.
Don't launch the HeLab GUI.

## Handoff

When all areas are done (or CoCo says stop): `handoff.md` with the counts, each finding's outcome
(fixed + commit / declined + why / needs Tony + the question), open risks, and proposed edits to
`AGENTS.md`, `roadmaps/known-issues.md` and others. Mend pushes `agent/codebase-review` once to
`TonyXTYan/HeLab`, checks its CI (`gh run watch`) and reports every RERUN; posts
`maestri floor status "<summary>" --state review`; and sends CoCo the summary. Lens confirms to
CoCo that it reviewed every fix.
