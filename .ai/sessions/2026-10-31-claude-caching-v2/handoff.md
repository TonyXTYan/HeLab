# Handoff: caching v2 (`agent/caching-v2`), Vault

Worker: Vault (Claude Opus 5.5). Brief: [brief.md](brief.md). Updated at each checkpoint.

## Stage 0 (checkpoint 1): A19.2, cache-5, cache-4, cache-6

Commits on `agent/caching-v2` (base `92fc597`, `dev/v0.0.8` at `d9d647f` merged):

| Commit | What |
|---|---|
| `b4ab6f6` | cache-5: a save whose guard names a re-keyed folder is `SaveRejected("cleared", REKEYED)`, its file retired at once |
| `46f481f` | cache-4: tests close the `sqlite3` connections they open (29 blocks in 11 files) |
| `cd6edca` | cache-6: `admin.py`'s comment on `prefs` and volume hints |
| `ce8eae7` | A19.2: the Clear fence between Clear converted TXY and a running conversion |

Checks at `ce8eae7` (macOS, M4 Max): `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`:
**8522 passed, 672 skipped, 2 warnings in 251.95s; no RERUN** (the warnings: pyqtgraph's NumPy 2.5
`arr.shape` DeprecationWarning in `test_t_spectrum.py`, known); `mypy helab/ --strict`, `mypy tests --strict`,
`mypy helab/ --strict --platform win32`: no issues; `pyright helab tests` and `--pythonplatform Windows`:
0 errors. Log: `.ai/temp/stage0/suite.log`.

Files outside the brief's owned paths, approved by CoCo (2026-10-31): `helab/convert/provenance.py` (the
fence) and `helab/convert/txy.py` (`write_atomic`'s optional `after_rename`). Both stay Qt-free and in `PURE`.

### A19.2: how the fence works

- `converted-txy/index.sqlite` gains a `fence` table (one row: a random token, `cleared_at`), added
  **within schema 1**: `CREATE TABLE IF NOT EXISTS` by the first Clear (and in `_TABLES` for a new index);
  `user_version` stays 1, so 0.0.7a1 reads and writes the index unchanged (convert-3's constraint).
- `clear_converted` first sets a new token (`TxyIndex.set_fence`, one `BEGIN IMMEDIATE`), then lists the
  folders and removes, as before.
- A conversion into the cache or temp base reads the token when it starts (`provenance.fence_of`, right
  after `_places`, before the listing). For each TXY: the row is written only while the token is unchanged
  (`record(fence=…)`, checked inside the row's transaction), then `hold(fence)` takes `BEGIN IMMEDIATE` and
  checks again, `write_atomic` renames, and `after_rename=index.release` lets go at once (a `finally` lets
  go too if anything failed before the rename). The row is still committed before the rename.
- So a Clear's `set_fence` lands either before the hold (the write is refused: `provenance.Cleared`, the
  temporary removed by `write_atomic`, the row forgotten) or after the rename (it waits on the lock, then
  lists and finds the TXY and removes it with its row). Each refused shot, and every later shot of that
  conversion (unread: `read` checks `index.fence()` first), is `shot_waiting` with reason `cleared`
  (`convert.CLEARED`); the next check converts them. A `FileNotFoundError` from the write while the fence
  has moved (a Clear removed the in-flight temporary, which `_OWN_FILE` matches) counts the same.
- Beside writes aren't fenced (`fence` is None): Clear never removes them.

CoCo's three points and the `after_rename` question:

1. **An older HeLab's Clear is unfenced.** 0.0.7a1's `clear_converted` never sets the token, so its Clear
   against this build's running conversion behaves as before (may leave TXY). Likewise 0.0.7a1's
   conversions never check it, so this build's Clear vs an old conversion is unfenced too.
2. **The held lock spans the rename alone.** `hold` is the last thing in `before_rename`; `after_rename`
   runs right after `os.replace`/`_rename_new` and before `_fsync_folder`. **Busy past `BUSY_SECONDS`**
   (10 s): `hold` raises `IndexUnavailable` with nothing held; `write_atomic` removes the temporary; the
   row is forgotten (or, if that is busy too, left matching no TXY on disk, so the shot is converted
   again); the exception fails the conversion as any index write it can't make does today. A manual run or
   `--once` is then simply run again; **in Live, a failed conversion stops auto-convert until the user
   presses Retry** (`explorer_live.py`'s `convert.error`), as any conversion error does today. The TXY
   already there is untouched (no rename happened): never a lost TXY. Test:
   `test_a_busy_lock_for_the_rename_fails_the_conversion_and_loses_no_txy`.
3. **Clear between pin and rename, both orders**: `test_a_clear_between_the_row_and_the_rename`
   (`before the lock`: refused, no TXY, no row, shot 2 waits unread; `while the rename holds it`: the
   Clear is shown blocked with the token unchanged, then removes the TXY and its row after the rename).
   Also `test_a_clear_after_a_conversion_started_refuses_its_rows_and_its_shots_wait` (fence moved before
   the row) and `test_the_fence_table_is_added_within_schema_1`.
4. **`after_rename` raising after the rename**: the TXY is in place and its row committed; `write_atomic`'s
   handler only removes the temporary name (already gone) and re-raises, skipping the folder fsync. In
   the converter the callback is `TxyIndex.release`, which suppresses `sqlite3.Error`, so it doesn't raise
   in practice; if it did, the `finally` calls `release` again (idempotent: `_held` is cleared first, and
   SQLite drops the lock with the connection at `index.close()` anyway). The converter's `except` would then
   forget the row of a TXY that exists, so that shot converts again next time (no loss). Test:
   `test_write_atomic_calls_after_rename_between_the_rename_and_the_folders_fsync` (default path unchanged;
   order rename → callback → fsync; raising leaves the file).

Gaps left (documented in `clear_converted`'s docstring):
- A base with **no index yet** isn't fenced: Clear makes no index (it would show as kept bytes in Settings ›
  Cache). Only the base's first conversion since the index (Q26.2), between its start and its first
  `open_index(write=True)` (the listing), can still write after such a Clear.
- A **damaged or busy** index isn't fenced (Clear can't write it); a **newer** HeLab's isn't ours.
- ~~Clear removes in-flight temporaries~~ **Fixed (S0-1, A~1, commit after `64280e0`):** Clear used to remove
  every `_OWN_FILE` partial of any age, so a conversion that started *after* the Clear's token, while the
  Clear was still removing, could lose its temporary: the rename raised `FileNotFoundError`, the conversion
  ended in an error, and in Live that stopped auto-convert until Retry (Assay's S0-1). Clear now leaves
  temporaries under `convert.PARTIAL_MAX_AGE` (1 h), as housekeeping does, and Settings › Cache's clearable
  count skips them too (`helab_txy._young_partial`). A conversion that started *before* the Clear never
  renames anyway (the fence). Tests: `test_a_clear_still_running_leaves_a_later_conversions_temporary_alone`
  (fails without the fix with that `FileNotFoundError`) and `test_the_helper_measures_and_clears_converted_txy`
  (a young temporary kept, an old one removed).

### cache-5

`_guard_holds` and `_check_result_guard` raise `SaveRejected("cleared", cache_store.REKEYED)` ("The
folder's data root changed before saving completed") instead of `ValueError`. Every save path already
handles `SaveRejected`: `save_dataset`/`add_pending` retire the file (`_reject_file`), `save_result`
retires it (`_reject_result_file`), `result_save` sends `result_not_saved` (reason `cleared`), listings and
summaries swallow it as before, and `confirm_dataset`'s caller (which caught only `StoreError`/
`SaveRejected`) no longer lets a raw `ValueError` escape. `adopt_pending_result`'s `except ValueError` is gone.

### cache-4

All 29 `with sqlite3.connect(…) as c:` blocks in tests are `with contextlib.closing(sqlite3.connect(…)) as
c, c:` (commit on exit kept, connection closed). The other direct connections in tests already close in
`finally`. Checked with a `gc.collect()` after every test and `-W always::ResourceWarning` on the 11 files:
no `unclosed database`; the same on the old `test_cache_switch.py` shows the leak
(`.ai/temp/cache-4/gc_plugin.py`, not committed).

## Steps 2–4 (checkpoint 2): the addendum, `.hlb` and the raw layer, store-v4's core (switch off)

| Commit | What |
|---|---|
| `9767d15` | step 2: [design-stage1.md](design-stage1.md), read by CoCo; T~1–T~3 sent to Tony |
| `b3945f1` | step 3: `helab/utils/hlb.py`, `helab/convert/raw_layer.py`, `check.convert_via_layer`, `check_samples.py --via-layer` |
| `9cbaa0a` | CI: the Converter backends job runs `tests/test_raw_layer.py` (CoCo's OK) |
| `cbf6e16` | step 4: the switch, store-v4 in `CacheStore` (`helab/utils/store_v4.py`), `LegacyStore`, the import, Keep, cache-2, makers, cache moves |
| `627d1ab` | step 4: the inventory measures store-v3 (`meta.legacy_bytes`, gap 8) |

Outside the brief's owned paths, approved by CoCo: `helab/convert/raw_layer.py` (new), `helab/convert/check.py`,
`dev/txy/check_samples.py`, `.github/workflows/ci-test.yml` (one line). New modules in `PURE`: `helab.utils.hlb`,
`helab.convert.raw_layer`.

### Step 3

- **`.hlb`** as the addendum §5: magic `\x89HLB\r\n\x1a\n`, `<u4` header length (≤ 16 MiB), JSON header (`format` 1,
  `kind`, `maker`, `meta`, `arrays` with explicit dtypes `|i1 |u1 <i8 <f8`, codec, chunks with offset, length,
  size, CRC32), Blosc chunks ≤ 64 MiB at element boundaries. Unknown header fields ignored; a newer `format`, an
  unknown dtype or codec, any damage: `HlbError`, never data. Bytes only (the store writes files, step 5).
- **Raw layer** as §6: compact `i8-i64d-1` when the strict path read the file, channels ≤ 127 and times < 2^62
  (looser than the design's 2^53 and still exact: every strict value is an integer float64, so its int64 and the
  deltas are exact); row 0 first, then stable time order. `f64-1` otherwise, in file order. `Facts` give
  `not_done` the same answer as the bytes. zstd 9 + byte shuffle.
- **Proof:** `tests/test_raw_layer.py` (every case, every textscan probe (1,381 inputs in 8 folders),
  `tests_sample_data/`, a seeded fuzz set of 57): byte-identical TXY from the layer with every available backend
  and the split path. **Here only `reference` and `numpy` are built: the cython backend is proved by CI's
  Converter backends job only** (rust, numba, mlx only wherever they are installed; the test skips a backend that
  can't run). Storing all
  rows in plain sorted order (row 0 not first) fails 54 of the tests.
- **Sample set** (`check_samples.py --positions all --via-layer --backend numpy`, read only, in memory; nothing in
  `~/HeLab-samples` changed, checked with `find -newer`): **303 identical, 1 cut, 2 variant, 3 empty (the 6
  proved exceptions), 0 differ**, the same table as the file path. 9.4 s for 309 shots.

### Step 4

- **The switch:** `store_v4` row (bool, off, no control); `cache_store.store_root()` reads it once per process
  (`live_layout`, lazily through `cache_setting.store_v4_enabled(app_settings())`); `store_root_for(dir, layout)`
  and `layout_of(root)` (the folder's name decides: `store-v4` is layout 4). Helpers never read it. Off: v3 as
  today, and `test_with_the_switch_off_store_v3_is_live_and_no_store_v4_is_ever_made`.
- **store-v4** = every v3 table (datasets included, T~3) + `makers` + `raw_layers` (empty until step 5) + `maker`
  columns on `datasets` and `results`; `meta.format` 1 (newer: read only), `gen_raw`, `imported_v3`,
  `legacy_bytes`; `store_v4.migrate` for tables added within layout 4 (none yet; called on every writable open).
  Not yet in v4: `legacy_v3` is written by step 6's question (unset = not answered = Keep).
- **cache-2:** in v4 a record kind's removal bumps `<kind>:<key>` (`store_v4.epoch_key`), datasets keep the
  folder's own row; v3 unchanged. A nested root's re-key moves only the folder rows (as today); a per-kind row
  left under the old key is harmless (a guard naming the old key is `REKEYED` anyway).
- **makers (Q28.4):** the session's maker is `HELAB_STORE_MAKER` in the environment, made at the GUI's (or
  `helab convert`'s) first `store_root()` under v4 and inherited by its helpers (`IOService` starts them with a copy
  of `os.environ`), so `store_options()` needs no change; a store without one (tests) makes its own. The row is
  written in the same transaction as the first data row. **Privacy (CoCo's note, block 29): the record holds the
  machine's hostname, and every `.hlb` header will carry the maker's record: fine on this machine, but a `.hlb` or a
  saved result shared off it carries the hostname.** The machine id is a random UUID in `app_folder()/machine-id`.
- **store-v3:** `LegacyStore` (`mode=ro`, else `mode=rw` + `query_only`; `NO_CKPT_ON_CLOSE`); the import once at
  v4's creation (retried while v3 can't be read; a v3 appearing later isn't imported); Keep's read-through of
  records and results (v4 exact, v3 exact, v4 outdated, v3 outdated; `ResultFound.legacy`; counts include v3's);
  Ignore/Clear never open v3. **Not built: copy-on-use** of v3 results into v4 (the addendum said "by the next save
  of that folder's results"); read-through only, while v3 is kept (A~3).
- **Cache moves:** the primary store (newest layout present) keeps `store_id`'s role; the record adds
  `store_ids`; `verify` checks each store; `checkpoint` writes the primary only; a v3 beside a v4 is read through
  `LegacyStore`. Older records (no `store_ids`) recover as before.
- **The guard test** (`test_only_legacy_store_ever_opens_store_v3_once_store_v4_is_live`): with v4 live, a session
  of opens, saves, results, records, purges, removals, the sweep, inventories and a copy move opens v3's database
  only from `legacy_store.py` (every `sqlite3.connect` and `CacheStore` open watched) and v3's files (all but
  `-wal`/`-shm`) are byte-identical, in place and in the copy. It fails if `cache_move` opens v3 itself.

Checks at `627d1ab` (macOS, M4 Max): `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`:
**8699 passed, 672 skipped, 2 warnings in 136.77s; no RERUN** (the known pyqtgraph warnings); `mypy helab/
--strict` (199 files), `mypy tests --strict` (178), `--platform win32`: no issues; `pyright helab tests` and
`--pythonplatform Windows`: 0 errors. Logs: `.ai/temp/step4/`.

### Checkpoint 2 review fixes (Assay, `review-checkpoint2.md`)

All six fixed, each with a test that fails before it; fix range `bdbd2bc..` this push.

| Finding | Commit | Fix |
|---|---|---|
| C2-2 Low | `471a980` | `.hlb`: the header's CRC32 after its length (header at offset 16); chunks must tile the body in order, no gap, overlap or trailing bytes. Format 1 still unwritten, so no bump |
| C2-3 Low | `6d53159` | `machine_id`: an invalid or empty file is replaced atomically, once; a missing one made with `os.link` so two first starts agree; never recursion |
| C2-1 Medium | `9d5889c` | Keep reads store-v3 for a key only while v4 never removed that kind for it (its generation, the key's epoch, its root's; a `None` save's tombstone `legacy-hidden:<kind>:<key>`, read by no guard; purges by age recorded in `meta.legacy_purged`) |
| C2-4 Nit | `9d5889c` | the result count adds only v3 lookups v4 lacks, none for a removed key; the step-4 test's 4 corrected to 3 |
| C2-5 Nit | `47a6723` | a root forgotten in v4 before a retried import stays forgotten (`meta.forgotten_before_import`); only roots are ever deleted of the imported state |
| C2-6 Nit | `0551343`, `630bf8e` | `cache_move.start(..., layout=)` makes the live store the primary (record `primary`); `CacheMover` sends `cache_store.live_layout()` as every move request's `layout` (CoCo's OK to edit it); without one (an old record), the newest as before |
| C2-7 Nit (re-check) | `f28f9ff` | purges by age keep two cutoffs per kind (the latest, and the latest that took scan histories with failures) |
| C2-8 Nit (re-check) | `4270080` | a retried import brings v3's flags set before v4's `prefs_cleared_at` in off, dated at the Clear |

Checks at `0551343`: **8723 passed, 672 skipped, 2 warnings in 154.35s; no RERUN**; mypy (also win32) and pyright
(also Windows) clean. Log: `.ai/temp/step4/suite-fixes.log`.

After the re-check (`ff1fe1a`): C2-7, C2-8 and C2-6's app half, each with a test that fails first. Checkpoint 2 now
lands with step 5's store side (`d207b61`, inert: store-v4 only, switch off) under them. Checks at `630bf8e`:
**8743 passed, 672 skipped, 2 warnings in 138.67s; no RERUN**; mypy (also win32) and pyright (also Windows) clean.
Log: `.ai/temp/step4/suite-c2b.log`. For Assay: the fix diff `ff1fe1a..630bf8e` and `d207b61`.

### Step 5, store side (`d207b61`, inert)

Raw layers in store-v4 (no `folder_cache.py`, no `raw_fill` helper yet: they wait for I/O Fixes):
`write_raw_file`, `start_raw_job` (`gen_raw`, `raw:<key>`, root epoch, the folder's `job_seq`), `save_raw_batch`
(one transaction and fit check per batch; same file kept, a later job's version replaces, changes in place named in
`overwritten` for Q28.6; over budget: nothing saved, never pending, as T~1 proposes), `mark_raw_seen` (`gone_at`),
`raw_rows`, `read_raw`, `remove_raw`; raw bytes and v3's counted bytes in `_live`; `inventory()["raw"]` and
`["older_stores"]` (Q28.5's list); Make room's order (datasets, raw seen, only copies; plan `raw_paths`,
`only_copy_paths`, `items`); a root's Clear takes its raw layers; the sweep's existing orphan rule over `raw/`;
the admin's `clear_raw` and `removed` kind `raw`. 16 tests in `tests/test_raw_layers_store.py`.

Assay's pass 3 (`99f7fd1`) on it, both fixed with a test that fails first:
- **C2-10 Low** (`0c08c5c`): the only-copy mark goes by when its evidence was taken: a sighting (a listing's
  time; a batch's `RawEntry.read_at`) clears `gone_at` only if newer than it, and a listing marks a shot gone only
  if newer than its last sighting.
- **C2-9 Low** (`6603b4b`): Don't cache with remove cached data also takes the folder's raw layers whose files
  were seen, and keeps only copies. **For Tony to confirm** (CoCo's decision per Q22.6: an only copy is never
  removed without being named; step 6's dialog may name and offer them).

Assay's notes for later steps:
- **Step 6:** Settings › Cache's Clear all passes `kinds=list(KINDS)` (`CacheTab.py:538`), so it doesn't take raw
  layers although it says "Removes everything in the disk cache"; with the raw row, Clear all includes `raw`. Make
  room's dialog names `only_copy_paths`.
- **Step 5's `raw_fill`:** publish each `.hlb` just before its batch's save (an unsaved file is an orphan the sweep
  deletes after an hour; a paused job could pass that).
- **Step 5's `raw_fill` passes `RawEntry.read_at`** (when it read each file), or C2-10/C2-11's ordering falls back to
  the save's time (Assay, pass 4).

Assay's pass 4 (`3c239a9`), both fixed with a test that fails first:
- **C2-11 Nit** (`0579fa1`): a replacing raw batch carries `gone_at` when a listing at or after its `read_at` found
  the shot gone.
- **C2-12 Nit** (`3f98958`, test-only): the via-layer test refuses file opens on its own thread only.

Not changed: `trim` (a lowered budget) still removes datasets only (A~4: give it Make room's order).

Checks at `3f98958`: **8746 passed, 672 skipped, 2 warnings in 134.48s; no RERUN**; mypy (also win32) and pyright
(also Windows) clean. Log: `.ai/temp/step4/suite-c2d.log`.

### Tony's answers (2026-10-31, via CoCo) and what's next

- **T~1 yes**: a raw batch over the budget is never saved and never asks. **T~2**: keep zstd 9. **T~3 yes**: store-v4
  carries `datasets` through stage 1. **C2-9 confirmed**: Don't cache with remove cached data keeps only copies.
- Checkpoint 2 lands at `a7b7257` (Assay pass 5: no open findings), after I/O Fixes (`471966b`) and Plot Identity.
- **New item (Tony), after step 5 and before step 7: export cache options and the file format with sample code.**
  Drafts: [hlb-format.md](hlb-format.md) (the format page, its "without HeLab" reader checked against a file
  HeLab wrote) and [design-export.md](design-export.md) (`hlb.read`, `raw_layer.columns`, `helab cache dump` and
  `export` to npz/mat/csv, read-only; one dispatch line in `helab/main.py`, to ask CoCo).
- Next: CoCo's word to merge `dev/v0.0.8`, then step 5's `folder_cache.py` part.

## Step 5 (after checkpoint 2 landed; `dev/v0.0.8` merged at `f5fe405`)

| Commit | What |
|---|---|
| `34ec22c` | cache-1: a data root's change of identity drops its folder flags and `write_beside` in RAM (`_root_prefs_gone`, beside `_root_constants_gone`'s three callers) |
| `fc25864` | `raw_fill` (helper operation), raw rows from conversions, Q28.6's notice, the Folder details line |

Files outside the owned paths, each approved by CoCo: `helab/io_helper.py` (dispatch, `SOURCE_OPERATIONS`,
`CACHE_ONLY`), `helab/utils/io_service.py` (`PAUSABLE`, `CACHE_OPERATIONS`, `LABELS`, `NOUNS`), `helab/utils/events.py`
(`RAW_OVERWRITTEN`), `helab/views/FolderDetailsPanel.py` (the amber Problems line; **Rivet's A39.4 edits that area
on Ground: merge `dev/v0.0.8` after Rivet pushes, before the next checkpoint push**).

- **raw_fill** runs on the background lane: pausable, refused offline, held during a cache move, and labelled
  "Cache raw pulses". It holds its slot until its exit is confirmed (`IOService`'s rule, unchanged). Its timeout is
  `NO_PROGRESS_TIMEOUT`, fed by heartbeats while it lists, reads and encodes. At most one per folder is queued or
  running (owner `raw_fill:<path>`, `IOService`'s dedup); a folder asked again, or one that yielded (`more`), is
  queued again when its run ends, at the back of the lane. It is never retried after an error until the next save
  asks.
- It is **triggered** by a valid `cache_saved`: Load, auto-load, presets' and reopened plots' loads, and Live's
  saves. Conversions save their own raw rows instead (`convert._RawRows`: cache or beside output, a data root,
  store-v4, online). Never for listings or scans, a Don't cache folder, without a data root, or in store-v3.
- **Q28.6:** a desktop notification once per shot per session, a log warning naming the folder, and Folder details'
  Problems line in amber ("N raw file(s) overwritten since cached", the files in its tooltip).
- Not built: the Folder details line comes from `FolderCache.raw_overwrites`, which lasts the session only (as
  Tony asked: once per shot per session).

Proposed docs (CoCo's request): **`io-and-browsing.md`**, lanes: "`raw_fill` (caching v2, store-v4 only) runs on a
background lane, pausable and refused offline, one per folder (`FolderCache.schedule_raw_fill` after a valid
`cache_saved`); it yields after about 30 s of work and is queued again at the back, so scans and Live's saves never
wait behind a large folder." **`cache-store.md`**: `raw_fill`, its batches and `read_at`, conversions' raw rows,
Q28.6's notice. **`converter.md`**: a conversion in store-v4 saves its shots' raw layers.

## Proposed doc changes (for the Coordinator)

- **known-issues** (cache-4): replace the `test_cache_switch.py` leak entry with: "Fixed on
  `agent/caching-v2` (`46f481f`): the leaks were the tests' own `with sqlite3.connect(...)` blocks (29 in
  11 files; sqlite3's context manager commits but never closes), not the store's error paths; tests now use
  `contextlib.closing`." In the entry above it (`test_root_discovery.py::test_volume_check_alone_…`), the
  sentence "The collected object may be one of `test_cache_switch.py`'s leaked connections (next)" becomes
  "…may have been one of the tests' leaked connections (fixed, `46f481f`); the patch-the-name fix still stands."
- **cache-store.md**, "Tables added within store-v3" (cache-6): "…and its re-key of a nested root leaves the
  subtree's constants (0.0.5) and converter flags (0.0.6) behind, and a 0.0.6 HeLab's Clear folder
  preferences leaves `write_beside` on."
- **cache-store.md** and the converter's Clear (S0-1): Clear converted TXY "removes … their leftover temporaries
  once over an hour old" (a younger one may be a conversion's write in progress).
- **cache-store.md**, "Converted TXY in the cache folder" (A19.2): add "Clear fences conversions already
  running (A19.2): it first sets a new token in the index's `fence` table, and a conversion that started
  before writes no TXY after it (its shots wait as `cleared` and convert at the next check); a base with
  no index yet, a damaged or busy index and 0.0.7a1's Clear or conversions aren't fenced."
- **converter.md**: the same in the converter's index section, plus "`txy.write_atomic` takes
  `after_rename` (run after the rename, before the folder fsync)" and the `shot_waiting` reason `cleared`.
- **AI_TODO**: A19.2 done.
- **AGENTS.md** (for Tony to confirm, wording only):
  - Disk cache: "Only helpers (and `helab convert`) open the store (`DIR_CACHES/store-v3`, `CacheStore`; with the
    `store_v4` switch on, `store-v4`, and store-v3 then only through `LegacyStore`, read only)".
  - `_migrate`: "A table or column added within `store-v3` or `store-v4` is added to older stores by
    `cache_store._migrate` (store-v4: `store_v4.migrate`) on every writable open, never only in `SCHEMA`."
  - Housekeeping (CoCo's note b): "the sweep deletes retired dataset and layer files, and store files no row names
    once over an hour old": the same orphan rule over `raw/` too (step 5), **no new removal**.
  - Settings: the `store_v4` row stays off until stage 2 and Tony's go (Q28.3).
- **cache-store.md:** a "store-v4 (caching v2, behind the switch)" section: the switch and `layout_of`; v4's
  tables and meta; per-kind epochs; makers and `HELAB_STORE_MAKER`; `LegacyStore`, the import and Keep;
  `inventory()["legacy"]`; cache moves with two stores (primary, `store_ids`).
- **converter.md:** `raw_layer` (encodings, facts, `RAW_PARSER_VERSION`), `check.convert_via_layer` and
  `check_samples.py --via-layer`.
- **testing.md:** the `switch_on` fixture in `tests/test_store_v4.py` (the `store_v4` row in the test's ini plus
  `cache_store._reset_live_layout()`); `tests/test_raw_layer.py` in the Converter backends job.
- **The plan** (`roadmaps/caching-v2.md`): stage 1's store-v4 carries `datasets` (T~3, pending Tony); the raw
  layer's compact limit is 2^62; the sample set's via-layer result.

## Follow-ups (provisional)

- ~~A~1~~ done in stage 0 (S0-1, above).
- **known-issues** (the fixes' CI 41164715526): add to the `test_io_service_run.py::test_writing_held_data_out_counts_as_progress`
  entry "Again: `agent/caching-v2` CI 41164715526 (Windows Tests 2/2, job 124429733436, marks 1.4 ms and 5.2 ms)".
  Its only RERUN; IOService untouched by this floor.
- **A~2** `pack_dataset`'s 2.1 GB limit stays for v4's `datasets` in stage 1 (blosc-pickle); stage 2's `.hlb`
  segments end it.
- **A~4** `trim` (the user lowers the budget) in Make room's order in store-v4 (today datasets only).
- **A~3** copy-on-use of store-v3's saved results into v4 (or decide read-through is enough while v3 is kept).
- **M~1** time the raw codec on the lab PC (`check_samples.py --via-layer`; zstd 9 measured 16 MB/s of raw text
  per M4 Max thread).
- **Step 5 owes:** `raw/` in `_known_files`/`_listed_files` (the sweep's orphan rule), v3's `legacy_bytes` in v4's
  usage and fit checks, the maker id in each `.hlb` header written, Make room's order.
- **known-issues** (S0-2, Assay; `explorer_live.py`, I/O Fixes' file, not fixed here): "Live's line counts
  shots waiting with reason `cleared` (A19.2: Clear converted TXY ran during that conversion) as stuck until
  the next check, and their tooltip ends 'A waiting file is checked again only when it changes', which is
  wrong for `cleared`: the next check converts them. Transient (one check interval). Fix: leave `cleared` out
  of `stuck()` (Assay's correction; not in `CONVERT_SETTLING`)."
