# Notes: TXY converter stage 2, backend numba (Worker, 2026-10-29)

Branch `agent/txy-numba` from `372f2ac`. Brief: [brief.md](brief.md). Results: [results.md](results.md).
Handoff: [handoff.md](handoff.md).

## Packages (floor venv only)

`uv pip install --python venv/bin/python numba` (prefix checked under the floor first):
**numba 0.68.1** and **llvmlite 0.50.0**, with the lock's numpy 2.5.4 unchanged. numba 0.68.1
requires `numpy>=1.22,<2.6` and `llvmlite>=0.50.0dev0,<0.51`, so with numba in the lock NumPy
can't move past 2.5.x until a numba release allows it (numba usually trails a NumPy minor by
weeks to months). [`requirements-bench.txt`](requirements-bench.txt) lists them. Nothing in
`requirements.txt`, the lock, `pyproject.toml` or `HeLab.spec`.

## Layout

| File | What |
|---|---|
| `helab/convert/backends/numba_backend.py` | Registers `numba` on import (`releases_gil=True`); `unavailable` imports numba on first ask (cached) and gives the ImportError's text when it fails, and refuses a profile with a candidate handling or position formula the kernels don't compile (none exist yet: the profile refuses them, so this guards future values). `reconstruct_numba` (the registered `run`), `reconstruct_numba_pieces` (within-shot: `serial`, `threads` on a given executor, `prange`), `piece_bounds`. |
| `helab/convert/backends/numba_kernels.py` | The `@njit(cache=True, nogil=True)` loops, imported only when numba is. numba is reached through `importlib.import_module` and a typed `_jit` wrapper (`cast` to the function's own type), so mypy and pyright check the kernels as plain typed Python with or without numba installed: no stub needed, no `type: ignore`. |
| `helab/convert/reconstruct.py` | One entry in `_MODULES` (the only shared edit). |
| `tests/test_convert_backend_numba.py` | Cases vs MATLAB, lab pairs, every field perturbed, random streams, pieces = whole, the cut rule, threads, `NoRowsError`, the uncached fallback, 24 threads racing a cold start; and, run everywhere, HeLab with numba blocked and registration importing no numba. |

No build files: numba compiles at run time.

## Two changes of form, and why neither changes the output

The kernels follow the reference loop for loop (MATLAB line numbers kept in the comments), with
two changes:

**1. No MATLAB output matrix.** The reference builds `NaN(floor(N/4), 5)`, grows it with zero
rows, and backs `which_row` off after an x pair with no y. Here a hit is written when found, and
the phantom row is rebuilt at the end:

- `which_row` is net non-decreasing over x1 rows (it goes up by one with an x pair and back by one
  only when that same x1 finds no y). So a row that got a hit is never written again, and every
  row past the last hit `W` that is ever written is row `W + 1`: by a failed x1 whose
  `which_row` was `W` then, that is, one after the last hit (or any, with no hits).
- Row `W + 1` survives the NaN filter only when it is a grown row (`W + 1 > floor(N/4)`,
  `matlab_overflow_row`): T = 0, its columns 2–3 those of the last such failed x pair, 4–5 zero.
  `finish` computes `0·bin_time`, `(c2 − c3)·v⊥x·bin_time`, `(0 − 0)·v⊥y·bin_time`, the
  reference's arithmetic on the same values (a negative v⊥ gives −0, as there; tested).
- Hits keep the reference's row order, then the final stable sort by T (L1528–1530).

**2. Pieces (within one shot).** `choose_bounds` cuts the sorted rows between `k` and `k + 1`
only where both times are finite and `t[k+1] − t[k] > window` (`search_window`, 3200 bins),
taking the first such gap at or after each of `pieces − 1` evenly spaced target rows. Why the
pieces' output is the whole's:

- For x1 at row `i ≤ k` and a finite row `j ≥ k + 1`: `t[j] ≥ t[k+1]` and `t[i] ≤ t[k]`, and
  rounded subtraction is monotonic, so `t[j] − t[i] ≥ t[k+1] − t[k] > window`: the reference
  skips `j` (L465 for x2, L515 for y1, L538 for y2), exactly as it skips a row past the array's
  ends; the same the other way round. A row with time ±Inf is skipped too (`|±Inf − x| = Inf`).
- A row with a NaN time is not skipped by the window test (`NaN > w` is false), but every test
  after it compares with NaN and fails, so it never matches and is never marked. An x1 with a NaN
  time likewise matches nothing. So reading or not reading a NaN row of another piece changes
  nothing.
- Hence each x1 reads and marks (channel NaN) only rows of its own piece, and the 36-row search
  inside a piece with the piece's bounds as ends equals the search over the whole array.
- What stays global: `t_zero` (first raw row, before sorting), the sort, the 2023 dead-time cut
  (applied to the whole sorted array before cutting, so a 20,000-bin `uniquetol` group is never
  split), the first-sorted-row skip (only piece 0 starts at row 1), `floor(N/4)` over all N rows
  (NaN rows included), the phantom (the last failed x pair after the last hit over all pieces,
  in order), and one stable sort by T over the concatenated hits.

Tested: every case under both profiles cut into 2, 3, 5, 1000 pieces asked (the `phantom_*` and
`dead_time_x1` cases really are cut), serial, threads and prange; 40 random streams × 4 profiles
× 2/7/50 pieces; all 309 shots × both profiles × 2/4/16/64 pieces asked, serial and prange
(`compare_samples.py`, 0 differences).

**Greedy matching and prange inside one piece:** not done, and it can't stay byte-identical as a
plain `prange` over x1 rows: whether an x1 matches depends on which pulses earlier x1 rows marked
used (`used_pulses` case: two x1 sharing one x2). Pieces are the only safe cut.

## NaN and sorting

- Times and channels float64 throughout; NaN marks used pulses as in the reference (`!=` and `==`
  with NaN behave the same in numba's compiled code: IEEE, no fastmath).
- Sorts: the raw rows are sorted with NumPy's `np.argsort(kind="stable")` (a timsort, which uses
  the TDC stream's near order: 24 ms against numba's mergesort's ~90 ms on the 24 largest shots;
  NumPy sorts without the GIL) and the order is passed in; the final sort of the hits is numba's
  `np.argsort(kind="mergesort")`, stable with NaN last too; checked against
  NumPy's `kind="stable"` on 2,000 random arrays with NaN and −0.0 (0 differences), and by the
  tests on every case and shot. Equal times (and 0.0 vs −0.0) keep file order.
- No `fastmath`; LLVM doesn't contract `a*b + c` into an FMA without it, so every product and
  sum rounds as Python's (the tests compare the hit arrays' bytes, signed zeros included).

## Threads and the GIL

A conversion is NumPy's stable argsort (which releases the GIL) and `convert` (order, dead time,
match, finish), one `nogil` call; the wrapper only builds the arguments (a few µs).
`releases_gil=True`: reconstruction alone scales about linearly with threads (results.md).
`prange` (`match_parallel`) runs on numba's threading layer, here `workqueue` with 16 threads
(checked with `numba.threading_layer()`; no TBB or OpenMP installed), which numba's docs say is
not safe to enter from two Python threads at once. So the registered backend never uses it; it
exists for the within-shot measurement. prange in the app would need `tbb` (another wheel) or a
lock around it.

**Lazy loading and threads** (Anvil's Cython finding): the loader is `importlib.import_module`
(Python's per-module import lock: a second thread waits for the first to finish executing the
module) and a `functools.cache`d import check (at worst run twice, same answer); numba compiles
under its own global compiler lock. Tested: 24 threads released by a barrier into a fresh process
with an empty cache folder (import, compile and cache write all raced), both profiles: all equal
the reference, 5 runs of 5.

**Exact bits** (Anvil): no `fastmath` anywhere, and every expression in the reference's order and
grouping (`0.5 * (x1 + x2 - T)`, `(tx + ty) / 2`, `(c2 - c3) * v * bin_time`, `x1 + x2 - y1 - y2`
left to right).

## `cache=True`, the frozen app, and the first call

**Source checkout:** numba writes `<module dir>/__pycache__/numba_kernels.<function>-<line>.py313.{nbi,nbc}`
(`InTreeCacheLocator`), or, if that folder isn't writable, the user-wide cache
(`~/Library/Caches/numba/<dir>_<sha1 of the module's folder>/`); `NUMBA_CACHE_DIR` comes before
both. Staleness is safe: the index is stamped with the SHA-256 of the source file's content
(numba 0.68's `_hash_source_file`; mtime and size only memoise it), and each entry's key holds the
function's bytecode hash and the CPU name and features, so a changed kernel or another CPU model
recompiles.

**Gitignore:** the repo's `.gitignore` had `*.pyc` but not `*.nbi`/`*.nbc`, so these files
showed as untracked in `helab/convert/backends/__pycache__/`; added on this branch at CoCo's
request.

**Frozen (PyInstaller), measured on a scratch onedir build** (`.ai/temp/pyi-numba/probe.spec`, a
probe that converts one file and reports numba's cache locator):

- PyInstaller doesn't find the backend by itself: `_MODULES` imports by string, so the build
  needs `hiddenimports` for `helab.convert.backends.numba_backend` and `…numba_kernels` (and, as
  today for `reference`, every backend module); then pyinstaller-hooks-contrib's numba and
  llvmlite hooks collect the rest. The probe ran and gave the reference's bytes.
- A frozen module's `co_filename` is **relative** (`helab/convert/backends/numba_kernels.py`).
  So numba's in-tree and `NUMBA_CACHE_DIR` locators (which need that file to exist) are skipped,
  and the cache goes to the **user-wide** folder, `~/Library/Caches/numba/backends_<sha1>/`
  (Windows, by numba's appdirs with no author: `%LOCALAPPDATA%\numba\Cache`), where the sha1 is of the
  **absolute path made from the launch folder**: a different launch folder means another cache
  folder and one more compile. Worse, launched with a HeLab checkout as its working folder, the
  relative path exists and numba writes the cache into that checkout's `__pycache__` (seen:
  my first run from the floor's root did). `NUMBA_CACHE_DIR` has no effect frozen.
- The stamp is the SHA-256 of `sys.executable` (the bootloader with the PKG holding the PYZ), so
  a new build recompiles once; touching the exe doesn't.
- Compile 1.3 s on the first run, 0.07 s cache load after.
- **A read-only user cache folder made `njit(cache=True)` raise at import of the kernels** ("no
  locator available"), failing the backend; `numba_kernels._compile` now falls back to
  `cache=False` (`numba_kernels.cached = False`): measured frozen, it converts correctly and
  compiles every run (1.1 s).

**The seam (Side's decision: the cache goes under HeLab's `cache_dir()`).**
`numba_backend.set_cache_folder(folder)` records the folder; `numba_kernels` takes it once as it
first loads (`take_cache_folder`, under a lock; another folder after that raises `BackendError`)
and, when one is given, puts a locator of its own first in numba's `CacheImpl._locator_classes`.
It answers only for `numba_kernels`' functions (any other numba code in the process keeps numba's
choice), writes straight into the folder, and keeps numba's stamp (`_SourceFileBackedLocatorMixin`:
the SHA-256 of the source file, of the executable when frozen) and line-number disambiguator. When
the folder can't be created or written it raises, which `_compile` turns into `cache=False`: never
a silent fallback to numba's own folders. It uses two numba-private names
(`_SourceFileBackedLocatorMixin`, `_CacheLocator`, plus the `_locator_classes` list), so a numba
upgrade must keep `tests/test_convert_backend_numba.py`'s cache tests passing. Measured frozen,
launched from a neutral folder: all eight cache files in the given folder, none in numba's;
compile 1.3 s, then 0.07 s loads; identical bytes. A source checkout and the app sharing one
folder overwrite each other's index (different stamps; from numba's `_load_index`, not measured), so each recompiles once after the other
ran. AOT (`numba.pycc`) is pending deprecation since numba 0.57 (present in 0.68 with a warning):
not used.

**Coverage in CI:** there is no AOT step and nothing CI must build: the JIT runs wherever numba is
installed. CI doesn't install numba (it isn't in the lock), so CI runs only the without-numba
tests (`test_helab_works_without_numba`, the registration test) and skips the rest with the reason
"the numba backend can't run here: numba can't be imported (No module named 'numba')". The numba
tests ran here (macOS arm64) only; x86-64 bit-identity (the kernels use only +, −, ×, ÷, abs and compares, so only FMA contraction
could differ, and numba doesn't contract without fastmath) is untested until
CI installs numba (A~1 in the handoff).
