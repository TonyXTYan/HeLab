# Handoff: SMB I/O audit, Part 1 (study and trace)

Branch `agent/smb-io-audit` (base 486cf56). Part 1 only: the code's logic is unchanged; an opt-in trace was
added. **Part 2 (fixes) waits for Tony's go.**

## Summary

- **Trace:** `HELAB_IO_TRACE=<file>` makes every helper append each operation it makes on a source folder
  to `<file>`, one JSON line each (what, which file, size and mtime, why, which request and tab). It is off by
  default; then nothing is written and helpers make the same calls. Tests: `tests/test_io_trace.py`.
- **Idle HeLab makes no source operations**: a tree left open, a folder shown, and tab switches all made 0
  operations per minute. Live with nothing new makes ~30 per minute (one folder stat per check, one listing a
  minute).
- **Biggest finding, a bug: data-root verification can loop.** After a listing reports a mount table that
  differs from the one the verification then sees, `roots_verify` re-runs back to back, ~14 times a second
  (27 helper processes a second), each time checking every known `.helab-root` (stat, lstat, open and
  read). Only a new folder listing stops it, and Live never lists that way, so it can run for hours. Mount
  tables do change on their own: three external disks mounted on this Mac during the test run.
- **Live during acquisition is busy, and its saves stat the whole folder:** every check lists the folder,
  opens `.helab-root` once per folder level up to the root, stats a sample of held shots and every new
  file. Every 10 new shots (and when Live stops) an ordinary load saves the folder, statting every TXY file
  three times.
- **Loads stat each TXY file 5 times**, and selecting a folder lists it 2–3 times. A RAM-only folder (no
  `.helab-root`) has no quick check: re-selecting it after 10 s lists it 3–4 times and stats every file
  twice, against 6 stats for a disk-cached folder.
- **Files still being written:** stats, yes (Live every check, loads' fingerprints, details scans). Opens:
  Live opens a file's last 4 kB once it looks settled, including while a writer that stalled for more than
  5 s still has it open. Reads: an ordinary load **read a half-written file** whose writer had stalled for
  more than 5 s, showed it and saved it to the disk cache (12,644 of 25,275 bytes, marked problematic); the
  next check re-reads it.
- **Real share:** not touched. A recipe below lets Tony run the trace himself.

## 1. The trace

Set `HELAB_IO_TRACE` to a **local** file before starting HeLab. Helpers inherit it; it is read in
`helab/io_helper.py` only (`io_helper.TRACE`). While tracing, the GUI adds whom each helper works for.

One line per operation:

| Field | Meaning |
|---|---|
| `t`, `pid` | Wall-clock time; the helper process |
| `op` | `scandir` (one per listing, with `entries`), `stat`, `lstat`, `entry_stat` (a listed entry's stat; `syscall` false on Windows), `read` (a whole TXY file, `bytes`), `read_tail` (Live's last-row check: open, seek, read ≤ 4 kB), `marker_read` (open and read `.helab-root`), `marker_write` / `marker_remove` / `marker_hide`, `icon` (one native icon lookup) |
| `path`, `reason` | The file or folder; why (e.g. `load: checking`, `live: identity`, `cached check: sample`) |
| `size`, `mtime_ns`, `error` | What a stat saw, or the exception's type |
| `request`, `target`, `flags`, `held` | The helper's operation (`live` for Live checks), its folder, the payload fields saying why (`automatic`, `scan_manual`, `listing_only`, `refresh_sequence`, `save`, `cache_base`, `full_check`, `live_since`…), shots held in RAM |
| `owner`, `tabs`, `lane`, `attempt` | From the GUI: the shared job, its subscribers (tab owners, `…:bg`, `…:live`, `…:live-save`), foreground/background/local, retry attempt |

Bookkeeping lines (not source I/O): `request` and `request_end` (seconds, error) per helper, `mounts` (the OS
mount table: psutil's `getfsstat` without waiting on macOS, drive types and mapped drives on Windows, no
server request) and `volume_id` (local volumes only; shares are never asked for an ID).

**Limits:** native calls inside Qt's icon lookup are one `icon` line each (Python can't see them). The trace
counts calls HeLab makes; how many reach the server depends on the SMB client's caches (Part 2). A line is
about 0.6 kB: the scenario runs below wrote 6 MB in 11 minutes, most of it from the verification loop.

The GUI process makes no source operation. FolderCache only normalizes paths lexically, and models render
from memory. A hook in the scenario runs (and `test_the_gui_process_never_touches_source_folders`) recorded
every Python `os.stat`/`lstat`/`scandir`/`listdir`/`open`/`os.path.*` call the GUI made on the share: none.
Qt's native file access isn't visible to that hook; the GUI uses none on source paths (only the user's
Open/Save dialogs).

## 2. Inventory: every code path that reaches a source folder

N = TXY files in the folder, S = its subfolders, D = folder levels from the folder up to its `.helab-root`
(up to `/` without one), K = known data-root locations that are mounted.

| # | Request (lane) | Triggered by | Source operations each time | How often it repeats |
|---|---|---|---|---|
| 1 | `resolve` (foreground) | A new tab without a path (the first tab at startup) | Stat each default folder until one exists (`/Volumes/dld_output` first) | Once per tab |
| 2 | `list`, browse step 1 (fg) | Tab opens its folder; expand; select a folder (unless it has saved counts and a disk cache); Up/Deselect; right-click Retry/Refresh and the status-line Retry (no timeout); toolbar Refresh (`listing_only`: the root and expanded shown branches); Clear data cache; a load that found the saved counts stale; another tab's load whose signature disagreed (snapshot marked stale) | lstat `.helab-root` (cache on), marker read if present or changed, 1 scandir (names only, no per-entry stat) | Repeated requests are answered from memory for 10 s (`FRESH_SECONDS`); after that a request replays memory, then lists again (automatic). Never on a timer |
| 3 | `details`, browse step 2 (bg) | After each completed `list` that isn't Refresh's, unless the folder's snapshot has details or a load of that leaf folder runs; after Refresh for folders whose saved results changed | scandir; a stat per TXY entry (a call each on macOS, free on Windows); lstat per subfolder; stat of the folder | Once per listing |
| 4 | `scan`, basic scan (bg) | Check folder status (manual, recursive); the visible-row auto scan (off by default; skips folders with saved results or failures) | As `details` | Per user action |
| 5 | `icons` (bg) | Visible rows not yet in the session's icon cache, at most 64 per helper; Refresh clears the visible rows' icons | One native lookup per folder | Once per folder per session, again after Refresh |
| 6 | `cached` (local) | Selecting a folder with a disk cache | None: the local disk cache only (confirmed) | — |
| 7 | `load`, quick check (fg) | Selecting a disk-cached folder whose data was last checked over 10 s ago; the cache-first check beside a cached read | Stat the folder; stat a sample of cached files (Medium: first, last and max(3, 1%) random) | Per selection |
| 8 | `load`, full (fg/bg) | Selecting an uncached or changed folder (auto-load), Load data, queue mode, Retry/Refresh (`full_check`), a RAM-only folder's re-check, per-file retries, a load moved back to the queue | scandir; per TXY file read: 5 stats (checking, before read, after read, verifying, cache-save verifying) and the read; per file reused: 3 stats (2 without a cache save); stat of the folder | Per selection or action |
| 9 | `load` + `live`, Live check (fg) | `live_interval` (3 s) after the previous check ends, while Live is on | Stat the folder. If its mtime is the last safe one (not within 2 s, nothing unsettled, listed within 60 s): nothing more. Else: scandir; D marker opens (walking up to the nearest `.helab-root`) and the mount table; sample stats of held shots (2 + max(3, 1%)); a stat per TXY not held; for files settled by age and unchanged since the last check: stat, tail read, then stat, read, stat; stat of the folder | ~18 checks a minute |
| 10 | Live save: `load` with `save` (bg) | Every `live_autosave_shots` (10) new shots; Live off, another folder, tab switch or close, quit | Row 8 for the whole folder: scandir, 3 stats per TXY file, reads of the new shots | Every 10 new shots |
| 11 | `roots_verify` (bg, runs last) | Startup; a listing reports a mount table other than the last verified one; **after each verification while the table listings reported differs from its own (the loop, finding 1)** | Per known mounted root: stat the folder, lstat and read its `.helab-root`; plus local volume IDs | See finding 1 |
| 12 | `volumes_verify` (local) | With every `roots_verify` request | Local volumes' IDs only (diskutil, GetVolumeInformationW); no share | With 11 |
| 13 | `root_create`, `root_reassign`, `root_remove` (fg) | The user's Place / It's a copy / Delete `.helab-root` | Marker write or replace or remove, and reads | Per user action |
| 14 | Duplicate-root hint (in a listing) | A listing finds a `.helab-root` also known elsewhere | lstat of the marker at each other location (possibly another share) | Per sighting |
| — | Local only, no source I/O | `cached`, `subtree_save`, `scan_history`, `cache_admin`, `invalidate`, `cache_move`, `drives` | None | — |

The GUI process has no row: it makes none.

## 3. Scenario runs (counts from the trace)

**Setup:** `scenarios.py` ran offscreen HeLab on a test share built from `tests_sample_data`: a local folder
with a `.helab-root`, dated runs of 30–300 TXY files (~100 kB each) and a sibling folder without a
`.helab-root` (RAM only). Settings were private, real defaults (settle age 5 s, Live 3 s, check level
Medium, autosave every 10 shots), except per-file read timeouts shortened to 3/4/5 s. A fake writer (its own
process) appended files during Live. Session 1 starts with an empty cache; session 2 restarts on it. The
share is local APFS, not SMB: the counts are HeLab's calls; timings and server requests differ on SMB. Full
per-phase tables: `trace-session1.md`, `trace-session2.md`.

| Phase | s | Helpers | Source ops | Ops/min | What they were |
|---|---|---|---|---|---|
| S1 startup | 2 | 8 | 11 | — | resolve, list + details + icons of the top folder |
| **S1 idle, tree open** | 60 | 0 | **0** | **0** | — |
| S1 expand 4 folders | 2 | 9 | 36 | — | 4 × (list + details), icons |
| S1 select and load run_a (120 TXY) | 2 | 3 | 724 | — | 2 listings; 600 stats (5 per file); 120 reads |
| S1 reselect run_a within 10 s | 4 | 0 | 0 | — | Answered from memory |
| **S1 idle** | 15 | 0 | **0** | **0** | — |
| S1 reselect run_b after 15 s (disk cached) | 1 | 1 | 6 | — | Quick check: folder stat + 5 samples |
| S1 second tab, RAM-only run_r (120 TXY) | 2 | 7 | 611 | — | 4 listings; 4 stats per file (no cache save); 120 reads |
| **S1 four tab switches, 15 s apart** | 65 | 0 | **0** | **0** | Shown data isn't re-checked on a tab switch |
| S1 toolbar Refresh | 2 | 11 | 46 | — | 5 relistings, 5 details, 13 icons |
| S1 Retry/Refresh on run_b (40 TXY) | 2 | 2 | 84 | — | list + full check: 2 stats per file, no reads |
| S1 select and load run_live (30 TXY) | 1 | 3 | 184 | — | As run_a |
| **S1 Live on, writer adds 12 shots in 64 s** | 64 | 30 | 460 | **434** | 19 checks, all listing: each 1 scandir, 5 marker opens, 5 samples, ~2 new-file stats; 11 tail reads; 1 autosave (42 × 3 stats) |
| S1 Live on, writer done, files settle | 15 | 5 | 35 | 140 | 2 listings, then one-stat checks |
| **S1 Live on, nothing new** | 60 | 20 | 31 | **31** | 19 one-stat checks + 1 listing a minute (with its 5 marker opens and 5 samples) |
| S1 Live off: save | 2 | 1 | 129 | — | scandir; 42 × 3 stats; 1 read |
| S1 load run_stall while a writer stalls mid-file | 9 | 4 | 73 | — | The half-written file read and cached (section 5); one verification, as the first listing since three disks mounted reported them |
| **S1 mount table reported changed, 30 s** | 30 | **803** | **1,242** | **2,483** | 414 `roots_verify` + 389 `volumes_verify`, one every 72 ms, until a listing |
| S1 a listing reports the real table | 16 | 4 | 12 | — | The loop stops after one more verification |
| S1 folder that can't be listed (permission) | 20 | 2 | 2 | 6 | 1 listing attempt, error, no retry |
| S1 file read that hangs (3 attempts) | 14 | 4 | 128 | — | Each attempt relists and restats all 20 files; completed reads kept |
| **S1 idle at the end** | 60 | 0 | **0** | **0** | — |
| S2 startup (cache known) | 2 | 9 | 14 | — | As S1, plus one root check |
| **S2 idle** | 60 | 0 | **0** | **0** | — |
| S2 expand 3 folders | 2 | 7 | 22 | — | 3 × (list + details), icons |
| S2 select cached run_a | 1 | 2 | 6 | — | Cached read (no source I/O) + quick check |
| S2 select cached run_b with one new shot (41 TXY) | 2 | 4 | 174 | — | 3 listings (list, details, load); 41 entry stats + 41 × 3 stats; 1 read |
| S2 RAM-only run_r: reselect after 15 s, unchanged | 5 | 4 | 249 | — | 4 listings; 120 × 2 stats |
| S2 disk-cached run_a: reselect after 15 s, unchanged | 1 | 1 | 6 | — | Quick check |

Nothing ran without a user action except Live checks, Live's saves and the verification loop. The only
operation that repeated more often than designed is the loop. (Live and the per-file retries run as
designed; Live's listing on every check during acquisition follows its rule, see finding 3.)

## 4. Findings, ranked by SMB traffic

1. **`roots_verify` loops back to back (bug).** `FolderCache._on_event` re-submits `_verify_roots()` when a
   verification ends with `_mounts_observed != _roots_mounts`: the mount table the last listing reported is
   not the one this verification saw. Only a listing (`list_folder`'s `mounts_seen`) updates
   `_mounts_observed`, so until the user browses again every verification ends the same way and starts
   another: ~14 per second, two helper processes each (`roots_verify` runs `verify_volumes` itself and
   `_verify_roots` also queues a `volumes_verify`), each one statting every known root, lstatting its marker
   and opening and reading it, and running diskutil for hinted local volumes. Live checks and loads don't
   report mounts, so a Live session keeps it going. Trigger: the mount table changes between a listing and
   the verification it asked for (which runs last, after background work and paused while the foreground
   works). Mount tables do change: three external disks mounted on this Mac during the 8-minute run (the
   next listing then asked for a verification), and in an earlier dry run a toolbar Refresh found a changed
   table too. *Fix (Part 2):* re-verify only when a listing has
   reported a table not yet asked about (compare with `_verify_asked`), at most every few seconds; run
   `verify_volumes` once per request.
2. **Live saves stat the whole folder three times.** An autosave (every 10 new shots) and the save when Live
   stops are ordinary loads: a full listing, a fingerprint pass, a verify pass and a cache-save verify pass
   over every TXY file, plus reads of the new shots. For N files that is 3N stats per 10 shots: for a
   1,000-shot run, 3,000 stats every 10 shots. *Fix:* save Live's data without re-statting held shots (trust
   them as Live does, with its sample check), and skip the cache-save verify when nothing was read after
   the first one.
3. **Live checks during acquisition list every time.** While any new file is unsettled, or the folder's
   mtime changed, `live_since` is None and the next check lists. Each listing check: a scandir of the whole
   folder (raw and TXY), D `.helab-root` opens walking up to the root (5 in the test: four absent, one
   read), samples of held shots (2 + max(3, 1%)) and a stat of every file not held. At 18 checks a minute
   that's ~18 scandirs, ~90 marker opens and ~90 (small folders) to ~220 (1,000 files) sample stats a minute. *Fix:* check the identity with
   the root's own marker once (its path is known after the first check) or once a minute; when the folder's
   mtime hasn't changed and only known files are unsettled, stat just those files instead of listing;
   sample less often.
4. **Loads stat each TXY file 5 times, and selections list 2–3 times.** Fingerprint (`load: checking`), before
   and after the read, the verify pass and the cache-save verify pass; reused files 3 times. Selecting an
   uncached folder lists it twice (the tree's listing and the load's); a cached folder with one new shot
   three times (listing, details, load). A 1,000-shot folder: ~5,000 stats and 1,000 reads. *Fix:* take the
   fingerprint from the load's own listing (free on Windows), drop the before-read stat (the fingerprint was
   just taken), skip the cache-save verify when nothing was read since the verify, and let the load's
   listing stand in for the tree's.
5. **RAM-only folders have no quick check.** `_unchanged_since_cache` needs the cache's dataset row, so a
   folder without a `.helab-root` (or with Don't cache) is fully re-checked on every re-selection after 10 s:
   3–4 listings and 2N stats (249 operations for 120 files, against 6 for the same folder with a disk cache).
   If Tony's shares have no `.helab-root` yet, every re-selection pays this. *Fix:* the same quick check from
   the RAM dataset's own file list and listing time.
6. **Browsing details:** each expand is a listing plus a details scan (a stat per TXY file on macOS, an lstat
   per subfolder). A day folder with 50 runs: 50 lstats per expand. Refresh relists the shown branches,
   reruns details where saved results changed, and looks every visible folder's icon up again. *Fix:* details
   for visible rows only; keep icons across Refresh.
7. **Startup:** the first tab resolves `/Volumes/dld_output` (a stat), lists it, scans its details and looks
   its visible rows' icons up; a verification checks every known root. Bounded, once per start.
8. **Retries are bounded:** a stuck file read gets 3 attempts, each relisting and restatting the folder
   (completed reads are kept). A failing listing isn't retried. Fine as designed.
9. **Tests can touch the real share:** the four test files that build `HelabMainWindow()` open a default
   tab, which resolves `/Volumes/dld_output` and, if it's mounted, lists it and scans its details and icons.
   Every agent's test run on Tony's Mac would then touch the real share. Not mounted here today. *Fix:*
   conftest replaces the default folders with a temporary one.

## 5. Files still being written

From the code, confirmed by the trace (the fake writer marked each file's write window):

| What | Touches a file still being written? |
|---|---|
| stat | **Yes.** Live stats every new file each check (21 stats of files under 5 s old in the run; `d_txy_forc1004` 3 times during its 7.5 s write). Loads stat every TXY file in their fingerprint pass, including young ones (then leave them out). Details and basic scans stat every TXY entry. |
| open + read of the last 4 kB (`_txy_complete`) | **Yes, when the writer stalls for more than 5 s.** Live opens a file settled by age and unchanged since the previous check. `d_txy_forc1009`, stalled 8 s mid-file, was opened while the writer had it open; Live saw the half row and didn't read it. |
| read | **Yes, in ordinary loads when the writer stalls for more than 5 s.** `_load` reads every file settled by age, with no whole-row check and no second look. `d_txy_forc2001`, selected 6.5 s into an 8 s stall, was read half-written, shown, and saved to the disk cache: 12,644 of 25,275 bytes, marked problematic (the half row became NaN). The next check re-reads it: its size changed, and the last file is always in the sample. Live never read a file during a write. |
| marker reads, icons | Folders and `.helab-root` only, never TXY files. |

Part 2 questions (not researched yet, as the brief says): whether a stat, an open or a read from macOS's or
Windows' SMB client breaks the writer's oplock or lease, or meets its sharing mode, and so slows or stalls
the converter; and then a fresh-file rule, for example: decide age from the listing's own data; never open
or read a file younger than the settle age or not seen unchanged across two looks; loads apply Live's rule.

## 6. Proposed Part 2 order (for Tony's decision)

1. Stop the verification loop (finding 1), with a trace test: "a changed mount table makes at most one
   verification until a listing reports another".
2. Live saves without full re-stats, and skip the repeated verify pass (findings 2 and 4).
3. Cheaper Live listing checks: identity and samples (finding 3).
4. A quick check for RAM-only data (finding 5).
5. Fresh-file rule for loads (section 5), after the SMB research.
6. Fewer listings per selection; details and icons (findings 4 and 6); the tests' default folder (finding 9).

Each fix gets a trace test, e.g. "an idle tree makes 0 source operations per minute after the first
listing" (true today: worth pinning down first).

## 7. Recipe: trace the real share (Tony)

macOS, from a checkout of this branch:

```bash
cd ~/GitHub/HeLab && git fetch && git switch agent/smb-io-audit   # or a worktree of it
source venv/bin/activate
export HELAB_IO_TRACE=~/Desktop/helab-trace-$(date +%Y%m%d-%H%M).jsonl   # a local file, never on the share
python -m helab
```

Use HeLab as when you saw the traffic: leave a tree open, browse, load, run Live during acquisition. Note
the times of what you do. Then quit HeLab and summarise:

```bash
python .ai/sessions/2026-10-19-claude-smb-io-audit/trace_summary.py "$HELAB_IO_TRACE" \
  --under /Volumes/dld_output --minutes > ~/Desktop/helab-trace-summary.md
```

The summary gives per-request, per-reason counts and rates, the most repeated paths, a per-minute timeline,
and operations on files modified under 5 s before. Look for `roots_verify` lines arriving several a second
(finding 1). Without phase marks the whole trace is one phase; split it with your noted times if useful.
Expect ~0.6 kB of trace per operation.

Windows lab PC (PowerShell): `$env:HELAB_IO_TRACE = "$env:USERPROFILE\Desktop\helab-trace.jsonl"; py -m helab`
(lines are appended without a lock there; the summary skips a garbled one, if any).

Optional, to see what other programs do to the share (Finder, Spotlight, previews), not only HeLab:
`sudo fs_usage -w -f filesys | grep dld_output` (Ctrl-C to stop). To count SMB requests on the wire:
`sudo tcpdump -i any -w ~/Desktop/smb.pcap port 445`, then Wireshark › Statistics › Service Response Time ›
SMB2 (not readable if the share encrypts SMB3 traffic).

Don't run `scenarios.py` against a real share: it builds and deletes its own test share.

## 8. Checks

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: 992 passed, 2 skipped, 2 xfailed,
  **no RERUN**.
- `mypy helab/ --strict`, `mypy tests --strict`, each also with `--platform win32`; `pyright helab tests`,
  also `--pythonplatform Windows`: all clean.
- `tests/test_io_trace.py`: 7 tests (section 1).
- Scenario runs: `scenarios.py OUT --session 1` then `--session 2` (11 minutes), summaries in this folder.

## 9. Proposed doc changes (for the coordinator)

- AGENTS.md, Testing: add the debug trace beside the test seams: "`HELAB_IO_TRACE=<file>` (`helab/io_helper.py`
  only): every helper appends each source-folder operation to `<file>` as one JSON line; off by default.
  Summarise with `.ai/sessions/2026-10-19-claude-smb-io-audit/trace_summary.py` (to move into `dev/` with
  Part 2)."
- `roadmaps/_readme.md`: an item "SMB I/O audit Part 2" with section 6's order, and finding 1 as a bug.
- `.ai/MANUAL_TODO.md`: "Trace HeLab on the real share (recipe in the audit's handoff, section 7)".

## 10. Files

- Code: `helab/io_helper.py` (trace and wrappers), `helab/utils/io_service.py` (`IORequest.trace`, `owners_of`),
  `helab/utils/folder_cache.py` (`_owners_of`), `tests/test_io_trace.py`.
- This folder: `brief.md`, `notes.md`, `handoff.md`, `scenarios.py`, `fake_writer.py`, `trace_summary.py`,
  `trace-session1.md`, `trace-session2.md` (paths shown as `<out>`). Raw traces were in the session
  scratchpad, not kept.
