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
| `raw` | `parse_raw`/`read_raw` → `RawPulses` (float64 channels and times in file order), as MATLAB's `textscan` reads them; the fast path is `fastio.parse_strict` for uniform `\r\n` or uniform `\n` plain `int,int` files (acceptance tested equal to `_STRICT_CRLF`/`_STRICT_LF`; a field over 16 digits takes the general reader, so one over 309 digits reads as Inf, as textscan does), the general reader for everything else. A marked place for stage 4's done-writing checks. |
| `profile` | `DetectorProfile` (frozen, `kw_only`): every constant MATLAB hard-codes; JSON (`SCHEMA`, `_MIGRATIONS`); `content_hash`; built-ins `matlab-2019` (default, Q6.10) and `matlab-2023-lab-edit`. |
| `reconstruct` | `reconstruct(pulses, profile, backend="reference")`; the registry (`register_backend`, `get_backend`, `available_backends`, `Backend.unavailable(profile)`, `releases_gil`, `_MODULES`); `NoRowsError`. |
| `backends/reference` | The port, loop for loop, with the MATLAB line numbers (`L…` 2019, `L2023:…`); `MatchStats` for the x2 report. Readable, not fast. |
| `txy` | `format_txy` (`%.8g`, `NaN`/`Inf`/`-Inf`, `\n` after every row on every platform) through `fastio`; it refuses anything but a 2-D float64 array (`ValueError`, any size, any memory layout), since hits are float64 by contract and the fast formatter reads bit patterns; `format_txy_by_value` is the general path; `write_txy`/`write_atomic`. |
| `fastio` | The fast strict parse (SWAR digits, GIL-free in NumPy) and the TXY formatter; `raw` and `txy` use them. |
| `split` | Within-shot pieces at safe gaps for any backend, merged byte for byte (`reconstruct_split`); see Backends. |
| `pipeline` | `convert_raw(bytes, profile, backend) -> bytes | None` (None: no file, as the 2019 wrapper for no hits). |
| `samples` | The sample manifest (`~/HeLab-samples/txy-v1/manifest.json`, SHA-256 checked on read); held-in/held-out positions. |
| `check` | `check_txy(ours, reference)`: identical, or the first differing line (`ENDED`, `NO_FINAL_NEWLINE`) and both hit counts; `ReferenceFault` and `prove_fault`. |
| `timing` | `time_shot`/`time_shots` with `Parallelism` (serial, processes, threads, within-shot through `split`); `summarise` (SI MB/s per stage, latency). |
| `backends/numpy_backend` | `numpy`, the default (stage 2): vectorised match, an exact sequential pass only for interfering x1s. |
| `backends/numba_backend`, `numba_kernels` | `numba` (optional): the loops under `@njit`, no fastmath, nogil; kernels imported only with numba; their cache folder set by the caller (`set_cache_folder`, absolute). |
| `backends/cython` | `cython` (optional): the loops compiled from `native/cython/_kernel.pyx` by `native/cython/build.py` (never committed); GIL released; unavailable until built or when stale (the source's SHA-256 is compiled in). |
| `backends/rust` | `rust` (optional): `native/rust/` (PyO3, maturin, abi3); GIL released; `reconstruct_rust(threads, piece_rows)` splits one shot itself. |
| `backends/mlx_gpu` | `mlx` (optional; Apple Silicon, macOS ≥ 14): first choices on the GPU in int32 differences, the greedy check and float64 output on the CPU. |

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

## Backends (stage 2, landed 2026-10-29)

`_MODULES`: `reference`, `numpy`, `cython`, `mlx`, `numba`, `rust`. A backend is a module in
`backends/` that calls `register_backend` on import **and** a line in `_MODULES` (a spawned
process-pool worker imports only those). It must give `reference`'s output byte for byte: every
case in `tests/data/convert/`, both built-ins, the quirks above, and every sample shot through
`check_samples.py` (all five do, whole and split, with everything built together:
`.ai/sessions/2026-10-29-claude-txy-bench/results.md`). Rules every backend follows:

- **Optional and lazy.** `Backend.unavailable(profile)` says why it can't run (package missing,
  extension not built or stale, no Metal); any error while loading (not only `ImportError`) leaves
  it unavailable with the reason, logged, never raised out of `available_backends()`. The loader is
  thread-safe (the timing harness's threads all make their first call at once). Its tests skip with
  an explicit reason (e.g. "cython extension not built (stage 4 packaging)") until CI builds it.
  An optional package's import carries a targeted pyright ignore, since pyright runs in the suite
  where the package isn't installed.
- **Exact bits.** No FMA contraction or fast-math (`-ffp-contract=off`, `/fp:precise`, no `mul_add`,
  numba without fastmath); T/X/Y in the reference's operation order; stable sorts, NaN last (an
  insertion pre-pass is fine if it hands over to a stable sort: raw files are nearly in time order).
- **Facts the backends use.** Marks only remove candidates: an x1's first choice ignoring used
  pulses is MATLAB's choice unless an earlier hit marked one of its pulses, so a parallel search
  plus a sequential pass over contested x1s is exact (numpy, mlx). The phantom row is the row after
  the last hit, written by the last x pair with no y after it, surviving when past `floor(N/4)`.
- **Within one shot** (`split.reconstruct_split`, rust's and cython's own `threads`): cut only
  between two finite sorted times more than max(window, dead times in bins) apart (every candidate
  test checks the window before the channel, so nothing across a cut is examined); global `t_zero`,
  the first-row skip in piece 0 only, the dead-time cuts per piece (safe because the gap exceeds
  the tolerance); when hits + 1 > N//4 the tail is rerun with the phantom row on; one stable sort
  by T. Proofs: the numpy, rust and cython session notes.

**Measured standing** (`.ai/sessions/2026-10-29-claude-txy-bench/results.md`; serial, all 309 shots, load 4-5): end to end per core numpy 119,
numba 171, cython 170, rust 178, mlx 72, reference 13 MB/s; reconstruction alone 279/869/915/
1056/111/14. Compiled backends then spend 80-83 % of a conversion reading and writing text.
Parallelise across shots in long-lived processes (numpy x12 warm 1,049 MB/s, rust 1,466); threads
stop at ~400 MB/s because the text I/O, `parse_raw` as well as `format_txy`, holds the GIL in
practice; within-shot splitting helps only slow backends or shots much denser than the samples (a
dense 25 MB shot: rust 144 ms, numpy 305 ms, Live's worst case). Recommendation (Q11.2): `numpy`
the default everywhere (meets both targets on one core); one optional compiled backend (rust, or
cython); drop numba (+145 MB) and mlx (+240 MB, slower than numpy).

**Frozen builds:** backends are imported by name from `_MODULES`, so `HeLab.spec` needs
`hiddenimports` for every backend module, the reference included (without it a frozen app can't
find `helab.convert.backends`); mlx also needs `collect_submodules('mlx')` and
`collect_data_files('mlx')`; numba ignores `NUMBA_CACHE_DIR` when frozen (its cache folder is set
through `set_cache_folder`, under `cache_dir()`, Q11.1). Compiled sources and build scripts live
in `native/` (`cython/`, `rust/`); binaries are never committed.

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
