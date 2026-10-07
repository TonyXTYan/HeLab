---
name: project-v0.0.5a-folder-browser
description: "Open threads on dev/v0.0.5a folder-browser work (summary panel, shared I/O queue, scan-failure history, io-lanes plan): what is committed, what is next, known bugs"
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

Next: io-lanes **Phase 3** (foreground/background lanes, pausing) and
**Phase 4** (timing log, docs), in
`.ai/sessions/2026-10-08-claude-io-lanes/plan.md`. Each phase waits for Tony's
go-ahead.

Open threads:
- Undecided: after a names-only listing, re-selecting a folder whose data is
  in RAM but not shown re-checks its files in a load helper (0 reads) instead
  of reusing memory instantly. Fix offered: keep the previous signature when
  the listing's TXY names are unchanged (risk: an in-place modification shows
  only after the details scan).
- Review findings still open: if the disk cache can't open, automatic scans
  are skipped silently; folders over 100k entries record a scan failure;
  `configure_concurrency` hardcodes 32 instead of `MAX_SIMULTANEOUS_IO`.
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
