---
date: 2026-10-08
status: settled
name: folder-io-queue
description: "Folder browser I/O: one shared queue (default 1 slot), 60 s no-progress timeouts (per-file 15/20/30 s load retries), two-step browse, helpers hold slots until confirmed exit, and how stopping helpers are shown"
metadata:
  node_type: memory
  type: result
---
How the active folder browser schedules filesystem I/O, and why. Code:
`helab/utils/io_service.py` (`IOService`), `helab/io_helper.py` (isolated
helper processes), `helab/utils/folder_cache.py` (shared jobs per tab).

## One shared queue

- Folder browsing, basic scans, loads, and cache writes share **one app-wide
  queue and concurrency limit**. Default **1**, configurable in
  Settings → General as "Simultaneous folder I/O operations" (max 32).
  Legacy separate scan/load limits do not override this default.
  Why: Tony wanted basic scans and loads to stop clogging I/O on the lab's
  network volumes (2026-10-07).
- Order: navigation and loads come before bulk scans, FIFO within each group.
  Explicit promotion of the selected folder's load is kept.
- Requests are deduplicated by `(owner, generation, path, operation)`.

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
- `details` is skipped while a load of that folder runs; the load sends and
  saves the same folder summary. Empty signature = unknown, never "changed".

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

## Not done (Tony's choice, 2026-10-08)

- Per-row "Retry 2/3" state in the tree (suggestion 4) — not chosen.
- Fast-fail idea: superseded by single 60 s no-progress attempts (Phase 1).
