# Results: TXY converter stage 2, final timings and recommendation (Tally, 2026-10-29)

Branch `agent/txy-bench` from `ed35099` (all five backends landed on `dev/v0.0.7`), every backend
built into this floor's venv ([notes.md](notes.md), step 1). MB is 10^6 bytes of **raw** file.

## Correctness

All six backends, built together on the landed code, with the shared fast I/O (`fastio`) and the
float64 guard in `format_txy`. Logs and JSON in [`checks/`](checks/).

| Check | reference | numpy | numba | cython | rust | mlx |
|---|---|---|---|---|---|---|
| Full suite, every extension built: 8646 passed, 8 skipped (none a backend's), no RERUN | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `check_samples.py --positions all` (`matlab-2019` vs MATLAB's TXY): 303 identical + 6 proved faults, 0 differ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `check_samples.py --profile matlab-2023-lab-edit --reference-dir` (stage 1's MATLAB 2023 runs on copies): 32 of 32 identical | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| vs reference, 309 shots × both built-ins, TXY bytes and outcomes (NumPy floor's `compare_backends.py`) | – | 618/618 | 618/618 | 618/618 | 618/618 | 618/618 |
| same, through `split.reconstruct_split` at every safe gap (`--split`, `min_rows=1`) | – | 618/618 | 618/618 | 618/618 | 618/618 | 2,472/2,472 (a) |
| backend's own comparison (its own within-shot path), both built-ins | – | – | 0 differences, whole and 2/4/16/64 pieces, serial and prange (`compare_samples.py`) | 1,854 conversions at 1/4/64 threads, 0 differ (`compare_reference.py`) | 309 × 4 variants × 2, 0 differ (`compare_samples.py`; up to 741,370 pieces in a shot) | 309/309 × 2, GPU and CPU search (`compare_backends.py`; 42,737 contested x1 under 2019, 0 under 2023) |

(a) mlx pays ~2.5 ms of GPU dispatch per call, so splitting at every safe gap (up to 741,370
pieces in one shot) would take hours; I stopped it after ~10 min (it reports only at the end). Instead
[`compare_split.py`](compare_split.py) asks `reconstruct_split` for at most 2, 8, 64 and 256 pieces
(`min_rows=1`): **2,472 conversions, 0 differ** (asked 256: cut into 3–256, median 249).

**No difference anywhere.** Nothing to report to the backend floors.
