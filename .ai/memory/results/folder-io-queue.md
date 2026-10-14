---
date: 2026-10-08
status: settled
name: folder-io-queue
description: "Folder browser I/O: cache-first display via a local lane (one-stat check when unmodified, files still being written skipped); one queue with a foreground lane (current tab's browsing + selected load) and background lanes (default 1) that pause cooperatively, 60 s no-progress timeouts (per-file 15/20/30 s load retries), two-step browse, helpers hold slots until confirmed exit, and how stopping/paused helpers are shown"
metadata:
  node_type: memory
  type: result
---
How the active folder browser schedules filesystem I/O, and why. Code:
`helab/utils/io_service.py` (`IOService`), `helab/io_helper.py` (isolated
helper processes), `helab/utils/folder_cache.py` (shared jobs per tab).

## Cache first (2026-10-08)

Tony: "cache shouldn't need to queue behind IO tasks". Cached results were not
showing because selection listed the folder, then the load waited for a
foreground slot, paused while the tab listed anything, and listed and statted
every TXY file before reading the cache. On a slow `/Volumes/dld_output`
nothing appeared.

- A **local lane** (`LOCAL_CAP` 2) runs `cached` reads (and small batched
  `subtree_save` writes of derived subfolder status): local disk cache only,
  never paused, never waits for source I/O. The data shows as unchecked:
  line 1 `… loaded (cached)`, cache line `Checking for changes…`.
- The check is the usual load with the shown dataset as its RAM base. If the
  cache has no unsettled files and the folder's mtime is not newer than the
  cache's `snapshot_at`, the helper answers with **one folder stat**
  (`unchanged`). Tony chose the plain mtime comparison: lab clocks are
  internet-synced, so no skew margin. Otherwise it lists and merges.
- A TXY file rewritten in place doesn't change the folder's mtime, so the
  folder stat can't see it (Codex review of PR #5, 2026-10-13). Tony's rule:
  **TXY files are written once; a repaired or regenerated file gets a new
  name**, never overwrites existing data. The escape hatch is right-click
  Retry / Refresh: the folder's next check (at once for the shown folder) is a
  `full_check`, comparing every file's size and mtime with the cache.
- Review of PR #5 (2026-10-13), Tony's decisions:
  - The check runs **beside** the cached read, not after it; RAM data counts
    as checked only for 10 s, so returning to a folder checks it again.
  - The folder stat also stats sample cached files: levels Swift (last),
    Fast (first+last), **Medium default** (+ max(3, 1%) random), High
    (+ max(10, 3%)), Full (always list). Not inodes: they differ by OS, file
    system and mount, and change on remounts.
  - Cached/held shots missing from the folder: stop before reading, hide the
    cached data. The check for missing shots runs before the cache is
    unpacked; the folder's RAM data is dropped and not shown again until a
    load completes. That flag is session-only (Tony: users will usually
    rebuild the cache anyway), kept for up to 8192 (2^13) folders, oldest
    dropped first.
  - Mismatch handling (Tony, 2026-10-13): **one list window, not a popup per
    folder**, so a large scan appends rows instead of flooding the screen
    (non-modal; opens without taking focus; once closed it stays closed until
    the next warning; status-bar "⚠ N mismatched" reopens it). Rows: folder,
    "missing of known", TXY files now, found time · load/scan, answer. Buttons
    Load as it is now / Don't load on the selected rows.
  - At 2, 4, 8… mismatched folders loads and scans **pause** (Tony asked for
    stop + tell; pause chosen so nothing is lost, with Cancel all loads and
    scans offered), banner says why and to check the mounted drive. From 8:
    Skip mismatched folders and keep going (session-only; no more holds or
    window, rows still added).
  - Scans detect it too: details / folder status check compare the listing
    with the dataset record's fingerprint (one SQLite row, no data file, no
    Blosc). Folders flagged Don't cache are ignored.
  - Pause (not cancel) at 2^N: Tony agreed. Load as it is now reuses old
    cached shots whose number, size and mtime_ns all match a current file;
    anything else is read again (Tony agreed, 2026-10-13).
- Review of the uncommitted work (2026-10-14), Tony's decisions:
  - Leaving a folder while its check runs beside the cached read: a check
    that hasn't found files to read is **cancelled with its read** (the cache
    holds the data; the next visit checks again). One reading new files is a
    real load: in Finish/Queue mode it moves to the background **with** its
    read, and they stop together. Moving every check with its read was
    rejected: holding ↓ would unpack the cache of every folder passed.
  - A full listing that finds the cache complete (none still being written)
    moves `snapshot_at` forward to the listing's start: otherwise any non-TXY
    change after caching (Finder's `.DS_Store`, analysis output) turned the
    quick check off for good. The quick check itself never moves it.
  - Missing shots: Retry stays enabled (mounting the right drive is a fix);
    the line adds **Review…**, which opens the list window on that folder.
  - **Wait for the selection to settle** (Finish, Cancel): Tony asked for
    0.3 s when I/O is busy, +0.1 s per queued I/O task (all kinds), at most
    1 s, and none when idle. "Busy" is load-based (running, queued or
    stopping, or an automatic load started < 0.3 s ago): any running I/O
    would make most clicks wait for background details/icons, and without
    "stopping" or "started moments ago" a held arrow slips through (each
    press cancels the last load, so I/O looks free). The folder's own
    listing isn't counted. In normal use I/O is idle and a click loads at
    once; the wait is for held arrows, unfamiliar clicking, heavy I/O and
    fresh starts. Cursor navigation itself is never delayed.
  - **One rule for "counts as checked"** (`FolderCache.counts_as_checked`):
    the tab's label and the memory answer of a load had drifted apart (cached
    data matched by a scan from the last 10 s showed "Checking for changes…"
    while its check was answered from memory). Tony: there shouldn't be two
    rules. The check levels answer a different question (how thorough a check
    is); a matching scan fingerprinted every TXY file, as thorough as Full.
- Selecting a folder with saved counts and a disk cache skips the listing.
- Check failure keeps the cached data: `Check failed`, error on line 1, Retry.
- **Files still being written:** TXY written once and never modified, but
  another PC may be writing one right now. Files modified within 5 s, or whose
  size/mtime changes while read, are not read or cached; loads and scans leave
  them out of signatures (otherwise scan and load disagree and the data is
  dropped and reloaded until the file settles). Line 1:
  `N still being written`; the cache's `unsettled` count forces a full check
  next time, because a growing file does not change the folder's mtime.
- Live updates are still not implemented ("we will implement live update later").

## One queue, foreground and background lanes (2026-10-08, io-lanes Phase 3)

- One app-wide queue. Requests are deduplicated by
  `(owner, generation, path, operation)`. Order: navigation and loads before
  bulk scans, FIFO within each group; the selected load can be promoted.
- **Foreground lane** (outside the setting): the current tab's listings
  (`list`, `resolve`) and its selected load. One listing and one load at once;
  at most **3** foreground processes including stopping ones, so a dead mount
  can't pile them up. A listing silent for **3 s** no longer holds the listing
  slot. In queue mode the tab's queued loads stay foreground, one at a time,
  so "queue" still means a new selection waits.
- **Background lanes**: Settings → General "Simultaneous background I/O
  operations" (key `simultaneous_folder_io_operations`, default **1**, max 32).
  Background loads, `details`, basic scans (manual and automatic), cache
  writes, history saves. Why: Tony wanted scans and loads to stop clogging the
  lab's network volumes (2026-10-07), and then "the GUI comes first": what he
  is looking at must never wait behind background work (2026-10-08).
- `FolderCache.foreground_owners` decides the lane; the current
  `FolderExplorer` claims it (tab switch, first tab, load-mode change).
  Switching tabs turns the old tab's work into background work.
- **Pausing** is cooperative: a `pause` file in the helper's private folder,
  checked between entries/files (a call already in progress finishes), with
  `paused`/`resumed` events. SIGSTOP was rejected: not on Windows, and it
  can't stop a call already stuck. While the foreground works, background
  loads/scans pause and none start; the selected load pauses while the tab
  lists. Resume **0.5 s** after the foreground goes idle (no stop–start
  between consecutive expands). The 0.5 s keeps an already paused load
  paused; a selected load starting after the listings ended is not paused
  (2026-10-14: each click paused its own load, right after the folder's own
  listing, for ~0.5 s). A paused helper keeps its slot (cap = the
  setting) and its no-progress timer is frozen. Tiny history/cache-clear
  writes don't pause.
- Selecting B while A loads (finish mode): A takes a free background slot and
  pauses, or, with none free, is stopped and requeued to restart from its RAM
  shots.
- Display: "· Paused" on summary line 2; a row's status icon stays while it
  is checked or loaded. A load shows in the RAM badge's place (green
  spinner = load, grey dotted circle = queued, green circle-pause = paused;
  icons drawn once). A listing/status check is a blue spinner: full size in
  the status icon's place before the first status, then a small one at the
  status icon's bottom right, like the outdated clock (2026-10-14),
  queue tooltip "Paused while the current tab browses or loads", main status
  bar "N loads paused" / "N scans paused". Tony confirmed the app "works so
  much better now" (2026-10-08).

## Timeouts and retries (changed 2026-10-08, io-lanes Phase 1)

- Timeouts measure **time without progress**. Helpers send heartbeats at
  least once a second while listing or checking files.
- Listings, scans and a load's listing phase: **one attempt, 60 s without
  progress, no retry**. Why: on 2026-10-08 all three 15/20/30 s attempts on a
  hung `/Volumes/dld_output` timed out, and big folders timed out while still
  progressing.
- Only a load's per-file reads retry: **15, 20, 30 s** per file; the next file
  gets a fresh budget. While a file is read only file events count as progress.
- Right-click Retry / Refresh and the status-line Retry list one folder with
  **no timeout** ("Retrying… 1 min 20 s · 3,200 entries", Cancel / Esc). A
  load retry keeps its per-file timeouts.
- A timed-out load restarts from the shots already in RAM after fingerprint
  validation.
- Cancellation stops retries. A load that has already delivered its data and
  is only writing the disk cache gets `FINISH_TIMEOUT = 120 s` and is never
  retried or failed.

## Slots are held until the helper is confirmed dead

- Running helpers, including background cache writers and cancelled or
  timed-out helpers, **occupy a slot until process exit is confirmed**.
  Lowering the limit lets running work finish.
- A daemon reaper confirms exit (`process.wait()`) without waiting for pipe or
  artifact readers. An in-memory exit flag frees the slot even if the `exit`
  message is delayed. Duplicate exit notifications are matched by request
  identity, so an old reader can't free a new retry's slot.
- **A retry never runs beside the attempt it replaces**: it stays queued
  ("held") until the old helper has exited.

### Observed 2026-10-08: killed helpers can take ~50 s to exit

Timing a basic scan of `/Volumes/dld_output/20241021_RT_low_mod_occ_350_mus`
(network volume): each killed helper needed ~47–53 s to exit, so ~100 s of a
2 m 45 s failure was spent waiting for helpers to die. Most likely they were
blocked in a filesystem call, and the kill can't take effect until that call
returns. With the default of 1 slot, all other I/O waits meanwhile.

## Two-step browse (2026-10-08, io-lanes Phase 2)

- `list`: one scandir, names only, gives counts/status at once; "Listing… N
  entries" in the summary. `details`: the full scan, in the background after
  the listing, for signature, dates and subfolder badges.
- The listing also reads each subfolder's saved summary/history/cache flags
  from the local cache (never the source). Fixed 2026-10-08: without this, a
  loading root skipped step 2, so `/Volumes/dld_output`'s 67 subfolders showed
  no saved status and auto visible scans rescanned them one by one.
- `details` is skipped while a load runs only for folders without
  subfolders; the load sends and saves the same folder summary. Empty
  signature = unknown, never "changed".

## How stopping helpers are shown (decided 2026-10-08)

Tony saw "Stopping previous operations: X" then "Queued: X" for the same
folder and found it confusing. Now:

- Each stopping helper is **one tooltip row**, merged with the retry or
  repeated request it holds, e.g.
  `Browse folder: <path> — timed out after 60 s without progress · stopping for 42 s · requested again; starts when it exits`.
  Load file retries read `attempt 1 of 3 timed out after 15 s without progress on <file> · … · attempt 2 of 3 starts when it exits`.
  Other row endings: "no retries left", "requested again; starts when it
  exits", "timed out while saving the data cache".
- Held requests are **not** listed or counted as queued.
- The tab status line and the main status bar name the longest-stopping
  operation: `Retry 2 of 3 waiting for timed-out basic scan to stop (42 s)`,
  plus "· N more stopping".
- After 5 s of stopping, the tooltip says the volume is probably not
  responding. If unrelated queued work is waiting on the held slot, it says so.
- Known limitation: an open tooltip doesn't refresh its seconds counter until
  hovered again.

- A requeued load's row reads "moved to the background queue · stopping ·
  restarts from the shots already loaded when it exits"; the status line says
  "Waiting for background load to stop".

## Not done (Tony's choice, 2026-10-08)

- Per-row "Retry 2/3" state in the tree (suggestion 4) — not chosen.
- Fast-fail idea: superseded by single 60 s no-progress attempts (Phase 1).
- Console logging (Tony, 2026-10-08): problems only, never routine browsing.
  One warning per failure of any operation ("Browse folder failed: <path> —
  <reason>"), each timeout attempt, a stopped helper still alive after 5 s and
  when it finally exits (with its stop time), a full queue, and folders over
  the entry limit; a requeued load is logged at info level.
- Per-scan timing log (planned io-lanes Phase 4): not added. Tony worried it
  would spam the log; if ever needed, make it opt-in or one summary line per
  slow scan.
