# SMB I/O audit: working notes (Part 1)

Branch `agent/smb-io-audit`, base 486cf56. Part 1 only: study and trace, no behaviour change.

## What was added

- `HELAB_IO_TRACE=<file>` (read in `helab/io_helper.py` only, as `io_helper.TRACE`): every source-folder
  operation a helper makes becomes one JSON line (`_trace`). Wrappers `_stat`, `_lstat`, `_isdir`,
  `_entry_stat`, `_scandir` (`_TracedListing`), `_read_marker`, `_read_txy_file`, `_mounts`, plus lines for
  Live's tail read (`read_tail`), icons (`icon`), marker writes and removals. Off: the wrappers make the same
  calls (same functions looked up at call time, so tests' patches still apply) and nothing is written.
- Each line: `t`, `pid`, `op`, `path`, `reason`, size/mtime_ns when known, `request` (operation; `live` for
  Live checks), `target`, `flags` (payload fields saying why: automatic, scan_manual, listing_only,
  refresh_sequence, revalidate, save, cache_base, full_check, live_since…), `held` (shots in RAM), and from
  the GUI (only while tracing, `IORequest.trace`): `owner` (job producer), `tabs` (its subscribers, via
  `FolderCache._owners_of`), `lane`, `attempt`. Bookkeeping lines: `request`, `request_end` (seconds, error),
  `mounts` (the OS mount table, no source I/O), `volume_id` (local volumes only).
- `tests/test_io_trace.py` (7 tests): off unless the variable names a file; off writes nothing and uses the
  plain scandir iterator; exact per-operation counts of a listing, scan and load; identical event kinds with
  tracing on and off; a Live check's folder stat, samples, tail read and identity marker reads; real helpers
  note their request, tab and lane; the GUI process makes no Python-visible call on the share while
  browsing, expanding, loading and refreshing (helpers do).
- Session scripts (not in the package): `scenarios.py` (offscreen HeLab on a test share, phase markers,
  GUI-process hook, fake writer), `fake_writer.py`, `trace_summary.py` (tables per phase; files touched
  while written or young).

## Slips

- While checking which shares are mounted I ran `ls -d /Volumes/*`: that stat'ed each mount point once
  (11 smbfs mounts of lab PCs), at most one attribute query per share. `/Volumes/dld_output` was not
  mounted. Since then only `mount` (the table) was used.

## Side observations (not SMB)

- A fresh store at startup: `cache_admin` (sweep or inventory) failed once with "database is locked" when
  two local-lane helpers opened the new store together (`Clean up disk cache failed … database is locked`).
  Startup's later jobs worked. Worth a look on the cache-store side; not part of this audit.
- Tests that build `HelabMainWindow()` (4 files) open a default tab, which resolves
  `DEV_POTENTIAL_DATA_PATHS`, starting with `/Volumes/dld_output`: a helper stats it and, if mounted, lists
  it, runs its details scan and fetches icons. On a Mac with the share mounted every such test run (and
  every agent's) touches the real share. Not mounted on this Mac today.

## Part 2 (2026-10-19, after Tony's go via Maestro)

Codex agreed with all six findings (review-codex.md); Maestro's constraints were followed. Commits, each
with its trace test:

- cff8df3 trace exactness (Codex's caveats): marker_open/fstat/read with real bytes (optional `trace`
  keyword on `data_roots.read_marker`, approved by Maestro, no other change there), `is_dir` counts per
  listing, real bytes read, no `is_symlink` probe, marker hiding traced, network trace files refused,
  stronger no-change test (full events and exact calls).
- 7b9b7e8 roots_verify loop.
- 0e9c0ad load stats (fingerprint from the listing, second verify only after rereads, a changed cached
  leaf folder takes the load's own status instead of a relisting and details scan).
- 2b55d59 half-written files in loads (recent file not ending with a newline: still being written);
  Live reads a ready file once instead of tail-then-file.
- c53a058 RAM-only quick check.
- 1e83f20 Live: pending-file checks without listing; the known root's marker only.
- 65a06b3 dedicated Live save from RAM (`io_helper.save_held`, arrays handed over by IOService).

Decisions worth recording:
- Live identity: the known root's marker is read on every listing check (one open), not once a minute;
  a missing or invalid marker walks again; another root at the folder stops Live. Location identities
  (no marker) use the mount table only. Codex warned once-a-minute alone would weaken remount protection.
- Live's pending path only answers "still waiting"; once a pending file is ready it lists the folder, so
  identity, the held-shot sample and the summary are unchanged for any check that reads.
- The Live save checks every held file by the listing's stats (no sample trust), hands all held arrays to
  the helper (local temp, written by the reader thread, not the GUI thread). Possible later optimisation:
  hand over only shots not in the cached dataset and unpack the rest.
- Loads' half-written rule is the trailing newline only (a whole row with an empty field is a damaged
  file's, read as problematic); Live keeps its stricter rule. RECENT_SECONDS = 600: older files ending
  mid-row are damaged, not being written.
- Not done (not among the six): tests' default tab resolving /Volumes/dld_output (conftest is shared),
  details per visible row only, icons kept across Refresh.

Test-tree note: the floor's `tests/__pycache__` was cloned from Ground, so tracebacks show Ground's
paths (`../../../HeLab/tests/...`) for unchanged test files; the code run is the floor's.
