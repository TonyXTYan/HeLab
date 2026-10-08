---
date: 2026-10-09
status: settled
name: folder-row-tooltip
description: "Folder-tree row tooltip: one fact per line in a fixed order (path, activity, Here, Subfolders, Folder modified, Status cache, Data cache, RAM, failures, one hint), each matching the row's icons; start times not counters; an open tooltip is re-shown when its row changes"
metadata:
  node_type: memory
  type: result
---
The row tooltip in the active folder tree (`SnapshotFileSystemModel._tooltip`),
rewritten 2026-10-09 after an audit found it crowded (up to ~20 lines, the same
date three times, raw state words like `idle`) and contradicting the icons
("Status: unknown" beside a `something` icon; a clock icon beside "No newer
folder modification time observed").

Fixed order, `Label: value`, lines only when they apply:

```
/data/D
Listing folder… since 00:30:49 · showing last results   ← busy only (or "Last check failed: … · showing earlier results")
Loading dataset…                                        ← load state only
Here: 2 shots, all converted                            ← own files ("no TXY files", "empty folder", "not checked yet")
Subfolders: none                                        ← "3 · TXY data in 1 · may be outdated", "not listed yet", "… · saved <date>"
Folder modified: 2026-10-09 00:45:18 (just now)         ← stated once, the reference for both caches
Status cache: 2026-10-09 00:43:18 (2m ago) · may be outdated   ← or "Status checked: …" (this session)
Data cache: 2026-10-09 00:43:18 (2m ago) · may be outdated
Data: shared RAM dataset open (read-only arrays)        ← mirrors the RAM badge
(scan-failure history block, unchanged)
Select the folder to check it again.                    ← one hint, never while busy
```

- The status line's label says its source (Tony, 2026-10-09): `Status cache:` =
  loaded from a saved summary and not rechecked (`cached_report`), with the full
  freshness note; `Status checked:` = checked in this session, noting only a
  later sign of change (`may be outdated` / `changes detected`), never
  `folder not modified since` or `freshness unknown`.
- **Status and Data cache are separate lines** (Tony, 2026-10-09), each
  with its own date and freshness suffix: `folder not modified since`,
  `may be outdated`, `changes detected (different TXY fingerprints)` or
  `freshness unknown`. The folder's modified time is stated once, on its own
  line, so nothing repeats; there is no separate "May be outdated:" line.
- A derived status's freshness sits on the Subfolders line, so the clock on the
  icon is explained by the line for whichever status it shows. When a listed
  subfolder is the outdated part, the hint says to select that subfolder.
- Here + Subfolders together explain the icon, so they never conflict: the icon is
  the own status when the folder holds data, else the derived one.
- Folders without subfolders always say `Subfolders: none` (listed, or known
  from the saved summary's `has_dirs`).
- **Qt does not rebuild an open tooltip while the mouse rests.** Busy lines give
  a start time (`since 00:30:49`), never elapsed counters, and
  `FolderExplorer._refresh_open_tooltip` re-shows an open tooltip when its row
  emits `dataChanged`. Relative ages ("2h ago") can still lag while it stays open.
- Ages come from the wall-clock scan date (`scanned_at`), the same instant as the
  printed date.
- The folder summary panel's tooltips (freshness wording) are separate and
  unchanged: [[folder-summary-indicators]].
