# Codebase review: Mend's notes

Worker: Mend (Claude Opus 5.5). Branch `agent/codebase-review` from `fc0f50d`.

## Baseline (2026-10-22, before any change)

From the floor root with `floor-env.sh`:

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: 2378 passed, 2 skipped,
  2 xfailed in 128 s; **no RERUN**. Two warnings, both pyqtgraph's NumPy 2.5 deprecation
  (`arr.shape = (3, 3)` in `pyqtgraph/functions.py`, from `test_t_spectrum.py`).
- `mypy helab/ --strict`: no issues (150 files). `mypy tests --strict`: no issues (104 files).
- `pyright helab tests`: 0 errors, 0 warnings.

## Findings

Each of Lens's findings (`findings.md`) as fixed (commit), declined (why) or needs Tony.
