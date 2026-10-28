# Brief: TXY converter stage 2, final timings and recommendation (`agent/txy-bench`)

Coordinator: CoCo, 2026-10-29 (overnight build; Side approves on Tony's behalf within the
[mandate](../2026-10-29-claude-v0.0.7-overnight/mandate.md)). One Worker, then a Reviewer.

## Read first

1. `AGENTS.md`, `roadmaps/agent-workflow.md`, `roadmaps/txy-converter.md` (Stage 2: measures,
   targets, done-when), `.ai/architecture/converter.md`.
2. The five backend handoffs and results: `.ai/sessions/2026-10-29-claude-txy-{numpy,numba,cython,rust,mlx}/`
   (`handoff.md`, `results.md`, `notes.md`; how each is built, its packages, its sizes).
3. `.ai/DECISIONS_TODO.md` Q6.5, Q6.9, Q9.2; `.ai/AI_TODO.md` A9.1, A10.2.

## Base and branch

Base `ed35099` (all five backends landed on `dev/v0.0.7`). Branch `agent/txy-bench` (this floor).

## Objective

The stage's results table and recommendation, from timings taken **serially by you alone on an
idle machine**, with every backend built against the landed code.

## Steps

1. **Build everything into this floor's venv only** (check `venv/bin/python -c "import sys;
   print(sys.prefix)"` is under the floor first; `uv pip install --python venv/bin/python …`):
   numba (the version the numba floor used), mlx, Cython (then `python native/cython/build.py`),
   maturin (then `maturin develop --release` in `native/rust/`). Packages from each floor's
   `requirements-bench.txt` or notes. List exactly what you installed.
2. **Correctness with everything built** (none of the floors, nor CI, has run all backends
   together on the landed code, with the shared fast I/O and the float64 guard):
   `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest` with all extensions built
   (the backend tests must run, not skip: count the skips and say which remain and why);
   `python dev/txy/check_samples.py --backend <b> --positions all` for every backend, both
   built-in profiles where the script allows; any backend-vs-reference comparison the floors
   left (e.g. the rust floor's `compare_samples.py`). Any difference: stop, report to CoCo.
3. **Idle machine.** Before the timing runs, tell CoCo (`maestri ask "CoCo" "ready to time"`) and
   wait for "go": CoCo makes sure every other agent is idle. Then check yourself: `uptime` load
   below ~2, no HeLab GUI running (`pgrep -fl "HeLab|helab"`), and record both in results. If
   the load won't settle, record it and carry on; don't wait more than ~15 min.
4. **Timings**, with stage 1's harness (`dev/txy/time_samples.py`, `helab/convert/timing.py`)
   over all 309 sample shots (read-only `~/HeLab-samples/txy-v1/`), each backend, serially (one
   backend at a time, nothing else running), at least 3 repeats, median and spread:
   - read, reconstruct, write separately; raw MB/s per core and total; latency per shot
     (median and max; small and the 3 largest per set); first call (import/JIT/GPU start);
   - parallelism: serial; processes 1, 2, 4, 8, 12 (and 16 if it helps); threads 1, 4, 8 for
     backends that release the GIL; within-shot (the shared `split.py`) for the large shots;
   - the size each backend adds to a PyInstaller build (from the floors' measurements; note
     which were measured vs estimated);
   - the machine (model, cores, RAM, macOS) and the load at each run.
5. **Results and recommendation** in `results.md` in your session folder: one table per measure,
   then a recommendation: the default backend that works everywhere (NumPy alone always works,
   Q9.2), the optional fast ones and when each is worth it, against the targets (Live: one shot
   every ~30 s; bulk: faster than raw files cross gigabit, ~100 MB/s; Q6.9). Input for A9.1
   (which backends to drop later: size, platforms, speed) and for stage 4's packaging floor (what
   each needs to build in CI). Say plainly where the numbers can't decide something.

## Rules

- Change no code. If a fix is needed, report it to CoCo; it goes to the backend's floor. Your
  commits: your session folder only (`.ai/sessions/2026-10-29-claude-txy-bench/`), plus any
  scratch under `.ai/temp`.
- Samples read-only; never the X share or other real data.
- Proposed doc changes (converter.md, the roadmap's stage 2 status) and provisional items
  (`Q~1`, `A~1`, `M~1`) go in `handoff.md`.
- Push once, when done. Report to CoCo with `maestri ask "CoCo" "…"` when done or blocked.
