# Notes: TXY converter stage 2, backend `cython` (Anvil, 2026-10-29)

Floor `TXY cython`, branch `agent/txy-cython` from `372f2ac`. Brief: [brief.md](brief.md). Results:
[results.md](results.md). Handoff: [handoff.md](handoff.md).

## Why Cython (not plain C with the C API)

- The kernel reads like `backends/reference.py`, loop for loop with the same MATLAB line numbers,
  which is what a reviewer checks it against; plain C would add the CPython/NumPy C API around
  the same loops (reference counting, array checks, error paths), and that's where C extensions
  go wrong.
- Typed memoryviews give the arrays without the NumPy C API, so the build needs no NumPy headers
  and the binary has no NumPy ABI tie (it links only `libSystem`); NumPy is used from Python
  for allocation only.
- `with nogil:` around each stage releases the GIL with no extra code.
- Cython is only a build-time dependency: the built module needs neither Cython nor a compiler.
  The cost is a generated 1.3 MB C file per build (not committed) and a Cython pin for the
  packaging floor.

## Files (owned paths, plus build files)

| Path | What |
|---|---|
| `native/cython/_kernel.pyx` | the kernel: `prepare` (stable NaN-last merge sort, time zero, dead-time cut), `match` (the 4-corner loop over a row range), `assemble` (NaN-T drop, scaling, final stable sort) |
| `native/cython/build.py` | the build script (Cython + setuptools' `build_ext --inplace`); writes `build/_kernel_build.h` with the source's SHA-256 |
| `native/cython/.gitignore` | `build/` (generated C, objects) |
| `helab/convert/backends/cython/__init__.py` | the backend: lazy, locked kernel import, stale-binary check, profile → kernel numbers, within-shot split, registration |
| `helab/convert/backends/cython/_kernel.pyi` | the kernel's types (strict mypy, pyright) |
| `helab/convert/backends/cython/.gitignore` | `_kernel*.so`, `.pyd`, `.dylib` |
| `helab/convert/reconstruct.py` | one `_MODULES` line |
| `tests/test_convert_backend_cython.py` | the tests (152) |
| `bench/` (this folder) | `compare_reference.py`, `run_timings.sh`, `within_shot.py`, `timings/` |

Packages added to the floor venv only: `Cython==3.3.0` (build only; `setuptools` 84.2.0 was
already there). Listed in [requirements-bench.txt](requirements-bench.txt).

## Exactness: why the bits are the same

- Every double operation is the reference's, in the same order: `0.5 * (x1 + x2 - T)`,
  `x1 - tx`, `(tx + ty) / 2`, `((c1 − c2)·v)·bin_time`, `fabs(x1 + x2 − y1 − y2)` (Cython emits the
  left-to-right parenthesisation); `x_limit` etc. are summed in Python exactly as the reference
  does and passed in as doubles; the dead-time tolerance `dead_time / bin_time` likewise.
- The build passes `-ffp-contract=off -fno-fast-math` (clang, GCC) and `/fp:precise` (MSVC). On
  arm64 clang may fuse `a*b + c` into one FMA within an expression by default, and GCC's
  GNU-mode default is `-ffp-contract=fast` (across statements); either would change last bits.
  No expression here has the `a*b ± c` shape today except after inlining (`x1 - 0.5*(…)`), which
  is exactly what `fast` would fuse.
- NaN: C comparisons with NaN are false as in Python, so the reference's `>`/`<`/`!=` tests are
  copied as written (not inverted): `fabs(t[j] − x1) > window` lets a NaN time through to the
  channel test, as the reference does, and it then never matches.
- Channels are compared as doubles; the reference compares a float with a Python int exactly.
  These agree for every channel that is exactly a double; `unavailable(profile)` refuses the
  others (|channel| > 2^53 not representable, or beyond float range).
- Sorts: a stable merge sort with insertion-sorted runs of 32 and the reference's order (ascending,
  NaN last, NaNs equal, −0.0 equal to 0.0), with a one-pass exit when already sorted.
- The phantom row: `match` reports, per row range, whether an x pair without a y came after its
  last hit and that pair's x columns; the backend adds MATLAB's grown row W + 1 when it lies past
  `floor(rows/4)` and `matlab_overflow_row` is on, as (0, x1′, x2′, 0, 0) through the same
  scaling (so a negative v⊥y gives Y = −0.0, as the reference; tested).
- Search depth: the offsets are cut at `2·rows + 2` (beyond that every offset leaves the rows),
  so an absurd `search_depth` costs nothing; equal to the reference's list otherwise (tested).
- A stale binary: the build compiles the source's SHA-256 in; in a checkout the backend compares it
  with `native/cython/_kernel.pyx` and refuses to run on a mismatch (frozen builds have no source
  and skip the check).

## Within one shot: the cut and its proof

`reconstruct_cython(pulses, profile, threads=k)`: `prepare` sorts and cuts dead time over the whole
shot, then `cut_points` takes the candidate cuts k where `t[k] − t[k−1] > search_window` (NumPy
`diff`; NaN gaps aren't `>`), and picks for each of k − 1 equal shares of the rows the first
candidate at or after it. Each piece is matched by `match(lo, hi)` in a thread pool (the GIL is
released), candidates limited to the piece. Proof (also in the module docstring):

1. **No search crosses a cut.** For x1 at row i < k ≤ j: t sorted, so t[j] ≥ t[k] and
   t[i] ≤ t[k−1]; rounded subtraction is monotone, so t[j] − t[i] ≥ t[k] − t[k−1] > window, and
   the whole-shot run skips row j at L465/L515/L538 for its time; the piece run skips it for being
   outside the piece. Symmetric for j < k ≤ i. NaN times sort to the end and pass no comparison
   (and no cut is made beside them), infinities give `>` correctly. So the 36-row search sees the
   same candidates, in the same order, in both runs.
2. **Pieces don't interact.** A match marks only rows its searches reached (L557–560), all in
   its piece, so each piece's channels evolve as in the whole run.
3. **Whole-shot state.** `t_zero` (the first raw row) and the dead-time cut are applied by
   `prepare` before cutting; only the first piece skips its first row.
4. **Order.** Pieces are joined in row order (each piece's hits in its x1 order), then one stable
   sort by T over everything, as the whole run.
5. **The phantom row.** In the whole run, rows 1..W are hits and row W + 1 holds the x columns of
   the last x pair without a y after the W-th hit (if any). Folding the pieces' reports in order
   (a piece with hits replaces the report with its own; a piece with no hits replaces it only if
   it has such a pair) gives that pair. W is the sum of the pieces' hits, and `floor(rows/4)`
   uses the whole shot's rows.

Tested: every case and both variants at 1, 2, 3, 8 and 64 threads; each of the `phantom_*` and
`dead_time_x1` cases at every possible number of pieces; a hand-made phantom carried across a
final piece with no x1; 200 random shots × 7 profiles × 1, 2, 5, 1000 threads (the random set
reaches the phantom row and ≥ 3 cuts in most shots, which a test asserts). On the samples, all 309
shots × both profiles × 1, 2, 4, 16, 64 threads equal the reference (3,090 conversions), with 64
pieces in 598 of 618 shot-profiles.

## Findings while building

- A thread race in the first version's lazy loader (found by the harness's `threads` mode, the
  first run): every worker made the first call at once and those that saw the loaded flag before
  the import finished got no kernel and no reason (`can't run: None`). Fixed with a lock and the
  flag set last; a test with a barrier and a slowed import fails on the old code.
- `from package import _kernel` returned the package's own `_kernel = None` global instead of
  the submodule (importlib's from-list checks the attribute first): the cache is named `_module`.
- After this backend, reconstruction is no longer the bottleneck: the shared reader (`parse_raw`,
  about 60 MB/s here) and writer (`format_txy` + `write_atomic`, about 130 MB/s) are (results.md).

## Building on other platforms (for the packaging floor)

- **macOS**: Xcode's command-line tools (clang). Builds for the running Python's arch (arm64
  here); a universal2 app needs `ARCHFLAGS="-arch arm64 -arch x86_64"` (both slices, about twice
  the size).
- **Linux**: GCC or clang and the Python headers (`python3.13-dev`, or a uv/manylinux Python,
  which ships them). Keep `-ffp-contract=off`: GCC's default contracts across statements on
  aarch64 (x86-64 without `-mfma` has no FMA, but don't rely on it). Wheels: cibuildwheel with
  manylinux images.
- **Windows**: MSVC Build Tools (VS 2022, "Desktop development with C++"), run from a shell with
  the compiler on PATH (setuptools finds it through vswhere). `/fp:precise` is the default and
  doesn't contract; never add `/fp:fast` or `/fp:contract`. Output `_kernel.cp313-win_amd64.pyd`.
- **Every platform**: `pip install Cython setuptools` at build time only, then
  `python native/cython/build.py`; one binary per Python minor version (CI's compat jobs on
  3.11/3.12/3.14 need their own build, or the tests there skip). A free-threaded Python (3.13t,
  3.14t) would need `# cython: freethreading_compatible=True` and a check of the shared state
  (the kernel has none besides the loader, which is locked).
- **PyInstaller**: the backend is imported through `_MODULES` and the kernel through
  `importlib`, which PyInstaller's analysis doesn't follow: `HeLab.spec` needs
  `hiddenimports=["helab.convert.backends.cython", "helab.convert.backends.cython._kernel"]`
  (the binary collected with it). Adds about 257 kB (196 kB stripped, 75 kB gzipped) on macOS
  arm64; nothing else (NumPy is already in the build).
- **CI today**: no build step, so the kernel tests skip with the reason; the rest
  (registration, running without the kernel, the offsets and cuts) run everywhere.
