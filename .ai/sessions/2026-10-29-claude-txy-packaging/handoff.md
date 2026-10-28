# Handoff: TXY converter stage 4, packaging every backend (Worker Crate, 2026-10-29)

Branch `agent/txy-packaging` from `01776d6`. Brief: [brief.md](brief.md).

## Summary

Every backend ships in the build (Q9.2): numba and mlx (macOS arm64 only) are in the lock, and the
Cython and Rust extensions are built by `native/build.py`. HeLab and the tests still work with
any backend missing; `setup.py`'s `install_requires` is unchanged, so `pip install -e .` needs no
compiler. CI builds both extensions on all three OSes before the tests and before PyInstaller.
`HELAB_REQUIRE_BACKENDS` makes a backend that can't load fail the run. Every backend is checked
byte for byte against the reference, in the venv and inside the packaged app.

Locally (M4 Max, macOS arm64): the packaged app converts the 39 cases × both built-ins
identically to the reference with all six backends.

## What changed

| Path | What |
|---|---|
| `requirements.txt`, `requirements.lock` | `numba`, `mlx; sys_platform == "darwin" and platform_machine == "arm64"`, build tools `Cython`, `maturin`. The lock is refreshed **without** `--upgrade`, so only new pins were added: cython 3.3.0, llvmlite 0.50.0, maturin 1.15.0, mlx and mlx-metal 0.32.4 (marked), numba 0.68.1. NumPy stays 2.5.4 (numba 0.68.1 wants `<2.6`). |
| `native/build.py` (new) | Builds the cython kernel in place (through `native/cython/build.py`) and the rust module as an abi3 wheel (maturin), installed with pip or uv into the running Python. It refuses a `RUSTFLAGS` with `target-cpu`. `--ci` also prints rustc/cargo versions, picks the required backends (cython, rust, numba, plus mlx when `mx.metal.is_available()`, which it prints; otherwise it posts a `::notice`), writes `HELAB_REQUIRE_BACKENDS` to `$GITHUB_ENV`, and runs the check. |
| `native/check_build.py` (new) | Each backend against `reference` on every `tests/data/convert/cases` case × both built-ins (`pipeline.convert_shot` bytes, or the same error). It runs in this Python, or with `--frozen APP` through a packaged app's `convert --watch … --once --output temp --workers 1`: one run per backend and profile, each with its own app, cache and temp folders and its own settings file. Files HeLab leaves waiting (`raw.not_done`) or can't convert are expected to give no TXY. It exits 1 on a difference or when a required backend is unavailable, and prints each unavailable backend's reason. |
| `native/pyinstaller-hooks/hook-mlx.py` (new) | mlx's submodules, its dylibs and `mlx.metallib` in `mlx/lib`; no headers or CMake files. |
| `HeLab.spec` | `hiddenimports`: every `_MODULES` backend (the reference too), plus each optional package present in the build Python (cython `_kernel`; `helab_convert_rs` and `helab_convert_rs.helab_convert_rs`; `numba_kernels`, `numba`, `numba.core.caching`; `mlx`, `mlx.core`). A missing one is printed and left out, so the app still builds without it. `hookspath` points at the mlx hook. `excludes`: `Cython`, `cython`, `pyximport` (only optional imports in pyarrow's conftest, scipy's test utils and pydantic.v1 would collect them: 5.6 MB). The `datas` list stays a literal, as `test_spec_datas` reads it. |
| `.github/workflows/ci-test.yml` | A "Build and check the converter backends" step (`python native/build.py --ci`) before "Run Tests", so the tests run with `HELAB_REQUIRE_BACKENDS` set. |
| `.github/workflows/ci-build.yml` | The same step before PyInstaller (skipped for a recovery build of a tag from before `native/build.py`). After PyInstaller, "Check every converter backend in the packaged app" (`check_build.py --frozen`, then `du -sh dist/HeLab`). Timeout raised from 15 to 25 min. |
| `tests/conftest.py` | `HELAB_REQUIRE_BACKENDS` (comma-separated). In `pytest_configure`, each named backend must load, or the run stops with a `UsageError` listing the reasons. A `pytest_runtest_makereport` wrapper turns a skip whose reason names a required backend (as a word) into a failure. |
| `tests/test_convert_required_backends.py` (new) | Tests both halves of the flag (nested pytest runs with this conftest, as `test_left_widgets` does), the name matching, and `check_build` in this Python, including a planted difference. |
| `tests/test_dependency_snapshot.py` | One line (CoCo approved): a requirement's name is the text before any `;` marker. |

## Checks

- `python native/build.py`: both extensions built (13 s here; cargo is incremental).
- `python native/check_build.py --require cython,rust,numba,mlx`: numpy, cython, mlx, numba and
  rust are each identical on all 78.
- `pyinstaller HeLab.spec --clean -y` (1:47), then `check_build.py --frozen …/HeLab.app/Contents/MacOS/HeLab
  --require cython,rust,numba,mlx`: reference, numpy, cython, mlx, numba and rust are each
  identical on all 78. The frozen numba cache is in `<cache>/numba` (Q11.1); nothing went to
  `~/Library/Caches/numba`. Negative check: a copy of the app without the cython `_kernel` gives
  "cython: unavailable: … the compiled kernel isn't built (No module named
  'helab.convert.backends.cython._kernel') …" and exit 1 when cython is required.
- Full suite, `HELAB_REQUIRE_BACKENDS=cython,rust,numba,mlx pytest -n 4 --reruns 5 --reruns-delay 1
  --basetemp=.ai/temp/pytest`: **8705 passed, 8 skipped, no RERUN** (2:54). The four
  backend test files alone: 793 passed, and the 4 skips left are numba's one-value fields.
  The first full run had 3 deterministic failures (counted as 15 reruns): `test_dependency_snapshot`
  (the marker) and `test_spec_datas` ×2 (`datas` was no longer a literal). Both are fixed above;
  these were not flakes.
- `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`: clean. With `--platform
  win32` / `--pythonplatform Windows`, the only errors are helab-core's known
  `io_ops/convert.py:344/346` (Keel's fix). Linux is clean.
- CI on all three OSes: see "CI" below.

## Sizes (macOS arm64 app, measured from the built `_internal`; zip -9)

| Backend | On disk | Zipped |
|---|---|---|
| mlx (`mlx/`: metallib 214 MB, libmlx 22 MB) | 234 MB | 78 MB |
| numba (`numba/` 1.1 MB + `llvmlite/` 126 MB) | 127 MB | 40 MB |
| rust (`helab_convert_rs/`) | 0.48 MB | 0.23 MB |
| cython (`_kernel.so`) | 0.27 MB | 0.09 MB |
| numpy, reference | ~0 (Python modules in the PYZ) | |

The whole `_internal` is 1,137 MB, and `HeLab.app` zips (ditto, as CI does) to 416 MB. The base
commit's spec, built in the same venv, gives 907 MB and 341 MB. That build already includes
numba, llvmlite and Cython, because pandas and scipy import them optionally once they are
installed.

## A9.1 note: what to remove once the backends are settled

- **mlx**: drop the `mlx` line from `requirements.txt` and re-lock (mlx and mlx-metal go), drop
  `"mlx"` from `HeLab.spec`'s `optional` and `native/pyinstaller-hooks/hook-mlx.py`, and drop the
  mlx branch in `native/build.py`'s `ci_required`. This saves **234 MB on disk and 78 MB zipped**
  (macOS arm64 only). Keep `_MODULES["mlx"]` or remove the backend module, as decided.
- **numba**: drop `numba` from `requirements.txt` and re-lock (numba and llvmlite go), drop it
  from the spec's `optional` and from `ci_required`. This saves **127 MB on disk and 40 MB
  zipped** on every OS. **Removing it from the spec alone saves nothing**: once numba is installed
  in the build venv, pandas' and scipy's optional imports collect it anyway. If it stays in the
  lock for development, add `"numba", "llvmlite"` to the spec's `excludes` instead.
- **cython or rust** (if only one is kept): for cython, drop `Cython` from `requirements.txt`, the
  `cython` target in `native/build.py` and the spec entry (0.27 MB / 0.09 MB). For rust, drop
  `maturin` likewise (0.48 MB / 0.23 MB). Their sizes are negligible. The real costs are CI time
  (cargo's LTO build on each job) and, for cython, one build per Python minor version and MSVC on
  Windows.

## CI

(Filled in after the run: see the end of this file.)

## Proposed doc changes (for the Coordinator)

- **`.ai/architecture/converter.md`**:
  - "Frozen builds" paragraph: replace with: "`HeLab.spec` lists every `_MODULES` backend in
    `hiddenimports` (the reference too), plus each optional package present in the build Python
    (the cython `_kernel`, `helab_convert_rs`, numba, mlx); a missing one is left out with a
    printed line, and the app has that backend unavailable with the reason. mlx's libraries and
    `mlx.metallib` come through `native/pyinstaller-hooks/hook-mlx.py` (no headers); Cython is
    excluded. `python native/build.py` builds the cython kernel in place and installs the rust
    module's abi3 wheel into the running Python (neither is part of `pip install -e .`);
    `native/check_build.py` checks every backend against the reference on `tests/data/convert/`,
    in this Python or (`--frozen APP`) through a packaged app's `convert --once`."
  - Backends, "Optional and lazy": add "CI sets `HELAB_REQUIRE_BACKENDS` (cython, rust, numba; mlx
    where `mx.metal.is_available()`), so there a backend that can't load stops the run and a skip
    naming one fails (`tests/conftest.py`)."
  - Module table, `backends/cython` and `backends/rust`: "built by `native/build.py`".
- **`.ai/architecture/release-and-ci.md`**: the test job's new step (`native/build.py --ci`, before
  the tests); the build job's two steps (the build before PyInstaller, `check_build.py --frozen`
  after) and its 25 min timeout. Runners need Rust (preinstalled on GitHub's images) and a C
  compiler (MSVC on `windows-latest`).
- **`.ai/architecture/testing.md`**: `HELAB_REQUIRE_BACKENDS` under the harness seams.
- **README "Setup (any machine)"**: an optional step after `uv pip install …`:
  "`python native/build.py` builds the converter's compiled backends (needs a C compiler and
  Rust; HeLab works without them)." Also note that a release build (`pyinstaller HeLab.spec`)
  ships them only if built first.
- **AGENTS.md** "Setup and commands": the same one line beside `pyinstaller HeLab.spec`.
- **`roadmaps/txy-converter.md`**, stage 4: packaging done; the sizes above.

## Provisional items

- **A~1** (A9.1 input): above. Note especially that numba must leave the lock, or be added to
  `excludes`, to save its 127 MB.
- **A~2** (CI time): every test and build job compiles the rust crate from cold (LTO fat,
  `codegen-units = 1`). If CI shows that is slow (Windows' test job is close to its limit), add
  `Swatinem/rust-cache@v2` with `workspaces: native/rust` to both jobs, or build the wheel once
  per OS in a job of its own and pass it on as an artifact. Today's figures are in "CI".
- **A~3**: the compatibility jobs (3.11, 3.12, 3.14, unpinned) also build and require cython, rust
  and numba. If numba has no wheel for a new Python, that job fails at `pip install` (they are
  `experimental`, so this doesn't block). Make numba conditional there if it does.
- **M~1** (Tony, lab Windows PC, Sandy Bridge): run the CI Windows build's
  `HeLab.exe convert --watch <copy of a run> --once --backend rust` and `--backend cython`, and
  check they load (no AVX2 instructions: the rust crate has no `target-cpu`, and cython builds with
  `/O2 /fp:precise`, without `/arch:AVX2`). This is the rust handoff's M~1, now on a packaged build.
- **M~2** (Tony): in a release build's `HeLab.app`, check that macOS signing and Gatekeeper accept
  the new `.so` and `.dylib` files (`helab_convert_rs.abi3.so`, the cython `_kernel`, libmlx,
  libllvmlite).
- **Q~1** (Tony; proposed: no): should `setup.py` gain an extra (`pip install -e .[fast]`) for
  numba, or build the extensions during `pip install`? Proposed: no. It would need a compiler
  and Rust on every lab PC, and `native/build.py` already does it for developers and CI.

## RERUNs

None in the final run. The first full run's 15 reruns were 3 deterministic failures, fixed above
(not flaky; nothing for known-issues).
