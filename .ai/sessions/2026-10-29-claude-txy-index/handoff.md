# Handoff: one index for HeLab's converted TXY (`agent/txy-index`)

Worker: Ledger (Claude Opus 5.5), 2026-10-29. Base `1d3bbb9`; `origin/dev/v0.0.7` (`9f0b21f`) merged in
before the final suite. Brief: [brief.md](brief.md). Coordinator: CoCo.

**Scope note (updated):** the brief's Q26.2 work, plus **Q27.4** (a Don't cache folder converts to the
temp folder) and **Q27.5** (Settings › Cache lists and clears the temp folder's converted TXY too),
both added by CoCo mid-floor after Tony's answers. Files beyond the brief's owned paths, each agreed
with CoCo: `helab/convert/txy.py` (the `before_rename` keyword), `helab/io_ops/admin.py` (both bases),
`helab/io_ops/events.py` (the `converted_txy` shape; docstrings), `helab/utils/folder_cache.py`
(`cache_admin` only: the `temps` parameter), `tests/test_helper_events.py`.

## Summary

- `converted-txy/index.sqlite` in each base (the cache folder's and the temp folder's), in
  `helab/convert/provenance.py` (Qt-free, standard library, already in `PURE`; no new module).
  The per-shot `d_txy_helab_<tag>_<N>.json` and `folder.json` are never written again.
- The row is written **before** the TXY's rename, pinning the size and mtime of the very file being
  renamed (`txy.write_atomic(..., before_rename=)`); a failed write removes the row only if still its own.
- A missing, unreadable, busy-for-a-reader, damaged or newer index only means shots convert again. A
  conversion sets a damaged or newer one aside (`index-damaged-<UTC>-<8 hex>.sqlite`,
  `index-newer-…`) and starts a new one. Housekeeping never deletes those; the user's Clear removes damaged ones, never a newer HeLab's.
- Settings › Cache measures and clears through each base's index, in a helper, asked first.
- Q27.4: the store's Don't cache flag, read by the conversion itself, sends the TXY to the temp
  folder (the app and `helab convert` alike).

## Design

### Schema (`PRAGMA user_version` = 1, `provenance.SCHEMA`)

```sql
CREATE TABLE folders (folder TEXT PRIMARY KEY,   -- converted-txy/<this>/: sha256(identity)[:24]
                      key TEXT NOT NULL,         -- root://… key, "" without a data root
                      source TEXT NOT NULL,      -- the source folder's path as last converted
                      bytes INTEGER NOT NULL,    -- its TXY's bytes (beside ones aren't there)
                      last_used REAL NOT NULL);  -- last conversion, or load taking a TXY (≤ hourly)
CREATE TABLE shots (folder TEXT NOT NULL, shot, raw_name, raw_size, raw_mtime_ns, raw_sha256,
                    profile_name, profile_version, profile_hash, profile_tag, profile_calibrated,
                    backend, output,              -- "beside" | "cache" | "temp"
                    txy_name, txy_size, txy_mtime_ns, txy_sha256, hits, converted_at, helab_version,
                    read_seconds, parse_seconds, reconstruct_seconds, format_seconds, write_seconds,
                    PRIMARY KEY (folder, profile_tag, shot));
```

The `shots` columns are `Provenance`'s fields (generated from the dataclass); a row whose values
aren't of their types reads as no row. `Provenance` lost `source_folder`/`source_key` (they're the
`folders` row's now) and gained `txy_mtime_ns`. One row per (folder, tag, shot), as the JSON file name
was: a beside conversion's row replaces a cache one of the same tag and shot, exactly as before.

### Journal mode, transactions, two writers

**WAL** (as the store's; changed from DELETE in review round 3, CoCo's approval on the CI evidence
below). Writes are rare and tiny (a row per shot, plus the folder's), each one `BEGIN IMMEDIATE`
transaction; `sqlite3.connect(timeout=BUSY_SECONDS)` = 10 s busy timeout (well inside the 60 s
no-progress timeout), and the transaction is tried again where SQLite answers busy at once rather
than risk a deadlock (`provenance._patient`: 10 s in all, each attempt's own busy timeout and the
last sleep being what is left of it, review Nit-7). **Why WAL:** with a rollback
journal, every commit needs every reader gone and deletes the journal file; two processes writing a
row each in turn starved each other on Windows CI (run 40879735789: `SQLITE_BUSY` after 10.65 s,
10.67 s, 10.81 s and 13.41 s in the two-writer test). In WAL, readers never block the writer, a
commit deletes nothing, and writers queue on one lock. The app's helpers and `helab convert` open
the index per operation (a conversion holds one connection for its run, never a transaction between
shots), so they write side by side; `test_two_writers_side_by_side_lose_nothing` runs two writer
processes at once (150 rows each, each opening the index per row like a conversion), then checks every
row and `PRAGMA integrity_check` (its writer prints its error, SQLite code and wait in one line if it
fails). **`-wal` and `-shm` are SQLite's own files:** never housekeeping's (`own_partial()` can't match
them), measured with the index's bytes in Settings › Cache (never as TXY, never in `clearable`), never
removed by Clear; the last connection to close checkpoints the `-wal` into the index and removes both,
so between conversions there is normally only `index.sqlite`. **WAL's shared memory needs a local
disk** (review Low-5): `cache_location.cache_location_problem` already refuses a cache folder on a
network drive, a UNC path or a synced folder, but the temp folder is the user's to set in Settings
(Browse…) and nothing checks it. So a conversion creates a new index in WAL only where
`cache_location_problem(base)` is empty, and with a rollback journal (DELETE) where it objects
(`io_ops.convert.journal_for`; the mode is kept in the file). Every open now uses a fully quoted
`file:` URI (`provenance._uri`: `file:` plus the path with every character but letters, digits and
`_.-~` percent-encoded), so a UNC `\\server\share` is a path, not a URI authority, and `?`, `#`, `%`
in a folder's name stay in it (tests: `test_the_index_uri_quotes_the_whole_path`,
`test_an_index_where_the_folder_may_not_be_local_uses_a_rollback_journal[|on a network drive]`).
Whether Settings should refuse such a temp folder outright is Q~5.

Readers (loads, Live checks, `save_held`, Settings › Cache's measure) open with `mode=rw`, never
create a file, get None for no file, another schema, or any SQLite error, and never set aside. They
are not quite read-only: a load that takes a TXY from a folder moves that folder's `last_used` on, at
most once an hour (`TxyIndex.touch`, one `UPDATE`, its errors ignored; Q~3).

### The rules keep their meaning

- **Current** exactly as before (`provenance.stale`): a row, the raw file's (size, mtime) as recorded,
  the TXY as recorded, the profile hash asked for. **One tightening:** "the TXY as recorded" is now
  its size **and mtime**, not its size alone (provisional, Q~1 below). It is what makes "row before
  rename" safe: a conversion killed between the row and the rename leaves a row naming a file that
  never arrived, and an older TXY of the same tag and size (a stopped redo or profile change) is told
  apart by its mtime (`test_a_write_killed_after_its_row_is_converted_again[False]`).
- **Row before rename, for every output** (beside too). The row pins `os.stat(temporary)` taken after
  the temporary file is written, fsynced and closed; the TXY bytes and the rename are exactly as
  before (the byte-for-byte converter tests are unchanged). A quick check (`folder_state`, the folder's
  mtime) that sees HeLab's folder changed therefore always finds the row already there.
- **Removed on a failed write only if still ours**: `TxyIndex.forget` deletes the row only where its
  `txy_sha256` and `txy_mtime_ns` are this write's (`test_a_failed_write_removes_its_row_only_if_still_its_own`,
  `test_a_lost_beside_race_leaves_the_other_conversions_record`). A kill runs no clean-up: the row
  stays and matches nothing, so the shot converts again.
- **Beside rows stay** when the TXY isn't in HeLab's folder (Clear keeps `output = 'beside'` rows and
  their folder's row); beside currency is still `beside_stale` (the dates), never the row. A beside
  conversion no longer creates HeLab's folder for the source at all (nothing goes in it).
- **The folder moved**: every row written also writes the folder's `key` and `source` (`record()`
  upserts them), replacing `folder.json`'s "rewritten when it moved".

### Mtimes: rename, coarse clocks

- **Rename keeps the mtime on all three OSes**: POSIX `rename(2)` changes no inode times but ctime
  (macOS APFS/HFS+, Linux); Windows `MoveFileEx` (what `os.replace`/`os.rename` call) keeps
  `LastWriteTime`. The hard-link rename (`replace=False`, beside) shares the inode. The new test
  `test_write_atomic_calls_before_rename_with_the_files_stat` checks size and mtime equal after the
  rename; CI's Windows jobs run it and every conversion test that re-checks currency.
- **Coarse mtimes** (FAT 2 s, exFAT 10 ms, NTFS 100 ns, SMB as the server keeps them): the row pins the
  mtime as `stat` reports it on that filesystem, so equality after the rename still holds. What
  weakens is only the tightening's extra protection: an older TXY of the same size written within the
  same tick (2 s on FAT) as the killed one would pass. That needs a redo killed between row and rename
  within 2 s of the previous write, on a FAT cache folder; then the result is the old TXY of the same
  tag (a previous conversion of the same shot), as size-alone would have accepted anyway.

### Damaged, newer, missing (brief item 3)

- **Missing**: shots convert again; a conversion creates a new index.
- **Damaged** (SQLite's `SQLITE_CORRUPT`/`SQLITE_NOTADB`, by `sqlite_errorcode`): a conversion, on
  opening, writing, or reading its rows (`read_shots(repair=True)`), renames it, journal first, to
  `index-damaged-<YYYYMMDDTHHMMSSZ>-<8 hex>.sqlite` (and `…sqlite-journal` / `-wal` / `-shm` if they
  exist), then starts a new one; its shots convert again. **Newer** (`user_version` > 1): set aside the
  same way as `index-newer-…`. Exact pattern (`provenance.SET_ASIDE_PATTERN`):
  `^index-(?:damaged|newer)-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\.sqlite(?:-journal|-wal|-shm)?$` (ASCII).
  **HeLab never removes them by itself**, so no housekeeping line is proposed. The user's Settings ›
  Cache Clear removes `index-damaged-…` ones with the converted TXY (measured in its bytes); it leaves
  `index-newer-…` ones, and a live newer index, alone (below).
- **On Windows, an index another process holds open can't be set aside** (`WinError 32`: a running
  `helab convert` or a load in another helper has it open; HeLab closes its own connection first,
  `read_shots` included). The conversion then fails with `IndexUnavailable` ("… is damaged/newer and
  couldn't be set aside") before any TXY, leaving the index as it was, and the next conversion sets it
  aside once the other handle is closed (helpers hold it only per operation)
  (`test_an_index_that_cant_be_set_aside_fails_the_conversion_to_be_tried_again`). **It never loops
  hot:** Live's auto-convert stops on a failed conversion and waits for Retry (or auto-convert off and
  on; `explorer_live`'s `convert.error`); `helab convert --watch` logs it and tries again after its
  `--interval`; Settings › TXY converter's conversion is one run; IOService retries only loads'
  no-progress timeouts, never a helper's `error`.
- **Busy or unwritable** (another process's transaction past 10 s, the disk, permissions):
  `provenance.IndexUnavailable` (an `OSError`): the conversion fails before that shot's TXY is
  renamed, as a failed TXY write always did, and is tried again
  (`test_an_index_that_cant_be_written_fails_the_conversion_to_be_tried_again`). Loads ignore index
  errors (no rows: MATLAB's TXY or none, as the source mode says).
- Tests: `test_a_missing_or_damaged_index_only_means_shots_convert_again[missing|not a database|malformed|newer]`.

### Old builds' JSON (brief item 4)

Ignored (never read), still measured and cleared by Settings › Cache like the untagged files before
Q18.4; never deleted otherwise. Clear keeps the old rule for them: an old record whose TXY isn't in
the folder (a beside TXY's) stays, and a folder left with `folder.json` alone goes.

### Settings › Cache (brief item 5, Q27.5)

- `helab_txy.converted_roots(cache_directory, temps)` → `{"cache": …, "temp": …}`;
  `converted_usage(root)` per base: TXY files, bytes (the index, its journal, damaged set-aside
  indexes, old builds' records and their leftover temporaries included), folders holding them,
  `last_used` (from the index), and `newer`. Every file is measured by its `stat`, not its row's size:
  a row can name a file a killed redo never renamed in, or one replaced by hand (review Nit-1).
  `converted_summary` gives the totals plus `bases`.
- **A newer HeLab's index is never ours to clear** (review Low-1): when `index.sqlite`'s
  `user_version` is above 1 (`provenance.index_schema`), Clear neither sets it aside nor writes its
  rows (its beside rows are the only account of those TXY); it still removes the TXY files the user
  asked to clear. `index-newer-…` set-aside files stay too. Their bytes are reported apart, as
  `newer`, not in `bytes`, and the row's tooltip adds "a newer HeLab's index, N kB, which Clear leaves"
  (`test_a_clear_leaves_a_newer_helabs_index_alone`).
- Old builds' `.folder.json.<16 hex>.partial` (review Low-2) are measured and cleared like the other
  legacy files (`_OWN_FILE` gains exactly `\.folder\.json\.[0-9a-f]{16}\.partial`), so Clear can
  remove their folder; a look-alike (upper-case hex) stays. Typed in the helper contract: `events.ConvertedUsageField` /
  `ConvertedSummaryField` (checked at the send by strict typing, and both admin paths by
  `test_the_converted_txy_summary_is_the_declared_shape`).
- `clear_converted(root)` per base: removes each folder's TXY and old records, deletes the rows of the
  very files removed (name, size, mtime: a TXY written again meanwhile keeps its row), drops a folder's
  row once no shot of it is left, removes set-aside indexes; keeps beside rows, other files, links, and
  the index itself.
- The GUI never opens an index: `cache_admin` `inventory` and `clear_converted_txy` run in a helper;
  `FolderCache.cache_admin` adds `temps=DIR_TEMPS` to those two actions' params (helpers never read
  `constants`). The Clear still asks first; its text now says "from the cache and temp folders".
- The row: `2 files · 2.0 kB · last used 2h ago`; tooltip: the fixed explanation, then one line per
  base (`Cache folder: 1 file in 1 folder · 1.5 kB`, `Temp folder: … · last used 2h ago`).
  CacheTab edits are confined to that row (constants `CONVERTED_TIP`, `CONVERTED_BASES`,
  `converted_used()` near the top; the row's setup; `clear_converted`'s text; `_update`'s two lines),
  expecting a small merge with the Byte Units floor's `byte_size` edits.
- When the disk cache is off this session, Settings › Cache runs no inventory at all, so the temp
  folder's TXY aren't listed then (Q~4).

### Q27.4: Don't cache converts to temp

`_places` (in the convert helper / `helab convert`) reads the store's `no_cache` flag for the folder
(`CacheStore.read_prefs`, exact folder only) when the output is `cache`; flagged → `temp`, fallback
"you chose Don't cache for this folder". **No FolderCache change**: the store is the authority, as for
its datasets' saves, so the command line honours it too. When the store **can't be opened** the
folder already has no key → temp ("the disk cache couldn't be read (…)"), as before; when it **answers
error** for the flag → temp, fallback "the folder's Don't cache flag couldn't be read (…)"; never the
cache folder, never a failed shot. A folder with **no data root** already went to temp. The TXY go to
`folder_for(temps, root key)`, which `helab_txy.folders()` already looks in, so loads and Live find
them (`test_a_dont_cache_folders_txy_are_found_in_the_temp_folder`). Turning the flag off: the next
conversion writes to the cache folder; the temp folder's TXY stay until Settings › Cache clears them.

### Housekeeping (brief item 6)

`own_partial()` is unchanged from before the floor (review Low-2): the TXY's temporaries and those
old builds gave their JSON (`.d_txy_helab_<tag>_<N>.json.<16 hex>.partial`, `.folder.json.<16
hex>.partial`): new builds write no JSON, but an old build's leftovers are HeLab's own and still go
once an hour old. The index's `-wal`/`-shm` (and an older build's `-journal`) are SQLite's, never
housekeeping's; set-aside indexes are the user's to clear.

### The cache-folder move (brief item 7)

`converted-txy/` is **inside** the cache folder (`base = dirname(cache["directory"]) = cache_dir()`),
so the move carries the index and TXY with it, by either route: a rename keeps everything; the copy
(`cache_move._copy_tree`) uses `shutil.copy2`, which sets the copy's mtime from the source's
`st_mtime_ns` (exact on APFS/ext4/NTFS-to-NTFS), and **copies the index's `-wal` with it** (it skips
only `-shm`, which SQLite rebuilds; it checkpoints only the store's database). That is consistent: no
writer runs during a move (helpers are stopped; `helab convert` registers in `cache_locks`, so none
starts), and normally there is no `-wal` at all (the last close checkpoints it); one a killed helper
left holds committed rows, which SQLite replays at the new place
(`test_a_cache_move_carries_rows_still_in_the_wal`: five rows only in the `-wal`, all read after the
copy). Test of the whole route:
`test_the_index_moves_with_the_cache_folder_and_its_shots_stay_current[rename|copy]` (nothing
converts again at the new place). **One route reconverts**: a copy onto a filesystem with coarser
mtimes (FAT/exFAT target) rounds the TXY's mtimes, so every shot there converts once again (the TXY
are rebuildable; nothing is lost). The temp folder never moves.

## Checks

Recorded in [notes.md](notes.md) with the output (full suite inside the floor's basetemp and once
outside it; the five type checks).

## Proposed doc changes (Coordinator applies)

### `.ai/architecture/converter.md`

(In "Provenance", for the journal mode: "WAL, as the store's (a rollback journal starved two writers
on Windows); the index is on a local disk, the cache folder never being on a share (`cache_location`
refuses one)". Not "works on a share".)

- **"Where files go"**: replace the "Changing before v0.0.7's release (Q26.2 …)" and "Q19.5 (decided,
  not built, Q27.4)" paragraphs with: "`<base>/converted-txy/index.sqlite` (Q26.2) holds the
  provenance: a `folders` table (HeLab's folder by its 24-hex name → key, source path, TXY bytes,
  last used) and a `shots` table (the provenance rows); `helab.convert.provenance`. A Don't cache
  folder converts to the temp folder (Q19.5, Q27.4: the store's flag, read in `_places`; unreadable →
  temp)." In the layout paragraph: `<…>/` "holds `d_txy_helab_<tag>_<N>.txt` (unless beside)"; drop
  the `.json` and `folder.json`; "the provenance row is written **before** the TXY's rename, for every
  output, pinning the size and mtime of the temporary file (`write_atomic(before_rename=)`); a
  conversion stopped between them leaves a row that matches no TXY: the shot converts again".
  Leftovers: "`own_partial()` is `partial()`: TXY temporaries only (old builds' JSON temporaries are
  Settings › Cache's to clear)".
- **"Provenance"**: replace with the schema above (short form), WAL journal mode and why, 10 s busy
  timeout and `_patient`, `BEGIN IMMEDIATE` per shot, readers never create or set aside, `stale(record, raw_size,
  raw_mtime_ns, profile_hash, txy=(size, mtime))`, damaged/newer set aside as
  `index-{damaged,newer}-<UTC>-<8 hex>.sqlite` (pattern above) and kept until the user's Clear,
  `IndexUnavailable` fails the conversion to be tried again. Drop "Why a record per shot and not a
  manifest" (superseded: SQLite transactions give the same isolation).
- **"Tags in HeLab's TXY names"**: "(records `d_txy_helab_<tag>_<N>.json`)" → "(provenance in the
  index; old builds' `.json` records are ignored)".

### `.ai/architecture/cache-store.md` (line 27)

"HeLab's own TXY under the cache **and temp** folders (`converted-txy/`, Q27.5) aren't in the store …
Settings → Cache shows their size per folder and when last used (`inventory.converted_txy`,
`events.ConvertedSummaryField`, through each folder's `index.sqlite`) and clears them when asked
(`cache_admin clear_converted_txy` with the temp folder as `temps`; `removed` kind `converted_txy`;
rows and old records of beside TXY stay; set-aside indexes go)."

### `.ai/architecture/io-and-browsing.md`

- In the long "Responsive filesystem I/O" paragraph, after "Loads and Live checks also read HeLab's
  folders under the cache and temp folders (`io_ops.helab_txy`, plain calls, not source I/O)", add:
  "and the base's `converted-txy/index.sqlite`, never created or set aside by a load, which only moves
  its folder's `last_used` on at most hourly; `convert` and `helab convert` write it. The GUI never
  opens it."
- Patched names (review Low-3): add `provenance.read_shots` (`helab.convert.provenance`, patched by
  `tests/test_txy_sources.py`; `helab_txy.find` and `convert` call it as `provenance.read_shots`).

### `AGENTS.md`

- Housekeeping list, last item: "every conversion with shots to convert deletes, by the same rules,
  its own leftovers in HeLab's `converted-txy/` folder (under the cache or temp folder):
  `io_ops.convert.own_partial()` (the TXY's temporaries, and those old builds gave their JSON records
  and `folder.json`). The index's `-wal`/`-shm` are SQLite's; an index set aside
  (`index-{damaged,newer}-<UTC>-<8 hex>.sqlite`) is never removed by housekeeping (Settings › Cache's
  Clear removes damaged ones, never a newer HeLab's)."
- "The disk cache" invariants could gain one line: "HeLab's converted-TXY provenance is one SQLite
  file per base (`converted-txy/index.sqlite`), opened only by helpers and `helab convert`; its row
  goes in before the TXY's rename; missing or damaged, shots only convert again (Q26.2)."
- Code map, `helab/convert/` row: `provenance` (the converted-TXY index).

## Questions, follow-ups, manual checks (provisional IDs)

- **Q~1** (Tony): accept the tightening "a HeLab TXY is current only while its size **and mtime** are
  the row's" (was size alone)? Proposed: yes (it is what makes the row-before-rename order safe; the
  only cost is a reconversion after a copy onto a coarser-mtime filesystem).
- **Q~2** (Tony): `helab convert --output cache` on a Don't cache folder converts to temp (the flag
  wins; the request can't tell a typed `--output cache` from the setting's default). Q12.4 made a typed
  `beside` override the folder's flag. Proposed: keep "the flag wins" for Don't cache (it is about the
  cache folder's contents, not the source folder), say so in `--help`.
- **Q~3** (Tony): `last_used` moves on with a conversion, and with a load taking a TXY from the folder
  at most once an hour (one small write from the load's helper). Proposed: keep; Settings › Cache
  shows "last used" per base.
- **Q~4** (Tony): with the disk cache off this session, Settings › Cache lists nothing, so the temp
  folder's converted TXY aren't shown or clearable then. Proposed: leave for caching v2 (rare: the
  cache is off only when its folder can't be used).
- **A~1**: `events.ShotKeptEvent`'s docstring still says "no local provenance record"; beside currency
  has been the TXY's date since Q18.4. Reword to "a beside TXY that isn't current (older than its raw
  file) or written by another conversion meanwhile".
- **A~2**: `helab_txy.converted_usage` still lists each hash folder (names only; `stat` only for files
  the index doesn't know). If converted-txy grows to tens of thousands of TXY, measure by the index
  alone and list folders only on Clear.
- **A~3**: done in review round 4 (the quoted `file:` URI above); dropped.
- **Q~5** (Tony): Settings › General lets the temp folder be set anywhere, and nothing checks it
  (only Help › Record I/O trace warns). On a network drive, a UNC path or a synced folder, HeLab's
  converted TXY of folders without a data root or marked Don't cache go there, and the index there now
  uses a rollback journal (slower with two writers, but sound where locks work). Should Settings refuse
  such a temp folder the way it refuses the cache folder? Proposed: yes, with the cache folder's
  wording: "HeLab's temp folder can't be on a network drive or in a synced folder ({problem}): choose
  a folder on this computer's own disk." (an existing such setting kept but warned about once, as for
  the cache folder's).
- **Orphan rows aren't pruned (review Nit-2), on purpose:** a row whose TXY isn't on disk (a kill
  between row and rename, a TXY deleted by hand) is harmless: it reads as stale, the next conversion of
  that shot replaces it (primary key), and Settings › Cache counts files, not rows. Pruning "rows
  without a TXY in HeLab's folder" would have to tell them from beside rows, whose TXY is never there
  and which are the only provenance of those TXY; Clear removes only the rows of the very files it
  removes. No follow-up proposed.
- **Known issue to file (Coordinator):** `tests/test_io_service_run.py::test_writing_held_data_out_counts_as_progress`,
  one RERUN in CI run 40863356565, job "windows Tests (2/2)" (123411955603), then passed: `assert (2 ==
  1)` with `where 2 = len([0.000682100000005903, 0.0014403000000129396])`, `tests\test_io_service_run.py:40`.
  Not this branch's code (IOService untouched): a Windows timing flake, two progress marks where one is
  expected.
- **Known issue to file (Coordinator): an xdist worker crash in `tests/test_root_discovery.py`.**
  CI run 40866574094 attempt 1, job 123422851726 ("macos + py3.13 / Tests (1/2)"), on 9691873:
  `INTERNALERROR> AssertionError: ('tests/test_root_discovery.py::test_volume_check_alone_refreshes_hints_without_visiting_markers', <WorkerController gw2>)`,
  run summary `3108 passed, 322 skipped, 12 warnings` with exit code 3, no RERUN (a crash isn't
  rerun). The test patches `os.lstat` for the whole process
  (`monkeypatch.setattr(os, "lstat", lambda *_: pytest.fail("visited a source folder"))`); while it
  ran, an unraisable (a garbage-collected object's warning) reached pytest's unraisable hook, whose
  `tracemalloc_message` ran coverage's `_should_trace` → `canonical_filename` → `os.path.realpath` →
  the patched `lstat` → `Failed` inside the hook, and the worker died. The collected object is
  unidentified (the hook failed before printing it). Attempt 2 (the failed job rerun) passed.
  Proposed fix: patch the name the code under test calls (e.g. `data_roots`' or `infra`'s, not
  `os.lstat` globally), or `gc.collect()` before patching.
- **Known issue to file (Coordinator): SQLite connections leaked by store tests.** On the base
  `9f0b21f` too, `tests/test_cache_switch.py` leaves three `sqlite3.Connection`s unclosed (Python
  3.13 `ResourceWarning: unclosed database`, seen with `-W always::ResourceWarning` and
  `PYTHONTRACEMALLOC`): two in `test_load_that_cannot_read_the_cache_leaves_its_flag_unknown`, one in
  `test_newer_store_is_read_but_never_written` (the store's error paths, not this branch's code). They
  surface whenever the GC collects them, in whatever test runs then: one way to land in the crash
  above. This floor's test files leak none.
- **M~1** (release smoke pass): on a machine with old-build `d_txy_helab_*.json` / `folder.json` in
  `converted-txy/`, open Settings › Cache: the row counts them, its tooltip lists Cache folder and Temp
  folder lines, Clear removes them; then convert a folder with Live on and see "last used just now".
- **M~2**: mark a folder Don't cache, convert it (Live auto-convert or Settings › TXY converter) and
  check its TXY appear under the temp folder's `converted-txy/` and still load as HeLab's.

## Review round 1 (Tern, `review.md`): what changed

- **High-1** (Windows CI red on `[newer]`): the tests' SQLite connections are closed
  (`contextlib.closing`, with `commit()`), at both places; the Windows behaviour when another process
  holds the index is described above and tested.
- **Low-1**: Clear leaves a newer HeLab's index (live or set aside) and its rows alone; reported as
  `newer` (`events.ConvertedUsageField.newer`) and in the tooltip.
- **Low-2**: `.folder.json.<16 hex>.partial` measured, cleared and housekept by an exact pattern;
  `own_partial()` restored to its pre-floor pattern; AGENTS.md proposal updated.
- **Low-3**: `helab_txy.find` calls `provenance.read_shots` by module; io-and-browsing proposal added.
- **Low-4**: doc proposals corrected (the cache folder is never on a share; loads move `last_used`).
- **Nits**: `read_shots` closes once on each path (first, before a set-aside); sizes by `stat`
  (`TxyIndex.held` dropped, nothing else used it); orphan rows kept on purpose (above).

## Review round 2 (Tern's re-check): Nit-4

Settings › Cache's Clear was enabled whenever the row's bytes were above 0, and those always include
the live index, which Clear keeps: after a Clear the row showed "0 files · N kB" with Clear enabled,
doing nothing. Now `converted_usage` also reports `clearable` / `clearable_bytes`: exactly what
`clear_converted` would remove, by the same rule (`_cleared`, shared by both: never the index, nor an
old record of a beside TXY; `folder.json` when it would be left alone; damaged set-aside indexes).
Clear is enabled only when `clearable` is above 0, its question names the clearable bytes and says
the index stays, and the row's tooltip says Clear keeps the index (counted in the row).
`clear_converted` now also counts the `folder.json` it removes in its bytes, so the two agree. Tests:
`test_the_helper_measures_and_clears_converted_txy` (clearable before, none after a Clear while bytes
remain) and `test_the_cache_tab_shows_and_clears_converted_txy` (after a Clear: "0 files · <index
size>", Clear all enabled, the converted row's Clear disabled; this assertion fails with the old gate).

## CI rerun on c546394: two writers creating the index (fixed)

CI run 40874212130 (c546394) passed every job, with two RERUNs, quoted from "rerun reasons":

- "windows + py3.13 / Tests (2/2)" (job 123448835455):
  `tests/test_convert_helab.py::test_two_writers_side_by_side_lose_nothing`, one rerun, then passed:
  `File "D:\a\HeLab\HeLab\helab\convert\provenance.py", line 352, in open_index` /
  `conn.execute("BEGIN IMMEDIATE")` / `sqlite3.OperationalError: database is locked`. **This branch's
  code:** SQLite answers busy at once, without waiting out its busy timeout, where waiting could
  deadlock, and two processes creating the index at the same moment on Windows hit that. Fixed:
  each index transaction (creating the tables, and every write) is tried again while the answer is
  busy, for up to `BUSY_SECONDS` (10 s) with a 5 ms to 100 ms back-off (`provenance._patient`);
  anything else, or busy past then, is raised as before (`IndexUnavailable`). Test:
  `test_a_transaction_answered_busy_at_once_is_tried_again_until_the_busy_timeout`.
- "windows + py3.13 / Tests (1/2)" (job 123448835517):
  `tests/test_gui_responsiveness.py::test_timeout_retry_releases_dead_helper_slot_while_artifact_reader_is_blocked[2]`,
  one rerun, then passed: `pytestqt.exceptions.TimeoutError: waitUntil timed out in 3000
  milliseconds` at `tests\test_gui_responsiveness.py:292`. Already in `roadmaps/known-issues.md`
  (line 94); not this branch's.

## Review round 3: the two-writer RERUN on Windows, and WAL

- CI 40877063866 (a0e313b) still reran `test_two_writers_side_by_side_lose_nothing` once on Windows
  (Tests 2/2, Converter backends), inside `_patient` from `TxyIndex._write`, error cut off.
- 0e79897 made the writer print its error. CI 40879735789 (0e79897), "rerun reasons", quoted:
  - windows Converter backends (job 123467827392), 1 rerun: `shot 0: IndexUnavailable: HeLab's TXY
    index couldn't be opened (database is locked) (cause OperationalError: database is locked; code
    SQLITE_BUSY) after 13.41 s`.
  - windows Tests (2/2) (job 123467827425), 4 reruns: `shot 14: … couldn't be written (database is
    locked) (… code SQLITE_BUSY) after 10.65 s`, `shot 16: … after 10.81 s`, `shot 2: … after 10.67 s`.
  - macos Tests (1/2) (job 123467827712), 1 rerun:
    `tests/test_root_discovery.py::test_volume_check_alone_refreshes_hints_without_visiting_markers`
    (`monkeypatch.setattr(os, "lstat", lambda *_: pytest.fail("visited a source folder"))`): the
    known-issue proposal above, this time as a rerun rather than a crash.
- Diagnosis: busy starvation past the 10 s timeout under a rollback journal on Windows. Fix (CoCo
  approved WAL on exactly this evidence): `journal_mode = WAL` at the index's creation (kept in the
  file). A load's `last_used` update waits at most 200 ms for a lock (`PRAGMA busy_timeout = 200` in
  `_mark_used`). The busy test now expects the failure at the write ("couldn't be written"): in WAL an
  exclusive writer no longer blocks opening and reading. Local stress: six writers × 300 rows, three
  trials, 1.5 s each, no error, only `index.sqlite` left.

## Review round 4 (Tern's round 3: 2 Low, 3 Nit)

- **Low-5** (the temp folder is the user's, maybe not local): a new index uses DELETE where
  `cache_location_problem(base)` objects, WAL elsewhere (`io_ops.convert.journal_for`, called as
  `cache_location.cache_location_problem`, the name tests patch); every open uses a fully quoted
  `file:` URI, so a UNC temp folder opens. Tests for both modes and the URI. Docstring (`provenance.py`)
  and the journal-mode text above corrected; Q~5 for Tony (refuse such a temp folder in Settings?).
- **Low-6** (the index never shrank): a Clear that removed rows ends with `VACUUM` (`TxyIndex.vacuum`,
  through `_patient`, its errors ignored); "a few kB" dropped from the tooltip, which now says a Clear
  gives back the space of the rows it removes. Test: 400 rows, the file under a quarter of its size
  after the Clear (`test_a_clear_that_removed_rows_gives_their_space_back`).
- **Nit-5** (an index made by an earlier head of this branch stays in DELETE): **accepted**, nothing
  with DELETE shipped (the index never reached Ground or a release); such a dev file still works, as
  DELETE is a supported mode.
- **Nit-6**: with no TXY left, the question reads "Removes what is left of HeLab's converted TXY: old
  records and damaged indexes (N kB), …", never "0 TXY files" (test).
- **Nit-7**: `_patient` now sets each attempt's busy timeout to what is left of `BUSY_SECONDS` and caps
  the last sleep at it, so the whole wait stays within 10 s (docstring true); it restores the
  connection's 10 s timeout after. Test: retries with shrinking timeouts, a held lock answered within
  `BUSY_SECONDS` plus 0.2 s.
- **The 200 ms `last_used` wait, pinned**: `test_a_load_whose_last_used_mark_times_out_still_returns_its_shots`
  holds the index's write lock while a load runs: the load returns HeLab's four shots, `last_used`
  stays, and it takes well under 5 s (it fails at 10.97 s with the 200 ms limit removed).
- **CI 40888404379 (87d0475) failed on two of this round's new tests**, fixed in the next commit:
  `test_the_index_uri_quotes_the_whole_path` on Windows Tests (1/2) (job 123498366820, 5 reruns, then
  failed): `OSError: [WinError 123] The filename, directory name, or volume label syntax is incorrect:
  '…\\a?b#c%d e'`: Windows forbids `?` in a name, so the folder there is `a#c%d e` (`?` is still
  tested off Windows). `test_a_transaction_answered_busy_at_once_is_tried_again_until_the_busy_timeout`
  on macOS Tests (2/2) (job 123498366886, 5 reruns, then failed) and both Converter-backends jobs (macOS
  4 reruns, Windows 10 with the URI test): `assert (180.245601541 - 179.548123916) < (0.3 + 0.2)`:
  CI's runners oversleep SQLite's busy-wait steps and ours; the test now uses `BUSY_SECONDS` = 1 s and
  a 0.6 s margin, still far below the 5 s an unbounded attempt would wait (the connection's sqlite3
  default timeout). `_patient` itself is unchanged.
