# Notes: TXY converter stage 2, final timings (Worker Tally, 2026-10-29)

Floor `HeLab--agenttxy-bench`, branch `agent/txy-bench` from `ed35099` (all five backends landed
on `dev/v0.0.7`). Brief: [brief.md](brief.md).

## Step 1: what was built into this floor's venv

`venv/bin/python -c "import sys; print(sys.prefix)"` gave
`/Users/tonyyan/GitHub-Local/.maestri/floors/HeLab--agenttxy-bench/venv` (a real folder, not a
link), so everything went into the floor only. Installed with
`uv pip install --python venv/bin/python numba==0.68.1 llvmlite==0.50.0 mlx==0.32.4 mlx-metal==0.32.4 Cython==3.3.0 maturin==1.15.0`
(the versions in each floor's `requirements-bench.txt`):

| Package | Version | For | Was there before |
|---|---|---|---|
| numba | 0.68.1 | numba backend (JIT) | no |
| llvmlite | 0.50.0 | numba | no |
| mlx | 0.32.4 | mlx backend | no |
| mlx-metal | 0.32.4 | mlx (Metal kernel library) | no |
| Cython | 3.3.0 | building the cython kernel (build time only) | no |
| maturin | 1.15.0 | building the rust extension (build time only) | no |
| setuptools | 84.2.0 | building the cython kernel | yes (lock) |
| numpy | 2.5.4 | everything | yes (lock) |
| helab-convert-rs | 0.1.0 (editable) | rust backend, from `maturin develop --release` in `native/rust/` | no |

Builds:

- `python native/cython/build.py` → `helab/convert/backends/cython/_kernel.cpython-313-darwin.so`
  (257,360 B; Apple clang 21.0.0, one `-Wunreachable-code` warning in Cython's generated C).
- `cd native/rust && maturin develop --release` (Homebrew rustc 1.99.1, 7.8 s from a cold
  `target/`) → `venv/lib/python3.13/site-packages/helab_convert_rs/helab_convert_rs.abi3.so`
  (474,128 B; the wheel is `cp311-abi3-macosx_11_0_arm64`).
- `available_backends()` → `['cython', 'mlx', 'numba', 'numpy', 'reference', 'rust']`; each
  `unavailable(profile)` is None.

numba's cache: every run here sets `NUMBA_CACHE_DIR=.ai/temp/txy/numba-cache` (numba honours it
unfrozen), so nothing lands in `helab/convert/backends/__pycache__`.

## Step 2: correctness with everything built

**Full suite** (`pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`, every
extension built, load ~8–14 from other floors): **8646 passed, 8 skipped, no RERUN** (181 s).
The 8 skips, none a backend that didn't run:

- 4 in `tests/test_convert_backend_numba.py:324` and 2 in `tests/test_convert_profile.py:114`:
  the perturbation tests' single-value fields `x2_handling` and `y_handling` (nothing to perturb
  to; on every floor since stage 1);
- `tests/test_data_roots.py:224`: opt-in native volume-ID check;
- `tests/test_folder_icons.py:187`: opt-in macOS native icon check.

So every backend test ran: none of the "not built", "can't be imported" or "MLX isn't installed"
skips the floors' handoffs list appeared. Type checks: `mypy helab/ --strict` (182 files),
`mypy tests --strict` (151), `pyright helab tests`: clean.

**Sample checker**, `dev/txy/check_samples.py --positions all --backend <b>` (`matlab-2019`
against MATLAB's TXY in the sample set), logs and JSON in [`checks/`](checks/):

| backend | shots | identical | cut | variant | empty | differ |
|---|---|---|---|---|---|---|
| reference | 309 | 303 | 1 | 2 | 3 | 0 |
| numpy | 309 | 303 | 1 | 2 | 3 | 0 |
| numba | 309 | 303 | 1 | 2 | 3 | 0 |
| cython | 309 | 303 | 1 | 2 | 3 | 0 |
| rust | 309 | 303 | 1 | 2 | 3 | 0 |
| mlx | 309 | 303 | 1 | 2 | 3 | 0 |

Each of the 6 listed reference faults was proved again with each backend.

**`matlab-2023-lab-edit` against MATLAB's own 2023 output**: the sample set has no 2023 TXY, so
the checker takes `--reference-dir`. Stage 1's MATLAB runs on copies (4 even shots per set, made by
`matlab_variant.py`) are on the reference floor's `.ai/temp/txy/matlab-2023/`; I copied the 32 raw
copies and 32 TXY to this floor's `.ai/temp/txy/matlab-2023/` (the checker picks shots by the raw
copy). `check_samples.py --positions even --limit 4 --profile matlab-2023-lab-edit --reference-dir
.ai/temp/txy/matlab-2023 --backend <b>`: **32 of 32 identical for every backend** (the empty ghost
d5 included, a 0-byte file). Lens's 152 odd-shot MATLAB runs aren't on this machine any more.

**Every backend against the reference, all 309 shots × both built-ins**, with the NumPy floor's
generic `compare_backends.py --backend <b>` (TXY bytes and outcomes), whole and with `--split`
(`split.reconstruct_split` with `min_rows=1`, cut at every safe gap): see the table in
[results.md](results.md#correctness).

**The floors' own comparisons** (each backend's own within-shot paths): see results.md.
