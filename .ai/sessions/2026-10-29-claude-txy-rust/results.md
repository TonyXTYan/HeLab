# Results: rust backend timings (Ferrous, 2026-10-29)

**Machine**: Apple M4 Max, 16 cores (arm64), macOS 26 (Darwin 25.6), Python 3.13.15, rustc 1.99.1
(Homebrew), PyO3 0.30.1, numpy crate 0.30.0, maturin 1.15.0; release build (`lto = "fat"`,
`codegen-units = 1`).
**What was running**: four other stage-2 backend floors (numpy, numba, cython, mlx) on the same
machine, each with its own builds, tests and timings; load average 8–13 throughout (given per row).
So these are indicative: the final timings are taken later, serially, on an idle machine.
**Data**: all 309 sample shots (217.5 MB raw; "large" = the 3 largest of each set, 24 shots,
101.7 MB; "small" the other 285, 115.8 MB). Profile `matlab-2019` unless stated. MB = 10^6 bytes of
raw file, per second.

Harness: `dev/txy/time_samples.py --positions all --backend rust [--parallelism …]` (stage 1's
`time_shots`: read = file read + `raw.parse_raw`, write = `txy.format_txy` + `write_atomic` with
fsyncs) and [`bench_rust.py`](bench_rust.py) (reconstruction alone, best of 3; Rust I/O; first
call). Logs: `.ai/temp/rust/timing2/` (gitignored).

## Byte identity (the bar)

| Check | Result |
|---|---|
| `tests/data/convert/cases/`, 39 cases × 2 variants vs MATLAB | identical, outcomes too |
| `tests_sample_data/` lab pairs, 4 split variants | identical |
| `check_samples.py --positions all --backend rust` (matlab-2019) | 303 identical, cut 1, variant 2, empty 3, **differ 0**; proofs held |
| `compare_samples.py --positions all`, both built-ins, 4 variants (whole, every gap ×1, every gap ×8 threads, auto ×8) vs reference | 309 × 4 × 2: **0 differ** (array bytes and TXY text) |

## Timings

| # | Measure | rust | reference (same run) | Load |
|---|---|---|---|---|
| 1 | Reconstruct, serial, harness, all shots | **969 MB/s** (2nd run 748) | 12.8 MB/s | 8.1 / 10.1 |
| 2 | Reconstruct, serial, harness, small / large shots | 716 / 1,620 MB/s | 9.3 / 22.0 MB/s | 8.1 |
| 3 | Reconstruct alone (bench, best of 3), all / large | 1,105 / 1,902 MB/s | – | 12.6 |
| 4 | Reconstruct, serial, `matlab-2023-lab-edit` | 864 MB/s (large 1,355) | – | 11.3 |
| 5 | Read (file + `parse_raw`, Python, shared) | 71 MB/s | 68 MB/s | 8.1 |
| 6 | Write (`format_txy` + `write_atomic`, Python, shared) | 164 MB/s | 149 MB/s | 8.1 |
| 7 | Total per core, serial (read + reconstruct + write) | **47 MB/s** | 10.0 MB/s | 8.1 |
| 8 | Latency per shot, all (median / max), whole pipeline | 10.1 / 346 ms | 50.1 / 766 ms | 8.1 |
| 9 | Latency, small shots (median / max) | 9.6 / 60 ms | 49.0 / 331 ms | 8.1 |
| 10 | Latency, large shots (median / max) | 28 / 346 ms | 151 / 766 ms | 8.1 |
| 11 | Reconstruct latency alone: < 1 MB shots (279) median / max | 0.29 / 1.97 ms | 37 / 144 ms | 8.1 |
| 12 | Reconstruct latency alone: the 24.1 MB shot (1.59 M rows) | 9.9 ms (read 336 ms, write 0.8 ms) | 426 ms | 8.1 |
| 13 | Across shots, processes ×4: wall (total) | **136 MB/s** | – | 10.4 |
| 14 | Across shots, processes ×8: wall | 226 MB/s | – | 10.9 |
| 15 | Across shots, processes ×16: wall | 258 MB/s | – | 10.9 |
| 16 | Across shots, threads ×4: wall | 46 MB/s | – | 10.9 |
| 17 | Across shots, threads ×8: wall | 48 MB/s | – | 11.5 |
| 18 | Within one shot, Rust threads 1 / 2 / 4 / 8 / 16 (reconstruct alone, all shots) | 1,105 / 1,185 / 1,202 / 1,227 / 1,085 MB/s | – | 12.6 |
| 19 | Within one shot, same, large shots | 1,902 / 2,219 / 2,374 / 2,462 / 2,326 MB/s | – | 12.6 |
| 20 | First call, fresh interpreter: import `helab.convert.backends.rust` (pulls helab.convert, NumPy) / import `helab_convert_rs` / first call / second call | 33 ms / 0.7 ms / 0.11 ms / 0.007 ms (no JIT) | – | 12.6 |
| 21 | Rust raw parser `parse_strict` (report only) vs Python `parse_raw`, in memory | **1,910 MB/s** vs 69 MB/s; 309 of 309 files strict, identical arrays | – | 12.6 |
| 22 | Rust TXY formatter `format_txy` (report only) vs Python, in memory | **596 MB/s** vs 184 MB/s (raw MB/s; 51.9 MB of TXY), identical bytes | – | 12.6 |
| 23 | Size added to a PyInstaller build | ≈ 0.47 MB: the abi3 `.so` (474,128 B with `panic = "unwind"`, review round 1; 440,864 B before, wheel 223,549 B); no other dependency (NumPy is already in). **Estimated from the wheel**, not a scratch build | – | – |

Notes on the rows:

- Rows 1–4: the harness's reconstruct includes the backend lookup, the profile check and the
  Python wrapper per call, which is why small shots (≈ 0.3 ms each) show less than the large ones.
  Before the insertion-sort change the same runs gave 286 MB/s serial (1st build, `timing/`): the
  stable merge sort of nearly-sorted rows was nearly all of it.
- Row 7: with the backend at ~1 GB/s, the Python read (71 MB/s) and write (164) are 93 % of the
  time. With Rust I/O (rows 21, 22) one core would do about 1 / (1/1,910 + 1/1,105 + 1/596) ≈
  **320 MB/s** before disk and fsync, so fast shared I/O (fastio, the NumPy floor's) is what
  matters next.
- Rows 13–15: processes scale with the Python I/O, not the backend; the machine was loaded (≈ 11)
  by the other floors, so ×16 gains little over ×8 here.
- Rows 16–17: threads stay at ≈ 47 MB/s whatever their number: `parse_raw` and `format_txy` hold
  the GIL. The backend itself releases it (`py.detach`), so threads would scale with GIL-free I/O.
- Rows 18–19: splitting one shot gains little (≤ 1.3× at 8 threads): after the cut, what's left
  serial is the sort and the O(N) passes; matching was already the smaller part. Every split is
  byte-identical (tested, and on all samples). Default: 1 thread per shot; split only for one huge
  shot in Live, if ever.
- Row 20: no JIT; the 33 ms is importing HeLab's converter modules and NumPy, common to every
  backend.
- Targets: Live (one shot per ~30 s) is met with a wide margin (largest shot ≈ 0.35 s, almost all
  Python read). Bulk ~100 MB/s: met by 4 processes today (row 13); with Rust or fast NumPy I/O a
  single core should pass it.
