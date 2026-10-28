# Handoff: TXY converter stage 2, backend `mlx` (Worker Prism, 2026-10-29)

Branch `agent/txy-mlx` from `372f2ac`. Brief: [brief.md](brief.md). Numbers: [results.md](results.md).
Packages: [requirements-bench.txt](requirements-bench.txt) (`mlx` and `mlx-metal` 0.32.4, floor venv only).

## Summary

An `mlx` backend that matches the reference byte for byte. The GPU finds every x1's **first choice**
(the first x2, then the first y pair, ignoring used pulses) in integers. The CPU keeps each first
choice that no earlier hit took, which is provably MATLAB's own choice, and recomputes only the
**contested** x1 rows, in order: 2.0 % of x1 under `matlab-2019` (3–5 % on the ringing old plates),
none under `matlab-2023-lab-edit`. T/X/Y are formed in float64 on the CPU from the matched rows, in
the reference's order.

**Honest result:** the GPU helps with the search only. The greedy order stays on the CPU.
Reconstruction runs at ~106–135 MB/s serial vs 13 for the reference at the same load. The GPU search
is 6× faster than the same search in NumPy, but each shot pays ~2.5 ms of fixed GPU overhead. With
the backend this fast, stage 1's reader (66 MB/s) and writer (160 MB/s) are the bottleneck: 32.6 MB/s
per core end to end; 108 MB/s with 4 processes and 172 MB/s with 8. Threads plateau at ~40 MB/s
(GIL). It adds **240 MB** to a PyInstaller build (the Metal kernel library) and runs only on Apple
Silicon with macOS 14 or later. Whether it beats the NumPy floor's own algorithm is for the final
serial run to say. My guess: it is worth shipping only as an optional fast backend on lab Macs, if
at all, given the size.

## What changed

| Path | What |
|---|---|
| `helab/convert/backends/mlx_gpu.py` (new) | The backend, registered as `mlx`; the module docstring explains the four steps and why the greedy pass is exact. `prepare` (sort, time zero, corner codes, int64 times, dead time), `first_choices_mlx` (GPU) / `first_choices_numpy` (the same on the CPU, for tests and comparison), `contested_at_start`, `resolve`, `assemble`, `reconstruct_mlx(…, gpu=True)`. A corner time with a fraction or ≥ 2^50, or a window ≥ 2^26 bins, sends the shot to the reference. MLX is imported lazily, under a lock (`_START`), on first use. |
| `helab/convert/reconstruct.py` | One line: `"mlx": "helab.convert.backends.mlx_gpu"` in `_MODULES` (the same line the other floors edit; a merge keeps every entry). |
| `tests/test_convert_backend_mlx.py` (new) | 203 tests; 98 run without MLX (the CPU variant of the same pipeline), the rest skip with the reason (`mlx backend unavailable: MLX isn't installed (pip install mlx)`, `… MLX needs Apple Silicon (this is linux x86_64)`, `… MLX finds no Metal GPU`). Every case × both profiles vs MATLAB and the reference; the 17 lab pairs; a fuzz of dense, ringing streams on 6 profiles (asserts that contested and cascaded changes happen); NaN/±Inf/fractional/huge times; empty and tiny files; depth 1; the integer dead-time cut vs `uniquetol_keep`; the integer limits; 16 threads × 4 rounds; 16 threads released together into the first load in a fresh process (×3); unavailable reasons; no `mlx`, Qt or constants on import. |
| `.ai/sessions/2026-10-29-claude-txy-mlx/` | brief, results, this handoff, `requirements-bench.txt`, `compare_backends.py` (mlx vs reference on the sample set, with contested counts), `step_timing.py` (per-step timing and first-call cost), `timing/*.json` (the harness runs). |

No build files: MLX ships wheels. Nothing in `pyproject.toml` or `HeLab.spec`.

## Checks

- 39 cases × 2 profiles: identical to MATLAB and to the reference (GPU and CPU search).
- `dev/txy/check_samples.py --positions all --backend mlx`: 303 identical + the 6 listed reference
  faults, proofs re-run with `mlx`; 0 unexplained; 309 of 309 checked.
- `compare_backends.py --positions all`: 309/309 identical to the reference under `matlab-2019`
  and under `matlab-2023-lab-edit`. (MATLAB's own 2023 output isn't on this machine any more; the
  reference matched it on 184 shots in stage 1.)
- Full suite and type checks: see "Final run" below.

## Final run (on `a46c150` plus these docs)

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: **6282 passed, 4 skipped,
  no RERUN**, 197 s (load 24.7 at the end).
- `mypy helab/ --strict` (174 files), `mypy tests --strict` (145 files), `pyright helab tests`: clean.
- With MLX hidden (`sys.modules['mlx'] = None`): `tests/test_convert_backend_mlx.py` 98 passed,
  105 skipped, each with the reason.

## Notes for the Coordinator and the final run

- **Cut for within-shot parallelism:** the backend parallelises within the shot itself (all x1
  at once on the GPU). The proof is in results.md, "Parallelism within one shot". It keeps no state
  between calls, so it can take `split.py`'s pieces in the final run.
- **Thread safety (Anvil's note):** MLX starts once under `_START`. The first-load test was stressed
  25 times in fresh processes with no failure. The registry's own `_load` relies on Python's
  per-module import lock, which serialises a concurrent import of the same module. That held here,
  but `reconstruct.py` is shared, so a lock there is a question for CoCo (Q~2).
- **FMA (Anvil's note):** every float operation is a separate NumPy float64 ufunc on the CPU, in the
  reference's order; nothing runs in float on the GPU.
- `mx.compile` would halve the search but costs ~560 ms of Metal compilation on its first call
  (measured; results.md). It isn't used.

## Proposed doc changes (for the Coordinator)

- `.ai/architecture/converter.md`, module table: add `backends/mlx_gpu` (Apple GPU; first choices on
  the GPU in int32 differences, greedy pass and float64 output on the CPU; Apple Silicon, macOS ≥ 14,
  `mlx` optional). Under "Backends (stage 2)", add the general fact this floor proved, which other
  backends may use: **an x1's first choice ignoring used pulses is MATLAB's choice unless an earlier
  hit marked one of its pulses** (marks only remove candidates), so a parallel search plus a
  sequential check of contested x1 rows is exact.
- `.ai/architecture/converter.md`, packaging note for stage 4: backends are imported by name from
  `_MODULES`, so a frozen build needs `hiddenimports` for every backend module, **the reference
  included** (found in the scratch build: without it the frozen app can't find
  `helab.convert.backends`). MLX also needs `collect_submodules('mlx')` and `collect_data_files('mlx')`.
- `roadmaps/txy-converter.md`, stage 2 results: the mlx row from results.md.

## Provisional items

- **A~1 (stage 4 packaging floor): MLX in CI as required tests where it can run.** On CI, run
  `tests/test_convert_backend_mlx.py` with `mlx` installed on the macOS arm64 runner and make its GPU
  tests required there. That needs Apple Silicon, macOS ≥ 14 and Metal visible to the runner. GitHub's
  hosted `macos-latest` runners are arm64 virtual machines, and I expect `mx.metal.is_available()` to
  be False there (unverified; PyTorch's MPS is reported unavailable on them). So first add a CI step
  that prints it. If it is False, the GPU tests can only be required on a self-hosted Apple Silicon
  runner. The CPU half of the tests (98) already runs everywhere. Linux and Windows always skip, with
  the reason.
- **A~2 (stage 4 packaging): hidden imports for the backends.** `HeLab.spec` needs
  `hiddenimports=['helab.convert.backends.reference', …]` for every backend it ships. If it ships
  mlx, it also needs `collect_submodules('mlx')` and `collect_data_files('mlx')`, and a frozen smoke
  test that converts one case with each backend.
- **Q~1 (Tony / Side): ship the mlx backend?** It adds 240 MB to the macOS build (80 MB
  compressed), runs only on Apple Silicon with macOS ≥ 14, and only the search runs on the GPU.
  Proposed answer: **no, not in the default build**. Keep it as an optional install for lab Macs, and
  revisit after the final serial run against the NumPy floor's backend.
- **Q~2 (CoCo): a lock in `reconstruct._load`?** Python's import lock already serialises concurrent
  imports of one backend module; a `threading.Lock` around `_load` would make that explicit for
  every backend. That is a shared-file change, so I left it alone.
- **M~1:** none. The tests use synthetic data and `tests_sample_data/`; nothing needs a screen.
