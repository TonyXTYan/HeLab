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
