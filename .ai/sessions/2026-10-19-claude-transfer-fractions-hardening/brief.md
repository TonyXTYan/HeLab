# Brief: Transfer fractions hardening

Floor "Transfer fractions hardening", branch agent/transfer-fractions-hardening, base 9f6ee5a (dev/v0.0.6, after Live L3). Worker: you (Claude Code, Opus 5.5, high). Review: a fresh Claude reviewer. Rules: your role, AGENTS.md (Script system, Live) and roadmaps/agent-workflow.md (Quick features).

## Background

Tony's Assistant built two quick features on Ground, which you harden:
- **ecbce5b, Transfer fractions:** `helab/scripts/standard/transfer_fractions.py`, a Python port of `legacy/Momentum_Bells_test`'s `monitor_momentum.m` / `fraction_calc.m`.
  - Orders are auto-found in the T histogram.
  - `DatasetAnalysis.detected_parameters` fills the manual centre and spacing from each run.
- **1bc3edb, From shot:** the shared Shots setting "From shot (0 = first)" is always shown and applies to all modes (all / last N / range), in every plot.

The MATLAB sources are on Ground at `~/GitHub/HeLab/legacy/Momentum_Bells_test` (read-only). Your floor's submodule folders are empty, so read them there. Don't init the submodule (~400 MB).

## Harden

1. **Detection edge cases:**
   - no events, one shot, one peak
   - peaks of similar height (order 0 picked wrongly)
   - orders closer than the FWHM
   - a search range that holds only side peaks
   - very wide or very narrow peaks
   - the 20,000-bin cap
   - NaN or inf in T
   - all events outside the XY box

   Each case either gives a correct answer or a clear message on the plot, never a crash or a silently wrong order 0.
2. **Manual mode:**
   - a `half_width` larger than half the spacing (overlapping windows): say so, or clip, and document which
   - a centre outside the data
3. **detected_parameters with L3's Live reruns:**
   - In auto mode, detection should refill the hidden manual values on each rerun.
   - Switching to manual should keep the last values.
   - `AnalysisInstance._show_detected` is in ScriptTreeSelector, which the Floating plot settings floor owns. **Ask me before changing it.**
4. **From shot:**
   - past the last shot
   - gaps in shot numbers
   - combined with last N, or with a range up to a shot
   - Live adding shots (L3)
   - the `describe_run` / `shots_brief` wording for every combination
5. **Fractions:**
   - zero totals
   - counts per shot against the original MATLAB, on synthetic data: write a small reference from `fraction_calc.m`'s logic in Python, and compare on fixtures
   - note any intended differences, e.g. fractions over the sum of the orders

Keep `compute` free of I/O.

## Ownership

You own:
- `helab/scripts/standard/transfer_fractions.py`
- `helab/analysis/selection.py`
- `tests/test_transfer_fractions.py`
- the Shots tests in `tests/test_analysis.py`
- new test files for this work
- your session folder

You don't own `helab/models/ScriptTreeSelector.py` or `helab/analysis/parameter_tree.py`: Floating plot settings owns them. Also not the I/O files (`io_helper`, `io_service`, `folder_cache`, `FolderExplorer`): the SMB audit owns them. Ask me for anything else.

## Checks and handoff

- Run the full suite: `pytest -n 6 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`. Report any RERUN by name.
- Run `mypy --strict` on helab and tests, also with `--platform win32`.
- Run pyright on helab and tests, also with `--pythonplatform Windows`.
- Run `git diff --check`.
- Commit each item separately, and bump the analysis version if its output changes.
- When done, write `handoff.md`:
  - what changed, decisions, a short on-screen checklist for Tony with real Bragg/magnetic data
  - proposed doc changes: the AGENTS.md Transfer fractions and Shots lines, and the "hardening done" line for `roadmaps/_readme.md`

  Then run `maestri floor status "..." --state review`, push, and report with `maestri ask "Maestro" "<summary>"`.
