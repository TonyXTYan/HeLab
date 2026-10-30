# Results: TXY converter stage 2, backend `mlx` (Prism, 2026-10-29)

**Machine:** Apple M4 Max (16 CPU cores), 128 GB, macOS 26.7; Python 3.13, NumPy from the lock,
MLX 0.32.4 (`mlx`, `mlx-metal`). **What was running:** four other backend floors (numpy, numba,
cython, rust) building and testing at the same time; load average 8 to 14 throughout (shown per run
in the session log). These timings are indicative; the final ones are taken serially on an idle
machine.

**Data:** the sample set `~/HeLab-samples/txy-v1/`, all 309 shots, 217.5 MB of raw files
(1,480,691 hits under `matlab-2019`). "Large" = the 3 largest shots of each set (24 shots,
101.7 MB); "small" = the other 285 (115.8 MB). MB/s are SI (10^6 bytes of raw file per second).

## Byte for byte

| Check | Result |
|---|---|
| 39 synthetic cases × `matlab-2019`, `matlab-2023-lab-edit` (outcome and bytes vs MATLAB and the reference) | 78 / 78 identical, GPU and CPU search |
| `dev/txy/check_samples.py --positions all --backend mlx` (`matlab-2019` vs MATLAB's TXY) | 303 identical + the 6 listed reference faults (cut 1, variant 2, empty 3), each proof re-run with `mlx`; 0 unexplained |
| `compare_backends.py --positions all` vs the reference, `matlab-2019` | 309 / 309 identical (GPU and CPU search) |
| same, `matlab-2023-lab-edit` | 309 / 309 identical |
| `tests_sample_data/` (17 lab pairs) | 17 / 17 |
| Fuzz (tests): 6 profiles × 40 dense streams with ringing; NaN, ±Inf, fractional and > 2^50 times | identical; the greedy pass changes 1,681 first choices under `matlab-2019`, 269 of them by cascade |

How often the greedy pass has to recompute (contested x1 rows at the start, `compare_backends.py`):

| Set | x1 rows | contested | changed | hits |
|---|---|---|---|---|
| 2019-halos-old-plates | 341,157 | 2,917 | 2,928 | 259,421 |
| 2020-halos-weak-trap | 215,296 | 530 | 534 | 123,344 |
| 2022-07-old-plates-he3he4 | 366,586 | 15,390 | 16,477 | 287,703 |
| 2022-07-old-plates-large-he3 | 471,751 | 23,894 | 25,590 | 358,269 |
| 2022-11-ghost-counts-mcp | 100,665 | 2 | 2 | 70,461 |
| 2023-02-new-plates-he3he4 | 254,377 | 1 | 1 | 145,422 |
| 2023-03-momentum-bells | 318,405 | 2 | 2 | 202,801 |
| 2024-11-rt-low-occupancy | 52,570 | 1 | 1 | 33,270 |
| **all, `matlab-2019`** | **2,120,807** | **42,737 (2.0 %)** | **45,535** | **1,480,691** |
| **all, `matlab-2023-lab-edit`** | 1,525,965 | 0 | 0 | 1,203,156 |

The old plates ring (a second x1/x2 within a few hundred bins), so 3 to 5 % of their x1 rows compete
for the same pulses; the new plates almost never do, and the 2023 dead time removes the
ringing x1 altogether.

## Timings (stage 1's harness, `dev/txy/time_samples.py --positions all`, `matlab-2019`)

| Measure | mlx | reference (same load) |
|---|---|---|
| Serial: read (file + parse, stage 1's reader) | 66.4 MB/s | 67.2 MB/s |
| Serial: reconstruct, all shots (one core + GPU) | **106 MB/s** | 13.0 MB/s |
| Serial: reconstruct, small shots | 72.0 MB/s | 9.5 MB/s |
| Serial: reconstruct, large shots | 233 MB/s | 22.2 MB/s |
| Serial: write (format + atomic write, stage 1's writer) | 160 MB/s | 152 MB/s |
| Serial: total per core (read + reconstruct + write) | 32.6 MB/s | 10.2 MB/s |
| Latency per shot, small: median / max | 15.2 / 83 ms | 47.6 / 293 ms |
| Latency per shot, large: median / max | 36.8 / 398 ms | 162 / 772 ms |
| Processes ×4: wall (total throughput) | 108 MB/s | (stage 1: 42 MB/s) |
| Processes ×8: wall | **172 MB/s** | – |
| Threads ×4: wall | 40.7 MB/s | – |
| Threads ×8: wall | 40.0 MB/s | – |
| First call: import of the backend module | 2.5 ms | – |
| First call: `import mlx.core` + Metal check | 37–39 ms | – |
| First call: first conversion (`basic` case) / the second | 9–10 ms / 2–3 ms | – |
| Transfer per shot (unified memory): up 0.26 MB / 1.7 MB / 14.4 MB | 0.02 / 0.04 / 0.24 ms | – |
| Transfer per shot: results down (8 bytes per x1) | ~0.01 ms | – |
| PyInstaller: size added (scratch onedir build, measured) | +240 MB on disk, +80 MB gzipped | – |

Inside the reconstruction (`step_timing.py --positions all`, best of 3, all 309 shots; MB/s of raw
file per step, seconds in brackets):

| Step | where | all | small | large |
|---|---|---|---|---|
| prepare (sort, time zero, integers, dead time) | CPU, NumPy | 913 (0.24 s) | 759 | 1189 |
| first-choice search | **GPU, MLX** | **252 (0.86 s)** | 161 | 707 |
| first-choice search, same algorithm | CPU, NumPy | 41 (5.33 s) | 28 | 87 |
| greedy pass (contested x1 rows) | CPU, Python | 481 (0.45 s) | 374 | 713 |
| output (T/X/Y, phantom row, sort) | CPU, NumPy | 3908 (0.06 s) | 2538 | 10132 |
| **sum, GPU search** | | **≈135 (1.61 s)** | | |
| sum, NumPy search instead | | ≈36 (6.08 s) | | |
| reference, for scale | CPU, Python | 12.8 (17.0 s) | 9.3 | 22.4 |

Reading the numbers:

- **The GPU helps, but only with the search.** The greedy order stays on the CPU, as the brief
  expected. The GPU search runs 6× faster than the same brute-force search in NumPy (252 vs 41 MB/s).
  It is **not** compared here with the NumPy floor's own algorithm, which is likely smarter than a
  36 × 36 pair tensor. That comparison is for the final serial run.
- **Each shot pays a fixed GPU cost**, about 2.5 ms of dispatch and synchronisation, and small shots
  feel it most (161 MB/s vs 707 on large ones). Transfer costs nothing on unified memory.
  `mx.compile` with padded batch sizes halves the search (e.g. 7.4 → 2.3 ms on a 2.5 MB shot), but
  its first call costs **~560 ms** of Metal compilation, against about 10 ms without it, and it
  would save only ~0.4 s over all 309 shots. So it was measured but not adopted; it stays an option
  for a long-lived converter.
- **The backend is no longer the bottleneck.** Reading (66 MB/s, stage 1's parser) and writing
  (160 MB/s) now take ~80 % of a serial shot, and the pipeline is 32.6 MB/s per core. Together with
  a fast reader and writer (the NumPy floor's), the reconstruction would allow ~100 MB/s per core.
  Today, processes get there: ×4 = 108 MB/s and ×8 = 172 MB/s wall. Each process's own throughput
  drops as they share the GPU and the busy CPUs.
- **Threads don't scale** (~40 MB/s at 4 or 8): parsing, the greedy pass and NumPy's small calls hold
  the GIL. MLX's evaluation may release it, but too little of the work is on the GPU to matter, so
  `releases_gil=False`. Threads are correct, though: 16 threads, including 16 hitting the first load
  at once, give the reference's bytes.
- **Live** (one shot every ~30 s) is met with a wide margin (median latency 16 ms; the largest
  shot, 24 MB, takes 0.4 s, mostly reading). **Bulk** at ~100 MB/s is met with 4 processes.

## Parallelism within one shot

The GPU search *is* the backend's within-shot parallelism: every x1 of the shot is searched at once
(8,192 per batch). Why that is safe, when MATLAB's match is sequential:

- A pulse used by a hit is marked, and a marked pulse can't be chosen again. Marks only ever
  *remove* candidates. An x1's **first choice** is the first valid x2, then the first valid y pair,
  in search order, ignoring marks. If none of its pulses was marked by an earlier hit, then every
  candidate before it fails whatever is marked, and MATLAB makes the same choice. The same argument
  covers "no x2" and "no y pair": removing candidates can't create one.
- So only an x1 whose first choice claims a pulse that an earlier x1's hit marks can differ (it is
  **contested**). Those are recomputed exactly, in x1 order, against the final hits of the x1 rows
  that can reach the same pulses. Pulses lie within ±18 rows of their x1, so only x1 rows up to 36
  rows apart interact.
- A recomputed x1 whose new hit marks a pulse that a later x1's first choice claims makes that x1
  contested too (a cascade). An x1 that is never queued keeps a first choice whose pulses no earlier
  final hit marks, so its choice is exact by the first point.
- The phantom row, `floor(N/4)` and the final stable sort are formed from the whole shot's final
  choices, exactly as the reference forms them.

The generic split (`split.py`, cutting at gaps longer than the match window) is the NumPy floor's.
This backend keeps no state between calls, so it can reconstruct split pieces like any other
backend. That is measured in the final serial run, as the brief says.

## Packaging (scratch PyInstaller builds under `.ai/temp/mlx-pyi/`, PyInstaller 6.22.3)

A minimal app that converts one file: NumPy and `helab.convert` only, **31.0 MB** (onedir); plus
the mlx backend and MLX, **271.0 MB** (+240 MB; 14.9 → 94.7 MB gzipped). Almost all of it is
`mlx/lib/mlx.metallib` (214 MB, the precompiled Metal kernels) and `libmlx.dylib` (21.7 MB). The
wheels download at 78.1 MB (`mlx-metal`) + 0.7 MB (`mlx`).

What the build needed (stage 4's spec will too):

- `--hidden-import helab.convert.backends.<name>` for **every** backend, the reference included:
  `_MODULES` imports them by name, which PyInstaller can't see. Without it even the reference
  backend fails in the frozen app (`No module named 'helab.convert.backends'`).
- `--collect-submodules mlx --collect-data mlx`: the extension imports `mlx._reprlib_fix` and
  `mlx.__array_api_info` from C, and needs `mlx.metallib` beside `libmlx.dylib`. Without them the
  frozen app stops at `ImportError: Encountered an error while initializing the extension`.
- With both, the frozen app reports the backend available and writes the same bytes.

MLX 0.32.4 has wheels for macOS 14, 15 and 26 on arm64 only (none for macOS 13 or Intel).
