# Brief: TXY converter stage 2, backend `numpy` (`agent/txy-numpy`)

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

Base `372f2ac` (stage 1 landed on `dev/v0.0.7`). Branch `agent/txy-numpy`.

## Objective

A `numpy` backend for `helab/convert/` that is byte-identical to the reference for every
built-in profile, measured for speed, with a short report.

## Backend specifics: NumPy (the default that must work everywhere)

- Pure NumPy, no compiled code: this is the candidate default backend (NumPy alone always works,
  Q9.2). The match is greedy and order-dependent (used pulses are marked NaN as x1 advances, the
  phantom row depends on `which_row`), so vectorise what doesn't change the order (candidate
  windows, sums, the final T/X/Y and sort) and keep an exact sequential pass where it does; say
  in your notes which parts are vectorised and why the result can't differ.
- **You also own the shared fast I/O and the within-shot split**, used by every backend:
  - fast text I/O: `raw.parse_raw` already has a strict path for uniform `\r\n`/`\n` plain
    `int,int` files (`_parse_strict`), and `txy.format_txy` formats value by value; make both fast
    (NumPy, no per-value Python where avoidable), byte-identical (`%.8g`, `NaN`/`Inf`, `-0`), in
    `raw.py`/`txy.py` or a new `fastio.py`, with tests that the fast path equals the general one
    on every case and probe in `tests/data/convert/`;
  - `helab/convert/split.py` (new) and `timing.py`'s `WITHIN_SHOT`: cut one shot's pulses at gaps
    the match can't cross, run the pieces with any backend in parallel, merge. The constraints
    (A10.2 in `.ai/AI_TODO.md`; `converter.md`, Backends): global `t_zero`, the first-row skip
    only in the first piece, the whole-file `floor(N/4)` preallocation (the phantom row), the
    2023 dead-time cuts (only at gaps over 20,000 bins, or applied before splitting), one final
    stable sort by T. Test that a split conversion equals the whole one on every case (with
    forced small pieces) and on `tests_sample_data/`.
- Owned paths add: `helab/convert/raw.py`, `helab/convert/txy.py`, `helab/convert/fastio.py`,
  `helab/convert/split.py`, `helab/convert/pipeline.py` and `helab/convert/timing.py` (no other
  backend floor touches those).

## Must

- Register through stage 1's backend interface (`register_backend` on import **and** one line in
  `_MODULES` in `helab/convert/reconstruct.py`; that line is the only edit to `reconstruct.py`, and
  since five floors add one, a later landing may need you to merge `dev/v0.0.7` and keep every
  line); callers don't change. Import lazily: HeLab and
  the tests must work when `numpy` isn't installed (the backend reports itself unavailable,
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

`helab/convert/backends/numpy*` (module or package), any build files the backend needs
(say which in your notes; nothing in `pyproject.toml` or `HeLab.spec` without asking CoCo),
`tests/test_convert_backend_numpy.py`, your session folder
`.ai/sessions/2026-10-29-claude-txy-numpy/`. Touch the shared parts of `helab/convert/`
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
