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
`helab/io_ops/scanning.py`, `SnapshotFileSystemModel`, `FolderExplorer`.

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
  the disk cache's `folder_summaries` table (since S5 of
  `roadmaps/cache-storage-and-settings.md`; store-v3 since data roots) and are restored before scanning,
  so counts show as soon as a folder is visible.

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
- Stored in the disk cache's `scan_histories` table, written
  only by isolated helpers. Keeps the latest 10 failures, ordered by a scan
  revision (not wall-clock time) and keyed by folder path within its SMB share
  (or by local path on ordinary volumes). A delayed write cannot restore old
  suppression after a later successful check. Mount device and inode numbers
  do not reset a failure. A record saved under a plain path while a share is
  unmounted is not used after an SMB share mounts at that path.
- A flagged folder skips **every automatic entry point**: startup, scrolling,
  toggling auto-scan, and snapshot revalidation. The saved state is read before
  any work is scheduled. Last successful counts, status, and loaded data are
  kept with their original dates.
- Browsing, Load data, and manual Basic scan / Refresh stay available. **Only
  a fresh successful scan clears the flag.** Replaying cached results or
  loading data does not. Clearing the loaded-data cache keeps the history.
- If the history can't be saved, suppression stays session-only with a
  warning. If it can't be read (the cache won't open, or its read fails),
  scans that aren't manual are skipped: a saved failure may be there.
- A folder with **no disk cache** (the cache off, or off by design for it: no
  `.helab-root` above it, a root pending confirmation, or an NFS/AFP/WebDAV
  mount) has no saved history. Its details and automatic scans run, guarded by
  the session's history alone (`FolderCache.submit` checks it for every
  automatic entry point), and failures stay in RAM without the "could not be
  saved" warning: Folder details already says RAM only (2026-10-18; before,
  such folders got no details or automatic scans, so only a load showed their
  status).

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
