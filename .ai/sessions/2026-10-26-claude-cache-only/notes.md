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
