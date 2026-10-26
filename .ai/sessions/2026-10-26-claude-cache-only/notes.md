# Notes: cache-only browsing

## C1: no-I/O result path (2026-10-26, `9c75340`)

### Why other tabs' results were dropped

`SnapshotFileSystemModel._shared_snapshot_changed` applied another tab's finished snapshot
through `request_scan(automatic=True)`. While refreshing, `request_scan` refuses automatic work,
so the result was dropped.

When not refreshing, the request went to `FolderCache.submit`, which replays the snapshot. For a
snapshot older than `FRESH_SECONDS` it then submitted a revalidating check: source I/O, for
nothing but showing a result already in memory.

### What changed

- **`FolderCache.replay_snapshot`** replays without `revalidate`. Its requests are marked
  `applied`, so `cancel_automatic_scans` (Refresh) leaves them.
- **`model.apply_snapshot`** uses it. Only a snapshot a load found outdated (`checked_at` 0), or
  none, still goes through `request_scan`.

### Evidence

- The two `SHARED_RESULTS_DURING_REFRESH` tests pass, and their markers are gone.
- `check_in_other_tab` asserts `service.pending` is unchanged after the other tab's check.
- New `test_applying_another_tabs_old_result_submits_no_source_operation[False|True]` ages the
  snapshot past `FRESH_SECONDS`. With the old code (`helab/` stashed), the `[False]` case fails:
  a `list` request is submitted.

### Checks

- Full suite (`-n 4 --reruns 5`): 4311 passed, 2 skipped, **no RERUN**, 2:16.
- mypy --strict on `helab/` (162 files) and on `tests/` (132 files): clean.
- pyright: 0 errors.

## C0: listings table size (2026-10-26)

Measured with a SQLite table of the proposed shape:

```sql
listings (path TEXT PRIMARY KEY, record TEXT, saved_at REAL)
-- plus an index on saved_at
```

- WAL mode, checkpointed before measuring the file.
- Keys are `root://<uuid>/data/2026DDDD/run_RRR_detuning_scan`.
- Each record holds the names list, `listed_at`, `status`, `count`, `raw_count`, `txy_count`,
  `empty`, `has_dirs` and `files` (compact JSON).

| Tree | Rows | File | Insert all (one txn) | One read |
|---|---|---|---|---|
| 100 days × 100 runs | 10,101 | 4.50 MB | 20 ms | 24 µs |
| 10 days × 1,000 runs | 10,011 | 4.41 MB | 19 ms | 22 µs |
| 1,000 days × 100 runs | 101,001 | 49.1 MB | 293 ms | 27 µs |

About 450 B per folder, mostly the repeated root key. Leaf folders (no subfolders) are most rows;
each needs its own row for its counts when no full summary exists. Machine: Tony's Mac (APFS
SSD), Python 3.13 sqlite3.

## C2: saved listings (2026-10-26)

### What's built

- **Store** (`helab/utils/cache_store.py`): new record kind `listings`.
  - It is in `KINDS` and `RECORD_TABLES`, so guards, `remove`, Clear all, `clear_root` and
    `root_usage` cover it.
  - Table `listings (path, record, saved_at)` with an index on `saved_at`, in `SCHEMA`, plus
    `_migrate` (table + index + `gen_listings`).
  - The re-key table list, the inventory (`listings.count`, `ages.listings`), `_RECORD_PURGES` and
    `purge_estimate` all include it.
  - A read-only store from before listings reads as missing, counts 0 and is skipped in
    `root_usage` (`_listings_table`).
  - `CacheStore.waiting(seconds)` sets a short busy wait for an optional write.
- **Helper** (`helab/io_ops/listings.py`, new):
  - `listing_record` stores names, `listed_at` and compact counts, never shot lists.
  - `valid_listing`, `listing_guard` and `save_listing`: best effort, "saved" / "unchanged" /
    "skipped".
  - `read_listing` and `saved_listing`, the local-lane read: disk cache only, keyed through
    `_open_store(local_lane=True)`.
- **`list_folder`** takes `listing_guard` after `_send_guard` (before the scandir). It saves after
  `send(report)`, so the tab never waits for the write. A failed or partial listing sends no report
  and saves nothing.
- **Settings → Cache**: a "Folder listings" row (count, Clear…, tooltip). Clear all's text and the
  purge text and estimate tooltip mention listings.

### Rules as built

- **Skip:** the write is skipped when the saved listing has the same names and counts and is under
  `REFRESH_SECONDS` (1 h) old, or when the saved one is newer.
- **Busy store:** the write waits `WRITE_WAIT` = 0.5 s for the lock, then is skipped.
- **Guard:** a re-keyed folder (a marker found by this listing) fails the guard's key check, and
  its next listing saves it.

### Cost

On Tony's Mac (APFS, WAL), measured on 200 folders with 100 names each:

| Operation | Median | p95 |
|---|---|---|
| A save | 0.15 ms | 0.24 ms |
| An unchanged skip (one read) | 0.035 ms | — |

### Not done in C2 (left to C3)

- The `saved_list` helper operation (dispatch in `io_helper`, the IOService local lane, the event
  shape for counts without shot lists). `io_helper.py` is shared with the Quick Fixes 2 floor.
- Status checks (`scan`) and `details` don't write listings yet (design.md §3).

### Mixed versions

An older HeLab's Clear all and root Clear cached data… don't remove listings (they name their own
tables) and don't bump `gen_listings`. Listings then outlive such a clear until purged, or until
this HeLab clears them. An older HeLab's nested-root re-key leaves listings at the old key; they
are re-saved at the new key by the next listing.

### Test seam note

`tests/conftest.py`'s fake volume seeding (`open_seeded` → `record_volume`) writes on every store
open in tests. A test that holds the write lock across `list_folder` therefore waits the store's
full busy timeout in the seam, not in listing code. `test_a_busy_store_skips_…` holds the lock
after the store is open.

### Checks (C2)

- Full suite (`-n 4 --reruns 5`): 4326 passed, 2 skipped, **no RERUN**, 1:52.
- The first run had 5 real failures, retried as 25 reruns, now fixed:
  - Three tests listed the record kinds and now include `listings`: `test_cache_tab`,
    `test_result_cache_settings`, `test_root_clear`.
  - The new test file imported helpers as `tests.…`, which mypy found twice (`test_typing`).
- mypy --strict on `helab/` (163 files) and on `tests/` (133 files): clean.
- pyright: 0 errors.
