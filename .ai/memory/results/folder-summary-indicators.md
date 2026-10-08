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

A fixed 3 lines (2026-10-08), so the tree's rows never move when the summary
changes. Earlier the block was 2-4 lines plus wrapping, and rows could jump
between the two clicks of a double-click. Every line is single-line and elided
(`ElidedLabel`); the full text is in `text()` and tooltips.

1. **Counts**, prefixed by the selected folder's relative path when it differs
   from the viewed path (`run_042 › 456 TXY found · 123 loaded (27%)`; the path
   gets its full width or at least 2/5 of the free space, middle-elided). Wording:
   `· Paused` while the current tab browses, `· Not loaded`, `· Previous data`,
   `· Changes detected`, raw-shots-only, empty folder, "TXY count not checked ·
   Retry manually"; "Scanning folder content for TXY files…" while scanning.
   Buttons on the right: **Cancel** (loading or listing retry), **Retry**
   (moved from the path bar; folder or load error, not while loading),
   **Deselect** (selected subfolder). All the same fixed width.
2. **Cache:** always shown. `Cached data found` / `Cached data loaded`
   (+ `· Cached 5m ago`), `Creating cache…`, `Cache updated 2m ago`,
   `No cached data`, plus a freshness hint; `Cache not checked` before any
   cache information, `No data to cache` for folders without TXY files. The
   tooltip has origin ("Loaded from disk cache"), the cache-miss reason, reuse
   counts, and the exact save date.
3. **Freshness:** `Status scan: 3m ago · … · Live updates off`, or
   `Basic scan failed 2h ago · Retry manually` (see
   [[basic-scan-defaults-and-failures]]).

Text starts 8 px in from the left, for looks.

The explorer has no status row of its own. Its tab activity (`Finding default
folder…`, basic scan progress `N scanned · N scanning · N paused · N queued ·
N failed` or its result, `N background loads: 1 loading, 2 queued`) leads the
main window's status bar, followed by `│` and the app-wide
`IOService.activity_summary()` (zero counts omitted, icon/cache-clear/history
work named, "Saving N data caches" only for real cache writers, `N operations
queued`). A spinner (space kept when idle) and the selected load's progress
bar sit in the status bar too.

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
