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
| `native/build.py` (new) | Builds the cython kernel in place (through `native/cython/build.py`) and the rust module as an abi3 wheel (maturin), installed with pip or uv into the running Python. It refuses a `RUSTFLAGS` with `target-cpu`. `--ci` also prints rustc/cargo versions, picks the required backends (cython, rust, numba, plus mlx when `mx.metal.is_available()`, which it prints; otherwise it posts a `::notice`), writes `HELAB_REQUIRE_BACKENDS` to `$GITHUB_ENV`, and runs the check. `--out DIR` builds both and saves the kernel (for this Python) and the wheel without installing them; `--ci --prebuilt DIR` installs those instead of building. maturin builds with `--locked` (`native/rust/Cargo.lock`). |
| `native/check_build.py` (new) | Each backend against `reference` on every `tests/data/convert/cases` case × both built-ins (`pipeline.convert_shot` bytes, or the same error). It runs in this Python, or with `--frozen APP` through a packaged app's `convert --watch … --once --output temp --workers 1`: one run per backend and profile, each with its own app, cache and temp folders and its own settings file. Files HeLab leaves waiting (`raw.not_done`) or can't convert are expected to give no TXY. `reference` and `numpy` are always required. A backend that says why it can't run (`unavailable()`, or "Backend 'x' can't run:" from the app) is "unavailable", which passes unless required. A difference or a crash (`unavailable()` raising, any other non-zero exit, a timeout) is "failed", which always fails. In-process, the reference must convert at least half the cases, or every backend's errors would "match" a broken one. It prints each reason and exits 1 on any failure. |
| `native/pyinstaller-hooks/hook-mlx.py` (new) | mlx's submodules, its dylibs and `mlx.metallib` in `mlx/lib`; no headers or CMake files. |
| `HeLab.spec` | `hiddenimports`: every `_MODULES` backend (the reference too), plus each optional package present in the build Python (cython `_kernel`; `helab_convert_rs` and `helab_convert_rs.helab_convert_rs`; `numba`, `numba.core.caching`, `numba_kernels`; `mlx`, `mlx.core`). The first module of each is the one probed, and a missing one is printed and left out, so the app still builds without it. `hookspath` points at the mlx hook. `excludes`: `Cython`, `cython`, `pyximport` (only optional imports in pyarrow's conftest, scipy's test utils and pydantic.v1 would collect them: 5.6 MB). The `datas` list stays a literal, as `test_spec_datas` reads it. |
| `.github/workflows/ci-test.yml` | Two jobs (CoCo's layout, after the macOS test job hit its limit twice). **"Converter backends"** (20 min limit of its own): the full environment, `build.py --ci` (both built, `HELAB_REQUIRE_BACKENDS` set, `check_build.py`), then `pytest tests/test_convert_*.py` with every backend required, so a missing or wrong backend still fails CI. **"Tests"**: the main suite as before the backends shipped. It installs the lock, then uninstalls numba, llvmlite, mlx and mlx-metal; nothing is built, the backend tests skip as before, and `HELAB_REQUIRE_BACKENDS` is unset. No time limit changed. (`build.py --out`/`--prebuilt`, from the artifact version, stay but CI no longer uses them.) |
| `.github/workflows/ci-build.yml` | "Build and check the converter backends" (`build.py --ci`, building in that job: PyInstaller needs them in its venv) before PyInstaller (skipped for a recovery build of a tag from before `native/build.py`). After PyInstaller, "Check every converter backend in the packaged app" (`check_build.py --frozen`, then `du -sh dist/HeLab`). Timeout raised from 15 to 25 min. |
| `tests/conftest.py` | `HELAB_REQUIRE_BACKENDS` (comma-separated). In `pytest_configure`, each named backend must load, or the run stops with a `UsageError` listing the reasons. A `pytest_runtest_makereport` wrapper (`trylast`, so it's inside pytest-rerunfailures') turns a skip whose reason names a required backend (as a word) into a failure. `pytest_configure` adds a `--rerun-except` pattern for those skips, so the failure is final, not rerun 5 times. All of this runs only when the variable is set. |
| `tests/test_convert_required_backends.py` (new) | Tests both halves of the flag (nested pytest runs with this conftest, as `test_left_widgets` does), the name matching, and `check_build` in this Python, including a planted difference and a reference that converts nothing; that a skip-turned failure isn't rerun (a nested `--reruns 2` run, checked to fail without the `--rerun-except` line). |
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
- CI on all three OSes: green on the merged tree (run 40759532405); see "CI" below.

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

**Run 40754482305** (on `7d2bff9`, before merging dev/v0.0.7): all three builds and the
macOS and Ubuntu tests passed. Windows tests failed, but only on helab-core's known failures
(`test_convert_helab.py` ×2, `test_typing.py` ×5 on `io_ops/convert.py:344/346`), which
dev/v0.0.7 `e064a53` fixes.

| Job | Backends step | Tests / PyInstaller | Frozen check | Job |
|---|---|---|---|---|
| macOS tests | 47 s | 10:46 | | 13:14 |
| Ubuntu tests | 33 s | 10:16 | | 12:07 |
| Windows tests | 65 s | 25:38 (failed) | | 28:31 |
| macOS build | 41 s | 3:17 | 21 s | 5:45 |
| Ubuntu build | 52 s | 2:03 | 15 s | 4:34 |
| Windows build | 96 s | 4:28 | 22 s | 8:19 |

- In every job, the backends step built cython and rust and found cython, rust and numba identical
  on all 78. On Windows mlx is "unavailable: MLX needs Apple Silicon (this is win32 AMD64)".
  **On GitHub's macOS arm64 runner `mx.metal.is_available()` is True** (the mlx handoff expected
  False), so mlx is required there too: identical on all 78, in the venv and in the packaged app,
  and its GPU tests run. In the packaged app, all six backends are identical on all three OSes.
- **The Windows test job took 28:31 against its 30 min limit.** About 1 min of that is the
  backends step. The rest is mostly the failing tests' 5 reruns with 5 s delays: the five mypy
  and pyright tests each rerun 5 times. The base commit's failing run took 20:18, and the last
  green dev/v0.0.7 run 24:05. On the merged tree it is 23:24 (below). A~2 (a rust cache) would save
  about 1 min per job if Windows gets tight.
- **RERUNs** on Windows besides the known failures (each passed on its retry; neither in my
  files): `tests/test_convert_helab.py::test_a_killed_helpers_workers_exit` (`assert not
  any(...)` at line 537: a worker still alive just after its helper was killed: helab-core's
  test), and `tests/test_test_isolation.py::test_pytest_imports_the_checkout_it_runs_in_before_any_other`
  (the nested pytest's "ERROR collecting test session" in pathlib's `lstat`; the cause is cut off
  in the summary). Both go to known-issues.

**Run 40759532405** (on `a6a5de4`, dev/v0.0.7 `e064a53` merged): **every job green on all three
OSes, no RERUN anywhere**. Tests: macOS 8708 passed / 8 skipped (4:33, mlx required), Ubuntu 8597 /
119 (7:40), Windows 8570 / 142 (20:13). A skip naming a required backend would have failed, so
no backend test skipped. **The Windows test job took 23:24** (backends step 1:14, tests 20:18),
inside its 30 min limit. Build jobs: macOS 6:28, Windows 8:20, Ubuntu 4:21, each with the
packaged-app check passing for all backends (about 20 s).

**Run 40763808196** (`0e163d1`, the backends in their own job, Side's request): every job green,
no RERUN. The test jobs install the prebuilt backends in 7-8 s (the build had taken 0:28-1:14).
**Windows test job 22:06** (tests 20:01; it was 23:24); Ubuntu 8:56; macOS 11:00. The backends
jobs took 0:50-1:44.

**Run 40765484151** (`e2f3e14`, Puffin's fixes), attempt 1: every build and backends job green,
Ubuntu and Windows tests green with no RERUN. But the **Windows test job took 25:11** (tests
23:09), with the split, and the **macOS test job was cancelled at its 20 min limit**. Its suite
reached 99 % (8677 passed) at 16 min, against 4:33-10:46 in the three earlier runs. The runner was
slow: a 100 s faulthandler dump caught matplotlib still building its font cache
(`font_manager._get_macos_fonts`). Two tests reran before the cut, and their reasons were lost
with the summary: `tests/test_convert_helab.py::test_heartbeats_while_computing_stop_after_the_budget`
(helab-core's) and `tests/test_analysis_gui.py::test_another_library_draws_the_plot_again_without_a_rerun`.
Neither is in my files. Attempt 2 of the macOS job: below.

**Where the time went** (CoCo's ask). Locally (M4 Max, load 13-80, so noisy): mypy strict on
helab 9.9 s with numba and mlx installed vs 9.2 s without, on tests 9.1 vs 8.3; pyright 35 vs 30 s.
The full suite was 2:55 with every backend (8710 tests) vs 3:18 without (8049). The converter
files alone, with every backend required, take 47 s (4220 tests). Nothing here explains a macOS
doubling. On CI, per test file (the gap between a worker's consecutive results), the slow macOS
job used 3,739 worker-seconds against 1,695 in the green `0e163d1` job, which also had every
backend installed and required. The extra time is spread over unrelated files (live plots +246 s,
result lifecycle +176, correlations +176, store identity +113, bose fits +112; numba +113, mlx
+48), about 2.2× each. So it isn't the backend tests or mypy. It is either the runner, or
something that slows every test while the backends are loaded in each of the 4 workers (memory on
the 3-core, 7 GB VM is a candidate; not proved). Earlier green runs varied too: macOS 4:33
(`a6a5de4`) and 9:14 (`0e163d1`) on the same setup. The new layout makes the main test job's
setup exactly what it was before this branch, whatever the cause.

**Run 40774765952** (`d115552`, the main job without the backends): **every job green, no
RERUN**.

| Job | macOS | Ubuntu | Windows |
|---|---|---|---|
| Converter backends (build + check + `test_convert_*`) | 4:50 (tests 1:30, 4220 passed, mlx required) | 2:26 (1:03) | 9:48 (6:52) |
| Tests (main, no backends) | 11:22 (suite 9:40) | 11:07 (9:50) | **27:12 (25:30)** |
| Build (+ packaged-app check) | 6:09 | 3:56 | 8:58 |

The main job now runs exactly dev/v0.0.7's suite setup (8020-8049 tests, as there) plus my 10
tests (12.6 s on Ubuntu). Yet against dev/v0.0.7 `e064a53` (run 40758706117: Windows 19:55, macOS
10:32, Ubuntu 6:50) Windows is +7 min and Ubuntu +4. Per test file, the slowdown is again uniform
over unrelated files (Windows 4,084 → 5,656 worker-seconds, ×1.4; Ubuntu 1,006 → 1,664, ×1.65; same
test counts per file). That points at runner speed, not this branch: no code of mine runs in that
job besides those 10 tests. It is not proved, though: a same-time control (re-running dev's test
jobs beside this branch's) would settle it.

The split saves about 1 min of the Windows test job. The same suite varies by 3-5 min between
runs, so the split alone doesn't keep Windows clear of 30 min, and macOS can now come near 20:
**Q~2**.

Locally after the merge: full suite with every backend required, **8708 passed, 8 skipped, no
RERUN**. `mypy --strict` for helab and tests with `--platform` darwin, win32 and
linux, and `pyright --pythonplatform` Darwin, Windows and Linux: all clean.

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
- **`.ai/architecture/release-and-ci.md`**: `ci-test.yml` has two independent jobs per OS and
  Python. "Converter backends" (20 min) builds and requires every backend (`build.py --ci`) and
  runs `tests/test_convert_*.py`. "Tests" runs the whole suite without the optional backends:
  numba, llvmlite, mlx and mlx-metal are uninstalled after the lock, nothing is built, and their
  tests skip. The build
  job builds its own (`build.py --ci`) before PyInstaller and checks the app after
  (`check_build.py --frozen`); **its timeout is 25 min** (was 15). `HELAB_REQUIRE_BACKENDS` reaches
  later steps **through `$GITHUB_ENV`**, so in the build job it also applies to "Test the older
  tagged commit before rebuilding recovery assets" (the step is skipped, and the variable unset,
  for a tag from before `native/build.py`). Runners need Rust (preinstalled on GitHub's images)
  and a C compiler (MSVC on `windows-latest`). GitHub's macOS arm64 runners have Metal, so mlx is
  required there.
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
- **Q~2** (Tony; Side asked, no limit changed tonight): **CI test-job time limits.** The Windows
  test job ran 22:06, 23:24 and 25:11 on this branch (limit 30, Q2.6), and one macOS test job hit
  its 20 min limit on a slow runner (normally 4:33-11:00). The compiled backends' tests add about
  1 min; building them is no longer in the test job. Options: (a) raise the limits (Windows 40,
  others 30); (b) split the test job into two shards per OS (e.g. the GUI tests and the rest),
  each with today's limit, which costs one more runner per OS; (c) leave them and re-run a job
  that hits the limit. Proposed: (a) now, as it changes nothing else; (b) when the suite grows
  again.
- **Q~1** (Tony; proposed: no): should `setup.py` gain an extra (`pip install -e .[fast]`) for
  numba, or build the extensions during `pip install`? Proposed: no. It would need a compiler
  and Rust on every lab PC, and `native/build.py` already does it for developers and CI.

## Review round 1 (Puffin: no blocker), all fixed

| Point | Fix |
|---|---|
| 1: a non-required backend that fails passes as "unavailable"; a crash counts as unavailable; a frozen app without reference/numpy would pass | `reference` and `numpy` are always required. "unavailable" only when the backend says why (`unavailable()`, or the app's "Backend 'x' can't run:"); `unavailable()` raising, any other exit, or a timeout is "failed" and always fails. In-process, the reference must convert at least half the cases. Checked: an app copy without the cython kernel gives "unavailable" and rc 0 when not required; `--frozen /usr/bin/false` gives "failed" for all six and rc 1. |
| 3: the spec's numba probe was `numba_kernels` (always there) | `numba` is first. |
| 4: maturin `--locked` | Done. |
| 5: conftest's check runs without the variable | Guarded by `if REQUIRED_BACKENDS:`. |
| Reruns of a skip-turned failure | Not rerun: `--rerun-except` (public option) plus a `trylast` wrapper; tested. |
| Stale ci-test.yml comment | Updated (Windows 20-24 min). |
| Docs | release-and-ci.md proposal above: the 25 min build timeout, and `$GITHUB_ENV` reaching the older-tag test step. |

## RERUNs

None in the final run. The first full run's 15 reruns were 3 deterministic failures, fixed above
(not flaky; nothing for known-issues).
