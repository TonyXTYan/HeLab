# Cache storage, memory budget and the Settings → Cache tab

Horizon: now (v0.0.5a). Added: 2026-10-10. Decisions agreed with Tony on 2026-10-10 (below);
built over several sessions and commits, tracked in [Sessions](#sessions).
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
| Disk budget | **Editable, default 8 GB.** It counts the whole store. Records are tiny and are never removed to make room. **Nothing is removed automatically.** At **80%**, automatic loads of folders with no cached data pause, and a dialog offers the purge settings. A save that won't fit, or an update to a cached folder while over 80%, asks first. |
| RAM budget | **Editable, in bytes, in steps of 1/128 of the computer's RAM, minimum 1 GB, default 1/8 of RAM.** Decides which loaded folders stay in RAM. |
| Large folders | The point is to stop **accidental** huge loads. **Automatic loads** above the RAM budget or 10% of RAM **don't start** and show an amber warning with "Load anyway…". **Deliberate loads** ask in a dialog. Above 30% of RAM, every load is **refused**. The RAM estimate is the **TXY files' size on disk, with no scaling**: it overestimates (data takes about 0.69× in RAM), which is the safe side. |
| Folder size | A basic scan records each file kind's count and total size in the folder's saved summary (`files`, see [File kinds](#file-kinds)). For now only TXY sizes are measured; raw `d*.txt` are counted, not sized. **Every load starts with a basic scan.** Its listing-and-stat phase is a complete basic scan, saved before any file is read, and it gives the size used by the large-folder check. |
| Folder flags | Right-click toggles **Don't cache this folder** and **Don't auto-load this folder**. They apply to **that folder only**, never to parents or subfolders. |
| Cache folder | Changing it **moves** the cache **while HeLab runs**. I/O pauses; on success HeLab switches to the new folder in place. On failure or Cancel it keeps the current folder and carries on, with a dialog giving the reason and **Show in Finder/Explorer** for any folder left to deal with by hand. The setting changes only after the copy is complete and checked. |
| Old browser | Assess and remove it entirely (see [Old browser removal](#old-browser-removal)). |
| `helab/scripts/` | This is the **analysis script system** for the right-hand panel and stays. Only `helab/scripts/dev/` (plotting-library prototypes) is affected by the removal. |

## Rules for every session

- The GUI process never opens the store. Only helpers do, on the **local lane**; the GUI uses
  their events and its memory (`FolderCache`).
- A failure is never reported as "nothing saved". Readers return found / not found / error; an
  error becomes a visible warning and never unblocks an automatic scan.
- Each save checks the store's `generation` and the folder's epoch in its own transaction, so a
  save that was already running can't write back data that was cleared.
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
| `meta` | `key` | `layout_version` (2), `generation` (bumped by every clear), `created_at` |
| `folder_summaries` | `path` | `record` JSON: today's `folder-scan-v1` content, with counts and sizes per file kind in `files` (see [File kinds](#file-kinds)); `identity`, `saved_at` |
| `scan_histories` | `path` | `record` JSON (today's `ScanHistory`), `saved_at` |
| `subtrees` | `path` | `record` JSON (today's `folder-subtree-v1`), `saved_at` |
| `folder_prefs` | `path` | `no_cache`, `no_auto_load` (booleans), `set_at`. The user's choices, not cache: never purged by age and never cleared by "Clear all"; only by its own Clear. |
| `datasets` | `path` | `file`, `bytes` (file size), `ram_bytes`, `rows`, `shots`, `fingerprint` JSON, `problematic` JSON, `info` JSON (`saved_at`, `snapshot_at`, `signature`, `counts`, `unsettled`), `epoch`, `last_used` (indexed) |

- The fingerprint list is about 100 KB for 3,000 shots, which is fine as JSON. It must be
  readable without decompressing the data, because the cache-first check uses it on its own.
- `last_used` is updated whenever a helper serves the dataset: shown from the cache, reused by a
  load, or confirmed by a check. It is one small write per load. Records have no access date
  (a listing shows hundreds at once); their purge uses `saved_at`, when HeLab last checked the
  folder. `saved_at` is indexed in every record table.
- "Clear by kind" is `DELETE FROM <table>` plus a `generation` bump, in one transaction.
- "Purge older than" and its estimate are one query on `last_used`.

**Datasets: `datasets/<id>.blosc`**, one file per folder (Blosc zstd-9 pickle of
`{shot: float64 (n, 3)}`, today's format). Writing one:
1. Compress, write to `datasets/tmp-<id>`, fsync, rename to `<id>.blosc`.
2. One transaction: check `generation` and the folder's `epoch`, upsert the `datasets` row, note
   the previous file.
3. Commit, then delete the previous file.

A killed writer leaves at most a `tmp-` or an unreferenced file. The maintenance sweep deletes
these once they are more than an hour old, so it can't race a writer that is still running.

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
  file format is versioned (`info.format`). A second kind can then be cached beside the first
  without ambiguity.
- **Not now:** measuring raw sizes (an extra stat per raw file on the network volume) and loading
  other formats. Both are on the overview's roadmap.

## Memory (RAM) budget

- **Setting:** steps of 1/128 of total RAM (`psutil.virtual_memory().total`), stored as a step
  count so it still makes sense after a RAM upgrade.
  - Minimum: max(1 GB, 1 step). Maximum: 64 steps (half of RAM).
  - Default: 16 steps (1/8 of RAM). Examples: 16 GB on 128 GB (Tony's Mac), 2 GB on a
    16 GB lab PC, 1 GB on 8 GB.
  - Shown as e.g. "16.0 GB (1/8 of 128 GB)". Typed values snap to the nearest step.
- **What it decides:** replaces `FolderCache.MAX_DATA_BYTES` (512 MiB today).
  - After every load, datasets not shown by any tab are dropped from RAM, least recently used
    first, until the total fits.
  - Datasets shown in a tab are never dropped, even over budget.
  - So the folder you just loaded stays; older unshown ones go first.
  - Lowering the setting applies at once and says what was dropped.
- The Cache tab's "This session" line shows: loaded data N folders · X of Y GB, and how much of
  it is pinned by open tabs.

## Large-folder warning

- **Estimate before reading: the TXY files' total size on disk, unscaled.**
  - On 2026-10-10, Tony's 19 cached folders measured 0.67–0.70× that size in RAM: a TXY row is
    about 35 bytes of text, but 24 bytes as three float64. Tony chose the unscaled size because
    overestimating is the safe side and needs no calibration.
  - **Every load starts with a basic scan.** Today's load already lists the folder and stats
    every TXY file (its fingerprint), then sends and saves that as the folder's summary
    (`scan_summary`) before reading anything. That phase is a full basic scan. It records
    `files.txy.bytes`, and the large-folder check runs on it right there, before the first file
    is read. Running a separate scan helper first would list and stat the folder twice, which
    is slow on the network volume, so the load's own scan phase is used.
  - A saved summary (from an earlier scan or load) lets HeLab decide **before** submitting the
    load, so an automatic load of a known-large folder doesn't even start a helper. A folder
    that has only been listed (names only) has no size yet; its load stops after the scan phase
    instead.
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
- **Warn** for network folders (`statfs` type smbfs/afpfs/nfs/webdav; UNC or remote drives on
  Windows) and synced folders (iCloud `Mobile Documents`, OneDrive, Dropbox, Google Drive). The
  cache database isn't safe there.
- **Confirm:** "HeLab pauses loading and folder checks while it moves the cache (706 MB) to X."
- **The move runs while HeLab stays open:**
  1. **Pause.** `IOService` stops starting work that uses the cache. Running jobs are cancelled
     or finish, and HeLab waits until every helper's exit is confirmed (the existing slot rule).
     Browsing memory, plots and loaded data stay usable.
  2. **Move**, with a progress window and **Cancel**. On the same disk it's an instant rename.
     On another disk, in this order:
     1. copy
     2. check the file count and bytes
     3. update `dir_caches`
     4. delete the old folder
  3. **Success:** switch to the new folder in place and resume. No restart. Every cache path is
     read through one function (`cache_dir()`), not the import-time `DIR_CACHES` constant.
  4. **Failure or Cancel** (no space, not writable, copy error, …): delete the partial copy,
     keep the current setting, and resume on the current cache. A dialog gives the reason in
     plain words, e.g. "Not enough space on 'Backup': needs 706 MB, 210 MB free".
     - It has **Show in Finder** (Windows: **Show in Explorer**) buttons for each folder that
       needs manual attention: a partial copy that couldn't be removed, an old cache that
       couldn't be deleted after the switch (marked "safe to delete"), or the target, to check
       its space or permissions.
     - Folders are opened with `QDesktopServices.openUrl`.
- **Why that order:** updating the setting only after the old folder is deleted would leave the
  setting pointing at a deleted folder if HeLab crashed in between. With this order there is
  always one usable cache and the setting points at it. If HeLab crashes between steps 3 and 4,
  the old folder is recorded in `dir_caches_previous` and deleted on the next start.
- **Other instances:** each running HeLab holds `<cache>/instances/<pid>.lock` (`QLockFile`).
  The move refuses while another live instance holds one. Ordinary use by two instances is fine:
  SQLite WAL handles it.
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
- **Disk budget:** GB, default 8, minimum 1, steps of 0.5. It counts the whole store; records are
  a fraction of a MB. Lowering it below current use asks first ("Removes cached data for 4
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
| `clear` (`kinds`) | Deletes the tables/files of those kinds and bumps `generation`. `FolderCache.cleared(kinds)` then resets its memory (`_disk_cached_paths`, cache states, `disk_cached` on datasets in RAM, snapshot summaries, histories, subtrees) and models re-render. |
| `purge` (`kind`, `older_than`, `include_failures`) | Datasets by `last_used`, or folder records by `saved_at`; returns what was freed |
| `trim` (`budget`) | Removes least recently used datasets until under the budget. **Only on the user's request**: lowering the budget, or "Make room" in the full-cache dialog. Never automatic. |
| `sweep` | Removes orphan dataset files more than an hour old; runs once after launch when idle |

Clearing data while a folder's save is running makes that save fail with "Cache was cleared
before saving completed", as the per-folder clear does today.

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
- The helper checks the budget inside the save transaction, with the compressed file's exact
  size. If it doesn't fit, the save is skipped and the helper sends `cache_full` (needed and
  free bytes).
- HeLab asks in a dialog: "Not enough room in the disk cache for X (420 MB, 7.9 of 8 GB used)".
  - **Make room:** remove the least recently used cached data until this folder fits, then
    save. The dialog says what that removes, e.g. "cached data for 4 folders (1.2 GB) not used
    since 3 Aug".
  - **Don't cache this folder now.**
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
- `os_cached.py`, `caching_setup.py` (replaced by the new store) and `threading_setup.py` (its
  pools and worker registries are used only by the old code)
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

## Sessions

Each row is one agent session ending in one or two commits (ask Tony first). Start a session by
reading this plan, the audit notes and AGENTS.md. End it by ticking the row with the commit hash.

| # | Session | Scope | Tests | Depends on | Status |
|---|---|---|---|---|---|
| S1 | Quick storage fixes | `statistics` off. Decide `blocked` inside `begin_scan`'s transaction. `save_subtrees`/`_save_summary` report failed saves. Reads that decide behaviour use `retry=True`. (Protects the current store until S5.) | Held write lock does not unblock an automatic scan; failed subtree save is reported | — | ☐ |
| S2 | Untangle the old browser | Plain `StatusReport`; move `fnum` and the column constants; new `closeEvent`; `main.py` and `conftest` no longer import old modules | Full suite; import test: loading `HelabMainWindow` imports none of the old modules | — | ☐ |
| S3 | Delete the old browser | Delete the modules, tests and Debug item; move `helab/scripts/dev/`; update AGENTS.md | Full suite | S2 | ☐ |
| S4 | New store module | `helab/utils/cache_store.py`: schema, versioning, dataset file writes, read results (found/missing/error), `generation`/epoch checks | Two processes writing at once; killed writer; newer `layout_version` opens read-only; error is not "missing" | — (parallel to S2/S3) | ☐ |
| S5 | Switch to the new store | Helpers (`list`, `details`, `scan`, `load`, `cached`, `invalidate`, `subtree_save`, `scan_history`) use `cache_store`; one `FILE_KINDS` table drives matching and counting; summaries save `files` (TXY sized) and datasets `ram_bytes`; `last_used` on use; old cache folders deleted at startup; diskcache removed | Existing cache-first, folder-cache and scan-history tests pass on the new store | S1, S3, S4 | ☐ |
| S6 | Cache maintenance | `cache_admin` (inventory, clear, both purges, trim, sweep); `FolderCache.cleared()`; budget check in the save transaction, `cache_full` | Clear during a running save; purge estimates equal what is freed; records survive trimming; an over-budget save is skipped, never auto-trimmed | S5 | ☐ |
| S7 | Budgets and the Cache tab | Rebuilt tab with both purges; disk budget (default 8 GB); RAM budget (1/128 steps, default 1/8) replacing `MAX_DATA_BYTES`; 80% pause of uncached automatic loads with its dialog; update-save prompt over 80%; full-cache dialog (Make room / Don't cache now); "Reset all settings…" | pytest-qt tests with a fake inventory; 80% dialog once per crossing, Ignore lasts the session; cached folders still open over 80%; one cache dialog at a time; RAM eviction keeps shown datasets | S6 | ☐ |
| S8 | Large-folder warning | Unscaled TXY-size estimate; `too_large` stop and `allow_large`; amber inline "Load anyway…"; queue skips; dialog for deliberate loads; the 30% refusal replaces the 1 GiB limit | Automatic loads never start or open a dialog; deliberate ones confirm; refusal; estimate from a saved summary vs from the load's own listing | S5 | ☐ |
| S9 | Cache folder move | Change… flow and checks, I/O pause until helpers exit, move with progress and Cancel, `cache_dir()` switch in place, `dir_caches_previous`, instance locks, failure dialog with Show in Finder/Explorer | Same-disk rename; cross-disk copy; failure and Cancel keep the current folder and resume; crash between switch and delete cleans up on start; refusal with another instance | S5 | ☐ |
| S10 | Folder flags | `folder_prefs` and its helper save; flags in listings; right-click toggles; row badge and tooltip; no-auto-load and no-cache behaviour; offer to remove cached data; "Don't auto-load" in the large-folder warning | Flag survives restart and purges; no-cache load never saves; no-auto-load select starts nothing; flags never inherited | S5 (S8 for the warning button) | ☐ |
| S11 | Wrap-up | AGENTS.md, `.ai/memory/results/` decision note, MANUAL_TODO native checks (dialogs, move, large-folder warning, flags), overview ticks | — | all | ☐ |

S1, S2 and S4 can start in any order. S7, S8, S9 and S10 are independent of each other.

## Acceptance

- No GUI-thread access to the store, at startup or in Settings.
- Under write contention, nothing reports "nothing saved"; a blocked folder is never scanned
  automatically.
- Clearing any kind while loads, scans and saves run leaves no stale badge, and nothing cleared
  comes back.
- Nothing is removed from the disk cache without the user asking. Records and folder flags are
  never removed to make room. Over 80%, uncached folders don't auto-load and cache updates ask
  first; a save that won't fit is skipped and asks.
- Folder flags apply to exactly one folder and survive restarts and purges.
- Loading never drops a dataset shown in a tab; the RAM budget holds for the rest.
- An automatic load above the warning threshold never starts and shows "Load anyway…". A
  deliberate one needs acceptance. Above 30% of RAM every load is refused.
- Moving the cache folder leaves exactly one cache, the setting points at it, and HeLab keeps
  running whether the move succeeds, fails or is cancelled.
- Native checks recorded in `.ai/MANUAL_TODO.md`.

## Still open

- Whether `/Volumes/dld_output`'s `st_dev` changes across remounts (MANUAL_TODO). If it does,
  folder identity needs another source before cache-only browsing.
