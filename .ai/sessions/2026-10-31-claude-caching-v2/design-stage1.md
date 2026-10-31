# Caching v2, stage 1: design addendum

Vault (Claude Opus 5.5), 2026-10-31, on `agent/caching-v2` after stage 0 (`baee813`). Builds on the
[store-v4 design note](../2026-10-29-claude-caching-audit/store-v4-design.md) ("design"), the
[readiness review](../2026-10-29-claude-caching-v2-readiness/readiness.md) ("readiness": D1–D13, gaps
1–11), the plan [`roadmaps/caching-v2.md`](../../../roadmaps/caching-v2.md), and block 28 (Q28.1–Q28.6,
all decided) and Q39.1. **No store-v4 code until CoCo has read this.** Where this differs from the design
note, it says so and why. Proposals for Tony are marked **T~n**; everything else takes the readiness
review's proposed default.

## 0. Summary

- **The switch** (Q28.3): a settings row `store_v4` (bool, default False, no UI), read once per process by
  `store_root()`, so the GUI and `helab convert` pick `store-v3` or `store-v4` and helpers just open the
  directory they are sent. Off: nothing changes and no `store-v4` folder is ever made (a test).
- **With the switch on, store-v4 is a complete live store** in stage 1: every store-v3 table carried over,
  **`datasets` included** (gap 1; the design note dropped it, which would stop dataset caching until stage
  2), plus `raw_layers`, `makers` and v4's `meta` keys. Stage 2 adds `txy_layers` additively and stops
  writing `datasets` (it becomes a read source within v4, as v3's datasets do under Keep). No v4 format
  change is needed between the stages.
- **store-v3 is opened only by `LegacyStore`** (read-only), for the one-time import of the user's state
  and Keep's read-through of records and results.
- **Raw layers** are filled by `raw_fill` in batches within the budget and **never ask** (T~1): a batch
  that doesn't fit isn't saved, and raw filling pauses at 80 %, like automatic loads.
- **Make room's order** (D8): other folders' datasets, then raw layers whose raw file was still there,
  then raw layers that are the only copy (named); plus "Clear old stores…" (Q28.5) as its own asked choice.
- **Codec** (Q22.7): zstd 9 + byte shuffle. *Measured* here: 16 MB/s of raw text per M4 Max thread to
  encode, ~1.7 GB/s to decode; on the lab's Sandy Bridge class, about 4–5 MB/s per thread (estimate).
- **`makers`** (Q28.4): one row per HeLab session (the GUI's run, or one `helab convert` run), its id in
  each `raw_layers`, `datasets` and `results` row and in every `.hlb` header.

## 1. Where the code goes

| Module | What | Qt | Area |
|---|---|---|---|
| `helab/utils/hlb.py` (new) | the `.hlb` container: write (atomic), read, validate | none, `PURE` | cache |
| `helab/convert/raw_layer.py` (new) | `RawPulses` ↔ the raw layer's arrays and `facts`; `not_done` from facts; `RAW_PARSER_VERSION` | none, `PURE` | convert |
| `helab/utils/cache_store.py` | `CacheStore` serves both layouts (3 and 4) from the folder name; v4's schema, `_migrate_v4`, `makers`, raw-layer methods, per-kind epochs, Make room's order | none (as today) | cache |
| `helab/utils/legacy_store.py` (new) | `LegacyStore`: store-v3 read-only (import, Keep's read-through, size) | none | cache |
| `helab/utils/cache_setting.py` | `store_v4_enabled(settings)` | QtCore (as today) | cache |
| `helab/utils/settings_defaults.py` | the `store_v4` row | — | app |
| `helab/utils/cache_move.py` | verify and record every store folder present | — | cache |
| `helab/io_ops/raw_fill.py` (new, step 5) | the `raw_fill` helper operation | none | io/cache |
| `helab/io_ops/events.py`, `admin.py`, `stores.py`, `convert.py` | new kinds; `clear_raw`, `clear_legacy`; raw rows from `convert` | none | as owned |
| `helab/utils/folder_cache.py` (step 5) | scheduling `raw_fill`, Q28.6's notice, cache-1 | Qt | io |
| `helab/views/CacheTab.py`, `CacheDialogs.py` (step 6) | the store-v3 question, Settings › Cache rows, Make room's rows | Qt | app |

`cache_store.py` is 2,673 lines: the v4-only parts (schema, import, raw layers) may go to a
`helab/utils/store_v4.py` mixin if they pass ~600 lines; same owner, same rules.

**Outside the brief's owned paths, to confirm:** `dev/txy/check_samples.py` and `helab/convert/check.py`
(step 3's `--via-layer`, which the brief asks for), `helab/convert/raw_layer.py` (a new convert module),
`tests/conftest.py` is **not** needed (the switch's test fixture lives in the store tests). Step 5 will
need Folder details' view for Q28.6's line (asked then).

## 2. The switch (Q28.3)

- **Row:** `STORE_V4_SETTING = "store_v4"`, `bool`, default `False`, "Developers only until caching v2
  stage 2: keep the disk cache in store-v4". No Settings control (it isn't the user's yet).
- **Read once per process**, at the first `cache_store.store_root(caches_dir)` call, through
  `cache_setting.store_v4_enabled(app_settings())` (imported lazily, so a helper that never calls
  `store_root` never touches settings). Never re-read: a running HeLab never changes store under its
  helpers. Callers today: `folder_cache.store_options` (GUI) and `convert_cli` (headless); `cache_move`
  stops calling `store_root` (§9).
- **Helpers don't know the switch:** they open the `directory` they are sent. `CacheStore` takes its
  layout from the folder's name (`store-v4` → 4, else 3), so a v3 path can never be opened as v4 or the
  reverse.
- **Tests turn it on** with a fixture (in the store tests) that writes `store_v4=true` to the test's own
  ini (conftest's `app_settings()` file) and resets the cached choice (`cache_store._reset_live_layout()`);
  tests of v4 internals construct `CacheStore(<tmp>/store-v4)` directly.
- **Off (the default) changes nothing:** `store-v3` stays the live store, and a test runs loads, saves,
  results, presets, Make room and the sweep with the switch off and asserts no `store-v4` folder exists.
- **Switch on, then off again:** v3 is used again; v4 stays on disk, unused (developers only).

## 3. Store-v4's schema

**Layout 4**, in `cache_dir()/store-v4/`: `records.sqlite`, `datasets/`, `results/`, `raw/`.

- **Carried over unchanged** from v3's `SCHEMA` and `ROOT_SCHEMA`, every table `_migrate` adds today
  included: `meta`, `folder_epochs`, `folder_summaries`, `scan_histories`, `subtrees`, `listings`,
  `folder_prefs`, `folder_constants`, `convert_prefs`, `presets`, `pending_saves` (still `UNIQUE (path)`:
  datasets only, see gap 2), `retired_files`, `datasets` (+ `maker`), `results` (+ `maker`),
  `pending_results`, `roots`, `root_volumes`, `mount_hints`.
- **New:**

```sql
CREATE TABLE makers (
  maker TEXT PRIMARY KEY,          -- the session's id (uuid4 hex)
  started_at REAL NOT NULL,
  record TEXT NOT NULL);           -- JSON, below; additive (unknown fields ignored)
CREATE TABLE raw_layers (
  path TEXT NOT NULL, shot INTEGER NOT NULL,          -- the folder's root:// key; d<N>.txt
  name TEXT NOT NULL,                                 -- the raw file's name (d<N>.txt)
  size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,   -- its fingerprint as read (settled)
  sha256 TEXT NOT NULL,                               -- of the bytes read
  parser INTEGER NOT NULL, encoding TEXT NOT NULL,    -- RAW_PARSER_VERSION; 'i8-i64d-1' | 'f64-1'
  facts TEXT NOT NULL, pulses INTEGER NOT NULL,       -- JSON (raw_layer.Facts)
  file TEXT NOT NULL, bytes INTEGER NOT NULL,         -- raw/<uuid>.hlb
  seen_at REAL NOT NULL,                              -- last look that found the file with this fingerprint
  gone_at REAL,                                       -- a later look found it gone (NULL: present then)
  maker TEXT NOT NULL, job_seq INTEGER NOT NULL, saved_at REAL NOT NULL, last_used REAL NOT NULL,
  PRIMARY KEY (path, shot));
CREATE INDEX raw_layers_last_used ON raw_layers (last_used);
CREATE INDEX raw_layers_file ON raw_layers (file);
```

- **`meta`** keys: `layout_version` 4, `format` 1 (§7), `store_id`, `created_at`, `gen_<kind>` as v3 plus
  `gen_raw`, `gen_results`, `gen_listings`; `budget`/`budget_set_at` (imported); `legacy_v3`
  (`{"choice": null|"keep"|"ignore"|"clear", "v3_store_id", "set_at"}`), `legacy_bytes`
  (`{"bytes", "writes", "measured_at", "v3_store_id"}`), `imported_v3` (`{"v3_store_id", "at"}`).
- **`cache_policy` and `txy_layers`/`txy_segments` wait for stage 2/4** (added then, additively).
- **v4's `_migrate`:** `_migrate(conn)` as today (it already copes with every v3 addition; on a new v4
  there is nothing to add), then `_migrate_v4(conn)` for tables and columns added **within** layout 4
  later, under the same rule (`BEGIN IMMEDIATE`, checked again); empty at first, with its test.
- **Per-kind folder epochs (cache-2):** in v4, a record kind's removal bumps `<kind>:<key>` (e.g.
  `summaries:root://…`) and only that; a dataset removal bumps the folder's own row (what dataset and
  pending saves check, as today); raw rows have `raw:<key>`; results keep `results:<key>`. Guards record
  the epochs of the kinds they cover. So a purge of old records no longer fences a dataset save waiting for
  Make room (cache-2's scenario: a test). Under v3 nothing changes (one epoch per folder).
- **What drops under Q39.1** (one HeLab per computer, A39.3): cache-3 (owner fields on pending saves and
  results) isn't built; "another HeLab writing store-v4 meanwhile" needs no handling beyond SQLite's (the
  same instance's helpers, as today). Kept anyway, being cheap: `LegacyStore` tolerates an older HeLab
  writing v3 (lab machines may still start one by hand), and `clear_legacy` checks the instance locks as a
  cache move does.

## 4. `makers` (Q28.4)

- **A session** is one GUI run or one `helab convert` run. Its id is made once in that process
  (`uuid4().hex`) and travels to helpers with every request in `store_options()["maker"]`
  (`{"maker", "started_at"}`; step 5, since `store_options` is `folder_cache`'s); `convert_cli` passes its
  own. Until step 5 wires it, a helper that writes a v4 row without one uses a per-process id (tests only:
  the switch is off).
- **The row** is written by the first helper that stores anything for that session (`INSERT OR IGNORE`, in
  the same transaction as the data row): `record` = `{"helab_version", "commit", "modified", "frozen",
  "branch"` (from `build_info`), `"machine"` (a random UUID in `app_folder()/machine-id`, made once, mode
  0600; tests have their own through `HELAB_APP_DIR_OVERRIDE`), `"hostname"` (`socket.gethostname()`),
  `"platform"` (`sys.platform`, `platform.machine()`), `"python"`, `"numpy"`, `"scipy"`, `"blosc"`}. The
  helper fills it from its own process, which runs the same install as the GUI.
- **Which rows carry `maker`:** `raw_layers`, `datasets`, `results` (and stage 2's `txy_layers`); every
  `.hlb` header carries the maker's id **and** its record, so a file alone can be traced. Not records
  (summaries, listings…) nor the user's own state, nor HeLab's TXY files (Q28.4: the frozen tag and
  `converted-txy/index.sqlite` say what made them).
- **Housekeeping:** none (no new removal). A makers row is ~400 B per session; rows no data row names stay.
- **Recorded only** in stage 1: never part of a key or a reuse rule (D6, Q27.1 decide that later).

## 5. The `.hlb` container (gap 4)

```
offset 0   magic     8 bytes  b"\x89HLB\r\n\x1a\n"   (PNG-style: catches text-mode and truncation damage)
offset 8   length    <u4      header bytes (≤ 16 MiB, else refused)
offset 12  crc32     <u4      the header's CRC32 (C2-2)
offset 16  header    JSON, UTF-8
then       chunks    each array's Blosc chunks, back to back, tiling the rest of the file exactly
```

- **Header:** `{"format": 1, "kind": "raw", "maker": {"maker", "record"}, "meta": {…}, "arrays": [{"name",
  "dtype"` (explicit byte order: `"|i1"`, `"<i8"`, `"<f8"`; only these), `"shape"`, `"codec": {"name":
  "blosc", "cname": "zstd", "clevel": 9, "shuffle": "byte", "typesize"}`, `"chunks": [{"offset", "length",
  "size", "crc32"}]}]}`. Offsets from the end of the header; `size` is the chunk's uncompressed bytes;
  `crc32` (zlib) of its compressed bytes (Blosc 1 has no checksum).
- **Chunks:** at most 64 MiB uncompressed each, cut at element boundaries (python-blosc 1.11.4's 2 GB
  limit never applies). Deltas are taken over the whole array **before** cutting, so a chunk boundary never
  splits a delta's meaning; decoding concatenates the chunks, then sums.
- **Validation on read:** magic, header length, `format` ≤ this HeLab's (newer: refused as "written by a
  newer HeLab", never rewritten), each array's dtype in the allowed set, `prod(shape) × itemsize` equal to
  the chunks' sizes, every chunk's CRC and decompressed size, no overlapping or out-of-file chunk. Any
  failure is an error answer (never "missing", AGENTS.md's read rule), and the file is left as it is.
- **Format rule:** unknown header fields are ignored (additive); a new codec or dtype is additive (old
  readers refuse that file as unknown, which is an error, never a rewrite); a change of layout bumps
  `format`.
- **Atomic write:** `raw/tmp-<uuid>` (exclusive create), write, `fsync`, rename to `raw/<uuid>.hlb`,
  `fsync` the folder; no row names it until the save's transaction (an orphan if killed: the sweep's
  existing rule, `_known_files` extended to `raw/`).

## 6. The raw layer and its codec

- **Order** (design §1, kept): row 0 first, then the other rows in stable time order. Every backend and
  `split` use only `times[0]` and a stable argsort (`numpy_backend.py:123-126`, `split.py:56-60`), so the
  decoded `RawPulses` gives byte-identical TXY. Proved by the tests (§12), not assumed.
- **`i8-i64d-1`** when the file took the strict fast path (`fastio.parse_strict` answered), every channel
  is an integer in 0–127 and every |time| < 2^53: arrays `channel` `|i1` [n] and `time` `<i8` [n] (row 0's
  time, then deltas along the stored order); zstd 9, byte shuffle (typesize 1 and 8).
- **`f64-1`** otherwise (the general reader, NaN, signs, decimals, |t| ≥ 2^53, channel > 127): `channels`
  and `times` `<f8` exactly as `parse_raw` gives them, **in file order** (no reordering of NaN rows),
  zstd 9, byte shuffle (typesize 8).
- **`facts`** (JSON): `rows`, `t_zero` (repr; `"nan"` allowed), `first_channel` (what `not_done`'s
  `_FIRST_FIELD` reads after leading `\r\n`, or null), `blank` (`not data.strip()`), `final_newline`,
  `line_endings` (`crlf`/`lf`/`cr`/`mixed`/`none`), `reader` (`strict`/`general`). `raw_layer.not_done(facts,
  trigger)` equals `raw.not_done(bytes, trigger)` for every trigger channel (a test over every case and the
  fuzz set).
- **`RAW_PARSER_VERSION = 1`**, bumped only when `parse_raw`'s output changes for some input. A row of
  an older parser is re-read when its file is reachable; while it isn't, it is used and labelled (Q22.6).
- **Encode cost** (Q22.7's zstd 9; *measured* on 60 sample files, 105 MB of raw text, 6.8 M pulses, M4 Max):

  | | size | encode (raw text) 1 thread / 4 | decode 1 thread / 4 |
  |---|---|---|---|
  | zstd 5 + shuffle | 2.06 B/pulse (0.133×) | 250 / 659 MB/s | 0.7 / 3.1 GB/s |
  | zstd 9 + shuffle | 1.91 B/pulse (0.124×) | **16 / 32 MB/s** | 1.7 / 3.0 GB/s |

  zstd 9 is 15× slower to encode for 7 % less. On a Sandy Bridge lab PC (about 3–4× slower per thread than
  an M4, estimate), about 4–5 MB/s per thread: a 0.7 MB shot takes ~0.15–0.2 s, a 1,000-shot folder
  (700 MB) ~2.5–3 min of one background helper's CPU. Live (a shot per 30 s) doesn't notice. Kept per
  Q22.7; the level is recorded per file, so changing it later needs no migration. **M~1:** time
  `check_samples.py --via-layer` on the lab PC. **T~2** only if that is too slow: zstd 5 (+7 %).

## 7. Format versions (Q27.2's rule; convert-3)

One rule for store-v4 and `.hlb`: **an additive change keeps the version** (a table, a column with a
default, a header field, a `meta` key, a new encoding name); only a breaking change bumps it. An older
HeLab meeting a newer version **reads what it understands or refuses, and never rewrites, sets aside or
removes the file**:

- store-v4 `meta.format` 1: a store whose `format` is above this HeLab's opens read-only (as a newer
  layout does today, `CacheStore._open`); `layout_version` 4 stays the folder's identity (a layout 5 would
  be `store-v5`, and Make room's "Clear old stores…" would offer v4 then).
- `.hlb` `format` 1: a newer file is an error answer (its folder reloads from the share), never replaced
  in place: the store's own save replaces a row's file only through a new file and retirement.
- `converted-txy/index.sqlite` stays `user_version` 1 (stage 0 added its `fence` table within it).
- What convert-3 showed goes wrong otherwise: 0.0.7a1 sets aside a newer index on every conversion, so two
  versions ping-pong. Store-v4 avoids the same by never setting a newer store aside.

## 8. store-v3: `LegacyStore`, the import and Keep (gap 5)

- **`LegacyStore(path)`** is the only code that opens `store-v3` once store-v4 is live. It opens
  `records.sqlite` with `mode=ro`; where that fails for want of a `-shm` (a WAL database closed cleanly),
  with a normal connection under `PRAGMA query_only = 1`. Both set `SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE`
  (Python 3.12+), so closing never checkpoints the WAL into `records.sqlite`. It never `makedirs`, never
  runs `_migrate`, has no write method, and reads missing tables as empty. *Checked* (SQLite 3.53.1, the venv's):
  `mode=ro` opens a WAL database closed cleanly (no `-shm`) and leaves `records.sqlite` byte-identical, creating
  `-wal`/`-shm` beside it; with `NO_CKPT_ON_CLOSE`, a reader closing last leaves it byte-identical too. SQLite may create `-wal`/`-shm`
  beside it: allowed (the brief's integration check hashes `records.sqlite` and the data files only).
- **A test fails on any other open of v3:** with the switch on, `CacheStore.__init__` (patched to record
  its root) and every `sqlite3.connect` (patched) are watched through a session of loads, results, Make
  room, a Clear of v4, the sweep, a cache move and the import; only `LegacyStore` may name `store-v3`.
- **The import (Q22.4)**, once, at v4's creation and whatever the choice: `folder_prefs`, `convert_prefs`,
  `folder_constants`, `presets` (deleted rows included), `roots`, `root_volumes`, `mount_hints`, and
  `budget`/`budget_set_at`. In v4's creating transaction, each row `INSERT OR IGNORE` (v4 is empty then),
  then `meta.imported_v3`. A v3 that can't be read: v4 is created without it and `imported_v3` isn't set,
  so the next open tries once more (the import is skipped when `imported_v3` names v3's current
  `store_id`). A v3 recreated later (other `store_id`) isn't imported again: what v4 holds is newer.
- **The choice** (step 6) is in `meta.legacy_v3`; until it is made, Keep (Q22.3). Ignore: v3 is never
  opened (a test with the open watched). Clear…: `clear_legacy` (asked, with its size; instance locks
  checked) removes the `store-v3` folder and sends `removed` kind `legacy`.
- **Keep's read-through (step 4):** `read_records`, `find_result`/`read_results` and the result counts read
  v4 first and, for a key v4 has no row for, v3; answers carry v4's `store_id` and `legacy: true` (so
  `FolderCache.store_answer` never sees a second store). A v3 result shown is copied into v4 by the next
  save of that folder's results (not on read: reads write nothing). v3's datasets aren't read in stage 1
  (stage 2's `matlab` seed); a folder loads from the share once and saves into v4.
- **Budget under Keep (gap 8, D9):** v3's live bytes (datasets + results + records, as v3's `_live`) count
  in v4's usage for every fit check and the 80 % line. Measured by `LegacyStore` at every inventory (startup
  and Settings › Cache) and stored in `meta.legacy_bytes` with v3's `writes` counter; a fit check uses the
  stored value (never opens v3 inside a save). Under Ignore or after Clear, 0.

## 9. Cache moves with two stores (gap 6)

- `cache_move` handles **every store folder present** (`store-v3`, `store-v4`), not the live one:
  `store_ids_at(cache_dir) -> {dirname: store_id}`, `verify(cache_dir, ids)` checks each present store's
  integrity, id and named files (v4 adds `raw_layers`' files; datasets and results as today), and the move
  record gains `store_ids` beside `store_id` (additive: an older record still recovers).
- **`checkpoint` touches only v4** (it writes; v3 is read-only from this HeLab once v4 is live). With v4
  live, v3 is copied or renamed as a passenger: verified by integrity, id and its named files' sizes,
  through `LegacyStore`, never checkpointed. With the switch off, v3 is the only store: as today.
- A test moves a cache with both stores (rename and copy, and a crash recovered) and checks both verify,
  v3's files byte-identical.

## 10. `raw_fill` and raw rows (gaps 2, 3, 7; step 5)

- **When** (Q19.10, Q22.1): after `loaded` of a folder that is disk cached (a data root, not Don't cache,
  the store on, not offline), FolderCache schedules one `raw_fill` on the background lane (pausable, refused
  offline); Live's saves and auto-convert schedule one too. Never for listings or scans.
- **Batches (gap 3):** a job takes its guard once (`gen_raw`, `raw:<key>` and root epochs, a new `job_seq`),
  lists the folder once (raw files' stats), skips shots whose row has the same fingerprint and parser
  (resuming a killed job costs one listing), and saves in batches of at most 50 shots or 64 MB of raw text,
  each one transaction and one fit check. Settled rules as today: unmodified for `settle_seconds`, not in
  the future, the same `fstat` before and after the read.
- **Yield:** a job handles at most ~30 s of work, then ends with `raw_fill_more`; FolderCache submits the
  next at the back of the background queue, so scans and Live's saves never wait behind a large folder.
- **Pending (gap 2), T~1:** a raw batch that doesn't fit isn't saved and never becomes a pending save: the
  job stops for that folder with `raw_not_saved` (`over_budget`), and raw filling pauses while usage is at
  80 % (as automatic loads do; deliberate loads still save their datasets). Raw layers are a speed-up
  of files still on the share, and a question per folder filled in the background would be noise.
  `pending_saves` therefore stays datasets-only, `UNIQUE (path)`. Alternative: pending raw units with
  Make room asked (the design note's text).
- **Ordering:** a row with the same fingerprint and parser is kept (`seen_at`, `last_used` touched); a
  different fingerprint replaces it only from a job with `job_seq` ≥ the row's (its listing is later); the
  replaced file is retired. A file gone at a later listing gets `gone_at` (its row and file stay: Q22.6).
- **Overwritten raw file (Q22.5, Q28.6):** a different fingerprint for a stored shot sends `raw_overwritten`
  (`path`, `shot`, `raw_name`, old and new size, mtime and SHA-256). FolderCache shows it once per shot per
  session: `events.notify(..., key=("raw_overwritten", path, shot), desktop=True)`, an amber Folder details
  line ("Raw file d12.txt was overwritten since HeLab cached it: read again; the TDC may be misconfigured")
  and a log warning. Live goes on.
- **Raw rows from `convert`:** a conversion already reads and parses each file; when the folder is disk
  cached, it saves the raw rows of the shots it converted, in the same batches and rules (one guard per
  conversion, never asks).
- **Clear (gap 7, step 5/6):** `cache_admin clear_raw` (all, or per folder/root), fenced by `gen_raw` and
  the `raw:` epochs; `removed` kind `raw`; Settings › Cache's "Raw pulses" row (size, count, Clear…).
  Clear all and a root's Clear cached data… include raw rows (they are cached data).
- **RAM:** a decoded raw layer lives in a helper only while it converts: not GUI RAM, outside the RAM
  budget (gap 8).

## 11. Make room (D8, D9, Q28.5; step 5)

For a dataset save that doesn't fit (asked, exactly the plan shown, rolled back as today):

1. other folders' **datasets**, least recently used first (re-readable from the share; stage 2's HeLab
   layers come first of all, being rebuildable locally);
2. **raw layers** whose files were present at the last look (`gone_at IS NULL`), a whole folder at a
   time, least recently used folder first;
3. **raw layers that are the only copy** (`gone_at` set), last, each folder named so in the dialog.

Never the folder being saved, nor a newer save waiting. **"Clear old stores…"** (Q28.5) is offered beside
it whenever an older store is found in the cache folder (store-v3 now; any `store-v<N>` below this layout
later), each with its size, as its own asked choice (it removes the whole older store, so it is never part
of an automatic plan). The 80 % pause message names store-v3 while it is counted.

## 12. Tests (by step)

- **Step 3:** `.hlb` round trip; corruption of each part (magic, length, header, dtype, CRC, size,
  truncation) is an error; chunking at 64 MiB with a small test limit; deltas across a chunk boundary.
  Layer equals file: every `tests/data/convert/cases/` and `textscan/` case and a seeded fuzz set (ties at
  equal times, row 0 not earliest, row 0 tied, |t| = 2^53 ± 1, 17-digit fields, NaN rows, CR-only and mixed
  endings, channel > 127, empty, blank-only): encode → decode → `reconstruct` byte-identical to the file
  path for every available backend and `split`; encoding chosen as expected; `not_done` from facts equals
  `not_done(bytes)`. `--via-layer` in memory (a test that it writes nothing).
- **Step 4:** switch off → no `store-v4` folder after a session; switch on → v4 live with every carried-over
  table; `_migrate_v4`; the import once (and retried after a failed read); Keep's read-through (records,
  exact and family results) with `legacy` answers under v4's `store_id`; Ignore never opens v3; the guard
  test on v3 opens; per-kind epochs (cache-2's scenario); `makers` rows and ids; a newer `format` opens
  read-only; cache move with both stores.
- **Steps 5–7:** as the brief: raw_fill batches, yield, resume, guards against each Clear, `job_seq`
  ordering, `gone_at`, Make room's order, never-ask over budget, the 80 % pause, the overwrite notice once
  per shot, convert's raw rows, `removed` kinds, `test_helper_events.py` for every new kind, cache-1, and the
  switch-on integration check in temp stores.

## 13. For Tony (via CoCo)

- **T~1** A raw batch that doesn't fit the budget is **not saved and never asks** (raw filling also pauses
  at 80 %); only dataset saves ask Make room. Alternative: raw units wait as pending saves and ask like
  datasets. Proposed: never ask.
- **T~2** (only if M~1 finds it too slow) zstd 5 instead of 9 for the raw layer: +7 % size, 15× faster to
  encode. Proposed: keep 9.
- **T~3** With the switch on, store-v4 carries v3's `datasets` table through stage 1, so a v4 store is fully
  usable for testing; stage 2 stops writing it. Proposed: yes (the design note dropped it, which leaves no
  dataset caching until stage 2).

## 14. Follow-ups

- **A~2** `pack_dataset`'s 2.1 GB limit stays for v4's `datasets` in stage 1 (blosc-pickle); stage 2's
  segments in `.hlb` end it.
- **M~1** time the raw codec on the lab PC (`check_samples.py --via-layer`).
