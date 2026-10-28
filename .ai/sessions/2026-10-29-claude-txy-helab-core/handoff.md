# Handoff: TXY converter stage 4, HeLab core (`agent/txy-helab-core`)

Worker: Keel (Claude Code, Opus 5.5), 2026-10-29. Base `ed35099`; brief in [brief.md](brief.md).

## Summary

HeLab now converts settled raw files to `d_txy_helab_<N>.txy` in its I/O helpers (operation
`convert`), with the settle checks, provenance per shot, the three outputs (cache, temp, beside)
and the AGENTS.md write rule proven by a test; `helab convert --watch <folder>` runs the same
function headless. No GUI controls: the Live, UI and packaging floors build on the interfaces
listed below. On the sample set (manual, read-only, output to the floor's temp folder) the
helper's output is byte-identical to MATLAB's for 95 of 96 shots of three sets (2019 halos,
2023-02 new plates, 2022-11 MCP), the one difference being the known `cut` fault (d3667).

**Checks** (at `HEAD` of `agent/txy-helab-core`): `pytest -n 4 --reruns 5 --reruns-delay 1
--basetemp=.ai/temp/pytest`: 8022 passed, 669 skipped (the compiled and MLX backends' tests, not
built or installed here, by design), **no RERUN**; `mypy helab/ --strict`, `mypy tests --strict`,
`pyright helab tests`: clean. After Gannet's fixes and the merge of `dev/v0.0.7` (`b08627a`): 8034
passed, 669 skipped, no RERUN with `--basetemp=.ai/temp/pytest`; with `--basetemp` in the session's
scratchpad (outside the checkout and outside `tempfile.gettempdir()`), 8035 passed, 669 skipped,
**1 RERUN**: `test_helabMainWindow.py::test_the_view_menu_has_no_thread_status_item_and_its_setting_is_retired`,
reason "Tests never touch real data, but this test's I/O asked for: ['<basetemp>/popen-gw2/test_window_icon_is_found_from0']"
(A~6). Types clean. Manual: Ctrl-C (SIGINT to the process group, as a terminal sends it)
during a 4-worker conversion stops in ~0.15 s with exit 0, no worker left and no partial file.

## What was built

| Path | What |
|---|---|
| `helab/io_ops/convert.py` (new) | `convert_folder(path, request, send)`: the operation. `ConvertRequest` (the payload), `folder_for`, `DEFAULT_WORKERS`, `SPLIT_BYTES`. Module docstring: settle checks, outputs, processes. |
| `helab/convert_cli.py` (new) | `helab convert --watch FOLDER` (`main(argv)`). |
| `helab/convert/provenance.py` (new, `PURE`) | `Provenance` (JSON record per shot), `stale`, `txy_name`, `provenance_name`, `TXY_PATTERN`. |
| `helab/convert/raw.py` | The done-writing checks at the marked place: `settled_by_age`, `not_done`, codes `SETTLING`, `CHANGED`, `NO_FINAL_NEWLINE`, `NOT_TRIGGER_FIRST`, `NO_ROWS`, `WAITING`. |
| `helab/convert/pipeline.py` | `convert_shot` (HeLab's own: timed, always a TXY, 0 bytes for no hits; pieces with an executor) → `Converted`; `APP_BACKEND = "numpy"`. `convert_raw` unchanged. |
| `helab/convert/txy.py` | `write_atomic(..., replace=False)`: never replaces an existing file (hard link, else check + rename). |
| `helab/convert/reconstruct.py` | `_LOAD_LOCK` (an `RLock`) around a backend's first import. |
| `helab/io_ops/events.py` | 8 kinds (below). |
| `helab/io_helper.py` | Dispatches `convert`; it is in `SOURCE_OPERATIONS` (source guard; `OFFLINE_REFUSED`). |
| `helab/io_ops/admin.py` | `cache_admin convert_prefs` (read, or set `write_beside`). |
| `helab/utils/cache_store.py` | Table `convert_prefs (path, write_beside, set_at)` in `SCHEMA` and `_migrate`; `read_convert_prefs`, `set_convert_prefs`; moved by `rekey_subtree`; cleared by `clear_prefs`; counted in `inventory()["prefs"]["write_beside"]`. |
| `helab/utils/folder_cache.py` | `convert_prefs` (RAM), `write_beside(path)`, `set_write_beside(path, on)`, `read_convert_prefs(path)`; `convert_prefs` and `prefs_cleared` handled. |
| `helab/utils/io_service.py` | `convert` in `PAUSABLE`, `LABELS`, `NOUNS`; not in `OFFLINE_OPERATIONS` or `LOCAL_OPERATIONS`. |
| `helab/utils/file_kinds.py` | `HELAB_TXY` (`d_txy_helab_<N>.txy`, `loaded=False`, `sized=False`, `counted_empty=False`: a summary names it only when present, so saved summaries keep their shape). |
| `helab/utils/settings_defaults.py`, `constants.py` | Row `converted_txy_output` (`cache` default, or `temp`); `read_convert_output(settings)`. |
| `helab/main.py` | `multiprocessing.freeze_support()` first when frozen; `convert` subcommand dispatched before Qt widgets, caches or Dash. |
| `tests/test_convert_helab.py` (new) | 32 tests (below). Updated: `test_cache_switch`, `test_folder_flags`, `test_headless_imports` (`provenance` in `PURE`), `test_helper_dispatch` (route), `test_helper_events` (`convert_cli.py` on the app side), `test_settings_defaults` (the new row isn't read by the window yet). |

## Interfaces for the Live, UI and packaging floors

### The operation

`IOService.submit(owner, generation, path, "convert", payload)` (through `FolderCache` as the
floor sees fit; nothing submits it yet). Background lane unless `FolderCache` makes it
foreground; pausable; refused by Work Offline; held during a cache move (its payload carries
`cache`, so `IOService.uses_cache` is true) and killed by `hold_cache`, like loads. The no-progress
timeout applies (heartbeats while reading, per 8 MB block, and while computing; none while a read
stalls). Payload (`io_ops.convert.ConvertRequest`):

| Field | Meaning |
|---|---|
| `path` | the source folder |
| `profile` | `DetectorProfile.to_dict()` (built-in or user; the helper never looks profiles up) |
| `temps` | HeLab's temp folder (`constants.DIR_TEMPS`), required |
| `cache` | `store_options()` ({} or absent: no data-root key, output falls back to temp) |
| `output` | `cache` (default) or `temp`: the setting (`read_convert_output`) |
| `beside` | the app believes the folder's `write_beside` flag is on; the helper checks the store again |
| `beside_confirmed` | command line only: beside for this run without the flag |
| `backend` | default `pipeline.APP_BACKEND` (`numpy`); unavailable → the operation errors before any read |
| `shots` | only these shot numbers (None: every raw file) |
| `seen` | **required**: the previous `convert_summary`'s `waiting` list; `[]` for a folder's first conversion (which then only records: every file not already current waits for the next check). None only from `helab convert --once` (one check, files unmodified for `ONCE_SETTLE_SECONDS` = 60 s). Live and every other caller in the app always send a list; a request without the key is refused. |
| `done`, `kept`, `skip` | the previous summary's `current`, `kept`, `unconvertible`, sent back: not checked again while unchanged |
| `redo` | `stale` (default: convert when the provenance says so) or `always` |
| `workers` | processes (default `DEFAULT_WORKERS`: min(4, cores/2); 1 in a frozen app, see A~1) |

**Settle rules** (A10.1): converted only when unmodified for `fingerprints.SETTLE_SECONDS` by this
computer's clock, with the same (size, mtime) at the previous check (`seen`) and this one, and again
before and after the read (fstat), so two checks are a check interval apart, not microseconds (the
age alone is fooled by a source clock behind ours or a share's stale attribute cache: Gannet M2). A
file seen for the first time waits one check (Live's interval); a shot with a current TXY is told
apart first and needs no read. With `seen` None (`--once` only) the age must be 60 s. A file dated
more than `fingerprints.FUTURE_SECONDS` ahead waits as `future`, and `clock_skew` (the existing
kind, `fingerprints._clock_ahead`; the app tells the user once per location) is sent once per
conversion. Content: ends with `\n`, first line on `profile.channel_trigger`. Unfinished files are
not read again while unchanged (their `seen` entry carries the reason). No rows once settled:
`shot_unconvertible` `no_rows` (Q10.2). Heartbeats while a shot computes stop after its budget
(`compute_budget`: 60 s plus 1 s per MB), so a hung backend times out (Gannet L4).

### Events (`helab/io_ops/events.py`)

| Kind | When | Fields (besides `kind`, `path`) |
|---|---|---|
| `convert_plan` | once, after the listing | `output` (`beside`/`cache`/`temp`), `fallback` (why not the one asked), `folder` (HeLab's folder: provenance, and the TXY unless beside), `txy_folder`, `key` (root key or ""), `profile` {name, version, hash, calibrated}, `backend`, `workers`, `raw`, `todo` |
| `shot_converted` | a TXY written | `shot`, `raw_name`, `raw_size`, `raw_mtime_ns`, `raw_sha256`, `output`, `txy`, `txy_size`, `provenance` (its JSON path), `hits` (Live's low-count check reads this), `replaced` (why an older HeLab TXY was replaced, or ""), `profile`, `backend`, `seconds` {read, parse, reconstruct, format, write} |
| `shot_waiting` | not converted yet | `shot`, `raw_name`, `raw_size`, `raw_mtime_ns`, `reason` (`settling`, `future`, `changed`, `no_final_newline`, `not_trigger_first`, `read_failed`), `message` |
| `shot_unconvertible` | settled, can't be converted | same fields; `reason` `no_rows` or `failed` |
| `shot_kept` | beside: a HeLab TXY already there that this conversion doesn't stand behind | `shot`, `txy`, `reason` |
| `convert_progress` | after each shot (≤ 4/s) | `done`, `todo`, `converted`, `raw_bytes` |
| `convert_summary` | the end, before `done` | `output`, `folder`, `txy_folder`, `converted`, `current`, `waiting`, `unconvertible`, `kept` (lists of `[name, size, mtime_ns]`, `waiting` with reason and message after), `seconds` |
| `partial_removed` | beside: a leftover temporary TXY of a killed write removed | `file`, `size`, `age` (s) |
| `clock_skew` (existing kind) | raw files dated over 2 s ahead of this clock | `seconds`, `location` |
| `convert_prefs` | `cache_admin convert_prefs` | `prefs` {write_beside, set_at} |

`tests/test_helper_events.py` counts `helab/convert_cli.py` as an app-side consumer (it logs
the converter's kinds); `convert_prefs` is matched by `FolderCache`.

### Where files go

`<base>/converted-txy/<sha256(identity)[:24]>/` (`io_ops.convert.folder_for(base, identity)`),
`base` = the cache folder (`dirname(cache["directory"])`, i.e. `cache_dir()`) for `cache`, else
`temps`; `identity` = the folder's `root://<uuid>/<relative>` key, else `path:<absolute path>`. It
holds `d_txy_helab_<N>.txy` (unless beside), `d_txy_helab_<N>.json` (always) and `folder.json`
(`{"helab": "converted-txy-folder", "version": 1, "key", "source", "updated_at"}`). Beside: only
`d_txy_helab_<N>.txy` in the source folder (temporary `.d_txy_helab_<N>.txy.<16 hex>.partial`, then
a no-replace rename); never a raw file, an existing TXY, or the provenance, which is written
**before** the beside TXY (a conversion stopped between them leaves a stale record: the shot is
converted again, never kept for good; Gannet L2; in the cache or temp the TXY goes first, so an old
record no longer matches it). **Leftovers** (Gannet M1, Q~7): a beside conversion removes its own
leftover temporary files in that folder: only names matching exactly the pattern `write_atomic`
makes (`txy.partial_pattern`; `convert.partial()`: `^\.d_txy_helab_\d+\.txy\.[0-9a-f]{16}\.partial$`),
regular files by `lstat` (a link is left alone, never followed), unmodified for `PARTIAL_MAX_AGE`
(1 h), only in a folder it is writing beside (the flag on, or `--output beside`); each is sent as
`partial_removed` (and traced).

### Provenance (`helab.convert.provenance`)

A JSON record per shot (`{"helab": "helab-txy-provenance", "version": 1, …}`): shot, source folder
and key, raw name/size/mtime/SHA-256, profile name/version/hash/calibrated, backend, output, TXY
name/size/SHA-256, hits, `converted_at`, HeLab version, seconds per step. `stale(record, raw_size,
raw_mtime_ns, profile_hash, txy_size)` says why a TXY is out of date (no TXY or record, the raw
file or TXY changed, another profile hash); backend and profile name/version don't make it stale
(equal hashes convert alike). Why a record per shot and not a manifest: each is written once by
the conversion that made its TXY, atomically, so two conversions never rewrite each other's, and
Live writes one small file per shot instead of the folder's whole list each time.

### For the UI floor

- Which TXY loads (Q6.6): `file_kinds.HELAB_TXY` is counted only; loads read MATLAB's. HeLab's in
  the cache/temp aren't in the source listing at all: find them with `folder_for` and the
  folder's key (`convert_plan.key`).
- The flag: `FolderCache.write_beside(path)`, `set_write_beside(path, on)` (needs a data root; no
  session-only choice), `read_convert_prefs(path)`; `folderPrefsChanged` fires on a change;
  Clear folder preferences clears it too (`prefs_cleared`). Listings don't attach it yet.
- The setting: `converted_txy_output`, `read_convert_output(settings)`; once the window reads it,
  drop it from `test_settings_defaults`'s exceptions.
- Profiles: send `DetectorProfile.to_dict()` of the chosen one. A10.3 (built-ins as JSON files) is
  not done here.
- **Clear folder preferences** (Settings → Cache) now also turns off `write_beside` (`clear_prefs`
  clears `convert_prefs` too), but `CacheTab`'s confirmation and row text (`CacheTab.py:433`, `:609`)
  name only "not cached" and "not auto-loaded": say it there too, from `inventory()["prefs"]
  ["write_beside"]` (Gannet L3; not edited here).

### For the packaging floor

- `helab/main.py` calls `multiprocessing.freeze_support()` first when frozen, so a worker the
  helper spawns (`--multiprocessing-fork`) runs and exits there. Check it in the built app
  (A~1), then let `DEFAULT_WORKERS` be the same frozen as from source.
- `HeLab convert --watch …` from a terminal: macOS `HeLab.app/Contents/MacOS/HeLab convert …`;
  on Windows the windowed exe has no console, so its lines go only to the log file (A~2).
- Backends are imported by name (`reconstruct._MODULES`), so they need `hiddenimports`; the numba
  cache folder is `<cache folder>/numba` (or `<temps>/numba` with the cache off), set in the helper
  and in each worker before first use.

## Decisions made here (technical; say if one is Tony's)

- **Numba's cache after a cache move:** neither restart nor stray folder is needed. A `convert`
  helper is one request per process, its payload carries `cache`, so `hold_cache` kills it before
  a move and the next one starts with the new folder. Only `helab convert` lives long, and it
  registers as a running HeLab, so no move runs while it does.
- **Workers only compute.** Reads, writes and every source call stay in the helper; workers get
  bytes and return TXY bytes, and exit on their parent's end (a pipe's EOF; tested by killing a
  helper mid-folder). So a cancelled helper writes nothing afterwards and slot rules hold.
- **Converter flags in their own table** (`convert_prefs`), not a `folder_prefs` column: older
  HeLabs write `folder_prefs` rows with `INSERT OR REPLACE` of named columns, which would reset a
  new column; and the existing flag API and tests keep their shape. Same rules otherwise.
- **`helab convert --output beside`** stands for the folder's flag for that run and saves nothing
  (Q~4).
- **One large shot** (≥ 20 MB raw) with workers > 1 is cut into pieces (`split`) in the pool.
- **`--once`** is one check (`seen` None): files unmodified for 60 s convert, younger ones are
  reported waiting; exit 0, 1 when the conversion fails, 2 for usage. **`--watch`**'s first pass
  only records (`seen` = `[]`) and converts from the second, each pass sending the last summary's
  lists back.

## Proposed doc changes (for the Coordinator)

### `.ai/architecture/converter.md`

Replace "Nothing in the app calls it yet (stage 4)." with "HeLab converts in its helpers (stage
4, below)." Add `provenance` to the module table: "`provenance`: `Provenance`, HeLab's JSON record
per shot (raw fingerprint, profile name/version/hash, backend, TXY size and SHA-256), `stale`,
the file names." In `raw`'s row replace "A marked place for stage 4's done-writing checks." with
"The done-writing checks: `settled_by_age`, `not_done` and their codes." In `pipeline`'s row add
"`convert_shot`: HeLab's own (timed; 0-byte TXY for no hits; pieces with an executor);
`APP_BACKEND` = `numpy`." Under "Writing TXY" add "`replace=False` never replaces an existing
file (HeLab's writes beside raw files)." Under Backends add "`_load` takes `_LOAD_LOCK` for a
backend's first import." Then new sections, from the interface sections above, shortened:

- **In HeLab (stage 4): the `convert` operation**: `io_ops.convert.convert_folder`, the payload
  table, lanes (background, pausable, offline refused, held during a cache move), workers
  (compute only; parent-death pipe; `DEFAULT_WORKERS`, 1 frozen; `SPLIT_BYTES`), heartbeats.
- **Settle checks**: the rules above, with d3667 as the evidence; `seen`/`done`/`skip`.
- **Events**: the table above.
- **Output locations**: the "Where files go" text, the setting, the flag (`convert_prefs`), the
  temp fallback without a data root (Q~1).
- **Provenance**: the record and `stale`, and why per shot.
- **`helab convert --watch`**: the options, `HeLab convert …` frozen, instance lock, root
  discovery once, logs, Ctrl-C, exit codes.

### `.ai/architecture/io-and-browsing.md`

- The operation list in the first paragraph: add `convert` to the families ("browse, scanning,
  loading, save_held, live, convert, icons, …").
- Names tests patch: `fingerprints.SETTLE_SECONDS` is now also read by `convert` (as
  `fingerprints.SETTLE_SECONDS`), so move it from "patched and read only in their own module" to
  the "called as `module.name`" list; `convert._read_raw` is patched and read only in `convert`.
- Queue rules: "`convert` (TXY conversion) is source I/O in the background slots, pausable like
  loads, refused by Work Offline, and held by a cache move like any request carrying `cache`."

### `.ai/architecture/cache-store.md`

After the folder flags sentence: "The converter's flags (`convert_prefs`: `write_beside`, Q9.7)
are a table of their own with the same rules: newest `set_at` wins, never removed by Clear all,
purges or making room, turned off by Clear folder preferences, moved by a nested root's re-key;
`cache_admin convert_prefs` reads or sets one (`FolderCache.write_beside`/`set_write_beside`)."
Add `convert_prefs` to the `_migrate` list. And: "HeLab's own TXY under the cache folder
(`converted-txy/`) aren't in the store: outside the disk budget, and nothing removes them without
asking (Q~3; whether they join the budget later, and so the housekeeping list, is Tony's)."

### `AGENTS.md`

- Code map: a row "`helab/convert_cli.py` | `helab convert --watch` (headless converter) |
  [converter](.ai/architecture/converter.md)", and `convert` in the `io_helper` row's operations.
- The cache rule "Only helpers open the store": "Only helpers (and `helab convert`, a headless
  process without the GUI) open the store".
- The write rule (Q~4, Side at landing): "…and, where the user turns it on per folder, or asks for
  it on the command line, converted `d_txy_helab_<N>.txy`".
- The housekeeping list, a line **(Q~7, to confirm)**: "a beside conversion deletes its own
  leftover temporary TXY in that source folder (`.d_txy_helab_<N>.txy.<16 hex>.partial`, exactly
  that pattern, regular files over an hour old, never through a link);".

## Provisional items

Q~1–Q~5 were **decided by Side overnight as proposed, for Tony to confirm** (2026-10-29).

- **Q~1** (decided by Side, for Tony to confirm): a folder without a data root, asked for
  `cache`, converts to the temp folder (`convert_plan.fallback` says "no .helab-root found here or
  above"), following "no data root, no disk cache". Decided: yes (built).
- **Q~2** (decided by Side, for Tony to confirm): provenance is never written beside the raw files
  (only `d_txy_helab_<N>.txy` is allowed there), so another computer reading a beside TXY doesn't
  know its profile. Options: (a) as now; (b) allow `d_txy_helab_<N>.json` beside too (amends
  AGENTS.md's write rule). Decided: (a) until a second HeLab needs it (stage 5 or Q6.7).
- **Q~3** (decided by Side, for Tony to confirm): HeLab's TXY in the cache folder are outside the
  8 GB budget and no housekeeping removes them. Decided: the UI floor shows their size in Settings →
  Cache with a Clear (asked first). **For Tony:** whether converted TXY join the disk budget later;
  that would add them to AGENTS.md's housekeeping list. Until then nothing removes them without
  asking.
- **Q~4** (decided by Side, for Tony to confirm): `helab convert --output beside` writes beside for
  that run without the folder's flag (the command line is the user's choice for that folder), and
  saves no flag. Decided: yes. Side updates AGENTS.md's write rule at landing ("where the user
  turns it on per folder, or asks for it on the command line").
- **Q~5** (decided by Side, for Tony to confirm): a settled raw file that never gets a final
  newline (or starts off the trigger channel) waits for good, re-checked only when it changes.
  Decided: keep waiting; Live shows it as waiting with the reason (no timer turning it
  unconvertible).
- **Q~6** (idea for Tony, from Side; not built): a manual **Convert anyway** for a file stuck
  waiting (no final newline, or off the trigger channel): the user's choice to convert it as it
  is, still never one modified within the settle age. A seam for it: a request field naming the
  shots to convert despite the content checks (e.g. `force_shots`), recorded in the provenance;
  for the Live or UI floor if Tony wants it.
- **Q~7** (Tony; Side decided, for Tony to confirm): a helper killed mid-way through a beside write
  (Cancel, a no-progress timeout, a cache move, Quit now; fsync can be slow on shares) leaves
  `.d_txy_helab_<N>.txy.<16 hex>.partial` in the source folder. Decided: a later beside conversion
  of that folder deletes such files of its own (exact pattern, regular file, over 1 h old, no
  links), sent as `partial_removed`; this is a deletion in a source folder, so it goes on
  AGENTS.md's housekeeping list (line above). Alternative: leave them and list them for the user.
- **A~1** (packaging floor): in the built app, run a `convert` with `workers` 2 (spawned workers
  through `freeze_support`) on all three OSes; if it works, make `DEFAULT_WORKERS` the same as
  from source.
- **A~2** (packaging floor): on Windows the windowed `HeLab.exe convert …` has no console; check
  where its output goes, and consider a small console launcher (`HeLab-convert.exe`) if the
  acquisition PC needs one.
- **A~3**: the numba floor's A~5 (a conftest session fixture setting the numba cache folder) is not
  done here (numba isn't installed on this floor, so no test loads its kernels).
- **A~4**: A10.3 (built-in profiles as JSON files) is not done here; it fits the UI floor's
  profile manager.
- **A~5** (Live floor): send each `convert_summary`'s lists back as `seen`/`done`/`skip`, so done
  shots aren't checked again and unfinished ones aren't read again.
- **A~6** (known issue, not from this floor): with `--basetemp` outside both the checkout and
  `tempfile.gettempdir()`, `test_window_icon_is_found_from_any_launch_folder` `chdir`s into its
  `tmp_path`, which `constants.DEV_POTENTIAL_DATA_PATHS` then lists (the working folder), so a
  helper of that window asking for it is refused by the source guard after the test ends, and the
  next test on the worker fails once (passed on rerun). Fix: let the guard allow pytest's basetemp
  (e.g. conftest adds it to the allowed folders), or restore the window's helpers before the test
  returns. For `roadmaps/known-issues.md`.
- **M~1** (Tony, lab): run `helab convert --watch <a copy of a run folder> --output temp` on the
  acquisition PC while files arrive (or copy them in one by one), and check that no shot is read
  early on the lab's share (mtime granularity, Windows file sharing: a raw file open for writing
  may fail to read, `read_failed`, retried next check).

## Tests

`tests/test_convert_helab.py`: settle checks (age, future date, half-written, off-trigger, no
rows; a file changing between checks and while read); HeLab's conversion (reference bytes, 0-byte
TXY for no hits); provenance round trip and `stale`; `write_atomic(replace=False)`; the operation
(temp, cache keyed by root, no root → temp, only some shots, workers and one large shot in pieces
byte-identical, a better profile converts again, `done`/`seen`/`skip`); beside (needs the flag,
the write audit: nothing but `d_txy_helab_<N>.txy` and its temporary name reaches the source
folder, an existing TXY kept, nothing written on a second pass; the command line's beside); the
store table (newest wins, Clear, re-key, migration); the helper process (dispatch, offline
refusal, source guard, killed helper's workers exit, nothing written after); numba's cache folder;
an unavailable backend; the file kind; the setting; 24 threads loading backends at once in a fresh
process (×3); `helab convert --once` and `--watch` with Ctrl-C.

After Gannet's review: a request without `seen` refused; a first conversion only records, then
converts, and finds converted shots current; one check wants 60 s; a future-dated file waits as
`future` with `clock_skew`; kept shots stay kept with the summary fed back; a beside write stopped
after its record is converted again; the partial pattern matches `write_atomic`'s names and no
look-alike; leftovers: only old regular own ones removed (young, look-alike, link and not-beside
left), and a really killed beside write's leftover (a subprocess `os._exit` before the rename) is
removed on a later pass once old; heartbeats stop after the compute budget (the ticker, the pool's
rule and a slowed backend end to end); the fallback texts (beside without a root, an unreadable
flag). The write audit also patches `io.open` (pathlib), `os.truncate`, `chmod`, `symlink`,
`renames`.

## Review fixes (Gannet, on `c40b4fb`: no blocker)

| Finding | Fix |
|---|---|
| M1: a killed beside write leaves its `.partial` in the source folder | A beside conversion removes its own old leftovers (rules above; Q~7, AGENTS.md housekeeping line proposed) |
| M2: two checks only with `seen` | `seen` required; `--watch` records first; `--once` 60 s; current shots first; `future` + `clock_skew` |
| L1: kept shots flip waiting/kept | `kept` entries `[name, size, mtime]`, sent back and honoured like `done` |
| L2: record after the beside TXY | the record first beside (removed if the TXY exists after all) |
| L3: CacheTab doesn't name `write_beside` | for the UI floor (above) |
| L4: endless compute heartbeats | `compute_budget` caps the ticker and the pool's heartbeats |
| Nits | fallback texts (beside without a root; flag unreadable); `convert_prefs` comment; no "0 workers"; wider write audit |
