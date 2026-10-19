# Brief: SMB I/O audit

Floor "SMB I/O audit", branch agent/smb-io-audit, base 486cf56 (dev/v0.0.6). Worker: Claude Code (Opus 5.5, xhigh), Worker role. Review: Codex. Rules: your role, AGENTS.md (Responsive filesystem I/O, Live, Caching), roadmaps/agent-workflow.md.

## Why

Tony sees HeLab sending a lot of requests to the SMB shares. The acquisition PC writes TXY files to those shares while HeLab watches them. Two questions:
1. **What touches the shares, how often, and why?** That covers listings, details scans, cached-data checks (sample stats), loads, Live checks, folder icons, `roots_verify` / `_discover_root` marker reads, retries, refreshes and tab switches.
2. **Does HeLab ever touch a file that is still being written?** That includes stat, open and read, not only reads. Today:
   - settle-age rules (`_settled`, `SETTLE_SECONDS`) decide what is *read*, but fresh files may still be stat'ed by scans, fingerprints and Live
   - `_txy_complete` opens the file to look at its tail
   - icon lookups may touch folders

## Scope now (Tony, 2026-10-19)

**Study the code only. Don't change any logic yet.** You may add optional, toggleable debug output: a trace that is off by default and changes nothing when off. Part 2 below is for later, after Tony has read your findings: don't start it.

## Part 1: study and trace (no behaviour change)


1. **Opt-in I/O trace.** Add `HELAB_IO_TRACE=<file>`, read in `helab/io_helper.py` only, like `HELAB_TEST_READ_GATE`. When set, every source-path operation a helper makes is appended as one JSON line: operation (scandir, stat, lstat, open, read bytes, marker read), path, size/mtime when known, request kind, owner/tab, reason (listing, details, cached check, load, live, icon, root…), and a timestamp. When unset it costs nothing. The GUI process must stay free of source I/O, as now; check that with the trace too (icons run in their own helper).
2. **Inventory.** List every code path that reaches a source folder: which request kind, what triggers it (selection, expand, visible-row scan, timer, Live interval, refresh, tab switch, mount change, retry), and how often it can repeat. Do this by reading the code, then confirm it with the trace.
3. **Scenarios** on a local test share built from the fixtures, with the trace on and offscreen GUI runs, each counting operations per minute:
   - idle with a tree open
   - browse and expand
   - select a cached folder
   - load
   - Live on a folder where a fake writer appends TXY files slowly, including one file written over several seconds with pauses
   - Refresh
   - tab switch
   - a mount change
   - a failing or timing-out folder

   Report the counts in a table and flag anything that repeats without a user action, or more often than its design says.
4. **Real share:** don't touch `/Volumes/dld_output` or any real share. Instead, write Tony a recipe to run the trace himself.

## Part 2: later, not now (fixes, after Tony has seen Part 1)

- Remove redundant or too-frequent operations: anything polled with no change, duplicated across tabs or lanes, or retried without bound.
- **Fresh-file rule:** decide, and propose to Tony, whether a file younger than `SETTLE_SECONDS` (by the listing's own data where possible) may be stat'ed at all, and never opened or read. Note the open in `_txy_complete`, the per-file stats in `_scan`, `_load` and `live_check`, and sample stats. Consider whether a stat on SMB can disturb the writer, e.g. through oplock breaks or Windows sharing modes. Look up what macOS and Windows SMB clients do, and cite sources.
- (Later) every fix gets a test that uses the trace (e.g. "an idle tree makes 0 source operations per minute after the first listing").

## Ownership

You own:
- `helab/io_helper.py`, `helab/utils/io_service.py`, `helab/utils/folder_cache.py`
- `helab/views/FolderExplorer.py`, `helab/models/SnapshotFileSystemModel.py`
- their tests, and a new `tests/test_io_trace.py`

Don't touch `helab/models/ScriptTreeSelector.py`, the plot docks or the settings panel in `HelabMainWindow` (the Settings panel hardening floor owns them), or `helab/analysis/`, `helab/scripts/`. Ask Maestro for anything else.

## Checks and handoff

- The usual full checks: the suite with `--reruns`, `mypy --strict` and pyright, including `--platform win32` / `--pythonplatform Windows`.
- Part 1 ends with `handoff.md`: the inventory, the trace tables, findings ranked by how much SMB traffic they cause, and proposed fixes. Report to Maestro and **wait for Tony's go** before Part 2.
- Commit freely on your branch. Push when Maestro says.
