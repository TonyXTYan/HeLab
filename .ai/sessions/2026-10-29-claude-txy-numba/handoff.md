# Handoff: TXY converter stage 2, backend numba (Worker, 2026-10-29)

Branch `agent/txy-numba` from `372f2ac`. Brief: [brief.md](brief.md). Design, proofs and the
frozen-app findings: [notes.md](notes.md). Measurements: [results.md](results.md). Scripts:
[`compare_samples.py`](compare_samples.py), [`bench_numba.py`](bench_numba.py). Packages:
[`requirements-bench.txt`](requirements-bench.txt) (numba 0.68.1, llvmlite 0.50.0; floor venv only).

## Summary

A `numba` backend, **byte-identical to the reference** on the 39 cases × 2 built-ins (against
MATLAB's own output), the lab pairs, every profile field perturbed, 40 random pulse streams with
NaN/±Inf/−0/repeated times, and **all 309 sample shots under both built-ins** (checker: 303
identical + the 6 listed exceptions proved again with numba, 0 differ; numba vs reference: 0
differences, whole and in 2–64 pieces).

**Speed** (M4 Max at load 10–14, indicative): reconstruction **746 MB/s per core** over all shots
(1,430 MB/s on the large ones), **63× the reference**, and it holds no GIL (threads scale it about
linearly). The whole pipeline is then set by stage 1's Python reader (70 MB/s) and writer
(154 MB/s): **43.5 MB/s serial, 133 MB/s with 4 processes, 187 with 12**; threads don't help the
pipeline until reading and writing release the GIL. Latency per shot: median 10 ms small, 29 ms
large. Within one shot: ≤ 1.5× (the sort stays serial). **First call:** 1.5 s compile once per
machine and build, then 0.1 s cache load + 0.1 s `import numba` per process. **Build size:**
+145 MB on disk, +52 MB zipped (llvmlite's 126 MB LLVM library).

## What was built

| File | What |
|---|---|
| `helab/convert/backends/numba_backend.py` | Registers `numba` (`releases_gil=True`); `set_cache_folder` (the caller's seam for the cache folder); imports numba only when asked (`unavailable` gives the ImportError's text); `reconstruct_numba` (registered), `reconstruct_numba_pieces` (within-shot: serial, threads, prange), `piece_bounds`. Sorts with NumPy's `argsort(kind="stable")`. |
| `helab/convert/backends/numba_kernels.py` | `@njit(cache=True, nogil=True)` loops (`prepare`, `choose_bounds`, `match`, `finish`, `convert`, `match_parallel` with prange), the reference's loops with MATLAB line numbers. numba via `importlib` and a typed wrapper: mypy/pyright check it as plain typed Python, no stub, with or without numba. Caches in the folder given to `set_cache_folder` (a locator of its own, first in numba's list, for this module's functions only), else where numba chooses; falls back to `cache=False` when the folder can't be written. |
| `helab/convert/reconstruct.py` | One `_MODULES` entry: `"numba": "helab.convert.backends.numba_backend"` (merging `dev/v0.0.7` later: keep every floor's entry). |
| `tests/test_convert_backend_numba.py` | 211 tests (see notes.md); skip with the reason when numba can't be imported, except the two that check HeLab without numba. |

Two changes of form from the reference, proved in notes.md and tested: the MATLAB output matrix
is replaced by hits in order plus the **phantom row rebuilt at the end** (the only row past the
last hit ever written is the next one, by a failed x pair after it); and the match can run over
**pieces cut where two consecutive finite times are more than `search_window` apart** (rows
across such a gap are always skipped by the window test; NaN rows never match or get marked;
`t_zero`, the sort, the 2023 dead-time cut, the first-row skip, `floor(N/4)` and the final sort
stay global). Greedy matching can't be split further (an x1's match depends on pulses earlier x1
rows used).

## Checks

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest` (numba installed, at load
  ~10 from the other floors): latest **6292 passed, 8 skipped, no RERUN** (after Kite's fixes); then 6290; after the cache seam 6286; at the
  pushed `7ef5935` 6284 passed; earlier 6282; no RERUN in any run. The 8 skips: 4 in my file and 2 in
  `test_convert_profile.py` are the single-value fields `x2_handling`/`y_handling`; 2 predate this floor.
- `mypy helab/ --strict` (175 files), `mypy tests --strict` (145), `pyright helab tests`: clean.
- With numba blocked (`sys.modules["numba"] = None`): the converter tests pass and the numba
  ones skip with "the numba backend can't run here: numba can't be imported (…)".
- Scratch frozen build (`.ai/temp/pyi-numba/`): runs, identical bytes, cache in the user-wide
  folder; read-only cache folder → uncached fallback works; after the seam, with
  `set_cache_folder` launched from a neutral folder: every cache file in the given folder, none in
  numba's, compile 1.3 s then load 0.07 s, identical bytes.

**Without numba, typing (MLX review's check):** `pyright helab tests` with a temporary config
whose venv is Ground's (no numba; `.ai/temp/pyright-ground/pyrightconfig.json`, the floor's root
and `tests/` in `extraPaths` so the floor's code is what's checked): **0 errors** over 318 files;
the same config flags a planted `import numba` (`reportMissingImports`), so the check can see the
problem. numba is reached only through `importlib`. mypy can't fail this way (`mypy.ini`:
`ignore_missing_imports = True`); `mypy --strict --python-executable` Ground's Python: clean.

**Errors while numba loads** (Rust review's gap): `import_problem` catches any `Exception`, not
only `ImportError`, so `unavailable()` and `available_backends()` never raise; tested with a planted
`numba` package raising `RuntimeError`, `ValueError` and `OSError`. If this numba's private cache
names change, the kernels compile without a cache instead of failing at import (tested by deleting
one).

## Proposed doc changes (for the Coordinator)

- **`.ai/architecture/converter.md`**, module table: add `backends/numba_backend` (registers
  `numba`, lazy numba import, `releases_gil`, pieces) and `backends/numba_kernels` (njit loops,
  imported only with numba; `cached`). Under **Backends**: "A backend needn't build MATLAB's
  output matrix: the phantom row is the row after the last hit, written by the last x pair with no
  y after it, surviving when past `floor(N/4)` (numba's `finish`)." And the **within-shot cut
  rule** with its proof (notes.md, "Pieces"): cut only between two finite times more than
  `search_window` apart; NaN rows are inert; Inf rows are skipped by the window.
- **converter.md** or `release-and-ci.md`: `_MODULES` imports backends by string, so a frozen
  build needs `hiddenimports` for every backend module in `_MODULES`, `reference` included
  (nothing in the app imports `helab.convert` yet, so today's build has no converter; my scratch
  build needed them).
- **`roadmaps/txy-converter.md`**, Stage 2: numba result line (identical; 746 MB/s/core
  reconstruction, 63×; pipeline bound by reading and writing; +145 MB / +52 MB zipped; 1.5 s
  first compile).
- **`.gitignore`**: done on this branch (`*.nbi`, `*.nbc`), as asked; was: numba's cache files land in
  `helab/convert/backends/__pycache__/` in a checkout and show as untracked; `*.pyc` doesn't
  cover them).

## Provisional items

- **Q~1, decided by Side overnight (for Tony to confirm):** numba's compiled-code cache goes in
  HeLab's cache folder (under `cache_dir()`, so it moves with the cache). Why it needed deciding:
  frozen, numba ignores `NUMBA_CACHE_DIR` and writes `~/Library/Caches/numba/backends_<sha1>/`
  (Windows `%LOCALAPPDATA%\numba\Cache`), outside HeLab's folders, never removed with them, named
  from the launch folder, and into a HeLab checkout when launched from one. Done here as a seam:
  `numba_backend.set_cache_folder(folder)` before the backend's first use (helab/convert stays
  free of `helab.utils`); stage 4's helab-core floor calls it in the helper with a folder under
  `cache_dir()` (A~4).
- **Note for A9.1** (Tony's Q9.2: every backend ships for now, as an optional backend): numba adds
  **+52 MB zipped** (+145 MB on disk; llvmlite's LLVM library is 126 MB, 113 MB after
  `strip -x`), and pins NumPy below 2.6 while in the lock (numba 0.68.1: `numpy>=1.22,<2.6`; the
  lock has 2.5.4).
- **A~1** (stage 4 packaging, Side's rule): numba needs no build step (JIT, no AOT; `numba.pycc`
  is pending deprecation), so CI covers only the without-numba path today: the numba tests skip
  there with "numba can't be imported (No module named 'numba')". If numba ships: add numba and
  llvmlite to the lock so CI runs `tests/test_convert_backend_numba.py` on all three OSes (the
  first x86-64 run of the bit-identity checks), make those skips failures in CI (e.g. an env var
  listing the backends that must be available), add the backend modules to `hiddenimports`, and
  warm the cache once in a helper at startup.
- **A~4** (stage 4, helab-core floor; Side's Q~1): in the helper process, before the numba
  backend's first use, call `numba_backend.set_cache_folder(cache_dir() / "numba")` (or the name
  the cache layout prefers; it must be absolute, a relative one raises `ValueError`). It is taken
  when the kernels first load and fixed for the process (another folder later raises
  `BackendError`). **After a cache-folder move**, a long-lived helper (Live) that has already
  loaded the kernels keeps writing to the old `<cache>/numba` (`numba_kernels.CACHE_FOLDER` is
  fixed at import, and numba's `ensure_cache_path` recreates the folder with `makedirs` if the move
  took it away; Kite): stage 4 must restart or replace such helpers after a move, or accept a stray
  old folder (compiled code only, safe to delete). An unwritable folder compiles without a cache
  (about 1.5 s per process), never numba's own folders. The housekeeping list in AGENTS.md may want a line: the numba folder holds
  only compiled code, safe to delete (recompiled on next use; stale entries are overwritten, not
  accumulated: one `.nbi` and one `.nbc` per kernel).
- **A~2**: done on this branch at CoCo's request: `backends.numba_backend` is in
  `tests/test_headless_imports.py`'s `PURE`. `numba_kernels` can't be listed: it needs numba.
- **A~3**: if the NumPy floor's shared `split.py` lands, `reconstruct_numba_pieces` can take its
  cut instead of `choose_bounds` (same rule), and `timing`'s `WITHIN_SHOT` can drive it.
- **A~5** (tests, conftest-wide; Kite): with no cache folder set, numba writes about 13
  `.nbi`/`.nbc` files per run into `helab/convert/backends/__pycache__`. My test file now sets
  a session-wide temp folder (`numba_cache_folder` fixture), so the suite writes none there
  (checked: 0 after a run). Proposed for `tests/conftest.py`: a session-scoped autouse fixture that
  calls `numba_backend.set_cache_folder(<session temp>/numba-cache)` (cheap: it imports no numba),
  so any later test that touches the numba backend inherits it; then my file's fixture can go.
- **Landing** (Kite 5): `dev/v0.0.7` gets one `_MODULES` entry and one `PURE` entry from each
  backend floor; keep every one when merging (`helab/convert/reconstruct.py`,
  `tests/test_headless_imports.py`).
- **M~1** (lab PCs, if numba ships): run the numba backend (or the frozen probe) on the Lab Side
  and Main PCs (Windows, Sandy Bridge): first-compile time, cache location, identical output.
