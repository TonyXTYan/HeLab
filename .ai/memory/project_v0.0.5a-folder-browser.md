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
- **Latent bug:** `get_path_from_setting_or_use_default` in
  `helab/utils/constants.py` checks a saved cache/temp path with
  `os.path.exists` only, not `os.access(..., os.W_OK)`. On the Lab Main PC a
  non-writable saved path crashes HeLab at import (see
  [[lab-main-pc-caveats]]). Still present on 2026-10-08.
