# Store v4: design note for caching v2

2026-10-29, Side's subagent (claude), read-only on `dev/v0.0.7` at `aa84e77`. **Planning only:
Tony has not approved any cache code** (block 19). It builds on the [audit](audit.md) and the plan
[`roadmaps/caching-v2.md`](../../../roadmaps/caching-v2.md); decided so far: Q19.4 (a fresh
store-v4 plus a one-time store-v3 choice), Q19.9 (cache raw pulses), Q19.10 (where the raw layer is
filled), Q18.4 (tags). Claims about today's code cite `file:line` on `dev/v0.0.7`; the Q18.2 and
Q18.4 code is on `agent/txy-followups` (`26a2ade`, `dda90fd`), not yet landed, and is cited as such.
Numbers marked *measured* come from read-only scripts on `~/HeLab-samples/txy-v1` (309 shots, 217.5
MB raw), kept in the session scratchpad. Proposals carry provisional IDs (`Q~n`).

> **Amended 2026-10-29 (Side, after docs audit 3 and the readiness review):** `Q~1`–`Q~10` are
> Q22.1–Q22.10, all decided ([DECISIONS_TODO](../../DECISIONS_TODO.md), Recently decided); the
> raw codec is **zstd 9** with byte shuffle (Q22.7; 27.5 MB, below), not level 5; the Q18.2 and
> Q18.4 code landed in `c718c71`. Later answers change parts of this note: Q19.3 (every source a
> plot uses gets a layer), Q19.7 and Q19.1 (temp and cache outputs stay as options), Q12.3 (its
> own budget for converted text TXY), Q26.2 (`converted-txy/index.sqlite`), Q27.2 (versioning:
> the plan's [Versioning](../../../roadmaps/caching-v2.md#versioning)), and block 28's open
> questions ([readiness](../2026-10-29-claude-caching-v2-readiness/readiness.md)). Where they
> differ, the plan and DECISIONS_TODO win.

## Summary

- `store-v4/` beside `store-v3/` in `cache_dir()`: the same SQLite record tables, minus `datasets`,
  plus `raw_layers` (one row per raw file), `txy_layers` (one row per folder and layer),
  `txy_segments` (the layer's data files) and `cache_policy` (the user's per-folder policy).
  Blobs are pickle-free files of Blosc chunks.
- **Raw layer:** the parsed pulses, row 0 first, then the rest in the converter's stable time
  order: int8 channels, int64 time deltas, zstd-5 with shuffle. That is 29.5 MB for the sample
  (0.136× raw), decoded at ~2.9 GB/s. A file the fast parser can't hold exactly in int64 (NaN,
  signs, decimals, |t| ≥ 2^53) keeps the parser's float64 arrays instead. The text facts the
  checks need (t_zero, the first line's channel, rows, final newline, line endings, diagnostics,
  SHA-256) are stored with it.
- **TXY layers:** `matlab` (MATLAB's `d_txy_forc`) and `helab:<profile hash>` (any tag with that
  hash), stored as float64 like today's datasets (zstd-9, no shuffle). A HeLab shot's identity is
  its raw file's (size, mtime) plus the profile hash, so a re-conversion is the same data and
  saved results keep matching.
- **Size correction to the plan.** *Measured:* at today's dataset settings a TXY layer is 15.5 MB
  (m19v1, 8 significant figures) or 17.0 MB (full float64), so the raw layer is about **1.9× a TXY
  layer**, not "about the same" (the plan compared against TXY at zstd-5 with shuffle). Raw plus
  one tag is about 2.8× what today's store keeps per folder.
- **store-v3** is opened only with a read-only SQLite connection (never `_migrate`, never
  `makedirs`). Under "Keep", what v4 lacks is read from v3 and copied into v4 when used. The user's
  own state (flags, constants, presets, root decisions) is imported into v4 once, whatever the
  choice. The choice is stored in v4's `meta`, so it moves with the cache folder.
- **Rules:** no new removal rule. Only the wording of AGENTS.md's sweep line widens ("retired
  dataset files" becomes "retired dataset and layer files"), and the `_migrate` rule names
  store-v4. Make room stays asked; it offers TXY layers first, then raw layers, and the raw layers
  whose raw file is gone last of all, saying so.

## 1. Schema

### store-v3 tables in store-v4

Today's tables: `cache_store.py:78-155`; `_migrate`: `cache_store.py:2602-2652`.

| v3 table | v4 | Notes |
|---|---|---|
| `meta` | changes | `layout_version` 4, a new `store_id`; `gen_raw` and `gen_txy` replace `gen_datasets`; new keys `legacy_v3` (the choice, below) and `legacy_bytes`. `budget`/`budget_set_at` are imported from v3 |
| `folder_epochs` | unchanged | folder and `root-clear://` epochs (`cache_store.py:157-160`), and `job_seq` per folder, which now orders every layer save of the folder |
| `folder_summaries`, `scan_histories`, `subtrees`, `listings` | unchanged | read through v3 under "Keep" (§4). Raw counts in summaries come with stage 5 (Q14.4) |
| `folder_prefs`, `folder_constants`, `convert_prefs`, `presets` | unchanged | imported from v3 once (§4) |
| `roots`, `root_volumes`, `mount_hints` | unchanged | imported from v3 once, so Same folder / It's a copy answers aren't asked again |
| `pending_saves` | changes | one row per **save unit** (every layer one job writes for a folder): `pending_id`, `path`, `parts` (JSON: `[{kind: raw\|txy, layer, shot?, file, bytes, record}]`), guard columns as today, `created_at`; `UNIQUE (path)` kept |
| `retired_files` | unchanged | any blob (raw, segment, result) |
| `datasets` | **goes** | replaced by `txy_layers` + `txy_segments` |
| `results`, `pending_results` | unchanged columns | what the lookup key contains changes (§2) |

### New tables

```sql
CREATE TABLE raw_layers (
  path TEXT NOT NULL,            -- the folder's root:// key, as datasets.path today
  shot INTEGER NOT NULL,         -- from d<N>.txt
  size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,  -- the raw file's fingerprint as read (settled)
  sha256 TEXT NOT NULL,          -- of the bytes read (provenance, and checks against beside TXY records)
  parser INTEGER NOT NULL,       -- RAW_PARSER_VERSION when parsed
  encoding TEXT NOT NULL,        -- 'i8-i64d-1' (compact) or 'f64-1' (exact fallback)
  facts TEXT NOT NULL,           -- JSON, below
  pulses INTEGER NOT NULL, file TEXT NOT NULL, bytes INTEGER NOT NULL,
  source_seen_at REAL NOT NULL,  -- last listing that saw this raw file with this fingerprint
  job_seq INTEGER NOT NULL, saved_at REAL NOT NULL, last_used REAL NOT NULL,
  PRIMARY KEY (path, shot));
CREATE INDEX raw_layers_last_used ON raw_layers (last_used);

CREATE TABLE txy_layers (
  path TEXT NOT NULL,
  layer TEXT NOT NULL,           -- 'matlab' | 'helab:<profile content hash>'
  tags TEXT NOT NULL,            -- JSON: tags seen for this hash (m19v1, p22v1, u<hash>…), display only
  shots INTEGER NOT NULL, rows INTEGER NOT NULL, ram_bytes INTEGER NOT NULL, bytes INTEGER NOT NULL,
  fingerprint TEXT NOT NULL,     -- JSON [[shot, size, mtime_ns]]: TXY file's (matlab) or raw file's (helab)
  problematic TEXT NOT NULL,     -- JSON [shot]
  info TEXT NOT NULL,            -- JSON: listed_at, folder_mtime_ns, names, hits per shot, precision,
                                 --   converter (HeLab version, backend) per shot for helab, unsettled
  raw_times TEXT NOT NULL DEFAULT '[]',
  job_seq INTEGER NOT NULL, last_used REAL NOT NULL,
  PRIMARY KEY (path, layer));
CREATE INDEX txy_layers_last_used ON txy_layers (last_used);

CREATE TABLE txy_segments (
  path TEXT NOT NULL, layer TEXT NOT NULL, seq INTEGER NOT NULL,
  file TEXT NOT NULL, bytes INTEGER NOT NULL, shots TEXT NOT NULL,  -- JSON [shot] held in this file
  PRIMARY KEY (path, layer, seq));

CREATE TABLE cache_policy (      -- the user's choice, like convert_prefs (never removed by Clear all,
  path TEXT PRIMARY KEY,         --   purges or Make room; Clear folder preferences turns it off)
  policy TEXT NOT NULL CHECK (policy IN ('raw', 'raw+tag', 'txy')),
  tag TEXT NOT NULL DEFAULT '', set_at REAL NOT NULL);
```

**Segments.** Today every Live autosave rewrites the folder's whole dataset file
(`save_held` → `_write_dataset`, `io_ops/save_held.py:22`, `io_ops/loading.py:741`). In v4 a save
appends one segment holding only the shots that are new or changed, and the row lists the current
segments. Compaction (rewrite into one segment, retiring the old ones) runs once a layer has more
than 8 segments or more than half its bytes superseded. A shot appearing in several segments: the
highest `seq` wins.

**Saved results:** no layer index is needed. The lookup key already holds each shot's fingerprint
and origin (`analysis/result_cache.py:57-62`, `analysis/results.py:54-76`), and §2 makes those
stable. (Q~9 asks whether "clear tag X's data and its results" is wanted; that would need a
`result_layers(result_id, layer)` index.)

### On disk

```
<cache_dir()>/store-v4/records.sqlite (+ -wal, -shm)
                       raw/<uuid>.hlb        one per raw file
                       txy/<uuid>.hlb        one per segment
                       results/<uuid>.npz    as today
<cache_dir()>/store-v3/…                     left as it is (§4)
```

**Blob container (`.hlb`), pickle-free.** Today's dataset files are Blosc pickles
(`cache_store.py:34, 459-478`). An `.hlb` file is: the magic `HLB1`, a uint32 header length, a JSON
header (`{"format", "arrays": [{"name", "dtype", "shape", "codec", "chunks": [[offset, length], …]}],
"meta": {…}}`), then Blosc chunks of at most 64 MB each. Today `pack_dataset` compresses a whole
folder in one Blosc call, and python-blosc 1.11.4's `MAX_BUFFERSIZE` is 2,147,483,631 bytes, so a
cached dataset over ~2.1 GB can't be saved today: a latent bug to file in known-issues. Unpacking
validates dtypes and shapes as `unpack_dataset` does (`cache_store.py:468-477`).

### Raw layer array format

- **Order.** Stored rows are row 0 of the file first (the trigger row MATLAB takes `t_zero` from),
  then every other row in the converter's stable time order. `np.argsort(times, kind="stable")` of
  that array gives the same rows in the same order as on the file's own rows. Row 0 sorts first
  among equal times either way, since it has the smallest file index, and the others keep their
  relative order. Backends use only `times[0]` and a stable sort (`backends/numpy_backend.py:123-
  125`, `backends/reference.py:94-101`), so the decoded `RawPulses` (`convert/raw.py:65`) feeds every
  backend unchanged. This is the stage 1 proof (§7). *Measured:* sorted order compresses to 29.5
  MB, file order to 34.8 MB (the files have 2.9 M descents in 13.7 M rows).
- **Compact encoding `i8-i64d-1`**, used when the file took the strict fast path (`raw.py:54-55`),
  every channel is in 0–127, and every |time| < 2^53. Then the int64 → float64 conversion is exact
  and equals what `parse_raw` gives; *measured:* the largest time is 5.2e13. Arrays: `channel`
  int8 [n]; `time` int64 [n] as row 0's time, then deltas along the stored order (row 1's delta is
  taken from row 0). Blosc zstd level 5 with byte shuffle (typesize 1 / 8; **level 9 chosen**, Q22.7: 27.5 MB). *Measured:* 29.5 MB,
  encode ~430 MB/s and decode (with the cumulative sum) ~2.9 GB/s of raw-text equivalent. zstd-9
  saves only 7 % at 16× the encode time.
- **Fallback `f64-1`**: `channels` and `times` float64 exactly as `parse_raw` returns them (NaN, Inf,
  fields over 16 digits; `raw.py:18-31`, `converter.md` (`raw`)), in the same order, zstd-5 with shuffle. It is rare (the
  general reader).
- **`facts` (JSON):** `t_zero` (float64 as text, NaN allowed), `first_channel` (the first line's
  integer channel per `raw._FIRST_FIELD`, `raw.py:159`, or null), `rows`, `final_newline`,
  `line_endings` (`crlf`/`lf`/`cr`/`mixed`), `reader` (`strict`/`general`), `diagnostics` (where the
  general reader stopped and why, NaN-filled fields), `no_rows`. `raw.not_done(data,
  channel_trigger)` (`raw.py:170`) is then answered from the facts for any profile's trigger channel.

### TXY layer format

A segment holds arrays `shots` int64 [k], `offsets` int64 [k+1] and `hits` float64 [N, 3] (T s,
X m, Y m), plus `problematic` in the header. Codec: zstd-9 without shuffle, as today (*measured*:
0.32× the TXY text; with shuffle 0.58). Precision follows the layer's profile: m19v1 and MATLAB's
hold the values the 8-significant-figure text parses to; newer tags hold full float64 (Q19.6).
*Measured* on the sample: full float64 is 17.0 MB against 15.5 MB rounded (+10 %), and pandas'
default parser equals round-trip parsing on all 4.3 M MATLAB values.

### Versions and what each invalidates

| Version | Where | A change invalidates |
|---|---|---|
| Store layout (4) | `meta.layout_version`, the folder name | nothing: v5 would be a new folder. A newer layout opens read-only, as today (`cache_store.py:574-576`) |
| Tables added within v4 | `_migrate` | nothing (added on writable open, as today) |
| `RAW_PARSER_VERSION` | `raw_layers.parser` | raw layers of older parsers are re-read from the raw file when it is reachable; while it isn't, the old layer is used and labelled (Q~6). Bumped only when `parse_raw`'s output changes for some input |
| Raw `encoding` | per row | nothing: decoders for every encoding stay |
| Profile content hash | the `helab:<hash>` layer | it is the identity: another hash is another layer |
| Tag | `txy_layers.tags`, file names | nothing (frozen, Q18.4; `file_tag`, `convert/profile.py:316-323` on `agent/txy-followups`); a tag whose definition changed would get a new hash, so a new layer |
| Converter code (HeLab version, backend) | `info` per shot | nothing: every backend is byte-identical by contract. A converter bug that changes an existing tag's output is a release blocker, not a cache rule |

## 2. Keys and identity

- **Raw layer key:** (`path` = root key, `shot`). Identity is (size, mtime_ns) read as settled plus
  `parser`. "Settled" follows the same rules as today: not modified within `SETTLE_SECONDS`, not
  dated in the future, the same fstat before and after the read. The converter's two-sighting
  `seen` rule (`converter.md`, settle rules) stays for conversions; a layer is keyed by exactly the
  bytes read, so a file that changes later is a new fingerprint, never a wrong one.
- **TXY layer key:** (`path`, `layer`). A shot's fingerprint is MATLAB's TXY file (size, mtime) for
  `matlab`, as today (`loading.py:376-381`), and **the raw file's** (size, mtime) for `helab:<hash>`.
  It no longer depends on a TXY file's mtime, so re-converting, clearing `converted-txy/`, or
  converting from the raw layer instead of the share all give the same key (audit K2).
- **Why key HeLab layers by hash, not tag:** origins are `helab:<profile hash>` today
  (`txy_sources.py` on `agent/txy-followups`, module docstring), and the plate profiles have
  `matlab-2019`'s hash until calibrated, so `m19v1` and `p22v1` data are identical. Keying by tag
  would store and identify the same data twice. Tags stay in file names and in `tags` for display
  (Q~2).
- **MATLAB TXY are the `matlab` layer**: data read from `d_txy_forc` files, never derived (MATLAB's
  output differs from `m19v1` on proved reference faults, `converter.md` "The sample set"). They
  keep the mismatch rule, the folder signature and status counts until stage 5 (Q14.4).
- **A source mode is a per-shot choice across layers** (`txy_sources.choose`/`helab_txy.compose`,
  `io_ops/helab_txy.py:180-192`), made when a load composes its dataset. Every mode is then disk
  cached with nothing stored twice; RAM arrays of a (shot, layer) can be shared between the modes'
  datasets (they are counted once, `utils/ram_buffers.py`).
- **Saved results** keep today's lookup key (`result_cache.py:57-62`) with the new per-shot
  fingerprints. A re-conversion is an exact match. A raw file that changes makes its HeLab shots
  "changed" in `Coverage.diff` (`results.py:69-76`), so the result shows as outdated until rerun.
  Results saved in v3 on MATLAB shots match exactly. On HeLab shots their fingerprints were TXY
  files', so they are found as their family's outdated result once (§4).
- **A raw file overwritten in place (free-run):** the new (size, mtime) replaces the row's
  fingerprint in the same transaction that retires the old blob. The source no longer holds the
  old pulses, so this is an update, as a re-read shot replaces a cached one today
  (`loading.py:539-546`), not a removal needing a question. HeLab shots made from it are
  re-converted; TXY layer entries keyed by the old raw fingerprint stop matching and are dropped at
  the layer's next save; results become outdated. Today's rule assumes raw files are never
  rewritten (Tony 2026-10-20, `loading.py:453`, `loading.py:514`), so a changed raw file of a held shot needs a
  rule: Q~5.

## 3. Read and write paths

### Who writes and reads each layer (all helpers; the GUI never opens a store)

| Operation (`helab/io_ops/`) | Lane | Reads | Writes |
|---|---|---|---|
| `load` (`loading.py:225`): Load, auto-load, presets', reopened plots' and a plot's source loads | foreground / as today | `txy_layers`, `raw_layers`, v3 under Keep | the layers its mode used; the raw layer through `raw_fill` (Q19.10) |
| `raw_fill` (new): one folder's raw files into the raw layer, after a load | background, pausable, refused offline | listing, raw files | `raw_layers` |
| `read_cached` (`loading.py:25`): cache-first, offline | local | layers, v3 under Keep | none (`last_used` only) |
| `live` check (`live.py`) | foreground | held fingerprints, new files | none until stage 3; then raw rows for raw files it converts |
| `save_held` (`save_held.py:22`): Live's autosave and stop | background | listing (stats only) | the TXY-layer segments of the held shots; raw rows for raw files it read |
| `convert` (`convert.py:375`): auto-convert, `helab convert` | background | raw files | raw rows (it parses every file anyway) and, by policy, the tag's TXY layer; TXY text only beside or with output `cache`/`temp` until stage 3 |
| `cache_admin` (`admin.py`) | local | — | clears, Make room, inventory, the v3 choice |

### Loading order for a shot of layer L (stage 2 onwards)

1. **TXY layer** L holds the shot with the current fingerprint (from the load's listing; offline,
   as stored, unverified, as `read_cached` does today).
2. **Raw layer** (HeLab layers only) holds the raw file's current fingerprint with the current
   parser: decode, convert with L's profile (in the load's worker pool, as `convert` does), and add
   it to L's save.
3. **The share:** for `helab`, a current HeLab TXY (beside, by tag and "newer than raw", Q18.4; or
   `converted-txy/`) is parsed; else the raw file is read, parsed and converted, and the raw row
   saved if the policy includes raw. For `matlab`, the `d_txy_forc` file, or under Keep a v3
   row's MATLAB shot with that fingerprint (§4).

Live keeps reading through the same order. One more point: a load of a folder with MATLAB TXY doesn't
read raw files today. Filling the raw layer there costs 2.4–3.6× the TXY bytes over the share (Q6.9),
so this note proposes it runs as a background `raw_fill` after `loaded`, so the folder shows as fast
as today (Q~1).

### Save guards and generations

- A job takes its guard first, as today (`start_dataset_job`, `cache_store.py:1136`): generations
  `gen_raw`, `gen_txy`, `gen_summaries`…, the folder's epoch, its root's `root-clear://` epoch, and a
  new `job_seq` for the folder.
- **One save unit per job:** every raw row and TXY segment a job writes for a folder commits in one
  transaction with one budget check (as `save_dataset`, `cache_store.py:1322-1393`). A unit that
  doesn't fit becomes one pending save (Make room / Don't cache), as today.
- **Ordering:** a TXY layer row is replaced only by a job with `job_seq` ≥ the row's (today's
  `_stored_job_seq`, `cache_store.py:1306`). A raw row with the **same** fingerprint and parser is
  idempotent (kept, `last_used` touched); a **different** fingerprint replaces it only from a job
  with `job_seq` ≥ the row's, since that job listed later.
- **Live and auto-convert together:** both may write the same raw row (same fingerprint: no-op).
  TXY segments append, so a Live autosave and a load of the same folder don't overwrite each
  other's shots; the folder's `job_seq` decides a shot both wrote. A Clear (epoch bump) fences
  both, as today (`_guard_holds`, `cache_store.py:1162`).
- Every save checks `no_cache` (`_check_cacheable`) and `cache_policy` in its transaction.

### Clear, Make room, offline

- **Clear by kind** (Settings → Cache) gains "Raw pulses" and "TXY data" (by layer, with its tags
  named); Clear all, a root's Clear cached data… (`clear_root`, `cache_store.py:2175`) and a folder's
  Clear loaded data cache clear both. Each sends `removed` with kinds `raw`, `txy`.
- **Make room** (asked; §5 for the order) removes whole rows: a folder's TXY layer, or a folder's raw
  rows, never the folder being saved.
- **Work Offline:** no source I/O. Loads use the layers (v4, then v3 under Keep); a HeLab layer
  missing from a folder whose raw layer is there is converted from it and saved (local work only,
  Q~8). `raw_fill` and reading the share are refused, as today's source operations.

## 4. The store-v3 compatibility choice (Q19.4)

- **Asked:** at startup, when the local-lane inventory finds `store-v3` with a `layout_version` 3
  `meta` and v4's `meta` has no `legacy_v3`. It may also be found when HeLab switches to a cache
  folder that holds one. The GUI asks once (CacheDialogs) and shows v3's size. Until it is answered,
  HeLab behaves as **Keep** (reads only; nothing written or removed), the choice that loses nothing
  (Q~3).
- **Stored:** in v4 `meta.legacy_v3` = `{choice, v3_store_id, set_at}`. It travels with the cache
  folder: a cache move renames or copies the whole folder (`utils/cache_move.py:343, 385-400`), both
  stores included. A second machine has its own cache folder and is asked there. If `v3_store_id`
  no longer matches (an older HeLab recreated v3), it is asked again.
- **Opening v3:** a separate `LegacyStore` reader with `sqlite3` URI `mode=ro`, never `CacheStore`.
  `CacheStore._open` would `makedirs` and `_migrate` it (`cache_store.py:579-581, 606`). It needs no
  write lock and has no write methods. An older HeLab may still be writing v3 in the same cache
  folder (lab machines run mixed versions); WAL read-only connections tolerate that. Windows and a
  v3 left without `-shm` need testing.
- **Store identity:** v3 rows reach the app inside v4 answers, marked `legacy: true`, under v4's
  `store_id`. `FolderCache.store_answer` (`folder_cache.py:1405`) then never sees a second store,
  and its "answers from another store wait for an identity probe" rule is untouched.
- **What Keep reads (v4 first, v3 when v4 misses):**
  - datasets: a v3 row's shots with origin `""` (MATLAB) and a fingerprint equal to the current
    listing seed the `matlab` layer; its `raw_times` too. HeLab-origin shots in it (keyed by a TXY
    file) are ignored. A v3 dataset used once is saved into v4 by that load (copy on use), so v3
    drains as folders are visited;
  - saved results: `find_result` falls back to v3 for both exact and family matches, and a v3 hit
    is copied into v4 when shown;
  - records: `folder_summaries`, `scan_histories` (so a saved scan failure still suppresses
    automatic scans), `subtrees`, `listings`, read where v4 has no row;
  - user state isn't read through: it was imported (below). If an older HeLab changes a flag in v3
    later, the newest `set_at` wins when both are read (the same rule as today's flags).
- **Imported once at v4's creation, whatever the choice:** `folder_prefs`, `convert_prefs`,
  `folder_constants`, `presets` (deleted rows included), `roots` with their decisions,
  `root_volumes`, `mount_hints`, and the budget. These are the user's choices, not cache. AGENTS.md
  forbids dropping flags, constants and presets without asking, and Ignore would otherwise drop
  them (Q~4).
- **Budget under Keep:** v3's live bytes (its `_live`, `cache_store.py:2247-2256`, measured
  read-only at inventory and stored in `meta.legacy_bytes` with v3's `writes` counter) add to v4's
  usage in every fit check and the 80 % pause. Copy on use double-counts a folder until v3 is
  cleared, which Settings says.
- **Clear store-v3 (asked, with its size):** a local-lane `cache_admin clear_legacy` deletes the
  `store-v3` folder only while no other HeLab instance runs (the `instances/<pid>.lock` check a
  cache move uses, `utils/cache_locks.py:9`). It sends `removed` kind `legacy`, and saved results
  shown from v3 then say RAM only.
- **Ignore:** v3 is never opened again; it isn't counted (not in use) and Settings → Cache shows it
  with its size and a Clear…. The choice can be changed later in Settings → Cache's
  "store-v3 (older HeLab's cache)" row (Keep using / Ignore / Clear…).

## 5. Budget and housekeeping

**One budget**: v4's raw blobs, TXY segments, results and records, plus v3's live bytes under Keep.

*Measured* per 217.5 MB of raw (309 shots, ~0.70 MB each; X's TXY/raw is 0.27–0.41 against the
sample's 0.23, so TXY layers weigh more on X):

| Kept | MB | × raw | × today's store |
|---|---|---|---|
| today: one dataset (MATLAB TXY) | 16.2 | 0.074 | 1.0 |
| raw layer | 29.5 | 0.136 | 1.8 |
| one HeLab layer: m19v1 / full float64 | 15.5 / 17.0 | 0.071 / 0.078 | ~1.0 |
| raw + one tag | ~45.5 | 0.21 | 2.8 |
| raw + MATLAB + one tag | ~61.5 | 0.28 | 3.8 |

An 8 GB budget holds ~107 GB of raw-equivalent folders today, ~38 GB as raw + tag, and ~28 GB as raw
+ MATLAB + tag. Live at one 0.7 MB shot per 30 s adds ~0.4 GB a day as raw + tag (Q~7).

**Make room's order** (always asked, plan exact and rolled back as `_room_plan`,
`cache_store.py:1529-1538`):

1. TXY layers, least recently used first (rebuildable from the raw layer locally);
2. raw layers whose raw file the last listing still saw (`source_seen_at`), least recently used
   first (rebuildable from the share);
3. raw layers whose raw file wasn't seen at the last listing: the only copy HeLab knows of, listed
   last and named so in the dialog (Q~6).

It never removes the folder being saved or a newer save waiting. Saved results keep their own Make
room (results only, `cache-store.md`).

**AGENTS.md:** no new removal rule is needed. Replacing a raw row on a changed fingerprint, and
dropping TXY entries of superseded shots at a layer's save, are updates like today's merges. Two
wording changes:

- the housekeeping line "the sweep deletes retired dataset files, and store files no row names…"
  becomes "retired dataset and layer files" (the same sweep, `_sweep_orphans`,
  `cache_store.py:2525`, with `_known_files`, `cache_store.py:2441`, extended to `raw/` and `txy/`);
- "A table or column added within `store-v3`…" names `store-v4`.

The rule that **would** be new, if Tony prefers it to asking: "the disk budget evicts TXY layers,
least recently used first", the only automatic removal on offer. It isn't proposed.

## 6. Policy: what each writes, and switching without migration

| Policy (`cache_policy`, global default a settings row) | Writes on load / Live / auto-convert |
|---|---|
| **raw** (convert on load) | raw rows; the `matlab` layer when a mode used MATLAB shots (they can't be derived); no HeLab layer |
| **raw + tag** (fast loads) | raw rows; the chosen tag's HeLab layer; `matlab` as used |
| **txy** (archives without raw, or raw not wanted) | the layers the load used (MATLAB's, HeLab's read from beside TXY, keyed then by the TXY file with origin `helab:<hash>` and `by_txy` in `info`); no raw rows |

Every policy **reads** whatever layers exist; a policy only decides what new saves write.
Switching therefore needs no migration and removes nothing; the user clears a kind if they want
the space back. Don't cache and no data root still mean RAM only for every layer (Q19.5, AGENTS.md).

## 7. Tests and build order

**Tests the build floor adds** (synthetic data only; the 309-shot check is a `dev/txy/` script,
since tests never touch real data):

- **Layer equals file:** for every case in `tests/data/convert/cases/`, every textscan probe
  (`tests/data/convert/textscan/`), `tests_sample_data/` raw files and a seeded random fuzz set
  (ties at equal times, NaN rows, row 0 not earliest, row 0 tied, |t| = 2^53 ± 1, 17-digit fields,
  CR-only files, channel > 127): encode → decode gives `RawPulses` whose stable sort and `times[0]`
  equal `parse_raw`'s (NaN-aware). `reconstruct` on it is byte-identical to the file path for every
  available backend, both built-ins and the split path. The encoder chooses compact or `f64-1`
  exactly when expected. `not_done` from `facts` equals `not_done(bytes)` for every trigger channel.
  `dev/txy/check_samples.py` gains a `--via-layer` pass over the sample set.
- **TXY layer:** decoded segments equal today's `pandas` parse of the same TXY (MATLAB's and m19v1
  text); full-precision tags equal `reconstruct` output bit for bit; compaction keeps every shot's
  newest copy.
- **Identity:** a re-conversion (cleared `converted-txy/`, layer path vs share path) gives the same
  coverage, so a saved result is an exact match; a changed raw file makes it outdated; `m19v1` and
  `p22v1` share one layer.
- **Guards:** Clear (kind, folder, root) during `raw_fill`, during a Live autosave, during
  auto-convert; two writers of one raw fingerprint (no-op), of two fingerprints (`job_seq` wins); a
  pending unit adopted after a Clear is refused; Make room's order (TXY, raw seen, raw only-copy);
  Don't cache and `cache_policy` checked in the transaction.
- **v3 compatibility:** v3's files are byte-identical and no file is added after a whole session of
  loads, results, Make room and a Clear of v4 (hash the folder before and after); v3 is never
  opened under Ignore (I/O trace); Keep seeds `matlab` from v3 and copies on use; v3 results exact
  on MATLAB shots and family-only on HeLab shots; the import of user state once; the choice
  survives a cache move (rename and copy); an older HeLab writing v3 meanwhile; `legacy` answers
  carry v4's `store_id`.
- **Offline:** `no_source_io` loads from layers, and a missing HeLab layer is made from the raw
  layer.
- `test_helper_events.py` covers the new kinds (`raw_fill` progress, `removed` kinds `raw`, `txy`,
  `legacy`).

**Build order, matching the plan's stages** (each needs Tony's go):

1. **Stage 1, the raw layer:** first `store-v4` with the carried-over tables, the user-state import,
   the v3 choice's dialog and its read-only reader (presets, flags, records, saved results), and
   the `.hlb` container. Then `raw_layers`, the encoder and decoder, the layer-equals-file tests and
   `--via-layer`, `raw_fill`, and raw rows written by `convert`. Make room's order (TXY before raw)
   in the store, since raw rows fill the budget from day one.
2. **Stage 2, TXY layers:** `txy_layers` and `txy_segments`, identity by raw fingerprint + hash,
   the loading order, every mode disk cached (Q19.3, Q14.5), v3 datasets as the `matlab` seed, and
   segments for Live's autosave.
3. **Stage 3, convert on read:** loads and Live convert from the raw layer; TXY text only beside
   the raw files and on export; `converted-txy/` read while present, cleared by the user; the temp
   output setting goes (Q19.1, Q19.7). *Amended by Tony's answers, 2026-10-29: the cache and temp
   outputs stay as options (Q19.1, Q19.7); see the plan.*
4. **Stage 4, the policy UI:** per folder (right-click, beside Don't cache) and global (Settings →
   Cache); Make room's dialog naming the only-copy raw layers; the Clear rows by kind and layer.

## 8. Open questions for Tony

- **Q~1 When does a load fill the raw layer?** (a) In a background `raw_fill` job after the folder
  shows (proposed: today's speed kept; raw files are 2.4–3.6× the TXY bytes over the share); (b)
  in the load itself.
- **Q~2 Key HeLab layers by profile hash, with tags as names?** Proposed: yes. `m19v1` and the
  uncalibrated plate tags hold identical data and would otherwise be stored and identified twice.
- **Q~3 Before the store-v3 question is answered, behave as Keep (read only)?** Proposed: yes.
- **Q~4 Import the user's own state from v3 into v4 once, whatever the choice** (flags,
  converter flags, constants, presets, data-root answers, mount hints, the budget)? Proposed: yes.
- **Q~5 A raw file that changes after it was read (free-run, or a writer resuming):** is free-run
  a real mode? Proposed: the changed file is read again, its HeLab shots re-converted and its
  layer row replaced; it never stops Live. MATLAB TXY keep the mismatch rule.
- **Q~6 Raw layers whose raw file is gone from the share (the only copy) or made by an older
  parser:** proposed: kept and used, labelled; Make room lists them last and names them; never
  removed automatically.
- **Q~7 The disk budget:** raw + tag needs ~2.8× today's space per folder. Keep 8 GB (proposed;
  Settings shows the split), or raise the default (e.g. 20 GB)?
- **Q~8 Working offline, may HeLab make and save a HeLab layer from the raw layer?** Proposed: yes
  (local work only, no source I/O).
- **Q~9 A "clear this tag's data and its saved results" action?** Proposed: not now (results are
  keyed by data, which stays valid); it would add a `result_layers` index.
- **Q~10 Text for full-precision tags (Q19.6):** a beside or exported TXY of a full-float64 tag
  written as `%.8g` no longer equals its layer. Proposed: such tags write `%.17g` text (about twice
  the size), so a text file and the layer always agree; alternatively their text is export only and
  never loaded as data.
