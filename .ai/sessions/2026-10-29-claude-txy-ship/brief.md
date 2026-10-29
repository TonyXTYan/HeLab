# Brief: ship NumPy + Cython, and split CI's tests in two (`agent/txy-ship`)

Coordinator: CoCo, 2026-10-29. Tony's decisions (commit `1e6de51`): Q11.2 NumPy stays the default and
Cython is the optional backend; Q11.3 keep all the backend code; Q16.1 no setup.py extra; Q16.2 (b)
two pytest groups per OS; Q18.1 (commit `376a081`) numba's cache in the temp folder. Items A9.1 and A17.2. One Worker, then a Reviewer.

## Read first

`AGENTS.md`; `.ai/architecture/{converter,release-and-ci,testing}.md`; `.ai/DECISIONS_TODO.md` Q11.2,
Q11.3, Q16.1, Q16.2; `.ai/AI_TODO.md` A9.1, A16.1-A16.3, A17.2; the packaging floor's handoff
(`.ai/sessions/2026-10-29-claude-txy-packaging/handoff.md`) and the bench's results.

## Base and branch

Base `6fcf012` (`dev/v0.0.7`, with Quick Fixes 6's typing-tests-first ordering). Branch `agent/txy-ship`.

## Objective

1. **A9.1: the build ships NumPy, Cython and the reference.** Numba (and llvmlite), MLX (and
   mlx-metal) and Rust (maturin) leave `requirements.txt`, `requirements.lock` (no `--upgrade` of
   anything else; check pandas/scipy no longer pull numba into the frozen app, or add it to
   `excludes`), `HeLab.spec` (hidden imports, the mlx hook, the packaged-app check) and CI's
   required set (`HELAB_REQUIRE_BACKENDS=cython`; the backends job builds only cython). **Their code
   stays** (`helab/convert/backends/{numba_backend,numba_kernels,mlx_gpu,rust}.py`, `native/rust/`,
   their tests, which skip with an explicit reason where the package isn't installed;
   `_MODULES` keeps them so a developer who installs one can use it). `native/build.py` keeps a
   way to build rust for developers (opt-in flag), not in CI. Report the size saved (macOS app).
2. **A17.2: two pytest groups per OS** in CI's Tests job (e.g. a matrix shard, `pytest --splits 2
   --group N` via a small conftest option or `-k`/path split, or xdist `--dist loadgroup` groups:
   your choice, say why), keeping Quick Fixes 6's typing-tests-first ordering in whichever group
   holds them, every test in exactly one group (a test checks the split covers the whole
   collection), coverage uploads merged as before, the release gate needing both groups. No time
   limit raised. Report each group's time per OS.
3. **Q18.1: numba's cache goes in HeLab's temp folder** (for developers trying numba, which no longer
   ships): where the helper and its workers set it (`set_cache_folder`, in `helab/io_ops/convert.py`),
   use the temps folder instead of the cache folder; approved as the one edit outside your paths.
4. Docs proposals: converter.md (what ships, numba's cache), release-and-ci.md (the groups), README
   setup line.

## Rules

No version bump, release, tag or PR. Owned paths: requirements files, `HeLab.spec`,
`.github/workflows/`, `native/build.py`, `native/check_build.py`, `native/pyinstaller-hooks/`,
`tests/conftest.py` (only for the group option), tests about packaging and CI. Not the backends'
code. Strict typing (incl. `--platform win32`); full suite inside and outside the checkout basetemp;
push to see CI (a checkpoint here); the landing needs CI green on 3 OSes by run ID.
