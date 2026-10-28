---
name: project-v0.0.5a-folder-browser
description: "Retired project note: dev/v0.0.5a folder-browser work shipped in v0.0.5a1 (2026-10-19); its open threads are tracked in known-issues, MANUAL_TODO and the roadmap. Kept: default cache folders, two choices not to revisit unasked"
metadata:
  node_type: memory
  type: project
---

**Retired 2026-10-28.** The `dev/v0.0.5a` folder-browser work (summary panel, I/O lanes, cache
first, scan-failure history; `5b49dfd`, `ec10fc8`) and the cache rebuild shipped in v0.0.5a1
(`main` `5a8ae6f`, 2026-10-19). Design: [[folder-summary-indicators]], [[folder-io-queue]],
[[basic-scan-defaults-and-failures]], [[disk-cache-and-budgets]]. Its open threads now live
elsewhere:

- folders over 100k entries record a scan failure; one background lane makes details and status
  checks wait for the selected load: `roadmaps/known-issues.md`;
- the "keep the previous signature" check on a real volume: `.ai/MANUAL_TODO.md`;
- automatic scans skipped silently when the disk cache can't open: `roadmaps/_readme.md`
  (Near term).

Still only here:

- Default cache/temp folders moved (2026-10-08) from the system temp dir to
  `~/Library/Caches/HeLab` (macOS) / `%LOCALAPPDATA%\HeLab` (Windows); unwritable saved paths
  fall back instead of crashing (see [[lab-main-pc-caveats]]).
- Not chosen, revisit only if Tony asks: a per-row "Retry 2/3" tree state. Accepted: an open
  tooltip doesn't live-refresh "stopping for N s" (a Qt limitation).
