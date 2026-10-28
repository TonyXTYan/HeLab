# Builder's notes: TXY converter stage 1 (Forge, 2026-10-29)

Evidence for the port in `helab/convert/`. MATLAB R2025b, run headless on probe files under
`.ai/temp/builder/probe/` (scratch, gitignored); the cross-checker's 39 cases (`crosscheck/cases/`,
copied into `tests/data/convert/cases/`) confirmed every point below independently.

## MATLAB's read (`tdc_importer`: textscan `%f64%f64`, `,`, ReturnOnError)

Measured on 36 probe files (all now in `tests/test_convert_raw.py`):

| Input | Rows |
|---|---|
| 0-byte file, or only `\r\n` | none (then MATLAB fails at `t_zero = raw(1,2)`) |
| last line without newline | read normally |
| last line `1,` or `1` | (1, NaN) |
| last line `1,3` (cut mid-number) | (1, 3) |
| blank lines anywhere | skipped |
| `\r\n`, `\r`, `\n` | all end a line |
| blanks/tabs around fields | ignored |
| `0,abc` | (0, NaN), then reading stops |
| `abc,300` | reading stops before it (no row) |
| `0,12abc` | (0, 12), then stops |
| `0,1 2` | (0, 1), (2, NaN): a blank separates fields |
| `5,100,7` | (5, 100), (7, NaN) |
| `5,100,` | (5, 100): a comma after a full row is ignored |
| `5,,100` | (5, NaN), (100, NaN) |
| `,200` | (NaN, 200) |
| `Inf`, `-inf`, `nan`, `NaN` | ±Inf, NaN |
| `+5`, `.5`, `5.`, `1E3`, `1d3`, `1e+3` | numbers (`d` is an exponent) |
| `1e` | 1, then stops (`e` fails as the next field) |
| `0x10` | 0, then stops |
| `-` or `.` alone | NaN for that field, then stops |
| NUL padding after the last line | ignored (stops there) |
| UTF-8 BOM | no rows |
| 9007199254740993 | 9007199254740992 (rounded to nearest) |

**Line endings** (Lens's F1, then 10 more probes of mine): the first non-blank line's ending
sets the mode. `\n` → only `\n` ends lines (a later `\r` is a stray character: the read stops);
a run of `\r` then `\n` (`\r\n`, `\r\r\n`) → `\r\n`, `\r` and `\n` all end lines; `\r` not followed
by `\n` → only `\r` (a later `\n` stops the read). `\n\r` counts as `\n`. Leading blank lines
don't set it (`\n1,10\r\n2,20\r\n` reads 2 rows). All 449 of Lens's probes (`tests/data/convert/textscan/`)
and my 10 are tests.

`raw._parse_textscan` implements exactly this; files of plain `\d+,\d+\r?\n` lines (every sample)
take `_parse_strict` (all `\r\n` or all `\n`; a mixed file takes the general reader), which gives
the same arrays (tested).

## MATLAB's write (`dlmwrite(…, 'precision', 8)`)

`%.8g` per value, `,` between, `\n` after every row including the last (the samples, written on
the Windows lab PC, have `\n` too). `-0` → `-0`, NaN → `NaN`, ±Inf → `Inf`/`-Inf`, 99999999.5 →
`1e+08`, 5e-324 → `4.9406565e-324`. `dlmwrite` of `[]` or `zeros(0,3)` writes a 0-byte file.
Python's `%.8g` matches C's for finite values (all 309 sample TXY and the cases agree).

## uniquetol (the 2023 x1 dead time)

`uniquetol(v, 20000, 'DataScale', 1)` on sorted values: groups are the values within ≤ 20000 of
the group's **first** value (not chained: 0, 10000, 20000 | 30000, 40000, 50000); IA keeps the
first of each group; ties keep the lowest index; every NaN is its own group. `0.5e-6/25e-12` is
exactly 20000. `dld_output_sorted(x1_index(lgc)) = nan` is linear indexing into column 1 (the
channel), so the dropped x1 rows just get channel NaN.

## Quirks reproduced (all in `backends/reference.py` and named in `DetectorProfile`)

From the brief: `how_many_x == ~1` (the first of two x2 kept; the second only stops the search),
the first sorted row skipped as the trigger (even when it is a corner), `t_zero` from the
unsorted first row, the −1, +1, −2, +2 … search over 36 rows, the T_sum skip, used pulses set to
channel NaN, no retry of the other x2.

Found while building (and by Lens independently):

1. **Phantom row** (`matlab_overflow_row`): the output is preallocated `NaN(floor(N/4), 5)`; MATLAB
   grows it with **zeros** when `which_row` passes the end, so an x1 with an x2 but no y in a grown
   row keeps T = 0 and survives the `isnan(col1)` filter: a hit at T = 0, X = (x1 − x2)·v·bin, Y = 0.
   Only reachable when nearly every row is used (tiny files); none of the samples hit it.
2. **The 3400 x2 check never binds**: rows more than T_sum = 3200 from x1 (`>`, so 3200 is kept)
   are skipped before it, so |x1 − x2| ≤ 3200 in effect. The y pulses are windowed relative to
   **x1**, not y1, and the y2 loop is centred on x1 too.
3. **A second y pair** breaks only the inner y2 loop; the outer y1 loop runs on, and only counts.
4. **X/Y formulas differ between variants**: 2019 computes ((x1 − tx) − (x2 − tx))·v·bin, the
   2023 edit (x1 − x2)·v·bin (`position_formula`). For integer times below 2^52 (every TDC file)
   they give the same doubles (Lens's F4); they can differ only for times with a fraction.
5. **Empty file → MATLAB error** (`NoRowsError`); **no hits** → 2019's `dld_raw_to_txy_counts`
   writes no file, the 2023 `dld_raw_to_txy` a 0-byte one (`write_empty_txy`).
6. A NaN time (truncated line) sorts last (MATLAB's sort is stable, NaN last) and never matches;
   a NaN `t_zero` (first line `5,`) makes every time NaN: no hits.
7. The final sort by T is stable (equal T keep their order of finding).

## The sample references

matlab-2019, all 309 shots: see the handoff's table. Three held-in references are not the 2019
converter's output for today's raw file; each is proved on every check run
(`dev/txy/reference_exceptions.py`, keyed by set, shot and reference SHA-256):

- `2019-halos-old-plates` d3667: the TXY was written 0.25 s after the raw file's mtime, and our
  output equals it when the raw is cut to any of lines 40,956–40,966 of 41,092: MATLAB read a
  half-written file. The evidence for stage 4's settle checks.
- `2022-07-old-plates-he3he4` d3: TXY written 2023-02-08 (raw 2022-07-27), byte-identical to
  matlab-2019 **plus a 2 µs x1 dead time** (uniquetol; 2019 time sums and X/Y formula). A third
  MATLAB variant, in no repo we have; it sits between the 2019 code and the 2023-08 lab sync
  (which has 0.5 µs, new time sums and the raw-columns change). Tried and ruled out: the 2023
  edit, 0.5/1/5 µs on x1, the commented-out x2/y1/y2 cuts, search depths 4–20.
- `2022-11-ghost-counts-mcp` d5: a 256-byte trigger-only file (15 trigger rows, one x1), no
  hits; its 0-byte TXY was written 54 days later by a wrapper that writes empty files.

`tests_sample_data/`: the 17 raw/TXY pairs in `bad/` and `goodish/` are reproduced byte for byte
(tested); `bad/d7`, `bad/d9` have no TXY; `bad_txy/d256`'s TXY is the deliberately broken fixture.

## Timings of the reference (Apple Silicon, 16 cores, machine busy: load ~8)

All 309 shots, 217.5 MB raw, 1.48 M hits, `dev/txy/time_samples.py`:

| Run | read MB/s | reconstruct MB/s | write MB/s | total MB/s | wall MB/s | latency median / max |
|---|---|---|---|---|---|---|
| serial | 70 | 13.7 | 171 | 10.7 | 10.7 | 47 / 754 ms |
| serial, small shots (285) | 68 | 10.0 | 113 | 8.1 | | 46 / 284 ms |
| serial, large shots (24) | 73 | 23.5 | 416 | 17.0 | | 135 / 754 ms |
| 4 processes | 72 | 13.6 | 165 | 10.7 | 42 | 47 / 729 ms |

Reconstruction dominates (~80 % of the time) in the reference; reading (the strict fast path) and
writing are not the bottleneck yet. Live (one shot every ~30 s) is already met; bulk at ~100 MB/s
needs stage 2.

## Packages

None beyond `requirements.lock`.
