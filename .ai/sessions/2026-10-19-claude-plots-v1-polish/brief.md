# Brief: Plots v1 polish

Floor "Plots v1 polish", branch agent/plots-v1-polish, base c8e3a2c (dev/v0.0.6). Rules: your role, AGENTS.md (see Script system, Visualization and Live) and roadmaps/agent-workflow.md. Background: .ai/sessions/2026-10-19-claude-dataset-view-plots/ (handoff and review-codex.md) and .ai/memory/results/analysis-plots.md.

Tony is trying the plots on his Mac and will send **many edit requests** while you work. Treat this floor as long-lived:
- commit each request separately
- don't push until I say the round is done
- the brief grows as requests arrive: keep a running list in notes.md

## First round (Tony, 2026-10-19)

1. **Script settings are empty.** Each plot's parameter tab needs basic, useful parameters. Proposed (Tony may change these):
   - Shots: all (default), the last N, or a range of shot numbers. Use this for the input selection of every plot; Live will use "last N" later.
   - View range: auto-crop (the current default, keep %) or manual T/X/Y min–max.
   - 3D scatter: point size, opacity, display cap (default 100k).
   - Histograms: bins (0 = auto, as now), log Y.
   - Counts per shot: nothing more for now, beyond the shot selection.

   Parameters go through the existing ParameterSpec/effective/describe path. The dock's source line and record must show them. Bump each changed analysis's `version`.
2. **Centre hint.** "<folder> is loaded – run a script to plot it" (CentralHint) hides while any plot dock is open, and comes back when the last one closes.
3. **Rename the group** "Plots" to **"Basic plots v1"**. Keep the version visible, e.g. from a group-level constant, so a later v2 is obvious.
4. **Live leftover:** make tests/test_live_io.py::test_a_live_check_pauses_background_work_only_while_it_reads deterministic. Gate the background helper so it is provably running before the Live read (wait for its first progress event, or block it on a FIFO), with a bounded timeout. Keep the Windows typing guard (c8e3a2c) in mind: any POSIX-only call goes inside `if sys.platform != "win32":`.

## Ownership

You own:
- `helab/analysis/`
- `helab/scripts/standard/`
- `helab/scripts/base.py`, `scripts_manager.py`
- `helab/models/ScriptTreeSelector.py`
- the plot-dock and central-hint code in `helab/views/HelabMainWindow.py`
- `tests/test_analysis*.py`, `tests/test_script_system.py`, `tests/test_live_io.py`
- your session folder

Ask me before touching anything else, especially `folder_cache.py`, `io_service.py`, `io_helper.py` and `FolderExplorer.py`.

## Checks

- Before each push round: the full suite, `pytest -n 6 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest` (`mkdir -p .ai/temp` once), plus `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests` and `git diff --check`.
- Windows typing: run `mypy tests --strict --platform win32` and `pyright tests --pythonplatform Windows` too. CI failed on that today.
- Report every RERUN by name.
- For visual changes, save offscreen renders, as before, to screenshots/ in your session folder.

## Handoff

- When a round is ready, write or extend handoff.md: what changed, decisions, open questions, proposed doc changes, manual checks.
- Then `maestri floor status "..." --state review` and report with `maestri ask "Maestro" "<summary>"`.
- Push only when I say so.
