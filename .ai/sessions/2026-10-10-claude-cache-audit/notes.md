# Cache infrastructure audit

Date: 2026-10-10
Baseline: `a7370b8` on `dev/v0.0.5a` (clean tree), diskcache 5.6.3, python-blosc 1.11.4.
Asked by 🎓Tony: "what is going on with settings -> cache tab? is that still consistent or
relevant to current cache infrastructure?", then "plan the full rebuild" and "audit cache
infrastructure for future proofing". Plan: [roadmaps/cache-storage-and-settings.md](../../../roadmaps/cache-storage-and-settings.md).

## What exists

| Store | Where | Used by the current browser | Opened by |
|---|---|---|---|
| `data_ram_cache` (FanoutCache, 16 shards, 8 GB) | `DIR_CACHES/data_ram_cache` | Yes, the only disk store | Helpers (`io_helper.py`); also the GUI at import (`caching_setup.py`) |
| `status_cache` (2 GB) | `DIR_CACHES/status_cache` | No: legacy `HelabFileSystemModel`, `StatusReport` | GUI at import |
| `os_file_system_cache` | `DIR_CACHES/os_file_system_cache` | No: legacy model/workers via `os_cached.py` | GUI at import |
| `FolderCache` (memory) | session | Yes: datasets (512 MiB budget), snapshots (256 folders / 100k entries), icons (4096), histories, subtrees | GUI |

Keys in `data_ram_cache` (all keyed by the lexically normalised path, `FolderCache.key`):

- Dataset: bare `path` → Blosc(zstd 9)-compressed pickle of `{shot: float64 (n, 3)}`;
  `("snapshot-fingerprint", path)`, `("snapshot-problematic", path)`, `("snapshot-cache-info", path)`,
  `("snapshot-epoch", path)` (bumped by per-folder "Clear loaded data cache").
- Metadata: `("folder-scan-v1", path)`, `("folder-scan-history-v1", path)`, `("folder-subtree-v1", path)`.

Tony's live cache on 2026-10-10 (read-only SQLite inventory, `~/Library/Caches/HeLab/caches`):

| Kind | Entries | Size |
|---|---|---|
| Datasets (`path`) | 19 | 667 MB |
| `snapshot-fingerprint` / `-problematic` | 19 / 19 | ~0 |
| `snapshot-cache-info` | 8 (11 datasets predate save dates) | ~0 |
| `snapshot-epoch` | 2 | ~0 |
| `folder-scan-v1` | 445 | ~0 |
| `folder-scan-history-v1` | 464 | ~0 |
| `folder-subtree-v1` | 33 | ~0 |
| Orphan blob files | 0 | 0 |

Per-shard MB: `[0, 47, 0, 0, 54, 31, 0, 0, 19, 0, 348, 0, 143, 0, 25, 0]`. Legacy caches: 1 MB each.

## Settings → Cache tab (`helab/views/SettingsDialog.py`)

1. Parameter overrides never apply: the dialog saves `diskcache/<name>/<key>`, `load_cache_param`
   reads `cache_params/<name>/<key>`. The form is disabled; Save still writes the dead keys.
2. If enabled, the form would corrupt values: all go through an integer spin box with B…TB units
   (`timeout` 0.2 → 0, `shards` 16 → "16 B", `cache_compression` → "1 B"); `tag_index` absent.
   `load_cache_param` would also return INI strings, not numbers.
3. "Force Save Cache to Disk" calls `close()`; diskcache writes are already durable.
4. "Clear Cache"/"Clear All Caches" run `FanoutCache.clear()` on the GUI thread, race helper
   writes, clear datasets + summaries + scan-failure history together, and bypass `FolderCache`
   (no epoch bump, `_disk_cached_paths`, cache states, snapshots, histories and subtrees in memory
   stay stale: badges keep saying "Cached data found").
5. Hits/misses/size are read on the GUI thread (3 caches × 16 shards).
6. Shows internal names; two of three caches are legacy; "Reset" calls `settings.clear()` (every
   HeLab setting, not just this dialog's).

## Storage findings (ranked)

### A. Confirmed bugs

1. **`statistics: True` turns every `get` into a write transaction.** diskcache `Cache.get`
   takes the slow path (`_transact`, `UPDATE Settings … hits/misses`) when statistics are on
   (`core.py` ~1162–1206). `FanoutCache.get` uses `retry=False` and returns the default on
   `Timeout` (`fanout.py` 257–287), with `timeout` 0.2 s. So under write contention a read
   silently returns `None`. The longest lock: `load()` stores the dataset blob inside
   `cache.transact()`, which locks **all 16 shards** (`fanout.py` 70–100) while
   `Disk.store` writes hundreds of MB.
   Consequences:
   - `scan()` reads the history outside a transaction; `None` parses as `empty_history()`
     (not blocked), so an **automatic scan runs on a blocked folder**. `begin_scan` does not
     re-check `blocked`. Violates the AGENTS.md rule "every automatic basic-scan entry point must
     honour the failure flag".
   - `list_folder` sends missing summaries/histories/subtrees (badges vanish until the next listing).
   - Only the Cache tab consumes the counters.
2. **Writes can fail silently.** `FanoutCache.set` returns `False` on timeout (`fanout.py` 125).
   `save_subtrees` ignores it and still sends `subtree_saved`; `_save_summary` ignores it.
3. **Eviction mixes metadata with datasets.** One `least-recently-stored` policy for every key,
   and FanoutCache splits `size_limit` per shard (`fanout.py` 38: 8 GB / 16 = 512 MB). Shard 10
   is at 348 MB; the next large dataset hashed there culls the oldest-stored entries of that shard,
   which are mostly scan histories and summaries. Losing a failure history re-enables automatic
   scans of a known-bad folder; losing a dataset's blob leaves its fingerprint/info (UI may show
   cache dates for a cache that is gone); losing `snapshot-epoch` disables the clear guard.
   "Least recently stored" also evicts a dataset used every day before one never reopened.

### B. Future-proofing risks

4. **No schema version for datasets or the layout.** Dataset keys are unversioned; the payload is
   a pickle (numpy 2 pickles reference `numpy._core`, unreadable by numpy 1.x; any format change
   has no migration path except "Cached dataset invalid" → re-read). python-blosc 1.x is in
   maintenance mode; Blosc2 is its successor.
5. **Killed writers can leak blobs.** `Disk.store` writes the file before the SQLite commit; a
   helper killed in between (timeout, cancel, quit) leaves a file no row points to. diskcache never
   removes these unless `check(fix=True)` runs. None on Tony's machine yet.
6. **Cross-shard "transactions" commit shard by shard** (ExitStack). A crash mid-commit can leave a
   new blob with an old fingerprint. Current readers tolerate it (unchanged shots must match the
   old fingerprint, so mismatches are re-read), but nothing documents or tests this.
7. **Resource sizing.** Each helper opens 16 shards with `sqlite_cache_size` 256K pages (~1 GiB
   page cache each, upper bound) and 1 GiB mmap. Blobs ≥ 8 MB are files, so DB pages stay small;
   the ceiling is far above need. `cache_compression` is not a diskcache option (stored as an
   unused setting).
8. **Cache location.**
   - `DIR_CACHES` changes need a restart (constants read at import), and the old cache is
     orphaned, not moved. The dialog says neither.
   - SQLite WAL is unsafe on network filesystems, and synced folders (iCloud/OneDrive) can
     conflict. Nothing stops choosing one.
   - diskcache pickles values, so the cache folder must be private to the user.
9. **Path keys are lexical.** The same folder via another mount name/drive letter/UNC path is a
   separate entry; a renamed folder loses its cache. Summaries/histories are guarded by
   `[st_dev, st_ino]`; whether `st_dev` of `/Volumes/dld_output` changes across remounts is
   untested. If it does, every remount discards saved summaries and failure history.
10. **Legacy stores open in the GUI process at import** (`main.py` → `caching_setup`), and
    `main.py` logs `cache_status_string()` (stats + volume of all three) before the window shows.
11. **Metadata grows without bound** (one record per path ever visited; tiny today: ~950 records).

### C. Fine as is

- Helpers own all reads/writes of `data_ram_cache` during browsing; the GUI never reads it while
  rendering.
- Per-folder clear (`invalidate`, right-click "Clear loaded data cache") goes through
  `FolderCache` with an epoch, so in-flight saves cannot repopulate it.
- No orphan files and no unreadable entries in the live cache.

## Old browser assessment

Checked 2026-10-10 with grep and CodeGraph against `a7370b8`.

The old browser is `HelabFileSystemModel` (a `QFileSystemModel`) with `StatusTreeView`,
`StatusIconDelegate`, and the QRunnable workers in `helab/workers/` (`StatusWorker`,
`StatusDeepWorker`, `StatusRescanWorker`, `DirectoryCheckWorker`, `LoadFolderToRamWorker`,
`HelabFSModelThrottleDataChangedEmit`). It relies on `os_cached.py`, `status_cache`,
`os_file_system_cache` and the pools and worker registries in `threading_setup.py`.

Where the current app still touches it:

| Link | Finding |
|---|---|
| `StatusReport` | The current model builds `StatusReport` objects (`SnapshotFileSystemModel` 502, 612, 703, 758) and uses only the status constants. The module imports `caching_setup`, `threading_setup`, `os_cached`, `DirectoryCheckWorker` and (at the end) `StatusWorker`, so importing it loads the whole old stack and opens all three FanoutCaches. |
| `fnum` | Defined in `caching_setup.py`; used by `FolderDetailsPanel`, `SettingsDialog`, `HelabMainWindow` (debug log) and old code. |
| `FolderTabWidget` | Uses `HelabFileSystemModel.COLUMN_*`; `clear_status_cache` (Debug → "Clear Status Cache") calls `explorer.rescan(True)` and clears the old worker registries. |
| `HelabMainWindow` | Star-imports `caching_setup` (twice), `os_cached`, `threading_setup`. `closeEvent` calls `cancel_all_workers`, waits on `all_pools_total_activeThreadCount`, then `close_all_caches`. `_setup_middle_area_deprecated` (uses `legacy_plotly`) is never called. |
| `main.py` | Imports `caching_setup`, logs `cache_status_string()` before the window shows. |
| Thread pools | No current code submits to `thread_pool_*`; only the old model and workers do. |
| `MemoryUsageWindow` | Uses pympler and psutil only; unrelated, stays. |
| Tests | Old-only: `test_helabFileSystemModel`, `test_statusworker_ut`, `test_statusDeppWorker`, `test_directoryCheckWorker`, `test_cachingSetup`, two `.disabled`. Shared: `conftest.py` calls `cancel_all_workers`; `test_gui_responsiveness` monkeypatches `status_cache.get` to forbid GUI access. |
| Scripts | `helab/scripts/` is the analysis script system: `ScriptTreeSelector` loads `helab/scripts/examples/` (or a chosen folder) and uses `plotly_3d_sactter.Plotly3DScatter`; `legacy_plotly` holds the lab's older Plotly figures. Only `helab/scripts/dev/` (9 plotting-library prototypes: matplotlib, plotly, dash, pyqtgraph, pyvista, vispy, manim) reads the old cache directly through `data_ram_cache` and `LoadFolderToRamWorker.default_algorithm_decompress`; nothing in the app loads them. |

Verdict: removable, low to medium risk, in two steps (untangle, then delete). User-visible change:
the Debug item only. Gains: no old caches opened at startup, faster imports, no diskcache once the
new store lands, simpler AGENTS.md. Plan: [S2/S3](../../../roadmaps/cache-storage-and-settings.md#old-browser-removal).

## Decisions

Recorded in the plan's Decisions table (Tony, 2026-10-10). Tony asked whether SQLite is bad for
large loads: it is only for small records; datasets stay compressed files beside it, as diskcache
already stored values over 8 MB as files. Tony's Mac has 128 GB RAM, so 1/128 steps are 1 GB.

Later on 2026-10-10 Tony settled the rest:
- Large-folder checks exist to stop accidental automatic loads: those never start and warn;
  deliberate loads confirm in a dialog.
- Defaults: 8 GB disk budget, 1/8 of RAM.
- The cache move runs while HeLab stays open and switches in place; on failure HeLab keeps
  the current folder and carries on. Order: copy, check, update setting, delete old (the reverse
  order Tony first suggested could leave the setting pointing at a deleted folder).
- Purges: cached data by `last_used` and folder records by `saved_at`, default 90 days, any
  number of days.
- Nothing is removed automatically: a 90% warning, and a dialog when a save doesn't fit.

### RAM size versus TXY size (measured 2026-10-10)

Read-only, from the 19 datasets in Tony's cache (0.3–1,066 MB of TXY each): a TXY row is
34.1–35.6 bytes of text, and the arrays take **0.67–0.70×** the TXY size (24 B per row). The
compressed cache file is about 0.27× the TXY size. Example: `Quant_eff_20260812` has 1,065.7 MB
of TXY, 729.8 MB in RAM and a 293.8 MB cache file. Tony chose to estimate RAM as the unscaled TXY
size (safe overestimate).

Further decisions the same day:
- An 80% pause for automatic loads of uncached folders, replacing the 90% warning. Cached
  folders still open, and their updates ask before saving.
- The won't-fit dialog offers only Make room or Don't cache now.
- Per-folder "don't cache" and "don't auto-load" flags, never inherited.
- A move-failure dialog with Show in Finder/Explorer.
- Scans record per-kind counts and sizes (`files`); only TXY is sized for now, but the code
  is table-driven so raw `d*.txt` and other formats can be added.
- Every load starts with a basic scan: the load's own listing-and-stat phase (already saved as
  the folder summary) provides the size before any file is read, rather than a separate scan
  helper listing the folder twice.

## Plan review (Codex, 2026-10-10)

Six findings on the plan; all accepted and written in:
1. **[P1] Session order.** S3 would have deleted `caching_setup.py` while the current browser
   and Settings still used it. It now stays until S5.
2. **[P1] Move crash window.** Added a `cache-move.json` record and startup recovery for rename
   and copy.
3. **[P1] Cached data skipped the large-folder guard.** The guard now also runs before
   `cached` reads.
4. **[P2] Reader lifetime.** Replaced files are retired and deleted after a grace period;
   readers re-read once.
5. **[P2] Purge/trim invalidation.** One removal function with per-folder epochs, `removed`
   events and `FolderCache.removed()`.
6. **[P1] Network locations.** Network and synced folders are refused, including at startup.

Second round, same day (Codex re-checked the revisions). Three more gaps, all accepted:
- **[P1]** The move recovery table missed states. Recovery now checks which folder holds the
  store (`store_id`) and uses the recorded step only for copies; every action is idempotent,
  and crashes are injected around every write.
- **[P1]** Per-folder epochs lived only in dataset rows, which removals delete. Added a durable
  `folder_epochs` table, read when each writing job starts.
- **[P2]** Deferred deletion vs Make room. The budget counts live data only (retired files are
  shown as "freeing"). An over-budget save becomes a `pending_saves` entry, which `make_room`
  adopts in the same transaction as the trim; no helper waits.

Third round (Codex):
- **[P2]** The sweep ran only at startup and once after. It is now scheduled by deadline from
  `FolderCache`.
- **[P1]** Make room could invalidate its own update. It now validates first, never evicts the
  target, and uses the fit rule: live − the target's old bytes + pending bytes.
- **[P2]** Adoption renamed a file. The final file name is now published before the pending row
  is registered, so adoption only changes rows.
- Wording reconciled: the budget counts live data, and clear-by-kind bumps folder epochs (Clear
  all bumps `generation`).

Fourth round (Codex, asked by Tony "is it ready to execute?"): five findings and two details,
all accepted.
- **[P1]** Clear-by-kind missed a first save in flight: per-kind generations.
- **[P1]** An older pending save could overwrite newer data: dataset `revision` compare-and-swap
  and `pending_id`.
- **[P1]** Move race with a starting instance: `cache.lock` and instance locks outside the
  cache, WAL checkpoint and verifying the copy as a store, Cancel until verified.
- **[P1]** The local-lane rule clashed with source helpers: the rule now applies to cache-only
  jobs.
- **[P2]** 80% approval: `pending_saves.reason = needs_approval`, and `adopt` rechecks the
  current budget.
- Details: the one-stat unchanged fast path is kept; S8 now depends on S7.

Fifth round (Codex): two narrow gaps, accepted.
- **[P1, S4]** Two jobs with the same base revision could stage pending saves out of order. A
  per-folder `job_seq` (taken when a load starts, stored in `folder_epochs`) now orders dataset
  writes and pending saves, replacing the revision compare-and-swap.
- **[P1, S9]** Rollback is limited to before cutover. After it, HeLab keeps the destination and
  finishes cleanup at the next start. Cutover requires `QSettings.sync()` and
  `status() == NoError` before recording `setting_updated`.

Codex: "S1–S3 can proceed."

Sixth round (Codex): if the settings write fails after a same-disk rename, HeLab renames back.
If that fails too, it keeps the destination and the move record and runs on the store that
exists. Codex: "no further plan-level blockers to execution".

"Is it overkill?" review (Codex, asked by Tony). Codex would keep the storage safeguards.
Applied:
- No promise to cache a second kind beside the first (datasets stay keyed by path), and no
  loader framework yet.
- Crash tests are bounded to meaningful transitions, not one case per copied file.
- A note that the RAM budget bounds retained datasets, not total memory.

Kept as Tony's decisions, flagged to him:
- the live cache move (Codex: S9 is the largest optional cost and could be deferred whole)
- the "I understand" checkbox (Codex: optional friction)
