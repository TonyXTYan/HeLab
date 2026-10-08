---
name: project-v0.0.5a-folder-browser
description: "Open threads on dev/v0.0.5a folder-browser work (summary panel, I/O lanes, cache first, scan-failure history): what is committed and pushed, what is open, known bugs"
metadata:
  node_type: memory
  type: project
---

Branch `dev/v0.0.5a`. Committed on **2026-10-08** (one commit, after
`b40547b`): the folder summary panel, cache-freshness icons, shared I/O queue,
scan-failure history, stopping-helper display, live-load fix, and io-lanes
Phases 1–2 (no-progress timeouts, two-step browse). 274 tests passed; mypy
--strict and pyright clean. Design: [[folder-summary-indicators]],
[[folder-io-queue]], [[basic-scan-defaults-and-failures]].

Later the same day: `e01aeef` (saved subfolder status at browse, cache dirs
moved) and `6637528` io-lanes **Phase 3** (foreground/background lanes,
cooperative pausing; 296 tests). Tony confirmed the app works much better.
Phase 4 = these memory updates; the per-scan timing log was dropped (log
spam). Plan: `.ai/sessions/2026-10-08-claude-io-lanes/plan.md`.

Then, still 2026-10-08, pushed to `TonyXTYan/dev/v0.0.5a` with `ec10fc8`:
- `6132a4b`: the folder summary is a fixed 3-line block (no row jumping) and
  the explorer's own status row merged into the main status bar — see
  [[folder-summary-indicators]].
- `5b49dfd`: **cache first** — cached data shows at once from a local lane,
  then one folder stat checks it; files still being written (5 s) are never
  read. 323 passed, 1 skipped. See [[folder-io-queue]]. Not yet tried on the
  real `/Volumes/dld_output` in the full app.

Open threads:
- Probably settled by cache first (`5b49dfd`): re-selecting a folder whose
  data is in RAM used to re-check its files in a load helper (0 reads) before
  showing it. Memory data now shows at once and an unmodified folder costs
  one stat, so the "keep the previous signature" fix is likely unneeded.
  Close it once confirmed on a real data volume.
- Review findings still open: if the disk cache can't open, automatic scans
  are skipped silently; folders over 100k entries record a scan failure.
  (`configure_concurrency` now uses `MAX_SIMULTANEOUS_IO`, fixed in Phase 3.)
- With the default of 1 background lane, folder details and basic scans
  (including a manual Basic scan) wait until the selected load finishes. As
  planned; revisit if Tony finds it slow.
- Status-message review by Codex (2026-10-08): TODO in MEMORY.md, details in
  `.ai/sessions/2026-10-08-codex-status-message-review/`.
- Per-row "Retry 2/3" tree state: not chosen; revisit only if Tony asks.
- An open tooltip doesn't live-refresh "stopping for N s" (Qt limitation;
  accepted).
- Fixed 2026-10-08 (after the big commit): default cache/temp folders moved
  from the system temp dir to `~/Library/Caches/HeLab` (macOS) /
  `%LOCALAPPDATA%\HeLab` (Windows); unwritable saved paths fall back instead
  of crashing (see [[lab-main-pc-caveats]]). Tony's 634 MB cache was moved
  there by the launch-time rename.
- 485 `helab_*` folders sit in macOS `$TMPDIR`, mostly from test runs
  (`helab_test_*` from conftest, `helab_data_*`/`helab_io_*` from helpers).
  The OS cleans them eventually; not deleted (Tony didn't ask).
