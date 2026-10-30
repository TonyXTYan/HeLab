# MATLAB's own converter, timed like the backends

2026-10-30, Side (the Assistant on Ground), at Tony's request in Chat ("can you do a timed matlab
benchmark and document findings?"). Stage 2's [benchmark](../2026-10-29-claude-txy-bench/results.md)
timed every Python backend but never MATLAB itself; this fills that gap.

## Method

- **Data:** the same 309 sample shots (`~/HeLab-samples/txy-v1`, 217.5 MB of raw text), copied and
  checked by SHA-256 into `.ai/temp/txy/matlab-bench/` (never the share, the sample set or `legacy/`).
- **MATLAB:** R2025b, headless (`-nodisplay -batch`), one process per repeat, 3 repeats per
  configuration. The generated script calls exactly what the converter calls per shot, with
  `tic`/`toc` around each part: `dld_read_5channels_reconst_multi_imp(file,1,0,1,0)` (read +
  reconstruct) and `dlmwrite(..., 'precision', 8)` (write). One untimed shot first, as the Python
  backends' warm-up. Variants: 2019 (`legacy/tdc_autoconverter`, the lab's running path; empty
  results not written) and the 2023 lab edit (`DLD_front_panel`'s `dld_raw_to_txy`), on one core
  (`-singleCompThread`, comparable to the per-core table) and, for 2019, with MATLAB's default
  implicit multithreading (as the lab runs it).
- **Python, same window:** numpy and the reference, 3 serial repeats each through stage 2's
  [`bench.py`](../2026-10-29-claude-txy-bench/bench.py) (`matlab-2019`). Cython couldn't run: its
  kernel isn't built on Ground (no Cython in Ground's venv, not installed for this).
- **Machine:** M4 Max (12 performance + 4 efficiency cores), macOS 26.7. **Busy:** load average
  15–23 throughout (two floors running their suites), against 4–5 in stage 2's run. So every
  number here is lower than on an idle machine; the ratios between rows, measured in the same
  10 minutes, are the useful part.
- Scripts: [`bench_matlab.py`](bench_matlab.py), [`run.sh`](run.sh). Raw: `timing/runs.jsonl`
  (MATLAB), `timing/backends.jsonl` (Python), `timing/shots-*.csv` (MATLAB per shot),
  `timing/machine.txt`.

## Results (median of 3, raw MB/s end to end unless noted)

| Converter | MB/s | read + reconstruct | write | latency median / max | hits |
|---|---|---|---|---|---|
| MATLAB 2019, one core | **21.7** (20.2–21.9) | 50 MB/s (4.3 s) | 38 MB/s (5.7 s) | 22 / 255 ms | 1,480,691 |
| MATLAB 2019, default threads | 22.6 (21.1–24.8) | 55 MB/s | 39 MB/s | 22 / 231 ms | 1,480,691 |
| MATLAB 2023 lab edit, one core | 18.9 (18.7–22.8) | 34 MB/s | 43 MB/s | 28 / 596 ms | 1,203,156 |
| numpy (HeLab's default), same window | **76.5** (58.7–82.2) | read 355, reconstruct 210 | 197 MB/s | 7 / 83 ms | 1,480,691 |
| reference (Python port), same window | 11.9 (11.7–12.0) | reconstruct 13 | 209 MB/s | 43 / 505 ms | 1,480,691 |

Plus **MATLAB's start: 6–8.5 s** per process (median 7.6 s) before the first shot.

## Findings

1. **numpy is ~3.5× MATLAB per core** under the same load (76.5 against 21.7 MB/s); on an idle
   machine stage 2 measured numpy at 119 MB/s, so MATLAB idle is likely ~30–35 MB/s (scaled by
   numpy's own slowdown, an estimate). Cython (170 MB/s idle, 1.4× numpy) would be ~5× MATLAB.
   On 12 processes numpy reached 1,050 MB/s idle, ~30–50× one MATLAB.
2. **MATLAB spends most of its time writing.** `dlmwrite` takes 57 % of a 2019 conversion (38 MB/s,
   against HeLab's 180–210 MB/s for the same text); reading and reconstructing run at ~50 MB/s.
   MATLAB's vectorised reconstruction is ~4× our plain-Python reference (which is the checker, not a
   converter), and numpy's is another ~4× beyond it.
3. **MATLAB's multithreading doesn't help** (22.6 against 21.7 MB/s): the work is per-shot text I/O
   and small array operations, not large matrix maths.
4. **Latency per shot:** MATLAB 22 ms typical and up to 0.26 s (2019) or 0.6 s (2023, its x1
   dead-time pass) on the largest shots; numpy 7 ms typical, 83 ms worst here. Both are far inside
   Live's needs; MATLAB's 7.6 s start matters only when it is launched per batch.
5. **The 2023 lab edit is ~13 % slower** than 2019 in MATLAB (more work in read + reconstruct, fewer
   hits to write), whereas in HeLab it is faster (fewer x1 after the dead-time cut: numpy 140 against
   119 MB/s in stage 2).
6. **Correctness, independently confirmed:** MATLAB R2025b's 2019 converter reproduces the sample
   set's archived TXY for 303 of 309 shots, every repeat: the same 303 that HeLab's `matlab-2019`
   matches. So the 6 that differ are faults of those archived files (as stage 1 proved), not of the
   port. The 2023 edit matches 9 (it changes the output by design). Hit counts equal HeLab's exactly.

## Not measured

- MATLAB's watcher loop (`tdc_auto_convert.m`'s polling and waits), only the conversion itself.
- MATLAB on a lab PC (older CPUs; the per-core ratio should hold roughly).
- Cython in this window (not built on Ground); an idle-machine rerun would firm up the absolute
  numbers.
