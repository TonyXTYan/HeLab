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
HeLab converts in its helpers and with `helab convert` (stage 4, below).

## `helab/convert/` (Qt-free: standard library and NumPy)

The modules are listed by hand in `PURE` (`tests/test_headless_imports.py`), which checks they import
no Qt, plotting library or `helab.utils.constants`: every module below but `backends.numba_kernels`
(imported only with numba). Nothing checks that a new `helab/convert` module is listed, as
`helab.analysis`'s are.

| Module | What |
|---|---|
| `raw` | `parse_raw`/`read_raw` → `RawPulses` (float64 channels and times in file order), as MATLAB's `textscan` reads them; the fast path is `fastio.parse_strict` for uniform `\r\n` or uniform `\n` plain `int,int` files (acceptance tested equal to `_STRICT_CRLF`/`_STRICT_LF`; a field over 16 digits takes the general reader, so one over 309 digits reads as Inf, as textscan does), the general reader for everything else. The done-writing checks: `settled_by_age`, `not_done` and their codes (the settle rules are below). |
| `profile` | `DetectorProfile` (frozen, `kw_only`): every constant MATLAB hard-codes; JSON (`SCHEMA`, `_MIGRATIONS`); `content_hash`; the five built-ins in `BUILTIN_PROFILES` ([Profiles in the app](#profiles-in-the-app)). |
| `reconstruct` | `reconstruct(pulses, profile, backend="reference")`; the registry (`register_backend`, `get_backend`, `available_backends`, `Backend.unavailable(profile)`, `releases_gil`, `_MODULES`); `NoRowsError`. |
| `backends/reference` | The port, loop for loop, with the MATLAB line numbers (`L…` 2019, `L2023:…`); `MatchStats` for the x2 report. Readable, not fast. |
| `txy` | `format_txy` (`%.8g`, `NaN`/`Inf`/`-Inf`, `\n` after every row on every platform) through `fastio`; it refuses anything but a 2-D float64 array (`ValueError`, any size, any memory layout), since hits are float64 by contract and the fast formatter reads bit patterns; `format_txy_by_value` is the general path; `write_txy`/`write_atomic`. |
| `fastio` | The fast strict parse (SWAR digits, GIL-free in NumPy) and the TXY formatter; `raw` and `txy` use them. |
| `split` | Within-shot pieces at safe gaps for any backend, merged byte for byte (`reconstruct_split`); see Backends. |
| `pipeline` | `convert_raw(bytes, profile, backend) -> bytes | None` (None: no file, as the 2019 wrapper for no hits); `convert_shot`: HeLab's own (timed; 0-byte TXY for no hits; pieces with an executor); `APP_BACKEND` = `numpy`. |
| `provenance` | The converted-TXY index (`converted-txy/index.sqlite`: `TxyIndex`, `read_shots`, set-aside, `IndexUnavailable`); `Provenance`, one row per shot (raw fingerprint, profile name/version/hash/tag, backend, TXY size, mtime and SHA-256), `stale`, the file names. |
| `samples` | The sample manifest (`~/HeLab-samples/txy-v1/manifest.json`, SHA-256 checked on read); held-in/held-out positions. |
| `check` | `check_txy(ours, reference)`: identical, or the first differing line (`ENDED`, `NO_FINAL_NEWLINE`) and both hit counts; `ReferenceFault` and `prove_fault`. |
| `timing` | `time_shot`/`time_shots` with `Parallelism` (serial, processes, threads, within-shot through `split`); `summarise` (SI MB/s per stage, latency). |
| `backends/numpy_backend` | `numpy`, the default (stage 2): vectorised match, an exact sequential pass only for interfering x1s. |
| `backends/numba_backend`, `numba_kernels` | `numba` (not shipped, A9.1; optional): the loops under `@njit`, no fastmath, nogil; kernels imported only with numba; their cache folder set by the caller (`set_cache_folder`, absolute). |
| `backends/cython` | `cython` (optional): the loops compiled from `native/cython/_kernel.pyx` by `native/build.py` (through `native/cython/build.py`; never committed); GIL released; unavailable until built or when stale (the source's SHA-256 is compiled in). |
| `backends/rust` | `rust` (not shipped, A9.1; optional): `native/rust/` (PyO3, maturin, abi3), built by `native/build.py`; GIL released; `reconstruct_rust(threads, piece_rows)` splits one shot itself. |
| `backends/mlx_gpu` | `mlx` (not shipped, A9.1; optional; Apple Silicon, macOS ≥ 14): first choices on the GPU in int32 differences, the greedy check and float64 output on the CPU. |

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

**textscan's line endings** (1,367 MATLAB-judged probes in `tests/data/convert/textscan/`: 449 in round 1, 918 in round 2):
only `\n` at the very start of the file are passed over to find the mode; the first line ending
sets it: after `\r\n` (also `\r\r\n`), all of `\r\n`, `\r`, `\n` end lines; after `\n` (also `\n\r`),
only `\n`; after `\r`, only `\r`; a stray ending of the other kind stops the read. Reading starts at
byte 0 in that mode. Other rules (empty fields, BOM, garbage, extra fields) are in `raw`'s docstring.

**Raw channels by era** (provisional while X is still being transferred, 2026-10-29;
[session](../sessions/2026-10-29-claude-txy-2025-plates/)): 0–3 the corners x1, x2, y1, y2; 4 the
MCP (recorded only in some runs, e.g. the 2022-11 ghost counts); 5 the trigger, with extra rows near
it. From June 2026, **channel 7** appears (~0.3 Hz in June, 0.003 Hz by September; never in the
4,335 earlier files checked). It marks the largest of the **bursts**: echo trains of ~23 corner
pulses within ±1 µs starting at the physical x1 end, at 6–8 Hz in 2026 (0.2–0.6 Hz in 2023–24,
4.5 Hz in the 2022-11 ghost counts). Bursts make ~0.8 false hits each (~16 % of hits outside the
atom windows; the (−6.6, −10.3) mm "spot" is one). The converter treats channel 7 like any other
unmapped channel: its rows only take places in the ±36-row search, as in MATLAB (172 of 172
post-swap shots identical). A burst veto is agreed for stage 3 (Q25.5, Tony 2026-10-29: opt-in, its own tag, after the lab check); the lab checks are M25.2 and M25.5.
The corner cables were swapped between 2026-06-27 and 2026-07-21: the image is turned by exactly
180° (± 0.3°) since, which `plates-2025` is to carry as a dated orientation (Q25.1, stage 3).

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
  an explicit reason (e.g. "cython extension not built (stage 4 packaging)") where it isn't built.
  CI's "Converter backends" job sets `HELAB_REQUIRE_BACKENDS=cython` (the compiled backend that
  ships, Q11.2), so there a cython kernel that can't load stops the run and a skip naming it fails
  (`tests/conftest.py`). numba, mlx and rust aren't installed in CI: their tests skip with the reason.
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
MATLAB itself (R2025b, `.ai/sessions/2026-10-30-claude-matlab-bench/results.md`, a busier machine):
the 2019 converter ~22 MB/s per core against numpy's 76 in the same window (~3.5×), 57 % of it in
`dlmwrite`, no gain from its threads, 6-8 s to start; it reproduces the same 303 of 309 archived TXY.
Parallelise across shots in long-lived processes (numpy x12 warm 1,049 MB/s, rust 1,466); threads
stop at ~400 MB/s because the text I/O, `parse_raw` as well as `format_txy`, holds the GIL in
practice; within-shot splitting helps only slow backends or shots much denser than the samples (a
dense 25 MB shot: rust 144 ms, numpy 305 ms, Live's worst case). Decided (Q11.2, Q11.3): `numpy`
the default everywhere (meets both targets on one core); cython ships as the compiled backend;
numba (+145 MB), mlx (+240 MB, slower than numpy) and rust are kept for developers, not shipped.

**Frozen builds** (`agent/txy-packaging`, landed `7cb168e`): `HeLab.spec` lists every `_MODULES`
backend in `hiddenimports` (the reference too: without it a frozen app can't find
`helab.convert.backends`), plus each optional package present in the build Python (the cython
`_kernel` when built); a missing one is left out with a printed line, and the app names the
unshipped ones unavailable with the reason. **What ships (A9.1, Q11.2; `agent/txy-ship`, landed
`134e2ec`): numpy (the default), cython and the reference.** numba, llvmlite, mlx and
`helab_convert_rs` are in `excludes` (`UNSHIPPED_BACKEND_PACKAGES`), so even a build Python that has
them packs none (pandas and scipy import numba optionally); their code stays (Q11.3) for a developer
who installs one. CI's build Python has no numba, so only `test_shipped_backends` and a local build
check those excludes. Size saved on macOS arm64: 357 MB on disk (1149 → 792 MB), 122 MB zipped.
Cython is excluded; the built-in profiles are datas. The helper sets numba's cache folder to HeLab's
temp folder (`<temps>/numba`, Q18.1; numba ignores `NUMBA_CACHE_DIR` when frozen). Compiled sources
and build scripts live in `native/` (`cython/`, `rust/`); binaries are never committed.
`python native/build.py` builds the cython kernel in place (not part of `pip install -e .`);
`--only rust` builds and installs rust's abi3 wheel (maturin installed by hand, `--locked`; never in
CI); `native/check_build.py` checks every backend against the reference on
`tests/data/convert/` (reference and numpy always required; a crash is a failure), in this Python or
(`--frozen APP`) through a packaged app's `convert --once`. CI runs the converter tests that use a
backend only in its "Converter backends" job, whose files are listed by hand in `ci-test.yml`
(the job: [release-and-ci](release-and-ci.md)): a new converter test that runs every available
backend must be added to that list, or it runs only without backends. `test_typing` and
`test_headless_imports` run in CI only without numba and mlx installed; with them, only locally.
`helab/main.py` calls `multiprocessing.freeze_support()` first when frozen, so the worker pool can
spawn there (its order: [release-and-ci](release-and-ci.md)).

## Writing TXY

`write_txy` creates a temporary name in the target folder with `os.open(…, O_CREAT|O_EXCL, 0o666)`
(so the kernel applies the umask), writes, fsyncs, renames into place and fsyncs the folder (not on
Windows): a reader never sees half a file. HeLab's own output name is `d_txy_helab_<tag>_<N>.txt`
(stage 4).

## In HeLab (stage 4)

Built on `agent/txy-helab-core` (landed `775fb1d`; session `.ai/sessions/2026-10-29-claude-txy-helab-core/`).
`reconstruct._load` takes `_LOAD_LOCK` for a backend's first import; `txy.write_atomic(replace=False)`
never replaces an existing file (HeLab's writes beside raw files).

#### The operation

`IOService.submit(owner, generation, path, "convert", payload)` (through `FolderCache.convert(owner, path)`,
which builds the payload and sends the folder's last summary's lists back; Live auto-convert is the
first caller, [live](live.md)). Background lane (never foreground: `convert` isn't in
`folder_cache.FOREGROUND_OPERATIONS`); pausable; refused by Work Offline; held during a cache move (its payload carries
`cache`, so `IOService.uses_cache` is true) and killed by `hold_cache`, like loads. The no-progress
timeout applies (heartbeats while reading, per 8 MB block, and while computing; none while a read
stalls). Payload (`io_ops.convert.ConvertRequest`):

| Field | Meaning |
|---|---|
| `path` | the source folder |
| `profile` | `DetectorProfile.to_dict()` (built-in or user; the helper never looks profiles up) |
| `temps` | HeLab's temp folder (`constants.DIR_TEMPS`), required |
| `cache` | `store_options()` ({} or absent: no data-root key, output falls back to temp) |
| `destination` | `cache` (default) or `temp`: the setting (`read_convert_output`). Not `output`: `IOService._run` sets `payload['output']` to the helper's private folder for every request (found by the Live floor; an end-to-end IOService test covers it). Events and provenance keep their `output` field. |
| `beside` | the app believes the folder's `write_beside` flag is on; the helper checks the store again |
| `beside_confirmed` | command line only: beside for this run without the flag |
| `backend` | default `pipeline.APP_BACKEND` (`numpy`); unavailable → the operation errors before any read |
| `shots` | only these shot numbers (None: every raw file) |
| `seen` | **required**: the previous `convert_summary`'s `waiting` list; `[]` for a folder's first conversion (which then only records: every file not already current waits for the next check). None only from `helab convert --once` (one check, files unmodified for `ONCE_SETTLE_SECONDS` = 60 s). Live and every other caller in the app always send a list; a request without the key is refused. |
| `done`, `kept`, `skip` | the previous summary's `current`, `kept`, `unconvertible`, sent back: not checked again while unchanged |
| `redo` | `stale` (default: convert when the provenance says so) or `always` |
| `workers` | processes (default `DEFAULT_WORKERS`: min(4, cores/2); 1 in a frozen app, see A12.1) |

**Settle rules** (A10.1): converted only when unmodified for `fingerprints.SETTLE_SECONDS` by this
computer's clock, with the same (size, mtime) at the previous check (`seen`) and this one, and again
before and after the read (fstat), so two checks are a check interval apart, not microseconds (the
age alone is fooled by a source clock behind ours or a share's stale attribute cache: Gannet M2). A
file seen for the first time waits one check (Live's interval); a shot with a current TXY is told
apart first and needs no read. With `seen` None (`--once` only) the age must be 60 s. A file dated
more than `fingerprints.FUTURE_SECONDS` ahead waits as `future`, and `clock_skew` (the existing
kind, `fingerprints._clock_ahead`; the app tells the user once per location) is sent once per
conversion. Content: ends with `\n`, first line on `profile.channel_trigger`. Unfinished files are
not read again while unchanged (their `seen` entry carries the reason). **Damaged** (Q18.5, `agent/txy-followups`, landed `c718c71`): a raw file unmodified for 20 s
(`DAMAGED_SECONDS`) both by its mtime and since HeLab first saw that (size, mtime) (a sixth field of
the `seen` entries; `--once` goes by the mtime alone and wants 60 s, `ONCE_SETTLE_SECONDS`, as its settle rule does: Q23.7 (c)) that still fails a content check (no final
newline, off the trigger channel, or no rows, which now waits like the others, Q23.3) is
`shot_unconvertible` `damaged` with its `problem`: no TXY, one notification per file, skipped while
unchanged, never holding up later shots. Heartbeats while a shot computes stop after its budget
(`compute_budget`: 60 s plus 1 s per MB), so a hung backend times out (Gannet L4).

#### Events (`helab/io_ops/events.py`)

The field lists are the `TypedDict`s there (`ConvertPlanEvent`, `ShotConvertedEvent`, `ShotWaitingEvent`,
`ShotUnconvertibleEvent`, `PartialRemovedEvent`, …), which `tests/test_helper_events.py` checks; this
table summarises them.

| Kind | When | Fields (besides `kind`, `path`) |
|---|---|---|
| `convert_plan` | once, after the listing | `output` (`beside`/`cache`/`temp`), `fallback` (why not the one asked), `folder` (HeLab's folder: provenance, and the TXY unless beside), `txy_folder`, `key` (root key or ""), `profile` {name, version, hash, tag, calibrated}, `backend`, `workers`, `raw`, `todo` |
| `shot_converted` | a TXY written | `shot`, `raw_name`, `raw_size`, `raw_mtime_ns`, `raw_sha256`, `output`, `txy`, `txy_size`, `provenance` (the index's path), `hits` (Live's low-count check reads this), `replaced` (why an older HeLab TXY was replaced, or ""), `profile`, `backend`, `seconds` {read, parse, reconstruct, format, write} |
| `shot_waiting` | not converted yet | `shot`, `raw_name`, `raw_size`, `raw_mtime_ns`, `reason` (`settling`, `future`, `changed`, `no_final_newline`, `not_trigger_first`, `no_rows`, `read_failed`), `message` |
| `shot_unconvertible` | settled, can't be converted | same fields; `reason` `damaged` (with `problem`: `no_final_newline`, `not_trigger_first` or `no_rows`), `failed`, or `no_rows` (`NoRowsError` while computing) |
| `shot_kept` | beside: a HeLab TXY already there that this conversion doesn't stand behind | `shot`, `txy`, `reason` |
| `convert_progress` | after each shot (≤ 4/s) | `done`, `todo`, `converted`, `raw_bytes` |
| `convert_summary` | the end, before `done` | `output`, `folder`, `txy_folder`, `converted`, `current`, `waiting`, `unconvertible`, `kept` (lists of `[name, size, mtime_ns]`, `waiting` with reason and message after), `seconds` |
| `partial_removed` | a leftover temporary file of a killed write removed: beside (`folder` is `path`), or in HeLab's own folder | `folder`, `file`, `size`, `age` (s) |
| `clock_skew` (existing kind) | raw files dated over 2 s ahead of this clock | `seconds`, `location` |
| `convert_prefs` | `cache_admin convert_prefs` | `prefs` {write_beside, set_at} |

`tests/test_helper_events.py` counts `helab/convert_cli.py` as an app-side consumer (it logs
the converter's kinds); `convert_prefs` is matched by `FolderCache`.

#### Where files go

**The index (Q26.2, `agent/txy-index`, landed `460360b`):** `<base>/converted-txy/index.sqlite` holds
the provenance: a `folders` table (HeLab's folder by its 24-hex name → key, source path, TXY bytes,
last used) and a `shots` table (the provenance rows), in `helab.convert.provenance`. Caching v2
later moves the provenance into the store's `txy_layers`. **A Don't cache folder converts to the
temp folder** (Q19.5, Q27.4): `_places` reads the store's `no_cache` flag for the folder when the
output is `cache`; flagged, or the flag unreadable → temp. **Unless typed** (Q30.2): `helab convert
--output cache` on a Don't cache folder warns (naming the folder) and asks on a terminal, `[y/N]`,
temp by default and without a terminal; `--output cache-forced` writes to the cache without asking
(one log line). The request's `cache_confirmed` is set by the command line only; the app and the
setting's default keep "the flag wins".

`<base>/converted-txy/<sha256(identity)[:24]>/` (`io_ops.convert.folder_for(base, identity)`),
`base` = the cache folder (`dirname(cache["directory"])`, i.e. `cache_dir()`) for `cache`, else
`temps`; `identity` = the folder's `root://<uuid>/<relative>` key, else `path:<absolute path>`. It
holds `d_txy_helab_<tag>_<N>.txt` (unless beside); no `.json` record or `folder.json` is written any
more (old builds' are ignored, measured and cleared by Settings › Cache only). Beside: only
`d_txy_helab_<tag>_<N>.txt` in the source folder (temporary `.d_txy_helab_<tag>_<N>.txt.<16 hex>.partial`, then
a no-replace rename), and HeLab's folder for that source isn't created. **The provenance row is
written before the TXY's rename, for every output**, pinning the size and mtime of the temporary
file (`txy.write_atomic(before_rename=)`; a rename keeps the mtime on all three OSes); a conversion
stopped between them leaves a row that matches no TXY, so the shot converts again (Gannet L2). A
failed write removes the row only if it is still its own. **Leftovers** (Gannet M1, Q12.7, Q18.6): a beside conversion removes its own
leftover temporary TXY in that source folder: only names matching exactly the pattern `write_atomic`
makes (`txy.partial_pattern`; `convert.partial()`: `^\.d_txy_helab_[a-z][a-z0-9]{1,15}_(?:0|[1-9][0-9]*)\.txt\.[0-9a-f]{16}\.partial$`, ASCII, from `BARE_NAME`),
regular files by `lstat` (a link is left alone, never followed), unmodified for `PARTIAL_MAX_AGE`
(1 h), only in a folder it is writing beside (the flag on, or `--output beside`); each is sent as
`partial_removed` (and traced). **Every** conversion with shots to convert also removes its own
leftovers in HeLab's `converted-txy/` folder for the source folder (`places["folder"]`: under the cache
folder or, when the output is temp, the temp folder), whatever its output, where a kill on Windows
often lands inside `write_atomic`: `own_partial()` matches the TXY's temporaries and those old builds
gave their JSON records and `folder.json`, with the same `lstat`, regular-file and age rules
(`_remove_own_partials`). The index's `-wal`/`-shm` (and an older build's `-journal`) are SQLite's,
never housekeeping's.

#### Provenance (`helab.convert.provenance`)

`converted-txy/index.sqlite` per base, `PRAGMA user_version` 1 (`provenance.SCHEMA`): `folders`
(`folder` 24-hex name, `key`, `source`, `bytes`, `last_used`) and `shots` (`Provenance`'s fields: shot,
raw name/size/mtime/SHA-256, profile name/version/hash/tag/calibrated, backend, output, TXY
name/size/mtime/SHA-256, hits, `converted_at`, HeLab version, seconds per step; one row per (folder,
tag, shot)). Every row written also upserts its folder's `key` and `source` (the folder moved).
`stale(record, raw_size, raw_mtime_ns, profile_hash, txy=(size, mtime))` says why a TXY is out of date
(no TXY or row, the raw file or TXY changed, another profile hash); a TXY is current only while its
size **and mtime** are the row's (Q30.1); backend and profile name/version don't make it stale.
**Journal:** WAL, as the store's (a rollback journal starved two writers on Windows); where
`cache_location_problem(base)` objects (a temp folder on a share or synced folder, Q30.5) a new index
uses a rollback journal (`io_ops.convert.journal_for`). Every open is a fully quoted `file:` URI
(`provenance._uri`). Each shot is one `BEGIN IMMEDIATE` transaction (`_prepare` takes the schema's only
at `user_version` 0); 10 s busy timeout, retried where SQLite answers busy at once (`_patient`). A
conversion holds one connection for its run. **Readers** (loads, Live checks, `save_held`, Settings ›
Cache) never create or set aside an index and get no rows on any error; a load that takes a TXY moves
its folder's `last_used` on at most hourly (`LAST_USED_STEP`, a 200 ms wait), and a use it skips is
sent as `txy_unmarked`, kept in `FolderCache` memory and written in the background about every 10 minutes while any are owed
(A30.4: one `cache_admin` `mark_used` helper, only if newer; not while the disk cache is off, working
offline or the foreground works; a busy index's marks, returned as `unwritten`, stay owed) and as HeLab
quits (Q30.3: a quit save, which takes over from the background write; [live](live.md)). **Damaged** (`SQLITE_CORRUPT`/`NOTADB`)
or **newer** (`user_version` > 1): a conversion sets it aside as `index-{damaged,newer}-<UTC>-<8 hex>.sqlite`
(`provenance.SET_ASIDE_PATTERN`, with its `-journal`/`-wal`/`-shm`) and starts a new one; housekeeping
never removes those (Settings › Cache's Clear removes damaged ones, never a newer HeLab's). An index
that can't be set aside (held open on Windows), is busy past 10 s or can't be written:
`IndexUnavailable` fails the conversion before that shot's rename, to be tried again. Missing or
damaged, shots only convert again.

#### Tags in HeLab's TXY names (Q18.4)

HeLab's TXY are `d_txy_helab_<tag>_<N>.txt` (`.txt`, like MATLAB's `d_txy_forc<N>.txt`), beside the raw
files and in HeLab's folders (provenance in the index; old builds' `.json` records are ignored). Built-in tags are frozen once used
and pinned by a test: `m19v1` (matlab-2019), `m23v1` (matlab-2023-lab-edit), `p17v1` (plates-2017),
`p22v1` (plates-2022), `p25t1` (plates-2025, testing; prefixes `a`/`b`/`t` for alpha, beta, testing;
Q23.1); other profiles are tagged `u` + 32 hex digits of their content hash (Q23.6, `agent/ui-polish`,
landed `c104502`; `USER_TAG_DIGITS`; `file_tag`: a built-in's tag only while its name, tag and hash are the
built-in's). Name patterns take a tag of 1 + 1–32 characters (`profile.NAME_TAG`, spelled out in
`file_kinds.HELAB_TXY`, `provenance._NAME`/`BARE_NAME` and so `partial()`/`own_partial()`, and
`helab_txy._OWN_FILE`; a test checks each); `TAG_PATTERN` (built-ins) stays at 16. A name is 50 characters
plus the shot's digits, 26 more while temporary. TXY from the first builds' `u` + 8 tags still match as
HeLab's, of another tag: a load for the profile ignores them, its shots convert again under the new tag, and
the old files are never deleted or replaced (Settings › Cache measures and clears them with HeLab's own).
**A path too long** (`io_ops.convert.path_too_long`, the OS's own refusal only): ENAMETOOLONG anywhere; on
Windows WinError 206, or WinError 3 / FileNotFoundError on a path of 260+ characters while the target's
folder still exists (a traced stat; gone, the run fails as before and the next check retries;
`convert.PLATFORM`, read at call time, lets tests try Windows' rules). A shot's `txy.write_atomic` refused so
becomes `shot_unconvertible` ("failed") with "Path too long for Windows (N characters; the limit is 259
unless long paths are turned on in Windows): <path>. Choose a shorter cache or temp folder (Settings), or a
shorter folder path", in the Live line's "N unconvertible" and its tooltip, a log warning and
`helab convert`'s output; the run goes on, and the shot isn't tried again while its raw file is unchanged,
this session. HeLab's folder that can't be made (`os.makedirs`) fails that conversion with the same wording. No metadata goes beside the raw files: a beside
TXY is current while newer than its raw file (`provenance.beside_stale`). Untagged
`d_txy_helab_<N>.txy` from before are ignored and never removed (converted again under the new names).
MATLAB's `tdc_autoconverter` skips HeLab's beside TXY only through its first-line check, not by name,
and lab scripts that glob `d*.txt` in a raw folder now also see them: such scripts should match
`d<N>.txt` exactly.

#### TXY sources (Q6.6, Q18.2; `agent/txy-ui` `475c6a6`, `agent/txy-followups` `c718c71`)

Four modes (`helab/utils/txy_sources.py`): `helab-priority` (the default for tabs and Live: HeLab's
current TXY of the chosen profile where they exist, MATLAB's `d_txy_forc` for the rest),
`matlab-priority` (MATLAB's, HeLab's filling shots MATLAB lacks), `helab-only` and `matlab-only`
(the setting `txy_source`, Settings → TXY converter "Tabs and Live read", [settings](settings.md);
old `matlab`/`helab` values read as the priority modes). A choice is a mode plus
a profile tag (`DatasetView.txy_choice`, `source@tag`); both priority modes share the identity `""`
(per-shot origins tell them apart where the data differs), so data of MATLAB's TXY alone keeps its
identity and saved results. FolderCache keys datasets and jobs by choice; a load's or Live check's
base must be of the very choice asked for (`_base(exact=…)`), so a Settings change never carries
held shots of the other mode over. A plot's TXY row picks "As the folder's tab" or a mode and a
profile. `io_ops.helab_txy` finds HeLab's TXY in its
folders (`folders()`: the cache base by root key, temps by root key, temps by path) and beside the raw
files, current only by provenance for the conversion profile's hash (`could_take` limits which records
are read). `load`, `live_check` and `save_held` take `txy` (FolderCache adds it to every load,
`with_txy`) and the held origins; shots are reused only from the same kind of TXY, and a held one is
trusted only with the wanted profile hash. **Only MATLAB's TXY feed the folder-mismatch rule**: a
held HeLab shot whose TXY is gone, changed or no longer current is read again or dropped as removed,
never a mismatch (HeLab's can go or be rewritten legitimately). The dataset signature is the
folder's MATLAB one (`helab_txy.folder_print`: the data's MATLAB shots plus the settled MATLAB TXY of
HeLab-held shots, never waiting or young files). Per-shot origins (`helab:<hash>`) are in the dataset's `info.txy`, `ViewIdentity.source`
and `Coverage.origins`; a 0-byte HeLab TXY is an empty shot. Each plot's settings have a TXY row
(`helab/views/plots/txy_source.py`): the default runs on the tab's data; another source is a dataset the
plot loads itself through FolderCache (RAM only, job key `load:<source>`), reloaded at each Live
revision; Reload of a released plot loads its own source. Live finds the root key itself when the app
has none (asked once per folder per session, `key_asked`).

#### Profiles in the app

Built-ins: `matlab-2019` (default), `matlab-2023-lab-edit`, and the plate profiles `plates-2017`,
`plates-2022`, `plates-2025` (equal to `matlab-2019` in output until calibrated; `plates-2025` marked
uncalibrated in the profile manager by `profile.UNCALIBRATED`; every built-in's `calibrated` field,
sent in events and provenance, is false), shipped as `helab/convert/builtin_profiles/*.json` (`builtin_files`, tested equal to the
definitions; in `setup.py`'s package data and `HeLab.spec`'s datas). User profiles are JSON files in
`<app folder>/profiles` (`helab/convert/user_profiles.py`). Settings → TXY converter
(`helab/views/ConverterTab.py`): the conversion profile, backend and output (the converter rows in
[settings](settings.md)), and the profile manager (built-ins read-only; duplicate, validated edit with
the hash shown, import, export; delete asks, and deleting the profile in use resets the setting;
edits save at once). Names sharing a hash are all shown. Each plot's settings suggest the plate profile
for the folder's date (`PLATE_SWAPS`, `suggested_plates`, Q6.10), never applied.

#### `helab convert --watch FOLDER` (`helab/convert_cli.py`, Q9.5)

Headless, dispatched in `helab/main.py` before any Qt (frozen: `HeLab convert …`; on Windows the
windowed exe has no console, so lines go only to the log). Options: `--once` (one check: files
unmodified for 60 s, to be read and to be called damaged), `--profile`, `--backend`, `--output temp|cache|beside` (beside for that run
without the folder's flag, saving none; Q12.4), `--workers`, `--interval`, `--again` (convert even
current shots). The same `convert_folder` as the helper operation; `--watch`'s first pass only
records and converts from the second, each pass sending the last summary's lists back. It
registers as a running HeLab (no cache move while it runs), finds the data root once, opens the
store like a helper, logs, stops cleanly on Ctrl-C; exit 0; 1 when `--once`'s conversion fails (`--watch` logs a failed pass
and goes on); 2 for usage.

#### Choices made in stage 4 (technical)

- Workers only compute: reads, writes and every source call stay in the helper; workers get bytes,
  return TXY bytes, and exit on their parent's end (a pipe's EOF), so a cancelled helper writes
  nothing afterwards and slot rules hold. One large shot (≥ 20 MB raw) with workers > 1 is cut into
  pieces (`split`) in the pool.
- The converter's per-folder flag is its own store table (`convert_prefs`), not a `folder_prefs`
  column (older HeLabs `INSERT OR REPLACE` named `folder_prefs` columns, which would reset a new one).

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
Both folders' `.gitattributes` and the Windows path check: [testing](testing.md).
