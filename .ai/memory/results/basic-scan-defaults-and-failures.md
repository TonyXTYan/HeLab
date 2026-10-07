---
date: 2026-10-08
status: settled
name: basic-scan-defaults-and-failures
description: "Basic scan: auto-scan of visible folders off by default and never rescans scanned folders; persisted failure history suppresses auto scans; magnifying glass + ! badge replaces 'Unavailable'"
metadata:
  node_type: memory
  type: result
---
Rules for basic scans (metadata-only checks of folder contents, without
reading the TXY files) in the active folder browser. Code:
`helab/utils/scan_history.py`, `helab/utils/folder_cache.py`,
`helab/io_helper.py`, `SnapshotFileSystemModel`, `FolderExplorer`.

## Defaults (Tony, 2026-10-07)

- Automatic basic scanning of visible folders is **off by default**. Toggle it
  in View or Settings → General.
- When on, it scans **only folders without saved scan results**, regardless of
  how old those results are. Tooltips show the cached age, but only a manual
  Basic scan / Refresh rescans. (Turning auto-scan on used to rescan cached
  folders; Tony called that a bug.)
- Manual Basic scan covers folders in view, the current folder, or any
  recursion depth, with progress and per-tab cancellation. Metadata-only scans
  never start automatic dataset loads.
- Scan summaries (raw/TXY counts, status, signature, scan date) persist in
  `data_ram_cache` under versioned keys and are restored before scanning, so
  counts show as soon as a folder is visible.

## Failure history (Tony, 2026-10-07/08)

Why: a folder on a slow network volume timed out three times on every
startup, holding up all other I/O.

- **One failure = the final outcome of a scan**: one 60 s no-progress
  timeout (since 2026-10-08; older records show "3 attempts") or an error. A
  browse listing error also records one; only a full scan (basic scan or
  browse details) clears it. Shared tabs record it once.
- **Not failures:** cancellation, queue rejection, and errors while saving
  metadata (a timeout while saving metadata after a completed scan must not
  mark the scan failed).
- Stored under `("folder-scan-history-v1", path)` in `data_ram_cache`, written
  only by isolated helpers. Keeps the latest 10 failures, ordered by a scan
  revision (not wall-clock time) and tied to the folder's `(st_dev, st_ino)`
  identity. A delayed write, or a different folder now at the same path, can't
  restore old suppression.
- A flagged folder skips **every automatic entry point**: startup, scrolling,
  toggling auto-scan, and snapshot revalidation. The saved state is read before
  any work is scheduled. Last successful counts, status, and loaded data are
  kept with their original dates.
- Browsing, Load data, and manual Basic scan / Refresh stay available. **Only
  a fresh successful scan clears the flag.** Replaying cached results or
  loading data does not. Clearing the loaded-data cache keeps the history.
- If the history can't be saved, suppression stays session-only with a
  warning.

## Display

- Badge: **option B, magnifying glass + "!"** (`ICON_SCAN_FAILED`, amber
  `#c48618`, tabler `ZOOM_EXCLAMATION`). It's in the Debug → Icons status
  group, and coexists with the matching and cache icons.
- When the badge shows, the status column's **"Unavailable" text is hidden**
  (Tony, 2026-10-08: the icon is enough; details go in the tooltip).
  "Cancelled", and errors on folders without a saved failure, keep their text.
  Text is drawn after the badges so they never overlap.
- Freshness line: `Basic scan failed 2h ago · Retry manually`. The tooltip has
  exact dates, attempts, the reason, the last successful scan, and recent
  history.
