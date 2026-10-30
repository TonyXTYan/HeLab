# Handoff: TXY ship (`agent/txy-ship`, Worker Claude Opus 5.5)

Base `6fcf012` (dev/v0.0.7). Items A9.1, A17.2, Q18.1 (and A16.3 on the way). Brief:
[brief.md](brief.md); design notes: [notes.md](notes.md).

## Summary

- **A9.1: the build ships NumPy, Cython and the reference.** numba (+llvmlite), mlx (+mlx-metal)
  and maturin left `requirements.txt` and the lock (re-locked **without** `--upgrade`: the diff is
  only those five pins removed; NumPy stays 2.5.4). `HeLab.spec` hidden-imports every `_MODULES`
  backend module (so the app names the unshipped ones unavailable, with the reason) plus cython's
  `_kernel` when built, and **excludes** `numba`, `llvmlite`, `mlx`, `helab_convert_rs`, so a build
  Python that still has them (a developer's venv: pandas and scipy import numba optionally) never
  packs them. The mlx hook (`native/pyinstaller-hooks/hook-mlx.py`) and `hookspath` are gone.
  `native/build.py` builds cython by default and in `--ci` (`HELAB_REQUIRE_BACKENDS=cython`); rust
  is opt-in (`--only rust`, with maturin installed by hand: a clear message if it isn't). CI's
  backends job builds and requires cython only. The backends' code and tests are untouched (Q11.3).
- **Size saved (macOS arm64, built here in the same venv, base spec `6fcf012` vs this branch, both
  with the cython kernel):** `HeLab.app` **1,149 → 792 MB (−357 MB)**, zipped with ditto as CI does
  **416 → 294 MB (−122 MB)**; `_internal` 1,110 → 757 MB (mlx 229 + llvmlite 124 + numba 2).
- **A17.2: two pytest groups per OS.** `tests/conftest.py`: `--test-group N/M`; a test's group is
  `crc32(node ID) % M + 1` (same on every OS, worker and run, nothing recorded), the slow-first
  tests (`test_typing.py`) dealt out in turn, then run first in their group as before. Why this
  over a path split, `loadgroup` or pytest-split: [notes.md](notes.md). `ci-test.yml`'s Tests job
  is a matrix `group: ['1/2', '2/2']` ("Tests (1/2)", "Tests (2/2)"), fail-fast off; the release
  gate's `needs.required-tests.result` fails if any group on any OS fails. Coverage: each macOS
  group uploads, Codecov merges (no `codecov.yml`). No time limit changed. `main` has no branch
  protection or rulesets, so no required-check names to update.
- **Q18.1:** the helper's numba cache folder is `request["temps"]/numba` (HeLab's temp folder), not
  beside the cache store (`helab/io_ops/convert.py`, the `if backend == "numba"` block only; its
  test renamed `test_the_numba_backends_cache_folder_is_in_the_temp_folder`).
- **A16.3 done:** `native/build.py`'s `--out`/`--prebuilt` (unused since the backends job) dropped,
  with the docstring that described them.

## Commits

- `3c3aec1` brief; `874fd2b` the change; notes; this handoff.

## Checks

- Full suite, `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: **8481 passed,
  353 skipped, no RERUN** (2:13; cython not yet built).
- Each group alone (same flags): `--test-group 1/2` **4225 passed, 170 skipped, 1 RERUN** (1:20);
  `2/2` **4256 passed, 183 skipped**, no RERUN (0:58). 4395 + 4439 = 8834 = the full run's tests.
  Worker-time from the full run's JUnit: 235 s vs 226 s (51/49).
  - **RERUN** `tests/test_gui_responsiveness.py::test_timeout_retry_releases_dead_helper_slot_while_artifact_reader_is_blocked[2]`,
    rerun reason: `pytestqt.exceptions.TimeoutError: waitUntil timed out in 3000 milliseconds`
    (`tests/test_gui_responsiveness.py:292`); passed on rerun. IOService timing, nothing this branch
    touches; not in known-issues yet (proposed below).
- Full suite with the basetemp outside the checkout (scratch folder, a path with a space), after
  building cython: **8630 passed, 204 skipped, no RERUN** (2:04).
- `python native/build.py --ci` here: reference, numpy, cython (and the locally installed mlx,
  numba) identical on all 78; rust unavailable. Backends job's test set with
  `HELAB_REQUIRE_BACKENDS=cython`: 976 passed, 200 skipped.
- `pyinstaller HeLab.spec` in this venv **with numba and mlx installed**, then
  `check_build.py --frozen … --require cython`: reference, numpy, cython identical on all 78;
  mlx, numba, rust unavailable with the reason ("numba can't be imported (ModuleNotFoundError…)"),
  i.e. the excludes hold. No numba/llvmlite/mlx/helab_convert_rs folder in `_internal`.
- Types: `mypy helab/ --strict`, `mypy tests --strict` (also with `--platform win32`),
  `pyright helab tests` (also `--pythonplatform Windows`): clean; `native/build.py` and
  `native/check_build.py` clean under `mypy --strict` and pyright too (not in the suite's scope).
- CI: run **40803552596** (`888b5bc`): green on 3 OSes, 2 RERUNs on Windows; see "CI" below.

## CI

**Run 40803552596** (`888b5bc`, this branch's code + notes): **every required job green**;
compatibility jobs skipped (push), release skipped. **2 RERUNs, both on Windows, one per group**
(below). Job time (pytest step) per OS:

| Job | macOS | Ubuntu | Windows |
|---|---|---|---|
| Tests (1/2) | 5:21 (4:09; 4072 passed, 322 skipped) | 3:53 (2:56; 4069 / 324) | 12:44 (11:02; 4059 / 333, 1 RERUN) |
| Tests (2/2) | 6:33 (4:52; 4093 / 347) | 6:26 (5:09; 4093 / 347) | 11:56 (10:02; 4077 / 361, 1 RERUN) |
| Converter backends (cython) | 1:59 (0:20; 660 / 516) | 1:54 (0:30) | 3:13 (1:20) |
| Build (+ packaged-app check) | 4:00 | 2:18 | 5:53 |

Against the packaging floor's runs (one Tests job: Windows 22-27 min, macOS 9-11, Ubuntu 7-11),
the longest job per OS is now Windows 12:44 (limit 30), macOS 6:33 and Ubuntu 6:26 (limits 20).
Ubuntu's two groups differ by 2:13 in the step on this one run, macOS by 0:43, Windows by 1:00;
the tests split 51/49 by worker time locally, so the gap is runner variance more than the split
(one run; watch a few). The backends job is faster than before (no rust compile, no numba/mlx).

RERUNs (quoted from "rerun reasons"):
- Windows Tests (1/2): `tests/test_gui_responsiveness.py::test_timeout_retry_releases_dead_helper_slot_while_artifact_reader_is_blocked[2]`:
  `pytestqt.exceptions.TimeoutError: waitUntil timed out in 3000 milliseconds`,
  `tests\test_gui_responsiveness.py:292` (the `finally`'s wait for the killed fake helpers to
  exit after `service.shutdown()`). The same test reran locally (macOS, `--test-group 1/2`). Passed
  on rerun both times.
- Windows Tests (2/2): `tests/test_plot_backends.py::test_2d_plots_draw_with_every_library[values0-Plotly-CountsPerShot]`:
  `worker 'gw3' crashed while running …` (no traceback; a Plotly/QtWebEngine test). Passed on rerun.

## Overlap with the followups floor (Quill)

- `helab/io_ops/convert.py`: mine is only the numba block in `convert_folder`; Quill changes file
  names and `.partial` patterns. `tests/test_convert_helab.py`: mine is the numba-folder test only.
- `native/check_build.py`: Quill changed the frozen check's glob for HeLab's TXY name (`26a2ade`);
  mine changed the docstring, the timeout comment and removed `metal_line`. Keep Quill's glob line.
  Note: this branch's frozen check still uses the old `d_txy_helab_<N>.txy` glob, which is right
  for this branch's helper.

## Proposed doc changes (for the Coordinator)

- **`.ai/architecture/converter.md`**
  - "Optional and lazy" bullet: "CI's "Converter backends" job sets `HELAB_REQUIRE_BACKENDS=cython`
    (the compiled backend that ships, Q11.2), so there a cython kernel that can't load stops the run
    and a skip naming it fails (`tests/conftest.py`). numba, mlx and rust aren't installed in CI:
    their tests skip with the reason."
  - "Frozen builds" paragraph, replace its middle: "`HeLab.spec` lists every `_MODULES` backend in
    `hiddenimports` (the reference too…), so the app names the unshipped ones unavailable with the
    reason, plus cython's `_kernel` when built (a missing one is left out with a printed line).
    **What ships (A9.1, Q11.2): numpy (the default), cython and the reference.** numba, llvmlite,
    mlx and `helab_convert_rs` are in `excludes` (`UNSHIPPED_BACKEND_PACKAGES`), so even a build
    Python that has them packs none (pandas and scipy import numba optionally); their code stays
    (Q11.3) for a developer who installs one. Size saved on macOS arm64: 357 MB on disk, 122 MB
    zipped. Cython is excluded; the built-in profiles are datas. … `python native/build.py` builds
    the cython kernel in place; `--only rust` builds and installs rust's abi3 wheel (maturin
    installed by hand; never in CI)." Drop the sentence on the mlx hook.
  - numba's cache: "The helper sets numba's cache folder to HeLab's temp folder
    (`<temps>/numba`, Q18.1; numba ignores `NUMBA_CACHE_DIR` when frozen)", replacing "under
    `cache_dir()`, Q11.1" (line ~142) and the base rule at ~227 if it mentions numba. The bullet
    "Numba's cache needs no restart after a cache move" (~310) becomes moot: drop it or say the
    temp folder doesn't move with the cache.
  - Last sentence of that paragraph: "`test_typing` and `test_headless_imports` run in CI only
    without numba and mlx installed" still holds (and now locally too after a fresh venv).
  - Backend table rows for numba, rust, mlx: add "(not shipped, A9.1)".
- **`.ai/architecture/release-and-ci.md`**, the `ci-test.yml` sentences: "`ci-test.yml` has two
  jobs per OS and Python: "Converter backends" (20 min) builds and requires cython
  (`native/build.py --ci`, `HELAB_REQUIRE_BACKENDS=cython`) and runs the converter tests that use a
  backend; "Tests" runs the whole suite **in two groups, each a job of its own ("Tests (1/2)",
  "Tests (2/2)", Q16.2)**: `pytest --test-group N/2` (`tests/conftest.py`: a crc32 of each test's
  node ID, the slow-first tests dealt out in turn; `tests/test_test_groups.py` checks every test is
  in exactly one). The caller's result, which the release gate needs, fails if either group does;
  each macOS group uploads coverage and Codecov merges them. The Tests job installs the lock
  without Cython (and fails if a backend package is present)…" Replace "Runners need Rust and a C
  compiler" with "Runners need a C compiler (MSVC on `windows-latest`)", and drop "GitHub's macOS
  arm64 runners have Metal, so mlx is required there". "Test-job times (… Q16.2)": replace with
  this run's group times.
- **`.ai/architecture/testing.md`**, after the slow-first paragraph: "`--test-group N/M` runs one
  group of the suite (CI: two per OS). A test's group is `zlib.crc32(nodeid) % M + 1`, and the
  `SLOW_FIRST_MODULES` tests are dealt out in turn; the slow-first order then applies inside the
  group. `config.stash[ALL_TESTS]` keeps the whole collection, which `tests/test_test_groups.py`
  checks splits once."
- **`README.md`** setup: `python native/build.py          # optional: the converter's compiled
  backend, cython (needs a C compiler; HeLab works without it)`, and "A release build (`pyinstaller
  HeLab.spec`) ships cython's kernel only if `native/build.py` ran first; numba, mlx and rust never
  ship (their code stays for developers: install the package, or maturin and Rust for
  `native/build.py --only rust`)."
- **`AGENTS.md`** command line: `python native/build.py   # optional: the cython converter backend
  (C compiler)`.
- **`native/` docstring outside my paths**: `helab/convert/backends/numba_backend.py`'s module
  docstring says "HeLab's helper passes one under `cache_dir()`": now HeLab's temp folder (Q18.1).
  rust's unavailable message says "build it with `maturin develop --release` in native/rust";
  `python native/build.py --only rust` is the documented way now. Both are backend code (not my
  paths): an A-item.

## Follow-ups (provisional IDs)

- **A~1** Fix the two backend strings above (numba_backend docstring; rust's unavailable hint).
- **A~2** known-issues, two flaky tests (neither listed yet; causes not looked into, nothing this
  branch touches):
  - `test_gui_responsiveness.py::test_timeout_retry_releases_dead_helper_slot_while_artifact_reader_is_blocked[2]`:
    reran locally (macOS) and on Windows CI run 40803552596, both `waitUntil timed out in 3000
    milliseconds` at line 292, the `finally`'s wait for the killed fake helpers (`python -c
    "time.sleep(60)"`) to exit after `service.shutdown()`. A candidate: that 3 s under load.
  - `test_plot_backends.py::test_2d_plots_draw_with_every_library[values0-Plotly-CountsPerShot]`:
    worker crashed on Windows CI run 40803552596 (no traceback; look for a faulthandler dump).
- **A~3** A16.1 (rust cache in CI) and A16.2 (compat jobs require numba) are moot now: rust and
  numba left CI. Close both.
- **A~4** Developer venvs (Ground's, floors') still have numba, llvmlite, mlx, mlx-metal and
  maturin: `uv pip install -r requirements.lock` never removes. Harmless for builds (excluded) and
  tests (they run where installed), but `uv pip sync requirements.lock` then `pip install -e .`
  gives the shipped set.
- **M~1** None new: the release smoke pass covers the app; the size drop shows in the next release
  zip (macOS ≈ 294 MB).

## Questions for Tony

None.
