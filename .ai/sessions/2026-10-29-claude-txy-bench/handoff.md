# Handoff: TXY converter stage 2, final timings and recommendation (Worker Tally, 2026-10-29)

Branch `agent/txy-bench` from `ed35099`. Brief: [brief.md](brief.md). Builds and correctness:
[notes.md](notes.md). Tables and recommendation: [results.md](results.md).

## Summary

- **Built in this floor's venv only:** numba 0.68.1 and llvmlite 0.50.0, mlx and mlx-metal
  0.32.4, Cython 3.3.0 (then `native/cython/build.py`), maturin 1.15.0 (then `maturin develop
  --release`, installing `helab-convert-rs` 0.1.0 editable). The list is in notes.md.
- **Correctness with all six backends built on the landed code:** no difference anywhere.
  - Full suite: 8646 passed, 8 skipped (none a backend's), **no RERUN**. mypy strict and pyright
    are clean.
  - `check_samples.py`: 303 identical plus the 6 proved faults for every backend, and 32/32
    against MATLAB's 2023 output.
  - Against the reference: 618/618 for every backend, whole and split.
  - Every floor's own comparison passes.
- **Timings:** serial, 3 repeats, 04:33–04:43, after CoCo's go.
  - The load did not settle below 2: it held at ~4–5 for the 15 minutes. One Safari tab held a
    core at ~90 %, plus WindowServer and App Tamer. This is recorded per run.
  - Repeats agree within a few percent.
- **Recommendation:**
  - **numpy is the default** everywhere: 119 MB/s per core end to end, 1,049 MB/s with 12
    processes, ~31 kB. Both targets are met on one core.
  - **rust is the optional fast backend**: 178 MB/s per core, reconstruction 1,056 MB/s,
    ≈ 0.47 MB, one abi3 wheel per OS. **cython** is its equal alternative; keep one of the two.
  - **Drop numba** (+145 MB, a ~175 ms start per process) **and mlx** (slower than NumPy on the
    CPU, +240 MB, Apple Silicon only).
  - The text I/O is now 80 % of a conversion with a compiled backend.
  - Parallelise across shots in processes: threads stop at ~400 MB/s, and within-shot
    splitting slows the fast backends down.

## Commits

- `6cfde7c` brief; `a206197` steps 1–2 plus the scripts; the final commit adds the timings, results
  and this handoff.
- Session folder only (and scratch under `.ai/temp/`). **No code changed.**

Scripts, all in this folder:

| Script | What it does |
|---|---|
| `bench.py` | One harness run with warm-up, load and machine recorded |
| `run_all.sh` | The whole serial plan |
| `first_call.py` | First-call costs, each in a fresh interpreter |
| `summarise.py` | Builds the tables |
| `compare_split.py` | mlx split with bounded pieces |

## Checks

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest` (all extensions built):
  **8646 passed, 8 skipped, no RERUN**, 181 s.
- `mypy helab/ --strict` (182 files), `mypy tests --strict` (151), `pyright helab tests`: clean.
- No code changed after those runs: the later commits touch only this session folder.

## Found on the way (no code fix needed; for the record)

1. **`pgrep -fl "HeLab|helab"` can't detect the GUI on a floor.** It matches every process whose
   command line has a HeLab folder in it: shells, the floor's own Python, CoCo's `maestri ask`. A
   check that works: `pgrep -fl 'HeLab.app/Contents/MacOS|bin/helab( |$)|-m helab'`. Proposed for
   the next timing brief or `roadmaps/agent-workflow.md`.
2. **The NumPy floor's `compare_backends.py --split` is impractical for mlx.** It splits at every
   safe gap (up to 741,370 pieces in one shot), and mlx pays ~2.5 ms per call, so the run would
   take hours. I stopped it and used `compare_split.py`: up to 256 pieces, 2,472 conversions,
   0 differ.
3. **`check_samples.py --reference-dir` selects shots by the raw copy** (`d<N>.txt`) in that
   folder, not by the TXY. Copying only the TXY checks nothing, and it exits 1 with "no shots were
   checked" (correctly). Stage 1's MATLAB 2023 runs exist only on the reference floor's
   `.ai/temp/txy/matlab-2023/`; I copied them here. They will vanish with that floor.

## Proposed doc changes (for the Coordinator)

- **`roadmaps/txy-converter.md`, Stage 2:**
  - Mark it **done** (pending review), linking this results.md.
  - The results line: all five backends byte-identical. Per core end to end: numpy 119, numba
    171, cython 170, rust 178, mlx 72, reference 13 MB/s. numpy with 12 processes reaches
    1,049 MB/s.
  - The recommendation: numpy default; rust (or cython) optional; drop numba and mlx.
  - Both targets are met by numpy on one core. The next lever is the text I/O, not the backends.
- **`.ai/architecture/converter.md`:**
  - **Backends section, one paragraph:** "Stage 2's measured standing (results in
    `.ai/sessions/2026-10-29-claude-txy-bench/results.md`). numpy is the default; compiled
    backends reconstruct at ~0.9–1.9 GB/s, but reading and writing then take 80 % of a
    conversion. Parallelise across shots in processes. Threads stop at ~400 MB/s because
    `format_txy` holds the GIL. `split.reconstruct_split` pays only for slow backends or shots
    much denser than the samples."
  - **Packaging note:** every `_MODULES` backend, the reference included, needs `hiddenimports`
    in a frozen build. The mlx and numba floors already proposed this; it is not yet in
    converter.md.
- **`.ai/AI_TODO.md` A9.1:** add this results.md as the input: sizes, platforms and the
  recommendation (drop numba and mlx; keep one of rust/cython).
- **`.ai/DECISIONS_TODO.md` Q6.9:** the benchmark it waited on is done. On this Mac every backend
  but the reference converts faster than gigabit delivers raw files, numpy on one core included.
  The lab PCs are untimed (M~1).

## Provisional items

- **Q~1 (Tony): which backends ship after testing (A9.1)?**
  - Proposed: numpy (default) plus rust as the one optional compiled backend; drop numba, mlx
    and cython.
  - Alternative: cython instead of rust if stage 4's CI finds C extensions easier than Rust
    wheels.
  - Alternative: numpy alone, since it meets both targets here; the compiled backends buy ~1.5×
    margin per core.
  - Waits on M~1 if the lab PCs matter for the choice.
- **Q~2 (Tony, low stakes): keep `reference` in the build?** Proposed: yes, as the test oracle and
  the readable specification, never the app's default. It is small, plain Python.
- **A~1 (next stage-2/3 work, if wanted): fast I/O.**
  - Reading (~560 MB/s) and writing (~340 MB/s) are now 80–83 % of a compiled backend's
    conversion.
  - The rust floor's Rust `parse_strict` (1,910 MB/s) and `format_txy` (596 MB/s) are measured
    and byte-identical on all samples (report only today).
  - Wired in behind the same byte-for-byte checks, they would take rust to ≈ 300 MB/s per core.
  - A GIL-free formatter would also make threads scale.
- **A~2 (stage 4, helab-core):** convert across shots in long-lived helper processes (a warm pool:
  1,049 MB/s for numpy at ×12, against 761 cold). Don't use within-shot splitting for the fast
  backends; it makes them slower on every sample shot.
- **A~3 (housekeeping):** keep stage 1's MATLAB 2023 outputs. The 32 files in the reference
  floor's `.ai/temp/txy/matlab-2023/` are the only `--reference-dir` set on this machine; Lens's
  152 odd-shot runs are gone. Proposed: copy them beside the sample set (e.g.
  `~/HeLab-samples/txy-v1-matlab-2023/`, read-only) before that floor is deleted.
- **M~1 (lab PCs):** time numpy (and the chosen compiled backend, once CI builds it) on the
  acquisition PC and the Lab Side PC. Use `bench.py --mode serial` and `processes-warm` at ×2 and
  ×4 on a copy of the sample set. This decides whether one core there keeps up with gigabit.
  Both PCs have a uv Python 3.13 venv. Run it at the PC itself, not over SSH: on the Main PC an
  elevated SSH session has poisoned HeLab's cache settings before.
- **M~2 (optional):** repeat the ×12/×16 rows with Safari closed, if the exact ceiling matters.
  Nothing in the recommendation depends on it.
