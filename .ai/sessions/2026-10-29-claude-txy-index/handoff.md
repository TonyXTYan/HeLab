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

**DELETE** (a rollback journal, SQLite's default). Writes are rare and tiny (a row per shot, plus the
folder's), each one `BEGIN IMMEDIATE` transaction; `sqlite3.connect(timeout=BUSY_SECONDS)` = 10 s
busy timeout (well inside the 60 s no-progress timeout). The app's helpers and `helab convert` open
the index per operation (a conversion holds one connection for its run, never a transaction between
shots), so they write side by side; `test_two_writers_side_by_side_lose_nothing` runs two writer
processes at once (150 rows each, each opening the index per row like a conversion), then checks every
row and `PRAGMA integrity_check`. Why not WAL: nothing to gain at this write rate, and it leaves
`-wal`/`-shm` files beside the index (the cache move's copy skips `-shm` and checkpoints only the
store's database). **The index is on a local disk:** `cache_location.cache_location_problem` already
refuses a cache folder on a network drive or a UNC path, and the temp folder is the OS's. (A UNC
*temp* override, a developer setting, would make every index open fail, since SQLite refuses a
`file://server/share/…` URI: loads would find no rows and conversions fail with `IndexUnavailable`;
A~3.)

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
once an hour old. SQLite's own `index.sqlite-journal` is SQLite's, never housekeeping's; set-aside
indexes are the user's to clear.

### The cache-folder move (brief item 7)

`converted-txy/` is **inside** the cache folder (`base = dirname(cache["directory"]) = cache_dir()`),
so the move carries the index and TXY with it, by either route: a rename keeps everything; the copy
(`cache_move._copy_tree`) uses `shutil.copy2`, which sets the copy's mtime from the source's
`st_mtime_ns` (exact on APFS/ext4/NTFS-to-NTFS), skips only `-shm` files (none here), and copies a hot
`-journal` too if a crash left one (consistent: no writer runs during a move; `helab convert`
registers in `cache_locks`, so none starts). Test:
`test_the_index_moves_with_the_cache_folder_and_its_shots_stay_current[rename|copy]` (nothing
converts again at the new place). **One route reconverts**: a copy onto a filesystem with coarser
mtimes (FAT/exFAT target) rounds the TXY's mtimes, so every shot there converts once again (the TXY
are rebuildable; nothing is lost). The temp folder never moves.

## Checks

Recorded in [notes.md](notes.md) with the output (full suite inside the floor's basetemp and once
outside it; the five type checks).

## Proposed doc changes (Coordinator applies)

### `.ai/architecture/converter.md`

(In "Provenance", for the journal mode: "DELETE; the index is on a local disk, the cache folder never
being on a share (`cache_location` refuses one)". Not "works on a share".)

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
- **"Provenance"**: replace with the schema above (short form), DELETE journal mode and why, 10 s busy
  timeout, `BEGIN IMMEDIATE` per shot, readers never create or set aside, `stale(record, raw_size,
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
  and `folder.json`). The index's `-journal` is SQLite's; an index set aside
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
- **A~3**: `provenance._connect` builds a `file://server/share/…` URI from a UNC path, which SQLite
  refuses. Only a developer's UNC temp-folder override reaches it (the cache folder is refused on a
  share). If one ever matters, open UNC paths without a URI (`mode=rw` then needs an existence check).
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
