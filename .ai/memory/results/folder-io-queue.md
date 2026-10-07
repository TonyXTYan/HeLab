---
date: 2026-10-08
status: settled
name: folder-io-queue
description: "Folder browser I/O: one queue with a foreground lane (current tab's browsing + selected load) and background lanes (default 1) that pause cooperatively, 60 s no-progress timeouts (per-file 15/20/30 s load retries), two-step browse, helpers hold slots until confirmed exit, and how stopping/paused helpers are shown"
metadata:
  node_type: memory
  type: result
---
How the active folder browser schedules filesystem I/O, and why. Code:
`helab/utils/io_service.py` (`IOService`), `helab/io_helper.py` (isolated
helper processes), `helab/utils/folder_cache.py` (shared jobs per tab).

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
  between consecutive expands). A paused helper keeps its slot (cap = the
  setting) and its no-progress timer is frozen. Tiny history/cache-clear
  writes don't pause.
- Selecting B while A loads (finish mode): A takes a free background slot and
  pauses, or, with none free, is stopped and requeued to restart from its RAM
  shots.
- Display: "· Paused" on summary line 2, paused rows show the queued glyph,
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
