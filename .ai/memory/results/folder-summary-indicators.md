---
date: 2026-10-08
status: settled
name: folder-summary-indicators
description: "Folder summary panel under the path bar (selected/counts/cache/freshness lines, Deselect/Cancel buttons) and the cache-freshness icons, with the wording Tony chose"
metadata:
  node_type: memory
  type: result
---
The summary panel under the path bar in `FolderExplorer`
(`helab/views/FolderExplorer.py`), and the freshness icons in
`SnapshotFileSystemModel`. Built in the 2026-10-07 Codex session (raw
transcript in `.ai/session-export-codex/`).

Why it exists: on startup the default folder (`/Volumes/dld_output`) loaded its
TXY data with almost no visible sign that anything was loaded.

## Layout (top to bottom, no vertical padding)

1. **Selected: <relative path>** with a **Deselect** button. Shown only when
   the selection differs from the viewed path. Deselect returns to viewing the
   path. Its tooltip says what happens to a running or queued load under the
   current load-on-select mode.
2. **Counts:** e.g. `456 TXY found · 123 loaded (27%)` (`· Paused` while
   the current tab browses), `· Not loaded`,
   `· Previous data`, `· Changes detected`, raw-shots-only, empty folder,
   "TXY count not checked · Retry manually". A **Cancel** button (aligned under
   Deselect) appears while loading. While scanning:
   "Scanning folder content for TXY files…".
3. **Cache:** `Cached data found` / `Cached data loaded` (+ `· Cached 5m ago`),
   `Creating cache…`, `Cache updated 2m ago`, `No cached data`, plus a freshness
   hint. The tooltip has origin, reuse counts, and the exact save date.
4. **Freshness:** `Status scan: 3m ago · … · Live updates off`, or
   `Basic scan failed 2h ago · Retry manually` (see
   [[basic-scan-defaults-and-failures]]).

All four lines have the same row height. Text starts 8 px in from the left,
for looks.

## Decisions and wording

- **Completed load counts take priority** over basic-scan counts: loading
  reads every file, so it's more accurate. The summary describes what this
  tab displays. A load finished in the background does not count as
  displayed.
- Tony disliked "disk cache available" (confusing). It became **"Cached data
  found"** (exists, not used yet) / **"Cached data loaded"** (this tab's data
  came from it).
- The two "not checked" lines repeated each other, so line 3 is cache state
  and line 4 is scan age/freshness. Relative ages ("5m ago") update live; exact
  dates go in tooltips. Summary rows stay single-line.
- Load-on-select modes (Settings): `cancel`, `finish` (default: finish the
  current load in the background), `queue` (queue folders kept selected
  for 3 s).

## Freshness icons (memory-only hints, never trigger scans or loads)

- Compare the data-cache save date and the basic-scan date with the folder's
  observed modification time.
- **Package + clock** (`cached_older`): data cache possibly outdated. Tony
  chose it from candidates in Debug → Icons. It's in the status icon group,
  which also lists every icon.
- **Amber clock overlay** on the matching/status icon: scan results older than
  the folder.
- A later TXY fingerprint difference confirms the data cache has changed. A
  missing date shows "unknown". Metadata observations carry their own dates, so
  an older snapshot replay can't overwrite newer folder modification metadata.
