---
date: 2026-10-09
status: settled
name: folder-summary-indicators
description: "Folder summary panel under the path bar, the short main status bar, the Folder details panel with load elapsed/time-left, and the cache-freshness icons, with the wording Tony chose"
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
   Below a data-root location waiting for Same folder or a copy? it says
   `RAM only · this .helab-root is also at another location` (full wording in
   the tooltip), and line 1 shows **Review…**, which opens the data-root
   window at that location (2026-10-18).
3. **Freshness:** `Status scan: 3m ago · … · Live updates off`, or
   `Basic scan failed 2h ago · Retry manually` (see
   [[basic-scan-defaults-and-failures]]).

Text starts 8 px in from the left, for looks.

The explorer has no status row of its own; activity is in the main status bar
and Folder details (both 2026-10-09, below).

## Main status bar (short, 2026-10-09)

Tony asked for a more concise status bar. Left: spinner, then this tab's main
activity in a few words (`FolderExplorer.activity_brief`), `│`, and app-wide
counts only (`IOService.activity_counts`): `Loading run_42 · 63% · ~1:10 left │
3 running · 1 paused · 5 queued`. The tab part is the selected load (`Queued X`,
`Paused X · 63%`, elapsed time until an estimate exists), else `Finding default
folder…`, `Checking folder status · N checked · N failed`, the check's result,
or `N background loads`. Stopping helpers show as `1 stopping (42 s)`. The
tooltip keeps the full wording (`activity_summary`, tab activity, queue
details). Every count is traceable there (Tony saw "2 running" with nothing
naming them, 2026-10-10): `queue_tooltip` starts with `Running:` and one row per
helper in the count (`IOService.running_requests`), e.g. `Load data: /path · 12 s
(current tab)`, then Stopping, Paused and Queued. The selected load's progress bar stays. Right: `CPU 3% · RAM 1.2 GB`
(HeLab only); system totals in the tooltip.

## Folder details (left-bottom panel, 2026-10-09)

Replaced the "Left Bottom Placeholder"; Tony named it **Folder details** (toggle
"Toggle Folder Details"). It took over the plot area's loading text, which was
hidden once any plot dock opened. Single-line elided rows, hidden when empty,
details in tooltips: Folder, State (+ thin progress bar), Files, Time, Rate,
Data, Loaded, Source, Problems, This tab, All I/O. The plot area keeps a
one-line hint in `CentralHint`, which has a second line and `add_widget`
reserved for later tips/quotes (roadmap idea).

Wording, checked row by row on 2026-10-10 against the summary's terms:

- **State:** `Queued`, `Loading`, `Checking for changes` (the check of data
  shown from memory or the disk cache, as the summary's cache line says),
  `Paused`, `… · Listing folder… N entries`, `… · Retrying file (attempt 2 of
  3)`; `Loaded`, `Loaded from cache · not checked yet`, `Check failed ·
  <error>` (cached data still shown), the load error, `Waiting · queues in 3 s
  if still selected` (counts down), `Folder changed · showing previous data` /
  `Showing previous data`, the scan state, `TXY count not checked`, `Not
  loaded`, `No TXY files here`.
- **Files:** the summary's terms: `456 TXY found · 450 loaded · 2 unreadable ·
  4 still being written` (progress while loading; `N TXY found` before).
- **Data:** `1,234 data rows · 12.35MB in RAM`. **Loaded:** `15:43:17 · 5m ago
  · took 1:42` (date shown when not today). `took` appears only when TXY files
  were read; a check answered without reading says `checked, unchanged`
  rather than "took 0:00".
- **Problems** (was "Errors"): `N shots unreadable or with invalid rows`; the
  list includes unreadable files and files whose NaN rows were dropped, so
  "errors" overlapped the Files row's `unreadable`.
- **Hint:** `Select a data folder to begin`, `Queued X…`, `Loading X…`,
  `Checking X for changes…`, `Loading paused: X…` / `Check paused: X…`,
  `Waiting to load X…`, `Loaded X — run a script to plot it`, `Could not
  load|check X — see Folder details`, `Showing previous data for X — see
  Folder details`, `X is not loaded — right-click it › Load data`, `No TXY
  files in X — select a data folder`.

**Elapsed and time left:** `0:42 elapsed · ~1:10 left`, `· estimating…` until
2 s of running time and 3 progress reports, `· finishing…` once every file is
read, `· no progress for 0:08` after 5 s without a progress report (a slow or
hung file: counting down from the last rate would sit at "~0:01 left"). A
paused load shows only its elapsed time. Queued and paused time is not
counted; a retry keeps the elapsed time and measures its rate afresh. The rate
(`12.5 MB/s · 40 files/s`) averages the last 10 s and counts only TXY files
actually read (`read_bytes`, `read_files`), because shots reused from RAM or
the disk cache cost almost nothing and files vary in size. The clock lives on the shared job, so a
tab joining a running load shows the same time. The loading tooltip shows the
timing too; the summary line under the path bar does not.

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
