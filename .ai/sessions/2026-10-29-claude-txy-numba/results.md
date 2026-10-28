# Results: the numba backend (Worker, 2026-10-29)

**Machine:** Apple M4 Max (12 performance + 4 efficiency cores), 128 GB, macOS 26.7; Python
3.13.15, NumPy 2.5.4, numba 0.68.1, llvmlite 0.50.0. **What was running:** four other backend
floors and their tests; load average **10–14 on 16 cores** throughout. My own test suite wasn't
running during the timings. These are indicative; the final timings are taken serially on an idle
machine.

**Data:** the sample set, all 309 shots, 217.5 MB raw (`~/HeLab-samples/txy-v1/`, read only);
"large" = the 3 largest shots of each set (24 shots, 101.7 MB, 6.57 M pulses), "small" = the other
285 (115.8 MB). Profile `matlab-2019` unless named. MB = 10^6 bytes of raw file.

## Correctness

| Check | Result |
|---|---|
| 39 synthetic cases × 2 built-ins vs MATLAB's output (`tests/test_convert_backend_numba.py`) | all identical (outcomes too: file / no file / error) |
| `tests_sample_data/` lab pairs | all reproduced |
| `dev/txy/check_samples.py --positions all --backend numba` | 303 identical, the 6 listed exceptions (1 cut, 2 variant, 3 empty) proved again with numba, **0 differ** |
| numba vs reference, all 309 shots, `matlab-2019` and `matlab-2023-lab-edit` (`compare_samples.py`) | **0 differences**, whole and cut into 2/4/16/64 pieces asked (serial and prange) |
| Every profile field perturbed (+ negative v⊥), 39 cases × 2 inputs × 2 bases, vs reference | identical |
| 40 random pulse streams (NaN/±Inf/−0/repeated times, NaN channels) × 4 profiles, whole and in pieces | bit-identical arrays |

## Speed

| Measure | Result | How |
|---|---|---|
| Reconstruction, 1 core, all shots (warm) | **746 MB/s** (0.29 s); reference 11.8 MB/s: **63×** | `bench_numba.py reconstruct` |
| Reconstruction, 1 core, large shots | **1,430 MB/s** (71 ms for 24 shots) | `bench_numba.py within` |
| Reconstruction, threads across shots (all shots) | 1: 774, 2: 1,572, 4: 3,016, 8: 4,108 MB/s (12: 2,724, noisy at load 13) | `bench_numba.py threads` |
| Pipeline serial (read + reconstruct + write), all | total **43.5 MB/s**: read 69.9, reconstruct 457, write 154 MB/s | `time_samples.py --backend numba` |
| Pipeline serial, `matlab-2023-lab-edit` | total 44.3: read 67.3, reconstruct 468, write 179 MB/s | same, `--profile` |
| Latency per shot, small | median **10.2 ms**, max 207 ms | serial pipeline |
| Latency per shot, large | median **28.5 ms**, max 350 ms | serial pipeline |
| Pipeline, 4 processes | wall **133 MB/s** | `--parallelism processes --workers 4` |
| Pipeline, 12 processes | wall **187 MB/s** (load 13) | `--workers 12` |
| Pipeline, 4 / 12 threads | wall 44.5 / 42.5 MB/s: no gain | `--parallelism threads` |
| Within one shot, large shots, 2 / 4 / 8 / 12 pieces | threads 58 / 49 / 46 / 54 ms; prange 59 / 51 / 55 / 49 ms; whole 71 ms: **≤ 1.5×** | `bench_numba.py within` |
| First call: `import numba` | 0.10–0.11 s | `bench_numba.py first-call`, 3 runs |
| First call, empty cache (compile) | **1.50–1.63 s** | fresh process, new `NUMBA_CACHE_DIR` |
| First call, cache filled (load) | **0.10–0.11 s**; next call 35–44 µs (a 5-hit file) | fresh process |
| Frozen app (scratch PyInstaller build): compile / load / read-only cache | 1.30 s / 0.07 s / 1.1 s every run (uncached fallback) | `.ai/temp/pyi-numba/` |
| Cache on disk | 440 kB, 4 `.nbc` (serial kernels; prange adds its own) | |
| Size added to a PyInstaller build | **+145 MB** on disk (onedir 176.0 vs 31.0 MB); **+52 MB** zipped (66.7 vs 14.9 MB). `libllvmlite.dylib` alone is 126 MB (113 MB after `strip -x`); numba's Python ~12 MB in the PYZ; extensions ~1 MB | measured: scratch build of a probe with and without numba (`probe.spec`), macOS arm64 |

## What the numbers say

- **Reconstruction is no longer the bottleneck.** Serially, of 5.0 s for all shots, reading
  (`parse_raw`, 3.1 s) and writing (`format_txy` + atomic write, 1.4 s) take 90 %;
  reconstruction 0.48 s, of which ~0.1 s is the first shot loading the compiled cache. The
  pipeline's 43.5 MB/s per core is set by the stage-1 reader and writer, which the NumPy floor's
  fast text I/O addresses.
- **Threads:** the kernel holds no GIL (reconstruction alone scales ~linearly with threads), but
  the pipeline's Python reader and writer do, so threads across whole conversions don't help
  until reading and writing release the GIL too. **Processes** do (133 MB/s with 4, 187 with
  12 under load), above the ~100 MB/s bulk target.
- **Within one shot** buys at most ~1.5× here: the sort (24 ms), dead-time pass and copy (9 ms)
  and final merge and sort (5 ms) stay serial against 44 ms of matching. Not worth it for the app
  (a shot reconstructs in tens of ms); processes across shots are the better lever.
- **Live** (one shot every ~30 s) is easy: ~10–30 ms per shot after a one-time 1.5 s compile per
  machine and build (0.1 s cache load per process after that).
- The sort change (NumPy's stable timsort instead of numba's mergesort, which took 70 % of the
  kernel's time) took reconstruction alone from 560 to 746 MB/s over all shots and from 745 to
  1,430 MB/s on the large ones; the earlier run's figures are in
  `.ai/temp/txy/timing-json/numba-*.json` (gitignored), the current ones in `v2-*.json`.
