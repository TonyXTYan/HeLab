# The TXY converter

Reference detail for agents working on `helab/convert/` ([index](README.md)). AGENTS.md keeps the
rules every task must follow; this file keeps the mechanics, names and behaviour. Keep it true:
on Ground, update it in the same commit as the code; on a floor, propose the change in your
handoff. The plan and open decisions are in [`roadmaps/txy-converter.md`](../../roadmaps/txy-converter.md);
stage 1's evidence is in `.ai/sessions/2026-10-29-claude-txy-reference/` (`notes.md`, the
cross-checker's `crosscheck/`).

## What it is

HeLab's replacement for MATLAB's `tdc_autoconverter`: a raw DLD file (`d<N>.txt`, `channel,time`
lines in 25 ps TDC bins) to TXY hits (T s from the trigger, X and Y m). Stage 1 (landed
2026-10-29) is a plain-Python port of the running path of `dld_raw_to_txy_counts` →
`dld_read_5channels_reconst_multi_imp(file, 1, 0, 1, 0)` → `dlmwrite(…, 'precision', 8)`, byte for
byte, and the harness later backends are measured with (`agent/txy-reference`, landed as `d26e196`).
Nothing in the app calls it yet (stage 4).

## `helab/convert/` (Qt-free: standard library and NumPy; every module in `PURE`)

| Module | What |
|---|---|
| `raw` | `parse_raw`/`read_raw` → `RawPulses` (float64 channels and times in file order), as MATLAB's `textscan` reads them; a fast path for uniform `\r\n` or uniform `\n` files, a general reader for everything else. A marked place for stage 4's done-writing checks. |
| `profile` | `DetectorProfile` (frozen, `kw_only`): every constant MATLAB hard-codes; JSON (`SCHEMA`, `_MIGRATIONS`); `content_hash`; built-ins `matlab-2019` (default, Q6.10) and `matlab-2023-lab-edit`. |
| `reconstruct` | `reconstruct(pulses, profile, backend="reference")`; the registry (`register_backend`, `get_backend`, `available_backends`, `Backend.unavailable(profile)`, `releases_gil`, `_MODULES`); `NoRowsError`. |
| `backends/reference` | The port, loop for loop, with the MATLAB line numbers (`L…` 2019, `L2023:…`); `MatchStats` for the x2 report. Readable, not fast. |
| `txy` | `format_txy` (`%.8g`, `NaN`/`Inf`/`-Inf`, `\n` after every row on every platform); `write_txy`/`write_atomic`. |
| `pipeline` | `convert_raw(bytes, profile, backend) -> bytes | None` (None: no file, as the 2019 wrapper for no hits). |
| `samples` | The sample manifest (`~/HeLab-samples/txy-v1/manifest.json`, SHA-256 checked on read); held-in/held-out positions. |
| `check` | `check_txy(ours, reference)`: identical, or the first differing line (`ENDED`, `NO_FINAL_NEWLINE`) and both hit counts; `ReferenceFault` and `prove_fault`. |
| `timing` | `time_shot`/`time_shots` with `Parallelism` (serial, processes, threads, within-shot); `summarise` (SI MB/s per stage, latency). |

`dev/txy/` holds the scripts that read the sample set (tests never do): `check_samples.py` (exit 1
on any unexplained mismatch, or when nothing was checked), `reference_exceptions.py`,
`matlab_variant.py` (MATLAB headless on copies under `.ai/temp/txy/`), `time_samples.py`,
`x2_report.py`, `x2_retry.py`. A script that imports helab sets the folder overrides first
(`source .ai/local/floor-env.sh` on a floor).

## What MATLAB does, and the quirks kept

Read with `textscan`, sort by time, then for each x1 (channel 0) search rows −1, +1, −2, +2, … up to
36 away for x2 (channel 1), then y1 and y2 (channels 2, 3), each within `T_sum` (3200 bins) of x1,
with `|x1 + x2 − y1 − y2| < 400`; T = (tx + ty)/2, X = (x1 − x2)·v⊥·25 ps, Y likewise. The full
walk-through is `crosscheck/matlab-walkthrough.md`. Reproduced on purpose, each named by the
profile where it can vary (the module docstring of `backends/reference.py` lists them with lines):

- `t_zero` is the first row as read, before sorting, whatever its channel; the first sorted row is
  skipped as "the trigger";
- `how_many_x == ~1` is `how_many_x == 0`: a second x2 only ends the search, the first is kept, and
  the other x2 is never retried when y fails (`x2_handling = "matlab"`); a second y pair breaks only
  the inner y2 loop (`y_handling`);
- the x2 test `|x1 − x2| < 3400` never binds: rows beyond `T_sum` are skipped first; y1 and y2 are
  both windowed around x1;
- the **phantom row**: the output is preallocated with `floor(rows/4)` NaN rows and grows with
  zeros, so an x1 with an x2 but no y in a grown row is a hit at T = 0, Y = 0
  (`matlab_overflow_row`);
- sorts are stable, NaN last (NumPy needs `kind="stable"`);
- a file with no rows: MATLAB errors (`NoRowsError`); no hits: the 2019 wrapper writes no file, the
  2023 `dld_raw_to_txy` a 0-byte one (`write_empty_txy`);
- the 2023 lab edit: x1 dead time by `uniquetol` (sorted; a group is everything within ≤ 20,000 bins
  of the group's **first** value, not chained; the first kept), `T_sum_x = 3390`, `T_sum_y = 3275`
  in T only (the window and match sums stay 3200), raw columns (`position_formula`).

**textscan's line endings** (449 + 1,367 MATLAB-judged probes in `tests/data/convert/textscan/`):
only `\n` at the very start of the file are passed over to find the mode; the first line ending
sets it: after `\r\n` (also `\r\r\n`), all of `\r\n`, `\r`, `\n` end lines; after `\n` (also `\n\r`),
only `\n`; after `\r`, only `\r`; a stray ending of the other kind stops the read. Reading starts at
byte 0 in that mode. Other rules (empty fields, BOM, garbage, extra fields) are in `raw`'s docstring.

## Profiles: schema and hash

`content_hash` (SHA-256) covers the fields that change the output, for provenance beside the name
and version. To extend the schema without changing existing profiles' hashes or breaking saved JSON:

- a new field gets a **neutral default** (`NEUTRAL`: the value that behaves as before it existed);
  `from_dict` fills a missing field with it and `content_hash` leaves a field at its neutral value
  out; a field with no neutral value is required;
- any other change (a rename, a changed meaning) bumps `SCHEMA` with a `_MIGRATIONS` step; unknown
  fields are always refused, as are a bool, 0 or future schema;
- `UNUSED_BY_OUTPUT` (the MCP and trigger channels today) stays out of the hash only while the
  output doesn't read it: `tests/test_convert_profile.py` perturbs every field on all cases and
  fails if the output changes while the hash doesn't. The built-ins' hashes are pinned in a test.
- `__post_init__` refuses NaN/Inf, negative sums and tolerances, and repeated corner channels.

## Backends (stage 2)

A backend is a module in `backends/` that calls `register_backend` on import **and** a line in
`_MODULES` (a spawned process-pool worker imports only those). It must give `reference`'s output
byte for byte: every case in `tests/data/convert/`, both built-ins, the quirks above, and every
sample shot through `check_samples.py`. `Backend.unavailable(profile)` says why it can't run (a
package missing, no GPU), so HeLab and the tests work without it. Splitting one shot must keep the
global `t_zero`, the first-row skip (first piece only), the whole-file `floor(N/4)`, the 2023 cuts
(only at gaps over 20,000 bins, or before splitting) and one final stable sort by T.

## Writing TXY

`write_txy` creates a temporary name in the target folder with `os.open(…, O_CREAT|O_EXCL, 0o666)`
(so the kernel applies the umask), writes, fsyncs, renames into place and fsyncs the folder (not on
Windows): a reader never sees half a file. HeLab's own output name is `d_txy_helab_<N>.txy`
(stage 4).

## The sample set and reference faults

`~/HeLab-samples/txy-v1/` (read-only, outside the repo; Q8.6): 8 sets, 309 shots. Under
`matlab-2019`, 303 are identical and 6 are **proved reference faults** (`dev/txy/reference_exceptions.py`,
keyed by set, shot and the reference's SHA-256; `check.prove_fault` re-proves each on every run, and
the checker fails on any unlisted mismatch or a listed one whose proof stops holding):

- `cut`: 2019-halos d3667, MATLAB read the raw file half-written (its TXY is 0.25 s younger than the
  raw file; ours matches with the raw cut at 40,956–40,966 lines);
- `variant`: 2022-07 he3he4 d2, d3, re-converted 2023-02-08 by a third MATLAB variant
  (`matlab-2019` plus a 2 µs x1 dead time);
- `empty`: 2020-halos d400, 2022-11 d5, 2023-02 d187, no hits, and a 0-byte reference from a wrapper
  that writes empty files (reported as its own class, never as identical).

`matlab-2023-lab-edit` is checked against MATLAB's own 2023 output made on copies (all 152 odd
shots and 32 even ones identical).

## Tests and fixtures

`tests/test_convert_*.py` use synthetic raw files (`tests/data/convert/cases/`: 39 cases with both
MATLAB variants' output; `textscan/`: the probes) and `tests_sample_data/`, never the sample set.
Fixtures compared byte for byte sit under a `.gitattributes` `* -text` (`tests/data/convert/`,
`tests_sample_data/`), or Windows CI's autocrlf rewrites them. `tests/test_windows_paths.py` fails
on tracked paths Windows can't check out (reserved names such as `nul.txt`, `<>:"|?*`, a trailing
dot or space).
