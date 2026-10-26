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

## CI 40272585640 on 3b2223f: Windows failure of the mount-hint test (2026-10-26)

**Result.** Green on macOS (4416) and Ubuntu (4414), no RERUN. On Windows,
`test_an_unmounted_shares_listing_is_found_offline_through_its_mount_hint` failed all 6 attempts:
no hint was recorded (`{}`).

**Cause: the test, not D1.**
- The test gave the fake share macOS's mount source, `//operator@server.example/LabData`.
- On Windows, `cache_paths._webdav_unc` treats a UNC whose first part has `user@` as WebDAV, which
  has no disk cache. So `CachePaths.key` raised `UnresolvedRemotePath` and `_mount_tops` skipped
  the mount.
- Real Windows SMB mounts come from `WNetGetConnectionW` as `\\server\share`, with no account in
  them. The expected key's mixed separators are fine: a Windows mount path as the key, an
  `smb://` URL as the value.

**Fix.**
- The test now uses each platform's own spelling: `\\server.example\LabData` (`smb`) on Windows,
  `//operator@…` (`smbfs`) elsewhere.
- A new test, `test_a_windows_mapped_drive_gets_a_hint_and_keys_offline_once_unmapped`, patches
  `cache_paths.sys` and `data_roots.sys` to `win32`, so it runs Windows' path logic on every OS. It
  checks that:
  - a mapped `Z:` is hinted as `smb://lab-server/labdata`, and the system drive isn't;
  - a `user@host` UNC gets no hint (the CI failure's cause);
  - with `Z:` gone, `Z:\2026\run_1` keys as `smb://lab-server/labdata/2026/run_1`, case-insensitively;
  - a drive mapped to another share at `Z:` wins.

**Checks.** Full suite: 4417 passed, 2 skipped, no RERUN.

Not pushed: it is folded into the push after Vernier's review.

## Review round 1 fixes (Vernier, `review-findings.md`), 2026-10-26

Each finding has a test that fails without its fix. Checked by setting aside `helab/` alone: the five
new tests failed, plus the failing-save test, whose patch target `CacheStore.save_listing` didn't
exist before. All pass with the fixes.

**P1. A finished ordinary load's cache-write tail kept reading the folder after Work Offline.**
- Fix: `IOService.set_offline` now also stops completed loads that aren't saves the user asked
  for. The tail ends `cancelled` with `OFFLINE_SAVE_STOPPED` ("Not cached: Work Offline stopped the
  save (it reads the folder); saved by its next load").
- FolderCache's finishing-writer path records it as a failed cache save: `saveEnded` "failed", off
  `quit_saves`.
- The data stays in RAM. Going offline never waits on a volume that may be gone.
- Test: `test_going_offline_stops_a_finished_loads_cache_write_which_reads_the_folder`. It also
  checks that a Live save's tail goes on.

**P2. A save asked for before the switch, but waiting for another load, was refused.**
- Fix: `FolderCache.set_offline(True)` marks waiting saves (`_deferred_saves`) `before_offline`.
  `FolderCache.submit` and `IOService.submit` let a `load` with `save` and `before_offline` through;
  the helper already exempts saves.
- New saves asked for offline are still refused.
- Test: `test_a_save_asked_for_before_going_offline_still_runs_after_the_load_it_waited_for`.

**P2. A stale nested hint beat a current containing mount.**
- Fix: `_offline_mounts` skips a hint at or below a current volume or share mount
  (`stores._volume_mount`: remote, SMB, below a `MOUNT_TOPS` folder, or a Windows drive other than
  the system's).
- Ordinary system mounts above a hint, such as a tmpfs `/tmp` or the system volume, don't count:
  otherwise every hint under `/tmp` or `/` would be ignored. This is narrower than "any non-system
  mount" on purpose.
- Test: `test_a_volume_or_share_mounted_above_a_hint_wins_over_it`.

**P2. An offline listing in flight absorbed Work Online's Refresh.**
- Fix: `FolderCache.set_offline(False)` cancels offline jobs (`payload["offline"]`) and their
  replays and answers still in `_deliveries`. Offline answers now carry `offline` in their
  payload.
- The model treats a `cancelled` of an offline request like Refresh's own cancel: the row is
  released with no error.
- Test: `test_work_online_cancels_a_saved_listing_in_flight_and_lists_the_folder_anew`. It sends
  the old listing's late events and checks they change nothing.

**P2. "Newer listing wins" was decided outside the write transaction.**
- Fix: `CacheStore.save_listing` compares (newer `listed_at`, or unchanged and under an hour old)
  and writes in one write transaction. `listings.save_listing` keeps its lock-free first look
  only as a shortcut.
- Test: `test_two_helpers_listing_at_once_never_let_the_older_listing_win`. The older helper's
  first look sees nothing (as if it read before the newer saved), and it still doesn't overwrite.

**Seams strengthened:**
- `deny_source`: patches `os.scandir`, `os.stat`, `os.lstat`, `os.listdir` and `open` for the source
  tree. The offline restart fixture arms it after the online session, so every in-process helper
  call offline that reaches the source fails, and a final check lists any tried.
- The window test opens a second tab and checks that Work Online relists both tabs' folders from
  the source.
- The in-flight switch is tested as above.

**Vernier's probe** (`review-probe-round1.py`) now prints an online `list` at Refresh, then stops:
it removes the old `saved_list` request from the queue itself, and going online has already
cancelled and removed it.

**Checks.** Full suite: 4422 passed, 2 skipped, **no RERUN**. mypy --strict on `helab/` and `tests/`
clean; pyright 0 errors.

## Review round 2 fix (Vernier), 2026-10-26

**P2. A disk mounted at a custom path didn't override an old nested hint.**
- Scenario: ext4 `/dev/sdb1` at `/srv/lab` was judged by its directory, so an old share hinted at
  `/srv/lab/subdir` still won.
- Fix: `stores._volume_mount(mount, volumes)` now decides by what the mount is, not where it is.
- **Counts as a volume** (its mount wins over hints at or below it):
  - a share or remote mount;
  - a mount with a volume ID this request has (`LocalVolumes`, supplied or verified);
  - a block device's filesystem (source `/dev/…`);
  - a Windows drive other than the system's;
  - anything below a mount top.
- **Never counts:** the system volume, or a pseudo filesystem such as tmpfs, whose hints below stay
  usable.
- Test: `test_a_disk_mounted_anywhere_wins_over_a_hint_below_it[True|False]`. It covers a known
  volume ID, and separately a `/dev` source alone; a tmpfs hint below `/run/user/1000` stays. With
  the known ID it checks Vernier's reproducer key, `root://new-root/subdir/run`. Both cases fail
  without the fix.

**Checks.** Full suite: 4424 passed, 2 skipped, **no RERUN**. mypy --strict on `helab/` and `tests/`
clean; pyright 0 errors.

## Review round 3 fix (Vernier's delta check; rule from CoCo), 2026-10-26

**P2. A current NFS4 mount at a custom path missed the rule.**
- psutil gave `remote=False`, and the mount had no volume ID, no `/dev` source and wasn't under a
  mount top. So an old nested SMB hint won again.
- CoCo asked to invert the rule rather than add a fourth case.

**Fix.** `_volume_mount` is replaced by `stores._transparent_mount`:
- A current mount at or above a hint's path wins over the hint, whatever its filesystem (disk,
  share, NFS, FUSE, CIFS, autofs, anything unknown).
- **Exceptions** (`TRANSPARENT_FILESYSTEMS`): the system volume (`fixed_mount`) and pseudo
  filesystems such as tmpfs, devtmpfs, devfs, ramfs, overlay, proc, sysfs and cgroup. Hints below
  these stay usable.
- Vernier's NFS reproducer, adapted to the new names (it imported `_volume_mount`): `/srv/lab/subdir/run`
  now raises `UnresolvedRemotePath` (NFS, no disk cache) instead of keying to `root://old-root/run`.

**Tests.** `test_any_mount_at_a_custom_path_wins_over_a_hint_below_it_unless_transparent`, run for
`nfs4`, `fuse`, `cifs` and `autofs`:
- each mount at `/srv/lab` wins over the `/srv/lab/subdir` hint;
- tmpfs at `/tmp` and at `/run/user/1000` keeps the hints below it.

Without the fix, `nfs4`, `fuse` and `autofs` fail; `cifs` already passed, its source being an SMB
share. The round 1 and round 2 tests still pass.

**Checks.** Full suite: 4428 passed, 2 skipped, **no RERUN**. mypy --strict on `helab/` and `tests/`
clean; pyright 0 errors.
