# Brief: TXY converter stage 4, packaging every backend (`agent/txy-packaging`)

Coordinator: CoCo, 2026-10-29 (overnight build; Side approves on Tony's behalf within the
[mandate](../2026-10-29-claude-v0.0.7-overnight/mandate.md)). One Worker, then a Reviewer. Runs
beside `agent/txy-live` and `agent/txy-ui`, all from helab-core landed + docs (01776d6).

## Read first

1. `AGENTS.md` (Versions and releases rules: no version bump, no release, no tag tonight),
   `roadmaps/agent-workflow.md`, `.ai/architecture/release-and-ci.md`, `.ai/architecture/converter.md`.
2. The five backend handoffs (`.ai/sessions/2026-10-29-claude-txy-{numpy,numba,cython,rust,mlx}/handoff.md`):
   their packaging items (hiddenimports for every `_MODULES` backend incl. the reference;
   collect_submodules/data for mlx; numba's cache in a frozen app; Cython on MSVC VS 2022 17.0+,
   never `/arch:AVX2` with an older toolset, `-ffp-contract=off`/no FMA; Rust via maturin-action,
   abi3-py311, no `target-cpu=native` because of the Sandy Bridge lab PC); the bench's results
   (`.ai/sessions/2026-10-29-claude-txy-bench/results.md`).
3. `.ai/DECISIONS_TODO.md` Q9.2; `.ai/AI_TODO.md` A9.1; Side's rule: the compiled backends' tests
   become required in CI.

## Base and branch

Base `01776d6` (helab-core landed). Branch `agent/txy-packaging`.

## Objective

Every backend ships in the build (Q9.2), NumPy alone always works, and CI builds and tests the
compiled ones on all three OSes.

## Scope

1. **Dependencies**: numba, mlx (macOS arm64 only), with platform markers, in `requirements.txt`
   and `requirements.lock` (follow the README's "updating dependencies"; don't `--upgrade`
   anything else; check numba's NumPy pin against the lock). Lazy imports stay: HeLab and the
   tests work with any backend missing.
2. **Compiled extensions in the build**: build the Cython and Rust extensions as part of the
   package build on macOS, Windows and Linux (setup.py / a build step; maturin for Rust),
   without committing binaries.
3. **CI** (`.github/workflows/ci-test.yml`, `ci-build.yml`): build the extensions on all three
   OSes before the tests, so the cython/rust (and numba; mlx where Metal exists, else a clear skip
   with `mx.metal.is_available()` printed) tests run; make a skip of a backend that should be
   there fail CI (an env flag the tests read, e.g. `HELAB_REQUIRE_BACKENDS=cython,rust,numba`).
   Add a CI check that each built kernel equals the reference on `tests/data/convert/`. Watch the
   Windows test job's time (limit 30 min; ~21 min now).
4. **`HeLab.spec`**: hiddenimports for every backend module in `_MODULES` (the reference
   included: the frozen app can't find `helab.convert.backends` otherwise), the compiled
   extensions, mlx's data, numba/llvmlite; the frozen `helab convert --watch` entry works. Build
   locally (`pyinstaller HeLab.spec --clean -y`) and check in the built app that every backend is
   available (or unavailable with the right reason) and converts a synthetic shot identically to
   the reference; report the size each adds.
5. **A9.1 note**: a short note, in your handoff, of what to remove once the default and the
   optional fast backends are settled, with the size each saves.

## Rules

- Owned paths: `setup.py`, `requirements.txt`, `requirements.lock`, `HeLab.spec`, `.github/workflows/`,
  build scripts under `native/`, `tests/conftest.py` only for the backend-requirement flag, new
  tests. No version bump, release, tag or PR. Machine-wide installs: none (packages only in this
  floor's venv).
- Push to see CI (that's a checkpoint here); keep pushes few.
- Everything else as in AGENTS.md: strict typing, the full suite and three type checks, RERUNs
  reported, docs only in your session folder with `Q~`/`A~`/`M~`, report to CoCo.
