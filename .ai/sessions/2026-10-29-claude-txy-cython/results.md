# Results: the `cython` converter backend (stage 2)

**Machine:** Apple M4 Max (12 performance + 4 efficiency cores, 16 in all), 128 GB, macOS 26
(Darwin 25.6), Python 3.13.15 (uv), Cython 3.3.0, Apple clang 21 (`-O3 -ffp-contract=off
-fno-fast-math`). **What was running:** four other converter floors (numba, numpy, rust, mlx)
plus Safari. Load average 7–10 for the final runs (up to 18 for earlier ones). These are
indicative timings; the final ones are taken later, serially, on an idle machine.

**Data:** all 309 sample shots (217.5 MB raw), profile `matlab-2019`. "Large" means the three
largest shots of each set (24 shots, 101.7 MB); "small" means the other 285 (115.8 MB). MB is
10^6 bytes. Kernel `1a595b8`.

Logs and JSON: `bench/timings/` (`run.log` and `cython-*.json`, `reference-serial.json` from
`dev/txy/time_samples.py` through `bench/run_timings.sh`; `within-shot.log` and `.json` from
`bench/within_shot.py`).

## Byte-identical

| Check | Result |
|---|---|
| `dev/txy/check_samples.py --backend cython --positions all` | 309 of 309: 303 identical, 1 cut, 2 variant, 3 empty (each proof holds again), 0 differ. The same as the reference. |
| cython vs reference, all 309 shots × both built-in profiles × 1, 2, 4, 16, 64 threads (`bench/compare_reference.py`) | 3,090 conversions, 0 differ (repeated after the sort change at 1, 4 and 64 threads: 1,854, 0 differ). 64 pieces in 598 of 618 shot-profiles. |
| 39 synthetic cases × 2 variants (outcome and bytes vs MATLAB) | all identical, also with `matlab_overflow_row` flipped, at 1, 2, 3, 8 and 64 threads |
| `tests_sample_data/` lab pairs | all reproduced, also at 4 and 16 threads; equal to the reference under 2023 |
| `matlab-2023-lab-edit` | identical to the reference on all 309 shots (the reference matches MATLAB's 2023 output: stage 1) |
| 200 random shots × 7 profiles × 1, 2, 5, 1000 threads | identical (covers the phantom row, NaN times, ties, dead time on every corner, depth 3 and 200, raw positions) |

## Timings

| Measure | cython | reference (same run) | Notes |
|---|---|---|---|
| Reconstruct, serial, per core: all / small / large | **801 / 657 / 1,066 MB/s** | 13.5 / 9.9 / 23.1 MB/s | 59× faster overall; harness `serial` |
| Reconstruct alone, best of 5 (kernel and wrapper): all / small / large | 1,047 / 859 / 1,419 MB/s | | `within_shot.py`, 1 thread |
| Read (file plus `parse_raw`), serial | 71 MB/s | 71 MB/s | shared Python code, unchanged |
| Write (`format_txy` plus `write_atomic`), serial | 153 MB/s | 156 MB/s | shared Python code, unchanged |
| Total per core (read + reconstruct + write), serial | **45.8 MB/s** | 10.6 MB/s | read and write are now 94 % of the time |
| Total, across shots in processes: ×4 / ×8 / ×12 (wall) | 161 / 267 / **359 MB/s** | | per worker 43 / 39 / 38 MB/s |
| Total, across shots in threads: ×4 / ×8 / ×12 (wall) | 49 / 49 / 49 MB/s | | GIL-bound: the Python reader and writer hold the GIL |
| Reconstruct alone, across shots in threads: ×1 / 2 / 4 / 8 / 12 (wall) | 958 / 1,858 / 3,522 / 6,216 / **8,456 MB/s** | | the GIL release: 8.8× at 12 threads |
| Reconstruct, within one shot, threads 1 / 2 / 4 / 8 / 12: large | 1,419 / 1,583 / **1,796** / 1,783 / 1,765 MB/s | | 1.27× at 4; at least 12 pieces in every large shot |
| Same, small | 859 / 919 / 948 / 813 / 696 MB/s | | pool overhead outweighs the gain |
| Kernel stages, large shots, serial: sort + time zero (`prepare`) / match / assemble | 2,793 / 3,400 / 75,181 MB/s | | the sort is about half (54 %) of kernel time |
| Latency per shot (read + reconstruct + write), serial: median / max | 10.2 / 354 ms | 47.1 / 748 ms | small shots: median 10.0, max 55 ms |
| Reconstruct latency per shot: median / max | 0.55 / 20 ms | 37.8 / 454 ms | largest shot (24.1 MB): 14.9 ms vs 420 ms |
| First call: importing the backend and loading the kernel (fresh process) | 3.2 ms | | after `helab.convert.raw` and `profile` are imported |
| First call: first vs second reconstruction (smallest shot) | 0.054 vs 0.020 ms | | no JIT, no warm-up |
| Size added to a PyInstaller build | about 257 kB (196 kB stripped, 75 kB gzipped) | 0 | **estimated** from the built `_kernel.cpython-313-darwin.so` (arm64), which links only `libSystem`; no runtime dependency beyond NumPy, already bundled. Not measured on a scratch build. |

## What the numbers say

- **Reconstruction is no longer the bottleneck.** At about 0.8–1 GB/s per core it takes about
  6 % of a conversion's time. The shared Python reader (71 MB/s) and writer (153 MB/s) take
  the rest. One core converts at about 46 MB/s whatever the backend does from here.
- **Live** (one shot every ~30 s) is met with a wide margin: the largest sample shot converts in
  0.35 s, the median one in 10 ms.
- **Bulk** (~100 MB/s): reached with processes (×4 gives 161 MB/s wall, ×12 gives 359), not with
  threads. Threads are held back by the GIL-bound reader and writer, not by this backend: alone,
  its reconstruction scales 8.8× on 12 threads. A GIL-free reader and writer (the NumPy floor's
  fast text I/O, or a Cython one) would make threads as good as processes without the process
  start-up and pickling.
- **Within one shot** helps only large shots (1.27× at 4 threads), because the sort, time zero and
  assembly stay serial and each call starts a thread pool. It isn't worth it for the samples. A
  per-piece sort (pieces cut on the unsorted stream) would need its own proof.
