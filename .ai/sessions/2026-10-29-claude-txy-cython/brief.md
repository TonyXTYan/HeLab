# Brief: TXY converter stage 2, backend `cython` (`agent/txy-cython`)

Coordinator: CoCo, 2026-10-29 (overnight build; Side approves on Tony's behalf within the
[mandate](../2026-10-29-claude-v0.0.7-overnight/mandate.md)). One Worker. Lens (stage 1's
cross-checker) checks your output on request through CoCo.

## Read first

1. `AGENTS.md`, `roadmaps/agent-workflow.md`.
2. [`roadmaps/txy-converter.md`](../../../roadmaps/txy-converter.md), Stage 2.
3. [`.ai/architecture/converter.md`](../../architecture/converter.md) (the module map, the quirks,
   the backend contract), then stage 1's handoff and notes in
   `.ai/sessions/2026-10-29-claude-txy-reference/` and A10.2 in `.ai/AI_TODO.md`. `helab/convert/`
   is the code; `backends/reference.py` is what you match.

## Base and branch

Base `372f2ac` (stage 1 landed on `dev/v0.0.7`). Branch `agent/txy-cython`.

## Objective

A `cython` backend for `helab/convert/` that is byte-identical to the reference for every
built-in profile, measured for speed, with a short report.

## Backend specifics: Cython (or plain C through a small extension)

- A compiled extension implementing the match loop (Cython with typed memoryviews, `nogil`, or C
  with the CPython/NumPy C API: your choice; say why). Sources under `native/cython/` (or
  `native/c/`), built into the floor venv with a build script there (e.g. `python
  native/cython/build.py` producing the extension inside `helab/convert/backends/`), not through
  `pyproject.toml` (the packaging floor wires builds into CI and `HeLab.spec` later, stage 4).
  The built binary is not committed (add its pattern to a `.gitignore` in your owned folder).
- Release the GIL around the match so `releases_gil` is True; measure threads.
- Compiler: Xcode's clang is installed; no machine-wide installs. `Cython` and `setuptools` only in
  the floor venv. Note what Windows (MSVC) and Linux builds will need, for the packaging floor.

## Must

- Register through stage 1's backend interface (`register_backend` on import **and** one line in
  `_MODULES` in `helab/convert/reconstruct.py`; that line is the only edit to `reconstruct.py`, and
  since five floors add one, a later landing may need you to merge `dev/v0.0.7` and keep every
  line); callers don't change. Import lazily: HeLab and
  the tests must work when `cython` isn't installed (the backend reports itself unavailable,
  and its tests skip with a reason).
- **Byte-identical** to the reference on: every synthetic case in `tests/data/convert/`, both
  built-in profiles, every quirk (phantom row, empty file behaviour, stable sorts, NaN times);
  and on every sample shot through stage 1's checker (`dev/txy/…`), with only the listed
  reference exceptions.
- Parallelism, each measured and each still byte-identical: across shots (processes); threads,
  where the backend releases the GIL; within one shot (cut the pulse stream at gaps longer than
  the match window: say how the cut is chosen and prove it can't change the output, including
  the phantom row and the 36-row search). The generic within-shot split (`split.py`, `timing`'s
  `WITHIN_SHOT`) is the NumPy floor's; other floors measure serial, processes and threads now,
  and within-shot in the final serial timing run; a backend with its own internal parallelism
  (Numba `prange`, Rust threads) may report that too.
- Measures, with stage 1's timing harness: raw MB/s per core and in total; latency per shot
  (small and large shots); reading, reconstruction and writing separately; first-call cost
  (JIT/import); and the size the backend adds to a PyInstaller build (measure on a scratch
  build under `.ai/temp`, or estimate from the wheel and its dependencies, saying which).
  Results in `results.md` in your session folder: one table row per measure, the machine, and
  what was running. These are your timings; the final ones are taken later, serially, on an idle
  machine.
- Packages only in this floor's venv: check `venv/bin/python -c "import sys; print(sys.prefix)"`
  is under the floor, then `uv pip install --python venv/bin/python <pkg>`. List them in your
  session folder and a `requirements-bench.txt` there; never in `requirements.txt` or the lock
  (stage 4's packaging floor does that, Q9.2). No machine-wide installs (Rust is already
  installed via Homebrew).
- Tests: synthetic data and `tests_sample_data/` only, never the sample set. They skip cleanly
  without the package. Strict typing (a `.pyi` stub or typed wrapper for a compiled module).

## Owned paths

`helab/convert/backends/cython*` (module or package), any build files the backend needs
(say which in your notes; nothing in `pyproject.toml` or `HeLab.spec` without asking CoCo),
`tests/test_convert_backend_cython.py`, your session folder
`.ai/sessions/2026-10-29-claude-txy-cython/`. Touch the shared parts of `helab/convert/`
only if the interface truly needs it, and ask CoCo first: five floors share it.

## Rules

- Samples `~/HeLab-samples/txy-v1/` read-only; never the X share or other real data.
- Commits: freely on your branch, with subject and body. Push once, when done (or when CoCo asks).
- Docs only in your session folder; proposed doc changes and provisional items (`Q~1`, `A~1`,
  `M~1`) in `handoff.md`.
- A question the brief doesn't answer: `maestri ask "CoCo" "…"`. A test that keeps failing after a
  cause hunt: write it up, tell CoCo, carry on.

## Done when

- Byte-identical as above; `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`,
  `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests` pass; RERUNs reported.
- `results.md` and `handoff.md` written; branch pushed; `maestri floor status … --state review`;
  report to CoCo with `maestri ask "CoCo" "…"`.
