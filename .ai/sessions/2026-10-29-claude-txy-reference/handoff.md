# Handoff: TXY converter stage 1, the reference and harness (builder, Forge, 2026-10-29)

Branch `agent/txy-reference` from `29e7e19`. Brief: [brief.md](brief.md). Evidence: [notes.md](notes.md);
x2 report: [x2-handling.md](x2-handling.md). The cross-checker's work is in `crosscheck/`.

## What was built

`helab/convert/` (Qt-free, standard library and NumPy; every module in `PURE`):

| Module | What |
|---|---|
| `raw` | `parse_raw`/`read_raw` → `RawPulses` (float64 channels and times in file order), as MATLAB's `textscan` reads them: a strict fast path for plain `\d+,\d+` files ending all lines alike (`\r\n` or `\n`), a general reader for everything else (truncated lines, blank lines, garbage, BOM, and the line-ending mode the first non-blank line sets; 46 behaviours of mine and Lens's 1,367 probes, all judged by MATLAB). A marked place for stage 4's done-writing checks. |
| `profile` | `DetectorProfile` (frozen): bin time, channel map, time-zero and first-row quirks, dead time per corner, search depth and window, match sums and tolerances per axis, the x−y sum tolerance, x2 and y handling (`"matlab"`), T time sums per axis, v⊥ per axis, `position_formula` (2019 centred vs 2023 raw columns), `matlab_overflow_row`, `write_empty_txy`, plus `name`, `version`, `calibrated`, `notes`. Validated (finite numbers, non-negative sums and tolerances, distinct corners). JSON (`schema: 1`; unknown fields refused; a missing field takes its neutral default if it has one, else is refused; `_MIGRATIONS` for later schemas). `content_hash`: SHA-256 of the output-changing fields, leaving out descriptive ones, `UNUSED_BY_OUTPUT` (MCP and trigger channel) and fields at their neutral default (`NEUTRAL`), so a field added later doesn't change existing hashes. Built-ins `matlab-2019` (default) and `matlab-2023-lab-edit`. |
| `reconstruct` | `reconstruct(pulses, profile, backend="reference")`, the registry (`register_backend`, `get_backend`, `available_backends`, `Backend.unavailable(profile)`, `releases_gil`), `NoRowsError`. |
| `backends/reference` | The port: MATLAB's loops one for one, with MATLAB line numbers in comments; `MatchStats` for the x2 report. |
| `txy` | `format_txy` (dlmwrite precision 8: `%.8g`, `NaN`/`Inf`/`-Inf`, `\n` after every row), `write_txy`/`write_atomic` (a new temporary name created with `os.open(…, 0o666)` so the kernel applies the umask, fsync, `os.replace`, folder fsync). |
| `pipeline` | `convert_raw(bytes, profile, backend) -> bytes | None` (None: no file, as 2019 for no hits). |
| `samples` | The manifest reader (SHA-256 checked on read), held-in/held-out positions. |
| `check` | `check_txy(ours, reference)`: identical, or the first differing line (`(ended)`, `(no final newline)` marked) and both hit counts; `None` = no file. `ReferenceFault` (`cut`, `variant`, `empty`) and `prove_fault`, which checks a fault again from the raw file. |
| `timing` | `time_shot`/`time_shots` with `Parallelism` serial, processes, threads, within-shot (stage 2), `summarise` (MB/s per stage, wall MB/s, latency). |

`dev/txy/`: `check_samples.py` (the checker over the sample set; prints checked of selected,
exits 1 on any unexplained mismatch or when nothing was checked), `reference_exceptions.py` (the
list of exceptions, below), `matlab_variant.py` (MATLAB headless on sample copies under
`.ai/temp/txy/`), `time_samples.py`, `x2_report.py`, `x2_retry.py` (the whole-shot retry
simulation).

Tests: `tests/test_convert_{raw,txy,profile,reference,harness}.py`; data `tests/data/convert/`:
`cases/` (Lens's 39 cases with MATLAB's output) and `textscan/` (Lens's 1,367 reader probes
with MATLAB's rows), `.gitattributes` `* -text`. `tests_sample_data/.gitattributes` `* -text` too
(Heron's blocker: Windows autocrlf turned its LF TXY into CRLF), with a guard test.

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
reference SHA-256, and each proof (`helab.convert.check.prove_fault`) runs again on every check
(Side's conditions). Lens confirmed the cut, variant and d5/d187 proofs independently, with its
oracle and with MATLAB; d400 is Lens's to confirm:

- **cut**: 2019-halos d3667. MATLAB read the raw file half-written; the TXY was written 0.25 s
  after the raw file's mtime. Our output is identical when the raw is cut to 40,956–40,966 lines.
- **variant**: 2022-07 he3he4 d2, d3, re-converted 2023-02-08 by a **third MATLAB variant**:
  matlab-2019 plus a 2 µs x1 dead time. Only 2.0 µs matches (Lens tried 1–3 µs). These two
  shots can't tell its X/Y formula: Lens's copy of the 2023 file with 2 µs and 3200/3200 sums
  also matches.
- **empty**: 2020-halos d400, 2022-11 d5, 2023-02 d187. No hits; the 2019 wrapper writes no
  file, but the reference is a 0-byte file. d400's was written 2 s after its raw file in 2020,
  so the lab's live converter then wrote empty files too. It wasn't only the 2023
  `dld_raw_to_txy`.

**matlab-2023-lab-edit vs MATLAB's own 2023 output** (`matlab_variant.py --variant 2023
--positions even --limit 4`, then `check_samples.py --profile matlab-2023-lab-edit
--reference-dir .ai/temp/txy/matlab-2023`): **32 of 32 identical**, 4 shots per set, among them
the empty ghost d5 (a 0-byte file). Lens ran MATLAB's 2023 variant on all 152 odd shots: the port
gives 152 of 152.

**Synthetic cases**: 39 × 2 variants identical to MATLAB, outputs and outcomes (file, no file,
error). **Reader**: Lens's 1,367 textscan probes and my 50 cases read as MATLAB does; Lens's
10,000-file fuzz against its oracle found no difference. **tests_sample_data**: all 17 raw/TXY
pairs reproduced (tested).

**CI** on 09a0711 (run 40713926667): success on macOS, Ubuntu and Windows (py3.13): 6079 / 6077 /
6051 passed; one RERUN on Windows, outside the converter (see known-issues below).

**Checks** (after review round 1): `pytest -n 4 --reruns 5 --reruns-delay 1
--basetemp=.ai/temp/pytest`: 5155 passed, 4 skipped (two are the perturbation test's
single-value fields `x2_handling`, `y_handling`), **no RERUN**. `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`:
clean.

## Timings of the reference

All 309 shots (217.5 MB), Apple Silicon (16 cores), with the machine busy (load ~8), so these are
indicative only:

| Run | read | reconstruct | write | total | wall | latency median / max |
|---|---|---|---|---|---|---|
| serial | 70 MB/s | 13.7 MB/s | 171 MB/s | 10.7 MB/s | 10.7 MB/s | 47 / 754 ms |
| 4 processes | 72 | 13.6 | 165 | 10.7 | 42 | 47 / 729 ms |

Small shots reconstruct at 10 MB/s, large ones (the 3 largest per set) at 23.5. Reconstruction
takes about 80 % of the time. Live is easily met; bulk at about 100 MB/s needs stage 2. (Measured
before the write gained its fsyncs, Heron 3; stage 2's serial timings on an idle machine replace
these.)

## x2 handling (report: [x2-handling.md](x2-handling.md))

Old plates: a second x2 candidate for 0.8–6.8 % of x1 with an x2; retrying it nets
0.13–0.67 % more hits per set (+4,255, 0.29 %, over all 309 shots, simulated over whole shots;
the same as Lens's figure; retrying every candidate adds only 34 more). The earlier 4,944 was a
non-committing upper estimate (Lens's F3). New plates (from 2022-11): about 0.01 %, so it barely matters. A
second y pair occurs for ≤ 0.27 % of hits. The default is unchanged.

## Quirks found beyond the brief (all reproduced; detail in notes.md)

1. The **phantom row**: MATLAB grows the `NaN(floor(N/4),5)` output with zeros, so a lone x pair
   in a grown row is a hit at T = 0, Y = 0 (`matlab_overflow_row`).
2. The 3400 x2 check never binds: the T_sum window (`>` 3200 skipped) comes first. y1 and y2 are
   both windowed around x1.
3. A second y pair breaks only the inner y2 loop.
4. 2019 and 2023 write X/Y with different formulas (`position_formula`). For integer times
   below 2^52 (every TDC file) they give the same doubles; they can differ only for times with a
   fraction.
5. Empty raw file → MATLAB error (`NoRowsError`); no hits → no file (2019) or a 0-byte file (2023).
6. NaN times (truncated lines) sort last and never match; a NaN `t_zero` gives no hits.
7. textscan's reading of malformed lines (notes.md table), e.g. a BOM gives no rows and
   `5,100,7` gives an extra row. The first non-blank line's ending decides which endings end a
   line (Lens's F1): after `\n` a later `\r` stops the read, after `\r` a later `\n` does.

## Review round 1 (Lens F1–F5, Heron 1–7), all fixed

| Item | Fix |
|---|---|
| Lens F1: line-ending mode | `raw._parse_textscan` takes the mode from the first non-blank line (`\r+\n` → all three, `\n` → only `\n`, `\r` → only `\r`); 10 more MATLAB probes of mine settled `\r\r\n` and `\n\r`. The fast path only takes uniformly ended files. Lens's probes are tests. |
| Lens F2 + Heron 3: file mode, durability | `write_atomic`: the temporary file is created with `os.open(…, O_EXCL, 0o666)`, so the kernel applies the umask (no process-wide umask read, Heron round 2); fsync, rename, folder fsync (as `cache_store`); tested. |
| Lens F3: retry figure | `dev/txy/x2_retry.py` simulates whole shots; x2-handling.md corrected (+4,255, 0.29 %). |
| Lens F4: rounding wording | `profile.py`, notes, handoff: the same doubles for integer times. |
| Lens F5: checker display | `(ended)` and `(no final newline)` markers; an empty side has no lines; tested. |
| Heron 1: Windows autocrlf | `tests_sample_data/.gitattributes` `* -text` (renormalising changed no file), guard test. |
| Heron 2 + Side: extensible schema | Neutral defaults, migrations, hash policy (above); hashes re-pinned (`matlab-2019` `fbaf4728…`, `matlab-2023-lab-edit` `a228f236…`); a test perturbs every field and fails if the output changes but the hash doesn't. |
| Heron 4: validation | NaN/Inf, negative sums and tolerances, equal corner channels refused; tested. |
| Heron 5: silent filter | `check_samples.py` prints checked of selected and exits 1 when none were checked. |
| Heron 6: spawned workers | `reconstruct.py` says a backend needs its `_MODULES` line. |
| Heron 7: proofs in the package | `ReferenceFault`/`prove_fault` in `helab/convert/check.py` with a synthetic test per kind; the list stays in `dev/txy/`. |
| Heron round 2, blocker: `nul.txt` | Windows refuses the reserved name at checkout; both copies renamed `nul_padding.txt`; `tests/test_windows_paths.py` checks every tracked path. |
| Heron round 2: umask | as F2 above. `mypy dev/txy --strict` is clean too. |
| Lens R2-1: files starting with line endings | the mode is found after only the leading `\n` (not `\r` or blanks), and reading starts at byte 0 in it (Lens's fix); Lens's new probe sets `ts4`, `fuzzeol`, `fuzzlead` are tests: 1,367 MATLAB-judged inputs, all agree. |

## Proposed doc changes (for the Coordinator)

- **New `.ai/architecture/converter.md`**, outline: purpose and stages; `helab/convert/`
  modules (the table above); what MATLAB does (read, sort, match, write) and the quirks list
  with the profile field for each; the reader's textscan rules, line-ending mode included;
  `DetectorProfile` fields and JSON schema 1; **the schema and hash policy** (a new field gets a
  neutral default, is filled in when missing and left out of the hash at that value; other
  changes bump `SCHEMA` with a migration; `UNUSED_BY_OUTPUT` fields join the hash once the output
  reads them, which the perturbation test enforces; hashes pinned in a test); the backend contract (byte-identical to `reference`,
  `NoRowsError`, the registry, `unavailable`, `releases_gil`); the harness (`samples`, `check`,
  `timing`, `dev/txy/`); the reference-fault classes (cut, variant, empty) and `prove_fault`;
  tests and data (`tests/data/convert/`); the rule that byte-exact fixtures sit under a
  `.gitattributes` `* -text` (`tests/data/convert/`, `tests_sample_data/`).
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
- **known-issues**: one RERUN on CI, outside the converter. Windows + py3.13, run 40713926667
  (commit 09a0711): `tests/test_preset_folder_live.py::test_offline_a_folder_never_listed_is_named_as_such`,
  "pytestqt.exceptions.TimeoutError: waitUntil timed out in 30000 milliseconds"
  (`tests\test_preset_folder_live.py:82`); passed on rerun. Not yet listed; cause not looked for
  (not this floor's code). Locally, the converter stage had no RERUN. F1 and F2 are fixed.
- **testing.md** (or AGENTS.md's tests rules): fixtures compared byte for byte need a
  `.gitattributes` `* -text` beside them, or Windows CI's autocrlf rewrites them.

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
  use `kind="stable"`). **Within-shot splitting** (Lens's note) must keep the global `t_zero` (the
  file's first raw row), the skip of the first sorted row (only in the first piece), the phantom
  row's whole-file `floor(N/4)` preallocation, the 2023 dead-time cuts (cut only at gaps longer
  than 20,000 bins, or apply them before splitting), and one final stable sort by T over all
  pieces; test that a split conversion equals the whole one on the `phantom_*` and
  `dead_time_x1` cases.
- **A~5** (stage 4, Heron 3): HeLab's TXY writes stay durable and readable by others: created
  with mode `0o666` (the umask applied), fsync, rename, folder fsync (`txy.write_atomic`), which matters once they go beside
  the raw files on a share (Q9.7).
- **A~4** (stage 4): ship the built-in profiles as JSON files inside the package (Q6.11), each
  tested to load equal to the Python definitions.
- **M~1** (for Tony): other TXY on X may be half-written reads like d3667 (TXY mtime within
  seconds of the raw file's). Counting them needs a listing pass on X, which only Tony or the
  Assistant may run. Worth knowing before stage 5 compares HeLab with MATLAB on every shot.
