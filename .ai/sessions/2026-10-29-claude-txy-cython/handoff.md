# Handoff: TXY converter stage 2, backend `cython` (Worker Anvil, 2026-10-29)

Branch `agent/txy-cython` from `372f2ac`. Brief: [brief.md](brief.md). Detail: [notes.md](notes.md)
(why Cython, exactness, the within-shot proof, builds on other platforms). Timings:
[results.md](results.md).

## What was built

- **`native/cython/_kernel.pyx`**: `backends/reference.py` loop for loop in Cython, with the same
  MATLAB line numbers. `prepare` does the stable NaN-last sort, time zero and the dead-time cut;
  `match` runs the 4-corner loop over a row range; `assemble` drops NaN T, scales and does the
  final stable sort. Each releases the GIL. It uses typed memoryviews and no NumPy C API, and
  links only `libSystem`.
- **`native/cython/build.py`**: `python native/cython/build.py [--force]` cythonizes the kernel
  and builds it in place as `helab/convert/backends/cython/_kernel<EXT_SUFFIX>`, which is
  gitignored, as are the intermediates in `native/cython/build/`. It passes
  `-ffp-contract=off -fno-fast-math` (`/fp:precise` on MSVC) and compiles in the source's
  SHA-256. Nothing is in `pyproject.toml`, `setup.py` or `HeLab.spec`.
- **`helab/convert/backends/cython/`** (`__init__.py`, `_kernel.pyi`, `.gitignore`): registers
  `cython` (`releases_gil=True`) and imports the kernel lazily under a lock. When the kernel
  isn't built, or is older than its source in this checkout, `unavailable()` says why, and
  likewise for a corner channel that isn't exactly a double. It turns the profile into the
  kernel's numbers. `reconstruct_cython(pulses, profile, threads=k)` cuts one shot at gaps
  longer than `search_window` and matches the pieces in threads; the proof is in the module
  docstring and notes.md.
- **`helab/convert/reconstruct.py`**: one `_MODULES` line, the only change to shared code.
- **`tests/test_convert_backend_cython.py`** (153 tests). The tests that run the kernel skip
  with the reason when it isn't built. The rest run everywhere: registration, HeLab without the
  kernel, the offsets, the cuts and the import purity check.

Packages (floor venv only): `Cython==3.3.0`, build time only; `setuptools` was already there.
[requirements-bench.txt](requirements-bench.txt).

## Results

- **Byte-identical**: `check_samples.py --backend cython --positions all` gives 303 identical plus
  the 6 proved exceptions, the same as the reference. Against the reference on all 309 shots ×
  both profiles × 1–64 threads: 3,090 conversions, 0 differ. Also identical on every case and
  variant (vs MATLAB too), the lab pairs, and 200 random shots × 7 profiles.
- **Speed** (shared machine, load 7–10): reconstruction runs at **801 MB/s per core** in the
  harness, against the reference's 13.5 (59×). The largest shot takes 14.9 ms against 420. The
  total per core is 46 MB/s, because the shared reader (71 MB/s) and writer (153) are now 94 %
  of the time. Across shots, 12 processes give 359 MB/s wall. Threads give only 49, since the
  Python reader and writer hold the GIL; the kernel alone scales 8.8× on 12 threads. Within one
  shot, only large shots gain (1.27× at 4 threads). First call: 3.2 ms to import, no warm-up.
  Size: about 257 kB, estimated from the binary.
- **Checks**: full suite `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`:
  **6232 passed, 4 skipped, no RERUN** (2:45, load ~8; the 4 skips aren't this floor's). With the
  kernel moved aside, the converter tests give 112 passed and 148 skipped, each with the reason (as CI
  without a build step will). `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`:
  clean.

## Found on the way

- A thread race in my first lazy loader, caught by the harness's `threads` mode: workers
  starting together saw no kernel (`can't run: None`). It is fixed and has a test that fails on
  the old code. Every other backend that loads lazily has the same trap.
- `from package import _kernel` returns a package global of that name rather than the submodule.
  The cache is named `_module`.

## Proposed doc changes (for the Coordinator)

- **`.ai/architecture/converter.md`**, module table: add a `backends/cython` row. "The reference's
  loops compiled with Cython (`native/cython/_kernel.pyx`, built by `native/cython/build.py`
  into the package, never committed); the GIL released; unavailable until built or when stale
  (the source's SHA-256 compiled in); `reconstruct_cython(…, threads=k)` splits within a shot."
- **converter.md**, Backends: a compiled backend's build must turn off FMA contraction and
  fast-math (`-ffp-contract=off`, `/fp:precise`), or the last bits of T/X/Y can change on arm64
  and with GCC. A lazy loader must be thread-safe (the harness's thread pool makes the first
  call from every worker at once).
- **converter.md**, Backends (or `split.py`'s docs, if the NumPy floor lands its generic split):
  the within-shot cut used here is on the **sorted, dead-time-cut** rows at
  `t[k] − t[k−1] > search_window`, with the phantom row's report folded over the pieces. The
  proof is in notes.md, "Within one shot".
- **AGENTS.md**: nothing new beyond the converter invariant already there. Optionally add
  `native/` to the code map: "`native/` | compiled converter backends' sources and build
  scripts (stage 2) | converter.md".
- **roadmaps/txy-converter.md**, Stage 2: cython done (results.md). The finding for the
  recommendation is that after a compiled backend, reading and writing are the bottleneck.
- **`tests/test_headless_imports.py`**: add `"backends.cython"` to the `helab.convert` names in
  `PURE`. My test checks the same in a subprocess, since the file isn't mine to edit.
- **known-issues**: nothing new. There was no RERUN locally; CI's first run on this branch will
  skip the kernel tests, since CI has no build step yet.

## Provisional items

- **A~1** (stage 4, packaging floor): wire the cython build into CI and `HeLab.spec`. Install
  Cython and setuptools at build time, run `python native/cython/build.py` before the tests (or
  the kernel tests skip, as they do in CI now), add
  `hiddenimports=["helab.convert.backends.cython", "helab.convert.backends.cython._kernel"]`
  (importlib-loaded modules aren't found by PyInstaller's analysis, which goes for every
  `_MODULES` backend), build one binary per Python minor version, and use `ARCHFLAGS` for
  universal2. Windows needs the MSVC Build Tools (VS 2022), never `/fp:fast` or `/fp:contract`;
  Linux needs GCC or clang with the Python headers and `-ffp-contract=off` (notes.md, "Building
  on other platforms").
- **A~2** (stage 2, whichever floor owns fast I/O): reading (`parse_raw`, 71 MB/s) and writing
  (`format_txy`, 153 MB/s) now bound every compiled backend at about 46 MB/s per core, and they
  hold the GIL, so threads don't help. A GIL-free strict-format reader and `%.8g` writer would
  lift both. That is the NumPy floor's remit; a Cython one could sit beside this kernel if CoCo
  wants it. It must give the same bytes as `format_txy`, including `NaN`, `Inf`, `-0` and
  platform `printf` differences, which is a check MSVC especially needs.
- **Q~1** (for Tony, stage 2 recommendation): Cython is the cheapest compiled option to ship. It
  adds about 257 kB, has no runtime dependency and no JIT warm-up (3 ms to load), and needs a C
  compiler only at build time. It is byte-identical and about 60× the reference. Should it be a
  default candidate beside the NumPy one, given its per-Python-version, per-platform build?
  Proposed: yes, if stage 4's CI builds it on all three OSes; otherwise an optional fast path.
- **M~1** (final timings): run `bench/run_timings.sh` and `bench/within_shot.py` serially on the
  idle machine. Today's numbers are taken with four other floors running.
