# Handoff: cache-only browsing (Work Offline), C0–C3

Harbor, floor "Cache Only", branch `agent/cache-only`, base `0840acb`. Brief: `brief.md`.
Design and decisions: `design.md`. Measurements and evidence: `notes.md`.

## What it does

**File › Work Offline** makes HeLab read only its local disk cache, with no source folder and no
server, until it is turned off. It is remembered across restarts.

- **Browsing:** the tree shows each folder's **saved listing**: its subfolder names and its counts,
  as last seen online.
- **Selecting a folder** shows its data from RAM, else from one cached read, never from the folder.
  The data is marked "not checked (offline)".
- **Plots** run on that data. Saved analysis results show as usual. Reopened plots wait for one
  cached read, as they already do.
- **Controls that would read a folder** are disabled with "Not while working offline":
  - Refresh, Check folder status, Live, and the tree's Retry / Refresh;
  - Place .helab-root (both), Open in File Manager, and Settings → Data roots' Show in Finder and
    Delete .helab-root…;
  - It's a copy…, Load as it is now, and the manual marker dialog's Save to folder….
- **Folder icons** stay generic (plus any already in memory).
- **Work Online** lists every tab's shown folders again (Refresh) and checks the current tab's
  selected folder as usual.

Commits on the branch:

| Commit | Stage |
|---|---|
| `9c75340` | C1: other tabs' results show during Refresh without I/O (the no-I/O replay path) |
| `503cc9a` | C0: design note and C1 notes |
| `6591e46` | C2: saved listings (`listings` kind, written by `list`, read in the local lane) |
| `60237d8` | C3 plan and the draft tests |
| `1574127` | D1: mount hints, so unmounted folders keep their cache key offline |
| `445bd23` | C3: Work Offline (the gate, `saved_list`, model, explorer, main window, four other windows, tests) |

Checks at `445bd23`:
- Full suite (`-n 4 --reruns 5 --reruns-delay 1`): 4382 passed, 2 skipped, **no RERUN**.
- mypy --strict on `helab/` (163 files) and on `tests/` (134 files): clean.
- pyright: 0 errors.

## Tony's decisions (2026-10-26, through CoCo: "agree to Harbor and Ferrule, proceed")

Everything is as `design.md` proposed it:

- **D1. Mount hints.** A `mount_hints` table, used only offline and only at mount paths nothing is
  mounted at now.
- **D2. Name and memory.** "Work Offline", remembered across restarts (`work_offline`, default
  off).
- **D3. Entering.** Live turns off first and its save finishes; source reads are cancelled; local
  work goes on.
- **D4. Listings record kind.** Its own Settings → Cache row, "Folder listings". Purged by age with
  the other folder records. Removed by Clear all and by a root's Clear cached data…. Not counted
  in the budget.
- **D5. Writing listings.** `list` helpers write them after sending their status: guarded, best
  effort, skipped when unchanged and under an hour old.
- **D6. Disabled controls.** Disabled with "Not while working offline". CoCo extended this to the
  four files outside the owned paths, listed below.
- **D7. Refusals.** A refused request is never shown as a failure.
- **D8. Leaving.** Work Online refreshes every tab. (Tony chose this over CoCo's current-tab-only
  variant.)
- **D9. Derived status.** Not saved offline.
- **D10. Start folder.** Starting offline, the first tab opens at the data root seen most recently.

## Files touched outside the brief's owned paths

| File | Change | Why |
|---|---|---|
| `helab/io_ops/stores.py` | Records mount hints; `offline` keys through them | D1, approved by Tony |
| `helab/io_ops/admin.py` | Passes `offline` to `_cache_store` | D1, so folder constants and prefs key offline |
| `helab/io_ops/events.py` | `OfflineListingEvent` | The typed helper-event contract |
| `helab/io_helper.py` | `saved_list` in `CACHE_ONLY` and the dispatch; `OFFLINE_REFUSED`; `offline` for invalidate | CoCo allowed it. Expect a one-entry `CACHE_ONLY` conflict with Quick Fixes 2 |
| `helab/views/explorer_live.py` | `OFFLINE_LIVE` reason in `live_unavailable` | Live is off offline |
| `helab/views/DataRootsTab.py` | Show in Finder and Delete .helab-root… off offline (no launch) | D6, CoCo approved |
| `helab/views/RootDuplicatesWindow.py` | It's a copy… off offline | D6, CoCo approved |
| `helab/views/MissingShotsWindow.py` | Load as it is now off offline | D6, CoCo approved |
| `helab/views/DataRootDialogs.py` | ManualMarkerDialog's Save to folder… off offline | D6, CoCo approved |
| `tests/conftest.py` | The seeded `_cache_store` wrapper passes `offline` on | One keyword, so seeded stores key offline |

`helab/utils/data_roots.py` and `helab/utils/cache_paths.py` were not changed: the hints are built
from their existing `Mount`, `CachePaths` and `LocalVolumes`.

## How it works (for the AGENTS.md entry)

### Saved listings (C2)

`store-v3` gains a record kind `listings`: `(path = root:// key, record, saved_at)`, with
`gen_listings`. It is added to older stores by `_migrate`; a read-only older store reads it as
missing.

- **What `list_folder` saves:** after sending its status, the folder's subfolder names and its own
  counts (status, count, raw/TXY counts, empty, `has_dirs`, files), with `listed_at`. It never
  saves shot lists.
- **Guard:** taken before the scandir.
- **When it skips the write:**
  - unchanged and under `REFRESH_SECONDS` (1 h) old;
  - a newer listing is already saved;
  - the store is busy for more than `WRITE_WAIT` (0.5 s);
  - a re-keyed folder.
- **Never** after a failed listing.
- **Cost:** 0.15 ms per save (median). Size about 450 B per folder: 4.5 MB per 10k folders.
- **Removed by:** Clear by kind (Folder listings), Clear all, purge by age, and a root's Clear cached
  data…. A nested root's re-key moves them.

### Mount hints (D1)

`mount_hints (mount_path, location, seen_at)` is in `ROOT_SCHEMA` plus `_migrate`.

- **Writing:** source helpers record the share or volume (`smb://server/share`, `vol://<id>`) at
  each source path's mount, never the system volume's, and only when it changed (best effort).
- **Reading:** an offline request (`"offline"` in its cache options, from `store_options()`) adds
  them back in `_cache_store` at mount paths nothing is mounted at now. A mount there now wins.

### The gate (C3)

- **`IOService`:**
  - `OFFLINE_OPERATIONS` are the only operations that start while `offline`: `cached`,
    `saved_list`, `cache_admin`, `result_find`, `result_save`, `invalidate`, `volumes_verify`,
    `trace_check`, `cache_move`, `drives`.
  - `submit` refuses the rest (one INFO line per operation).
  - `set_offline(True)` cancels queued and running source work, except saves already asked for
    (`finishes_offline`).
  - `_start` refuses a straggler.
- **`FolderCache.set_offline`** (`offline`, `offlineChanged`):
  - It cancels shared jobs, except saves, and drops pending subtree saves.
  - `submit` (through `_offline_submit`):
    - turns a tab's `list` into a local-lane `saved_list` job, with no snapshot and no scan
      history, replayed to its subscribers;
    - turns `resolve` into the newest data root;
    - answers any other source operation with `offline`, then `done` (`scan_skipped`) for scans or
      `cancelled` for the rest.
  - `save_subtree` saves nothing offline.
  - Going online verifies volumes and roots again.
- **`io_helper`:** refuses `OFFLINE_REFUSED` (source operations, `resolve`, `roots_verify`) for an
  offline request before any handler. A save is exempt.
- **`io_ops/listings.saved_list_folder`:** sends a folder's saved records, then its saved
  subfolders, then an `OfflineListingEvent`.
  - A subfolder never checked in full gets its own listing's counts.
  - A folder never listed sends `listed` False.
  - A folder above the data roots lists the way down to them.
- **`newest_root_folder`:** answers the start-up `resolve`.
- **Model:** `offline_listed_at` / `offline_unlisted` on rows. Tooltip lines "Offline: showing saved
  results from <date>" and "Subfolders: not listed while online". No icon or details requests
  offline. Rows cancelled by going offline go back to idle.
- **Explorer:**
  - `_show_offline` replaces the load.
  - `offline_data_note` gives the reason no data shows.
  - The summary lines read "Offline · cached data only · listed <age>", "not checked (offline)",
    "No cached data (offline)" and "Data not kept (offline): work online to load it".
- **Main window:** File › Work Offline, the status-bar button, and Refresh and Check folder status
  disabled offline. `set_work_offline` saves the setting.

## Proposed doc edits (for CoCo when merging)

**AGENTS.md:**
- **Responsive filesystem I/O:** a "Work Offline" bullet with the gate summary above, after the
  "local lane" bullet.
- **Caching:** add `listings` to the record kinds and to "Clear all"; add `mount_hints` beside
  `root_volumes` in **Data roots › Local lane**.
- **The `helab/io_ops/` family list:** add `listings`.
- **Settings persistence:** the `work_offline` row.
- **Testing:** `tests/test_offline_browsing.py` denies source access with `no_source_io` and
  `answer`; tests that call `set_offline` reset `folder_cache._offline`.

**`roadmaps/cache-only-browsing.md`:**
- Mark the plan done for C0–C3.
- Record D1–D10 (with D8 as every tab).
- Open decisions resolved: explicit switching; Live off, then source work cancelled.
- Keep "automatic switching after a reachability failure" as an unchosen idea.
- Link `design.md`.

**`roadmaps/cache-storage-and-settings.md`:** the `listings` kind (its row, purge, clear and
re-key) and the `mount_hints` table, with their sizes.

**`roadmaps/_readme.md`:**
- Close "Cross-tab status results during Refresh" (`9c75340`) and "Cache-only browsing" (C0–C3).
- Follow-ups, if wanted:
  - `scan` and `details` writing listings too, so folders checked but never expanded become
    navigable offline;
  - a Disk cache off session offline, which today gives error rows ("The disk cache is off for
    this session").

**`roadmaps/known-issues.md`:** the mixed-versions caveat. An older HeLab's Clear all and root
clear don't remove listings or bump `gen_listings`, and its re-key leaves them at the old key. The
next listing re-saves them, so this is harmless.

**`.ai/MANUAL_TODO.md`:** the on-screen checks below, and a real-volume check: unmount the lab
share, restart, browse and plot.

## On-screen checks (not done: no GUI on the floor)

1. **Start online and browse:** a data root, two levels down, and load a folder.
2. **Turn on File › Work Offline:**
   - The check mark and the status-bar "Offline · cached data only" appear.
   - Refresh and Check folder status grey out with the reason in their tooltips.
   - Live is greyed and its tooltip says "Live is off while working offline".
3. **Navigate the tree:**
   - Counts and status icons show.
   - A folder never expanded online has no expand arrow; its tooltip says "Not listed while online".
   - Row tooltips end "Offline: showing saved results from …".
   - Icons stay generic.
4. **Select the loaded folder:**
   - Its data shows at once.
   - The cache line ends "not checked (offline)".
   - The third line reads "Offline · cached data only · listed …".
5. **Select a folder never loaded:** "Data not kept (offline): work online to load it" and "No
   cached data (offline)"; nothing spins.
6. **Open a plot on the loaded folder:** it runs. Close it; a saved Correlations or Release time
   result shows from the disk cache.
7. **Right-click menu:** Retry / Refresh, Check folder status, Open in File Manager and Place
   .helab-root here… are greyed with the reason; Folder constants… and Clear loaded data cache
   work.
8. **Settings → Data roots:** Show in Finder and Delete .helab-root… are greyed; Clear cached data…
   works. **Settings → Cache:** the Folder listings row counts folders and its Clear… asks first.
9. **Quit and start again:** HeLab starts offline, and the first tab opens at the last data root.
10. **Real volume:** unmount the share, restart offline, and repeat 3–6. The paths shown are the
    share's usual `/Volumes/…` paths.
11. **Click the status-bar button › Yes (Work Online):** every tab relists, the selected folder is
    checked ("Checking for changes…"), the controls come back, and the setting is off at the next
    start.
12. **Log:** one INFO line "Work Offline on: cached data only", then a "Working offline: no …" line
    once per refused operation kind.

## Open points and caveats

- **Offline with the disk cache off** (the cache folder refused, or `DISK_CACHE_ENABLED` false):
  `saved_list` fails with "The disk cache is off for this session", so rows show that error.
  Honest, but a dedicated line would be nicer.
- **Saved listings are authoritative offline.** A folder deleted since its listing still shows by
  name until it is listed online. Its data shows only if cached.
- **Windows:** a disconnected mapped drive is still in the mount table (`WNetGetConnection` 1201),
  so it is keyed as today and hints aren't needed there. Not tested on Windows by hand.
- **Merging dev:** `dev/v0.0.6` hasn't been merged in yet. Quick Fixes 2 (`agent/quick-fixes-2`
  `26994dd`) changes one `io_helper.CACHE_ONLY` entry, so a trivial conflict is expected.
