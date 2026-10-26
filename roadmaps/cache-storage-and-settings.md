# Cache storage, memory budget and the Settings → Cache tab

Horizon: now (v0.0.5a). Added: 2026-10-10. Decisions agreed with Tony on 2026-10-10 (below);
built over several sessions and commits, tracked in [Sessions](#sessions). **Done 2026-10-11**
(S1–S11); settled summary: `.ai/memory/results/disk-cache-and-budgets.md`; native checks:
`.ai/MANUAL_TODO.md`.
Evidence and the old-browser assessment: [cache audit](../.ai/sessions/2026-10-10-claude-cache-audit/notes.md).
Priority and completion: [overview](_readme.md).

## Why

The Settings → Cache tab was built for the old folder browser:

- It shows three disk caches; only `data_ram_cache` is still used.
- Its parameter form can't save.
- Its Clear buttons block the GUI and leave badges stale.

The audit found worse problems underneath, in the diskcache-based store:

- With statistics on, every read is a write. A read that loses the lock waits 0.2 s, then
  silently answers "nothing saved", so an automatic scan can run on a folder blocked by scan
  failures.
- Writes can fail silently.
- Eviction treats tiny records and datasets alike, with the 8 GB limit split into 16 × 512 MB, so
  scan-failure history can be deleted to make room for data.
- There is no version number, so formats can't change safely.

The old browser's code is still imported at startup, and opens two caches nothing reads.

Goal:

- a cache we understand and can change safely
- memory and disk budgets the user controls
- a warning before a load that could exhaust RAM
- a Cache tab that shows what is stored and clears it safely
- no old-browser code left

## Decisions (Tony, 2026-10-10)

| Topic | Decision |
|---|---|
| Old cache contents | **Drop everything** (datasets and records). Early development: rebuilding is cleaner and less risky than migrating. |
| Dataset format | **Keep the Blosc-compressed pickle for now.** Roadmap item to look into a pickle-free format later. |
| Records | Plain readable records, not pickles: **SQLite with JSON text** (see [Store layout](#store-layout)). Datasets stay compressed **files**, never inside SQLite. |
| Record retention | **Records are kept automatically forever**; only the user removes them. Datasets record when they were last used. |
| Purge | Two age-based purges in the Cache tab, **default 90 days, any number of days can be typed**: cached data not used in N days, and folder records not checked in N days (scan failures only if ticked). Each shows what it frees before removing. |
| Disk budget | **Editable, default 8 GB.** It counts live data: dataset files in use plus the records database. Files being freed and pending saves don't count. Records are tiny and are never removed to make room. **Nothing is removed automatically.** At **80%**, automatic loads of folders with no cached data pause, and a dialog offers the purge settings. A save that won't fit, or an update to a cached folder while over 80%, asks first. |
| RAM budget | **Editable, in bytes, in steps of 1/128 of the computer's RAM, minimum 1 GB, default 1/8 of RAM.** Decides which loaded folders stay in RAM. |
| Large folders | The point is to stop **accidental** huge loads. **Automatic loads** above the RAM budget or 10% of RAM **don't start** and show an amber warning with "Load anyway…". **Deliberate loads** ask in a dialog. Above 30% of RAM, every load is **refused**. The RAM estimate is the **TXY files' size on disk, with no scaling**: it overestimates (data takes about 0.69× in RAM), which is the safe side. |
| Folder size | A basic scan records each file kind's count and total size in the folder's saved summary (`files`, see [File kinds](#file-kinds)). For now only TXY sizes are measured; raw `d*.txt` are counted, not sized. **Every load that lists the folder starts with a basic scan**: its listing-and-stat phase is a complete basic scan, saved before any file is read, and it gives the size used by the large-folder check. The one-stat "unchanged" check of cached data is kept; it doesn't list, and its size comes from the dataset record. |
| Folder flags | Right-click toggles **Don't cache this folder** and **Don't auto-load this folder**. They apply to **that folder only**, never to parents or subfolders. |
| Cache folder | Changing it **moves** the cache **while HeLab runs**. I/O pauses; on success HeLab switches to the new folder in place. On failure or Cancel it keeps the current folder and carries on, with a dialog giving the reason and **Show in Finder/Explorer** for any folder left to deal with by hand. The setting changes only after the copy is complete and checked, and a move record lets the next start repair an interrupted move. **Network and synced folders are refused**, not just warned about. |
| Old browser | Assess and remove it entirely (see [Old browser removal](#old-browser-removal)). |
| `helab/scripts/` | This is the **analysis script system** for the right-hand panel and stays. Only `helab/scripts/dev/` (plotting-library prototypes) is affected by the removal. |

## Rules for every session

- The GUI process never opens the store; it uses helper events and its memory (`FolderCache`).
  - **Source helpers** (`list`, `details`, `scan`, `load`) keep reading and writing their own
    folder's records and dataset, as today. They run on the foreground/background lanes.
  - **Cache-only jobs** (`cached`, `cache_admin`, `subtree_save`, `scan_history`, flag saves,
    `sweep`) run on the **local lane** and never touch source folders.
- A failure is never reported as "nothing saved". Readers return found / not found / error; an
  error becomes a visible warning and never unblocks an automatic scan.
- Each save checks, in its own transaction, the values it read when its job started: its
  kind's generation and the folder's `folder_epochs` value. Dataset saves also carry a
  per-folder **job sequence** taken at job start (see [Save guard](#removals)). A save that was
  already running can't write back data that was removed, or overwrite newer data.
- Tests use temporary cache folders (`HELAB_DIR_CACHES_OVERRIDE`) and never touch the user's
  cache.
- Each session ends with the full suite, mypy strict and pyright green. Then update this plan's
  [Sessions](#sessions) table and ask Tony before committing.

## Store layout

All under `DIR_CACHES/store-v2/` (unchanged default: `~/Library/Caches/HeLab/caches`).

**Records: `records.sqlite`** (SQLite, WAL)
- The helpers' connections set `busy_timeout` to 30 s, so a timeout is an error, not a miss.
- Every record is human-readable JSON text, so the file can be inspected with `sqlite3` or DB
  Browser.

| Table | Key | Columns |
|---|---|---|
| `meta` | `key` | `layout_version` (2), `store_id` (UUID), `created_at`, and one generation per record kind: `gen_datasets`, `gen_summaries`, `gen_histories`, `gen_subtrees`. Clear-by-kind bumps that kind's; Clear all bumps all four. |
| `folder_epochs` | `path` | `epoch` (integer): bumped by every removal that touches the folder. `job_seq` (integer): incremented by every dataset-writing job (load) **when it starts**, in a short transaction that returns the job's number. Never deleted, so it outlives the rows it guards and covers folders with records but no dataset. |
| `folder_summaries` | `path` | `record` JSON: today's `folder-scan-v1` content, with counts and sizes per file kind in `files` (see [File kinds](#file-kinds)); `identity`, `saved_at` |
| `scan_histories` | `path` | `record` JSON (today's `ScanHistory`), `saved_at` |
| `subtrees` | `path` | `record` JSON (today's `folder-subtree-v1`), `saved_at` |
| `folder_prefs` | `path` | `no_cache`, `no_auto_load` (booleans), `set_at`. The user's choices, not cache: never purged by age and never cleared by "Clear all"; only by its own Clear. |
| `pending_saves` | `pending_id` (UUID) | `path` (unique: a pending save with a higher `job_seq` replaces one with a lower; a lower one arriving later is discarded instead), `reason` (`over_budget` / `needs_approval`), `file`, `bytes`, `record` JSON (the dataset row to insert), `gen_datasets`, `epoch` and `job_seq` read when the job started, `created_at`. A compressed dataset waiting for the user's answer. |
| `retired_files` | `file` | `retired_at`. Dataset files no row uses any more; the sweep deletes them after a grace period (see [Reader safety](#store-layout)). |
| `datasets` | `path` | `file`, `bytes` (file size), `ram_bytes`, `rows`, `shots`, `fingerprint` JSON, `problematic` JSON, `info` JSON (`saved_at`, `snapshot_at`, `signature`, `counts`, `unsettled`), `last_used` (indexed), `job_seq` (of the job that wrote it) |

- The fingerprint list is about 100 KB for 3,000 shots, which is fine as JSON. It must be
  readable without decompressing the data, because the cache-first check uses it on its own.
- `last_used` is updated whenever a helper serves the dataset: shown from the cache, reused by a
  load, or confirmed by a check. It is one small write per load. Records have no access date
  (a listing shows hundreds at once); their purge uses `saved_at`, when HeLab last checked the
  folder. `saved_at` is indexed in every record table.
- "Clear by kind" is `DELETE FROM <table>` plus a bump of that kind's generation, in one
  transaction (see [Removals](#removals)). That also stops a folder's **first** save still in
  flight, which has no row yet.
- "Purge older than" and its estimate are one query on `last_used`.

**Datasets: `datasets/<id>.blosc`**, one file per folder (Blosc zstd-9 pickle of
`{shot: float64 (n, 3)}`, today's format). Writing one:
1. Compress, write to `datasets/tmp-<id>`, fsync, rename to `<id>.blosc`.
2. One transaction: check the [save guard](#removals) values read when the job started and
   the [fit rule](#when-the-disk-cache-fills-up), upsert the `datasets` row (with its `job_seq`), note
   the previous file.
3. Commit. The previous file is **not** deleted now: the same transaction adds it to
   `retired_files` (file, retired_at).

**Reader safety.** A reader may look up a row and open its file just after a writer replaces
it. WAL readers can still see the older row, and on Windows an open file can't be deleted.
So no removal deletes a dataset file directly:
- Replacements, purges, trims and clears put the file in `retired_files`.
- The sweep deletes retired files after a grace period (10 minutes; see
  [sweep scheduling](#cache-maintenance-cache_admin-helper-operation-local-lane)). On Windows, a file that is
  still open is retried on the next sweep.
- A reader that finds its file missing re-reads the row once in a new transaction. If the row
  now names another file, it opens that. If the row is gone, the answer is "missing". Otherwise
  it is an error, never "missing".

A killed writer leaves at most a `tmp-` or an unreferenced file. The sweep deletes these once
they are more than an hour old, so it can't race a writer that is still running.

**Versioning.** At startup a helper checks `layout_version`:
- a missing store is created
- the old `data_ram_cache/`, `status_cache/` and `os_file_system_cache/` folders are deleted in
  the background
- a **newer** version than this HeLab understands opens read-only, and the Cache tab says so

The dataset file format is the second thing to version: `info.format = "blosc-pickle-1"`.

diskcache is no longer used once the switch is done (and the old browser is gone); remove it from
`requirements.txt`.

## File kinds

TXY files are the only kind loaded and sized today, but the code must not assume it. Raw
`d*.txt` and later formats (e.g. other converter outputs) should be a table entry, not a
rewrite. Design rules for every session:

- **One table of file kinds** (e.g. `FILE_KINDS` in a small module the helper imports):
  - name (`txy`, `raw`), filename pattern and shot-number group
  - whether it is loaded
  - whether its size is measured, and its in-RAM estimate rule (today: on-disk bytes, unscaled)

  `io_helper.py`'s `RAW`/`TXY` regexes and the separate `raw`/`txy` sets become lookups in it.
- **Summaries store per-kind entries:** `files: {"txy": {"count": 456, "bytes": 1065700000},
  "raw": {"count": 460}}`. A missing `bytes` means "not measured", never 0. Status
  classification (`ok`, `fixable`, …) keeps working from the counts.
- **The large-folder estimate** sums the sizes of the kinds a load will read. Today that is TXY.
- **Dataset records** name the kind they were loaded from (`info.kind = "txy"`), and the dataset
  file format is versioned (`info.format`). These are labels only: datasets stay keyed by path,
  one per folder. Caching a second kind for the same folder would need a schema change (key by
  path and kind), decided when that format arrives.
- **Keep it small:** a shared table for matching, counting and sizing. No general loader
  framework until a second format actually needs loading.
- **Not now:** measuring raw sizes (an extra stat per raw file on the network volume) and loading
  other formats. Both are on the overview's roadmap.

## Memory (RAM) budget

- **Setting:** steps of 1/128 of total RAM (`psutil.virtual_memory().total`), stored as a step
  count so it still makes sense after a RAM upgrade.
  - Minimum: max(1 GB, 1 step). Maximum: 64 steps (half of RAM).
  - Default: 16 steps (1/8 of RAM). Examples: 16 GB on 128 GB (Tony's Mac), 2 GB on a
    16 GB lab PC, 1 GB on 8 GB.
  - Shown as e.g. "16.0 GB (1/8 of 128 GB)". Typed values snap to the nearest step.
- **What it decides:** replaces `FolderCache.MAX_DATA_BYTES` (512 MiB before S7).
  - After every load, datasets not shown by any tab are dropped from RAM, least recently used
    first, until the total fits.
  - Datasets shown in a tab are never dropped, even over budget.
  - So the folder you just loaded stays; older unshown ones go first.
  - Lowering the setting applies at once and says what was dropped.
  - It bounds **retained** datasets, not HeLab's total memory: data shown in tabs and a load's
    peak can exceed it.
- The Cache tab's "This session" line shows: loaded data N folders · X of Y GB, and how much of
  it is pinned by open tabs.

## Large-folder warning

- **Estimate before reading: the TXY files' total size on disk, unscaled.**
  - On 2026-10-10, Tony's 19 cached folders measured 0.67–0.70× that size in RAM: a TXY row is
    about 35 bytes of text, but 24 bytes as three float64. Tony chose the unscaled size because
    overestimating is the safe side and needs no calibration.
  - **The one-stat fast path stays.** When a tab holds the cached dataset and the folder isn't
    modified since the cache's file list, the load answers `unchanged` from one folder stat,
    without listing (`_unchanged_since_cache`). Its size comes from the dataset record's saved
    file sizes, and nothing new is read. It must not be replaced by a full scan.
  - **Every load that lists the folder starts with a basic scan.** Today's load already lists the folder and stats
    every TXY file (its fingerprint), then sends and saves that as the folder's summary
    (`scan_summary`) before reading anything. That phase is a full basic scan. It records
    `files.txy.bytes`, and the large-folder check runs on it right there, before the first file
    is read. Running a separate scan helper first would list and stat the folder twice, which
    is slow on the network volume, so the load's own scan phase is used.
  - A saved summary (from an earlier scan or load) lets HeLab decide **before** submitting the
    load, so an automatic load of a known-large folder doesn't even start a helper. A folder
    that has only been listed (names only) has no size yet; its load stops after the scan phase
    instead.
  - **Cached data goes through the same guard.** Cache first unpacks a folder's dataset into
    RAM (`cached`) before any source scan, so a large folder loaded deliberately once (and
    cached) would otherwise open automatically later without a warning.
    - The guard therefore runs before every `cached` read too, using the dataset record's TXY
      size (unscaled, as decided). The record's `ram_bytes` is shown alongside.
    - Listings send each subfolder's dataset size with its cache flags, so the decision is
      made in memory before anything is submitted.
    - The `cached` helper checks again before decompressing and stops with `too_large` unless
      the request carries `allow_large`.
    - Accepting once never makes later automatic loads skip the check.
- **Thresholds**, applied to that estimate:
  - **Refuse** above 30% of total RAM. No override; this replaces the fixed 1 GiB input limit.
  - **Warn** above the RAM budget, or above 10% of total RAM.
  - The peak during a load is higher than the final size: the helper also holds the shots and
    compresses them for the cache. So the dialog says "may briefly use about 2–3× this".
    Reducing that peak is a separate idea (the helper could compress the saved `.npy` artifacts
    instead of holding a copy).
- **Automatic loads** (auto-load on select, the load queue, anything that isn't a deliberate
  "Load data") are what this guards against:
  - They never open a dialog and **never start**. If the helper would need confirmation, it
    stops before reading with a `too_large` event.
  - The summary line and Folder details show `Large folder · ~2.1 GB in RAM · Load anyway…` in
    amber, like the freshness warnings, and the status bar shows it too.
  - In queue mode the folder is skipped and the queue moves to the next one, so one big folder
    can't stall it.
- **Deliberate loads** (right-click › Load data, Retry, "Load anyway…") still confirm, because
  right-clicking the wrong folder is an accident too:
  1. A dialog shows the estimate, the budget and total RAM.
  2. Ticking "I understand this may slow down or stop HeLab" enables **Load anyway**.
  3. The load is resubmitted with `allow_large`.
- **Above 30% of RAM** every load is refused, deliberate or not.
- The warning offers **Don't auto-load this folder** as well, so a known-huge folder stops
  coming up (see [Folder flags](#folder-flags)).

## Cache folder move

- **General tab:** the cache folder is shown read-only, with a **Change…** button that opens a
  folder picker.
- **The target must be:**
  - writable (probe file)
  - empty or new, and not inside the current cache
  - on a disk with enough free space for the current size
- **Refuse** network folders (`statfs` type smbfs/afpfs/nfs/webdav/cifs; UNC paths or remote
  drives on Windows). SQLite's WAL mode doesn't work on network filesystems
  (<https://www.sqlite.org/wal.html>).
- **Refuse** synced folders too (iCloud `Mobile Documents`, OneDrive, Dropbox, Google Drive):
  their clients can move files to the cloud or create conflicts under the database.
- **The same check runs at startup** on the saved cache path (a path set before this rule, or a
  volume that has changed). If it fails, HeLab uses the default folder for this session and
  says why. The saved setting is left for the user to change.
- **Confirm:** "HeLab pauses loading and folder checks while it moves the cache (706 MB) to X."
- **The move runs while HeLab stays open:**
  1. **Pause.** `IOService` stops starting work that uses the cache. Running jobs are cancelled
     or finish, and HeLab waits until every helper's exit is confirmed (the existing slot rule).
     Browsing memory, plots and loaded data stay usable.
  2. **Move**, with a progress window. On the same disk it's an instant rename. On another
     disk, in this order:
     1. **Checkpoint**, with every helper stopped: `PRAGMA wal_checkpoint(TRUNCATE)` on the
        source, so `records.sqlite` holds all committed state and no `-wal` file is needed
     2. copy
     3. **verify the copy as a store, not just as files**:
        - open the destination read-only
        - `PRAGMA integrity_check` returns `ok`
        - same `store_id` and layout
        - every `datasets` and `pending_saves` row's file exists, with the recorded bytes
     4. update `dir_caches`
     5. delete the old folder
     - **Cancel** works until the copy is verified (deletes the partial copy, resumes on the
       source). From "Switching to the new folder…" (`verified` recorded) the button is
       disabled: the switch finishes or is recovered at the next start. A rename has no
       cancel point; it's instant.
  3. **Success:** switch to the new folder in place and resume. No restart. Every cache path is
     read through one function (`cache_dir()`), not the import-time `DIR_CACHES` constant.
  4. **Failure or Cancel.** What happens depends on whether the **cutover** (the setting
     pointing at the destination, saved) has happened:
     - **Before cutover** (no space, not writable, copy or verification error, Cancel): discard
       the copy, keep the setting, and resume on the intact source.
     - **After cutover** (e.g. deleting the old folder fails halfway): never roll back. Keep the
       destination and its setting, resume on it, report the leftover source files, and let
       recovery finish deleting them at the next start (the move record stays until then).
     - **Cutover rule:** write `dir_caches`, call `QSettings.sync()`, and check
       `QSettings.status() == NoError` **before** recording `setting_updated`. If that fails,
       it is still "before cutover". Deleting the source, and later deleting the move record,
       each happen only after the previous step is recorded.
     - **Rename, then the settings write fails.** After a same-disk rename, the source path no
       longer exists, so "resume on the source" needs the rename undone first:
       1. Rename the destination back to the source path, and confirm the setting still names
          the source.
       2. If renaming back fails, keep the destination and the move record. HeLab resumes on
          the store that exists (the destination), for this session only, and startup recovery
          repairs the setting ("valid at `to` only" → setting = `to`).
       3. Never delete the only complete store.
     - A dialog gives the reason in plain words, e.g. "Not enough space on 'Backup': needs
       706 MB, 210 MB free".
     - It has **Show in Finder** (Windows: **Show in Explorer**) buttons for each folder that
       needs manual attention: a partial copy that couldn't be removed, an old cache that
       couldn't be deleted after the switch (marked "safe to delete"), or the target, to check
       its space or permissions.
     - Folders are opened with `QDesktopServices.openUrl`.
- **Why that order:** updating the setting only after the old folder is deleted would leave the
  setting pointing at a deleted folder if HeLab crashed in between.
- **Move record, for crash recovery (rename and copy alike).**
  - Before touching anything, HeLab writes `cache-move.json` with `from`, `to`, `method`
    (`rename`/`copy`) and `step`. It sits in the per-user app folder (`default_app_dir`),
    outside both caches, and is written atomically: temp file, fsync, rename.
  - The record also holds the store's `store_id` (a UUID in `meta`), and is updated after each
    step:
    - rename: `started` → `renamed` → `setting_updated`
    - copy: `started` → `copied` → `verified` → `setting_updated` → `old_deleted`
  - A crash can come between any operation and its record update. So recovery **checks the
    folders themselves** and uses the step only where the folders can't tell. "Valid at X"
    means X holds a `records.sqlite` with this `store_id` and the expected layout.
  - Every recovery action is idempotent (setting a value, deleting a folder), so a crash
    during recovery is recovered the same way at the next start.
  - At startup, **before any cache is opened**, a leftover record is resolved:

    | Method | Last step recorded | Valid at | Recovery |
    |---|---|---|---|
    | rename | any | `from` only | Nothing moved: setting = `from`. |
    | rename | any | `to` only | Rename done (recorded or not): setting = `to`. |
    | rename | any | neither | Can't happen with an atomic rename. Treat as lost: new empty store at the setting, tell the user, keep the record for the log. |
    | copy | `started`, `copied` | `from` (and maybe `to`) | The copy is unverified: delete `to`, setting = `from`. A copy that finished but wasn't recorded is redone next time; safe, only slower. |
    | copy | `verified` | both | setting = `to`, then record `setting_updated`, then delete `from`. |
    | copy | `setting_updated` | `to` (and maybe a partly deleted `from`) | Finish deleting `from`. Never roll back to it. |
    | copy | `old_deleted` | `to` | Nothing left but deleting the record. |
    | copy | `verified` or later | `to` invalid | Shouldn't happen (`to` was checked). If `from` is still valid, setting = `from`; otherwise a new empty store. Tell the user either way. |

  - Deleting `from` starts only after `setting_updated` is recorded, so a partly deleted `from`
    is never the setting's target.
  - The record is deleted when its recovery finishes, and the user is told what was repaired.
  - Tests: inject a crash before and after each **meaningful transition**, for both methods:
    move-record writes, the rename, copy completion, verification, the settings write
    (`sync()`), and source cleanup. Add a representative partial copy and a partial source
    deletion. Not one case per copied file. Every case ends with one valid store and the setting
    pointing at it.
- **Other instances, without a race.** Two lock kinds, both in the per-user app folder
  (`default_app_dir`), outside every cache folder:
  - `cache.lock`: one `QLockFile`, held **exclusively** by a move from its check to its
    cutover, and by every HeLab **during startup** while it resolves a move record and
    registers itself.
  - `instances/<pid>.lock`: held by each running HeLab for its whole life.
  - **Startup:**
    1. Take `cache.lock`. If a move holds it, show "Another HeLab is moving the cache…" and
       wait.
    2. Resolve any move record.
    3. Register `instances/<pid>.lock`.
    4. Release `cache.lock`.
    5. Open the cache.
  - **Move:**
    1. Take `cache.lock`.
    2. Refuse if any other live instance lock exists.
    3. Move.
    4. Release `cache.lock`.

    An instance that starts during a move waits at step 1 of its startup, so it can't open the
    cache mid-move.
  - Ordinary use by two instances is fine: SQLite WAL handles it.
- **Temp folder:** a change takes effect on the next start; nothing is moved.

## Settings → Cache tab

```
Disk cache   ~/Library/Caches/HeLab/caches            [Open]   (Change… is on General)
  706 MB of 8.0 GB budget  [████░░░░░░░░░░]   Budget [  8.0 ] GB
  Cached data        19 folders · 667 MB · last used 2h ago          [Clear…]
  Folder summaries   445 folders                                     [Clear…]
  Scan failures      3 folders skip automatic checks                 [Forget…]
  Subfolder status   33 folders                                      [Clear…]
  Checked 10:42                                         [Refresh] [Clear all…]
Folder preferences   2 folders not cached · 1 folder not auto-loaded  [Clear…]   (not in Clear all)
Remove old entries
  Cached data not used in the last    [ 90 ] days — frees ~420 MB (7 folders)     [Remove…]
  Folder records not checked in the last [ 90 ] days — 120 folders (~0.1 MB)      [Remove…]
    ☐ Include scan failures (automatic checks will try those folders again)
Memory
  RAM budget [ 16.0 GB (1/8 of 128 GB) ▾▴ ]   In use: 3 folders · 2.1 GB (1.4 GB shown in tabs)
```

- **Purges:**
  - Day boxes default to 90 and accept any number of days (1–3650). The estimate updates as
    you type and comes from the last `inventory`.
  - Cached data uses each dataset's `last_used`.
  - Folder records (summaries, subfolder status, and scan failures only if ticked) use
    `saved_at`, i.e. when HeLab last checked that folder. Records have no last-used date: a
    listing shows hundreds at once, and recording each would be a write per row.
  - Removing cached data never touches TXY files; the next load re-reads the source.
- **Disk budget:** GB, default 8, minimum 1, steps of 0.5.
  - It counts **live** data: dataset files that rows point to, plus `records.sqlite` (a
    fraction of a MB).
  - Retired files waiting out their grace period don't count. The tab shows them separately
    ("freeing 1.2 GB").
  - So for up to 10 minutes, disk use can exceed the budget by what was just removed. Saves
    also check the **disk's actual free space**; a full disk is reported as an error, not as
    "over budget". Lowering it below current use asks first ("Removes cached data for 4
  folders (1.2 GB), least recently used first").
- **Where the numbers come from:** the `cache_admin inventory` helper job. The tab shows
  `Checking…` until it arrives. Memory numbers come from `FolderCache`. The GUI never opens the
  store.
- **Confirmations:** every Clear/Remove says what is lost and what stays. Examples: "Loaded
  data stays open"; "Automatic checks will try these folders again".
- **While a job runs:** buttons are disabled. Tooltips hold the exact dates.
- **Layout:** single-line rows, no vertical padding. Fixed parameters go in a tooltip.
- **Removed:** the parameter form, "Force Save", hits/misses, internal cache names.
- **Reset** becomes "Reset all settings…" with a confirmation, since it clears every HeLab
  setting.

## Cache maintenance (`cache_admin` helper operation, local lane)

| Action | Does |
|---|---|
| `inventory` | Counts and bytes per kind, blocked folders, budget, the `last_used` histogram for the purge estimate, orphan files, layout version |
| `clear` (`kinds`) | Removes everything of those kinds and bumps each kind's generation (see [Removals](#removals)); Clear all bumps all four. |
| `purge` (`kind`, `older_than`, `include_failures`) | Datasets by `last_used`, or folder records by `saved_at`; returns what was freed |
| `trim` (`budget`) | Removes least recently used datasets until under the budget. **Only on the user's request**: lowering the budget, or "Make room" in the full-cache dialog. Never automatic. |
| `adopt` (`pending_id`, `make_room`) | Validates a pending save (save guard, fit rule on current usage). With `make_room`, removes least recently used **other** datasets until it fits. Then adopts it, all in one transaction (see [When the disk cache fills up](#when-the-disk-cache-fills-up)) |
| `discard` (`pending_id`) | Drops a pending save |
| `sweep` | Deletes retired files past their grace period, pending saves over an hour old and orphan files over an hour old. Returns the next deadline (the earliest retired-file or pending-save expiry). |

**Sweep scheduling.** The sweep runs at startup, then **by deadline**, not just once:
- Every `removed`, `cache_full`, `cache_approval` and `adopt`/`discard` result, and every sweep result, carries the
  store's next cleanup deadline.
- `FolderCache` keeps one single-shot timer for the earliest deadline and submits a `sweep` on
  the local lane when it fires.
- A sweep that finds a file still open (Windows) returns a deadline one minute later.

So retired files are gone within the grace period plus a minute, and expired pending saves
within their hour, without a restart.

### Removals

**Every** removal goes through one store function: Clear, both purges, trim, "Make room",
lowering the budget, a folder's "Don't cache", and the per-folder "Clear loaded data cache".
In **one transaction** it:
1. deletes the rows
2. by path (purges, trim, Make room, don't-cache, per-folder clear): bumps each affected
   folder's `folder_epochs` row, creating it if missing; by kind (Clear, Clear all): bumps that
   kind's generation
3. moves dataset files to `retired_files`
4. returns the affected paths and kinds

**Save guard.** Every helper that may write reads, when its job **starts** (load, scan,
details, subtree save, scan history, flag saves), up to three values, and its write
transaction checks they are unchanged:

| Value | Catches |
|---|---|
| the generation of each kind it writes | A Clear or Clear all of that kind, **including a folder's first save still in flight** (no row yet, so no epoch bump would reach it) |
| the folder's `folder_epochs` value (0 if no row) | A removal of this folder: purge, trim, Make room, don't-cache, per-folder clear. Rows are never deleted, so a later removal always changes the value. |
| datasets only: the job's `job_seq` | A **newer** job for the same folder (another load, another HeLab instance). The write (or a pending save's adoption) succeeds only if its `job_seq` is greater than the stored dataset row's. Superseding a pending save compares `job_seq` too. A UUID identifies a save; only `job_seq` orders them. |

A failed check discards the write ("Cache was cleared before saving completed" or "Newer data
is already cached"), so nothing removed comes back and nothing newer is overwritten.

The helper sends `removed` (paths, kinds). `FolderCache.removed(paths, kinds)` resets exactly
those entries in memory:
- `_disk_cached_paths`, cache states and the `disk_cached` flag of datasets still in RAM (which
  stay loaded)
- snapshot summaries, histories and subtrees, as applicable
- for a Clear by kind, every path of that kind (the event says "all")

Models then re-render, so no badge says "Cached data found" for data that is gone.

Tests: each removal kind runs while a save, a load and a scan of an affected folder are in
progress; afterwards nothing removed comes back and no badge is stale.

### When the disk cache fills up

Records are never removed to make room: they're tiny, and losing scan failures would re-enable
automatic scans of bad folders. **Nothing is removed automatically.** There are two thresholds.

**80% of the budget: automatic loads of uncached folders pause.**
- Selecting a folder with **no cached data** doesn't load it. Its row, summary line and Folder
  details show `Auto-load paused — disk cache 80% full · Load data`. Deliberate loads still work.
- Folders **with cached data** still open from the cache and are checked as usual. If the check
  finds changes that would grow the cache, HeLab asks before saving the update:
  - "X changed: save the update to the disk cache (+120 MB, 6.6 of 8 GB)?"
  - Buttons: **Save update** and **Don't cache this update now**.
  - Either way, the updated data stays in RAM.
  - Storage: the same pending-save protocol as below. The helper publishes the file and
    inserts a `pending_saves` row with reason `needs_approval` (when usage is at or over 80% and
    the save grows the cache), sends `cache_approval` with its `pending_id`, and exits.
  - **Save update** runs `cache_admin adopt(pending_id)`. It rechecks the save guard and the
    fit rule against the **current** usage. If the save no longer fits, the pending save
    becomes `over_budget` and the Make room dialog below takes over.
- **When usage crosses 80%,** a dialog: "Disk cache is 80% full (6.4 of 8 GB). Automatic loading
  of new folders is paused until you free space."
  - **Open purge settings:** opens the Cache tab at "Remove old entries".
  - **Ignore this time:** auto-loading continues for this session. HeLab asks again on the next
    launch, or when usage rises another 10% of the budget.
- **Resuming:** once usage is below 80% (after a purge, a clear or a bigger budget), automatic
  loading resumes by itself. The status bar says so once.
- The View menu's auto-load toggle is not changed. The pause is separate, and its reason is in
  the tooltips.

**A save that would go over 100%:**
- The load still completes and its data is in RAM; only the cache save waits.
- The helper has already compressed the data and published it under its **final** name
  (`tmp-<id>` → fsync → `<id>.blosc`, unreferenced so far) when it checks the budget in the save
  transaction, so the size is exact.
- **Fit rule** (here and in `make_room`): live total − this folder's current dataset bytes (if
  it has one, since it is being replaced) + the new file's bytes ≤ budget.
- If it doesn't fit:
  - the same transaction inserts a `pending_saves` row (reason `over_budget`): a new
    `pending_id`, path, the final file name, bytes, the dataset row's JSON, and the save-guard
    values read when the job started
  - the helper sends `cache_full` (`pending_id`, needed, free) and exits; nothing waits, no
    slot is held
  - pending bytes don't count toward the budget
- A crash before that row is committed leaves an unreferenced `<id>.blosc`, which the sweep
  removes after an hour. Adoption later only changes database rows; no file is renamed then.
- HeLab asks in a dialog: "Not enough room in the disk cache for X (420 MB, 7.9 of 8 GB used)".
  - **Make room:** one `cache_admin adopt(pending_id, make_room=True)` job, in one transaction.
    The dialog holds the `pending_id`, so the answer applies to exactly the save it describes.
    1. **Validate first.** If that `pending_id` is gone (replaced by a newer pending save, or
       expired), or its save-guard values no longer match (the folder was cleared, or a newer
       dataset was saved: a higher `job_seq` is stored), discard it (row deleted, file retired), remove
       nothing else, and tell the user why.
    2. **Trim others.** Remove the least recently used datasets, **never this folder's own**,
       until the fit rule holds. This is a normal removal: rows deleted, their epochs bumped,
       files retired.
    3. **Adopt.** Replace this folder's dataset row with the pending record. Its previous file,
       if any, is retired, as in any replacement, and its epoch is **not** bumped. Then delete
       the `pending_saves` row.

    The space counts as available as soon as the transaction commits; retired files free the
    disk itself after the grace period. The dialog says what Make room removes, e.g. "cached
    data for 4 folders (1.2 GB) not used since 3 Aug", computed with the fit rule.
  - **Don't cache this folder now:** `cache_admin discard(pending_id)` deletes that pending
    row and retires its file, if they still exist.
- Pending saves not resolved within an hour (or left by a quit) are deleted by the sweep, by
  deadline or at the next startup.
- If the folder alone is bigger than the whole budget, only "Don't cache this folder now" is
  offered, with a hint to raise the budget.
- Only one cache dialog is open at a time. Other folders that need one meanwhile show
  `Not cached — disk cache full` in the summary's cache line and Folder details.

## Folder flags

Set from the row's right-click menu: **Don't cache this folder** and **Don't auto-load this
folder** (checkable). They apply to that folder only, never to its parent or subfolders.

- **Storage:** stored in `folder_prefs` by a local-lane helper. Listings send each subfolder's
  flags with its saved summary, so the GUI has them in memory before the row is clicked.
- **Display:** a small badge on the row, and a tooltip line ("Not cached: your choice", "Not
  auto-loaded: your choice").
- **Don't auto-load:** selecting the folder loads nothing, cached or not. The summary line shows
  `Auto-load off for this folder · Load data`. Deliberate loads work as usual.
- **Don't cache:**
  - Loads read the folder into RAM but never save it to disk, and cache first doesn't apply.
  - Ticking it offers to remove the folder's existing cached data, e.g. "Remove its cached data
    (420 MB)?".
- **Never removed automatically.** Purges and "Clear all" leave the flags alone; the Cache tab's
  "Folder preferences" row clears them.

## Old browser removal

The current browser (`SnapshotFileSystemModel` + helpers) replaced `HelabFileSystemModel` in
v0.0.5a. The audit ([notes](../.ai/sessions/2026-10-10-claude-cache-audit/notes.md#old-browser-assessment))
found it removable with low to medium risk. The only visible change is one Debug menu item.

**Remove:**
- the browser: `HelabFileSystemModel`, `StatusTreeView`, `StatusIconDelegate`
- the workers: `StatusWorker`, `StatusDeepWorker`, `StatusRescanWorker`, `DirectoryCheckWorker`,
  `LoadFolderToRamWorker`, `HelabFSModelThrottleDataChangedEmit`
- `os_cached.py` and `threading_setup.py` (its pools and worker registries are used only by the
  old code)
- from `caching_setup.py`: `status_cache`, `os_file_system_cache` and their settings
- **Not in S3:** `caching_setup.py` keeps `data_ram_cache` and `load_cache_param`.
  `SnapshotFileSystemModel` and `FolderExplorer.clear_data_cache` build their helper cache
  options from it until S5, and `SettingsDialog` imports it until S7. S5 replaces the options
  with `cache_store` and deletes the file. Until S7, the old Cache tab shows only
  `data_ram_cache` (one row, Clear still blocking as today).
- Debug → "Clear Status Cache"
- tests: `test_helabFileSystemModel`, `test_statusworker_ut`, `test_statusDeppWorker`,
  `test_directoryCheckWorker`, `test_cachingSetup`, plus two `.disabled` files

**Keep, after untangling:**
- `StatusReport`: the current browser uses it as its data type (`FolderNode.report`), but its
  module imports `caching_setup`, `threading_setup`, `os_cached` and both workers. Importing it
  pulls in the whole old stack. Keep a plain class (fields, status constants, icon helpers) and
  delete the cache/worker methods.
- `fnum` → a small formatting module (Folder details, Settings and the main window use it).
- `FolderTabWidget`: replace the `HelabFileSystemModel.COLUMN_*` constants and
  `clear_status_cache`.
- `HelabMainWindow`:
  - drop the star imports of `caching_setup`, `os_cached` and `threading_setup`
  - simplify `closeEvent`, which waits for the old thread pools and calls `close_all_caches`
  - drop the dead `_setup_middle_area_deprecated`
- `main.py`: drop the cache import and `cache_status_string()` at startup.
- `tests/conftest.py`: drop `cancel_all_workers`. `test_gui_responsiveness` monkeypatches
  `status_cache`; rewrite it to forbid store access instead.
- `helab/scripts/dev/` (prototypes of plotting libraries that read the old cache directly): move
  to `dev/plotting-prototypes/` as unmaintained reference, not loaded by the app.
- Docs: AGENTS.md's Threading, Caching and "earlier `HelabFileSystemModel`" paragraphs.

## Saved analysis results (result caching R2, 2026-10-23)

The result cache's own rules are in [result caching](result-caching.md); what it adds here:

- **Store layout:** `results` (one row per folder `root://` key and exact lookup key, a new
  `result_id` every save, `last_used`), `pending_results` (results waiting for Make room or
  Discard) and `gen_results` in `meta`; data in `results/<uuid>.npz` (NumPy arrays and a JSON
  tree, never a pickle). Older `store-v3` stores gain them on a writable open (`_migrate`).
- **Settings → Cache:** a Cached analysis row (count, size, Clear…, purge by `last_used`) and
  **Reuse saved analysis results** (`result_reuse`, on by default). Clear all leaves results.
- **Settings → Data roots:** Clear cached analysis… per root (button and menu), beside Clear
  cached data…, which leaves results.
- **Budget:** results count toward the one disk budget; one that doesn't fit asks Make room
  (least recently shown other results, never datasets) or Discard.
- **Store identity:** presets and saved results follow one rule, `FolderCache.store_answer`: the
  cache folder decides which store is in use, answers from another store wait for an identity
  probe, and writes name their store ([AGENTS.md › Caching](../AGENTS.md)).

## Sessions

Each row is one agent session ending in one or two commits (ask Tony first). Start a session by
reading this plan, the audit notes and AGENTS.md. End it by ticking the row with the commit hash.

| # | Session | Scope | Tests | Depends on | Status |
|---|---|---|---|---|---|
| S1 | Quick storage fixes | `statistics` off. Decide `blocked` inside `begin_scan`'s transaction. `save_subtrees`/`_save_summary` report failed saves. Reads that decide behaviour use `retry=True`. (Protects the current store until S5.) | Held write lock does not unblock an automatic scan; failed subtree save is reported | — | ☑ 2026-10-10 `fe5a5b7` |
| S2 | Untangle the old browser | Plain `StatusReport`; move `fnum` and the column constants; new `closeEvent`; `main.py` and `conftest` no longer import old modules | Full suite; import test: loading `HelabMainWindow` imports none of the old modules | — | ☑ 2026-10-10 `24493cc` |
| S3 | Delete the old browser | Delete the modules, tests and Debug item; strip the two old caches from `caching_setup.py` (the file stays until S5); old Cache tab shows only `data_ram_cache`; move `helab/scripts/dev/`; update AGENTS.md | Full suite; the app starts and Settings opens | S2 | ☑ 2026-10-10 `f36916a` |
| S4 | New store module | `helab/utils/cache_store.py`: schema, versioning, dataset file writes, `retired_files` with deferred deletion, reader re-read on a missing file, the single removal function with durable `folder_epochs`, per-kind generations, per-folder `job_seq` ordering, `pending_saves` with `pending_id` and `reason`, read results (found/missing/error), save-guard checks | Two processes writing at once; killed writer; reader racing a replacement; removal racing a save; Clear by kind before a folder's first row exists; an older job's save or pending save never overwrites or supersedes a newer one, including the older job finishing last with neither adopted; newer `layout_version` opens read-only; error is not "missing" | — (parallel to S2/S3) | ☑ 2026-10-10 `7040a29` |
| S5 | Switch to the new store | Helpers (`list`, `details`, `scan`, `load`, `cached`, `invalidate`, `subtree_save`, `scan_history`) use `cache_store`; one `FILE_KINDS` table drives matching and counting; summaries save `files` (TXY sized) and datasets `ram_bytes`; `last_used` on use; old cache folders deleted at startup; `caching_setup.py` and diskcache removed (the old Cache tab reads nothing until S7, so S5 shows "Rebuilt in a later update" there); network/synced cache path refused at startup | Existing cache-first, folder-cache and scan-history tests pass on the new store; the app starts and Settings opens | S1, S3, S4 | ☑ 2026-10-10 `fd4e020` |
| S6 | Cache maintenance | `cache_admin` (inventory, clear, both purges, trim, adopt, discard, sweep); pending saves on `cache_full` and `cache_approval`; `removed` events and `FolderCache.removed()`; budget check in the save transaction, `cache_full` | Every removal kind during a running save, load and scan: nothing comes back, no stale badge; retired files and expired pending saves go by deadline without a restart; Make room or Save update with a stale or superseded `pending_id` removes nothing; Save update re-checks the current budget and turns into Make room when over; never evicts the target's own dataset, and uses the fit rule; a crash before or after the pending row commits leaves no dangling reference; purge estimates equal what is freed; records survive trimming; an over-budget save becomes a pending save, never auto-trimmed; Make room adopts it, or discards it if the folder was cleared meanwhile; retired bytes don't count toward the budget | S5 | ☑ 2026-10-10 `ef4c0ca` |
| S7 | Budgets and the Cache tab | Rebuilt tab with both purges; disk budget (default 8 GB); RAM budget (1/128 steps, default 1/8) replacing `MAX_DATA_BYTES`; 80% pause of uncached automatic loads with its dialog; update-save prompt over 80%; full-cache dialog (Make room / Don't cache now); "Reset all settings…" | pytest-qt tests with a fake inventory; 80% dialog once per crossing, Ignore lasts the session; cached folders still open over 80%; one cache dialog at a time; RAM eviction keeps shown datasets | S6 | ☑ 2026-10-10 `52201ca` |
| S8 | Large-folder warning | Uses S7's RAM budget setting. Unscaled TXY-size estimate (the one-stat fast path keeps using the record's sizes); guard before both `load` and `cached`; `too_large` stop and `allow_large`; amber inline "Load anyway…"; queue skips; dialog for deliberate loads; the 30% refusal replaces the 1 GiB limit | Automatic loads never start or open a dialog; a large **cached** folder doesn't open automatically even after an earlier deliberate load; deliberate ones confirm; refusal; estimate from a saved summary vs from the load's own listing; the unchanged fast path still answers from one stat | S7 | ☑ 2026-10-11 `34f59c6` |
| S9 | Cache folder move | Change… flow and checks (network/synced refused), I/O pause until helpers exit, `cache.lock` and instance locks in the app folder, WAL checkpoint and store verification, Cancel until verified, `cache-move.json` record and startup recovery, move with progress and Cancel, `cache_dir()` switch in place, instance locks, failure dialog with Show in Finder/Explorer | Same-disk rename; cross-disk copy; failure and Cancel before cutover keep the source; a failure deleting the source after cutover keeps the destination and finishes at the next start; a settings write that fails `sync()`/`status()` counts as before cutover; a successful rename followed by a failed settings write, with the rename-back succeeding and failing; a simulated crash before and after each meaningful transition (record writes, rename, copy completion, verification, settings write, source cleanup, plus one partial copy and one partial deletion), for rename and copy, recovers to one valid store with the setting pointing at it; refusal with another instance; an instance starting mid-move waits; a corrupt copy fails verification; network target refused | S5 | ☑ 2026-10-11 `9ba2eae` |
| S10 | Folder flags | `folder_prefs` and its helper save; flags in listings; right-click toggles; row badge and tooltip; no-auto-load and no-cache behaviour; offer to remove cached data; "Don't auto-load" in the large-folder warning | Flag survives restart and purges; no-cache load never saves; no-auto-load select starts nothing; flags never inherited | S5. The warning's "Don't auto-load" button is added by whichever of S8 and S10 lands second. | ☑ 2026-10-11 `eafcf4b` |
| S11 | Wrap-up | AGENTS.md, `.ai/memory/results/` decision note, MANUAL_TODO native checks (dialogs, move, large-folder warning, flags), overview ticks | — | all | ☑ 2026-10-11 `8eb45d2` |

S1, S2 and S4 can start in any order. S8 needs S7 (the RAM budget setting). S9 and S10 are
independent of S7, S8 and each other.

Notes from finished sessions:

- **S1:** `FanoutCache.get` returns the default on `sqlite3.OperationalError` even with
  `retry=True`, so a plain read can't tell an error from "nothing saved". S1 therefore
  makes the decisions that matter under the write lock, reading the history through
  `scan_history.read_saved` (the shard's own `get`, which raises). `begin_scan` raises
  `ScanSkipped` for a blocked folder (or, for an automatic scan, a malformed history). A
  scan that is not manual is skipped when the history read fails or the cache can't be
  opened, and `write_outcome` fails rather than overwrite saved failures (both found in
  Codex's review). Display reads still use `FanoutCache.get`. Subtree saves run in one
  transaction and fail the job instead of reporting saved; a failed summary save sends
  `summary_save_failed`, which `FolderCache` logs. S4's readers must return found / missing /
  error themselves rather than rely on diskcache.
- **S2:** `StatusReport` is now plain data. The old browser's methods live in a
  `LegacyStatusReport` subclass, which S3 deletes with the rest. `fnum` moved to
  `helab/utils/number_format.py`. Besides `_setup_middle_area_deprecated`, the four dock
  helpers only it called were removed (one imported `helab/scripts/dev/`). `closeEvent` no
  longer waits for the old pools or closes caches. The `conftest` fixture cancels old
  workers only if a test already imported them. `caching_setup` is still imported (via
  `SnapshotFileSystemModel`, `FolderExplorer`, `SettingsDialog`) until S5/S7.
- **S3:** Deleted the old browser's model, tree view, delegate, all of `helab/workers/`,
  `LegacyStatusReport`, `os_cached.py`, `threading_setup.py`, their five tests and two
  `.disabled` files, and Debug → "Clear Status Cache" (with `FolderTabWidget.clear_status_cache`).
  `caching_setup.py` opens only `data_ram_cache`; `cache_status_string` and
  `close_all_caches` went with the old caches. `load_cache_param` stays for the helpers'
  options until S5. `helab/scripts/dev/` is now `dev/plotting-prototypes/` with a README;
  the prototypes no longer run (they import `LoadFolderToRamWorker`). `SynchronisedDict`
  stays: the Dash server uses it. Checked offscreen: the main window and Settings open, and
  the Cache tab shows one row. The old `status_cache/` and `os_file_system_cache/` folders
  stay on disk until S5 deletes them.
- **S4:** `helab/utils/cache_store.py` (`CacheStore`), not yet used by any helper. Reads
  return `Read` (found / missing / error); writes raise `StoreError`, `StoreReadOnly` or
  `SaveRejected` (`cleared`, `newer`, `gone`). A job takes its `SaveGuard` with `guard(paths,
  kinds)`, or `start_dataset_job(path, kinds)` for a load, which also takes the next `job_seq`.
  Datasets: `write_dataset_file` (publish), then `save_dataset` or `add_pending`, and later
  `adopt_pending` / `discard_pending`. Also `remove(kinds, paths=None)`, `sweep(now)`,
  `next_deadline()`, `touch_dataset`, `pack_dataset` / `unpack_dataset`. Choices made here:
  - A removal by path bumps the folder's epoch whatever kinds it removes, so it also stops
    that folder's in-flight dataset save (conservative).
  - `save_records` is all or nothing: one cleared folder rejects the batch. S5 decides
    whether subtree batches save per folder instead.
  - An older job may still save directly while a newer job's pending save waits (nothing newer
    is stored yet); adopting the newer one still replaces it. A newer direct save drops older
    pending saves.
  - A rejected save retires its already-published file at once.
  - The `folder_prefs` table exists but is unused until S10. The budget, fit rule, Make room
    and `inventory` are S6.
  - Codex's review found three bugs, all fixed with tests. A file still open made the sweep
    return a deadline already past. A read-only store still published dataset files. The
    read-only SQLite URI didn't encode the path, so `%`, `?` or `#` in a folder name broke it.
    A second review found three more, also fixed with tests. A repeated save of the same file
    retired the live file. `read_dataset` inside an outer transaction re-read a stale snapshot,
    so it now refuses to run there. A failed file write raised a raw `OSError` and left its
    `tmp-` file; it now raises `StoreError` and removes the file.

- **S5:** Every helper opens `CacheStore` at `store_options()["directory"]` (`DIR_CACHES/store-v2`);
  the GUI only passes that path. `caching_setup.py` and diskcache are gone, and nothing in the app
  imports them (tested). Choices made here:
  - Each job takes its save guard when it starts: `scan`/`details` for summaries and histories,
    `load` with `start_dataset_job` (its `job_seq`), `subtree_save` and `scan_history` at helper
    start. A Clear during a scan discards both its summary and its history write (tested).
  - Listings read each batch of 128 subfolders' records in four queries
    (`read_dataset_infos` added to the store: sizes and `info` without the fingerprint).
  - A load reads only the dataset row when the caller already holds every shot; otherwise it
    reads row and file together. `last_used` is touched when a load reuses the dataset, a
    `cached` read shows it, or the one-stat check confirms it.
  - Display reads turn an unreadable history into "unknown" (None), never empty, so an
    automatic scan stops; `begin_scan` and `write_outcome` read under the write lock and raise.
  - A store written by a newer HeLab is still read (cached shots are reused) but nothing is
    saved, and each load warns. Scans then can't record their start, so automatic scans and
    details skip those folders; manual scans run.
  - Startup cleanup is a `cache_admin` helper (action `sweep`, local lane) that deletes the old
    diskcache folders and runs `CacheStore.sweep()` once per session. Deadline scheduling and the
    other actions are S6.
  - `FILE_KINDS` lives in `helab/utils/file_kinds.py`. Summaries save `files` (raw counted, TXY
    counted and sized); the large-folder estimate (S8) can use `ram_per_byte`.
  - The network/synced check (`helab/utils/cache_location.py`, reused by S9) uses `psutil`
    mount types (smbfs, afpfs, nfs, webdav, cifs…, or Windows `remote`), UNC paths, and known
    sync folders (iCloud `Mobile Documents`, `Library/CloudStorage`, OneDrive, Dropbox, Google
    Drive). A refused folder is replaced by the default for the session, with a warning dialog.
  - The Settings Cache tab shows only the store's folder and "rebuilt in a later update".
  - Codex's review found two bugs, both fixed with tests. Listings and scans turned an
    unreadable summary, subfolder status or dataset row (I/O error or malformed JSON) into
    "not cached", clearing valid badges; such keys are now left out, so the GUI keeps what it
    knew, and a `cache_warning` is sent, recorded in `FolderCache.cache_read_errors` and shown
    in the row and summary tooltips ("Saved results unknown: …"). A load that can't read the
    cache leaves `disk_cached` out of `loaded` too. And a refused cache folder with no safe
    default stayed in use; the disk cache is now off for that session (`DISK_CACHE_ENABLED`,
    `store_options()` empty, cache-only helpers refuse).
    A second review found two more, also fixed with tests. A store that failed to open still
    reported folders as not cached; it now sends a `cache_warning` and leaves the flags out
    (a helper with no cache configured still says "not cached"). And a load took its save
    guard after importing NumPy and pandas, so a clear in that window was undone by its save;
    `load` now takes the guard right after opening the store, before anything else (so the
    one-stat check takes a `job_seq` too). A third pass found the same race in `scan`, which
    restored saved results before taking its guard; it now takes it first too (tested). Every
    writing helper now takes its guard right after opening the store.
- **S6:** `CacheStore` gained the budget (`save_dataset(..., budget=)` returns a `SaveResult`:
  saved, or pending with `reason`), `adopt_pending(..., budget=, make_room=)` returning an
  `AdoptResult` (with a `RoomPlan` when it doesn't fit), `room_plan`, `trim`, `purge_datasets`,
  `purge_records`, `inventory`, and the module function `purge_estimate`. The helper runs
  `cache_admin` actions with `params`; `FolderCache` has `cache_admin()`, `removed()`,
  `pending_saves`, the sweep timer and the signals `cacheRemoved`, `pendingSavesChanged` and
  `cacheAdminResult` that S7's tab and dialogs use. Choices made here:
  - The budget is bytes, default 8 GiB (`DISK_BUDGET_SETTING`, read at startup and after
    Settings; S7 adds the control). It travels in `store_options()`.
  - Live usage counts the records database by its pages in use (`page_count × page_size`),
    not the WAL file, whose size changes with checkpoints rather than with the records.
  - `needs_approval` applies only to a folder that already has cached data, when the save
    grows it and live usage is at least 80% before the save. A new folder that fits is saved
    (S7 pauses automatic loads of new folders over 80%).
  - Clearing a folder's data also drops its pending save, and a newer direct save drops older
    ones, so Make room on such a `pending_id` answers "gone" and removes nothing. A pending save
    whose folder had another removal (e.g. a records purge) answers "cleared".
  - Record purges remove each kind by its own `saved_at`; without "Include scan failures",
    histories with failures are kept, and histories without any are purged with the summaries.
    `inventory` returns the raw ages, so `purge_estimate` uses the same comparisons as the purge.
  - In memory, removed datasets stay loaded but lose their cache flag; saved summaries
    (`cached_report` nodes), histories and subfolder statuses are forgotten, and listing
    entries, snapshots and events read before the removal drop those fields.
  - Codex's review found five bugs, all fixed with tests (each fails with its fix reverted).
    A load's late `cache_saved` after a Clear restored the badge; finishing loads now ignore
    cache events when a removal came after they started. A failed scan's follow-up history
    write took a fresh guard after "Forget scan failures" and saved the old failure again; the
    scan helper now sends its guard (`save_guard`) and the app passes it to that write, and
    skips the outcome if histories were removed since. Ordinary replacements didn't schedule
    the sweep; `cache_saved` now carries `next_deadline`. Pending saves were matched by folder,
    so a late answer about an older save cleared a newer one, and expired ones stayed listed;
    they are now matched by `pending_id`, and `swept` lists `expired_ids`. And the budget was
    checked before the row was written, so a large fingerprint could push usage over it; the
    save (and Make room) now writes the row inside a savepoint, measures, and rolls back to a
    pending save if it doesn't fit. Usage counts the database's pages in use, less pending
    saves' records.
  - A deeper second review found six more, all fixed with tests (each fails with its fix
    reverted). Trim now measures after each removal (a dataset's records go with it). The
    Make room preview (`room_plan(pending_id, budget)`) runs the real adoption in a savepoint
    and rolls it back, so it removes exactly what Make room would. Late `scan_history_saved`
    and `adopt` results, and inventories, are ignored for what a removal since their job
    started took away. Saves list the older pending saves they `superseded`, and pending
    events carry `job_seq`, so the shown pending save is always the newest. And a rejected
    save reports the cleanup deadline for the file it retired.
  - A final review found three more, fixed with tests (each fails with its fix reverted).
    `FolderCache` now remembers answered, superseded and expired pending ids and each folder's
    newest save `job_seq` (saves carry it too), so a late `cache_full` can't revive a save the
    store no longer has. An inventory keeps pending changes that events made after it was
    requested. And a sweep the full queue rejected is retried after `SWEEP_RETRY` (5 s), at
    startup too. Then two inventory races: `inventory` lists each pending save's `job_seq`, which
    orders it against late events like one an event added; and an inventory requested before
    the last one applied is ignored, also by `cacheAdminResult` viewers. Last, listings send
    their `save_guard` too, so a failed listing's queued history write can't undo "Forget scan
    failures"; and clearing subfolder status cancels a queued `subtree_save`, whose batch was
    derived before the clear.
- **S7:** Helpers report the store's live usage with their results (`usage`, `usage_seq` on
  `cache_saved`, pending events, `admin_result`, `swept` and the inventory), and pending events
  carry `replaces` (the folder's current dataset bytes) for the update prompt's growth.
  `usage_seq` is `[store_id, writes]`: every write transaction bumps the store's `writes` count
  (`meta`), and a measurement is as new as the count it saw, so a slow inventory that finishes
  after a Clear never brings back the usage before it (clock times could). The inventory's pending
  saves carry `replaces` and, for `over_budget`, the room plan, so a question restored after a
  restart shows the same numbers; questions show `FolderCache.disk_usage`, the newest usage.
  `FolderCache` keeps the newest measurement (`disk_usage`) and decides the 80% pause
  (`auto_load_paused`, `autoLoadPauseChanged`, `diskNearlyFull`, `ignore_disk_nearly_full`,
  `update_auto_load_pause` after a budget change). `CacheDialogs` (`helab/views/CacheDialogs.py`)
  asks one question at a time; the Cache tab is `helab/views/CacheTab.py`. Choices made here:
  - The pause applies to automatic loads only (selection, the queue's dwell, the check after a
    cached read never pauses: its folder has cached data). A folder held in memory isn't paused
    either, since its load is answered from memory. Retry and the summary's **Load** button,
    right-click › Load data and the background queue are deliberate.
  - Ignore keeps loading for the session; dropping below 80% doesn't reset it, but rising another
    10% of the budget above the usage at Ignore asks again. Without Ignore, the dialog comes once
    per crossing. The 80% dialog has no escape button: Esc or closing the window doesn't choose.
  - Questions about held saves come before the 80% warning (the warning waits one event-loop turn,
    since the event that crossed 80% may also hold a save). A question whose save was answered
    elsewhere, superseded or expired closes unanswered. Save update that no longer fits becomes
    the Make room question for the same `pending_id`. Esc on a save question is "not now":
    nothing is removed. While another modal window (e.g. Settings) is open, questions wait.
  - Make room removes exactly the folders its question named (`room_paths` → `adopt_pending(
    expected_room=…)`), or nothing: if the plan changed (a new budget, other data cached), the save
    stays pending with the new plan and is asked again. A question is identified by its kind, room
    plan and the budget in effect, so a changed plan or budget replaces an open question and re-asks
    an answered one. Questions show the budget in effect; after a budget change the main window
    requests an inventory, which brings room plans for the new budget.
  - A Make room / Save update whose job fails is asked again, saying why ("Make room failed: …");
    a failed Don't cache isn't (still "not now": the save waits in the store until it expires), and
    the status bar says so.
  - The Cache tab's buttons are disabled until the inventory arrives and while a job runs; a job
    ends with a fresh inventory. Read-only stores (newer layout) disable every removal. The record
    purge estimate counts rows ("N records", per kind in the tooltip); records have no size.
  - Lowering the disk budget below the last inventory's usage asks first (`trim_estimate`: least
    recently used datasets until usage fits, an upper bound) and then sends `trim`.
  - Every request carries the budget and when the app set it (`budget_set_at`). The store records
    the newest (`meta.budget`, `CacheStore._active_budget`) in every `cache_admin` job, in a
    save's transaction and in Make room / Save update, and uses it over an older request's: a load
    that started before the user lowered the budget saves within the new one.
  - Settings saves a changed disk budget only once the store has it: Save sends a `budget` job (or
    the `trim`, which records the budget in its own transaction, so a failed trim changes nothing),
    waits for it with Save disabled ("Changing the disk budget…"), then writes every setting.
    Declining, a job that can't be queued, or one that fails saves nothing and keeps the dialog open
    at the Cache tab, saying why. While the job runs, the budget field, Save and Reset are disabled,
    and Save writes only the budget the store acknowledged. Closing Settings while the job runs sets
    the saved budget again (so it is newer than the change) and `FolderCache.sync_budget` sends it
    until a job has recorded it, retrying when the queue is full or the job fails. Budgets are
    saved with Save, like the other settings. Save compares the field with the budget in effect
    (`store_options()`), not the saved setting: "Reset all settings…" saves the defaults at once,
    so Save after Reset still sends the default budget, and Reset then Cancel has the main window
    set it and `sync_budget` it.
  - The tab's inventory may be old. Lowering the budget without a trim sends `budget` with `fit`:
    the helper records it only if the data cached by then fits (`CacheStore.lower_budget`, in one
    transaction). Otherwise it records nothing, and the tab asks with the current usage ("now uses
    …") and sends the trim; declining saves nothing.
  - A budget or trim job that fails may already have committed: the tab then sets the budget in
    effect again and sends it until recorded (`FolderCache.restore_budget`), as Cancel does.
  - At startup, after the sweep, an inventory restores saves still waiting from an earlier session
    (otherwise they would expire unasked) and the usage for the 80% pause; it is retried if the
    queue is full.
  - Sizes are binary units shown as "GB" (the budget's 8 GB is 8 GiB), as the status bar already did.
  - The RAM budget is saved as steps (`ram_budget_steps`) and counts every dataset held in RAM
    once, including ones only a tab still shows (e.g. invalidated); lowering it drops unshown datasets at
    once and the status bar says what was dropped. The main status bar shows one-time notices
    (`show_status_notice`), e.g. "Disk cache below 80% — automatic loading resumed".
  - "Folder preferences" in the tab waits for S10, which adds `folder_prefs`.
- **S8:** `helab/utils/large_folder.py` holds the thresholds (`limits`: warn above min(RAM budget,
  10% of RAM), refuse above 30%), the `verdict` and the `estimate` (a fingerprint's sizes, unscaled,
  without shots already held). Every `load` and `cached` request carries `limits`, `deliberate` and `allow_large`
  (`FolderExplorer._large_payload`). Choices made here:
  - The helper's load checks right after its scan phase, which is sent and now saved first, and
    counts only shots the tab doesn't already hold, so the check of data in RAM (and the one-stat
    fast path) is never stopped. `read_cached` checks the record's TXY size before reading the
    dataset, and again on the dataset it read (it may have been replaced meanwhile). Both stop
    with `too_large` (`estimate`, `refused`); the 1 GiB input limit is gone. A load whose cached
    dataset is larger than allowed (the folder shrank) doesn't unpack it and reads the files
    instead ("Cached dataset too large to reuse").
  - Dataset records save `txy_bytes` and `ram_bytes` in `info`; listings send them with each
    subfolder's `cache_info` (summed from the fingerprint for records saved before S8). The tab
    decides in memory before anything is submitted: a load by the folder's own size
    (`FolderCache.large_estimate`, the newest saved summary), a cached read by the dataset's
    (`cached_estimate`). A cached dataset too large to read whole isn't read; the load then
    decides by the folder's size and reads the files, so an old, larger cache never blocks a
    folder that is small now.
  - `FolderExplorer._large_blocked` runs before both the cached read and the load. A helper's
    stop (`_large_stops`) is the newest word on a folder until it is measured again (a scan
    or a cached save after it) or the folder's data in RAM changes (a stop counts what a load
    would add to what was held then), so a fresh, smaller size replaces an earlier refusal and
    an approved cached read's follow-up check runs. For data
    already in RAM only such a stop counts (what a load would add), so a deliberate update that
    its helper found large is asked about rather than retried. A deliberate load (Retry,
    "Load anyway…", right-click › Load data) asks with `LargeFolderDialog` (tick box enables Load
    anyway). The yes covers only the request that call submits (`_allowing`, reset when the call
    returns), and whether a request was asked for travels with it (`deliberate` and
    `allow_large` in its payload), so neither outlives it: later automatic loads are checked
    again and never ask. A deliberate load whose size only its helper found is asked about
    after the helper stops (dropped if Cancel comes first: `_cancel_count`); an automatic one (including queue mode's background
    loads) just stops, shows the warning and lets the queue move on.
  - The warning: summary line `… · Large folder · ~2.1 GB in RAM` in amber with a **Load anyway…**
    button, Folder details' state row (amber), the status bar, the central hint and the row
    tooltip. Refused: `Too large to load · ~X in RAM, over 30% of RAM`, with no button. When
    earlier data stays shown, the summary line adds the warning after it and Folder details says
    "… · Update not loaded: Large folder · …".
  - "Don't auto-load this folder" in the warning waits for S10's folder flags.

- **S9:** `helab/utils/cache_move.py` (record, checks, rename/copy/verify, cutover, cleanup,
  abort, `recover`), `helab/utils/cache_locks.py` (`FileLock`: OS file locks, `flock` /
  `msvcrt.locking`, released by the OS when their process ends, so a crash never leaves one
  stuck and nothing is taken over), `helab/views/CacheMover.py` (the flow and its dialogs) and a
  `cache_move` helper operation (`check`, `move`, `cleanup`, `abort`, `recover`) on the local
  lane, with no time limit. Choices made here:
  - The cache folder (`dir_caches`) moves whole: its contents land in the chosen folder, which
    must be empty or new. The General tab shows it read-only with **Change…**; Save never
    writes it, and "Reset all settings…" keeps it (where the cache is isn't a preference).
  - Pause: `IOService.hold_cache` stops running helpers that open the cache (they are
    cancelled; a load shows "Cancelled — Retry") and holds the rest; the move starts once
    `cache_busy()` is false (every exit confirmed). Queued helpers get the current cache
    options when they start (`IOService.cache_options`), so nothing queued before the move
    opens the old folder.
  - Each step is its own request (a new generation); Cancel's abort reuses the move's key, so it
    starts only after the stopped move helper has exited. A rename has no cancel point; Cancel
    is removed at "Switching to the new folder…".
  - The cutover is `write_cache_setting`: set, `sync()`, `status()` and read back. A failed
    write is before the cutover: a copy is discarded (`abort(before_cutover=True)`); a rename is
    renamed back (`undo_rename`), or, if that fails, the destination is used for the session and
    the next start repairs the setting.
  - A copy is made in a sibling staging folder (`.<name>.helab-moving`) that the move creates
    exclusively and marks with `.helab-move-<id>`, and renamed to the target only if the target
    is still empty. Undoing a copy deletes only a folder holding that marker, never files put in
    the target after the check, a folder already in the staging folder's place, or a user's own
    copy of the cache. The marker is removed from the new cache folder after the cutover. A rename that has happened is renamed back
    by `abort`; `abort` never deletes the record while the store is only at the target.
  - Each move has an `id` in its record; `cleanup` and `abort` touch only their own move's
    record, and a move doesn't start while an earlier one's record remains (e.g. its old folder
    couldn't be deleted: restart to finish it). The mover keeps `cache.lock` until a copy's old
    folder is deleted, so no other move starts meanwhile (I/O resumes at the switch; Settings can
    close then). A third lock, `move.lock`, is held by the helper doing a move step, which can
    outlive its HeLab; startup and `lock_for_move` wait for it. Each holder writes a token in
    its lock (the move id, or `startup-<pid>-…`), and a move step's helper, once it holds
    `move.lock`, acts only if `cache.lock` is still held with its token: a helper that outlived
    its HeLab never touches what a new HeLab is using.
  - A cutover whose record can't be written after the setting was saved still switches; the
    record stays at its last step and the next start finishes. After a failed settings write the
    in-memory setting is put back (a later sync must not save the discarded folder); a rename
    renamed back resumes on the source even if its record can't be deleted. Any unexpected error
    while handling a step resumes I/O and reports, leaving the record for the next start.
  - A move whose rename can't be undone after a failure (or an abort after its helper ended
    abruptly) reports where the store is (`store_at`); HeLab then uses the target for the
    session and the next start saves the setting. A record at `old_deleted` whose destination
    is unreadable is reported and kept, not silently dropped. A cache folder containing the app folder (its record and locks) is never moved.
  - When HeLab can't tell where the store is, it never guesses: an undo whose helper fails or
    can't be queued, or a startup recovery that fails or leaves a record while the setting
    doesn't name the move's store (`usable_after_recovery`), turns the disk cache off for the
    session (`start_cache_dir(usable=False)`, nothing saved), and the next start tries again.
    A record with no valid store left is set aside (`cache-move.failed-<time>.json`) for the log
    instead of blocking the cache at every start; one whose source is fine but whose setting
    couldn't be saved is kept. Recovery is never "usable" after a failed settings write (the
    attempted value may linger in the helper's memory), and queued helpers get empty cache
    options once the cache is off (a cache-only job then fails; a source job runs without it).
  - Recovery never opens or trusts a folder that is now on a network or synced folder: it
    counts as holding no store, so a safe source is kept.
  - The cache path is resolved without saving at import; a default that replaced a missing or
    unusable setting is saved only at startup while `cache.lock` is held
    (`constants.start_cache_dir`), so a launch during a rename can't overwrite the moved
    setting. The legacy temp-folder migration runs there too.
  - The copy skips SQLite's `-shm` file (rebuilt on open) after `wal_checkpoint(TRUNCATE)`;
    verification opens the copy with `query_only`, since a read-only open of a WAL database
    fails without its shared-memory file.
  - `cleanup` deletes nothing before the cutover is recorded, whoever calls it.
  - Startup (`main._start_cache`): take `cache.lock` (showing "Another HeLab is moving the
    cache…" while waiting, also for a running `move.lock`), recover in a helper (it reads the
    store, may delete a folder and saves the setting itself; skipped without a record), register
    `instances/<pid>.lock`, release, then re-resolve the cache folder (`resolve_cache_dir`,
    `set_cache_dir`). What recovery repaired
    is shown once the window is up. A record whose stores can't both be found stays, as the
    table says.

- **S10:** `CacheStore.read_prefs` / `set_prefs` (a later `set_at` wins, e.g. another HeLab; a
  row is kept when its flags are turned off or cleared, so its `set_at` still rejects an older
  choice arriving late, and a listing's fresh "off" replaces a stale "on") / `clear_prefs`; `cache_admin` actions `prefs` (with
  `remove_cached`) and `clear_prefs`; listings send each subfolder's `prefs` (and a listing of
  the folder itself sends `folder_prefs`); `FolderCache.prefs`, `folder_prefs`,
  `set_folder_prefs` (shown at once, then saved) and `folderPrefsChanged`. Choices made here:
  - Every dataset save, pending save and adoption checks the folder's `no_cache` flag in its
    own transaction (`SaveRejected("no_cache")`), so a load that started before the user ticked
    it never saves. A load of such a folder (from the request or the saved flag) neither reads
    nor writes its cached data ("Not cached: your choice"); cache first doesn't apply, though
    data already in RAM still shows.
  - "Don't auto-load": an automatic load of the folder starts nothing, not even a cached read.
    Summary line `… · Auto-load off for this folder` with **Load**, Folder details and the
    hint say so; untick it while the folder is selected and it loads by itself.
  - Ticking "Don't cache" on a folder with cached data asks "Remove its cached data
    (420 MB)?" (Remove cached data / Keep it). Records carry the dataset file's size
    (`disk_bytes`) for this.
  - Row badges (tabler `database-off`, `player-pause`, grey) and tooltip lines "Not cached: your
    choice" / "Not auto-loaded: your choice".
  - A listing that finds no flags doesn't undo this session's newer choice.
  - `set_prefs_removing` removes the folder's cached data in the same transaction, and only if
    this choice was the one saved: a superseded request removes nothing.
  - Setting a flag stops this tab's automatic work it rules out (queued or running loads and
    cached reads for Don't auto-load; cached reads for Don't cache), keeping deliberate work;
    the cached-read helper also refuses a folder whose saved flag says not to cache it. A flag
    that can't be read counts as "don't cache" for that load or read (with a warning), and a
    load that saves nothing by choice never shows "Cache update failed".
  - A deliberate load's cached read keeps it deliberate: its follow-up check runs even with
    auto-load off (for the folder or the tab), unless Cancel comes first.
  - A flag that can't be saved (helper error, cancellation, a full queue) is put back to what the
    store last confirmed (never to another unsaved choice), and the tab that set it says so
    ("HeLab couldn't save your choice for …").
  - Clear records its time (`meta.prefs_cleared_at`, never lowered by an older Clear finishing
    last) and changes only rows chosen before it: a choice made before it is refused even for a
    folder that had no flags yet, and one saved after it stays; its result carries that time, so a newer saved choice
    that arrived first stays. Don't cache set during a queued automatic cached read loads the
    folder from its files instead.
  - The large-folder warning gets a **No auto-load** button beside **Load anyway…** (S8 landed
    first, so S10 adds it).
  - The Cache tab's "Folder preferences" row shows the counts with its own Clear…; Clear all and
    the purges never touch the flags.

- **S11:** Wrap-up: the settled decisions and review lessons in
  `.ai/memory/results/disk-cache-and-budgets.md` (indexed in `.ai/memory/MEMORY.md`), native
  checks for the dialogs, the move, the large-folder warning and the flags in
  `.ai/MANUAL_TODO.md`, the overview ticked, and the S7–S10 review history in
  `.ai/sessions/2026-10-11-claude-cache-rebuild-s7-s10/notes.md`. AGENTS.md was updated in each
  session.

## Acceptance

- No GUI-thread access to the store, at startup or in Settings.
- Under write contention, nothing reports "nothing saved"; a blocked folder is never scanned
  automatically.
- Any removal (clear, purge, trim, make room, don't-cache) while loads, scans and saves run
  leaves no stale badge, and nothing removed comes back.
- A reader never fails because a writer replaced or removed a dataset file at the same moment.
- Nothing is removed from the disk cache without the user asking. Records and folder flags are
  never removed to make room. Over 80%, uncached folders don't auto-load and cache updates ask
  first; a save that won't fit is skipped and asks.
- Folder flags apply to exactly one folder and survive restarts and purges.
- Loading never drops a dataset shown in a tab; the RAM budget holds for the rest.
- An automatic load above the warning threshold never starts and shows "Load anyway…", whether
  the data would come from the source or the disk cache. A deliberate one needs acceptance.
  Above 30% of RAM every load is refused.
- Moving the cache folder leaves exactly one cache, the setting points at it, and HeLab keeps
  running whether the move succeeds, fails, is cancelled or is interrupted by a crash (repaired
  at the next start).
- The cache is never placed on a network or synced folder.
- Native checks recorded in `.ai/MANUAL_TODO.md`.

## Still open

- Whether `/Volumes/dld_output`'s `st_dev` changes across remounts (MANUAL_TODO). If it does,
  folder identity needs another source before cache-only browsing. It does (2026-10-15):
  SMB share keys for now, then proposed [data roots](data-roots.md) (2026-10-16).
