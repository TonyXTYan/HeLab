# Results: TXY converter stage 2, final timings and recommendation (Tally, 2026-10-29)

Branch `agent/txy-bench` from `ed35099` (all five backends landed on `dev/v0.0.7`), every backend
built into this floor's venv ([notes.md](notes.md), step 1). MB is 10^6 bytes of **raw** file.

## Summary

- **All six backends give the reference's bytes** on everything, built together on the landed
  code. The full suite passes with none of them skipped.
- **Default: `numpy`.** It needs nothing beyond HeLab's own dependencies and adds ~31 kB to the
  build. It runs at **119 MB/s on one core** end to end, 9.2× the reference's 13 (21× on reconstruction alone). With 12 warm
  processes it reaches **1,049 MB/s**. That clears both targets on this Mac: Live (a shot every
  ~30 s; the worst shot takes 58 ms) and bulk (~100 MB/s).
- **Optional fast backend: `rust`.** It has the fastest reconstruction (1,056 MB/s) and the
  smallest build cost of the compiled backends: ≈ 0.47 MB, one abi3 wheel per OS and arch, no
  runtime dependency, no JIT. `cython` is as fast (915) and smaller (257 kB), but needs one
  build per Python minor version and MSVC on Windows. `numba` is as fast (869), but adds
  +145 MB (+52 MB zipped) and takes 1.1 s to compile on first use.
- **`mlx` should go (A9.1).** On every measure it is slower than NumPy on the CPU: reconstruction
  111 vs 279 MB/s, 72 vs 119 MB/s end to end. It adds +240 MB and runs only on Apple Silicon.
- **The text I/O is now the bottleneck, not the backend.** With a compiled backend, reading
  (~560 MB/s) and writing (~340 MB/s) are 80–83 % of a conversion. So rust, cython and numba are
  only **1.43–1.49× numpy** per core end to end, although they reconstruct 3–4× faster.
- **Parallelism:**
  - **Across shots in processes** is the lever: about 9× on 12 processes.
  - **Threads** stop at ~400 MB/s: in practice the text I/O, the parse as well as the format,
    holds the GIL.
  - **Within one shot**, `split.py` never helps the fast backends on the sample shots. On the
    24 large shots it halves their reconstruction speed. It pays only for the reference, and on
    a dense 25 MB shot for numpy and mlx (2.2×).
- **What the numbers can't decide:** see the end. In short: whether any compiled backend is
  worth shipping, since NumPy already meets both targets here; rust vs cython; and how fast the
  lab PCs are (Windows x86-64, untimed).

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

## How the timings were taken

- **Machine:** Mac16,5, Apple M4 Max with 16 cores (12 performance + 4
  efficiency), 128 GiB (137 GB), macOS 26.7 (25G229), on AC power. Python 3.13.15, NumPy 2.5.4,
  numba 0.68.1, MLX 0.32.4, Cython 3.3.0 (Apple clang 21), Rust 1.99.1 (PyO3 0.30, `lto = "fat"`).
  Commit `a206197`. Details in [`timing/machine.txt`](timing/machine.txt).
- **Idle check (step 3):** CoCo confirmed every other agent idle and gave the go at 04:18. No
  HeLab GUI and no pytest were running.
  - The brief's `pgrep -fl "HeLab|helab"` can't show the GUI: it matches 7 processes, every
    shell and Python with a HeLab folder in its path. The narrower check (`HeLab.app/Contents/MacOS`,
    `bin/helab`, `-m helab`) found none.
  - **The load did not settle below 2.** It was 3.9–4.9 for the full 15 minutes
    ([`timing/load_wait.log`](timing/load_wait.log)). The cause: one Safari tab's web-content
    process held 88–96 % of a core throughout, plus WindowServer at ~40 % and App Tamer at
    ~40–50 %. These are not agents, so I recorded it and carried on, as the brief says.
  - The load before each run was 4.5–8.3 (median 5.9). That includes this run's own process
    pools: the 1-minute average lags.
  - Repeats agree closely: most spreads are within ±3 %, and the largest are ~10 % (12–16
    processes; numpy ×12 spans ~9 %). So the idle load from one busy core barely shows below 12
    workers. At ×12 the workers fill the 12 performance cores that tab shares, and at ×16 every
    core, so **both the ×12 and ×16 columns understate an idle ceiling**.
- **Run:** [`run_all.sh`](run_all.sh), 04:33–04:43, one backend at a time. Each measure was
  repeated 3 times, each repeat in a fresh process. Each cell below is the **median (min–max)**
  of the 3.
  - Every run goes through stage 1's harness, `helab.convert.timing.time_shot`, via
    [`bench.py`](bench.py): read = file read + `parse_raw`; reconstruct; write = `format_txy` +
    `write_atomic` (fsync, rename, folder fsync).
  - Data: all 309 sample shots (217.5 MB raw, 1,480,691 hits under `matlab-2019`). "Large" is
    the 3 largest of each set by raw bytes (24 shots, 101.7 MB); "small" is the other 285.
  - **"Large" means large, not dense.** The large shots hold ~2,900 hits per raw MB against
    ~10,200 for the small ones. The 3 largest of all (2019-halos d2227, d2134, d1937, 23–24 MB)
    have only 15–20 hits each under `matlab-2019`. So the "large" reconstruct and write rates are
    high because those shots are sparse. For a dense worst case, see the 25 MB `time_large` table
    under [Within one shot](#within-one-shot-splitreconstruct_split).
  - The sample files sit in the page cache after the first run, so "read" is mostly the parse.
  - Raw data: `timing/runs.jsonl` (288 runs), `timing/first_call.jsonl`, `timing/time_large.log`,
    `timing/run.log`. The tables come from [`summarise.py`](summarise.py), whose full output is
    in `timing/tables.md`.
- **Warm-up:** every serial, thread and within-shot run first converts one shot untimed, so
  import, JIT and GPU start stay out of the throughput. First calls are measured on their own,
  below.
  - "Warm" process pools start their workers and warm each one before the clock starts: the
    steady state of long-lived helpers.
  - "Cold" pools are `timing.time_shots(PROCESSES)` as it is, with pool start, imports and
    first calls inside the wall time: a one-off folder conversion.
- numba's cache is in `.ai/temp/txy/numba-cache` (`NUMBA_CACHE_DIR`), warm except where marked.

## Serial, one core (all 309 shots, raw MB/s)

| backend | read | reconstruct | reconstruct small | reconstruct large | write | **total per core** |
|---|---|---|---|---|---|---|
| reference | 545 (545–556) | 14 (14–14) | 10 (10–10) | 24 (24–24) | 300 (286–308) | 13.0 (12.9–13.1) |
| numpy | 555 (548–558) | 279 (276–281) | 204 (200–205) | 483 (480–487) | 332 (322–336) | **119.1** (116.9–120.1) |
| numba | 569 (549–570) | 869 (858–869) | 648 (639–649) | 1,414 (1,406–1,418) | 338 (325–341) | **170.6** (165.0–171.4) |
| cython | 556 (541–557) | 915 (905–924) | 723 (710–730) | 1,315 (1,311–1,324) | 335 (325–336) | **170.2** (165.8–170.6) |
| rust | 566 (551–567) | 1,056 (1,046–1,059) | 761 (752–763) | 1,881 (1,875–1,907) | 343 (331–343) | **177.7** (172.7–177.8) |
| mlx | 544 (541–556) | 111 (111–114) | 77 (77–79) | 223 (223–224) | 322 (311–322) | **72.0** (71.0–72.6) |

Where a conversion's time goes (one serial run, seconds for all shots: read / reconstruct / write;
the read and write share):

| backend | read | reconstruct | write | read + write |
|---|---|---|---|---|
| reference | 0.40 | 15.66 | 0.73 | 7 % |
| numpy | 0.40 | 0.79 | 0.68 | 58 % |
| numba | 0.38 | 0.25 | 0.64 | 80 % |
| cython | 0.40 | 0.24 | 0.67 | 82 % |
| rust | 0.38 | 0.21 | 0.63 | 83 % |
| mlx | 0.40 | 1.92 | 0.68 | 36 % |

`matlab-2023-lab-edit` (serial; fewer x1 after the dead-time cut, so faster):

| backend | reconstruct | total per core | latency max (ms) |
|---|---|---|---|
| reference | 17 (17–17) | 15.4 (15.4–15.5) | 465 |
| numpy | 361 (348–362) | 139.8 (133.7–140.2) | 60 |
| numba | 969 (968–981) | 181.4 (181.4–187.5) | 56 |
| cython | 975 (972–996) | 180.5 (180.1–187.1) | 59 |
| rust | 1,045 (1,038–1,053) | 185.9 (182.2–190.7) | 55 |
| mlx | 155 (151–156) | 90.7 (89.8–92.2) | 72 |

## Latency per shot (serial; read + reconstruct + write, ms)

| backend | all: median | all: max | small: median | small: max | large: median | large: max |
|---|---|---|---|---|---|---|
| reference | 39.4 | 462 (458–465) | 38.0 | 246 | 115.7 | 462 |
| numpy | 4.4 | 58.4 (58.0–60.7) | 4.4 | 28.9 | 9.6 | 58.4 |
| numba | 3.3 | 54.6 (54.3–54.7) | 3.2 | 15.0 | 7.2 | 54.6 |
| cython | 3.2 | 61.7 (58.8–62.4) | 3.2 | 14.7 | 7.3 | 61.7 |
| rust | 3.1 | 53.5 (53.2–56.1) | 3.0 | 15.4 | 7.5 | 53.5 |
| mlx | 7.5 | 72.2 (70.2–76.8) | 7.1 | 49.1 | 17.1 | 72.2 |

The max is the largest shot (2019-halos d2227, 24.1 MB, 1.59 M rows) for every backend. It is
nearly all reading: with rust, 44 ms read, 5 ms reconstruct and under 1 ms write, because it has
only 20 hits. **Live's worst case is a dense shot, not this one:** the dense 25 MB shot below takes
144 ms with rust and 305 ms with numpy (reconstruct and format, before reading).

## First call (fresh interpreter, ms; [`first_call.py`](first_call.py))

`convert_raw` (no file written) on a small shot (2023-02 d1210, 24 kB) and on the largest (24.1 MB).
"Backend start" is `get_backend(b).unavailable(profile)`: it imports the backend module and its
package, and checks the GPU for mlx.

| backend | import `helab.convert` (NumPy included) | backend start | small: 1st | small: 2nd | large: 1st | large: 2nd |
|---|---|---|---|---|---|---|
| reference | 26.0 | 0.4 | 3.2 | 3.0 | 433 | 423 |
| numpy | 26.0 | 0.5 | 0.6 | 0.4 | 58.2 | 48.9 |
| numba, warm cache | 28.1 | 76.2 (`import numba`) | **99.2** (cache load) | 0.3 | 54.9 | 44.7 |
| numba, empty cache | 25.8 | 73.9 | **1,141** (1,122–1,185; compile) | 0.3 | 54.3 | 44.9 |
| cython | 27.4 | 2.8 | 0.4 | 0.2 | 57.9 | 48.7 |
| rust | 28.4 | 2.1 | 0.4 | 0.2 | 53.2 | 43.4 |
| mlx | 28.5 | 28.3 (MLX + Metal) | 8.0 | 1.5 | 72.3 | 62.4 |

Every first conversion is ~10 ms slower than the second (page faults, NumPy's first calls). Only
numba has a real start-up cost: about 175 ms per process with a warm cache **and a warm OS file
cache** (these runs came back to back), and 1.2 s the first time on a machine or after an upgrade.
The Reviewer (Ibis) saw ~0.6 s after a few idle minutes, once the OS had dropped llvmlite's
126 MB library from its file cache. A HeLab helper started after idle time pays the latter.

## Across shots: processes (wall MB/s, all 309 shots)

Warm pool (workers started and warmed before the clock: long-lived helpers):

| backend | ×1 | ×2 | ×4 | ×8 | ×12 | ×16 |
|---|---|---|---|---|---|---|
| reference | 13 | 26 (25–26) | 50 | 99 | 132 (130–133) | 139 (135–139) |
| numpy | 118 (115–119) | 230 (219–231) | 422 (422–430) | 792 (774–800) | **1,049** (1,023–1,116) | 1,149 (1,125–1,168) |
| numba | 163 (162–166) | 313 (305–326) | 594 (585–595) | 1,065 (1,040–1,076) | 1,443 (1,433–1,467) | 1,472 (1,431–1,550) |
| cython | 165 (161–169) | 325 (320–328) | 588 (583–595) | 1,064 (1,050–1,129) | 1,363 (1,354–1,464) | 1,525 (1,500–1,638) |
| rust | 167 (163–173) | 318 (317–333) | 629 (609–631) | 1,098 (1,054–1,133) | **1,466** (1,452–1,537) | 1,590 (1,565–1,719) |
| mlx | 71 (70–73) | 131 (126–132) | 254 (248–260) | 388 (372–399) | 443 (443–444) | 453 (443–468) |

Per-core throughput in the same runs (raw bytes over the sum of each worker's stage times). It falls
as the efficiency cores and shared memory bandwidth come in:

| backend | ×1 | ×2 | ×4 | ×8 | ×12 | ×16 |
|---|---|---|---|---|---|---|
| reference | 13 | 13 | 13 | 12 | 12 | 10 |
| numpy | 119 | 117 | 109 | 104 | 93 | 79 |
| numba | 166 | 160 | 153 | 141 | 129 | 106 |
| cython | 168 | 165 | 154 | 142 | 127 | 109 |
| rust | 171 | 164 | 163 | 145 | 136 | 112 |
| mlx | 71 | 66 | 64 | 49 | 38 | 29 |

mlx stops at ~450 MB/s because every process shares one GPU (and pays ~2.5 ms per dispatch).

Cold pool (`time_shots(PROCESSES)` as it is; pool start, imports and first calls in the wall time):

| backend | ×1 | ×4 | ×12 |
|---|---|---|---|
| reference | 13 | 50 (49–50) | 126 (122–127) |
| numpy | 111 (111–113) | 374 (372–375) | 761 (741–768) |
| numba | 135 (133–140) | 318 (305–318) | **399** (386–401) |
| cython | 158 (157–164) | 524 (522–525) | 996 (949–999) |
| rust | 161 (160–162) | 530 (517–532) | 958 (957–969) |
| mlx | 66 (62–67) | 221 (209–226) | 346 (342–358) |

numba loses most in a cold pool: each worker imports numba and loads its cache (~175 ms), against
~0.2 s of work per worker at ×12.

## Across shots: threads (wall MB/s)

| backend | ×1 | ×4 | ×8 |
|---|---|---|---|
| numpy (`releases_gil` False; for comparison) | 119 (118–120) | 218 (209–218) | 193 (189–193) |
| numba | 169 (167–171) | 351 (347–370) | 403 (390–405) |
| cython | 172 (166–174) | 356 (353–357) | 390 (384–399) |
| rust | 175 (175–179) | 366 (356–375) | 404 (403–406) |

Threads stop at ~400 MB/s, against ~1,080 for 8 processes, because **the text I/O, parse and format,
holds the GIL in practice**. The per-thread stage rates show it. With rust at ×1 / ×4 / ×8 threads,
read falls 561 / 268 / 128 MB/s and write 338 / 171 / 95, while reconstruct (GIL released) only
slips 1,056 / 822 / 731. In 8 processes read stays at ~430 and write at ~290. The NumPy floor
made the parse's digit loop release the GIL, but the measured read stage scales no better than
the write. `format_txy`'s `%` formatting holds the GIL throughout. A GIL-free parse **and** formatter would make threads scale (handoff A~1).

## Within one shot (`split.reconstruct_split`)

The 24 large shots (0.4–24 MB), each split into up to N pieces on a warmed pool: threads for
numba, cython and rust (they release the GIL), processes for the others. Reconstruct MB/s, and the
max latency in ms:

| backend | serial: rec | serial: max | ×2: rec | ×2: max | ×4: rec | ×4: max | ×8: rec | ×8: max |
|---|---|---|---|---|---|---|---|---|
| reference | 24 | 462 | 38 | 249 | 41 | 194 | 43 | **191** |
| numpy | 483 | **58** | 378 | 91 | 398 | 85 | 395 | 85 |
| numba | 1,414 | **55** | 720 | 68 | 724 | 67 | 726 | 67 |
| cython | 1,315 | **62** | 741 | 67 | 734 | 68 | 743 | 67 |
| rust | 1,881 | **54** | 780 | 68 | 783 | 68 | 794 | 67 |
| mlx | 223 | **72** | 228 | 99 | 228 | 93 | 234 | 93 |

A dense 25 MB shot (2022-07 he3he4 d1 repeated 10×, 1.55 M rows; the NumPy floor's
`time_large.py`, processes for every backend). Times are reconstruct + format, in ms, median of 3;
the reference uses 2 copies (5 MB):

| backend | whole | split ×2 | ×4 | ×8 | best gain |
|---|---|---|---|---|---|
| reference (5 MB) | 598 | 302 | 171 | 136 | 4.4× |
| numpy | 305 | 222 | 172 | 141 | 2.2× |
| numba | 301 (a) | 137 | 125 | 120 | (a) |
| cython | 129 | 134 | 123 | 120 | 1.08× |
| rust | 144 | 130 | 122 | 118 | 1.22× |
| mlx | 493 | 318 | 254 | 217 | 2.3× |

(a) numba's "whole" is the script's first numba call in a fresh process, so it includes the ~175 ms
start (first-call table). The true gain is about cython's.

So split costs more than it saves for every fast backend on real sample shots. It sorts the whole
shot itself before cutting, then each piece is handed over (pickled for processes, or the backend's
own sort again), and the final merge is serial. For the compiled backends the shot's reconstruction
is only ~15–60 ms to begin with. It pays only for slow backends, and for dense shots several times
the largest sample.

## Size added to a PyInstaller build

| backend | added | how known |
|---|---|---|
| numpy | ~31 kB (Python source: `numpy_backend.py`, `fastio.py`, `split.py`; NumPy is already bundled) | estimated (NumPy floor) |
| numba | **+145 MB** on disk, **+52 MB** zipped (`libllvmlite.dylib` alone is 126 MB) | **measured**: scratch build with and without (numba floor, macOS arm64) |
| cython | ~257 kB (`_kernel.cpython-313-darwin.so`: 257,360 B here; 75 kB gzipped); links only libSystem | estimated from the binary (cython floor; same size rebuilt here) |
| rust | ≈ 0.47 MB (`helab_convert_rs.abi3.so`: 474,128 B here) | estimated from the wheel (rust floor; same size rebuilt here) |
| mlx | **+240 MB** on disk, **+80 MB** gzipped (`mlx.metallib` is 214 MB) | **measured**: scratch build (mlx floor) |

## Against the targets (Q6.9)

- **Live, a shot every ~30 s:** met by every backend, the reference included. The worst sample shot
  is 0.46 s with the reference and 54–72 ms with the others; that shot is sparse and mostly reading.
  The dense 25 MB shot takes 118–144 ms (compiled), 305 ms (numpy), 493 ms (mlx) and ~3 s
  (reference, extrapolated from 5 MB) to reconstruct and format. That is still 60× or more under 30 s for
  every backend but the reference. Live doesn't decide the backend.
- **Bulk, faster than raw files cross gigabit (~100 MB/s, at most ~117 MB/s of payload):**

  | backend | one core | processes needed for ~100 MB/s (warm) |
  |---|---|---|
  | numpy | 119 MB/s | 1 |
  | numba, cython, rust | 170–178 MB/s | 1 |
  | mlx | 72 MB/s | 2 |
  | reference | 13 MB/s | 8 |

  On this Mac, NumPy on one core already converts faster than gigabit delivers raw files, with
  ~15 cores to spare. Q6.9's premise (convert as they're read, store no TXY) holds for the
  converter's speed with any backend but the reference.

## Recommendation

1. **Default backend: `numpy`**, everywhere (Q9.2: NumPy alone always works).
   - It is byte-identical on everything.
   - It needs no compiler, no extra package and no per-platform build, and adds ~31 kB.
   - It meets both targets on one core here.
   - HeLab should convert across shots in its helper processes (NumPy floor A~2), not in
     threads, and not split a shot.
2. **Optional fast backend: `rust`**, if one ships.
   - It reconstructs fastest: 1,056 MB/s over all shots, 3.8× numpy. The 1,881 MB/s on "large"
     shots flatters it: those are the largest but sparsest shots. On the dense 25 MB shot it
     reconstructs and formats in 144 ms, against numpy's 305.
   - End to end it is 1.49× numpy per core (178 vs 119) and ~1.4× at 12 processes
     (1,466 vs 1,049).
   - It costs ≈ 0.47 MB, and one abi3 wheel per OS and arch serves CPython 3.11–3.14.
   - It has no runtime dependency beyond NumPy, no JIT and a 2 ms start.
   - CI needs Rust and maturin on all three OSes (the rust floor's A~1).
   - Worth it when one core must do more than ~120 MB/s: a slower lab PC at gigabit, a
     10-gigabit link, or re-converting archives. The rust floor's Rust parser (1,910 MB/s) and
     formatter (596 MB/s) are also the obvious way to lift the I/O, which is now 80 % of the time.
3. **`cython`: keep as the alternative to rust, not both** (A9.1).
   - It is the same speed class (915 MB/s reconstruct, 170 end to end), smaller (257 kB), and has
     no JIT.
   - But it needs one binary per Python minor version and OS, and MSVC (VS 2022) on Windows.
   - If stage 4's CI finds Rust easier to build on three OSes than C extensions, drop cython;
     otherwise drop rust. The numbers alone don't choose between them: 15 % on reconstruction,
     4 % end to end.
4. **`numba`: drop** (A9.1).
   - It is as fast as cython and rust, but adds +145 MB (+52 MB zipped).
   - Every process pays ~175 ms to start (~0.6 s after idle time, once the OS file cache is cold),
     and the first compile takes 1.1 s.
   - It pins NumPy below 2.6, and its cold pools are the slowest of the fast backends (399 vs
     ~1,000 MB/s at ×12).
   - It offers nothing the two compiled backends don't, at ~310× rust's size (145 MB vs
     0.47 MB) and ~560× cython's (vs 257 kB).
5. **`mlx`: drop** (A9.1).
   - It is slower than NumPy's CPU algorithm on every measure: reconstruction 111 vs 279 MB/s,
     end to end 72 vs 119.
   - It tops out at ~450 MB/s across processes (one GPU), adds +240 MB (+80 MB zipped), and runs
     only on Apple Silicon with macOS 14 or later.
   - The greedy match stays on the CPU, and the per-dispatch cost outweighs the parallel search
     at these shot sizes.
6. **`reference`: keep** as the readable specification and test oracle, never as the app's
   converter (13 MB/s).

**Input for stage 4's packaging floor**, if Tony keeps every backend for now (Q9.2):

| backend | build in CI | runtime | platforms |
|---|---|---|---|
| numpy | nothing | NumPy | all |
| rust | Rust toolchain + `maturin build --release` (maturin-action), one abi3 wheel per OS/arch; `hiddenimports` `helab_convert_rs` | NumPy | macOS arm64/x86_64, Windows x64, Linux x86_64 (default target, no AVX: fine on Sandy Bridge) |
| cython | Cython + setuptools + a C compiler (clang, GCC, MSVC 2022) with `-ffp-contract=off` / `/fp:precise`; `native/cython/build.py` per Python minor version | NumPy | all three, one build each |
| numba | add numba and llvmlite to the lock (pins NumPy < 2.6); `hiddenimports`; warm the cache in a helper | numba, llvmlite | all three (wheels) |
| mlx | `collect_submodules('mlx')`, `collect_data_files('mlx')` | MLX | macOS ≥ 14 arm64 only; GPU tests likely can't run on GitHub's macOS runners |

Every backend module (the reference included) needs `hiddenimports`, since `_MODULES` imports them
by name.

## What the numbers can't decide

- **Whether any compiled backend is worth shipping.** NumPy already meets both targets on this Mac,
  so a compiled backend buys margin (1.5× per core), not a target. That is Tony's call on size and
  CI effort against headroom (A9.1).
- **rust vs cython.** They are within 15 % on reconstruction and 4 % end to end. Choose on CI and
  packaging effort, not speed.
- **The lab PCs.** Everything here is one M4 Max. The lab PCs are older Windows x86-64 machines
  (the Lab Side PC is a Sandy Bridge), where one core may well be 3–5× slower. At
  that speed NumPy on one core could fall below 100 MB/s, and a compiled backend or 2–4 processes
  would matter more. A timing run there would settle it (M~1). None of the compiled backends has
  been built or run on x86-64 yet: CI skips their tests today.
- **The ×12 and ×16 columns.** At ×12 the workers fill the 12 performance cores, and at ×16 every
  core, all shared with the Safari tab's busy core. So both understate a truly idle machine's
  ceiling (numpy ×12 spans ~9 %). The ×1–×8 columns are unaffected within the spreads shown.
- **The write stage's fsyncs on other disks.** Here the atomic write is cheap on an internal SSD.
  On a network share or an HDD the write stage would be set by the disk, whatever the backend.
