# Cache-only browsing: design note (C0)

Harbor, 2026-10-26, floor "Cache Only", base `0840acb`. Plan: `roadmaps/cache-only-browsing.md`.
Each section gives a **recommendation** and the alternatives. Decisions for Tony are numbered
**D1–D10** and listed together at the end.

## The finding that shapes the rest: unmounted paths have no cache key

The disk cache keys a folder by `root://<uuid>/<relative>`. The helper finds that key from the
**current mount table**: `/Volumes/lab-data/2026/run1` → `smb://server/share/2026/run1` (SMB) or
`vol://<volume ID>/…` (local disks) → the `roots` table → the root's UUID
(`io_ops.stores._cache_store`, `cache_paths.CachePaths.key`). Once the share is unmounted,
`/Volumes/lab-data/…` matches no mount, so it has **no key**: `cached` reads, saved results and
saved status all answer "no data root" (RAM only). Offline browsing of an unmounted volume
therefore needs a saved link from the mount path to its location.

**Recommendation: mount hints.** A small store table `mount_hints (mount_path, location, seen_at)`
records, for each mount a source helper keyed paths under, its location prefix
(`smb://server/share` or `vol://<id>`). `root_volumes` already records this for local volumes;
this adds SMB shares and Windows mapped drives. Only **offline** requests (`"offline": true` in the
request's cache options) use hints, and only for a path that **no current mount** contains. A path
that is mounted is keyed from the mount table exactly as today, so online rules don't change, and a
different volume now mounted at that path is never mistaken for the old one.

- The user sees the paths they knew (`/Volumes/lab-data/2026/run1`), and every RAM structure
  (`FolderCache`, tabs, plots, `DatasetView`) keeps keying by source path, unchanged.
- A mount path seen with suffixes (`lab-data`, `lab-data-1`) keeps one row each, all pointing to
  the same location.
- Touches `io_ops/stores.py` (`_cache_store`'s local-lane branch), outside the brief's owned
  paths: **D1** asks for it.

Alternative: browse by data root instead of path. The tree would show "Data roots ▸ label ▸
relative path" offline. That's cleaner in identity terms, but every path-keyed structure (tabs,
`FolderCache`, plots, presets) would need a second addressing scheme. Not recommended.

## 1. Name and control (D2)

**Recommendation:** **Work Offline**, a checkable item in the **File** menu. While it is on, the
status bar shows a clickable `Offline · cached data only` button; clicking it offers
**Work Online**. No toolbar button: the toolbar is full, and switching is rare.

- **Switching is explicit only.** No switch after a failed listing; automatic switching stays an
  idea, as the plan says.
- **Remembered across restarts** (`work_offline`, default off, a `settings_defaults.py` row). At
  home or travelling you restart HeLab several times, and starting online would first fail on the
  missing mount. The status-bar button makes the state obvious at every start.
  - Alternative: session-only, with HeLab always starting online.

Other names: "Cached data only", "Offline mode", "Cache-only browsing". Tony names it.

## 2. Entering: running work

**Recommendation.** The gate (§5) closes at once to new source work. Then:

1. **Live turns off first.** Its stop-save (`save_held`: one listing plus stats, which is source
   I/O) is the one source job allowed to finish. The status line says "Finishing Live's save
   before working offline…". If the volume is unreachable, the save fails by its no-progress
   timeout and the shots stay in RAM, as when Live's save fails today.
   - Alternative: ask "Save Live's shots first? / Go offline now (keep them in RAM unsaved)".
2. **Cancelled:** listings, details, status checks, icon lookups, `resolve`, `roots_verify`, and
   loads that read source files (checks and plain loads). A partly read load isn't kept: its shots
   weren't saved, and the cached read shows what was.
3. **Saves already running finish:** finishing loads' disk-cache writes (local), and Live and
   other saves already writing.
4. **Local-lane work goes on:** cached reads, cache admin, the sweep, presets, results,
   `volumes_verify`.
5. **Marker writes already running** (`root_create`, `root_remove`, etc.: one small write each)
   finish rather than being killed mid-write.

## 3. Saved listings (C2)

### What one holds

One row per listed folder:

- **Subfolder names** (sorted).
- **The folder's own names-only status**: `status`, `count`, `raw_count`, `txy_count`, `empty`,
  `has_dirs`, `files` (per-kind counts). That's the compact form `folder_summaries` uses, without
  the shot-number lists.
- **`listed_at`**: wall-clock time the listing started.

Subfolders' counts, badges and dates come from their own records (summaries, histories, subtrees,
datasets, results), read with the listing exactly as `list` reads them today (`_saved_folders`).
A folder's own row is the fallback when no full summary exists.

### Key, scope and table

- **Key:** the folder's `root://` key. Rows exist only below data roots; RAM-only folders have no
  store, as for every other record.
- **Table:** `listings (path TEXT PRIMARY KEY, record TEXT NOT NULL, saved_at REAL NOT NULL)`,
  indexed on `saved_at`, the same shape as `subtrees`. It becomes a new record kind `listings` in
  `KINDS` / `RECORD_TABLES`, so the existing guard, removal, re-key and purge code covers it.
- Added to older stores by `_migrate` (like `folder_constants`), never only in `SCHEMA`. A
  read-only old store reads as empty.

### When it is written

By the `list` helper, after it sends its final status. That way the write never delays what the
tab shows, only the helper's exit, by milliseconds.

- **Save guard:** the guard the listing takes before its scandir (`_send_guard`, already sent):
  `gen_listings`, the folder's epoch and the root's epoch. A Clear during the listing makes its
  save a no-op.
- **Skip when unchanged:** the helper skips the write if the names and counts match the saved row
  and the row is under an hour old. Browsing back and forth then costs no writes, and `listed_at`
  stays at most an hour behind.
- **Best effort:** a busy write lock (short timeout) or any store error skips the write, with a
  DEBUG log line. Saved listings are an extra, never a reason for a listing to fail.
- **Never on a partial or failed listing.** Refresh's listing-only relist writes it too.
  - Status checks (`scan`) and `details` also list the folder in full, so they could write it as
    well. A folder checked but never expanded would then be navigable offline.
  - C2 starts with `list` only (every browse runs one); adding `scan` is a small follow-up if
    wanted.

**Normal browsing is unchanged.** It still lists the folder. Using saved listings online to skip a
scandir stays out of scope.

### Retention and clearing (D4)

- **Purge by age with the folder records:** `purge_records` gains `listings`, so Settings → Cache's
  purge by age removes listings not refreshed since the cutoff.
- **Clear by kind:** its own row in Settings → Cache, **"Folder listings"** with Clear…, worded
  "Offline browsing can't show these folders' subfolders until they're listed again." It is part
  of Clear all, and a root's Clear cached data… removes the root's listings too.
- **Re-key** of a nested root moves them (`rekey_subtree` table list).
- **Not counted** toward the disk budget, like the other record tables.
- Alternative: fold listings into the "Folder summaries" row. One row fewer, but clearing statuses
  would quietly break offline navigation.

### Size (measured, `notes.md`)

A SQLite table in the proposed format holds about 450 bytes per folder, mostly the repeated
`root://<uuid>/…` key:

| Folders | Size | Bulk insert | One read |
|---|---|---|---|
| 10,101 (100 days × 100 runs) | 4.5 MB | 20 ms | 24 µs |
| 10,011 (10 × 1,000) | 4.4 MB | 19 ms | 22 µs |
| 101,001 | 49 MB | 0.29 s | 27 µs |

That's comparable to `folder_summaries` for the same folders. No row cap is proposed; purge by age
is the bound.

## 4. Offline browsing (C3 shape)

- **Listing a folder offline:** `FolderCache.submit` turns the tab's `list` into a local-lane
  `saved_list` (new op, `io_ops` read-only).
  - It reads the folder's `listings` row and its subfolders' saved records.
  - It sends the same events as `list` (`entries`, then `status` with `offline: true` and
    `listed_at`), so the model needs only labels.
  - No row gives `status` `not_listed`: the tree shows "Not listed while online", with no expand
    arrow.
- **Above data roots** (e.g. a tab at `/Volumes` or `C:\`), there are no rows. The folder shows
  only the paths leading to known data roots, from the `roots` table and hints, so every root
  remains reachable.
- **Start-up offline:** `resolve` (which probes `DEV_POTENTIAL_DATA_PATHS`, network paths among
  them) is refused. The first tab opens at the most recently seen data root's hinted path.
- **Selecting a folder:** the data shows from RAM, else from a `cached` read. Never a load.
  - The summary's third line says `Offline · cached <date> · not checked`.
  - A folder without cached data says `No cached data (offline)`.
  - Evicted from RAM with no disk cache: `Data not kept (offline): work online to load it`.
- **Plots:** they run on whatever the tab shows. Reopened plots already use RAM or one `cached`
  read only (`FolderWait`). Saved analysis results (`result_find`, `result_save`) are local and
  work. Released plots reload from RAM or the cache, as they do now.
- **Derived status isn't saved offline** (`subtree_save` is refused). Deriving from saved
  children and saving would re-date old information as new. Shown derivations are memory only.
- **Icons:** generic, plus any already in session memory. No lookups.

**Controls offline (D6):**

- **Disabled**, with the tooltip "Not while working offline": Refresh, Retry, Check folder status,
  Live, right-click Retry / Refresh, Place .helab-root (menu and File item), ManualMarkerDialog's
  Save to folder…, Load as it is now (MissingShotsWindow), It's a copy… (RootDuplicatesWindow),
  Delete .helab-root… (Settings → Data roots), and Show in Finder / Open in File Manager.
  - Revealing a source path launches a file manager on the share, which may wake the network.
  - Copy path stays.
- **Allowed:** Clear cached data, folder flags and constants (local writes), presets, Settings →
  Cache, Same folder (`root_same`, a store write), cache move.
- Alternative: hide those items instead of disabling them (less clutter, but users don't see why
  they're gone).

## 5. The gate

**Where it sits:** two places, belt and braces.

1. **`FolderCache.submit`**, the request boundary for tabs, plots, Live and windows. Here a refused
   request gets an `offline` event, so callers show a state rather than an error, and `list` is
   rewritten to `saved_list`.
2. **`IOService.submit`**, for everything that bypasses `FolderCache` (main window's `drives` and
   `trace_check`, `CacheMover`, startup recovery, `FolderCache`'s own `service.submit` calls). It
   refuses any operation not on the allowed list, returns False and logs one INFO line per
   operation per session.

Plus a **helper seam:** offline requests carry `"offline": true`, and the helper refuses
`SOURCE_OPERATIONS`, `resolve` and `roots_verify` before touching anything. Tests also arm a
fixture that fails any source operation reaching `IOService._start` while offline.

**Allowed offline (local disk only):**

- `cached`, `saved_list` (new);
- `cache_admin` (all actions, including presets, constants, prefs, `root_same` and inventory);
- `result_find`, `result_save`, `invalidate` (Clear loaded data cache);
- `volumes_verify`: local volume IDs via diskutil, never shares; needed for cached reads on USB
  disks;
- `trace_check` (the temp folder), `cache_move` (user's own local folders), `drives` (Windows
  `GetLogicalDrives`, no I/O on drives);
- a `load` with `save` already running when entering (§2).

**Refused offline:**

- `list` (rewritten to `saved_list`), `details`, `scan`, `icons`, `resolve`;
- `load` in every form (checks, plain loads, Live checks, new saves, `save_held`);
- `root_create`, `root_reassign`, `root_remove`, `marker_save`;
- `roots_verify`: it re-reads markers on mounted volumes;
- `subtree_save` and `scan_history`: they write derived or failure records that only source checks
  should produce.

**What a refused one tells the user (D7):** never "queue full" or "failed", and never a scan
failure in history.

- **Tree rows** keep their saved state; the tooltip's hint line becomes "Offline: showing saved
  results from <date>".
- **Load actions** show the summary's line, e.g. "No cached data (offline)".
- **Disabled controls** carry the tooltip above.
- **The log** gets one INFO line per refused operation kind per session.

## 6. Leaving offline (D8)

**Recommendation: Work Online runs Refresh on every open tab** (one listing per shown branch,
which replaces saved status with checked status: today's toolbar Refresh), then the current tab's
selection gets its normal cache-first check.

- Data shown offline was marked unchecked (`verified` false), so the next selection of each folder
  checks it, by the existing rule.
- Plots keep their results; a later Live or load revises them as usual.
- **Meanwhile the tree keeps the offline rows**, with their "saved <date>" tooltips, until each
  listing replaces them. Folders that no longer exist disappear when their parent's listing
  completes.
- Mount-table changes trigger the existing `volumes_verify` / `roots_verify`.
- Alternative: no Refresh, letting folders recheck only as they are selected (cheaper, but the
  tree keeps stale counts longer).

## 7. Audit: every entry point that can submit source I/O

How each is gated (FC = `FolderCache.submit`, IOS = `IOService.submit`, both = FC then IOS).
"Disable" means the control is disabled offline as well as refused at the gate.

| Entry point | Operation | Offline |
|---|---|---|
| `SnapshotFileSystemModel.request_scan` (selection, expand, `fetchMore`, `setRootPath`, Refresh relists, `_shared_snapshot_changed` fallback, rootDecided relists in `FolderExplorer._io_event`) | `list` / `scan` | FC: `list` → `saved_list`; `scan` refused (row stays, offline hint) |
| `model._request_details` (browse step 2, Refresh's deferred details) | `details` | FC refuses |
| `model.request_folder_icons` / `FolderExplorer._load_visible_icons` | `icons` | FC refuses; generic icons |
| `model.rescan` / `refresh` / `FolderExplorer.refresh_folder` / `_retry` / status-line Retry | `list` (`no_timeout`) | Disable; FC refuses |
| `FolderExplorer._check_visible_folders`, `_dispatch_deep` (Check folder status) | `scan` | Disable; FC refuses |
| `FolderExplorer._resolve_default` (tab start) | `resolve` | FC refuses; start at the newest data root's hinted path |
| `FolderExplorer._load_to_ram_cache`, `queue_load`, MissingShotsWindow Load as it is now | `load` | FC refuses; the summary line says why |
| `FolderExplorer._show_cached`, `plots/instance.py` reload, `plots/arrangement.py` `FolderWait` | `cached` | Allowed (with hints) |
| `explorer_live.LiveController` check | `load` + `live` | Disable Live; FC refuses |
| `FolderCache.save` (Live autosave and stop-save), `_start_deferred` | `load` + `save` | New: refused; running: finish (§2) |
| `FolderCache._resume_load` (timed-out load restarts), `_replay` revalidate, `wait_for_clear` resubmit | `load` / scans | FC refuses |
| `FolderExplorer.place_root`, File › Place .helab-root… | `root_create` | Disable; FC refuses |
| `DataRootDialogs.ManualMarkerDialog` Save to folder… | `marker_save` | Disable; FC refuses (Copy stays) |
| `FolderCache.reassign_root` (It's a copy…) | `root_reassign` | Disable; FC refuses |
| `FolderCache.remove_root` (Settings → Data roots Delete .helab-root…) | `root_remove` | Disable; FC refuses |
| `FolderCache._verify_markers` | `roots_verify` | IOS refuses; not scheduled offline |
| `FolderCache._verify_volumes` | `volumes_verify` | Allowed (local volume IDs) |
| `FolderCache._save_subtrees` | `subtree_save` | IOS refuses; the model doesn't queue saves offline |
| `FolderCache._record_scan_outcome` | `scan_history` | No scans offline; IOS refuses |
| `FolderCache.cache_admin` (CacheTab, DataRootsTab, CacheDialogs, folder flags, Folder constants…, presets, identity probe, sweep, budget, inventory) | `cache_admin` | Allowed |
| `FolderCache.find_result` / `save_result` | `result_find` / `result_save` | Allowed |
| `FolderExplorer.clear_data_cache` | `invalidate` | Allowed |
| `HelabMainWindow` Windows drives menu | `drives` | Allowed (no drive I/O) |
| `HelabMainWindow` Record I/O trace | `trace_check` | Allowed |
| `CacheMover`, `main.py` startup recovery | `cache_move` | Allowed |
| `FolderExplorer` right-click Open in File Manager, `DataRootsTab` Show in Finder (`QDesktopServices` / detached launch of a source path) | none (GUI launch) | Disable |
| Native dialogs: Settings Change… folder pickers, Load Scripts…, marker Save to folder… | none (QFileDialog, the user browsing) | Left as is: the user chooses where to look (marker Save is disabled above) |
| Dash server (`127.0.0.1`), Open in browser | none (local) | Allowed: localhost only |

No GUI-process `os.path` / `scandir` call touches source folders (grep of `helab/views`,
`helab/models`, `folder_cache`, `io_service`: only the app's own temp, icon and cache folders).

## Decisions for Tony

- **D1. Mount hints.** A new `mount_hints` table, used only offline for unmounted paths. It needs
  edits in `io_ops/stores.py` and `cache_paths`/`data_roots` (outside my owned paths). Without it,
  offline mode works only while the volume is mounted (e.g. mounted but slow or unreachable).
- **D2. Name and control.** "Work Offline" in the File menu, plus the status-bar button
  `Offline · cached data only`. Remembered across restarts (alternative: session only).
- **D3. Entering.** Live off, with its stop-save allowed to finish; source reads cancelled;
  local-lane work goes on (alternative: ask about Live's save).
- **D4. Listings.** A new kind `listings` with its own Settings → Cache row "Folder listings".
  Purged by age with folder records; removed by Clear all and by a root's Clear cached data…; not
  in the budget (alternative: fold into "Folder summaries").
- **D5. Listing writes.** By `list` helpers after their status: guarded, best-effort, skipped when
  unchanged and under an hour old.
- **D6. Controls offline.** Disabled with a "Not while working offline" tooltip (alternative:
  hidden). This list includes Show in Finder / Open in File Manager.
- **D7. Refused requests.** Never shown as failures; tooltip "Offline: showing saved results from
  <date>"; one INFO log line per kind.
- **D8. Leaving.** Work Online runs Refresh on every tab, then the normal cache-first check
  (alternative: no Refresh).
- **D9. Derived status.** Not saved while offline (`subtree_save` refused).
- **D10. Start-up offline.** The first tab opens at the most recently seen data root (no `resolve`).

## C1 (done): the no-I/O result path

Commit `9c75340`. `FolderCache.replay_snapshot` applies a snapshot in RAM to a tab with no helper
and no revalidation, whatever its age, marked `applied` so Refresh doesn't cancel it. The model's
`apply_snapshot` uses it for other tabs' results. C3's offline listings reuse the same event path.

## C3 plan: the `saved_list` operation and the gate's API (drafted 2026-10-26, after C2)

This is written before Tony's answers on D1, D2 and D8. The names are placeholders where D2 names
the control.

### `saved_list`: a tab's listing, offline

**Request.** In offline mode, a tab's `request_scan(path)` reaches `FolderCache.submit(…, "list")`
as today.

- `FolderCache` rewrites the helper operation to `saved_list`.
  - The shared job stays keyed `("list", path)`, and its subscribers' requests keep operation
    `list`, so the model's request bookkeeping is unchanged.
  - The job's payload gains `listing_only: True` and `offline: True`.
  - `IOService.submit` gets `operation="saved_list"`, a `LOCAL_OPERATIONS` and `CACHE_OPERATIONS`
    entry: the local lane, never paused, never waiting for source work.
- The payload carries the cache options with `"offline": True` (for D1's mount hints) and
  `verified_volumes`.
- In `io_helper.py`, `saved_list` joins `CACHE_ONLY` and dispatches to
  `io_ops.listings.saved_list_folder`.
  - It does **not** join `SOURCE_OPERATIONS`.
  - Wait for Quick Fixes 2 to land: it changes `io_helper.CACHE_ONLY` and the dispatch.

**Helper** (`io_ops.listings.saved_list_folder(path, send, cache_options, verified_volumes)`):

1. Open the store in the local lane (`_open_store(local_lane=True, …)`). A volume not yet verified
   raises `VolumeUnverified`, and the app retries the listing on `volumesVerified`, as for cached
   reads.
2. Read the folder's listing with `read_listing`, then send, in this order:
   - **`data_root`** for the folder: `stores._data_root`, already used by `list`.
   - **`scan_cached`**: the folder's own saved summary (`metadata._send_saved`, as `list` sends
     it).
     - With no summary, it carries one built from the listing's counts (`status`, `count`,
       `raw_count`, `txy_count`, `empty`, `has_dirs`, `files`, `scanned_at` = `listed_at`,
       `signature` ""), so the model's `_restore_summary` shows the counts as saved results
       (`cached_report`).
     - It also carries `subtree_cached`, plus the folder's `disk_cached` / `cache_info` /
       `results` flags.
   - **`entries`**: one per saved name (`path` = `os.path.join(path, name)`), each with its saved
     records from `metadata._saved_folders` and `_result_counts`, exactly as `list` sends them.
     Batches of 128.
   - **`status`**: a new `OfflineListingEvent`, shown below.
3. With no listing row (missing), send `status` with `listed: false`, no entries.
4. A read error ends in `error` with the store's message. The tab shows its usual error row; it is
   not a scan failure, since `FolderCache` doesn't record history for offline jobs.

The new event type, in `helab/io_ops/events.py`:

```python
class OfflineListingEvent(TypedDict):
    """A saved listing's status of its folder (cache-only browsing): no shot lists, counts only."""
    kind: Literal["status"]
    details: Literal[False]
    offline: Literal[True]
    listed: bool                 # False: never listed while online (no saved listing)
    listed_at: float | None      # When the saved listing was made
    empty: bool | None
    has_dirs: bool | None
    # `kind` stays "status": it joins HelperEvent, with tests/test_helper_events.py updated.
```

**In the app:**

- **`FolderCache._on_event`** for an offline `list` job does three things differently:
  - It **stores no `FolderSnapshot`**: saved data is never offered to other tabs as a fresh
    listing.
  - It records no scan outcome or history.
  - It emits no `snapshotChanged`.

  So C1's replay path never sees offline listings, and a tab listing the same folder runs its own
  `saved_list` (a 24 µs read). Subscribers get the events as they come.
- **The model** treats the request as `listing_only` (already: no `_apply_status`, no
  `statusReady`, no automatic load, no details). It applies the summary through the existing
  `scan_cached` and `entries` branches. On `status` with `offline` it sets
  `node.offline_listed_at` (new field), and on `listed: false` it sets
  `node.offline_unlisted = True`.
  - **Rows not listed while online:** no expand arrow (`hasChildren` false); the tooltip says
    "Not listed while online".
  - **Rows with a saved listing:** the tooltip's Subfolders line adds "listed <date>"; the hint
    line is "Offline: showing saved results from <date>".
- **`done`** prunes children not in the listing, as today, so a saved listing is authoritative
  for the tab while offline. A folder deleted since remains in the saved names, which is honest:
  it is what was last seen.

**Above data roots** (no row and no key: e.g. `/Volumes` or `C:\`). `saved_list_folder` answers
`listed: false` plus entries for the known data roots below the path. They come from
`store.root_locations()` turned into source paths through the hints (D1), keeping only the
step-by-step path down. Each such entry carries `{"root_path": true}`.

### Gate API

- **`IOService`:**
  - `offline: bool` and `OFFLINE_OPERATIONS` (the allowed list in §5).
  - `submit` refuses any other operation while offline: returns False and logs one INFO line per
    operation per session.
  - `set_offline(on)` cancels running and queued requests whose operation isn't allowed (§2),
    except loads with `save` already started.
- **`FolderCache`:**
  - `offline` (read-only property), `set_offline(on)` (calls the service's, cancels shared jobs as
    §2 says, emits `offlineChanged(bool)`), and `store_options()` adding `"offline": True`.
  - `submit` rewrites `list` → `saved_list` and refuses the rest of §5 by delivering
    `{"kind": "offline", "operation": op}` and then `{"kind": "done", "offline": True}` to the
    subscriber. `submit` returns True (accepted, answered), so callers never show "Scan queue
    full".
  - `_shared_snapshot_changed` / `replay_snapshot` are unchanged: offline jobs make no snapshots.
- **The model** handles `offline` events: the row stays idle with no error, and the tooltip hint
  is as above.
- **The explorer:**
  - Selection while offline calls only `_show_cached` (RAM, else one `cached` read), never
    `_load_to_ram_cache`.
  - The summary's third line says `Offline · cached <saved_at> · not checked`, or
    `No cached data (offline)`.
- **Live:** `start_live` refuses with "Live is off while working offline".
- **The main window:** the File menu toggle, the status-bar button, the start-up offline path
  (D10), and Work Online (D8).
- **Helper seam:**
  - `io_helper.main` refuses `SOURCE_OPERATIONS`, `resolve` and `roots_verify` when
    `request["cache"].get("offline")`.
  - Tests arm `no_source_io` (draft below), which fails the test if any source operation reaches
    `IOService._start` while offline.

### C3 tests (draft)

The draft is `tests/test_offline_browsing.py.disabled`, not collected (`.disabled`, AGENTS.md), so
strict mypy doesn't check calls to API that doesn't exist yet. At C3 it is renamed to `.py` and
made to pass. xfail would be collected, and mypy would fail on the missing methods. It covers:

- the seam;
- the gate, for every operation;
- entering offline, cancelling source work;
- navigation on saved listings, folders never listed, and paths above data roots;
- selection showing cached data only;
- no cached data, and data evicted from RAM;
- the disabled controls;
- icons;
- plots (one-off run and reopened plot) on cached data;
- the Settings tabs;
- a restart with the source folder deleted;
- Work Online (D8 pending).
