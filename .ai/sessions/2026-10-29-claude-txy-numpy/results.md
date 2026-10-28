# Results: the NumPy backend, fast I/O and the within-shot split (indicative timings)

**Machine:** Apple M4 Max, 16 cores, macOS 26.7, Python 3.13, NumPy 2.5.4.

**Load:** **busy**. Four other backend floors (Numba, Cython, Rust, MLX) were building and
timing at the same time, with a load average of 11–19 over the runs (each run's load is below).
These are my timings: the final ones are taken later, serially, on an idle machine.

**Data:** all 309 sample shots (217.5 MB raw), profile `matlab-2019`, through `dev/txy/time_samples.py`
(JSON in `timing/`) unless named. MB/s is SI (10^6 bytes) of **raw** input. "Small" is 285 shots,
"large" the 3 largest of each set (24 shots). The read stage is the file read plus the parse;
the write stage is formatting plus the atomic write (fsync, rename, folder fsync).

The parallel runs were taken at `ea29972` (SWAR reader, block-`%` writer); the table formatter
that followed (`e539e5e`) is the same speed serially (374 vs 385 MB/s).

## Byte identity

| Check | Result |
|---|---|
| 39 synthetic cases × 2 profiles vs MATLAB's output and outcome | all identical (tests) |
| `tests_sample_data/` × 2 profiles vs the reference | all identical (tests) |
| `check_samples.py --positions all --backend numpy` (matlab-2019) | 303 identical + 6 proved exceptions (cut 1, variant 2, empty 3), 0 differ: the reference's table |
| `check_samples.py --profile matlab-2023-lab-edit --reference-dir <stage 1's MATLAB 2023 runs>` | 32 of 32 identical to MATLAB's own 2023 output |
| `compare_backends.py`: 309 shots × 2 profiles, numpy vs reference | 618 of 618 identical |
| `compare_backends.py --split`: the same, cut at every safe gap | 618 of 618 identical |
| Random dense files (integer, fractional, ~2^53, ±Inf, NaN times; varied profiles; split too) | over 7,000 files, 0 differences; the exact pass ran tens of thousands of times, phantom rows made |

## Timings

| Measure | Value | Run (load) |
|---|---|---|
| Reconstruct, serial, all shots | **258 MB/s** (reference: 13.1, ×20) | serial (16.0) |
| Reconstruct, small / large shots | 191 / 433 MB/s | serial (16.0) |
| Total per core (read + reconstruct + write), serial | **109 MB/s** (reference: 12.2) | serial (16.0) |
| Read stage (read + parse), serial | 502 MB/s | serial (16.0) |
| Write stage (format + atomic write), serial | 304 MB/s (fsync-noisy: 134 in a run at load 19.6) | serial (16.0) |
| Parse only: stage 1 → fastio, 1 thread / 8 threads | 72 → **608** / 1,081 MB/s | bench_io (16.8) |
| Format only: stage 1 → fastio, 1 thread / 8 threads | 179 → **374** / 470 MB/s | bench_io (16.8) |
| Atomic write only (fsync, rename, folder fsync) | 2,654 MB/s | bench_io (16.0) |
| Processes across shots, 4 / 8 workers: wall | **332 / 558 MB/s** | processes (19.1 / 18.7) |
| Processes, per-core total (sum of stage times) | 98 / 94 MB/s | processes |
| Threads across shots, 4: wall | 163 MB/s (GIL-bound Python parts; `releases_gil` False) | threads (18.7) |
| Within-shot, samples, 4 processes: wall | 99 MB/s (most shots are under the 50,000-row piece minimum, so not cut) | within-shot (18.7) |
| Within-shot, one large dense shot (25 MB, 1.55 M rows: 2022-07 d1 ×10), numpy | whole 325 ms; split ×4 189 ms, ×8 166 ms (2.0×) | time_large (15.7) |
| Within-shot, the same ×2 (5 MB), reference | whole 643 ms; split ×8 151 ms (4.3×) | time_large (15.7) |
| Latency per shot, median / max, serial | 4.6 / 61 ms (reference 41.7 / 483) | serial (16.0) |
| Latency, small shots median / max | 4.5 / 31 ms | serial |
| Latency, large shots median / max | 10.5 / 61 ms | serial |
| First call: import of the backend | 35–37 ms (a fresh process, helab.convert and NumPy included) | bench_io |
| First call: first vs second conversion | 0.38 MB: 4.1 vs 3.7 ms; 24 MB: 62 vs 51 ms (no JIT; warm caches only) | bench_io |
| Size added to a PyInstaller build | **~31 kB** of Python source (`numpy_backend.py` 18 kB, `fastio.py` 7 kB, `split.py` 6 kB), estimated: NumPy is already bundled (a HeLab dependency; 25 MB in the venv) | estimate |

Where the time goes now (serial, all shots): read 0.43 s, reconstruct 0.84 s, write 0.72 s of
1.99 s. The reconstruct stage is no longer dominant: formatting (~0.58 s of the write) is the
largest piece of I/O, then the parse.

## Against the targets (Q6.9)

- **Live** (a shot every ~30 s): 5 ms median, 61 ms max per shot. Easily met.
- **Bulk ~100 MB/s:** met serially on one core (109 MB/s here, under load), and 330–560 MB/s
  with 4–8 processes.

## Recommendation (for the stage 2 Reviewer)

NumPy as the **default backend that works everywhere**. It needs no compiled code and adds
nothing to the build but its Python files. It is byte-identical on everything above, ~20× the
reference's reconstruction and above the bulk target on one core. Parallelism: across shots in
processes (HeLab's helpers already are). Within-shot splitting pays only for large dense shots,
and for slow backends.
