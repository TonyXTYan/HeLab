# Handoff: TXY converter stage 1, the reference and harness (builder, Forge, 2026-10-29)

Branch `agent/txy-reference` from `29e7e19`. Brief: [brief.md](brief.md). Evidence: [notes.md](notes.md);
x2 report: [x2-handling.md](x2-handling.md). The cross-checker's work is in `crosscheck/`.

## What was built

`helab/convert/` (Qt-free, standard library and NumPy; every module in `PURE`):

| Module | What |
|---|---|
| `raw` | `parse_raw`/`read_raw` → `RawPulses` (float64 channels and times in file order), as MATLAB's `textscan` reads them: a strict fast path for plain `\d+,\d+\r?\n` files, a general reader for everything else (truncated lines, blank lines, garbage, BOM; 36 behaviours measured). A marked place for stage 4's done-writing checks. |
| `profile` | `DetectorProfile` (frozen): bin time, channel map, time-zero and first-row quirks, dead time per corner, search depth and window, match sums and tolerances per axis, the x−y sum tolerance, x2 and y handling (`"matlab"`), T time sums per axis, v⊥ per axis, `position_formula` (2019 centred vs 2023 raw columns), `matlab_overflow_row`, `write_empty_txy`, plus `name`, `version`, `calibrated`, `notes`. JSON (`schema: 1`, unknown or missing fields refused), `content_hash` (SHA-256 of the output-changing fields). Built-ins `matlab-2019` (default) and `matlab-2023-lab-edit`. |
| `reconstruct` | `reconstruct(pulses, profile, backend="reference")`, the registry (`register_backend`, `get_backend`, `available_backends`, `Backend.unavailable(profile)`, `releases_gil`), `NoRowsError`. |
| `backends/reference` | The port: MATLAB's loops one for one, with MATLAB line numbers in comments; `MatchStats` for the x2 report. |
| `txy` | `format_txy` (dlmwrite precision 8: `%.8g`, `NaN`/`Inf`/`-Inf`, `\n` after every row), `write_txy`/`write_atomic` (temporary name, then `os.replace`). |
| `pipeline` | `convert_raw(bytes, profile, backend) -> bytes | None` (None: no file, as 2019 for no hits). |
| `samples` | The manifest reader (SHA-256 checked on read), held-in/held-out positions. |
| `check` | `check_txy(ours, reference)`: identical, or the first differing line and both hit counts; `None` = no file. |
| `timing` | `time_shot`/`time_shots` with `Parallelism` serial, processes, threads, within-shot (stage 2), `summarise` (MB/s per stage, wall MB/s, latency). |

`dev/txy/`: `check_samples.py` (the checker over the sample set; exit 1 on any unexplained
mismatch), `reference_exceptions.py` (the proved exceptions, below), `matlab_variant.py` (MATLAB
headless on sample copies under `.ai/temp/txy/`), `time_samples.py`, `x2_report.py`.

Tests: `tests/test_convert_{raw,txy,profile,reference,harness}.py` (171 tests); data
`tests/data/convert/cases/` (Lens's 39 cases with MATLAB's output; `.gitattributes` `* -text`).

## Results

**matlab-2019, all 309 sample shots** (`check_samples.py --positions all`):

| Set | Shots | Identical | Cut | Variant | Empty | Differ |
|---|---|---|---|---|---|---|
| 2019-halos-old-plates | 43 | 42 | 1 | 0 | 0 | 0 |
| 2020-halos-weak-trap | 42 | 41 | 0 | 0 | 1 | 0 |
| 2022-07-old-plates-he3he4 | 42 | 40 | 0 | 2 | 0 | 0 |
| 2022-07-old-plates-large-he3 | 43 | 43 | 0 | 0 | 0 | 0 |
| 2022-11-ghost-counts-mcp | 10 | 9 | 0 | 0 | 1 | 0 |
| 2023-02-new-plates-he3he4 | 43 | 42 | 0 | 0 | 1 | 0 |
| 2023-03-momentum-bells | 43 | 43 | 0 | 0 | 0 | 0 |
| 2024-11-rt-low-occupancy | 43 | 43 | 0 | 0 | 0 | 0 |
| **all** | **309** | **303** | **1** | **2** | **3** | **0** |

The six exceptions are listed in `dev/txy/reference_exceptions.py`, keyed by set, shot and
reference SHA-256, and each proof runs again on every check (Side's conditions). Lens confirmed
the cut, variant and d5/d187 proofs independently, with its oracle and with MATLAB:

- **cut**: 2019-halos d3667. MATLAB read the raw file half-written; the TXY was written 0.25 s
  after the raw file's mtime. Our output is identical when the raw is cut to 40,956–40,966 lines.
- **variant**: 2022-07 he3he4 d2, d3, re-converted 2023-02-08 by a **third MATLAB variant**:
  matlab-2019 plus a 2 µs x1 dead time. Only 2.0 µs matches (Lens tried 1–3 µs). These two
  shots can't tell its X/Y formula: Lens's copy of the 2023 file with 2 µs and 3200/3200 sums
  also matches.
- **empty**: 2020-halos d400, 2022-11 d5, 2023-02 d187. No hits; the 2019 wrapper writes no
  file, but the reference is a 0-byte file. d400's was written 2 s after its raw file in 2020,
  so the lab's live converter then wrote empty files too. It wasn't only the 2023
  `dld_raw_to_txy`. Lens hadn't flagged d400; tell Lens it's in the list.

**matlab-2023-lab-edit vs MATLAB's own 2023 output** (`matlab_variant.py --variant 2023
--positions even --limit 4`, then `check_samples.py --profile matlab-2023-lab-edit
--reference-dir .ai/temp/txy/matlab-2023`): **32 of 32 identical**, 4 shots per set, among them
the empty ghost d5 (a 0-byte file).

**Synthetic cases**: 39 × 2 variants identical to MATLAB, outputs and outcomes (file, no file,
error). **tests_sample_data**: all 17 raw/TXY pairs reproduced (tested).

**Checks**: `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: 4653 passed,
2 skipped, **no RERUN**. `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`:
clean.

## Timings of the reference

All 309 shots (217.5 MB), Apple Silicon (16 cores), with the machine busy (load ~8), so these are
indicative only:

| Run | read | reconstruct | write | total | wall | latency median / max |
|---|---|---|---|---|---|---|
| serial | 70 MB/s | 13.7 MB/s | 171 MB/s | 10.7 MB/s | 10.7 MB/s | 47 / 754 ms |
| 4 processes | 72 | 13.6 | 165 | 10.7 | 42 | 47 / 729 ms |

Small shots reconstruct at 10 MB/s, large ones (the 3 largest per set) at 23.5. Reconstruction
takes about 80 % of the time. Live is easily met; bulk at about 100 MB/s needs stage 2.

## x2 handling (report: [x2-handling.md](x2-handling.md))

Old plates: a second x2 candidate for 0.8–6.8 % of x1 with an x2; retrying it would recover
about 0.1–0.8 % more hits. New plates (from 2022-11): about 0.01 %, so it barely matters. A
second y pair occurs for ≤ 0.27 % of hits. The default is unchanged.

## Quirks found beyond the brief (all reproduced; detail in notes.md)

1. The **phantom row**: MATLAB grows the `NaN(floor(N/4),5)` output with zeros, so a lone x pair
   in a grown row is a hit at T = 0, Y = 0 (`matlab_overflow_row`).
2. The 3400 x2 check never binds: the T_sum window (`>` 3200 skipped) comes first. y1 and y2 are
   both windowed around x1.
3. A second y pair breaks only the inner y2 loop.
4. 2019 and 2023 compute X/Y with different roundings (`position_formula`).
5. Empty raw file → MATLAB error (`NoRowsError`); no hits → no file (2019) or a 0-byte file (2023).
6. NaN times (truncated lines) sort last and never match; a NaN `t_zero` gives no hits.
7. textscan's reading of malformed lines (notes.md table), e.g. a BOM gives no rows and
   `5,100,7` gives an extra row.

## Proposed doc changes (for the Coordinator)

- **New `.ai/architecture/converter.md`**, outline: purpose and stages; `helab/convert/`
  modules (the table above); what MATLAB does (read, sort, match, write) and the quirks list
  with the profile field for each; `DetectorProfile` fields and JSON schema 1; the content hash
  covers the output-changing fields only; the backend contract (byte-identical to `reference`,
  `NoRowsError`, the registry, `unavailable`, `releases_gil`); the harness (`samples`, `check`,
  `timing`, `dev/txy/`); the reference exceptions and their proofs; tests and data
  (`tests/data/convert/`, `.gitattributes`).
- **AGENTS.md** code map, one row: `helab/convert/` | converter: raw parsing, detector profiles,
  backends, TXY writing, harness | converter.md. Invariant line (proposed): "Every converter
  backend gives `reference`'s output byte for byte (`dev/txy/check_samples.py`)".
- **roadmaps/txy-converter.md**: stage 1 done (with this commit). Correct "Decided, First bar":
  MATLAB's references are not all from the 2019 converter. Six of 309 aren't: a half-written
  read, a third variant (2 µs x1 dead time, 2023-02) and three empty files. The bar is identical
  output or a proved exception. Under "What the MATLAB converter does", add the third variant and
  the phantom row.
- **Findings** (`2026-10-28-claude-txy-converter-plan/findings.md`, if it is kept current): the
  2023 lab edit isn't the only later variant; uniquetol's grouping is now confirmed (first of
  group, ≤, not chained).
- **known-issues**: none from this stage (no flaky tests, no RERUN).

## Provisional items

- **Q~1** (for Tony): should the third MATLAB variant (2019 plus a 2 µs x1 dead time, used on
  2023-02-08 to re-convert 2022-07 he3he4 shots) become a built-in profile? Proposed: no, it stays
  a dev finding (CoCo's and Side's call tonight); ask Tony whether he knows who ran it and why.
- **Q~2** (for Tony, stage 4): a raw file with no rows (0 bytes or blank) makes MATLAB fail.
  What should HeLab do? Proposed: the settle check refuses it while it may still be written; once
  settled, it is reported as unconvertible (no TXY, a notification), never silently skipped.
- **A~1** (stage 4, Side's decision tonight): a conversion with 0 hits still writes an empty HeLab
  TXY, so "converted, empty" differs from "not converted yet" (`write_empty_txy` for HeLab's own
  output, whatever the profile says for MATLAB comparison).
- **A~2** (stage 4): d3667 is the evidence for the settle checks. MATLAB converted a raw file
  0.25 s after its last write and lost the end of the shot. Test the settle check with a
  synthetic half-written file.
- **A~3** (stage 2): every backend must pass all 39 cases as well as the samples, including the
  phantom row, `NoRowsError` and the stable NaN-last sorts (NumPy's default argsort isn't stable;
  use `kind="stable"`).
- **A~4** (stage 4): ship the built-in profiles as JSON files inside the package (Q6.11), each
  tested to load equal to the Python definitions.
- **M~1** (for Tony): other TXY on X may be half-written reads like d3667 (TXY mtime within
  seconds of the raw file's). Counting them needs a listing pass on X, which only Tony or the
  Assistant may run. Worth knowing before stage 5 compares HeLab with MATLAB on every shot.
