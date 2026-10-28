# Cross-checker notes (Lens, 2026-10-29)

What I did, in order, with where the evidence is. The results and findings are in
[handoff.md](handoff.md).

## 1. Independent reading

- Read both MATLAB variants and both wrappers without the builder's code, and wrote
  [matlab-walkthrough.md](matlab-walkthrough.md) (§9 is the numbered quirk checklist).
- Probed MATLAB R2025b headless on copies under `.ai/temp/crosscheck/`: textscan on 24 malformed
  inputs ([probes/ts](probes/ts)), `uniquetol` grouping (first of a group, not chained,
  inclusive at 20000, ties → first index), matrix growth (`NaN(1,5)` assigned at row 2 pads with
  zeros), and `dlmwrite` precision 8 formatting (`-0`, `NaN`, `Inf`, exponents, empty matrix → a
  0-byte file).
- Found one quirk not in the findings: the **phantom row** (walkthrough §6.1). MATLAB grows the
  preallocated `NaN(floor(N/4),5)` with zeros, so a lone x1+x2 after the last hit leaves a hit
  at T = 0, Y = 0. Confirmed by MATLAB on four cases.
- Wrote [tools/oracle.py](tools/oracle.py), a stdlib transcription of the walkthrough (not the
  port), to predict MATLAB's output. Byte-identical to MATLAB on all 39 cases × 2 variants.

## 2. Synthetic cases

[cases/](cases/README.md): 39 raw files from [tools/gen_cases.py](tools/gen_cases.py), each run
through both MATLAB variants by [tools/run_matlab_cases.m](tools/run_matlab_cases.m). Committed
in `13dba76`; the builder copied them to `tests/data/convert/cases/`. `cases/.gitattributes`
(`* -text`) keeps their bytes on Windows checkouts (raw CRLF, TXY LF); the builder added the
same to `tests/data/convert/`.

## 3. The reference faults

My oracle over all 309 sample shots (`tools/oracle_samples.py`): 306 identical. The three others
and Forge's claims, each checked with MATLAB on copies (`.ai/temp/crosscheck/odd3`, `d400`):

| Shot | Class | Evidence |
|---|---|---|
| 2019-halos d3667 | cut | the raw cut to K complete lines reproduces the reference for exactly K = 40,956…40,966 (of 41,092); MATLAB 2019 on the 40,956-line copy: identical |
| 2022-07 he3he4 d2, d3 | variant | only a 2.0 µs x1 dead time reproduces them (1, 1.5, 2.5, 3 µs don't), with T from `T_sum` 3200; MATLAB, a copy of the 2023 file with `2e-6` and `T_sum_x/y = 3200`: identical on both |
| 2020-halos d400, 2022-11 d5, 2023-02 d187 | empty | no hit (d400: trigger, one x1, eleven y2; d5: 13 trigger rows; d187: trigger rows, one x1, one x2); MATLAB 2019 writes no file, the 2023 wrapper a 0-byte file equal to the reference |

My oracle run counted the three empty shots as identical because it compared bytes (empty =
empty); the port's `check_txy` correctly tells "no file" from a 0-byte file.

## 4. Checking the port (d14f0cb; `helab/` unchanged since 9268515)

- Read `backends/reference.py`, `raw.py`, `txy.py`, `profile.py`, `reconstruct.py`,
  `pipeline.py`, `check.py`, `samples.py`, `timing.py`, `dev/txy/*.py` against the
  walkthrough. Every item of the §9 checklist is in the port, with the right MATLAB line.
- Cases: the port's `convert_raw` on 39 × 2: 78/78 as MATLAB (file / no file / error, bytes).
- Differential fuzz ([tools/fuzz_recon.py](tools/fuzz_recon.py)): 10,000 random dense,
  boundary-heavy raw files (all tolerance edges, dropped corners, extra pulses, duplicates,
  shuffled order, NaN lines, no trailing newline) × 2 variants, port vs oracle: 0 differences.
- MATLAB-judged reader fuzz ([probes/fuzzts](probes/fuzzts)): 400 malformed inputs; the port
  matched MATLAB on 395 (my oracle's reader only 298). The 5 others are all finding F1, pinned
  down by [probes/ts2](probes/ts2) and [probes/ts3](probes/ts3).
- Samples with `dev/txy/check_samples.py`: odd positions first (152 shots), then all 309.
- The 2023 variant: my own MATLAB run (not `matlab_variant.py`) of the 2023 wrapper on copies of
  all 152 odd-position shots (`.ai/temp/crosscheck/m2023`, 614,136 hits), checked with
  `check_samples.py --profile matlab-2023-lab-edit --reference-dir`: 152/152 identical.
- `pytest -n 4 --reruns 5 --reruns-delay 1 tests/test_convert_*.py tests/test_headless_imports.py`:
  173 passed, no reruns. `mypy --strict` (helab/convert, tests/test_convert_*) and `pyright` on
  the same paths: clean. (The builder runs the full suite.)

## 5. x2 handling

[tools/x2_measure.py](tools/x2_measure.py) runs the oracle with an `x2_mode` that retries the
second x2 candidate (`retry2`) or every candidate in the window (`retry_all`) when the first
finds no y pair, **simulating the whole shot** (a recovered hit takes its pulses from later x1
rows). Totals in [x2-measure.json](x2-measure.json). Results and comparison in the handoff.

## Packages

None installed. MATLAB R2025b only, on copies under `.ai/temp/crosscheck/`.
