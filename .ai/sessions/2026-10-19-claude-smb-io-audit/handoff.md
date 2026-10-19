# Handoff: SMB I/O audit

Branch `agent/smb-io-audit` (base 486cf56). **Part 2 (fixes) is done** and comes first below, with
round 3 (Tony's decisions: settle age only; the trace as a per-session menu switch); Part 1 (the study,
the "before") follows unchanged in substance. Codex's reviews of Part 1 and of Part 2 (at e3802af, with
two corrections, now done): `review-codex.md`.

## Part 2 summary

Tony's rule: fix what Codex agreed with; Codex agreed with all six findings. Each fix is its own commit
with trace tests, following Codex's constraints and Maestro's notes:

| Commit | Finding | What changed |
|---|---|---|
| cff8df3 | Trace caveats | `.helab-root` reads traced as `marker_open`, `marker_fstat`, `marker_read` (real bytes); each listing counts its `is_dir` checks; reads record the bytes actually read; no `is_symlink` probe while tracing; marker hiding's stat and chflags traced; `HELAB_IO_TRACE` on a network drive or share refused with a warning (round 3: the variable is gone, see below); the no-change test compares full events and the exact calls on the folder. |
| 7b9b7e8 | 1. roots_verify loop | Only a listing reporting a mount table not yet asked about asks for a check (`_verify_asked`); a check that saw another table than listings reported never re-queues itself; a table reported while a check runs gets one follow-up; a failed check waits for the next listing; the marker check follows the local volume check and reuses its IDs (no second diskutil); marker checks at most every 5 s as a backstop. |
| 0e9c0ad | 4. Load stats | The fingerprint comes from the load's own listing (free on Windows); the before- and after-read stats stay; the cache-save verify pass runs only if files were read after the load's own verify; a changed cached leaf folder takes the load's status instead of a relisting and details scan. |
| 2b55d59, 8079252, then removed | 6. Half-written files | 2b55d59 and 8079252 dropped a recent file whose last row wasn't whole, in loads and Live. **Removed by Tony's decision** (round 3): settle age only. A TXY write never takes more than 5 s, a content check is an assumption about the file's format, and a writer paused at a row's end would pass it anyway. Kept: the 5 s settle age, Live's metadata-only "unchanged since the previous check", the before/after-read stats, and Live opening a ready file once (one open instead of tail-then-file). |
| c53a058 | 5. RAM-only quick check | Data in RAM without a disk cache gets the quick check from its own load's listing time, names and identity: same location (mount table), same data root (one marker read), folder unmodified since, nothing unsettled then, the sample unchanged; never for Retry/Refresh. |
| 1e83f20 | 3. Live checks | While the folder's mtime is the one its last listing saw, a check stats only the files still being written; once one is ready, it lists as before (identity, sample, read). The identity check reads only the marker the first listing found, on every listing check (not once a minute); a missing or different marker there is looked for again or stops Live (remount). |
| 65a06b3 | 2. Live saves | A dedicated save: the RAM dataset's arrays go to the helper (written to its private local folder by IOService's reader thread, off the GUI thread); the helper lists the folder once, checks every held file's size and mtime from that listing (no sampling), the identity, missing and changed files, then saves the full dataset under a load's guard, budget and pending-save rules (`_write_dataset`, shared with `_load`). No TXY file is read. |
| b71a698 | 5 and 4, follow-up | The rerun showed a duplicate: selecting a RAM-held leaf folder relisted it and rescanned its details. Now it's checked by its load (as disk-cached folders already were), whose listing updates the row on a change; a load's listing marks a leaf folder's snapshot as just checked, so other tabs don't relist it. |
| 6eb6a9c | Windows test | The read_marker trace test expects no steps for a folder-named `.helab-root` on Windows (can't be opened as a file there). |
| d59f6a9 | Trace destination | `HELAB_IO_TRACE` is resolved (realpath) before the network check, so a local link to a share is refused; UNC prefixes refused given or resolved. Superseded in round 3: the trace always goes into the temp folder. |
| 47d9def | Round 3: settle age only | Settle age only, by Tony's decision; the converter's temp-name rename remains the real fix. Loads and Live no longer look at a file's last row (`_whole_last_row`, `RECENT_SECONDS` and Live's `_txy_complete` removed); a file is read once it is 5 s old (`SETTLE_SECONDS`) and, in Live, unchanged in size and mtime since the previous check (`seen`, metadata only). The stalled-writer tests now document that a writer stalled for longer than the settle age is read as it is, by design. |
| 9773b8a (C below changes the files) | Round 3: trace switch | **Help › Record I/O trace (this session)**, off at every start and never saved. Each recording is a new `io-trace-<date>-<time>.jsonl` in `<temp folder>/io-traces` (`IOService.start_io_trace`; a second one within the same second gets `-2`), never next to the data or at a path the user gives; helpers get the file with each request (`request.trace["file"]`). While on, the status bar shows "● I/O trace" (its tooltip names the file); **Help › Show I/O trace folder** opens the folder. The terminal gets one INFO line when it starts (`I/O trace on: <path>`) and one when it stops (`I/O trace off: <path>`), unticked or on quitting (`IOService.shutdown`), nothing else. Turning it on with earlier traces there asks once: "N earlier I/O traces (X MB) in <folder>." with **Keep** (default) or **Delete old traces** (only earlier `io-trace-*.jsonl` files there, never the new one); with none, no question. Nothing is deleted automatically. The test seam `HELAB_TEST_IO_TRACE=<file>` (helpers only) replaces the user-facing `HELAB_IO_TRACE`, and the network/realpath refusal of a given path is gone. |

### Round 3 notes

- **The temp folder is not refused at startup.** Only the cache folder is (`refuse_unsafe_cache_dir`);
  `constants.py` takes `DIR_TEMPS` from the setting or the default without the network/synced check. So
  the switch checks it itself (the cache folder's `cache_location_problem`, in a helper since F): on a
  network or synced temp folder it is refused, unticked, with a warning naming the folder and pointing to
  Settings → General (a changed temp folder applies after a restart). Refusing the temp folder at startup,
  as the cache folder is, would be a change in `constants.py` (not mine).
- One wording change outside my owned paths: `data_roots.read_marker`'s docstring said ``HELAB_IO_TRACE``;
  it now says "Help › Record I/O trace". No code change there beyond the approved `trace` keyword.
- **Review fixes (C):** each recording is a folder `io-trace-<date>-<time>` (made with an exclusive
  `mkdir`, so on, off and on within a second gets `-2`) holding one `<pid>.jsonl` per helper
  (`io_helper._trace_path`): the MSVC C runtime emulates `O_APPEND` with a seek and a write, so helpers
  sharing a file could silently overwrite each other's lines on Windows. A PID reused later appends after
  the exited helper's lines. `trace_summary.py` and `compare_traces.py` read a recording's folder (or a
  single file of an earlier build). Delete old traces works per recording (its `.jsonl` files, then the
  emptied folder; older single files too); a file Windows won't delete because a running helper still has
  it open is kept, and a message says how many were kept and where (`delete_io_traces`).
- **Review fix (D):** a recording's name is reserved when it starts: its folder is made then, with an
  exclusive `mkdir`, before any helper writes, so on, off and on again within one second always gets a
  new folder (`-2`). **"Off" isn't immediate for helpers already running:** a helper started while the
  trace was on keeps tracing into that recording's folder until it exits (a long load or a save can go
  on after `I/O trace off` has printed); only helpers started later aren't traced. A recording's last
  lines can therefore come after its off line; the next recording never gets them.
- **Review fix (F), off the GUI thread:** there is no startup result for the temp folder to reuse (only
  the cache folder is checked at startup), so turning the trace on submits a local-lane helper,
  `trace_check` (`io_helper.trace_check`): it runs the network/synced check (`realpath`, the mount table
  via psutil, which a disconnected mapped drive can stall) and lists the earlier recordings with their
  files and sizes. The window waits for its answer (`_on_trace_check`) and only then asks Keep/Delete and
  starts the recording; a 10 s no-progress timeout bounds it (then "HeLab couldn't check its temp folder…"
  and the item is unticked); unticking meanwhile cancels the check and ignores its answer. The GUI thread
  then only deletes the listed files (if asked) and makes the recording folder, in a temp folder the
  check found local. (Show I/O trace folder still makes the io-traces folder on the GUI thread, as the
  user's own request to open it.)
- `HelabMainWindow`: only the Help menu items, the status-bar note and the Keep/Delete question
  (`_toggle_io_trace`, `_on_trace_check`, `_refuse_io_trace`, `_ask_delete_old_traces`,
  `_show_io_trace_folder`); no plot-dock code touched.
- Tests: `tests/test_io_trace.py` (the seam, a helper tracing to the file its request names, the folder,
  the name, the two INFO lines, the refusal), `tests/test_helabMainWindow.py` (off at start; none, Keep and
  Delete; refusal; Keep as the dialog's default).

### Review item E (Tony's decision, 2026-10-20): a recently read shot that changes is read again

- **Rule.** A held shot that **Live itself read** less than **5 minutes** ago
  (`FolderExplorer.LIVE_REREAD_SECONDS` = 300, measured from when Live delivered it, per shot in
  `LiveSession.read_at`; read again: from then) that changes in size or mtime is read again, like a new
  file (settled by age and unchanged a check apart, before/after-read stats), and replaces the held one
  (`loaded` without it in `memory_shots`, its new array as a `shot` event, `live_reread`: shot, path, old
  and new size and mtime). Live goes on; nothing is listed as mismatched. Until it is read, it waits as
  a file still being written does (`live_seen`, counted as still being written), and listings stat it
  besides the sample. Older held shots that change still stop Live (`shots_missing`, changed). The
  initial load's shots aren't Live's: one of those changing while Live watches still stops Live.
- **Why 5 minutes.** A partly read shot is noticed by the next listing (the next new shot changes the
  folder; the newest held shot is in every check level's sample) or at the latest by the once-a-minute
  listing, or by the next save (every 10 new shots, and on stop), which checks every held file. Five
  minutes covers a writer pausing a few minutes plus that delay. Detection costs nothing extra: no new
  stats except the changed shot's own until it's read.
- **`save_held`:** the save gets the same `recent` list. A recent shot that changed is read again before
  the save (once settled, unchanged while read; else saved as held and counted as unsettled) and saved
  as it is now, not reported as a mismatch; older changed shots still stop the save. Fixed after the
  recheck at 660ba9c: such a save now sends the folder's summary with its new fingerprint before
  `loaded` (`scan_summary`, adopted as a Live check's: `_adopt_load_summary(live=True)` for
  `save_memory` jobs). Without it FolderCache saw the new signature differ from the snapshot's and
  cancelled the save before its disk write (the tab got "cancelled", RAM kept the partial shot). This
  was chosen over exempting saves from the signature check because it keeps the folder's status (tree
  row, counts, signature) matching the data the save writes, as Live checks do; an exemption would
  have left the snapshot with the partial shot's signature. Tests of the tab now run saves through the
  real `save_held` (`tests/test_live.py`'s `replay`).
- **Telling the user.** The tab's Live line and Folder details' state row say "Shot 1009 changed after
  it was read (writer paused > 5 s?): read again" (several: "Shots …") for **one minute** after the
  re-read (`LIVE_REREAD_NOTE_SECONDS`; new shots don't clear it, so it stays long enough to be seen at a
  shot every few seconds); the Live line's tooltip adds when and the rule. The note is kept per folder
  (`FolderExplorer._reread_notes`), so after Live off, once its save ends, it stays in Folder details
  and on the summary's third line for the rest of the minute. One WARNING per shot: `Live:
  shot N changed S s after Live read it, read again: <path> (size A → B bytes, mtime X → Y). The converter
  writing to a temporary name and renaming it avoids this.` The re-read shot counts as not yet cached, so
  the next save writes its new data.
- **Ownership:** Folder details' state row is in `helab/views/FolderDetailsPanel.py`, outside my owned
  paths: one small append there (`explorer.live_reread_note(path)`), as Maestro's brief asked for the
  note in Folder details. Everything else is in owned files.
- **Tests:** `tests/test_live_check.py` (a recent changed shot waits once, then is read again and
  replaces the held one; an older one, or with `recent` naming others, still stops the check),
  `tests/test_io_trace.py` (`save_held`: a recent changed shot is read again and saved as it is now; not
  recent: a mismatch, nothing saved), `tests/test_live.py` (the tab: read again, Live goes on, the note on
  the Live line and in Folder details, the WARNING with path and sizes, the note gone after a minute, then
  a shot read longer ago that changes stops Live as mismatched).
- **Proposed AGENTS.md Live wording** (replacing "otherwise `shots_missing` … is planned)." in the Live
  paragraph): "otherwise `shots_missing` (`reason` root or changed) stops Live and lists the folder as
  mismatched, except for a held shot Live itself read in the last 5 minutes (`LiveSession.read_at`,
  `FolderExplorer.LIVE_REREAD_SECONDS`, sent as `recent`): when it changes, its writer paused longer than
  the settle age, so it is read again like a new file and replaces the held one (`live_reread`), by
  Tony's decision. The Live line and Folder details say "Shot N changed after it was read (writer paused
  > 5 s?): read again" for a minute, and one WARNING per shot logs its path, old and new (size, mtime) and
  the seconds since Live read it. Saves (`io_helper.save_held`, from RAM: one listing, every held file
  checked by its stats, no TXY read) read such a shot again first. A new file is read only when settled
  by age and unchanged since the previous check (`seen`): metadata only, by Tony's decision; its content
  isn't checked. The converter writing to a temporary name and renaming it remains the real fix."

### Before and after (the same scenarios, rerun)
### Before and after (the same scenarios, rerun)

Same setup as Part 1 (offscreen HeLab, local APFS test share, real defaults, read timeouts 3/4/5 s),
rerun after round 3 (with the trace on as the menu sets it); one scenario differs: Live's writer now
pauses 4 s mid-file instead of stalling 8 s (Part 1), as a real write would.
Counts are HeLab's calls on the share; marker reads are counted as opens in both runs. Only rows that
changed, plus idle rows; full tables: `compare-session1.md`, `compare-session2.md`; per-phase detail:
`trace-session{1,2}-before.md`, `trace-session{1,2}-after.md`.

| Phase | Helpers | Listings | Stats | Marker opens | Reads | Tail reads |
|---|---|---|---|---|---|---|
| Idle, tree open (60 s, both sessions) | 0 | 0 | 0 | 0 | 0 | 0 |
| Tab switches (4 × 15 s) | 0 | 0 | 0 | 0 | 0 | 0 |
| Select and load run_a (120 TXY) | 3 | 2 | 602 → **482** | 0 | 120 | 0 |
| Select and load run_b (40 TXY) | 2 | 2 | 202 → **162** | 0 | 40 | 0 |
| Select and load run_live (30 TXY) | 3 | 2 | 152 → **122** | 0 | 30 | 0 |
| **Live, writer adds 12 shots in 64 s** (pause 4 s, was a stall of 8 s) | 30 | 20 → **17** | 313 → **204** | 95 → **21** | 21 → **10** | 11 → **0** |
| Live, files settling (15 s) | 5 → 6 | 2 | 21 → 25 | 10 → **2** | 1 → 2 | 1 → **0** |
| Live, nothing new (60 s) | 20 | 1 | 25 | 5 → **1** | 0 | 0 |
| **Live off: save** | 1 | 1 | 127 → **42** | 0 → 1 | 1 → **0** | 0 |
| Load during a stalled write (11 TXY) | 4 → 2 | 2 | 59 → **46** | 1 → 0 | 11 | 0 |
| **Mount table reported changed (30 s)** | 803 → **2** | 0 | 828 → **2** | 414 → **1** | 0 | 0 |
| **Cached folder with one new shot (41 TXY)** | 4 → 2 | 3 → **1** | 170 → **86** | 0 | 1 | 0 |
| **RAM-only folder reselected, unchanged (120 TXY)** | 4 → 3 | 4 → **2** | 245 → **9** | 0 | 0 | 0 |
| Startup, fresh store | 8 → 9 | 2 | 5 → 7 | 1 → 2 | 0 | 0 |
| Toolbar Refresh | 11 | 10 | 22 | 1 | 0 | 0 |

- **Unchanged by design:** a first load of a RAM-only folder (485 stats on macOS: the fingerprint from
  the listing is still one stat per file there, free only on Windows), Retry/Refresh's full check, the
  listing before an uncached folder's load (it gives the tree's names and saved status first), the
  stuck-read retries, the failing listing.
- **Startup +1 helper, +2 stats, +1 marker:** the marker check now follows the volume check, so on a
  fresh store it also checks the root the first listing just found; and the first listing's report
  during the startup volume check gets its one follow-up volume check (local lane, no share).
- **Toolbar Refresh:** unchanged in this rerun. (The Part 2 rerun had +2 helpers there: a real mount
  change, an iOS Simulator runtime image mounted during the run, which the Refresh listing reported and
  which got exactly one verification.)
- **Files still being written (settle age only):** Live's writer pausing 4 s mid-file: its files were
  only statted while being written, never opened. The load during an 8 s stall read shot 2001 half-written
  (selected 6.5 s into the stall, so past the 5 s settle age): accepted by design (next section).
- **Live, writer adding a file every 4 s:** each new file changes the folder's mtime, so most checks still
  list (20 → 17); the savings there are the marker opens (5 → 1 per listing) and the tail reads (gone).
  The pending-file checks pay off when files are slow to finish or rare.

Projected for a real run (N = 1,000 TXY files, a new shot every ~10 s, macOS):
- Live autosave every 10 shots: ~3,000 stats and 10 reads from the share → 1 listing, 1,000 listing
  stats (none on Windows), 1 marker read, no read.
- A load of N files: 5N → 4N stats on macOS, 3N on Windows (when the cache is saved).
- Re-selecting unchanged data: 6 operations whether it's disk cached or RAM only (was 2N + 4 listings for
  RAM only).
- After a mount change: one verification per new table reported (was unbounded until a listing).

### Files still being written: rule now, research, limits

What HeLab does now (trace, `trace-session1-after.md` "Files touched while the fake writer was writing them"):
- **Stats:** still made of files being written (Live's new and pending files, a load's fingerprint, a
  details scan). They are how HeLab learns a file is young; on servers that follow Windows' oplock rules
  they shouldn't change the writer's caching (1 below).
- **Opens and reads:** only of files settled by age (unmodified for 5 s); Live also waits until a new
  file shows the same size and mtime a check later (`seen`: metadata only, not a format assumption).
  Settle age only, by Tony's decision; the converter's temp-name rename remains the real fix. Neither
  loads nor Live look at a file's content to judge whether it's finished (the whole-row checks of
  2b55d59 and 8079252, and Live L2's `_txy_complete`, were removed in round 3): a TXY write never takes
  more than 5 s, and a writer paused at a row's end would pass such a check anyway. So a writer stalled
  longer than the settle age is read as it is, by design: the partial row is dropped as unreadable
  (problematic), the rest is shown and cached, and the finished file's new size makes the next check
  read it again (in Live, a held shot that later changes stops Live with "changed": TXY files are
  written once). Live opens a ready file once instead of twice (tail, then file).

Research (sources at the end of this section). These are statements of the protocols and the client
code; no SMB packet capture or native Windows run was made, and servers (Windows, Samba, NAS firmware)
and client versions differ.
1. **A stat shouldn't break the writer's oplock or lease, where the server follows Windows' rules.**
   Windows' file system rule is that an open asking only for FILE_READ_ATTRIBUTES, FILE_WRITE_ATTRIBUTES
   or SYNCHRONIZE "does not break" an oplock [1]. Apple's SMB client source stats with a compound
   CREATE/QUERY_INFO/CLOSE asking for SMB2_FILE_READ_ATTRIBUTES | SMB2_SYNCHRONIZE, share access ALL [2]
   (its `main` branch, not pinned to a macOS release). This covers caching state only: a stat still
   costs a round trip, and a server that breaks oplocks on any open would behave otherwise.
2. **A data open from another computer can break the writer's write caching.** Under those rules, an
   open for data from another client breaks a Read-Write-Handle oplock to Read-Handle (to Read-Write if
   the share modes would conflict), and "an acknowledgment must be received before the operation
   continues" [1]; a client whose lease loses write caching "MUST flush any cached data associated with
   this file" [3]. So if the converter's client holds such a lease, HeLab's read makes it flush and stop
   caching writes to that file: expected to slow it, not to fail it, provided the share modes allow both
   opens (5). Whether the converter holds a lease at all depends on its client, the server and the share.
3. **The server's size and mtime can lag the writer.** A client holding write caching can keep writes it
   hasn't sent; they reach the server when it flushes (on close, a lease break [3], or its own schedule).
   So a file can look unchanged on the server for longer than the settle age while its writer is still
   writing into its cache, and a reader's open can force the flush. This is why age alone can't prove a
   file is finished.
4. **Client caches can make stats stale.** Apple's client caches a file's attributes for (now − mtime)/10,
   between 2 and 30 s [4]: a young file's attributes are fetched again after 2 s. Windows' default
   lifetimes are 10 s for file information, 10 s for directory listings (without directory leases) and
   5 s for "not found" (FileInfoCacheLifetime, DirectoryCacheLifetime, FileNotFoundCacheLifetime), with
   64 files' information cached by default (FileInfoCacheEntriesMax) [5]. These are upper bounds on how
   old a cached answer can be, not a statement that every lookup is that stale.
5. **Sharing modes.** Apple's client source opens files for reading with share access ALL [2], which
   doesn't deny the writer's access. Python's `open()` on Windows goes through the C runtime's `_wopen`,
   which shares read and write but not delete [6]; the exact mask (`_SH_DENYNO` → FILE_SHARE_READ |
   FILE_SHARE_WRITE) is from the UCRT source as carried in ReactOS, secondary evidence [7]. So while a
   Windows HeLab reads a file, its writer can keep writing but likely can't delete or rename that file.
   If the converter itself opened files denying read sharing, HeLab's open would fail instead (and be
   retried by the next check).

Decision taken (implemented): stats of young files allowed; opens and reads only of files settled by age
(settle age only, by Tony's decision; the converter's temp-name rename remains the real fix); Live also
needs a new file unchanged since the previous check (metadata); one data open per new file in Live.

Proposed, not done (Tony's call):
- **Windows clients and Live's "unchanged since the last check" rule:** two stats 3 s apart can both come
  from the 10 s file-information cache [5], so on Windows the rule can be weaker than on macOS. A fix would
  be to require the two looks to be at least 10 s apart on Windows.
- **The real fix stays the converter's temporary-name rename** (on the roadmap): write `…tmp`, close, then
  rename to `d_txy_forc<N>.txt`. Age can't prove the writer finished: a writer stalled longer than the
  settle age, or caching writes as in 3, still looks finished. And a converter that replaced a
  finished file by renaming over it could fail while a Windows HeLab reads it (5); writing new names
  doesn't.

Sources:
[1] Microsoft, "Checking the Oplock State of an IRP_MJ_CREATE Operation", https://learn.microsoft.com/en-us/windows-hardware/drivers/ifs/irp-mj-create2
[2] Apple SMBClient source, `kernel/smbfs/smbfs_smb_2.c` (`smb2fs_smb_cmpd_query`, `smb2fs_smb_cmpd_create_read`), `main` branch, https://github.com/apple-oss-distributions/SMBClient
[3] Microsoft, [MS-SMB2] "Receiving a Lease Break Notification" (client flushes cached data when write caching is removed), https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-smb2/4f35576a-6f3b-40f0-a832-1c30b0afccb3
[4] Apple SMBClient source, `kernel/smbfs/smbfs_node.h` (`SMB_CACHE_TIME`, `SMB_MINATTRTIMO` 2, `SMB_MAXATTRTIMO` 30), `main` branch, https://github.com/apple-oss-distributions/SMBClient
[5] Microsoft, "Performance tuning for file servers" (client registry defaults), https://learn.microsoft.com/en-us/windows-server/administration/performance-tuning/role/file-server
[6] Microsoft, "_sopen, _wsopen" (`_SH_DENYNO` "Permits read and write access"), https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/sopen-wsopen
[7] UCRT `lowio/open.cpp` as carried in ReactOS (`_wopen` → `_SH_DENYNO`; `_SH_DENYNO` → FILE_SHARE_READ | FILE_SHARE_WRITE), https://doxygen.reactos.org/d2/dce/open_8cpp_source.html

### Ownership

- One change outside my owned paths, approved by Maestro: `helab/utils/data_roots.py` `read_marker`
  gained an optional keyword-only `trace` callback (default None: unchanged without it), so the trace can
  record its open, fstat and read. No other change there; `test_read_marker_behaves_the_same_with_a_trace_callback`
  checks identical results and errors with and without it.
- Otherwise only owned paths: `helab/io_helper.py`, `helab/utils/io_service.py`, `helab/utils/folder_cache.py`,
  `helab/views/FolderExplorer.py`, `helab/models/SnapshotFileSystemModel.py`, and their tests
  (`tests/test_io_trace.py`, plus small updates in `test_root_discovery.py`, `test_cache_first.py`,
  `test_folder_cache.py`, `test_live_check.py`, `test_gui_responsiveness.py`).
- Live L3 runs in parallel. `live_check(memory=[])` still raises on this branch by design: L3's
  672a96b changes that guard to `memory is None` and merges on top. A save of an empty Live dataset is
  skipped (nothing to save); a growing one saves (tested). Checked by cherry-picking 672a96b onto this
  branch's head (e04dfa5) on a scratch branch: it applied cleanly; `tests/test_live*.py` and
  `test_io_trace.py` passed (68), the full suite passed (1018, 2 skipped, 2 xfailed; one RERUN of
  `test_window_resize.py::test_label_keeps_painting_after_resize[single]`, a paint-timing test), mypy
  --strict and pyright clean. The scratch branch was deleted; nothing of L3 is on this branch.

### Checks (Part 2)

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: **1014 passed, 2 skipped,
  2 xfailed, no RERUN** (after round 3; before it, 1010 with no RERUN). One earlier Part 2 run had reruns:
  a strict-mypy failure in my own new test helper, fixed before that commit.
- `mypy helab/ --strict`, `mypy tests --strict`, both with `--platform win32`; `pyright helab tests`, also
  `--pythonplatform Windows`: clean (after round 3).
- `tests/test_io_trace.py`: 24 tests (the trace itself, and one or more per fix); the trace switch's
  window tests in `tests/test_helabMainWindow.py` (4).
- Scenario reruns after round 3: two sessions, no GUI-process call on the share (`compare-session{1,2}.md`,
  `trace-session{1,2}-after.md`; `compare_traces.py` now matches a renamed phase by its name before " (",
  marked †).
- After the review fixes (B, C, D, F), the dev/v0.0.6 merge and E: full suite **1181 passed, 2 skipped,
  2 xfailed, no RERUN** (one earlier run had 5 RERUNs of `test_typing.py::test_mypy_helab_tests_strict`, a
  real strict-mypy error in my new test, fixed before the commit); typing clean in both modes. Both
  scenario sessions rerun with recording folders (one file per helper, read whole by the summaries): no
  GUI-process call on the share, every phase's counts as in the round 3 tables except one Live check
  fewer in the 60 s writer phase (29 helpers, 16 listings, 195 stats, 20 marker opens; timing), so E
  adds no I/O. The committed tables are round 3's.

### Not done (outside the six; for Tony)

- Tests whose main window opens a default tab on `/Volumes/dld_output` (Part 1 finding 9): a conftest
  change (shared file).
- Details scans for visible rows only; icons kept across Refresh (Part 1 finding 6).
- The startup "database is locked" on a fresh store (notes).
- The Windows "seen twice" interval above.

### Proposed doc changes (for the coordinator)

- AGENTS.md, Testing: beside `HELAB_TEST_LOCAL_MOUNT`, `HELAB_TEST_VOLUME_ID` and `HELAB_TEST_READ_GATE`,
  add "`HELAB_TEST_IO_TRACE=<folder>` (`helab/io_helper.py` only: every helper appends each source-folder
  operation to its own `<folder>/<pid>.jsonl`, as Help › Record I/O trace does; `tests/test_io_trace.py`)".
- AGENTS.md, Responsive I/O: "**I/O trace:** Help › Record I/O trace (this session), off at every start
  and never saved, records every helper's source-folder operations as JSON lines in a new recording folder
  `<temp folder>/io-traces/io-trace-<date>-<time>/`, one `<pid>.jsonl` per helper (Windows' C runtime
  emulates O_APPEND, so helpers never share a file; `IOService.trace_dir`, sent with each request);
  refused when the temp folder is on a network or synced folder. A status-bar note while on; Help › Show
  I/O trace folder; earlier recordings are kept unless the user picks Delete old traces when asked." Summarise
  with this folder's `trace_summary.py`, compare with `compare_traces.py` (both read a recording's folder;
  to move to `dev/`).
- AGENTS.md, Responsive I/O: verification asked only by a listing's new mount table (one follow-up, never
  self-requeued, 5 s backstop); a load's fingerprint from its listing, the cache-save verify only after
  rereads; files still being written: settle age only, by Tony's decision (the converter's temp-name
  rename remains the real fix); the RAM quick check (`memory_check`); selecting a RAM-held leaf folder
  doesn't list it.
- AGENTS.md, Live: checks stat only pending files while the folder's mtime is the last listing's; the
  identity reads the known root's marker; saves are `save_held` from RAM (listing, every held file
  checked, no read), not an ordinary load.
- `roadmaps/_readme.md`: mark the SMB audit's Part 2 done; add the Windows "seen twice" interval and the
  remaining Part 1 items (tests' default tab, details per visible row, icons across Refresh).
- `.ai/MANUAL_TODO.md`: trace the real share with this branch (recipe in Part 1, section 7, now the menu
  switch; compare with a trace of `main` if wanted, which needs Part 1's `HELAB_IO_TRACE` build, with
  `compare_traces.py`).
- Possibly `constants.py`: refuse a network or synced temp folder at startup, as the cache folder is
  (round 3 notes).

---

## Part 1: study and trace (before the fixes)

Branch `agent/smb-io-audit` (base 486cf56). Part 1 only: the code's logic is unchanged; an opt-in trace was
added. **Part 2 (fixes) waits for Tony's go.**

### Summary

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

### 1. The trace

(Part 1's switch, as written here, was `HELAB_IO_TRACE`; since round 3 it is Help › Record I/O trace
(this session), with the file in the temp folder, and the test seam `HELAB_TEST_IO_TRACE`; see section 7.
Part 2 split `marker_read` into `marker_open`, `marker_fstat` and `marker_read`.)

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

### 2. Inventory: every code path that reaches a source folder

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

### 3. Scenario runs (counts from the trace)

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

### 4. Findings, ranked by SMB traffic

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

### 5. Files still being written

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

### 6. Proposed Part 2 order (for Tony's decision)

1. Stop the verification loop (finding 1), with a trace test: "a changed mount table makes at most one
   verification until a listing reports another".
2. Live saves without full re-stats, and skip the repeated verify pass (findings 2 and 4).
3. Cheaper Live listing checks: identity and samples (finding 3).
4. A quick check for RAM-only data (finding 5).
5. Fresh-file rule for loads (section 5), after the SMB research.
6. Fewer listings per selection; details and icons (findings 4 and 6); the tests' default folder (finding 9).

Each fix gets a trace test, e.g. "an idle tree makes 0 source operations per minute after the first
listing" (true today: worth pinning down first).

### 7. Recipe: trace the real share (Tony)

(Updated in round 3: the trace is a menu switch now.) macOS, from a checkout of this branch:

```bash
cd ~/GitHub/HeLab && git fetch && git switch agent/smb-io-audit   # or a worktree of it
source venv/bin/activate
python -m helab
```

In HeLab, **Help › Record I/O trace (this session)** (the status bar shows "● I/O trace"; the terminal
prints `I/O trace on: <path>`). Use HeLab as when you saw the traffic: leave a tree open, browse, load,
run Live during acquisition. Note the times of what you do. Then untick it (or quit HeLab): the terminal
prints `I/O trace off: <path>` (helpers already running finish their lines in that folder). **Help › Show I/O trace folder** opens the folder: by default
`~/Library/Caches/HeLab/temps/io-traces` (Windows `%LOCALAPPDATA%\HeLab\temps\io-traces`; Settings →
General shows the temp folder). Each recording is a new folder there (`io-trace-<date>-<time>`, one
`<pid>.jsonl` per helper); earlier ones stay unless you pick Delete old traces when asked. Summarise the
newest (the summary merges a folder's files in time order):

```bash
python .ai/sessions/2026-10-19-claude-smb-io-audit/trace_summary.py \
  "$(ls -td ~/Library/Caches/HeLab/temps/io-traces/io-trace-*/ | head -1)" \
  --under /Volumes/dld_output --minutes > ~/Desktop/helab-trace-summary.md
```

The summary gives per-request, per-reason counts and rates, the most repeated paths, a per-minute timeline,
and operations on files modified under 5 s before. Look for `roots_verify` lines arriving several a second
(finding 1). Without phase marks the whole trace is one phase; split it with your noted times if useful.
Expect ~0.6 kB of trace per operation.

Windows lab PC: `py -m helab`, then the same menu item. Each helper writes its own file, so the C
runtime's emulated append (a seek, then a write) can't make helpers overwrite each other's lines.

Optional, to see what other programs do to the share (Finder, Spotlight, previews), not only HeLab:
`sudo fs_usage -w -f filesys | grep dld_output` (Ctrl-C to stop). To count SMB requests on the wire:
`sudo tcpdump -i any -w ~/Desktop/smb.pcap port 445`, then Wireshark › Statistics › Service Response Time ›
SMB2 (not readable if the share encrypts SMB3 traffic).

Don't run `scenarios.py` against a real share: it builds and deletes its own test share.

### 8. Checks

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: 992 passed, 2 skipped, 2 xfailed,
  **no RERUN**.
- `mypy helab/ --strict`, `mypy tests --strict`, each also with `--platform win32`; `pyright helab tests`,
  also `--pythonplatform Windows`: all clean.
- `tests/test_io_trace.py`: 7 tests (section 1).
- Scenario runs: `scenarios.py OUT --session 1` then `--session 2` (11 minutes), summaries in this folder.

### 9. Proposed doc changes (for the coordinator)

(Superseded by Part 2's list above.)

- AGENTS.md, Testing: add the debug trace beside the test seams: "`HELAB_IO_TRACE=<file>` (`helab/io_helper.py`
  only): every helper appends each source-folder operation to `<file>` as one JSON line; off by default.
  Summarise with `.ai/sessions/2026-10-19-claude-smb-io-audit/trace_summary.py` (to move into `dev/` with
  Part 2)."
- `roadmaps/_readme.md`: an item "SMB I/O audit Part 2" with section 6's order, and finding 1 as a bug.
- `.ai/MANUAL_TODO.md`: "Trace HeLab on the real share (recipe in the audit's handoff, section 7)".

### 10. Files

- Code: `helab/io_helper.py` (trace and wrappers), `helab/utils/io_service.py` (`IORequest.trace`, `owners_of`),
  `helab/utils/folder_cache.py` (`_owners_of`), `tests/test_io_trace.py`.
- This folder: `brief.md`, `notes.md`, `handoff.md`, `scenarios.py`, `fake_writer.py`, `trace_summary.py`,
  `trace-session1.md`, `trace-session2.md` (paths shown as `<out>`). Raw traces were in the session
  scratchpad, not kept.
